from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "packages" / "agent-runtime" / "contracts" / "agent-runtime-state" / "1.0.0"
PACKAGE = ROOT / "packages" / "agent-runtime"


def rows(command: list[str], environment: dict[str, str]) -> dict[str, dict]:
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=30, check=False)
    if completed.returncode or completed.stderr:
        raise RuntimeError("consumer failed")
    result: dict[str, dict] = {}
    for line in completed.stdout.decode("utf-8", "strict").splitlines():
        row = json.loads(line)
        case_id = row.pop("case_id", None)
        if not isinstance(case_id, str) or case_id in result:
            raise RuntimeError("invalid consumer rows")
        result[case_id] = row
    return result


def raw_row(command: list[str], environment: dict[str, str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=30, check=False)
    if completed.returncode or completed.stderr:
        raise RuntimeError("raw consumer failed")
    lines = completed.stdout.decode("utf-8", "strict").splitlines()
    if len(lines) != 1:
        raise RuntimeError("invalid raw consumer output")
    return json.loads(lines[0])


def main() -> int:
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME"}}
    environment.update({"PYTHONPATH": str(PACKAGE / "python"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PIP_NO_INDEX": "1", "npm_config_offline": "true"})
    contract = str(CONTRACT.resolve())
    python_command = [sys.executable, "-B", "-m", "intelliengine_agent_runtime.agent_runtime_state_cli", "--contract-root", contract]
    typescript_command = ["node", str(PACKAGE / "src" / "agent-runtime-state" / "cli.ts"), "--contract-root", contract]
    python_rows = rows(python_command, environment)
    typescript_rows = rows(typescript_command, environment)
    suite = json.loads((CONTRACT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    expected = {item["case_id"]: item["expected"] for item in suite["cases"]}
    if set(python_rows) != set(expected) or set(typescript_rows) != set(expected):
        raise RuntimeError("AgentRuntimeState consumer case coverage mismatch")
    for case_id in sorted(expected, key=lambda value: value.encode("utf-8")):
        if python_rows[case_id] != expected[case_id] or typescript_rows[case_id] != expected[case_id] or python_rows[case_id] != typescript_rows[case_id]:
            raise RuntimeError(f"AgentRuntimeState consumer result mismatch: {case_id}")
    state = next(item for item in suite["cases"] if item["case_id"] == "state-registered-not-dormant")["input"]["state"]
    raw = json.dumps(state, separators=(",", ":"))
    expected_raw = {"interface": "agent_runtime_state", "mode": "transport", "object_result": "invalid", "operation_outcome": "succeeded", "issues": [{"code": "agent_runtime_state.invalid_state_field", "path": "/state_revision", "severity": "error"}]}
    for token in ("1.0", "1e0", "-0"):
        probe = raw.replace('"state_revision":2', f'"state_revision":{token}').encode("utf-8").hex()
        python_raw = raw_row([*python_command, "--raw-hex", probe], environment)
        typescript_raw = raw_row([*typescript_command, "--raw-hex", probe], environment)
        if python_raw != expected_raw or typescript_raw != expected_raw or python_raw != typescript_raw:
            raise RuntimeError(f"AgentRuntimeState raw transport mismatch: {token}")
    report = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    print(json.dumps({"case_count": len(expected), "raw_transport_probe_count": 3, "report_sha256": hashlib.sha256(report).hexdigest(), "status": "passed"}, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())