# RFC-007：KnowledgeUnit 受控证据变更契约

- 状态：提案
- 创建日期：2026-08-30
- 关联 Issue：[GitHub Issue #83](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/83)

## 背景与范围

现有 KnowledgeUnit 项目投影可只读计算 `blocked`、`needs_evidence`、`ready`，但不拥有证据写入。现有 `change-set` 1.0.0 仅服务 `agent_runtime.transition`，不得重解释为证据操作。本 RFC 定义后续独立 `knowledge-unit-evidence-change` family 的边界，使 IDE 先预演候选证据变更对工程投影的影响；真实提交另行实施。

## 术语与可见边界

- **候选证据变更**：一个尚未提交的、不可变输入集合上的纯计算请求；不是“证据已经被接受”的声明。
- **证据可用集合**：传入现有 `projectKnowledge` 的规范 `evidence_node_refs` 集合。首版预演只允许计算向其中加入一个精确 `CognitiveNodeRef` 的集合差；不定义删除、替换或任意写入。
- **投影闭包**：以同一 KnowledgeUnit 文档集、可用节点集、契约 root 和候选前后证据集各计算一次 `projectKnowledge` 后，所有 `units`、`node_dependents`、`unit_dependents` 的规范结果。候选节点可能同时改变多个单元，不能只显示用户选择的目标单元。
- **已验证预演**：只在输入锚点、前后摘要和完整投影闭包一致时显示的只读结果；UI 只能标注“未提交 / 未获授权验证”，不得显示“已批准”“已掌握”或“已执行”。

## 目标

1. 用固定 `KnowledgeUnitRef`、候选 `CognitiveNodeRef`、前后投影摘要和精确 ProvenanceRecord 引用描述候选证据变更。
2. 使 ControlPolicy、审批与未来持久化层可验证同一纯计划、目标、scope、context、actor 与来源绑定。
3. 历史 KnowledgeUnit/CognitiveNode revision 不被覆盖；修正以新的批准变更补偿。
4. 默认只读预演；依赖、版本或引用缺失时封闭失败。

## 非目标

- 不修改已发布的 `change-set`、`control-policy`、KnowledgeUnit 或 CognitiveNode 1.0.0。
- 不实现数据库、提交 API、审批服务、授权查询、Agent、RuntimeKernel、网络或用户数据写入。
- 不将工程证据解释为个人掌握、执行成功或权限授予。
- 不把候选证据变更扩展成编辑 KnowledgeUnit、CognitiveNode、Thoughtflow、代码、模型、测试结果或来源原件的入口。

## 提案

### 所有权与隔离

`packages/control-plane` 拥有未来 `knowledge-unit-evidence-change` 1.0.0 的候选变更、纯计划摘要、影响摘要、审批绑定与补偿声明；`packages/knowledge-units` 保持文档和只读投影所有权；CognitiveNode/ProvenanceRecord 分别拥有对象与来源；未来持久化 authority 另行拥有提交账本。该 family 不能与 `change-set` 1.0.0 互换，也不能由同一版本号推导权限或兼容性。

### 最小候选语义

候选须封闭地包含：

- `operation_class: "knowledge_unit.evidence_change"` 与新 family/version，并固定为**新增一个候选证据可用节点**；
- 精确 `knowledge_unit_ref`、候选 `evidence_node_ref`、`authority_scope_ref`、`runtime_context_ref`、`actor_ref`；目标 ref 必须位于规范 catalog，候选节点必须是目标单元的 required-evidence ref。否则拒绝，而不是生成“零影响”伪预演；
- 可复算输入锚点：规范 KnowledgeUnit 文档集、`available_node_refs`、变更前 `evidence_node_refs`、锁定 KnowledgeUnit 契约版本/摘要及各自摘要；`after_evidence_node_refs` 只能等于规范的 before 集合加候选节点，不能由调用方自由指定；
- 精确 `provenance_record_ref`，只引用、不复制原件、提示词、私有记忆或凭据；
- 纯 `projection_input_digest`、`before_projection_digest`、`after_projection_digest`、`plan_digest`、`command_fingerprint`；
- 有界影响：`impact_summary.changed_unit_refs` 必须精确等于完整投影闭包的 before/after 差异，且每个差异均绑定状态与两类 missing-ref 集合；有 Thoughtflow 适配输入时，受影响 step refs 必须等于验证后的 before/after Thoughtflow impact 差异，否则明示 `thoughtflow_impact: "not_evaluated"`，不得让调用方填入任意步骤。候选目标、节点依赖者和全部变化单元必须一致；候选节点已在 before 集合时仅可产生稳定的 `no_change`，不能伪造影响；
- `proposed | approved | rejected | revoked | expired | indeterminate`、有效期和不覆盖历史的补偿声明；`approved` 只能由下述独立审批证据验证，候选 JSON 中的状态字段不是审批事实。

预演器必须以输入锚点中的不可变 KnowledgeUnit 文档、可用节点、候选证据集合和锁定契约 root 重新调用 `projectKnowledge`；仅当 before/after 结果的规范摘要、完整投影闭包和候选计划都完全匹配时才显示预演。调用方声称的 `approved` 状态、自由文本来源或任意路径均不能成为事实。在首个只读预演版本中，即使候选携带 `approved`，也只能给出“审批解析尚不可用”的非授权结果，不能升级展示或解锁任何后续动作。

### 摘要、审批与绑定

每个摘要使用 family 锁定的 JCS bytes、显式 hash-algorithm/version 和 SHA-256；未知算法、算法版本不一致、重复成员、非规范集合或 digest mismatch 一律拒绝。发布契约时须将下表中的覆盖关系写入 machine schema、fixtures 和 lock，禁止只用名称相同的字段推断等价：

| 摘要 | 必须覆盖 |
| --- | --- |
| `projection_input_digest` | family/version、canonical catalog、available set、before/after evidence sets、KnowledgeUnit contract ref/digest |
| `before_projection_digest` / `after_projection_digest` | 对应的完整 `projectKnowledge` canonical result |
| `plan_digest` | operation、target/candidate refs、input/before/after digest、精确 impact closure、补偿声明 |
| `command_fingerprint` | plan digest、actor/scope/context、provenance ref、审批/Policy evidence refs 与有效期 |

候选默认且只能被验证为 `proposed`。未来若页面要显示“审批验证通过的预测”，独立审批 resolver 必须提供精确 `approval_ref`、关联 `control_policy_ref`、状态、有效期、撤销位和规范 decision digest；verifier 必须把它们与 actor、scope、context、operation、target、provenance、plan digest 和 command fingerprint 逐项绑定。现有 `control-policy` 1.0.0 若不支持 `knowledge_unit.evidence_change`，即不构成该证据；在可兼容的独立 Policy/approval family 发布前，不得产生授权的 `approved` 验证结果。

### 审批与提交边界

候选、纯计划和可视化预演恒为 `side_effects: forbidden`。未来真实提交必须在持久化边界重新验证精确目标、当前 input anchors/before 摘要、ProvenanceRecord、ControlPolicy 决策、批准 family、有效期与 CAS 前置条件。任何不匹配、撤销、过期、未知 major、非规范集合、闭包不完整或不可判定投影均拒绝；不自动补齐证据、不隐式 `ready`、不执行模型或 Agent。补偿只能创建新的、同样受批准的候选以恢复另一份证据集合，绝不覆写 KnowledgeUnit、CognitiveNode、来源或既有变更历史。

## 兼容、迁移与发布

已有 `change-set` 1.0.0、ControlPolicy 1.0.0、KnowledgeUnit 1.0.0 与历史文档不变。新 family 以独立 schema、fixtures、JCS lock、诊断和双语言验证发布；未知 major 拒绝，较新同 major 仅兼容读取且不得驱动预演或提交。能力开关默认关闭；本 RFC 不迁移用户数据。

## 验收与测试要求

- transport 拒绝重复成员、BOM、非安全整数、未知字段、非规范 refs 和 `after_evidence_node_refs` 不是 `before + candidate` 的任何输入；
- 双语言验证器对同一 fixture 一致，篡改 before/after/plan/fingerprint/provenance/Policy 任一项均封闭拒绝；
- 预演覆盖补齐单证据、多单元闭包变化、仍缺证据、前置阻断、空影响、过期/撤销/未批准/无效输入，证明不改输入或工程状态；
- 页面只显示已验证差异、完整影响闭包与未提交/未获授权验证边界，不展示敏感内容或宣称掌握/执行完成。

## 备选方案

1. 扩展既有 ChangeSet 1.0.0：拒绝，破坏 agent-runtime 已发布语义。
2. 直接将 evidence ref 加入投影输入：拒绝，缺少审批、来源、回滚与审计链。
3. 仅做 UI 模拟：拒绝，无法与可验证纯计划和未来提交安全衔接。

## 决策与后续

本 RFC 尚未接受。接受后依次建立：新 family 契约/双语言 verifier → 只读预演插件 → ControlPolicy/Provenance 适配 → 默认关闭的 durable 提交与审计。真实写入仍需单独人工审查。
