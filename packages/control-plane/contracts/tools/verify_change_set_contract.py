from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NoReturn

sys.dont_write_bytecode = True

VERSION, FAMILY = "1.0.0", "change-set"
DIRECTORY = Path(FAMILY) / VERSION
SAFE_INTEGER = 9_007_199_254_740_991
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
OPAQUE_REF = re.compile(r"^[a-z][a-z0-9-]{0,31}/[a-z][a-z0-9-]{0,63}$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$")
REFERENCE = re.compile(r"^change-set/([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9a-f-]{36})@sha256:([0-9a-f]{64})$")
PROVENANCE_REF = re.compile(r"^provenance-record/1\.0\.0/[0-9a-f-]{36}@sha256:[0-9a-f]{64}$")
POLICY_REF = re.compile(r"^control-policy/1\.0\.0/decision/[0-9a-f-]{36}@sha256:[0-9a-f]{64}$")
SENSITIVE = ("credential", "secret", "password", "prompt", "memory", "source_text", "original_content", "content_body", "access-token", "bearer", "token")
STATUSES = {"proposed", "approved", "rejected", "revoked", "expired", "indeterminate"}
EFFECT_CLASSES = {"authority-state", "resource-cleanup", "runtime-lifecycle"}
REASON_CODES = {"manual_recovery_required", "irreversible_external_effect"}
REQUEST_KEYS = {"actor_ref", "authority_scope_ref", "command_fingerprint", "control_policy_ref", "operation_class", "provenance_record_ref", "pure_plan", "runtime_context_ref", "target_ref"}
CHANGE_SET_KEYS = REQUEST_KEYS | {"change_set_digest", "change_set_id", "expires_at", "family", "impact_summary", "rollback", "status", "valid_from", "version"}
SCHEMAS = {
    "binding_request": "schemas/binding-request.schema.json",
    "binding_result": "schemas/binding-result.schema.json",
    "change_set": "schemas/change-set.schema.json",
    "contract": "schemas/contract.schema.json",
    "diagnostic": "schemas/diagnostic.schema.json",
}
REQUIRED_DIAGNOSTICS = {
    "change_set.binding_actor_mismatch", "change_set.binding_after_mismatch",
    "change_set.binding_before_mismatch", "change_set.binding_context_mismatch",
    "change_set.binding_fingerprint_mismatch", "change_set.binding_operation_mismatch",
    "change_set.binding_plan_mismatch", "change_set.binding_policy_mismatch",
    "change_set.binding_provenance_mismatch", "change_set.binding_scope_mismatch",
    "change_set.binding_target_mismatch", "change_set.expired",
    "change_set.impact_unbounded", "change_set.indeterminate",
    "change_set.invalid_change_set", "change_set.invalid_contract",
    "change_set.invalid_diagnostics", "change_set.invalid_fixtures",
    "change_set.invalid_json_bytes", "change_set.invalid_lock",
    "change_set.lock_digest_mismatch", "change_set.lock_unsafe_path",
    "change_set.missing_change_set", "change_set.not_approved",
    "change_set.not_yet_valid", "change_set.protected_content",
    "change_set.rejected", "change_set.revoked",
    "change_set.rollback_inconsistent", "change_set.unknown_field",
    "change_set.unsupported_major",
}
PUBLIC_FAILURE_CODES = REQUIRED_DIAGNOSTICS
EXPECTED_LOCKED_ARTIFACTS = {
    "change-set/1.0.0/contract.json",
    "change-set/1.0.0/diagnostics/diagnostics.json",
    "change-set/1.0.0/fixtures/cases.json",
    "change-set/1.0.0/schemas/binding-request.schema.json",
    "change-set/1.0.0/schemas/binding-result.schema.json",
    "change-set/1.0.0/schemas/change-set.schema.json",
    "change-set/1.0.0/schemas/contract.schema.json",
    "change-set/1.0.0/schemas/diagnostic.schema.json",
}
SCHEMA_PROJECTIONS = {
    "schemas/binding-request.schema.json": "c843e4a522e200afce5ec1667133cc433bd4918b0b391715d7fe27aa6285cfcd",
    "schemas/binding-result.schema.json": "63988e744dd6a9faf0c96ca1396f5125a9685990de8d76c4c5b46d2632d87573",
    "schemas/change-set.schema.json": "87b946971bd7c182a655f9e1d69419c51a013796529d48f5c8dab19971b43152",
    "schemas/contract.schema.json": "78839a18ecaf7955c7ff3589e065f81dafe5e9d9988d61126b3e80d2a9119399",
    "schemas/diagnostic.schema.json": "dc6fe9ddc367f5dac32f491aabec9755946fe64231e4734c37bc3e4eb82f95d7",
}
FIXTURE_CASES_PROJECTION = "33e336201911a954c0c609307a6717a379eb1229b6889a4acb6713e0c96131a5"


class VerificationError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def reject(code: str, detail: str) -> NoReturn:
    raise VerificationError(code, detail)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            reject("change_set.invalid_json_bytes", "duplicate JSON member")
        result[key] = value
    return result


def _integer(token: str) -> int:
    value = int(token)
    if abs(value) > SAFE_INTEGER:
        reject("change_set.invalid_json_bytes", "unsafe integer")
    return value


def _float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value) or (value.is_integer() and abs(value) > SAFE_INTEGER):
        reject("change_set.invalid_json_bytes", "invalid JSON number")
    return value


def _unicode(value: object) -> None:
    if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        reject("change_set.invalid_json_bytes", "unpaired surrogate")
    if isinstance(value, list):
        for item in value:
            _unicode(item)
    if isinstance(value, dict):
        for key, item in value.items():
            _unicode(key)
            _unicode(item)


def parse_json_bytes(raw: bytes) -> object:
    if not isinstance(raw, bytes):
        reject("change_set.invalid_json_bytes", "JSON input must be bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        reject("change_set.invalid_json_bytes", "UTF-8 BOM is forbidden")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_int=_integer, parse_float=_float, parse_constant=lambda _: reject("change_set.invalid_json_bytes", "non-finite number"))
    except VerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("change_set.invalid_json_bytes", "invalid JSON bytes")
    _unicode(value)
    return value


def load_json(path: Path) -> object:
    if not path.is_file():
        reject("change_set.missing_change_set", "missing artifact")
    return parse_json_bytes(path.read_bytes())


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        reject("change_set.invalid_json_bytes", "non-finite number")
    if value == 0:
        return "0"
    text = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":")).lower()
    sign, text = ("-", text[1:]) if text.startswith("-") else ("", text)
    if "e" not in text:
        return sign + (text[:-2] if text.endswith(".0") else text)
    mantissa, exponent_text = text.split("e")
    exponent = int(exponent_text)
    digits = mantissa.replace(".", "")
    if 1e-6 <= abs(value) < 1e21:
        position = 1 + exponent
        if position <= 0:
            return sign + "0." + "0" * -position + digits
        if position >= len(digits):
            return sign + digits + "0" * (position - len(digits))
        return sign + digits[:position] + "." + digits[position:]
    return f"{sign}{mantissa[:-2] if mantissa.endswith('.0') else mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def jcs_bytes(value: object) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, (int, float)):
        return _number(value).encode("ascii")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(jcs_bytes(item) for item in value) + b"]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            reject("change_set.invalid_json_bytes", "object keys must be strings")
        return b"{" + b",".join(jcs_bytes(key) + b":" + jcs_bytes(value[key]) for key in sorted(value, key=lambda item: item.encode("utf-16-be"))) + b"}"
    reject("change_set.invalid_json_bytes", "unsupported JSON value")


def compatibility_state(version: object) -> str:
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        return "rejected"
    major, minor, _ = (int(part) for part in version.split("."))
    if major != 1:
        return "rejected"
    return "supported" if minor == 0 else "compatible_read"


def _closed(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        reject(code, "must be a closed object")
    extra = set(value) - keys
    if extra:
        if any(any(word in key.lower() for word in SENSITIVE) for key in extra):
            reject("change_set.protected_content", "protected content is forbidden")
        reject("change_set.unknown_field", "unknown fields are forbidden")
    if set(value) != keys:
        reject(code, "required closed fields differ")
    return value


def _digest(value: object, code: str = "change_set.invalid_change_set") -> str:
    if not isinstance(value, str) or HEX_64.fullmatch(value) is None:
        reject(code, "invalid digest")
    return value


def _opaque(value: object, code: str = "change_set.invalid_change_set") -> str:
    if not isinstance(value, str) or len(value) > 96 or OPAQUE_REF.fullmatch(value) is None:
        reject(code, "invalid opaque reference")
    if any(word in value.lower() for word in SENSITIVE):
        reject("change_set.protected_content", "protected content is forbidden")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None:
        reject("change_set.invalid_change_set", "invalid UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reject("change_set.invalid_change_set", "invalid UTC timestamp")
    return value


def _timestamp_key(value: str) -> tuple[datetime, int]:
    base = datetime.fromisoformat(value[:19] + "+00:00")
    fraction = value[20:-1] if len(value) > 20 else ""
    return base, int((fraction + "0" * 9)[:9]) if fraction else 0


def pure_plan_digest(plan: dict[str, object]) -> str:
    return hashlib.sha256(jcs_bytes({key: value for key, value in plan.items() if key != "plan_digest"})).hexdigest()


def _validate_plan_shape(value: object) -> dict[str, object]:
    plan = _closed(value, {"after_digest", "before_digest", "plan_digest", "pure"}, "change_set.invalid_change_set")
    if plan["pure"] is not True:
        reject("change_set.invalid_change_set", "plan must be pure")
    for key in ("after_digest", "before_digest", "plan_digest"):
        _digest(plan[key])
    return plan


def validate_pure_plan(value: object) -> dict[str, object]:
    plan = _validate_plan_shape(value)
    if plan["before_digest"] == plan["after_digest"]:
        reject("change_set.invalid_change_set", "approved plan must describe actual change")
    if plan["plan_digest"] != pure_plan_digest(plan):
        reject("change_set.lock_digest_mismatch", "plan digest mismatch")
    return plan


def _validate_impact(value: object, target_ref: str) -> dict[str, object]:
    impact = _closed(value, {"effect_classes", "resource_refs", "summary_code"}, "change_set.invalid_change_set")
    resources, effects = impact["resource_refs"], impact["effect_classes"]
    if not isinstance(resources, list) or not 1 <= len(resources) <= 16 or not all(isinstance(item, str) for item in resources):
        reject("change_set.impact_unbounded", "resource boundary must contain 1 through 16 refs")
    if resources != sorted(set(resources)):
        reject("change_set.invalid_change_set", "resource refs must be unique sorted")
    for resource in resources:
        _opaque(resource)
    if target_ref not in resources:
        reject("change_set.invalid_change_set", "impact must include exact target")
    if not isinstance(effects, list) or not 1 <= len(effects) <= 3 or not all(isinstance(item, str) for item in effects) or effects != sorted(set(effects)) or any(effect not in EFFECT_CLASSES for effect in effects):
        reject("change_set.impact_unbounded", "effect classes are invalid")
    if impact["summary_code"] != "agent-runtime-transition":
        reject("change_set.invalid_change_set", "summary must be finite")
    return impact


def _validate_rollback(value: object) -> dict[str, object]:
    rollback = _closed(value, {"compensation_operation_class", "overwrites_history", "reason_code", "requires_new_approved_change_set", "strategy"}, "change_set.invalid_change_set")
    if rollback["overwrites_history"] is not False or rollback["requires_new_approved_change_set"] is not True:
        reject("change_set.rollback_inconsistent", "history is immutable and compensation needs new approval")
    if rollback["strategy"] == "compensation":
        if rollback["compensation_operation_class"] != "agent_runtime.transition.compensation" or rollback["reason_code"] is not None:
            reject("change_set.rollback_inconsistent", "invalid compensation declaration")
    elif rollback["strategy"] == "not_automatically_reversible":
        if rollback["compensation_operation_class"] is not None or not isinstance(rollback["reason_code"], str) or rollback["reason_code"] not in REASON_CODES:
            reject("change_set.rollback_inconsistent", "automatic rollback exclusion must be explicit")
    else:
        reject("change_set.rollback_inconsistent", "unknown rollback strategy")
    return rollback


def change_set_digest(change_set: dict[str, object]) -> str:
    return hashlib.sha256(jcs_bytes({key: value for key, value in change_set.items() if key != "change_set_digest"})).hexdigest()


def exact_reference(change_set: dict[str, object]) -> str:
    return f"change-set/{VERSION}/{change_set['change_set_id']}@sha256:{change_set['change_set_digest']}"


def _parse_reference(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or (match := REFERENCE.fullmatch(value)) is None:
        reject("change_set.missing_change_set", "reference must be exact")
    major, minor, patch, item_id, digest = match.groups()
    if (major, minor, patch) != ("1", "0", "0"):
        reject("change_set.unsupported_major", "binding reference version must be exact")
    return item_id, digest


def validate_change_set(value: object) -> dict[str, object]:
    change_set = _closed(value, CHANGE_SET_KEYS, "change_set.invalid_change_set")
    if change_set["family"] != FAMILY or change_set["version"] != VERSION:
        reject("change_set.invalid_change_set", "published binding version must be exact")
    if not isinstance(change_set["change_set_id"], str) or UUID.fullmatch(change_set["change_set_id"]) is None:
        reject("change_set.invalid_change_set", "change_set_id must be UUID")
    _digest(change_set["change_set_digest"])
    if not isinstance(change_set["status"], str) or change_set["status"] not in STATUSES:
        reject("change_set.invalid_change_set", "invalid status")
    for key in ("actor_ref", "authority_scope_ref", "runtime_context_ref", "target_ref"):
        _opaque(change_set[key])
    if change_set["operation_class"] != "agent_runtime.transition":
        reject("change_set.invalid_change_set", "unsupported operation class")
    _digest(change_set["command_fingerprint"])
    if not isinstance(change_set["provenance_record_ref"], str) or PROVENANCE_REF.fullmatch(change_set["provenance_record_ref"]) is None:
        reject("change_set.invalid_change_set", "provenance ref must bind exact 1.0.0")
    if not isinstance(change_set["control_policy_ref"], str) or POLICY_REF.fullmatch(change_set["control_policy_ref"]) is None:
        reject("change_set.invalid_change_set", "policy ref must bind exact decision 1.0.0")
    validate_pure_plan(change_set["pure_plan"])
    _validate_impact(change_set["impact_summary"], change_set["target_ref"])
    _validate_rollback(change_set["rollback"])
    valid_from, expires_at = _timestamp(change_set["valid_from"]), _timestamp(change_set["expires_at"])
    if _timestamp_key(expires_at) <= _timestamp_key(valid_from):
        reject("change_set.invalid_change_set", "validity interval must be non-empty")
    if change_set["change_set_digest"] != change_set_digest(change_set):
        reject("change_set.lock_digest_mismatch", "change set digest mismatch")
    return change_set


def _rejected(code: str) -> dict[str, str]:
    return {"status": "rejected", "diagnostic": code if code in PUBLIC_FAILURE_CODES else "change_set.invalid_change_set"}


def read_change_set_bytes(raw: bytes) -> dict[str, str]:
    try:
        value = parse_json_bytes(raw)
        if not isinstance(value, dict):
            reject("change_set.invalid_json_bytes", "change set bytes must encode object")
        state = compatibility_state(value.get("version"))
        if state == "compatible_read":
            return {"status": "compatible_read", "diagnostic": ""}
        if state != "supported":
            return _rejected("change_set.unsupported_major")
        validate_change_set(value)
    except VerificationError as error:
        return _rejected(error.code)
    return {"status": "valid", "diagnostic": ""}


def validate_binding(change_sets: object, reference: object, request: object, validation_time: object) -> dict[str, str]:
    try:
        if not isinstance(change_sets, list):
            reject("change_set.invalid_change_set", "change_sets must be list")
        request = _closed(request, REQUEST_KEYS, "change_set.invalid_change_set")
        _validate_plan_shape(request["pure_plan"])
        change_set_id, digest = _parse_reference(reference)
        validation_time = _timestamp(validation_time)
        normalized = [validate_change_set(item) for item in change_sets]
        candidates = [item for item in normalized if item["change_set_id"] == change_set_id and item["change_set_digest"] == digest]
        if len(candidates) != 1:
            reject("change_set.missing_change_set", "exact change set not found")
        change_set = candidates[0]
        status_diagnostics = {
            "proposed": "change_set.not_approved", "rejected": "change_set.rejected",
            "revoked": "change_set.revoked", "expired": "change_set.expired",
            "indeterminate": "change_set.indeterminate",
        }
        if change_set["status"] != "approved":
            reject(status_diagnostics[change_set["status"]], "only approved can be admitted")
        now = _timestamp_key(validation_time)
        if now < _timestamp_key(change_set["valid_from"]):
            reject("change_set.not_yet_valid", "approval is not yet valid")
        if now >= _timestamp_key(change_set["expires_at"]):
            reject("change_set.expired", "approval is expired")
        mismatches = {
            "actor_ref": "change_set.binding_actor_mismatch",
            "authority_scope_ref": "change_set.binding_scope_mismatch",
            "runtime_context_ref": "change_set.binding_context_mismatch",
            "target_ref": "change_set.binding_target_mismatch",
            "operation_class": "change_set.binding_operation_mismatch",
            "command_fingerprint": "change_set.binding_fingerprint_mismatch",
            "provenance_record_ref": "change_set.binding_provenance_mismatch",
            "control_policy_ref": "change_set.binding_policy_mismatch",
        }
        for key, diagnostic in mismatches.items():
            if change_set[key] != request[key]:
                reject(diagnostic, "binding mismatch")
        for key, diagnostic in (("before_digest", "change_set.binding_before_mismatch"), ("after_digest", "change_set.binding_after_mismatch"), ("plan_digest", "change_set.binding_plan_mismatch")):
            if change_set["pure_plan"][key] != request["pure_plan"][key]:
                reject(diagnostic, "plan binding mismatch")
    except VerificationError as error:
        return _rejected(error.code)
    return {"status": "accepted", "diagnostic": ""}


def validate_binding_bytes(raw_change_sets: object, reference: object, raw_request: object, validation_time: object) -> dict[str, str]:
    try:
        if not isinstance(raw_change_sets, list) or not all(isinstance(raw, bytes) for raw in raw_change_sets):
            reject("change_set.invalid_json_bytes", "raw change sets must be byte list")
        change_sets = [parse_json_bytes(raw) for raw in raw_change_sets]
        request = parse_json_bytes(raw_request)
        return validate_binding(change_sets, reference, request, validation_time)
    except VerificationError as error:
        return _rejected(error.code)


def _safe_path(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        reject("change_set.lock_unsafe_path", "unsafe lock path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts or pure.as_posix() != value or "\\" in value:
        reject("change_set.lock_unsafe_path", "unsafe lock path")
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        reject("change_set.lock_unsafe_path", "unsafe lock path")
    return candidate


def _locked_paths(root: Path) -> list[str]:
    return sorted(EXPECTED_LOCKED_ARTIFACTS, key=lambda item: item.encode("utf-8"))


def _verify_lock(root: Path) -> None:
    tree = root / DIRECTORY
    actual = {path.relative_to(root).as_posix() for path in tree.rglob("*") if path.is_file() and path != tree / "lock.json"}
    if actual != EXPECTED_LOCKED_ARTIFACTS:
        reject("change_set.invalid_lock", "closed contract tree differs")
    lock = load_json(tree / "lock.json")
    if not isinstance(lock, dict) or set(lock) != {"entries", "self_digest", "version"} or lock.get("self_digest") != "excluded" or lock.get("version") != VERSION or not isinstance(lock.get("entries"), list):
        reject("change_set.invalid_lock", "invalid lock")
    entries = lock["entries"]
    paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if paths != _locked_paths(root) or len(entries) != len(paths):
        reject("change_set.invalid_lock", "lock coverage differs")
    for entry in entries:
        if set(entry) != {"digest_kind", "path", "sha256"} or entry["digest_kind"] != "jcs_sha256" or not isinstance(entry["sha256"], str) or HEX_64.fullmatch(entry["sha256"]) is None:
            reject("change_set.invalid_lock", "invalid lock entry")
        path = _safe_path(root, entry["path"])
        if hashlib.sha256(jcs_bytes(load_json(path))).hexdigest() != entry["sha256"]:
            reject("change_set.lock_digest_mismatch", "lock digest mismatch")


def _schema(value: object, name: str) -> None:
    if not isinstance(value, dict) or value.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or value.get("type") != "object" or value.get("additionalProperties") is not False or not isinstance(value.get("properties"), dict) or set(value.get("required", [])) != set(value["properties"]):
        reject("change_set.invalid_contract", "schema must be closed")
    if hashlib.sha256(jcs_bytes(value)).hexdigest() != SCHEMA_PROJECTIONS[name]:
        reject("change_set.invalid_contract", "schema semantic projection mismatch")


def verify(root: Path) -> None:
    _verify_lock(root)
    manifest = load_json(root / DIRECTORY / "contract.json")
    expected = {"diagnostics": "diagnostics/diagnostics.json", "family": FAMILY, "fixtures": "fixtures/cases.json", "schemas": SCHEMAS, "side_effects": "forbidden", "version": VERSION}
    if manifest != expected:
        reject("change_set.invalid_contract", "invalid manifest")
    for relative in SCHEMAS.values():
        _schema(load_json(root / DIRECTORY / relative), relative)
    diagnostics = load_json(root / DIRECTORY / "diagnostics/diagnostics.json")
    if not isinstance(diagnostics, dict) or set(diagnostics) != {"diagnostics", "version"} or diagnostics.get("version") != VERSION or not isinstance(diagnostics.get("diagnostics"), list):
        reject("change_set.invalid_diagnostics", "invalid diagnostics")
    entries = diagnostics["diagnostics"]
    codes = [entry.get("code") for entry in entries if isinstance(entry, dict) and set(entry) == {"code"}]
    if codes != sorted(REQUIRED_DIAGNOSTICS, key=lambda item: item.encode("utf-8")) or len(codes) != len(entries):
        reject("change_set.invalid_diagnostics", "diagnostic catalog differs")
    suite = load_json(root / DIRECTORY / "fixtures/cases.json")
    if not isinstance(suite, dict) or set(suite) != {"cases", "version"} or suite.get("version") != VERSION or not isinstance(suite.get("cases"), list) or not suite["cases"]:
        reject("change_set.invalid_fixtures", "invalid fixture suite")
    if hashlib.sha256(jcs_bytes(suite["cases"])).hexdigest() != FIXTURE_CASES_PROJECTION:
        reject("change_set.invalid_fixtures", "fixture semantic projection mismatch")
    ids = [case.get("case_id") for case in suite["cases"] if isinstance(case, dict)]
    if len(ids) != len(suite["cases"]) or not all(isinstance(item, str) for item in ids) or ids != sorted(ids, key=lambda item: item.encode("utf-8")) or len(set(ids)) != len(ids):
        reject("change_set.invalid_fixtures", "invalid fixture IDs")
    base_cases = [case for case in suite["cases"] if isinstance(case, dict) and case.get("case_id") == "approved-bound-change-set"]
    if len(base_cases) != 1 or set(base_cases[0]) != {"case_id", "expected", "input"}:
        reject("change_set.invalid_fixtures", "missing approved fixture")
    base_input = base_cases[0]["input"]
    if not isinstance(base_input, dict) or set(base_input) != {"change_sets", "reference", "request", "validation_time"}:
        reject("change_set.invalid_fixtures", "invalid approved fixture")
    for case in suite["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("expected"), dict):
            reject("change_set.invalid_fixtures", "invalid fixture")
        if "input" in case:
            if set(case) != {"case_id", "expected", "input"}:
                reject("change_set.invalid_fixtures", "invalid input fixture")
            result = validate_binding(**case["input"])
        elif "mutation" in case:
            if set(case) != {"case_id", "expected", "mutation"}:
                reject("change_set.invalid_fixtures", "invalid mutation fixture")
            mutation = _closed(case["mutation"], {"path", "target", "value"}, "change_set.invalid_fixtures")
            if mutation["target"] not in {"change_set", "request", "validation_time"} or not isinstance(mutation["path"], str):
                reject("change_set.invalid_fixtures", "invalid fixture mutation")
            fixture_input = copy.deepcopy(base_input)
            if mutation["target"] == "validation_time":
                if mutation["path"] != "":
                    reject("change_set.invalid_fixtures", "invalid time mutation")
                fixture_input["validation_time"] = mutation["value"]
            else:
                target = fixture_input["change_sets"][0] if mutation["target"] == "change_set" else fixture_input["request"]
                parts = mutation["path"].split(".")
                if not parts or any(not part for part in parts):
                    reject("change_set.invalid_fixtures", "invalid mutation path")
                for part in parts[:-1]:
                    if not isinstance(target, dict) or part not in target:
                        reject("change_set.invalid_fixtures", "unknown mutation path")
                    target = target[part]
                if not isinstance(target, dict):
                    reject("change_set.invalid_fixtures", "invalid mutation target")
                target[parts[-1]] = mutation["value"]
                if mutation["target"] == "change_set":
                    fixture_input["change_sets"][0]["change_set_digest"] = change_set_digest(fixture_input["change_sets"][0])
                    fixture_input["reference"] = exact_reference(fixture_input["change_sets"][0])
            result = validate_binding(**fixture_input)
        elif "raw_request" in case:
            if set(case) != {"case_id", "expected", "raw_request"} or not isinstance(case["raw_request"], str):
                reject("change_set.invalid_fixtures", "invalid raw fixture")
            result = validate_binding_bytes([jcs_bytes(base_input["change_sets"][0])], base_input["reference"], case["raw_request"].encode("utf-8"), base_input["validation_time"])
        else:
            reject("change_set.invalid_fixtures", "unknown fixture form")
        if result != case["expected"]:
            reject("change_set.invalid_fixtures", "fixture result mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    try:
        verify(parser.parse_args().root.resolve())
    except VerificationError as error:
        print(error.code, file=sys.stderr)
        return 1
    print("change-set 1.0.0 verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
