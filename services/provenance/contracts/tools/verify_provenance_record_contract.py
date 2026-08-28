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
REFERENCE = re.compile(r"^provenance-record/([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9a-f-]{36})@sha256:([0-9a-f]{64})$")
REQUIRED_DIAGNOSTICS = {"provenance.binding_actor_mismatch", "provenance.binding_context_mismatch", "provenance.binding_fingerprint_mismatch", "provenance.binding_intent_mismatch", "provenance.binding_scope_mismatch", "provenance.binding_subject_mismatch", "provenance.derivation_cycle", "provenance.expired", "provenance.invalid_json_bytes", "provenance.lock_digest_mismatch", "provenance.lock_unsafe_path", "provenance.missing_record", "provenance.protected_content", "provenance.revoked", "provenance.unknown_field", "provenance.unsupported_major"}
SENSITIVE_WORDS = ("credential", "secret", "password", "prompt", "memory", "source_text", "original_content", "content_body")

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
            reject("provenance.invalid_json_bytes", f"duplicate member: {key}")
        result[key] = value
    return result

def _integer(token: str) -> int:
    value = int(token)
    if abs(value) > SAFE_INTEGER:
        reject("provenance.invalid_json_bytes", "unsafe integer")
    return value

def _float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        reject("provenance.invalid_json_bytes", "non-finite number")
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
        reject("provenance.invalid_json_bytes", f"UTF-8 BOM: {label}")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_int=_integer, parse_float=_float, parse_constant=lambda _: reject("provenance.invalid_json_bytes", "non-finite number"))
    except VerificationError: raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error: reject("provenance.invalid_json_bytes", f"invalid JSON: {label}: {error}")
    _unicode(value)
    return value

def load_json(path: Path) -> object:
    if not path.is_file(): reject("provenance.missing_record", f"missing artifact: {path}")
    return parse_json_bytes(path.read_bytes(), path.as_posix())

def _number(value: int | float) -> str:
    if isinstance(value, int): return str(value)
    if value == 0: return "0"
    text = repr(value).lower()
    return text[:-2] if text.endswith(".0") else text

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
        if any(any(word in key.lower() for word in SENSITIVE_WORDS) for key in extras): reject("provenance.protected_content", f"protected field: {sorted(extras)}")
        reject("provenance.unknown_field", f"unknown fields: {sorted(extras)}")
    if set(value) != keys: reject(code, "required closed fields differ")
    return value

def parse_reference(value: object) -> tuple[str, str]:
    if not isinstance(value, str): reject("provenance.missing_record", "reference must be string")
    match = REFERENCE.fullmatch(value)
    if match is None: reject("provenance.missing_record", "reference must be exact immutable reference")
    major, _, _, record_id, digest = match.groups()
    if major != "1": reject("provenance.unsupported_major", f"unsupported major: {major}")
    return record_id, digest

def validate_record(value: object) -> dict[str, object]:
    keys = {"actor_ref", "authority_scope_ref", "derives_from", "expires_at", "family", "fingerprint", "intent_digest", "record_digest", "record_id", "revoked", "runtime_context_ref", "subject_ref", "valid_from", "version"}
    record = _closed(value, keys, "provenance.invalid_record")
    if record["family"] != "provenance-record" or record["version"] != VERSION: reject("provenance.unsupported_major", "record family/version differs")
    if not isinstance(record["record_id"], str) or UUID.fullmatch(record["record_id"]) is None: reject("provenance.invalid_record", "record_id must be UUID")
    for key in ("record_digest", "intent_digest", "fingerprint"):
        if not isinstance(record[key], str) or HEX_64.fullmatch(record[key]) is None: reject("provenance.invalid_record", f"{key} must be sha256")
    for key in ("subject_ref", "actor_ref", "authority_scope_ref", "runtime_context_ref", "valid_from", "expires_at"):
        if not isinstance(record[key], str) or not record[key]: reject("provenance.invalid_record", f"{key} must be non-empty")
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
            if parent not in graph: reject("provenance.missing_record", f"missing parent: {parent}")
            visit(parent, seen, active)
        active.remove(node); seen.add(node)
    seen: set[str] = set()
    for node in graph: visit(node, seen, set())

def validate_binding(records: list[dict[str, object]], reference: object, request: object, validation_time: object) -> dict[str, str]:
    record_id, digest = parse_reference(reference)
    if not isinstance(request, dict) or not isinstance(validation_time, str): reject("provenance.missing_record", "request and deterministic time required")
    candidates = [record for record in records if record["record_id"] == record_id and record["record_digest"] == digest]
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
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) or pure.parts[:2] != ("provenance-record", VERSION): reject("provenance.lock_unsafe_path", f"unsafe path: {path}")
    candidate = (root / Path(*pure.parts)).resolve()
    try: candidate.relative_to(root.resolve())
    except ValueError: reject("provenance.lock_unsafe_path", f"path escapes root: {path}")
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
        if hashlib.sha256(jcs_bytes(load_json(artifact))).hexdigest() != entry["sha256"]: reject("provenance.lock_digest_mismatch", f"digest mismatch: {relative}")
    actual = {path.relative_to(root).as_posix() for path in (root / DIRECTORY).rglob("*.json") if path.relative_to(root).as_posix() != LOCK_PATH.as_posix()}
    if locked != actual: reject("provenance.invalid_lock", "lock coverage mismatch")

def verify(root: Path) -> None:
    root = root.resolve()
    contract = _closed(load_json(root / CONTRACT_PATH), {"family", "record", "side_effects", "version"}, "provenance.invalid_contract")
    if contract["family"] != "provenance-record" or contract["version"] != VERSION or contract["side_effects"] != "forbidden": reject("provenance.invalid_contract", "identity/side effects differ")
    record = validate_record(contract["record"])
    diagnostics = _closed(load_json(root / DIAGNOSTICS_PATH), {"diagnostics", "version"}, "provenance.invalid_diagnostics")
    if diagnostics["version"] != VERSION or not isinstance(diagnostics["diagnostics"], list) or {item.get("code") for item in diagnostics["diagnostics"] if isinstance(item, dict)} != REQUIRED_DIAGNOSTICS: reject("provenance.invalid_diagnostics", "catalog differs")
    fixtures = _closed(load_json(root / FIXTURES_PATH), {"cases", "version"}, "provenance.invalid_fixtures")
    if fixtures["version"] != VERSION or not isinstance(fixtures["cases"], list) or {item.get("case_id") for item in fixtures["cases"] if isinstance(item, dict)} != {"baseline", "missing", "expired", "revoked", "actor", "scope", "context", "intent", "fingerprint", "unknown-major"}: reject("provenance.invalid_fixtures", "coverage differs")
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