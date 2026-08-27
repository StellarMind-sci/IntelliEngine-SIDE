from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

import intelliengine_agent_runtime as package

import intelliengine_agent_runtime.agent_runtime_state as state_runtime
from intelliengine_agent_runtime.agent_runtime_state import (  # noqa: E402
    aggregate_visible_states,
    execute_fixture_suite,
    parse_and_validate_transport,
    plan_transition,
    validate_state,
)

CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "agent-runtime-state" / "1.0.0"

def suite() -> dict:
    return json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))

def case(case_id: str) -> dict:
    return copy.deepcopy(next(item for item in suite()["cases"] if item["case_id"] == case_id))

class AgentRuntimeStatePythonRuntimeTests(unittest.TestCase):
    def test_public_package_exports_read_only_state_api(self) -> None:
        self.assertTrue({"validate_state", "plan_transition", "aggregate_visible_states", "state_summary", "validate_transition_record"}.issubset(set(package.__all__)))
    def test_executes_every_locked_case_using_real_runtime(self) -> None:
        results = execute_fixture_suite(CONTRACT_ROOT)
        self.assertEqual(len(results), 33)
        self.assertTrue(all(item["actual"] == item["expected"] for item in results))

    def test_same_profile_ref_rebind_ignores_json_member_order(self) -> None:
        item = case("rebind-same-ref-no-change")["input"]
        ref = item["intent"]["target_profile_ref"]
        item["intent"]["target_profile_ref"] = {"revision": ref["revision"], "id": ref["id"]}
        self.assertEqual(plan_transition(item["state"], item["intent"], CONTRACT_ROOT)["plan"]["disposition"], "no_change")

    def test_raw_state_revision_rejects_non_integer_lexical_tokens(self) -> None:
        state = case("state-registered-not-dormant")["input"]["state"]
        raw = json.dumps(state, separators=(",", ":"))
        for token in ("1.0", "1e0", "-0"):
            with self.subTest(token=token):
                result = parse_and_validate_transport(raw.replace('"state_revision":2', f'"state_revision":{token}').encode("utf-8"), CONTRACT_ROOT)
                self.assertEqual(result["object_result"], "invalid")
                self.assertEqual(result["issues"][0], {"code": "agent_runtime_state.invalid_state_field", "path": "/state_revision", "severity": "error"})

    def test_locked_contract_rejects_unsafe_root_and_schema_reference_closure(self) -> None:
        def replace_reference(root: Path, reference: str) -> None:
            schema_path = root / "schemas" / "agent-runtime-state.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["$ref"] = reference
            schema_path.write_text(json.dumps(schema, separators=(",", ":")), encoding="utf-8")
            lock_path = root / "lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            for entry in lock["entries"]:
                if entry["path"] == "schemas/agent-runtime-state.schema.json":
                    entry["sha256"] = hashlib.sha256(state_runtime.canonicalize(schema)).hexdigest()
            lock_path.write_text(json.dumps(lock, separators=(",", ":")), encoding="utf-8")

        with self.assertRaises(Exception):
            state_runtime.load_locked_contract(CONTRACT_ROOT.parent)
        for reference in ("#/~2", "../diagnostics/agent-runtime-state.json", "file:///tmp/outside.json", "https://example.invalid/schema.json", "unlisted.json"):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "agent-runtime-state" / "1.0.0"
                root.parent.mkdir(parents=True)
                shutil.copytree(CONTRACT_ROOT, root)
                replace_reference(root, reference)
                with self.assertRaises(Exception):
                    state_runtime.load_locked_contract(root)
    def test_transport_rejects_duplicate_keys_and_invalid_utf8(self) -> None:
        self.assertEqual(parse_and_validate_transport(b'{"contract_version":"1.0.0","contract_version":"1.0.0"}', CONTRACT_ROOT)["issues"][0]["code"], "agent_runtime_state.invalid_json")
        self.assertEqual(parse_and_validate_transport(b'{"text":"\xed\xa0\x80"}', CONTRACT_ROOT)["issues"][0]["code"], "agent_runtime_state.invalid_json")

    def test_plan_transition_is_pure_and_does_not_mutate_inputs(self) -> None:
        item = case("summon-increases-local-epoch")["input"]
        state, intent = item["state"], item["intent"]
        original_state, original_intent = copy.deepcopy(state), copy.deepcopy(intent)
        result = plan_transition(state, intent, CONTRACT_ROOT)
        self.assertEqual(result["operation_outcome"], "succeeded")
        self.assertEqual(result["plan"]["target_status"], "active")
        self.assertEqual(result["plan"]["state_revision"], state["state_revision"] + 1)
        self.assertEqual(result["plan"]["activation_epoch"], state["activation_epoch"] + 1)
        self.assertEqual(state, original_state)
        self.assertEqual(intent, original_intent)

    def test_aggregate_counts_only_caller_supplied_visible_states(self) -> None:
        visible = case("aggregate-visible-authorized-only")["input"]["aggregate_input"]
        result = aggregate_visible_states(visible, CONTRACT_ROOT)
        self.assertEqual(result["aggregate"], {"contract_version": "1.0.0", "visible_state_count": 3, "active_count": 1, "dormant_count": 1, "archived_count": 1})
        self.assertNotIn("authority_scope_ref", result["aggregate"])
        self.assertNotIn("runtime_context_ref", result["aggregate"])

    def test_differential_runner_compares_all_python_and_typescript_fields(self) -> None:
        import subprocess

        completed = subprocess.run(
            [sys.executable, "-B", str(PACKAGE_ROOT.parents[1] / "scripts" / "agent-runtime-state" / "differential.py")],
            cwd=PACKAGE_ROOT.parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["case_count"], 33)
        self.assertEqual(report["raw_transport_probe_count"], 3)
    def test_compatible_minor_is_read_only_not_transitionable(self) -> None:
        item = case("summon-increases-local-epoch")["input"]
        state = copy.deepcopy(item["state"])
        state["contract_version"] = "1.1.0"
        self.assertEqual(validate_state(state, CONTRACT_ROOT)["object_result"], "compatible_read")
        result = plan_transition(state, item["intent"], CONTRACT_ROOT)
        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["operation_outcome"], "rejected")
        self.assertEqual(result["issues"][0]["code"], "agent_runtime_state.unsupported_contract_version")

if __name__ == "__main__":
    unittest.main(verbosity=2)