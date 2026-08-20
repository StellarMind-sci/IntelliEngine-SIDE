from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "cognitive-node" / "1.0.0"
VERIFIER = PACKAGE_ROOT / "contracts" / "tools" / "verify_cognitive_node.py"
PYTHON_PACKAGE = PACKAGE_ROOT / "python"

sys.path.insert(0, str(PYTHON_PACKAGE))
from intelliengine_conformance.json_codec import canonicalize  # noqa: E402
from intelliengine_conformance.schema_validation import is_valid  # noqa: E402


class CognitiveNodeContractTests(unittest.TestCase):
    def run_verifier(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(VERIFIER), "--root", str(root)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def copy_contract(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        destination = Path(temporary.name) / "cognitive-node" / "1.0.0"
        shutil.copytree(CONTRACT_ROOT, destination)
        profile_source = PACKAGE_ROOT / "contracts" / "profile"
        profile_destination = Path(temporary.name) / "profile"
        shutil.copytree(profile_source, profile_destination)
        return temporary, destination

    def write_json_and_relock(self, root: Path, relative: str, value: object) -> None:
        path = root / relative
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        lock_path = root / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(canonicalize(value)).hexdigest()
        for entry in lock["entries"]:
            if entry["path"] == relative:
                entry["sha256"] = digest
                break
        else:
            self.fail(f"missing lock entry for {relative}")
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def test_repository_bundle_is_self_consistent(self) -> None:
        completed = self.run_verifier(CONTRACT_ROOT)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "cognitive node contract 1.0.0 verified",
        )

    def test_type_id_grammar_drift_is_rejected_after_relocking(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        relative = "schemas/cognitive-node.schema.json"
        schema = json.loads((root / relative).read_text(encoding="utf-8"))
        schema["properties"]["type_id"]["pattern"] = "^.+$"
        self.write_json_and_relock(root, relative, schema)

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("schema_drift", completed.stderr)

    def test_type_definition_cannot_use_cognitive_node_state_pairs(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        relative = "diagnostics/type-definition.json"
        catalog = json.loads((root / relative).read_text(encoding="utf-8"))
        target = next(
            entry
            for entry in catalog["codes"]
            if entry["code"] == "type_definition.invalid_structure"
        )
        target["allowed_pairs"] = [["opaque", "succeeded"]]
        self.write_json_and_relock(root, relative, catalog)

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("diagnostic_drift", completed.stderr)

    def test_diagnostic_code_cannot_drift_to_another_legal_pair(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        relative = "diagnostics/type-definition.json"
        catalog = json.loads((root / relative).read_text(encoding="utf-8"))
        target = next(
            entry
            for entry in catalog["codes"]
            if entry["code"] == "type_definition.invalid_structure"
        )
        target["allowed_pairs"] = [["valid", "succeeded"]]
        self.write_json_and_relock(root, relative, catalog)

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("diagnostic_drift", completed.stderr)

    def test_valid_transport_fixture_must_satisfy_cognitive_node_schema(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        relative = "fixtures/cases.json"
        suite = json.loads((root / relative).read_text(encoding="utf-8"))
        target = next(
            case
            for case in suite["cases"]
            if case["case_id"] == "core-entity-transport-valid"
        )
        target["input"]["id"] = "NOT-A-UUID"
        self.write_json_and_relock(root, relative, suite)

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("fixture_invalid", completed.stderr)

    def test_valid_fixture_sets_must_use_utf8_canonical_order(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        relative = "fixtures/cases.json"
        suite = json.loads((root / relative).read_text(encoding="utf-8"))
        target = next(
            case
            for case in suite["cases"]
            if case["case_id"] == "core-entity-transport-valid"
        )
        target["input"]["provenance_refs"] = ["prov:z", "prov:a"]
        self.write_json_and_relock(root, relative, suite)

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("fixture_invalid", completed.stderr)

    def test_validation_result_schema_rejects_cross_product_state_pairs(self) -> None:
        schema = json.loads(
            (CONTRACT_ROOT / "schemas/validation-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        illegal = {
            "interface": "cognitive_node",
            "mode": "transport",
            "object_result": "invalid",
            "operation_outcome": "resource_exhausted",
            "issues": [],
        }

        self.assertFalse(is_valid(illegal, schema))

    def test_diagnostic_schema_accepts_nested_json_pointer_paths(self) -> None:
        schema = json.loads(
            (CONTRACT_ROOT / "schemas/diagnostic.schema.json").read_text(
                encoding="utf-8"
            )
        )
        diagnostic = {
            "code": "cognitive_node.invalid_data",
            "path": "/data/expression",
            "severity": "error",
        }

        self.assertTrue(is_valid(diagnostic, schema))

    def test_locked_contract_tampering_is_rejected(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        path = root / "fixtures/canonical-vectors.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["vectors"][0]["jcs"] = "{}"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("canonical_drift", completed.stderr)

    def test_unlocked_contract_file_is_rejected(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        (root / "unlocked.json").write_text("{}\n", encoding="utf-8", newline="\n")

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("lock_closure", completed.stderr)

    def test_lock_path_cannot_escape_contract_root(self) -> None:
        temporary, root = self.copy_contract()
        self.addCleanup(temporary.cleanup)
        lock_path = root / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["entries"][0]["path"] = "../outside.json"
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        completed = self.run_verifier(root)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsafe_path", completed.stderr)

    def test_fixture_suite_covers_core_product_semantic_outcomes(self) -> None:
        suite = json.loads(
            (CONTRACT_ROOT / "fixtures/cases.json").read_text(encoding="utf-8")
        )
        case_ids = {case["case_id"] for case in suite["cases"]}
        required = {
            "compatible-read",
            "invalid-data",
            "type-resolution-indeterminate",
            "untrusted-type-opaque",
            "type-definition-forbidden-ref",
            "type-definition-unsupported-vocabulary",
        }

        self.assertTrue(required.issubset(case_ids), required - case_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
