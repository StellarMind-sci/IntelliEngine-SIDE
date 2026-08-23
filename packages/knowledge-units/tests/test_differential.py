from __future__ import annotations

import importlib.util
import shutil
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
RUNNER_PATH = PACKAGE_ROOT / "scripts" / "differential.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("knowledge_unit_differential", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load differential runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KnowledgeUnitDifferentialTests(unittest.TestCase):
    def test_real_consumers_match_all_eight_machine_results(self) -> None:
        runner = load_runner()
        node = shutil.which("node")
        self.assertIsNotNone(node)

        report = runner.run_gate(REPOSITORY_ROOT, Path(node))

        self.assertEqual(report, {"case_count": 8, "status": "passed"})

    def test_one_consumer_drift_reports_case_and_smallest_path(self) -> None:
        runner = load_runner()
        expected = {
            "linear-equation-valid": {
                "object_result": "valid",
                "operation_outcome": "succeeded",
                "issues": [],
            }
        }
        typescript = {key: dict(value) for key, value in expected.items()}
        python = {key: dict(value) for key, value in expected.items()}
        typescript["linear-equation-valid"]["object_result"] = "invalid"

        with self.assertRaisesRegex(
            ValueError,
            r"linear-equation-valid:/object_result",
        ):
            runner.compare_projections(expected, typescript, python)


if __name__ == "__main__":
    unittest.main(verbosity=2)
