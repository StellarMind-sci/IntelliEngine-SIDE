from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_runtime_state import execute_fixture_suite, parse_and_validate_transport


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--raw-hex")
    args = parser.parse_args()
    if args.raw_hex is not None:
        try:
            raw = bytes.fromhex(args.raw_hex)
        except ValueError:
            raw = b""
        print(json.dumps(parse_and_validate_transport(raw, args.contract_root), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0
    for item in execute_fixture_suite(args.contract_root):
        print(json.dumps({"case_id": item["case_id"], **item["actual"]}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())