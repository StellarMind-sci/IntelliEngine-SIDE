# 双消费者差分门禁运行手册

## 目的与边界

本门禁分别以子进程启动 TypeScript 与 Python conformance consumer。runner 不导入任何
consumer，也不把其中一个实现作为权威；语言无关 profile、lock、fixtures 和每个 case 的
`expected` 投影是唯一机器事实。

门禁会独立执行以下检查：

- 严格解析 UTF-8、无 BOM 的 NDJSON，拒绝重复键、非法 JSON 和非封闭字段；
- 要求双方各输出 24 个唯一且完整的 case，并验证状态组合、摘要、issues 和 work units；
- 对机器 expected 和双方结果分别重新做 JCS，再逐 case、逐字段比较；
- 即使双方同步产生相同错误结果，只要偏离 machine expected 仍会失败；
- 在启动 consumer 前检查 lock 闭包、安全相对路径、未锁文件和外部 `$ref`；
- consumer crash、超时、成功时写 stderr、缺失/重复/额外 case 都产生稳定基础设施错误码；
- 失败报告只包含 `code`、`consumer` 和最小 `path`，不会输出 fixture payload。

## 本地运行

在仓库根目录使用 Python 3.12 和 Node 24：

```powershell
python -B tests/conformance/test_differential.py
python -B scripts/conformance/differential.py `
  --profile-root packages/cognitive-ir/contracts/profile/1.0.0 `
  --node node
```

成功或失败均只向 stdout 输出一个封闭报告对象；成功示例：

```json
{"case_count":24,"issues":[],"profile_version":"1.0.0","report_version":"1.0.0","status":"passed"}
```

失败时仍只输出一行脱敏 JSON，并以状态 1 退出；参数或配置用法错误由命令行解析器以状态 2
退出。例如：

```json
{"case_count":24,"issues":[{"case_id":"case-id","code":"conformance.result_mismatch","consumer":"typescript","details_sha256":"...","path":"/case-id","status":"expected_mismatch"}],"profile_version":"1.0.0","report_version":"1.0.0","status":"failed"}
```

## 稳定错误类别

- `conformance.result_mismatch`：consumer 与 machine expected 或双方结果不一致。
- `conformance.consumer_crashed` / `consumer_timeout`：子进程退出、stderr、超时或输出上限失败。
- `conformance.output_invalid`：输出不是严格的单行 JSON 序列或不符合封闭投影。
- `conformance.fixture_set_mismatch`：case 集合缺失、重复或含额外项。
- `conformance.offline_boundary_violation`：路径、lock 闭包或外部引用门禁失败。

## CI 与回滚

Linux 和 Windows CI 均使用标准库运行，不执行 `npm install`、`pip install` 或其他网络依赖安装。
workflow 会先运行 profile verifier 和两套 consumer 自身测试，再运行 runner 测试与真实差分。
checkout 和工具链 setup 可以使用 GitHub Actions 基础设施；conformance 执行阶段会清理 Node
注入环境、启用 pip/npm offline 标志并把代理指向不可用本地端口。这是依赖与资源读取门禁，
不是操作系统级 socket 沙箱，不能声称可监控任意恶意子进程。首次产品发布前还必须由
[Issue #22：OS 级 conformance 子进程沙箱](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/22)
增加 OS sandbox 门禁；该 Issue 是首次发布的阻断项。

若 runner 本身出现缺陷，回滚本 Issue 的 workflow、runner、测试和本文档即可；不得通过修改
portable profile、fixtures 或任一 consumer 来规避差分失败。差异应先最小化到 case ID 和字段
路径，再在独立 consumer 或契约 Issue 中修复。
