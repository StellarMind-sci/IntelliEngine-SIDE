# RFC-002：M1 公共契约工具链与跨语言一致性基线

- 状态：已接受
- 负责人：StellarMind-sci（Issue #7 assignee）
- 创建日期：2026-08-10
- 决定日期：2026-08-10
- 关联 Issues：[GitHub Issue #7](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/7)
- 依赖：[ADR-0003：先稳定契约，再并行实现使用方](../adr/0003-contract-first-parallelism.md)、[ADR-0005：CognitiveNode 与学科扩展契约](../adr/0005-cognitive-node-and-domain-extension-contract.md)

## 摘要

M1 将依次稳定 11 个公共契约。如果没有统一的规范数据、Schema profile、资源预算、诊断、
fixtures 和跨语言验证方式，各模块即使都声称使用 JSON Schema 2020-12，也可能对同一输入给出
不同结论。本 RFC 建议：

1. 采用 **TypeScript 主实现 + Python 独立次实现**；两者都不是规范来源。
2. 以版本化的语言无关 schema、profile manifest、预算规则和 fixtures 作为唯一机器事实。
3. 复用 ADR-0005 已接受的 I-JSON-compatible 数据域与 RFC 8785 JCS 规范字节。
4. 固定受限 JSON Schema 2020-12 profile、离线 digest `$ref`、线性 regex 子集和确定性
   work-unit 计数。
5. 每项公共契约至少由两个独立消费者运行相同 fixtures，并在 CI 中比较规范结果。

本 RFC 只决定 M1 的契约工具链和一致性基线，不定义 11 个公共契约的领域字段，也不实现
validator、运行时、UI、插件或业务逻辑。

## 问题

### 当前工程问题

仓库已决定公共契约及其契约测试先合并，再并行实现使用方；CognitiveNode 又进一步接受了
canonical JSON/JCS、受限 JSON Schema、离线 digest bundle、结构化诊断和跨语言 fixtures。
但仓库尚未决定：

- M1 用哪种语言编写首个可执行契约工具，以及第二个独立消费者是什么；
- 哪些语言无关文件才是规范来源，怎样防止生成物反向覆盖规范；
- 受限 JSON Schema 2020-12 profile 的允许关键字、求值顺序和禁止项；
- regex、`$ref`、组合器和集合比较如何获得跨实现一致的资源预算；
- fixtures 如何表达输入、预期结果、规范字节、摘要和诊断；
- 怎样证明两个实现得到相同结果，而不是分别通过两套自有测试；
- 兼容变化、迁移、发布、回滚和安全门禁怎样进入 CI。

如果这些问题留给每个契约实现临时决定，会出现三个风险：同一实例在不同语言中有效性不同，
资源耗尽被错误报告为对象无效，以及某一实现的库行为悄悄升级成事实标准。

### 仓库事实

- 产品首阶段 Web 优先，执行平面首期为隔离 Python/Jupyter。
- `packages/*` 负责语言无关公共契约和确定性领域逻辑，不依赖应用 UI 或部署基础设施。
- `packages/cognitive-ir` 拥有 CognitiveNode、TypeDefinition 及其通用扩展规则。
- ADR-0003 要求公共契约与契约测试先合并，再并行实现使用方。
- ADR-0005 已接受 RFC 8259 I-JSON-compatible profile、RFC 8785 JCS、有限 binary64、
  safe integer、受限 JSON Schema 2020-12、离线 digest bundle、线性 regex、稳定诊断和
  至少两个独立消费者。
- 当前没有已发布的 M1 schema、validator、需要原地迁移的公共契约数据或生产兼容承诺。

### 假设

- M1 的机器契约以 UTF-8 JSON 和 JSON Schema 表达，Markdown 只解释设计，不替代机器文件。
- TypeScript 工具主要服务 Web IDE、Node CI 和 packages；Python 工具主要服务科研/执行平面并
  充当真正独立的互操作消费者。
- 两种实现可以选用不同底层库，但库行为必须被本 profile 收紧，不能成为隐式规范。
- CI 可以在无网络的 conformance 步骤中运行 Node 与 Python。

这些假设在本 RFC 接受前不是长期事实。

## 目标与非目标

### 目标

1. 选定 M1 的主实现、独立次实现及各自职责。
2. 定义语言无关机器契约的唯一事实来源、目录类别、版本和锁定方式。
3. 为 canonical JSON/JCS、Schema profile、digest 引用和 regex 固定可实现边界。
4. 定义与机器速度无关的 work-unit 计数和 portable 资源预算。
5. 定义稳定诊断、fixture 格式和双消费者一致性判定。
6. 给出 CI、安全、兼容、迁移、发布、可观测性与回滚门槛。
7. 把后续工作拆成单 Issue、单 PR、可独立验收的任务。

### 非目标

- 不定义 ProjectPackage、CognitiveNode、KnowledgeUnit、Thoughtflow、AgentProfile、
  ControlPolicy、ChangeSet、ProvenanceRecord、DomainPlugin、RuntimeKernel 或 ModelProvider 的
  领域字段。
- 不修改 ADR-0005 的 CognitiveNode/TypeDefinition 语义、错误码或安全边界。
- 不实现 JSON parser、canonicalizer、schema validator、CLI、Python 包或 TypeScript 包。
- 不决定 UI、数据库、网络 API、模型提供商、Agent 行为或沙箱实现。
- 不允许任一语言库、生成代码或 wall-clock timeout 成为 portable validity 规则。
- 不承诺 M1 之外任意语言都是正式消费者；新增语言须通过同一 conformance 门槛。

## 术语

- **机器契约**：可由程序读取、版本化并受测试保护的 schema、profile、预算规则、诊断目录和
  fixture manifest。
- **规范来源（normative source）**：决定有效实例集合和预期结果的语言无关文件。
- **主实现**：首先提供开发者反馈、生成只读派生产物和运行大多数 packages 测试的实现；
  不拥有修改规范的特权。
- **独立次实现**：不调用主实现代码、不过桥到同一 validator 的第二消费者。
- **portable-valid**：在规范 profile 与预算内，所有 conforming consumers 必须给出相同
  对象结论的输入。
- **work unit**：由机器契约按逻辑求值动作计数的确定性预算单位，不代表 CPU 指令或毫秒。
- **锁文件**：记录规范文件路径、适用的 JCS/raw SHA-256、profile/fixture 版本和生成器版本，
  但不记录自身摘要的清单。

## 提案

### 1. 工具链与所有权

采用 **方案 A：TypeScript 主实现 + Python 独立次实现**。

| 内容 | 所有者 | 责任 | 禁止事项 |
|---|---|---|---|
| 语言无关 JSON/JCS 基线与 schema profile | `packages/cognitive-ir` | 维护规范文件、预算规则、公共诊断和基础 fixtures | 不定义其他契约的领域字段 |
| 各公共契约 schema 与 fixtures | 对应契约模块 | 维护本契约实例、诊断和消费方测试 | 不复制或放宽基础 profile |
| TypeScript conformance 实现 | 对应后续 tooling Issue | 主开发反馈、Node CI、只读代码生成 | 不回写或“修正”规范输入 |
| Python conformance 实现 | 对应后续 tooling Issue | 独立解析、校验、JCS、摘要和差分验证 | 不导入/调用 TypeScript 实现或共享原生 validator |
| CI differential runner | 仓库级 CI | 对同一 fixture 比较规范结果 | 不以“两个都成功退出”替代结果比较 |

规范优先级为：已接受 ADR → 版本化机器契约与 fixtures → 兼容实现 → 说明文档。实现代码、
第三方库默认行为、生成类型和示例都不得反向覆盖机器契约。Markdown 与机器事实冲突时阻断发布，
由独立 Issue 修复；不得由 runner 猜测哪一方正确。

### 2. 规范工件类别

后续实现 Issue 应建立以下类别，最终目录名可按模块规则落位，但语义不得改变：

| 类别 | 内容 | 是否规范 |
|---|---|---|
| `profile` | JSON 数据域、允许 keyword、求值规则、work-unit 表、资源上限 | 是 |
| `schemas` | 每个公共契约的版本化 JSON Schema | 是 |
| `diagnostics` | 稳定 code、severity、适用阶段和合法状态对 | 是 |
| `fixtures` | 输入 bytes、依赖 bundle、预期规范结果和边界用例 | 是 |
| `lock` | 除 lock 自身外，上述文件的 JCS/raw SHA-256、版本和依赖闭包 | 是 |
| `generated` | TypeScript/Python 类型、索引、文档或缓存 | 否，可删除重建 |

规范 JSON 文件必须自身通过同一 JSON 数据 profile。唯一例外是专门测试无效 UTF-8、重复键、
非法 JSON、BOM、非法 escape 或 surrogate 的 parser-negative **原始输入 bytes**；这些输入不是
规范 JSON 工件，由合法的 case manifest 以 raw SHA-256 锁定。锁文件只覆盖规范文件和这些 raw
输入，不包含 lock 自身、时间戳、绝对路径、机器名或随机顺序，因此不存在自摘要递归。lock 的
JCS SHA-256 可记录在 release metadata、Git tag/commit 或上级发布清单中，但不得写回被摘要的
lock。任何生成命令都必须可重复；CI 重新生成后出现 diff 即失败。

profile、fixture set 和每个公共 contract 分别使用 canonical `MAJOR.MINOR.PATCH`。profile major
进入每个 contract manifest 的显式依赖；consumer 不得按“仓库最新版本”隐式选择 profile。

### 3. Canonical JSON 与 JCS

所有规范 JSON、实例 fixture、预期结构化结果、schema resource 和 lock manifest 采用
ADR-0005 的数据域：

1. 无 BOM UTF-8；任意嵌套层重复键、无效 UTF-8、非法 escape、未配对 surrogate 均拒绝。
2. 字符串是 Unicode scalar value 序列，不执行 NFC/NFD 等 normalization。
3. JSON number 必须是有限 IEEE-754 binary64；整数限制为
   `[-9007199254740991, 9007199254740991]`。超长整数及任意精度小数由契约显式使用 canonical
   十进制字符串或结构表示。
4. 规范字节使用 RFC 8785 JCS UTF-8 bytes；对象键按 JCS 的 unsigned UTF-16 code units 排序，
   普通数组保持顺序。
5. 摘要固定为小写十六进制 SHA-256。schema resource URI 固定为
   `urn:intelliengine:schema:sha256:<64-lowercase-hex>`。
6. parser 必须先拒绝有歧义的原始 bytes，再构建 JSON 值；不能先交给会丢失重复键信息的普通
   object parser。

两个消费者必须分别从原始 fixture bytes 开始执行，不能共享已解析对象。JCS 输出比较使用原始
bytes 或 lowercase SHA-256，不以宿主对象深比较替代。

这里刻意存在两种不同排序：JCS canonicalization 严格按 RFC 8785 的 unsigned UTF-16 code
units 排对象键；validator 为了确定求值、诊断聚合和 set-like 数组顺序，继续按 ADR-0005 的
unsigned UTF-8 bytes 排序。实现不得为了复用一个 comparator 而合并二者。fixtures 必须包含
astral-vs-BMP 对照，例如键 U+1F600 与 U+E000：JCS/UTF-16 中前者在先，而 validator/UTF-8
遍历与诊断序中后者在先，并分别断言 bytes、摘要、work units 和 issues 顺序。

只有成功解析且通过本 JSON 数据 profile 的 JSON 值才有 JCS bytes/JCS SHA-256。parser-negative
输入只记录原始 bytes 的 SHA-256，expected result 不允许伪造 `jcs_sha256`；其合法 manifest、
expected result 和 lock 本身仍须通过规范 JSON 自校验。

### 4. 受限 JSON Schema 2020-12 profile

#### 4.1 允许范围

schema 根必须是 object schema，`$schema` 精确等于
`https://json-schema.org/draft/2020-12/schema`。允许的标准关键字为：

- Core：`$schema`、`$ref`、`$defs`、`$comment`；
- Applicator：`allOf`、`anyOf`、`oneOf`、`not`、`if`、`then`、`else`、`dependentSchemas`、
  `prefixItems`、`items`、`contains`、`properties`、`patternProperties`、`additionalProperties`、
  `propertyNames`、`unevaluatedItems`、`unevaluatedProperties`；
- Validation：`type`、`enum`、`const`、`multipleOf`、`maximum`、`exclusiveMaximum`、`minimum`、
  `exclusiveMinimum`、`maxLength`、`minLength`、`pattern`、`maxItems`、`minItems`、`uniqueItems`、
  `maxContains`、`minContains`、`maxProperties`、`minProperties`、`required`、
  `dependentRequired`；
- Annotation：`title`、`description`、`default`、`deprecated`、`readOnly`、`writeOnly`、
  `examples`、`format`、`contentEncoding`、`contentMediaType`、`contentSchema`。

`format` 和 content 关键字只产生 annotation，不参与有效性。允许名称以 `x-` 开头的未知
annotation，其值按普通 JSON 数据无损保留且不扫描其中的 schema-like 字段。其他未知 keyword
或 vocabulary 一律拒绝。

#### 4.2 禁止范围

- 禁止 `$id`、`$anchor`、`$dynamicRef`、`$dynamicAnchor`、相对 URI、HTTP(S)、文件、包或环境
  搜索；
- `$ref` 只允许本 schema 内 JSON Pointer fragment，或锁定 bundle 中的 digest URI；
- 禁止自定义 meta-schema、`$vocabulary`、Format-Assertion 和实现私有 keyword；
- 禁止执行脚本、原生扩展、用户回调、网络和文件读取；
- schema boolean 值允许作为 subschema；schema 文档根仍必须是 object；
- 对 binary64 数值断言按其精确有限二进制值比较；`multipleOf` 采用两个 binary64 值对应的精确
  有理数运算，不使用 epsilon、decimal context 或宿主浮点余数。

#### 4.3 引用与递归

validator 必须先验证 bundle 摘要并构建完整只读内存映射，再开始 schema 求值。缺失 resource、
摘要不匹配、重复 URI 对应不同 bytes 或 profile 外引用在注册阶段拒绝，绝不回退外部查找。

只有**同一 schema resource 内的 local JSON Pointer fragment**可以形成结构递降递归：每次回到
同一 schema location 前，instance location 必须严格进入子属性或子数组元素。只在本地 schema
locations 间循环且不推进 instance location 的非生产环在 admission 阶段拒绝。求值键使用
`(schema_digest, schema_pointer, instance_pointer)`；同一键在当前调用栈再次出现表示非生产环，
而不是自动视为 valid。

跨 resource digest 引用图必须是 DAG，禁止任何跨 resource cycle。原因是 resource URI 包含其
JCS bytes 的摘要；两个 resource 若在内容中互相写入对方最终 digest，会形成不可构造、不可验证
的内容寻址固定点。validator 先验证每项 digest，再按 URI UTF-8 bytes 顺序构图和检查 DAG；
不能用临时 URI、占位 digest 或加载顺序绕过。fixtures 必须覆盖有效跨 resource DAG、本地对象/
数组结构递降递归、本地非生产环拒绝，以及试图构造跨 resource 环时至少一个 digest 必然不匹配
并在构图/求值前拒绝；不得宣称存在“有效跨 bundle 环”fixture。

#### 4.4 2020-12 求值与 annotation 规则

本 profile 不采用宿主库的可选短路或 annotation 默认行为，固定如下：

- `$ref` 是普通 applicator；解析并求值目标后，同一 schema object 的所有 sibling keywords 仍按
  ordinal 继续求值。`$ref` 不能替换整个 schema object，也不能隐藏 sibling assertion。
- annotation 只从**成功的 schema evaluation**向父级传播。失败 schema 自身及其后代产生的
  annotation 全部丢弃；诊断不是 annotation，不受此规则影响。
- `allOf` 求值全部分支；仅全部成功时合并全部分支 annotation。`anyOf` 求值全部分支，至少一个
  成功时合并所有成功分支 annotation，失败分支丢弃。`oneOf` 求值全部分支，恰好一个成功时只
  保留该分支 annotation；零个或多个成功时不传播 annotation。
- `not` 总是丢弃其 subschema 的全部 annotation。`if` 必须求值；成功时传播 `if` subschema 的
  annotation 并只求值/传播成功的 `then`，失败时丢弃 `if` annotations 并只求值/传播成功的
  `else`。缺少所选分支等价于成功的空 schema 且不产生 annotation。
- 成功的 `properties`、`patternProperties` 和 `additionalProperties` 分别产生实际应用且成功
  校验的 property-name set；同一属性可被前两者同时求值，但集合去重。`unevaluatedProperties`
  在全部其他相邻 applicators 及成功分支 annotation 合并后最后运行，只处理仍未被标记的属性；
  它成功后把这些属性加入 evaluated set，失败则其 annotation 丢弃。
- 成功的 `prefixItems` 与 `items` 产生其实际成功求值的 index set。`contains` 必须求值每个数组
  元素，先得到成功 indexes，再用其数量判定默认至少 1 个及显式 `minContains`/`maxContains`；
  只有整体 `contains` 成功时传播该 index set，数量失败时全部丢弃。`unevaluatedItems` 在其他
  相邻 applicators 及成功分支的 index annotation 合并后最后运行；因此失败的 `contains` 不会
  标记任何 index，余下元素仍由 `unevaluatedItems` 求值。
- `dependentSchemas`、`propertyNames` 和普通 schema-valued applicator 只传播成功 subschema 的
  annotation。多个 annotation 值的组合按 2020-12 对应 keyword 规则；内部 evaluated name/index
  set 去重后分别按 UTF-8 bytes/数值升序规范化，不能使用对象输入顺序。
- `contentSchema` 的值必须递归通过 schema admission，但 content vocabulary 仍只作 annotation，
  semantic validation 不把解码内容作为新 instance 求值。

以上每一条必须有正/负 fixtures，并断言 validity、传播后的 evaluated sets、issues 和 work
units；尤其覆盖 `$ref` sibling、失败分支 annotation 丢弃、anyOf 多成功、oneOf 多成功、失败
`contains` 配合 `unevaluatedItems`，以及 properties/pattern/additional/unevaluated 的重叠属性。

### 5. Regex 安全子集

`pattern` 与 `patternProperties` 使用 Unicode scalar value、区分大小写、非锚定搜索。允许：

- escaped literal 和普通 literal；
- `.`、`^`、`$`；
- 简单/否定字符类与 Unicode scalar 范围；
- 普通捕获无关分组 `(...)` 和 alternation `|`；
- 贪婪 `*`、`+`、`?`、`{m}`、`{m,n}`，其中 `0 <= m <= n <= 10000`。

禁止 backreference、lookaround、named/atomic/conditional group、inline flag、lazy/possessive
quantifier、实现私有 escape、Unicode property escape，以及对包含 quantifier 或 alternation 的
group 再量化。字符类不能包含字符串属性或集合运算。注册器按未来机器 grammar 解析而不是用
字符串黑名单；任一实现不能安全表达的合法 pattern 必须导致该实现不合规，不能把 pattern
降级为 annotation。

匹配器必须具有相对于 `pattern_scalar_count + input_scalar_count` 的确定性线性上界。
宿主 regex 引擎只有在完整通过安全 grammar 和一致性 fixtures 后才能使用。

regex grammar 解析、安全性检查和编译发生在 TypeDefinition admission，而不是首次 semantic
匹配时。先执行 1,024 Unicode-scalar 固定上限；超限直接返回
`type_definition.resource_exhausted + not_evaluated/resource_exhausted`。上限内 pattern 按第 6 节
admission 规则预扣 grammar/AST/compact-counter 编译 units；语法或线性规则不合法返回
`type_definition.invalid_schema + invalid/succeeded`，admission work-unit 不足返回
`type_definition.resource_exhausted`。编译器必须使用不展开 `{m,n}` 的 compact counter node，
编译产物不进入规范 digest且不能改变计数；运行环境无法提供合规引擎时是
`type_definition.validation_indeterminate + not_evaluated/indeterminate`，不能伪装为 schema
invalid。semantic 阶段只消费已成功 admission 的编译表示，并按匹配计数式预扣 units。

### 6. Work-unit 计数与资源预算

#### 6.1 通用规则

- work-unit 是规范逻辑计数，不测量 CPU、内存或 wall-clock。
- admission 与 semantic validation 使用彼此独立的计数器和上限，结果分别报告；固定
  bytes/depth/count 上限在 work-unit 计数前检查。
- 求值顺序固定为：schema object 的 keyword 按下表 ordinal；map 键和对象属性按属性名 UTF-8
  bytes 升序；数组按索引升序；组合器按 schema 数组顺序。
- 为获得完整 annotation 和稳定诊断，`allOf`、`anyOf`、`oneOf` 评估所有分支；不能因已知
  valid/invalid 而改变计数。`if` 只评估被选择的 `then` 或 `else`。
- 每个逻辑动作在执行前预扣 units；若下一动作会超过上限，立即返回
  `not_evaluated + resource_exhausted`，不产生部分对象结论。
- 实现可以优化、memoize 或并行，但必须报告与规范逻辑求值相同的 unit 数和结果。

keyword ordinal 为：

| ordinal | keywords（同一格内仍按列出顺序） |
|---:|---|
| 0～30 | `$schema`、`$ref`、`$defs`、`$comment`，步长 10 |
| 100～130 | `allOf`、`anyOf`、`oneOf`、`not`，步长 10 |
| 140～142 | `if`、`then`、`else`，步长 1 |
| 150～170 | `dependentSchemas`、`prefixItems`、`items`，步长 10 |
| 180～182 | `contains`、`minContains`、`maxContains`，步长 1，并作为一个 contains transaction 完成有效性与 annotation 判定 |
| 190～220 | `properties`、`patternProperties`、`additionalProperties`、`propertyNames`，步长 10 |
| 300～370 | `type`、`enum`、`const`、`multipleOf`、`maximum`、`exclusiveMaximum`、`minimum`、`exclusiveMinimum`，步长 10 |
| 400～420 | `maxLength`、`minLength`、`pattern`，步长 10 |
| 500～520 | `maxItems`、`minItems`、`uniqueItems`，步长 10 |
| 600～630 | `maxProperties`、`minProperties`、`required`、`dependentRequired`，步长 10 |
| 700～800 | `title`、`description`、`default`、`deprecated`、`readOnly`、`writeOnly`、`examples`、`format`、`contentEncoding`、`contentMediaType`、`contentSchema`，步长 10 |
| 850 | 所有 `x-` annotation，内部按 keyword UTF-8 bytes 升序 |
| 900～910 | `unevaluatedItems`、`unevaluatedProperties`，步长 10，强制最后求值 |

表中“700～800”的显示范围按逐项步长规则展开：`title=700`，依次递增 10，
`contentSchema=800`；850 与 900 仍保持后续顺序。机器 profile 必须把每个 keyword 展开成唯一
整数，不能只保存分组文本。`then`/`else` 的 keyword visit 始终计数；只有 `if` 选择的分支再
计进入分支和子 schema units。`minContains`/`maxContains` 只与同一 schema object 的 `contains`
共同生效；缺少 `contains` 时仍计 keyword visit，但不产生 assertion 或 annotation。

#### 6.2 TypeDefinition admission 完整算法

固定 size/depth/count 检查通过后，按以下算法计入 250,000 admission units：

1. 先对完整 TypeDefinition JSON 值收费一次 `json_value_cost`，确保 owner、capabilities、
   provenance、bundle metadata 和 schema values 都进入 admission 预算；后续 schema 遍历和
   regex/ref 费用是语义检查的附加成本，并非替代这笔结构成本。
2. primary resource 先处理，bundle resources 再按 digest URI UTF-8 bytes 升序处理。对每个
   resource 校验 JCS SHA-256，收费 `1 + ceil(resource_jcs_bytes / 256)`；每个 `$ref` 图边收费
   1，每个 resource vertex 收费 1，随后检查跨 resource DAG 和本地非生产环。
3. 对每个 resource 从 root 深度优先、前序访问全部 schema locations，包括未被 `$ref` 到的
   `$defs`。进入一个 object/boolean schema 收费 1；object schema 的已出现 keywords 按 ordinal
   访问，每个 keyword 收费 1。
4. schema-map keywords `$defs`、`dependentSchemas`、`properties`、`patternProperties`：map 的
   每个 member 按键 UTF-8 bytes 顺序收费 1，再递归其 schema。schema-array keywords `allOf`、
   `anyOf`、`oneOf`、`prefixItems`：每个 element 按索引收费 1，再递归其 schema。single-schema
   keywords `not`、`if`、`then`、`else`、`items`、`contains`、`additionalProperties`、
   `propertyNames`、`unevaluatedItems`、`unevaluatedProperties`、`contentSchema`：收费 1 后递归。
5. 其余 keyword 与 `x-` annotation 使用 `json_value_cost`：scalar/null 为 1；array 为
   `1 + 元素数 + Σ元素 cost`；object 为 `1 + member 数 + Σmember-value cost`，member 按 UTF-8
   bytes 排序。annotation 中看似 schema 的键不递归按 schema 解释。
6. `$ref` 除 keyword unit 外，解析、定位和检查一次目标收费 1。local ref-depth 和 bundle graph
   仍受固定上限约束。`pattern` 的值及每个 `patternProperties` key 分别执行 regex admission：
   grammar parse 收费 `1 + pattern_scalars`；构建规范 AST 收费 `1 + ast_nodes`；构建不展开有界
   重复的 compact-counter 表示收费 `1 + ast_nodes`。AST 中 literal、dot、anchor、class、每个
   class range、concatenation、alternation、group 和 quantifier 各计一个 node。
7. 任一步下一笔费用超过剩余 admission 预算即停止，不部分扣费，返回
   `type_definition.resource_exhausted + not_evaluated/resource_exhausted`。若完成，报告实际扣费；
   实现缓存、并行、跳过未引用 `$defs` 或复用已编译 regex 都不能减少规范计数。

该算法穷举了所有允许 keyword 的 value 形状。profile/schema 结构或 regex grammar 本身非法，
且在预算内能得出结论时，才返回对应 `invalid/succeeded`；预算先耗尽时不得继续猜测对象 invalid。

#### 6.3 Semantic validation 固定计数表

| 动作 | units |
|---|---:|
| 应用一个 schema/instance location pair，包括 boolean schema | 1 |
| 访问每个出现的 allowed keyword，含 core、applicator、assertion、annotation、`x-` 与 unevaluated | 1 |
| 访问 schema 声明 map 的一个 member | 1 |
| 访问一个对象 member 或数组 element | 1 |
| 做一次 property-name 存在性、集合 membership 或 additional 分类检查 | 1 |
| 对一个 required/dependentRequired 名称做存在性检查 | 1 |
| 进入一个 applicator 分支或被选择的 conditional 分支 | 1 |
| 解析一次 `$ref` 并定位目标 | 1 |
| `const` 或 `enum` 的一次 schema candidate/instance JCS 比较 | `1 + ceil(candidate_jcs_bytes / 256) + ceil(instance_jcs_bytes / 256)` |
| 为 `uniqueItems` 的一个 instance item 生成/比较 JCS 摘要 | `1 + ceil(item_jcs_bytes / 256)` |
| 对一个 property name 或 string 尝试一次 regex | `1 + pattern_scalars + input_scalars` |
| 求值一次数值断言，包括精确 `multipleOf` | 1 |
| 向 evaluated-property/evaluated-item set 合并一个新标记；重复标记不收费 | 1 |

schema object 中每个出现的 allowed keyword 都先按 ordinal 收费 1；这包括 `$schema`、`$ref`、
`$defs`、`$comment`、全部 applicator/assertion/annotation、`x-` 和 unevaluated keywords。
`$schema`、`$comment`、`x-` 在 semantic 阶段只收 keyword visit，不遍历其值。`$defs` 也只收
keyword visit，不遍历声明 map；只有 `$ref` 实际命中其中某个 subschema 时，才按 `$ref` 解析、
进入 schema/instance pair 和目标 keywords 逐项收费。admission 仍按 6.2 节遍历全部 `$defs`。

对象 applicators 按以下穷举规则收费，所有 schema map keys 和 instance members 分别按 UTF-8
bytes 升序：

- `properties`：收 keyword visit；每个声明 member 收 1 次 map-member visit 和 1 次同名属性
  existence check。不存在则停止该声明；存在则收 1 次实际 member access，随后按普通规则应用
  subschema。subschema 成功且该名称尚未进入 evaluated set 时，merge 再收 1。
- `patternProperties`：收 keyword visit；每个声明 pattern 收 1 次 map-member visit。每个实际
  member 对本 keyword 收 1 次 member access；随后对每个声明 pattern 收完整 regex-attempt 公式，
  不另收 classification fee。每个匹配项都应用其 subschema；成功产生的新 evaluated 名称 merge
  收 1，重复标记不收费。不能在首次匹配或失败后短路其余 patterns。
- `additionalProperties`：收 keyword visit；每个实际 member 收 1 次 member access 和 1 次
  additional classification。分类使用 `properties` 的声明名称和 `patternProperties` 已按上述
  规则得到的语法匹配结果；复用结果不退还前面规范应收 units，也不重复收 regex-attempt。仅对
  未被任一名称/模式覆盖的 member 应用 subschema；成功产生的新 evaluated 名称 merge 收 1。
- `unevaluatedProperties`：在 ordinal 910 收 keyword visit；每个实际 member 收 1 次 member
  access 和 1 次 evaluated-set membership check。已标记则跳过；未标记则应用 subschema，成功
  产生的新标记 merge 收 1。任一 subschema 失败时不收 merge unit，annotation 按 4.4 节丢弃。

`required` 收 keyword visit，并按 schema 数组索引访问全部名称；每个名称收 1 次 array-element
access 和 1 次 existence check，不访问 instance value、不应用 subschema。`dependentRequired` 收 keyword visit，按触发
属性名 UTF-8 bytes 顺序为每个声明 map member 收 1，再收 1 次触发属性 existence check；触发
属性不存在时不检查其 dependency 数组，存在时按数组索引为每个 dependency 收 1 次
array-element access 和 1 次 existence check。两者都不因发现首个缺失名称而短路；重复/非法
声明已在 admission 阶段拒绝。

`prefixItems`/`items`/`contains`/`unevaluatedItems` 对每个受影响元素访问并计数。`contains` 必须
检查所有元素。令 `J(v)=ceil(length(JCS(v))/256)`。`const` 的完整比较费用是
`1 + J(schema_const) + J(current_instance)`；`enum` 对 schema 数组中的**每个** candidate 都收
1 次 array-element access，再收 `1 + J(candidate) + J(current_instance)` 的比较费，即每项总计
`2 + J(candidate) + J(current_instance)`，并全扫，即使已找到相等项也不短路。实现可以缓存
instance/candidate 的 JCS bytes 或摘要以减少实际计算，但每次逻辑比较仍收完整公式 units。
`uniqueItems` 对每项只做一次 JCS+SHA-256；digest 相同后再比较 JCS bytes，但碰撞比较不增加
规范 unit，因而实现差异不会改变预算。

memoization 不能免除逻辑 units。相同求值键由多个分支引用时，每次逻辑引用都按表计数，但
可以复用缓存结论。非生产递归在 schema admission 阶段拒绝，不进入实例预算。

生成、去重、排序和截断结构化 diagnostics **不消耗 work units**；它们受每阶段最多 100 项的
独立固定上限约束。若下一逻辑动作费用大于剩余预算，该动作不执行、不部分扣费，
`work_units_consumed` 保留为已成功预扣的数值，并在预算外生成唯一 mandatory
resource-exhausted diagnostic。这样不会出现“预算已耗尽却还需为耗尽诊断扣费”的悖论。
`limit-1`、`limit`、`limit+1` fixtures 必须断言停止动作、consumed 值、唯一 code 和无部分
object result。

#### 6.4 Portable 上限

复用 ADR-0005 的最低边界：CognitiveNode 1,048,576 JCS bytes；TypeDefinition 含 bundle
2,097,152 JCS bytes；JSON 深度 64；members + elements 总数 100,000；单字符串 262,144 UTF-8
bytes；单数组 10,000 项；bundle 128 resources；`$ref` 链 64；单 regex 1,024 Unicode scalars。

本 RFC 建议 schema semantic validation 的 portable 上限为 **1,000,000 work units/对象**，
TypeDefinition admission（含 schema/profile 检查）上限为 **250,000 work units/定义**。
单次 conformance case 的全部 dependency admission 与目标 validation 分开计数并分别报告；
consumer 不得用更低 wall-clock timeout把预算内输入改写为 `resource_exhausted`。

每项固定上限必须提供 `limit-1`、`limit`、`limit+1` fixture。外部进程中断、OOM、服务不可用或
宿主取消只能是 `indeterminate`；策略给出的更低业务预算只能在对象已 valid 后拒绝操作，不能
修改 portable validity。

### 7. 稳定诊断与规范结果

每个 validator 结果至少输出：`profile_version`、`contract_id`、`contract_version`、`mode`、
`object_result`、`operation_outcome`、`work_units_consumed`、`issues` 和可选规范摘要。
这些是 conformance runner 的比较投影，不替领域契约决定业务 API 字段。

领域错误码由各公共契约拥有；runner 只可使用下列基础设施码：

| code | 含义 |
|---|---|
| `conformance.fixture_invalid` | fixture 自身不满足 manifest/schema/lock |
| `conformance.digest_mismatch` | 规范工件或 bundle 摘要不匹配 |
| `conformance.consumer_crashed` | consumer 没有返回完整结构化结果 |
| `conformance.result_mismatch` | 两个消费者的规范比较投影不同 |
| `conformance.generated_drift` | 可重建生成物与仓库内容不一致 |
| `conformance.network_or_file_access` | 离线阶段检测到未授权外部访问 |

runner 不能把基础设施码伪装成领域对象 invalid。领域 issues 继续使用稳定 code、JSON Pointer、
`error|warning|info`、结构化 details，以及 ADR-0005 固定的去重、截断和规范排序。localized
message、stack trace、耗时、内存和库版本可另作非规范诊断，不进入一致性等值比较。

### 8. 语言无关 Fixtures

每个 fixture case 是不可变目录，至少包含：

- 原始输入 bytes；
- case manifest：稳定 `case_id`、profile/contract/version、phase/mode、依赖文件、digest 算法和
  `raw|jcs` digest kind；
- 可选 schema bundle、authority/provenance/reference 等依赖 stubs；stub 的内部字段由对应后续
  契约拥有，基础工具链不得发明；
- expected result：规范比较投影、JCS SHA-256（仅成功解析且 profile-valid 时）、raw SHA-256、
  work units、issues；parser-negative case 禁止出现 JCS digest；
- `purpose` 和 `boundary` 元数据，用于证明正常、失败或 `limit-1|limit|limit+1` 覆盖。

fixture case 不得内联时间、随机数、绝对路径或本地化 message。case ID 一经发布不得把原输入或
预期结果原地替换；修正有效集合或语义时创建新的 contract/profile 版本和新 case ID。只修复
说明文字而机器内容不变可以 patch。

fixtures 至少分为：parser/JCS、schema admission、semantic validation、annotations、diagnostics、
resource、security、compatibility 和 contract-specific consumer examples。schema 组必须覆盖
有效跨 resource DAG、本地结构递降递归、本地非生产环、不可构造的跨 resource cycle 尝试、
`$ref` siblings、组合器/conditional annotation、contains/min/max/unevaluatedItems、重叠对象
applicators、regex admission/编译预算及 UTF-16-vs-UTF-8 astral/BMP 排序。每个公共契约必须至少
提供一个独立 producer 输出和一个 consumer 输入用例；CognitiveNode 还必须覆盖 ADR-0005 测试
计划。

### 9. 双消费者一致性

TypeScript 与 Python consumer 必须：

1. 分别读取相同原始 bytes、profile、schemas、bundle 和 lock；
2. 不通过 FFI、子进程、HTTP 或共享原生 validator 调用对方；
3. 分别产生规范结果 JSON；
4. 由 runner 对两份结果再次执行 profile 校验和 JCS；
5. 比较 object/operation 结果、work units、issues、canonical digest 和规范输出；
6. 任一差异以 `conformance.result_mismatch` 阻断合并，不以多数投票或主实现优先解决。

若两个实现同时与 expected result 不同，fixture 仍然失败。若 fixture 与已接受 ADR 冲突，先停止
并通过 RFC/ADR 流程修正规范；不能仅修改 expected 让测试转绿。

### 10. 数据流

```text
已接受 ADR
  → 语言无关 profile/schema/diagnostics/fixtures
  → JCS + SHA-256 lock
  → TypeScript consumer ─┐
                         ├→ differential runner → CI 证据
  → Python consumer ─────┘
  → 只读生成物与各模块 consumer tests
```

任何写入规范工件的操作必须是显式 Issue/PR。validator 运行、类型生成和测试不得自动修改规范
文件。AI 生成的规范变更必须保留 Issue/PR、前后 digest、独立审查和可回滚提交。

## 公共接口

本 RFC 新增的长期接口仅是未来待实现的 **M1 conformance profile**：

- profile/version 与 contract/version 的显式绑定；
- JCS/SHA-256 规范内容和离线 digest bundle；
- 允许 keyword、regex grammar、work-unit 表和 portable limits；
- fixture manifest、expected result comparison projection 和 lock；
- `conformance.*` 基础设施错误码。

它不增加或修改任何一个业务公共契约字段。具体 JSON Schema 文件与 manifest 字段必须在本 RFC
接受后的机器契约 Issue 中给出 schema 和 fixtures；在该 Issue 合并前，本文是决策提案而不是
可宣称已实现的 portable validator 契约。

### 版本与兼容规则

| 变化 | 最低版本 |
|---|---|
| 仅说明澄清，不改变有效集合、计数或输出 | patch |
| 新增可选 annotation、fixture 或不改变旧 case 的诊断元数据 | minor |
| 新增/删除 assertion keyword、改变求值/计数、上限、regex 语义或规范结果 | major |
| 收紧有效输入、把 annotation 改为 assertion、改变 digest/JCS | major |

contract major 必须锁定一个受支持的 profile major。profile minor 不会自动适用于旧 contract；
升级必须经显式 lock 变更和完整双消费者回归。未知 profile major 拒绝，不能 best-effort 校验。

## 安全、溯源与控制策略

- parser、canonicalizer、validator 和 runner 一律把输入、schema、bundle、expected result 当作
  不可信数据。
- conformance 阶段默认断网，并只允许读取已锁定的仓库文件；HTTP、文件 `$ref`、包搜索和插件
  discovery 均阻断。
- TypeScript 与 Python 依赖必须锁版本、接受依赖扫描，并记录 runtime 与依赖版本；这些版本是
  证据，不是规范有效性输入。
- 禁止 fixture 包含真实密钥、凭据、用户私有 Agent 记忆、受版权保护原件或生产数据；安全用例
  使用明显的合成标记。
- CI 日志不得输出完整 opaque payload；默认只输出 case ID、digest、状态、code 和最小差异路径。
- work-unit 和固定 size/count 限制是平台最低安全边界。业务策略可以更严格地拒绝后续操作，但
  不能将对象重新分类为 invalid。
- 规范变更记录旧/新 digest、作者、关联 Issue/PR、审查结论和回滚提交；不得原地覆盖已发布
  profile、contract schema 或 fixture case。
- 生成器只能写 `generated` 目录，不能修改 schema/profile/fixture/lock。CI 对写集做范围检查。

## 替代方案

### A. 推荐：TypeScript 主实现 + Python 独立次实现

优点：与 Web-first、Node CI 和 packages 开发路径一致，同时用 Python 覆盖科研/Jupyter 运行时；
两个生态能真实暴露数字、Unicode、regex 和 JSON Schema 差异。开发者反馈快，未来数学切片也
无需先增加第三种语言。

代价：维护两套实现和差分 runner；必须防止 Python 变成 TypeScript 包装器，也必须限制两种
第三方 schema 库的默认差异。主/次称谓可能被误解为规范优先级，因此本 RFC 明确机器契约才是
规范来源。

### B. Python 主实现 + TypeScript 独立次实现

优点：科学计算、Jupyter、数据处理与后续数学垂直切片更直接；Python 原型速度快。

代价：M1 首要消费者包括 Web IDE 和 packages，主反馈链路会更远；可能让浏览器侧持续依赖
Python 服务，削弱开放工程包的本地检查能力。跨语言保证与维护成本并未减少。

适用条件：产品把首期核心体验改为 notebook/服务端优先，而非 Web IDE 优先。

### C. 暂不固定主实现，所有实现地位完全对等

优点：语言中立表述最纯粹，不形成组织上的主实现惯性；未来可并行增加 Rust、Java 等消费者。

代价：M1 初期没有明确的生成器、开发者反馈和故障归属；每项改动需要同时协调两套工具，容易
让机器契约无人负责或由先合并的实现事实主导。即使称为对等，仍必须指定 CI、发布和生成物的
维护责任。

适用条件：已有两个成熟团队和实现，且能共同维护同一机器契约；当前仓库不满足。

### 引用递归的替代说明

曾考虑允许 digest bundle resources 互相递归引用，但该方案并非真实可构造的内容寻址工件：
每个 URI 都取决于包含对方最终 URI 的 bytes，形成摘要固定点。使用临时 ID 再重写会让摘要失效，
使用非内容寻址别名又破坏 ADR-0005 的离线不可变边界。因此本 RFC 只允许同一 resource 内的
local fragment 结构递降递归，跨 resource 引用固定为 DAG。更严格的“禁止全部递归”可简化实现，
但会排除树、表达式和嵌套节点等有限实例上的常见递归 schema，暂不推荐。

## CI、测试与验收计划

每个涉及 profile、公共契约或 conformance 实现的 PR 依次通过：

1. 治理、格式、lint、类型检查和规范 JSON 原始 bytes 检查；
2. profile/schema/diagnostic/fixture/lock 自校验；
3. JCS 与 SHA-256 已知向量，包括 Unicode、数字、重复键和非法输入；
4. TypeScript consumer 单元及契约测试；
5. Python consumer 单元及契约测试；
6. 双消费者全量 differential；
7. keyword、完整 annotation 传播、regex admission/编译、digest `$ref` DAG、本地结构递降递归、
   UTF-16/UTF-8 双排序和所有固定预算的边界 fixtures；
8. 禁网、禁止文件引用、digest 篡改、非生产递归、恶意 regex 和日志泄漏测试；
9. 生成物重建无 diff，旧 contract/profile 兼容矩阵无回归；
10. 受影响模块的 consumer test 与构建。

首次发布门槛：

- profile 与 machine schemas 经独立契约审查，P0/P1/P2 均已处理；
- 两个消费者不共享 validator，实现身份与依赖清晰；
- 所有 normative fixtures 的规范比较投影一致；
- 每项资源上限具备 `limit-1`、`limit`、`limit+1`；
- 无网络/文件隐式读取，安全测试通过；
- 变更说明、兼容矩阵、旧/新 digest、feature flag 和回滚命令齐全。

随机/fuzz 测试可以每日运行并生成 Issue，但只有失败样本被最小化、去除敏感数据并固化为
确定性 fixture 后，才成为合并门禁和长期事实。

## 迁移与发布

### 初始发布顺序

1. 接受本 RFC，创建 ADR；在此之前不实现提案。
2. 独立 Issue 固化 profile manifest/schema、keyword ordinals、regex grammar、work-unit 表、
   limits、fixture manifest、expected result 和 lock。
3. 独立 Issue 实现 TypeScript consumer，只对已合并机器契约负责。
4. 独立 Issue 实现 Python consumer，不读取 TypeScript 生成物作为校验依据。
5. 独立 Issue 建立 differential runner 与 CI 安全门禁。
6. CognitiveNode schema/fixtures 首先接入并完成跨语言验收。
7. 其余公共契约按依赖顺序逐项接入；每次最多变化一个公共契约。

当前无已发布 M1 数据，不做原地数据迁移。仓库外原型只能通过单独导入 Issue，先按其声明的旧
profile 校验，再由显式迁移生成新版本和 provenance；不能被工具静默“修复”为当前格式。

### 兼容期与 Feature Flag

- profile/contract major 升级时，至少一个发布周期同时保留旧 major 的只读校验和新 major 的
  opt-in 写入；写入使用显式 profile/version，不能自动跟随最新版本。
- 新 validator 先以 differential shadow 模式运行，不影响提交结论；全量 fixtures 一致后再切换
  写入路径。shadow 差异只记录合成/脱敏摘要。
- 移除旧 major 前必须证明项目包扫描无剩余写入依赖，提供导出/迁移/保持只读三种路径。

### 可观测性

按 profile、contract、consumer、mode、object result、operation outcome、diagnostic code 和
resource bucket 记录计数；另记录 work-unit 分布、差异 case ID、旧/新 digest 和 consumer
版本。不得记录完整 payload、原件、凭据或私有 Agent 记忆。wall-clock 与内存只用于运维，
不能参与 portable validity。

### 回滚

- RFC/ADR 尚未实现：撤回候选 RFC 或用新 ADR 替代，不存在数据回滚。
- 机器契约尚未发布：回退对应 PR，重新生成 lock；不得修改已发布 tag。
- consumer 有缺陷而规范未变：回滚 consumer/feature flag，继续使用上一 conforming 版本；
  保留失败 fixture 作为回归证据。
- 规范本身有缺陷：冻结写入，保留旧 major 只读能力，创建新 profile/contract 版本和迁移 Issue；
  不原地改写已发布 schema、fixture 或历史 JCS bytes。
- 安全漏洞：立即禁用受影响写入/导出能力并保留只读隔离；修复仍须通过双消费者与安全回归。

## 建议的后续 Issues

### 1. `[Contract Infra] 固化 M1 portable profile 与机器契约`

- 唯一结果：提交 profile/schema、regex grammar、work-unit/limits、fixture manifest、diagnostics
  projection 和 lock 的语言无关机器文件及自校验 fixtures。
- 允许路径：仅 `packages/cognitive-ir` 的新 contracts/fixtures 区和对应测试；不实现 validator。
- 依赖：本 RFC 已接受并形成 ADR。

### 2. `[cognitive-ir] 实现 TypeScript conformance consumer`

- 唯一结果：从原始 bytes 消费已锁定 profile 并输出规范比较投影。
- 非目标：Python、业务契约字段、网络 registry、mutation。
- 依赖：Issue 1 已合并。

### 3. `[cognitive-ir] 实现 Python 独立 conformance consumer`

- 唯一结果：不调用 TypeScript 实现，独立运行同一 fixtures。
- 非目标：Jupyter UI、求解器、业务代码。
- 依赖：Issue 1 已合并；可与 Issue 2 并行。

### 4. `[CI] 建立双消费者 differential 与离线安全门禁`

- 唯一结果：比较规范投影、检测外部访问、生成物漂移和兼容回归。
- 依赖：Issue 2、3 已合并。

### 5. `[Contract] 固化 CognitiveNode/TypeDefinition schema 与完整 fixtures`

- 唯一结果：把 ADR-0005 转成一个公共契约的机器 schema 和 fixtures。
- 非目标：validator 实现、其他 10 个公共契约字段。
- 依赖：Issue 1～4 已合并。

### 6. `[Interop] CognitiveNode 双消费者接受测试`

- 唯一结果：证明 ADR-0005 要求的 JCS、数字、schema、预算、诊断和安全结果一致。
- 依赖：Issue 5 已合并。

后续 ProvenanceRecord、ControlPolicy、ModelProvider 等契约继续各自建立 RFC/ADR/schema/fixtures
Issue；不能把它们合并进上述基础设施 PR。

## 产品负责人决策（已全部接受）

产品负责人于 2026-08-10 明确接受下表第 1～9 项全部推荐值；真实替代方案均未采用。
下表继续保留替代方案和主要影响，作为决定依据与后续审查基线：

| # | 决策 | 推荐值 | 真实替代 | 主要影响 |
|---:|---|---|---|---|
| 1 | 主/次实现 | TypeScript 主 + Python 独立次 | Python 主 + TS 次；暂不固定 | 决定开发反馈、维护责任和首期集成路径，不改变机器契约权威 |
| 2 | 规范来源 | 语言无关 profile/schema/fixtures/lock 唯一权威 | 主实现代码为权威 | 推荐值避免库行为成为隐式标准 |
| 3 | Schema profile | 接受本文允许/禁止 keyword、精确数值和完整 annotation 语义 | 缩小 keyword；接受任意 2020-12 | 推荐值表达力较高但机器契约测试面更大；任意实现会漂移 |
| 4 | 引用与递归 | 本地 fragment 可结构递降递归；跨 resource digest 引用必须为 DAG | 禁止全部递归；改用非内容寻址外部 ref | 推荐值兼顾常见递归数据、内容寻址和确定性，需 admission 图检查 |
| 5 | Regex | 接受本文线性安全 grammar | 仅 literal；宿主 regex 全开放 | 推荐值需要专用 parser，但避免 ReDoS 和跨引擎差异 |
| 6 | Work-unit | 接受固定计数表；semantic 1,000,000，admission 250,000 | 延后决定；按毫秒/实现计数 | 推荐值可形成跨语言资源结论，需更多边界 fixtures |
| 7 | 一致性 | 两个消费者的规范投影逐项相同 | 只要求各自测试通过；主实现优先 | 推荐值成本更高，但能发现共同 fixture 之外的漂移 |
| 8 | 发布 | shadow → 双消费者全绿 → 显式版本写入 | 首实现完成即发布 | 推荐值上线更慢，但可回滚且不污染持久化格式 |
| 9 | 兼容 | major 显式绑定，旧 major 至少一周期只读 | 总是升级到最新；永久支持所有版本 | 推荐值避免静默升级，也限制长期维护成本 |

若未来改变第 3～6 项任一已接受值，必须先通过新的 RFC/ADR 替代本决定；不得留给实现 Issue
临时选择，也不得静默改写已接受历史。

## 决定

- 决定者：产品负责人。
- 决定日期：2026-08-10。
- 决定：接受“产品负责人决策（已全部接受）”表中第 1～9 项的全部推荐值，不修改其技术含义，
  不新增第 10 项决定。
- 未采用方案：表中全部真实替代方案均未采用；保留它们用于记录权衡和未来替代 ADR 的背景。
- 后续边界：创建对应 ADR 后，以独立 Issue 固化语言无关机器契约；机器契约、TypeScript/Python
  consumers、差分 CI 和 CognitiveNode schema 仍须分别通过实现、测试、独立审查与合并门禁。
  在这些门禁完成前，不得宣称 portable semantic conformance 已实现。
