# 认知工程 IDE

SIDE 将资料、知识、模型、思维链、长期 Agent、验证与工程成果连接为可运行的认知工程环境。

开发只从两份文件开始：

- [产品愿景](docs/product/vision.md)
- [日常开发流程](docs/runbooks/development.md)

普通功能完成后应可测试并交付演示；高风险功能在测试后交付人工审查。运行核心治理检查：

```powershell
python scripts/verify_governance.py
```
