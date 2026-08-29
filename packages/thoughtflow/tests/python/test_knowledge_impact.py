from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_thoughtflow.knowledge_impact import project_knowledge_impacts


CASES = json.loads((PACKAGE_ROOT / "tests" / "fixtures" / "knowledge-impact-cases.json").read_text(encoding="utf-8"))["cases"]


class KnowledgeImpactTests(unittest.TestCase):
    def test_projects_each_hand_authored_case(self) -> None:
        for case in CASES:
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(project_knowledge_impacts(case["flow"], case["projection"]), case["expected"])

    def test_projection_is_read_only_and_never_reports_execution_or_selection(self) -> None:
        case = CASES[0]
        flow = copy.deepcopy(case["flow"])
        projection = copy.deepcopy(case["projection"])

        result = project_knowledge_impacts(flow, projection)

        self.assertEqual(flow, case["flow"])
        self.assertEqual(projection, case["projection"])
        self.assertFalse({"executed_operations", "selected_branch", "branch_selection", "mastery", "write"} & set(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)