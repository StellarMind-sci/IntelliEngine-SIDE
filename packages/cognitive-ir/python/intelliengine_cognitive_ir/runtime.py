from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intelliengine_conformance.json_codec import JsonInputError, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid


JsonObject = dict[str, Any]


def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "error"}


def _result(
    interface: str,
    mode: str,
    object_result: str,
    outcome: str,
    issues: list[JsonObject] | None = None,
) -> JsonObject:
    return {
        "interface": interface,
        "mode": mode,
        "object_result": object_result,
        "operation_outcome": outcome,
        "issues": issues or [],
    }


def _utf8_sorted_unique(values: Any) -> bool:
    return (
        isinstance(values, list)
        and all(isinstance(value, str) for value in values)
        and len(values) == len(set(values))
        and values == sorted(values, key=lambda value: value.encode("utf-8"))
    )


def parse_and_validate_transport(raw: bytes, node_schema: JsonObject) -> JsonObject:
    try:
        node = parse_json_bytes(raw)
    except JsonInputError as error:
        if error.reason == "duplicate-member":
            code = "cognitive_node.duplicate_key"
        elif error.reason in {"invalid-utf8", "invalid-json-escape", "unpaired-surrogate"}:
            code = "cognitive_node.invalid_unicode"
        elif error.reason in {"non-finite-number", "unsafe-integer"}:
            code = "cognitive_node.invalid_number"
        else:
            code = "cognitive_node.invalid_json"
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue(code, error.path)])
    return validate_transport(node, node_schema)


def validate_transport(node: Any, node_schema: JsonObject) -> JsonObject:
    if not isinstance(node, dict):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.invalid_json", "")])
    required = node_schema["required"]
    missing = next((name for name in required if name not in node), None)
    if missing is not None:
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.missing_field", f"/{missing}")])
    version = node.get("contract_version")
    if not isinstance(version, str) or not version.startswith("1."):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.unsupported_contract_version", "/contract_version")])
    properties = node_schema["properties"]
    if not is_valid(node.get("id"), properties["id"]):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.invalid_id", "/id")])
    if not is_valid(node.get("revision"), properties["revision"]):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.invalid_revision", "/revision")])
    if node.get("base_kind") not in properties["base_kind"]["enum"]:
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.invalid_base_kind", "/base_kind")])
    provenance = node.get("provenance_refs")
    if provenance == []:
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.missing_provenance", "/provenance_refs")])
    if not _utf8_sorted_unique(provenance):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.noncanonical_set", "/provenance_refs")])
    if not is_valid(node, node_schema):
        return _result("cognitive_node", "transport", "invalid", "succeeded", [_issue("cognitive_node.invalid_json", "")])
    return _result("cognitive_node", "transport", "valid", "succeeded")


def validate_semantic(
    node: Any,
    node_schema: JsonObject,
    type_definition: JsonObject,
    snapshot: str,
) -> JsonObject:
    transport = validate_transport(node, node_schema)
    if transport["object_result"] != "valid":
        return transport
    if snapshot == "type-id-absent":
        return _result("cognitive_node", "semantic", "opaque", "succeeded", [_issue("cognitive_node.unknown_type", "/type_id")])
    if snapshot == "type-id-present-version-unavailable":
        return _result("cognitive_node", "semantic", "opaque", "succeeded", [_issue("cognitive_node.unsupported_type_version", "/type_version")])
    if snapshot == "exact-type-owner-untrusted":
        return _result("cognitive_node", "semantic", "opaque", "succeeded", [_issue("cognitive_node.untrusted_type", "/type_id")])
    if snapshot == "authority-indeterminate":
        return _result("cognitive_node", "semantic", "not_evaluated", "indeterminate", [_issue("cognitive_node.type_resolution_indeterminate", "/type_id")])
    if snapshot == "older-compatible-math-equation-1.2.0":
        if is_valid(node["data"], type_definition["data_schema"]):
            return _result("cognitive_node", "semantic", "compatible_read", "succeeded")
        return _result("cognitive_node", "semantic", "opaque", "succeeded", [_issue("cognitive_node.unsupported_type_version", "/type_version")])
    if snapshot != "exact-math-equation":
        raise ValueError(f"unsupported test snapshot: {snapshot}")
    if node["base_kind"] != type_definition["base_kind"]:
        return _result("cognitive_node", "semantic", "invalid", "succeeded", [_issue("cognitive_node.base_kind_mismatch", "/base_kind")])
    if not is_valid(node["data"], type_definition["data_schema"]):
        missing = next(
            (name for name in type_definition["data_schema"].get("required", []) if name not in node["data"]),
            None,
        )
        path = f"/data/{missing}" if missing else "/data"
        return _result("cognitive_node", "semantic", "invalid", "succeeded", [_issue("cognitive_node.invalid_data", path)])
    return _result("cognitive_node", "semantic", "valid", "succeeded")


def _walk_schema(schema: Any, allowed_keywords: set[str]) -> str | None:
    if isinstance(schema, bool):
        return None
    if not isinstance(schema, dict):
        return "type_definition.invalid_schema"
    maps = {"$defs", "dependentSchemas", "properties", "patternProperties"}
    arrays = {"allOf", "anyOf", "oneOf", "prefixItems"}
    singles = {"not", "if", "then", "else", "items", "contains", "additionalProperties", "propertyNames", "unevaluatedItems", "unevaluatedProperties", "contentSchema"}
    for key, value in schema.items():
        if key == "$ref":
            if not isinstance(value, str) or not (
                value == "#"
                or value.startswith("#/")
                or (value.startswith("urn:intelliengine:schema:sha256:") and len(value) == 97)
            ):
                return "type_definition.forbidden_ref"
        if key not in allowed_keywords and not key.startswith("x-"):
            return "type_definition.unsupported_schema_vocabulary"
        children: list[Any] = []
        if key in maps and isinstance(value, dict):
            children = list(value.values())
        elif key in arrays and isinstance(value, list):
            children = value
        elif key in singles:
            children = [value]
        for child in children:
            problem = _walk_schema(child, allowed_keywords)
            if problem:
                return problem
    return None


def validate_type_definition(
    definition: Any,
    definition_schema: JsonObject,
    allowed_keywords: set[str],
    context: JsonObject,
) -> JsonObject:
    if not is_valid(definition, definition_schema):
        return _result("type_definition", "registration", "invalid", "succeeded", [_issue("type_definition.invalid_structure", "")])
    problem = _walk_schema(definition["data_schema"], allowed_keywords)
    if problem:
        key = "$ref" if problem.endswith("forbidden_ref") else "unknownKeyword"
        return _result("type_definition", "registration", "invalid", "succeeded", [_issue(problem, f"/data_schema/{key}")])
    if context.get("namespace_decision") == "denied":
        return _result("type_definition", "registration", "valid", "policy_denied", [_issue("type_definition.namespace_denied", "/type_id")])
    return _result("type_definition", "registration", "valid", "succeeded")


def run_fixture_suite(contract_root: Path, profile_root: Path) -> list[JsonObject]:
    suite = parse_json_bytes((contract_root / "fixtures" / "cases.json").read_bytes())
    node_schema = parse_json_bytes((contract_root / "schemas" / "cognitive-node.schema.json").read_bytes())
    definition_schema = parse_json_bytes((contract_root / "schemas" / "type-definition.schema.json").read_bytes())
    profile = parse_json_bytes((profile_root / "profile.json").read_bytes())
    allowed_keywords = set(profile["schema_profile"]["allowed_keywords"])
    cases = suite["cases"]
    math_definition = next(case["input"] for case in cases if case["case_id"] == "math-equation-type-definition-valid")
    rows: list[JsonObject] = []
    for case in cases:
        case_id = case["case_id"]
        operation = case["operation"]
        value = case["input"]
        if case["category"] == "resource":
            interface = "type_definition" if operation == "registration" else "cognitive_node"
            code = "type_definition.resource_exhausted" if interface == "type_definition" else "validation.resource_exhausted"
            mode = "registration" if interface == "type_definition" else "transport"
            result = _result(interface, mode, "not_evaluated", "resource_exhausted", [_issue(code, "")])
        elif case["category"] == "parser":
            mapping = {
                "parser-duplicate-key": ("duplicate-member", "cognitive_node.duplicate_key", ""),
                "parser-unpaired-surrogate": ("unpaired-surrogate", "cognitive_node.invalid_unicode", ""),
            }
            profile_case_id = value["portable_profile_fixture"]
            expected_reason, code, path = mapping[profile_case_id]
            profile_case = parse_json_bytes(
                (profile_root / "fixtures" / profile_case_id / "case.json").read_bytes()
            )
            primary = profile_case["input"]["primary"]
            prefix = "profile/1.0.0/"
            if not isinstance(primary, str) or not primary.startswith(prefix) or "\\" in primary:
                raise ValueError(f"unsafe parser fixture path: {primary}")
            parts = primary[len(prefix) :].split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise ValueError(f"unsafe parser fixture path: {primary}")
            candidate = (profile_root / Path(*parts)).resolve()
            candidate.relative_to(profile_root.resolve())
            try:
                parse_json_bytes(candidate.read_bytes())
            except JsonInputError as error:
                if error.reason != expected_reason:
                    raise ValueError(
                        f"parser fixture {profile_case_id} produced {error.reason}, expected {expected_reason}"
                    ) from error
            else:
                raise ValueError(f"parser fixture {profile_case_id} unexpectedly parsed")
            result = _result("cognitive_node", "transport", "invalid", "succeeded", [_issue(code, path)])
        elif operation == "transport":
            result = validate_transport(value, node_schema)
        elif operation == "semantic":
            result = validate_semantic(value, node_schema, math_definition, case["context"]["type_snapshot"])
        elif operation == "registration":
            result = validate_type_definition(value, definition_schema, allowed_keywords, case["context"])
        else:
            raise ValueError(f"unsupported fixture operation: {operation}")
        rows.append({"case_id": case_id, **result})
    return sorted(rows, key=lambda row: row["case_id"].encode("utf-8"))
