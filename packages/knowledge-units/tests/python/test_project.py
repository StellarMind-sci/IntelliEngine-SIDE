from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
PYTHON_ROOT = PACKAGE_ROOT / "python"
COGNITIVE_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
FIXTURE_PATH = PACKAGE_ROOT / "tests" / "fixtures" / "project-projection-cases.json"
sys.path[:0] = [str(PYTHON_ROOT), str(COGNITIVE_PYTHON)]

from intelliengine_knowledge_units.project import project_knowledge


CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "knowledge-unit" / "1.0.0"
PREREQUISITE_REF = {"id": "10000000-0000-4000-8000-000000000001", "revision": 1}
DEPENDENT_REF = {"id": "10000000-0000-4000-8000-000000000002", "revision": 1}
EVIDENCE_REF = {"id": "20000000-0000-4000-8000-000000000002", "revision": 1}
NONCANONICAL_CASES = (
    ("noncanonical-available-duplicate", "/available_node_refs"),
    ("noncanonical-available-unordered", "/available_node_refs"),
    ("noncanonical-available-invalid-ref", "/available_node_refs"),
    ("noncanonical-evidence-duplicate", "/evidence_node_refs"),
    ("noncanonical-evidence-unordered", "/evidence_node_refs"),
    ("noncanonical-evidence-invalid-ref", "/evidence_node_refs"),
)


def load_case(case_id: str):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["case_id"] == case_id)
    units = [copy.deepcopy(fixture["unit_catalog"][index]) for index in case["unit_indexes"]]
    if case.get("cycle"):
        units[0]["prerequisite_unit_refs"] = [copy.deepcopy(DEPENDENT_REF)]
    return units, case["available_node_refs"], case["evidence_node_refs"]


class KnowledgeUnitProjectTests(unittest.TestCase):
    def project_case(self, case_id: str):
        units, available, evidence = load_case(case_id)
        return project_knowledge(units, available, evidence, CONTRACT_ROOT)

    def test_empty_evidence_marks_dependent_unit_as_needs_evidence(self) -> None:
        result = self.project_case("empty-evidence")

        self.assertEqual(result["object_result"], "valid")
        self.assertEqual(result["operation_outcome"], "succeeded")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["units"][1], {
            "ref": DEPENDENT_REF,
            "status": "needs_evidence",
            "missing_prerequisite_refs": [],
            "missing_evidence_node_refs": [EVIDENCE_REF],
        })

    def test_missing_prerequisite_blocks_dependent_unit_and_lists_ref(self) -> None:
        result = self.project_case("missing-prerequisite")

        self.assertEqual(result["units"], [{
            "ref": DEPENDENT_REF,
            "status": "blocked",
            "missing_prerequisite_refs": [PREREQUISITE_REF],
            "missing_evidence_node_refs": [],
        }])

    def test_complete_evidence_reports_no_missing_evidence(self) -> None:
        result = self.project_case("full-evidence")

        self.assertEqual(result["units"][1], {
            "ref": DEPENDENT_REF,
            "status": "ready",
            "missing_prerequisite_refs": [],
            "missing_evidence_node_refs": [],
        })

    def test_evidence_node_reports_the_two_direct_unit_dependents(self) -> None:
        result = self.project_case("full-evidence")

        entry = next(item for item in result["node_dependents"] if item["node_ref"] == EVIDENCE_REF)
        self.assertEqual(entry, {
            "node_ref": EVIDENCE_REF,
            "unit_refs": [PREREQUISITE_REF, DEPENDENT_REF],
        })

    def test_prerequisite_ref_reports_transitive_reverse_unit_dependents(self) -> None:
        result = self.project_case("full-evidence")

        entry = next(item for item in result["unit_dependents"] if item["unit_ref"] == PREREQUISITE_REF)
        self.assertEqual(entry, {
            "unit_ref": PREREQUISITE_REF,
            "dependent_unit_refs": [DEPENDENT_REF],
        })

    def test_prerequisite_cycle_is_invalid(self) -> None:
        result = self.project_case("prerequisite-cycle")

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"], [{
            "code": "knowledge_project.prerequisite_cycle",
            "path": "/units",
            "severity": "error",
        }])

    def test_duplicate_unit_ref_is_invalid(self) -> None:
        units, available, evidence = load_case("full-evidence")
        result = project_knowledge(units + [copy.deepcopy(units[1])], available, evidence, CONTRACT_ROOT)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"], [{
            "code": "knowledge_project.duplicate_unit_ref",
            "path": "/units/2",
            "severity": "error",
        }])

    def test_noncanonical_available_and_evidence_sets_are_closed_invalid_results(self) -> None:
        for case_id, path in NONCANONICAL_CASES:
            with self.subTest(case_id=case_id):
                self.assertEqual(self.project_case(case_id), {
                    "object_result": "invalid",
                    "operation_outcome": "succeeded",
                    "issues": [{
                        "code": "knowledge_project.noncanonical_set",
                        "path": path,
                        "severity": "error",
                    }],
                    "units": [],
                    "node_dependents": [],
                    "unit_dependents": [],
                })


if __name__ == "__main__":
    unittest.main(verbosity=2)
