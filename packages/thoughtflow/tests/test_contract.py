from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "thoughtflow" / "1.0.0"
VERIFIER_PATH = PACKAGE_ROOT / "contracts" / "tools" / "verify_contract.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("thoughtflow_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Thoughtflow verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(case_id: str) -> dict:
    suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(case for case in suite["cases"] if case["case_id"] == case_id))


class ThoughtflowContractTests(unittest.TestCase):
    def test_bundled_contract_and_cases_verify(self) -> None:
        verifier = load_verifier()

        report = verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report, {"case_count": 18, "contract_version": "1.0.0"})

    def test_linear_equation_iteration_flow_is_valid(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)

        self.assertEqual(result, {
            "object_result": "valid",
            "operation_outcome": "succeeded",
            "issues": [],
        })

    def test_normal_control_cycle_is_rejected(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("normal-control-cycle"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.unconstrained_cycle")

    def test_loop_must_target_iteration(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("loop-wrong-target"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_loop")

    def test_decision_requires_one_default_branch(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("decision-missing-default"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_branch_set")

    def test_operation_requires_known_behavior_and_node_coverage(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("operation-unknown-behavior"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.unknown_behavior")

    def test_data_dependency_does_not_make_step_reachable(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("data-only-reachability"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.unreachable_step")

    def test_top_level_reference_closure_is_exact(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_case(fixture("unused-cognitive-ref"), CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.reference_closure_mismatch")

    def test_duplicate_json_key_is_rejected_from_raw_bytes(self) -> None:
        verifier = load_verifier()
        raw = b'{"contract_version":"1.0.0","contract_version":"1.0.0"}'

        result = verifier.validate_raw(raw, CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_json")

    def test_invalid_utf8_is_rejected_from_raw_bytes(self) -> None:
        verifier = load_verifier()

        result = verifier.validate_raw(b'{"title":"\xff"}', CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_json")

    def test_opaque_reference_is_indeterminate_not_invalid(self) -> None:
        verifier = load_verifier()
        case = fixture("linear-equation-iteration-valid")
        flow, snapshot = verifier.materialize(case, CONTRACT_ROOT)
        snapshot["knowledge_units"][0]["object_result"] = "opaque"
        snapshot["knowledge_units"][0].pop("document", None)

        result = verifier.validate_reference_snapshot(flow, snapshot)

        self.assertEqual(result["object_result"], "not_evaluated")
        self.assertEqual(result["operation_outcome"], "indeterminate")
        self.assertEqual(result["issues"][0]["code"], "thoughtflow.opaque_reference")

    def test_missing_reference_snapshot_is_indeterminate_not_invalid(self) -> None:
        verifier = load_verifier()
        case = fixture("linear-equation-iteration-valid")
        flow, snapshot = verifier.materialize(case, CONTRACT_ROOT)
        snapshot["cognitive_nodes"].pop()

        result = verifier.validate_reference_snapshot(flow, snapshot)

        self.assertEqual(result["object_result"], "not_evaluated")
        self.assertEqual(result["operation_outcome"], "indeterminate")
        self.assertEqual(result["issues"][0]["code"], "thoughtflow.reference_snapshot_incomplete")

    def test_revision_transition_rejects_revision_only_change(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        candidate = copy.deepcopy(flow)
        candidate["revision"] += 1

        result = verifier.validate_revision_transition(flow, candidate)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.revision_without_change")

    def test_revision_transition_rejects_rewritten_history(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        candidate = copy.deepcopy(flow)
        candidate["revision"] += 1
        candidate["steps"][0]["title"] = "改写既有目标"

        result = verifier.validate_revision_transition(flow, candidate)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.history_rewrite")

    def test_sequence_transition_cannot_carry_verification_outcome(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        flow["transitions"][0]["outcome"] = "passed"

        result = verifier.validate_flow(flow)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_transition")

    def test_verification_feedback_requires_an_outcome(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        flow["transitions"][7].pop("outcome")

        result = verifier.validate_flow(flow)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_transition")

    def test_step_kind_cannot_carry_fields_from_another_kind(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        flow["steps"][1]["artifact_key"] = "not-an-analysis-field"

        result = verifier.validate_flow(flow)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_step")

    def test_machine_schema_rejects_cross_kind_step_fields(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        flow["steps"][1]["artifact_key"] = "not-an-analysis-field"
        schema = json.loads((CONTRACT_ROOT / "schemas" / "thoughtflow.schema.json").read_text(encoding="utf-8"))

        accepted = verifier.is_valid(flow, schema, schema)

        self.assertFalse(accepted)

    def test_bom_is_rejected_from_raw_bytes(self) -> None:
        verifier = load_verifier()
        flow, _ = verifier.materialize(fixture("linear-equation-iteration-valid"), CONTRACT_ROOT)
        raw = b"\xef\xbb\xbf" + json.dumps(flow, ensure_ascii=False).encode("utf-8")

        result = verifier.validate_raw(raw, CONTRACT_ROOT)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_json")

    def test_nested_json_cannot_escape_lock_closure(self) -> None:
        verifier = load_verifier()
        import shutil
        import tempfile

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
        case = fixture("linear-equation-iteration-valid")
        case["expected"] = {
            "object_result": "invalid",
            "operation_outcome": "succeeded",
            "issues": [{"code": "thoughtflow.invalid_json", "path": "", "severity": "error"}],
        }

        result = verifier.validate_case(case, CONTRACT_ROOT)

        self.assertNotEqual(result, case["expected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
