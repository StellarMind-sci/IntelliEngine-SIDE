from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


MAX_OUTPUT_BYTES = 1_048_576


def parse_rows(raw: bytes, label: str) -> dict[str, dict[str, object]]:
    if len(raw) > MAX_OUTPUT_BYTES:
        raise RuntimeError(f"{label} output exceeded limit")
    text = raw.decode("utf-8", errors="strict")
    rows: dict[str, dict[str, object]] = {}
    for line in text.splitlines():
        value = json.loads(line)
        case_id = value.pop("case_id")
        if not isinstance(case_id, str) or case_id in rows:
            raise RuntimeError(f"{label} emitted an invalid case id")
        rows[case_id] = value
    return rows


def run(command: list[str], environment: dict[str, str], label: str) -> dict[str, dict[str, object]]:
    completed = subprocess.run(
        command,
        cwd=environment["REPOSITORY_ROOT"],
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeError(f"{label} failed")
    return parse_rows(completed.stdout, label)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare CognitiveNode consumers")
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    package_root = repository_root / "packages" / "cognitive-ir"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "REPOSITORY_ROOT": str(repository_root),
        "PYTHONPATH": str(package_root / "python"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    common = [
        "--contract-root",
        str(arguments.contract_root.resolve()),
        "--profile-root",
        str(arguments.profile_root.resolve()),
    ]
    python_rows = run(
        [sys.executable, "-B", "-m", "intelliengine_cognitive_ir.cli", *common],
        environment,
        "python",
    )
    type_script_rows = run(
        [str(arguments.node.resolve()), str(package_root / "src" / "cognitive-node" / "cli.ts"), *common],
        environment,
        "typescript",
    )
    suite = json.loads((arguments.contract_root / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    expected = {case["case_id"]: case["expected"] for case in suite["cases"]}
    if python_rows != expected or type_script_rows != expected or python_rows != type_script_rows:
        raise RuntimeError("CognitiveNode consumer result mismatch")
    print(json.dumps({"case_count": len(expected), "status": "passed"}, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
