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

        self.assertEqual(report, {"case_count": 18, "contract_version": "1.0.0"})

    def test_local_transitions_are_pure_and_keep_contexts_independent(self) -> None:
        summon = self.verifier.validate_case(self.case("summon-increases-local-epoch"), CONTRACT_ROOT)
        rebind = self.verifier.validate_case(self.case("rebind-dormant-next-revision"), CONTRACT_ROOT)
        mismatch = self.verifier.validate_case(self.case("local-key-mismatch"), CONTRACT_ROOT)

        self.assertEqual(summon["plan"], {"operation": "summon", "disposition": "change", "target_status": "active", "state_revision": 2, "activation_epoch": 1})
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


if __name__ == "__main__":
    unittest.main(verbosity=2)