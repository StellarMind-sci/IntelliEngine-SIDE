from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYTHON_CLI = PACKAGE_ROOT / "python" / "intelliengine_thoughtflow" / "cli.py"
TS_CLI = PACKAGE_ROOT / "src" / "thoughtflow" / "cli.ts"


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def smallest_difference(left: Any, right: Any, path: str = "") -> str | None:
    if type(left) is not type(right):
        return path
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            child = f"{path}/{_pointer_token(str(key))}"
            if key not in left or key not in right:
                return child
            found = smallest_difference(left[key], right[key], child)
            if found is not None:
                return found
        return None
    if isinstance(left, list):
        for index in range(max(len(left), len(right))):
            child = f"{path}/{index}"
            if index >= len(left) or index >= len(right):
                return child
            found = smallest_difference(left[index], right[index], child)
            if found is not None:
                return found
        return None
    return None if left == right else path


def compare_projections(left: dict, right: dict) -> None:
    pointer = smallest_difference(left, right)
    if pointer is None:
        return
    case_id = "unknown"
    parts = pointer.split("/")
    if len(parts) > 2 and parts[1] == "fixtures":
        try:
            case_id = left["fixtures"][int(parts[2])]["case_id"]
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        pointer = "/" + "/".join(parts[3:])
    raise ValueError(f"Thoughtflow differential mismatch: {case_id} {pointer}")


def _run(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def run_differential(contract_root: Path) -> dict:
    root = contract_root.resolve(strict=True)
    python_result = _run([sys.executable, str(PYTHON_CLI), "--contract-root", str(root)])
    typescript_result = _run(["node", str(TS_CLI), "--contract-root", str(root)])
    compare_projections(python_result, typescript_result)
    return {"case_count": len(python_result["fixtures"]), "contract_version": python_result["contract_version"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, default=PACKAGE_ROOT / "contracts" / "thoughtflow" / "1.0.0")
    args = parser.parse_args()
    print(json.dumps(run_differential(args.contract_root), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
