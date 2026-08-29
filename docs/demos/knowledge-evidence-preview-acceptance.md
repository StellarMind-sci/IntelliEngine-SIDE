# KnowledgeUnit 验证证据预览验收

## 用户能力与边界

用户可在不改变工程状态的前提下，离线查看一个 KnowledgeUnit 的工程验证证据状态、关联验证要求，以及仅供查看的 Thoughtflow 定位提示。每个页面固定标识 `mode: preview` 与 `side_effects: forbidden`。

这不是个人掌握度判断：`mastery_criteria` 在此仅表示工程证据标准，任何状态都不宣称用户“已掌握”。预览不执行 Thoughtflow、Agent、代码、模型或网络操作，也不创建、保存或提交证据。

## 前置条件与验收入口

- 在仓库根目录 `E:\Projects\IDE` 执行命令。
- 使用 Node.js 24：`node --version` 应显示 `v24.x`。其他本机版本可用于页面检查，但不能替代正式 Node 24 CI。
- CLI 只读取仓库内的固定 demo fixture，向 stdout 输出 HTML。以下 PowerShell 重定向仅由验收者在临时目录生成静态文件。

## 五态操作与预期

### Blocked：先处理前置知识

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case blocked --format html > $env:TEMP\knowledge-evidence-blocked.html
Start-Process $env:TEMP\knowledge-evidence-blocked.html
```

预期：显示红色 `state: blocked`；验证与工程证据标准列表存在且均为 `missing`，但只读导航只提示“先完成缺失前置知识”；显示“受影响的工程步骤”及 `analysis-linear`。页面不把任何列表或状态称为“掌握”。

### Needs evidence：定位验证步骤

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case needs-evidence --format html > $env:TEMP\knowledge-evidence-needs-evidence.html
Start-Process $env:TEMP\knowledge-evidence-needs-evidence.html
```

预期：显示紫色 `state: needs_evidence`；列出缺失的工程证据，以及关联的 validation/mastery 标准；只定位 `verification-linear`，并在“受影响的工程步骤”中显示该步骤，不导航到 analysis 或 operation 步骤。

### Ready：证据要求满足

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case ready --format html > $env:TEMP\knowledge-evidence-ready.html
Start-Process $env:TEMP\knowledge-evidence-ready.html
```

预期：显示绿色 `state: ready`；所有证据行均为 `satisfied`，显示“当前验证要求已满足；不伪造下一步。”，不显示导航或步骤列表。

### Empty：保留证据要求但无安全导航

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case empty --format html > $env:TEMP\knowledge-evidence-empty.html
Start-Process $env:TEMP\knowledge-evidence-empty.html
```

预期：显示灰色 `state: empty`；仍展示缺失证据和验证要求，但显示“当前工程流没有可安全定位的受影响步骤；不伪造下一步。”，不显示导航或步骤列表。

### Invalid：封闭的无效输入

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case invalid --format html > $env:TEMP\knowledge-evidence-invalid.html
Start-Process $env:TEMP\knowledge-evidence-invalid.html
```

预期：显示橙色 `state: invalid_input`；focus 为“无”，验证与工程证据标准列表为空，显示“输入或上游投影无效；预览已封闭，不生成导航。”，不显示导航或步骤列表。

## 异常场景

```powershell
node plugins/math/knowledge-evidence-preview/cli.ts --case missing --format html
$LASTEXITCODE
node plugins/math/knowledge-evidence-preview/cli.ts --case __proto__ --format json
$LASTEXITCODE
node plugins/math/knowledge-evidence-preview/cli.ts --case ready --format text
$LASTEXITCODE
```

预期：三条 CLI 命令均为非零退出、stdout 为空；stderr 依次稳定为 `unknown demo case: missing`、`unknown demo case: __proto__`、`unknown output format: text`。CLI 不读取任意用户指定文件，也不会创建工程文件。

## 自动化与视觉证据

```powershell
node --test plugins/math/knowledge-evidence-preview/tests/*.test.ts
python scripts/verify_governance.py
```

专属 [Knowledge Evidence Preview workflow](../../.github/workflows/knowledge-evidence-preview.yml) 在 Ubuntu 与 Windows 的 Node.js 24 上运行完整插件测试。下列 HTML 均由当前 CLI stdout 生成并逐字节核验；PNG 由无网络的本地无头浏览器渲染，覆盖阻断、缺证据、正常、空与错误状态：

- Blocked：[HTML](artifacts/knowledge-evidence-preview/blocked.html)；[PNG](artifacts/knowledge-evidence-preview/blocked.png)
- Needs evidence：[HTML](artifacts/knowledge-evidence-preview/needs-evidence.html)；[PNG](artifacts/knowledge-evidence-preview/needs-evidence.png)
- Ready：[HTML](artifacts/knowledge-evidence-preview/ready.html)；[PNG](artifacts/knowledge-evidence-preview/ready.png)
- Empty：[HTML](artifacts/knowledge-evidence-preview/empty.html)；[PNG](artifacts/knowledge-evidence-preview/empty.png)
- Invalid：[HTML](artifacts/knowledge-evidence-preview/invalid.html)；[PNG](artifacts/knowledge-evidence-preview/invalid.png)

## 已知限制与回滚

这是固定 fixture 的只读预览，不访问网络、数据库、外部工具或 Plugin SDK；它不替代实际工程执行或持久化验证证据。该切片没有迁移、用户数据或外部调用。撤回时，在确认提交后执行：

```powershell
git revert <feature-commit>
```

将 `<feature-commit>` 替换为本切片的完整 SHA 或唯一短 SHA。
