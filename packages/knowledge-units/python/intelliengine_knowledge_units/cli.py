from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import run_fixture_suite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, required=True)
    args = parser.parse_args()
    for row in run_fixture_suite(args.contract_root):
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
