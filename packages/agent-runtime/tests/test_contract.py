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
    def test_verify_contract_rejects_noncanonical_fixture_case_order(self) -> None:
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_contract = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied_contract)
            fixture_path = copied_contract / "fixtures" / "cases.json"
            suite = json.loads(fixture_path.read_text(encoding="utf-8"))
            suite["cases"][0], suite["cases"][1] = suite["cases"][1], suite["cases"][0]
            fixture_path.write_text(json.dumps(suite), encoding="utf-8")
            self.refresh_lock(copied_contract, verifier)

            with self.assertRaisesRegex(ValueError, "fixture case IDs"):
                verifier.verify_contract(copied_contract)
    def test_reference_snapshot_closure_mismatches_are_invalid(self) -> None:
        verifier = load_verifier()
        profile = {**self.valid_profile(), "provenance_refs": ["provenance://synthetic/a", "provenance://synthetic/b"]}
        missing = {"contract_version": "1.0.0", "provenance": [{"ref": "provenance://synthetic/a", "object_result": "available"}]}
        extra = {"contract_version": "1.0.0", "provenance": [{"ref": "provenance://synthetic/algebra-mentor", "object_result": "available"}, {"ref": "provenance://synthetic/other", "object_result": "available"}]}

        missing_result = verifier.validate_reference_snapshot(profile, missing)
        self.assertEqual((missing_result["object_result"], missing_result["operation_outcome"]), ("invalid", "succeeded"))
        self.assertEqual(missing_result["issues"][0]["code"], "agent_profile.dangling_provenance_reference")
        self.assertEqual(missing_result["issues"][0]["path"], "/provenance_refs/1")
        extra_result = verifier.validate_reference_snapshot(self.valid_profile(), extra)
        self.assertEqual((extra_result["object_result"], extra_result["operation_outcome"]), ("invalid", "succeeded"))
        self.assertEqual(extra_result["issues"][0]["code"], "agent_profile.dangling_provenance_reference")
        self.assertEqual(extra_result["issues"][0]["path"], "/provenance/1/ref")

    def test_profile_paths_escape_json_pointer_tokens(self) -> None:
        verifier = load_verifier()
        result = verifier.validate_profile({**self.valid_profile(), "unexpected/key~token": True})

        self.assertEqual(result["issues"][0]["code"], "agent_profile.invalid_profile_field")
        self.assertEqual(result["issues"][0]["path"], "/unexpected~1key~0token")
        snapshot_result = verifier.validate_reference_snapshot(self.valid_profile(), {"contract_version": "1.0.0", "provenance": [], "unexpected/key~token": True})
        self.assertEqual(snapshot_result["issues"][0]["path"], "/unexpected~1key~0token")

    def test_profile_enforces_string_and_jcs_size_limits(self) -> None:
        verifier = load_verifier()
        at_limit = {**self.valid_profile(), "display_name": "x" * 262144}
        above_limit = {**self.valid_profile(), "display_name": "x" * 262145}
        self.assertEqual(verifier.validate_profile(at_limit)["object_result"], "valid")
        self.assertEqual(verifier.validate_profile(above_limit)["issues"][0]["code"], "agent_profile.invalid_json")
        self.assertEqual(verifier.validate_raw(json.dumps(at_limit, separators=(",", ":")).encode("utf-8"), CONTRACT_ROOT)["object_result"], "valid")
        self.assertEqual(verifier.validate_raw(json.dumps(above_limit, separators=(",", ":")).encode("utf-8"), CONTRACT_ROOT)["issues"][0]["code"], "agent_profile.invalid_json")
        bounded = "x" * 200000
        raw_profile = {
            **self.valid_profile(),
            "display_name": bounded,
            "persona": {"summary": bounded, "principles": ["state assumptions"], "communication_style": bounded},
            "goals": [bounded],
            "working_style": {"planning_preference": bounded, "reasoning_preference": bounded, "verification_preference": bounded},
            "collaboration_preferences": {"interaction_preference": bounded, "feedback_preference": bounded},
        }
        raw = json.dumps(raw_profile, separators=(",", ":")).encode("utf-8")
        self.assertGreater(len(raw), 1048576)
        self.assertEqual(verifier.validate_raw(raw, CONTRACT_ROOT)["issues"][0]["code"], "agent_profile.invalid_json")

    def test_fixture_input_schema_is_closed_and_mode_specific(self) -> None:
        verifier = load_verifier()
        fixture_schema = json.loads((CONTRACT_ROOT / "schemas" / "fixture-suite.schema.json").read_text(encoding="utf-8"))
        input_schema = fixture_schema["properties"]["cases"]["items"]["properties"]["input"]
        private_input = {"mode": "profile", "profile": self.valid_profile(), "private_memory": "not permitted"}
        unsupported_input = {"mode": "unsupported", "profile": self.valid_profile()}

        self.assertFalse(verifier.is_valid(private_input, input_schema, input_schema))
        self.assertFalse(verifier.is_valid(unsupported_input, input_schema, input_schema))

    def test_verify_contract_rejects_open_or_remote_referenced_schemas(self) -> None:
        verifier = load_verifier()
        for relative, mutate in (
            ("schemas/agent-profile-ref.schema.json", lambda schema: schema.__setitem__("additionalProperties", True)),
            ("schemas/validation-result.schema.json", lambda schema: schema["properties"]["issues"].__setitem__("items", {"$ref": "https://example.invalid/diagnostic.schema.json"})),
            ("schemas/validation-result.schema.json", lambda schema: schema["properties"]["issues"].__setitem__("items", {"$ref": "diagnostic.schema.json#/does-not-exist"})),
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary_directory:
                copied_contract = Path(temporary_directory) / "contract"
                shutil.copytree(CONTRACT_ROOT, copied_contract)
                schema_path = copied_contract / relative
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                mutate(schema)
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_lock(copied_contract, verifier)

                with self.assertRaises(ValueError):
                    verifier.verify_contract(copied_contract)

    def test_agent_profile_ref_schema_rejects_invalid_closed_refs(self) -> None:
        verifier = load_verifier()
        schema = json.loads((CONTRACT_ROOT / "schemas" / "agent-profile-ref.schema.json").read_text(encoding="utf-8"))
        valid_ref = {"id": "018f5e3a-7abc-7def-8abc-0123456789ab", "revision": 1}

        self.assertTrue(verifier.is_valid(valid_ref, schema, schema))
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual({probe["case_id"] for probe in suite["schema_probes"]}, {"agent-profile-ref-extra", "agent-profile-ref-invalid-id", "agent-profile-ref-invalid-revision", "agent-profile-ref-valid"})
        for invalid_ref in ({**valid_ref, "extra": True}, {**valid_ref, "id": "not-a-uuid"}, {**valid_ref, "revision": 0}):
            with self.subTest(invalid_ref=invalid_ref):
                self.assertFalse(verifier.is_valid(invalid_ref, schema, schema))
    def test_resource_limits_reject_deep_and_oversized_profiles_without_exceptions(self) -> None:
        verifier = load_verifier()
        at_array_limit = {**self.valid_profile(), "goals": [f"goal-{index:05d}" for index in range(10000)]}
        above_array_limit = {**self.valid_profile(), "goals": [f"goal-{index:05d}" for index in range(10001)]}
        self.assertEqual(verifier.validate_profile(at_array_limit)["object_result"], "valid")
        self.assertEqual(verifier.validate_profile(above_array_limit)["issues"][0]["code"], "agent_profile.invalid_json")
        nested: object = 0
        for _ in range(2000):
            nested = {"next": nested}
        deep_profile = {**self.valid_profile(), "unexpected": nested}
        direct_result = verifier.validate_profile(deep_profile)
        self.assertEqual(direct_result["issues"][0]["code"], "agent_profile.invalid_json")
        encoded = json.dumps(self.valid_profile(), separators=(",", ":")).encode("utf-8")
        deep_raw = encoded[:-1] + b',"unexpected":' + (b'{"next":' * 2000) + b'0' + (b'}' * 2001)
        raw_result = verifier.validate_raw(deep_raw, CONTRACT_ROOT)
        self.assertEqual(raw_result["issues"][0]["code"], "agent_profile.invalid_json")
        oversized_snapshot = {"contract_version": "1.0.0", "provenance": [{"ref": f"provenance://synthetic/{index:05d}-" + ("x" * 250), "object_result": "available"} for index in range(5000)]}
        snapshot_result = verifier.validate_reference_snapshot(self.valid_profile(), oversized_snapshot)
        self.assertEqual(snapshot_result["object_result"], "not_evaluated")
        self.assertEqual(snapshot_result["issues"][0]["code"], "agent_profile.reference_snapshot_incomplete")

    def test_semver_component_size_is_deterministically_invalid(self) -> None:
        verifier = load_verifier()
        profile = {**self.valid_profile(), "contract_version": ("9" * 5000) + ".0.0"}
        direct_result = verifier.validate_profile(profile)
        raw_result = verifier.validate_raw(json.dumps(profile, separators=(",", ":")).encode("utf-8"), CONTRACT_ROOT)

        self.assertEqual(direct_result["issues"][0]["code"], "agent_profile.unsupported_contract_version")
        self.assertEqual(raw_result["issues"][0]["code"], "agent_profile.unsupported_contract_version")
    def test_contract_declares_all_agent_profile_schemas_and_diagnostics(self) -> None:
        verifier = load_verifier()

        report = verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report["contract_version"], "1.0.0")

    def test_validation_result_schema_closes_result_issue_pairs(self) -> None:
        verifier = load_verifier()
        validation = json.loads((CONTRACT_ROOT / "schemas" / "validation-result.schema.json").read_text(encoding="utf-8"))
        diagnostic = json.loads((CONTRACT_ROOT / "schemas" / "diagnostic.schema.json").read_text(encoding="utf-8"))
        resolved_validation = json.loads(json.dumps(validation))
        resolved_validation["properties"]["issues"]["items"] = diagnostic
        issue = {"code": "agent_profile.invalid_json", "severity": "error", "path": "/"}
        invalid_results = (
            {"interface": "agent_profile", "mode": "profile", "object_result": "valid", "operation_outcome": "succeeded", "issues": [issue]},
            {"interface": "agent_profile", "mode": "profile", "object_result": "invalid", "operation_outcome": "succeeded", "issues": []},
            {"interface": "agent_profile", "mode": "profile", "object_result": "compatible_read", "operation_outcome": "succeeded", "issues": []},
            {"interface": "agent_profile", "mode": "reference", "object_result": "not_evaluated", "operation_outcome": "indeterminate", "issues": []},
            {"interface": "agent_profile", "mode": "profile", "object_result": "valid", "operation_outcome": "succeeded", "issues": [], "extra": True},
        )

        for result in invalid_results:
            with self.subTest(result=result):
                self.assertFalse(verifier.is_valid(result, resolved_validation, resolved_validation))
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
