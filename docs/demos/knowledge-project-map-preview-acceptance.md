# KnowledgeUnit 工程知识图谱预览：验收说明

## 用户可感知能力

固定线性方程工程案例现在可把实际 `projectKnowledge` 投影呈现为一个只读工程图：KnowledgeUnit 状态卡、已加载单元的内部先修边、缺失证据、未加载的外部先修阻断，以及选中 CognitiveNode 对 KnowledgeUnit 的反向影响。

这不是普通笔记或静态知识图谱。图上的状态和关系均来自现有 KnowledgeUnit 投影；它帮助工程开发者在验证过程中看见“哪个工程知识单元、哪条先修、哪个证据节点会受影响”。

## 严格边界

- 输出恒为 `mode: "preview"`、`side_effects: "forbidden"`、`not_persisted`；不保存 KnowledgeUnit、Thoughtflow、证据、ChangeSet 或用户数据。
- 不执行代码、模型或 Agent，不访问网络，不读取用户提供的路径。
- `ready` 仅为投影状态，绝不表示个人掌握、验证完成或工程完成。
- 图中的“未加载的外部先修”仅为投影中的引用，页面明确不把它伪造成已加载的 KnowledgeUnit。
- CLI 仅接受四个内置固定案例，拒绝未知、`__proto__`、路径式、重复或缺失参数。

## 前置条件

- 在仓库根目录运行 PowerShell。
- Node.js 24（GitHub CI 使用 Node 24）。本地 Node 支持 TypeScript strip types 即可复现。

`--no-warnings` 仅抑制 Node 对相邻历史 `.ts` 包边界的运行时提示，不改变投影、图谱或安全边界。

## 可视化验收入口

无需执行代码即可先打开四个真实离线工件：

| 状态 | HTML | 浏览器截图 | 应看到的结果 |
| --- | --- | --- | --- |
| 正常图谱 | [normal.html](artifacts/knowledge-project-map-preview/normal.html) | [normal.png](artifacts/knowledge-project-map-preview/normal.png) | 两张单元状态卡、`等式变形 → 一元一次方程求解` 内部先修、后一单元 `needs_evidence`，以及 CognitiveNode 的反向影响。 |
| 外部先修阻断 | [blocked.html](artifacts/knowledge-project-map-preview/blocked.html) | [blocked.png](artifacts/knowledge-project-map-preview/blocked.png) | 一张 `blocked` 单元卡和虚线“未加载的外部先修”；该引用不被伪造成图中的单元。 |
| 空反向影响 | [empty.html](artifacts/knowledge-project-map-preview/empty.html) | [empty.png](artifacts/knowledge-project-map-preview/empty.png) | 图仍存在，但选中节点没有受影响单元，明确显示“不伪造影响”。 |
| 输入无效 | [invalid.html](artifacts/knowledge-project-map-preview/invalid.html) | [invalid.png](artifacts/knowledge-project-map-preview/invalid.png) | 无单元、无先修边、无外部先修、无反向影响，明确显示“未形成工程图”。 |

也可在资源管理器中双击任意 HTML，或运行：

```powershell
Start-Process .\docs\demos\artifacts\knowledge-project-map-preview\normal.html
```

## 逐步复现

在仓库根目录按状态运行。JSON 是机器可审查的真实输出；HTML 输出与同名仓库工件逐字节一致。

```powershell
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case normal --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case normal --format html
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case blocked --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case blocked --format html
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case empty --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case empty --format html
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case invalid --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case invalid --format html
```

预期：

1. `normal` 返回 `state: "valid"`，包含两项 `units`、一条 `prerequisite_edges`、一项缺失证据节点，并将默认选中的 CognitiveNode 反向关联到一元一次方程求解单元。
2. `blocked` 返回 `state: "valid"`，但唯一单元为 `blocked`，并在 `external_prerequisite_refs` 中出现等式变形引用。
3. `empty` 返回 `state: "empty"`、仍有两项单元但 `affected_unit_refs` 为空；不创建伪造影响。
4. `invalid` 返回 `state: "invalid_input"`，所有单元、边、外部先修和影响数组均为空。

异常输入必须非零退出、stdout 为空、stderr 精确为稳定错误信息：

```powershell
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case __proto__ --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case ..\normal --format json
node --no-warnings --experimental-strip-types .\plugins\math\knowledge-project-map-preview\cli.ts --case normal --format __proto__
```

## 自动化与视觉证据

```powershell
node --test .\plugins\math\knowledge-project-map-preview\tests\*.test.ts
node --test .\packages\knowledge-units\tests\runtime.test.ts
```

测试覆盖固定 CLI 四态、未知/原型/路径/重复参数拒绝、JSON/HTML 工件逐字节一致性、动态值 HTML 转义与无 script/iframe/inline event handler，并验证四张真实 PNG 的签名和 `1440 × 1800` 尺寸。截图由本机 Chrome headless 对同名离线 HTML 生成，每个状态使用独立临时 user-data-dir。

GitHub Actions 工作流 `Knowledge Project Map Preview` 在 Ubuntu 与 Windows 的 Node 24 上运行插件测试。

## 已知限制

- 这是固定数学工程案例，不接受任意用户工程、文本、路径或外部数据。
- 外部先修只有引用和阻断意义；加载、创建、变更或审批该先修不属于本切片。
- 没有 ChangeSet、版本写入、审批或回滚记录，因为本切片无持久化行为。

## 回滚

若需撤销，回滚本任务的单一提交即可；删除 CLI、渲染器、工件、验收说明和专用 CI，不需要迁移、恢复或清理用户数据。