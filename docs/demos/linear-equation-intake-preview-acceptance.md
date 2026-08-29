# 线性方程文本摄入预览验收

## 用户能力与边界

用户可从固定纯文本示例离线查看原文、受限格式的来源引用、规范化的一元一次方程，以及已经过 CognitiveNode 传输与语义校验的**未持久化候选节点**。每张页面固定标识 `mode: preview` 与 `side_effects: forbidden`，并明确说明“候选尚未写入工程”。

预览只接受固定 CLI fixture，不接受、读取或解析用户指定文件，也不支持 DOCX、图片或通用数学文本导入；来源引用只接受 `prov:<kind>:<identifier>[:<identifier>...]`，不接受任意 provenance 字符串。为以真实 CognitiveNode public contract 验证候选，插件会从自身固定推导的仓库路径只读锁定 schema 与 math type definition，但不接受任意路径。它不执行代码或模型，不写入工程，不联网，不调用 Agent 或 ChangeSet。本功能是受限一元一次方程 parser 的展示，不是通用数学提取器。

## 前置条件与验收入口

- 在仓库根目录 `E:\Projects\IDE` 执行命令。
- 使用 Node.js 24：`node --version` 应显示 `v24.x`。其他本机版本可以用于页面检查，但不能替代正式 Node 24 CI。
- CLI 只读取仓库内固定的 `fixtures/demo-cases.json`，并向 stdout 输出 HTML；候选验证还会从插件内部固定推导的路径只读锁定 CognitiveNode schema 与 math type definition，均不接受任意文件路径。下面的 PowerShell 重定向仅由验收者在临时目录生成静态页面。

## 四态操作与预期

### Ready：规范方程与有效候选

```powershell
node plugins/math/linear-equation-intake-preview/cli.ts --case ready --format html > $env:TEMP\linear-equation-intake-ready.html
Start-Process $env:TEMP\linear-equation-intake-ready.html
```

预期：页面显示 `state: ready`、原文 `2x + 3 = 11`、来源 `prov:source:algebra-example-1`、规范方程 `2*x + 3 = 11`、变量 `x` 与有效候选 CognitiveNode（含 `id`、type、data、provenance）。页面始终显示“候选尚未写入工程”。

### Empty：空白原文不生成候选

```powershell
node plugins/math/linear-equation-intake-preview/cli.ts --case empty --format html > $env:TEMP\linear-equation-intake-empty.html
Start-Process $env:TEMP\linear-equation-intake-empty.html
```

预期：页面显示 `state: empty` 和“输入为空。”；原文与来源仍可查看，规范方程与变量均为“无”，且没有 candidate 节点详情。

### Invalid：受限 parser 封闭拒绝

```powershell
node plugins/math/linear-equation-intake-preview/cli.ts --case invalid --format html > $env:TEMP\linear-equation-intake-invalid.html
Start-Process $env:TEMP\linear-equation-intake-invalid.html
```

预期：页面显示 `state: invalid_input`；原文 `x^2 = 4` 和来源可追查，但不出现规范方程、变量或 candidate 节点详情。它只表示该固定 parser 不支持此输入，不评价数学问题本身。

### Negative：合法负系数与常数

```powershell
node plugins/math/linear-equation-intake-preview/cli.ts --case negative --format html > $env:TEMP\linear-equation-intake-negative.html
Start-Process $env:TEMP\linear-equation-intake-negative.html
```

预期：页面显示 `state: ready`、原文 `-x - 4 = 0`、来源 `prov:source:negative-example`、规范方程 `-1*x - 4 = 0` 和有效候选节点，证明合法负系数与常数不是异常输入。候选仍未写入工程。

## 异常场景

```powershell
node plugins/math/linear-equation-intake-preview/cli.ts --case missing --format html
$LASTEXITCODE
node plugins/math/linear-equation-intake-preview/cli.ts --case __proto__ --format json
$LASTEXITCODE
node plugins/math/linear-equation-intake-preview/cli.ts --case ready --format text
$LASTEXITCODE
```

预期：三条 CLI 命令均为非零退出，stdout 均为空；stderr 依次精确为 `unknown demo case: missing`、`unknown demo case: __proto__`、`unknown output format: text`。异常输入不会接受或读取用户指定文件，也不会触发工程写入。

## 自动化与视觉证据

```powershell
node --test plugins/math/linear-equation-intake-preview/tests/*.test.ts
node --test packages/cognitive-ir/tests/ts/*.test.ts
python scripts/verify_governance.py
```

专属 [Linear Equation Intake Preview workflow](../../.github/workflows/linear-equation-intake-preview.yml) 在 Ubuntu 与 Windows 的 Node.js 24 上运行完整插件测试。下列 HTML 均由当前 CLI stdout 生成并逐字节核验；PNG 由无网络的本地无头浏览器渲染，覆盖正常、负系数、空和错误状态：

- Ready：[HTML](artifacts/linear-equation-intake-preview/ready.html)；[PNG](artifacts/linear-equation-intake-preview/ready.png)
- Negative：[HTML](artifacts/linear-equation-intake-preview/negative.html)；[PNG](artifacts/linear-equation-intake-preview/negative.png)
- Empty：[HTML](artifacts/linear-equation-intake-preview/empty.html)；[PNG](artifacts/linear-equation-intake-preview/empty.png)
- Invalid：[HTML](artifacts/linear-equation-intake-preview/invalid.html)；[PNG](artifacts/linear-equation-intake-preview/invalid.png)

## 已知限制与回滚

此切片只解析固定 CLI fixture 中的受限一元一次方程文本；它不是文件导入、OCR、DOCX/图片解析或一般数学语言理解，也不替代用户确认或工程执行。候选节点仅在内存中生成，CognitiveNode 校验成功不等于已写入工程。

该切片没有迁移、用户数据或外部调用。若需要撤回已提交功能，在确认目标提交后执行：

```powershell
git revert <feature-commit>
```

将 `<feature-commit>` 替换为本功能提交的完整 SHA 或唯一短 SHA。