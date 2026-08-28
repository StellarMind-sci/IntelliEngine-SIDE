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

1. 为 `AgentRuntimeState` 定义从独立受控写命令到耐久提交和提交后执行的权威链路。
2. 定义 canonical request、稳定 `request_id`、指纹、幂等重放与 `indeterminate` 恢复。
3. 要求针对局部唯一键的 durable CAS，并让 State、新写入 family 的不可变权威记录、幂等最终结果和 outbox 原子可见。
4. 明确 `ControlPolicy`、`ChangeSet`、`ProvenanceRecord`、`RuntimeKernel` 的证据在写入链中的位置和所有权。
5. 以 `state_id + activation_epoch + lease/fence` 防止关闭、重启或重新召唤后的旧执行提交副作用。
6. 规定 close 先提交 `dormant`，清理失败不恢复 authority。
7. 给出后续公共契约、实现、集成与 IDE 体验的可执行依赖顺序。

### 非目标

- 不实现存储、数据库、网络、Policy、ChangeSet、lease、模型调用、工具调用、UI 或 feature flag。
- 不修改已发布的 `AgentRuntimeState` 1.0.0 或 `AgentProfile` 1.0.0，也不新增生命周期动作或状态。
- 不把已发布 `agent-runtime-state` 1.0.0 的只读 `TransitionIntent`/`TransitionRecord` 提升为写入口，也不把其中的 `applied` 重解释为真实提交。
- 不定义 `ControlPolicy`、`ChangeSet`、`ProvenanceRecord`、`RuntimeKernel` 的完整 Schema；它们各自仍由独立公共契约拥有。
- 不允许 aggregate、AgentProfile、角色、人格、能力、来源内容或 `active` 状态成为权限凭据；命令中的 opaque provenance ref 只建立溯源关联，不授权。
- 不建立跨模型、插件、外部工具和任意数据库的分布式事务。

## 提案

### 所有权与权威链

`packages/agent-runtime` 拥有局部 RuntimeState、新写命令/权威记录 contract family、权威状态 ledger、幂等结果和 outbox 的语义；`packages/control-plane` 拥有 ControlPolicy 决策、ChangeSet 审批、影响预演与回滚计划；RuntimeKernel/执行平面拥有 lease、资源与副作用 fencing；`services/provenance` 拥有原件和派生来源记录；`apps/web-ide` 仅是后续命令调用方。

完整链路如下。这里的 `ProtectedScopeAdmission` 是**调用身份与局部 scope/context 非泄露准入门**：它只证明 actor 可以对该受保护局部键发起这类命令或结果查询，不读取局部 State、不查询 `request_id`、不替代完整 ControlPolicy，也不表示最终状态变化已获批。准入失败统一返回不披露原因的拒绝，不能让调用方区分 scope/context、`request_id` 或 State 是否存在。

```text
AgentRuntimeTransitionCommand envelope
  -> 严格 transport / schema（不访问 authority-local 数据）
  -> ProtectedScopeAdmission(actor, authority_scope_ref, runtime_context_ref, agent_profile_id, operation class)
  -> canonical bytes / request fingerprint
  -> request_id 幂等查询
  -> authority-local State 读取和提交时 CAS
  -> 纯 plan_transition
  -> ProvenanceRecord ref validation
  -> ControlPolicy 可验证决策证据
  -> ChangeSet 可验证批准与影响摘要
  -> RuntimeKernel lease/fence preparation（不执行）
  -> 原子提交 State + AgentRuntimeAuthorityTransitionRecord + idempotency final result + outbox
  -> post-commit outbox
  -> RuntimeKernel admission check
  -> 受控执行
  -> RuntimeKernel final-commit check
```

任何阶段缺失、无法验证或语义不匹配均 fail closed。新的 `AgentRuntimeTransitionCommand` 只是请求，不是权限凭证；新的 `AgentRuntimeAuthorityTransitionRecord` 只是不可变审计与恢复依据，不是第二份可修改状态；outbox 是提交后工作交付依据，不是当前权限。

准入门只能依赖已经认证的 actor 与 authority/control-plane 拥有的 scope/context 成员关系、按稳定 AgentProfile 逻辑 ID 索引的受保护对象能力或等价授权索引，不能把调用方给出的 opaque ref 当成授权，也不能为了决定是否准入而读取 State、Profile revision 绑定或幂等日志。对命令、按 `request_id` 查询结果、读取局部 State 的入口，都要先通过同一或更严格的非泄露准入门。未通过时可写入与局部状态无关的最小安全事件（例如 actor、入口类别、时间和通用拒绝码），但不得请求或记录 `request_id` 是否存在、State 是否存在、当前 revision/status、Profile 绑定或可关联出受保护局部键的详细信息。

### 请求规范化、幂等与结果

每个状态命令都需要稳定 `request_id`。系统先严格解析有限的命令 envelope，拒绝未知/重复字段、非规范数值和不支持版本；只有通过 `ProtectedScopeAdmission` 后，才允许生成 canonical bytes、计算 request fingerprint、查询或创建幂等记录以及读取局部 State。准入前不返回 `request_id_reused`、`conflict`、`no_change`、State-not-found 或任何可区分局部存在性的诊断。

fingerprint 至少覆盖命令 contract family/version、局部唯一键、精确期望 Profile 引用、转换操作、CAS 前置条件、actor/授权上下文引用、provenance ref 及影响语义的选项；不得依赖 JSON 字段顺序或瞬时网络元数据。对于 `rebind_profile`，`target_profile_ref` 的精确 `(id, revision)` 是 fingerprint、纯计划和最终 CAS evidence 的必填部分；其他操作不得携带它。提交时必须重新证明当前 State 为 `dormant`、当前精确 ProfileRef 等于 expected ProfileRef、目标 Profile 可读且与当前 Profile 的逻辑 `id` 完全相同，并确认 target ref 与已批准计划/fingerprint 完全一致。跨 Profile ID、active 或 archived rebind 只能拒绝，不能通过遗漏 target、重算计划或把新 revision 当作“latest”绕过。

- 相同 `request_id` 和相同 fingerprint：重放首次最终结果，不重新规划、授权或执行。
- 相同 `request_id`、不同 fingerprint：`request_id_reused` conflict，不能覆盖旧记录。
- 首次请求：建立幂等处理中记录，再继续链路。
- 无法判断提交是否已发生：返回非最终 `indeterminate`；调用方只能以原 `request_id` 查询恢复，不得换 ID 重做。
- `committed`、`no_change`、`conflict`、`rejected` 均为稳定最终结果。相同请求在后来策略或状态变化后不得取得新含义。

`no_change` 是最终幂等结果：不得增加 `state_revision` 或 `activation_epoch`，不得创建新 lease、启动执行或产生会授予副作用的 outbox。

### 结果分支与持久化矩阵

下表规定一次命令在各分支能产生哪些事实。“journal”指新的写命令 family 的 authority-local 幂等记录；“Record”指新的 `AgentRuntimeAuthorityTransitionRecord`，不是已发布只读 `AgentRuntimeTransitionRecord` 1.0.0。只有通过非泄露准入后才能接触二者或局部 State。

| 结果分支 | journal / 稳定重放 | State 写入 | immutable Record | Policy | ChangeSet | fence preparation | outbox |
|---|---|---|---|---|---|---|---|
| transport-invalid | 不创建；不稳定重放 | 否 | 否 | 否 | 否 | 否 | 否 |
| pre-authorization-denied | 不创建；统一非披露拒绝，可在授权变化后重新评估 | 否；也不读取 | 否；只允许与局部状态无关的最小安全事件 | 否 | 否 | 否 | 否 |
| idempotency pending（同 ID/同 fingerprint） | 复用既有 pending；只返回 pending/indeterminate recovery ref，不创建第二条 | 否 | 否 | 否 | 否 | 否 | 否 |
| request ID 复用不同 fingerprint | 不改写既有 journal；对该已获准调用稳定返回 `request_id_reused` conflict | 否；不读取无关 State | 否；既有最终 Record 保持不变 | 否 | 否 | 否 | 否 |
| CAS conflict | 创建/终结为稳定 conflict 并重放 | 否 | 是，记录已获准目标与最小冲突事实，不复制无关 State | 否 | 否 | 否 | 否 |
| pure rejected | 创建/终结为稳定 rejected 并重放 | 否 | 是 | 否 | 否 | 否 | 否 |
| no_change | 创建/终结为稳定 no_change 并重放 | 否；revision/epoch 不变 | 是 | 否 | 否 | 否；不创建 lease | 否 |
| Provenance validation denied | 创建/终结为稳定 rejected 并重放 | 否 | 是，仅记录最小拒绝事实与可安全披露的 provenance 验证摘要 | 否；不得调用或创建 | 否；不得调用或创建 | 否；不得准备 fence | 否 |
| proposed change：Policy denied | 创建/终结为稳定 rejected 并重放 | 否 | 是，引用决策摘要 | 是 | 否 | 否 | 否 |
| ChangeSet denied | 创建/终结为稳定 rejected 并重放 | 否 | 是，引用 Policy/ChangeSet 摘要 | 是 | 是 | 否 | 否 |
| fence preparation denied | 创建/终结为稳定 rejected 并重放 | 否 | 是，引用前三项证据摘要 | 是 | 是 | 是 | 否 |
| committed change | 原子终结为 stable committed 并重放 | 是，且仅一次 CAS | 是，与 State/result 原子可见 | 是 | 是 | 是 | 仅在契约声明 post-commit work 时原子追加 |
| indeterminate / post-commit cleanup | 不新建；只能以原 `request_id` 恢复既有 pending/final；indeterminate 不是可重解释最终结果 | 不得二次写；依据 commit marker 判定旧/新权威状态 | 不得补写孤立 Record；只读取同一原子提交中的 Record | 不重新解释；只验证恢复所需的既有证据 | 同左 | 同左；旧 epoch 始终受栅栏 | 只消费已提交 outbox；cleanup 可重试但不得恢复 authority |

若 barrier 未能证明提交与否，响应保持 `indeterminate`，不得换 request ID 或重新执行实际变化；恢复器只能完成同一已持久 pending/事务，或证明 marker 未越过后保留旧 State。`no_change` 绝不增加 revision、epoch、lease、Record 以外的副作用事实或 outbox；只有 pure plan 确认存在 actual change 时才验证 `ProvenanceRecord`。provenance 验证失败必须终结为可稳定重放的 `rejected` journal 与最小 `AgentRuntimeAuthorityTransitionRecord`，不得改变 State，不得调用或创建 Policy、ChangeSet、fence preparation 或 outbox；同一已获准请求只能重放这一结果。未经非泄露准入的路径仍不得借该分支获知局部 State 或 `request_id` 是否存在。provenance 验证成功后，才依次进入 Policy、ChangeSet、fence preparation 与原子提交链。

### durable CAS 与原子事务

唯一可写目标是 `(authority_scope_ref, runtime_context_ref, AgentProfile.id)` 指向的局部权威状态。create 必须以 absent 作为原子前置条件；其他操作必须携带并在最终提交时重新验证 `state_id`、`state_revision`、准确 ProfileRef 与两个不透明上下文引用。事务外读取不能替代提交时 CAS。竞争同一前置版本时，最多一个请求可提交，其他请求稳定 conflict；不同局部唯一键互不覆盖。

推荐的 authority-local 事务是：

```text
BEGIN
  recheck request_id/fingerprint
  recheck State 与 CAS
  revalidate ProvenanceRecord、Policy、ChangeSet 与 fence preparation 句柄
  write new State（仅 actual change）
  append immutable AgentRuntimeAuthorityTransitionRecord
  finalize idempotency result
  append post-commit outbox event（仅需后续工作时）
COMMIT
```

State、AgentRuntimeAuthorityTransitionRecord、幂等最终结果和 outbox 必须对权威读取方原子可见。若具体存储不能提供同一物理事务，适配器必须提供经同等测试的 `pending -> commit marker` 逻辑屏障：未越过 marker 不暴露新 State、outbox worker 不消费、幂等查询可区分 pending/final/indeterminate；崩溃恢复要么完成同一提交，要么保持旧权威状态，绝不产生两个权威状态或可执行的未提交事件。禁止“先写状态，尽力补审计”或“先启动执行，再记录状态”。

### Policy、ChangeSet 与 RuntimeKernel

纯规划成功不等于获权。每次状态变更必须消费由独立所有者签发、可验证且与 canonical command/fingerprint 绑定的：

- ControlPolicy decision evidence：actor、scope、context、目标对象、允许操作、时效/撤销及约束；
- approved ChangeSet evidence：before/after 计划、影响范围、回滚/补偿、审批状态和时效；
- RuntimeKernel fencing preparation：局部状态、预期 `state_id`、`activation_epoch`、执行域、单调 fence generation、租约时效，并绑定 Policy/ChangeSet/fingerprint。

上述对象均为不透明句柄或其最小摘要；AgentRuntimeState 不复制、不定义或旁路其完整 schema。无效、过期、撤销、跨 scope/context、计划不匹配或无法验证的证据必须拒绝。

lease preparation 不等于最终执行权。执行 worker 在启动副作用前必须重新执行 admission check：当前状态为 `active`，`state_id`、`activation_epoch`、lease、fence、Policy、ChangeSet、authority scope 与 runtime context 全部匹配。任何结果写回、工具操作、工程修改或外部副作用提交之前，还必须在同一授权/提交边界重新执行 final-commit check。仅在 admission 检查一次不够。

### close、archive 与故障恢复

close 的顺序固定为：规划 active→dormant；取得证据与 fence preparation；原子提交 dormant、AgentRuntimeAuthorityTransitionRecord、最终结果和 cleanup outbox；使旧 epoch authority 立即失效；再撤销 lease、停止进程和清理资源。清理失败、超时或重连不得恢复 active、不得重新授权旧 lease；outbox 可重试，存活的旧进程仍必须被 fence 阻止提交。

archived 继续遵守既有路径，不能用旧 request、旧 lease 或旧 ChangeSet 直接恢复。恢复归档 Agent 是新的受控请求。崩溃、连接中断和网络分区由 request_id、ledger 和 commit barrier 恢复；无法判定时保持 `indeterminate`，绝不猜测成功或失败。

### 默认关闭与可观测性

受控写入通过默认关闭 capability flag 发布。关闭时禁止任何增加运行权限的写入、召唤和 RuntimeKernel 启动，但只读验证/投影继续可用，且已提交 close/撤销的安全清理应有独立通道继续完成。开关状态、request_id、fingerprint 版本、State/AuthorityTransitionRecord 引用、Policy/ChangeSet/fence 句柄摘要和恢复状态应进入最小审计与诊断；不得记录私有记忆、完整提示词、凭据、完整策略或无权上下文。

## 公共接口

### 已发布只读 family 与不可跨越的隔离边界

已发布 `agent-runtime-state` 1.0.0 明确声明 `side_effects: forbidden`，其中已有只读 `TransitionIntent`、`TransitionPlan` 和 `AgentRuntimeTransitionRecord` schema。该 family 只用于 raw validation、纯 `plan_transition`、只读记录一致性校验和授权输入的 aggregate；其 `AgentRuntimeTransitionRecord.outcome` 固定为 `applied | no_change | conflict | rejected`。这里的 `applied` 只表示**只读记录所描述的计划结果通过既有契约校验**，永远不等于 authority ledger 已提交，不得重命名或适配成 `committed`。

真实写入必须新增并分别版本化的 contract family：

- `agent-runtime-transition-command` 1.0.0：拥有 `AgentRuntimeTransitionCommand`、canonical serialization/fingerprint、非泄露准入后的 request journal、`AgentRuntimeTransitionCommandResult` 和 recovery query；
- `agent-runtime-authority-transition-record` 1.0.0：拥有 `AgentRuntimeAuthorityTransitionRecord`，记录已进入 authority 链的稳定结果及最小证据引用。

family 名称是写入隔离的第一道边界：写 API 只接受新的 command family，即使旧 `agent-runtime-state` 未来发布 2.0.0，也不会因此自动获得副作用权限；同为 `1.0.0` 也不表示两个 family 可以互换。两个新 family 各自未知 major 必须拒绝，诊断使用独立命名空间，不能复用旧 `agent_runtime_state.*` 诊断来暗示 durable conflict、rejected 或提交结果。已发布 1.0.0 schema、fixtures、lock、结果枚举和诊断不得原地修改。

兼容适配仅允许单向进入无副作用路径：旧 `TransitionIntent` 可继续输入既有 pure planner；旧 `TransitionPlan`/`AgentRuntimeTransitionRecord` 可继续验证。若已获准的调用方随后希望真实执行，control plane 必须创建一个**新的** `AgentRuntimeTransitionCommand`，赋予新的写命令 `request_id`、actor、精确 scope/context、CAS、provenance 和证据链，重新通过本 RFC 的准入与完整授权；禁止把旧对象机械提升或从其字段推导权限。旧 `applied/no_change/conflict/rejected` 只能作为只读 plan/record 观察，不得导入 journal、稳定重放为新结果，或映射为 `committed`。

### 新写入接口的最小边界

`AgentRuntimeTransitionCommand` 至少表达：contract family/version、request_id、两个 opaque refs、AgentProfile ID/精确期望引用、操作、CAS 前置条件、actor ref、`provenance_record_ref`、correlation refs 与受限 semantic options。`rebind_profile` 还必须携带精确 `target_profile_ref`；其他操作禁止该字段。命令不得接受 aggregate、客户端伪造的最终 State/revision/epoch/批准或角色化权限声明。

`provenance_record_ref` 只是指向稳定 `ProvenanceRecord` 契约对象的 opaque 精确引用，命令 family 不复制来源正文，也不能把任意自由字符串当成有效溯源。命令契约发布前，`ProvenanceRecord` 的引用格式、版本和最小验证语义必须先稳定；写入链只通过 provenance resolver 验证该引用属于已获准的 actor/scope/context 与本次意图。已发布只读 `TransitionRecord.provenance_ref` 不能充当这一证明或免除新依赖。

后续内部 `AdmittedTransition` 仅携带 canonical command/fingerprint、Policy decision handle、approved ChangeSet handle、RuntimeKernel fence preparation handle、纯计划引用和证据时效。`AgentRuntimeTransitionCommandResult` 至少输出 request_id、fingerprint、`committed | no_change | conflict | rejected | indeterminate`、State/AuthorityTransitionRecord/recovery refs 与稳定诊断。按 request_id 查询结果的只读接口必须先执行同等或更严格的 `ProtectedScopeAdmission`，未经准入只能返回统一不披露拒绝。

新 family 须使用严格 schema、锁定 canonical/fingerprint 算法、稳定诊断，并让 Python/TypeScript 对相同 fixtures 的字节、指纹、结果和诊断一致；它们不得改变已发布只读 1.0.0 的兼容读取行为。

## 安全、溯源与控制策略

- 读取 State、拥有 Profile、被标为教师/分身/科学导师、拥有能力证据或某处 active，均不产生写入、模型、文件、网络、设备或项目权限。
- aggregate 只从控制平面已授权局部投影派生；不得用于 CAS、命令目标选择、跨上下文授权或写回。
- 所有证据句柄必须绑定 actor、局部唯一键、计划、fingerprint、有效期和权限范围，防止 confused deputy 与跨工程复用；`rebind_profile` 的绑定必须包括精确 target ProfileRef。
- 只有通过非泄露准入的请求，最终结果才可以用最小信息连接 request_id→fingerprint→actor/ProvenanceRecord ref→旧 State→plan→Policy→ChangeSet→fence→新 State→AuthorityTransitionRecord→outbox/recovery；不得复制用户私有记忆、受保护原件、提示词或凭据。
- 任何不确定的策略、批准、fence 或提交均不得执行。关闭已提交后，宁可等待可恢复清理，也不可保留旧执行提交权。
- request_id/AuthorityTransitionRecord 查询和日志访问必须先通过非泄露准入；长留存需区分审计记录、完整结果和防复用墓碑，并允许按合规策略最小化非权威附属信息。

## 替代方案

### A. 事务型 authority ledger（推荐）

将 State、immutable AgentRuntimeAuthorityTransitionRecord、幂等最终结果和 outbox 放入单一 authority-local 事务或等价屏障中。它给出单一事实来源、可验证 CAS、可恢复 request_id 与明确审计，不要求 Policy、ChangeSet、RuntimeKernel 或外部工具参与分布式事务。代价是要实现 ledger、保留策略和恢复器。

### B. 直接覆盖原始状态后补日志（拒绝）

实现短，但无法证明并发、超时、审计/outbox 部分成功或旧执行 fencing；会使重试可能重复召唤/关闭，违反显式授权与可溯源要求。

### C. 所有模块参加任意分布式事务（延期）

理论覆盖范围更大，但模型、工具、插件和外部系统通常不支持事务；锁、故障域和部署成本过大，且无法撤销已发生外部副作用。本阶段改用 authority transaction + outbox + fencing + 补偿。

### D. 只追加事件、读取时全量重放（延期）

有完整历史优势，但仍需要 CAS、幂等和 fencing，并会扩大 M1 范围。当前保持权威 State 投影与 immutable AgentRuntimeAuthorityTransitionRecord，未来可演进。

### E. 以 aggregate 集中写入（拒绝）

破坏既有局部隔离、泄露无权上下文且无法得到正确 CAS；与 RFC-005/ADR-0009 冲突。

## 迁移与发布

1. 先审查并接受 RFC，记录 ADR；不写入、不改现有 `agent-runtime-state` 1.0.0。
2. RFC/ADR 后可并行稳定 `ControlPolicy`、`ChangeSet`、`RuntimeKernel fencing` 与 `ProvenanceRecord` 四个独立公共契约和契约测试；每项都要定义可验证的 opaque ref/handle、版本和失败语义。
3. 四项全部 stable 后，才定义 `agent-runtime-transition-command` 与 `agent-runtime-authority-transition-record` 新 family：Command、canonical serialization/fingerprint（含 rebind target ref）、非泄露准入输入、CAS、Result、AuthorityTransitionRecord、幂等、outbox refs 和新诊断。
4. 再实现单存储 authority ledger、durable CAS、journal、outbox、查询/恢复、默认关闭 flag；其后才接入 Policy/ChangeSet/ProvenanceRecord/RuntimeKernel 集成与故障恢复验证。
5. 仅 staging 内部预览通过后，IDE 才提供单 Agent/多 Agent 的召唤、关闭、封存和状态体验；UI 必须显示 conflict/rejected/indeterminate/cleanup pending，而不能伪造成功。

```text
RFC-006 + ADR
  ├─ ControlPolicy contract + tests ───────┐
  ├─ ChangeSet contract + tests ──────────┤
  ├─ RuntimeKernel fencing + tests ───────┼─> transition-command + authority-record contracts
  └─ ProvenanceRecord contract + tests ───┘                         |
                                                                     v
                                      authority ledger / CAS / journal / outbox
                                                                     |
                                                                     v
                         cross-module integration + recovery / security tests
                                                                     |
                                                                     v
                         default-off internal preview -> IDE summon/control UI
```

四项前置契约可以并行，但不得共同修改一个未稳定公共接口；两个状态写入 family 必须等待四者完成并以各自稳定引用为前置。任何先行实验只能使用不可发布的 test double，不能形成持久生产数据或对外兼容承诺。启用后若需回滚，先停止新增运行权限，保留只读与撤销/清理通道；不得删除已提交 State 或 journal 后重放旧请求。状态修复通过新的获权补偿命令完成，不能覆盖历史。

## 测试计划

后续各 Issue 必须覆盖：

1. transport-invalid 在准入前失败；对无权 actor，存在/不存在的 scope、context、State、request_id 及同 ID 同/异 fingerprint 均返回同一非披露拒绝，并证明未读 State、未查/建 journal、未建 AuthorityTransitionRecord；最小安全事件不得带局部存在信息；
2. 已发布 `agent-runtime-state` 1.0.0 的 Intent/Plan/Record 仍只走 pure validation/plan，`side_effects: forbidden` 不变；旧 `applied` 绝不映射为 committed，旧对象和旧诊断不能进入新 write API；
3. 新 family 严格输入、引用闭包、版本、canonical bytes/fingerprint 和 Python/TypeScript 差分；`rebind_profile.target_profile_ref(id,revision)` 的省略、字段变化、跨 ID、非 dormant、与 plan/CAS evidence 不一致均被拒绝；
4. 相同 request_id 同 fingerprint 只执行一次、不同 fingerprint conflict、最终结果稳定重放、pending/timeout 后仅以原 ID 恢复；
5. 同一局部前置版本竞争时唯一 CAS 成功，不同 scope/context 独立并发，aggregate 不可作 CAS；
6. 按结果矩阵验证 transport/pre-authorization/pending/conflict/pure rejected/no_change/Provenance validation denied/Policy denied/ChangeSet denied/fence preparation denied/committed/indeterminate/cleanup 的 journal、State、Record、Policy、ChangeSet、fence 与 outbox 写入集合；provenance 验证失败必须产生稳定 rejected journal 与最小 AuthorityTransitionRecord，并证明未改变 State、未调用或创建 Policy/ChangeSet、未准备 fence、未创建 outbox；
7. 在 journal 占位、State、AuthorityTransitionRecord、result、outbox、commit response、worker 与清理各故障点注入崩溃，恢复后没有两个权威状态、孤立可见 State、无结果 committed 或可执行未提交 outbox；
8. `ProvenanceRecord` 缺失、过期、撤销、错 actor、错 scope/context 或与 command/fingerprint/意图不匹配时，必须在 pure plan 后、Policy 前停止，并覆盖稳定重放与无权路径不泄露局部 State；Policy、ChangeSet 与 fence 的缺失、过期、撤销或绑定不匹配也分别拒绝；ProvenanceRecord 原件正文不得复制到命令、journal 或 Record；
9. admission 后 close、重新 summon、晚到模型/工具回调或重复 outbox 时，旧 state/epoch/fence 不能提交；close 先 durable dormant，清理失败不恢复 active，安全清理可重试；
10. feature flag 默认拒绝增加 authority 且没有调试旁路；读取权限、Profile、persona、role、ability 或 aggregate 均不能升级为命令权限；
11. 端到端演练：Profile→局部 dormant→新 Command→非泄露准入→pure plan→ProvenanceRecord validation（无效即停止）→Policy→ChangeSet→fence preparation→atomic active→受控输出→close→atomic dormant→旧输出阻断→cleanup recovery→request result 查询。

## 已接受事实、推荐、仍待产品负责人决定的事项

### 已接受事实

- 用户可长期保有并召唤一个或 N 个任意设定的 Agent，不受固定角色限制。
- Profile 与 RuntimeState 分离；局部唯一键、三态、显式 rebind、epoch 和授权过滤 aggregate 已由 RFC-005/ADR-0009 固定。
- aggregate 只读且无写入、lease 或授权含义。
- AI 修改需要溯源、显式权限和回滚；真实副作用须经控制平面和隔离执行边界。
- 当前运行时仅能读取、验证、预演和汇总。

### 推荐

1. 采用方案 A 的事务型 authority ledger；
2. State、AgentRuntimeAuthorityTransitionRecord、幂等最终结果和 outbox 同一逻辑提交边界；
3. 保存通过非泄露准入后的 conflict/rejected/no_change 等稳定最终结果，以 request_id 重放；pre-authorization denial 不进入局部 journal；
4. 使用 durable CAS 与 admission/final-commit 双栅栏；
5. close 先持久化 dormant，安全清理独立于“新增权限”开关；
6. 允许经过同等故障测试的 commit-marker barrier 适配器；
7. 首个真实预览仅限单项目、单 RuntimeKernel、dormant↔active、默认关闭且无外部工具/高风险网络能力。

### 仍待产品负责人决定的事项

1. 是否接受方案 A 作为权威存储根边界（推荐接受）。
2. 是否把通过非泄露准入后的 conflict、Policy/ChangeSet/fence 拒绝和 no_change 持久化为不可重解释的最终 request 结果（推荐是；pre-authorization denial 排除）。
3. AgentRuntimeAuthorityTransitionRecord、完整幂等结果和防复用墓碑的保留/匿名化期限（推荐审计记录按项目溯源策略，完整结果保留恢复期，后保留最小墓碑）。
4. 常规写入关闭后，已提交 close 的 lease 撤销/资源清理能否走独立安全通道（推荐能）。
5. 不具同物理事务的存储是否接受严格等价 barrier 适配器（推荐接受，但必须通过同等故障测试）。
6. 首个内部预览是否限于单本地项目、单 RuntimeKernel、dormant/active 和默认关闭（推荐是）。

## 决定

草案阶段保持为空。接受后创建 ADR，并按上述依赖图创建独立契约、模块、集成与 UI Issue；在这些独立 Issue 通过前，不实现真实状态转换。