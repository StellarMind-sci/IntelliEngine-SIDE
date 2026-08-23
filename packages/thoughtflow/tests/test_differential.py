from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "thoughtflow" / "1.0.0"
RUNNER_PATH = PACKAGE_ROOT / "scripts" / "differential.py"
PYTHON_CLI = PACKAGE_ROOT / "python" / "intelliengine_thoughtflow" / "cli.py"
TS_CLI = PACKAGE_ROOT / "src" / "thoughtflow" / "cli.ts"


def load_runner():
    spec = importlib.util.spec_from_file_location("thoughtflow_differential", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load differential runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ThoughtflowDifferentialTests(unittest.TestCase):
    def test_real_consumers_match_all_machine_results_and_queries(self) -> None:
        runner = load_runner()

        report = runner.run_differential(CONTRACT_ROOT)

        self.assertEqual(report, {"case_count": 18, "contract_version": "1.0.0"})

    def test_smallest_drift_path_is_reported(self) -> None:
        runner = load_runner()
        left = {"fixtures": [{"case_id": "case-a", "actual": {"object_result": "valid"}}]}
        right = {"fixtures": [{"case_id": "case-a", "actual": {"object_result": "invalid"}}]}

        with self.assertRaisesRegex(ValueError, r"case-a.*?/actual/object_result"):
            runner.compare_projections(left, right)

    def test_python_cli_rejects_parent_fixture_path(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PYTHON_CLI), "--contract-root", str(CONTRACT_ROOT), "--fixture-path", "../outside.json"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("outside.json", completed.stdout)
        self.assertIn("unsafe fixture path", completed.stderr)

    def test_typescript_cli_rejects_backslash_fixture_path(self) -> None:
        completed = subprocess.run(
            ["node", str(TS_CLI), "--contract-root", str(CONTRACT_ROOT), "--fixture-path", "fixtures\\cases.json"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("unsafe fixture path", completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
