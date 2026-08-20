from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import run_fixture_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CognitiveNode contract fixtures")
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    arguments = parser.parse_args()
    for row in run_fixture_suite(arguments.contract_root, arguments.profile_root):
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
