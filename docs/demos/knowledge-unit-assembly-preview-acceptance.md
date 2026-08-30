# 一元一次方程 KnowledgeUnit 组装预览验收

## 用户能力与边界

用户可离线查看一个已经通过 CognitiveNode 与 KnowledgeUnit 固定合同校验的**未持久化 KnowledgeUnit 草案**：它展示规范来源、KnowledgeUnit 标题与 ID、`core`、`evidence`、`example`、`representation` 四类 CognitiveNode 角色，以及代入验证证据尚未记录时的工程导航。

`needs_evidence` 是合同结构有效、但工程验证证据尚未记录的正常紫色状态。它**不表示用户已掌握**，不表示代入验证已经完成，也不是 `ready`。预览固定显示 `mode: preview` 与 `side_effects: forbidden`；不写入工程、不执行模型或代码、不联网、不调用 Agent 或 ChangeSet。

CLI 只读取插件内固定 `fixtures/demo-cases.json`，并通过真实的“方程摄入 → KnowledgeUnit 组装”路径生成结果。组装与校验只读使用插件内部固定推导的 CognitiveNode 1.0.0 与 KnowledgeUnit 1.0.0 仓库合同资源；不接受或读取用户指定路径、文件、DOCX 或图片。

## 前置条件与验收入口

- 在仓库根目录 `E:\Projects\IDE` 执行命令。
- 正式 CI 使用 Node.js 24；本地可用 `node --version` 核验版本。
- 下列 PowerShell 命令只将 CLI 的 stdout 输出到验收者临时目录，不改变项目工程状态。

## 三态操作与预期

### Needs evidence：有效草案，等待代入验证记录

```powershell
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case needs-evidence --format html > $env:TEMP\knowledge-unit-assembly-needs-evidence.html
Start-Process $env:TEMP\knowledge-unit-assembly-needs-evidence.html
```

预期：页面以紫色显示 `state：needs_evidence`；显示来源 `prov:source:algebra-example-1`、标题“解一元一次方程：2*x + 3 = 11”、KnowledgeUnit ID、四类 role 到 node ref 的映射、验证规则“将解代回原方程后等式成立。”、一个 `missing evidence ref` 和中文导航。页面必须明确写出“合同结构有效，但代入验证证据尚未记录”及“不表示用户已掌握”。

### Empty：上游没有可组装的方程

```powershell
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case empty --format html > $env:TEMP\knowledge-unit-assembly-empty.html
Start-Process $env:TEMP\knowledge-unit-assembly-empty.html
```

预期：页面显示 `state：empty` 与“上游没有可组装的方程候选。”；不显示 KnowledgeUnit 草案、候选节点、投影或缺失证据引用。

### Invalid：上游输入被封闭拒绝

```powershell
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case invalid --format html > $env:TEMP\knowledge-unit-assembly-invalid.html
Start-Process $env:TEMP\knowledge-unit-assembly-invalid.html
```

预期：页面显示 `state：invalid_input` 与上游预览无效的诊断；不显示 KnowledgeUnit 草案、候选节点、投影或缺失证据引用。它表示受限上游方程预览未能组装，不评价数学问题或用户能力。

## 异常 CLI

```powershell
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case missing --format html
$LASTEXITCODE
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case __proto__ --format json
$LASTEXITCODE
node plugins/math/knowledge-unit-assembly-preview/cli.ts --case empty --format text
$LASTEXITCODE
```

预期：每条命令均非零退出且 stdout 为空；stderr 依次为 `unknown demo case: missing`、`unknown demo case: __proto__`、`unknown output format: text`。错误参数不会触发用户路径读取、工程写入或执行。

## 自动化与可视化证据

```powershell
node --test plugins/math/knowledge-unit-assembly-preview/tests/*.test.ts
git diff --check
```

专属 [KnowledgeUnit Assembly Preview workflow](../../.github/workflows/knowledge-unit-assembly-preview.yml) 在 Ubuntu 与 Windows 的 Node.js 24 上运行完整插件测试。测试会验证真实 CLI 到真实组装器的三态路径、HTML 安全转义、无 `script`/`iframe`/事件处理器、非掌握措辞、异常 CLI 的 stdout/stderr，以及下列 HTML 与当前 CLI stdout 的逐字节一致性：

- Needs evidence：[HTML](artifacts/knowledge-unit-assembly-preview/needs-evidence.html)
- Empty：[HTML](artifacts/knowledge-unit-assembly-preview/empty.html)
- Invalid：[HTML](artifacts/knowledge-unit-assembly-preview/invalid.html)

本工作区未找到可用的本地无头浏览器或 Playwright/Puppeteer，因此没有伪造 PNG 链接或将截图标记为已完成。精确探测命令与结果为：`where.exe chrome; where.exe msedge; where.exe chromium; node -e "for (const m of ['playwright','@playwright/test','puppeteer']) ..."`；三种浏览器均未找到，三个 Node 包均为 `no`。以上三份 HTML 可离线直接打开，并由自动化逐字节核验，作为当前替代可视化验收证据。

## 已知限制与回滚

此切片只演示固定的一元一次方程 fixture，不是通用数学导入、文件导入、OCR、DOCX/图片解析、工程保存、模型执行或学习掌握评估。`needs_evidence` 只反映缺少工程验证证据，不产生或确认任何用户掌握数据。

本功能没有迁移、用户数据或外部调用。若需撤回已合并功能，在确认目标提交后执行：

```powershell
git revert <feature-commit>
```

将 `<feature-commit>` 替换为本功能提交的完整 SHA 或唯一短 SHA。