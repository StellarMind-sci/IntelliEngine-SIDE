from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COGNITIVE_IR_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
if str(COGNITIVE_IR_PYTHON) not in sys.path:
    sys.path.insert(0, str(COGNITIVE_IR_PYTHON))

from intelliengine_conformance.json_codec import canonicalize, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid


JsonObject = dict[str, Any]
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SAFE_INTEGER = 9007199254740991
CAPABILITIES = {
    "runtime.math.numeric",
    "runtime.math.symbolic",
    "runtime.visualization.2d",
}
REQUIRED = [
    "contract_version",
    "id",
    "revision",
    "title",
    "concept_boundary",
    "learning_objectives",
    "node_bindings",
    "prerequisite_unit_refs",
    "behaviors",
    "validations",
    "mastery_criteria",
    "provenance_refs",
]


def _load(path: Path) -> Any:
    return parse_json_bytes(path.read_bytes())


def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "error"}


def _result(valid: bool, issue: JsonObject | None = None) -> JsonObject:
    return {
        "object_result": "valid" if valid else "invalid",
        "operation_outcome": "succeeded",
        "issues": [] if issue is None else [issue],
    }


def _ref_key(ref: Any) -> tuple[bytes, int] | None:
    if not isinstance(ref, dict) or set(ref) != {"id", "revision"}:
        return None
    identifier = ref.get("id")
    revision = ref.get("revision")
    if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
        return None
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= SAFE_INTEGER:
        return None
    return identifier.encode("utf-8"), revision


def _sorted_unique(values: Any, key) -> bool:
    if not isinstance(values, list):
        return False
    keys = [key(value) for value in values]
    return all(item is not None for item in keys) and len(keys) == len(set(keys)) and keys == sorted(keys)


def _string_set(values: Any) -> bool:
    return _sorted_unique(values, lambda value: value.encode("utf-8") if isinstance(value, str) and value else None)


def _binding_key(binding: Any):
    if not isinstance(binding, dict) or set(binding) != {"role", "node_ref"}:
        return None
    role = binding.get("role")
    ref = _ref_key(binding.get("node_ref"))
    if role not in {"core", "evidence", "example", "representation"} or ref is None:
        return None
    return role.encode("utf-8"), *ref


def _named_key(field: str):
    def key(value: Any):
        if not isinstance(value, dict) or not isinstance(value.get(field), str):
            return None
        return value[field].encode("utf-8")
    return key


def _walk_pointer(document: Any, pointer: str) -> tuple[Any, str | int]:
    if not pointer.startswith("/"):
        raise ValueError("mutation path must be a JSON Pointer")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    leaf: str | int = int(parts[-1]) if isinstance(current, list) else parts[-1]
    return current, leaf


def _apply_mutation(unit: JsonObject, mutation: JsonObject) -> JsonObject:
    value = copy.deepcopy(unit)
    kind = mutation["kind"]
    parent, leaf = _walk_pointer(value, mutation["path"])
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


def _materialize(case: JsonObject, root: Path) -> tuple[JsonObject, list[JsonObject]]:
    input_value = case["input"]
    if "unit" in input_value:
        return copy.deepcopy(input_value["unit"]), copy.deepcopy(input_value["available_node_refs"])
    suite = _load(root / "fixtures" / "cases.json")
    base = next(item for item in suite["cases"] if item["case_id"] == input_value["base_case_id"])
    unit, available = _materialize(base, root)
    return _apply_mutation(unit, input_value["mutation"]), available


def _collect_refs(unit: JsonObject) -> list[tuple[bytes, int]]:
    refs: list[Any] = []
    boundary = unit.get("concept_boundary")
    if isinstance(boundary, dict):
        refs.extend(boundary.get("focus_node_refs", []))
    for objective in unit.get("learning_objectives", []):
        if isinstance(objective, dict):
            refs.extend(objective.get("target_node_refs", []))
    for binding in unit.get("node_bindings", []):
        if isinstance(binding, dict):
            refs.append(binding.get("node_ref"))
    for behavior in unit.get("behaviors", []):
        if isinstance(behavior, dict):
            refs.extend(behavior.get("input_node_refs", []))
            refs.extend(behavior.get("output_node_refs", []))
    for validation in unit.get("validations", []):
        if isinstance(validation, dict):
            refs.extend(validation.get("subject_node_refs", []))
            refs.extend(validation.get("evidence_node_refs", []))
    for criterion in unit.get("mastery_criteria", []):
        if isinstance(criterion, dict):
            refs.extend(criterion.get("evidence_node_refs", []))
    return [key for ref in refs if (key := _ref_key(ref)) is not None]


def validate_unit(unit: Any, available_node_refs: Any, schema: Any | None = None) -> JsonObject:
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
    if not isinstance(unit["title"], str) or not unit["title"] or len(unit["title"]) > 512:
        return _result(False, _issue("knowledge_unit.invalid_json", "/title"))
    if not _sorted_unique(unit["node_bindings"], _binding_key):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/node_bindings"))
    if not _sorted_unique(unit["prerequisite_unit_refs"], _ref_key):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/prerequisite_unit_refs"))
    if not _string_set(unit["provenance_refs"]):
        return _result(False, _issue("knowledge_unit.noncanonical_set", "/provenance_refs"))
    for field, identifier in (("learning_objectives", "objective_id"), ("behaviors", "behavior_id"), ("validations", "validation_id"), ("mastery_criteria", "criterion_id")):
        if not _sorted_unique(unit[field], _named_key(identifier)):
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
    available = set(_ref_key(ref) for ref in available_node_refs)
    for ref in _collect_refs(unit):
        if ref not in available:
            return _result(False, _issue("knowledge_unit.dangling_node_ref", ""))
    bound = {_ref_key(binding["node_ref"]) for binding in unit["node_bindings"]}
    if any(ref not in bound for ref in _collect_refs(unit)):
        return _result(False, _issue("knowledge_unit.dangling_node_ref", "/node_bindings"))
    nested_sets: list[tuple[str, Any]] = []
    boundary = unit.get("concept_boundary")
    if isinstance(boundary, dict):
        nested_sets.append(("/concept_boundary/focus_node_refs", boundary.get("focus_node_refs")))
        if not _string_set(boundary.get("out_of_scope_statements")):
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
    boundary = unit["concept_boundary"]
    if not isinstance(boundary, dict) or not boundary.get("focus_node_refs") or not _sorted_unique(boundary.get("focus_node_refs"), _ref_key) or not _string_set(boundary.get("out_of_scope_statements")):
        return _result(False, _issue("knowledge_unit.invalid_json", "/concept_boundary"))
    if schema is not None and not is_valid(unit, schema, schema):
        return _result(False, _issue("knowledge_unit.invalid_json", ""))
    return _result(True)


def validate_case(case: JsonObject, root: Path) -> JsonObject:
    unit, available = _materialize(case, root)
    schema = _load(root / "schemas" / "knowledge-unit.schema.json")
    return validate_unit(unit, available, schema)


def _verify_lock(root: Path) -> None:
    lock = _load(root / "lock.json")
    entries = lock.get("entries") if isinstance(lock, dict) else None
    if not isinstance(entries, list):
        raise ValueError("invalid lock")
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.json")
        if path.relative_to(root).as_posix() != "lock.json"
    )
    declared_paths = [entry.get("path") for entry in entries]
    if declared_paths != actual_paths:
        raise ValueError("lock closure mismatch")
    for entry in entries:
        if entry.get("digest_kind") != "jcs_sha256":
            raise ValueError("unsupported digest kind")
        document = _load(root / entry["path"])
        digest = hashlib.sha256(canonicalize(document)).hexdigest()
        if digest != entry.get("sha256"):
            raise ValueError(f"digest mismatch: {entry['path']}")


def verify_contract(root: Path) -> JsonObject:
    root = root.resolve()
    contract = _load(root / "contract.json")
    if contract.get("contract_family") != "knowledge-unit" or contract.get("contract_version") != "1.0.0":
        raise ValueError("invalid contract manifest")
    catalog = _load(root / "diagnostics" / "knowledge-unit.json")
    codes = set(catalog.get("codes", []))
    suite = _load(root / "fixtures" / "cases.json")
    fixture_schema = _load(root / "schemas" / "fixture-suite.schema.json")
    result_schema = _load(root / "schemas" / "validation-result.schema.json")
    if not is_valid(suite, fixture_schema, fixture_schema):
        raise ValueError("fixture suite does not match its machine schema")
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list) or len(cases) != 8:
        raise ValueError("fixture suite must contain eight cases")
    case_ids = [case.get("case_id") for case in cases]
    if any(not isinstance(case_id, str) for case_id in case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case IDs are invalid or duplicated")
    for case in cases:
        if not is_valid(case.get("expected"), result_schema, result_schema):
            raise ValueError(f"fixture expected result is invalid: {case['case_id']}")
        computed = validate_case(case, root)
        if computed != case.get("expected"):
            raise ValueError(f"fixture result mismatch: {case['case_id']}")
        if any(issue["code"] not in codes for issue in computed["issues"]):
            raise ValueError(f"unknown diagnostic: {case['case_id']}")
    _verify_lock(root)
    return {"case_count": len(cases), "contract_version": contract["contract_version"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "knowledge-unit" / "1.0.0")
    args = parser.parse_args()
    report = verify_contract(args.root)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
