from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
COGNITIVE_IR = PACKAGE_ROOT.parent / "cognitive-ir" / "python"
if str(COGNITIVE_IR) not in sys.path:
    sys.path.insert(0, str(COGNITIVE_IR))
from intelliengine_conformance.json_codec import canonicalize, parse_json_bytes
from intelliengine_conformance.schema_validation import is_valid

SAFE_INTEGER = 9_007_199_254_740_991
MAX_BYTES = 1_048_576
MAX_STRING = 262_144
MAX_ARRAY = 10_000
MAX_DEPTH = 64
MAX_MEMBERS = 100_000
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
UUIDV7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
REQUIRED = ("contract_version", "id", "revision", "display_name", "persona", "goals", "working_style", "declared_capabilities", "collaboration_preferences", "provenance_refs")
FORBIDDEN = {"runtime_state", "memory", "private_memory", "model", "model_binding", "permission", "permissions", "team", "project"}

class ContractLoadError(ValueError):
    pass

def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")

def _issue(code: str, path: str) -> dict:
    return {"code": code, "path": path, "severity": "warning" if code == "agent_profile.compatible_read" else "error"}

def _result(mode: str, result: str, outcome: str, issue: dict | None = None) -> dict:
    return {"interface": "agent_profile", "mode": mode, "object_result": result, "operation_outcome": outcome, "issues": [] if issue is None else [issue]}

def _invalid(mode: str, code: str, path: str) -> dict:
    return _result(mode, "invalid", "succeeded", _issue(code, path))

def _unknown(code: str, path: str) -> dict:
    return _result("reference", "not_evaluated", "indeterminate", _issue(code, path))

def _semver(value: object) -> tuple[int, int, int] | None:
    match = SEMVER.fullmatch(value) if isinstance(value, str) else None
    if match is None or any(len(part) > 18 for part in match.groups()):
        return None
    return tuple(int(part) for part in match.groups())

def _set(value: object, required: bool) -> bool | None:
    if not isinstance(value, list) or (required and not value): return None
    try: encoded = [item.encode("utf-8") if isinstance(item, str) and item else None for item in value]
    except UnicodeEncodeError: return None
    if any(item is None for item in encoded): return None
    return len(encoded) == len(set(encoded)) and encoded == sorted(encoded)

def _limits(value: Any, jcs_limit: int = MAX_BYTES) -> bool:
    stack, seen, count = [(value, 1)], set(), 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_DEPTH: return False
        if isinstance(current, str):
            try:
                if len(current.encode("utf-8")) > MAX_STRING: return False
            except UnicodeEncodeError: return False
        elif isinstance(current, dict):
            if id(current) in seen: return False
            seen.add(id(current)); count += len(current)
            if count > MAX_MEMBERS: return False
            for key, child in current.items():
                if not isinstance(key, str): return False
                stack.extend(((key, depth), (child, depth + 1)))
        elif isinstance(current, list):
            if id(current) in seen or len(current) > MAX_ARRAY: return False
            seen.add(id(current)); count += len(current)
            if count > MAX_MEMBERS: return False
            stack.extend((child, depth + 1) for child in current)
        elif current is not None and not isinstance(current, (bool, int, float)): return False
    try: return len(canonicalize(value)) <= jcs_limit
    except Exception: return False

def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or not relative.endswith(".json"):
        raise ContractLoadError("unsafe artifact")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts): raise ContractLoadError("unsafe artifact")
    root = root.resolve(strict=True); candidate = (root / Path(*pure.parts)).resolve(strict=True)
    try: candidate.relative_to(root)
    except ValueError as error: raise ContractLoadError("artifact escape") from error
    return candidate

def _walk_refs(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                if not isinstance(child, str) or not (child == "#" or child.startswith("#/") or (child.endswith(".json") or ".json#" in child)):
                    raise ContractLoadError("external reference")
                if ":" in child or "\\" in child: raise ContractLoadError("external reference")
            _walk_refs(child)
    elif isinstance(value, list):
        for child in value: _walk_refs(child)

def load_locked_contract(contract_root: Path | str) -> dict[str, Any]:
    root = Path(contract_root)
    if root.is_symlink() or root.name != "1.0.0" or root.parent.name != "agent-profile":
        raise ContractLoadError("unsafe contract root")
    root = root.resolve(strict=True)
    lock_path = _safe(root, "lock.json")
    if lock_path.is_symlink(): raise ContractLoadError("unsafe lock")
    lock = parse_json_bytes(lock_path.read_bytes())
    if not isinstance(lock, dict) or lock.get("contract_version") != "1.0.0" or lock.get("self_digest") != "excluded" or not isinstance(lock.get("entries"), list):
        raise ContractLoadError("invalid lock")
    locked, documents = [], {}
    for entry in lock["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "digest_kind", "sha256"} or entry["digest_kind"] != "jcs_sha256" or not re.fullmatch(r"[0-9a-f]{64}", str(entry["sha256"])):
            raise ContractLoadError("invalid lock entry")
        relative = entry["path"]
        if relative == "lock.json" or relative in locked: raise ContractLoadError("invalid lock closure")
        target = _safe(root, relative)
        if target.is_symlink(): raise ContractLoadError("symlink artifact")
        value = parse_json_bytes(target.read_bytes()); digest = hashlib.sha256(canonicalize(value)).hexdigest()
        if digest != entry["sha256"]: raise ContractLoadError("lock mismatch")
        _walk_refs(value); locked.append(relative); documents[relative] = value
    actual = sorted((item.resolve().relative_to(root).as_posix() for item in root.rglob("*.json") if item.is_file() and item.resolve() != lock_path), key=lambda value: value.encode())
    if actual != locked: raise ContractLoadError("lock closure mismatch")
    manifest = documents.get("contract.json")
    if not isinstance(manifest, dict) or manifest.get("contract_version") != "1.0.0" or manifest.get("contract_family") != "agent-profile" or manifest.get("side_effects") != "forbidden":
        raise ContractLoadError("invalid manifest")
    return {"root": root, "documents": documents, "manifest": manifest}

def _loaded(root: Path | str | None) -> dict[str, Any]:
    default = PACKAGE_ROOT / "contracts" / "agent-profile" / "1.0.0"
    return load_locked_contract(default if root is None else root)

def validate_profile(profile: object, contract_root: Path | str | None = None) -> dict:
    loaded = _loaded(contract_root); schema = loaded["documents"]["schemas/agent-profile.schema.json"]
    if not isinstance(profile, dict) or not _limits(profile): return _invalid("profile", "agent_profile.invalid_json", "")
    missing = next((field for field in REQUIRED if field not in profile), None)
    if missing: return _invalid("profile", "agent_profile.missing_field", f"/{missing}")
    unknown = sorted((field for field in profile if field not in REQUIRED), key=lambda value: value.encode())
    if unknown:
        key = unknown[0]; return _invalid("profile", "agent_profile.forbidden_runtime_field" if key in FORBIDDEN else "agent_profile.invalid_profile_field", f"/{_pointer(key)}")
    version = _semver(profile["contract_version"])
    if version is None or version[0] != 1: return _invalid("profile", "agent_profile.unsupported_contract_version", "/contract_version")
    if not isinstance(profile["id"], str) or UUIDV7.fullmatch(profile["id"]) is None: return _invalid("profile", "agent_profile.invalid_id", "/id")
    if isinstance(profile["revision"], bool) or not isinstance(profile["revision"], int) or not 1 <= profile["revision"] <= SAFE_INTEGER: return _invalid("profile", "agent_profile.invalid_revision", "/revision")
    for field in ("goals", "declared_capabilities", "provenance_refs"):
        valid = _set(profile[field], True)
        if valid is None: return _invalid("profile", "agent_profile.invalid_profile_field", f"/{field}")
        if not valid: return _invalid("profile", "agent_profile.noncanonical_set", f"/{field}")
    if isinstance(profile["persona"], dict) and "principles" in profile["persona"]:
        principle_set = _set(profile["persona"]["principles"], False)
        if principle_set is False: return _invalid("profile", "agent_profile.noncanonical_set", "/persona/principles")
    if not is_valid(profile, schema, schema):
        invalid = next((field for field in REQUIRED if not is_valid(profile[field], schema["properties"][field], schema)), "")
        return _invalid("profile", "agent_profile.invalid_profile_field", f"/{invalid}" if invalid else "")
    return _result("profile", "compatible_read", "succeeded", _issue("agent_profile.compatible_read", "/contract_version")) if version > (1, 0, 0) else _result("profile", "valid", "succeeded")

def parse_and_validate_transport(raw: bytes, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES: return _invalid("transport", "agent_profile.invalid_json", "")
    try: profile = parse_json_bytes(raw)
    except Exception: return _invalid("transport", "agent_profile.invalid_json", "")
    result = validate_profile(profile, contract_root); result["mode"] = "transport"; return result

def validate_references(profile: object, snapshot: object | None, contract_root: Path | str | None = None) -> dict:
    loaded = _loaded(contract_root); profile_result = validate_profile(profile, loaded["root"])
    if profile_result["object_result"] == "invalid": profile_result["mode"] = "reference"; return profile_result
    if profile_result["object_result"] == "compatible_read": return _unknown("agent_profile.reference_snapshot_incomplete", "/contract_version")
    schema = loaded["documents"]["schemas/reference-snapshot.schema.json"]
    if not isinstance(snapshot, dict) or not _limits(snapshot): return _unknown("agent_profile.reference_snapshot_incomplete", "")
    extra = sorted(set(snapshot) - {"contract_version", "provenance"}, key=lambda value: value.encode())
    if extra or _semver(snapshot.get("contract_version")) != (1, 0, 0) or not is_valid(snapshot, schema, schema): return _unknown("agent_profile.reference_snapshot_incomplete", f"/{_pointer(extra[0])}" if extra else "/contract_version" if _semver(snapshot.get("contract_version")) != (1, 0, 0) else "/provenance")
    indexed, last = {}, None
    for index, entry in enumerate(snapshot["provenance"]):
        key = entry["ref"].encode("utf-8")
        if (last is not None and key <= last): return _unknown("agent_profile.reference_snapshot_incomplete", f"/provenance/{index}/ref")
        last = key; indexed[entry["ref"]] = (index, entry["object_result"])
    assert isinstance(profile, dict)
    for index, ref in enumerate(profile["provenance_refs"]):
        item = indexed.get(ref)
        if item is None or item[1] == "invalid": return _invalid("reference", "agent_profile.dangling_provenance_reference", f"/provenance_refs/{index}")
        if item[1] in ("opaque", "compatible_read"): return _unknown("agent_profile.opaque_provenance_reference", f"/provenance_refs/{index}")
    refs = set(profile["provenance_refs"])
    for ref, (index, _) in indexed.items():
        if ref not in refs: return _invalid("reference", "agent_profile.dangling_provenance_reference", f"/provenance/{index}/ref")
    return _result("reference", "valid", "succeeded")

def validate_revision_transition(previous: object, candidate: object, contract_root: Path | str | None = None) -> dict:
    loaded = _loaded(contract_root)
    for value in (previous, candidate):
        result = validate_profile(value, loaded["root"])
        if result["object_result"] == "invalid": result["mode"] = "revision_transition"; return result
        if result["object_result"] == "compatible_read": return _invalid("revision_transition", "agent_profile.unsupported_contract_version", "/contract_version")
    assert isinstance(previous, dict) and isinstance(candidate, dict)
    if previous["id"] != candidate["id"]: return _invalid("revision_transition", "agent_profile.revision_identity_mismatch", "/id")
    if candidate["revision"] <= previous["revision"]: return _invalid("revision_transition", "agent_profile.revision_not_increased", "/revision")
    before, after = copy.deepcopy(previous), copy.deepcopy(candidate); before.pop("revision"); after.pop("revision")
    return _invalid("revision_transition", "agent_profile.revision_without_change", "/revision") if canonicalize(before) == canonicalize(after) else _result("revision_transition", "valid", "succeeded")

def profile_summary(profile: object, contract_root: Path | str | None = None) -> dict:
    validation = validate_profile(profile, contract_root)
    if validation["object_result"] not in ("valid", "compatible_read"): return {"validation": validation, "summary": None}
    assert isinstance(profile, dict)
    return {"validation": validation, "summary": {"id": profile["id"], "revision": profile["revision"], "display_name": profile["display_name"], "declared_capabilities": list(profile["declared_capabilities"]), "goals": list(profile["goals"])}}

def _case_result(case: dict, root: Path) -> dict:
    data = case.get("input", {})
    mode = data.get("mode") if isinstance(data, dict) else None
    if mode == "raw":
        try: return parse_and_validate_transport(bytes.fromhex(data["raw_hex"]), root)
        except Exception: return _invalid("transport", "agent_profile.invalid_json", "/input/raw_hex")
    if mode == "profile": return validate_profile(data.get("profile"), root)
    if mode == "reference": return validate_references(data.get("profile"), data.get("snapshot"), root)
    if mode == "revision_transition": return validate_revision_transition(data.get("previous"), data.get("candidate"), root)
    return _invalid("profile", "agent_profile.invalid_json", "/input/mode")

def execute_fixture_suite(contract_root: Path | str) -> list[dict]:
    loaded = _loaded(contract_root); suite = loaded["documents"]["fixtures/cases.json"]
    return [{"case_id": case["case_id"], "actual": _case_result(case, loaded["root"]), "expected": copy.deepcopy(case["expected"])} for case in suite["cases"]]