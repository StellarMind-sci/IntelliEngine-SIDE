# 线性方程模型预览验收

## 前置条件

- 在仓库根目录 `E:\Projects\IDE` 执行命令。
- 需要 Node.js 24（`node --version` 应显示 `v24.x`）。
- 本预览只读取仓库内固定的 `fixtures/demo-cases.json`；CLI 不写文件。下面的 PowerShell 重定向由操作者创建临时 HTML 文件。

## 可复现验收

### Ready：生成模型建议

```powershell
node plugins/math/linear-equation-preview/cli.ts --case ready --format html > $env:TEMP\side-preview-ready.html
Start-Process $env:TEMP\side-preview-ready.html
```

预期：浏览器页面显示 `mode: preview`、`side_effects: forbidden`、工程状态 `ready`、方程 `2*x + 3 = 11`、解 `x = 4`、关联的 operation/verification 步骤、SymPy 建议和断言 `2 * 4 + 3 == 11`。页面明确说明建议未执行。

### Blocked：展示前置缺失，不生成建议

```powershell
node plugins/math/linear-equation-preview/cli.ts --case blocked --format html > $env:TEMP\side-preview-blocked.html
Start-Process $env:TEMP\side-preview-blocked.html
```

预期：页面以阻断样式显示 `blocked`、`equality-transformations-unit@1` 位于“缺失前置”，并显示受影响的 operation/verification 步骤。页面不出现 SymPy 代码或 `from sympy import`。

### Empty：没有可编译行为

```powershell
node plugins/math/linear-equation-preview/cli.ts --case empty --format html > $env:TEMP\side-preview-empty.html
Start-Process $env:TEMP\side-preview-empty.html
```

预期：页面以空状态样式显示 `empty` 和“没有可编译的线性方程行为”，不猜测无关 Thoughtflow 步骤，也不出现 SymPy 代码。

## 异常场景

```powershell
node plugins/math/linear-equation-preview/cli.ts --case missing --format html
$LASTEXITCODE
node plugins/math/linear-equation-preview/cli.ts --case ready --format text
$LASTEXITCODE
```

预期：第一条命令退出非零并只向 stderr 输出 `unknown demo case: missing`；第二条退出非零并只向 stderr 输出 `unknown output format: text`。两条命令均不向 stdout 写入预览。

## 截图方法

分别打开三个临时 HTML 文件后，使用 Windows 的 `Win+Shift+S` 截取整个可见预览页。每张截图应保留标题、`mode`、`side_effects`、工程状态和相应主体内容：ready 的 SymPy 建议、blocked 的缺失前置、empty 的空状态说明。浏览器不可用时，可保存 CLI 的完整 HTML stdout 作为替代视觉证据，并记录未能截屏的环境原因。

## 自动化证据

```powershell
node --test plugins/math/linear-equation-preview/tests/render-cli.test.ts
node --test plugins/math/linear-equation-preview/tests/*.test.ts
node plugins/math/linear-equation-preview/cli.ts --case ready --format json
node plugins/math/linear-equation-preview/cli.ts --case blocked --format html
node plugins/math/linear-equation-preview/cli.ts --case empty --format html
python scripts/verify_governance.py
node --test packages/thoughtflow/tests/ts/*.test.ts
```

预期：测试通过；ready JSON 含 `proposal`；blocked 与 empty HTML 不含 `from sympy import`；治理检查通过。

## 已知限制

此页面仅是只读模型预览，不是 Python 执行、SymPy 验证结果或用户掌握证据。它不调用 Python、SymPy、Agent、网络、数据库或外部工具，不注册 Plugin SDK，也不读取 CLI 参数指定的任意文件。只有 `ready` 可展示代码建议；`blocked`、`needs_evidence`、`empty` 和 `invalid_input` 不展示建议。

## 回滚

该切片没有持久化状态、迁移或外部调用。若需要撤回已提交功能，在确认目标提交后执行：

```powershell
git revert <feature-commit>
```

将 `<feature-commit>` 替换为本功能提交的完整 SHA 或唯一短 SHA。
