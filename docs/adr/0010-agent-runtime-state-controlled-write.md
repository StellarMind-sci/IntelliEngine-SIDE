# ADR-0010：AgentRuntimeState 采用受控写入与执行栅栏

- 状态：已接受
- 日期：2026-08-28
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-006：AgentRuntimeState 受控写入与执行栅栏](../rfc/0006-agent-runtime-state-controlled-write-and-fencing.md)、[GitHub Issue #56](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/56)、[GitHub Issue #58](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/58)

## 背景

SIDE 已完成长期 `AgentProfile`、局部 `AgentRuntimeState` 1.0.0 机器契约和 Python/TypeScript
只读消费者。现有能力只能验证、预演和汇总生命周期状态，不会持久化转换、启动真实执行、授予
工具权限或产生外部副作用。若未来把“召唤/关闭”直接实现为覆盖一条状态记录，将无法安全处理
并发覆盖、重复请求、崩溃后的未知提交、状态与审计部分成功、关闭后旧执行继续提交，以及把人格、
角色、aggregate 或 `active` 误当权限等风险。

ADR-0008 将 `AgentProfile` 固定为长期身份锚点，ADR-0009 将每条局部权威状态的唯一键固定为：

```text
(authority_scope_ref, runtime_context_ref, AgentProfile.id)
```

同一长期 Agent 因而可以在不同项目或会话中独立处于 `active`、`dormant`、`archived`。
状态与 Profile、记忆、模型绑定、团队关系和权限继续分离；授权过滤 aggregate 只是由调用方已获权
读取的局部投影派生出的只读视图，不能成为命令、CAS、授权或批量目标的输入。

RFC-006 已定义真实状态变更前必须具备的 durable CAS、幂等、溯源、策略、变更批准、执行栅栏、
恢复和默认关闭边界。产品负责人于 2026-08-28 接受 RFC-006 的六项产品决定。本 ADR 将其固化
为后续公共契约和实现必须遵守的长期规则；它不表示存储、ControlPolicy、ChangeSet、
RuntimeKernel、OS 隔离、UI、真实召唤/关闭或任何副作用已经完成。

## 决定

### 保留身份、局部状态和只读边界

ADR-0008、ADR-0009 的以下语义不变：

- 局部唯一键仍为 `(authority_scope_ref, runtime_context_ref, AgentProfile.id)`；不得改用
  `state_id`、Profile revision、显示名称、会话 ID 或 aggregate。
- 生命周期仍只有 `active`、`dormant`、`archived` 三态；永久删除仍是未来独立高风险操作。
- `AgentProfile` 与 `AgentRuntimeState` 分离。Persona、目标、角色、能力、记忆、模型绑定、
  团队/项目关系、策略和凭据不得嵌入 RuntimeState，也不得由转换反向改写 Profile。
- aggregate 仍然只读、派生、授权过滤且非权威；不得枚举无权上下文，不得作为命令目标、CAS
  输入、授权凭据、“关闭全部”或跨上下文写回入口。
- `active` 只表示该局部上下文中的可发现生命周期状态，本身不授予模型、文件、网络、设备、
  工具或项目写入权限。

### 写入 family 与已发布只读 family 严格隔离

已发布 `agent-runtime-state` 1.0.0 保持 `side_effects: forbidden`。其中的
`TransitionIntent`、`TransitionPlan`、`AgentRuntimeTransitionRecord` 只用于原始输入校验、
纯 `plan_transition`、只读记录一致性检查和授权输入的 aggregate 投影。旧记录的 `applied`
只表示所描述的纯计划结果通过只读契约校验，永远不表示 authority ledger 已提交，不得映射或
重解释为 `committed`。

真实写入必须由 `packages/agent-runtime` 后续新增并分别版本化的 family 承载：

- `agent-runtime-transition-command`：拥有写命令、canonical serialization/fingerprint、
  通过非泄露准入后的 request journal、稳定结果和 recovery query；
- `agent-runtime-authority-transition-record`：拥有不可变
  `AgentRuntimeAuthorityTransitionRecord`，记录进入权威链后的稳定结果和最小证据引用，
  但不是第二份可修改 State。

写 API 只能接受新的 command family。旧对象不能机械提升为写命令，旧诊断不能表达 durable
冲突、拒绝或提交结果，旧 `applied/no_change/conflict/rejected` 也不能导入新 journal。即使旧
family 发布新 major，也不会自动获得副作用权限；已发布 1.0.0 schema、fixtures、lock、诊断和
结果枚举不得原地修改。

### ProtectedScopeAdmission 先于 State 和 journal

请求首先只能进行不访问 authority-local 数据的严格 transport/envelope 校验。随后必须执行
`ProtectedScopeAdmission`：以已认证 actor、控制平面拥有的 scope/context 成员关系、稳定
AgentProfile 逻辑 ID 和操作类别，判断调用者能否对受保护局部键发起命令或查询结果。

该准入门不读取局部 State、Profile revision 绑定或 request journal，不查询 `request_id` 是否
存在，不把调用方提供的 opaque ref 当成授权，不替代完整 ControlPolicy，也不批准状态变化。
存在或不存在的 scope、context、State 和 request ID 必须返回不可区分的统一拒绝。

只有通过准入后，系统才可生成 canonical bytes/fingerprint、查询或建立 journal、读取局部 State
以及返回 request ID 复用或 CAS 诊断。准入失败不进入局部 journal；如需安全审计，只能记录与局部
存在性无关的最小事件，不得包含 request ID、State、revision、Profile 绑定或可关联出局部键的
细节。读取 State 和按 request ID 查询结果也必须先通过同等或更严格的非泄露准入。

### 稳定结果与 actual-change 证据链

每条命令必须携带稳定 `request_id` 和由锁定算法产生的 fingerprint。fingerprint 至少绑定 family
及版本、局部唯一键、精确 expected ProfileRef、操作、CAS 前置条件、actor/授权上下文、
`provenance_record_ref` 及影响语义的选项；`rebind_profile` 还必须绑定精确 target ProfileRef。

- 相同 request ID 与相同 fingerprint 重放首次最终结果，不重新规划、授权或执行。
- 相同 request ID 与不同 fingerprint 稳定返回 `request_id_reused` conflict，不覆盖原记录。
- `committed`、`no_change`、`conflict` 和通过非泄露准入后的各类 `rejected` 都是不可重解释
  的稳定最终结果；后来策略或 State 变化不能改变同一请求的含义。
- 无法证明提交是否发生时只返回非最终 `indeterminate`；恢复必须沿用原 request ID 和同一已持久
  pending/事务，不得换 ID 重做 actual change。

纯计划确认 `no_change` 时即终结稳定结果：不得增加 `state_revision` 或
`activation_epoch`，不得创建 lease、授予权限、进入 Policy/ChangeSet/fence 链或产生执行
outbox。CAS conflict、pure rejected 和 no_change 可以形成最小不可变权威记录以支持已获准请求的
审计，但都不能改写 State。

只有纯计划确认存在 actual change 后，才按固定顺序消费证据：

```text
ProvenanceRecord validation
  -> ControlPolicy decision evidence
  -> approved ChangeSet evidence
  -> RuntimeKernel fencing preparation
  -> atomic authority transaction
```

`services/provenance`、`packages/control-plane` 和 RuntimeKernel/执行平面分别拥有上述公共契约
的完整 Schema 和验证语义。RuntimeState 与新命令 family 只持有精确 opaque ref/handle 或最小
摘要，不复制来源/策略正文，也不另行定义这些契约。证据必须绑定 actor、局部唯一键、计划、
fingerprint、有效期和权限范围。缺失、过期、撤销、跨 scope/context 或计划不匹配时 fail closed。
ProvenanceRecord 验证失败必须在 Policy 前终结为稳定 rejected，后续 Policy、ChangeSet、fence
和 outbox 均不得创建。

### authority ledger、durable CAS、留存与恢复

采用事务型 authority ledger 作为 AgentRuntimeState 受控写入的唯一权威根边界：

- create 以 absent 为原子前置条件；
- 其他 actual-change 操作在最终提交时重新验证 `state_id`、`state_revision`、精确 ProfileRef
  和两个 opaque 上下文引用；事务外读取不能替代最终 CAS；
- 同一前置版本竞争时最多一个请求提交，其余请求终结为稳定 conflict；不同局部唯一键互不覆盖。

一次 committed change 的逻辑提交边界必须同时包含新 State、不可变
`AgentRuntimeAuthorityTransitionRecord`、journal 最终结果，以及仅在需要提交后工作时才追加的
outbox。权威读取方必须原子看到这些事实。禁止先写 State 再尽力补审计，也禁止先启动执行再记录
状态。

不能提供同一物理事务的存储，只能通过严格等价的 `pending/commit-marker/outbox` barrier
适配器实现同一逻辑边界。适配器必须通过与单事务实现相同的原子性、并发和崩溃恢复测试：marker
前不得暴露新 State 或消费 outbox；恢复要么完成原事务，要么保持旧权威状态；不能证明等价时不得
发布。

通过非泄露准入后的 conflict、Policy/ChangeSet/fence rejected 与 no_change 均保存到 journal，
以支持稳定重放；pre-authorization denial 不进入局部 journal。
`AgentRuntimeAuthorityTransitionRecord` 按项目审计与溯源策略保留；完整幂等结果至少覆盖可
重试和恢复周期。周期结束后仍保留只含 request ID、fingerprint 摘要、最终结果摘要和版本的最小
防重放墓碑；非权威附属信息可依合规策略匿名化。墓碑不得让相同 request ID 获得新含义。

### RuntimeKernel 双重栅栏和安全关闭

fence preparation 只预备未来执行条件，不等于最终执行权。执行 worker 在启动副作用前必须重验
当前 State 为 active，并核对 `state_id`、`activation_epoch`、lease、fence generation、
Policy、ChangeSet、authority scope 和 runtime context。任何结果写回、工具操作、工程修改或外部
副作用提交前，还必须在同一授权/提交边界执行 final-commit check。只做一次 admission check
不足以阻止关闭、重启、重新召唤或迟到回调后的旧 epoch 提交。

close 固定为先提交 authority、后清理资源：先经证据链与 CAS 原子提交
`active -> dormant`、不可变 Record、最终结果和 cleanup outbox，使旧 epoch 立即失效；随后才
撤销 lease、停止进程和清理资源。清理失败、超时、重连或进程仍存活不得恢复 active 或旧 lease；
清理可通过 outbox 重试，但存活旧进程仍须被 fence 阻止提交。

常规写入能力由默认关闭的 capability flag 控制。关闭时禁止增加运行权限的写入、召唤和
RuntimeKernel 启动，但已经提交的 close、lease 撤销和资源清理可以在独立安全通道继续完成。
该通道只能减少或终结 authority，不能新增、扩展或恢复运行权限，也不能成为调试旁路。

### 首个内部预览和实施顺序

首个真实内部预览只支持单个本地项目、单个 RuntimeKernel、既有合法
`dormant <-> active` 转换，且 capability flag 默认关闭；不接外部工具或高风险网络能力。
封存、rebind、多项目/多 Kernel、批量写入、外部工具、网络和更高自主性必须另行验证，不能由
首个预览隐式获得。

后续顺序固定为：

1. `ProvenanceRecord`、`ControlPolicy`、`ChangeSet`、`RuntimeKernel fencing` 四个前置
   公共契约及契约测试分别由独立 Issue 完成。四项可以并行，但不得共同修改未稳定接口或提前实现
   状态命令。
2. 四项全部稳定并合并后，才按依赖关系串行定义和稳定
   `agent-runtime-transition-command` 与 `agent-runtime-authority-transition-record` 新 family；
   在它们发布前不得开始真实写入使用方。
3. 两个新 family 稳定后，再以独立 Issue 实现 authority ledger、durable CAS、journal、outbox、
   查询/恢复和默认关闭 flag。
4. 再接入 ProvenanceRecord、Policy、ChangeSet 和 RuntimeKernel，执行跨模块、并发、崩溃恢复、
   安全和双重 fencing 验证。
5. 只有 staging 内部预览通过后，IDE 才能接入召唤、关闭、封存、恢复和状态展示；UI 必须如实显示
   conflict、rejected、indeterminate 和 cleanup pending，不能伪造成功。

先行实验只能使用不可发布的 test double，不得形成持久生产数据或兼容承诺。公共契约和契约测试
必须先于使用方，每项公共接口变化继续由一个独立 Issue/PR 交付。

## 结果

### 收益

- 未来召唤或关闭一个或 N 个长期 Agent 时，各局部上下文可保持确定的并发、重试、审计和恢复
  语义，而不破坏长期身份或其他上下文。
- 非泄露准入阻止无权调用者以 State、request ID 或错误差异探测受保护项目和会话。
- 事务型 ledger、durable CAS、稳定结果和双重 fencing 防止重复提交、部分成功与关闭后的陈旧执行。
- 独立 contract family 与证据链保持身份、状态、溯源、策略、变更批准和执行职责独立演进。
- 默认关闭和只减权安全清理通道允许在控制风险时继续终结已有 authority。

### 成本与约束

- 实现必须维护 canonical fingerprint、durable journal、不可变记录、恢复器、outbox、保留策略、
  CAS、epoch/lease/fence 和 Python/TypeScript 一致性；不能退化为 active 布尔写入。
- 四个前置契约、新 command/record family 和 ledger/integration 必须依序稳定，真实召唤与 UI
  后置于安全前置，不能为演示跳过门禁。
- barrier 适配器承担与物理事务相同的故障证明成本；没有等价证据时只能使用单事务实现。
- 最小墓碑、审计记录和诊断仍可能涉及敏感关联，必须遵守项目审计、溯源、最小化、匿名化和访问
  控制策略，不得记录私有记忆、提示词、凭据或受保护原件正文。
- 本 ADR 只确定应用层架构边界，不提供数据库耐久性、OS/容器隔离、设备安全、UI 或真实副作用的
  完成证明。

### 回滚

任何写入实现或生产数据出现前，可以回退相应未发布 PR；本 ADR 的已接受语义如需改变，必须通过
新 RFC 和替代 ADR 决定。已发布 `agent-runtime-state` 1.0.0 与未来的新 family 均不得原地改写。

启用后的安全回滚顺序是：停止新增或扩展运行权限，保留只读查询和独立撤销/清理通道，冻结有
问题的写入适配器与 worker，并沿原 request ID、ledger 和 commit marker 完成恢复。不得删除已提交
State、Record、journal 或墓碑后重放旧请求，也不得覆盖历史；修复 authority 必须创建新的获授权
补偿命令。若 epoch/fence 或 barrier 失效，必须阻断受影响副作用提交，不能只回滚 UI。

## 验证

- `python scripts/verify_governance.py` 必须通过；该检查只证明 ADR 和治理结构有效，不证明任何
  受控写入、存储、策略、执行或 UI 已实现。
- ADR 必须经独立审查，逐项核对 RFC-006 六项产品决定、ADR-0003/0004/0006/0008/0009、局部
  唯一键、三态、Profile/State 分离、aggregate 禁写、family 隔离、非泄露准入、actual-change
  证据顺序、原子 ledger、CAS、稳定结果、留存、恢复、双重 fencing、close 和实施依赖。
- 四个前置公共契约必须各自提供版本化机器工件、稳定 opaque ref/handle、失败语义、契约测试和
  独立审查；在其全部稳定前，新写命令 family 不能发布。
- 新 command/authority-record family 必须验证严格 transport、版本、canonical bytes/fingerprint、
  request ID 重放/复用、非泄露诊断、result/record 映射，以及 Python/TypeScript 对相同 fixtures
  的字节、指纹、结果和诊断一致；并证明旧只读 1.0.0 不被修改或提升。
- ledger 与 barrier 实现必须通过同一局部 CAS 竞争、跨局部并发、pending/final/indeterminate、
  State/Record/result/outbox 各故障点崩溃恢复、无孤立可见事实、无可执行未提交 outbox 和最小墓碑
  防重放测试。
- 集成验证必须覆盖 Provenance 缺失/错绑定、Policy/ChangeSet/fence 拒绝、no_change 不授权、
  close 先 dormant、旧 epoch/lease/迟到回调被 admission 与 final-commit 双重阻断、清理失败不恢复
  authority、默认关闭无旁路，以及端到端 summon/close/recovery 演练。
- OS isolation、外部工具、网络权限、生产部署和 IDE 体验必须由后续 Issue/测试独立证明；本 ADR、
  治理检查或未来单个契约测试均不得作为这些能力已完成的证据。
