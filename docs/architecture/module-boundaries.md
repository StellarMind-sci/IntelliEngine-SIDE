# 模块边界

| 模块 | 负责什么 | 不应负责什么 |
|---|---|---|
| apps/web-ide | IDE 外壳、认知画布、交互组合 | 领域事实或策略解析 |
| packages/cognitive-ir | 通用原语和扩展规则 | 学科求解器或 UI |
| packages/thoughtflow | 节点契约、投影、分支和重放 | 未经授权的直接文件写入 |
| packages/knowledge-units | 知识单元 schema 与组合 | 课程展示逻辑 |
| packages/control-plane | 策略作用域、优先级、预演和审计 | 模型提供商的具体调用 |
| packages/agent-runtime | 长期 Agent 身份、记忆、状态和团队 | 模型提供商实现 |
| packages/model-gateway | 提供商无关的模型能力与路由 | Agent 身份或产品策略 |
| packages/project-format | 可移植 manifest 与兼容性 | 密钥或隐式云端状态 |
| packages/plugin-sdk | 插件契约、权限和贡献能力 | 内置学科行为 |
| services/ingestion | DOCX/文本/图片提取和候选模型 | 最终产品决策 |
| services/sandbox | 隔离执行与资源限制 | 信任策略的归属 |
| services/provenance | 不可变原件、溯源记录和派生关系 | 原始资料的领域解释 |
| plugins/math | 数学类型、求解器、校验器和视图 | 跨学科内核规则 |

公共契约与契约测试必须先合并，再并行实现依赖它们的模块。
