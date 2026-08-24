# ADR-0008：AgentProfile 是分层长期 Agent 个体的身份锚点

- 状态：已接受
- 日期：2026-08-24
- 替代的旧 ADR：无
- 关联 RFC/Issues：[RFC-004：AgentProfile v1 与长期 Agent 个体契约](../rfc/0004-agent-profile-long-lived-agent-contract.md)、[GitHub Issue #40](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/40)、[GitHub Issue #42](https://github.com/StellarMind-sci/IntelliEngine-SIDE/issues/42)

## 背景

SIDE 的用户可随时召唤一个或 N 个长期 AI 个体，并通过工程实践、协作、验证与版本迭代培养它们。该产品方向要求每个 Agent 在关闭、恢复、换模型、跨工程协作或退出团队后仍保有连续身份；同时不得把用户私有记忆、模型凭据、实时权限或团队关系意外打包进可移植对象。

若把这些内容全部耦合为一个 Agent 文档，运行时变化会悄悄改写长期身份，也会让记忆、模型或团队的实现阻塞彼此演进。若只保存可复制模板，又无法表达长期个体的连续成长。RFC-004 已比较替代方案并确定采用“分层长期个体”。本 ADR 将该决定固化为后续公共契约与实现任务必须遵守的长期边界。

## 决定

### AgentProfile 的所有权和身份含义

`packages/agent-runtime` 拥有 `AgentProfile`、`AgentProfileRef`、Profile 修订校验和只读投影。`AgentProfile` 是一个长期 Agent 个体的可移植、可版本化身份锚点，而不是临时聊天、固定角色模板或模型会话。

Profile v1 必须携带稳定逻辑 ID、修订、显示名称、人格设定、长期目标、工作风格、声明能力、协作偏好和非空 provenance 引用。教师、学生、科学导师和用户分身均由用户自定义的 Profile 内容表达，不创建固定 role enum。`AgentProfileRef` 必须固定为 `(id, revision)`；使用方不得以“最新”、显示名称、文件路径或会话 ID 替代它。

### 分层边界

以下对象与 Profile 分离，并分别由后续独立契约拥有：

- `AgentRuntimeState`：当前 `active`、`dormant`、`archived` 状态和运行时会话。
- `MemoryLedger`：用户私有长期记忆及其受控摘要。
- `CapabilityEvidence`：来自工程、验证和项目产物的实际能力证据。
- `ModelBinding`：由 `packages/model-gateway` 拥有的供应商无关模型能力与路由。
- `ControlBinding`：由控制平面拥有的权限、信任、自主性、审计、ChangeSet 与回滚。
- `AgentTeam`、`AgentRelation`、`ProjectAssignment`：团队、关系、角色、项目分工和中心调度。

这些对象通过精确 `AgentProfileRef` 关联 Profile；它们不是嵌套 Profile 字段，不能反向改写 Profile，也不得因人格、角色、能力声明、来源或信任标签自动取得模型、文件、网络、设备、项目写入或外部工具权限。

### 生命周期、成长和重绑定

`active` 表示已唤醒并可在获授权范围内参与工程；`dormant` 表示已关闭但保留身份、设定、记忆、能力证据与关系；`archived` 表示长期封存且默认不参与搜索、调度或协作，但可恢复。永久删除不是普通状态，而是未来控制平面的独立高风险操作，必须具有影响预览、显式授权、审计、保留/导出选择与可恢复期。

除 `revision` 外，Profile 规范内容发生变化时必须创建更高 revision；只改 revision、回退 revision、改变 ID 或改写历史均无效。观察到的能力证据、记忆和运行时结果不会自动改变 Profile。只有用户或获授权策略通过 ChangeSet 的审查、验证、提交和回滚流程，才可形成新的 Profile revision。

同一逻辑 Agent 产生新 Profile revision 时，已经存在的 `AgentRuntimeState`、记忆、团队关系和模型绑定不得自动跟随。未来状态与控制平面契约必须定义显式、可审计的 rebind 操作，记录旧/新 `AgentProfileRef`、连续性影响和回滚；在该契约完成前，现有对象继续固定在原 revision。

### 无副作用、兼容和导出边界

AgentProfile v1 的校验、固定引用、摘要和兼容读取必须是确定、离线、无副作用的。它们不得调用模型、读取私有记忆、改变状态、加入团队、授予权限、执行代码或提交 ChangeSet。未知 major 拒绝；同 major 的较新 minor 只能带版本提示地兼容读取，不可用于任何写入或智能副作用。

私有记忆、提示词、凭据、模型会话、用户身份和受保护原件不得进入 Profile fixtures、诊断、差分输出或默认开放工程包。显式加密导出、来源解析、导入 authority 与受保护数据检查由未来 ProjectPackage、ProvenanceRecord 与控制平面契约决定；缺失结论时 fail closed。

### 实施顺序

1. 先以单独 Issue 交付 AgentProfile 1.0.0 的 schema、诊断、fixtures、JCS lock 和独立机器验证器。
2. 契约经独立审查并合并后，再以单独 Issue 交付 Python 与 TypeScript 独立只读消费者、CLI 和 differential runner。
3. 只有两种消费者和跨语言结果通过后，UI、Agent 协作、数学插件或后续项目格式才可依赖该 Profile 契约。
4. 状态切换、记忆、团队、模型调用、控制策略、ChangeSet 写入、工程包导出和真实执行各自建立独立 RFC/ADR/Issue；不得借本契约暗中实现。

## 结果

### 收益

- 用户创建的多个 Agent 都拥有独立、可恢复、可演化且不绑定单一模型的长期身份。
- 运行时变化不会污染可移植 Profile，工程包可默认保护私有记忆与凭据。
- 团队、关系、模型、控制和记忆可独立并行演进，避免多任务改写同一核心对象。
- 版本化 Profile、ChangeSet 与显式 rebind 为成长、审计、回滚和未来跨工程协作提供可解释路径。

### 成本与约束

- 需要维护多个引用对象和后续契约，v1 不能以“方便”为由把它们折叠回 Profile。
- M1 只提供只读验证和投影，不能宣称已实现召唤、状态切换、真实记忆、团队调度或自动执行。
- Profile、状态、记忆、能力证据和关系之间的持久化一致性、并发与删除语义必须留给相应后续契约，不能由 Profile validator 假装证明。

### 回滚

机器契约或消费者未发布前，可回退对应 PR。已发布的 1.x 工件不得原地改写；发现语义缺陷时，冻结受影响写入或导出能力，保留旧版本只读路径，通过新 RFC、替代 ADR 和显式新版本修复。消费者缺陷可回滚消费者或关闭功能开关，并保留最小失败 fixture 作为回归证据。

## 验证

- `python scripts/verify_governance.py` 必须通过；它只证明仓库治理和 ADR 结构，不证明运行时已实现。
- ADR 必须逐项映射 RFC-004 的长期身份锚点、分层边界、三状态生命周期、独立永久删除、ChangeSet 成长、显式 rebind、私有记忆导出限制和无副作用边界。
- 后续机器契约必须覆盖一个/N 个独立 Profile、用户自定义角色、非法/泄露字段、revision 转换、来源引用、compatible_read、成长证据不自动改写 Profile、状态不自动 rebind 以及 JSON/Unicode/expected 篡改。
- 后续 Python/TypeScript 消费者必须对所有机器结果、revision 结论和摘要逐字段一致，并在 Linux 与 Windows CI 中通过；任何差异阻断合并。