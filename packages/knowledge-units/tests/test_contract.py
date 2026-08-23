from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "knowledge-unit" / "1.0.0"
VERIFIER_PATH = PACKAGE_ROOT / "contracts" / "tools" / "verify_contract.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("knowledge_unit_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load KnowledgeUnit verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KnowledgeUnitContractTests(unittest.TestCase):
    def test_bundled_linear_equation_unit_is_valid(self) -> None:
        verifier = load_verifier()

        report = verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report, {"case_count": 8, "contract_version": "1.0.0"})

    def test_bundled_suite_covers_dangling_cognitive_node_refs(self) -> None:
        verifier = load_verifier()
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        fixture = next(case for case in suite["cases"] if case["case_id"] == "node-ref-dangling")

        result = verifier.validate_case(fixture, CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "knowledge_unit.dangling_node_ref")

    def test_self_dependency_is_rejected_by_real_validation(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, root)
            suite = json.loads((root / "fixtures" / "cases.json").read_text(encoding="utf-8"))
            valid = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")
            unit = valid["input"]["unit"]
            unit["prerequisite_unit_refs"] = [{"id": unit["id"], "revision": unit["revision"]}]

            result = verifier.validate_case(valid, root)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"], [{
            "code": "knowledge_unit.self_dependency",
            "path": "/prerequisite_unit_refs/0",
            "severity": "error",
        }])

    def test_mastery_criterion_without_evidence_is_rejected(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, root)
            suite = json.loads((root / "fixtures" / "cases.json").read_text(encoding="utf-8"))
            valid = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")
            valid["input"]["unit"]["mastery_criteria"][0]["evidence_node_refs"] = []

            result = verifier.validate_case(valid, root)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "knowledge_unit.mastery_without_evidence")

    def test_validation_result_rejects_illegal_state_pairs(self) -> None:
        verifier = load_verifier()
        schema = json.loads((CONTRACT_ROOT / "schemas" / "validation-result.schema.json").read_text(encoding="utf-8"))
        illegal = {
            "object_result": "valid",
            "operation_outcome": "resource_exhausted",
            "issues": [],
        }

        self.assertFalse(verifier.is_valid(illegal, schema, schema))


    def test_machine_schemas_accept_every_bundled_fixture_and_result(self) -> None:
        verifier = load_verifier()
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        fixture_schema = json.loads((CONTRACT_ROOT / "schemas" / "fixture-suite.schema.json").read_text(encoding="utf-8"))
        result_schema = json.loads((CONTRACT_ROOT / "schemas" / "validation-result.schema.json").read_text(encoding="utf-8"))

        self.assertTrue(verifier.is_valid(suite, fixture_schema, fixture_schema))
        for fixture in suite["cases"]:
            with self.subTest(case_id=fixture["case_id"]):
                self.assertTrue(
                    verifier.is_valid(fixture["expected"], result_schema, result_schema),
                    fixture["expected"],
                )


    def test_nested_lock_json_cannot_escape_digest_closure(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, root)
            nested = root / "schemas" / "nested" / "lock.json"
            nested.parent.mkdir()
            nested.write_text('{"unlocked":true}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lock closure mismatch"):
                verifier.verify_contract(root)

    def test_fixture_expected_is_not_replayed(self) -> None:
        verifier = load_verifier()
        fixture = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))["cases"][0]
        fixture["expected"] = {
            "object_result": "invalid",
            "operation_outcome": "succeeded",
            "issues": [{"code": "knowledge_unit.invalid_json", "path": "", "severity": "error"}],
        }

        result = verifier.validate_case(fixture, CONTRACT_ROOT)

        self.assertNotEqual(result, fixture["expected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
