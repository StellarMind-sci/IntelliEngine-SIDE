# 线性方程 KnowledgeUnit → verification 路径预览：验收说明

## 用户可感知能力

这个离线只读切片把固定的线性方程输入经过实际的 intake、KnowledgeUnit 组装、知识投影和 Thoughtflow impact navigator，展示为可审查的工程学习路径：

`线性方程文本 → 未持久化 KnowledgeUnit 草案 → 缺失证据 →（仅有关联上下文时）verification 步骤提示`

它不是笔记页，也不是独立刷题模式：缺失的代入验证证据会反向影响当前工程验证步骤。所有页面均由限定 CLI 调用真实 bridge 生成，而非手写展示数据。

## 严格边界

- 输出恒为 `mode: "preview"`、`side_effects: "forbidden"`；不写入文件、数据库或用户数据。
- `flow_context.persistence` 为 `not_persisted`；它不是已保存的 Thoughtflow。
- 不执行代码、模型或 Agent，不访问网络，不读取用户提供的路径。
- 不宣称掌握、验证完成或“ready”。`needs_evidence` 只表示仍缺少可追踪的验证证据。
- CLI 只接受四个内置固定案例，拒绝未知值和 `__proto__` 等原型式输入。

## 前置条件

- 在仓库根目录运行 PowerShell。
- Node.js 24（CI 使用 Node 24）。本地 Node 支持 TypeScript strip types 后即可复现。

命令中的 `--no-warnings` 只抑制 Node 对相邻历史 `.ts` 包边界的运行时提示，**不改变** bridge 输出或安全边界。

## 可视化验收入口

无需运行工程即可先查看四个真实工件：

| 状态 | 真实 HTML | 浏览器截图 | 应看到的结果 |
| --- | --- | --- | --- |
| 已关联验证步骤 | [verification.html](artifacts/linear-equation-verification-path-preview/verification.html) | [verification.png](artifacts/linear-equation-verification-path-preview/verification.png) | `needs_evidence`、一个缺失证据节点、仅提示 `verification-linear-equation`。 |
| 未映射上下文 | [unmapped.html](artifacts/linear-equation-verification-path-preview/unmapped.html) | [unmapped.png](artifacts/linear-equation-verification-path-preview/unmapped.png) | 草案存在但无关联 verification 步骤，明确显示“**不伪造下一步**”。 |
| 上游为空 | [empty.html](artifacts/linear-equation-verification-path-preview/empty.html) | [empty.png](artifacts/linear-equation-verification-path-preview/empty.png) | 无 KnowledgeUnit、flow、navigation 或 impacted step。 |
| 输入无效 | [invalid.html](artifacts/linear-equation-verification-path-preview/invalid.html) | [invalid.png](artifacts/linear-equation-verification-path-preview/invalid.png) | 无 KnowledgeUnit、flow、navigation 或 impacted step。 |

也可以在资源管理器中双击任意 HTML，或从 PowerShell 打开，例如：

```powershell
Start-Process .\docs\demos\artifacts\linear-equation-verification-path-preview\verification.html
```

## 逐步复现

在仓库根目录依次运行。每条 JSON 命令展示机器可审查的真实输出；对应 HTML 命令可重定向到临时文件后打开，输出应与仓库同名 HTML 工件字节一致。

```powershell
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case verification --format json
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case verification --format html
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case unmapped --format json
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case unmapped --format html
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case empty --format json
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case empty --format html
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case invalid --format json
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case invalid --format html
```

预期：

1. `verification` 返回 `needs_evidence`，`flow_context.persistence = not_persisted`，并且导航只为“返回 verification 步骤补充缺失证据。”
2. `unmapped` 有合法 KnowledgeUnit，但 `steps`、navigation 和 impacted steps 都为空；诊断明确说明不伪造下一步。
3. `empty` 与 `invalid` 均没有草案、flow、navigation、impact 或缺失证据引用。
4. 所有 HTML 均显示 `preview`、`forbidden`、`not_persisted` 或未形成 flow 的事实，并展示“无写入/无执行/未完成验证”的边界。

异常场景可按下列命令检查；应为非零退出、stdout 为空、stderr 以稳定的 `错误：` 开头：

```powershell
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case __proto__ --format json
node --no-warnings --experimental-strip-types .\plugins\math\linear-equation-verification-path-preview\cli.ts --case verification --format __proto__
```

## 自动化与视觉证据

```powershell
node --test .\plugins\math\linear-equation-verification-path-preview\tests\*.test.ts
```

测试覆盖四态实际 bridge 输出、CLI 拒绝路径、JSON/HTML 工件逐字节一致性、HTML 无 script/iframe/inline event handler，以及四张真实 PNG 的签名与 `1440 × 1800` 尺寸。截图由本机 Chrome headless 对同名离线 HTML 生成，每个状态使用独立临时 user-data-dir。

GitHub Actions 工作流 `Linear Equation Verification Path Preview` 在 Ubuntu 与 Windows 的 Node 24 上执行同一插件测试。

## 已知限制

- 这是固定线性方程案例的演示入口，不接受任意用户文本、工程路径或外部数据。
- `not_persisted` 表示没有 ChangeSet、审批、版本写入或回滚记录；这些状态写入能力不在本任务范围。
- 缺失证据仅来自当前固定投影，不等同于真实用户掌握度判断。

## 回滚

若需要撤销这项演示，回滚本任务的单一提交即可：删除其 CLI、渲染器、专用 artifact、文档与 workflow；不需要迁移或恢复任何用户数据，因为该切片从不持久化。