# ADR-0009：AgentRuntimeState 采用局部生命周期与授权过滤聚合

- 状态：已接受
- 日期：2026-08-27
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-005：AgentRuntimeState 生命周期与召唤边界](../rfc/0005-agent-runtime-state-lifecycle-and-summoning.md)、[GitHub Issue #48](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/48)、[GitHub Issue #50](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/50)

## 背景

SIDE 允许用户长期保有、随时召唤或关闭一个或 N 个 Agent 个体。一个长期 Agent 可能同时参与多个工程或会话；在一个上下文中应当可参与，不代表在另一个上下文中也可参与。把生命周期状态写进 `AgentProfile` 会污染 ADR-0008 的长期身份锚点；把它做成控制域内唯一的全局状态，则无法表达同一 Agent 在不同工程或会话中的独立状态。

产品负责人已于 2026-08-27 在 RFC-005 中选择方案 C：生命周期记录是局部的，汇总视图只能在调用者已经获授权读取的局部范围内派生。后续实现还必须避免将“已唤醒”“人格”“能力”或 aggregate 误解释为权限、模型会话或跨项目控制权。

本 ADR 固化生命周期的长期边界与交付顺序；它不表示状态机、存储、权限、执行 lease、召唤 UI 或任何真实副作用已经实现。

## 决定

### 局部状态的身份、所有权与三态

`packages/agent-runtime` 将拥有 `AgentRuntimeState`、其精确引用、状态机、局部只读投影、状态修订、activation epoch 和状态诊断。每条权威局部状态的存储唯一键固定为：

```text
(authority_scope_ref, runtime_context_ref, AgentProfile.id)
```

其中 `authority_scope_ref` 是控制平面拥有的不透明控制域引用，`runtime_context_ref` 是不透明的项目或会话上下文引用，`AgentProfile.id` 是 ADR-0008 定义的长期逻辑身份。`state_id` 只标识创建成功后的那一条局部状态，`AgentProfileRef` 仍精确固定为 `(id, revision)`，但 revision 不属于局部唯一键，因此同一逻辑 Agent 的 dormant rebind 不会生成另一条局部记录。

同一 Agent 可在不同 `runtime_context_ref` 中独立处于 `active`、`dormant` 或 `archived`；相同上下文但不同 `authority_scope_ref` 也独立。某一上下文不存在局部状态表示尚未注册，不等同于 dormant，也不得影响同一 Agent 的其他局部记录。

- `active` 表示该局部上下文的 Agent 已唤醒且可被发现；它仍须通过独立的 ProjectAssignment、ControlPolicy、ModelBinding 和 RuntimeKernel lease 才能参与任何工程副作用。
- `dormant` 表示该局部上下文已关闭，不能接收该上下文的新任务、主动调用模型或提交该上下文的新副作用，但不删除长期身份或其他分层对象。
- `archived` 表示该局部上下文长期封存，默认从搜索、推荐、调度、协作和批量召唤中排除；只读检查须使用精确 ID 或显式包含归档。

状态不得包含 persona、goals、角色、能力、私有记忆、模型或密钥、团队/项目语义、权限、策略正文、任务、进程、输出或 UI 状态。

### 显式局部转换、并发与 epoch fencing

所有转换只作用于同一局部唯一键，不能读取、改变、推断或关闭其他上下文。创建必须以“该唯一键不存在”为原子前置条件，创建后的状态为 dormant；正常转换仅允许 `dormant → active → dormant → archived → dormant`。`active → archived` 与 `archived → active` 必须拒绝，永久删除不属于该状态机。

Profile rebind 是显式、可审计的局部操作，只能在 dormant 时进行；目标 Ref 必须具有相同的 Profile ID，且不会迁移或改写 MemoryLedger、CapabilityEvidence、ModelBinding、AgentTeam、AgentRelation 或 ProjectAssignment。Profile 新 revision、应用启动、模型重连、团队变化或状态读取都不得自动 rebind 或自动转换状态。

每条局部状态具有单调递增的 `state_revision`，用于 compare-and-swap；所有非创建操作携带精确 `{state_id, state_revision}`、精确 expected ProfileRef 以及两个不透明上下文引用。写入还具有稳定 `request_id`：相同规范请求返回首次持久结果，不重复 revision、epoch、ChangeSet 或副作用；同一 request ID 对应不同规范 payload 返回 conflict；过期 expected state 也返回 conflict。目标本已满足时为 no_change，不增加 revision/epoch，也不授予新 lease。非法输入、非法版本或禁止状态路径为 rejected，控制/存储依赖不足时 fail closed。

每次实际进入 active 都增加局部 `activation_epoch`。执行平面必须将 lease 绑定 `(state_id, activation_epoch)`；每一项副作用的 admission 和最终 commit 都要在同一个不可分割的授权/提交边界原子重验权威状态为 active 且 lease 完全匹配。close 必须先原子提交 non-active 状态，使旧 epoch 无法通过最终 commit；后续进程或会话清理可重试，但其失败、重连或延迟均不得恢复 authority。状态、不可变 TransitionRecord、幂等结果与 fencing 的提交必须原子可见。

Control plane 仍拥有 TransitionIntent 的提出、ControlPolicy 解析、ChangeSet 批准、影响预演、提交与回滚；RuntimeKernel/执行平面拥有 lease、资源与副作用 fencing。RuntimeState 既不是权限凭证，也不替代上述控制职责。

### 授权过滤的 aggregate 不是全局状态或控制入口

`packages/agent-runtime` 可以为查看目的生成 aggregate/projection，但只能从控制平面显式提供、且当前调用者已经获授权读取的局部投影集派生。aggregate：

- 只读、派生且非权威；不拥有 `state_revision`、`activation_epoch`、lease、TransitionIntent、写入权或授权含义；
- 不得枚举、探测、推断或泄露无权项目/会话的存在、标识、数目或状态；空集不等于所有局部状态均不存在；
- 不能覆盖局部状态，不能因一个上下文 active 推论另一个上下文可用，也不能替代 ProjectAssignment、会话、ControlPolicy 或其他权限检查；
- 不得隐式触发“关闭全部”、召唤或任何跨上下文写入。

未来确需处理多个局部状态时，只能以显式 batch intent 指明目标局部记录及“原子全成功”或“逐记录结果”的语义，并对每条记录执行 Policy、ChangeSet 与 CAS。aggregate 永远不能成为该命令的隐藏输入或写入入口。

### 与长期身份及其他分层对象的关系

ADR-0008 的 `AgentProfile` 继续是可移植、版本化的长期身份锚点；RuntimeState 仅通过精确 `AgentProfileRef` 绑定它，运行时转换不会改写 Profile。MemoryLedger 拥有私有长期记忆，CapabilityEvidence 拥有能力证据，`packages/model-gateway` 的 ModelBinding 拥有模型路由，AgentTeam/AgentRelation/ProjectAssignment 拥有团队、关系、角色和项目分工；这些对象均不得被 RuntimeState、aggregate、persona、角色、能力、来源或 active 状态隐式授权。

`authority_scope_ref` 与 `runtime_context_ref` 都是不透明引用：它们不能携带用户身份、权限、策略正文、项目角色、任务或会话内容，也不能独立授权。项目和会话的具体语义仍归后续独立契约所有。

### 导入、导出、删除、回滚与执行隔离边界

默认开放工程包不得包含 authority-local operational RuntimeState。未来显式导出的只读生命周期快照必须排除 authority 身份、策略正文、lease、会话、资源、私有记忆与凭据；导入仅可作为证据读取，不能直接 active。目标域必须重新映射 authority、验证精确 ProfileRef，并经新的 Policy/ChangeSet 创建本地 dormant 状态；来源 active、epoch、任务和会话绝不迁移。冲突不得静默合并，来源链和 remap 由 ProjectPackage/ProvenanceRecord 契约定义。

永久删除是独立高风险控制操作，不能添加为 `deleted` 状态；它需要影响预览、显式高风险授权、依赖与保留检查、导出选择、审计和可恢复期。回滚通过新的获授权补偿转换返回安全 dormant，而不是覆盖历史记录。若发现 epoch fencing 缺陷，必须冻结受影响状态写入与副作用执行，不能仅回滚 UI。

本 ADR 只规定应用层的状态、策略和 fencing 边界，并不提供 OS 级进程隔离、容器隔离或设备安全承诺；这些保障仍须由 sandbox、安全与部署契约独立实现和验证。

### 实施顺序与兼容门禁

遵守 ADR-0003、ADR-0004、ADR-0006 和 ADR-0008，实施顺序固定为：

1. 独立 Issue 先发布版本化机器契约：局部 State/Ref、TransitionIntent/Record、aggregate 的只读 schema、诊断、fixtures、JCS lock 和无副作用 verifier；其中不含写入 API、存储 CAS、Policy、ChangeSet、lease 或 UI。
2. 契约经独立审查并合并后，Python 与 TypeScript 分别实现独立只读消费者、纯函数校验/转换预演、局部 summary 和授权输入的 aggregate 投影，并以 fixtures 与 differential runner 验证逐字段一致。
3. 两种消费者与跨语言差分通过后，另行实现 durable CAS、idempotency journal、ControlPolicy、ChangeSet、RuntimeKernel fencing 和 feature flag 默认关闭的受控写入。
4. 只有受控写入通过安全与集成验证后，IDE 才能接入单 Agent/多 Agent 召唤、关闭、封存、恢复、状态可视化及用户快捷控制体验；批量写入和跨工程体验继续以独立 Issue 扩展。

未知 major 的状态/intent/aggregate 工件必须拒绝；同 major 较新 minor 仅可无副作用兼容读取，不能用于 transition、rebind、导入激活或权限判断。已发布的 1.x 工件不得原地重写。

## 结果

### 收益

- 同一长期 Agent 可以安全地在不同项目或会话中保持独立、可解释、可恢复的参与状态。
- 局部 CAS、幂等和 epoch fencing 给未来真正的召唤/关闭提供并发与陈旧执行防线。
- 授权过滤 aggregate 为用户提供可见性，同时避免暴露其他工程或会话关联。
- 身份、记忆、模型、团队、项目分工、权限和运行状态仍可按各自契约独立演进。

### 成本与约束

- M1 必须维护局部唯一键、精确 ProfileRef、两类不透明引用、状态 revision、epoch、幂等和可见性过滤，不能用简单 active 布尔值替代。
- aggregate 的正确性依赖控制平面先提供授权过滤后的局部投影集；它不能成为绕过控制平面或做“全局状态查询”的捷径。
- 本 ADR 不构成任何运行时能力、真实模型调用、存储耐久性、权限、OS isolation 或 IDE 交互的完成验收。

### 回滚

在机器契约或消费者未发布前，可回退对应 PR；不得重写已发布 1.x 工件。若后续消费者或 UI 有缺陷，关闭相应 feature flag 或回滚使用方，保留只读验证路径和最小失败 fixture。若语义缺陷影响已接受边界，冻结写入，保留历史只读，通过新的 RFC、替代 ADR、显式版本和迁移修复；不得用“修正 aggregate”掩盖局部状态或 fencing 缺陷。

## 验证

- `python scripts/verify_governance.py` 必须通过；它只验证治理结构，不证明状态机或运行时已经实现。
- ADR 必须经独立审查，逐项核对 RFC-005 方案 C 的局部唯一键、三态、rebind、CAS/幂等、epoch fencing、aggregate 可见性、分层边界、导入/导出/删除、隔离边界和实施顺序，并确认不冲突 ADR-0003、0004、0006、0008。
- 后续机器契约必须覆盖一个/N 个 Agent、相同 Agent 的跨上下文独立状态、局部创建竞态、stale CAS、幂等重放、no_change、非法路径、rebind、旧 epoch 副作用拒绝和授权过滤 aggregate。
- 后续 Python/TypeScript 消费者必须对相同原始 fixtures 的 validation、diagnostic、transition plan、summary 和 aggregate 投影逐字段一致；未知 major、较新 minor 只读、无权上下文与空授权集均须有负向用例。