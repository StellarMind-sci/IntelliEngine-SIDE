# RFC-003：Thoughtflow v1 思维链公共契约

- 状态：已接受
- 负责人：StellarMind-sci
- 创建日期：2026-08-24
- 关联 Issues：[GitHub Issue #32](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/32)

## 问题

SIDE 已经能够表示和校验固定版本的 CognitiveNode 与 KnowledgeUnit，但尚无公共结构把目标、
显式工程推理、知识依赖、行为声明、条件分支、验证反馈和迭代组织成一个可编辑、可检查的工程流程。
如果 UI、Agent、数学插件和运行时各自发明“思维链”，同一工程会出现不兼容的节点、边、循环和
执行语义，也可能让自然语言步骤或行为声明绕过控制平面直接产生副作用。

本 RFC 中的 Thoughtflow 是用户可见、可编辑、可版本化的工程推理与控制图。它不保存、要求或
暴露模型提供商不可见的内部推理过程，也不把聊天记录当作工程事实。用户或 Agent 只有主动写入
图中的目标、分析、决定、证据和验证，才成为 Thoughtflow 内容。

## 目标与非目标

### 目标

1. 定义一个可移植的 Thoughtflow v1 封套、固定版本身份、步骤、转移和外部引用模型。
2. 表达目标、分析、操作声明、决策、验证、产物和迭代七类显式工程步骤。
3. 表达顺序、数据依赖、条件分支、验证反馈和受约束循环，同时拒绝任意或无界循环。
4. 固定引用 CognitiveNode、KnowledgeUnit 及 KnowledgeUnit 中声明的 behavior，而不复制其内容。
5. 支持无副作用的校验、图投影、可达性分析和候选下一步模拟。
6. 为后续 ChangeSet、ControlPolicy、RuntimeKernel、代码投影和 Agent 协作留下明确边界。
7. 提供语言无关机器工件、稳定诊断和至少两个独立只读消费者所需的确定语义。

### 非目标

- 不记录或推断模型隐藏的 chain-of-thought，不把聊天原文自动视为工程步骤。
- 不在 Thoughtflow v1 中执行 behavior、代码、文件、网络、设备、模型调用或外部工具。
- 不定义权限授予、信任等级、审批、提交、撤销、运行账本或执行结果；这些属于 ControlPolicy、
  ChangeSet 和 RuntimeKernel。
- 不把文件路径、行号、IDE 编辑器位置或供应商私有会话 ID 固化为可移植身份。
- 不定义 UI 布局、节点坐标、颜色、折叠状态、个人阅读进度或个人掌握状态。
- 不在本 RFC 中定义 ProjectPackage、AgentProfile、ProvenanceRecord 或代码投影契约的字段。

## 提案

### 所有权与分层

`packages/thoughtflow` 拥有 Thoughtflow 封套、步骤/转移种类、图不变量、固定引用、只读模拟和
投影规则，但不拥有学科知识、行为实现、权限策略、运行时副作用或 IDE 布局。

- `packages/cognitive-ir` 拥有 `CognitiveNodeRef` 的身份和版本语义。
- `packages/knowledge-units` 拥有 `KnowledgeUnitRef`、知识边界、行为声明和验证/掌握标准。
- `packages/thoughtflow` 只引用上述固定版本对象，并决定它们如何参与显式工程流程。
- `packages/control-plane` 与后续 ChangeSet/ControlPolicy 决定谁可以提议、批准和提交修改。
- RuntimeKernel 决定行为如何执行并产生可审计结果；Thoughtflow 不授予或实现执行能力。

### Thoughtflow 封套

Thoughtflow v1 的规范对象至少包含：

- `contract_version`：canonical SemVer；v1 首版为 `1.0.0`。
- `id`：canonical lowercase UUID；producer 应生成 UUIDv7。
- `revision`：从 1 开始的安全整数；`(id, revision)` 唯一表示不可变版本。
- `title`：面向用户的非空标题。
- `entry_step_id`：唯一入口步骤。
- `steps`：按 `step_id` 的 unsigned UTF-8 bytes 规范排序的非空集合。
- `transitions`：按稳定复合键规范排序的集合。
- `knowledge_unit_refs`：本图允许使用的固定 `KnowledgeUnitRef` 闭包。
- `cognitive_node_refs`：本图允许使用的固定 `CognitiveNodeRef` 闭包。
- `provenance_refs`：非空、规范排序的来源引用集合。

除 `revision` 外，任何规范字段变化都必须创建更高 revision；不得原地覆盖。只改变 revision 而
不改变其他规范内容也是无效转换。运行游标、迭代计数、已选分支、执行输出、节点坐标和个人 UI
状态不属于 Thoughtflow 定义版本，后续由运行记录、ChangeSet 或体验层拥有。

单对象校验只能证明当前封套与图自洽，不能凭空证明 revision 演进合法。后续机器契约必须提供独立的
`validate_revision_transition(previous, candidate)` 只读比较模式，验证同一 ID、revision 单调递增、
内容确实变化。历史存储是否被改写不能由两个对象证明，必须由后续不可变存储与 ChangeSet 审计保证；
真正提交仍由 ChangeSet/ControlPlane 负责。


### 步骤

每个步骤至少包含 `step_id`、`kind`、`title`、`description`、`knowledge_unit_refs` 和
`cognitive_node_refs`。步骤引用必须是顶层闭包的子集，且固定到具体 revision。

`kind` 是闭合集合：

1. `goal`：声明当前流程要达到或证明的目标。
2. `analysis`：记录用户或 Agent 主动外化的假设、分解、比较或解释。
3. `operation`：引用一个已声明 behavior 的惰性操作提议；自身不执行。
4. `decision`：声明需要在多个显式分支之间选择的决策点。
5. `verification`：描述验证对象、接受条件和证据引用。
6. `artifact`：代表流程中产生或消费的逻辑产物，不持有文件路径或 IDE 行号。
7. `iteration`：唯一可以控制循环返回与退出的显式迭代控制器。

`goal` 必须包含非空 `success_statement`，说明何种可观察事实代表目标达成。`verification` 必须包含
非空 `acceptance_statement` 和至少一个 `evidence_node_refs`；证据引用必须同时出现在该步骤和
顶层 CognitiveNodeRef 闭包中。`artifact` 必须包含流程内稳定且非空的 `artifact_key`，供后续
投影契约建立映射，但它不是文件路径、存储位置或全局对象身份。

顶层 KnowledgeUnitRef/CognitiveNodeRef 闭包必须恰好等于所有步骤、behavior_ref 和验证证据使用
的引用并集；既不允许漏项，也不允许携带未使用引用。这样可以避免在合法图中夹带与流程无关的数据，
并让导出和审计只处理实际依赖。


`operation` 必须包含 `behavior_ref`，由固定 `KnowledgeUnitRef` 与该知识单元内的 `behavior_id`
组成。该知识单元必须存在于顶层闭包，behavior 必须存在，且步骤引用必须覆盖 behavior 的输入与
输出 CognitiveNodeRef。引用 behavior 只证明“声明可用”，不证明权限获批或执行成功。

`iteration` 必须包含：

- `max_iterations`：1 至 10,000 的整数上限；
- `exit_condition`：非空、面向用户的显式退出条件说明；
- `verification_step_ids`：至少一个固定的 verification 步骤，用来判定继续或退出所需的证据。

退出条件在 v1 中是声明数据，不是可执行表达式。只读消费者可以报告候选路径，但不能根据自然语言
条件自动产生执行结论。

### 转移与分支

每条转移至少包含 `transition_id`、`kind`、`from_step_id` 和 `to_step_id`。首尾步骤必须存在，
且不得自环。`kind` 是闭合集合：

- `sequence`：普通先后关系。
- `data_dependency`：目标步骤依赖来源步骤声明的认知对象或产物。
- `branch`：decision 或 iteration 控制器的显式条件分支。
- `verification_feedback`：verification 的通过、失败或待补证据反馈。
- `loop`：唯一允许闭合有向环的返回边。

`branch` 必须包含非空 `branch_label` 和 `condition_statement`；同一来源的 label 唯一，并且必须
恰有一个 `is_default=true` 的分支，供条件无法判定时安全停留或交给用户选择。默认分支不代表授权。

`verification_feedback` 与 `loop` 都必须声明 `outcome`。`verification_feedback` 允许
`passed`、`failed` 或 `needs_evidence`；`loop` 只允许 `failed` 或 `needs_evidence`，
不能把验证通过映射为自动重试。它们只描述未来结果如何连接流程，不伪造当前验证结果。

`branch` 只能由 decision 或 iteration 发出；这两类步骤必须至少有两条 branch，所有 branch label
唯一且恰有一个默认分支。它们不得发出 sequence 或 verification_feedback 控制转移，但可以声明
data_dependency。默认分支只是显式候选，条件未判定时只读模拟仍返回“需要外部决定”，不得自动前进。

`verification_feedback` 与 `loop` 只能由 verification 发出；同一来源在两种转移中的 outcome
必须联合唯一。每个 verification 至少有一条 verification_feedback；作为 loop 来源时，还必须有
至少一条非 loop feedback 提供退出路径。

`loop` 的来源 verification 必须列在目标 iteration 的 `verification_step_ids` 中。

### 受约束循环

Thoughtflow v1 采用受约束循环，而不是纯 DAG 或任意有向图：

1. 删除所有 `loop` 转移后，剩余图必须是有向无环图。
2. 每条 `loop` 转移的目标必须是 `iteration` 步骤。
3. loop 来源必须是 verification，且属于目标 iteration 声明的验证步骤。
4. 每个包含循环的强连通分量必须恰好包含一个 iteration 控制器，并至少包含一个 verification 步骤。
5. loop 来源必须能从其 iteration 控制器通过非 loop 转移到达，禁止跨越无关子图回跳。
6. iteration 必须具有 `max_iterations`、退出条件和验证步骤；无界循环一律拒绝。
7. 只读模拟最多展开到声明上限，并返回候选路径或“需要外部决定”，不得执行 operation。

这允许表达“提出方案 → 实验/计算 → 验证失败 → 修正 → 再验证”的真实工程过程，同时保证循环
可以被识别、解释、静态限制和安全停止。

### 图完整性与可达性

- `entry_step_id` 必须存在；图中至少有一个 goal 和一个 verification。
- 删除 loop 后，所有步骤必须从入口经 sequence、branch 或 verification_feedback 控制转移可达；
  data_dependency 不建立控制可达性，不能用来掩盖孤立步骤。
- 删除 loop 后，入口是唯一没有入站控制转移的步骤；其余步骤至少有一条入站控制转移。
- 顶层引用闭包与步骤实际使用引用必须完全相等，不接受未使用或未声明引用。
- 同一集合内的步骤、转移、引用、label、outcome 和局部标识必须唯一并使用规范排序。
- goal、decision、verification 和 iteration 的结构要求必须由机器契约逐项校验。
- 不允许悬空 CognitiveNodeRef、KnowledgeUnitRef、behavior_ref、步骤引用或验证步骤引用。
- 固定引用对象必须达到其所属契约要求的只读可解释状态；`opaque`、未知 major 或无法验证的引用
  不得驱动 branch、loop 或 operation，只能以不可解释引用保留并返回稳定诊断。
- 图合法不等于可执行、已授权、已验证或已完成。对象结论与操作结论继续保持正交。

### 只读能力与数据流

校验分为两个明确阶段：transport/graph 校验只消费 Thoughtflow 原始 bytes，不查询注册表；reference
校验显式消费调用方提供的不可变 KnowledgeUnit 文档集合与 CognitiveNodeRef 可用集合。
`ReferenceSnapshot` 是调用方显式提供的只读校验输入，不是 Thoughtflow 持久化字段。每个条目固定
一个 CognitiveNodeRef 或 KnowledgeUnitRef，并携带该对象的 `object_result`；只有需要检查
behavior 的可解释 KnowledgeUnit 条目才携带规范 document。snapshot 禁止路径、URL、回调、隐式
registry 或“使用最新版本”语义，所有引用都必须精确到 revision。


- transport/graph 缺陷返回 `object_result=invalid + operation_outcome=succeeded`。
- 引用快照缺失、不可验证或外部查询失败返回
  `object_result=not_evaluated + operation_outcome=indeterminate`，不能伪装成 invalid。
- 快照完整但固定引用或 behavior 不存在，返回
  `object_result=invalid + operation_outcome=succeeded` 及稳定 dangling/unknown 诊断。
- 引用对象为 opaque 或仅 compatible_read 时，图可保留，但不得驱动 branch、loop 或 operation；
  reference 结果保持 `not_evaluated + indeterminate`，并指出最小阻塞路径。

只读模拟只消费已通过 reference 校验的对象。遇到自然语言 branch、verification outcome 或
iteration exit condition 时返回“需要外部决定”及候选后继，不自行猜测条件真假。

首个运行时只提供：原始 JSON 解析、结构/引用校验、可达性与循环分析、确定性图摘要、指定步骤的
候选后继查询，以及在不选择自然语言条件的情况下进行有界路径模拟。

数据流为：

`原始 Thoughtflow bytes + 固定引用快照 → transport 校验 → 图/引用校验 → 只读投影或候选路径`

任何修改、反向代码投影或运行请求只能先产生后续契约定义的变更意图。代码修改影响 Thoughtflow、
或 Thoughtflow 间接控制代码的双向能力，必须经 ProjectPackage/代码投影、ChangeSet、ControlPolicy
和 RuntimeKernel 的版本化接口完成；不得把文件写入隐藏进本契约的 operation 或 artifact。

## 公共接口

后续契约 Issue 将在 `packages/thoughtflow` 提供：

- `Thoughtflow` 与 `ThoughtflowRef` JSON Schema；
- `ThoughtflowStep`、`ThoughtflowTransition` 和 `KnowledgeBehaviorRef` 的封闭结构；
- validation result、稳定 `thoughtflow.*` 诊断目录、语言无关 fixtures 和 JCS lock；
- `ReferenceSnapshot` 只读输入 schema，但不把 snapshot 写入 Thoughtflow 对象；
- Python 的 `parse_and_validate_transport`、`validate_references`、`validate_revision_transition`、
  `graph_summary`、`next_candidates` 和 `simulate_bounded`，以及 TypeScript 对等 camelCase API；
- 两种语言各自独立的 fixture CLI；
- 双消费者 differential runner。

M1 工件遵循 ADR-0005/0006：I-JSON-compatible 原始输入、JCS、canonical SemVer、安全整数、
unsigned UTF-8 集合顺序、离线 `$ref`、封闭结果状态和确定性诊断。未知 contract major 拒绝；同一
major 的较新 minor 只允许无副作用兼容读取，不能驱动 branch、loop、operation 或写入。

本 RFC 不定义代码定位器、执行 trace、权限结论、ChangeSet 或运行结果结构，因此这些后续接口
可以独立演进，而不改变 Thoughtflow v1 图定义的身份。

## 安全、溯源与控制策略

- 所有标题、说明、条件、引用和 opaque 数据都视为不可信输入；校验过程确定、离线且无副作用。
- operation、loop、decision 和 verification 只是声明，不授予 capability、权限、信任或工具访问。
- 高信任 Agent、知识单元作者或 Thoughtflow 所有者都不能绕过平台安全上限。
- provenance_refs 强制非空；创建、派生、重构、代码投影和回滚的完整关系由 ProvenanceRecord
  后续契约拥有。
- 诊断和日志只记录流程/步骤/转移 ID、版本、状态、错误码和最小路径，不默认记录敏感说明、
  CognitiveNode data、原件或用户私有 Agent 记忆。
- 任何未来副作用都必须经过 ControlPolicy 逐级授权、ChangeSet 预演与审查、RuntimeKernel 限制、
  审计和可回滚提交；依赖接口缺失或结论无法判定时 fail closed。
- 回滚不改写历史 revision，而是恢复到已知图内容并创建可追踪的新 revision/ChangeSet。

## 替代方案

### A. 纯 DAG

优点是校验和静态分析最简单，不存在无限循环。缺点是不能自然表达实验失败、调试、模型校准、
反复验证和能力迭代，只能复制展开节点或把关键过程隐藏在单个 operation 中，因此不采用。

### B. 任意有向图

优点是表达自由、实现初期字段少。缺点是循环不可解释、无法静态限制，可能形成无界模拟，且 UI、
Agent 和运行时会各自猜测循环入口与退出条件，因此不采用。

### C. 受约束循环（推荐）

普通路径保持 DAG，只有显式 iteration + loop 可以形成环，并强制上限、退出说明和验证节点。
它保留真实工程迭代，又能确定性校验和安全停止，因此采用。

### D. 把 Thoughtflow 当成聊天/模型推理日志

实现成本低，但不可编辑、不可验证、与模型提供商绑定，并可能诱导收集隐藏推理或敏感上下文，
不符合开放工程格式和仓库长期事实原则，因此不采用。

## 迁移与发布

1. 本 RFC 经产品负责人审阅接受后，创建 ADR 固化选择。
2. 独立 contract Issue 实现 1.0.0 schema、诊断、fixtures、lock 和只读 verifier。
3. 契约独立审查并合并后，独立 runtime Issue 实现 Python/TypeScript 消费者与差分验证。
4. 首版只以只读方式进入 M1；不开放写入、执行、Agent 自动提交或代码同步。
5. 后续 ChangeSet、ControlPolicy、RuntimeKernel 和代码投影契约完成后，再通过新 Issue 增加受控集成。

可观测性只输出合成 case ID、版本、图规模、状态、诊断 code 和最小差异路径。回滚契约/消费者 PR
即可恢复上一主分支；已发布 1.x 工件不得原地改写，缺陷通过新版本和兼容期修复。

## 测试计划

机器契约至少包含以下真实产品场景：

1. 一元一次方程：目标 → 分析 → 符号变换 operation → verification → 通过反馈。
2. 验证失败后通过 iteration 返回分析步骤，并在上限内再次验证。
3. 悬空步骤、CognitiveNodeRef、KnowledgeUnitRef 或 behavior_ref 被拒绝。
4. operation 引用了不存在的 behavior 或未覆盖 behavior 输入/输出节点时被拒绝。
5. decision 缺少条件、重复 label、缺少唯一默认分支或被模拟器自动选择时被拒绝。
6. verification/loop outcome 重复、通过后循环或循环不存在非 loop 退出路径时被拒绝。
7. 普通边形成环、loop 未指向 iteration、循环缺少 verification 或无上限时被拒绝。
8. 孤立/不可达步骤、仅由 data_dependency 伪装可达、非法入口、自环和重复 ID 被拒绝。
9. 未知 contract major、重复 JSON key、非法 UTF-8、非规范集合顺序和非法状态对被拒绝。
10. 引用快照缺失、opaque、compatible_read 与真实 dangling 引用产生各自固定结果状态。
11. revision 未变化、只改 revision、回退 revision 或改写历史内容被 transition 模式拒绝。
12. fixture expected 被篡改不能改变消费者实际计算结果。
13. Python 与 TypeScript 对全部机器结果、图摘要和候选后继逐字段一致。

契约、消费者和 differential CI 必须在 Linux 与 Windows 运行；Issue #22 完成前只宣称应用层只读
与确定性验证，不宣称任意子进程获得 OS 级文件/网络隔离，也不开放 portable 写入或执行。

## 决定

产品负责人于 2026-08-24 接受本 RFC，并选择“受约束循环”方案：Thoughtflow v1 允许由验证失败或
证据不足触发、具有唯一控制器和明确迭代上限的循环；移除 `loop` 边后，控制图必须保持无环。

同时确认以下边界：Thoughtflow 只保存用户或 Agent 主动写入的显式工程推理，不保存模型隐藏的
chain-of-thought；`operation` 和 behavior 仅声明意图，不产生代码、文件、网络、设备、模型或工具
副作用；引用必须固定版本并由显式快照校验；分支不由模拟器自动替用户选择。

后续由独立 ADR 固化该决定，并将机器契约与 Python/TypeScript 只读运行时拆成独立 Issues 交付。
