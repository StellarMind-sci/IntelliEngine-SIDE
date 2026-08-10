# 认知工程 IDE

这是“认知工程 IDE”的治理与实现仓库。

仓库、测试、ADR 和公共契约是长期事实来源；单个 Codex 任务只是一次可替换的执行单元，
不应承载整个项目的记忆。

建议从以下文件开始阅读：

- [产品愿景](docs/product/vision.md)
- [系统架构](docs/architecture/system-context.md)
- [项目里程碑](docs/roadmap/milestones.md)
- [完整开发流程](docs/runbooks/development.md)
- [面向 Codex 的开发指导](docs/runbooks/codex-development-guide.md)
- [大阶段完成日志](docs/roadmap/stage-log.md)
- [贡献与开发流程](CONTRIBUTING.md)
- [给 Codex 的仓库规则](AGENTS.md)

提交 Pull Request 前，运行：

```powershell
python scripts/verify_governance.py
```
