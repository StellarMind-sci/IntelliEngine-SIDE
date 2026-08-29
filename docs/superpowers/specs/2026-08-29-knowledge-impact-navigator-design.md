# KnowledgeUnit 工程影响导航预览：设计

## 目标与边界

本切片让用户从一个已计算的 KnowledgeUnit 工程状态，看到 Thoughtflow 中哪些步骤因此受影响，以及应回到哪个验证或前置点。它是只读导航，不执行步骤、不写入证据、不生成 ChangeSet，也不把工程状态表述为个人掌握度。

复用 `packages/thoughtflow/src/thoughtflow/knowledge-impact.ts` 的 `projectKnowledgeImpacts(flow, projection)`；该 runtime 是唯一的影响归因来源。新组件不重算、修改或放宽其状态语义。

## 用户结果

1. **阻断**：目标单元 `blocked` 时，展示缺失前置、受影响的 analysis/operation 步骤，以及“先完成前置知识再继续该步骤”的只读导航。KnowledgeUnit projector 的前置优先语义允许它同时列出缺失证据；这仍是合法 blocked，不得拒绝或改写为 needs_evidence。
2. **缺证据**：目标单元 `needs_evidence` 时，展示缺失证据、受影响 verification 步骤，以及“返回验证步骤补充证据”的只读导航。
3. **正常/空**：`ready`，或任一有效聚焦单元没有关联 impact/flow 步骤时，明确显示没有待处理的工程影响，不伪造下一步或误报输入无效。
4. **异常**：输入或上游 impact 投影不是 valid/succeeded 时封闭显示 invalid_input，不产生导航条目。

## 输入和输出

内部函数 `createKnowledgeImpactNavigator(request)` 接收不可变 `flow`、KnowledgeUnit project projection、规范 `{ id, revision }` 的 `focus_ref`。它调用既有 impact runtime，并输出：

```text
{ mode, side_effects, state, focus, navigation, impacted_steps, reasons }
```

所有成功输出固定为 `mode: "preview"`、`side_effects: "forbidden"`。只有 `blocked` 与 `needs_evidence` 有导航文本；不存在按钮、命令、代码、Agent 或执行权。数组按 UTF-8 字节序稳定排序，输入保持不变。

`renderKnowledgeImpactNavigatorHtml(result)` 只输出无客户端脚本、可打印的 HTML；动态值必须转义。CLI 只读固定 JSON fixture，向 stdout 输出 JSON 或 HTML；未知 case/format 非零并写稳定 stderr，CLI 不创建文件。

## 范围

- `plugins/math/knowledge-impact-navigator/` 的纯 view-model、HTML renderer、CLI、fixture 与 Node 测试；
- `docs/demos/` 的可复制验收说明与 normal/blocked/needs-evidence/empty/invalid 视觉证据；
- `.github/workflows/knowledge-impact-navigator.yml` 的 Node 24 Ubuntu/Windows 测试；path trigger 同时覆盖直接复用的 Thoughtflow impact runtime 与 KnowledgeUnit project runtime。

## 非目标

- 不修改公共合同、schema、lock、既有 runtime、SDK 注册或数据库；
- 不执行 Thoughtflow、Python、SymPy、Agent、网络或外部工具；
- 不写状态、证据、ChangeSet、项目包或用户数据；
- 不宣称 OS 隔离、代理控制、真实执行或个人掌握度。

## 验收与风险

交付 normal、blocked、needs-evidence、empty、invalid 五态的 CLI/HTML 证据与截图。自动化覆盖真实 impact runtime、状态过滤、确定排序、空/异常输入、CLI 错误和 HTML 转义。风险是将导航误解为控制命令；通过显式 preview/forbidden 标签、无交互脚本和无可执行 proposal 消除该歧义。回滚仅移除该独立切片与 CI，不影响既有项目数据或契约。
