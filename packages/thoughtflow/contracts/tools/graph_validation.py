from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

JsonObject = dict[str, Any]
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SAFE_INTEGER = 9007199254740991
CONTROL_KINDS = {"sequence", "branch", "verification_feedback"}


def issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "error"}


def result(valid: bool, diagnostic: JsonObject | None = None) -> JsonObject:
    return {"object_result": "valid" if valid else "invalid", "operation_outcome": "succeeded", "issues": [] if diagnostic is None else [diagnostic]}


def ref_key(value: Any) -> tuple[bytes, int] | None:
    if not isinstance(value, dict) or set(value) != {"id", "revision"}:
        return None
    identifier, revision = value.get("id"), value.get("revision")
    if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
        return None
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= SAFE_INTEGER:
        return None
    return identifier.encode("utf-8"), revision


def sorted_unique(values: Any, key) -> bool:
    if not isinstance(values, list):
        return False
    keys = [key(value) for value in values]
    return all(item is not None for item in keys) and len(keys) == len(set(keys)) and keys == sorted(keys)


def transition_key(value: Any):
    if not isinstance(value, dict):
        return None
    fields = [value.get("from_step_id"), value.get("kind"), value.get("branch_label", value.get("outcome", "")), value.get("to_step_id"), value.get("transition_id")]
    if not all(isinstance(item, str) for item in fields):
        return None
    return tuple(item.encode("utf-8") for item in fields)


def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency.get(current, []))
    return seen


def _has_cycle(nodes: list[str], adjacency: dict[str, list[str]], indegree: dict[str, int]) -> bool:
    counts = dict(indegree)
    pending = deque(node for node in nodes if counts.get(node, 0) == 0)
    visited = 0
    while pending:
        current = pending.popleft()
        visited += 1
        for target in adjacency.get(current, []):
            counts[target] = counts.get(target, 0) - 1
            if counts[target] == 0:
                pending.append(target)
    return visited != len(nodes)


def _step_refs(step: JsonObject, field: str) -> list[tuple[bytes, int]] | None:
    values = step.get(field)
    if not sorted_unique(values, ref_key):
        return None
    return [ref_key(value) for value in values]


def validate_flow(flow: Any, schema: Any | None = None, schema_validator=None) -> JsonObject:
    if not isinstance(flow, dict):
        return result(False, issue("thoughtflow.invalid_json", ""))
    version = flow.get("contract_version")
    if not isinstance(version, str) or not version.startswith("1."):
        return result(False, issue("thoughtflow.unsupported_contract_version", "/contract_version"))
    if not isinstance(flow.get("id"), str) or UUID.fullmatch(flow["id"]) is None:
        return result(False, issue("thoughtflow.invalid_json", "/id"))
    revision = flow.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= SAFE_INTEGER:
        return result(False, issue("thoughtflow.invalid_revision", "/revision"))
    if schema is not None and schema_validator is not None and not schema_validator(flow, schema, schema):
        return result(False, issue("thoughtflow.invalid_json", ""))

    steps = flow.get("steps")
    if not sorted_unique(steps, lambda item: item.get("step_id", "").encode("utf-8") if isinstance(item, dict) and isinstance(item.get("step_id"), str) and item.get("step_id") else None):
        return result(False, issue("thoughtflow.noncanonical_set", "/steps"))
    transitions = flow.get("transitions")
    if not sorted_unique(transitions, transition_key):
        return result(False, issue("thoughtflow.noncanonical_set", "/transitions"))
    if not sorted_unique(flow.get("knowledge_unit_refs"), ref_key):
        return result(False, issue("thoughtflow.noncanonical_set", "/knowledge_unit_refs"))
    if not sorted_unique(flow.get("cognitive_node_refs"), ref_key):
        return result(False, issue("thoughtflow.noncanonical_set", "/cognitive_node_refs"))
    if not sorted_unique(flow.get("provenance_refs"), lambda value: value.encode("utf-8") if isinstance(value, str) and value else None):
        return result(False, issue("thoughtflow.noncanonical_set", "/provenance_refs"))

    step_by_id = {step["step_id"]: step for step in steps}
    if flow.get("entry_step_id") not in step_by_id:
        return result(False, issue("thoughtflow.dangling_step", "/entry_step_id"))
    if not any(step.get("kind") == "goal" for step in steps) or not any(step.get("kind") == "verification" for step in steps):
        return result(False, issue("thoughtflow.invalid_step", "/steps"))

    used_knowledge: set[tuple[bytes, int]] = set()
    used_nodes: set[tuple[bytes, int]] = set()
    for index, step in enumerate(steps):
        common = {"step_id", "kind", "title", "description", "knowledge_unit_refs", "cognitive_node_refs"}
        expected_fields = {
            "goal": common | {"success_statement"},
            "analysis": common,
            "operation": common | {"behavior_ref"},
            "decision": common,
            "verification": common | {"acceptance_statement", "evidence_node_refs"},
            "artifact": common | {"artifact_key"},
            "iteration": common | {"max_iterations", "exit_condition", "verification_step_ids"},
        }.get(step.get("kind"))
        if expected_fields is None or set(step) != expected_fields:
            return result(False, issue("thoughtflow.invalid_step", f"/steps/{index}"))

        knowledge = _step_refs(step, "knowledge_unit_refs")
        nodes = _step_refs(step, "cognitive_node_refs")
        if knowledge is None or nodes is None:
            return result(False, issue("thoughtflow.noncanonical_set", f"/steps/{index}"))
        used_knowledge.update(knowledge)
        used_nodes.update(nodes)
        kind = step.get("kind")
        if kind == "goal" and not step.get("success_statement"):
            return result(False, issue("thoughtflow.invalid_step", f"/steps/{index}/success_statement"))
        if kind == "operation":
            behavior = step.get("behavior_ref")
            if not isinstance(behavior, dict) or ref_key(behavior.get("knowledge_unit_ref")) is None or not isinstance(behavior.get("behavior_id"), str) or not behavior["behavior_id"]:
                return result(False, issue("thoughtflow.invalid_step", f"/steps/{index}/behavior_ref"))
            used_knowledge.add(ref_key(behavior["knowledge_unit_ref"]))
        if kind == "verification":
            evidence = step.get("evidence_node_refs")
            if not step.get("acceptance_statement") or not sorted_unique(evidence, ref_key) or not evidence:
                return result(False, issue("thoughtflow.invalid_step", f"/steps/{index}"))
            evidence_keys = {ref_key(value) for value in evidence}
            if not evidence_keys.issubset(set(nodes)):
                return result(False, issue("thoughtflow.reference_closure_mismatch", f"/steps/{index}/evidence_node_refs"))
            used_nodes.update(evidence_keys)
        if kind == "artifact" and not step.get("artifact_key"):
            return result(False, issue("thoughtflow.invalid_step", f"/steps/{index}/artifact_key"))
        if kind == "iteration":
            maximum = step.get("max_iterations")
            verification_ids = step.get("verification_step_ids")
            if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 10000 or not step.get("exit_condition"):
                return result(False, issue("thoughtflow.invalid_loop", f"/steps/{index}"))
            if not isinstance(verification_ids, list) or not verification_ids or len(verification_ids) != len(set(verification_ids)) or verification_ids != sorted(verification_ids, key=lambda value: value.encode("utf-8")):
                return result(False, issue("thoughtflow.invalid_loop", f"/steps/{index}/verification_step_ids"))
            if any(value not in step_by_id or step_by_id[value].get("kind") != "verification" for value in verification_ids):
                return result(False, issue("thoughtflow.dangling_step", f"/steps/{index}/verification_step_ids"))

    top_knowledge = {ref_key(value) for value in flow["knowledge_unit_refs"]}
    top_nodes = {ref_key(value) for value in flow["cognitive_node_refs"]}
    if top_knowledge != used_knowledge:
        return result(False, issue("thoughtflow.reference_closure_mismatch", "/knowledge_unit_refs"))
    if top_nodes != used_nodes:
        return result(False, issue("thoughtflow.reference_closure_mismatch", "/cognitive_node_refs"))

    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    indegree = {step_id: 0 for step_id in step_by_id}
    outgoing: dict[str, list[tuple[int, JsonObject]]] = defaultdict(list)
    for index, transition in enumerate(transitions):
        common = {"transition_id", "kind", "from_step_id", "to_step_id"}
        expected_fields = {
            "sequence": common,
            "data_dependency": common,
            "branch": common | {"branch_label", "condition_statement", "is_default"},
            "verification_feedback": common | {"outcome"},
            "loop": common | {"outcome"},
        }.get(transition.get("kind"))
        if expected_fields is None or set(transition) != expected_fields:
            return result(False, issue("thoughtflow.invalid_transition", f"/transitions/{index}"))

        source, target = transition.get("from_step_id"), transition.get("to_step_id")
        if source not in step_by_id:
            return result(False, issue("thoughtflow.dangling_step", f"/transitions/{index}/from_step_id"))
        if target not in step_by_id:
            return result(False, issue("thoughtflow.dangling_step", f"/transitions/{index}/to_step_id"))
        if source == target:
            return result(False, issue("thoughtflow.invalid_transition", f"/transitions/{index}"))
        outgoing[source].append((index, transition))
        if transition.get("kind") in CONTROL_KINDS:
            adjacency[source].append(target)
            reverse[target].append(source)
            indegree[target] += 1

    node_ids = list(step_by_id)
    if _has_cycle(node_ids, adjacency, indegree):
        return result(False, issue("thoughtflow.unconstrained_cycle", "/transitions"))
    reachable = _reachable(flow["entry_step_id"], adjacency)
    for index, step in enumerate(steps):
        if step["step_id"] not in reachable:
            return result(False, issue("thoughtflow.unreachable_step", f"/steps/{index}"))
    roots = [node for node in node_ids if indegree[node] == 0]
    if roots != [flow["entry_step_id"]]:
        return result(False, issue("thoughtflow.invalid_transition", "/entry_step_id"))

    for index, step in enumerate(steps):
        controls = [(i, item) for i, item in outgoing.get(step["step_id"], []) if item.get("kind") != "data_dependency"]
        kind = step.get("kind")
        if kind in {"decision", "iteration"}:
            branches = [item for _, item in controls if item.get("kind") == "branch"]
            labels = [item.get("branch_label") for item in branches]
            if len(branches) < 2 or len(branches) != len(controls) or any(not isinstance(label, str) or not label for label in labels) or len(labels) != len(set(labels)) or sum(item.get("is_default") is True for item in branches) != 1 or any(not item.get("condition_statement") for item in branches):
                return result(False, issue("thoughtflow.invalid_branch_set", f"/steps/{index}"))
        elif kind == "verification":
            feedback = [item for _, item in controls if item.get("kind") == "verification_feedback"]
            loops = [(i, item) for i, item in controls if item.get("kind") == "loop"]
            if not feedback or len(feedback) + len(loops) != len(controls):
                return result(False, issue("thoughtflow.invalid_transition", f"/steps/{index}"))
            for transition_index, loop in loops:
                target = step_by_id[loop["to_step_id"]]
                if loop.get("outcome") not in {"failed", "needs_evidence"}:
                    return result(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}/outcome"))
                if target.get("kind") != "iteration" or step["step_id"] not in target.get("verification_step_ids", []):
                    return result(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}"))
                if loop["from_step_id"] not in _reachable(loop["to_step_id"], adjacency):
                    return result(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}"))
                component = _reachable(loop["to_step_id"], adjacency) & _reachable(loop["from_step_id"], reverse)
                if sum(step_by_id[item].get("kind") == "iteration" for item in component) != 1 or not any(step_by_id[item].get("kind") == "verification" for item in component):
                    return result(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}"))
            outcomes = [item.get("outcome") for item in feedback] + [item.get("outcome") for _, item in loops]
            if len(outcomes) != len(set(outcomes)):
                return result(False, issue("thoughtflow.duplicate_outcome", f"/steps/{index}"))
        elif any(item.get("kind") in {"branch", "verification_feedback", "loop"} for _, item in controls):
            return result(False, issue("thoughtflow.invalid_transition", f"/steps/{index}"))

    return result(True)
