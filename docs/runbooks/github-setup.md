# GitHub 设置手册

创建并推送远程仓库后，完成以下操作：

1. 创建 GitHub Project，添加字段：状态、里程碑、模块、任务类型、优先级、依赖和审查状态。
   不要在仓库 Markdown 中复制这份实时状态。
2. 创建标签：codex-task、rfc、contract、module、integration、review、docs、release、blocked，
   以及各顶层模块分组标签。
3. 使用真实 GitHub 用户名创建或更新 .github/CODEOWNERS；要求负责人审查 ADR、
   Cognitive IR、控制平面和工程格式相关修改。
4. 保护 main：要求 Pull Request、治理 CI、已解决讨论；禁止强推和删除分支。
5. 当实际命令出现后，将 lint、单元、契约、集成、安全、兼容和构建检查加入必需状态检查。
6. 只有在存在可部署代码后，才配置 preview、staging 和 production 环境；生产环境要求人工批准，
   并保护部署密钥。

创建远程仓库、GitHub Project 和分支保护都是外部状态变更，不能由本地 bootstrap 脚本自动完成。
