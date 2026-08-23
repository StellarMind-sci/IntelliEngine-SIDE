# ADR-0007：Thoughtflow v1 显式工程推理图与受约束循环

- 状态：已接受
- 日期：2026-08-24
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-003：Thoughtflow v1 思维链公共契约](../rfc/0003-thoughtflow-contract.md)、[GitHub Issue #32](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/32)、[GitHub Issue #34](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/34)

## 背景

CognitiveNode 已能表达认知对象，KnowledgeUnit 已能围绕固定版本的认知节点组织可验证知识与行为
声明，但 SIDE 尚缺少一种公共结构，把目标、显式工程推理、知识依赖、行为声明、条件分支、验证
反馈和迭代组织成用户可编辑、可检查的工程流程。若 UI、Agent、学科插件和运行时各自定义流程，
代码系统逻辑与用户看到的思维链会发生漂移，行为声明也可能绕开未来的控制平面直接产生副作用。

产品负责人于 2026-08-24 接受 RFC-003 的“受约束循环”方案。本 ADR 固化该决定，不表示机器
契约、Python/TypeScript 消费者、代码双向投影、Agent 自动修改或执行能力已经实现。

## 决定

### 产品含义与所有权

Thoughtflow 是用户可见、可编辑、可版本化的工程推理与控制图，是代码系统逻辑、功能链条和问题
解决过程的抽象。它只保存用户或 Agent 主动写入的目标、分析、决定、证据、验证和迭代，不保存、
要求或推断模型提供商不可见的内部 chain-of-thought，也不把聊天记录自动提升为工程事实。

Thoughtflow 公共契约由 packages/thoughtflow 拥有。其引用的 CognitiveNode 与 KnowledgeUnit
仍由各自模块拥有；Thoughtflow 只保存固定版本引用和显式引用快照，不复制或改写被引用对象。

### 图模型

Thoughtflow v1 固定支持七类步骤：

1. goal：工程目标或待解决问题。
2. analysis：显式分析、假设或推导。
3. operation：拟进行的行为声明及其输入、输出节点覆盖。
4. decision：需要用户、Agent 或未来策略层明确选择的条件分支。
5. verification：对结果、证据或约束的验证。
6. artifact：代码、公式、模型、数据或其他工程产物的显式引用。
7. iteration：验证失败后重新进入分析或调整的受控入口。

固定支持五类转移：sequence、data_dependency、branch、verification_feedback 和 loop。
data_dependency 只表达数据关系，不能伪装控制可达性；branch 必须具有互不重复的显式标签和
唯一默认分支，但只读模拟器不得自动替用户选择默认分支。

### 受约束循环

Thoughtflow v1 允许循环，但必须同时满足以下条件：

- 移除所有 loop 边后，控制图保持有向无环。
- loop 只能从 verification 出发并指向 iteration。
- 循环只允许由 failed 或 needs_evidence 结果触发，不能在通过后继续循环。
- 每个强连通循环区域恰有一个循环控制器和明确的 max_iterations。
- 循环必须存在非 loop 退出路径，达到迭代上限时返回稳定的停止结果，不能继续执行。

普通转移、自环、缺少验证的循环、无上限循环和没有退出路径的循环均无效。该模型允许用户表达
真实的“验证失败—调整—再验证”工程过程，同时保证分析和模拟可终止。

### 引用、修订与结果

CognitiveNodeRef、KnowledgeUnitRef 和 KnowledgeBehaviorRef 必须固定对象身份与版本；
behavior_ref 必须指向对应 KnowledgeUnit 中已声明的 behavior，operation 的输入输出必须覆盖
该 behavior 声明的节点关系。

ReferenceSnapshot 显式区分 available、opaque 和 unavailable 等可观察状态。引用无法读取或
版本不受支持时，结果必须为 not_evaluated 或 indeterminate，不能伪装成对象 invalid；只有已经
取得足够证据并发现悬空或不一致引用时，才能给出 invalid。

同一 Thoughtflow 身份的修订转换必须保持 revision 单调增加，并拒绝无变化修订、回退 revision
或在仅允许追加/替换的转换中改写历史内容。存储层不可变性仍由未来 ProjectPackage、ChangeSet
和溯源服务负责，运行时校验器不得宣称已经证明持久化历史不可变。

### 无副作用与控制边界

Thoughtflow v1 的 operation、behavior 和 artifact 均为声明或引用。解析、校验、图摘要、可达性、
候选下一步和有界模拟不得执行代码，不得写文件，不得访问网络、设备、模型或外部工具，也不得
创建进程。它们不能授予权限、提交 ChangeSet、自动选择分支或把模拟结果写回工程。

未来双向代码投影和真实工程控制必须依次经过 ProjectPackage/代码投影、ChangeSet、ControlPolicy
与 RuntimeKernel，并保留显式权限、溯源和回滚。Issue #22 完成前，项目只宣称应用层只读和确定
性验证，不宣称已获得操作系统级文件或网络隔离，也不开放 portable 写入或执行。

### 实现顺序与兼容性

1. 先以独立 Issue 交付 Thoughtflow 1.0.0 的 profile、schema、diagnostics、fixtures、lock 和
   独立机器验证器，形成语言无关规范证据。
2. 机器契约合并后，再以独立 Issue 交付 Python 与 TypeScript 只读消费者、图查询、有界模拟和
   差分验证；两种消费者不得互相调用或共享业务校验实现。
3. UI、Agent、数学插件和代码投影只能依赖已合并契约，不得各自扩展公共字段或执行语义。
4. 已发布 1.x 机器工件不得原地改写；兼容修复采用新版本、明确兼容期和回滚路径。
5. 改变本 ADR 的产品含义、循环边界、引用结论或副作用边界，必须通过新 RFC 和替代 ADR。

## 结果

### 收益

- 用户、Agent、UI 和学科插件共享同一套可见、可修改的工程推理与控制结构。
- 分支、验证反馈和有限循环能表达真实工程迭代，同时保持可分析、可终止和可回滚。
- 固定版本引用与独立引用快照让知识、认知节点和行为声明之间的关系可验证、可溯源。
- 声明与执行严格分离，为后续控制策略和运行内核保留安全边界。

### 成本与约束

- 契约必须维护循环、可达性、引用快照和修订转换等跨字段不变量，不能只依赖 JSON Schema。
- Python 与 TypeScript 需要独立实现并逐项差分，增加初期开发和 fixture 维护成本。
- v1 不提供真实执行、自动代码同步或 Agent 自动提交；这些能力必须等待后续控制契约。

### 回滚

机器契约发布前可回滚对应 ADR 或实现 PR。机器契约发布后不得改写已有 1.x 工件；若规范存在
缺陷，应冻结相关写入或集成能力，保留旧版本只读路径，通过新 RFC、替代 ADR 和新契约版本修复。
运行时缺陷可回滚消费者或关闭功能开关，并将最小失败案例保留为回归 fixture。

## 验证

- `python scripts/verify_governance.py` 必须通过；该检查只证明治理结构有效，不证明运行时已实现。
- ADR 必须逐项映射 RFC-003 的七类步骤、五类转移、受约束循环、引用快照、修订和无副作用边界。
- 后续机器契约必须覆盖线性流程、条件分支、验证反馈、有限循环、非法环、悬空引用、opaque 引用、
  非法修订、重复 JSON key、非法 UTF-8、未知 major 和 expected 篡改等正负用例。
- 后续 Python/TypeScript 消费者必须对规范结果、图摘要、候选后继和有界模拟逐字段一致，并在
  Windows 与 Linux CI 中通过；任一差异阻断合并。

