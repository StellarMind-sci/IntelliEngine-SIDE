from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

COGNITIVE_IR_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(COGNITIVE_IR_ROOT / "python"))

from intelliengine_conformance.schema_validation import is_valid  # noqa: E402
from verify_profile import VerificationError as ProfileVerificationError
from verify_profile import jcs_bytes, parse_json_bytes


sys.dont_write_bytecode = True

CONTRACT_VERSION = "1.0.0"
SAFE_INTEGER = 9_007_199_254_740_991
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
TYPE_ID_PATTERN = r"^[a-z0-9]+(?:[.-][a-z0-9]+)*/[a-z0-9]+(?:[.-][a-z0-9]+)*$"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
CAPABILITY_PATTERN = TYPE_ID_PATTERN[:-1] + r"@(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
BASE_KINDS = [
    "action",
    "assumption",
    "constraint",
    "entity",
    "evidence",
    "experiment",
    "goal",
    "process",
    "relation",
    "state",
    "variable",
]
SCHEMAS = {
    "cognitive_node": "schemas/cognitive-node.schema.json",
    "cognitive_node_ref": "schemas/cognitive-node-ref.schema.json",
    "diagnostic": "schemas/diagnostic.schema.json",
    "fixture_suite": "schemas/fixture-suite.schema.json",
    "lock": "schemas/lock.schema.json",
    "type_definition": "schemas/type-definition.schema.json",
    "validation_result": "schemas/validation-result.schema.json",
}
COGNITIVE_NODE_REQUIRED = {
    "contract_version",
    "id",
    "revision",
    "base_kind",
    "type_id",
    "type_version",
    "data",
    "provenance_refs",
}
TYPE_DEFINITION_REQUIRED = {
    "definition_format_version",
    "type_id",
    "type_version",
    "base_kind",
    "owner",
    "data_schema",
    "schema_bundle",
    "required_capabilities",
    "provenance_refs",
}
COGNITIVE_NODE_CODES = {
    "cognitive_node.base_kind_mismatch",
    "cognitive_node.capability_denied",
    "cognitive_node.duplicate_key",
    "cognitive_node.idempotency_conflict",
    "cognitive_node.invalid_base_kind",
    "cognitive_node.invalid_data",
    "cognitive_node.invalid_id",
    "cognitive_node.invalid_json",
    "cognitive_node.invalid_number",
    "cognitive_node.invalid_revision",
    "cognitive_node.invalid_unicode",
    "cognitive_node.missing_field",
    "cognitive_node.missing_provenance",
    "cognitive_node.mutation_indeterminate",
    "cognitive_node.mutation_resource_exhausted",
    "cognitive_node.noncanonical_set",
    "cognitive_node.permission_denied",
    "cognitive_node.revision_authority_conflict",
    "cognitive_node.revision_conflict",
    "cognitive_node.type_resolution_indeterminate",
    "cognitive_node.unknown_type",
    "cognitive_node.unresolved_provenance",
    "cognitive_node.unresolved_reference",
    "cognitive_node.unsupported_contract_version",
    "cognitive_node.unsupported_type_version",
    "cognitive_node.untrusted_type",
    "validation.interrupted",
    "validation.issues_truncated",
    "validation.resource_exhausted",
}
TYPE_DEFINITION_CODES = {
    "type_definition.authority_indeterminate",
    "type_definition.base_kind_drift",
    "type_definition.capability_denied",
    "type_definition.forbidden_ref",
    "type_definition.immutable_key_conflict",
    "type_definition.invalid_capability_id",
    "type_definition.invalid_field",
    "type_definition.invalid_format_version",
    "type_definition.invalid_schema",
    "type_definition.invalid_structure",
    "type_definition.issues_truncated",
    "type_definition.namespace_denied",
    "type_definition.resource_exhausted",
    "type_definition.unsupported_schema_vocabulary",
    "type_definition.untrusted_owner",
    "type_definition.validation_indeterminate",
}
LEGAL_PAIRS = {
    ("cognitive_node", "transport"): {
        ("valid", "succeeded"),
        ("invalid", "succeeded"),
        ("not_evaluated", "resource_exhausted"),
        ("not_evaluated", "indeterminate"),
    },
    ("cognitive_node", "semantic"): {
        ("valid", "succeeded"),
        ("invalid", "succeeded"),
        ("compatible_read", "succeeded"),
        ("opaque", "succeeded"),
        ("not_evaluated", "resource_exhausted"),
        ("not_evaluated", "indeterminate"),
    },
    ("cognitive_node", "mutation"): {
        ("valid", "succeeded"),
        ("valid", "conflict"),
        ("valid", "policy_denied"),
        ("valid", "resource_exhausted"),
        ("valid", "indeterminate"),
    },
    ("type_definition", "registration"): {
        ("valid", "succeeded"),
        ("invalid", "succeeded"),
        ("valid", "policy_denied"),
        ("valid", "conflict"),
        ("not_evaluated", "resource_exhausted"),
        ("not_evaluated", "indeterminate"),
    },
}

PAIR_INVALID = {("invalid", "succeeded")}
PAIR_OPAQUE = {("opaque", "succeeded")}
PAIR_VALID_POLICY = {("valid", "policy_denied")}
PAIR_VALID_CONFLICT = {("valid", "conflict")}
PAIR_VALID_RESOURCE = {("valid", "resource_exhausted")}
PAIR_VALID_INDETERMINATE = {("valid", "indeterminate")}
PAIR_NOT_EVALUATED_RESOURCE = {("not_evaluated", "resource_exhausted")}
PAIR_NOT_EVALUATED_INDETERMINATE = {("not_evaluated", "indeterminate")}


def expected_diagnostic_pairs(code: str) -> set[tuple[str, str]]:
    if code in {"validation.issues_truncated", "type_definition.issues_truncated"}:
        return set()
    if code in {
        "cognitive_node.unknown_type",
        "cognitive_node.untrusted_type",
        "cognitive_node.unsupported_type_version",
    }:
        return PAIR_OPAQUE
    if code in {
        "cognitive_node.revision_conflict",
        "cognitive_node.revision_authority_conflict",
        "cognitive_node.idempotency_conflict",
        "cognitive_node.unresolved_provenance",
        "cognitive_node.unresolved_reference",
        "type_definition.immutable_key_conflict",
        "type_definition.base_kind_drift",
    }:
        return PAIR_VALID_CONFLICT
    if code in {
        "cognitive_node.permission_denied",
        "cognitive_node.capability_denied",
        "type_definition.namespace_denied",
        "type_definition.untrusted_owner",
        "type_definition.capability_denied",
    }:
        return PAIR_VALID_POLICY
    if code == "cognitive_node.mutation_resource_exhausted":
        return PAIR_VALID_RESOURCE
    if code == "cognitive_node.mutation_indeterminate":
        return PAIR_VALID_INDETERMINATE
    if code in {"validation.resource_exhausted", "type_definition.resource_exhausted"}:
        return PAIR_NOT_EVALUATED_RESOURCE
    if code in {
        "validation.interrupted",
        "cognitive_node.type_resolution_indeterminate",
        "type_definition.validation_indeterminate",
        "type_definition.authority_indeterminate",
    }:
        return PAIR_NOT_EVALUATED_INDETERMINATE
    return PAIR_INVALID


class ContractError(Exception):
    pass


def reject(code: str, detail: str) -> NoReturn:
    raise ContractError(f"{code}: {detail}")


def require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        reject("invalid_structure", f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        reject("invalid_structure", f"{label} must be an array")
    return value


def is_utf8_sorted_unique(values: object) -> bool:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        return False
    return len(values) == len(set(values)) and values == sorted(values, key=lambda value: value.encode("utf-8"))


def safe_path(root: Path, relative: object) -> tuple[str, Path]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        reject("unsafe_path", f"invalid POSIX relative path: {relative}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        reject("unsafe_path", f"unsafe relative path: {relative}")
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        reject("unsafe_path", f"path escapes contract root: {relative}")
    return pure.as_posix(), candidate


def load_json(root: Path, relative: str) -> object:
    canonical, path = safe_path(root, relative)
    if not path.is_file() or path.is_symlink():
        reject("missing_file", f"missing regular file: {canonical}")
    try:
        return parse_json_bytes(path.read_bytes(), path)
    except ProfileVerificationError as error:
        reject("invalid_json", f"{canonical}: {error.code}")


def validate_contract(root: Path) -> dict[str, object]:
    contract = require_object(load_json(root, "contract.json"), "contract.json")
    expected_keys = {
        "contract_family",
        "contract_version",
        "portable_profile",
        "base_kinds",
        "limits",
        "schemas",
        "diagnostics",
        "fixtures",
        "canonical_vectors",
    }
    if set(contract) != expected_keys:
        reject("contract_drift", "contract.json fields are not closed")
    if contract["contract_family"] != "cognitive-node" or contract["contract_version"] != CONTRACT_VERSION:
        reject("contract_drift", "contract identity changed")
    if contract["base_kinds"] != BASE_KINDS:
        reject("contract_drift", "base_kind set or canonical order changed")
    if contract["schemas"] != SCHEMAS:
        reject("contract_drift", "schema catalog changed")
    limits = require_object(contract["limits"], "limits")
    expected_limits = {
        "cognitive_node_jcs_bytes": 1_048_576,
        "type_definition_jcs_bytes": 2_097_152,
        "json_depth": 64,
        "json_members_and_elements": 100_000,
        "json_string_utf8_bytes": 262_144,
        "json_array_elements": 10_000,
        "schema_bundle_resources": 128,
        "ref_chain": 64,
        "regex_unicode_scalars": 1_024,
    }
    if limits != expected_limits:
        reject("contract_drift", "portable limits changed")
    profile = require_object(contract["portable_profile"], "portable_profile")
    if profile.get("profile_version") != "1.0.0":
        reject("profile_binding", "portable profile version must be 1.0.0")
    profile_path = root.parents[1] / "profile" / "1.0.0" / "profile.json"
    try:
        profile_value = parse_json_bytes(profile_path.read_bytes(), profile_path)
    except (OSError, ProfileVerificationError) as error:
        reject("profile_binding", f"cannot read bound portable profile: {error}")
    actual_profile_digest = hashlib.sha256(jcs_bytes(profile_value)).hexdigest()
    if profile.get("profile_jcs_sha256") != actual_profile_digest:
        reject("profile_binding", "portable profile digest mismatch")
    return contract


def validate_schemas(root: Path) -> None:
    loaded = {name: require_object(load_json(root, path), path) for name, path in SCHEMAS.items()}
    node = loaded["cognitive_node"]
    if set(require_list(node.get("required"), "CognitiveNode.required")) != COGNITIVE_NODE_REQUIRED:
        reject("schema_drift", "CognitiveNode required fields changed")
    node_properties = require_object(node.get("properties"), "CognitiveNode.properties")
    if set(node_properties) != COGNITIVE_NODE_REQUIRED:
        reject("schema_drift", "CognitiveNode declared fields changed")
    if require_object(node_properties["revision"], "revision").get("maximum") != SAFE_INTEGER:
        reject("schema_drift", "CognitiveNode safe revision limit changed")
    if require_object(node_properties["contract_version"], "contract_version").get("pattern") != SEMVER_PATTERN:
        reject("schema_drift", "CognitiveNode contract SemVer grammar changed")
    if require_object(node_properties["type_version"], "type_version").get("pattern") != SEMVER_PATTERN:
        reject("schema_drift", "CognitiveNode type SemVer grammar changed")
    if require_object(node_properties["type_id"], "type_id").get("pattern") != TYPE_ID_PATTERN:
        reject("schema_drift", "CognitiveNode type_id grammar changed")
    if require_object(node_properties["id"], "id").get("pattern") != UUID_PATTERN:
        reject("schema_drift", "CognitiveNode UUID grammar changed")
    if require_object(node_properties["base_kind"], "base_kind").get("enum") != [
        "entity", "variable", "relation", "constraint", "state", "process", "goal",
        "evidence", "assumption", "action", "experiment",
    ]:
        reject("schema_drift", "CognitiveNode base_kind declaration changed")
    definition = loaded["type_definition"]
    if set(require_list(definition.get("required"), "TypeDefinition.required")) != TYPE_DEFINITION_REQUIRED:
        reject("schema_drift", "TypeDefinition required fields changed")
    definition_properties = require_object(definition.get("properties"), "TypeDefinition.properties")
    if set(definition_properties) != TYPE_DEFINITION_REQUIRED:
        reject("schema_drift", "TypeDefinition declared fields changed")
    if require_object(definition_properties["definition_format_version"], "definition_format_version").get("pattern") != SEMVER_PATTERN:
        reject("schema_drift", "TypeDefinition format SemVer grammar changed")
    if require_object(definition_properties["type_version"], "type_version").get("pattern") != SEMVER_PATTERN:
        reject("schema_drift", "TypeDefinition type SemVer grammar changed")
    if require_object(definition_properties["type_id"], "type_id").get("pattern") != TYPE_ID_PATTERN:
        reject("schema_drift", "TypeDefinition type_id grammar changed")
    capabilities = require_object(definition_properties["required_capabilities"], "required_capabilities")
    if require_object(capabilities.get("items"), "required_capabilities.items").get("pattern") != CAPABILITY_PATTERN:
        reject("schema_drift", "capability ID grammar changed")
    data_schema = require_object(definition_properties["data_schema"], "data_schema")
    data_properties = require_object(data_schema.get("properties"), "data_schema.properties")
    if require_object(data_properties.get("$schema"), "$schema").get("const") != "https://json-schema.org/draft/2020-12/schema":
        reject("schema_drift", "TypeDefinition meta-schema changed")
    if require_object(data_properties.get("type"), "data_schema.type").get("const") != "object":
        reject("schema_drift", "TypeDefinition data_schema root must be object")


def validate_catalog(root: Path, relative: str, interface: str, required_codes: set[str]) -> set[str]:
    catalog = require_object(load_json(root, relative), relative)
    if set(catalog) != {"interface", "codes"} or catalog.get("interface") != interface:
        reject("diagnostic_drift", f"invalid catalog identity: {relative}")
    entries = require_list(catalog.get("codes"), f"{relative}.codes")
    codes: list[str] = []
    for entry_value in entries:
        entry = require_object(entry_value, f"{relative}.code")
        if set(entry) != {"code", "severity", "allowed_pairs"}:
            reject("diagnostic_drift", f"diagnostic entry fields are not closed: {relative}")
        code = entry.get("code")
        if not isinstance(code, str):
            reject("diagnostic_drift", f"diagnostic code is not a string: {relative}")
        if entry.get("severity") not in {"error", "warning", "info"}:
            reject("diagnostic_drift", f"invalid severity: {code}")
        interface_pairs = set().union(
            *(pairs for (candidate_interface, _), pairs in LEGAL_PAIRS.items() if candidate_interface == interface)
        )
        declared_pairs: set[tuple[str, str]] = set()
        for pair_value in require_list(entry.get("allowed_pairs"), f"{code}.allowed_pairs"):
            pair = require_list(pair_value, f"{code}.pair")
            if len(pair) != 2 or tuple(pair) not in interface_pairs:
                reject("diagnostic_drift", f"illegal diagnostic state pair: {code}")
            declared_pairs.add((str(pair[0]), str(pair[1])))
        if declared_pairs != expected_diagnostic_pairs(code):
            reject("diagnostic_drift", f"diagnostic state mapping changed: {code}")
        codes.append(code)
    if codes != sorted(codes, key=lambda value: value.encode("utf-8")) or len(codes) != len(set(codes)):
        reject("diagnostic_drift", f"diagnostic codes must be unique and UTF-8 sorted: {relative}")
    if set(codes) != required_codes:
        reject("diagnostic_drift", f"diagnostic code set changed: {relative}")
    return set(codes)


def validate_fixtures(
    root: Path,
    relative: str,
    allowed_codes: set[str],
    node_schema: dict[str, object],
    type_definition_schema: dict[str, object],
) -> None:
    suite = require_object(load_json(root, relative), relative)
    if set(suite) != {"contract_version", "cases"} or suite.get("contract_version") != CONTRACT_VERSION:
        reject("fixture_invalid", "fixture suite identity changed")
    cases = require_list(suite.get("cases"), "fixtures.cases")
    ids: set[str] = set()
    required_categories = {"transport", "semantic", "type-definition", "resource", "parser"}
    categories: set[str] = set()
    for case_value in cases:
        case = require_object(case_value, "fixture case")
        if set(case) != {"case_id", "category", "operation", "input", "context", "expected"}:
            reject("fixture_invalid", "fixture case fields are not closed")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in ids:
            reject("fixture_invalid", f"duplicate or invalid case_id: {case_id}")
        ids.add(case_id)
        category = case.get("category")
        if not isinstance(category, str):
            reject("fixture_invalid", f"invalid category: {case_id}")
        categories.add(category)
        expected = require_object(case.get("expected"), f"{case_id}.expected")
        if set(expected) != {"interface", "mode", "object_result", "operation_outcome", "issues"}:
            reject("fixture_invalid", f"expected fields are not closed: {case_id}")
        key = (expected.get("interface"), expected.get("mode"))
        pair = (expected.get("object_result"), expected.get("operation_outcome"))
        if key not in LEGAL_PAIRS or pair not in LEGAL_PAIRS[key]:
            reject("fixture_invalid", f"illegal state pair: {case_id}")
        issue_codes: list[str] = []
        for issue_value in require_list(expected.get("issues"), f"{case_id}.issues"):
            issue = require_object(issue_value, f"{case_id}.issue")
            if not {"code", "path", "severity"}.issubset(issue) or not set(issue).issubset({"code", "path", "severity", "details"}):
                reject("fixture_invalid", f"invalid issue shape: {case_id}")
            code = issue.get("code")
            if code not in allowed_codes:
                reject("fixture_invalid", f"unknown diagnostic code in {case_id}: {code}")
            issue_codes.append(str(code))
        if "cognitive_node.unknown_type" in issue_codes and "cognitive_node.unsupported_type_version" in issue_codes:
            reject("fixture_invalid", f"unknown and unsupported type are mutually exclusive: {case_id}")
        interface = expected.get("interface")
        if interface == "type_definition" and any(not code.startswith("type_definition.") for code in issue_codes):
            reject("fixture_invalid", f"TypeDefinition leaked another diagnostic namespace: {case_id}")
        input_value = case.get("input")
        object_result = expected.get("object_result")
        mode = expected.get("mode")
        if interface == "cognitive_node" and isinstance(input_value, dict) and "contract_version" in input_value:
            schema_valid = is_valid(input_value, node_schema)
            if (mode == "semantic" or object_result == "valid") and not schema_valid:
                reject("fixture_invalid", f"fixture claims a schema-invalid CognitiveNode is usable: {case_id}")
            if (mode == "semantic" or object_result == "valid") and not is_utf8_sorted_unique(input_value.get("provenance_refs")):
                reject("fixture_invalid", f"CognitiveNode provenance_refs are not canonical: {case_id}")
        if interface == "type_definition" and isinstance(input_value, dict) and "definition_format_version" in input_value:
            schema_valid = is_valid(input_value, type_definition_schema)
            if object_result in {"valid", "not_evaluated"} and not schema_valid:
                reject("fixture_invalid", f"fixture claims a schema-invalid TypeDefinition is usable: {case_id}")
            if object_result in {"valid", "not_evaluated"}:
                if not is_utf8_sorted_unique(input_value.get("provenance_refs")):
                    reject("fixture_invalid", f"TypeDefinition provenance_refs are not canonical: {case_id}")
                if not is_utf8_sorted_unique(input_value.get("required_capabilities")):
                    reject("fixture_invalid", f"TypeDefinition required_capabilities are not canonical: {case_id}")
                bundle = input_value.get("schema_bundle")
                if not isinstance(bundle, list):
                    reject("fixture_invalid", f"TypeDefinition schema_bundle is not an array: {case_id}")
                uris = [item.get("uri") for item in bundle if isinstance(item, dict)]
                if len(uris) != len(bundle) or not is_utf8_sorted_unique(uris):
                    reject("fixture_invalid", f"TypeDefinition schema_bundle is not canonical: {case_id}")
    if categories != required_categories:
        reject("fixture_invalid", f"fixture categories incomplete: {sorted(categories)}")


def validate_canonical_vectors(root: Path, relative: str) -> None:
    document = require_object(load_json(root, relative), relative)
    if set(document) != {"contract_version", "vectors"} or document.get("contract_version") != CONTRACT_VERSION:
        reject("canonical_drift", "canonical vector identity changed")
    seen: set[str] = set()
    for vector_value in require_list(document.get("vectors"), "canonical vectors"):
        vector = require_object(vector_value, "canonical vector")
        if set(vector) != {"vector_id", "value", "jcs"}:
            reject("canonical_drift", "canonical vector fields are not closed")
        vector_id = vector.get("vector_id")
        if not isinstance(vector_id, str) or vector_id in seen:
            reject("canonical_drift", f"duplicate vector: {vector_id}")
        seen.add(vector_id)
        expected = vector.get("jcs")
        if not isinstance(expected, str) or jcs_bytes(vector.get("value")) != expected.encode("utf-8"):
            reject("canonical_drift", f"JCS vector mismatch: {vector_id}")
    if seen != {"object-key-order", "negative-zero", "array-order", "utf16-key-order"}:
        reject("canonical_drift", "canonical vector coverage changed")


def validate_lock(root: Path) -> None:
    lock = require_object(load_json(root, "lock.json"), "lock.json")
    if set(lock) != {"contract_version", "self_digest", "entries"}:
        reject("lock_invalid", "lock fields are not closed")
    if lock.get("contract_version") != CONTRACT_VERSION or lock.get("self_digest") != "excluded":
        reject("lock_invalid", "lock identity changed")
    entries = require_list(lock.get("entries"), "lock.entries")
    locked: dict[str, str] = {}
    paths: list[str] = []
    for entry_value in entries:
        entry = require_object(entry_value, "lock entry")
        if set(entry) != {"path", "digest_kind", "sha256"} or entry.get("digest_kind") != "jcs_sha256":
            reject("lock_invalid", "lock entry fields or digest kind are invalid")
        relative, path = safe_path(root, entry.get("path"))
        if relative == "lock.json" or relative in locked or not relative.endswith(".json"):
            reject("lock_invalid", f"invalid or duplicate lock path: {relative}")
        if not path.is_file() or path.is_symlink():
            reject("missing_file", f"locked file missing: {relative}")
        value = load_json(root, relative)
        actual = hashlib.sha256(jcs_bytes(value)).hexdigest()
        if entry.get("sha256") != actual:
            reject("digest_mismatch", f"JCS digest mismatch: {relative}")
        locked[relative] = actual
        paths.append(relative)
    if paths != sorted(paths, key=lambda value: value.encode("utf-8")):
        reject("lock_invalid", "lock entries must be UTF-8 sorted")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.json")
        if path.relative_to(root).as_posix() != "lock.json"
    }
    if set(locked) != actual_files:
        reject("lock_closure", f"lock closure mismatch: missing={sorted(actual_files - set(locked))}, extra={sorted(set(locked) - actual_files)}")


def verify(root: Path) -> None:
    root = root.resolve()
    if not root.is_dir() or root.name != CONTRACT_VERSION or root.parent.name != "cognitive-node":
        reject("invalid_root", "root must be cognitive-node/1.0.0")
    contract = validate_contract(root)
    validate_schemas(root)
    node_schema = require_object(load_json(root, SCHEMAS["cognitive_node"]), "CognitiveNode schema")
    type_definition_schema = require_object(load_json(root, SCHEMAS["type_definition"]), "TypeDefinition schema")
    cognitive_codes = validate_catalog(
        root,
        require_object(contract["diagnostics"], "diagnostics")["cognitive_node"],
        "cognitive_node",
        COGNITIVE_NODE_CODES,
    )
    type_codes = validate_catalog(
        root,
        require_object(contract["diagnostics"], "diagnostics")["type_definition"],
        "type_definition",
        TYPE_DEFINITION_CODES,
    )
    validate_fixtures(
        root,
        str(contract["fixtures"]),
        cognitive_codes | type_codes,
        node_schema,
        type_definition_schema,
    )
    validate_canonical_vectors(root, str(contract["canonical_vectors"]))
    validate_lock(root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify CognitiveNode contract bundle")
    default_root = Path(__file__).resolve().parents[1] / "cognitive-node" / CONTRACT_VERSION
    parser.add_argument("--root", type=Path, default=default_root)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        verify(arguments.root)
    except ContractError as error:
        print(f"cognitive-node-contract.{error}", file=sys.stderr)
        return 1
    print(f"cognitive node contract {CONTRACT_VERSION} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
