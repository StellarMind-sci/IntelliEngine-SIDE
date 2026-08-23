from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COGNITIVE_IR_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
TOOLS_ROOT = Path(__file__).resolve().parent
for path in (COGNITIVE_IR_PYTHON, TOOLS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from intelliengine_conformance.json_codec import canonicalize, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid
from graph_validation import issue, ref_key, result, sorted_unique, validate_flow

JsonObject = dict[str, Any]


def _load(path: Path) -> Any:
    return parse_json_bytes(path.read_bytes())


def _walk_pointer(document: Any, pointer: str) -> tuple[Any, str | int]:
    if not pointer.startswith("/"):
        raise ValueError("mutation path must be a JSON Pointer")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current, int(parts[-1]) if isinstance(current, list) else parts[-1]


def _apply_mutation(document: Any, mutation: JsonObject) -> Any:
    value = copy.deepcopy(document)
    parent, leaf = _walk_pointer(value, mutation["path"])
    kind = mutation["kind"]
    if kind == "replace":
        parent[leaf] = copy.deepcopy(mutation["value"])
    elif kind == "remove":
        del parent[leaf]
    elif kind == "reverse":
        parent[leaf] = list(reversed(parent[leaf]))
    elif kind == "append":
        parent[leaf].append(copy.deepcopy(mutation["value"]))
    else:
        raise ValueError(f"unsupported fixture mutation: {kind}")
    return value


def _materialize_input(case: JsonObject, root: Path) -> JsonObject:
    value = case["input"]
    if value.get("mode") == "revision" and "base_case_id" in value:
        suite = _load(root / "fixtures" / "cases.json")
        base_case = next(item for item in suite["cases"] if item["case_id"] == value["base_case_id"])
        base = _materialize_input(base_case, root)
        previous = copy.deepcopy(base["flow"])
        candidate_root = copy.deepcopy(base)
        for mutation in value["candidate_mutations"]:
            candidate_root = _apply_mutation(candidate_root, mutation)
        return {"mode": "revision", "previous": previous, "candidate": candidate_root["flow"]}
    if "base_case_id" in value:
        suite = _load(root / "fixtures" / "cases.json")
        base_case = next(item for item in suite["cases"] if item["case_id"] == value["base_case_id"])
        return _apply_mutation(_materialize_input(base_case, root), value["mutation"])
    return copy.deepcopy(value)


def materialize(case: JsonObject, root: Path) -> tuple[JsonObject, JsonObject]:
    value = _materialize_input(case, root)
    return value["flow"], value.get("snapshot", {"cognitive_nodes": [], "knowledge_units": []})


def validate_raw(raw: bytes, root: Path) -> JsonObject:
    try:
        flow = parse_json_bytes(raw)
    except Exception:
        return result(False, issue("thoughtflow.invalid_json", ""))
    schema = _load(root / "schemas" / "thoughtflow.schema.json")
    return validate_flow(flow, schema, is_valid)


def _snapshot_map(entries: Any) -> dict[tuple[bytes, int], JsonObject] | None:
    if not sorted_unique(entries, lambda entry: ref_key(entry.get("ref")) if isinstance(entry, dict) else None):
        return None
    return {ref_key(entry["ref"]): entry for entry in entries}


def _indeterminate(code: str, path: str) -> JsonObject:
    return {"object_result": "not_evaluated", "operation_outcome": "indeterminate", "issues": [issue(code, path)]}


def validate_reference_snapshot(flow: Any, snapshot: Any, schema: Any | None = None) -> JsonObject:
    graph_result = validate_flow(flow, schema, is_valid if schema is not None else None)
    if graph_result["object_result"] != "valid":
        return graph_result
    if not isinstance(snapshot, dict):
        return _indeterminate("thoughtflow.reference_snapshot_incomplete", "")
    cognitive = _snapshot_map(snapshot.get("cognitive_nodes"))
    knowledge = _snapshot_map(snapshot.get("knowledge_units"))
    if cognitive is None or knowledge is None:
        return _indeterminate("thoughtflow.reference_snapshot_incomplete", "")

    for index, reference in enumerate(flow["cognitive_node_refs"]):
        entry = cognitive.get(ref_key(reference))
        path = f"/cognitive_node_refs/{index}"
        if entry is None:
            return _indeterminate("thoughtflow.reference_snapshot_incomplete", path)
        state = entry.get("object_result")
        if state == "invalid":
            return result(False, issue("thoughtflow.dangling_reference", path))
        if state in {"opaque", "compatible_read"}:
            return _indeterminate("thoughtflow.opaque_reference", path)
        if state != "available":
            return _indeterminate("thoughtflow.reference_snapshot_incomplete", path)

    for index, reference in enumerate(flow["knowledge_unit_refs"]):
        entry = knowledge.get(ref_key(reference))
        path = f"/knowledge_unit_refs/{index}"
        if entry is None:
            return _indeterminate("thoughtflow.reference_snapshot_incomplete", path)
        state = entry.get("object_result")
        if state == "invalid":
            return result(False, issue("thoughtflow.dangling_reference", path))
        if state in {"opaque", "compatible_read"}:
            return _indeterminate("thoughtflow.opaque_reference", path)
        document = entry.get("document")
        if state != "available" or not isinstance(document, dict) or ref_key({"id": document.get("id"), "revision": document.get("revision")}) != ref_key(reference):
            return result(False, issue("thoughtflow.dangling_reference", path))

    knowledge_by_ref = knowledge
    for step_index, step in enumerate(flow["steps"]):
        if step.get("kind") != "operation":
            continue
        behavior_ref = step["behavior_ref"]
        entry = knowledge_by_ref[ref_key(behavior_ref["knowledge_unit_ref"])]
        behaviors = entry["document"].get("behaviors", [])
        behavior = next((item for item in behaviors if isinstance(item, dict) and item.get("behavior_id") == behavior_ref["behavior_id"]), None)
        if behavior is None:
            return result(False, issue("thoughtflow.unknown_behavior", f"/steps/{step_index}/behavior_ref"))
        required = {ref_key(item) for item in behavior.get("input_node_refs", []) + behavior.get("output_node_refs", [])}
        actual = {ref_key(item) for item in step["cognitive_node_refs"]}
        if None in required or not required.issubset(actual):
            return result(False, issue("thoughtflow.behavior_node_coverage", f"/steps/{step_index}/cognitive_node_refs"))
    return result(True)


def validate_revision_transition(previous: Any, candidate: Any) -> JsonObject:
    if not isinstance(previous, dict) or not isinstance(candidate, dict):
        return result(False, issue("thoughtflow.invalid_json", ""))
    if previous.get("id") != candidate.get("id"):
        return result(False, issue("thoughtflow.revision_identity_mismatch", "/id"))
    old_revision, new_revision = previous.get("revision"), candidate.get("revision")
    if isinstance(old_revision, bool) or isinstance(new_revision, bool) or not isinstance(old_revision, int) or not isinstance(new_revision, int):
        return result(False, issue("thoughtflow.invalid_revision", "/revision"))
    if new_revision <= old_revision:
        return result(False, issue("thoughtflow.revision_not_increased", "/revision"))
    old_content, new_content = copy.deepcopy(previous), copy.deepcopy(candidate)
    old_content.pop("revision", None)
    new_content.pop("revision", None)
    if old_content == new_content:
        return result(False, issue("thoughtflow.revision_without_change", "/revision"))
    for field, identifier in (("steps", "step_id"), ("transitions", "transition_id")):
        old_items = previous.get(field, [])
        new_by_id = {item.get(identifier): item for item in candidate.get(field, []) if isinstance(item, dict)}
        for index, item in enumerate(old_items):
            if new_by_id.get(item.get(identifier)) != item:
                return result(False, issue("thoughtflow.history_rewrite", f"/{field}/{index}"))
    return result(True)


def validate_case(case: JsonObject, root: Path) -> JsonObject:
    value = _materialize_input(case, root)
    mode = value.get("mode")
    if mode == "revision":
        return validate_revision_transition(value.get("previous"), value.get("candidate"))
    schema = _load(root / "schemas" / "thoughtflow.schema.json")
    graph_result = validate_flow(value.get("flow"), schema, is_valid)
    if graph_result["object_result"] != "valid" or mode == "graph":
        return graph_result
    if mode == "reference":
        return validate_reference_snapshot(value["flow"], value.get("snapshot"), schema)
    return result(False, issue("thoughtflow.invalid_json", "/mode"))


def _verify_lock(root: Path) -> None:
    lock = _load(root / "lock.json")
    entries = lock.get("entries") if isinstance(lock, dict) else None
    if not isinstance(entries, list):
        raise ValueError("invalid lock")
    actual_paths = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.json") if path.relative_to(root).as_posix() != "lock.json")
    declared_paths = [entry.get("path") for entry in entries]
    if declared_paths != actual_paths:
        raise ValueError("lock closure mismatch")
    for entry in entries:
        if entry.get("digest_kind") != "jcs_sha256":
            raise ValueError("unsupported digest kind")
        digest = hashlib.sha256(canonicalize(_load(root / entry["path"]))).hexdigest()
        if digest != entry.get("sha256"):
            raise ValueError(f"digest mismatch: {entry['path']}")


def verify_contract(root: Path) -> JsonObject:
    root = root.resolve()
    contract = _load(root / "contract.json")
    if contract.get("contract_family") != "thoughtflow" or contract.get("contract_version") != "1.0.0" or contract.get("side_effects") != "forbidden":
        raise ValueError("invalid contract manifest")
    catalog = _load(root / "diagnostics" / "thoughtflow.json")
    codes = set(catalog.get("codes", []))
    suite = _load(root / "fixtures" / "cases.json")
    fixture_schema = _load(root / "schemas" / "fixture-suite.schema.json")
    result_schema = _load(root / "schemas" / "validation-result.schema.json")
    if not is_valid(suite, fixture_schema, fixture_schema):
        raise ValueError("fixture suite does not match its machine schema")
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list) or len(cases) != 18:
        raise ValueError("fixture suite must contain eighteen cases")
    case_ids = [case.get("case_id") for case in cases]
    if any(not isinstance(case_id, str) for case_id in case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case IDs are invalid or duplicated")
    for case in cases:
        if not is_valid(case.get("expected"), result_schema, result_schema):
            raise ValueError(f"fixture expected result is invalid: {case['case_id']}")
        computed = validate_case(case, root)
        if computed != case.get("expected"):
            raise ValueError(f"fixture result mismatch: {case['case_id']}: {computed!r}")
        if any(item["code"] not in codes for item in computed["issues"]):
            raise ValueError(f"unknown diagnostic: {case['case_id']}")
    _verify_lock(root)
    return {"case_count": len(cases), "contract_version": contract["contract_version"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "thoughtflow" / "1.0.0")
    args = parser.parse_args()
    print(json.dumps(verify_contract(args.root), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
