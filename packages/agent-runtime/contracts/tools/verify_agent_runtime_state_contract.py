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
MAX_JCS_BYTES = 1_048_576
MAX_STRING_UTF8_BYTES = 262_144
MAX_ARRAY_ELEMENTS = 10_000
MAX_DEPTH = 64
MAX_MEMBERS = 100_000
UUID_V7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ARTIFACT_PATH = re.compile(r"^[a-z0-9][a-z0-9._/-]*\.json$")
STATE_FIELDS = {"contract_version", "state_id", "state_revision", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "status", "activation_epoch", "last_transition_ref"}
REQUIRED_SCHEMA_PATHS = {
    "agent_profile_ref": "schemas/agent-profile-ref.schema.json",
    "agent_runtime_state": "schemas/agent-runtime-state.schema.json",
    "agent_runtime_state_ref": "schemas/agent-runtime-state-ref.schema.json",
    "transition_intent": "schemas/transition-intent.schema.json",
    "transition_plan": "schemas/transition-plan.schema.json",
    "transition_record": "schemas/transition-record.schema.json",
    "aggregate_input": "schemas/aggregate-input.schema.json",
    "aggregate_output": "schemas/aggregate-output.schema.json",
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
    candidate = (root.resolve() / Path(*portable.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("invalid artifact path") from error
    return candidate


def _within_limits(value: Any, *, byte_limit: int = MAX_JCS_BYTES) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    seen: set[int] = set()
    members = 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_DEPTH:
            return False
        if isinstance(current, str):
            try:
                if len(current.encode("utf-8")) > MAX_STRING_UTF8_BYTES:
                    return False
            except UnicodeEncodeError:
                return False
        elif isinstance(current, dict):
            if id(current) in seen:
                return False
            seen.add(id(current)); members += len(current)
            if members > MAX_MEMBERS or any(not isinstance(key, str) for key in current):
                return False
            for key, item in current.items():
                stack.append((key, depth)); stack.append((item, depth + 1))
        elif isinstance(current, list):
            if id(current) in seen or len(current) > MAX_ARRAY_ELEMENTS:
                return False
            seen.add(id(current)); members += len(current)
            if members > MAX_MEMBERS:
                return False
            stack.extend((item, depth + 1) for item in current)
        elif current is not None and (isinstance(current, bool) or not isinstance(current, int) or abs(current) > SAFE_INTEGER):
            return False
    try:
        return len(canonicalize(value)) <= byte_limit
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return False


def _raw_within_limits(raw: bytes) -> bool:
    if len(raw) > MAX_JCS_BYTES:
        return False
    depth, in_string, escaped = 0, False, False
    for byte in raw:
        if in_string:
            if escaped: escaped = False
            elif byte == 0x5C: escaped = True
            elif byte == 0x22: in_string = False
        elif byte == 0x22: in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > MAX_DEPTH: return False
        elif byte in (0x7D, 0x5D): depth -= 1
    return not in_string and depth == 0


def _semver(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or (match := SEMVER.fullmatch(value)) is None or any(len(part) > 18 for part in match.groups()):
        return None
    return tuple(int(part) for part in match.groups())


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "warning" if code == "agent_runtime_state.compatible_read" else "error"}


def _result(mode: str, object_result: str, outcome: str = "succeeded", issue: JsonObject | None = None, **extra: Any) -> JsonObject:
    return {"interface": "agent_runtime_state", "mode": mode, "object_result": object_result, "operation_outcome": outcome, "issues": [] if issue is None else [issue], **extra}


def _invalid(mode: str, code: str, path: str) -> JsonObject:
    return _result(mode, "invalid", "succeeded", _issue(code, path))


def _state_schema(root: Path | None = None) -> JsonObject:
    base = root or REPOSITORY_ROOT / "packages" / "agent-runtime" / "contracts" / "agent-runtime-state" / "1.0.0"
    return _load(_artifact_path(base, "schemas/agent-runtime-state.schema.json"))


def _state_ref(state: JsonObject) -> JsonObject:
    return {"state_id": state["state_id"], "state_revision": state["state_revision"]}


def _profile_ref_valid(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"id", "revision"} and isinstance(value.get("id"), str) and UUID_V7.fullmatch(value["id"]) is not None and isinstance(value.get("revision"), int) and not isinstance(value["revision"], bool) and 1 <= value["revision"] <= SAFE_INTEGER


def validate_state(state: object, schema: object | None = None) -> JsonObject:
    mode = "state"
    if not isinstance(state, dict) or not _within_limits(state):
        return _invalid(mode, "agent_runtime_state.invalid_json", "")
    missing = next((field for field in STATE_FIELDS if field not in state), None)
    if missing is not None:
        return _invalid(mode, "agent_runtime_state.missing_field", f"/{missing}")
    unknown = sorted((field for field in state if field not in STATE_FIELDS), key=lambda item: item.encode("utf-8"))
    if unknown:
        return _invalid(mode, "agent_runtime_state.forbidden_state_field", f"/{_pointer(unknown[0])}")
    version = _semver(state["contract_version"])
    if version is None or version[0] != 1:
        return _invalid(mode, "agent_runtime_state.unsupported_contract_version", "/contract_version")
    if not isinstance(state["state_id"], str) or UUID_V7.fullmatch(state["state_id"]) is None:
        return _invalid(mode, "agent_runtime_state.invalid_state_id", "/state_id")
    for name in ("state_revision", "activation_epoch"):
        value = state[name]
        lower = 1 if name == "state_revision" else 0
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= SAFE_INTEGER:
            return _invalid(mode, "agent_runtime_state.invalid_state_field", f"/{name}")
    if not all(isinstance(state[name], str) and state[name] and len(state[name].encode("utf-8")) <= 256 for name in ("authority_scope_ref", "runtime_context_ref", "last_transition_ref")):
        return _invalid(mode, "agent_runtime_state.invalid_opaque_ref", "/authority_scope_ref")
    if state["status"] not in {"active", "dormant", "archived"}:
        return _invalid(mode, "agent_runtime_state.invalid_status", "/status")
    if not _profile_ref_valid(state["agent_profile_ref"]):
        return _invalid(mode, "agent_runtime_state.invalid_profile_ref", "/agent_profile_ref")
    active_schema = schema if schema is not None else _state_schema()
    if not is_valid(state, active_schema, active_schema):
        return _invalid(mode, "agent_runtime_state.invalid_state_field", "")
    if version > (1, 0, 0):
        return _result(mode, "compatible_read", issue=_issue("agent_runtime_state.compatible_read", "/contract_version"))
    return _result(mode, "valid")


def validate_raw(raw: bytes, root: Path) -> JsonObject:
    if not isinstance(raw, bytes) or not _raw_within_limits(raw):
        return _invalid("transport", "agent_runtime_state.invalid_json", "")
    try:
        state = parse_json_bytes(raw)
    except Exception:
        return _invalid("transport", "agent_runtime_state.invalid_json", "")
    return {**validate_state(state, _state_schema(root)), "mode": "transport"}


def _intent_error(intent: Any) -> tuple[str, str] | None:
    allowed = {"contract_version", "request_id", "operation", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "expected_state", "expected_state_ref", "expected_profile_ref", "target_profile_ref", "reason_ref"}
    if not isinstance(intent, dict) or not _within_limits(intent): return ("agent_runtime_state.invalid_json", "")
    unknown = sorted((field for field in intent if field not in allowed), key=lambda item: item.encode("utf-8"))
    if unknown: return ("agent_runtime_state.invalid_transition_intent", f"/{_pointer(unknown[0])}")
    if _semver(intent.get("contract_version")) != (1, 0, 0): return ("agent_runtime_state.unsupported_contract_version", "/contract_version")
    if not isinstance(intent.get("request_id"), str) or UUID_V7.fullmatch(intent["request_id"]) is None: return ("agent_runtime_state.invalid_transition_intent", "/request_id")
    if intent.get("operation") not in {"create_state", "summon", "close", "archive", "restore", "rebind_profile"}: return ("agent_runtime_state.invalid_transition_intent", "/operation")
    if not all(isinstance(intent.get(name), str) and intent[name] for name in ("authority_scope_ref", "runtime_context_ref")): return ("agent_runtime_state.invalid_opaque_ref", "/authority_scope_ref")
    if not _profile_ref_valid(intent.get("agent_profile_ref")): return ("agent_runtime_state.invalid_profile_ref", "/agent_profile_ref")
    operation = intent["operation"]
    if operation == "create_state":
        if intent.get("expected_state") != "absent" or any(name in intent for name in ("expected_state_ref", "expected_profile_ref", "target_profile_ref")):
            return ("agent_runtime_state.invalid_transition_intent", "/expected_state")
    else:
        ref = intent.get("expected_state_ref")
        if not isinstance(ref, dict) or set(ref) != {"state_id", "state_revision"} or not isinstance(ref.get("state_id"), str) or UUID_V7.fullmatch(ref["state_id"]) is None or isinstance(ref.get("state_revision"), bool) or not isinstance(ref.get("state_revision"), int) or ref["state_revision"] < 1:
            return ("agent_runtime_state.invalid_state_ref", "/expected_state_ref")
        if not _profile_ref_valid(intent.get("expected_profile_ref")):
            return ("agent_runtime_state.invalid_profile_ref", "/expected_profile_ref")
    if operation == "rebind_profile":
        target = intent.get("target_profile_ref")
        if not _profile_ref_valid(target) or target["id"] != intent["agent_profile_ref"]["id"]:
            return ("agent_runtime_state.invalid_rebind", "/target_profile_ref")
    elif "target_profile_ref" in intent:
        return ("agent_runtime_state.invalid_transition_intent", "/target_profile_ref")
    return None


def _plan(intent: JsonObject, disposition: str, before: JsonObject | None, *, target_status: str | None = None, target_profile_ref: JsonObject | None = None) -> JsonObject:
    operation = intent["operation"]
    if before is None:
        return {"operation": operation, "disposition": disposition, "authority_scope_ref": intent["authority_scope_ref"], "runtime_context_ref": intent["runtime_context_ref"], "agent_profile_ref": intent["agent_profile_ref"], "state_ref": None, "target_status": target_status, "state_revision": 1, "activation_epoch": 0}
    return {"operation": operation, "disposition": disposition, "authority_scope_ref": intent["authority_scope_ref"], "runtime_context_ref": intent["runtime_context_ref"], "agent_profile_ref": intent["agent_profile_ref"], "state_ref": _state_ref(before), "target_status": target_status or before["status"], "state_revision": before["state_revision"] + (1 if disposition == "change" else 0), "activation_epoch": before["activation_epoch"] + (1 if disposition == "change" and target_status == "active" else 0), **({"target_profile_ref": target_profile_ref} if target_profile_ref is not None else {})}


def plan_transition(state: object | None, intent: object, schema: object | None = None) -> JsonObject:
    error = _intent_error(intent)
    if error is not None: return _result("transition", "invalid", "rejected", _issue(*error))
    assert isinstance(intent, dict)
    operation = intent["operation"]
    if operation == "create_state":
        if state is not None: return _result("transition", "valid", "conflict", _issue("agent_runtime_state.local_state_exists", "/expected_state"))
        return _result("transition", "valid", plan=_plan(intent, "change", None, target_status="dormant"))
    validation = validate_state(state, schema)
    if validation["object_result"] == "compatible_read":
        return _result("transition", "invalid", "rejected", _issue("agent_runtime_state.unsupported_contract_version", "/contract_version"))
    if validation["object_result"] != "valid":
        return _result("transition", "invalid", "rejected", validation["issues"][0] if validation["issues"] else None)
    assert isinstance(state, dict)
    if any(intent[name] != state[name] for name in ("authority_scope_ref", "runtime_context_ref")):
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.local_state_mismatch", "/runtime_context_ref"))
    if intent["agent_profile_ref"] != state["agent_profile_ref"] or intent["expected_profile_ref"] != state["agent_profile_ref"]:
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.profile_ref_mismatch", "/expected_profile_ref"))
    if intent["expected_state_ref"] != _state_ref(state):
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.stale_state_ref", "/expected_state_ref"))
    status = state["status"]
    transitions = {
        "summon": {"active": "no_change", "dormant": "change", "archived": "rejected"},
        "close": {"active": "change", "dormant": "no_change", "archived": "rejected"},
        "archive": {"active": "rejected", "dormant": "change", "archived": "no_change"},
        "restore": {"active": "rejected", "dormant": "no_change", "archived": "change"},
    }
    if operation == "rebind_profile":
        if status != "dormant": return _result("transition", "valid", "rejected", _issue("agent_runtime_state.forbidden_transition", "/operation"))
        target = intent["target_profile_ref"]
        if target == state["agent_profile_ref"]: return _result("transition", "valid", plan=_plan(intent, "no_change", state, target_profile_ref=target))
        return _result("transition", "valid", plan=_plan(intent, "change", state, target_profile_ref=target))
    outcome = transitions[operation][status]
    if outcome == "rejected": return _result("transition", "valid", "rejected", _issue("agent_runtime_state.forbidden_transition", "/operation"))
    target = {"summon": "active", "close": "dormant", "archive": "archived", "restore": "dormant"}[operation]
    return _result("transition", "valid", plan=_plan(intent, outcome, state, target_status=target))


def aggregate_visible_states(value: object, schema: object | None = None) -> JsonObject:
    if not isinstance(value, dict) or not _within_limits(value) or set(value) != {"contract_version", "visible_states"} or _semver(value.get("contract_version")) is None:
        return _invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", "")
    version = _semver(value["contract_version"])
    if version is None or version[0] != 1:
        return _invalid("aggregate", "agent_runtime_state.unsupported_contract_version", "/contract_version")
    if version > (1, 0, 0): return _result("aggregate", "compatible_read", issue=_issue("agent_runtime_state.compatible_read", "/contract_version"))
    states = value["visible_states"]
    if not isinstance(states, list) or len(states) > MAX_ARRAY_ELEMENTS:
        return _invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", "/visible_states")
    state_ids: set[str] = set(); local_keys: set[tuple[str, str, str]] = set(); counts = {"active": 0, "dormant": 0, "archived": 0}
    for index, state in enumerate(states):
        result = validate_state(state, schema)
        if result["object_result"] != "valid": return _invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", f"/visible_states/{index}")
        assert isinstance(state, dict)
        key = (state["authority_scope_ref"], state["runtime_context_ref"], state["agent_profile_ref"]["id"])
        if state["state_id"] in state_ids or key in local_keys: return _invalid("aggregate", "agent_runtime_state.duplicate_visible_state", f"/visible_states/{index}")
        state_ids.add(state["state_id"]); local_keys.add(key); counts[state["status"]] += 1
    return _result("aggregate", "valid", aggregate={"contract_version": "1.0.0", "visible_state_count": len(states), "active_count": counts["active"], "dormant_count": counts["dormant"], "archived_count": counts["archived"]})


def validate_transition_record(record: object, schema: object | None = None) -> JsonObject:
    mode = "record"
    fields = {"contract_version", "record_id", "request_id", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "operation", "outcome", "before_state", "after_state", "provenance_ref"}
    if not isinstance(record, dict) or not _within_limits(record):
        return _invalid(mode, "agent_runtime_state.invalid_json", "")
    if set(record) != fields or _semver(record.get("contract_version")) != (1, 0, 0):
        return _invalid(mode, "agent_runtime_state.invalid_transition_record", "")
    if not all(isinstance(record.get(name), str) and UUID_V7.fullmatch(record[name]) is not None for name in ("record_id", "request_id")):
        return _invalid(mode, "agent_runtime_state.invalid_transition_record", "/record_id")
    if not all(isinstance(record.get(name), str) and record[name] for name in ("authority_scope_ref", "runtime_context_ref", "provenance_ref")) or not _profile_ref_valid(record.get("agent_profile_ref")):
        return _invalid(mode, "agent_runtime_state.invalid_transition_record", "/authority_scope_ref")
    if record.get("operation") not in {"create_state", "summon", "close", "archive", "restore", "rebind_profile"} or record.get("outcome") not in {"applied", "no_change", "conflict", "rejected"}:
        return _invalid(mode, "agent_runtime_state.invalid_transition_record", "/operation")
    snapshots = []
    for name in ("before_state", "after_state"):
        snapshot = record[name]
        if snapshot is None:
            snapshots.append(None); continue
        required = {"state_id", "state_revision", "status", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref"}
        if not isinstance(snapshot, dict) or set(snapshot) != required or not isinstance(snapshot.get("state_id"), str) or UUID_V7.fullmatch(snapshot["state_id"]) is None or isinstance(snapshot.get("state_revision"), bool) or not isinstance(snapshot.get("state_revision"), int) or snapshot["state_revision"] < 1 or snapshot.get("status") not in {"active", "dormant", "archived"} or not _profile_ref_valid(snapshot.get("agent_profile_ref")):
            return _invalid(mode, "agent_runtime_state.invalid_transition_record", f"/{name}")
        if any(snapshot[key] != record[key] for key in ("authority_scope_ref", "runtime_context_ref", "agent_profile_ref")):
            return _invalid(mode, "agent_runtime_state.record_local_mismatch", f"/{name}")
        snapshots.append(snapshot)
    if snapshots[0] is not None and snapshots[1] is not None and snapshots[0]["state_id"] != snapshots[1]["state_id"]:
        return _invalid(mode, "agent_runtime_state.record_local_mismatch", "/after_state/state_id")
    return _result(mode, "valid")
def validate_case(case: dict, root: Path) -> JsonObject:
    value = case.get("input") if isinstance(case, dict) else None
    if not isinstance(value, dict): return _invalid("state", "agent_runtime_state.invalid_json", "/input")
    mode = value.get("mode")
    if mode == "raw":
        try: return validate_raw(bytes.fromhex(value["raw_hex"]), root)
        except (KeyError, TypeError, ValueError): return _invalid("transport", "agent_runtime_state.invalid_json", "/input/raw_hex")
    if mode == "state": return validate_state(value.get("state"), _state_schema(root))
    if mode == "transition": return plan_transition(value.get("state"), value.get("intent"), _state_schema(root))
    if mode == "aggregate": return aggregate_visible_states(value.get("aggregate_input"), _state_schema(root))
    if mode == "record": return validate_transition_record(value.get("record"))
    return _invalid("state", "agent_runtime_state.invalid_json", "/input/mode")


def _locked_json_paths(root: Path) -> list[str]:
    paths = []
    for path in root.resolve().rglob("*.json"):
        if not path.is_file(): continue
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        if relative == "lock.json": continue
        if ARTIFACT_PATH.fullmatch(relative) is None: raise ValueError("lock closure mismatch")
        paths.append(relative)
    return sorted(paths, key=lambda item: item.encode("utf-8"))


def _jcs_sha256(path: Path) -> str:
    return hashlib.sha256(canonicalize(_load(path))).hexdigest()


def _verify_lock(root: Path) -> None:
    lock = _load(_artifact_path(root, "lock.json"))
    if not isinstance(lock, dict) or set(lock) != {"contract_version", "self_digest", "entries"} or lock.get("contract_version") != "1.0.0" or lock.get("self_digest") != "excluded": raise ValueError("invalid lock")
    actual = _locked_json_paths(root); entries = lock.get("entries")
    if not isinstance(entries, list) or [entry.get("path") if isinstance(entry, dict) else None for entry in entries] != actual: raise ValueError("lock closure mismatch")
    for entry, relative in zip(entries, actual):
        if not isinstance(entry, dict) or set(entry) != {"path", "digest_kind", "sha256"} or entry.get("digest_kind") != "jcs_sha256" or entry.get("sha256") != _jcs_sha256(_artifact_path(root, relative)): raise ValueError("lock digest mismatch")


def _json_pointer_exists(document: Any, fragment: str) -> bool:
    if fragment == "":
        return True
    if not fragment.startswith("/"):
        return False
    current = document
    for token in fragment[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and (token == "0" or not token.startswith("0")) and int(token) < len(current):
            current = current[int(token)]
        else:
            return False
    return True


def _validate_schema_refs(value: Any, root: Path, source_relative: str, declared: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_schema_refs(item, root, source_relative, declared)
        return
    if not isinstance(value, dict):
        return
    reference = value.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise ValueError("invalid schema reference")
        if reference.startswith("#"):
            target_relative, fragment = source_relative, reference[1:]
        else:
            target, separator, fragment = reference.partition("#")
            if not target or not separator or ":" in target or "\\" in target:
                raise ValueError("invalid schema reference")
            candidate = (PurePosixPath(source_relative).parent / PurePosixPath(target)).as_posix()
            if candidate not in declared:
                raise ValueError("invalid schema reference")
            target_relative = candidate
        if not _json_pointer_exists(_load(_artifact_path(root, target_relative)), fragment):
            raise ValueError("invalid schema reference")
    for item in value.values():
        _validate_schema_refs(item, root, source_relative, declared)


def _validate_catalog(catalog: Any) -> dict[str, JsonObject]:
    legal = {("valid", "succeeded"), ("valid", "conflict"), ("valid", "rejected"), ("invalid", "succeeded"), ("invalid", "rejected"), ("compatible_read", "succeeded"), ("compatible_read", "rejected")}
    if not isinstance(catalog, dict) or set(catalog) != {"contract_version", "codes"} or catalog.get("contract_version") != "1.0.0" or not isinstance(catalog["codes"], list): raise ValueError("invalid diagnostic catalog")
    entries: dict[str, JsonObject] = {}
    for entry in catalog["codes"]:
        if not isinstance(entry, dict) or set(entry) != {"code", "severity", "allowed_pairs"} or not isinstance(entry.get("code"), str) or re.fullmatch(r"agent_runtime_state\.[a-z][a-z0-9_]*", entry["code"]) is None or entry.get("severity") not in {"error", "warning"} or not isinstance(entry.get("allowed_pairs"), list) or not entry["allowed_pairs"]: raise ValueError("invalid diagnostic catalog")
        pairs = {tuple(pair) for pair in entry["allowed_pairs"] if isinstance(pair, list) and len(pair) == 2}
        if len(pairs) != len(entry["allowed_pairs"]) or not pairs <= legal or entry["code"] in entries: raise ValueError("invalid diagnostic catalog")
        entries[entry["code"]] = entry
    if list(entries) != sorted(entries, key=lambda item: item.encode("utf-8")): raise ValueError("invalid diagnostic catalog")
    return entries


def verify_contract(root: Path) -> JsonObject:
    root = root.resolve(); _verify_lock(root)
    manifest = _load(_artifact_path(root, "contract.json")); expected_limits = {"contract_jcs_bytes": MAX_JCS_BYTES, "json_array_elements": MAX_ARRAY_ELEMENTS, "json_depth": MAX_DEPTH, "json_members_and_elements": MAX_MEMBERS, "json_string_utf8_bytes": MAX_STRING_UTF8_BYTES}
    if not isinstance(manifest, dict) or set(manifest) != {"contract_family", "contract_version", "side_effects", "set_order", "limits", "schemas", "diagnostics", "fixtures"} or manifest.get("contract_family") != "agent-runtime-state" or manifest.get("contract_version") != "1.0.0" or manifest.get("side_effects") != "forbidden" or manifest.get("set_order") != "unsigned-utf8" or manifest.get("limits") != expected_limits or manifest.get("schemas") != REQUIRED_SCHEMA_PATHS or manifest.get("diagnostics") != {"agent_runtime_state": "diagnostics/agent-runtime-state.json"} or manifest.get("fixtures") != "fixtures/cases.json": raise ValueError("invalid contract manifest")
    for relative in REQUIRED_SCHEMA_PATHS.values():
        schema = _load(_artifact_path(root, relative))
        if not isinstance(schema, dict) or schema.get("type") != "object" or schema.get("additionalProperties") is not False: raise ValueError("invalid contract schema")
        _validate_schema_refs(schema, root, relative, set(REQUIRED_SCHEMA_PATHS.values()))
    catalog = _validate_catalog(_load(_artifact_path(root, manifest["diagnostics"]["agent_runtime_state"])))
    suite = _load(_artifact_path(root, manifest["fixtures"])); cases = suite.get("cases") if isinstance(suite, dict) else None; probes = suite.get("schema_probes") if isinstance(suite, dict) else None
    if not isinstance(suite, dict) or set(suite) != {"contract_version", "cases", "schema_probes"} or suite.get("contract_version") != "1.0.0" or not isinstance(cases, list) or not isinstance(probes, list) or not cases: raise ValueError("fixture suite is invalid")
    case_ids = [case.get("case_id") if isinstance(case, dict) else None for case in cases]
    if case_ids != sorted(case_ids, key=lambda item: item.encode("utf-8")) or len(set(case_ids)) != len(case_ids): raise ValueError("fixture case IDs are invalid or noncanonical")
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"case_id", "input", "expected"}: raise ValueError("fixture case is invalid")
        computed = validate_case(case, root)
        if computed != case["expected"]: raise ValueError(f"fixture result mismatch: {case['case_id']}: {computed!r}")
        for issue in computed["issues"]:
            entry = catalog.get(issue["code"])
            if entry is None or entry["severity"] != issue["severity"] or [computed["object_result"], computed["operation_outcome"]] not in entry["allowed_pairs"]: raise ValueError(f"catalog issue mismatch: {case['case_id']}")
    probe_ids = [probe.get("case_id") if isinstance(probe, dict) else None for probe in probes]
    if probe_ids != sorted(probe_ids, key=lambda item: item.encode("utf-8")) or len(set(probe_ids)) != len(probe_ids): raise ValueError("fixture schema probe IDs are invalid or noncanonical")
    for probe in probes:
        if not isinstance(probe, dict) or set(probe) != {"case_id", "schema", "value", "valid"} or probe["schema"] not in REQUIRED_SCHEMA_PATHS: raise ValueError("fixture schema probe is invalid")
        schema = _load(_artifact_path(root, REQUIRED_SCHEMA_PATHS[probe["schema"]]))
        if is_valid(probe["value"], schema, schema) != probe["valid"]: raise ValueError(f"fixture schema probe mismatch: {probe['case_id']}")
    return {"case_count": len(cases), "contract_version": "1.0.0"}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "agent-runtime-state" / "1.0.0")
    print(json.dumps(verify_contract(parser.parse_args().root), separators=(",", ":"), sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())