from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from intelliengine_conformance.json_codec import JsonInputError, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid


JsonObject = dict[str, Any]
SAFE_INTEGER = 9007199254740991
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
CAPABILITIES = {
    "runtime.math.numeric",
    "runtime.math.symbolic",
    "runtime.visualization.2d",
}
REQUIRED = [
    "contract_version", "id", "revision", "title", "concept_boundary",
    "learning_objectives", "node_bindings", "prerequisite_unit_refs",
    "behaviors", "validations", "mastery_criteria", "provenance_refs",
]


def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "error"}


def _result(valid: bool, issue: JsonObject | None = None) -> JsonObject:
    return {
        "object_result": "valid" if valid else "invalid",
        "operation_outcome": "succeeded",
        "issues": [] if issue is None else [issue],
    }


def _ref_key(value: Any) -> tuple[bytes, int] | None:
    if not isinstance(value, dict) or set(value) != {"id", "revision"}:
        return None
    identifier = value.get("id")
    revision = value.get("revision")
    if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None or isinstance(revision, bool) or not isinstance(revision, int):
        return None
    if not 1 <= revision <= SAFE_INTEGER:
        return None
    return identifier.encode("utf-8"), revision


def _sorted_unique(values: Any, key) -> bool:
    if not isinstance(values, list):
        return False
    keys = [key(value) for value in values]
    return all(item is not None for item in keys) and len(keys) == len(set(keys)) and keys == sorted(keys)


def _binding_key(value: Any):
    if not isinstance(value, dict):
        return None
    role = value.get("role")
    ref = _ref_key(value.get("node_ref"))
    return None if not isinstance(role, str) or ref is None else (role.encode("utf-8"), *ref)


def _named_key(field: str):
    return lambda value: value[field].encode("utf-8") if isinstance(value, dict) and isinstance(value.get(field), str) else None


def _collect_refs(unit: JsonObject) -> list[tuple[bytes, int]]:
    values: list[Any] = []
    boundary = unit.get("concept_boundary", {})
    if isinstance(boundary, dict):
        values.extend(boundary.get("focus_node_refs", []))
    for objective in unit.get("learning_objectives", []):
        if isinstance(objective, dict):
            values.extend(objective.get("target_node_refs", []))
    for binding in unit.get("node_bindings", []):
        if isinstance(binding, dict):
            values.append(binding.get("node_ref"))
    for behavior in unit.get("behaviors", []):
        if isinstance(behavior, dict):
            values.extend(behavior.get("input_node_refs", []))
            values.extend(behavior.get("output_node_refs", []))
    for validation in unit.get("validations", []):
        if isinstance(validation, dict):
            values.extend(validation.get("subject_node_refs", []))
            values.extend(validation.get("evidence_node_refs", []))
    for criterion in unit.get("mastery_criteria", []):
        if isinstance(criterion, dict):
            values.extend(criterion.get("evidence_node_refs", []))
    return [key for value in values if (key := _ref_key(value)) is not None]


def validate_unit(unit: Any, available_node_refs: Any, contract_root: Path) -> JsonObject:
    if not isinstance(unit, dict):
        return _result(False, _issue("knowledge_unit.invalid_json", ""))
    missing = next((field for field in REQUIRED if field not in unit), None)
    if missing is not None:
        return _result(False, _issue("knowledge_unit.missing_field", f"/{missing}"))
    if not isinstance(unit["contract_version"], str) or not unit["contract_version"].startswith("1."):
        return _result(False, _issue("knowledge_unit.unsupported_contract_version", "/contract_version"))
    if not isinstance(unit["id"], str) or UUID.fullmatch(unit["id"]) is None:
        return _result(False, _issue("knowledge_unit.invalid_id", "/id"))
    if isinstance(unit["revision"], bool) or not isinstance(unit["revision"], int) or not 1 <= unit["revision"] <= SAFE_INTEGER:
        return _result(False, _issue("knowledge_unit.invalid_revision", "/revision"))
    if not _sorted_unique(unit["node_bindings"], _binding_key):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/node_bindings"))
    if not _sorted_unique(unit["prerequisite_unit_refs"], _ref_key):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/prerequisite_unit_refs"))
    if not _sorted_unique(unit["provenance_refs"], lambda value: value.encode("utf-8") if isinstance(value, str) and value else None):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/provenance_refs"))
    for field, name in (("learning_objectives", "objective_id"), ("behaviors", "behavior_id"), ("validations", "validation_id"), ("mastery_criteria", "criterion_id")):
        if not _sorted_unique(unit[field], _named_key(name)):
            return _result(False, _issue("knowledge_unit.noncanonical_set", f"/{field}"))
    identity = (unit["id"].encode("utf-8"), unit["revision"])
    for index, reference in enumerate(unit["prerequisite_unit_refs"]):
        if _ref_key(reference) == identity:
            return _result(False, _issue("knowledge_unit.self_dependency", f"/prerequisite_unit_refs/{index}"))
    for index, criterion in enumerate(unit["mastery_criteria"]):
        if not isinstance(criterion, dict) or not criterion.get("evidence_node_refs"):
            return _result(False, _issue("knowledge_unit.mastery_without_evidence", f"/mastery_criteria/{index}/evidence_node_refs"))
    for index, behavior in enumerate(unit["behaviors"]):
        if not isinstance(behavior, dict) or behavior.get("capability") not in CAPABILITIES:
            return _result(False, _issue("knowledge_unit.invalid_behavior_capability", f"/behaviors/{index}/capability"))
    if not _sorted_unique(available_node_refs, _ref_key):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/available_node_refs"))
    available = {_ref_key(reference) for reference in available_node_refs}
    refs = _collect_refs(unit)
    if any(reference not in available for reference in refs):
        return _result(False, _issue("knowledge_unit.dangling_node_ref", ""))
    bound = {_ref_key(binding["node_ref"]) for binding in unit["node_bindings"]}
    if any(reference not in bound for reference in refs):
        return _result(False, _issue("knowledge_unit.dangling_node_ref", "/node_bindings"))
    nested_sets: list[tuple[str, Any]] = []
    boundary = unit.get("concept_boundary")
    if isinstance(boundary, dict):
        nested_sets.append(("/concept_boundary/focus_node_refs", boundary.get("focus_node_refs")))
        if not _sorted_unique(boundary.get("out_of_scope_statements"), lambda value: value.encode("utf-8") if isinstance(value, str) and value else None):
            return _result(False, _issue("knowledge_unit.noncanonical_set", "/concept_boundary/out_of_scope_statements"))
    for index, objective in enumerate(unit["learning_objectives"]):
        nested_sets.append((f"/learning_objectives/{index}/target_node_refs", objective.get("target_node_refs")))
    for index, behavior in enumerate(unit["behaviors"]):
        nested_sets.append((f"/behaviors/{index}/input_node_refs", behavior.get("input_node_refs")))
        nested_sets.append((f"/behaviors/{index}/output_node_refs", behavior.get("output_node_refs")))
    for index, validation in enumerate(unit["validations"]):
        nested_sets.append((f"/validations/{index}/subject_node_refs", validation.get("subject_node_refs")))
        nested_sets.append((f"/validations/{index}/evidence_node_refs", validation.get("evidence_node_refs")))
    for index, criterion in enumerate(unit["mastery_criteria"]):
        nested_sets.append((f"/mastery_criteria/{index}/evidence_node_refs", criterion.get("evidence_node_refs")))
    for path, references in nested_sets:
        if not _sorted_unique(references, _ref_key):
            return _result(False, _issue("knowledge_unit.noncanonical_set", path))
    schema = parse_json_bytes((contract_root / "schemas" / "knowledge-unit.schema.json").read_bytes())
    if not is_valid(unit, schema, schema):
        return _result(False, _issue("knowledge_unit.invalid_json", ""))
    return _result(True)


def parse_and_validate(raw: bytes, available_node_refs: Any, contract_root: Path) -> JsonObject:
    try:
        value = parse_json_bytes(raw)
    except JsonInputError:
        return _result(False, _issue("knowledge_unit.invalid_json", ""))
    return validate_unit(value, available_node_refs, contract_root)


def _walk(document: Any, pointer: str) -> tuple[Any, str | int]:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current, int(parts[-1]) if isinstance(current, list) else parts[-1]


def _mutate(unit: JsonObject, mutation: JsonObject) -> JsonObject:
    value = copy.deepcopy(unit)
    parent, leaf = _walk(value, mutation["path"])
    kind = mutation["kind"]
    if kind == "remove":
        del parent[leaf]
    elif kind == "reverse":
        parent[leaf] = list(reversed(parent[leaf]))
    elif kind == "clear":
        parent[leaf] = []
    elif kind == "replace":
        parent[leaf] = copy.deepcopy(mutation["value"])
    elif kind == "append-self-dependency":
        parent[leaf].append({"id": value["id"], "revision": value["revision"]})
    else:
        raise ValueError(f"unsupported fixture mutation: {kind}")
    return value


def run_fixture_suite(contract_root: Path) -> list[JsonObject]:
    suite = parse_json_bytes((contract_root / "fixtures" / "cases.json").read_bytes())
    base = next(case for case in suite["cases"] if "unit" in case["input"])
    base_unit = base["input"]["unit"]
    available = base["input"]["available_node_refs"]
    rows = []
    for case in suite["cases"]:
        unit = copy.deepcopy(case["input"]["unit"]) if "unit" in case["input"] else _mutate(base_unit, case["input"]["mutation"])
        rows.append({"case_id": case["case_id"], **validate_unit(unit, available, contract_root)})
    return sorted(rows, key=lambda row: row["case_id"].encode("utf-8"))
