# RFC-005：AgentRuntimeState 生命周期与召唤边界

- 状态：已接受
- 负责人：StellarMind-sci
- 创建日期：2026-08-24
- 关联 Issues：[GitHub Issue #48](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/48)

## 问题

SIDE 已用 `AgentProfile` 和精确 `AgentProfileRef(id, revision)` 定义长期 Agent 身份，但尚未定义“这个 Agent 现在是否被唤醒”的独立工程对象。用户需要像召唤 NPC 一样管理一个或 N 个长期自定义 Agent：可唤醒、关闭、封存和恢复，而不丢失身份、记忆、能力证据或关系。

若状态写入 Profile，关闭会改写身份；若每次召唤都创建短期 Agent，则无法恢复同一个长期个体；若状态只是一枚布尔值，并发快捷键、后台策略、崩溃恢复或多窗口操作还可能让已关闭的旧执行继续提交结果。因此必须先确定 `AgentRuntimeState` 的对象身份、三种状态、精确 Profile 绑定、并发、审计和控制边界。

## 目标与非目标

### 目标

1. 定义可版本化、可审计的**局部** `AgentRuntimeState`，精确引用 Profile，并使同一长期 Agent 可在不同项目或会话中独立处于不同状态。
2. 定义 `active`、`dormant`、`archived` 及创建、召唤、关闭、封存、恢复和显式 rebind。
3. 定义状态修订、乐观并发、幂等和 activation epoch，使关闭后的旧执行不能继续获准产生副作用。
4. 分开无副作用读取/预演与未来经 ControlPolicy、ChangeSet、RuntimeKernel 执行的写入。
5. 保留身份、记忆、能力证据、团队/关系和项目分工；永久删除保持独立高风险操作。
6. 定义只读的全局汇总投影，但不让它取得局部状态写入权、权限或 lease；让后续契约、消费者、控制平面和 IDE 体验无需重新决定产品方向。

### 非目标

- 不实现持久化、写入、调度、模型/工具调用、代码执行、会话或 UI。
- 不定义 ControlPolicy、ChangeSet、RuntimeKernel、MemoryLedger、CapabilityEvidence、ModelBinding、AgentTeam/Relation、ProjectAssignment 或 ProjectPackage 的完整字段。
- 不固定教师、学生、科学导师、用户分身等角色，不限制 Agent 数量与设定。
- 不把人格、目标、角色、工作风格、声明能力、证据、来源或信任解释为权限。
- `active` 不代表一定有模型会话、任务、项目权限或算力。
- 不定义永久删除、所有权转移或私有记忆导出。
- 不允许状态改写 Profile，也不让 Profile 新 revision 自动重绑定状态。

## 提案

### 选择摘要与所有权

本 RFC 接受**方案 C：每个项目或会话上下文一份局部生命周期记录**。状态是稳定对象，引用精确 Profile revision；同一长期 Agent 可以在项目 A 为 `active`、在项目 B 为 `dormant`。召唤、关闭、封存和恢复只改变指定上下文中的局部状态，不创建短期人格或项目副本，也不改写其他上下文。

`packages/agent-runtime` 还可从所有局部记录生成全局 aggregate/projection，供用户查看其**已经获授权读取**的上下文中该 Agent 是否可参与、休眠或封存。aggregate 只能从控制平面显式提供的已授权局部投影集派生；它不得枚举、探测或暴露无权项目/会话的存在、标识或状态。aggregate 只是派生、只读视图：它没有 `state_revision`、`activation_epoch`、写入权或授权含义，不能覆盖任何局部状态，不能授予参与权，也不能把某处 `active` 推论为另一处可用。未来“关闭全部”只能是显式 batch intent，经 ControlPolicy、ChangeSet 和逐记录 CAS 后以原子全成功或清晰的逐 Agent 结果提交；它不能由 aggregate 隐式触发。

`packages/agent-runtime` 拥有状态结构、版本、状态机、只读投影、Profile 绑定、`state_revision`、`activation_epoch` 和诊断。控制平面与 ControlPolicy/ChangeSet 拥有提出、批准、提交和回滚；RuntimeKernel/执行平面拥有 lease、资源和副作用 fencing；模型、记忆、证据、团队、关系、项目和权限由各自契约拥有。

局部状态同时引用控制平面拥有的 opaque `authority_scope_ref` 和不透明 `runtime_context_ref`（项目或会话上下文）。二者均不携带用户身份、权限、策略正文、项目角色、任务或会话内容，也不能独立授权；项目角色、团队关系和具体会话语义仍由其未来独立对象拥有。

### 数据草案

```json
{
  "contract_version": "1.0.0",
  "state_id": "019...uuidv7",
  "state_revision": 7,
  "authority_scope_ref": "control-scope:...",
  "runtime_context_ref": "project-or-session:...",
  "agent_profile_ref": { "id": "019...uuidv7", "revision": 3 },
  "status": "active",
  "activation_epoch": 4,
  "last_transition_ref": "agent-runtime-transition:..."
}
```

- `contract_version` 是 canonical SemVer；未知 major 拒绝，同 major 较新 minor 仅无副作用兼容读取。
- `state_id` 是 canonical lowercase UUID，producer 应生成 UUIDv7；它是某一个局部记录的稳定身份，不是 Profile、项目、会话或执行 ID。
- `state_revision` 从 1 开始，每次实际转换或 rebind 增加 1；no_change/重放不增加。
- `authority_scope_ref` 是 opaque 控制域引用；`runtime_context_ref` 是 opaque 项目或会话上下文引用。局部状态的存储唯一键是 `(authority_scope_ref, runtime_context_ref, agent_profile_ref.id)`；同一长期 Agent 可以在不同上下文拥有独立记录。schema 不能证明存储唯一性。
- `agent_profile_ref` 精确到 revision，不得使用 latest、名称、路径或会话 ID。
- `status` 是闭合集合 `active | dormant | archived`，没有 `deleted`、`busy`、`error` 或角色状态。
- `activation_epoch` 从 0 开始，每次实际进入 active 增加 1，从不回退或复用。
- `last_transition_ref` 指向不可变审计记录，完整历史不嵌入投影。

状态不得包含 persona、goals、role、能力、私有记忆、提示词、模型/密钥、团队/项目语义、策略正文、权限、任务、进程、输出或 UI 状态。

未来写入另定义 `AgentRuntimeTransitionIntent`（request、operation、`authority_scope_ref`、`runtime_context_ref`、expected state ref、精确 expected ProfileRef、可选 target ProfileRef、reason/provenance）和不可变 `AgentRuntimeTransitionRecord`（请求摘要、局部唯一键、旧/新状态、结果、诊断、actor/Policy/ChangeSet/provenance、时间和回滚关联）。Intent 不是权限凭证，Record 不是可重放命令。

### 状态语义

- `active`：Agent 在该局部上下文已唤醒，可被发现，并在独立有效授权、分工和 lease 下参与工程；可以没有模型、任务、团队或算力。每次进入 active 产生新 epoch，执行 lease 必须绑定 `(state_id, activation_epoch)`。每一次副作用的 admission 和最终 commit 都必须重新读取权威状态，并在同一个不可分割的授权/提交边界中验证 `status == active` 且 lease 的 `(state_id, activation_epoch)` 与权威状态完全相同；只在 admission 检查一次不够。
- `dormant`：Agent 在该局部上下文已关闭，不接收该上下文的新任务、不主动调用模型或提交该上下文的新副作用；身份、Profile、记忆、证据、模型绑定、关系和项目记录保留。`close` 必须原子提交 non-active 状态并使旧 epoch 的全部 lease 失效，之后才可报告已提交；因此 epoch 即使只在下一次进入 active 时递增，旧执行也已经无法通过 status/lease 的 commit 校验。进程和会话清理可以重试，但清理成功、失败或重连都不能恢复其 authority。用户仍可发现和召唤它。
- `archived`：在该局部上下文长期封存，默认搜索、推荐、调度、协作和批量召唤排除它；精确 ID 或显式包含归档时可只读检查。它不删除外部对象，不能直接执行、rebind 或进入 active，须先恢复到 dormant。

Profile 在某个上下文没有局部 RuntimeState，表示尚未在该上下文注册，与该上下文的 dormant 不同，UI 不得混淆；它不影响 Profile 在其他上下文的状态。

### 转换与 rebind

下表的“当前”始终指同一 `(authority_scope_ref, runtime_context_ref, AgentProfile.id)` 的局部记录；任何转换不得读取、改变或推断其他上下文的状态。

| 操作 | 当前不存在 | 当前 active | 当前 dormant | 当前 archived |
|---|---|---|---|---|
| `create_state` | 状态变更：创建 dormant，revision=1、epoch=0 | `conflict`：唯一键已存在 | `conflict`：唯一键已存在 | `conflict`：唯一键已存在 |
| `summon` | `conflict`：预期现有状态不存在 | `no_change` | 状态变更：active，revision +1、epoch +1 | `rejected`：必须先 restore |
| `close` | `conflict`：预期现有状态不存在 | 状态变更：dormant，revision +1并 fencing 旧 epoch | `no_change` | `rejected`：archived 不是普通关闭状态 |
| `archive` | `conflict`：预期现有状态不存在 | `rejected`：必须先 close | 状态变更：archived，revision +1 | `no_change` |
| `restore` | `conflict`：预期现有状态不存在 | `rejected`：active 无需恢复 | `no_change` | 状态变更：dormant，revision +1 |
| `rebind_profile` | `conflict`：预期现有状态不存在 | `rejected` | 同 Ref 为 `no_change`；同 Profile ID 的不同 Ref 为状态变更，revision +1、epoch 不变 | `rejected` |

禁止 active→archived、archived→active、active/archived rebind、跨 Profile ID rebind、deleted 状态，以及因应用启动、模型重连、团队变化或 Profile 新 revision 自动转换。两步路径让“停止参与”和“长期可见性”分别可观察、授权、审计和回滚。

Profile 新 revision 出现时状态继续绑定旧 Ref。rebind 必须由显式 Intent、ControlPolicy、ChangeSet 完成且只在 dormant；目标 Profile 存在、可读且逻辑 ID 相同。可绑定更高或历史 revision 以支持显式回滚，但不覆盖历史。rebind 不迁移 MemoryLedger、CapabilityEvidence、ModelBinding、Team/Relation 或 ProjectAssignment。

### 幂等、并发、竞态与恢复

`create_state` 必须携带等价于 `expected_state = absent` 的前置条件，并使用 `(authority_scope_ref, runtime_context_ref, agent_profile_ref.id)` 作为局部存储唯一键；`state_id` 是成功创建后该记录的稳定身份，不参与该唯一键。两个不同 request 并发创建同一局部唯一键时，只有一个可由 absent 原子变为存在，另一个返回 `conflict`。不同上下文可并发创建，且彼此不冲突。相同 request 的崩溃重试则由幂等记录返回首次结果。

除 create 外，所有操作必须携带 expected state ref `{ state_id, state_revision }`、精确 `expected_profile_ref`，以及该局部记录的 `authority_scope_ref` 与 `runtime_context_ref`。这两个 opaque ref 必须和权威记录完全匹配；`state_id` 选择生命周期记录，`state_revision` 提供 CAS，Profile ID 只标识长期 Agent；它们与局部上下文 ref 均不得互相替代。

确定性判定顺序如下：

1. 无法解析或不满足封闭 schema 的输入返回 `rejected`；有效 request 才能形成规范 payload。
2. 查询 `request_id`：与已存规范 payload 完全一致时返回首次持久结果；同 request 不同 payload 返回 `conflict`。
3. 校验 contract/Profile refs；非法、跨 Profile ID 或不支持写入的版本返回 `rejected`。
4. 校验 expected state：create 要求局部唯一键 absent；其他操作要求 `{state_id,state_revision}`、`expected_profile_ref`、`authority_scope_ref`、`runtime_context_ref` 和权威状态完全匹配。不存在、已存在或任一不匹配返回 `conflict`。
5. 按上表判定：合法改变返回状态变更计划；目标已满足返回 `no_change`；禁止转换返回 `rejected`。
6. 只有状态变更计划继续进入 ControlPolicy、ChangeSet、fencing 和原子提交；`no_change` 不增加 revision/epoch、不创建执行 lease，也不伪装为新的授权。

所有写入同时使用稳定 `request_id` 与上述 expected state：

1. 同 request/相同规范 payload 重放，返回首次持久结果，不重复 revision、epoch、ChangeSet 或副作用。
2. 同 request/不同 payload 返回 `conflict` 并 fail closed。
3. 不同 request 的 expected state 过期时返回 `conflict`；即使目标碰巧相同，也不能掩盖期间的 rebind/转换。
4. expected state 正确且目标已满足，返回 `no_change`，不建 revision，也不授予新 lease。
5. 当前状态、TransitionRecord、幂等结果和 epoch fencing 必须比较并交换、原子可见。

同一局部记录上的并发 summon/archive、close/rebind、restore/archive 只有一个提交者，失败者重新读取并重新授权，不能自动改 expected state；不同 runtime_context_ref 的状态转换不互相覆盖或获得彼此的 lease。每个副作用的 admission 与 commit 都再次原子验证权威 `status == active` 和 lease epoch；若状态已提交但进程/会话清理失败，权威状态仍是新状态，旧 epoch 无法提交，清理可重试且不得静默恢复 active。

### 只读与未来写入数据流

M1 可先实现：原始 bytes 校验、显式固定 Profile 快照引用校验、确定性局部摘要/可见性、仅消费控制平面已授权局部投影集的全局只读 aggregate、纯函数转换预演，以及记录/revision/epoch 一致性校验。它们不得访问模型、记忆、团队、网络、项目文件或策略服务，也不得创建状态、ChangeSet、lease 或审计事实。

```text
TransitionIntent
  → transport / schema / exact ProfileRef
  → expected state + idempotency
  → pure transition plan
  → ControlPolicy + impact preview
  → ChangeSet approval
  → RuntimeKernel fencing preparation
  → atomic State + Record + idempotency commit
  → read projection + retryable cleanup
```

依赖缺失、Profile 不可读、策略不支持、ChangeSet 未批准或提交失败均 fail closed。人格、角色、能力或模型状态不能替代 Policy。

### 一个或 N 个 Agent

每个局部状态有独立 state ID、revision 和 epoch；同一 Agent 的不同上下文也不共享这些值。每个 Agent 有独立 Profile ID，多个 Agent 不得共享 Profile revision、私有记忆或授权。批量召唤可以覆盖一个或 N 个 Agent 的一个或 N 个显式局部状态，必须声明原子全成功或逐状态部分结果，不能静默部分成功。全局 aggregate 只显示调用者已获授权的局部结果，不参与批量命令的写入或授权。

## 公共接口

后续 contract Issue 在 `packages/agent-runtime` 分阶段交付：

- 局部 State、Ref、TransitionIntent、TransitionRecord 与只读 aggregate JSON Schema；State 与 Intent 均须携带 `authority_scope_ref` 和 `runtime_context_ref`；
- 状态、操作、结果与稳定 `agent_runtime_state.*` 诊断；
- 显式 Profile reference snapshot、validation result、fixtures、JCS lock；
- 纯函数 `validate_state`、`validate_profile_reference`、`plan_transition`、`state_summary`，以及 Python/TypeScript 对等 API 与 differential runner。

首个契约 PR 不含写入 API、Policy 解析、ChangeSet 提交、存储 CAS、lease、模型会话和批量写入。兼容沿用 M1：I-JSON、JCS、canonical SemVer、安全整数、unsigned UTF-8 排序、离线 `$ref`、封闭结果和确定诊断。较新同 major 仅只读，不允许 transition、rebind、导入激活或权限判断；已发布 1.x 工件不原地改写。

## 安全、溯源与控制策略

- persona、目标、角色、工作风格、能力声明/证据、来源、信任和 active 状态都不授权模型、文件、网络、设备、项目或工具；平台上限优先。
- 每次参与仍需独立 ProjectAssignment、ControlPolicy、ModelBinding 和 RuntimeKernel lease。`aggregate` 的读取还需要控制平面显式给出可见的局部投影集；它不得成为枚举其他项目/会话或绕过该可见性过滤的旁路。
- reason、actor/scope refs 和外部字符串不可信；日志不得回显隐私或凭据。
- applied、no_change、conflict、rejected、indeterminate 都有稳定结果；成功事件关联 actor、Policy、ChangeSet、provenance，无权请求保留最小安全审计。
- 回滚创建新受控转换，不覆盖历史。永久删除不属于状态机，未来必须有影响预览、显式高风险授权、依赖/保留检查、导出选择、审计和可恢复期；契约缺失时 fail closed。
- 私有记忆、提示词、会话、凭据、用户身份和受保护原件不得进入状态、fixtures、诊断、差分输出或默认工程包。

### 导出、导入与兼容

默认开放工程包不包含 authority-local operational state。未来显式导出只读生命周期快照时须排除 authority 身份、策略正文、lease、会话、资源、私有记忆和凭据。导入只能作为证据读取，不能直接 active；目标域重新映射 authority、验证 ProfileRef，并经新 Policy/ChangeSet 创建本地 dormant 状态。来源 active 不携带活性或权限，不恢复来源会话、epoch 或任务。ID/引用冲突不得静默合并，remap 与来源链由 ProjectPackage/ProvenanceRecord 定义。

## 替代方案

### A. 状态放入 AgentProfile

对象少但每次召唤都改身份，污染 Profile 且违反 ADR-0008，不采用。

### B. 每次召唤创建短期 Agent

会话隔离直观，但无法恢复同一长期个体，记忆、证据与关系分裂，不采用。

### C. 每项目或每会话一份 RuntimeState（已选择）

用户于 2026-08-27 选择本方案。同一长期 Agent 可在多个明确上下文独立 active/dormant/archived；局部状态的唯一键、CAS、审计与 fencing 均留在该上下文。全局 aggregate 只读且仅由调用者已获授权的局部状态投影派生；它不替代 ProjectAssignment、会话、权限或状态写入，也不让“关闭全部”成为隐式操作。

### D. 控制域内每个长期 Agent 一份 RuntimeState（未采用）

该方案便于得到唯一全局唤醒状态，但无法表达同一长期 Agent 在不同工程或会话同时保持不同可参与性；它与已选择的用户管理方式不符。

### E. 只用 active 布尔值

无法区分关闭/封存，也没有 revision、幂等、rebind、fencing，不采用。

## 迁移与发布

1. 产品负责人已于 2026-08-27 选择方案 C 并接受本 RFC；后续 ADR 必须固化局部状态与只读 aggregate 的边界。
2. 接受后创建 ADR，再拆 contract Issue。
3. 先交付 schema、诊断、fixtures、lock、无副作用 verifier；审查后实现双语言消费者和差分测试。
4. 再实现 durable CAS、idempotency journal、ChangeSet、Policy 和 epoch fencing，feature flag 默认关闭。
5. staging 先 dry-run/影子预演，再开放单 Agent summon/close，最后 archive/restore、rebind、批量和 UI/快捷键。

可观测性记录 version、operation、旧/新 status、revision、epoch、结果、诊断、延迟和恢复次数，不记录 persona、记忆、提示词、凭据、模型正文或私有资料。

回滚先关闭写入 flag，保留只读。已提交状态通过新获授权补偿转换回安全 dormant，不覆盖历史。较新字段保持 opaque 只读，旧消费者禁止写入。发现 epoch fencing 缺陷时冻结全部状态写入与副作用执行，不能只回滚 UI。

## 测试计划

1. 一个/N 个 Agent 的 Profile、局部 state、revision、epoch 独立；同一 Agent 在两个不同 runtime_context_ref 中、或相同 context 而不同 authority_scope_ref 中，可同时具有不同状态，且各处 CAS/epoch/lease 互不影响。
2. Profile 在某局部上下文无状态与该上下文 dormant 区分；创建默认 dormant，且不改变其在其他上下文的状态。
3. 合法链 `dormant → active → dormant → archived → dormant → active` 的 revision/epoch 正确。
4. 直接 active↔archived、非法 rebind、跨 ID、deleted 被拒绝。
5. 新 Profile revision 不自动 rebind；dormant 显式 rebind 可审计且不改 epoch。
6. 幂等重放、同 request 不同 payload、stale expected state 和 `no_change` 语义准确；覆盖 summon(active)、close(dormant)、archive(archived)、restore(dormant) 和 same-ref rebind。
7. summon/archive、close/rebind、restore/archive 并发只有一个 CAS 成功。
8. 每次副作用 admission 与 commit 均原子重验 active+epoch；close 后旧 lease 无副作用权，清理失败不恢复 authority，再次 summon 使用更大 epoch。
9. 转换/rebind 不删除或改写 Profile、记忆、证据、模型、团队、关系、项目对象。
10. persona、角色、能力、来源、信任和 active 不产生权限/模型调用。
11. 未知 major 拒绝；较新同 major 只读但禁止写入。
12. 默认导出排除 authority-local state；局部快照导入不自动 active；冲突不静默合并；aggregate 不被导出为可写事实，且 aggregate fixture/summary 只能使用已授权的合成局部投影集，不能泄露无权上下文。
13. 在预演、状态、审计、清理阶段注入崩溃，恢复后只有一个权威状态/幂等结果。
14. 模拟会话无法终止和网络分区，证明 epoch fencing 阻断旧副作用。
15. Policy 缺失、ChangeSet 未批准、Profile 不完整、CAS/审计失败均 fail closed。
16. Python/TypeScript 对 fixtures、诊断、summary、plan 一致并在 Windows/Linux CI 运行；aggregate 的可见性过滤、空集和无权上下文不得暴露也必须逐字段一致。

## 已接受的产品决定

产品负责人于 2026-08-27 选择方案 C：`AgentRuntimeState` 的权威记录按 `(authority_scope_ref, runtime_context_ref, AgentProfile.id)` 局部唯一；同一长期 Agent 可在不同项目或会话上下文独立 active、dormant 或 archived。全局 aggregate 是仅由控制平面显式提供的已授权局部投影集派生的只读视图，不具有 revision、epoch、lease、权限或写入权，也不得暴露无权上下文。

其余安全选择为：创建 dormant；active/archived 必经 dormant；rebind 仅 dormant；导入不自动 active；删除独立高风险。

## 决定

本 RFC 已接受。下一步创建 ADR，随后拆分机器契约、双语言只读消费者、控制平面写入与 IDE 召唤体验 Issues；在这些独立 Issue 完成前，本 RFC 不实现状态切换。
