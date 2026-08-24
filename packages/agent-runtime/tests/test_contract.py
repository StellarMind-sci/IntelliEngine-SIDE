from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import re
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "agent-profile" / "1.0.0"
VERIFIER = PACKAGE_ROOT / "contracts" / "tools" / "verify_contract.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("agent_profile_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier at {VERIFIER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentProfileContractTests(unittest.TestCase):
    def valid_profile(self) -> dict[str, object]:
        return {
            "contract_version": "1.0.0",
            "id": "018f5e3a-7abc-7def-8abc-0123456789ab",
            "revision": 1,
            "display_name": "Synthetic Algebra Mentor",
            "persona": {"summary": "Explains algebra through examples.", "principles": ["state assumptions"], "communication_style": "calm"},
            "goals": ["help learners check algebra"],
            "working_style": {"planning_preference": "outline", "reasoning_preference": "examples", "verification_preference": "check"},
            "declared_capabilities": ["algebra.explanation"],
            "collaboration_preferences": {"interaction_preference": "discuss", "feedback_preference": "concrete corrections"},
            "provenance_refs": ["provenance://synthetic/algebra-mentor"],
        }

    def refresh_lock(self, root: Path, verifier: object) -> None:
        lock_path = root / "lock.json"
        entries = [
            {
                "path": relative,
                "digest_kind": "jcs_sha256",
                "sha256": verifier._jcs_sha256(root / relative),
            }
            for relative in verifier._locked_json_paths(root)
        ]
        lock_path.write_text(
            json.dumps(
                {
                    "contract_version": "1.0.0",
                    "self_digest": "excluded",
                    "entries": entries,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    def test_profile_requires_canonical_persona_principles(self) -> None:
        verifier = load_verifier()
        sorted_profile = self.valid_profile()
        sorted_profile["persona"] = {**sorted_profile["persona"], "principles": ["state assumptions", "verify examples"]}
        unsorted_profile = self.valid_profile()
        unsorted_profile["persona"] = {**unsorted_profile["persona"], "principles": ["verify examples", "state assumptions"]}

        self.assertEqual(verifier.validate_profile(sorted_profile)["object_result"], "valid")
        result = verifier.validate_profile(unsorted_profile)
        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "agent_profile.noncanonical_set")
        self.assertEqual(result["issues"][0]["path"], "/persona/principles")
    def test_profile_rejects_runtime_or_private_memory_fields(self) -> None:
        verifier = load_verifier()
        result = verifier.validate_profile({**self.valid_profile(), "runtime_state": "active"})
        self.assertEqual(result["issues"][0]["code"], "agent_profile.forbidden_runtime_field")
        self.assertEqual(result["issues"][0]["path"], "/runtime_state")

    def test_missing_snapshot_is_indeterminate_not_invalid(self) -> None:
        verifier = load_verifier()
        result = verifier.validate_reference_snapshot(self.valid_profile(), None)
        self.assertEqual(result["object_result"], "not_evaluated")
        self.assertEqual(result["operation_outcome"], "indeterminate")
        self.assertEqual(result["issues"][0]["code"], "agent_profile.reference_snapshot_incomplete")

    def test_revision_must_change_content_and_increase(self) -> None:
        verifier = load_verifier()
        previous = self.valid_profile()
        candidate = {**previous, "revision": 2}
        self.assertEqual(
            verifier.validate_revision_transition(previous, candidate)["issues"][0]["code"],
            "agent_profile.revision_without_change",
        )
    def test_manifest_paths_cannot_escape_contract_root(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            copied_contract = temporary_root / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            manifest = json.loads((copied_contract / "contract.json").read_text(encoding="utf-8"))
            manifest["fixtures"] = "../outside.json"
            (copied_contract / "contract.json").write_text(json.dumps(manifest), encoding="utf-8")
            shutil.copyfile(CONTRACT_ROOT / "fixtures" / "cases.json", temporary_root / "outside.json")
            self.refresh_lock(copied_contract, verifier)

            with self.assertRaisesRegex(ValueError, "artifact path"):
                verifier.verify_contract(copied_contract)

    def test_reference_snapshot_rejects_unsorted_entries_and_top_level_extra(self) -> None:
        verifier = load_verifier()
        profile = {**self.valid_profile(), "provenance_refs": ["provenance://synthetic/a", "provenance://synthetic/b"]}
        unsorted = {
            "contract_version": "1.0.0",
            "provenance": [
                {"ref": "provenance://synthetic/b", "object_result": "available"},
                {"ref": "provenance://synthetic/a", "object_result": "available"},
            ],
        }
        with_extra = {
            "contract_version": "1.0.0",
            "provenance": [
                {"ref": "provenance://synthetic/a", "object_result": "available"},
                {"ref": "provenance://synthetic/b", "object_result": "available"},
            ],
            "extra": True,
        }

        for snapshot in (unsorted, with_extra):
            result = verifier.validate_reference_snapshot(profile, snapshot)
            self.assertEqual(result["object_result"], "not_evaluated")
            self.assertEqual(result["issues"][0]["code"], "agent_profile.reference_snapshot_incomplete")

    def test_profile_handles_unknown_surrogate_key_without_python_exception(self) -> None:
        verifier = load_verifier()
        profile = self.valid_profile()
        profile["bad\ud800"] = True

        result = verifier.validate_profile(profile)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "agent_profile.invalid_json")

    def test_fixture_suite_covers_reviewed_raw_and_set_regressions(self) -> None:
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        case_ids = {case["case_id"] for case in suite["cases"]}

        self.assertTrue({"raw-unpaired-surrogate", "unsorted-provenance", "duplicate-declared-capabilities"} <= case_ids)
    def test_verify_contract_uses_the_supplied_root_reference_schema(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_contract = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            reference_schema_path = copied_contract / "schemas" / "reference-snapshot.schema.json"
            reference_schema = json.loads(reference_schema_path.read_text(encoding="utf-8"))
            reference_schema["properties"]["provenance"]["minItems"] = 999
            reference_schema_path.write_text(json.dumps(reference_schema), encoding="utf-8")
            self.refresh_lock(copied_contract, verifier)

            with self.assertRaisesRegex(ValueError, "fixture result mismatch"):
                verifier.verify_contract(copied_contract)
    def test_verify_contract_rejects_tampered_diagnostic_catalog(self) -> None:
        verifier = load_verifier()

        def mutate_invalid_json(catalog: dict, **updates: object) -> None:
            index = next(index for index, entry in enumerate(catalog["codes"]) if entry["code"] == "agent_profile.invalid_json")
            catalog["codes"][index] = {**catalog["codes"][index], **updates}

        for mutate in (
            lambda catalog: mutate_invalid_json(catalog, severity="warning"),
            lambda catalog: mutate_invalid_json(catalog, allowed_pairs=[["not_a_result", "succeeded"]]),
        ):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary_directory:
                copied_contract = Path(temporary_directory) / "contract"
                shutil.copytree(CONTRACT_ROOT, copied_contract)
                catalog_path = copied_contract / "diagnostics" / "agent-profile.json"
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                mutate(catalog)
                catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                self.refresh_lock(copied_contract, verifier)

                with self.assertRaises(ValueError):
                    verifier.verify_contract(copied_contract)

    def test_verify_contract_rejects_tampered_manifest_limits_and_shape(self) -> None:
        verifier = load_verifier()
        for mutate in (
            lambda manifest: manifest["limits"].__setitem__("json_depth", 63),
            lambda manifest: manifest.__setitem__("unexpected", True),
        ):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary_directory:
                copied_contract = Path(temporary_directory) / "contract"
                shutil.copytree(CONTRACT_ROOT, copied_contract)
                manifest_path = copied_contract / "contract.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                self.refresh_lock(copied_contract, verifier)

                with self.assertRaises(ValueError):
                    verifier.verify_contract(copied_contract)
    def test_contract_declares_all_agent_profile_schemas_and_diagnostics(self) -> None:
        verifier = load_verifier()

        report = verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report["contract_version"], "1.0.0")

    def test_schema_preserves_reviewed_profile_version_identity_and_set_bounds(self) -> None:
        profile = json.loads(
            (CONTRACT_ROOT / "schemas" / "agent-profile.schema.json").read_text(
                encoding="utf-8"
            )
        )
        profile_ref = json.loads(
            (CONTRACT_ROOT / "schemas" / "agent-profile-ref.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(profile["properties"]["declared_capabilities"]["minItems"], 1)
        for schema in (profile, profile_ref):
            pattern = schema["properties"]["id"]["pattern"]
            self.assertIsNotNone(re.fullmatch(pattern, "018f5e3a-7abc-7def-8abc-0123456789ab"))
            self.assertIsNone(re.fullmatch(pattern, "018f5e3a-7abc-4def-8abc-0123456789ab"))
        version_pattern = profile["properties"]["contract_version"]["pattern"]
        self.assertIsNotNone(re.fullmatch(version_pattern, "1.1.0"))
        self.assertIsNone(re.fullmatch(version_pattern, "01.1.0"))

    def test_schema_preserves_reviewed_result_lock_and_fixture_boundaries(self) -> None:
        validation = json.loads(
            (CONTRACT_ROOT / "schemas" / "validation-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        diagnostic = json.loads(
            (CONTRACT_ROOT / "schemas" / "diagnostic.schema.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (CONTRACT_ROOT / "schemas" / "lock.schema.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot = json.loads(
            (CONTRACT_ROOT / "schemas" / "reference-snapshot.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fixture_suite = json.loads(
            (CONTRACT_ROOT / "schemas" / "fixture-suite.schema.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = json.loads(
            (CONTRACT_ROOT / "diagnostics" / "agent-profile.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("compatible_read", validation["properties"]["object_result"]["enum"])
        compatible_pair = next(
            pair
            for pair in validation["oneOf"]
            if pair["properties"]["object_result"] == {"const": "compatible_read"}
        )
        self.assertEqual(compatible_pair["properties"]["mode"], {"enum": ["transport", "profile"]})
        indeterminate_pair = next(
            pair
            for pair in validation["oneOf"]
            if pair["properties"]["object_result"] == {"const": "not_evaluated"}
        )
        self.assertEqual(indeterminate_pair["properties"]["mode"], {"const": "reference"})
        self.assertEqual(diagnostic["properties"]["severity"]["enum"], ["error", "warning"])
        compatible = next(code for code in catalog["codes"] if code["code"] == "agent_profile.compatible_read")
        self.assertEqual(compatible["severity"], "warning")
        self.assertEqual(compatible["allowed_pairs"], [["compatible_read", "succeeded"]])
        self.assertEqual(lock["required"], ["contract_version", "self_digest", "entries"])
        self.assertEqual(lock["properties"]["self_digest"]["const"], "excluded")
        entry = lock["properties"]["entries"]["items"]
        self.assertIn("digest_kind", entry["required"])
        self.assertEqual(entry["properties"]["digest_kind"]["const"], "jcs_sha256")
        self.assertEqual(snapshot["properties"]["provenance"]["minItems"], 1)
        cases = fixture_suite["properties"]["cases"]
        self.assertEqual(cases["minItems"], 1)
        self.assertEqual(cases["items"]["properties"]["case_id"]["pattern"], "^[a-z0-9]+(?:-[a-z0-9]+)*$")

    def test_nested_json_cannot_escape_lock_closure(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_contract = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            nested = copied_contract / "schemas" / "nested"
            nested.mkdir()
            (nested / "added.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lock closure mismatch"):
                verifier.verify_contract(copied_contract)

    def test_lock_digest_tampering_is_rejected(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_contract = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            manifest_path = copied_contract / "contract.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["side_effects"] = "tampered"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lock digest mismatch"):
                verifier.verify_contract(copied_contract)

    def test_lock_cannot_include_itself(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_contract = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            lock_path = copied_contract / "lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["entries"].append(
                {"path": "lock.json", "digest_kind": "jcs_sha256", "sha256": "0" * 64}
            )
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lock closure mismatch"):
                verifier.verify_contract(copied_contract)

    def test_fixture_expected_is_not_replayed(self) -> None:
        verifier = load_verifier()
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        case = suite["cases"][0]
        case["expected"] = {
            "interface": "agent_profile",
            "mode": "profile",
            "object_result": "invalid",
            "operation_outcome": "succeeded",
            "issues": [{"code": "agent_profile.invalid_json", "path": "", "severity": "error"}],
        }

        self.assertNotEqual(verifier.validate_case(case, CONTRACT_ROOT), case["expected"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
