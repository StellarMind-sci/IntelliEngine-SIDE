from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COGNITIVE_IR_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
if str(COGNITIVE_IR_PYTHON) not in sys.path:
    sys.path.insert(0, str(COGNITIVE_IR_PYTHON))

from intelliengine_conformance.json_codec import canonicalize, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid


JsonObject = dict[str, Any]
SAFE_INTEGER = 9_007_199_254_740_991
UUID_V7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ARTIFACT_PATH = re.compile(r"^[a-z0-9][a-z0-9._/-]*\.json$")
REQUIRED_FIELDS = [
    "contract_version", "id", "revision", "display_name", "persona", "goals",
    "working_style", "declared_capabilities", "collaboration_preferences", "provenance_refs",
]
FORBIDDEN_RUNTIME_FIELDS = {
    "runtime_state", "memory", "private_memory", "model", "model_binding",
    "permission", "permissions", "team", "project",
}
REQUIRED_SCHEMA_PATHS = {
    "agent_profile": "schemas/agent-profile.schema.json",
    "agent_profile_ref": "schemas/agent-profile-ref.schema.json",
    "reference_snapshot": "schemas/reference-snapshot.schema.json",
    "diagnostic": "schemas/diagnostic.schema.json",
    "validation_result": "schemas/validation-result.schema.json",
    "fixture_suite": "schemas/fixture-suite.schema.json",
    "lock": "schemas/lock.schema.json",
}


def _load(path: Path) -> Any:
    return parse_json_bytes(path.read_bytes())


def _artifact_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ARTIFACT_PATH.fullmatch(relative) is None:
        raise ValueError("invalid artifact path")
    portable = PurePosixPath(relative)
    if portable.is_absolute() or any(part in {"", ".", ".."} for part in portable.parts):
        raise ValueError("invalid artifact path")
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*portable.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError("invalid artifact path") from error
    return candidate


def _is_utf8_encodable(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(value, list):
        return all(_is_utf8_encodable(item) for item in value)
    if isinstance(value, dict):
        return all(_is_utf8_encodable(key) and _is_utf8_encodable(item) for key, item in value.items())
    return True

def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "warning" if code == "agent_profile.compatible_read" else "error"}


def _result(mode: str, object_result: str, operation_outcome: str, issue: JsonObject | None = None) -> JsonObject:
    return {
        "interface": "agent_profile",
        "mode": mode,
        "object_result": object_result,
        "operation_outcome": operation_outcome,
        "issues": [] if issue is None else [issue],
    }


def _invalid(mode: str, code: str, path: str) -> JsonObject:
    return _result(mode, "invalid", "succeeded", _issue(code, path))


def _indeterminate(code: str, path: str) -> JsonObject:
    return _result("reference", "not_evaluated", "indeterminate", _issue(code, path))


def _semver(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or (match := SEMVER.fullmatch(value)) is None:
        return None
    return tuple(int(part) for part in match.groups())


def _canonical_string_set(value: Any, *, required: bool) -> bool | None:
    if not isinstance(value, list) or (required and not value):
        return None
    try:
        encoded = [item.encode("utf-8") if isinstance(item, str) and item else None for item in value]
    except UnicodeEncodeError:
        return None
    if any(item is None for item in encoded):
        return None
    return len(encoded) == len(set(encoded)) and encoded == sorted(encoded)


def _schema(root: Path | None = None) -> JsonObject:
    if root is None:
        base = REPOSITORY_ROOT / "packages" / "agent-runtime" / "contracts" / "agent-profile" / "1.0.0"
        return _load(base / "schemas" / "agent-profile.schema.json")
    return _load(_artifact_path(root, "schemas/agent-profile.schema.json"))


def _reference_schema(root: Path | None = None) -> JsonObject:
    if root is None:
        base = REPOSITORY_ROOT / "packages" / "agent-runtime" / "contracts" / "agent-profile" / "1.0.0"
        return _load(base / "schemas" / "reference-snapshot.schema.json")
    return _load(_artifact_path(root, "schemas/reference-snapshot.schema.json"))

def validate_profile(profile: object, schema: object | None = None) -> JsonObject:
    mode = "profile"
    if not isinstance(profile, dict) or not _is_utf8_encodable(profile):
        return _invalid(mode, "agent_profile.invalid_json", "")
    missing = next((field for field in REQUIRED_FIELDS if field not in profile), None)
    if missing is not None:
        return _invalid(mode, "agent_profile.missing_field", f"/{missing}")
    unknown = sorted((field for field in profile if field not in REQUIRED_FIELDS), key=lambda value: value.encode("utf-8"))
    if unknown:
        field = unknown[0]
        code = "agent_profile.forbidden_runtime_field" if field in FORBIDDEN_RUNTIME_FIELDS else "agent_profile.invalid_profile_field"
        return _invalid(mode, code, f"/{field}")
    version = _semver(profile["contract_version"])
    if version is None or version[0] != 1:
        return _invalid(mode, "agent_profile.unsupported_contract_version", "/contract_version")
    if not isinstance(profile["id"], str) or UUID_V7.fullmatch(profile["id"]) is None:
        return _invalid(mode, "agent_profile.invalid_id", "/id")
    revision = profile["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= SAFE_INTEGER:
        return _invalid(mode, "agent_profile.invalid_revision", "/revision")
    for field in ("goals", "declared_capabilities", "provenance_refs"):
        canonical = _canonical_string_set(profile[field], required=True)
        if canonical is None:
            return _invalid(mode, "agent_profile.invalid_profile_field", f"/{field}")
        if not canonical:
            return _invalid(mode, "agent_profile.noncanonical_set", f"/{field}")
    persona = profile["persona"]
    if isinstance(persona, dict) and "principles" in persona:
        principles = _canonical_string_set(persona["principles"], required=False)
        if principles is False:
            return _invalid(mode, "agent_profile.noncanonical_set", "/persona/principles")
    active_schema = schema if schema is not None else _schema()
    if not is_valid(profile, active_schema, active_schema):
        first_invalid = next((field for field in REQUIRED_FIELDS if not is_valid(profile[field], active_schema["properties"][field], active_schema)), "")
        return _invalid(mode, "agent_profile.invalid_profile_field", f"/{first_invalid}" if first_invalid else "")
    if version > (1, 0, 0):
        return _result(mode, "compatible_read", "succeeded", _issue("agent_profile.compatible_read", "/contract_version"))
    return _result(mode, "valid", "succeeded")


def validate_raw(raw: bytes, root: Path) -> JsonObject:
    try:
        profile = parse_json_bytes(raw)
    except Exception:
        return _invalid("transport", "agent_profile.invalid_json", "")
    result = validate_profile(profile, _schema(root))
    return {**result, "mode": "transport"}


def validate_reference_snapshot(profile: object, snapshot: object | None, profile_schema: object | None = None, reference_schema: object | None = None) -> JsonObject:
    profile_result = validate_profile(profile, profile_schema)
    if profile_result["object_result"] == "invalid":
        return {**profile_result, "mode": "reference"}
    if profile_result["object_result"] == "compatible_read":
        return _indeterminate("agent_profile.reference_snapshot_incomplete", "/contract_version")
    if not isinstance(snapshot, dict) or not _is_utf8_encodable(snapshot):
        return _indeterminate("agent_profile.reference_snapshot_incomplete", "")
    extra = sorted((field for field in snapshot if field not in {"contract_version", "provenance"}), key=lambda field: field.encode("utf-8"))
    if extra:
        return _indeterminate("agent_profile.reference_snapshot_incomplete", f"/{extra[0]}")
    if _semver(snapshot.get("contract_version")) != (1, 0, 0):
        return _indeterminate("agent_profile.reference_snapshot_incomplete", "/contract_version")
    snapshot_schema = reference_schema if reference_schema is not None else _reference_schema()
    if not is_valid(snapshot, snapshot_schema, snapshot_schema):
        return _indeterminate("agent_profile.reference_snapshot_incomplete", "/provenance")
    entries = snapshot["provenance"]
    keys: list[bytes] = []
    indexed: dict[str, tuple[int, JsonObject]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"ref", "object_result"} or not isinstance(entry.get("ref"), str) or entry.get("object_result") not in {"available", "invalid", "opaque", "compatible_read"}:
            return _indeterminate("agent_profile.reference_snapshot_incomplete", f"/provenance/{index}")
        key = entry["ref"].encode("utf-8")
        if key in keys or (keys and key < keys[-1]):
            return _indeterminate("agent_profile.reference_snapshot_incomplete", f"/provenance/{index}/ref")
        keys.append(key)
        indexed[entry["ref"]] = (index, entry)
    assert isinstance(profile, dict)
    for index, ref in enumerate(profile["provenance_refs"]):
        path = f"/provenance_refs/{index}"
        item = indexed.get(ref)
        if item is None:
            return _indeterminate("agent_profile.reference_snapshot_incomplete", path)
        _, entry = item
        state = entry["object_result"]
        if state == "invalid":
            return _invalid("reference", "agent_profile.dangling_provenance_reference", path)
        if state in {"opaque", "compatible_read"}:
            return _indeterminate("agent_profile.opaque_provenance_reference", path)
    profile_refs = set(profile["provenance_refs"])
    for ref, (index, _) in indexed.items():
        if ref not in profile_refs:
            return _indeterminate("agent_profile.reference_snapshot_incomplete", f"/provenance/{index}/ref")
    return _result("reference", "valid", "succeeded")

def validate_revision_transition(previous: object, candidate: object, schema: object | None = None) -> JsonObject:
    for profile in (previous, candidate):
        validation = validate_profile(profile, schema)
        if validation["object_result"] == "invalid":
            return {**validation, "mode": "revision_transition"}
        if validation["object_result"] == "compatible_read":
            return _invalid("revision_transition", "agent_profile.unsupported_contract_version", "/contract_version")
    assert isinstance(previous, dict) and isinstance(candidate, dict)
    if previous["id"] != candidate["id"]:
        return _invalid("revision_transition", "agent_profile.revision_identity_mismatch", "/id")
    if candidate["revision"] <= previous["revision"]:
        return _invalid("revision_transition", "agent_profile.revision_not_increased", "/revision")
    old_content, new_content = copy.deepcopy(previous), copy.deepcopy(candidate)
    old_content.pop("revision")
    new_content.pop("revision")
    if canonicalize(old_content) == canonicalize(new_content):
        return _invalid("revision_transition", "agent_profile.revision_without_change", "/revision")
    return _result("revision_transition", "valid", "succeeded")


def validate_case(case: dict, root: Path) -> JsonObject:
    input_value = case.get("input") if isinstance(case, dict) else None
    if not isinstance(input_value, dict):
        return _invalid("profile", "agent_profile.invalid_json", "/input")
    mode = input_value.get("mode")
    if mode == "raw":
        try:
            raw = bytes.fromhex(input_value["raw_hex"])
        except (KeyError, TypeError, ValueError):
            return _invalid("transport", "agent_profile.invalid_json", "/input/raw_hex")
        return validate_raw(raw, root)
    if mode == "profile":
        return validate_profile(input_value.get("profile"), _schema(root))
    if mode == "reference":
        return validate_reference_snapshot(input_value.get("profile"), input_value.get("snapshot"), _schema(root), _reference_schema(root))
    if mode == "revision_transition":
        return validate_revision_transition(input_value.get("previous"), input_value.get("candidate"), _schema(root))
    return _invalid("profile", "agent_profile.invalid_json", "/input/mode")



def _locked_json_paths(root: Path) -> list[str]:
    root_resolved = root.resolve()
    paths: list[str] = []
    for path in root_resolved.rglob("*.json"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root_resolved).as_posix()
        except ValueError as error:
            raise ValueError("invalid artifact path") from error
        if relative == "lock.json":
            continue
        if ARTIFACT_PATH.fullmatch(relative) is None:
            raise ValueError("lock closure mismatch")
        paths.append(relative)
    return sorted(paths, key=lambda value: value.encode("utf-8"))


def _jcs_sha256(path: Path) -> str:
    return hashlib.sha256(canonicalize(_load(path))).hexdigest()


def _verify_lock(root: Path) -> None:
    lock_path = _artifact_path(root, "lock.json")
    if not lock_path.is_file():
        raise ValueError("lock closure mismatch")
    lock_schema = _load(_artifact_path(root, "schemas/lock.schema.json"))
    lock = _load(lock_path)
    if not is_valid(lock, lock_schema, lock_schema):
        raise ValueError("invalid lock")
    entries = lock.get("entries") if isinstance(lock, dict) else None
    if not isinstance(entries, list):
        raise ValueError("invalid lock")
    entry_paths = [entry.get("path") if isinstance(entry, dict) else None for entry in entries]
    actual_paths = _locked_json_paths(root)
    if entry_paths != actual_paths:
        raise ValueError("lock closure mismatch")
    for entry, relative in zip(entries, actual_paths):
        if not isinstance(entry, dict) or entry.get("digest_kind") != "jcs_sha256":
            raise ValueError("lock digest mismatch")
        if entry.get("sha256") != _jcs_sha256(_artifact_path(root, relative)):
            raise ValueError("lock digest mismatch")
def _validate_manifest(manifest: Any) -> None:
    expected_limits = {
        "agent_profile_jcs_bytes": 1_048_576,
        "reference_snapshot_jcs_bytes": 1_048_576,
        "json_array_elements": 10_000,
        "json_depth": 64,
        "json_members_and_elements": 100_000,
        "json_string_utf8_bytes": 262_144,
    }
    if not isinstance(manifest, dict) or set(manifest) != {"contract_family", "contract_version", "side_effects", "set_order", "limits", "schemas", "diagnostics", "fixtures"}:
        raise ValueError("invalid contract manifest")
    if manifest.get("contract_family") != "agent-profile" or manifest.get("contract_version") != "1.0.0":
        raise ValueError("invalid contract manifest")
    if manifest.get("side_effects") != "forbidden" or manifest.get("set_order") != "unsigned-utf8":
        raise ValueError("invalid contract safety metadata")
    if manifest.get("limits") != expected_limits:
        raise ValueError("invalid contract limits")
    if manifest.get("schemas") != REQUIRED_SCHEMA_PATHS:
        raise ValueError("contract must declare every AgentProfile schema")
    if manifest.get("diagnostics") != {"agent_profile": "diagnostics/agent-profile.json"}:
        raise ValueError("contract must declare the AgentProfile diagnostic catalog")
    if manifest.get("fixtures") != "fixtures/cases.json":
        raise ValueError("invalid contract artifact path")


def _validate_catalog(catalog: Any) -> dict[str, JsonObject]:
    legal_pairs = {("valid", "succeeded"), ("invalid", "succeeded"), ("compatible_read", "succeeded"), ("not_evaluated", "indeterminate")}
    if not isinstance(catalog, dict) or set(catalog) != {"contract_version", "codes"} or catalog.get("contract_version") != "1.0.0":
        raise ValueError("invalid diagnostic catalog")
    codes = catalog.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("invalid diagnostic catalog")
    entries: dict[str, JsonObject] = {}
    encoded_codes: list[bytes] = []
    for entry in codes:
        if not isinstance(entry, dict) or set(entry) != {"code", "severity", "allowed_pairs"}:
            raise ValueError("invalid diagnostic catalog")
        code, severity, allowed_pairs = entry.get("code"), entry.get("severity"), entry.get("allowed_pairs")
        if not isinstance(code, str) or re.fullmatch(r"agent_profile\.[a-z][a-z0-9_]*", code) is None or severity not in {"error", "warning"}:
            raise ValueError("invalid diagnostic catalog")
        if not isinstance(allowed_pairs, list) or not allowed_pairs:
            raise ValueError("invalid diagnostic catalog")
        pairs: set[tuple[str, str]] = set()
        for pair in allowed_pairs:
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
                raise ValueError("invalid diagnostic catalog")
            normalized = (pair[0], pair[1])
            if normalized not in legal_pairs or normalized in pairs:
                raise ValueError("invalid diagnostic catalog")
            pairs.add(normalized)
        encoded = code.encode("utf-8")
        if code in entries:
            raise ValueError("invalid diagnostic catalog")
        entries[code] = entry
        encoded_codes.append(encoded)
    if encoded_codes != sorted(encoded_codes):
        raise ValueError("invalid diagnostic catalog")
    return entries

def verify_contract(root: Path) -> JsonObject:
    root = root.resolve()
    _verify_lock(root)
    manifest = _load(root / "contract.json")
    _validate_manifest(manifest)
    diagnostics = manifest["diagnostics"]
    artifact_paths = [*manifest["schemas"].values(), *diagnostics.values(), manifest.get("fixtures")]
    resolved_artifacts = [_artifact_path(root, relative_path) for relative_path in artifact_paths]
    if any(not path.is_file() for path in resolved_artifacts):
        raise FileNotFoundError("declared contract artifact is missing")
    catalog = _load(_artifact_path(root, diagnostics["agent_profile"]))
    catalog_entries = _validate_catalog(catalog)
    suite = _load(_artifact_path(root, manifest["fixtures"]))
    fixture_schema = _load(_artifact_path(root, manifest["schemas"]["fixture_suite"]))
    result_schema = _load(_artifact_path(root, manifest["schemas"]["validation_result"]))
    diagnostic_schema = _load(_artifact_path(root, manifest["schemas"]["diagnostic"]))
    resolved_result_schema = copy.deepcopy(result_schema)
    resolved_result_schema["properties"]["issues"]["items"] = diagnostic_schema
    resolved_fixture_schema = copy.deepcopy(fixture_schema)
    resolved_fixture_schema["properties"]["cases"]["items"]["properties"]["expected"] = resolved_result_schema
    if not is_valid(suite, resolved_fixture_schema, resolved_fixture_schema):
        raise ValueError("fixture suite does not match its machine schema")
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list):
        raise ValueError("fixture suite is invalid")
    case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case IDs are invalid or duplicated")
    try:
        canonical_case_ids = sorted(case_ids, key=lambda case_id: case_id.encode("utf-8"))
    except (AttributeError, UnicodeEncodeError) as error:
        raise ValueError("fixture case IDs are invalid or noncanonical") from error
    if case_ids != canonical_case_ids:
        raise ValueError("fixture case IDs are invalid or noncanonical")
    for case in cases:
        expected = case["expected"]
        if not is_valid(expected, resolved_result_schema, resolved_result_schema):
            raise ValueError(f"fixture expected result is invalid: {case['case_id']}")
        computed = validate_case(case, root)
        if computed != expected:
            raise ValueError(f"fixture result mismatch: {case['case_id']}: {computed!r}")
        for issue in computed["issues"]:
            entry = catalog_entries.get(issue["code"])
            if entry is None or issue.get("severity") != entry["severity"] or [computed["object_result"], computed["operation_outcome"]] not in entry["allowed_pairs"]:
                raise ValueError(f"catalog issue mismatch: {case['case_id']}")
    return {"case_count": len(cases), "contract_version": manifest["contract_version"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "agent-profile" / "1.0.0")
    args = parser.parse_args()
    print(json.dumps(verify_contract(args.root), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())