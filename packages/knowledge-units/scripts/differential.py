from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


JsonObject = dict[str, Any]


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _first_difference(left: Any, right: Any, path: str = "") -> str | None:
    if type(left) is not type(right):
        return path or ""
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right), key=lambda value: value.encode("utf-8"))
        for key in keys:
            child = f"{path}/{_pointer_token(key)}"
            if key not in left or key not in right:
                return child
            difference = _first_difference(left[key], right[key], child)
            if difference is not None:
                return difference
        return None
    if isinstance(left, list):
        for index in range(max(len(left), len(right))):
            child = f"{path}/{index}"
            if index >= len(left) or index >= len(right):
                return child
            difference = _first_difference(left[index], right[index], child)
            if difference is not None:
                return difference
        return None
    return None if left == right else (path or "")


def compare_projections(expected: dict[str, JsonObject], typescript: dict[str, JsonObject], python: dict[str, JsonObject]) -> None:
    expected_ids = set(expected)
    if set(typescript) != expected_ids or set(python) != expected_ids:
        raise ValueError("case-set:/case_id")
    for case_id in sorted(expected, key=lambda value: value.encode("utf-8")):
        for candidate in (typescript[case_id], python[case_id]):
            difference = _first_difference(expected[case_id], candidate)
            if difference is not None:
                raise ValueError(f"{case_id}:{difference}")
        difference = _first_difference(typescript[case_id], python[case_id])
        if difference is not None:
            raise ValueError(f"{case_id}:{difference}")


def _environment(repository_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"COMSPEC", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
    }
    knowledge_python = repository_root / "packages" / "knowledge-units" / "python"
    cognitive_python = repository_root / "packages" / "cognitive-ir" / "python"
    environment.update({
        "PYTHONPATH": os.pathsep.join((str(knowledge_python), str(cognitive_python))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
    })
    return environment


def _run(command: list[str], repository_root: Path, environment: dict[str, str]) -> dict[str, JsonObject]:
    completed = subprocess.run(
        command,
        cwd=repository_root,
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise ValueError("consumer process failed")
    if len(completed.stdout) > 1024 * 1024:
        raise ValueError("consumer output exceeded limit")
    try:
        lines = completed.stdout.decode("utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("consumer output is malformed") from error
    projection: dict[str, JsonObject] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise ValueError("consumer output is malformed")
        case_id = row.pop("case_id")
        if case_id in projection:
            raise ValueError("consumer output has duplicate case")
        projection[case_id] = row
    return projection


def run_gate(repository_root: Path, node: Path) -> JsonObject:
    repository_root = repository_root.resolve()
    contract_root = repository_root / "packages" / "knowledge-units" / "contracts" / "knowledge-unit" / "1.0.0"
    suite = json.loads((contract_root / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    expected = {case["case_id"]: case["expected"] for case in suite["cases"]}
    environment = _environment(repository_root)
    typescript = _run(
        [str(node), str(repository_root / "packages" / "knowledge-units" / "src" / "knowledge-unit" / "cli.ts"), "--contract-root", str(contract_root)],
        repository_root,
        environment,
    )
    python = _run(
        [sys.executable, "-B", "-m", "intelliengine_knowledge_units.cli", "--contract-root", str(contract_root)],
        repository_root,
        environment,
    )
    compare_projections(expected, typescript, python)
    return {"case_count": len(expected), "status": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--node", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_gate(args.repository_root, args.node), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
