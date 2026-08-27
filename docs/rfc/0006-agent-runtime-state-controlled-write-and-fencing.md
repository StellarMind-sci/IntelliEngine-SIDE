# RFC-006：AgentRuntimeState 受控写入与执行栅栏

- 状态：草案
- 负责人：StellarMind-sci
- 创建日期：2026-08-28
- 关联 Issues：[GitHub Issue #56](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/56)

## 问题

SIDE 已经完成长期 `AgentProfile` 与局部 `AgentRuntimeState` 的只读契约、双语言运行时与转换预演。用户可以长期持有并在需要时召唤一个或 N 个自定义 Agent；同一 Agent 可在不同工程或会话中拥有独立生命周期状态。现有权威局部唯一键固定为：

```text
(authority_scope_ref, runtime_context_ref, AgentProfile.id)
```

但当前实现不会写入状态、创建真实执行、授予工具权限或操作资源。若直接把“召唤/关闭”实现成更新一条状态记录，会产生重复请求、并发覆盖、崩溃后未知提交、状态和审计部分成功、关闭后旧执行继续提交，以及把人格、角色、aggregate 或 `active` 误当权限等风险。

本 RFC 定义真实状态变更前的受控写入边界：耐久 CAS、幂等结果、不可变审计、控制策略与变更批准证据、RuntimeKernel epoch fencing、恢复和默认关闭的发布方式。它不改变 RFC-005 与 ADR-0009 已接受的局部状态边界。

## 目标与非目标

### 目标

1. 为 `AgentRuntimeState` 定义从状态意图到耐久提交和提交后执行的权威链路。
2. 定义 canonical request、稳定 `request_id`、指纹、幂等重放与 `indeterminate` 恢复。
3. 要求针对局部唯一键的 durable CAS，并让 State、不可变 TransitionRecord、幂等最终结果和 outbox 原子可见。
4. 明确 `ControlPolicy`、`ChangeSet`、`RuntimeKernel` 的证据在写入链中的位置和所有权。
5. 以 `state_id + activation_epoch + lease/fence` 防止关闭、重启或重新召唤后的旧执行提交副作用。
6. 规定 close 先提交 `dormant`，清理失败不恢复 authority。
7. 给出后续公共契约、实现、集成与 IDE 体验的可执行依赖顺序。

### 非目标

- 不实现存储、数据库、网络、Policy、ChangeSet、lease、模型调用、工具调用、UI 或 feature flag。
- 不修改已发布的 `AgentRuntimeState` 1.0.0 或 `AgentProfile` 1.0.0，也不新增生命周期动作或状态。
- 不定义 `ControlPolicy`、`ChangeSet`、`RuntimeKernel` 的完整 Schema；它们各自仍由独立公共契约拥有。
- 不允许 aggregate、AgentProfile、角色、人格、能力、来源或 `active` 状态成为命令输入或权限凭据。
- 不建立跨模型、插件、外部工具和任意数据库的分布式事务。

## 提案

### 所有权与权威链

`packages/agent-runtime` 拥有局部 RuntimeState、转换命令概念、权威状态 ledger、TransitionRecord、幂等结果和 outbox 的语义；`packages/control-plane` 拥有 ControlPolicy 决策、ChangeSet 审批、影响预演与回滚计划；RuntimeKernel/执行平面拥有 lease、资源与副作用 fencing；`services/provenance` 拥有原件和派生来源记录；`apps/web-ide` 仅是后续命令调用方。

完整链路如下：

```text
TransitionIntent
  -> 严格 transport / canonical bytes / request fingerprint
  -> request_id 幂等查询
  -> authority-local State 读取和提交时 CAS
  -> 纯 plan_transition
  -> ControlPolicy 可验证决策证据
  -> ChangeSet 可验证批准与影响摘要
  -> RuntimeKernel lease/fence preparation（不执行）
  -> 原子提交 State + TransitionRecord + idempotency final result + outbox
  -> post-commit outbox
  -> RuntimeKernel admission check
  -> 受控执行
  -> RuntimeKernel final-commit check
```

任何阶段缺失、无法验证或语义不匹配均 fail closed。`TransitionIntent` 只是请求，不是权限凭证；TransitionRecord 只是不可变审计与恢复依据，不是第二份可修改状态；outbox 是提交后工作交付依据，不是当前权限。

### 请求规范化、幂等与结果

每个状态命令都需要稳定 `request_id`。在接触策略、状态存储或 RuntimeKernel 前，系统必须严格解析输入、拒绝未知/重复字段、非规范数值和不支持版本，生成 canonical bytes 并计算 request fingerprint。fingerprint 至少覆盖命令版本、局部唯一键、精确 Profile 引用、转换操作、CAS 前置条件、actor/授权上下文引用及影响语义的选项；不得依赖 JSON 字段顺序或瞬时网络元数据。

- 相同 `request_id` 和相同 fingerprint：重放首次最终结果，不重新规划、授权或执行。
- 相同 `request_id`、不同 fingerprint：`request_id_reused` conflict，不能覆盖旧记录。
- 首次请求：建立幂等处理中记录，再继续链路。
- 无法判断提交是否已发生：返回非最终 `indeterminate`；调用方只能以原 `request_id` 查询恢复，不得换 ID 重做。
- `committed`、`no_change`、`conflict`、`rejected` 均为稳定最终结果。相同请求在后来策略或状态变化后不得取得新含义。

`no_change` 是最终幂等结果：不得增加 `state_revision` 或 `activation_epoch`，不得创建新 lease、启动执行或产生会授予副作用的 outbox。

### durable CAS 与原子事务

唯一可写目标是 `(authority_scope_ref, runtime_context_ref, AgentProfile.id)` 指向的局部权威状态。create 必须以 absent 作为原子前置条件；其他操作必须携带并在最终提交时重新验证 `state_id`、`state_revision`、准确 ProfileRef 与两个不透明上下文引用。事务外读取不能替代提交时 CAS。竞争同一前置版本时，最多一个请求可提交，其他请求稳定 conflict；不同局部唯一键互不覆盖。

推荐的 authority-local 事务是：

```text
BEGIN
  recheck request_id/fingerprint
  recheck State 与 CAS
  revalidate Policy、ChangeSet 与 fence preparation 句柄
  write new State（或保留 no_change State）
  append immutable TransitionRecord
  finalize idempotency result
  append post-commit outbox event（仅需后续工作时）
COMMIT
```

State、TransitionRecord、幂等最终结果和 outbox 必须对权威读取方原子可见。若具体存储不能提供同一物理事务，适配器必须提供经同等测试的 `pending -> commit marker` 逻辑屏障：未越过 marker 不暴露新 State、outbox worker 不消费、幂等查询可区分 pending/final/indeterminate；崩溃恢复要么完成同一提交，要么保持旧权威状态，绝不产生两个权威状态或可执行的未提交事件。禁止“先写状态，尽力补审计”或“先启动执行，再记录状态”。

### Policy、ChangeSet 与 RuntimeKernel

纯规划成功不等于获权。每次状态变更必须消费由独立所有者签发、可验证且与 canonical intent 绑定的：

- ControlPolicy decision evidence：actor、scope、context、目标对象、允许操作、时效/撤销及约束；
- approved ChangeSet evidence：before/after 计划、影响范围、回滚/补偿、审批状态和时效；
- RuntimeKernel fencing preparation：局部状态、预期 `state_id`、`activation_epoch`、执行域、单调 fence generation、租约时效，并绑定 Policy/ChangeSet/fingerprint。

上述对象均为不透明句柄或其最小摘要；AgentRuntimeState 不复制、不定义或旁路其完整 schema。无效、过期、撤销、跨 scope/context、计划不匹配或无法验证的证据必须拒绝。

lease preparation 不等于最终执行权。执行 worker 在启动副作用前必须重新执行 admission check：当前状态为 `active`，`state_id`、`activation_epoch`、lease、fence、Policy、ChangeSet、authority scope 与 runtime context 全部匹配。任何结果写回、工具操作、工程修改或外部副作用提交之前，还必须在同一授权/提交边界重新执行 final-commit check。仅在 admission 检查一次不够。

### close、archive 与故障恢复

close 的顺序固定为：规划 active→dormant；取得证据与 fence preparation；原子提交 dormant、Record、最终结果和 cleanup outbox；使旧 epoch authority 立即失效；再撤销 lease、停止进程和清理资源。清理失败、超时或重连不得恢复 active、不得重新授权旧 lease；outbox 可重试，存活的旧进程仍必须被 fence 阻止提交。

archived 继续遵守既有路径，不能用旧 request、旧 lease 或旧 ChangeSet 直接恢复。恢复归档 Agent 是新的受控请求。崩溃、连接中断和网络分区由 request_id、ledger 和 commit barrier 恢复；无法判定时保持 `indeterminate`，绝不猜测成功或失败。

### 默认关闭与可观测性

受控写入通过默认关闭 capability flag 发布。关闭时禁止任何增加运行权限的写入、召唤和 RuntimeKernel 启动，但只读验证/投影继续可用，且已提交 close/撤销的安全清理应有独立通道继续完成。开关状态、request_id、fingerprint 版本、State/Record 引用、Policy/ChangeSet/fence 句柄摘要和恢复状态应进入最小审计与诊断；不得记录私有记忆、完整提示词、凭据、完整策略或无权上下文。

## 公共接口

本 RFC 只定义未来接口边界，不新增 Schema。后续 `TransitionIntent` 至少表达：契约版本、request_id、两个 opaque refs、AgentProfile ID/精确期望引用、操作、CAS 前置条件、actor/provenance/correlation refs 与受限 semantic options。它不得接受 aggregate、客户端伪造的最终 State/revision/epoch/批准或角色化权限声明。

后续内部 `AdmittedTransition` 仅携带 canonical intent/fingerprint、Policy decision handle、approved ChangeSet handle、RuntimeKernel fence preparation handle、纯计划引用和证据时效。后续 `TransitionResult` 至少输出 request_id、fingerprint、`committed|no_change|conflict|rejected|indeterminate`、State/Record/recovery refs 与稳定诊断。按 request_id 查询结果的只读接口必须实施同等或更严格的 scope/context 授权，不能泄露其他工程或会话。

已发布 1.0.0 读取接口继续兼容。未来命令契约须显式版本、严格 schema、锁定 canonical/fingerprint 算法、稳定诊断，并让 Python/TypeScript 对同 fixtures 字节、指纹、结果和诊断一致。

## 安全、溯源与控制策略

- 读取 State、拥有 Profile、被标为教师/分身/科学导师、拥有能力证据或某处 active，均不产生写入、模型、文件、网络、设备或项目权限。
- aggregate 只从控制平面已授权局部投影派生；不得用于 CAS、命令目标选择、跨上下文授权或写回。
- 所有证据句柄必须绑定 actor、局部唯一键、计划、fingerprint、有效期和权限范围，防止 confused deputy 与跨工程复用。
- 每个最终结果应以最小信息连接 request_id→fingerprint→actor/provenance→旧 State→plan→Policy→ChangeSet→fence→新 State→Record→outbox/recovery；不得复制用户私有记忆、受保护原件、提示词或凭据。
- 任何不确定的策略、批准、fence 或提交均不得执行。关闭已提交后，宁可等待可恢复清理，也不可保留旧执行提交权。
- request_id/Record 查询和日志访问应受授权控制；长留存需区分审计记录、完整结果和防复用墓碑，并允许按合规策略最小化非权威附属信息。

## 替代方案

### A. 事务型 authority ledger（推荐）

将 State、immutable TransitionRecord、幂等最终结果和 outbox 放入单一 authority-local 事务或等价屏障中。它给出单一事实来源、可验证 CAS、可恢复 request_id 与明确审计，不要求 Policy、ChangeSet、RuntimeKernel 或外部工具参与分布式事务。代价是要实现 ledger、保留策略和恢复器。

### B. 直接覆盖原始状态后补日志（拒绝）

实现短，但无法证明并发、超时、审计/outbox 部分成功或旧执行 fencing；会使重试可能重复召唤/关闭，违反显式授权与可溯源要求。

### C. 所有模块参加任意分布式事务（延期）

理论覆盖范围更大，但模型、工具、插件和外部系统通常不支持事务；锁、故障域和部署成本过大，且无法撤销已发生外部副作用。本阶段改用 authority transaction + outbox + fencing + 补偿。

### D. 只追加事件、读取时全量重放（延期）

有完整历史优势，但仍需要 CAS、幂等和 fencing，并会扩大 M1 范围。当前保持权威 State 投影与 immutable TransitionRecord，未来可演进。

### E. 以 aggregate 集中写入（拒绝）

破坏既有局部隔离、泄露无权上下文且无法得到正确 CAS；与 RFC-005/ADR-0009 冲突。

## 迁移与发布

1. 先审查并接受 RFC，记录 ADR；不写入、不改现有 1.0.0。
2. RFC/ADR 后并行稳定 `ControlPolicy`、`ChangeSet`、`RuntimeKernel fencing` 三个独立公共契约和契约测试。
3. 三项 stable 后再定义 AgentRuntimeState command：Intent、canonical serialization/fingerprint、CAS、Result、Record、幂等、outbox refs 和诊断。
4. 再实现单存储 authority ledger、durable CAS、journal、outbox、查询/恢复、默认关闭 flag；其后才接入 Policy/ChangeSet/RuntimeKernel 集成与故障恢复验证。
5. 仅 staging 内部预览通过后，IDE 才提供单 Agent/多 Agent 的召唤、关闭、封存和状态体验；UI 必须显示 conflict/rejected/indeterminate/cleanup pending，而不能伪造成功。

```text
RFC-006 + ADR
  ├─ ControlPolicy contract + tests ─┐
  ├─ ChangeSet contract + tests ────┼─> State command contract + tests
  └─ RuntimeKernel fencing + tests ─┘            |
                                                  v
                           authority ledger / CAS / journal / outbox
                                                  |
                                                  v
                     cross-module integration + recovery / security tests
                                                  |
                                                  v
                     default-off internal preview -> IDE summon/control UI
```

前三项契约可并行，但不得共同修改一个未稳定公共接口；状态命令必须等待三者完成。启用后若需回滚，先停止新增运行权限，保留只读与撤销/清理通道；不得删除已提交 State 或 journal 后重放旧请求。状态修复通过新的获权补偿命令完成，不能覆盖历史。

## 测试计划

后续各 Issue 必须覆盖：

1. 严格输入、引用闭包、版本、canonical bytes/fingerprint 和 Python/TypeScript 差分；
2. 相同 request_id 同指纹的只执行一次、不同指纹 conflict、最终结果稳定重放、timeout 后原 ID 恢复；
3. 同一局部前置版本竞争时唯一 CAS 成功，不同 scope/context 独立并发，aggregate 不可作 CAS；
4. 在 journal 占位、State、Record、result、outbox、commit response、worker 与清理各故障点注入崩溃，恢复后没有两个权威状态、孤立可见 State、无结果 committed 或可执行未提交 outbox；
5. 缺失/过期/撤销/错 actor 或错 scope 的 Policy、ChangeSet、fence 一律拒绝；
6. admission 后 close、重新 summon、晚到模型/工具回调或重复 outbox 时，旧 state/epoch/fence 不能提交；
7. close 先 durable dormant，清理失败不恢复 active，安全清理可重试；
8. feature flag 默认拒绝增加 authority，且没有调试旁路；
9. 读取权限、Profile、persona、role、ability 或 aggregate 均不能升级为命令权限；
10. 端到端演练：Profile→局部 dormant→summon intent→Policy→ChangeSet→fence→atomic active→受控输出→close→atomic dormant→旧输出阻断→cleanup recovery→request result 查询。

## 已接受事实、推荐、仍待产品负责人决定的事项

### 已接受事实

- 用户可长期保有并召唤一个或 N 个任意设定的 Agent，不受固定角色限制。
- Profile 与 RuntimeState 分离；局部唯一键、三态、显式 rebind、epoch 和授权过滤 aggregate 已由 RFC-005/ADR-0009 固定。
- aggregate 只读且无写入、lease 或授权含义。
- AI 修改需要溯源、显式权限和回滚；真实副作用须经控制平面和隔离执行边界。
- 当前运行时仅能读取、验证、预演和汇总。

### 推荐

1. 采用方案 A 的事务型 authority ledger；
2. State、Record、幂等最终结果和 outbox 同一逻辑提交边界；
3. 保存 conflict/rejected/no_change 等稳定最终结果，以 request_id 重放；
4. 使用 durable CAS 与 admission/final-commit 双栅栏；
5. close 先持久化 dormant，安全清理独立于“新增权限”开关；
6. 允许经过同等故障测试的 commit-marker barrier 适配器；
7. 首个真实预览仅限单项目、单 RuntimeKernel、dormant↔active、默认关闭且无外部工具/高风险网络能力。

### 仍待产品负责人决定的事项

1. 是否接受方案 A 作为权威存储根边界（推荐接受）。
2. 是否把 conflict、Policy/ChangeSet/fence 拒绝和 no_change 持久化为不可重解释的最终 request 结果（推荐是）。
3. TransitionRecord、完整幂等结果和防复用墓碑的保留/匿名化期限（推荐审计记录按项目溯源策略，完整结果保留恢复期，后保留最小墓碑）。
4. 常规写入关闭后，已提交 close 的 lease 撤销/资源清理能否走独立安全通道（推荐能）。
5. 不具同物理事务的存储是否接受严格等价 barrier 适配器（推荐接受，但必须通过同等故障测试）。
6. 首个内部预览是否限于单本地项目、单 RuntimeKernel、dormant/active 和默认关闭（推荐是）。

## 决定

草案阶段保持为空。接受后创建 ADR，并按上述依赖图创建独立契约、模块、集成与 UI Issue；在这些独立 Issue 通过前，不实现真实状态转换。