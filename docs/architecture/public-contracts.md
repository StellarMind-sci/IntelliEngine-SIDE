# 公共契约

公共契约只在产品能力确实需要稳定的跨模块、跨语言或可导出兼容性时创建或修改。它不是功能开发前的清单，也不要求先完成所有计划类型。

已有 CognitiveNode、Thoughtflow、AgentProfile、AgentRuntimeState、ProvenanceRecord 和 ControlPolicy 契约继续约束使用它们的代码。内部实现、UI、只读解析、可视化和实验原型可以直接开发，并以目标测试和演示验证。

涉及可移植格式、真实写入、权限或跨语言互操作时，任务卡标记为高风险并保留相应契约测试、兼容性与回滚证据。
