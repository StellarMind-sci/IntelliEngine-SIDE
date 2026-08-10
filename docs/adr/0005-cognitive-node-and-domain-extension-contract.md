# ADR-0005：CognitiveNode 与学科扩展契约

- 状态：已接受
- 日期：2026-08-10
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-001：CognitiveNode 与学科扩展契约](../rfc/0001-cognitive-node-and-domain-extension-contract.md)、[GitHub Issue #1](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/1)、[GitHub Issue #5](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/5)

## 背景

M1 必须先稳定公共契约，才能让数学插件、其他学科插件、KnowledgeUnit、Thoughtflow、
解析服务和 Agent 使用方并行开发。此前仓库只把 `CognitiveNode` 列为计划中的公共契约，
尚未长期固定其封套、身份、序列化、版本、类型扩展、未知类型、安全、诊断和回滚边界。
各使用方若各自定义节点结构，既会造成接口漂移，也可能让扩展数据绕过控制平面、权限检查
或平台安全上限。

产品负责人于 2026-08-10 接受 RFC-001“产品负责人决策”表中的全部 16 项推荐方案。
本 ADR 将这些选择固化为长期架构决定；RFC 中未分配给 CognitiveNode 的其他公共契约字段、
请求结构、存储模型和运行时 API 仍须由各自后续 RFC 或机器契约决定。

## 决定

### 所有权与契约边界

`packages/cognitive-ir` 拥有 CognitiveNode 封套、v1 基础种类、`CognitiveNodeRef`、
`CognitiveNodeTypeDefinition` 扩展规则和校验结果语义，但不拥有学科求解器、UI、原件、
权限策略或副作用执行。`org.intelliengine.core/*` 类型由 `packages/cognitive-ir` 拥有；
第一方学科类型由对应 `plugins/*` 拥有；项目动态类型仅在经控制平面授权的项目范围内拥有。
类型定义只能声明解释数据所需的能力，不能授予能力、权限或信任，也不能覆盖平台安全上限。

CognitiveNode v1 的 `base_kind` 是闭合集合：`entity`、`variable`、`relation`、
`constraint`、`state`、`process`、`goal`、`evidence`、`assumption`、`action` 和
`experiment`。其中 `action` 与 `experiment` 仍是惰性声明数据，不会自行产生副作用。

### 已接受的 16 项选择

1. **规范数据域与不可变版本内容。** 拒绝任意嵌套层的重复键、非法 Unicode 和其他有歧义
   JSON 输入；使用 RFC 8259 的 I-JSON-compatible profile，并以 RFC 8785 JCS UTF-8 bytes
   及其摘要表示规范版本内容、内容相等性和完整性。原始输入 blob 只能作为 provenance 原件
   单独保存。JCS 内容相同不合并逻辑节点身份，也不替代 `(id, revision)` 的版本身份。

2. **数字与高精度表示。** JSON number 必须是有限 IEEE-754 binary64；整数限定在
   `[-9007199254740991, 9007199254740991]`。更长整数使用无歧义的 canonical 十进制字符串，
   任意精度小数由具体类型 schema 显式定义字符串或结构表示，不使用语言私有数值。

3. **TypeDefinition 独立元版本。** `CognitiveNodeTypeDefinition` 使用独立的
   `definition_format_version`，不与 CognitiveNode `contract_version` 绑定。所有持久化的
   `contract_version`、`definition_format_version` 和 `type_version` 都使用无前导零的
   canonical `MAJOR.MINOR.PATCH`，禁止 prerelease 和 build metadata。

4. **可移植 JSON Schema profile。** 类型 schema 固定使用受限的 JSON Schema 2020-12
   profile、可证明线性上界的 regex 子集和离线内容寻址 digest bundle；禁止网络、文件系统、
   包搜索或其他隐式 `$ref` 回退。实现 portable semantic validator 之前，必须先由独立机器契约
   穷举允许 keyword 的 work-unit 计数、求值规则、总上限和边界 fixtures。该机器契约完成前，
   实现不得自定 work-unit 或宣称 portable semantic conformance。

5. **类型权威与 capability 依赖。** 每次类型解析必须显式绑定不可变、可验证且作用域明确的
   权威快照，并从中获得唯一、稳定的 namespace owner 与 required capability 结论；不得从
   DNS、在线 registry、本机插件目录或加载顺序猜测。权威快照、DomainPlugin 和 ControlPolicy
   的结构、签名、生命周期及查询 API 由其各自后续契约决定，CognitiveNode 不预先定义字段。

6. **mutation 原子性与幂等性。** 节点创建、更新、迁移和回滚必须消费原子前置条件、幂等
   标识和稳定 conflict；检查与写入不可分割，相同逻辑提交重放不得产生额外 revision 或
   provenance，竞争和幂等冲突不得自动改号、静默重基或 best-effort 去重。mutation request、
   operation ledger、重试窗口和审计字段由后续 ChangeSet/ControlPlane 契约决定。

7. **资源耗尽语义。** RFC-001 固定的 JSON、封套、bundle、引用和 regex size/count 上限是
   portable 最低边界；schema work-unit 上限及完整计数规则由第 4 项的机器契约锁定。
   资源耗尽、策略拒绝、外部依赖无法判定和对象无效是不同事实，不得把超限、超时或服务中断
   伪装成对象 `invalid`。

8. **正交校验状态。** 所有相关结果分为 `object_result` 与 `operation_outcome`：前者只描述
   被检查对象，后者只描述本次操作。合法值和各模式合法状态对是封闭集合；transport 不查询
   类型注册表且不产生 `opaque`，semantic 只在 transport valid 后运行，mutation 只接收精确
   类型版本的 semantic valid 对象。未列出的状态对必须拒绝，不能猜测含义。

9. **`compatible_read` 的受限能力。** 只理解同一 type major 的较旧定义时，若本地 schema
   仍接受数据，可进行带版本差异标记的只读展示、搜索和受控导出；不得求解、驱动 Thoughtflow
   控制分支、mutation、自动迁移、执行或产生其他副作用。写入必须理解精确类型定义。

10. **最小封套与强制溯源。** CognitiveNode 的八个必填字段是 `contract_version`、`id`、
    `revision`、`base_kind`、`type_id`、`type_version`、`data` 和非空
    `provenance_refs`。除 `revision` 自身外，任何已序列化封套字段（包括未知字段）或 `data`
    JSON 值变化都必须创建更高 revision；不得原地覆盖，只改变 revision 而不改变其他内容也
    是无效转换。用户直接创建的节点同样必须引用来源记录。

11. **单一主要类型与固定引用组合。** 一个节点 revision 只有一个 `base_kind`、`type_id` 和
    `type_version` 组合；跨学科内容通过固定到 `(id, revision)` 的 `CognitiveNodeRef` 组合，
    不在 v1 节点内叠加多 facet `extensions` map。多 facet 只有在真实用例证明必要后才另开 RFC。

12. **逻辑身份格式。** `id` 是稳定、全局唯一的 canonical lowercase UUID，producer 应生成
    UUIDv7；`id` 表示逻辑节点，`(id, revision)` 唯一表示一次不可变节点版本。UUID 不编码项目、
    类型、权限或存储位置，路径变化不得重写 ID，内容摘要也不是逻辑或版本身份。

13. **跨项目 fork-on-write 与 revision authority。** 导入或离线复制可保留原 ID 和历史
    revisions，但默认只读。目标项目无法证明自己拥有该 ID 的唯一 revision authority 时，
    首次修改必须生成新 UUID、从 revision `1` 开始，并以 ProvenanceRecord 记录原
    `CognitiveNodeRef` 的 fork 来源。各 fork 保留不同 ID；合并时引用重写必须显式、可审查并
    保留 fork/reconcile provenance。缺少或冲突的 authority 产生稳定 conflict，不自动选边。

14. **`base_kind` 的 major 演进。** v1 基础种类保持闭合，插件和项目类型只能增加
    `type_id`，不能注册新的 `base_kind`。增加基础种类是 CognitiveNode contract major 变更；
    同一 `type_id` 的所有版本必须保持相同 `base_kind`，改变时必须使用新 `type_id`。

15. **结构化诊断与唯一外部映射。** 结果必须提供稳定 code、JSON Pointer path、固定
    `error|warning|info` severity、确定性聚合、去重、截断和规范排序；本地化 message 不是机器
    接口。CognitiveNode 与 TypeDefinition 使用各自封闭且唯一的外部错误映射，TypeDefinition
    只暴露 `type_definition.*`，不得同时泄漏 `cognitive_node.*`、`validation.*` 或 registry
    内部 code。一个缺陷只映射到一个最具体的公共 code。

16. **opaque 导出默认安全拒绝。** 未知、版本不兼容或不可信类型的数据可按规范 JSON 值无损
    保留，但不得被解释、修改、迁移、求解或执行。ProjectPackage 边界和控制平面必须在复制或
    导出前检查密钥、凭据、用户私有全局 Agent 记忆及其他受保护数据并显式授权；检查不可用时
    保持 `object_result=opaque` 并返回 `operation_outcome=indeterminate`，策略拒绝时返回
    `opaque + policy_denied`，两者均不得默认导出。ProjectPackage 的具体字段由其后续契约决定。

### 版本、兼容与引用规则

- CognitiveNode 封套、TypeDefinition 封套和具体学科类型分别独立使用 SemVer。新增可选字段或
  放宽合法值通常是 minor；新增必填字段、删除或重命名字段、收紧合法值或改变语义是 major；
  不改变有效实例集合的澄清是 patch。
- 不支持的 CognitiveNode contract major 必须拒绝，且不得返回“部分有效”节点；相同 major 的
  较新 minor 可在 transport 中保留未知封套元数据，但修改、重签名或提交前必须完整理解该 minor。
- `CognitiveNodeTypeDefinition` 是 CognitiveNode 契约族的一部分，不新增独立顶层公共契约；
  `(type_id, type_version)` 是不可变注册键，同一 `type_id` 不得发生 `base_kind` 漂移。
- `CognitiveNodeRef` 的最小值对象仅含 `id` 和 `revision`，并固定指向一个节点版本；本 ADR
  不定义 KnowledgeUnit、Thoughtflow 或其他引用方的字段。
- 类型定义缺失、版本不兼容或 owner 不可信时，节点分别以稳定的唯一外部结果降级为 opaque，
  不得静默转换成 core 类型。权威快照缺失、不可验证或冲突时，不得猜测对象结论。

### 安全、溯源、审计与回滚

- `data`、类型定义和 opaque 内容一律视为不可信输入。baseline 校验必须确定、无副作用、离线，
  不得执行脚本、加载原生库或访问网络。
- 读取原始 JSON、transport 校验、semantic 解释、创建、修改、迁移、导出和执行是不同能力；
  类型所有权、节点作者或 Agent 信任等级都不自动授予项目写入、运行时、文件或网络权限。
- CognitiveNode 只持有非空 `provenance_refs`；原件和派生图由 ProvenanceRecord 拥有。创建、
  派生、迁移、fork、reconcile 和回滚都必须保留可解析来源，但其 ID 和字段由后续契约定义。
- 类型注册、namespace 权威变化、节点 mutation、授权拒绝和回滚必须进入控制平面审计；日志默认
  只记录身份、版本、类型、状态和错误码，不记录敏感 `data` 或原件内容。
- 回滚不能删除、覆盖或改写历史 revision。它使用与 mutation 相同的原子和幂等保证，创建新
  provenance 与更高 revision，并保持旧 `(id, revision)` 对应的 JCS bytes 不变。

### 对后续契约的硬依赖

1. 在 CognitiveNode JSON Schema、TypeDefinition schema、完整 schema-profile/work-unit 机器契约、
   语言无关 fixtures 和契约测试接受并合并前，不得实现或宣称 portable semantic validator。
2. DomainPlugin 必须定义 namespace claim/evidence 的发布，ControlPolicy 必须定义稳定的
   capability/permission 结论；二者各自契约接受并合并前，不得实现生产类型解析。
3. ProvenanceRecord 契约必须定义其自身的身份、不可变性和派生关系；该契约及引用完整性规则
   合并前，不得完成 CognitiveNode mutation 集成。
4. ChangeSet/ControlPlane 契约必须提供原子前置条件、幂等提交、稳定冲突、审计和回滚行为；
   该契约合并前，不得实现节点 mutation、迁移或回滚集成。
5. ProjectPackage 契约必须提供受保护数据导出检查结论，以及导入时只读、唯一 revision authority
   或必须 fork 的稳定判定；该契约合并前，不得把 opaque 导出或跨项目 authority 流程发布为完整能力。
6. KnowledgeUnit 与 Thoughtflow 必须由各自契约决定如何消费固定 `CognitiveNodeRef` 及是否要求
   semantic-valid；各契约与 ChangeSet/ControlPlane 依赖合并前，不得进行对应跨模块集成。

以上依赖只规定 CognitiveNode consumer 需要的行为和依赖顺序，不规定 AuthoritySnapshot、
ProvenanceRecord、DomainPlugin、ControlPolicy、ChangeSet、ControlPlane、ProjectPackage、
KnowledgeUnit 或 Thoughtflow 的字段、签名、存储、ledger、生命周期或 API。

## 结果

### 收益

- 通用工具可在不了解学科 payload 时稳定识别节点身份、不可变版本、基础种类、类型和来源。
- 内置、插件和项目动态类型共享同一命名、版本、兼容、安全和诊断模型。
- 未知或不可信类型既不会丢失数据，也不会被误解释或误执行。
- 固定 revision 引用、原子 mutation、幂等提交和强制溯源为重放、审计、跨项目分叉及可验证
  回滚建立统一边界。

### 成本与约束

- 节点和类型定义必须先具备 provenance，创建流程更严格。
- JCS、binary64、受限 JSON Schema、权威快照和跨语言 fixtures 增加基础设施及一致性测试成本。
- portable validator、生产类型解析、mutation、opaque 导出和跨项目导入分别受上述后续契约
  阻塞，不能仅凭本 ADR 上线。
- 单一主要类型会产生更细粒度的节点图；新增通用基础种类需要 contract major 变更。
- UUID、RFC 8785、JSON Schema 2020-12 和 canonical SemVer 成为长期互操作承诺。

### 授权边界

产品负责人接受 RFC-001 并形成本 ADR，只表示上述架构选择已接受。它不等于 schema、契约测试、
实现、数据迁移、发布或生产使用授权，也不授权提交、推送、创建分支或 Pull Request、合并、
GitHub 状态变更或启动下游任务。每项后续工作必须获得独立任务契约和相应操作授权；公共契约
及其契约测试仍须先接受并合并，使用方才能并行实现。

ADR-0005 的发布前置是 `docs/rfc/0001-cognitive-node-and-domain-extension-contract.md` 已先进入
权威分支。在该关联链接目标合并前，本 ADR 只能作为本地候选，不得单独发布，也不得被任何
下游实现引用。

## 验证

- `python scripts/verify_governance.py` 必须通过；该脚本当前只证明 ADR 命名和仓库治理结构。
  ADR 的状态、日期、关联链接及 16 项决定内容由本任务人工核对，并接受独立审查；这些内容不在
  该脚本的验证范围内。
- 后续机器契约必须提供 RFC-001 测试计划要求的语言无关 fixtures，并由至少两个独立消费者
  验证 canonical JSON、数字、schema、资源边界、状态对、诊断映射、fork-on-write、幂等和回滚。
- 后续每个公共契约与实现 Issue 必须独立审查其所有权、兼容性、权限、溯源、资源边界和回滚，
  不得用本 ADR 补写其他契约尚未决定的字段。
