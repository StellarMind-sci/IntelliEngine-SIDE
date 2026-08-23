from __future__ import annotations

import copy
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

COGNITIVE_IR_PYTHON = Path(__file__).resolve().parents[3] / "cognitive-ir" / "python"
if str(COGNITIVE_IR_PYTHON) not in sys.path:
    sys.path.insert(0, str(COGNITIVE_IR_PYTHON))

from intelliengine_conformance.json_codec import canonicalize

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
CONTROL = {"sequence", "branch", "verification_feedback"}
CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "thoughtflow" / "1.0.0"
FLOW_SCHEMA = json.loads((CONTRACT_ROOT / "schemas" / "thoughtflow.schema.json").read_text(encoding="utf-8"))
MAX_JCS_BYTES = 4194304


def _schema_valid(value: Any, schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    declared = schema.get("type")
    if declared == "object" and not isinstance(value, dict):
        return False
    if declared == "array" and not isinstance(value, list):
        return False
    if declared == "string" and not isinstance(value, str):
        return False
    if declared == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            return False
        if "items" in schema and any(not _schema_valid(item, schema["items"]) for item in value):
            return False
    if isinstance(value, dict):
        if any(name not in value for name in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        for name, item in value.items():
            if name in properties:
                if not _schema_valid(item, properties[name]):
                    return False
            elif schema.get("additionalProperties") is False:
                return False
    if "oneOf" in schema and sum(_schema_valid(value, child) for child in schema["oneOf"]) != 1:
        return False
    return True


def _within_size_limit(value: Any) -> bool:
    try:
        encoded = canonicalize(value)
    except (TypeError, UnicodeEncodeError, ValueError):
        return False
    return len(encoded) <= MAX_JCS_BYTES


def issue(code: str, path: str) -> dict:
    return {"code": code, "path": path, "severity": "error"}


def verdict(valid: bool, diagnostic: dict | None = None) -> dict:
    return {"object_result": "valid" if valid else "invalid", "operation_outcome": "succeeded", "issues": [] if diagnostic is None else [diagnostic]}


def indeterminate(code: str, path: str) -> dict:
    return {"object_result": "not_evaluated", "operation_outcome": "indeterminate", "issues": [issue(code, path)]}


def ref_key(value: Any):
    if not isinstance(value, dict) or set(value) != {"id", "revision"}:
        return None
    if not isinstance(value["id"], str) or UUID.fullmatch(value["id"]) is None:
        return None
    revision = value["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= 9007199254740991:
        return None
    return value["id"].encode(), revision


def ordered(values: Any, key) -> bool:
    if not isinstance(values, list):
        return False
    keys = [key(value) for value in values]
    return all(value is not None for value in keys) and len(keys) == len(set(keys)) and keys == sorted(keys)


def transition_key(value: Any):
    if not isinstance(value, dict):
        return None
    parts = [value.get("from_step_id"), value.get("kind"), value.get("branch_label", value.get("outcome", "")), value.get("to_step_id"), value.get("transition_id")]
    return tuple(part.encode() for part in parts) if all(isinstance(part, str) for part in parts) else None


def reachable(start: str, edges: dict[str, list[str]]) -> set[str]:
    seen, pending = set(), [start]
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(edges.get(current, []))
    return seen


def validate_graph(flow: Any) -> dict:
    if not isinstance(flow, dict):
        return verdict(False, issue("thoughtflow.invalid_json", ""))
    if not isinstance(flow.get("contract_version"), str) or not flow["contract_version"].startswith("1."):
        return verdict(False, issue("thoughtflow.unsupported_contract_version", "/contract_version"))
    if not isinstance(flow.get("id"), str) or UUID.fullmatch(flow["id"]) is None:
        return verdict(False, issue("thoughtflow.invalid_json", "/id"))
    if isinstance(flow.get("revision"), bool) or not isinstance(flow.get("revision"), int) or flow["revision"] < 1:
        return verdict(False, issue("thoughtflow.invalid_revision", "/revision"))
    if not _schema_valid(flow, FLOW_SCHEMA) or not _within_size_limit(flow):
        return verdict(False, issue("thoughtflow.invalid_json", ""))
    steps, transitions = flow.get("steps"), flow.get("transitions")
    if not ordered(steps, lambda x: x.get("step_id", "").encode() if isinstance(x, dict) and x.get("step_id") else None):
        return verdict(False, issue("thoughtflow.noncanonical_set", "/steps"))
    if not ordered(transitions, transition_key):
        return verdict(False, issue("thoughtflow.noncanonical_set", "/transitions"))
    if not ordered(flow.get("knowledge_unit_refs"), ref_key):
        return verdict(False, issue("thoughtflow.noncanonical_set", "/knowledge_unit_refs"))
    if not ordered(flow.get("cognitive_node_refs"), ref_key):
        return verdict(False, issue("thoughtflow.noncanonical_set", "/cognitive_node_refs"))
    if not ordered(flow.get("provenance_refs"), lambda x: x.encode() if isinstance(x, str) and x else None):
        return verdict(False, issue("thoughtflow.noncanonical_set", "/provenance_refs"))
    by_id = {step["step_id"]: step for step in steps}
    if flow.get("entry_step_id") not in by_id:
        return verdict(False, issue("thoughtflow.dangling_step", "/entry_step_id"))
    if not any(step["kind"] == "goal" for step in steps) or not any(step["kind"] == "verification" for step in steps):
        return verdict(False, issue("thoughtflow.invalid_step", "/steps"))

    used_ku, used_cn = set(), set()
    base_step = {"step_id", "kind", "title", "description", "knowledge_unit_refs", "cognitive_node_refs"}
    extras = {"goal": {"success_statement"}, "analysis": set(), "operation": {"behavior_ref"}, "decision": set(), "verification": {"acceptance_statement", "evidence_node_refs"}, "artifact": {"artifact_key"}, "iteration": {"max_iterations", "exit_condition", "verification_step_ids"}}
    for index, step in enumerate(steps):
        expected = extras.get(step.get("kind"))
        if expected is None or set(step) != base_step | expected:
            return verdict(False, issue("thoughtflow.invalid_step", f"/steps/{index}"))
        if not ordered(step["knowledge_unit_refs"], ref_key) or not ordered(step["cognitive_node_refs"], ref_key):
            return verdict(False, issue("thoughtflow.noncanonical_set", f"/steps/{index}"))
        used_ku.update(ref_key(value) for value in step["knowledge_unit_refs"])
        used_cn.update(ref_key(value) for value in step["cognitive_node_refs"])
        kind = step["kind"]
        if kind == "operation":
            behavior = step["behavior_ref"]
            if not isinstance(behavior, dict) or ref_key(behavior.get("knowledge_unit_ref")) is None or not behavior.get("behavior_id"):
                return verdict(False, issue("thoughtflow.invalid_step", f"/steps/{index}/behavior_ref"))
            used_ku.add(ref_key(behavior["knowledge_unit_ref"]))
        if kind == "verification":
            if not step["acceptance_statement"] or not ordered(step["evidence_node_refs"], ref_key) or not step["evidence_node_refs"]:
                return verdict(False, issue("thoughtflow.invalid_step", f"/steps/{index}"))
            evidence = {ref_key(value) for value in step["evidence_node_refs"]}
            if not evidence.issubset({ref_key(value) for value in step["cognitive_node_refs"]}):
                return verdict(False, issue("thoughtflow.reference_closure_mismatch", f"/steps/{index}/evidence_node_refs"))
            used_cn.update(evidence)
        if kind == "iteration":
            maximum = step["max_iterations"]
            if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 10000 or not step["exit_condition"]:
                return verdict(False, issue("thoughtflow.invalid_loop", f"/steps/{index}"))
            verification_ids = step["verification_step_ids"]
            if not verification_ids or len(verification_ids) != len(set(verification_ids)) or verification_ids != sorted(verification_ids, key=lambda value: value.encode("utf-8")):
                return verdict(False, issue("thoughtflow.invalid_loop", f"/steps/{index}/verification_step_ids"))
            if any(value not in by_id or by_id[value]["kind"] != "verification" for value in verification_ids):
                return verdict(False, issue("thoughtflow.dangling_step", f"/steps/{index}/verification_step_ids"))
    if {ref_key(value) for value in flow["knowledge_unit_refs"]} != used_ku:
        return verdict(False, issue("thoughtflow.reference_closure_mismatch", "/knowledge_unit_refs"))
    if {ref_key(value) for value in flow["cognitive_node_refs"]} != used_cn:
        return verdict(False, issue("thoughtflow.reference_closure_mismatch", "/cognitive_node_refs"))

    edges, reverse, indegree, outgoing = defaultdict(list), defaultdict(list), {key: 0 for key in by_id}, defaultdict(list)
    common = {"transition_id", "kind", "from_step_id", "to_step_id"}
    fields = {"sequence": common, "data_dependency": common, "branch": common | {"branch_label", "condition_statement", "is_default"}, "verification_feedback": common | {"outcome"}, "loop": common | {"outcome"}}
    for index, transition in enumerate(transitions):
        if set(transition) != fields.get(transition.get("kind"), set()):
            return verdict(False, issue("thoughtflow.invalid_transition", f"/transitions/{index}"))
        source, target = transition["from_step_id"], transition["to_step_id"]
        if source not in by_id or target not in by_id:
            field = "from_step_id" if source not in by_id else "to_step_id"
            return verdict(False, issue("thoughtflow.dangling_step", f"/transitions/{index}/{field}"))
        if source == target:
            return verdict(False, issue("thoughtflow.invalid_transition", f"/transitions/{index}"))
        outgoing[source].append((index, transition))
        if transition["kind"] in CONTROL:
            edges[source].append(target); reverse[target].append(source); indegree[target] += 1

    counts, queue, visited = dict(indegree), deque(key for key, value in indegree.items() if value == 0), 0
    while queue:
        current = queue.popleft(); visited += 1
        for target in edges[current]:
            counts[target] -= 1
            if counts[target] == 0: queue.append(target)
    if visited != len(by_id):
        return verdict(False, issue("thoughtflow.unconstrained_cycle", "/transitions"))
    seen = reachable(flow["entry_step_id"], edges)
    for index, step in enumerate(steps):
        if step["step_id"] not in seen:
            return verdict(False, issue("thoughtflow.unreachable_step", f"/steps/{index}"))
    roots = [step_id for step_id in by_id if indegree[step_id] == 0]
    if roots != [flow["entry_step_id"]]:
        return verdict(False, issue("thoughtflow.invalid_transition", "/entry_step_id"))

    for index, step in enumerate(steps):
        controls = [(i, item) for i, item in outgoing[step["step_id"]] if item["kind"] != "data_dependency"]
        if step["kind"] in {"decision", "iteration"}:
            branches = [item for _, item in controls if item["kind"] == "branch"]
            labels = [item.get("branch_label") for item in branches]
            if len(branches) < 2 or len(branches) != len(controls) or len(labels) != len(set(labels)) or sum(item.get("is_default") is True for item in branches) != 1 or any(not item.get("condition_statement") for item in branches):
                return verdict(False, issue("thoughtflow.invalid_branch_set", f"/steps/{index}"))
        elif step["kind"] == "verification":
            feedback = [item for _, item in controls if item["kind"] == "verification_feedback"]
            loops = [(i, item) for i, item in controls if item["kind"] == "loop"]
            if not feedback or len(feedback) + len(loops) != len(controls):
                return verdict(False, issue("thoughtflow.invalid_transition", f"/steps/{index}"))
            for transition_index, loop in loops:
                target = by_id[loop["to_step_id"]]
                if loop["outcome"] not in {"failed", "needs_evidence"} or target["kind"] != "iteration" or step["step_id"] not in target["verification_step_ids"] or loop["from_step_id"] not in reachable(loop["to_step_id"], edges):
                    return verdict(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}" + ("/outcome" if loop["outcome"] not in {"failed", "needs_evidence"} else "")))
                component = reachable(loop["to_step_id"], edges) & reachable(loop["from_step_id"], reverse)
                if sum(by_id[item]["kind"] == "iteration" for item in component) != 1 or not any(by_id[item]["kind"] == "verification" for item in component):
                    return verdict(False, issue("thoughtflow.invalid_loop", f"/transitions/{transition_index}"))
            outcomes = [item["outcome"] for item in feedback] + [item["outcome"] for _, item in loops]
            if len(outcomes) != len(set(outcomes)):
                return verdict(False, issue("thoughtflow.duplicate_outcome", f"/steps/{index}"))
        elif any(item["kind"] in {"branch", "verification_feedback", "loop"} for _, item in controls):
            return verdict(False, issue("thoughtflow.invalid_transition", f"/steps/{index}"))
    return verdict(True)


def validate_references(flow: dict, snapshot: Any) -> dict:
    graph = validate_graph(flow)
    if graph["object_result"] != "valid": return graph
    if not isinstance(snapshot, dict): return indeterminate("thoughtflow.reference_snapshot_incomplete", "")
    def mapping(name):
        entries = snapshot.get(name)
        if not ordered(entries, lambda x: ref_key(x.get("ref")) if isinstance(x, dict) else None): return None
        return {ref_key(entry["ref"]): entry for entry in entries}
    cognitive, knowledge = mapping("cognitive_nodes"), mapping("knowledge_units")
    if cognitive is None or knowledge is None: return indeterminate("thoughtflow.reference_snapshot_incomplete", "")
    for field, entries, table in (("cognitive_node_refs", flow["cognitive_node_refs"], cognitive), ("knowledge_unit_refs", flow["knowledge_unit_refs"], knowledge)):
        for index, reference in enumerate(entries):
            item, path = table.get(ref_key(reference)), f"/{field}/{index}"
            if item is None: return indeterminate("thoughtflow.reference_snapshot_incomplete", path)
            if item.get("object_result") == "invalid": return verdict(False, issue("thoughtflow.dangling_reference", path))
            if item.get("object_result") in {"opaque", "compatible_read"}: return indeterminate("thoughtflow.opaque_reference", path)
            if item.get("object_result") != "available": return indeterminate("thoughtflow.reference_snapshot_incomplete", path)
    for index, step in enumerate(flow["steps"]):
        if step["kind"] != "operation": continue
        entry = knowledge[ref_key(step["behavior_ref"]["knowledge_unit_ref"])]
        behavior = next((x for x in entry.get("document", {}).get("behaviors", []) if x.get("behavior_id") == step["behavior_ref"]["behavior_id"]), None)
        if behavior is None: return verdict(False, issue("thoughtflow.unknown_behavior", f"/steps/{index}/behavior_ref"))
        required = {ref_key(x) for x in behavior.get("input_node_refs", []) + behavior.get("output_node_refs", [])}
        if not required.issubset({ref_key(x) for x in step["cognitive_node_refs"]}):
            return verdict(False, issue("thoughtflow.behavior_node_coverage", f"/steps/{index}/cognitive_node_refs"))
    return verdict(True)


def validate_revision(previous: Any, candidate: Any) -> dict:
    if not isinstance(previous, dict) or not isinstance(candidate, dict): return verdict(False, issue("thoughtflow.invalid_json", ""))
    if previous.get("id") != candidate.get("id"): return verdict(False, issue("thoughtflow.revision_identity_mismatch", "/id"))
    if candidate.get("revision", 0) <= previous.get("revision", 0): return verdict(False, issue("thoughtflow.revision_not_increased", "/revision"))
    old, new = copy.deepcopy(previous), copy.deepcopy(candidate); old.pop("revision", None); new.pop("revision", None)
    if old == new: return verdict(False, issue("thoughtflow.revision_without_change", "/revision"))
    for field, identity in (("steps", "step_id"), ("transitions", "transition_id")):
        table = {x[identity]: x for x in candidate.get(field, [])}
        for index, item in enumerate(previous.get(field, [])):
            if table.get(item[identity]) != item: return verdict(False, issue("thoughtflow.history_rewrite", f"/{field}/{index}"))
    return verdict(True)


def apply_mutation(document: Any, mutation: dict) -> Any:
    value = copy.deepcopy(document); parts = mutation["path"].strip("/").split("/"); parent = value
    for part in parts[:-1]: parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    leaf = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    if mutation["kind"] == "replace": parent[leaf] = copy.deepcopy(mutation["value"])
    elif mutation["kind"] == "remove": del parent[leaf]
    elif mutation["kind"] == "reverse": parent[leaf].reverse()
    elif mutation["kind"] == "append": parent[leaf].append(copy.deepcopy(mutation["value"]))
    return value


def materialize(case: dict, suite: dict) -> dict:
    value = case["input"]
    if value.get("mode") == "revision" and "base_case_id" in value:
        base = materialize(next(x for x in suite["cases"] if x["case_id"] == value["base_case_id"]), suite)
        candidate = copy.deepcopy(base)
        for mutation in value["candidate_mutations"]: candidate = apply_mutation(candidate, mutation)
        return {"mode": "revision", "previous": base["flow"], "candidate": candidate["flow"]}
    if "base_case_id" in value:
        base = materialize(next(x for x in suite["cases"] if x["case_id"] == value["base_case_id"]), suite)
        return apply_mutation(base, value["mutation"])
    return copy.deepcopy(value)
