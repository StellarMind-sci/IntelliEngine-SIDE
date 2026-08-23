from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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


    def test_projection_covers_expected_explicit_queries_and_simulation(self) -> None:
        runner = load_runner()
        projection = runner._run([sys.executable, str(PYTHON_CLI), "--contract-root", str(CONTRACT_ROOT)])
        fixture = next(item for item in projection["fixtures"] if item["actual"]["object_result"] == "valid")

        self.assertEqual(fixture["actual"], fixture["expected"])
        self.assertTrue(any("selected_branch" in item["input"] for item in fixture["queries"]))
        self.assertTrue(any("observed_outcome" in item["input"] for item in fixture["queries"]))
        self.assertEqual([item["scenario_id"] for item in fixture["simulations"]], [
            "missing_inputs", "first_options", "last_options", "max_steps_one",
        ])

    def test_matching_consumers_cannot_override_machine_expected(self) -> None:
        runner = load_runner()
        projection = {
            "fixtures": [{
                "case_id": "case-a",
                "actual": {"object_result": "valid", "operation_outcome": "succeeded", "issues": []},
                "expected": {"object_result": "invalid", "operation_outcome": "succeeded", "issues": [{"code": "thoughtflow.invalid_json", "path": "", "severity": "error"}]},
            }],
        }

        with self.assertRaisesRegex(ValueError, r"case-a.*machine expected"):
            runner.assert_machine_expected(projection)


    def test_both_clis_reject_the_same_lexical_path_attack_matrix(self) -> None:
        commands = ([sys.executable, str(PYTHON_CLI)], ["node", str(TS_CLI)])
        unsafe_paths = (
            "../outside.json", "fixtures/../cases.json", "fixtures\\cases.json",
            "/absolute/outside.json", "C:/absolute/outside.json",
            "./fixtures/cases.json", "fixtures//cases.json", "",
        )
        for command in commands:
            for unsafe in unsafe_paths:
                with self.subTest(command=command[0], unsafe=unsafe):
                    completed = subprocess.run(
                        [*command, "--contract-root", str(CONTRACT_ROOT), "--fixture-path", unsafe],
                        capture_output=True, text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn("unsafe fixture path", completed.stderr)

    def test_both_clis_reject_realpath_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_text('{"synthetic_secret":"must-not-be-read"}', encoding="utf-8")
            link = root / "escape.json"
            try:
                link.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            for command in ([sys.executable, str(PYTHON_CLI)], ["node", str(TS_CLI)]):
                completed = subprocess.run(
                    [*command, "--contract-root", str(root), "--fixture-path", "escape.json"],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertIn("fixture escapes contract root", completed.stderr)
                self.assertNotIn("must-not-be-read", completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
