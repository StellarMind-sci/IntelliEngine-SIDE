from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .validation import (
    indeterminate,
    issue,
    materialize,
    validate_graph,
    validate_references as _validate_references,
    validate_revision,
    verdict,
)


def _reject_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def parse_and_validate_transport(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            raise ValueError("BOM is forbidden")
        flow = json.loads(text, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return verdict(False, issue("thoughtflow.invalid_json", ""))
    return validate_graph(flow)


def validate_references(flow: dict, snapshot: dict) -> dict:
    return _validate_references(flow, snapshot)


def validate_revision_transition(previous: dict, candidate: dict) -> dict:
    return validate_revision(previous, candidate)


def graph_summary(flow: dict) -> dict:
    kinds: dict[str, int] = {}
    for step in flow["steps"]:
        kinds[step["kind"]] = kinds.get(step["kind"], 0) + 1
    kinds = {key: kinds[key] for key in sorted(kinds)}
    controllers = [
        {"max_iterations": step["max_iterations"], "step_id": step["step_id"]}
        for step in flow["steps"] if step["kind"] == "iteration"
    ]
    return {
        "entry_step_id": flow["entry_step_id"],
        "step_count": len(flow["steps"]),
        "transition_count": len(flow["transitions"]),
        "step_kinds": kinds,
        "loop_controllers": controllers,
    }


def _candidate(transition: dict) -> dict:
    value = {
        "kind": transition["kind"],
        "to_step_id": transition["to_step_id"],
        "transition_id": transition["transition_id"],
    }
    for field in ("branch_label", "condition_statement", "is_default"):
        if field in transition:
            value[field] = transition[field]
    return value


def next_candidates(
    flow: dict,
    step_id: str,
    observed_outcome: str | None = None,
    selected_branch: str | None = None,
) -> dict:
    step = next((item for item in flow["steps"] if item["step_id"] == step_id), None)
    if step is None:
        return {"status": "unknown_step", "candidates": []}
    outgoing = [
        transition for transition in flow["transitions"]
        if transition["from_step_id"] == step_id and transition["kind"] != "data_dependency"
    ]
    if step["kind"] in {"decision", "iteration"}:
        candidates = [_candidate(item) for item in outgoing if item["kind"] == "branch"]
        if selected_branch is None:
            return {"status": "requires_selection", "candidates": candidates}
        chosen = [item for item in candidates if item["branch_label"] == selected_branch]
        return {"status": "ready" if chosen else "invalid_selection", "candidates": chosen}
    if step["kind"] == "verification":
        if observed_outcome is None:
            return {"status": "requires_observation", "candidates": [_candidate(item) for item in outgoing]}
        chosen = [_candidate(item) for item in outgoing if item.get("outcome") == observed_outcome]
        return {"status": "ready" if chosen else "unknown_outcome", "candidates": chosen}
    return {"status": "ready", "candidates": [_candidate(item) for item in outgoing]}


def simulate_bounded(
    flow: dict,
    observations: dict[str, list[str]],
    branch_selections: dict[str, list[str]],
    max_steps: int,
) -> dict:
    if max_steps < 1:
        return {"status": "max_steps_reached", "path": [], "iteration_counts": {}}
    steps = {step["step_id"]: step for step in flow["steps"]}
    observation_index: dict[str, int] = {}
    branch_index: dict[str, int] = {}
    iteration_counts: dict[str, int] = {}
    path: list[str] = []
    current = flow["entry_step_id"]
    for _ in range(max_steps):
        path.append(current)
        step = steps[current]
        outcome = None
        branch = None
        if step["kind"] == "verification":
            index = observation_index.get(current, 0)
            values = observations.get(current, [])
            if index < len(values):
                outcome = values[index]
                observation_index[current] = index + 1
        if step["kind"] in {"decision", "iteration"}:
            index = branch_index.get(current, 0)
            values = branch_selections.get(current, [])
            if index < len(values):
                branch = values[index]
                branch_index[current] = index + 1
        candidates = next_candidates(flow, current, outcome, branch)
        if candidates["status"] != "ready":
            return {"status": candidates["status"], "path": path, "current_step_id": current, "candidates": candidates["candidates"], "iteration_counts": iteration_counts}
        if not candidates["candidates"]:
            return {"status": "completed", "path": path, "current_step_id": current, "iteration_counts": iteration_counts}
        transition = candidates["candidates"][0]
        if transition["kind"] == "loop":
            controller = transition["to_step_id"]
            count = iteration_counts.get(controller, 0) + 1
            iteration_counts[controller] = count
            if count >= steps[controller]["max_iterations"]:
                return {"status": "iteration_limit_reached", "path": path, "current_step_id": current, "iteration_counts": iteration_counts}
        current = transition["to_step_id"]
    return {"status": "max_steps_reached", "path": path, "current_step_id": current, "iteration_counts": iteration_counts}


def execute_fixture_suite(contract_root: Path) -> list[dict]:
    suite = json.loads((contract_root / "fixtures" / "cases.json").read_text(encoding="utf-8"))
    results = []
    for case in suite["cases"]:
        value = materialize(case, suite)
        if value["mode"] == "revision":
            actual = validate_revision_transition(value["previous"], value["candidate"])
        else:
            actual = validate_graph(value["flow"])
            if actual["object_result"] == "valid" and value["mode"] == "reference":
                actual = validate_references(value["flow"], value["snapshot"])
        results.append({"case_id": case["case_id"], "actual": actual, "expected": copy.deepcopy(case["expected"])})
    return results
