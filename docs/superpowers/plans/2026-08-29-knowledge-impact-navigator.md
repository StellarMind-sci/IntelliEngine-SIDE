# KnowledgeUnit 工程影响导航预览：实施计划

**目标：** 将已验证的 KnowledgeUnit→Thoughtflow impact projection 交付为可视、可审查、零副作用的工程导航预览。

**架构：** 在 `plugins/math/knowledge-impact-navigator` 建立 TypeScript view-model、无脚本 HTML renderer 和固定 fixture CLI。view-model 直接消费 Thoughtflow 的现有 `projectKnowledgeImpacts`，仅聚焦一个 KnowledgeUnit ref；不会重写投影逻辑。Node 24 的独立 CI 在 Ubuntu/Windows 执行同一真实测试集合。

**规格：** `docs/superpowers/specs/2026-08-29-knowledge-impact-navigator-design.md`

## 全局约束

- 只修改本插件目录、演示文档/产物和新增专属 workflow；不动既有 runtime、合同、schema、lock 或 SDK。
- 固定 `mode: "preview"`、`side_effects: "forbidden"`；无执行、写入、网络、Agent、外部工具或用户数据。
- 只调用既有 impact runtime；上游 invalid/indeterminate、聚焦 ref 非规范或不匹配一律封闭为 `invalid_input`。
- blocked（缺失前置非空，可同时有证据缺口）与 needs_evidence（无缺失前置、证据缺口非空）有非可执行导航文案；ready 或任何有效但无关联 impact 的 focus 均返回 empty 且无导航。
- CLI 仅固定 fixture→stdout；renderer 无 script、逃逸全部动态文本。

## Task 1：核心导航 view-model 与真实影响测试

**文件：** `fixtures/demo-cases.json`、`navigator.ts`、`tests/navigator.test.ts`。

1. 先写 RED：真实 flow/projection 分别覆盖 blocked→analysis/operation、needs_evidence→verification、ready、无关联步骤、非法 focus/上游 invalid；验证排序、输入不变和无导航门控。
2. 实现最小 `createKnowledgeImpactNavigator`，调用 `projectKnowledgeImpacts` 并聚焦 ref。
3. 跑 GREEN：`node --test plugins/math/knowledge-impact-navigator/tests/navigator.test.ts`，及 `node --test packages/thoughtflow/tests/ts/*.test.ts`。
4. 提交核心实现。

## Task 2：静态渲染、CLI、CI 与验收证据

**文件：** `render.ts`、`cli.ts`、`tests/render-cli.test.ts`、`docs/demos/knowledge-impact-navigator-acceptance.md`、`docs/demos/artifacts/knowledge-impact-navigator/**`、`.github/workflows/knowledge-impact-navigator.yml`。

1. 先写 RED：renderer 覆盖五态与转义，CLI 覆盖 stdout/stderr/未知参数；blocked 与 needs-evidence 视觉状态必须不同。
2. 最小实现无脚本 renderer 与 stdout-only CLI。
3. 新 workflow 使用 Node 24、Ubuntu/Windows、path trigger 覆盖插件、演示、workflow 及直接 Thoughtflow/KnowledgeUnit 依赖，并跑插件全集。
4. 从 CLI 生成五态 HTML/PNG，并在验收说明提供命令、预期、异常、视觉/自动化证据、限制与回滚。
5. 跑 GREEN：插件全集、Thoughtflow TS、治理检查、五条 CLI，及 `git diff --check`。

## 最终审核与交付

独立审查整个 diff，重点检查复用而非重写 impact 语义、状态门控、动态转义、CLI 防御、Node 24 CI 与视觉证据。通过后在合并结果重跑插件、Thoughtflow 与治理验证；推送并等待双平台 CI，关闭 #74，交付五态截图与详细验收步骤。
