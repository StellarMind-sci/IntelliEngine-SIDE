from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn


sys.dont_write_bytecode = True


PROFILE_VERSION = "1.0.0"
PROFILE_DIRECTORY = Path("profile") / PROFILE_VERSION
PROFILE_PATH = PROFILE_DIRECTORY / "profile.json"
LOCK_PATH = PROFILE_DIRECTORY / "lock.json"
DIAGNOSTICS_PATH = PROFILE_DIRECTORY / "diagnostics" / "conformance.json"
FIXTURE_MANIFEST_PATH = PROFILE_DIRECTORY / "fixtures" / "manifest.json"
SCHEMA_DIRECTORY = PROFILE_DIRECTORY / "schemas"
SAFE_INTEGER = 9_007_199_254_740_991
REQUIRED_SCHEMAS = {
    "diagnostics.schema.json",
    "expected-result.schema.json",
    "fixture-case.schema.json",
    "fixture-manifest.schema.json",
    "lock.schema.json",
    "profile.schema.json",
}
REQUIRED_DIAGNOSTICS = {
    "conformance.consumer_crashed",
    "conformance.digest_mismatch",
    "conformance.fixture_invalid",
    "conformance.generated_drift",
    "conformance.network_or_file_access",
    "conformance.result_mismatch",
}
REQUIRED_CATEGORIES = {
    "annotation",
    "lock",
    "parser",
    "profile",
    "recursion",
    "reference-dag",
    "regex",
    "sorting",
    "work-unit",
}
REQUIRED_PARSER_CASES = {
    "parser-bom",
    "parser-duplicate-key",
    "parser-invalid-escape",
    "parser-invalid-utf8",
    "parser-unpaired-surrogate",
}
EXPECTED_ALLOWED_KEYWORDS = (
    "$schema", "$ref", "$defs", "$comment", "allOf", "anyOf", "oneOf", "not",
    "if", "then", "else", "dependentSchemas", "prefixItems", "items", "contains",
    "minContains", "maxContains", "properties", "patternProperties", "additionalProperties",
    "propertyNames", "type", "enum", "const", "multipleOf", "maximum", "exclusiveMaximum",
    "minimum", "exclusiveMinimum", "maxLength", "minLength", "pattern", "maxItems", "minItems",
    "uniqueItems", "maxProperties", "minProperties", "required", "dependentRequired", "title",
    "description", "default", "deprecated", "readOnly", "writeOnly", "examples", "format",
    "contentEncoding", "contentMediaType", "contentSchema", "x-*", "unevaluatedItems",
    "unevaluatedProperties",
)
LEGAL_STATE_PAIRS = {
    ("valid", "succeeded"),
    ("invalid", "succeeded"),
    ("opaque", "succeeded"),
    ("opaque", "indeterminate"),
    ("opaque", "policy_denied"),
    ("not_evaluated", "resource_exhausted"),
    ("not_evaluated", "indeterminate"),
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def reject(code: str, detail: str) -> NoReturn:
    raise VerificationError(code, detail)


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            reject("profile.duplicate_json_member", f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _parse_integer(token: str) -> int:
    value = int(token)
    if abs(value) > SAFE_INTEGER:
        reject("profile.unsafe_integer", f"integer outside portable range: {token}")
    return value


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        reject("profile.invalid_json_number", f"non-finite binary64: {token}")
    return value


def _validate_unicode_scalars(value: object) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            reject("profile.invalid_unicode_scalar", "unpaired surrogate is forbidden")
        return
    if isinstance(value, list):
        for item in value:
            _validate_unicode_scalars(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode_scalars(key)
            _validate_unicode_scalars(item)


def parse_json_bytes(raw: bytes, path: Path) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        reject("profile.invalid_json_bytes", f"UTF-8 BOM is forbidden: {path}")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_pairs_without_duplicates,
            parse_int=_parse_integer,
            parse_float=_parse_float,
            parse_constant=lambda token: reject(
                "profile.invalid_json_number", f"non-finite number: {token}"
            ),
        )
    except VerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reject("profile.invalid_json_bytes", f"invalid JSON in {path}: {error}")
    _validate_unicode_scalars(value)
    return value


def load_json(path: Path, missing_code: str = "profile.missing_file") -> object:
    if not path.is_file():
        reject(missing_code, f"missing file: {path}")
    return parse_json_bytes(path.read_bytes(), path)


def _jcs_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    text = repr(value).lower()
    negative = text.startswith("-")
    unsigned = text[1:] if negative else text
    prefix = "-" if negative else ""
    if "e" not in unsigned:
        if unsigned.endswith(".0"):
            unsigned = unsigned[:-2]
        return prefix + unsigned
    mantissa, exponent_text = unsigned.split("e")
    exponent = int(exponent_text)
    digits = mantissa.replace(".", "")
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        decimal_position = 1 + exponent
        if decimal_position <= 0:
            fixed = "0." + ("0" * -decimal_position) + digits
        elif decimal_position >= len(digits):
            fixed = digits + ("0" * (decimal_position - len(digits)))
        else:
            fixed = digits[:decimal_position] + "." + digits[decimal_position:]
        return prefix + fixed
    normalized_mantissa = mantissa[:-2] if mantissa.endswith(".0") else mantissa
    exponent_sign = "+" if exponent >= 0 else "-"
    return f"{prefix}{normalized_mantissa}e{exponent_sign}{abs(exponent)}"


def jcs_bytes(value: object) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, (int, float)):
        return _jcs_number(value).encode("ascii")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(jcs_bytes(item) for item in value) + b"]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        members = [jcs_bytes(key) + b":" + jcs_bytes(value[key]) for key in keys]
        return b"{" + b",".join(members) + b"}"
    reject("profile.invalid_json_value", f"unsupported JSON value: {type(value).__name__}")


def require_object(value: object, code: str, detail: str) -> dict[str, object]:
    if not isinstance(value, dict):
        reject(code, detail)
    return value


def require_list(value: object, code: str, detail: str) -> list[object]:
    if not isinstance(value, list):
        reject(code, detail)
    return value


def require_exact_keys(value: dict[str, object], keys: set[str], code: str, detail: str) -> None:
    if set(value) != keys:
        reject(code, f"{detail}: expected={sorted(keys)}, actual={sorted(value)}")


def safe_relative_path(root: Path, value: object, code: str = "fixture.unsafe_path") -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value:
        reject(code, f"path must be a non-empty POSIX relative path: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        reject(code, f"unsafe relative path: {value}")
    candidate = (root / Path(*pure.parts)).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        reject(code, f"path escapes contracts root: {value}")
    return pure.as_posix(), candidate


def parse_pointer(pointer: object) -> list[str]:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        reject("fixture.invalid_pointer", f"invalid JSON Pointer: {pointer}")
    segments: list[str] = []
    for raw in pointer.split("/")[1:] if pointer else []:
        index = 0
        decoded = ""
        while index < len(raw):
            if raw[index] != "~":
                decoded += raw[index]
                index += 1
                continue
            if index + 1 >= len(raw) or raw[index + 1] not in "01":
                reject("fixture.invalid_pointer", f"invalid JSON Pointer escape: {pointer}")
            decoded += "~" if raw[index + 1] == "0" else "/"
            index += 2
        segments.append(decoded)
    return segments


def pointer_target(document: object, pointer: object) -> tuple[object, str | int]:
    segments = parse_pointer(pointer)
    if not segments:
        reject("fixture.invalid_pointer", "root replacement is not allowed by the fixture DSL")
    current = document
    for segment in segments[:-1]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            reject("fixture.invalid_pointer", f"pointer does not resolve: {pointer}")
    final: str | int = int(segments[-1]) if isinstance(current, list) and segments[-1].isdigit() else segments[-1]
    return current, final


def _step(action: str | None, condition: str, iteration: str, order: str, formula: str | None = None) -> dict[str, object]:
    return {"action": action, "condition": condition, "formula": formula, "iteration": iteration, "order": order}


def expected_keyword_rule(keyword: str) -> dict[str, object]:
    annotation_only = {"title", "description", "default", "deprecated", "readOnly", "writeOnly", "examples", "format", "contentEncoding", "contentMediaType", "contentSchema", "x-*"}
    semantic_visit_only = {"$schema", "$defs", "$comment"} | annotation_only
    schema_arrays = {"allOf", "anyOf", "oneOf", "prefixItems"}
    schema_maps = {"$defs", "dependentSchemas", "properties", "patternProperties"}
    schema_singles = {"not", "if", "then", "else", "items", "contains", "additionalProperties", "propertyNames", "unevaluatedItems", "unevaluatedProperties", "contentSchema"}
    applicators = ((schema_arrays | schema_maps | schema_singles) - {"$defs", "contentSchema"}) | {"$ref"}
    evaluated_properties = {"properties", "patternProperties", "additionalProperties", "unevaluatedProperties"}
    evaluated_items = {"prefixItems", "items", "contains", "unevaluatedItems"}
    admission = [_step("schema_keyword_visit", "always", "once", "keyword-ordinal")]
    if keyword == "$ref":
        admission.append(_step("ref_resolution", "keyword-value-present", "once", "keyword-ordinal"))
    elif keyword in schema_arrays:
        admission.append(_step("schema_array_element", "keyword-value-is-array", "schema-array-elements", "schema-array-order"))
    elif keyword in schema_maps:
        admission.append(_step("schema_map_member", "keyword-value-is-map", "map-values", "unsigned-utf8-bytes"))
        if keyword == "patternProperties":
            admission += [_step(None, "each-map-key", "map-keys", "unsigned-utf8-bytes", "regex_grammar_parse"), _step(None, "grammar-accepted", "ast-nodes", "construction-order", "regex_ast"), _step(None, "grammar-accepted", "ast-nodes", "construction-order", "regex_compact_counter")]
    elif keyword in schema_singles:
        admission.append(_step("single_schema_descent", "keyword-selects-schema", "once", "keyword-ordinal"))
    elif keyword == "pattern":
        admission += [_step(None, "keyword-value-present", "once", "keyword-ordinal", "json-value-cost"), _step(None, "keyword-value-is-string", "pattern-scalars", "scalar-order", "regex_grammar_parse"), _step(None, "grammar-accepted", "ast-nodes", "construction-order", "regex_ast"), _step(None, "grammar-accepted", "ast-nodes", "construction-order", "regex_compact_counter")]
    else:
        admission.append(_step(None, "keyword-value-present", "once", "keyword-ordinal", "json-value-cost"))

    semantic = [_step("keyword_visit", "always", "once", "keyword-ordinal")]
    if keyword == "$ref":
        semantic += [_step("ref_resolution", "keyword-applicable", "once", "keyword-ordinal"), _step("schema_instance_pair", "each-selected-subschema", "once", "keyword-ordinal")]
    elif keyword == "properties":
        semantic += [_step("map_member_visit", "each-declared-property", "declared-map-members", "unsigned-utf8-bytes"), _step("property_presence_or_membership_check", "each-declared-property", "declared-map-members", "unsigned-utf8-bytes"), _step("object_member_or_array_element_visit", "declared-property-present", "declared-map-members", "unsigned-utf8-bytes"), _step("schema_instance_pair", "declared-property-present", "declared-map-members", "unsigned-utf8-bytes"), _step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "declared-map-members", "unsigned-utf8-bytes")]
    elif keyword == "patternProperties":
        semantic += [_step("map_member_visit", "each-declared-pattern", "declared-map-members", "unsigned-utf8-bytes"), _step("object_member_or_array_element_visit", "each-actual-member", "actual-object-members", "unsigned-utf8-bytes"), _step(None, "each-actual-member-times-each-pattern", "actual-members-x-declared-patterns", "member-then-pattern-utf8", "regex_attempt"), _step("schema_instance_pair", "pattern-matched", "actual-members-x-declared-patterns", "member-then-pattern-utf8"), _step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "actual-members-x-declared-patterns", "member-then-pattern-utf8")]
    elif keyword == "dependentSchemas":
        semantic += [_step("map_member_visit", "each-dependent-declaration", "declared-map-members", "unsigned-utf8-bytes"), _step("property_presence_or_membership_check", "trigger-property", "declared-map-members", "unsigned-utf8-bytes"), _step("applicator_branch_entry", "trigger-present", "declared-map-members", "unsigned-utf8-bytes"), _step("schema_instance_pair", "trigger-present", "declared-map-members", "unsigned-utf8-bytes")]
    elif keyword == "dependentRequired":
        semantic += [_step("map_member_visit", "each-dependent-declaration", "declared-map-members", "unsigned-utf8-bytes"), _step("property_presence_or_membership_check", "trigger-property", "declared-map-members", "unsigned-utf8-bytes"), _step("object_member_or_array_element_visit", "trigger-present-each-dependency", "dependency-array-elements", "array-index"), _step("required_name_presence_check", "trigger-present-each-dependency", "dependency-array-elements", "array-index")]
    elif keyword == "contains":
        semantic += [_step("object_member_or_array_element_visit", "each-actual-array-element", "actual-array-elements", "array-index"), _step("schema_instance_pair", "each-actual-array-element", "actual-array-elements", "array-index"), _step("evaluated_set_new_marker", "contains-count-succeeded-new-marker", "matched-array-elements", "array-index")]
    elif keyword == "enum":
        semantic += [_step("object_member_or_array_element_visit", "each-enum-candidate", "enum-candidates", "schema-array-order"), _step(None, "each-enum-candidate-full-scan", "enum-candidates", "schema-array-order", "const_or_enum_jcs_compare")]
    elif keyword == "const":
        semantic.append(_step(None, "always", "once", "keyword-ordinal", "const_or_enum_jcs_compare"))
    elif keyword == "if":
        semantic += [_step("applicator_branch_entry", "evaluate-if-schema", "once", "if-then-else"), _step("schema_instance_pair", "evaluate-if-schema", "once", "if-then-else")]
    elif keyword in {"then", "else"}:
        semantic += [_step("applicator_branch_entry", "branch-selected-by-if", "selected-conditional", "if-then-else"), _step("schema_instance_pair", "selected-branch", "selected-conditional", "if-then-else")]
    elif keyword == "required":
        semantic += [_step("object_member_or_array_element_visit", "each-required-name", "required-array-elements", "array-index"), _step("required_name_presence_check", "each-required-name", "required-array-elements", "array-index")]
    elif keyword == "uniqueItems":
        semantic += [_step("object_member_or_array_element_visit", "each-actual-array-element", "actual-array-elements", "array-index"), _step(None, "each-actual-array-element", "actual-array-elements", "array-index", "unique_item_digest")]
    elif keyword == "pattern":
        semantic.append(_step(None, "instance-string", "once", "keyword-ordinal", "regex_attempt"))
    elif keyword == "additionalProperties":
        semantic += [_step("object_member_or_array_element_visit", "each-actual-member", "actual-object-members", "unsigned-utf8-bytes"), _step("property_presence_or_membership_check", "classify-additional-member", "actual-object-members", "unsigned-utf8-bytes"), _step("schema_instance_pair", "member-is-additional", "actual-object-members", "unsigned-utf8-bytes"), _step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "actual-object-members", "unsigned-utf8-bytes")]
    elif keyword == "unevaluatedProperties":
        semantic += [_step("object_member_or_array_element_visit", "each-actual-member", "actual-object-members", "unsigned-utf8-bytes"), _step("property_presence_or_membership_check", "evaluated-property-membership", "actual-object-members", "unsigned-utf8-bytes"), _step("schema_instance_pair", "member-not-evaluated", "actual-object-members", "unsigned-utf8-bytes"), _step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "actual-object-members", "unsigned-utf8-bytes")]
    elif keyword == "propertyNames":
        semantic += [_step("object_member_or_array_element_visit", "each-actual-member", "actual-object-members", "unsigned-utf8-bytes"), _step("applicator_branch_entry", "each-property-name", "actual-object-members", "unsigned-utf8-bytes"), _step("schema_instance_pair", "property-name-instance", "actual-object-members", "unsigned-utf8-bytes")]
    elif keyword in {"prefixItems", "items", "unevaluatedItems"}:
        condition = "prefix-index-covered" if keyword == "prefixItems" else "post-prefix-item" if keyword == "items" else "item-not-evaluated"
        semantic += [_step("object_member_or_array_element_visit", condition, "affected-array-elements", "array-index")]
        if keyword == "unevaluatedItems":
            semantic.append(_step("property_presence_or_membership_check", "evaluated-item-membership", "actual-array-elements", "array-index"))
        semantic += [_step("schema_instance_pair", condition, "affected-array-elements", "array-index"), _step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "affected-array-elements", "array-index")]
    elif keyword in applicators:
        semantic += [_step("applicator_branch_entry", "keyword-applicable", "applicator-branches", "schema-array-order"), _step("schema_instance_pair", "each-selected-subschema", "applicator-branches", "schema-array-order")]
        if keyword in evaluated_properties:
            semantic.append(_step("evaluated_set_new_marker", "subschema-succeeded", "map-values", "unsigned-utf8-bytes"))
        if keyword in evaluated_items:
            semantic.append(_step("evaluated_set_new_marker", "subschema-succeeded", "all-array-items", "index-ascending"))
    elif keyword not in semantic_visit_only:
        numeric = {"multipleOf", "maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum", "maxLength", "minLength", "maxItems", "minItems", "maxProperties", "minProperties", "minContains", "maxContains"}
        if keyword in numeric:
            semantic.append(_step("numeric_assertion", "keyword-applicable", "once", "keyword-ordinal"))
    return {
        "admission_steps": admission,
        "annotation_rule": "discard-always" if keyword == "not" else "evaluated-properties" if keyword in {"properties", "patternProperties"} else "evaluated-items-on-count-success" if keyword == "contains" else "propagate-selected-success" if keyword in {"if", "then", "else"} else "collect-on-success" if keyword in annotation_only else "propagate-success-only" if keyword in applicators else "none",
        "evaluated_set_rule": "properties-on-success" if keyword in evaluated_properties else "items-on-success" if keyword in evaluated_items else "none",
        "semantic_steps": semantic,
    }


def validate_profile(value: object) -> None:
    profile = require_object(value, "profile.invalid_manifest", "profile must be an object")
    require_exact_keys(
        profile,
        {
            "canonical_json", "compatibility", "conformance", "diagnostics",
            "implementation_roles", "normative_artifacts", "portable_limits",
            "profile_id", "profile_version", "publication", "references",
            "regex_profile", "schema_draft", "schema_profile", "work_units",
        },
        "profile.machine_decision_drift",
        "profile top-level closure changed",
    )
    exact = {
        "profile_id": "org.intelliengine.conformance",
        "profile_version": PROFILE_VERSION,
        "schema_draft": "https://json-schema.org/draft/2020-12/schema",
        "implementation_roles": {"normative_implementation": "none", "primary": "typescript", "secondary": "python-independent", "shared_validator": "forbidden"},
        "normative_artifacts": {"categories": ["profile", "schemas", "diagnostics", "fixtures", "lock"], "priority": ["accepted-adr", "machine-artifacts", "conforming-implementations", "documentation"]},
        "conformance": {"consumer_count": 2, "comparison": "exact-normative-projection", "expected_result_required": True, "primary_consumer_priority_on_mismatch": False},
        "publication": {"compatibility": "major-explicit-minor-opt-in", "mode": "shadow-until-two-consumers-conform", "old_major_read_only_minimum_release_cycles": 1},
        "compatibility": {"contract_profile_binding": "explicit-major", "minor_upgrade": "explicit-lock-change", "old_major_mode": "read-only", "old_major_minimum_release_cycles": 1},
        "references": {"cross_resource": "digest-uri-dag-only", "digest_uri_prefix": "urn:intelliengine:schema:sha256:", "external_fallback": "forbidden", "local_fragment_recursion": "instance-location-must-descend", "non_productive_local_cycle": "reject-at-admission"},
        "canonical_json": {"digest": "sha-256-lowercase-hex", "format": "RFC-8785-JCS", "integer_maximum": SAFE_INTEGER, "integer_minimum": -SAFE_INTEGER, "jcs_key_order": "unsigned-utf16-code-units", "normalization": "none", "raw_input_requirements": ["utf8-without-bom", "no-duplicate-members", "unicode-scalars-only", "finite-binary64-numbers"], "validator_order": "unsigned-utf8-bytes"},
        "diagnostics": {"catalog": "diagnostics/conformance.json", "maximum_per_phase": 100, "sort_order": ["path-utf8", "severity", "code-utf8", "details-jcs"]},
    }
    for key, expected in exact.items():
        if profile.get(key) != expected:
            reject("profile.machine_decision_drift", f"accepted machine decision changed: {key}")

    schema_profile = require_object(profile.get("schema_profile"), "profile.invalid_manifest", "schema_profile must be an object")
    ordinals = require_object(schema_profile.get("keyword_ordinals"), "profile.invalid_manifest", "keyword_ordinals must be an object")
    if not ordinals or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in ordinals.values()):
        reject("profile.invalid_keyword_ordinal", "ordinals must be non-negative integers")
    if len(ordinals.values()) != len(set(ordinals.values())):
        reject("profile.duplicate_keyword_ordinal", "keyword ordinals must be unique")
    allowed = require_list(schema_profile.get("allowed_keywords"), "profile.invalid_manifest", "allowed_keywords must be an array")
    if tuple(allowed) != EXPECTED_ALLOWED_KEYWORDS or set(allowed) != set(ordinals):
        reject("profile.keyword_catalog_mismatch", "allowed keywords and ordinals differ")
    expected_schema_decisions = {
        "annotation_only_keywords": ["title", "description", "default", "deprecated", "readOnly", "writeOnly", "examples", "format", "contentEncoding", "contentMediaType", "contentSchema", "x-*"],
        "forbidden_keywords": ["$id", "$anchor", "$dynamicRef", "$dynamicAnchor", "$vocabulary"],
        "unknown_x_annotation": "preserve-without-schema-scan",
        "evaluation_rules": {"allOf": "evaluate-all-propagate-only-if-all-succeed", "anyOf": "evaluate-all-propagate-all-successful-branches", "contains": "evaluate-all-propagate-indexes-only-if-count-succeeds", "failed_schema_annotations": "discard", "if_then_else": "evaluate-if-and-selected-branch-only", "not": "always-discard-subschema-annotations", "oneOf": "evaluate-all-propagate-only-the-sole-successful-branch", "ref_siblings": "evaluate-by-ordinal", "unevaluated": "evaluate-last-after-successful-annotation-merge"},
    }
    for key, expected in expected_schema_decisions.items():
        if schema_profile.get(key) != expected:
            reject("profile.machine_decision_drift", f"schema-profile decision changed: {key}")

    expected_limits = {
        "bundle_resources": 128, "cognitive_node_jcs_bytes": 1_048_576,
        "diagnostics_per_phase": 100, "json_depth": 64,
        "json_members_and_elements": 100_000, "ref_chain": 64,
        "regex_unicode_scalars": 1_024, "schema_admission_work_units": 250_000,
        "semantic_validation_work_units": 1_000_000, "single_array_items": 10_000,
        "single_string_utf8_bytes": 262_144, "type_definition_bundle_jcs_bytes": 2_097_152,
    }
    if profile.get("portable_limits") != expected_limits:
        reject("profile.machine_decision_drift", "portable limits changed")
    regex_profile = require_object(profile.get("regex_profile"), "profile.invalid_manifest", "regex_profile must be object")
    if set(regex_profile) != {"ast_nodes", "case_sensitive", "forbidden", "matching", "maximum_repeat", "productions", "quantifier_constraints", "terminals", "unicode_domain"}:
        reject("profile.machine_decision_drift", "regex grammar is not structural")
    if regex_profile.get("case_sensitive") is not True or regex_profile.get("matching") != "unanchored-search" or regex_profile.get("maximum_repeat") != 10_000 or regex_profile.get("unicode_domain") != "scalar-values":
        reject("profile.machine_decision_drift", "regex scalar decisions changed")
    if regex_profile.get("ast_nodes") != ["literal", "dot", "anchor", "class", "class-range", "concatenation", "alternation", "group", "quantifier"] or regex_profile.get("quantifier_constraints") != {"greedy_only": True, "group_with_alternation_or_quantifier_may_be_quantified": False, "maximum": 10_000, "minimum": 0}:
        reject("profile.machine_decision_drift", "regex AST or quantifier decisions changed")
    expected_forbidden_regex = ["backreference", "lookaround", "named-group", "atomic-group", "conditional-group", "inline-flag", "lazy-quantifier", "possessive-quantifier", "implementation-private-escape", "unicode-property-escape", "quantified-group-containing-quantifier-or-alternation"]
    if regex_profile.get("forbidden") != expected_forbidden_regex:
        reject("profile.machine_decision_drift", "forbidden regex constructs changed")
    terminals = require_list(regex_profile.get("terminals"), "profile.machine_decision_drift", "regex terminals missing")
    terminal_names = set()
    allowed_repeats = {"once", "optional", "zero-or-more"}
    for terminal_value in terminals:
        terminal = require_object(terminal_value, "profile.machine_decision_drift", "regex terminal must be object")
        require_exact_keys(terminal, {"lexeme", "machine_predicate", "name", "token_kind"}, "profile.machine_decision_drift", "regex terminal is not closed")
        predicate = terminal.get("machine_predicate")
        if terminal.get("lexeme") is None and predicate is None:
            reject("profile.machine_decision_drift", "regex terminal has neither lexeme nor predicate")
        if predicate is not None:
            predicate_object = require_object(predicate, "profile.machine_decision_drift", "regex predicate must be object")
            require_exact_keys(predicate_object, {"kind", "values"}, "profile.machine_decision_drift", "regex predicate is not closed")
            if predicate_object.get("kind") not in {"unicode-scalar-excluding", "escape-literal-catalog", "bounded-repeat"} or not require_list(predicate_object.get("values"), "profile.machine_decision_drift", "regex predicate catalog missing"):
                reject("profile.machine_decision_drift", "regex predicate is not machine-readable")
        terminal_names.add(terminal.get("name"))
    expected_terminals = [
        {"lexeme": None, "machine_predicate": {"kind": "unicode-scalar-excluding", "values": ["\\", ".", "^", "$", "[", "]", "(", ")", "|", "*", "+", "?", "{", "}"]}, "name": "literal", "token_kind": "scalar"},
        {"lexeme": "\\", "machine_predicate": {"kind": "escape-literal-catalog", "values": [".", "*", "+", "?", "[", "]", "(", ")", "{", "}", "|", "^", "$", "\\"]}, "name": "escape", "token_kind": "escaped-scalar"},
        {"lexeme": ".", "machine_predicate": None, "name": "dot", "token_kind": "punctuation"},
        {"lexeme": "^", "machine_predicate": None, "name": "start-anchor", "token_kind": "punctuation"},
        {"lexeme": "$", "machine_predicate": None, "name": "end-anchor", "token_kind": "punctuation"},
        {"lexeme": "[", "machine_predicate": None, "name": "class-open", "token_kind": "punctuation"},
        {"lexeme": "]", "machine_predicate": None, "name": "class-close", "token_kind": "punctuation"},
        {"lexeme": "^", "machine_predicate": None, "name": "negation", "token_kind": "punctuation"},
        {"lexeme": "-", "machine_predicate": None, "name": "range-separator", "token_kind": "punctuation"},
        {"lexeme": "|", "machine_predicate": None, "name": "pipe", "token_kind": "punctuation"},
        {"lexeme": "(", "machine_predicate": None, "name": "group-open", "token_kind": "punctuation"},
        {"lexeme": ")", "machine_predicate": None, "name": "group-close", "token_kind": "punctuation"},
        {"lexeme": "*", "machine_predicate": None, "name": "star", "token_kind": "quantifier"},
        {"lexeme": "+", "machine_predicate": None, "name": "plus", "token_kind": "quantifier"},
        {"lexeme": "?", "machine_predicate": None, "name": "question", "token_kind": "quantifier"},
        {"lexeme": "{m}|{m,n}", "machine_predicate": {"kind": "bounded-repeat", "values": ["{m}", "{m,n}", "0<=m<=n<=10000"]}, "name": "bounded-repeat", "token_kind": "quantifier"},
    ]
    if terminals != expected_terminals:
        reject("profile.machine_decision_drift", "regex lexical catalog changed")
    productions = require_list(regex_profile.get("productions"), "profile.machine_decision_drift", "regex productions missing")
    production_names = {require_object(item, "profile.machine_decision_drift", "production must be object").get("name") for item in productions}
    if terminal_names & production_names:
        reject("profile.machine_decision_drift", "regex terminal and production names overlap")
    if production_names != {"pattern", "alternation", "alternation-tail", "concatenation", "quantified-atom", "atom", "character-class", "class-item", "range", "group", "quantifier"}:
        reject("profile.machine_decision_drift", "regex production catalog changed")
    for item in productions:
        production = require_object(item, "profile.machine_decision_drift", "production must be object")
        require_exact_keys(production, {"alternatives", "name"}, "profile.machine_decision_drift", "production is not closed")
        for alternative in require_list(production.get("alternatives"), "profile.machine_decision_drift", "alternatives must be array"):
            for symbol_value in require_list(alternative, "profile.machine_decision_drift", "alternative must be array"):
                symbol = require_object(symbol_value, "profile.machine_decision_drift", "symbol must be object")
                require_exact_keys(symbol, {"name", "repeat"}, "profile.machine_decision_drift", "symbol is not closed")
                if symbol.get("name") not in terminal_names | production_names or symbol.get("repeat") not in allowed_repeats:
                    reject("profile.machine_decision_drift", "regex symbol or repeat is not accepted")
    if not {"literal", "escape", "start-anchor", "end-anchor", "class-open", "class-close", "range-separator", "negation"}.issubset(terminal_names):
        reject("profile.machine_decision_drift", "regex lexical terminals are incomplete")
    expected_terminal_names = {"literal", "escape", "dot", "start-anchor", "end-anchor", "class-open", "class-close", "negation", "range-separator", "pipe", "group-open", "group-close", "star", "plus", "question", "bounded-repeat"}
    if terminal_names != expected_terminal_names:
        reject("profile.machine_decision_drift", "regex terminal catalog changed")
    work_units = require_object(profile.get("work_units"), "profile.invalid_manifest", "work_units must be object")
    if set(work_units) != {"admission_actions", "admission_formulas", "admission_limit", "budget_rule", "diagnostics_cost_units", "formula_language", "json_value_cost", "keyword_rules", "precharge_and_stop", "semantic_actions", "semantic_formulas", "semantic_limit", "traversal"}:
        reject("profile.machine_decision_drift", "work-unit tables are incomplete")
    if work_units.get("admission_limit") != 250_000 or work_units.get("semantic_limit") != 1_000_000 or work_units.get("budget_rule") != "precharge-whole-action-or-stop" or work_units.get("diagnostics_cost_units") != 0 or work_units.get("formula_language") != "integer-expression-v1":
        reject("profile.machine_decision_drift", "work-unit scalar decisions changed")
    if work_units.get("precharge_and_stop") != {"exceeding_action_executed": False, "partial_charge": False, "partial_object_result": False, "resource_diagnostic_cost_units": 0}:
        reject("profile.machine_decision_drift", "work-unit precharge/stop decisions changed")
    if work_units.get("json_value_cost") != {"array": {"base": 1, "per_element": 1, "recursive_value_cost": True}, "object": {"base": 1, "member_order": "unsigned-utf8-bytes", "per_member": 1, "recursive_value_cost": True}, "scalar_or_null": 1}:
        reject("profile.machine_decision_drift", "JSON value cost changed")
    expected_work_tables = {
        "admission_actions": {"graph_edge": 1, "graph_vertex": 1, "json_array_base": 1, "json_array_element": 1, "json_object_base": 1, "json_object_member": 1, "json_scalar_or_null": 1, "ref_resolution": 1, "schema_array_element": 1, "schema_keyword_visit": 1, "schema_location_entry": 1, "schema_map_member": 1, "single_schema_descent": 1},
        "admission_formulas": {"regex_ast": "1+ast_nodes", "regex_compact_counter": "1+ast_nodes", "regex_grammar_parse": "1+pattern_scalars", "resource_digest": "1+ceil(resource_jcs_bytes/256)"},
        "semantic_actions": {"applicator_branch_entry": 1, "evaluated_set_new_marker": 1, "keyword_visit": 1, "map_member_visit": 1, "numeric_assertion": 1, "object_member_or_array_element_visit": 1, "property_presence_or_membership_check": 1, "ref_resolution": 1, "required_name_presence_check": 1, "schema_instance_pair": 1},
        "semantic_formulas": {"const_or_enum_jcs_compare": "1+ceil(candidate_jcs_bytes/256)+ceil(instance_jcs_bytes/256)", "regex_attempt": "1+pattern_scalars+input_scalars", "unique_item_digest": "1+ceil(item_jcs_bytes/256)"},
        "traversal": {"arrays": "index-ascending", "combiners": "schema-array-order", "maps_and_instance_members": "unsigned-utf8-bytes", "schema_keywords": "keyword-ordinal"},
    }
    for key, expected in expected_work_tables.items():
        if work_units.get(key) != expected:
            reject("profile.machine_decision_drift", f"work-unit table changed: {key}")
    rules = require_object(work_units.get("keyword_rules"), "profile.invalid_manifest", "keyword_rules must be object")
    if set(rules) != set(EXPECTED_ALLOWED_KEYWORDS):
        reject("profile.machine_decision_drift", "keyword-specific work-unit rules are incomplete")
    for keyword, rule_value in rules.items():
        rule = require_object(rule_value, "profile.machine_decision_drift", f"keyword rule must be object: {keyword}")
        if rule != expected_keyword_rule(keyword):
            reject("profile.machine_decision_drift", f"keyword rule semantics changed: {keyword}")


def validate_diagnostics(value: object) -> None:
    document = require_object(value, "diagnostics.invalid_catalog", "diagnostics catalog must be object")
    require_exact_keys(document, {"diagnostics", "profile_version"}, "diagnostics.invalid_catalog", "catalog is not closed")
    entries = require_list(document.get("diagnostics"), "diagnostics.invalid_catalog", "diagnostics must be array")
    codes: list[str] = []
    for value in entries:
        entry = require_object(value, "diagnostics.invalid_catalog", "diagnostic entry must be object")
        require_exact_keys(entry, {"code", "phase", "severity"}, "diagnostics.invalid_catalog", "entry is not closed")
        if entry.get("severity") != "error" or not isinstance(entry.get("code"), str):
            reject("diagnostics.invalid_catalog", "diagnostic entry is invalid")
        codes.append(entry["code"])
    if len(codes) != len(set(codes)) or set(codes) != REQUIRED_DIAGNOSTICS:
        reject("diagnostics.invalid_catalog", "diagnostic catalog is incomplete")


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(target in graph and visit(target) for target in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False
    return any(visit(node) for node in graph)


def validate_expected(value: object, case_id: str) -> dict[str, object]:
    expected = require_object(value, "fixture.invalid_expected", f"expected result must be object: {case_id}")
    required = {"contract_id", "contract_version", "issues", "mode", "object_result", "operation_outcome", "profile_version", "raw_sha256", "work_units_consumed"}
    allowed = required | {"jcs_sha256"}
    if not required.issubset(expected) or not set(expected).issubset(allowed):
        reject("fixture.invalid_expected", f"expected projection is not closed: {case_id}")
    if (expected["object_result"], expected["operation_outcome"]) not in LEGAL_STATE_PAIRS:
        reject("fixture.illegal_state_pair", f"illegal expected state pair: {case_id}")
    if expected.get("profile_version") != PROFILE_VERSION or expected.get("contract_version") != PROFILE_VERSION:
        reject("fixture.invalid_expected", f"unexpected version: {case_id}")
    if not isinstance(expected.get("work_units_consumed"), int) or expected["work_units_consumed"] < 0:
        reject("fixture.invalid_expected", f"invalid work units: {case_id}")
    for field in ("raw_sha256", "jcs_sha256"):
        if field in expected and (not isinstance(expected[field], str) or HEX_64.fullmatch(expected[field]) is None):
            reject("fixture.invalid_expected", f"invalid digest: {case_id}/{field}")
    issues = require_list(expected.get("issues"), "fixture.invalid_expected", f"issues must be array: {case_id}")
    for issue in issues:
        item = require_object(issue, "fixture.invalid_expected", f"issue must be object: {case_id}")
        require_exact_keys(item, {"code", "path", "severity"}, "fixture.invalid_expected", "issue is not closed")
    return expected


SUPPORTED_MACHINE_SCHEMA_KEYWORDS = {
    "$defs", "$ref", "$schema", "additionalProperties", "allOf", "anyOf", "const",
    "else", "enum", "if", "items", "maximum", "maxItems", "minimum",
    "minItems", "oneOf", "pattern", "properties", "required", "then",
    "type", "uniqueItems",
}


def _schema_pointer(root_schema: dict[str, object], reference: str) -> object:
    if not reference.startswith("#/"):
        reject("profile.invalid_schema", f"unsupported local schema reference: {reference}")
    current: object = root_schema
    for raw in reference[2:].split("/"):
        segment = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or segment not in current:
            reject("profile.invalid_schema", f"unresolved local schema reference: {reference}")
        current = current[segment]
    return current


def _machine_schema_valid(instance: object, schema_value: object, root_schema: dict[str, object], registry: dict[str, dict[str, object]]) -> bool:
    schema = require_object(schema_value, "profile.invalid_schema", "machine schema node must be object")
    unsupported = set(schema) - SUPPORTED_MACHINE_SCHEMA_KEYWORDS
    if unsupported:
        reject("profile.invalid_schema", f"unsupported machine schema keywords: {sorted(unsupported)}")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            reject("profile.invalid_schema", "$ref must be a string")
        target = _schema_pointer(root_schema, reference) if reference.startswith("#/") else registry.get(reference)
        if target is None:
            reject("profile.invalid_schema", f"unresolved machine schema reference: {reference}")
        target_root = root_schema if reference.startswith("#/") else require_object(target, "profile.invalid_schema", "referenced schema must be object")
        if not _machine_schema_valid(instance, target, target_root, registry):
            return False
    expected_type = schema.get("type")
    type_checks = {
        "null": instance is None,
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "boolean": isinstance(instance, bool),
    }
    if expected_type is not None and (expected_type not in type_checks or not type_checks[expected_type]):
        return False
    if "const" in schema and instance != schema["const"]:
        return False
    if "enum" in schema and instance not in require_list(schema["enum"], "profile.invalid_schema", "enum must be array"):
        return False
    if isinstance(instance, str) and "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str) or re.search(pattern, instance) is None:
            return False
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            return False
        if "maximum" in schema and instance > schema["maximum"]:
            return False
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            return False
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            return False
        if schema.get("uniqueItems") is True and len({jcs_bytes(item) for item in instance}) != len(instance):
            return False
        if "items" in schema and any(not _machine_schema_valid(item, schema["items"], root_schema, registry) for item in instance):
            return False
    if isinstance(instance, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            reject("profile.invalid_schema", "required must be a string array")
        if any(key not in instance for key in required):
            return False
        properties = require_object(schema.get("properties", {}), "profile.invalid_schema", "properties must be object")
        for key, child_schema in properties.items():
            if key in instance and not _machine_schema_valid(instance[key], child_schema, root_schema, registry):
                return False
        extras = set(instance) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            return False
        if isinstance(additional, dict) and any(not _machine_schema_valid(instance[key], additional, root_schema, registry) for key in extras):
            return False
    if "allOf" in schema and any(not _machine_schema_valid(instance, branch, root_schema, registry) for branch in require_list(schema["allOf"], "profile.invalid_schema", "allOf must be array")):
        return False
    if "oneOf" in schema and sum(_machine_schema_valid(instance, branch, root_schema, registry) for branch in require_list(schema["oneOf"], "profile.invalid_schema", "oneOf must be array")) != 1:
        return False
    if "anyOf" in schema and not any(_machine_schema_valid(instance, branch, root_schema, registry) for branch in require_list(schema["anyOf"], "profile.invalid_schema", "anyOf must be array")):
        return False
    if "if" in schema:
        condition = _machine_schema_valid(instance, schema["if"], root_schema, registry)
        selected = schema.get("then") if condition else schema.get("else")
        if selected is not None and not _machine_schema_valid(instance, selected, root_schema, registry):
            return False
    return True


def _assert_machine_schema(instance: object, schema: dict[str, object], registry: dict[str, dict[str, object]], label: str) -> None:
    if not _machine_schema_valid(instance, schema, schema, registry):
        reject("profile.machine_schema_validation", f"artifact does not conform to machine schema: {label}")


def _locked_fixture_path(root: Path, value: object, locked: set[str]) -> Path:
    relative, path = safe_relative_path(root, value)
    if relative not in locked:
        reject("fixture.unlocked_path", f"fixture path is not covered by lock: {relative}")
    if not path.is_file():
        reject("fixture.missing_file", f"fixture input missing: {relative}")
    return path


def _issue_codes(expected: dict[str, object]) -> list[object]:
    return [item.get("code") for item in expected["issues"] if isinstance(item, dict)]


def _dry_count_trace(profile: dict[str, object], case_id: str, case: dict[str, object]) -> int:
    assertions = require_object(case.get("assertions"), "fixture.work_unit_trace_drift", f"assertions missing: {case_id}")
    trace = require_list(assertions.get("work_unit_trace"), "fixture.work_unit_trace_drift", f"work-unit trace missing: {case_id}")
    work_units = require_object(profile.get("work_units"), "profile.invalid_manifest", "work_units must be object")
    rules = require_object(work_units.get("keyword_rules"), "profile.invalid_manifest", "keyword rules missing")
    total = 0
    for value in trace:
        item = require_object(value, "fixture.work_unit_trace_drift", f"trace item must be object: {case_id}")
        require_exact_keys(item, {"expected_units", "formula_inputs", "iterations", "keyword", "machine_name", "phase", "source", "step_index"}, "fixture.work_unit_trace_drift", f"trace item is not closed: {case_id}")
        keyword, phase, source = item.get("keyword"), item.get("phase"), item.get("source")
        iterations, step_index = item.get("iterations"), item.get("step_index")
        if phase not in {"admission", "semantic"} or source not in {"keyword-step", "machine-action", "machine-formula"} or not isinstance(iterations, int) or iterations < 1:
            reject("fixture.work_unit_trace_drift", f"trace selector is invalid: {case_id}")
        inputs = require_object(item.get("formula_inputs"), "fixture.work_unit_trace_drift", f"formula inputs invalid: {case_id}/{keyword}")
        if source == "keyword-step":
            if not isinstance(keyword, str) or not isinstance(step_index, int) or step_index < 0 or item.get("machine_name") is not None:
                reject("fixture.work_unit_trace_drift", f"keyword trace selector differs: {case_id}")
            rule = require_object(rules.get(keyword), "fixture.work_unit_trace_drift", f"trace keyword missing: {case_id}/{keyword}")
            steps = require_list(rule.get(f"{phase}_steps"), "fixture.work_unit_trace_drift", f"trace phase missing: {case_id}/{keyword}")
            if step_index >= len(steps):
                reject("fixture.work_unit_trace_drift", f"trace step is out of range: {case_id}/{keyword}")
            step = require_object(steps[step_index], "fixture.work_unit_trace_drift", f"trace step invalid: {case_id}/{keyword}")
            action, formula = step.get("action"), step.get("formula")
        else:
            if keyword is not None or step_index is not None or not isinstance(item.get("machine_name"), str):
                reject("fixture.work_unit_trace_drift", f"machine trace selector differs: {case_id}")
            action = item["machine_name"] if source == "machine-action" else None
            formula = item["machine_name"] if source == "machine-formula" else None
        if action is not None:
            table_name = "admission_actions" if phase == "admission" else "semantic_actions"
            table = require_object(work_units.get(table_name), "profile.invalid_manifest", f"{table_name} missing")
            if inputs or action not in table or not isinstance(table[action], int):
                reject("fixture.work_unit_trace_drift", f"action trace differs: {case_id}/{keyword}")
            actual_units = table[action] * iterations
        elif formula == "json-value-cost":
            if set(inputs) != {"cost"} or not isinstance(inputs["cost"], int) or inputs["cost"] < 1:
                reject("fixture.work_unit_trace_drift", f"JSON value cost inputs differ: {case_id}")
            actual_units = inputs["cost"] * iterations
        elif formula == "resource_digest":
            if set(inputs) != {"resource_jcs_bytes"} or not isinstance(inputs["resource_jcs_bytes"], int) or inputs["resource_jcs_bytes"] < 0:
                reject("fixture.work_unit_trace_drift", f"resource digest inputs differ: {case_id}")
            actual_units = (1 + math.ceil(inputs["resource_jcs_bytes"] / 256)) * iterations
        elif formula in {"regex_grammar_parse"}:
            if set(inputs) != {"pattern_scalars"} or not isinstance(inputs["pattern_scalars"], int):
                reject("fixture.work_unit_trace_drift", f"regex grammar inputs differ: {case_id}")
            actual_units = (1 + inputs["pattern_scalars"]) * iterations
        elif formula in {"regex_ast", "regex_compact_counter"}:
            if set(inputs) != {"ast_nodes"} or not isinstance(inputs["ast_nodes"], int):
                reject("fixture.work_unit_trace_drift", f"regex AST inputs differ: {case_id}")
            actual_units = (1 + inputs["ast_nodes"]) * iterations
        else:
            reject("fixture.work_unit_trace_drift", f"unsupported trace formula: {case_id}/{formula}")
        if item.get("expected_units") != actual_units:
            reject("fixture.work_unit_trace_drift", f"trace units differ: {case_id}/{keyword}/{step_index}")
        total += actual_units
    expected = validate_expected(case.get("expected"), case_id)
    if expected.get("work_units_consumed") != total:
        reject("fixture.work_unit_trace_drift", f"trace total differs: {case_id}")
    return total


def _validate_action(root: Path, case_id: str, case: dict[str, object], expected: dict[str, object], locked: set[str]) -> None:
    action = require_object(case.get("action"), "fixture.invalid_action", f"action must be object: {case_id}")
    kind = action.get("kind")
    input_value = require_object(case.get("input"), "fixture.unsafe_path", f"input must be a closed path object: {case_id}")
    require_exact_keys(input_value, {"bundle", "instance", "primary", "schema"}, "fixture.invalid_case", f"input is not closed: {case_id}")
    bundle = require_list(input_value.get("bundle"), "fixture.invalid_case", f"bundle must be array: {case_id}")
    for path_value in bundle:
        _locked_fixture_path(root, path_value, locked)
    paths: dict[str, Path | None] = {}
    for field in ("instance", "primary", "schema"):
        value = input_value.get(field)
        if value is None:
            paths[field] = None
        elif field == "primary" and value == LOCK_PATH.as_posix() and kind in {"tamper", "append-lock-entry"}:
            _, paths[field] = safe_relative_path(root, value)
        else:
            paths[field] = _locked_fixture_path(root, value, locked)
    primary = paths["primary"]
    if primary is None:
        reject("fixture.invalid_case", f"primary input is required: {case_id}")

    if kind == "parse-negative":
        require_exact_keys(action, {"kind"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        raw = primary.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected["raw_sha256"] or "jcs_sha256" in expected:
            reject("fixture.digest_kind_mismatch", f"parser-negative digest projection differs: {case_id}")
        try:
            parse_json_bytes(raw, primary)
        except VerificationError:
            return
        reject("fixture.invalid_case", f"parser-negative input unexpectedly parsed: {case_id}")

    mutation_kinds = {"remove", "tamper", "append-lock-entry"}
    if kind not in mutation_kinds:
        raw = primary.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected["raw_sha256"]:
            reject("fixture.invalid_expected", f"raw digest differs from input: {case_id}")
        parsed = parse_json_bytes(raw, primary)
        if expected.get("jcs_sha256") != hashlib.sha256(jcs_bytes(parsed)).hexdigest():
            reject("fixture.invalid_expected", f"JCS digest differs from input: {case_id}")

    simple_kinds = {"verify-profile", "schema-admission", "semantic-validation", "transport", "verify-reference-graph"}
    if kind in simple_kinds:
        require_exact_keys(action, {"kind"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        return
    if kind == "remove":
        require_exact_keys(action, {"kind", "path"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        _locked_fixture_path(root, action.get("path"), locked)
        if "profile.missing_file" not in _issue_codes(expected):
            reject("fixture.invalid_action", f"remove action lacks missing-file result: {case_id}")
        return
    if kind == "replace":
        require_exact_keys(action, {"kind", "path", "pointer", "value"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        target = _locked_fixture_path(root, action.get("path"), locked)
        document = copy.deepcopy(load_json(target))
        container, key = pointer_target(document, action.get("pointer"))
        if isinstance(container, dict):
            if key not in container:
                reject("fixture.invalid_pointer", f"replace target missing: {case_id}")
            container[key] = action.get("value")
        elif isinstance(container, list) and isinstance(key, int) and key < len(container):
            container[key] = action.get("value")
        else:
            reject("fixture.invalid_pointer", f"replace target missing: {case_id}")
        try:
            if target == (root / PROFILE_PATH).resolve():
                validate_profile(document)
        except VerificationError as error:
            if error.code not in _issue_codes(expected):
                reject("fixture.invalid_action", f"replace result differs: {case_id}")
            return
        reject("fixture.invalid_action", f"replace action did not produce expected rejection: {case_id}")
    if kind == "tamper":
        require_exact_keys(action, {"kind", "operation", "path", "pointer"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        if action.get("operation") != "reverse-array":
            reject("fixture.invalid_action", f"unknown tamper operation: {case_id}")
        target = _locked_fixture_path(root, action.get("path"), locked)
        document = copy.deepcopy(load_json(target))
        container, key = pointer_target(document, action.get("pointer"))
        selected = container.get(key) if isinstance(container, dict) else container[key] if isinstance(container, list) and isinstance(key, int) and key < len(container) else None
        if not isinstance(selected, list):
            reject("fixture.invalid_pointer", f"tamper pointer is not an array: {case_id}")
        selected.reverse()
        declared = require_object(load_json(root / LOCK_PATH), "lock.invalid_manifest", "lock must be object")
        target_relative = target.relative_to(root).as_posix()
        current_digest = hashlib.sha256(jcs_bytes(load_json(target))).hexdigest()
        tampered_digest = hashlib.sha256(jcs_bytes(document)).hexdigest()
        entry = next((item for item in declared.get("entries", []) if isinstance(item, dict) and item.get("path") == target_relative), None)
        if not entry or (entry.get("sha256") == current_digest and entry.get("sha256") == tampered_digest) or "conformance.digest_mismatch" not in _issue_codes(expected):
            reject("fixture.invalid_action", f"tamper action does not prove digest mismatch: {case_id}")
        return
    if kind == "append-lock-entry":
        require_exact_keys(action, {"entry", "kind", "path"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        relative, target = safe_relative_path(root, action.get("path"))
        if relative != LOCK_PATH.as_posix() or target != (root / LOCK_PATH).resolve() or "lock.self_inclusion" not in _issue_codes(expected):
            reject("fixture.invalid_action", f"self-inclusion action differs: {case_id}")
        return
    if kind == "work-unit-boundary":
        require_exact_keys(action, {"kind", "limit", "next_action_units", "phase", "preconsumed"}, "fixture.invalid_action", f"action is not closed: {case_id}")
        phase = action.get("phase")
        limit = 250_000 if phase == "admission" else 1_000_000 if phase == "semantic" else None
        if limit is None or action.get("limit") != limit:
            reject("fixture.work_unit_boundary_drift", f"work-unit phase/limit differs: {case_id}")
        preconsumed, next_units = action.get("preconsumed"), action.get("next_action_units")
        if not isinstance(preconsumed, int) or not isinstance(next_units, int) or next_units < 1:
            reject("fixture.work_unit_boundary_drift", f"work-unit action is invalid: {case_id}")
        exhausted = preconsumed + next_units > limit
        resource_code = "type_definition.resource_exhausted" if phase == "admission" else "cognitive_node.resource_exhausted"
        assertions = require_object(case.get("assertions"), "fixture.invalid_case", f"assertions missing: {case_id}")
        if exhausted:
            if expected["work_units_consumed"] != preconsumed or expected["object_result"] != "not_evaluated" or expected["operation_outcome"] != "resource_exhausted" or _issue_codes(expected) != [resource_code] or assertions != {"no_partial_result": True, "resource_issue_count": 1, "stopped_action": "next-action"}:
                reject("fixture.work_unit_boundary_drift", f"exhaustion result differs: {case_id}")
        elif expected["work_units_consumed"] != preconsumed + next_units or expected["operation_outcome"] != "succeeded" or expected["issues"]:
            reject("fixture.work_unit_boundary_drift", f"successful boundary result differs: {case_id}")
        return
    reject("fixture.invalid_action", f"unknown fixture action kind: {kind}")


def validate_fixtures(root: Path, locked: set[str]) -> None:
    manifest = require_object(load_json(root / FIXTURE_MANIFEST_PATH), "fixture.invalid_manifest", "fixture manifest must be object")
    require_exact_keys(manifest, {"cases", "fixture_set_version", "profile_version", "schema"}, "fixture.invalid_manifest", "manifest is not closed")
    entries = require_list(manifest.get("cases"), "fixture.invalid_manifest", "manifest cases must be array")
    categories: set[str] = set()
    case_ids: set[str] = set()
    loaded: dict[str, dict[str, object]] = {}
    for value in entries:
        entry = require_object(value, "fixture.invalid_manifest", "manifest entry must be object")
        require_exact_keys(entry, {"case_id", "category", "path"}, "fixture.invalid_manifest", "manifest entry is not closed")
        case_id, category, relative = entry.get("case_id"), entry.get("category"), entry.get("path")
        if not all(isinstance(item, str) for item in (case_id, category, relative)):
            reject("fixture.invalid_manifest", "manifest fields must be strings")
        if case_id in case_ids:
            reject("fixture.invalid_manifest", f"duplicate case id: {case_id}")
        expected_path = f"{case_id}/case.json"
        if relative != expected_path:
            reject("fixture.id_path_mismatch", f"manifest path differs from id: {case_id}")
        case_ids.add(case_id)
        categories.add(category)
        manifest_case_path = f"{PROFILE_DIRECTORY.as_posix()}/fixtures/{relative}"
        case_path = _locked_fixture_path(root, manifest_case_path, locked)
        case = require_object(load_json(case_path, "fixture.missing_file"), "fixture.invalid_case", f"case must be object: {case_id}")
        if case.get("case_id") != case_id or case.get("category") != category:
            reject("fixture.id_path_mismatch", f"case identity differs from manifest: {case_id}")
        required_case = {"action", "assertions", "boundary", "case_id", "category", "expected", "input", "phase", "profile_version", "purpose", "resources"}
        if set(case) != required_case:
            reject("fixture.invalid_case", f"case is not closed: {case_id}")
        expected = validate_expected(case.get("expected"), case_id)
        _validate_action(root, case_id, case, expected, locked)
        loaded[case_id] = case
    if categories != REQUIRED_CATEGORIES or not REQUIRED_PARSER_CASES.issubset(case_ids):
        reject("fixture.coverage_mismatch", "required fixture categories or parser cases are missing")

    profile = require_object(load_json(root / PROFILE_PATH), "profile.invalid_manifest", "profile must be object")
    for traced_case_id in ("regex-grammar-boundary", "annotation-propagation", "local-object-recursion"):
        if traced_case_id not in loaded:
            reject("fixture.work_unit_trace_drift", f"required traced fixture missing: {traced_case_id}")
        _dry_count_trace(profile, traced_case_id, loaded[traced_case_id])
    regex_assertions = require_object(loaded["regex-grammar-boundary"].get("assertions"), "fixture.invalid_case", "regex assertions missing")
    expected_regex_vectors = [
        {"pattern": "a{4}", "result": "accept"},
        {"pattern": "a{1,4}", "result": "accept"},
        {"pattern": "a{4,1}", "result": "reject"},
        {"pattern": "\\.", "result": "accept"},
        {"pattern": "\\q", "result": "reject-private-escape"},
    ]
    if regex_assertions.get("declaration_vectors") != expected_regex_vectors:
        reject("fixture.regex_declaration_drift", "regex declaration vectors changed")

    object_case = loaded.get("local-object-recursion", {})
    array_case = loaded.get("local-array-recursion", {})
    if require_object(object_case.get("assertions"), "fixture.invalid_case", "object assertions missing").get("instance_location") != "strict-descendant-property" or require_object(array_case.get("assertions"), "fixture.invalid_case", "array assertions missing").get("instance_location") != "strict-descendant-array-item":
        reject("fixture.recursion_boundary_drift", "productive recursion boundary changed")
    nonproductive = require_object(loaded.get("local-nonproductive-cycle", {}).get("assertions"), "fixture.invalid_case", "nonproductive assertions missing")
    if nonproductive.get("productive") is not False or nonproductive.get("instance_location") != "unchanged":
        reject("fixture.recursion_boundary_drift", "nonproductive recursion boundary changed")
    sorting = require_object(loaded.get("sorting-utf16-vs-utf8", {}).get("assertions"), "fixture.invalid_case", "sorting assertions missing")
    if sorting.get("jcs_key_order") != ["😀", ""] or sorting.get("validator_key_order") != ["", "😀"]:
        reject("fixture.sorting_boundary_drift", "UTF-16 and UTF-8 order boundary changed")

    for case_id, should_cycle in (("cross-resource-dag", False), ("cross-resource-cycle-attempt", True)):
        case = loaded.get(case_id, {})
        assertions = require_object(case.get("assertions"), "fixture.invalid_case", f"assertions missing: {case_id}")
        graph_label = "cycle-attempt" if should_cycle else "dag"
        if assertions.get("graph") != graph_label:
            reject("fixture.reference_dag_drift", f"reference graph declaration changed: {case_id}")
        graph: dict[str, list[str]] = {}
        mismatch = False
        for resource_value in require_list(case.get("resources"), "fixture.invalid_case", f"resources missing: {case_id}"):
            resource = require_object(resource_value, "fixture.invalid_case", f"resource must be object: {case_id}")
            path_value = resource.get("path")
            if not isinstance(path_value, str):
                reject("fixture.invalid_case", f"resource path missing: {case_id}")
            path = _locked_fixture_path(root, path_value, locked)
            parsed = load_json(path, "fixture.missing_file")
            actual = hashlib.sha256(jcs_bytes(parsed)).hexdigest()
            if resource.get("actual_sha256") != actual:
                reject("fixture.invalid_case", f"resource actual digest differs: {case_id}")
            mismatch = mismatch or resource.get("claimed_sha256") != actual
            graph[str(resource.get("uri"))] = list(resource.get("refs", []))
        if _has_cycle(graph) != should_cycle:
            reject("fixture.reference_dag_drift", f"reference graph topology differs: {case_id}")
        if should_cycle:
            expected = validate_expected(case.get("expected"), case_id)
            issue_codes = {item.get("code") for item in expected["issues"] if isinstance(item, dict)}
            if not mismatch or expected["operation_outcome"] == "succeeded" or "conformance.digest_mismatch" not in issue_codes:
                reject("fixture.cross_resource_cycle_expectation", "cycle attempt must prove a digest mismatch before evaluation")
        elif mismatch:
            reject("fixture.reference_dag_drift", "valid DAG contains a digest mismatch")


def validate_schemas(root: Path) -> None:
    schema_root = root / SCHEMA_DIRECTORY
    names = {path.name for path in schema_root.glob("*.json")}
    if names != REQUIRED_SCHEMAS:
        reject("profile.schema_catalog_mismatch", f"machine schema catalog differs: {sorted(names)}")
    schemas: dict[str, dict[str, object]] = {}
    for name in sorted(names):
        schema = require_object(load_json(schema_root / name), "profile.invalid_schema", f"schema must be object: {name}")
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            reject("profile.invalid_schema", f"schema root is not closed: {name}")
        schemas[name] = schema
    expected_digest = hashlib.sha256(jcs_bytes(schemas["expected-result.schema.json"])).hexdigest()
    case_properties = require_object(schemas["fixture-case.schema.json"].get("properties"), "profile.invalid_schema", "case properties missing")
    expected_property = require_object(case_properties.get("expected"), "profile.invalid_schema", "case expected ref missing")
    if expected_property.get("$ref") != f"urn:intelliengine:schema:sha256:{expected_digest}":
        reject("profile.invalid_schema", "fixture case expected-result digest ref differs")
    case_schema = schemas["fixture-case.schema.json"]
    if set(case_schema.get("required", [])) != {"action", "assertions", "boundary", "case_id", "category", "expected", "input", "phase", "profile_version", "purpose", "resources"}:
        reject("profile.invalid_schema", "fixture-case required fields differ")
    input_schema = require_object(require_object(case_properties.get("input"), "profile.invalid_schema", "case input schema missing"), "profile.invalid_schema", "case input schema missing")
    if input_schema.get("additionalProperties") is not False or set(input_schema.get("required", [])) != {"bundle", "instance", "primary", "schema"}:
        reject("profile.invalid_schema", "fixture input schema is not closed")
    entry_schema = require_object(require_object(require_object(schemas["lock.schema.json"].get("properties"), "profile.invalid_schema", "lock properties missing").get("entries"), "profile.invalid_schema", "lock entries missing").get("items"), "profile.invalid_schema", "lock entry schema missing")
    expected_conditions = [
        {"if": {"properties": {"digest_kind": {"const": "jcs_sha256"}}, "required": ["digest_kind"]}, "then": {"properties": {"path": {"pattern": "^profile/1\\.0\\.0/.+\\.json$"}}}},
        {"if": {"properties": {"digest_kind": {"const": "raw_sha256"}}, "required": ["digest_kind"]}, "then": {"properties": {"path": {"pattern": "^profile/1\\.0\\.0/fixtures/raw/[^/]+\\.raw$"}}}},
    ]
    if entry_schema.get("additionalProperties") is not False or entry_schema.get("allOf") != expected_conditions:
        reject("profile.lock_schema_conflict", "lock digest-kind/path constraints differ")
    expected_state_closure = [{"oneOf": [
        {"properties": {"object_result": {"const": "valid"}, "operation_outcome": {"const": "succeeded"}}},
        {"properties": {"object_result": {"const": "invalid"}, "operation_outcome": {"const": "succeeded"}}},
        {"properties": {"object_result": {"const": "opaque"}, "operation_outcome": {"enum": ["succeeded", "indeterminate", "policy_denied"]}}},
        {"properties": {"object_result": {"const": "not_evaluated"}, "operation_outcome": {"enum": ["resource_exhausted", "indeterminate"]}}},
    ]}]
    if schemas["expected-result.schema.json"].get("allOf") != expected_state_closure:
        reject("profile.expected_schema_conflict", "expected-result legal state closure differs")

def validate_machine_artifacts(root: Path) -> None:
    schemas = {name: require_object(load_json(root / SCHEMA_DIRECTORY / name), "profile.invalid_schema", f"schema must be object: {name}") for name in REQUIRED_SCHEMAS}
    registry = {f"urn:intelliengine:schema:sha256:{hashlib.sha256(jcs_bytes(schema)).hexdigest()}": schema for schema in schemas.values()}
    _assert_machine_schema(load_json(root / PROFILE_PATH), schemas["profile.schema.json"], registry, PROFILE_PATH.as_posix())
    _assert_machine_schema(load_json(root / DIAGNOSTICS_PATH), schemas["diagnostics.schema.json"], registry, DIAGNOSTICS_PATH.as_posix())
    _assert_machine_schema(load_json(root / LOCK_PATH), schemas["lock.schema.json"], registry, LOCK_PATH.as_posix())
    manifest = load_json(root / FIXTURE_MANIFEST_PATH)
    _assert_machine_schema(manifest, schemas["fixture-manifest.schema.json"], registry, FIXTURE_MANIFEST_PATH.as_posix())
    manifest_object = require_object(manifest, "fixture.invalid_manifest", "fixture manifest must be object")
    for entry_value in require_list(manifest_object.get("cases"), "fixture.invalid_manifest", "manifest cases must be array"):
        entry = require_object(entry_value, "fixture.invalid_manifest", "manifest entry must be object")
        relative = entry.get("path")
        case_relative = f"{PROFILE_DIRECTORY.as_posix()}/fixtures/{relative}"
        _, case_path = safe_relative_path(root, case_relative)
        case = load_json(case_path, "fixture.missing_file")
        _assert_machine_schema(case, schemas["fixture-case.schema.json"], registry, case_relative)


def declared_lock_paths(root: Path) -> set[str]:
    lock = require_object(load_json(root / LOCK_PATH), "lock.invalid_manifest", "lock must be object")
    entries = require_list(lock.get("entries"), "lock.invalid_manifest", "lock entries must be array")
    declared: set[str] = set()
    for value in entries:
        entry = require_object(value, "lock.invalid_manifest", "lock entry must be object")
        relative, _ = safe_relative_path(root, entry.get("path"), "lock.invalid_path")
        if relative in declared:
            reject("lock.duplicate_path", f"duplicate lock path: {relative}")
        declared.add(relative)
    return declared


def validate_lock(root: Path) -> None:
    lock = require_object(load_json(root / LOCK_PATH), "lock.invalid_manifest", "lock must be object")
    require_exact_keys(lock, {"entries", "profile_version", "self_digest"}, "lock.invalid_manifest", "lock is not closed")
    entries = require_list(lock.get("entries"), "lock.invalid_manifest", "lock entries must be array")
    lock_relative = LOCK_PATH.as_posix()
    locked: set[str] = set()
    for value in entries:
        entry = require_object(value, "lock.invalid_manifest", "lock entry must be object")
        require_exact_keys(entry, {"digest_kind", "path", "sha256"}, "lock.invalid_manifest", "lock entry is not closed")
        kind, path_value, digest = entry.get("digest_kind"), entry.get("path"), entry.get("sha256")
        if kind not in {"jcs_sha256", "raw_sha256"}:
            reject("lock.invalid_digest_kind", f"unsupported digest kind: {kind}")
        if not isinstance(path_value, str) or not isinstance(digest, str) or HEX_64.fullmatch(digest) is None:
            reject("lock.invalid_manifest", "lock entry fields are invalid")
        pure = PurePosixPath(path_value)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path_value or pure.parts[:2] != ("profile", PROFILE_VERSION):
            reject("lock.invalid_path", f"unsafe lock path: {path_value}")
        if path_value == lock_relative:
            reject("lock.self_inclusion", "lock must not include itself")
        if path_value in locked:
            reject("lock.duplicate_path", f"duplicate lock path: {path_value}")
        locked.add(path_value)
        artifact = root / Path(*pure.parts)
        if not artifact.is_file():
            reject("lock.missing_artifact", f"locked artifact missing: {path_value}")
        if kind == "raw_sha256":
            if "/fixtures/raw/" not in f"/{path_value}" or path_value.endswith(".json"):
                reject("lock.digest_kind_mismatch", f"raw digest used outside parser-negative bytes: {path_value}")
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        else:
            if not path_value.endswith(".json"):
                reject("lock.digest_kind_mismatch", f"JCS digest used for non-JSON bytes: {path_value}")
            actual = hashlib.sha256(jcs_bytes(load_json(artifact))).hexdigest()
        if actual != digest:
            reject("conformance.digest_mismatch", f"digest mismatch: {path_value}")
    normative_root = root / PROFILE_DIRECTORY
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in normative_root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != lock_relative
    }
    if locked != actual_paths:
        reject("lock.coverage_mismatch", f"lock coverage differs; missing={sorted(actual_paths-locked)}, extra={sorted(locked-actual_paths)}")


def verify(root: Path) -> None:
    locked = declared_lock_paths(root)
    validate_profile(load_json(root / PROFILE_PATH))
    validate_diagnostics(load_json(root / DIAGNOSTICS_PATH))
    validate_schemas(root)
    validate_fixtures(root, locked)
    validate_lock(root)
    validate_machine_artifacts(root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify portable profile self-consistency")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        verify(args.root.resolve())
    except VerificationError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return 1
    print(f"portable profile {PROFILE_VERSION} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
