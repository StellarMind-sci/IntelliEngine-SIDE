# RFC：CognitiveNode 与学科扩展契约

- 状态：已接受
- 负责人：StellarMind-sci（Issue #1 assignee）
- 创建日期：2026-08-09
- 决定日期：2026-08-10
- 关联 Issues：[GitHub Issue #1](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/1)

## 问题

M1 要先稳定公共契约，之后才能并行实现使用方。在本 RFC 被接受前，仓库只把 `CognitiveNode`
列为计划中的公共契约，并把 `packages/cognitive-ir` 指定为通用原语和扩展规则的
所有者；尚无已接受的 ADR 或契约定义其字段、序列化、版本、扩展、校验和未知类型行为。

这会让数学、其他学科插件、KnowledgeUnit、Thoughtflow、解析服务和 Agent 使用方各自
发明不兼容的节点结构。更严重的是，如果扩展数据能够直接携带可执行行为、隐式取得权限，
或在无法识别类型时仍被执行，就会绕过控制平面和平台安全上限。

本 RFC 提出一个稳定的核心封套、一个同属 CognitiveNode 契约族的类型定义结构，以及
明确的兼容、隔离和回滚规则。产品负责人已于 2026-08-10 接受全部 16 项推荐方案；本文件
记录该架构决定，但不替代尚待单独授权创建的 ADR、机器契约和契约测试，也不授权实现。

## 事实、假设与约束

### 仓库事实

- Cognitive IR 是跨学科共用的实体、变量、关系、约束、状态、过程、目标、证据、假设、
  动作和实验等原语。
- `packages/cognitive-ir` 负责通用原语和扩展规则，不负责学科求解器或 UI。
- `plugins/math` 负责数学类型、求解器、校验器和视图，不负责跨学科内核规则。
- 动态类型默认允许创建，但不能绕过能力和权限检查。
- 不可变原件和派生关系由溯源层负责；任何产生副作用的动作都必须经过控制平面。
- 已接受的 ADR 要求先合并公共契约及其契约测试，再并行实现使用方。
- 当前仓库尚无 CognitiveNode schema、实现、数据迁移或使用方代码。

### 提案采用的假设

- 第一版开放工程格式可以使用 UTF-8 JSON 作为语言无关的交换表示。
- `id` 表示逻辑节点身份，`(id, revision)` 表示不可变节点版本身份；JCS 规范字节及其摘要只
  表示该版本的规范内容，并作为内容相等性与完整性依据，而不是逻辑或版本身份。
- 一个节点在同一 revision 只有一个主要学科类型；跨学科组合通过节点引用完成，
  而不是在同一节点上叠加多个可互相覆盖的 facet。
- ProvenanceRecord、KnowledgeUnit、Thoughtflow、DomainPlugin、ControlPolicy 和 ChangeSet
  将由各自的 RFC 定义；本 RFC 只规定 CognitiveNode 对它们的最小依赖方向。
- 产品需要安全地传输尚未安装插件的节点，因此“未知类型”不能等同于“丢弃数据”。
- 跨项目导入默认不转移原 node ID 的 revision authority；无法证明唯一 authority 时采用
  fork-on-write，而不是让多个离线项目继续同一 revision 序列。

上述假设已随全部 16 项推荐方案于 2026-08-10 获产品负责人确认；它们仍不是 ADR-0001～0004
既有决定，也必须在后续获授权的 ADR 中形成长期架构记录后才能作为实现依据。

## 目标与非目标

### 目标

1. 给出唯一、语言无关且可序列化的 CognitiveNode 最小封套。
2. 为每个字段定义语义、所有权和可机器校验的不变量。
3. 让内置、插件和项目动态类型使用同一扩展机制，且命名不冲突。
4. 明确与 ProvenanceRecord、KnowledgeUnit 和 Thoughtflow 的引用关系。
5. 明确 envelope 与学科类型各自的版本、兼容和迁移规则。
6. 在缺少类型定义时保留数据，同时禁止语义执行和修改。
7. 让权限、溯源、审计和回滚边界满足现有控制工程 ADR。
8. 为后续 schema、验证器和契约测试 Issue 提供验收基线，并明确 portable semantic 实现前
   必须先固化的机器契约。

### 非目标

- 不实现 schema、验证器、注册表、迁移器、学科插件、求解器、UI 或运行时。
- 不定义数学方程、单位、张量、化学结构等具体学科 payload。
- 不定义 ProvenanceRecord、KnowledgeUnit、Thoughtflow、DomainPlugin、ControlPolicy、
  ChangeSet 或 ProjectPackage 的完整字段。
- 不决定数据库表、索引、缓存、消息协议或网络 API。
- 不允许扩展数据携带可直接执行的代码、权限授予或控制策略覆盖。
- 不解决同一节点同时挂载多个独立学科 facet 的组合语义。
- 不修改其他计划中的公共契约。

## 术语

- **封套（envelope）**：所有 CognitiveNode 都必须具有、由 cognitive-ir 所有的字段。
- **基础种类（base kind）**：跨学科稳定的通用认知原语。
- **类型定义（type definition）**：说明某个 `type_id` 和 `type_version` 的基础种类、
  payload schema、所有者和所需能力的不可变声明。
- **语义可用（semantic-valid）**：既通过封套校验，也能用兼容类型定义校验其 `data`。
- **惰性节点（opaque node）**：封套可安全读取和无损传输，但当前环境不能解释其学科语义。
- **逻辑节点身份（logical node identity）**：由 `id` 表示；内容相同不表示逻辑节点相同。
- **节点版本身份（node revision identity）**：由 `(id, revision)` 表示，唯一指向某个逻辑
  节点的一次不可变版本。
- **revision**：某个稳定节点 ID 的不可变内容版本，不是契约或类型 schema 版本。
- **规范对象（canonical object）**：通过本 RFC JSON profile 后，以 JCS 生成唯一 UTF-8
  规范字节的 JSON 值；JCS bytes/digest 是版本内容的规范表示、相等性与完整性依据，不是身份。
- **权威快照（authority snapshot）**：供 consumer 对 namespace/capability 作稳定离线判定的
  不可变、可验证输入；具体结构、提供者和生命周期均由后续契约决定。

## 提案

### 1. 所有权与边界

| 内容 | 所有者 | 边界 |
|---|---|---|
| CognitiveNode 封套、基础种类、引用和校验状态 | `packages/cognitive-ir` | 不包含学科求解或 UI 行为 |
| `org.intelliengine.core` 类型定义 | `packages/cognitive-ir` | 只表达通用原语 |
| 第一方学科类型定义 | 对应 `plugins/*` | 不能改写封套、基础种类或平台权限 |
| 项目动态类型定义 | 项目范围，经控制平面授权 | 不能占用 core/plugin 命名空间 |
| 原件和派生关系 | `services/provenance` | CognitiveNode 仅持有引用 |
| 副作用、授权、提交和回滚 | 控制平面和 ChangeSet | 节点本身是惰性声明数据 |

注册类型只声明“解释数据需要哪些能力”，不授予能力。信任级别也不产生权限。

### 2. 基础种类

`base_kind` 是闭合集合，v1 包含：

| 值 | 稳定语义 |
|---|---|
| `entity` | 可被稳定指认的对象或概念 |
| `variable` | 可取值或被约束的符号 |
| `relation` | 两个或多个对象之间的陈述或联系 |
| `constraint` | 限制有效状态或解空间的条件 |
| `state` | 某个上下文或时点的声明性快照 |
| `process` | 状态之间的声明性变化或演化 |
| `goal` | 期望达到或验证的条件 |
| `evidence` | 支持或反驳某项陈述的观察或结果 |
| `assumption` | 明确记录但尚未验证的前提 |
| `action` | 拟执行操作的惰性描述；本身不得产生副作用 |
| `experiment` | 可复现实验计划的惰性描述；本身不得启动运行时 |

给闭合集合增加值属于 CognitiveNode envelope 的 major 变更。学科扩展通常新增
`type_id`，不得扩展 `base_kind`。

### 3. CognitiveNode 最小封套

所有字段均为必填：

| 字段 | 类型 | 语义与约束 |
|---|---|---|
| `contract_version` | SemVer 字符串 | CognitiveNode 封套版本；必须是无前导零的 `MAJOR.MINOR.PATCH`，禁止 prerelease 和 build metadata |
| `id` | 字符串 | 逻辑节点身份；稳定、全局唯一的 canonical lowercase UUID，创建者应生成 UUIDv7 |
| `revision` | 正整数 | `1..9007199254740991`；单调性只在 mutation/原子提交阶段检查 |
| `base_kind` | 枚举字符串 | 上表中的一个通用原语，必须与类型定义一致 |
| `type_id` | 字符串 | 命名空间限定的学科类型标识，格式为 `<namespace>/<local-name>` |
| `type_version` | SemVer 字符串 | `data` 所遵循的类型定义版本 |
| `data` | JSON object | 由类型定义的 JSON Schema 校验；不得侵入或覆盖封套字段 |
| `provenance_refs` | 非空字符串数组 | 引用 ProvenanceRecord；元素唯一、按字典序排列，不内联原件或溯源记录 |

`type_id` 使用 ASCII grammar
`^[a-z0-9]+(?:[.-][a-z0-9]+)*/[a-z0-9]+(?:[.-][a-z0-9]+)*$`。namespace 和
local-name 都不得为空，也不得出现连续或首尾分隔符。语法校验不等于所有权验证；类型解析
必须绑定一个由后续契约提供的不可变、可验证权威快照。保留规则如下：

- `org.intelliengine.core/*` 只允许 `packages/cognitive-ir` 注册。
- `org.intelliengine.<subject>/*` 只允许被分配该 namespace 的第一方插件注册。
- 第三方插件使用权威快照证明其控制的反向域名 namespace。
- 项目动态类型使用 `project.<project-uuid>/*`，且只能在对应项目范围注册。

UUID 只决定逻辑节点身份，不编码项目、类型、权限或存储位置。导入项目时不得因路径变化重写
`id`；发生身份冲突时必须显式生成新的节点和新的溯源关系。

#### 跨项目分叉与 revision authority

本 RFC 推荐 **fork-on-write**，以保证每个节点版本身份 `(id, revision)` 只映射到一组 JCS bytes：

- 一个 node ID 在任一时刻只有一条被承认可继续增加 revision 的权威 lineage。如何证明或
  转移该 authority 由未来 ProjectPackage/ChangeSet/ControlPlane RFC 决定，本 RFC 不定义字段。
- 导入或离线复制可以保留原 ID 和历史 revisions，但在目标项目中默认只读。
- 目标项目若不能证明自己拥有该 ID 的唯一 revision authority，首次修改必须生成新 UUID、
  从 revision `1` 开始，并通过 ProvenanceRecord 记录对原 `CognitiveNodeRef` 的 fork 来源；
  原 ID 的历史 revision 保持不变。
- 两个项目从同一 ref 离线修改时各自生成不同新 ID，不得都发布原 ID 的下一个 revision。
- 重新合并时保留各 fork ID。引用重写必须是显式、可审查的合并操作，并保留 fork/reconcile
  provenance；相同 JCS 内容只表示版本内容相等，不得据此自动折叠逻辑身份或节点版本身份。
  具体引用重写和 provenance 字段由后续契约定义。
- 缺少 authority 证明却尝试继续原 ID，或同时出现两个候选权威 lineage，必须产生稳定的
  `cognitive_node.revision_authority_conflict` 外部结果，而不是自动选择一方。

### 4. 封套不变量

1. `(id, revision)` 是不可变节点版本身份并唯一映射到一组 JCS 规范字节；提交后该映射不可
   改变。JCS bytes/digest 用于版本内容相等性与完整性，原始输入 blob 不属于规范版本内容。
2. 除 `revision` 本身外，任一已序列化封套字段（包括未知字段）或 `data` 的 JSON 值变化
   都必须创建更高 revision；不得原地覆盖。只改变 `revision` 而不改变其他内容是无效转换。
3. 同一 `type_id` 在所有版本中必须保持同一 `base_kind`；改变基础种类必须使用新 `type_id`。
4. `type_version` 必须指向注册的不可变类型定义，才能进入语义执行或修改流程。
5. `data` 只能是符合本 RFC JSON profile 的 JSON object，不允许重复键、非法 Unicode、
   NaN、Infinity、二进制对象或语言私有值。
6. `provenance_refs` 至少有一项。用户直接创建的节点也必须引用“用户创建”来源记录。
7. 封套和类型定义不能授予权限、提高信任或覆盖平台安全上限。
8. 任意节点引用必须固定到节点版本身份 `(id, revision)`，不能只依赖“最新版本”。
9. transport/semantic 只检查当前对象局部事实；revision 单调性、引用存在性和当前 revision
   比较只能在 mutation 的原子提交阶段判定。
10. 原 ID 的只读导入不改变逻辑节点身份；无唯一 revision authority 的首次写入必须 fork 新 ID。

### 5. CognitiveNodeRef

其他契约引用 CognitiveNode 时使用以下最小值对象：

```json
{
  "id": "0190c6b8-7a42-7a1b-8c2d-6a3f5b7e9d10",
  "revision": 1
}
```

该引用是 CognitiveNode 契约族的一部分，不定义引用方字段。提交时引用必须能解析到唯一的、
已通过至少 transport 校验的节点 revision；是否要求 semantic-valid 由引用方契约另行收紧。

### 6. CognitiveNodeTypeDefinition

类型定义是 CognitiveNode 扩展机制的一部分，不新增独立顶层公共契约。每个定义的所有
下列字段均为必填：

| 字段 | 类型 | 规则 |
|---|---|---|
| `definition_format_version` | SemVer 字符串 | 类型定义封套自身的版本；v1 推荐 `1.0.0` |
| `type_id` | 字符串 | 与节点字段相同；注册者必须证明 namespace 所有权 |
| `type_version` | SemVer 字符串 | 与 `type_id` 共同组成不可变注册键 |
| `base_kind` | 枚举字符串 | 对该 `type_id` 的所有版本保持不变 |
| `owner` | `{scope, id}` | `scope` 为 `core`、`plugin` 或 `project`；`id` 标识负责方 |
| `data_schema` | JSON Schema | 遵守下述固定 2020-12 profile，根类型必须是 object |
| `schema_bundle` | 数组 | 被允许的离线内容寻址 schema resources；无外部引用时为空数组 |
| `required_capabilities` | 字符串数组 | capability ID 唯一、排序；只声明使用条件，不授予权限 |
| `provenance_refs` | 非空字符串数组 | 追踪静态定义来源或动态定义的创建过程 |

这些字段、TypeDefinition envelope 和注册流程的所有公共诊断都必须使用下文
`type_definition.*` 错误族；不得借用 CognitiveNode、通用 validation 或 registry 内部 code。

`definition_format_version`、`type_version` 和节点的 `contract_version` 都必须使用无前导零的
canonical `MAJOR.MINOR.PATCH`；持久化或注册值禁止 prerelease 和 build metadata。版本
字符串先做语法校验，再按数值三元组比较；`1.0.0` 与任何其他词法形式均不等价。

#### 类型定义演进矩阵

`definition_format_version` 管理上述定义封套：新增可选元数据是 minor，新增必填字段、
删除字段或改变字段语义是 major，完全不改变有效定义集合的澄清是 patch。

`type_version` 管理具体 `data` 语义及其信任边界：

| 变化 | 最低版本级别 |
|---|---|
| schema 注释/说明变化，且有效实例集合和解释不变 | patch |
| schema 新增可选字段、放宽约束或增加兼容 schema resource | minor |
| schema 新增必填字段、收紧约束、删除/重命名字段或改变含义 | major |
| `owner.scope`、`owner.id` 或 namespace 权威所有者变化 | major |
| 删除 required capability（允许更多环境只读/执行） | minor |
| 新增、重命名或提升 required capability 版本 | major |
| 增加不改变权威依据的佐证 provenance | patch |
| 删除/替换权威 provenance，或改变来源所支撑的语义 | major |
| `schema_bundle` 内容变化 | 按其引起的 schema 有效集合/语义变化使用 patch、minor 或 major |

任何变化都必须创建新的不可变类型定义键；“最低版本级别”不允许用较低级别发布。
相同 `definition_format_version` major 的未知定义封套字段按 JSON 值保留并忽略，不得影响
schema 断言。旧读取方可无损传输较新 minor，但注册、重签名或修改前必须完整理解该 minor。

#### JSON Schema 2020-12 portable admissibility profile

- `data_schema.$schema` 必须精确等于
  `https://json-schema.org/draft/2020-12/schema`；禁止自定义 meta-schema。
- 实现必须支持下列固定 vocabulary URIs：
  `https://json-schema.org/draft/2020-12/vocab/core`、
  `https://json-schema.org/draft/2020-12/vocab/applicator`、
  `https://json-schema.org/draft/2020-12/vocab/validation`、
  `https://json-schema.org/draft/2020-12/vocab/unevaluated`、
  `https://json-schema.org/draft/2020-12/vocab/meta-data`、
  `https://json-schema.org/draft/2020-12/vocab/format-annotation` 和
  `https://json-schema.org/draft/2020-12/vocab/content`。`format` 与 content keywords 只作为
  annotation，禁止 Format-Assertion；需要强制格式时必须用本 profile 可移植的
  `pattern`、长度或数值关键字表达。
- 不允许 schema 声明 `$vocabulary`。固定 vocabularies 之外只允许名称以 `x-` 开头的
  annotation keywords；它们的值按普通 JSON 数据处理，其中出现的 schema-like keyword
  一律不参与解析。它们必须无损保留且不影响有效性。其他未知 keyword，或任何未知
  required vocabulary，都以 `type_definition.unsupported_schema_vocabulary` 拒绝。
- `pattern` 和 `patternProperties` 使用 Unicode scalar value 语义及 JSON Schema 的非锚定
  匹配。portable 子集仅含普通字符、简单/否定字符类、范围、贪婪 `* + ? {m} {m,n}`、
  `^ $`、普通分组和 alternation；禁止 backreference、lookaround、named group、inline flag、
  lazy quantifier、嵌套量词（包括对内部含量词或 alternation 的 group 再量化）和实现私有转义。
  validator 必须使用对 pattern length 与 input Unicode scalar count 具有确定性线性上界的引擎；
  无法证明线性时间的表达式在注册时拒绝。完整机器 grammar 由后续 schema-profile Issue 固化。
- v1 禁止 `$id`、相对 `$ref`、`$dynamicRef` 和 `$dynamicAnchor`。`$ref` 只允许同一 schema
  内的 JSON Pointer fragment，或 `urn:intelliengine:schema:sha256:<64-lowercase-hex>`。
- 每个 `schema_bundle` 项包含 `uri`、`sha256` 和 `schema`。`uri` 必须使用上述 digest URI，
  且 hex 与对 `schema` 的 JCS 规范字节计算出的 SHA-256 完全一致；bundled schema 禁止
  `$id`，只允许本地 fragment 或 bundle 内已有 digest URI。解析器构建完整内存映射后再
  校验，禁止 HTTP、文件系统、包搜索或其他隐式回退。

该 admissibility profile 只决定 schema 是否允许注册，并收紧明显的跨语言差异；超出 profile
的 schema 不是“尽力校验”，而是在注册阶段明确拒绝。它没有穷举所有允许 keyword 的
work-unit 计数，因此单凭本节不能实现或宣称 portable semantic validator；完整求值预算的硬
前置依赖见“可移植资源预算框架”。

#### namespace 与 capability 消费侧不变量

本 RFC 不定义 AuthoritySnapshot、DomainPlugin 或 ControlPolicy 的字段、签名、序号、转移/
撤销生命周期或查询 API，只要求后续契约满足以下 CognitiveNode 消费条件：

- 每次类型解析都绑定一个不可变、可验证且作用域明确的权威快照；不得从环境隐式选择。
- 快照必须能让 consumer 唯一判定 `type_id` 的 owner 是否可信，以及 required capability 是否
  在当前作用域成立。缺失、冲突或撤销必须映射为下文唯一的 CognitiveNode 外部结果。
- consumer 不得回退到 DNS、网络 registry、本机插件目录或“先到先得”猜测所有权。
- capability ID 复用完整 `type_id` ASCII grammar，并追加 canonical
  `@MAJOR.MINOR.PATCH`；禁止通配符、范围、prerelease 和 build metadata，例如
  `org.intelliengine.runtime/python-execute@1.0.0`。capability 始终不等于 permission。
- 同一 `(type_id, type_version)` 不得被不同 JCS bytes 覆盖，同一 `type_id` 不得漂移
  `base_kind`；consumer 必须获得稳定冲突结果。

未来 DomainPlugin RFC 只定义 namespace claim/evidence 的发布，独立 ControlPolicy RFC 只定义
capability/permission 结论；权威快照的结构和提供者由这些后续契约的架构审查另行归属，本
RFC 不作分配。所需后续契约均合并前，生产类型解析被阻塞，只能用明确的测试前提模拟
“不可变且可验证的快照已提供”。

第一版只允许声明式 JSON Schema，不允许在类型定义中内嵌脚本、二进制、提示词或回调。
学科求解器和更深语义校验属于插件实现，并须由未来 DomainPlugin 与 ControlPolicy 契约
显式约束。schema/fixtures 可以先实现，但不得在本 RFC 中补写其他契约的具体结构。

### 7. 数据流

1. 解析服务或用户操作产生候选 `data` 和 ProvenanceRecord 引用。
2. cognitive-ir 的 transport 只校验 JSON profile 和封套，不查询类型注册表。
3. semantic 固定权威/registry snapshot，解析类型定义并校验 `data_schema`。
4. 控制平面分别检查调用方权限、精确 capability grant 和平台安全上限。
5. 通过校验与授权的候选节点由后续 ChangeSet/ControlPlane 契约附加原子前置条件和幂等
   标识，接受审查并提交。
6. KnowledgeUnit 和 Thoughtflow 仅保存 `CognitiveNodeRef`，不复制权威节点内容。
7. 执行结果或人工修订通过新 ProvenanceRecord 和更高 revision 回写；不得改变历史 revision。

第 4、5、7 步都会产生副作用，因此不能由 CognitiveNode 反序列化或类型 schema 校验自动触发。

## 公共接口

### 1. 序列化

本契约采用 RFC 8259 JSON 的下列 I-JSON-compatible 可移植数据 profile，并以 RFC 8785
JCS 规范字节作为
唯一 canonical representation：

1. 输入必须是无 BOM 的 UTF-8 JSON object。任一嵌套层出现重复对象键都立即以
   接口自己的结构错误拒绝：CognitiveNode 使用 `cognitive_node.duplicate_key`，TypeDefinition
   使用 `type_definition.invalid_structure`；不得采用 first-wins、last-wins 或合并行为。
2. 字符串必须是 Unicode scalar value 序列。无效 UTF-8、未配对 UTF-16 surrogate 和
   非法 escape 在 CognitiveNode 使用 `cognitive_node.invalid_unicode`，在 TypeDefinition 使用
   `type_definition.invalid_structure`。不得执行 NFC/NFD 等 Unicode normalization；相同视觉
   文本的不同 code-point 序列仍是不同值。
3. JSON number 必须能表示为有限 IEEE-754 binary64 并按 JCS/ECMAScript 规则重序列化；
   溢出、NaN 和 Infinity 拒绝；CognitiveNode 使用 `cognitive_node.invalid_number`，
   TypeDefinition 使用 `type_definition.invalid_structure`。整数值若超出
   `[-9007199254740991, 9007199254740991]`，
   必须改用符合 `^(0|-?[1-9][0-9]*)$` 的十进制字符串。需要任意精度小数的类型必须在
   `data_schema` 中定义字符串/结构表示，不得依赖语言私有 decimal 或大数 JSON number。
4. JCS 递归按未转义属性名的 unsigned UTF-16 code units 排序对象键，并保持普通数组顺序。
   普通数组顺序有语义，不得被 canonicalizer 重排。
5. 集合数组是显式例外：`provenance_refs`、`required_capabilities` 必须去重并按元素 UTF-8
   bytes 的 unsigned lexicographic order 升序；`schema_bundle` 按 `uri` 使用同一规则排序。
   validator 拒绝未排序输入，不替调用方静默重排。类型自己的 set-like 数组必须在 schema
   和类型语义中另行给出唯一性与排序规则，否则按有序数组处理。
6. 字段名固定使用 `snake_case`。同一 contract/definition-format major 的未知封套元数据
   字段必须按 JSON 值无损保留；不承诺保留原始空白、escape 词法、数字词法或对象键顺序。
7. `data` 是否允许未知字段由精确 `data_schema` 决定，封套验证器不得替类型定义猜测。

解析器先按上述 profile 构建规范 JSON 值，再产生 JCS UTF-8 bytes。内容摘要、签名、
`(id, revision)` 所映射版本内容的不可变比较、幂等重放内容比较和 schema bundle 摘要全部
使用这些规范字节。
原始输入 blob 不属于 CognitiveNode；若产品需要保留它，只能由 ingestion/provenance 层作为
单独原件保存。这样，语义等价但空白或对象键顺序不同的输入映射到同一规范对象，而重复键
等有歧义输入不会进入对象模型。

### 2. 版本与兼容规则

封套、类型定义封套和学科类型分别独立使用 SemVer，且持久化版本都禁止 prerelease/build
metadata：

| 变化 | 版本级别 |
|---|---|
| 文档澄清、且不改变有效实例集合 | patch |
| 新增可选字段、放宽合法值、增加非必需元数据 | minor |
| 删除/重命名字段、增加必填字段、收紧合法值、改变字段语义 | major |

兼容行为：

- 不支持的 `contract_version` major：CognitiveNode 校验失败；外层容器可以保留原始 blob，
  但不得把它声明为已解析节点。
- 相同 contract major 的较新 minor：transport 验证已知必填字段并按 JSON 值保留未知字段；
  修改、重签名或提交之前必须升级到完整理解该 minor 的写入方。
- 精确注册的 `type_id + type_version`：可以进行完整 semantic 校验。
- 只注册同 major 的较旧类型定义：如果 `data` 仍能通过本地 schema，可标为
  `compatible_read`；否则降级为 opaque。`compatible_read` 只允许明确标注版本差异的只读
  展示、搜索和导出，不允许求解器、运行时、Thoughtflow 控制分支、mutation、自动迁移或
  任何副作用。写入必须使用精确类型定义。
- 锁定快照中不存在 `type_id`：semantic 返回
  `opaque + cognitive_node.unknown_type`。
- 锁定快照中存在 `type_id`，但没有可接受的 `type_version`（包括只存在不同 major）：semantic
  返回 `opaque + cognitive_node.unsupported_type_version`。
- 类型定义存在但当前权威快照明确判定 owner 不可信、已撤销或不匹配：semantic 返回
  `opaque + cognitive_node.untrusted_type`。上述三类都不得执行、修改或迁移。

类型定义一旦被已提交节点引用，不得原地替换。迁移必须是显式、可审查、可回滚的
`old CognitiveNodeRef -> new CognitiveNodeRef` 过程，并创建新的 ProvenanceRecord。

### 3. revision mutation 的消费侧不变量

本 RFC 不定义 mutation request、ChangeSet、operation ledger、重试窗口或审计记录的字段和
生命周期，只要求未来 ChangeSet/ControlPlane 契约为 CognitiveNode 提供以下行为：

1. mutation 只在 candidate 已得到 semantic `object_result=valid` 后运行。
2. 提交必须包含原子前置条件，能唯一表达“首次创建时该 ID 不存在”或“更新时预期当前
   CognitiveNodeRef”；检查与写入不可分割。
3. 首次创建使用 revision `1`。同一权威 lineage 的更新使用相同 ID 且 revision 精确递增 `1`；
   无 revision authority 时必须遵守 fork-on-write。
4. 提交必须携带幂等标识。相同逻辑提交的重放返回第一次的 outcome 和同一 ref，不新增
   revision/provenance；同一标识对应不同逻辑提交时返回稳定 conflict。
5. 同一 `(id, revision)` 只能对应一组 JCS bytes；竞争、过期前置条件、幂等冲突和 revision
   authority 冲突都不得自动改号或静默重基。
6. migration/rollback 复用同一原子和幂等保证，但具体请求结构、保留期和恢复协议由后续 RFC
   决定。

`revision` 为正安全整数属于 transport 结构检查；“是否单调、是否当前、是否唯一、是否有
revision authority”只在 mutation 阶段判定。发生 conflict 后，调用方必须重新读取状态并按
后续契约显式重试；不得把旧候选静默套到新 revision。

### 4. 校验模式、诊断与结果

所有 transport、semantic、TypeDefinition registration 和 mutation 结果都使用两个正交字段：

- `object_result = valid|invalid|compatible_read|opaque|not_evaluated`，只陈述被检查对象；
- `operation_outcome = succeeded|conflict|policy_denied|resource_exhausted|indeterminate`，
  只陈述本次操作是否完成及未完成原因。

具体函数名和承载结构由后续实现 Issue 决定，但下表是封闭、穷尽的合法状态对：

| 模式 | 进入条件与检查 | 合法 `(object_result, operation_outcome)` |
|---|---|---|
| `transport` | JSON profile、封套局部结构、版本语法、基础种类、非空来源引用 | `(valid, succeeded)`；`(invalid, succeeded)`；`(not_evaluated, resource_exhausted)`；`(not_evaluated, indeterminate)` |
| `semantic` | 仅 transport valid；绑定权威快照、解析类型、校验 schema | `(valid, succeeded)`；`(invalid, succeeded)`；`(compatible_read, succeeded)`；`(opaque, succeeded)`；`(not_evaluated, resource_exhausted)`；`(not_evaluated, indeterminate)` |
| `mutation` | 仅 semantic 精确版本 valid；检查引用、authority、原子前置条件、权限/能力 | `(valid, succeeded)`；`(valid, conflict)`；`(valid, policy_denied)`；`(valid, resource_exhausted)`；`(valid, indeterminate)` |

未列出的任何状态对均为契约错误，consumer 必须拒绝而不是猜测含义。例如 transport 的
`(opaque, succeeded)`、semantic 的 `(valid, policy_denied)`、mutation 的
`(opaque, succeeded)`、任一模式的 `(invalid, resource_exhausted)` 均非法。TypeDefinition
registration 只使用其下方错误码表明确列出的状态对，不扩展上述三种模式。
复制/导出属于未来 ProjectPackage 操作，不属于 semantic 或 mutation；其安全检查保留已有
`opaque` object result，并在安全章节单独规定 operation outcome。mutation 中的
`policy_denied` 则始终保留 `object_result=valid`。

transport 不查询类型注册表，也不返回 opaque。未知、缺失、禁用、不可信或版本不兼容的
类型都必须先通过 transport，然后仅由 semantic 查询固定快照后判为 opaque。mutation 不接收
`opaque`、`compatible_read` 或 `invalid` 对象；这些状态不会作为 mutation 结果出现。

典型组合：结构错误是 `invalid + succeeded`；未知类型是 `opaque + succeeded`；权限拒绝发生
在 semantic valid 之后，因此必须是 `valid + policy_denied`；revision/authority/idempotency
竞争是 `valid + conflict`；在得出对象结论前超过固定或已锁定的确定性预算是
`not_evaluated + resource_exhausted`；外部依赖不可验证是
`not_evaluated + indeterminate`。operation outcome 不得被改写为对象 invalid。

#### 多错误诊断

校验报告至少包含稳定 `code`、JSON Pointer `path`、`severity` 和可选结构化 `details`。
`severity` 值集固定为 `error|warning|info`；本地化 `message` 不是机器接口。规则如下：

- 解析失败、重复键、非法 Unicode 和在构树前触发的 size/depth 上限会短路，因为不存在可信的
  完整 JSON tree；后续机器契约锁定后的 schema work-unit 耗尽会短路当前 semantic 阶段，因为
  无法得出完整对象结论，即使 JSON tree 已经存在也不得继续聚合成 `invalid`。
- semantic 只在 transport 为 valid 后运行；mutation 只在 semantic 精确版本 valid 后运行。
- 同一阶段收集所有可独立判定的问题，最多 100 个。相同
  `(code, path, JCS(details))` 去重；超过上限时，CognitiveNode 接口增加一次
  `validation.issues_truncated` warning，TypeDefinition 接口增加一次
  `type_definition.issues_truncated` warning。warning 不改变状态对。
- 输出先按 severity `error < warning < info`，再按 path、code 的 unsigned UTF-8 bytes，最后
  按 `JCS(details)` 排序。issues 是规范有序数组，不是调用方可重排的集合。
- warning/info 不会把 valid 改成 invalid；opaque、compatible_read 和其他非 valid 状态由
  阶段结果决定。失败时不得返回“部分有效”的可变节点。

#### 可移植资源预算框架

下列 JSON/封套 size/count 上限是本 RFC 可直接执行的最低输入边界；计数基于解析后的 JSON
值或 JCS UTF-8 bytes，与机器速度无关。它们本身不足以声称已具备 portable semantic
validator：

| 资源 | portable 上限 |
|---|---:|
| 单个 CognitiveNode JCS bytes | 1,048,576 |
| 单个 TypeDefinition（含 bundle）JCS bytes | 2,097,152 |
| JSON 最大嵌套深度 | 64 |
| object members + array elements 总数 | 100,000 |
| 单个字符串 UTF-8 bytes | 262,144 |
| 单个数组元素数 | 10,000 |
| schema bundle resources | 128 |
| 单次 `$ref` 解析链 | 64 |
| 单个 regex Unicode scalar 数 | 1,024 |
| schema validation work-unit 上限 | 本 RFC 不规定；由后续锁定的 schema-profile 机器契约给出 |

work-unit 在本 RFC 中只是预算框架，不是可直接实现的计数算法。后续 schema-profile 机器契约
必须穷举所有允许 keyword 的计数规则、applicator 分支和数组元素的访问规则、`$ref`/递归、
regex、`uniqueItems` 等成本、求值/短路顺序、精确总上限及边界 fixtures。该机器契约及 fixtures
接受并合并，是实现任何 portable semantic validator 的硬前置条件；在此之前，实现不得自定
work-unit、宣称 portable conformance，或用本节示例推导缺失规则。本 RFC 不定义该机器契约的
字段或文件格式。

本契约的 CognitiveNode/TypeDefinition consumer 只依赖以下不变量：同一已锁定 schema profile
与 fixture 在各符合实现中必须产生相同计数和结果；实现优化不得改变机器契约规定的逻辑
计数；超过固定 size/count 上限或已锁定 work-unit 上限返回
`object_result=not_evaluated + operation_outcome=resource_exhausted`，不声称对象结构非法。
外部 code 必须按被调用接口选择，TypeDefinition 不得复用 `validation.*`。
实现可以提供更高的本地只读上限，但不得把超限对象提交或导出为 portable-valid。对同时在
已锁定 profile 的 size/count/work-unit 上限内的输入，portable-conforming validator 必须完成并
得出相同 object result，不得配置更低 wall-clock timeout。宿主被外部中断或 validator 服务
不可用时只能返回 `not_evaluated + indeterminate`，该次运行不能作为 portable conformance
证据，且永远不能把对象标成 invalid。平台可以在 semantic valid 后拒绝 mutation，此时返回
`valid + policy_denied`，不能用较低策略预算伪装 validation 结论。这四类结果保持正交。

下表只属于 CognitiveNode transport/semantic/mutation；TypeDefinition 不得返回其中的
`cognitive_node.*` 或 `validation.*` code：

| code | 条件 | `object_result` | `operation_outcome` |
|---|---|---|---|
| `cognitive_node.invalid_json` | 不是合法 JSON object | `invalid` | `succeeded` |
| `cognitive_node.duplicate_key` | 任意 JSON object 出现重复键 | `invalid` | `succeeded` |
| `cognitive_node.invalid_unicode` | 无效 UTF-8、非法 escape 或未配对 surrogate | `invalid` | `succeeded` |
| `cognitive_node.invalid_number` | 数字不满足 binary64/safe-integer profile | `invalid` | `succeeded` |
| `cognitive_node.noncanonical_set` | 规定的集合数组重复或未按规则排序 | `invalid` | `succeeded` |
| `cognitive_node.missing_field` | 缺少必填封套字段 | `invalid` | `succeeded` |
| `cognitive_node.invalid_id` | ID 不是 canonical lowercase UUID | `invalid` | `succeeded` |
| `cognitive_node.invalid_revision` | revision 不是正安全整数 | `invalid` | `succeeded` |
| `cognitive_node.unsupported_contract_version` | contract major 不支持 | `invalid` | `succeeded` |
| `cognitive_node.invalid_base_kind` | 不在闭合集合中 | `invalid` | `succeeded` |
| `cognitive_node.unknown_type` | 绑定快照中不存在该 type_id | `opaque` | `succeeded` |
| `cognitive_node.untrusted_type` | 定义存在，但绑定快照明确判定 owner 不可信、已禁用或已撤销 | `opaque` | `succeeded` |
| `cognitive_node.unsupported_type_version` | type_id 存在，但没有可接受版本，包括 type major 不兼容 | `opaque` | `succeeded` |
| `cognitive_node.type_resolution_indeterminate` | 权威快照缺失、不可验证或给出冲突权威结论 | `not_evaluated` | `indeterminate` |
| `cognitive_node.base_kind_mismatch` | 节点与类型定义的基础种类不同 | `invalid` | `succeeded` |
| `cognitive_node.invalid_data` | data 不符合类型 schema | `invalid` | `succeeded` |
| `cognitive_node.missing_provenance` | provenance_refs 为空 | `invalid` | `succeeded` |
| `cognitive_node.revision_conflict` | 原子前置条件过期、revision 非预期增量或唯一键竞争 | `valid` | `conflict` |
| `cognitive_node.revision_authority_conflict` | 无唯一 authority 却继续原 ID，或出现竞争 lineage | `valid` | `conflict` |
| `cognitive_node.idempotency_conflict` | 同一幂等标识对应不同逻辑提交 | `valid` | `conflict` |
| `cognitive_node.unresolved_provenance` | mutation 时 provenance 引用不可解析 | `valid` | `conflict` |
| `cognitive_node.unresolved_reference` | mutation 时固定 revision 引用不存在 | `valid` | `conflict` |
| `validation.resource_exhausted` | 超过本 RFC 固定 size/count 上限，或超过已锁定 schema-profile 机器契约的 work-unit 上限 | `not_evaluated` | `resource_exhausted` |
| `validation.interrupted` | validator 不可用或宿主外部中断 | `not_evaluated` | `indeterminate` |
| `cognitive_node.mutation_resource_exhausted` | semantic valid 后，mutation 外部检查超过确定性预算 | `valid` | `resource_exhausted` |
| `cognitive_node.mutation_indeterminate` | semantic valid 后，mutation 外部依赖无法确定结果 | `valid` | `indeterminate` |
| `cognitive_node.permission_denied` | semantic valid，但调用方无 mutation 权限 | `valid` | `policy_denied` |
| `cognitive_node.capability_denied` | semantic valid，但环境缺少 required capability | `valid` | `policy_denied` |

#### 类型定义与注册结果

TypeDefinition 校验/注册也复用正交字段。成功注册是 `valid + succeeded`；失败不得产生部分
entry。该接口只暴露 `type_definition.*`，内部 registry 原因不得直接返回给 CognitiveNode
consumer。TypeDefinition 接口的封闭合法状态对为：`(valid, succeeded)`、
`(invalid, succeeded)`、`(valid, policy_denied)`、`(valid, conflict)`、
`(not_evaluated, resource_exhausted)`、`(not_evaluated, indeterminate)`。未列出的组合非法；该
接口不产生 `opaque` 或 `compatible_read`。结构、字段和 schema 错误属于对象 invalid；资源
耗尽和外部中断发生在无法完成对象结论时；policy/conflict 只在定义对象 valid 后发生。

稳定错误码如下：

| code | 条件 | `object_result` | `operation_outcome` |
|---|---|---|---|
| `type_definition.invalid_structure` | 缺少必填字段、根不是 object、重复键、非法 Unicode/number，或 envelope/集合结构无效 | `invalid` | `succeeded` |
| `type_definition.invalid_field` | type_id、type_version、base_kind、owner、provenance 或其他普通字段值/格式无效 | `invalid` | `succeeded` |
| `type_definition.namespace_denied` | 定义有效，但绑定快照明确否定 owner/作用域 | `valid` | `policy_denied` |
| `type_definition.untrusted_owner` | 定义有效、namespace 匹配，但 owner 被明确判定不可信、禁用或撤销 | `valid` | `policy_denied` |
| `type_definition.capability_denied` | 定义有效，但策略明确拒绝其 required capability 声明或注册 | `valid` | `policy_denied` |
| `type_definition.immutable_key_conflict` | 同一注册键已有不同 JCS bytes | `valid` | `conflict` |
| `type_definition.base_kind_drift` | 同一 type_id 的 base_kind 与既有定义不同 | `valid` | `conflict` |
| `type_definition.invalid_capability_id` | capability ID 语法、排序或版本无效 | `invalid` | `succeeded` |
| `type_definition.invalid_format_version` | definition format SemVer 无效或 major 不支持 | `invalid` | `succeeded` |
| `type_definition.invalid_schema` | schema 结构/profile 无效、根类型不允许，或 regex 不符合 portable admissibility 规则 | `invalid` | `succeeded` |
| `type_definition.unsupported_schema_vocabulary` | schema 使用 profile 外 vocabulary/keyword | `invalid` | `succeeded` |
| `type_definition.forbidden_ref` | `$ref` 非本地 fragment/digest URI，或 bundle 摘要不匹配 | `invalid` | `succeeded` |
| `type_definition.resource_exhausted` | 超过固定 TypeDefinition 大小、深度、成员、字符串、数组、bundle/ref/regex 限制 | `not_evaluated` | `resource_exhausted` |
| `type_definition.validation_indeterminate` | TypeDefinition validator 被外部中断或校验服务不可用，无法完成对象结论 | `not_evaluated` | `indeterminate` |
| `type_definition.authority_indeterminate` | 注册所需权威快照缺失、不可验证或冲突 | `not_evaluated` | `indeterminate` |

分类必须按最具体 code 输出：definition format 和 capability ID 分别使用其专用 code；其他普通
字段错误使用 `invalid_field`；schema、未知 vocabulary 和 forbidden ref 分别使用对应 code；
资源超限与外部中断分别使用 `resource_exhausted` 和 `validation_indeterminate`。一个具体缺陷
不得再以 `cognitive_node.*`、`validation.*` 或 registry 内部 code 重复暴露；多个不同 path 的
独立缺陷仍按多错误诊断规则聚合。

唯一外部映射按互斥顺序判定：锁定快照中 `type_id` 不存在，只映射为
`cognitive_node.unknown_type`；`type_id` 存在但没有可接受版本（包括 major 不兼容），只映射为
`cognitive_node.unsupported_type_version`；定义存在但当前权威明确不可信、禁用或撤销，只映射为
`cognitive_node.untrusted_type`；快照缺失、不可验证或权威冲突，只映射为
`cognitive_node.type_resolution_indeterminate`。同一 semantic 输入不得同时返回
`cognitive_node.unknown_type` 与 `cognitive_node.unsupported_type_version`。
不得同时向同一调用方暴露 registry 内部 code 和 `cognitive_node.*` 两套 code。内部 registry
诊断可用于受限运维日志，但不是公共接口。

### 5. 与其他公共契约的关系

#### ProvenanceRecord

- CognitiveNode 只持有 `provenance_refs`，不内联原件、摘录或转换图。
- 新建、派生、迁移和回滚 revision 都必须有来源记录。
- ProvenanceRecord 的 ID 格式、不可变字段和派生图由其独立 RFC 决定；本 RFC 暂时只要求
  非空引用和提交时可解析。

#### KnowledgeUnit

- KnowledgeUnit 聚合一个或多个 `CognitiveNodeRef`，但不拥有或复制节点。
- KnowledgeUnit 的版本变化不会隐式修改 CognitiveNode；反向亦然。
- KnowledgeUnit 是否要求引用 semantic-valid 节点，由其契约决定。

#### Thoughtflow

- Thoughtflow 把 `CognitiveNodeRef` 用作输入、输出、上下文或声明性参数。
- Thoughtflow 执行不得直接修改节点；任何结果通过 ChangeSet 创建新 revision。
- `action` 和 `experiment` 节点只是描述，不能因进入 Thoughtflow 而自动获得执行权限。

#### DomainPlugin

- 未来 DomainPlugin 契约负责发布类型定义和提供 namespace claim/evidence；权威快照如何
  形成不由本 RFC 决定。
- 本 RFC 不提前规定 DomainPlugin 的 manifest 字段或加载 API。
- 缺少、禁用或不可信插件时，其节点必须降级为 opaque，而不是静默转成 core 类型。
- 生产类型解析在 DomainPlugin namespace 发布契约和 ControlPolicy capability/permission
  契约分别合并前处于阻塞；测试快照不得被误标为生产权威。

#### ProjectPackage

- 未来 ProjectPackage 契约必须让 consumer 稳定判定导入节点是只读、已证明唯一 revision
  authority，还是必须 fork；本 RFC 不规定证明字段或转移流程。
- ProjectPackage 还必须为 opaque 导出提供受保护数据检查 outcome；本 RFC 只消费该结论。

#### ControlPolicy 与 ChangeSet/ControlPlane

- ControlPolicy 必须向 consumer 提供稳定的 capability/permission 结论，但其字段、优先级和
  生命周期由独立 RFC 决定。
- ChangeSet/ControlPlane 必须提供原子前置条件、幂等提交和稳定冲突 outcome，但其 request、
  ledger、重试窗口和审计 schema 由独立 RFC 决定。
- CognitiveNode consumer 只依赖这些行为，不拥有或复制上述契约的状态机。

opaque 节点携带的 `base_kind` 只是通过枚举语法检查的未验证声明，可用于明确标注为
“未知类型”的通用展示，不得驱动执行、权限判断、自动迁移或可信语义推断。

## 安全、溯源与控制策略

### 权限与信任

- 读取原始 JSON、transport 校验、semantic 解释、创建、修改、迁移和执行是不同能力。
- 节点作者、类型所有者、Agent 信任等级均不能自动获得项目写入、运行时、文件或网络权限。
- 项目动态类型创建、插件类型注册、节点迁移和 revision 提交必须经过控制平面。
- 平台安全上限优先于全局、项目、团队、Agent、节点和任务范围的策略。

### 数据与执行安全

- `data` 和类型定义一律视为不可信输入。
- JSON 解析必须使用本 RFC 的深度、大小和引用数量边界；schema 校验必须消费后续锁定机器
  契约给出的线性 regex 与确定性 work-unit 预算。机器契约合并前不得实现 portable semantic
  validator；wall-clock timeout 不是对象有效性规则。
- baseline 校验必须确定、无副作用、离线，不得执行脚本、加载原生库或访问网络。
- opaque 节点可被列出，也可成为复制、导出或删除的候选（相关操作仍需权限与下述检查）；
  不得被求解、渲染为可信语义、自动迁移或作为运行时参数执行。
- opaque 的 `data` 必须被视为可能含有密钥、凭据、用户私有全局 Agent 记忆或其他受保护
  内容。复制/导出前必须由 ProjectPackage 边界和控制平面执行受保护数据检查并显式授权；
  检查不可用时保留 `object_result=opaque`，并返回 `operation_outcome=indeterminate`；策略
  拒绝时返回 `opaque + policy_denied`，不得默认放行。本 RFC 不定义 ProjectPackage 字段。
- 日志默认只记录 ID、revision、type、版本、状态和错误码，不记录敏感 `data` 或原件内容。

### 审计与回滚

- 类型注册、namespace 所有权变化、节点创建/修改/迁移、授权拒绝和回滚均写入控制平面审计。
- 回滚不删除或覆盖历史 revision；后续 ChangeSet/ControlPlane 契约必须让回滚满足本 RFC 的
  原子前置条件和幂等消费要求，并创建新 provenance 和更高 revision。
- 当绑定的权威快照明确判定类型不可信时，节点降级为 opaque；canonical JSON 值和
  provenance 引用仍保留。
- 当前只记录 RFC 接受结论，尚无运行时数据；若产品负责人以后撤回决定，应修订状态与决定
  记录，并在存在 ADR 后按新的 ADR 替代流程处理。

## 示例

以下 UUID、provenance ID 和类型数据仅用于说明提案，不表示其他契约已经确定。

### 有效 envelope：core entity

该实例只证明 JSON profile 和封套；完整 semantic fixture 仍必须配套已注册的
`org.intelliengine.core/entity@1.0.0` TypeDefinition。

```json
{
  "contract_version": "1.0.0",
  "id": "0190c6b8-7a42-7a1b-8c2d-6a3f5b7e9d10",
  "revision": 1,
  "base_kind": "entity",
  "type_id": "org.intelliengine.core/entity",
  "type_version": "1.0.0",
  "data": {
    "name": "pendulum bob"
  },
  "provenance_refs": [
    "prov:source:pendulum-notes:paragraph-12"
  ]
}
```

### 有效：数学插件类型

以下节点与紧随其后的 TypeDefinition 只是 semantic fixture **片段**。完整 fixture 由后续
契约测试提供一个满足消费侧不变量的测试快照，以及最小 provenance/reference stubs；本 RFC
不定义这些依赖的字段。

```json
{
  "contract_version": "1.0.0",
  "id": "0190c6b8-7b03-724f-a6e1-1706659f32cd",
  "revision": 3,
  "base_kind": "relation",
  "type_id": "org.intelliengine.math/equation",
  "type_version": "1.2.0",
  "data": {
    "expression": "x^2 + y^2 = r^2",
    "symbols": ["r", "x", "y"]
  },
  "provenance_refs": [
    "prov:derivation:equation-extraction:42"
  ]
}
```

对应的 TypeDefinition：

```json
{
  "definition_format_version": "1.0.0",
  "type_id": "org.intelliengine.math/equation",
  "type_version": "1.2.0",
  "base_kind": "relation",
  "owner": {
    "scope": "plugin",
    "id": "org.intelliengine.math"
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "minLength": 1
      },
      "symbols": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "uniqueItems": true
      }
    },
    "required": ["expression", "symbols"],
    "additionalProperties": false
  },
  "schema_bundle": [],
  "required_capabilities": [],
  "provenance_refs": [
    "prov:type:math-equation:1"
  ]
}
```

### 可传输但不可语义使用：未知第三方类型

该实例在 `transport` 模式为 `valid`，因为 transport 不查询类型。在 semantic 模式中，
若绑定快照没有该类型，则返回 `object_result=opaque + operation_outcome=succeeded`，唯一外部
code 为 `cognitive_node.unknown_type`。
系统必须按 JSON 值保留 `data`，但不能执行或修改它。

```json
{
  "contract_version": "1.0.0",
  "id": "0190c6b8-7c21-77ea-9c8d-d56e3fd94e34",
  "revision": 1,
  "base_kind": "state",
  "type_id": "org.example.neuroscience/activation-map",
  "type_version": "2.0.0",
  "data": {
    "opaque_vendor_value": "preserve-me"
  },
  "provenance_refs": [
    "prov:import:external-project:7"
  ]
}
```

版本不兼容对照：若同一锁定快照已经包含
`org.example.neuroscience/activation-map`，但只包含 `1.x` 定义，而上述节点请求 `2.0.0`，则唯一
外部 code 是 `cognitive_node.unsupported_type_version`，不得同时返回 `unknown_type`。

### 无效：缺少溯源

```json
{
  "contract_version": "1.0.0",
  "id": "0190c6b8-7d10-72c8-82aa-2b6f86ab2d33",
  "revision": 1,
  "base_kind": "variable",
  "type_id": "org.intelliengine.core/variable",
  "type_version": "1.0.0",
  "data": {"name": "x"},
  "provenance_refs": []
}
```

结果：`cognitive_node.missing_provenance`，组合为 `invalid + succeeded`。

### 无效：基础种类与类型定义冲突

```json
{
  "contract_version": "1.0.0",
  "id": "0190c6b8-7e55-7623-a707-3796bd50f812",
  "revision": 1,
  "base_kind": "action",
  "type_id": "org.intelliengine.math/equation",
  "type_version": "1.2.0",
  "data": {
    "expression": "x = 1",
    "symbols": ["x"]
  },
  "provenance_refs": ["prov:user:1"]
}
```

结果：只返回 `cognitive_node.base_kind_mismatch`，组合为 `invalid + succeeded`；`data` 本身
符合 equation schema，因此不得额外返回 `invalid_data`，也不得把 equation 当作 action 执行。

### 操作拒绝：项目类型占用 core namespace

测试前提：harness 提供一个不可变、可验证的测试快照，明确 `org.intelliengine.core/*`
只归 `packages/cognitive-ir`，且示例 project owner 对该 namespace 没有权限。其余依赖均有效，
因此预期只有一个规范诊断。

```json
{
  "definition_format_version": "1.0.0",
  "type_id": "org.intelliengine.core/custom-secret-type",
  "type_version": "1.0.0",
  "base_kind": "entity",
  "owner": {
    "scope": "project",
    "id": "0190c6b8-7f61-7b0b-a217-7da2ff2d41aa"
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object"
  },
  "schema_bundle": [],
  "required_capabilities": [],
  "provenance_refs": ["prov:user:type-definition:1"]
}
```

结果：`type_definition.namespace_denied`，组合为
`object_result=valid + operation_outcome=policy_denied`；不得额外返回 registry 内部 code。

## 替代方案

### A. 推荐：稳定封套 + 单一命名空间类型 + 类型注册表

优点：核心字段小、跨语言、类型所有权清楚；缺插件时可惰性保留；一个节点只有一个主要
语义，校验和迁移路径确定。代价：跨学科组合需要多个节点和显式引用；类型注册表及
namespace 治理需要额外实现。

### B. 每个节点使用自由 `extensions` 键值映射并叠加多个 facet

优点：一个对象可以同时附加数学、物理和 UI 数据。缺点：facet 冲突顺序、所有权、局部
版本、跨 facet 不变量和删除语义都不明确；未知 facet 可能影响已知 facet 的解释。
第一版不采用，待真实组合用例证明必要后另开 RFC。

### C. 把所有学科类型放进一个中心化封闭联合 schema

优点：工具链简单，所有有效类型编译时可知。缺点：每个插件都必须修改 cognitive-ir，
动态项目类型不可表达，并行开发会持续争用同一契约，违反 contract-first 的扩展目标。

### D. 只定义 `{id, type, payload}`，其余完全交给使用方

优点：字段最少。缺点：没有 revision 固定引用、来源、版本、兼容或安全边界；每个使用方
仍会产生不同含义，无法作为公共契约。

### E. 以接收的原始 JSON blob 作为不可变对象

优点：可以字节级保存空白、escape、数字词法和对象键顺序。缺点：语义相同的 JSON 会因
序列化差异得到不同版本内容表示；重复键的实现差异无法消除，签名和跨语言比较更脆弱。
本提案改为由 provenance 保存原始 blob，CognitiveNode 只使用拒绝歧义输入后的 JCS 规范对象。

## 结果与取舍

### 正面结果

- 通用工具可在不知道学科细节时识别逻辑节点身份、节点版本身份、基础种类、类型和来源。
- 插件与项目动态类型共享一致的命名、版本和安全模型。
- 未知类型不会造成数据丢失，也不会被误执行。
- 固定 revision 引用支持重放、比较、审计和可验证回滚。

### 成本与限制

- 所有节点和类型定义都必须先建立 ProvenanceRecord，创建流程更严格。
- 类型注册表、namespace 所有权和精确版本分发会增加基础设施工作。
- 生产类型解析分别依赖 DomainPlugin namespace 发布和 ControlPolicy capability/permission
  契约，不能只完成本 RFC 就上线。
- JCS/binary64/profile 和 portable resource limits 需要至少两个语言实现维护一致测试向量。
- 原子前置条件和幂等保证会提高 ChangeSet/ControlPlane 复杂度；具体存储模型不由本 RFC 决定。
- 单一主要类型可能导致较细粒度节点图；多 facet 需求需要以后用真实场景重新评估。
- UUID、JSON Schema 2020-12、RFC 8785 和 SemVer 会成为长期格式承诺。

## 迁移、发布、可观测性与回滚

### 迁移与发布顺序

1. 产品负责人已于 2026-08-10 接受全部 16 项推荐方案，本 RFC 只记录该结论。
2. 后续须由另行授权的任务创建 ADR；本次接受记录不创建 ADR，也不启动实现或 Git 发布。
3. 独立 Issue 固化 JSON/TypeDefinition schema、完整 schema-profile 机器契约、全部允许 keyword
   的 work-unit 计数规则、边界向量和语言无关契约测试。
4. 上述机器契约与测试合并后，才独立实现 cognitive-ir 的解析、校验和测试 registry。
5. DomainPlugin namespace 发布 RFC 与 ControlPolicy capability/permission RFC 分别接受并合并后，
   才实现生产类型解析。
6. ChangeSet/ControlPlane 原子前置条件与幂等 RFC 合并后，才实现 mutation 集成。
7. 再分别实现 ProvenanceRecord、KnowledgeUnit 和 Thoughtflow 集成。
8. 最后用数学插件做第一条端到端兼容、opaque 安全导出与回滚验证。

当前仓库没有既有 CognitiveNode 数据，因此没有原地迁移。任何仓库外原型数据都必须
通过单独、显式的导入迁移 Issue 处理，不能由本 RFC 假定兼容。

### 发布门槛

- canonical JSON、TypeDefinition、完整 JSON Schema profile/work-unit 机器契约和契约测试已由
  独立审查者确认；本 RFC 的预算框架不能替代该门槛。
- 至少两个独立消费者使用同一测试向量：一个 producer、一个 consumer。
- 未知/不可信类型、major 不兼容、注册错误、CAS 幂等、权限拒绝、资源边界和回滚测试通过。
- DomainPlugin namespace 发布、ControlPolicy capability/permission 与 ChangeSet/ControlPlane
  原子/幂等契约分别合并；不得用测试快照或本 RFC 中的描述替代发布门槛。
- 公共契约版本、支持范围和类型注册表快照可被诊断工具读取。

### 可观测性

实现至少记录以下不含 payload 的指标或审计维度：校验模式、`object_result`、
`operation_outcome`、错误码、`contract_version`、`definition_format_version`、`type_id`、
`type_version`、所绑定权威输入的稳定诊断标识（若后续契约提供）、`opaque`/`compatible_read`
数量、`resource_exhausted`/`indeterminate`、revision conflict、operation replay、迁移成功/失败和
策略拒绝。
不得把日志或遥测事件结构在本 RFC 中升级为新的公共契约。

### 回滚

- 接受记录尚未进入 ADR 或实现：回退本 RFC 的状态/决定记录即可，无业务数据回滚。
- schema 尚未发布：回退 schema/测试变更，不存在用户数据迁移。
- schema 已发布：不得原地改变已发布版本；发布新 patch/minor/major，并通过 ChangeSet
  创建更高节点 revision。需要撤销的类型降级为 opaque，保留原始数据和来源。

## 测试计划

后续契约测试必须是语言无关的 JSON fixtures，至少覆盖：

1. core envelope 片段通过 transport；数学节点 + TypeDefinition 片段在后续测试补充满足消费侧
   不变量的测试快照和最小引用 stubs 后通过 semantic。
2. 顶层和嵌套重复键、无效 UTF-8、未配对 high/low surrogate、非法 escape 被确定性拒绝。
3. Unicode normalization 不发生：NFC/NFD 视觉等价字符串产生不同 JCS bytes 和摘要。
4. RFC 8785 数字边界向量、`-0`、最小/最大 binary64、溢出、safe integer 边界和 canonical
   大整数字符串在至少两种语言产生相同结果。
5. JCS UTF-16 对象键排序覆盖 ASCII、控制字符、BMP、surrogate pair；普通数组保持顺序，
   三种集合数组覆盖已排序、重复、逆序和相同前缀 UTF-8 bytes。
6. 空白、escape 和对象键顺序不同但 JSON 值相同的输入产生相同 JCS bytes；未知封套字段按
   JSON 值 round-trip，但测试明确不要求保留原始词法 blob。
7. 空 provenance、无效 UUID、revision 为 0/超过 safe integer、未知 base kind、data 非
   object 被拒绝；除 revision 外任意封套/data 变化都要求更高 revision，revision-only 变化拒绝。
8. TypeDefinition 的 definition format/type SemVer 覆盖 canonical 字符串、前导零、
   prerelease/build metadata、未知 minor 元数据 round-trip 和不支持 major。
9. schema、owner、capability、provenance 和 bundle 的 patch/minor/major 变化分别验证演进矩阵，
   同一不可变注册键的不同 JCS bytes 返回 `immutable_key_conflict`。
10. schema admissibility profile 覆盖精确 `$schema`、固定 vocabularies、format annotation-only、未知 `x-`
    annotation、未知 keyword/vocabulary、portable regex 合法子集、嵌套量词和非线性表达式拒绝。
11. `$ref` 覆盖本地 fragment、正确 digest bundle、摘要错配、相对/HTTP/file ref、缺少 bundle、
    循环/ref-depth 边界，并证明校验不产生网络或文件访问。
12. 使用不规定内部字段的测试快照前提，分别覆盖：type_id 不存在只返回
    `cognitive_node.unknown_type`；type_id 存在但无可接受版本（含 major 不兼容）只返回
    `cognitive_node.unsupported_type_version`；owner 不可信/禁用/撤销只返回
    `cognitive_node.untrusted_type`；权威冲突和快照缺失只返回
    `cognitive_node.type_resolution_indeterminate`。同一输入不得同时返回 unknown-type 与
    unsupported-version；capability 覆盖复用 type-id ASCII grammar、canonical 精确版本及
    permission 分离。
13. transport 覆盖全部 4 个、semantic 覆盖全部 6 个、mutation 覆盖全部 5 个合法
    `object_result + operation_outcome` 状态对；另覆盖代表性非法对：transport
    `(opaque, succeeded)`、semantic `(valid, policy_denied)`、mutation `(opaque, succeeded)`、
    任一模式 `(invalid, resource_exhausted)`，并断言 consumer 拒绝。mutation 权限拒绝必须为
    `(valid, policy_denied)`，且 mutation 永不产生 `opaque`/`compatible_read`。
14. `compatible_read` 只允许带版本差异标记的展示/搜索/受控导出；求解、Thoughtflow 分支、
    mutation、迁移和执行全部阻止。
15. 节点与类型定义 base kind 不匹配只产生 `cognitive_node.base_kind_mismatch`；注册操作稳定
    断言 `type_definition.namespace_denied`、`type_definition.immutable_key_conflict`、
    `type_definition.base_kind_drift`、`type_definition.unsupported_schema_vocabulary` 和
    `type_definition.forbidden_ref`。
16. 同一原子前置条件的两项并发 mutation 只有一个 succeeded；失败项为
    `object_result=valid + operation_outcome=conflict`。测试不假定 request 字段名。
17. 相同幂等逻辑提交重放返回同一 ref；复用幂等标识表达不同提交返回 idempotency conflict；
    重复 migration/rollback 不创建额外 revision/provenance，且不假定 ledger 数据模型。
18. 两个项目从同一只读 ref 离线首次修改时，各自生成不同新 ID/revision 1，并各自记录 fork
    provenance；原 ID 不出现两个不同 revision 2。
19. 两个 fork 重新合并时保留 fork IDs；引用重写只随显式合并发生，JCS 相同也不自动折叠
    逻辑节点身份；缺少 authority 却继续原 ID 返回 revision-authority conflict。
20. `CognitiveNodeRef` 固定 revision；provenance 和节点悬空引用只在 mutation 阶段产生
    `valid + conflict`。
21. 本 RFC 每个固定 portable size/count limit 都提供 `limit-1`、`limit`、`limit+1` fixture；
    CognitiveNode 超限返回 `validation.resource_exhausted`，TypeDefinition 超限返回
    `type_definition.resource_exhausted`，两者均为 `not_evaluated + resource_exhausted`，不返回
    invalid，也不跨接口泄漏 code namespace。
22. 后续 schema-profile 机器契约必须为全部允许 keyword 固化计数规则和 executable fixtures；
    至少覆盖 anyOf/oneOf/allOf、递归 `$ref`、contains、uniqueItems、enum、regex 及该契约选定的
    work-unit `limit-1`、`limit`、`limit+1` 边界。本 RFC 不预设这些 fixture 的具体计数。
23. 只有后续机器契约合并后，才验证同一锁定 profile/fixture 在所有 conforming validators
    得出相同计数和结果；外部中断只能返回 `not_evaluated + indeterminate`，且该次运行不能
    作为 conformance 证据。
24. 多错误 fixture 验证 severity 值集、短路边界、去重、100 项截断及规范排序；截断 warning
    在 CognitiveNode 接口为 `validation.issues_truncated`，在 TypeDefinition 接口为
    `type_definition.issues_truncated`。
25. TypeDefinition 覆盖全部 6 个合法状态对和代表性非法对，并逐类断言唯一外部 code：缺字段/
    envelope 结构为 `type_definition.invalid_structure`；普通字段格式为 `invalid_field`，definition
    format 与 capability ID 使用各自专用 code；schema/regex、vocabulary、ref 分别为
    `invalid_schema`、`unsupported_schema_vocabulary`、`forbidden_ref`；固定资源超限为
    `resource_exhausted`；外部中断为 `validation_indeterminate`；namespace、owner trust、
    capability 策略拒绝分别为 `namespace_denied`、`untrusted_owner`、`capability_denied`；注册键
    和 base-kind 冲突分别为 `immutable_key_conflict`、`base_kind_drift`；权威无法判定为
    `authority_indeterminate`。TypeDefinition 调用方不得收到 `cognitive_node.*`、`validation.*`
    或 registry 内部 code。
26. opaque 复制/导出分别覆盖受保护数据检查通过、`opaque + policy_denied` 和
    `opaque + indeterminate`；不得泄露密钥、凭据、私有全局 Agent 记忆或受保护内容。
27. contract major 不兼容被拒绝且不返回部分有效节点；未知相同 major 元数据无损传输。
28. 回滚满足后续契约提供的原子/幂等行为，产生更高 revision，旧 revision JCS bytes 不变。

完整 semantic fixture 必须同时携带 node、精确 TypeDefinition、离线 schema bundle、满足
本 RFC 消费侧不变量的测试快照和最小 provenance/reference stubs；快照/stub 的内部字段由
各自后续契约测试决定，不得用“测试环境预注册”隐藏依赖，也不得由本 RFC 越界固定。

契约 fixtures、实现单元测试和跨模块集成测试必须放在后续独立 Issue 中；本任务不添加
测试实现。

## ADR 冲突审计

| ADR | 审计结论 |
|---|---|
| ADR-0001 模块化单仓库 | 不冲突；契约仍由 `packages/cognitive-ir` 所有，学科实现留在插件 |
| ADR-0002 仓库是长期记忆 | 不冲突；本 RFC 已记录产品接受结论，但仍须由后续获授权任务创建 ADR 才形成长期架构决定 |
| ADR-0003 契约优先并行 | 不冲突；本 RFC 只保留对其他契约的消费不变量，具体字段分别交给独立 RFC，先合并契约/测试再并行 |
| ADR-0004 控制工程元控制层 | 不冲突；类型只声明能力，所有副作用、权限和回滚仍由控制平面处理 |

现有 ADR 均未规定 CognitiveNode 字段、序列化、类型注册或未知类型行为，因此本 RFC
不是对已接受决定的替代 ADR。

## 建议的后续 Issues

### 1. `[Contract] 固化 CognitiveNode JSON Schema 与语言无关测试向量`

- 目的：把接受后的 RFC 转成唯一机器可读契约。
- 范围：节点/TypeDefinition schema、canonical JSON/JCS 向量、完整 schema-profile 机器契约、
  全部允许 keyword 的 work-unit 计数规则与上限、错误码、完整 semantic fixtures 和全部
  portable limit 边界；不实现 validator 或业务行为，也不定义其他公共契约字段。
- 依赖：本 RFC 被接受并创建 ADR。

### 2. `[cognitive-ir] 实现 CognitiveNode 解析、校验与类型注册表`

- 目的：实现 transport/semantic、正交结果、稳定外部错误映射和测试 registry。
- 范围：`packages/cognitive-ir` 消费已合并的 JSON/schema profile 机器契约，实现诊断聚合和
  测试 registry；不自行补写计数规则，也不实现 mutation、生产权威快照、学科类型或控制平面。
- 依赖：后续 Issue 1 的 schema 与契约测试已合并。

### 3. `[RFC] 定义 ProvenanceRecord 契约及 CognitiveNode 引用完整性`

- 目的：确定 provenance ID、不可变性、派生关系和引用解析。
- 范围：ProvenanceRecord 一个公共契约；不修改 CognitiveNode 核心字段。
- 依赖：本 RFC 接受；可与实现 Issue 2 顺序规划，但须在 mutation 集成前合并。

### 4. `[RFC] 定义 DomainPlugin namespace 发布与类型定义交付`

- 目的：决定插件如何发布 TypeDefinition、证明 namespace claim 并供权威解析消费。
- 范围：只定义 DomainPlugin 一个公共契约；不定义 ControlPolicy、mutation 或数学类型。
- 依赖：本 RFC 接受。

### 5. `[RFC] 定义 ControlPolicy capability 与 permission 解析`

- 目的：决定 required capability 和显式 permission 如何在作用域内形成稳定结论。
- 范围：只定义 ControlPolicy 一个公共契约；不定义 DomainPlugin manifest 或 mutation request。
- 依赖：本 RFC 接受；与后续 Issue 4 的接口通过独立契约审查对齐。

### 6. `[RFC] 定义 ChangeSet/ControlPlane 的原子前置条件与幂等提交`

- 目的：决定 request 结构、原子提交、幂等保证、重试窗口、审计和冲突结果。
- 范围：ChangeSet/ControlPlane 边界；不修改 CognitiveNode schema 或替 ProvenanceRecord 定字段。
- 依赖：本 RFC 及后续 Issue 3 接受。

### 7. `[Integration] KnowledgeUnit 与 Thoughtflow 使用固定 CognitiveNodeRef`

- 目的：验证聚合、执行输入输出、revision 固定和回滚不发生接口漂移。
- 范围：跨模块集成测试，不重新定义三个公共契约。
- 依赖：CognitiveNode、KnowledgeUnit、Thoughtflow 各自契约及后续 Issue 6 均已合并。

### 8. `[Interop] 跨语言 canonical/schema/resource conformance`

- 目的：在后续机器契约锁定后，证明至少两个独立实现对 JCS、Unicode、数字、regex、bundle、
  诊断排序、work-unit 计数和资源边界一致。
- 范围：conformance runner 与 fixtures；不实现产品功能。
- 依赖：后续 Issue 1、2 完成。

### 9. `[Plugin: Math] 注册首个数学类型并验证 unknown-type 降级`

- 目的：用真实 equation 类型验证注册、禁用插件、opaque round-trip 和重新启用。
- 范围：`plugins/math` 的一个类型和集成 fixtures；不扩展 CognitiveNode 封套。
- 依赖：后续 Issue 2、4、5、8 完成。

### 10. `[RFC] 定义 ProjectPackage 受保护数据导出门槛`

- 目的：决定 opaque/未知内容导出前的受保护数据检查、拒绝和无法判定行为。
- 范围：只定义 ProjectPackage 一个公共契约；不修改 CognitiveNode 或 ControlPolicy 字段。
- 依赖：本 RFC 及后续 Issue 5 接受。

### 11. `[RFC] 定义 ProjectPackage 导入时的 revision authority 证明`

- 目的：决定导入如何证明只读、authority 转移或必须 fork，并为 ChangeSet 提供消费结论。
- 范围：只定义 ProjectPackage 一个公共契约；不定义 ChangeSet request 或 ProvenanceRecord 字段。
- 依赖：本 RFC 接受；与后续 Issue 3、6 通过独立契约审查对齐。

## 产品负责人决策（已全部接受）

产品负责人于 2026-08-10 明确回复“同意全部推荐方案”。下表第 1～16 项的“推荐值”全部
接受；“真实替代方案”均未采用，但继续保留其主要代价，作为决定审计记录。该结论没有新增
第 17 项决定，也没有改变下表任何技术内容。

| # | 决策 | 推荐值 | 真实替代方案 | 主要代价 | 受影响后续 Issue |
|---:|---|---|---|---|---|
| 1 | canonical 数据域与不可变版本内容 | 拒绝重复键/非法 Unicode；使用 I-JSON/JCS profile，以 JCS bytes/digest 表示版本内容并判断内容相等性与完整性，原始 blob 仅可作 provenance 原件 | 保留原始 blob，并以原始 bytes 表示版本内容 | 同一 JSON 值会因空白/键顺序被视为不同内容，未知字段原样往返更简单但互操作差；两种方案都不改变 `id`/`(id, revision)` 的身份含义 | 1、2、8 |
| 2 | 数字与字符串表示 | binary64 + safe integer；超长整数用 canonical 十进制字符串，任意精度小数由类型 schema 显式编码 | 允许任意精度 JSON number | 跨语言 parser/JCS 摘要难一致；推荐方案要求领域类型显式建模精度 | 1、2、8、9 |
| 3 | TypeDefinition 元版本 | 新增独立 `definition_format_version`；所有持久化 SemVer 禁止 prerelease/build metadata | 绑定 CognitiveNode `contract_version`，或允许 prerelease/build | 独立版本多一个协商维度；绑定方案会让定义封套与节点封套耦合 | 1、2、4 |
| 4 | JSON Schema profile | 固定 2020-12、线性 regex 和离线 digest bundle；实现前由后续机器契约穷举允许 keyword 的 work-unit 规则、上限和 fixtures | 接受任意 2020-12 validator/网络 `$ref`，或由实现各自计算预算 | 推荐方案会阻塞 validator 直到机器契约完成并限制插件表达力；替代方案跨语言、离线结果和资源结论不确定 | 1、2、8、9 |
| 5 | 类型权威与 capability 依赖 | CognitiveNode 只要求解析时绑定不可变、可验证快照并获得稳定结论；快照/策略结构交给独立 RFC | 从本机插件或在线服务临时猜测 | 推荐方案在 DomainPlugin 与 ControlPolicy 各自契约完成前阻塞生产解析 | 2、4、5、9 |
| 6 | mutation 的原子与幂等依赖 | CognitiveNode 只要求原子前置条件、幂等标识和稳定 conflict；request/ledger 交给后续 RFC | 自动重基或 best-effort 去重 | 推荐方案增加下游控制平面工作；替代方案破坏并发重试和审计 | 3、6、7 |
| 7 | 资源耗尽语义 | 本 RFC 固定 size/count 上限，work-unit 上限和完整计数由后续机器契约锁定；用正交结果区分耗尽、拒绝、无法判定与对象 invalid | 所有限制/timeout 都返回 invalid，或各实现自定 work-unit | 推荐方案增加硬前置契约和边界 fixtures；替代方案把环境失败误写成对象事实或造成跨语言漂移 | 1、2、8 |
| 8 | 校验状态模型 | `object_result` 与 `operation_outcome` 正交，并封闭穷举每种模式的合法状态对；transport 不判 opaque，mutation 只接收 semantic valid | 单一 status 同时表达对象和操作，或允许任意两字段组合 | 推荐方案调用方需处理两个字段和非法组合；替代方案会混淆权限拒绝与对象无效 | 1、2、7、9 |
| 9 | `compatible_read` 可执行范围 | 仅带标记的展示、搜索和受控导出；零求解、零控制分支、零 mutation/执行 | 同 major 自动具备完整执行兼容 | 推荐方案牺牲旧 consumer 的自动执行；替代方案会忽略新 minor 语义 | 1、2、7、9 |
| 10 | 最小封套与 provenance | 保留八个必填字段，所有节点含非空 provenance；任一非 revision 序列化变化创建新 revision | 允许临时无来源节点或可选 provenance | 推荐方案提高创建门槛；替代方案产生不可追踪对象和特殊迁移 | 1、3、6 |
| 11 | 学科组合模型 | 单一主要类型 + 固定节点引用；多 facet 延后另开 RFC | 节点内多 facet extensions map | 推荐方案增加节点数量；替代方案需立即解决 facet 冲突、版本和权限 | 1、7、9 |
| 12 | 逻辑节点 ID 格式 | `id` 使用 canonical lowercase UUID，producer 应用 UUIDv7；`(id, revision)` 标识不可变节点版本 | 项目路径 ID、任意 URI 或内容地址 ID | UUID 不可读；其他方案在导入、重命名或循环引用时复杂，且容易混淆逻辑身份与内容摘要 | 1、2 |
| 13 | 跨项目分叉与 revision authority | 导入节点默认只读；无法证明唯一 authority 时首次修改 fork 新 ID/revision 1，并保留 fork provenance | 每个项目都继续原 ID 的 revision 序列 | 推荐方案需要引用重写与合并流程；替代方案会让同一 `(id, revision)` 对应不同内容 | 1、3、6、7、11 |
| 14 | `base_kind` 演进 | v1 闭合集合；新增值提升 contract major | 插件可注册 base kind | 推荐方案新增原语成本高；替代方案使通用 consumer 无法稳定解释 | 1、2、9 |
| 15 | 诊断与注册结果 | 固定正交结果、severity、聚合和唯一外部错误映射；CognitiveNode 与 TypeDefinition 使用各自封闭错误族，后者只暴露 `type_definition.*` | 只返回 boolean/本地化 message，或跨接口复用/同时暴露多套码 | 推荐方案扩大契约测试面；替代方案无法可靠自动化、跨语言对齐或判断错误属于哪个接口 | 1、2、8 |
| 16 | opaque 导出安全 | ProjectPackage/控制平面检查受保护数据，检查不可用时默认不导出 | opaque 一律可无损导出 | 推荐方案可能阻塞合法备份；替代方案可能泄露密钥、凭据或私有记忆 | 5、9、10 |

### 给产品负责人的通俗说明

下列说明与上表一一对应；上表保留精确技术含义，这里只解释产品选择和用户影响。

1. **规范内容格式**
   - 要决定什么：格式不同但含义相同的 JSON，是否算作同一份版本内容。
   - 推荐什么：拒绝有歧义的输入，并把 JSON 转成统一 JCS 内容后再比较或校验完整性。
   - 用户会看到什么：换行、空格或键顺序不同不会制造内容差异，但逻辑节点 ID 不会因此合并。
   - 选替代方案会失去什么：可以原样保留输入字节，但跨工具比较、签名和去重会不稳定。

2. **数字如何保存**
   - 要决定什么：大整数和高精度小数怎样在不同语言中保持一致。
   - 推荐什么：普通数字使用共同安全范围，超大整数和任意精度小数用明确的字符串或结构表示。
   - 用户会看到什么：跨语言打开同一节点时数值不会悄悄改变，但插件要明确高精度格式。
   - 选替代方案会失去什么：写入更自由，但不同语言可能得到不同数值、摘要或校验结果。

3. **类型定义自身如何升级**
   - 要决定什么：类型定义的封套是否拥有独立版本。
   - 推荐什么：使用独立、正式且无预发布后缀的 `definition_format_version`。
   - 用户会看到什么：节点格式和类型定义格式可以分别升级，兼容范围更清楚。
   - 选替代方案会失去什么：版本字段更少，但两种格式会被绑在一起，升级时影响面更大。

4. **允许哪些 schema 规则**
   - 要决定什么：插件能使用哪些 JSON Schema 能力，以及资源消耗怎样跨语言一致。
   - 推荐什么：固定离线、受限的 2020-12 profile，并在实现前完成独立机器契约和预算 fixtures。
   - 用户会看到什么：validator 会晚于机器契约交付，但相同数据在不同环境中结果一致。
   - 选替代方案会失去什么：插件可更快使用更多特性，但离线、安全和跨语言结果无法保证。

5. **谁有权发布类型、环境是否具备能力**
   - 要决定什么：系统依据什么信任类型所有者，并判断当前环境能否使用该类型。
   - 推荐什么：只消费不可变、可验证的权威结论；具体提供方式由后续独立契约决定。
   - 用户会看到什么：缺少可信依据时节点仍可保留，但不会被解释或执行。
   - 选替代方案会失去什么：本机临时发现更方便，但同一项目在不同机器上可能得到不同结论。

6. **并发修改和重试**
   - 要决定什么：两次同时修改或网络重试怎样避免覆盖和重复创建 revision。
   - 推荐什么：要求原子前置条件、幂等标识和稳定 conflict，具体请求结构留给后续契约。
   - 用户会看到什么：冲突会明确提示重新读取，重复请求不会重复产生版本。
   - 选替代方案会失去什么：实现较简单，但可能静默覆盖、重复提交或难以审计。

7. **资源不足时怎样报告**
   - 要决定什么：预算耗尽、服务中断、策略拒绝和数据无效是否要区分。
   - 推荐什么：固定本 RFC 的 size/count 边界；work-unit 由后续机器契约锁定，并保持四类结果正交。
   - 用户会看到什么：系统会说明“数据有错”还是“本次没算完/不允许”，不会把超时说成坏数据。
   - 选替代方案会失去什么：错误接口较简单，但用户和自动化无法判断应修数据、重试还是申请权限。

8. **对象结论和操作结论是否分开**
   - 要决定什么：一个状态是否同时表达对象有效性和操作成功与否。
   - 推荐什么：保留两个正交字段，并只允许本 RFC 穷举的状态对。
   - 用户会看到什么：有效对象被权限拒绝时仍显示对象有效，错误原因更准确。
   - 选替代方案会失去什么：字段更少，但权限、冲突、未知类型和无效数据容易混为一谈。

9. **旧读取方能对新 minor 类型做什么**
   - 要决定什么：只部分理解较新类型时，是否允许执行或修改。
   - 推荐什么：只允许带版本提示的展示、搜索和受控导出，禁止求解、mutation 和执行。
   - 用户会看到什么：旧客户端仍能查看或转交数据，但需升级后才能编辑或运行。
   - 选替代方案会失去什么：自动执行更方便，但可能忽略新版本加入的重要语义或安全限制。

10. **节点最少必须保存什么**
    - 要决定什么：是否所有节点都必须有完整封套和非空来源。
    - 推荐什么：保留八个必填字段，任何版本内容变化都创建新 revision，并始终记录来源。
    - 用户会看到什么：创建步骤更严格，但每个版本都可追踪、比较和回滚。
    - 选替代方案会失去什么：临时创建更快，但会产生无来源、难迁移或不可审计的数据。

11. **跨学科信息怎样组合**
    - 要决定什么：一个节点承载一个主要类型，还是同时叠加多个 facet。
    - 推荐什么：第一版使用单一主要类型，通过固定节点引用组合不同学科内容。
    - 用户会看到什么：可能出现更多小节点，但每个节点的类型和权限边界清楚。
    - 选替代方案会失去什么：单节点更紧凑，但必须立即解决 facet 冲突、版本和删除顺序。

12. **逻辑节点 ID 使用什么格式**
    - 要决定什么：逻辑节点及其不可变 revision 如何被稳定引用。
    - 推荐什么：逻辑节点使用 lowercase UUID；`(id, revision)` 唯一指向一个不可变节点版本。
    - 用户会看到什么：ID 不太易读，但移动、重命名和离线导入不会改变引用。
    - 选替代方案会失去什么：路径或内容地址更直观，但重命名、循环引用和身份/内容区分更复杂。

13. **离线副本修改后是否还是原节点**
    - 要决定什么：两个项目离线修改同一 revision 时如何避免产生两个“下一版本”。
    - 推荐什么：默认只读；无法证明唯一 revision authority 时 fork 新 ID，并保留 fork provenance。
    - 用户会看到什么：合并时会看到两个明确分支，即使内容相同也不会自动合并逻辑身份。
    - 选替代方案会失去什么：ID 数量较少，但同一 `(id, revision)` 可能对应不同内容，无法可靠引用。

14. **基础种类能否由插件新增**
    - 要决定什么：`base_kind` 是平台闭合集合，还是允许插件自由扩展。
    - 推荐什么：v1 保持闭合，新增通用种类必须提升 CognitiveNode contract major。
    - 用户会看到什么：通用工具始终能识别基础种类，但新增平台原语会更慢。
    - 选替代方案会失去什么：插件扩展更快，但未安装插件的工具无法稳定理解节点类别。

15. **错误是否可供程序稳定处理**
   - 要决定什么：只显示文本错误，还是提供稳定状态对、severity 和唯一外部错误码。
   - 推荐什么：保留结构化诊断和唯一外部映射；CognitiveNode 与 TypeDefinition 各用自己的
     错误族，不暴露 registry 内部码。
   - 用户会看到什么：界面、自动化和跨语言客户端能给出一致处理与提示。
   - 选替代方案会失去什么：实现接口更小，但错误来源会混淆，只能依赖易变化的文字，难以
     自动恢复或测试。

16. **未知内容能否直接导出**
    - 要决定什么：系统无法理解 opaque 数据时，是否仍可不检查就复制或导出。
    - 推荐什么：先经过受保护数据检查和授权；检查不可用时默认不导出。
    - 用户会看到什么：某些合法备份可能被暂时阻止，但系统会给出拒绝或无法判定的原因。
    - 选替代方案会失去什么：导出更顺畅，但可能泄露密钥、凭据或用户私有记忆。

若其中任一决定改变封套字段、canonical 数据域、扩展组合、并发或安全边界，应先修订本
RFC，再安排 schema 和实现 Issue；不得在实现任务中临时决定。

## 决定

- 决定者：产品负责人。
- 决定日期：2026-08-10。
- 决定：接受“产品负责人决策（已全部接受）”表中第 1～16 项的全部推荐值；没有新增第
  17 项决定，也没有修改任何推荐值的技术含义。
- 未选替代方案：表中第 1～16 项“真实替代方案”均未采用；该列及“主要代价”列是逐项
  保留的替代方案记录。主要理由是避免跨语言与离线结果漂移，维护逻辑身份、不可变版本、
  溯源、并发与回滚的一致性，防止权限或受保护数据边界被绕过，并保留稳定、可自动化的诊断。
  多 facet、路径/内容地址 ID、任意 schema/数字、隐式权威、best-effort 提交、宽松执行兼容、
  插件扩展 base kind、非结构化错误和无检查 opaque 导出等方案的具体代价仍以表中各行为准。
- 授权边界：本决定只授权在 RFC 中记录架构接受结论；不授权创建或修改 ADR，不授权 schema、
  契约测试、业务代码或下游实现，不授权提交、推送、分支、PR 或任何 GitHub 状态变更。任何
  后续工作仍须独立授权，并遵守“公共契约及契约测试先合并，再并行实现使用方”的既有规则。
