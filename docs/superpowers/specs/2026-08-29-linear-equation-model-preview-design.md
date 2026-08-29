# 线性方程模型预览设计

## 目标

为一个受约束的一元一次方程工程提供只读、可视化、可审查的模型预览。用户看到的不是笔记或刷题页面，而是当前 KnowledgeUnit 与 Thoughtflow 在工程上是否可生成一份 Python/SymPy 建议、其公式、变量、验证断言和阻断原因。

## 已有事实与边界

- 已合并的 KnowledgeUnit 投影把工程状态表达为 `ready`、`blocked`、`needs_evidence`；Thoughtflow 影响投影能指出受影响步骤与原因。
- `solve-linear-equation` 已声明 `calculation` / `runtime.math.symbolic` 行为，但目前没有数学执行器、输入解析器、Web IDE 或已发布 Plugin SDK。
- 因此本切片不运行 SymPy、不创建工程状态、不授予 capability，也不声称已经有可加载的 DomainPlugin。代码归属 `plugins/math`，但只是未来插件可复用的纯预览组件。

## 用户结果

用户运行固定演示后，获得一个可直接在浏览器打开的 HTML 预览和等价的结构化 JSON：

1. **正常**：`2x + 3 = 11` 显示规范模型、`x = 4`、SymPy 建议、`2 * 4 + 3 == 11` 验证断言，以及关联 operation/verification 步骤。
2. **阻断**：当目标 KnowledgeUnit 为 `blocked` 或 `needs_evidence` 时，显示缺失前置或证据和受影响步骤，且 `proposal` 为 `null`；绝不输出可执行代码建议。
3. **空状态**：当 Thoughtflow 没有匹配的 `solve-linear-equation` operation 时，显示没有可编译行为；不把无关步骤或其他 capability 猜成数学模型。

预览明确标记 `mode: "preview"`、`side_effects: "forbidden"`。它不描述个人掌握程度，只有工程前置与验证证据状态。

## 输入和输出

内部函数 `createLinearEquationPreview(request)` 接收：

- 受限 equation `{ variable: "x", coefficient: 2, constant: 3, right_hand_side: 11 }`；所有字段必须是有限安全数，`coefficient !== 0`。
- KnowledgeUnit project projection 的只读 `units` 结果，以及对应的不可变 `knowledge_units` 文档；后者只用于确认行为和 capability。
- Thoughtflow 的只读 `steps`，只读取 operation 的 `behavior_ref` 与 verification step。

它只匹配 Thoughtflow operation 的行为 ID `solve-linear-equation`，并要求对应不可变 KnowledgeUnit 文档含同名行为、`calculation` kind 与 `runtime.math.symbolic` capability。固定演示 fixture 在内部对齐这些字段；它不修改既有跨模块 fixture。输出为：

```text
{ mode, side_effects, state, equation, proposal, impacted_steps, reasons }
```

`proposal` 只会在 `ready` 状态存在，包含 canonical equation、solution、SymPy source suggestion 和 verification assertion。所有数组稳定排序；输入深拷贝后只读处理。

HTML 渲染函数 `renderLinearEquationPreviewHtml(preview)` 只把该结构化预览转换为无脚本、可打印的单页 HTML。命令行入口读取固定 fixture，向 stdout 输出 JSON 或 HTML；用户可重定向 stdout 到本地文件后打开。CLI 本身不写文件。

## 范围

- 在 `plugins/math/linear-equation-preview/` 新建 TypeScript 纯函数、HTML renderer、CLI、固定演示 fixture 和 Node 测试。
- 在 `docs/demos/` 新建验收说明，含复制即用的三种场景命令、预期结果、异常/空状态与截图获取方法。

## 非目标

- 不调用 Python、SymPy、NumPy、模型服务、Agent、网络、文件写入、数据库或外部工具。
- 不解析自然语言、DOCX 或图片；方程输入为固定结构化值。
- 不修改 CognitiveNode、KnowledgeUnit、Thoughtflow、Plugin SDK、ControlPolicy、ChangeSet 或任一公共 schema/lock。
- 不注册/加载插件，不新增权限，不把预览解释为执行结果或用户掌握证据。

## 验收与证据

自动化测试必须覆盖正常、阻断、空状态、非法方程（系数为零/非安全数）和输入不变性。命令行必须能用固定 fixture 输出每种场景的 JSON 与 HTML。

交付时提供：

- 生成的三张 HTML 验收页或其截图：正常、阻断、空状态；
- 完整的可复制命令和每步预期；
- 对应 Node 测试与治理检查输出；
- 已知限制：只生成代码建议，尚未执行或验证 Python。

## 风险与回滚

最大风险是把建议误当成执行，故输出固定携带 `side_effects: "forbidden"`，阻断状态没有代码提案。另一个风险是未来误把该目录视为已注册插件，文档明确它没有 SDK 注册。

回滚仅需回退本切片的提交；它没有持久化状态、迁移、外部调用或公共格式变化。
