# KnowledgeUnit 工程投影与可信引用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让工程能够只读解释 KnowledgeUnit 的依赖、证据和节点影响，并把非就绪知识单元精确映射到 Thoughtflow 步骤。

**Architecture:** 保持 KnowledgeUnit 1.0.0 文档不可变。`packages/knowledge-units` 新增双语言项目投影，在现有逐单元校验之上计算依赖和证据状态；`packages/thoughtflow` 仅把投影映射到步骤影响。修复现有 runtime 与机器 verifier 的引用身份漂移；不执行、写回或持久化任何对象。

**Tech Stack:** Python 3.12 标准库、Node 24 内建 test runner、JSON fixture、现有 Cognitive IR canonical JSON 工具。

**Spec:** `docs/superpowers/specs/2026-08-29-knowledge-unit-projection-design.md`

## Global Constraints

- 不修改任何 1.0.0 contract schema、fixtures、diagnostics 或 lock。
- 所有集合均按 unsigned UTF-8 bytes 排序并去重；固定引用为小写 UUID 与安全整数 revision。
- 只读、离线、无文件/网络/模型/进程执行；不得写用户状态或授予 capability。
- `ready`、`blocked`、`needs_evidence` 描述工程证据与依赖，不描述个人掌握。
- Python 与 TypeScript 必须使用独立实现，并以同一手工 fixture 逐字段比对。
- 每个生产行为先完成 RED，再写最小 GREEN 实现；报告中保留 RED/GREEN 命令与结果。
- 每项任务单独提交；只运行目标模块、直接依赖与验收命令。

---

### Task 1: Thoughtflow KnowledgeUnit snapshot 身份收口

**Files:**
- Modify: `packages/thoughtflow/python/intelliengine_thoughtflow/validation.py`
- Modify: `packages/thoughtflow/src/thoughtflow/validation.ts`
- Modify: `packages/thoughtflow/tests/python/test_runtime.py`
- Modify: `packages/thoughtflow/tests/ts/runtime.test.ts`

**Interfaces:**
- Consumes: 已有 `validate_references(flow, snapshot)` 与 `validateReferences(flow, snapshot)`。
- Produces: 两运行时对 `available` KnowledgeUnit 的 document/ref 身份不匹配返回 `thoughtflow.dangling_reference`。

- [ ] **Step 1: 写 Python RED 测试**

在 `valid_flow()` 对应的 fixture snapshot 中，将首个 `knowledge_units[0].document.id` 替换为另一个合法 UUID。断言 `validate_references(flow, snapshot)` 的 `object_result == "invalid"`、诊断 code 为 `thoughtflow.dangling_reference`、path 为 `/knowledge_unit_refs/0`。

- [ ] **Step 2: 运行 Python RED**

Run: `python -B packages/thoughtflow/tests/python/test_runtime.py`

Expected: 新测试失败，实际结果为 `valid`。

- [ ] **Step 3: 写 TypeScript RED 测试**

对 TypeScript `validFlow()` fixture 做同一错配，断言 `validateReferences` 返回相同封闭结果。

- [ ] **Step 4: 运行 TypeScript RED**

Run: `node --test packages/thoughtflow/tests/ts/runtime.test.ts`

Expected: 新测试失败，实际结果为 `valid`。

- [ ] **Step 5: 最小实现**

在两个 runtime 的 reference validation 循环中，对每个 available KnowledgeUnit entry 加入等价检查：

```text
entry.document 是 object
entry.document.id/revision 组成的固定 ref == 当前 flow KnowledgeUnitRef
```

不匹配时返回既有 `dangling_reference` 与当前索引 path。不要新增诊断、schema 或 snapshot 字段。

- [ ] **Step 6: GREEN 与回归**

Run:

```powershell
python -B packages/thoughtflow/tests/python/test_runtime.py
node --test packages/thoughtflow/tests/ts/runtime.test.ts
python -B packages/thoughtflow/tests/test_differential.py
```

Expected: 全部通过；已有 fixture 结果不变。

- [ ] **Step 7: 提交**

```powershell
git add packages/thoughtflow
git commit -m "fix(thoughtflow): verify knowledge snapshot identity"
```

### Task 2: KnowledgeUnit 运行时资源边界

**Files:**
- Modify: `packages/knowledge-units/python/intelliengine_knowledge_units/runtime.py`
- Modify: `packages/knowledge-units/src/knowledge-unit/runtime.ts`
- Modify: `packages/knowledge-units/tests/python/test_runtime.py`
- Modify: `packages/knowledge-units/tests/ts/runtime.test.ts`

**Interfaces:**
- Consumes: `validate_unit` / `validateUnit`、已有 `knowledge_unit_jcs_bytes=1048576` 合同限制。
- Produces: 大于限制的结构有效 unit 返回 `object_result="not_evaluated"`、`operation_outcome="resource_exhausted"`，并使用已有 `knowledge_unit.invalid_json` 诊断作为最小稳定错误码；边界内 unit 保持 valid。

- [ ] **Step 1: 写 Python RED 边界测试**

从 bundled valid unit 构造 JCS 字节数恰为 1,048,576 与 1,048,577 的两个 unit；只通过扩大 `concept_boundary.out_of_scope_statements[0]` 的 UTF-8 内容，不改变其他语义。断言前者 valid，后者 `not_evaluated/resource_exhausted`。

- [ ] **Step 2: 运行 Python RED**

Run: `python -B packages/knowledge-units/tests/python/test_runtime.py`

Expected: 超限 unit 被错误报告 valid。

- [ ] **Step 3: 写 TypeScript RED 边界测试并运行**

在 TypeScript 中以现有 canonical JSON 工具构造同样边界，执行：

```powershell
node --test packages/knowledge-units/tests/ts/runtime.test.ts
```

Expected: 超限 unit 被错误报告 valid。

- [ ] **Step 4: 最小实现**

从 `contract.json` 读取限制值或在两语言使用同一明确常量 `1048576`。在 schema 成功前返回资源耗尽前先计算 canonical JCS UTF-8 字节数；严格大于限制才返回：

```json
{"object_result":"not_evaluated","operation_outcome":"resource_exhausted","issues":[{"code":"knowledge_unit.invalid_json","path":"","severity":"error"}]}
```

不得改变 validation-result schema、fixture lock 或任一 1.0.0 contract 工件。

- [ ] **Step 5: GREEN 与回归**

Run:

```powershell
python -B packages/knowledge-units/tests/python/test_runtime.py
node --test packages/knowledge-units/tests/ts/runtime.test.ts
python -B packages/knowledge-units/tests/test_differential.py
python -B packages/knowledge-units/tests/test_contract.py
```

Expected: 全部通过；8 个 machine fixture 不变。

- [ ] **Step 6: 提交**

```powershell
git add packages/knowledge-units
git commit -m "fix(knowledge-units): enforce runtime size limit"
```

### Task 3: KnowledgeUnit 项目投影

**Files:**
- Create: `packages/knowledge-units/python/intelliengine_knowledge_units/project.py`
- Modify: `packages/knowledge-units/python/intelliengine_knowledge_units/__init__.py`
- Create: `packages/knowledge-units/src/knowledge-unit/project.ts`
- Create: `packages/knowledge-units/tests/fixtures/project-projection-cases.json`
- Create: `packages/knowledge-units/tests/python/test_project.py`
- Create: `packages/knowledge-units/tests/ts/project.test.ts`
- Create: `packages/knowledge-units/tests/test_project_differential.py`

**Interfaces:**
- Consumes: `validate_unit` / `validateUnit`，签名 `project_knowledge(units, available_node_refs, evidence_node_refs, contract_root)` 与 `projectKnowledge(units, availableNodeRefs, evidenceNodeRefs, contractRoot)`。
- Produces: 投影结果 `object_result`、`operation_outcome`、`issues`、`units`、`node_dependents`、`unit_dependents`。

- [ ] **Step 1: 写手工 projection fixture 与 Python RED**

创建两个固定数学单元：`resolve-linear-equation` 前置 `understand-equality-transformations`。fixture 包含完整 available nodes、空 evidence、完整 evidence、缺失先修和前置环四种案例。Python 测试逐字面断言：

- 空 evidence 时 dependent unit 为 `needs_evidence`；
- 缺失先修时 dependent unit 为 `blocked` 并列出缺失 ref；
- 使用一个证据节点时该节点的 `node_dependents` 返回两个直接使用它的 unit refs；
- 修改先修 ref 的 `unit_dependents` 返回其反向闭包；
- 前置环返回 `invalid` 与 `knowledge_project.prerequisite_cycle`。

- [ ] **Step 2: 运行 Python RED**

Run: `python -B packages/knowledge-units/tests/python/test_project.py`

Expected: import 或函数缺失；不是 fixture 语法错误。

- [ ] **Step 3: 写 TypeScript RED 并运行**

使用同一 JSON fixture 与手工字面 expected：

```powershell
node --test packages/knowledge-units/tests/ts/project.test.ts
```

Expected: module 或 function 缺失。

- [ ] **Step 4: 最小双语言实现**

实现独立的 project module：

1. 逐 unit 调用已有 validator；任一 invalid 返回 `knowledge_project.invalid_unit` 与 `/units/<index>`。
2. 验证 unit refs 与 evidence refs 为规范、去重、按 UTF-8 排序集合；重复 unit ref 返回 `knowledge_project.duplicate_unit_ref`。
3. 构建 prerequisite 边；检测仅在工程内闭合的有向环，返回 `knowledge_project.prerequisite_cycle`。
4. 对每 unit：存在任何缺失 prerequisite 为 `blocked`；否则缺少任意 validation/mastery evidence node 为 `needs_evidence`；否则为 `ready`。
5. 从所有 unit 内的既有 node 引用构建直接 `node_dependents`；构建 transitive `unit_dependents`。
6. 所有结果按 unsigned UTF-8 规范排序。结果只读且不得导入 Thoughtflow。

- [ ] **Step 5: GREEN 与差分**

Run:

```powershell
python -B packages/knowledge-units/tests/python/test_project.py
node --test packages/knowledge-units/tests/ts/project.test.ts
python -B packages/knowledge-units/tests/test_project_differential.py
python -B packages/knowledge-units/tests/test_contract.py
```

Expected: 两语言对同一 fixture 逐字段一致；既有 contract tests 通过。

- [ ] **Step 6: 提交**

```powershell
git add packages/knowledge-units
git commit -m "feat(knowledge-units): add project projection"
```

### Task 4: Thoughtflow 知识影响适配器与数学演示

**Files:**
- Create: `packages/thoughtflow/python/intelliengine_thoughtflow/knowledge_impact.py`
- Modify: `packages/thoughtflow/python/intelliengine_thoughtflow/__init__.py`
- Create: `packages/thoughtflow/src/thoughtflow/knowledge-impact.ts`
- Create: `packages/thoughtflow/tests/fixtures/knowledge-impact-cases.json`
- Create: `packages/thoughtflow/tests/python/test_knowledge_impact.py`
- Create: `packages/thoughtflow/tests/ts/knowledge-impact.test.ts`
- Create: `packages/thoughtflow/tests/test_knowledge_impact_differential.py`

**Interfaces:**
- Consumes: 已合并 Task 3 的 valid projection 与已有 Thoughtflow flow；`project_knowledge_impacts(flow, projection)` / `projectKnowledgeImpacts(flow, projection)`。
- Produces: `{object_result, operation_outcome, issues, impacted_steps}`；每项为 `{step_id, reasons:[{knowledge_unit_ref,status,missing_prerequisite_refs,missing_evidence_node_refs}]}`。

- [ ] **Step 1: 写 Python RED 演示测试**

使用已有线性方程 Thoughtflow 与 Task 3 的 fixture projection。断言：

- `blocked` 先修单元影响所有显式引用它的 analysis/operation step；
- `needs_evidence` 单元影响引用该单元的 verification step；
- ready projection 返回空 `impacted_steps`；
- output 不含 `executed_operations`、branch selection、个人掌握或写入字段。

- [ ] **Step 2: 运行 Python RED**

Run: `python -B packages/thoughtflow/tests/python/test_knowledge_impact.py`

Expected: import 或函数缺失。

- [ ] **Step 3: 写 TypeScript RED 并运行**

```powershell
node --test packages/thoughtflow/tests/ts/knowledge-impact.test.ts
```

Expected: module 或 function 缺失。

- [ ] **Step 4: 最小双语言实现**

只读取 flow steps 的 `knowledge_unit_refs` 与 operation `behavior_ref.knowledge_unit_ref`。对 projection 中非 ready unit 产生 reason；合并同一 step 的 reasons；按 step ID 与 fixed ref 排序。投影 invalid 或 flow 不具备所需集合时返回 `not_evaluated/indeterminate`，且不尝试执行、模拟或修改 flow。

- [ ] **Step 5: GREEN、差分与完整直接回归**

Run:

```powershell
python -B packages/thoughtflow/tests/python/test_knowledge_impact.py
node --test packages/thoughtflow/tests/ts/knowledge-impact.test.ts
python -B packages/thoughtflow/tests/test_knowledge_impact_differential.py
python -B packages/thoughtflow/tests/test_contract.py
python -B packages/thoughtflow/tests/python/test_runtime.py
node --test packages/thoughtflow/tests/ts/*.test.ts
python -B packages/thoughtflow/tests/test_differential.py
python scripts/verify_governance.py
```

Expected: 所有命令通过；演示只生成影响解释，不产生副作用。

- [ ] **Step 6: 提交**

```powershell
git add packages/thoughtflow
git commit -m "feat(thoughtflow): project knowledge impacts"
```
