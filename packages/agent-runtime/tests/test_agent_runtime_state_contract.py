"""Executable acceptance tests for the AgentRuntimeState 1.0.0 machine contract."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "agent-runtime" / "contracts" / "agent-runtime-state" / "1.0.0"
VERIFIER_PATH = REPOSITORY_ROOT / "packages" / "agent-runtime" / "contracts" / "tools" / "verify_agent_runtime_state_contract.py"


def load_verifier():
    specification = importlib.util.spec_from_file_location("verify_agent_runtime_state_contract", VERIFIER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class AgentRuntimeStateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = load_verifier()
        self.suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))

    def case(self, case_id: str) -> dict[str, object]:
        return next(case for case in self.suite["cases"] if case["case_id"] == case_id)

    def refresh_lock(self, root: Path) -> None:
        entries = [
            {
                "path": relative,
                "digest_kind": "jcs_sha256",
                "sha256": self.verifier._jcs_sha256(self.verifier._artifact_path(root, relative)),
            }
            for relative in self.verifier._locked_json_paths(root)
        ]
        (root / "lock.json").write_text(
            json.dumps({"contract_version": "1.0.0", "self_digest": "excluded", "entries": entries}),
            encoding="utf-8",
        )

    def test_contract_is_a_closed_offline_machine_profile(self) -> None:
        report = self.verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report, {"case_count": 33, "contract_version": "1.0.0"})

    def test_local_transitions_are_pure_and_keep_contexts_independent(self) -> None:
        summon = self.verifier.validate_case(self.case("summon-increases-local-epoch"), CONTRACT_ROOT)
        rebind = self.verifier.validate_case(self.case("rebind-dormant-next-revision"), CONTRACT_ROOT)
        mismatch = self.verifier.validate_case(self.case("local-key-mismatch"), CONTRACT_ROOT)

        self.assertEqual({key: summon["plan"][key] for key in ("operation", "disposition", "target_status", "state_revision", "activation_epoch")}, {"operation": "summon", "disposition": "change", "target_status": "active", "state_revision": 2, "activation_epoch": 1})
        self.assertEqual(summon["plan"]["runtime_context_ref"], "project:geometry")
        self.assertEqual(summon["plan"]["state_ref"]["state_revision"], 1)
        self.assertEqual(rebind["plan"]["activation_epoch"], 0)
        self.assertEqual(rebind["plan"]["target_profile_ref"]["revision"], 2)
        self.assertEqual(mismatch["operation_outcome"], "conflict")
        self.assertEqual(mismatch["issues"][0]["code"], "agent_runtime_state.local_state_mismatch")

    def test_aggregate_is_authorized_input_only_and_does_not_leak_contexts(self) -> None:
        result = self.verifier.validate_case(self.case("aggregate-visible-authorized-only"), CONTRACT_ROOT)
        empty = self.verifier.validate_case(self.case("aggregate-empty"), CONTRACT_ROOT)

        self.assertEqual(result["aggregate"], {"contract_version": "1.0.0", "visible_state_count": 3, "active_count": 1, "dormant_count": 1, "archived_count": 1})
        self.assertNotIn("authority_scope_ref", result["aggregate"])
        self.assertNotIn("runtime_context_ref", result["aggregate"])
        self.assertEqual(empty["aggregate"]["visible_state_count"], 0)

    def test_transport_rejects_duplicate_keys_invalid_utf8_and_unsafe_numbers(self) -> None:
        self.assertEqual(self.verifier.validate_case(self.case("transport-duplicate-json-key"), CONTRACT_ROOT)["issues"][0]["code"], "agent_runtime_state.invalid_json")
        self.assertEqual(self.verifier.validate_raw(b'\xff', CONTRACT_ROOT)["issues"][0]["code"], "agent_runtime_state.invalid_json")
        state = copy.deepcopy(self.case("state-registered-not-dormant")["input"]["state"])
        state["state_revision"] = 9_007_199_254_740_992
        self.assertEqual(self.verifier.validate_state(state)["issues"][0]["code"], "agent_runtime_state.invalid_json")

    def test_verifier_rejects_tampered_expected_without_replaying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied)
            fixture = json.loads((copied / "fixtures" / "cases.json").read_text(encoding="utf-8"))
            fixture["cases"][0]["expected"] = {"tampered": True}
            (copied / "fixtures" / "cases.json").write_text(json.dumps(fixture), encoding="utf-8")
            self.refresh_lock(copied)
            with self.assertRaisesRegex(ValueError, "fixture result mismatch"):
                self.verifier.verify_contract(copied)

    def test_verifier_rejects_path_escape_and_lock_closure_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied)
            manifest_path = copied / "contract.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemas"]["agent_runtime_state"] = "../escape.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.refresh_lock(copied)
            with self.assertRaisesRegex(ValueError, "invalid contract manifest"):
                self.verifier.verify_contract(copied)
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied = Path(temporary_directory) / "contract"
            shutil.copytree(CONTRACT_ROOT, copied)
            nested = copied / "schemas" / "nested"; nested.mkdir()
            (nested / "added.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lock closure mismatch"):
                self.verifier.verify_contract(copied)

    def test_verifier_rejects_missing_local_pointer_and_remote_schema_ref(self) -> None:
        for reference in ("#/does-not-exist", "../escape.json#/state", "https://example.invalid/remote.json"):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as temporary_directory:
                copied = Path(temporary_directory) / "contract"
                shutil.copytree(CONTRACT_ROOT, copied)
                schema_path = copied / "schemas" / "agent-runtime-state.schema.json"
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                schema["properties"]["status"]["$ref"] = reference
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                self.refresh_lock(copied)
                with self.assertRaisesRegex(ValueError, "invalid schema reference"):
                    self.verifier.verify_contract(copied)

    def test_plan_and_record_schema_bind_the_scoped_local_identity(self) -> None:
        plan_schema = json.loads((CONTRACT_ROOT / "schemas" / "transition-plan.schema.json").read_text(encoding="utf-8"))
        record_schema = json.loads((CONTRACT_ROOT / "schemas" / "transition-record.schema.json").read_text(encoding="utf-8"))
        bare_plan = {"operation": "close", "disposition": "change", "target_status": "dormant", "state_revision": 3, "activation_epoch": 1}
        bare_record = {"contract_version": "1.0.0", "record_id": "019f5e3a-7abc-7def-8abc-0123456789d1", "request_id": "019f5e3a-7abc-7def-8abc-0123456789d2", "state_id": "019f5e3a-7abc-7def-8abc-0123456789a1", "operation": "close", "outcome": "applied", "provenance_ref": "provenance:synthetic"}
        self.assertFalse(self.verifier.is_valid(bare_plan, plan_schema, plan_schema))
        self.assertFalse(self.verifier.is_valid(bare_record, record_schema, record_schema))

    def test_transition_rejects_compatible_read_state_for_write_previews(self) -> None:
        state = copy.deepcopy(self.case("state-compatible-read")["input"]["state"])
        intent = copy.deepcopy(self.case("no-change-close-dormant")["input"]["intent"])
        intent["expected_state_ref"] = {"state_id": state["state_id"], "state_revision": state["state_revision"]}
        result = self.verifier.plan_transition(state, intent)
        self.assertEqual((result["object_result"], result["operation_outcome"]), ("invalid", "rejected"))
        self.assertEqual(result["issues"][0]["code"], "agent_runtime_state.unsupported_contract_version")

    def test_aggregate_applies_global_i_json_budget_before_per_state_iteration(self) -> None:
        base = copy.deepcopy(self.case("state-registered-not-dormant")["input"]["state"])
        visible_states = []
        for index in range(3000):
            state = copy.deepcopy(base)
            state["state_id"] = f"019f5e3a-7abc-7def-8abc-{index:012x}"
            state["runtime_context_ref"] = f"project:budget-{index:05d}" + ("x" * 230)
            visible_states.append(state)
        result = self.verifier.aggregate_visible_states({"contract_version": "1.0.0", "visible_states": visible_states})
        self.assertEqual(result["issues"][0]["code"], "agent_runtime_state.invalid_aggregate_input")
    def test_record_rebind_uses_logical_profile_id_and_preserves_exact_snapshot_refs(self) -> None:
        record = copy.deepcopy(self.case("record-valid-local-transition")["input"]["record"])
        record.pop("agent_profile_ref", None)
        record["agent_profile_id"] = record["before_state"]["agent_profile_ref"]["id"]
        record["operation"] = "rebind_profile"
        record["before_state"]["status"] = "dormant"
        record["after_state"]["status"] = "dormant"
        record["after_state"]["agent_profile_ref"]["revision"] = 2
        valid = self.verifier.validate_transition_record(record)
        self.assertEqual((valid["object_result"], valid["operation_outcome"]), ("valid", "succeeded"))
        cross_id = copy.deepcopy(record)
        cross_id["after_state"]["agent_profile_ref"]["id"] = "018f5e3a-7abc-7def-8abc-0123456789ac"
        self.assertEqual(self.verifier.validate_transition_record(cross_id)["issues"][0]["code"], "agent_runtime_state.record_local_mismatch")

if __name__ == "__main__":
    unittest.main(verbosity=2)