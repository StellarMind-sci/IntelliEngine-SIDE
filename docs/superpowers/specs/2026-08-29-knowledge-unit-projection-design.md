# KnowledgeUnit 工程投影与可信引用设计

## 目标

交付一个只读的 KnowledgeUnit 工程投影：同一工程中的多个知识单元可按固定版本组织，系统能够展示前置关系、缺失证据、CognitiveNode 变化的影响范围，以及受影响的 Thoughtflow 步骤。

该能力服务于“在工程中学习”。它解释当前工程需要补什么证据、哪些步骤会被影响，而不是提供笔记、课程页面、刷题、个人掌握百分比或自动推荐。

## 已有基础与问题

KnowledgeUnit 1.0.0 已固定概念边界、学习目标、前置单元、节点绑定、行为、验证、掌握判据和来源引用；Python 与 TypeScript 都提供只读校验。Thoughtflow 1.0.0 固定引用 KnowledgeUnit，并以 reference snapshot 校验 operation 的 behavior。

当前缺口有两类：

1. KnowledgeUnit 只能逐个校验，不能形成项目级前置图、证据缺口和反向影响视图。
2. Thoughtflow 两套运行时没有落实机器 verifier 已有的规则：available KnowledgeUnit 的 `document.id` 与 `document.revision` 必须精确匹配 snapshot `ref`。错误文档因此可能被 operation 使用。

## 范围

本阶段新增或修复以下只读能力：

- 强化 KnowledgeUnit 双语言运行时的输入资源上限，保证运行时不把超过契约 `knowledge_unit_jcs_bytes=1048576` 的单元报告为有效。
- 令 Thoughtflow Python 和 TypeScript runtime 与已有机器 verifier 一致：available KnowledgeUnit document 的固定 `(id, revision)` 必须匹配对应 snapshot ref。
- 在 `packages/knowledge-units` 中增加项目投影 API。它校验一组 KnowledgeUnit 文档后，计算前置关系、缺失前置、跨单元环、证据缺口、节点直接关联和反向影响闭包。
- 在 `packages/thoughtflow` 中增加一个只读适配器：把 Thoughtflow 的 KnowledgeUnitRef 使用点与投影中的 `blocked` / `needs_evidence` 状态对应，输出每个受影响 step 的最小原因和工程建议。
- 以“一元一次方程”扩展成至少两个相关知识单元的数学工程样例，证明先修缺失、补足证据和节点变更会产生确定的 KnowledgeUnit 与 Thoughtflow 影响结果。

## 非目标

- 不改写 KnowledgeUnit、Thoughtflow、CognitiveNode、ProvenanceRecord 或 Agent 1.0.0 已发布 schema/lock。
- 不新增用户持久化状态、个人掌握百分比、数据库、文件写入、网络调用、模型调用或真实执行。
- 不授予 behavior capability，不接入 ControlPolicy、ChangeSet 或 RuntimeKernel。
- 不把当前字符串形式的 `provenance_refs` 重新定义为 ProvenanceRecord 公共引用。
- 不创造独立“学习模式”、课程页或刷题功能。

## 架构

### KnowledgeUnit Project Projection

Python API：

```python
project_knowledge(units, available_node_refs, evidence_node_refs, contract_root) -> dict
```

TypeScript API：

```ts
projectKnowledge(units, availableNodeRefs, evidenceNodeRefs, contractRoot): Record<string, unknown>
```

`units` 是同一工程已取得的不可变 KnowledgeUnit 文档；`available_node_refs` 是可用于结构校验的已知 CognitiveNodeRef 集合；`evidence_node_refs` 是当前工程已经提供验证或掌握证据的 CognitiveNodeRef 集合。后者只能用于判断项目证据是否充分，不能表示个人掌握状态。

投影按 unsigned UTF-8 顺序输出：

```json
{
  "object_result": "valid | invalid",
  "operation_outcome": "succeeded",
  "issues": [{"code":"knowledge_project.*","path":"/...","severity":"error"}],
  "units": [{
    "ref":{"id":"...","revision":1},
    "status":"ready | blocked | needs_evidence",
    "missing_prerequisite_refs": [],
    "missing_evidence_node_refs": []
  }],
  "node_dependents": [{"node_ref":{"id":"...","revision":1},"unit_refs":[]}],
  "unit_dependents": [{"unit_ref":{"id":"...","revision":1},"dependent_unit_refs":[]}]
}
```

`invalid` 表示输入不满足投影前提，例如单元本身无效、重复固定引用、跨单元前置环或 `evidence_node_refs` 不规范。缺少工程内未载入的前置单元是可解释的 `blocked`，不是格式错误。缺少验证或掌握证据是 `needs_evidence`，不是个人失败或单元无效。

每个节点与单元之间的关系来自 KnowledgeUnit 已有的 focus、target、binding、behavior、validation 和 mastery 引用；投影不复制节点内容。

### Thoughtflow Impact Adapter

Python API：

```python
project_knowledge_impacts(flow, projection) -> dict
```

TypeScript API：

```ts
projectKnowledgeImpacts(flow: unknown, projection: unknown): Record<string, unknown>
```

适配器只读取已经通过 Thoughtflow graph/reference 校验的 flow 和有效 KnowledgeUnit projection。它枚举使用非 `ready` KnowledgeUnitRef 的步骤，并为每个步骤输出固定 `step_id`、`knowledge_unit_ref`、状态和最小原因列表。所有受影响步骤按 `step_id` 的 unsigned UTF-8 顺序输出；同一 step 的原因按 KnowledgeUnitRef 顺序输出。

适配器不评估自然语言条件、不改变图、不写回投影，不把 `needs_evidence` 当作 verification outcome，也不执行 operation。

### 可信引用修复

两套 Thoughtflow runtime 在 `validate_references` / `validateReferences` 中必须对每个 `object_result="available"` KnowledgeUnit snapshot entry 验证：

```text
document.id == ref.id && document.revision == ref.revision
```

任何不匹配返回已有的 `thoughtflow.dangling_reference`，路径指向对应 `/knowledge_unit_refs/<index>`。这是既有机器 verifier 的语义收口，不是公共契约变更。

### 资源与版本边界

KnowledgeUnit runtime 在结构校验前后以 JCS UTF-8 字节数核验 `knowledge_unit_jcs_bytes`。大于 1,048,576 字节的结构有效单元返回封闭的 `not_evaluated + resource_exhausted` 结果；大小恰好等于限制允许继续校验。

本阶段不改变现有版本兼容语义，也不改变已发布 validation-result schema。固定版本的追踪继续由现有 `(id, revision)` 引用承担。

## 数据流

```text
不可变 KnowledgeUnit 文档 + 已知节点 + 当前证据节点
  -> 单元只读校验
  -> 项目投影（依赖 / 证据 / 反向影响）
  -> 已校验 Thoughtflow
  -> 受影响步骤和补证据提示
```

任何写入、执行、Agent 自动提交或运行时授权都在此数据流之外。

## 测试与验收

- 每个新增或修复行为先以 Python、TypeScript 的真实运行时测试写出 RED，再以最小实现转绿。
- 两语言项目投影对同一数学样例输出逐字段一致；差分测试要覆盖前置缺失、前置环、证据缺失、节点反向影响和非规范 evidence 输入。
- Thoughtflow identity 回归必须先证明现有 runtime 错误接受错配 document，再证明 Python/TypeScript 都与 verifier 一样拒绝。
- KnowledgeUnit 资源边界覆盖 1,048,575、1,048,576、1,048,577 JCS 字节；运行时结果必须符合 validation-result 已有状态对。
- 运行 KnowledgeUnit、Thoughtflow、CognitiveNode 直接回归及 `python scripts/verify_governance.py`。
- 每张任务卡只修改批准目录；不产生用户数据或外部副作用。

## 风险与回滚

投影是可重新计算的只读派生物，不保存数据库状态。任一任务可通过 revert 回退，不需要迁移或数据恢复。

最大风险是把工程证据误写成个人掌握或执行授权；接口明确把证据限定为当前工程的可用节点，并将状态限制为 `ready`、`blocked`、`needs_evidence`。任何需要执行、权限、持久化或个人学习档案的扩展必须另开高风险任务。
