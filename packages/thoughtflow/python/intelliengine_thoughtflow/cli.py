from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
COGNITIVE_IR_PYTHON = PACKAGE_ROOT.parent / "cognitive-ir" / "python"
if str(COGNITIVE_IR_PYTHON) not in sys.path:
    sys.path.insert(0, str(COGNITIVE_IR_PYTHON))
if str(PACKAGE_ROOT / "python") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_conformance.json_codec import parse_json_bytes
from intelliengine_thoughtflow.runtime import graph_summary, next_candidates, simulate_bounded, validate_references, validate_revision_transition
from intelliengine_thoughtflow.validation import materialize, validate_graph


def safe_fixture(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if (
        not relative or "\\" in relative or relative.startswith("/")
        or relative.startswith("//") or re.match(r"^[A-Za-z]:/", relative)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("unsafe fixture path")
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root.joinpath(*parts).resolve(strict=True)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("fixture escapes contract root") from error
    return candidate


def query_projection(flow: dict) -> list[dict]:
    queries = []
    for step in flow["steps"]:
        step_id = step["step_id"]
        queries.append({"input": {"step_id": step_id}, "result": next_candidates(flow, step_id)})
        outgoing = [item for item in flow["transitions"] if item["from_step_id"] == step_id]
        if step["kind"] in {"decision", "iteration"}:
            for transition in outgoing:
                if transition["kind"] == "branch":
                    selected = transition["branch_label"]
                    queries.append({
                        "input": {"selected_branch": selected, "step_id": step_id},
                        "result": next_candidates(flow, step_id, selected_branch=selected),
                    })
        if step["kind"] == "verification":
            seen = set()
            for transition in outgoing:
                outcome = transition.get("outcome")
                if outcome is not None and outcome not in seen:
                    seen.add(outcome)
                    queries.append({
                        "input": {"observed_outcome": outcome, "step_id": step_id},
                        "result": next_candidates(flow, step_id, observed_outcome=outcome),
                    })
    return queries


def scenario_inputs(flow: dict, choose_last: bool) -> tuple[dict, dict]:
    observations, branches = {}, {}
    for step in flow["steps"]:
        outgoing = [item for item in flow["transitions"] if item["from_step_id"] == step["step_id"]]
        if step["kind"] in {"decision", "iteration"}:
            values = [item["branch_label"] for item in outgoing if item["kind"] == "branch"]
            if values:
                branches[step["step_id"]] = [values[-1 if choose_last else 0]] * 100
        if step["kind"] == "verification":
            values = []
            for item in outgoing:
                if item.get("outcome") is not None and item["outcome"] not in values:
                    values.append(item["outcome"])
            if values:
                observations[step["step_id"]] = [values[-1 if choose_last else 0]] * 100
    return observations, branches


def simulation_projection(flow: dict) -> list[dict]:
    first_observations, first_branches = scenario_inputs(flow, False)
    last_observations, last_branches = scenario_inputs(flow, True)
    scenarios = [
        ("missing_inputs", {}, {}, 40),
        ("first_options", first_observations, first_branches, 40),
        ("last_options", last_observations, last_branches, 40),
        ("max_steps_one", {}, {}, 1),
    ]
    return [
        {
            "scenario_id": scenario_id,
            "input": {"branch_selections": branches, "max_steps": maximum, "observations": observations},
            "result": simulate_bounded(flow, observations, branches, maximum),
        }
        for scenario_id, observations, branches, maximum in scenarios
    ]


def projection(root: Path, fixture_path: str) -> dict:
    suite = parse_json_bytes(safe_fixture(root, fixture_path).read_bytes())
    fixtures = []
    for case in suite["cases"]:
        value = materialize(case, suite)
        summary = None
        queries = []
        simulations = []
        if value["mode"] == "revision":
            actual = validate_revision_transition(value["previous"], value["candidate"])
        else:
            actual = validate_graph(value["flow"])
            if actual["object_result"] == "valid" and value["mode"] == "reference":
                actual = validate_references(value["flow"], value["snapshot"])
            if actual["object_result"] == "valid":
                summary = graph_summary(value["flow"])
                queries = query_projection(value["flow"])
                simulations = simulation_projection(value["flow"])
        fixtures.append({
            "case_id": case["case_id"], "actual": actual, "expected": case["expected"],
            "summary": summary, "queries": queries, "simulations": simulations,
        })
    return {"contract_version": suite["contract_version"], "fixtures": fixtures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--fixture-path", default="fixtures/cases.json")
    args = parser.parse_args()
    print(json.dumps(projection(args.contract_root, args.fixture_path), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())