from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

sys.dont_write_bytecode = True
VERSION = "1.0.0"
DIRECTORY = Path("provenance-record") / VERSION
CONTRACT_PATH = DIRECTORY / "contract.json"
DIAGNOSTICS_PATH = DIRECTORY / "diagnostics" / "diagnostics.json"
FIXTURES_PATH = DIRECTORY / "fixtures" / "cases.json"
LOCK_PATH = DIRECTORY / "lock.json"
SAFE_INTEGER = 9_007_199_254_740_991
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
OPAQUE_REF = re.compile(r"^[a-z][a-z0-9-]{0,31}/[A-Za-z0-9._:@/-]{1,160}$")
RFC3339_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,9})?Z$")
REFERENCE = re.compile(r"^provenance-record/([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9a-f-]{36})@sha256:([0-9a-f]{64})$")
REQUIRED_DIAGNOSTICS = {"provenance.binding_actor_mismatch", "provenance.binding_context_mismatch", "provenance.binding_fingerprint_mismatch", "provenance.binding_intent_mismatch", "provenance.binding_scope_mismatch", "provenance.binding_subject_mismatch", "provenance.derivation_cycle", "provenance.expired", "provenance.invalid_json_bytes", "provenance.lock_digest_mismatch", "provenance.lock_unsafe_path", "provenance.missing_record", "provenance.protected_content", "provenance.revoked", "provenance.unknown_field", "provenance.unsupported_major"}
SENSITIVE_WORDS = ("credential", "secret", "password", "prompt", "memory", "source_text", "original_content", "content_body")
PUBLIC_FAILURE_CODES = REQUIRED_DIAGNOSTICS | {"provenance.invalid_contract", "provenance.invalid_diagnostics", "provenance.invalid_fixtures", "provenance.invalid_lock", "provenance.invalid_record"}

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
            reject("provenance.invalid_json_bytes", "duplicate JSON member")
        result[key] = value
    return result

def _integer(token: str) -> int:
    value = int(token)
    if abs(value) > SAFE_INTEGER:
        reject("provenance.invalid_json_bytes", "unsafe integer")
    return value

def _float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value) or (value.is_integer() and abs(value) > SAFE_INTEGER):
        reject("provenance.invalid_json_bytes", "invalid JSON number")
    return value

def _unicode(value: object) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            reject("provenance.invalid_json_bytes", "unpaired surrogate")
    elif isinstance(value, list):
        for item in value: _unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items(): _unicode(key); _unicode(item)

def parse_json_bytes(raw: bytes, label: str = "input") -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        reject("provenance.invalid_json_bytes", "UTF-8 BOM is forbidden")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_int=_integer, parse_float=_float, parse_constant=lambda _: reject("provenance.invalid_json_bytes", "non-finite number"))
    except VerificationError: raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error: reject("provenance.invalid_json_bytes", "invalid JSON bytes")
    _unicode(value)
    return value

def load_json(path: Path) -> object:
    if not path.is_file(): reject("provenance.missing_record", "missing artifact")
    return parse_json_bytes(path.read_bytes(), path.as_posix())

def _number(value: int | float) -> str:
    if isinstance(value, int): return str(value)
    if not math.isfinite(value): reject("provenance.invalid_json_bytes", "non-finite number")
    if value == 0: return "0"
    text = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":")).lower()
    sign = "-" if text.startswith("-") else ""
    text = text[len(sign):]
    if "e" not in text: return sign + (text[:-2] if text.endswith(".0") else text)
    mantissa, exponent_text = text.split("e")
    exponent = int(exponent_text)
    digits = mantissa.replace(".", "")
    if 1e-6 <= abs(value) < 1e21:
        position = 1 + exponent
        if position <= 0: return sign + "0." + "0" * -position + digits
        if position >= len(digits): return sign + digits + "0" * (position - len(digits))
        return sign + digits[:position] + "." + digits[position:]
    mantissa = mantissa[:-2] if mantissa.endswith(".0") else mantissa
    return f"{sign}{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"

def jcs_bytes(value: object) -> bytes:
    if value is None: return b"null"
    if value is True: return b"true"
    if value is False: return b"false"
    if isinstance(value, (int, float)): return _number(value).encode("ascii")
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list): return b"[" + b",".join(jcs_bytes(item) for item in value) + b"]"
    if isinstance(value, dict): return b"{" + b",".join(jcs_bytes(key) + b":" + jcs_bytes(value[key]) for key in sorted(value, key=lambda key: key.encode("utf-16-be"))) + b"}"
    reject("provenance.invalid_json_bytes", f"unsupported value: {type(value).__name__}")

def record_digest(record: dict[str, object]) -> str:
    return hashlib.sha256(jcs_bytes({key: value for key, value in record.items() if key != "record_digest"})).hexdigest()

def exact_reference(record: dict[str, object]) -> str:
    return f"provenance-record/{VERSION}/{record['record_id']}@sha256:{record['record_digest']}"

def _closed(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict): reject(code, "must be object")
    extras = set(value) - keys
    if extras:
        if any(any(word in key.lower() for word in SENSITIVE_WORDS) for key in extras): reject("provenance.protected_content", "protected content is forbidden")
        reject("provenance.unknown_field", "unknown fields are forbidden")
    if set(value) != keys: reject(code, "required closed fields differ")
    return value

def parse_reference(value: object) -> tuple[str, str]:
    if not isinstance(value, str): reject("provenance.missing_record", "reference must be string")
    match = REFERENCE.fullmatch(value)
    if match is None: reject("provenance.missing_record", "reference must be exact immutable reference")
    major, _, _, record_id, digest = match.groups()
    if major != "1": reject("provenance.unsupported_major", "unsupported major")
    return record_id, digest

def compatibility_state(version: object) -> str:
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        return "rejected"
    major, minor, _ = (int(part) for part in version.split("."))
    if major != 1: return "rejected"
    return "supported" if minor == 0 else "compatible_read"

def _opaque_ref(value: object) -> None:
    if not isinstance(value, str) or len(value) > 192 or value.endswith("/") or ".." in value or "//" in value or OPAQUE_REF.fullmatch(value) is None:
        reject("provenance.invalid_record", "invalid opaque reference")
    if any(word in value.lower() for word in SENSITIVE_WORDS):
        reject("provenance.protected_content", "protected content is forbidden")

def _timestamp(value: object) -> str:
    if not isinstance(value, str) or RFC3339_UTC.fullmatch(value) is None:
        reject("provenance.invalid_record", "invalid UTC timestamp")
    if int(value[11:13]) > 23 or int(value[14:16]) > 59 or int(value[17:19]) > 59:
        reject("provenance.invalid_record", "invalid UTC timestamp")
    try:
        from datetime import datetime
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reject("provenance.invalid_record", "invalid UTC timestamp")
    return value
def validate_record(value: object) -> dict[str, object]:
    keys = {"actor_ref", "authority_scope_ref", "derives_from", "expires_at", "family", "fingerprint", "intent_digest", "record_digest", "record_id", "revoked", "runtime_context_ref", "subject_ref", "valid_from", "version"}
    record = _closed(value, keys, "provenance.invalid_record")
    if record["family"] != "provenance-record": reject("provenance.invalid_record", "invalid record family")
    if record["version"] != VERSION: reject("provenance.invalid_record", "published record version must be exact")
    if not isinstance(record["record_id"], str) or UUID.fullmatch(record["record_id"]) is None: reject("provenance.invalid_record", "record_id must be UUID")
    for key in ("record_digest", "intent_digest", "fingerprint"):
        if not isinstance(record[key], str) or HEX_64.fullmatch(record[key]) is None: reject("provenance.invalid_record", "invalid digest field")
    for key in ("subject_ref", "actor_ref", "authority_scope_ref", "runtime_context_ref"):
        _opaque_ref(record[key])
    record["valid_from"] = _timestamp(record["valid_from"])
    record["expires_at"] = _timestamp(record["expires_at"])
    if not isinstance(record["revoked"], bool) or not isinstance(record["derives_from"], list): reject("provenance.invalid_record", "revoked/derives_from invalid")
    if record["derives_from"] != sorted(set(record["derives_from"])): reject("provenance.invalid_record", "derivation refs must be unique sorted")
    for parent in record["derives_from"]: parse_reference(parent)
    if record["expires_at"] <= record["valid_from"]: reject("provenance.invalid_record", "invalid validity interval")
    if record["record_digest"] != record_digest(record): reject("provenance.lock_digest_mismatch", "record digest mismatch")
    return record

def validate_derivation(records: list[dict[str, object]]) -> None:
    graph = {exact_reference(record): list(record["derives_from"]) for record in records}
    def visit(node: str, seen: set[str], active: set[str]) -> None:
        if node in active: reject("provenance.derivation_cycle", "derivation graph has cycle")
        if node in seen: return
        active.add(node)
        for parent in graph.get(node, []):
            if parent not in graph: reject("provenance.missing_record", "missing derived record")
            visit(parent, seen, active)
        active.remove(node); seen.add(node)
    seen: set[str] = set()
    for node in graph: visit(node, seen, set())

def _rejected(code: str) -> dict[str, str]:
    return {"status": "rejected", "diagnostic": code if code in PUBLIC_FAILURE_CODES else "provenance.invalid_json_bytes"}

def validate_binding_bytes(raw_records: list[bytes], reference: object, raw_request: bytes, validation_time: object) -> dict[str, str]:
    try:
        records = [parse_json_bytes(raw, "record") for raw in raw_records]
        request = parse_json_bytes(raw_request, "request")
        if not all(isinstance(record, dict) for record in records) or not isinstance(request, dict):
            reject("provenance.invalid_json_bytes", "binding bytes must encode objects")
    except VerificationError as error:
        return _rejected(error.code)
    return validate_binding(records, reference, request, validation_time)

def read_record_bytes(raw: bytes) -> dict[str, str]:
    try:
        value = parse_json_bytes(raw, "record")
        if not isinstance(value, dict): reject("provenance.invalid_json_bytes", "record bytes must encode object")
        version = value.get("version")
        state = compatibility_state(version)
        if state == "compatible_read": return {"status": "compatible_read", "diagnostic": ""}
        if state != "supported": return _rejected("provenance.unsupported_major")
        validate_record(value)
    except VerificationError as error:
        return _rejected(error.code)
    return {"status": "valid", "diagnostic": ""}
def validate_binding(records: list[dict[str, object]], reference: object, request: object, validation_time: object) -> dict[str, str]:
    record_id, digest = parse_reference(reference)
    if not isinstance(request, dict): reject("provenance.missing_record", "invalid binding request")
    validation_time = _timestamp(validation_time)
    try:
        normalized = [validate_record(record) for record in records]
        validate_derivation(normalized)
    except VerificationError as error:
        return {"status": "rejected", "diagnostic": error.code}
    candidates = [record for record in normalized if record["record_id"] == record_id and record["record_digest"] == digest]
    if len(candidates) != 1: return {"status": "rejected", "diagnostic": "provenance.missing_record"}
    record = candidates[0]
    if record["revoked"]: return {"status": "rejected", "diagnostic": "provenance.revoked"}
    if not (record["valid_from"] <= validation_time < record["expires_at"]): return {"status": "rejected", "diagnostic": "provenance.expired"}
    expected = {"subject_ref": "provenance.binding_subject_mismatch", "actor_ref": "provenance.binding_actor_mismatch", "authority_scope_ref": "provenance.binding_scope_mismatch", "runtime_context_ref": "provenance.binding_context_mismatch", "intent_digest": "provenance.binding_intent_mismatch", "fingerprint": "provenance.binding_fingerprint_mismatch"}
    for key, code in expected.items():
        if request.get(key) != record[key]: return {"status": "rejected", "diagnostic": code}
    return {"status": "accepted", "diagnostic": ""}

def _safe_path(root: Path, path: object) -> tuple[str, Path]:
    if not isinstance(path, str) or not path or "\\" in path: reject("provenance.lock_unsafe_path", "non-POSIX lock path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) or pure.parts[:2] != ("provenance-record", VERSION): reject("provenance.lock_unsafe_path", "unsafe lock path")
    candidate = (root / Path(*pure.parts)).resolve()
    try: candidate.relative_to(root.resolve())
    except ValueError: reject("provenance.lock_unsafe_path", "lock path escapes contract root")
    return pure.as_posix(), candidate

def validate_lock(root: Path) -> None:
    lock = _closed(load_json(root / LOCK_PATH), {"entries", "version", "self_digest"}, "provenance.invalid_lock")
    if lock["version"] != VERSION or lock["self_digest"] != "excluded" or not isinstance(lock["entries"], list): reject("provenance.invalid_lock", "invalid lock header")
    locked: set[str] = set()
    for entry in lock["entries"]:
        entry = _closed(entry, {"digest_kind", "path", "sha256"}, "provenance.invalid_lock")
        relative, artifact = _safe_path(root, entry["path"])
        if relative == LOCK_PATH.as_posix() or relative in locked or entry["digest_kind"] != "jcs_sha256" or not isinstance(entry["sha256"], str) or HEX_64.fullmatch(entry["sha256"]) is None: reject("provenance.invalid_lock", "invalid lock entry")
        locked.add(relative)
        if hashlib.sha256(jcs_bytes(load_json(artifact))).hexdigest() != entry["sha256"]: reject("provenance.lock_digest_mismatch", "lock digest mismatch")
    actual = {path.relative_to(root).as_posix() for path in (root / DIRECTORY).rglob("*.json") if path.relative_to(root).as_posix() != LOCK_PATH.as_posix()}
    if locked != actual: reject("provenance.invalid_lock", "lock coverage mismatch")

def verify(root: Path) -> None:
    root = root.resolve()
    contract = _closed(load_json(root / CONTRACT_PATH), {"family", "record", "side_effects", "version"}, "provenance.invalid_contract")
    if contract["family"] != "provenance-record" or contract["version"] != VERSION or contract["side_effects"] != "forbidden": reject("provenance.invalid_contract", "identity/side effects differ")
    record = validate_record(contract["record"])
    diagnostics = _closed(load_json(root / DIAGNOSTICS_PATH), {"diagnostics", "version"}, "provenance.invalid_diagnostics")
    if diagnostics["version"] != VERSION or not isinstance(diagnostics["diagnostics"], list) or {item.get("code") for item in diagnostics["diagnostics"] if isinstance(item, dict)} != PUBLIC_FAILURE_CODES: reject("provenance.invalid_diagnostics", "catalog differs")
    fixtures = _closed(load_json(root / FIXTURES_PATH), {"cases", "version"}, "provenance.invalid_fixtures")
    if fixtures["version"] != VERSION or not isinstance(fixtures["cases"], list): reject("provenance.invalid_fixtures", "invalid fixtures")
    if {item.get("case_id") for item in fixtures["cases"] if isinstance(item, dict)} != {"raw-duplicate-key", "newer-minor", "unknown-field"}: reject("provenance.invalid_fixtures", "fixture coverage differs")
    for case in fixtures["cases"]:
        case = _closed(case, {"case_id", "expected", "input_raw"}, "provenance.invalid_fixtures")
        expected = _closed(case["expected"], {"diagnostic", "status"}, "provenance.invalid_fixtures")
        if not isinstance(case["input_raw"], str) or read_record_bytes(case["input_raw"].encode("utf-8")) != expected:
            reject("provenance.invalid_fixtures", "fixture result differs")
    validate_derivation([record]); validate_lock(root)

def main() -> int:
    parser = argparse.ArgumentParser(description="Verify provenance-record 1.0.0")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try: verify(args.root)
    except VerificationError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr); return 1
    print(f"provenance-record {VERSION} verified"); return 0

if __name__ == "__main__": raise SystemExit(main())