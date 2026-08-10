# ADR-0006：M1 公共契约工具链与跨语言一致性基线

- 状态：已接受
- 日期：2026-08-10
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-002：M1 公共契约工具链与跨语言一致性基线](../rfc/0002-m1-contract-toolchain-and-conformance.md)、[GitHub Issue #7](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/7)、[GitHub Issue #9](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/9)

## 背景

M1 将依次稳定 11 个公共契约。若每个契约或语言实现自行选择 JSON 解析、Schema 求值、正则、
资源预算、诊断和 fixture 规则，同一输入可能在不同消费者中得到不同有效性、摘要或错误结果，
第三方库的默认行为也可能意外成为事实标准。ADR-0003 要求公共契约及其契约测试先合并，
ADR-0005 又要求 CognitiveNode 使用可移植 JSON Schema profile、确定性资源边界和至少两个
独立消费者，因此必须先固化一套语言无关、可差分验证的 M1 基线。

产品负责人于 2026-08-10 接受 RFC-002“产品负责人决策”表中的全部九项推荐值。本 ADR 只固化
这些工具链与一致性决定，不定义 ProjectPackage、CognitiveNode、KnowledgeUnit、Thoughtflow、
AgentProfile、ControlPolicy、ChangeSet、ProvenanceRecord、DomainPlugin、RuntimeKernel 或
ModelProvider 的领域字段，也不表示 validator、consumer、CI 或任一业务契约已经实现。

## 决定

### 所有权与规范优先级

`packages/cognitive-ir` 拥有语言无关 JSON/JCS 基线、M1 conformance profile、公共诊断和基础
fixtures；各公共契约的 schema 与专属 fixtures 由对应契约模块拥有。TypeScript 主实现、Python
独立次实现和仓库级 differential runner 分别由后续独立 Issue 实现，不得借工具链所有权定义
其他公共契约的领域字段。

规范优先级为：已接受 ADR → 版本化机器工件与 fixtures → 合规实现 → 说明文档。实现代码、
第三方库行为、生成类型、缓存和示例均不得覆盖规范来源；发生冲突时阻断发布并通过独立 Issue
修复。生成器只能写非规范的 `generated` 类工件，不能回写 profile、schema、fixtures 或 lock。

### 已接受的九项选择

1. **TypeScript 主实现与 Python 独立次实现。** TypeScript 提供 Web/Node/packages 的首要开发
   反馈与只读派生产物；Python 服务科研执行平面并作为真正独立的互操作消费者。两者均不是规范
   来源。Python 不得调用、包装或共享 TypeScript validator，TypeScript 也不得以“主实现”身份
   在结果冲突时获得优先权。

2. **语言无关机器工件是唯一机器规范。** 版本化 `profile`、`schemas`、`diagnostics`、
   `fixtures` 和 `lock` 决定有效实例集合与预期规范结果，`generated` 仅是可删除重建的派生物。
   规范 JSON 与实例使用 ADR-0005 的 I-JSON-compatible 数据域和 RFC 8785 JCS UTF-8 规范字节；
   摘要固定为小写十六进制 SHA-256。parser 必须先从原始 bytes 拒绝重复键、非法 UTF-8、BOM、
   非法 escape、未配对 surrogate 和其他歧义，再构建 JSON 值。JCS 对象键按 unsigned UTF-16
   code units 排序；validator 遍历、诊断和 set-like 规范序按 unsigned UTF-8 bytes 排序，二者
   不得合并。lock 不摘要自身，也不包含时间戳、绝对路径、机器名或随机顺序。

3. **受限 JSON Schema 2020-12 与完整 annotation 语义。** 机器 profile 必须穷举 RFC-002 已接受
   的允许/禁止 keyword、精确 binary64 数值语义、固定 keyword ordinal、`$ref` sibling、组合器、
   conditional、`contains` 与 `unevaluated*` 的完整求值及 annotation 传播规则。`format`、content
   关键字和 `x-` 扩展只产生 annotation；失败分支 annotation 丢弃。未知 keyword、动态引用、
   自定义 vocabulary、网络/文件/包搜索、脚本、原生扩展和用户回调均拒绝。任一宿主库只有被
   profile 收紧并通过共同 fixtures 后才能使用，其短路或默认 annotation 行为不具规范权威。

4. **只允许本地结构递降递归，跨资源引用必须是 digest DAG。** 同一 schema resource 内的 local
   JSON Pointer fragment 只有在实例位置严格进入子属性或子数组元素时才可递归；不推进实例位置
   的本地非生产环在 admission 阶段拒绝。跨 resource `$ref` 只能指向锁定的内容摘要 URI，资源
   引用图必须无环；先验证全部摘要并构建只读内存映射，再进行求值，禁止临时 URI、占位摘要、
   外部回退或加载顺序绕过。

5. **正则固定为线性安全 grammar。** `pattern` 和 `patternProperties` 使用 RFC-002 的 Unicode
   scalar、区分大小写、非锚定搜索语义及允许构造；拒绝 backreference、lookaround、私有 escape、
   Unicode property escape、危险嵌套量化等非线性或跨引擎不稳定构造。grammar 必须由机器规则
   解析，匹配复杂度相对 pattern 与 input scalar 数量具有确定性线性上界。正则在 TypeDefinition
   admission 时解析、检查并编译为不展开有界重复的紧凑表示；不能在首次 semantic 匹配时临时
   决定语义或将不支持的合法 pattern 降级为 annotation。

6. **采用确定性 work-unit 与固定 portable 上限。** work unit 表示规范逻辑动作，不是 CPU、
   内存、毫秒或宿主实现计数。admission 与 semantic validation 使用独立计数器，按 RFC-002 的
   固定遍历、预扣、分支、比较、正则和 annotation 规则计数；缓存、并行、短路或 memoization
   不能改变规范计数。schema semantic validation 上限为每对象 **1,000,000 work units**，
   TypeDefinition admission 上限为每定义 **250,000 work units**。下一动作超出预算时不执行、
   不部分扣费且不产生部分对象结论；外部中断、OOM 或宿主取消是 `indeterminate`，不得伪装为
   对象 invalid 或 portable `resource_exhausted`。RFC-002 与 ADR-0005 的其他固定 size/count
   下限同样保持有效。

7. **双消费者规范结果逐项一致。** TypeScript 与 Python 必须分别从相同原始 bytes、profile、
   schemas、bundle、fixtures 和 lock 产生规范结果。runner 对两份结果重新执行 profile 校验与
   JCS，并逐项比较 object/operation 结果、work units、issues、canonical digest 和规范输出；
   任一差异以 `conformance.result_mismatch` 阻断合并。两个实现同时偏离 expected result 仍然
   失败，不能以各自测试通过、多数投票或主实现优先替代差分一致性。

8. **shadow 后才允许显式版本写入。** 新 validator 先在 differential shadow 模式运行，不改变
   提交结论；共同 fixtures、规范投影、安全测试和生成物漂移检查全部通过后，才可经后续门禁
   开放显式 profile/contract 版本写入。不得在首个 consumer 完成时发布写路径，也不得让写入
   自动跟随仓库“最新”版本。shadow 差异只记录合成或脱敏摘要。

9. **major 显式绑定并保留兼容期。** contract major 必须显式锁定受支持的 profile major，未知
   major 拒绝；profile minor 不会自动适用于旧 contract，升级须修改 lock 并完成双消费者回归。
   profile/contract major 升级时，至少一个发布周期同时保留旧 major 的只读校验与新 major 的
   opt-in 写入；移除旧 major 前必须证明无剩余写入依赖，并提供导出、迁移或保持只读路径。

改变以上任一已接受选择，必须先以新 RFC 和替代 ADR 作出决定；实现 Issue 不得临时放宽、重释
或以第三方库限制覆盖这些规则。

### 安全、溯源与控制边界

- parser、canonicalizer、validator、runner、schema、bundle、fixture 和 expected result 均按
  不可信输入处理。conformance 默认断网，只读已锁定仓库文件；禁止 HTTP/文件 `$ref`、包搜索、
  插件发现、脚本和原生回调。依赖必须锁版本并扫描，但依赖版本只是证据，不是有效性输入。
- fixture 禁止真实密钥、凭据、生产数据、用户私有全局 Agent 记忆和受保护原件；安全用例使用
  明显的合成标记。日志只记录 case ID、digest、版本、状态、code、资源桶和最小差异路径，不
  输出完整 opaque payload。业务策略可以在对象已 valid 后更严格地拒绝操作，但不能改写
  portable validity。
- 每次规范变更必须保留关联 Issue/PR、作者、独立审查、旧/新 digest 和可回滚提交；已发布的
  profile、schema、fixture case 与历史 JCS bytes 不得原地覆盖。AI 生成的规范修改同样遵守
  显式权限、来源证据、范围审计和回滚门禁。

### 后续依赖与发布门禁

1. 先以独立 Issue 固化语言无关 profile manifest/schema、keyword ordinal、regex grammar、
   work-unit/limits、fixture manifest、expected result、diagnostics projection 和 lock；在该机器
   契约合并前，不得实现或宣称 portable semantic conformance。
2. 机器契约合并后，TypeScript 与 Python consumers 由不同 Issue 实现；二者可以并行，但必须
   独立读取规范工件，不能共享 validator。
3. 两个 consumers 合并后，以独立 Issue 建立 differential runner、离线安全门禁、生成物漂移
   和兼容矩阵；这些门禁全部通过后，CognitiveNode/TypeDefinition schema 与完整 fixtures 才能
   首先接入并完成跨语言验收。
4. 其余公共契约继续按 ADR-0003 和模块依赖逐项建立 RFC/ADR/schema/fixtures；每个任务最多修改
   一项公共契约，不能借基础设施 PR 定义其领域字段或提前实现使用方。

## 结果

### 收益

- M1 的有效性、摘要、诊断、资源结论和兼容行为由可版本化的语言无关证据决定。
- Web/Node 与 Python/科研执行平面会在产品实现前暴露 Unicode、数字、Schema、regex 和资源计数
  差异，避免单一库成为隐式标准。
- 离线内容寻址、确定性预算、双消费者差分、显式版本和 shadow 发布为安全回滚及后续并行开发
  提供稳定门禁。

### 成本与约束

- 必须维护两套独立实现、共同 fixtures 和差分 runner；完整 annotation 语义、专用 regex parser
  与边界用例提高初期基础设施成本。
- 所有固定上限均须有 `limit-1`、`limit`、`limit+1` 证据；任何优化都必须保持规范结果与计数。
- 在机器 profile、双消费者和差分 CI 合并前，M1 的 11 个业务公共契约均不能宣称获得 portable
  validator，使用方也不能绕过契约优先门禁并行实现。

### 回滚

- 机器契约未发布时，可回退对应 PR 并重新生成 lock，但不得修改已发布 tag。
- consumer 缺陷而规范未变时，回滚 consumer 或 feature flag，继续使用上一 conforming 版本，
  并把最小化失败 fixture 保留为回归证据。
- 规范本身有缺陷时，冻结写入，保留旧 major 只读能力，通过新 RFC/ADR 与新 profile/contract
  版本修复并建立显式迁移；不得改写已发布 schema、fixture 或历史规范 bytes。
- 安全漏洞时立即关闭受影响的写入或导出能力并保持只读隔离，修复仍须通过双消费者与安全回归。

## 验证

- `python scripts/verify_governance.py` 必须通过；该检查只证明 ADR 命名和仓库治理结构，不证明
  九项技术语义已由代码实现。
- 本 ADR 的状态、日期、RFC/Issue 链接、九项一一映射、所有权、安全、溯源、依赖和回滚由本
  任务人工核对并接受独立审查；不得用 RFC 文本存在代替 ADR 映射审查。
- 后续机器契约须自校验规范 JSON、profile、schema、diagnostics、fixtures 和 lock，并提供 JCS、
  Unicode/数字、完整 annotation、digest DAG、本地递归、regex、固定预算及安全边界的正负用例。
- 每个固定资源上限须有 `limit-1`、`limit`、`limit+1`；TypeScript/Python 必须逐项输出相同规范
  投影，生成物重建无 diff，离线访问检测和旧/新 major 兼容矩阵通过。
- CognitiveNode 仍须单独落实 ADR-0005 的 schema 与完整 fixtures；其他十个公共契约也须各自
  通过契约审查和消费者测试，本 ADR 不构成其字段或实现验收。
