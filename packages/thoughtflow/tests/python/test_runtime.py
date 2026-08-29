from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "thoughtflow" / "1.0.0"
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_thoughtflow.validation import canonicalize
from intelliengine_thoughtflow.runtime import (
    execute_fixture_suite,
    graph_summary,
    next_candidates,
    parse_and_validate_transport,
    simulate_bounded,
    validate_references,
    validate_revision_transition,
)


def valid_flow() -> dict:
    suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    return copy.deepcopy(suite["cases"][0]["input"]["flow"])

def valid_snapshot() -> dict:
    suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    return copy.deepcopy(suite["cases"][0]["input"]["snapshot"])

RUNTIME_CASES = json.loads((PACKAGE_ROOT / "tests" / "fixtures" / "runtime-cases.json").read_text(encoding="utf-8"))


def rename_step(flow: dict, previous: str, new: str) -> None:
    for step in flow["steps"]:
        if step["step_id"] == previous:
            step["step_id"] = new
        if step["kind"] == "iteration":
            step["verification_step_ids"] = [new if value == previous else value for value in step["verification_step_ids"]]
    if flow["entry_step_id"] == previous:
        flow["entry_step_id"] = new
    for transition in flow["transitions"]:
        if transition["from_step_id"] == previous:
            transition["from_step_id"] = new
        if transition["to_step_id"] == previous:
            transition["to_step_id"] = new


def transition_tuple(value: dict) -> tuple[bytes, ...]:
    parts = [value["from_step_id"], value["kind"], value.get("branch_label", value.get("outcome", "")), value["to_step_id"], value["transition_id"]]
    return tuple(part.encode("utf-8") for part in parts)


def collision_flow() -> dict:
    flow = valid_flow()
    collision = RUNTIME_CASES["nul_tuple_collision"]
    rename_step(flow, "s04-operation", collision["target_step_ids"][0])
    rename_step(flow, "s07-success", collision["target_step_ids"][1])
    flow["steps"].sort(key=lambda step: step["step_id"].encode("utf-8"))
    flow["transitions"].extend(copy.deepcopy(collision["transitions"]))
    flow["transitions"].sort(key=transition_tuple)
    return flow


def sized_flow(target_bytes: int) -> dict:
    ref = {"id": "018f0c20-7a8b-7c1d-8a2e-333333333333", "revision": 1}
    steps = [{"step_id": "s0000", "kind": "goal", "title": "g", "description": "x", "knowledge_unit_refs": [], "cognitive_node_refs": [], "success_statement": "done"}]
    for index in range(1, 601):
        steps.append({"step_id": f"s{index:04d}", "kind": "analysis", "title": "a", "description": "x", "knowledge_unit_refs": [], "cognitive_node_refs": []})
    steps.extend([
        {"step_id": "s0601", "kind": "verification", "title": "v", "description": "x", "knowledge_unit_refs": [], "cognitive_node_refs": [ref], "acceptance_statement": "ok", "evidence_node_refs": [ref]},
        {"step_id": "s0602", "kind": "goal", "title": "z", "description": "x", "knowledge_unit_refs": [], "cognitive_node_refs": [], "success_statement": "done"},
    ])
    transitions = [{"transition_id": f"t{index:04d}", "kind": "sequence", "from_step_id": f"s{index:04d}", "to_step_id": f"s{index + 1:04d}"} for index in range(601)]
    transitions.append({"transition_id": "t0601", "kind": "verification_feedback", "from_step_id": "s0601", "to_step_id": "s0602", "outcome": "passed"})
    flow = {"contract_version": "1.0.0", "id": "018f0c20-7a8b-7c1d-8a2e-111111111111", "revision": 1, "title": "sized", "entry_step_id": "s0000", "steps": steps, "transitions": transitions, "knowledge_unit_refs": [], "cognitive_node_refs": [ref], "provenance_refs": ["p"]}
    remaining = target_bytes - len(canonicalize(flow))
    assert remaining >= 0
    for step in steps:
        added = min(8191, remaining)
        step["description"] += "x" * added
        remaining -= added
    assert remaining == 0
    assert len(canonicalize(flow)) == target_bytes
    return flow


class ThoughtflowPythonRuntimeTests(unittest.TestCase):
    def test_executes_all_machine_fixtures_without_replaying_expected(self) -> None:
        results = execute_fixture_suite(CONTRACT_ROOT)

        self.assertEqual(len(results), 18)
        self.assertTrue(all(item["actual"] == item["expected"] for item in results))

    def test_rejects_available_knowledge_unit_with_mismatched_document_identity(self) -> None:
        snapshot = valid_snapshot()
        snapshot["knowledge_units"][0]["document"]["id"] = "018f0c20-7a8b-7c1d-8a2e-666666666666"

        result = validate_references(valid_flow(), snapshot)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "thoughtflow.dangling_reference")
        self.assertEqual(result["issues"][0]["path"], "/knowledge_unit_refs/0")

    def test_rejects_available_knowledge_unit_with_mismatched_document_revision(self) -> None:
        snapshot = valid_snapshot()
        snapshot["knowledge_units"][0]["document"]["revision"] = 2

        result = validate_references(valid_flow(), snapshot)

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "thoughtflow.dangling_reference")
        self.assertEqual(result["issues"][0]["path"], "/knowledge_unit_refs/0")

    def test_raw_transport_rejects_duplicate_members(self) -> None:
        result = parse_and_validate_transport(b'{"contract_version":"1.0.0","contract_version":"1.0.0"}')

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_json")

    def test_raw_transport_enforces_locked_schema_and_size_boundary(self) -> None:
        mutations = []
        extra = valid_flow()
        extra["unknown"] = True
        mutations.append(extra)
        missing = valid_flow()
        del missing["title"]
        mutations.append(missing)
        for flow in mutations:
            with self.subTest(keys=sorted(flow)):
                raw = json.dumps(flow, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.assertEqual(parse_and_validate_transport(raw)["issues"][0]["code"], "thoughtflow.invalid_json")

        self.assertEqual(parse_and_validate_transport(json.dumps(sized_flow(4194303), separators=(",", ":")).encode())["object_result"], "valid")
        self.assertEqual(parse_and_validate_transport(json.dumps(sized_flow(4194304), separators=(",", ":")).encode())["object_result"], "valid")
        self.assertEqual(parse_and_validate_transport(json.dumps(sized_flow(4194305), separators=(",", ":")).encode())["object_result"], "invalid")

    def test_future_same_major_minor_is_compatible_read_and_cannot_drive_control(self) -> None:
        flow = valid_flow()
        flow["contract_version"] = "1.1.0"
        compatible_result = {
            "object_result": "not_evaluated", "operation_outcome": "indeterminate",
            "issues": [{"code": "thoughtflow.unsupported_contract_version", "path": "/contract_version", "severity": "error"}],
        }
        self.assertEqual(parse_and_validate_transport(json.dumps(flow, separators=(",", ":")).encode()), compatible_result)
        long_version = valid_flow()
        long_version["contract_version"] = f"1.{'9' * 5000}.0"
        self.assertEqual(parse_and_validate_transport(json.dumps(long_version, separators=(",", ":")).encode()), compatible_result)
        self.assertEqual(next_candidates(flow, "s03-iteration")["status"], "compatible_read")
        self.assertEqual(simulate_bounded(flow, observations={}, branch_selections={}, max_steps=10)["status"], "compatible_read")
        candidate = copy.deepcopy(flow)
        candidate["revision"] = 2
        candidate["title"] = "future mutation"
        self.assertEqual(validate_revision_transition(flow, candidate)["object_result"], "not_evaluated")

    def test_transition_tuple_comparison_cannot_collide_across_nul_boundaries(self) -> None:
        raw = json.dumps(collision_flow(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(parse_and_validate_transport(raw)["object_result"], "valid")

    def test_graph_summary_is_deterministic(self) -> None:
        summary = graph_summary(valid_flow())

        self.assertEqual(summary, {
            "entry_step_id": "s01-goal",
            "step_count": 7,
            "transition_count": 8,
            "step_kinds": {
                "analysis": 1, "artifact": 1, "goal": 2, "iteration": 1,
                "operation": 1, "verification": 1,
            },
            "loop_controllers": [{"max_iterations": 3, "step_id": "s03-iteration"}],
            "reachable_step_count": 7,
            "reachable_step_ids": ["s01-goal", "s02-analysis", "s03-iteration", "s04-operation", "s05-artifact", "s06-verification", "s07-success"],
        })

    def test_iteration_requires_explicit_branch_selection(self) -> None:
        result = next_candidates(valid_flow(), "s03-iteration")

        self.assertEqual(result["status"], "requires_selection")
        self.assertEqual([item["branch_label"] for item in result["candidates"]], ["retry", "stop"])

    def test_verification_outcome_selects_explicit_feedback(self) -> None:
        result = next_candidates(valid_flow(), "s06-verification", observed_outcome="failed")

        self.assertEqual(result, {
            "status": "ready",
            "candidates": [{"kind": "loop", "outcome": "failed", "to_step_id": "s03-iteration", "transition_id": "t08"}],
        })

    def test_simulation_stops_at_declared_iteration_limit(self) -> None:
        result = simulate_bounded(
            valid_flow(),
            observations={"s06-verification": ["failed", "failed", "failed", "failed"]},
            branch_selections={"s03-iteration": ["retry", "retry", "retry", "retry"]},
            max_steps=40,
        )

        self.assertEqual(result["status"], "iteration_limit_reached")
        self.assertEqual(result["iteration_counts"], {"s03-iteration": 3})
        self.assertNotIn("executed_operations", result)

    def test_revision_only_change_is_rejected(self) -> None:
        previous = valid_flow()
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 2

        result = validate_revision_transition(previous, candidate)

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.revision_without_change")


    def test_simulation_never_chooses_first_of_multiple_control_successors(self) -> None:
        flow = valid_flow()
        flow["transitions"].append({
            "transition_id": "t99", "kind": "sequence",
            "from_step_id": "s01-goal", "to_step_id": "s03-iteration",
        })

        result = simulate_bounded(flow, observations={}, branch_selections={}, max_steps=5)

        self.assertEqual(result["status"], "ambiguous_control")
        self.assertEqual(result["current_step_id"], "s01-goal")

    def test_tampered_expected_cannot_change_actual(self) -> None:
        suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        case = copy.deepcopy(suite["cases"][0])
        original_expected = copy.deepcopy(case["expected"])
        case["expected"] = {
            "object_result": "invalid",
            "operation_outcome": "succeeded",
            "issues": [{"code": "thoughtflow.invalid_json", "path": "", "severity": "error"}],
        }

        raw = json.dumps(case["input"]["flow"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        actual = parse_and_validate_transport(raw)

        self.assertEqual(actual, original_expected)
        self.assertNotEqual(actual, case["expected"])


    def test_missing_verification_observation_is_indeterminate(self) -> None:
        result = simulate_bounded(
            valid_flow(), observations={},
            branch_selections={"s03-iteration": ["retry"]}, max_steps=10,
        )

        self.assertEqual(result["status"], "requires_observation")
        self.assertEqual(result["object_result"], "not_evaluated")
        self.assertEqual(result["operation_outcome"], "indeterminate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
