#!/usr/bin/env python3
"""Core governance file check without external dependencies."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "package.json",
    ".github/ISSUE_TEMPLATE/codex-task.yml",
    ".github/ISSUE_TEMPLATE/high-risk-task.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/product/vision.md",
    "docs/architecture/system-context.md",
    "docs/roadmap/milestones.md",
    "docs/runbooks/development.md",
    "docs/runbooks/codex-development-guide.md",
    "docs/runbooks/rollback.md",
]


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []

    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(errors, f"缺少必需文件：{relative}")

    if errors:
        print("Governance check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Governance check passed: {len(REQUIRED_FILES)} core files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
