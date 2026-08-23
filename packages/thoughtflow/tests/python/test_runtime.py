from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "thoughtflow" / "1.0.0"
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_thoughtflow.runtime import (
    execute_fixture_suite,
    graph_summary,
    next_candidates,
    parse_and_validate_transport,
    simulate_bounded,
    validate_revision_transition,
)


def valid_flow() -> dict:
    suite = json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    return copy.deepcopy(suite["cases"][0]["input"]["flow"])


class ThoughtflowPythonRuntimeTests(unittest.TestCase):
    def test_executes_all_machine_fixtures_without_replaying_expected(self) -> None:
        results = execute_fixture_suite(CONTRACT_ROOT)

        self.assertEqual(len(results), 18)
        self.assertTrue(all(item["actual"] == item["expected"] for item in results))

    def test_raw_transport_rejects_duplicate_members(self) -> None:
        result = parse_and_validate_transport(b'{"contract_version":"1.0.0","contract_version":"1.0.0"}')

        self.assertEqual(result["issues"][0]["code"], "thoughtflow.invalid_json")

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
        })

    def test_iteration_requires_explicit_branch_selection(self) -> None:
        result = next_candidates(valid_flow(), "s03-iteration")

        self.assertEqual(result["status"], "requires_selection")
        self.assertEqual([item["branch_label"] for item in result["candidates"]], ["retry", "stop"])

    def test_verification_outcome_selects_explicit_feedback(self) -> None:
        result = next_candidates(valid_flow(), "s06-verification", observed_outcome="failed")

        self.assertEqual(result, {
            "status": "ready",
            "candidates": [{"kind": "loop", "to_step_id": "s03-iteration", "transition_id": "t08"}],
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
