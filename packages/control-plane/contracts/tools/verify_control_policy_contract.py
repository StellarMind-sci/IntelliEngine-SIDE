from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NoReturn

sys.dont_write_bytecode = True
VERSION, FAMILY = "1.0.0", "control-policy"
DIRECTORY = Path(FAMILY) / VERSION
SAFE_INTEGER = 9_007_199_254_740_991
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
OPAQUE_REF = re.compile(r"^[a-z][a-z0-9-]{0,31}/[a-z][a-z0-9-]{0,63}$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$")
REFERENCE = re.compile(r"^control-policy/([0-9]+)\.([0-9]+)\.([0-9]+)/decision/([0-9a-f-]{36})@sha256:([0-9a-f]{64})$")
PROVENANCE_REF = re.compile(r"^provenance-record/([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9a-f-]{36})@sha256:([0-9a-f]{64})$")
SENSITIVE = ("credential", "secret", "password", "prompt", "memory", "source_text", "original_content", "content_body", "access-token", "bearer", "token")
SAFETY_CAPS = ["no-device", "no-file", "no-final-commit", "no-model", "no-network", "no-runtime-lease"]
REQUIRED_DIAGNOSTICS = {"control_policy.binding_actor_mismatch", "control_policy.binding_context_mismatch", "control_policy.binding_fingerprint_mismatch", "control_policy.binding_operation_mismatch", "control_policy.binding_plan_mismatch", "control_policy.binding_provenance_mismatch", "control_policy.binding_scope_mismatch", "control_policy.binding_target_mismatch", "control_policy.denied", "control_policy.expired", "control_policy.indeterminate", "control_policy.invalid_contract", "control_policy.invalid_decision", "control_policy.invalid_diagnostics", "control_policy.invalid_fixtures", "control_policy.invalid_json_bytes", "control_policy.invalid_lock", "control_policy.lock_digest_mismatch", "control_policy.lock_unsafe_path", "control_policy.missing_decision", "control_policy.protected_content", "control_policy.revoked", "control_policy.safety_cap_mismatch", "control_policy.unknown_field", "control_policy.unsupported_major"}
SCHEMAS = {"binding_request": "schemas/binding-request.schema.json", "binding_result": "schemas/binding-result.schema.json", "contract": "schemas/contract.schema.json", "decision": "schemas/decision.schema.json", "diagnostic": "schemas/diagnostic.schema.json"}
SCHEMA_PROJECTIONS = {"schemas/binding-request.schema.json":"9999b90d57439c8984be1b34657b2e230ae1580fceb86603258c87ac13b2aea8","schemas/binding-result.schema.json":"2f974645b17e63b2bc64faad8ca2dd340349ec92415c2ff1e0008c0a0dd64c25","schemas/contract.schema.json":"f088fe0853f433a4387e5e35ef75e13988d77946fff3d404c7b42af7cc22b9ea","schemas/decision.schema.json":"f7f6123e40a1c9bbdbc244abaff78a41ca2b108c83a2a9fab8b3779a3dad9a54","schemas/diagnostic.schema.json":"cc9b7088e26e58e8286a92592bf76ea28d76adaf803e0134b0dd6ccaaade0573"}
EXPECTED_LOCKED_ARTIFACTS = {"control-policy/1.0.0/contract.json", "control-policy/1.0.0/diagnostics/diagnostics.json", "control-policy/1.0.0/fixtures/cases.json", "control-policy/1.0.0/schemas/binding-request.schema.json", "control-policy/1.0.0/schemas/binding-result.schema.json", "control-policy/1.0.0/schemas/contract.schema.json", "control-policy/1.0.0/schemas/decision.schema.json", "control-policy/1.0.0/schemas/diagnostic.schema.json"}
FIXTURE_CASES_PROJECTION = "cc54cd696f8f209c31fcbb67620b7c06e48c4015945bb47ff5c772323ec3a81e"

class VerificationError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail); self.code, self.detail = code, detail

def reject(code: str, detail: str) -> NoReturn:
    raise VerificationError(code, detail)

def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result: reject("control_policy.invalid_json_bytes", "duplicate JSON member")
        result[key] = value
    return result

def _integer(token: str) -> int:
    value = int(token)
    if abs(value) > SAFE_INTEGER: reject("control_policy.invalid_json_bytes", "unsafe integer")
    return value

def _float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value) or (value.is_integer() and abs(value) > SAFE_INTEGER): reject("control_policy.invalid_json_bytes", "invalid JSON number")
    return value

def _unicode(value: object) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value): reject("control_policy.invalid_json_bytes", "unpaired surrogate")
    elif isinstance(value, list):
        for item in value: _unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items(): _unicode(key); _unicode(item)

def parse_json_bytes(raw: bytes) -> object:
    if not isinstance(raw, bytes): reject("control_policy.invalid_json_bytes", "JSON input must be bytes")
    if not isinstance(raw, bytes): reject("control_policy.invalid_json_bytes", "JSON input must be bytes")
    if raw.startswith(b"\xef\xbb\xbf"): reject("control_policy.invalid_json_bytes", "UTF-8 BOM is forbidden")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_int=_integer, parse_float=_float, parse_constant=lambda _: reject("control_policy.invalid_json_bytes", "non-finite number"))
    except VerificationError: raise
    except (UnicodeDecodeError, json.JSONDecodeError): reject("control_policy.invalid_json_bytes", "invalid JSON bytes")
    _unicode(value); return value

def load_json(path: Path) -> object:
    if not path.is_file(): reject("control_policy.missing_decision", "missing artifact")
    return parse_json_bytes(path.read_bytes())

def _number(value: int | float) -> str:
    if isinstance(value, int): return str(value)
    if not math.isfinite(value): reject("control_policy.invalid_json_bytes", "non-finite number")
    if value == 0: return "0"
    text = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":")).lower()
    sign, text = ("-", text[1:]) if text.startswith("-") else ("", text)
    if "e" not in text: return sign + (text[:-2] if text.endswith(".0") else text)
    mantissa, exponent_text = text.split("e"); exponent = int(exponent_text); digits = mantissa.replace(".", "")
    if 1e-6 <= abs(value) < 1e21:
        pos = 1 + exponent
        if pos <= 0: return sign + "0." + "0" * -pos + digits
        if pos >= len(digits): return sign + digits + "0" * (pos - len(digits))
        return sign + digits[:pos] + "." + digits[pos:]
    return f"{sign}{mantissa[:-2] if mantissa.endswith('.0') else mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"

def jcs_bytes(value: object) -> bytes:
    if value is None: return b"null"
    if value is True: return b"true"
    if value is False: return b"false"
    if isinstance(value, (int, float)): return _number(value).encode("ascii")
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list): return b"[" + b",".join(jcs_bytes(item) for item in value) + b"]"
    if isinstance(value, dict): return b"{" + b",".join(jcs_bytes(key) + b":" + jcs_bytes(value[key]) for key in sorted(value, key=lambda key: key.encode("utf-16-be"))) + b"}"
    reject("control_policy.invalid_json_bytes", "unsupported JSON value")

def compatibility_state(version: object) -> str:
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None: return "rejected"
    major, minor, _ = (int(part) for part in version.split("."))
    return "supported" if (major, minor) == (1, 0) else ("compatible_read" if major == 1 else "rejected")

def _closed(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict): reject(code, "must be object")
    extra = set(value) - keys
    if extra:
        if not all(isinstance(key, str) for key in extra): reject(code, "unknown fields are forbidden")
        if any(any(word in key.lower() for word in SENSITIVE) for key in extra): reject("control_policy.protected_content", "protected content is forbidden")
        reject("control_policy.unknown_field", "unknown fields are forbidden")
    if set(value) != keys: reject(code, "required closed fields differ")
    return value

def _opaque(value: object) -> None:
    if not isinstance(value, str) or len(value) > 96 or OPAQUE_REF.fullmatch(value) is None: reject("control_policy.invalid_decision", "invalid opaque reference")
    if any(word in value.lower() for word in SENSITIVE): reject("control_policy.protected_content", "protected content is forbidden")

def _timestamp(value: object) -> str:
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None: reject("control_policy.invalid_decision", "invalid UTC timestamp")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: reject("control_policy.invalid_decision", "invalid UTC timestamp")
    return value

def _timestamp_key(value: str) -> tuple[datetime, int]:
    base = datetime.fromisoformat(value[:19] + "+00:00")
    fractional = value[20:-1] if len(value) > 20 else ""
    return base, int((fractional + "0" * 9)[:9]) if fractional else 0

def decision_digest(decision: dict[str, object]) -> str:
    return hashlib.sha256(jcs_bytes({key: value for key, value in decision.items() if key != "decision_digest"})).hexdigest()

def exact_reference(decision: dict[str, object]) -> str:
    return f"control-policy/{VERSION}/decision/{decision['decision_id']}@sha256:{decision['decision_digest']}"

def policy_reference(decision: dict[str, object]) -> str:
    return f"control-policy/{VERSION}/policy/{decision['policy_id']}@sha256:{decision['policy_digest']}"

def _reference(value: object, pattern: re.Pattern[str]) -> tuple[str, str]:
    if not isinstance(value, str) or (match := pattern.fullmatch(value)) is None: reject("control_policy.invalid_decision", "reference must be exact")
    major, minor, patch, item_id, digest = match.groups()
    if (major, minor, patch) != ("1", "0", "0"): reject("control_policy.unsupported_major", "unsupported reference version")
    return item_id, digest

def validate_decision(value: object) -> dict[str, object]:
    keys = {"actor_ref", "authority_scope_ref", "command_fingerprint", "constraints", "decision_digest", "decision_id", "expires_at", "family", "operation_class", "outcome", "policy_digest", "policy_id", "provenance_record_ref", "pure_plan_digest", "revoked", "runtime_context_ref", "target_ref", "valid_from", "version"}
    decision = _closed(value, keys, "control_policy.invalid_decision")
    if decision["family"] != FAMILY or decision["version"] != VERSION: reject("control_policy.invalid_decision", "family/version must be exact")
    for key in ("decision_id", "policy_id"):
        if not isinstance(decision[key], str) or UUID.fullmatch(decision[key]) is None: reject("control_policy.invalid_decision", "identifier must be UUID")
    for key in ("decision_digest", "policy_digest", "command_fingerprint", "pure_plan_digest"):
        if not isinstance(decision[key], str) or HEX_64.fullmatch(decision[key]) is None: reject("control_policy.invalid_decision", "invalid digest")
    for key in ("actor_ref", "authority_scope_ref", "runtime_context_ref", "target_ref"): _opaque(decision[key])
    if decision["operation_class"] != "agent_runtime.transition" or decision["outcome"] not in {"allow", "deny", "indeterminate"} or not isinstance(decision["revoked"], bool): reject("control_policy.invalid_decision", "invalid decision fields")
    _reference(decision["provenance_record_ref"], PROVENANCE_REF)
    decision["valid_from"], decision["expires_at"] = _timestamp(decision["valid_from"]), _timestamp(decision["expires_at"])
    if _timestamp_key(decision["expires_at"]) <= _timestamp_key(decision["valid_from"]): reject("control_policy.invalid_decision", "invalid validity interval")
    constraints = _closed(decision["constraints"], {"platform_safety_caps", "requires_changeset", "requires_fence"}, "control_policy.invalid_decision")
    if constraints["platform_safety_caps"] != SAFETY_CAPS or constraints["requires_changeset"] is not True or constraints["requires_fence"] is not True: reject("control_policy.safety_cap_mismatch", "platform safety cap may not be weakened")
    if decision["decision_digest"] != decision_digest(decision): reject("control_policy.lock_digest_mismatch", "decision digest mismatch")
    return decision

def _rejected(code: str) -> dict[str, str]:
    return {"status": "rejected", "diagnostic": code if code in REQUIRED_DIAGNOSTICS else "control_policy.invalid_json_bytes"}

def read_decision_bytes(raw: bytes) -> dict[str, str]:
    try:
        value = parse_json_bytes(raw)
        if not isinstance(value, dict): reject("control_policy.invalid_json_bytes", "decision must be object")
        state = compatibility_state(value.get("version"))
        if state == "compatible_read": return {"status": "compatible_read", "diagnostic": ""}
        if state != "supported": return _rejected("control_policy.unsupported_major")
        validate_decision(value)
    except VerificationError as error: return _rejected(error.code)
    return {"status": "valid", "diagnostic": ""}

def validate_binding(decisions: list[dict[str, object]], reference: object, request: object, validation_time: object) -> dict[str, str]:
    try:
        if not isinstance(decisions, list): reject("control_policy.invalid_decision", "decisions must be list")
        request = _closed(request, {"actor_ref", "authority_scope_ref", "command_fingerprint", "operation_class", "provenance_record_ref", "pure_plan_digest", "runtime_context_ref", "target_ref"}, "control_policy.invalid_decision")
        decision_id, digest = _reference(reference, REFERENCE); validation_time = _timestamp(validation_time)
        candidates = [decision for decision in (validate_decision(value) for value in decisions) if decision["decision_id"] == decision_id and decision["decision_digest"] == digest]
        if len(candidates) != 1: return _rejected("control_policy.missing_decision")
        decision = candidates[0]
        if decision["revoked"]: return _rejected("control_policy.revoked")
        if not (_timestamp_key(decision["valid_from"]) <= _timestamp_key(validation_time) < _timestamp_key(decision["expires_at"])): return _rejected("control_policy.expired")
        if decision["outcome"] != "allow": return _rejected("control_policy.denied" if decision["outcome"] == "deny" else "control_policy.indeterminate")
        expected = {"actor_ref":"control_policy.binding_actor_mismatch", "authority_scope_ref":"control_policy.binding_scope_mismatch", "runtime_context_ref":"control_policy.binding_context_mismatch", "target_ref":"control_policy.binding_target_mismatch", "operation_class":"control_policy.binding_operation_mismatch", "command_fingerprint":"control_policy.binding_fingerprint_mismatch", "pure_plan_digest":"control_policy.binding_plan_mismatch", "provenance_record_ref":"control_policy.binding_provenance_mismatch"}
        for key, code in expected.items():
            if request.get(key) != decision[key]: return _rejected(code)
        return {"status": "accepted", "diagnostic": ""}
    except VerificationError as error: return _rejected(error.code)

def validate_binding_bytes(raw_decisions: list[bytes], reference: object, raw_request: bytes, validation_time: object) -> dict[str, str]:
    try:
        if not isinstance(raw_decisions, list) or not all(isinstance(raw, bytes) for raw in raw_decisions): reject("control_policy.invalid_json_bytes", "raw decisions must be byte list")
        decisions, request = [parse_json_bytes(raw) for raw in raw_decisions], parse_json_bytes(raw_request)
        if not all(isinstance(value, dict) for value in decisions) or not isinstance(request, dict): reject("control_policy.invalid_json_bytes", "binding values must be objects")
        return validate_binding(decisions, reference, request, validation_time)
    except VerificationError as error: return _rejected(error.code)

def _locked_paths(root: Path) -> list[str]:
    base = root / DIRECTORY
    if not base.is_dir(): reject("control_policy.invalid_lock", "contract directory missing")
    paths = []
    for path in base.rglob("*"):
        if path.is_dir(): continue
        relative = path.relative_to(root).as_posix()
        if relative == f"{FAMILY}/{VERSION}/lock.json": continue
        if path.suffix != ".json": reject("control_policy.invalid_lock", "closed tree contains unsupported file")
        paths.append(relative)
    return sorted(paths, key=lambda path: path.encode("utf-8"))

def _safe_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")): reject("control_policy.lock_unsafe_path", "unsafe lock path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.parts[:2] != (FAMILY, VERSION): reject("control_policy.lock_unsafe_path", "unsafe lock path")
    path = (root / Path(*pure.parts)).resolve()
    try: path.relative_to(root.resolve())
    except ValueError: reject("control_policy.lock_unsafe_path", "lock path escapes root")
    return path

def _verify_lock(root: Path) -> None:
    lock = load_json(root / DIRECTORY / "lock.json")
    if not isinstance(lock, dict) or set(lock) != {"entries", "self_digest", "version"} or lock.get("version") != VERSION or lock.get("self_digest") != "excluded": reject("control_policy.invalid_lock", "invalid lock")
    paths, entries = _locked_paths(root), lock.get("entries")
    if set(paths) != EXPECTED_LOCKED_ARTIFACTS: reject("control_policy.invalid_lock", "locked artifact set mismatch")
    if not isinstance(entries, list) or len(entries) != len(paths): reject("control_policy.invalid_lock", "lock closure mismatch")
    for entry, relative in zip(entries, paths):
        if not isinstance(entry, dict) or set(entry) != {"digest_kind", "path", "sha256"} or entry.get("digest_kind") != "jcs_sha256" or entry.get("path") != relative: reject("control_policy.invalid_lock", "invalid lock entry")
        if not isinstance(entry.get("sha256"), str) or hashlib.sha256(jcs_bytes(load_json(_safe_path(root, entry["path"])))).hexdigest() != entry["sha256"]: reject("control_policy.lock_digest_mismatch", "lock digest mismatch")

def _schema(value: object, name: str) -> None:
    if not isinstance(value, dict) or value.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or value.get("type") != "object" or value.get("additionalProperties") is not False or not isinstance(value.get("properties"), dict) or set(value.get("required", [])) != set(value["properties"]): reject("control_policy.invalid_contract", "invalid schema")
    if name.endswith("decision.schema.json") and value["properties"].get("actor_ref") != {"maxLength":96,"pattern":"^[a-z][a-z0-9-]{0,31}/[a-z][a-z0-9-]{0,63}$","type":"string"}: reject("control_policy.invalid_contract", "decision actor_ref schema mismatch")
    if hashlib.sha256(jcs_bytes(value)).hexdigest() != SCHEMA_PROJECTIONS.get(name): reject("control_policy.invalid_contract", "schema semantic projection mismatch")


def verify(root: Path) -> None:
    _verify_lock(root)
    manifest = load_json(root / DIRECTORY / "contract.json")
    if manifest != {"diagnostics":"diagnostics/diagnostics.json","family":FAMILY,"fixtures":"fixtures/cases.json","schemas":SCHEMAS,"side_effects":"forbidden","version":VERSION}: reject("control_policy.invalid_contract", "invalid manifest")
    for relative in SCHEMAS.values(): _schema(load_json(root / DIRECTORY / relative), relative)
    diagnostics = load_json(root / DIRECTORY / "diagnostics" / "diagnostics.json")
    if not isinstance(diagnostics, dict) or set(diagnostics) != {"diagnostics", "version"} or diagnostics.get("version") != VERSION or not isinstance(diagnostics.get("diagnostics"), list): reject("control_policy.invalid_diagnostics", "invalid diagnostics")
    entries = diagnostics["diagnostics"]
    if not all(isinstance(item, dict) and set(item) == {"code"} and isinstance(item["code"], str) and re.fullmatch(r"control_policy\.[a-z_]+", item["code"]) is not None for item in entries) or [item["code"] for item in entries] != sorted(REQUIRED_DIAGNOSTICS, key=lambda item: item.encode("utf-8")): reject("control_policy.invalid_diagnostics", "invalid diagnostics")
    suite = load_json(root / DIRECTORY / "fixtures" / "cases.json")
    if not isinstance(suite, dict) or set(suite) != {"cases", "version"} or suite.get("version") != VERSION or not isinstance(suite.get("cases"), list) or not suite["cases"]: reject("control_policy.invalid_fixtures", "invalid fixture suite")
    if hashlib.sha256(jcs_bytes(suite["cases"])).hexdigest() != FIXTURE_CASES_PROJECTION: reject("control_policy.invalid_fixtures", "fixture semantic projection mismatch")
    ids = [case.get("case_id") for case in suite["cases"] if isinstance(case, dict)]
    if not all(isinstance(item, str) for item in ids) or ids != sorted(ids, key=lambda item: item.encode("utf-8")) or len(set(ids)) != len(ids) or len(ids) != len(suite["cases"]): reject("control_policy.invalid_fixtures", "invalid fixture IDs")
    for case in suite["cases"]:
        if not isinstance(case, dict) or set(case) != {"case_id", "expected", "input"} or not isinstance(case["input"], dict): reject("control_policy.invalid_fixtures", "invalid fixture")
        data = case["input"]
        if set(data) == {"decisions", "reference", "request", "validation_time"}: result = validate_binding(data["decisions"], data["reference"], data["request"], data["validation_time"])
        elif set(data) == {"raw_decisions", "reference", "raw_request", "validation_time"} and isinstance(data["raw_decisions"], list) and all(isinstance(raw, str) for raw in data["raw_decisions"]) and isinstance(data["raw_request"], str): result = validate_binding_bytes([raw.encode("utf-8") for raw in data["raw_decisions"]], data["reference"], data["raw_request"].encode("utf-8"), data["validation_time"])
        else: reject("control_policy.invalid_fixtures", "invalid fixture input")
        if result != case["expected"]: reject("control_policy.invalid_fixtures", "fixture result mismatch")

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    try: verify(parser.parse_args().root.resolve())
    except VerificationError as error: print(error.code, file=sys.stderr); return 1
    print("control-policy 1.0.0 verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
