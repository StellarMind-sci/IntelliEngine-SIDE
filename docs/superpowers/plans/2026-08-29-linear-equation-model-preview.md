# 线性方程模型预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让一个受约束的线性方程 KnowledgeUnit/Thoughtflow 工程生成可视、可审查、零副作用的数学模型预览。

**Architecture:** 在 plugins/math/linear-equation-preview 建立纯 TypeScript 编译器和 HTML renderer。编译器只读取不可变 KnowledgeUnit 文档、只读项目投影与 Thoughtflow 步骤，正常状态产生 SymPy 建议；阻断、缺证据、空匹配和非法输入均产生无 proposal 的封闭结果。CLI 只从固定 fixture 读取并写 stdout，验收 HTML 由用户重定向保存。

**Tech Stack:** Node 24 内建 TypeScript type stripping、Node 内建 test runner、JSON fixture、无外部依赖。

**Spec:** docs/superpowers/specs/2026-08-29-linear-equation-model-preview-design.md

## Global Constraints

- 只在 plugins/math/linear-equation-preview/**、docs/demos/** 与新增 `.github/workflows/math-preview.yml` 增加本切片文件；不得修改任何已发布契约、schema、lock、既有 fixture 或 runtime。
- 纯预览：不启动 Python/SymPy/进程/Agent/网络/数据库，不写工程状态、证据或用户数据，不注册 Plugin SDK。
- 结果必须含 mode: "preview" 与 side_effects: "forbidden"；不得把建议称为执行结果或个人掌握证据。
- 仅匹配 operation behavior_ref.behavior_id === "solve-linear-equation"、对应 KnowledgeUnit 的同名 calculation 行为及 runtime.math.symbolic capability。
- 只有目标单元状态为 ready 时产生 proposal；blocked、needs_evidence、空匹配和非法输入均不得输出代码建议。
- `ready` 必须没有缺失先修或证据；`blocked` 必须有缺失先修；`needs_evidence` 必须无缺失先修且有证据缺口；重复或矛盾投影封闭为 invalid_input。solution、SymPy 建议和 verification assertion 必须从精确有理数表示生成，不得依赖浮点除法。
- CLI 只从固定 fixture 读入，向 stdout 输出 JSON 或 HTML；它不得自行创建或修改文件。
- 用户验收必须覆盖正常、阻断、空状态，提供可复制命令、预期结果、视觉证据、自动化证据、已知限制与回滚。
- 每个生产行为先取得 RED，再写最小 GREEN；Node 测试必须运行真实 CLI/renderer，不使用 mock。

---

## 文件结构

- plugins/math/linear-equation-preview/preview.ts：把固定数学输入、KnowledgeUnit 文档、投影与 Thoughtflow 步骤编译为结构化预览。
- plugins/math/linear-equation-preview/render.ts：把预览无脚本地渲染为可打印 HTML。
- plugins/math/linear-equation-preview/cli.ts：从固定 demo fixture 选择 case，输出 JSON 或 HTML。
- plugins/math/linear-equation-preview/fixtures/demo-cases.json：ready、blocked、empty、invalid-equation 的手工输入与字面预期。
- plugins/math/linear-equation-preview/tests/preview.test.ts：核心编译器 RED/GREEN。
- plugins/math/linear-equation-preview/tests/render-cli.test.ts：HTML renderer 与真实 CLI 行为。
- docs/demos/linear-equation-model-preview-acceptance.md：用户验收入口和三状态视觉证据说明。

### Task 1: 只读预览编译器与固定工程案例

**Files:**
- Create: plugins/math/linear-equation-preview/fixtures/demo-cases.json
- Create: plugins/math/linear-equation-preview/tests/preview.test.ts
- Create: plugins/math/linear-equation-preview/preview.ts

**Interfaces:**
- Consumes: PreviewRequest = { equation, knowledge_units, projection, flow }。每个 target document 有 id、revision、title 和 behaviors；projection unit 有 ref、status、missing_prerequisite_refs、missing_evidence_node_refs；flow step 有 step_id、kind、可选 behavior_ref。
- Produces: createLinearEquationPreview(request): PreviewResult；PreviewResult 精确含 mode、side_effects、state、equation、proposal、impacted_steps、reasons。
- proposal 为 null 或 { canonical_equation, solution: { variable, value }, sympy_source, verification_assertion }。

- [ ] **Step 1: Write the failing test and fixture**

创建 fixture 的 ready case：equation 为 variable x、coefficient 2、constant 3、right_hand_side 11；预期 state 为 ready、solution 为 4、canonical_equation 为 2*x + 3 = 11、verification_assertion 为 2 * 4 + 3 == 11。

同一 fixture 另有：
- blocked：目标 unit 为 blocked，且有一个固定 missing_prerequisite_ref；
- empty：flow 不含 matching operation；
- invalid-equation：coefficient 为 0。

在 preview.test.ts 写真实 API 测试。ready 必须手工字面断言：
~~~
assert.equal(preview.mode, "preview");
assert.equal(preview.side_effects, "forbidden");
assert.equal(preview.state, "ready");
assert.deepEqual(preview.proposal.solution, { variable: "x", value: 4 });
assert.equal(preview.proposal.canonical_equation, "2*x + 3 = 11");
assert.equal(preview.proposal.verification_assertion, "2 * 4 + 3 == 11");
~~~
另行断言 blocked 的 proposal 为 null 且含缺失前置；empty 为 state empty 且 proposal 为 null；invalid 为 state invalid_input 且 proposal 为 null；调用前后输入深相等。

- [ ] **Step 2: Run RED**

Run: node --test plugins/math/linear-equation-preview/tests/preview.test.ts

Expected: 因 ../preview.ts 不存在失败；不得因 fixture JSON 语法失败。

- [ ] **Step 3: Write minimal implementation**

创建 preview.ts：
~~~
export function createLinearEquationPreview(request: PreviewRequest): PreviewResult
~~~
它依次：校验 equation（variable 为单 ASCII 字母、数为有限安全数、coefficient 非零）；按 operation 引用找到同一 immutable KnowledgeUnit；确认同名 calculation/runtime.math.symbolic behavior；从 projection 取得 unit 状态；对 blocked/needs_evidence 返回 reasons 和 null proposal；对 ready 用 (right_hand_side - constant) / coefficient 生成固定 SymPy source。impacted_steps 仅含 matching operation 与 flow verification step，按 step_id 升序。不得 import、spawn 或调用执行器。

- [ ] **Step 4: Run GREEN and direct regression**

Run:
~~~
node --test plugins/math/linear-equation-preview/tests/preview.test.ts
python -B packages/knowledge-units/tests/python/test_project.py
node --test packages/thoughtflow/tests/ts/*.test.ts
~~~
Expected: 新编译器全绿；直接依赖回归不变。

- [ ] **Step 5: Commit**

Run:
~~~
git add plugins/math/linear-equation-preview
git commit -m "feat(math): add linear equation model preview"
~~~

### Task 2: HTML/CLI 预览与可复现验收说明

**Files:**
- Create: plugins/math/linear-equation-preview/render.ts
- Create: plugins/math/linear-equation-preview/cli.ts
- Create: plugins/math/linear-equation-preview/tests/render-cli.test.ts
- Create: docs/demos/linear-equation-model-preview-acceptance.md

**Interfaces:**
- Consumes: Task 1 的 PreviewResult 与 fixtures/demo-cases.json。
- Produces: renderLinearEquationPreviewHtml(preview): string；CLI：node plugins/math/linear-equation-preview/cli.ts --case <case-id> --format <json|html>。
- CLI 对未知 case 或 format 以非零状态退出并把 stable message 写入 stderr；不写文件。

- [ ] **Step 1: Write the failing test**

在 render-cli.test.ts 写两类真实测试：
~~~
const html = renderLinearEquationPreviewHtml(blockedPreview);
assert.match(html, /工程状态：blocked/);
assert.match(html, /缺失前置/);
assert.doesNotMatch(html, /from sympy import/);
~~~
以及 spawnSync(process.execPath, ["plugins/math/linear-equation-preview/cli.ts", "--case", "ready", "--format", "html"])。断言状态 0、stdout 含 2*x + 3 = 11、stderr 为空。

另行断言 empty HTML 显示“没有可编译的线性方程行为”；未知 case 的 CLI 非零且 stderr 为 unknown demo case: missing；HTML 对 < 与 & 值转义。

- [ ] **Step 2: Run RED**

Run: node --test plugins/math/linear-equation-preview/tests/render-cli.test.ts

Expected: 因 render.ts 与 cli.ts 不存在失败；不是 spawn cwd 或 fixture 路径错误。

- [ ] **Step 3: Write minimal renderer and CLI**

实现无 JavaScript 的单页 HTML：标题、mode、side_effects、状态、公式、受影响步骤、原因；ready 才显示 SymPy 与验证断言。所有文字经过 HTML escape；内联 CSS 区分 ready、blocked/needs_evidence、empty，且可打印。

CLI 通过 new URL("./fixtures/demo-cases.json", import.meta.url) 读取 fixture、调用 Task 1 API，并严格只用 process.stdout.write/process.stderr.write。

- [ ] **Step 4: Write acceptance guide**

在 docs/demos/linear-equation-model-preview-acceptance.md 写明：
1. Node 24 与仓库根目录前置条件；
2. ready、blocked、empty 三条 HTML 命令：
~~~
node plugins/math/linear-equation-preview/cli.ts --case ready --format html > $env:TEMP\side-preview-ready.html
Start-Process $env:TEMP\side-preview-ready.html
~~~
3. 每页预期、unknown case 异常预期、截图要求；
4. 自动化命令、已知限制，以及 git revert <feature-commit> 回滚方式。

明确 HTML 是 preview，不是 Python 执行、验证结果或掌握证据。

- [ ] **Step 5: Run GREEN, acceptance commands, governance**

Run:
~~~
node --test plugins/math/linear-equation-preview/tests/*.test.ts
node plugins/math/linear-equation-preview/cli.ts --case ready --format json
node plugins/math/linear-equation-preview/cli.ts --case blocked --format html
node plugins/math/linear-equation-preview/cli.ts --case empty --format html
python scripts/verify_governance.py
~~~
Expected: 所有测试通过；ready JSON 含 proposal；blocked/empty HTML 不含 from sympy import；治理通过。

- [ ] **Step 6: Commit**

Run:
~~~
git add plugins/math/linear-equation-preview docs/demos/linear-equation-model-preview-acceptance.md
git commit -m "feat(math): render linear equation preview"
~~~
