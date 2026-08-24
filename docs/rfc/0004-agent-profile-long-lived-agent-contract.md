# RFC-004：AgentProfile v1 与长期 Agent 个体契约

- 状态：已接受
- 负责人：StellarMind-sci
- 创建日期：2026-08-24
- 关联 Issues：[GitHub Issue #40](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/40)

## 问题

SIDE 的 Agent 不是一次性聊天窗口或固定角色模板。用户应能像召唤 NPC 一样创建一个或 N 个长期个体；每个个体有自己的设定、工作风格、目标和成长轨迹，可以暂时关闭后恢复，并能在不同工程、团队和模型之间继续存在。

若身份档案、私有记忆、当前会话、团队角色、模型供应商和权限策略被保存在同一个对象中，换模型、退出项目、关闭会话或导出工程都会意外改变“这个 Agent 是谁”，还可能把用户私有记忆、密钥或权限带入开放工程包。反过来，若 AgentProfile 只是一份可复制模板，则无法表达同一长期个体的连续身份、成长和可恢复性。

M1 因此需要一个可移植、可版本化、无副作用的 `AgentProfile` 公共契约，先固定长期个体的身份边界，让未来的记忆、团队、控制平面、模型网关和项目格式可以独立演进。

## 目标与非目标

### 目标

1. 定义稳定的 `AgentProfile` v1 封套和 `AgentProfileRef`，用于标识一个长期 Agent 个体及其固定修订。
2. 支持用户自定义人格设定、目标、工作风格、声明能力和协作偏好，但不把教师、学生、科学导师或用户分身固化成封闭模板类别。
3. 规定 Profile 修订、成长证据、运行时状态、记忆、团队关系、模型绑定和控制策略之间的分层边界。
4. 固定 `active`、`dormant`、`archived` 三种运行状态的产品语义；永久删除独立于普通状态转换。
5. 提供语言无关机器契约、稳定诊断、Python 与 TypeScript 独立只读消费者及差分验证所需的确定语义。
6. 保持模型供应商可替换，保持私有长期记忆默认不进入开放工程包，并让所有副作用继续服从 ControlPolicy、ChangeSet 与 RuntimeKernel。

### 非目标

- 不实现模型调用、提示词执行、工具调用、文件/网络/设备访问、自动提交或代码修改。
- 不定义 MemoryLedger 的存储、检索、摘要、遗忘或跨用户共享协议，也不把用户私有记忆放入 Profile。
- 不定义 AgentTeam、AgentRelation、ProjectAssignment、ControlPolicy、ChangeSet、ModelProvider、ProjectPackage、ProvenanceRecord 或 RuntimeKernel 的字段。
- 不把角色名称、人格文本、能力声明或 Agent 信任等级解释为权限、模型能力保证、身份认证或自动授权。
- 不定义 UI 外观、NPC 形象、聊天记录、供应商私有会话 ID、模型密钥、个人设备配置或真人协作。
- 不在 M1 提供 Profile 的持久化写入、状态切换、永久删除、记忆写入或团队调度；首版运行时只读。

## 提案

### 所有权与分层

`packages/agent-runtime` 拥有 `AgentProfile`、`AgentProfileRef`、Profile 的修订校验和只读投影，但不拥有模型提供商实现、权限决策、工程包导出、记忆内容或团队业务规则。

```text
AgentProfile（公开、可移植、可版本化的长期身份）
 ├─ AgentRuntimeState（当前 active / dormant / archived）
 ├─ MemoryLedger（用户私有长期记忆和可审查摘要）
 ├─ CapabilityEvidence（工程中的实际能力证据）
 ├─ ModelBinding（供应商无关的模型路由）
 ├─ ControlBinding（策略、授权、审计和 ChangeSet）
 └─ AgentTeam / AgentRelation / ProjectAssignment（团队、关系和分工）
```

下游对象通过固定 `AgentProfileRef(id, revision)` 指向 Profile；它们不是 Profile 的嵌套字段，也不能反向改写 Profile。这样一个 Agent 可以同时参与多个工程、在不同团队担任不同角色，并在替换模型、关闭会话或离开项目后保留自身身份。

- `packages/control-plane` 拥有谁可提出、批准、提交或回滚 Profile 修订、状态变化和能力推广。
- `packages/model-gateway` 拥有 `ModelBinding` 与模型能力/路由；Profile 不绑定供应商、模型名称或密钥。
- 未来 `MemoryLedger` 拥有私有记忆及其访问结论；开放工程包默认排除其内容。
- 未来 Agent 团队对象拥有角色、关系、项目分工、中心调度和群体讨论；Profile 只可表达协作偏好。
- `ProvenanceRecord` 与 `ProjectPackage` 分别拥有来源/派生和导出/导入的完整协议；Profile 只保存引用。

### AgentProfile 封套

`AgentProfile` v1 是长期身份的规范声明，至少包含以下字段：

- `contract_version`：canonical SemVer；v1 首版为 `1.0.0`。
- `id`：canonical lowercase UUID；producer 应生成 UUIDv7。它标识逻辑 Agent，不编码项目、角色、模型、权限或存储位置。
- `revision`：从 1 开始的安全整数；`(id, revision)` 唯一表示一个不可变 Profile 修订。
- `display_name`：非空、面向用户的显示名称，不要求全局唯一。
- `persona`：用户自定义的长期人格/定位声明，包括 `summary`、`principles` 与 `communication_style`。这些是可读描述，不是隐藏提示词、模型内部推理或访问控制规则。
- `goals`：非空、规范排序的长期目标集合；它们表达愿望和职责方向，不等同于当前项目任务或执行队列。
- `working_style`：显式的工作/解释偏好，例如偏向分解、反例检查、实验记录或教学引导；它不授予自主执行权。
- `declared_capabilities`：非空、规范排序的自我声明能力标签。标签只用于展示、匹配和用户选择；实际能力以独立 `CapabilityEvidence` 与控制策略结论为准。
- `collaboration_preferences`：希望如何与用户和其他 Agent 协作的声明，例如偏好讨论、分工或复核；它不保存当前团队成员、关系、角色或调度规则。
- `provenance_refs`：非空、去重且按 unsigned UTF-8 bytes 规范排序的字符串来源引用数组。用户直接创建的 Agent 也应有可记录的创建来源；具体 ProvenanceRecord 格式由其后续契约拥有。

封套不得包含：生命周期当前值、运行会话、聊天记录、私有记忆正文、记忆检索索引、模型/供应商/密钥、权限/信任级别、团队/关系/项目角色、当前任务、执行结果、设备路径或 UI 状态。

`AgentProfileRef` 固定为 `{ id, revision }`。任何消费方不得使用“最新 revision”、文件路径、显示名称或模型会话 ID 代替引用。Profile 创建后可以尚未被唤醒，也可以暂时没有任何团队、记忆、模型绑定或能力证据；这些缺失不使 Profile 无效。

### 修订与成长

除 `revision` 以外的任何 Profile 规范字段变化都必须创建更高 revision。只改变 revision 而不改变其他规范内容无效；回退 revision、改变逻辑 ID 或改写历史内容同样无效。机器契约必须提供纯函数 `validate_revision_transition(previous, candidate)`，只验证同 ID、revision 单调增加和内容确实变化；它不能凭空证明后端历史存储没有被覆盖。

Agent 的成长分成两个层次：

1. **观察到的成长**：运行时形成 `CapabilityEvidence`、项目产物、验证结果和受控记忆摘要。它们可以表明 Agent 已展现某种能力，但不会自动改写 Profile。
2. **身份设定的成长**：只有用户或获授权策略经 ChangeSet 审查、验证和提交后，才可把新的目标、工作风格、人格原则或声明能力写成新的 Profile revision。

这让 Agent 能长期学习和演化，同时防止一次错误推理、提示注入或短期会话漂移悄悄改变其长期身份。

### 生命周期与召唤

生命周期属于未来 `AgentRuntimeState`，不属于 Profile 修订内容。它必须引用一个精确的 `AgentProfileRef`，并使用以下闭合集合：

- `active`：Agent 已被唤醒，可在获授权范围内参与工程。
- `dormant`：Agent 已关闭，不主动参与工程；身份、设定、记忆、能力证据和关系均保留，可再次恢复。
- `archived`：Agent 长期封存，默认不参与搜索、调度或团队协作，但仍可恢复。

创建 Profile、召唤、休眠、封存和恢复均不得暗中改变 Profile 内容。永久删除不是普通状态：它必须由后续控制平面提供显式的高风险操作、影响预览、授权、保留/导出选择、审计和可恢复期；M1 不实现该操作。

### 只读能力与数据流

v1 的校验器只消费 AgentProfile 原始 JSON bytes 与调用方显式提供的固定引用快照；不查询模型服务、记忆库、团队目录、网络注册表或本地插件目录。

```text
原始 Profile bytes
  → transport 校验
  → Profile 结构和规范顺序校验
  → 显式 provenance 引用快照校验
  → 只读投影、固定引用或 revision-transition 结论
```

- transport 校验不查询外部系统；重复 JSON key、非法 UTF-8、未知 major、非规范集合顺序和非法字段返回稳定 `agent_profile.*` 诊断。
- provenance 快照缺失、不可读或版本不支持时，结论为 `not_evaluated + indeterminate`，不能伪装成 Profile 本身无效。
- 快照完整但固定来源不存在或不匹配时，结论为 `invalid + succeeded`，并给出最小稳定路径。
- 已通过校验的 Profile 仅可展示、搜索、固定引用和受控导出；不得因此调用模型、读取记忆、改变状态、加入团队、授予权限、执行代码或提交 ChangeSet。

首个运行时提供：原始 JSON 解析、结构校验、显式 provenance 引用校验、revision transition 校验、确定性摘要和独立 fixture CLI。Python 与 TypeScript 各自实现，任何差异阻断合并。

## 公共接口

后续契约 Issue 在 `packages/agent-runtime` 交付：

- `AgentProfile` 与 `AgentProfileRef` JSON Schema；
- `AgentProfileReferenceSnapshot` 只读输入 schema；它不是持久化 Profile 字段；
- validation result、稳定 `agent_profile.*` 诊断目录、语言无关 fixtures 和 JCS lock；
- Python 的 `parse_and_validate_transport`、`validate_references`、`validate_revision_transition` 与 `profile_summary`，以及 TypeScript 对等 camelCase API；
- 两种语言独立的 fixture CLI 与 differential runner。

M1 工件沿用 ADR-0005/0006 的可移植规则：I-JSON-compatible 输入、JCS、canonical SemVer、安全整数、unsigned UTF-8 规范排序、离线 `$ref`、封闭结果状态和确定性诊断。未知 contract major 拒绝；同 major 的较新 minor 只允许带版本提示的无副作用兼容读取，不可用于写入、状态切换、记忆访问、模型调用、团队调度或权限判断。

## 安全、溯源与控制策略

- Profile 中的所有字符串、声明能力、人格描述和 opaque 内容均视为不可信输入；校验过程确定、离线且无副作用。
- 人格、角色名称、能力声明、来源作者、Agent 信任等级或高质量能力证据均不自动授予模型、文件、网络、设备、项目写入或外部工具权限。平台安全上限优先于全局、项目、团队、Agent、节点和任务策略。
- 私有记忆、提示词、凭据、模型会话、用户身份和受保护原件不得进入 fixtures、诊断、差分输出或默认开放工程包；显式加密导出由未来 ProjectPackage 和控制平面共同决定。
- `provenance_refs` 强制非空；Profile 的创建、fork、成长、导入、导出和回滚来源关系由未来 ProvenanceRecord 与 ChangeSet 记录。
- 任何未来状态变化、成长提案、团队关系变更、模型绑定或实际执行都必须经 ControlPolicy 逐级授权、ChangeSet 预演与审查、RuntimeKernel 限制、审计和回滚；依赖结论缺失时 fail closed。
- 回滚不覆盖历史 Profile revision，而是恢复已知内容并以新 revision/ChangeSet 保留可追踪历史。

## 替代方案

### A. 一体化 Agent 文档

把身份、记忆、当前状态、团队、模型和权限全放入 AgentProfile。其优点是初始 schema 少、读取方便；缺点是私有数据和可移植数据混杂，关闭/换模型/退出团队会改变身份，跨工程并发修改冲突严重，因此不采用。

### B. 模板化 Agent

让 AgentProfile 只保存模板，每次召唤都生成短期运行实例。其优点是生命周期简单；缺点是无法保留同一长期个体的连续身份、记忆和成长轨迹，也不符合用户可随时关闭后恢复的产品方向，因此不采用。

### C. 分层长期个体

AgentProfile 固定可移植身份，运行时、记忆、能力证据、模型、控制和团队分别拥有独立边界。其代价是存在更多引用对象与未来契约；收益是 Agent 可以长期演化、跨工程协作、替换模型，并仍保持安全、可审查和可导出，因此采用。

## 迁移与发布

1. 本 RFC 已由产品负责人选择方案 C 并确认生命周期、成长和团队分层方向；下一项工作是创建 ADR。
2. ADR 合并后，以独立 contract Issue 发布 AgentProfile 1.0.0 的 schema、诊断、fixtures、lock 和只读 verifier。
3. 契约通过独立审查并合并后，再以独立 runtime Issue 实现 Python 与 TypeScript 消费者、CLI 和 differential runner。
4. M1 首版只读；Profile 写入、状态切换、记忆、团队、模型调用、自动提交和真实执行均保持关闭。
5. 后续 ProjectPackage、ProvenanceRecord、ControlPolicy、ChangeSet、ModelProvider 和 RuntimeKernel 分别就其自身字段与写入能力建立新 RFC/ADR，不得在 AgentProfile 1.0.0 中暗中追加。

已发布 1.x 工件不得原地改写。发现契约缺陷时，冻结受影响写入或导出能力，保留旧版本只读路径，通过新 RFC、替代 ADR 和显式新版本修复；消费者缺陷可回滚消费者或关闭功能开关，并把最小失败 case 留作回归。

可观测性只记录合成 case ID、contract/version、对象/操作结果、诊断 code、资源桶和最小 JSON Pointer；不得记录 persona 正文、记忆、提示词、凭据或模型会话。

## 测试计划

机器契约至少覆盖以下真实与负向场景：

1. 用户创建一个数学工程导师与多个独立协作 Agent；每个 Profile 有独立 ID、设定、目标和能力声明。
2. 教师、学生、科学导师和用户分身以用户自定义人格/目标表达，而非固定 role enum。
3. 缺少必填身份字段、空文本、重复能力、非规范排序、非法 UUID/revision/contract version 被拒绝。
4. 运行状态、模型 ID、密钥、私有记忆、团队成员、项目角色或权限字段被塞入 Profile 时被拒绝。
5. Profile 可在尚未唤醒、未绑定模型、没有记忆或没有团队时保持 valid。
6. 相同 ID 的 revision 增长且内容变化通过；只改 revision、回退 revision、变更 ID 或历史内容重写被拒绝。
7. CapabilityEvidence 或 MemoryLedger 发生变化不会改变同一 Profile revision；经合法 ChangeSet 的成长提案才产生新的 Profile revision。
8. provenance 快照缺失、不可读、未知版本和真实悬空来源产生不同的稳定结果，不能误报为对象无效。
9. 原始 JSON 的重复 key、非法 UTF-8、非法 Unicode、未知 major 和 expected 篡改均不能绕过实际校验。
10. Profile 的能力、人格、来源、信任或角色声明不能产生权限、模型调用、文件/网络访问、状态切换或 ChangeSet 提交。
11. Python 与 TypeScript 对全部机器 case、revision 结论和摘要逐字段一致，且分别不读取网络、进程、文件系统中契约根目录之外的内容。

契约、消费者和 differential CI 必须在 Linux 与 Windows 运行。Issue #22 完成前只宣称应用层只读与确定性验证，不宣称任意子进程获得 OS 级文件/网络隔离，也不开放 portable 写入或执行。

## 决定

产品负责人于 2026-08-24 选择“分层长期个体”方案：`AgentProfile` 是可版本化、可移植的长期身份锚点；私有记忆、当前运行状态、能力证据、模型绑定、控制策略以及团队/项目关系独立拥有。`active`、`dormant`、`archived` 是运行时状态，永久删除独立处理。

Profile 的成长只能经可审查、可回滚的 ChangeSet 创建新 revision，运行时不得自行改写人格、目标、工作风格或声明能力。v1 只提供语言无关的机器契约和双语言只读运行时；执行、写入、记忆、团队调度和模型调用留给后续的独立公共契约。

后续由 ADR 固化此决定，并将机器契约、Python/TypeScript 消费者、独立审查和跨语言集成拆为独立 Issues。
