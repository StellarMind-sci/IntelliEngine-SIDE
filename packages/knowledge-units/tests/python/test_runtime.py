from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "knowledge-unit" / "1.0.0"
PYTHON_ROOT = PACKAGE_ROOT / "python"
COGNITIVE_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
sys.path[:0] = [str(PYTHON_ROOT), str(COGNITIVE_PYTHON)]


def unit_with_jcs_size(unit: dict, size: int) -> dict:
    from intelliengine_conformance.json_codec import canonicalize

    value = json.loads(json.dumps(unit))
    statements = value["concept_boundary"]["out_of_scope_statements"]
    statements[0] = ""
    statements[0] = "x" * (size - len(canonicalize(value)))
    assert len(canonicalize(value)) == size
    return value


class KnowledgeUnitPythonRuntimeTests(unittest.TestCase):
    def run_cli(self, contract_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "intelliengine_knowledge_units.cli",
                "--contract-root",
                str(contract_root),
            ],
            cwd=REPOSITORY_ROOT,
            env={
                "PYTHONPATH": os.pathsep.join((str(PYTHON_ROOT), str(COGNITIVE_PYTHON))),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_executes_all_eight_contract_cases_exactly(self) -> None:
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        expected = {case["case_id"]: case["expected"] for case in suite["cases"]}

        completed = self.run_cli(CONTRACT_ROOT)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([row["case_id"] for row in rows], sorted(expected))
        self.assertEqual(
            {row["case_id"]: {key: value for key, value in row.items() if key != "case_id"} for row in rows},
            expected,
        )

    def test_invalid_unit_identity_returns_stable_diagnostics(self) -> None:
        from intelliengine_knowledge_units.runtime import validate_unit

        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        valid = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")["input"]

        invalid_id = json.loads(json.dumps(valid["unit"]))
        invalid_id["id"] = 7
        id_result = validate_unit(invalid_id, valid["available_node_refs"], CONTRACT_ROOT)

        invalid_revision = json.loads(json.dumps(valid["unit"]))
        invalid_revision["revision"] = 0
        revision_result = validate_unit(invalid_revision, valid["available_node_refs"], CONTRACT_ROOT)

        self.assertEqual(
            id_result["issues"],
            [{"code": "knowledge_unit.invalid_id", "path": "/id", "severity": "error"}],
        )
        self.assertEqual(
            revision_result["issues"],
            [{"code": "knowledge_unit.invalid_revision", "path": "/revision", "severity": "error"}],
        )

    def test_nested_node_ref_sets_require_canonical_order(self) -> None:
        from intelliengine_knowledge_units.runtime import validate_unit

        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        valid = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")["input"]
        unit = json.loads(json.dumps(valid["unit"]))
        unit["learning_objectives"][0]["target_node_refs"].reverse()

        result = validate_unit(unit, valid["available_node_refs"], CONTRACT_ROOT)

        self.assertEqual(result["issues"], [{
            "code": "knowledge_unit.noncanonical_set",
            "path": "/learning_objectives/0/target_node_refs",
            "severity": "error",
        }])

    def test_rejects_structurally_valid_unit_larger_than_jcs_limit(self) -> None:
        from intelliengine_knowledge_units.runtime import validate_unit

        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        valid = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")["input"]
        at_limit = unit_with_jcs_size(valid["unit"], 1_048_576)
        over_limit = unit_with_jcs_size(valid["unit"], 1_048_577)

        self.assertEqual(validate_unit(at_limit, valid["available_node_refs"], CONTRACT_ROOT)["object_result"], "valid")
        self.assertEqual(
            validate_unit(over_limit, valid["available_node_refs"], CONTRACT_ROOT),
            {
                "object_result": "not_evaluated",
                "operation_outcome": "resource_exhausted",
                "issues": [{"code": "knowledge_unit.invalid_json", "path": "", "severity": "error"}],
            },
        )

    def test_raw_transport_rejects_duplicate_members(self) -> None:
        from intelliengine_knowledge_units.runtime import parse_and_validate

        result = parse_and_validate(
            b'{"contract_version":"1.0.0","contract_version":"1.0.0"}',
            [],
            CONTRACT_ROOT,
        )

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "knowledge_unit.invalid_json")
        invalid_utf8 = parse_and_validate(b"\xff", [], CONTRACT_ROOT)

        self.assertEqual(invalid_utf8["object_result"], "invalid")
        self.assertEqual(invalid_utf8["issues"][0]["code"], "knowledge_unit.invalid_json")

    def test_fixture_expected_is_not_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, root)
            path = root / "fixtures" / "cases.json"
            suite = json.loads(path.read_text(encoding="utf-8"))
            target = next(case for case in suite["cases"] if case["case_id"] == "linear-equation-valid")
            target["expected"] = {
                "object_result": "invalid",
                "operation_outcome": "succeeded",
                "issues": [{"code": "knowledge_unit.invalid_json", "path": "", "severity": "error"}],
            }
            path.write_text(json.dumps(suite, ensure_ascii=False) + "\n", encoding="utf-8")

            completed = self.run_cli(root)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = {row["case_id"]: row for row in map(json.loads, completed.stdout.splitlines())}
        self.assertEqual(rows["linear-equation-valid"]["object_result"], "valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
