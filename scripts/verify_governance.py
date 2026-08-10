#!/usr/bin/env python3
"""无需额外依赖的仓库长期治理检查。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "package.json",
    ".github/ISSUE_TEMPLATE/codex-task.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/ci.yml",
    "docs/product/vision.md",
    "docs/product/glossary.md",
    "docs/product/non-goals.md",
    "docs/architecture/system-context.md",
    "docs/architecture/module-boundaries.md",
    "docs/architecture/public-contracts.md",
    "docs/rfc/0000-template.md",
    "docs/adr/0000-template.md",
    "docs/roadmap/milestones.md",
    "docs/roadmap/stage-log.md",
    "docs/runbooks/development.md",
    "docs/runbooks/codex-development-guide.md",
    "docs/runbooks/github-setup.md",
    "docs/runbooks/automation.md",
]

MODULE_DIRS = [
    "apps/web-ide",
    "packages/cognitive-ir",
    "packages/thoughtflow",
    "packages/knowledge-units",
    "packages/control-plane",
    "packages/agent-runtime",
    "packages/model-gateway",
    "packages/project-format",
    "packages/plugin-sdk",
    "services/ingestion",
    "services/sandbox",
    "services/provenance",
    "plugins/math",
]

SKILLS = [
    "issue-planner",
    "rfc-author",
    "module-implementer",
    "contract-reviewer",
    "integration-reviewer",
    "release-verifier",
]


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_skill(errors: list[str], name: str) -> None:
    folder = ROOT / ".agents" / "skills" / name
    skill = folder / "SKILL.md"
    metadata = folder / "agents" / "openai.yaml"
    if not skill.is_file():
        fail(errors, f"缺少 skill 文件：{skill.relative_to(ROOT)}")
        return
    if not metadata.is_file():
        fail(errors, f"缺少 skill 元数据：{metadata.relative_to(ROOT)}")
    text = skill.read_text(encoding="utf-8")
    if "TODO" in text:
        fail(errors, f"{skill.relative_to(ROOT)} 中仍有未完成 TODO")
    match = re.match(r"^---\nname:\s*([^\n]+)\ndescription:\s*([^\n]+)\n---", text)
    if not match:
        fail(errors, f"{skill.relative_to(ROOT)} 的 frontmatter 无效")
    elif match.group(1).strip() != name:
        fail(errors, f"{skill.relative_to(ROOT)} 的 skill 名称不匹配")


def main() -> int:
    errors: list[str] = []

    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(errors, f"缺少必需文件：{relative}")

    for relative in MODULE_DIRS:
        if not (ROOT / relative).is_dir():
            fail(errors, f"缺少模块目录：{relative}")

    for guidance in ("apps/AGENTS.md", "packages/AGENTS.md", "services/AGENTS.md", "plugins/AGENTS.md"):
        if not (ROOT / guidance).is_file():
            fail(errors, f"缺少分区规则文件：{guidance}")

    for name in SKILLS:
        validate_skill(errors, name)

    adr_pattern = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")
    for path in (ROOT / "docs" / "adr").glob("*.md"):
        if not adr_pattern.match(path.name):
            fail(errors, f"ADR 文件名无效：{path.relative_to(ROOT)}")

    if errors:
        print("治理检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"治理检查通过：{len(REQUIRED_FILES)} 个文件，"
          f"{len(MODULE_DIRS)} 个模块，{len(SKILLS)} 个 skills。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
