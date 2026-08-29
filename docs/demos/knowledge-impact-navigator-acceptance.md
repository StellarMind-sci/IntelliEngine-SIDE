# KnowledgeUnit 工程影响导航预览验收

## 前置条件

- 在仓库根目录 `E:\Projects\IDE` 执行命令。
- 使用 Node.js 24（`node --version` 应显示 `v24.x`）。
- CLI 只读取仓库内固定的 demo fixture；它只向 stdout 输出 JSON 或 HTML，不写入工程状态、证据、ChangeSet 或用户数据。下面的 PowerShell 重定向由操作者创建临时 HTML 文件。

## 可复现验收

以下命令均可在浏览器中打开五态只读预览。每个页面都应显示 `mode: preview`、`side_effects: forbidden`、`state`，以及“仅导航提示，不执行、不写入”。

### Blocked：前置知识阻断

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case blocked --format html > $env:TEMP\knowledge-impact-blocked.html
Start-Process $env:TEMP\knowledge-impact-blocked.html
```

预期：红色 `blocked` 状态；显示缺失前置 `10000000-0000-4000-8000-000000000011@1`、`a-operation` 与 `z-analysis`，并只给出返回前置知识的只读导航。

### Needs evidence：验证证据缺口

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case needs-evidence --format html > $env:TEMP\knowledge-impact-needs-evidence.html
Start-Process $env:TEMP\knowledge-impact-needs-evidence.html
```

预期：紫色 `needs_evidence` 状态；显示缺失证据 `20000000-0000-4000-8000-000000000001@1` 和 `verification-evidence`，并只给出返回 verification 的只读导航。

### Ready：没有待处理工程影响

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case ready --format html > $env:TEMP\knowledge-impact-ready.html
Start-Process $env:TEMP\knowledge-impact-ready.html
```

预期：绿色 `ready` 状态；明确显示“没有待处理的工程影响，不伪造下一步”，不显示只读导航。

### Empty：没有关联步骤

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case empty --format html > $env:TEMP\knowledge-impact-empty.html
Start-Process $env:TEMP\knowledge-impact-empty.html
```

预期：灰色 `empty` 状态；明确显示没有待处理工程影响，不推测无关 Thoughtflow 步骤，也不显示只读导航。

### Invalid：输入封闭

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case invalid --format html > $env:TEMP\knowledge-impact-invalid.html
Start-Process $env:TEMP\knowledge-impact-invalid.html
```

预期：橙色 `invalid_input` 状态；说明输入或上游投影无效，预览封闭且不生成导航。

## 异常场景

```powershell
node plugins/math/knowledge-impact-navigator/cli.ts --case missing --format html
$LASTEXITCODE
node plugins/math/knowledge-impact-navigator/cli.ts --case __proto__ --format json
$LASTEXITCODE
node plugins/math/knowledge-impact-navigator/cli.ts --case ready --format text
$LASTEXITCODE
```

预期：三条命令均退出非零、stdout 为空，stderr 依次精确为 `unknown demo case: missing`、`unknown demo case: __proto__`、`unknown output format: text`。CLI 不读取任意用户指定文件，也不会创建文件。

## 持久化视觉证据

以下 HTML 由当前 CLI 的只读 stdout 生成；PNG 由无网络的本地无头浏览器全页渲染。它们覆盖正常、阻断、空与异常状态：

- Blocked：[HTML](artifacts/knowledge-impact-navigator/blocked.html)；[PNG](artifacts/knowledge-impact-navigator/blocked.png)
- Needs evidence：[HTML](artifacts/knowledge-impact-navigator/needs-evidence.html)；[PNG](artifacts/knowledge-impact-navigator/needs-evidence.png)
- Ready：[HTML](artifacts/knowledge-impact-navigator/ready.html)；[PNG](artifacts/knowledge-impact-navigator/ready.png)
- Empty：[HTML](artifacts/knowledge-impact-navigator/empty.html)；[PNG](artifacts/knowledge-impact-navigator/empty.png)
- Invalid：[HTML](artifacts/knowledge-impact-navigator/invalid.html)；[PNG](artifacts/knowledge-impact-navigator/invalid.png)

## 自动化证据

```powershell
node --test plugins/math/knowledge-impact-navigator/tests/*.test.ts
node --test packages/thoughtflow/tests/ts/*.test.ts
python scripts/verify_governance.py
node plugins/math/knowledge-impact-navigator/cli.ts --case blocked --format json
node plugins/math/knowledge-impact-navigator/cli.ts --case needs-evidence --format html
node plugins/math/knowledge-impact-navigator/cli.ts --case ready --format json
node plugins/math/knowledge-impact-navigator/cli.ts --case empty --format html
node plugins/math/knowledge-impact-navigator/cli.ts --case invalid --format json
```

预期：插件、Thoughtflow 与治理检查全部通过。专属 [Knowledge Impact Navigator workflow](../../.github/workflows/knowledge-impact-navigator.yml) 在 Ubuntu 与 Windows 的 Node.js 24 上运行完整插件测试集；本机不是 Node 24 时，本地结果不替代正式 CI 证据。

## 已知限制

这是只读导航预览，不执行或控制 Thoughtflow，也不是个人掌握度、Agent 操作、模型执行、Python/SymPy 验证或状态写入。它仅消费固定 demo fixture 和既有 impact runtime 的结果；不访问网络、数据库、外部工具或 Plugin SDK。

## 回滚

本切片不包含持久化状态、迁移或外部调用。若需要撤回已提交功能，确认目标提交后执行：

```powershell
git revert <feature-commit>
```

将 `<feature-commit>` 替换为此功能提交的完整 SHA 或唯一短 SHA。
