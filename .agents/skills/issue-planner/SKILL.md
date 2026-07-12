---
name: issue-planner
description: 将产品 Epic、RFC 或过大的改动拆成边界清晰的 GitHub Issue 任务契约。用于规划里程碑、准备并行 Codex 工作，或当一项请求跨多个模块、公共契约或多个可审查 PR 时。
---

# Issue 拆分器

1. 阅读产品意图、当前架构、已接受 ADR、模块边界和已有 Issues。
2. 绘制依赖图；公共契约与契约测试必须先于使用方。
3. 每个 Issue 只保留一句话结果、一个主要模块、最多一项公共契约变化、一组验收测试和一个 PR。
4. 阻止并行 Issues 修改同一不稳定契约、数据库结构或核心文件。
5. 每个 Issue 必须写明背景、交付物、范围、非目标、允许路径、输入输出、接口影响、依赖、
   验收条件、测试、风险和回滚。
6. 标注任务类型：contract、module、integration、review、docs 或 release，并说明哪些可以并行。
7. 拒绝模糊任务，直到新 Codex 任务无需自行决定产品方向即可执行。

先输出依赖顺序，再输出可直接复制到 GitHub 的 Issue 内容。
