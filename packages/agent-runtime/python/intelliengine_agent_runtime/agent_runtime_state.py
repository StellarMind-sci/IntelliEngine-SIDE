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

SAFE = 9_007_199_254_740_991
MAX = 1_048_576
MAX_STRING = 262_144
MAX_ARRAY = 10_000
MAX_DEPTH = 64
MAX_MEMBERS = 100_000
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
UUIDV7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
STATE_FIELDS = ("contract_version", "state_id", "state_revision", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "status", "activation_epoch", "last_transition_ref")
INTENT_FIELDS = ("contract_version", "request_id", "operation", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "expected_state", "expected_state_ref", "expected_profile_ref", "target_profile_ref", "reason_ref")
RECORD_FIELDS = ("contract_version", "record_id", "request_id", "authority_scope_ref", "runtime_context_ref", "agent_profile_id", "operation", "outcome", "before_state", "after_state", "provenance_ref")
OPERATIONS = {"create_state", "summon", "close", "archive", "restore", "rebind_profile"}
STATUSES = {"active", "dormant", "archived"}
FORBIDDEN = {"persona", "goals", "role", "capability", "capabilities", "memory", "private_memory", "model", "model_binding", "permission", "permissions", "team", "project", "task", "process", "output", "ui_state"}

class ContractLoadError(ValueError):
    pass

def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")

def _issue(code: str, path: str) -> dict:
    return {"code": code, "path": path, "severity": "warning" if code == "agent_runtime_state.compatible_read" else "error"}

def _result(mode: str, object_result: str, outcome: str, issue: dict | None = None, **extra: Any) -> dict:
    value = {"interface": "agent_runtime_state", "mode": mode, "object_result": object_result, "operation_outcome": outcome, "issues": [] if issue is None else [issue]}
    value.update(extra)
    return value

def _invalid(mode: str, code: str, path: str, outcome: str = "succeeded") -> dict:
    return _result(mode, "invalid", outcome, _issue(code, path))

def _object(value: Any) -> bool:
    return isinstance(value, dict)

def _semver(value: Any) -> tuple[int, int, int] | None:
    match = SEMVER.fullmatch(value) if isinstance(value, str) else None
    if match is None or any(len(part) > 18 for part in match.groups()):
        return None
    return tuple(int(part) for part in match.groups())

def _version(value: Any) -> str:
    parsed = _semver(value)
    if parsed is None or parsed[0] != 1:
        return "invalid"
    return "exact" if parsed == (1, 0, 0) else "compatible"

def _integer(value: Any, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= SAFE

def _scalar(value: Any) -> bool:
    if isinstance(value, str):
        try:
            return all(not 0xD800 <= ord(item) <= 0xDFFF for item in value)
        except TypeError:
            return False
    if isinstance(value, list):
        return all(_scalar(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _scalar(key) and _scalar(item) for key, item in value.items())
    return value is None or isinstance(value, (bool, int, float))

def _limits(value: Any) -> bool:
    stack, seen, count = [(value, 1)], set(), 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_DEPTH:
            return False
        if isinstance(current, str):
            try:
                if len(current.encode("utf-8")) > MAX_STRING:
                    return False
            except UnicodeEncodeError:
                return False
        elif isinstance(current, dict):
            if id(current) in seen:
                return False
            seen.add(id(current)); count += len(current)
            if count > MAX_MEMBERS:
                return False
            stack.extend((key, depth) for key in current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if id(current) in seen or len(current) > MAX_ARRAY:
                return False
            seen.add(id(current)); count += len(current)
            if count > MAX_MEMBERS:
                return False
            stack.extend((item, depth + 1) for item in current)
        elif current is not None and not isinstance(current, (bool, int, float)):
            return False
    try:
        return len(canonicalize(value)) <= MAX
    except Exception:
        return False

def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or not relative.endswith(".json"):
        raise ContractLoadError("unsafe artifact")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise ContractLoadError("unsafe artifact")
    candidate = (root / Path(*pure.parts)).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ContractLoadError("artifact escape") from error
    return candidate

def _walk_refs(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                if not isinstance(child, str) or not (child == "#" or child.startswith("#/") or child.endswith(".json") or ".json#" in child) or ":" in child or "\\" in child:
                    raise ContractLoadError("external reference")
            _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            _walk_refs(child)

def _pointer_exists(document: Any, fragment: str) -> bool:
    if fragment == "":
        return True
    if not fragment.startswith("/"):
        return False
    current = document
    for token in fragment[1:].split("/"):
        decoded, index = "", 0
        while index < len(token):
            if token[index] != "~":
                decoded += token[index]; index += 1; continue
            if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                return False
            decoded += "~" if token[index + 1] == "0" else "/"; index += 2
        if isinstance(current, dict) and decoded in current:
            current = current[decoded]
        elif isinstance(current, list) and decoded.isdigit() and (len(decoded) == 1 or not decoded.startswith("0")) and int(decoded) < len(current):
            current = current[int(decoded)]
        else:
            return False
    return True

def _validate_refs(value: Any, documents: dict[str, Any], source: str) -> None:
    if isinstance(value, list):
        for child in value:
            _validate_refs(child, documents, source)
        return
    if not isinstance(value, dict):
        return
    reference = value.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise ContractLoadError("invalid schema reference")
        if reference.startswith("#"):
            target, fragment = source, reference[1:]
        else:
            target_text, marker, fragment = reference.partition("#")
            pure = PurePosixPath(target_text)
            if not target_text or ":" in target_text or "\\" in target_text or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise ContractLoadError("invalid schema reference")
            target = (PurePosixPath(source).parent / pure).as_posix()
            if not marker:
                fragment = ""
        if target not in documents or not _pointer_exists(documents[target], fragment):
            raise ContractLoadError("invalid schema reference")
    for child in value.values():
        _validate_refs(child, documents, source)
def load_locked_contract(contract_root: Path | str) -> dict[str, Any]:
    root = Path(contract_root)
    if root.is_symlink() or root.name != "1.0.0" or root.parent.name != "agent-runtime-state":
        raise ContractLoadError("unsafe contract root")
    root = root.resolve(strict=True)
    lock_path = _safe(root, "lock.json")
    lock = parse_json_bytes(lock_path.read_bytes())
    if not _object(lock) or lock.get("contract_version") != "1.0.0" or lock.get("self_digest") != "excluded" or not isinstance(lock.get("entries"), list):
        raise ContractLoadError("invalid lock")
    paths: list[str] = []; documents: dict[str, Any] = {}
    for entry in lock["entries"]:
        if not _object(entry) or set(entry) != {"path", "digest_kind", "sha256"} or entry["digest_kind"] != "jcs_sha256" or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None:
            raise ContractLoadError("invalid lock entry")
        relative = entry["path"]
        if relative == "lock.json" or relative in paths:
            raise ContractLoadError("invalid lock closure")
        target = _safe(root, relative)
        if target.is_symlink():
            raise ContractLoadError("symlink artifact")
        value = parse_json_bytes(target.read_bytes())
        _walk_refs(value)
        if hashlib.sha256(canonicalize(value)).hexdigest() != entry["sha256"]:
            raise ContractLoadError("lock mismatch")
        paths.append(relative); documents[relative] = value
    actual = sorted((item.resolve().relative_to(root).as_posix() for item in root.rglob("*.json") if item.resolve() != lock_path), key=lambda item: item.encode())
    if paths != actual:
        raise ContractLoadError("lock closure mismatch")
    for source, document in documents.items():
        _validate_refs(document, documents, source)
    manifest = documents.get("contract.json")
    if not _object(manifest) or manifest.get("contract_family") != "agent-runtime-state" or manifest.get("contract_version") != "1.0.0" or manifest.get("side_effects") != "forbidden":
        raise ContractLoadError("invalid manifest")
    return {"root": root, "documents": documents, "manifest": manifest}

def _loaded(root: Path | str | None) -> dict[str, Any]:
    return load_locked_contract(PACKAGE_ROOT / "contracts" / "agent-runtime-state" / "1.0.0" if root is None else root)

def _profile_ref(value: Any) -> bool:
    return _object(value) and set(value) == {"id", "revision"} and isinstance(value["id"], str) and UUIDV7.fullmatch(value["id"]) is not None and _integer(value["revision"], 1)

def _state_ref(value: Any) -> bool:
    return _object(value) and set(value) == {"state_id", "state_revision"} and isinstance(value["state_id"], str) and UUIDV7.fullmatch(value["state_id"]) is not None and _integer(value["state_revision"], 1)

def _opaque(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value.encode("utf-8")) <= 256

def validate_state(state: Any, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    if not _object(state) or not _scalar(state) or not _limits(state):
        return _invalid("state", "agent_runtime_state.invalid_json", "")
    missing = next((field for field in STATE_FIELDS if field not in state), None)
    if missing:
        return _invalid("state", "agent_runtime_state.missing_field", f"/{missing}")
    extra = sorted((field for field in state if field not in STATE_FIELDS), key=lambda item: item.encode())
    if extra:
        code = "agent_runtime_state.forbidden_state_field" if extra[0] in FORBIDDEN else "agent_runtime_state.invalid_state_field"
        return _invalid("state", code, f"/{_pointer(extra[0])}")
    version = _version(state["contract_version"])
    if version == "invalid":
        return _invalid("state", "agent_runtime_state.unsupported_contract_version", "/contract_version")
    if not isinstance(state["state_id"], str) or UUIDV7.fullmatch(state["state_id"]) is None:
        return _invalid("state", "agent_runtime_state.invalid_state_id", "/state_id")
    if not _integer(state["state_revision"], 1):
        return _invalid("state", "agent_runtime_state.invalid_state_field", "/state_revision")
    if not _opaque(state["authority_scope_ref"]):
        return _invalid("state", "agent_runtime_state.invalid_opaque_ref", "/authority_scope_ref")
    if not _opaque(state["runtime_context_ref"]):
        return _invalid("state", "agent_runtime_state.invalid_opaque_ref", "/runtime_context_ref")
    if not _profile_ref(state["agent_profile_ref"]):
        return _invalid("state", "agent_runtime_state.invalid_profile_ref", "/agent_profile_ref")
    if state["status"] not in STATUSES:
        return _invalid("state", "agent_runtime_state.invalid_status", "/status")
    if not _integer(state["activation_epoch"]):
        return _invalid("state", "agent_runtime_state.invalid_state_field", "/activation_epoch")
    if not _opaque(state["last_transition_ref"]):
        return _invalid("state", "agent_runtime_state.invalid_opaque_ref", "/last_transition_ref")
    return _result("state", "compatible_read", "succeeded", _issue("agent_runtime_state.compatible_read", "/contract_version")) if version == "compatible" else _result("state", "valid", "succeeded")

def _raw_state_integer_issue(raw: bytes) -> tuple[str, str] | None:
    try:
        text, index, issue = raw.decode("utf-8", "strict"), 0, None
        targets = {
            "/state_revision": "agent_runtime_state.invalid_state_field",
            "/activation_epoch": "agent_runtime_state.invalid_state_field",
            "/agent_profile_ref/revision": "agent_runtime_state.invalid_profile_ref",
        }
        def space() -> None:
            nonlocal index
            while index < len(text) and text[index] in " \t\r\n":
                index += 1
        def string() -> str:
            nonlocal index
            if text[index] != '"':
                raise ValueError("string")
            index += 1; value = ""
            while index < len(text):
                character = text[index]; index += 1
                if character == '"':
                    return value
                if character != "\\":
                    value += character; continue
                escape = text[index]; index += 1
                named = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
                if escape in named:
                    value += named[escape]; continue
                if escape != "u" or not re.fullmatch(r"[0-9a-fA-F]{4}", text[index:index + 4]):
                    raise ValueError("escape")
                value += chr(int(text[index:index + 4], 16)); index += 4
            raise ValueError("string")
        def scalar() -> str:
            nonlocal index
            match = re.match(r"(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)", text[index:])
            if match is None:
                raise ValueError("value")
            index += len(match.group(0)); return match.group(0)
        def value(path: str) -> None:
            space()
            if text[index] == '"':
                string(); return
            if text[index] == "{":
                object(path); return
            if text[index] == "[":
                index_array(); return
            scalar()
        def index_array() -> None:
            nonlocal index
            index += 1; space()
            if text[index] == "]":
                index += 1; return
            while True:
                value(""); space()
                if text[index] == "]":
                    index += 1; return
                if text[index] != ",":
                    raise ValueError("array")
                index += 1
        def object(path: str) -> None:
            nonlocal index, issue
            index += 1; space()
            if text[index] == "}":
                index += 1; return
            while True:
                space(); key = string(); child_path = f"{path}/{_pointer(key)}"; space()
                if text[index] != ":":
                    raise ValueError("object")
                index += 1; space()
                if child_path in targets:
                    token = re.match(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text[index:])
                    if token is not None:
                        index += len(token.group(0))
                        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", token.group(0)) and issue is None:
                            issue = (targets[child_path], child_path)
                    else:
                        value(child_path)
                else:
                    value(child_path)
                space()
                if text[index] == "}":
                    index += 1; return
                if text[index] != ",":
                    raise ValueError("object")
                index += 1
        space(); object(""); space()
        return issue
    except (IndexError, UnicodeDecodeError, ValueError):
        return None
def parse_and_validate_transport(raw: bytes, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    if not isinstance(raw, bytes) or len(raw) > MAX:
        return _invalid("transport", "agent_runtime_state.invalid_json", "")
    try:
        value = parse_json_bytes(raw)
    except Exception:
        return _invalid("transport", "agent_runtime_state.invalid_json", "")
    lexical = _raw_state_integer_issue(raw)
    if lexical is not None:
        return _invalid("transport", *lexical)
    value = validate_state(value, contract_root)
    value["mode"] = "transport"
    return value

def _validate_intent(intent: Any) -> tuple[dict | None, str]:
    if not _object(intent) or not _scalar(intent) or not _limits(intent):
        return _invalid("transition", "agent_runtime_state.invalid_transition_intent", "", "rejected"), ""
    missing = next((field for field in ("contract_version", "request_id", "operation", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref") if field not in intent), None)
    if missing or any(field not in INTENT_FIELDS for field in intent):
        path = f"/{missing}" if missing else f"/{_pointer(sorted((field for field in intent if field not in INTENT_FIELDS), key=lambda item: item.encode())[0])}"
        return _invalid("transition", "agent_runtime_state.invalid_transition_intent", path, "rejected"), ""
    if _version(intent["contract_version"]) != "exact":
        return _invalid("transition", "agent_runtime_state.unsupported_contract_version", "/contract_version", "rejected"), ""
    operation = intent["operation"]
    if operation not in OPERATIONS or not isinstance(intent["request_id"], str) or UUIDV7.fullmatch(intent["request_id"]) is None or not _opaque(intent["authority_scope_ref"]) or not _opaque(intent["runtime_context_ref"]) or not _profile_ref(intent["agent_profile_ref"]):
        return _invalid("transition", "agent_runtime_state.invalid_transition_intent", "/operation", "rejected"), ""
    if operation == "create_state":
        if intent.get("expected_state") != "absent" or any(field in intent for field in ("expected_state_ref", "expected_profile_ref", "target_profile_ref")):
            return _invalid("transition", "agent_runtime_state.invalid_transition_intent", "/expected_state", "rejected"), ""
    else:
        if not _state_ref(intent.get("expected_state_ref")):
            return _invalid("transition", "agent_runtime_state.invalid_state_ref", "/expected_state_ref", "rejected"), ""
        if not _profile_ref(intent.get("expected_profile_ref")):
            return _invalid("transition", "agent_runtime_state.invalid_profile_ref", "/expected_profile_ref", "rejected"), ""
        if operation == "rebind_profile" and not _profile_ref(intent.get("target_profile_ref")):
            return _invalid("transition", "agent_runtime_state.invalid_rebind", "/target_profile_ref", "rejected"), ""
        if operation != "rebind_profile" and "target_profile_ref" in intent:
            return _invalid("transition", "agent_runtime_state.invalid_transition_intent", "/target_profile_ref", "rejected"), ""
    return None, operation

def _plan(intent: dict, state: dict | None, target_status: str, disposition: str, target_profile_ref: dict | None = None) -> dict:
    change = disposition == "change"
    value = {"operation": intent["operation"], "disposition": disposition, "authority_scope_ref": intent["authority_scope_ref"], "runtime_context_ref": intent["runtime_context_ref"], "agent_profile_ref": copy.deepcopy(intent["agent_profile_ref"]), "state_ref": None if state is None else {"state_id": state["state_id"], "state_revision": state["state_revision"]}, "target_status": target_status, "state_revision": 1 if state is None else state["state_revision"] + (1 if change else 0), "activation_epoch": 0 if state is None else state["activation_epoch"] + (1 if change and target_status == "active" else 0)}
    if target_profile_ref is not None:
        value["target_profile_ref"] = copy.deepcopy(target_profile_ref)
    return value

def plan_transition(state: Any, intent: Any, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    invalid_intent, operation = _validate_intent(intent)
    if invalid_intent is not None:
        return invalid_intent
    assert isinstance(intent, dict)
    if operation == "create_state":
        if state is None:
            return _result("transition", "valid", "succeeded", plan=_plan(intent, None, "dormant", "change"))
        state_result = validate_state(state, contract_root)
        if state_result["object_result"] == "invalid":
            return {**state_result, "mode": "transition", "operation_outcome": "rejected"}
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.local_state_exists", "/expected_state"))
    state_result = validate_state(state, contract_root)
    if state_result["object_result"] != "valid":
        return _invalid("transition", "agent_runtime_state.unsupported_contract_version", "/contract_version", "rejected") if state_result["object_result"] == "compatible_read" else {**state_result, "mode": "transition", "operation_outcome": "rejected"}
    assert isinstance(state, dict)
    for field in ("authority_scope_ref", "runtime_context_ref"):
        if state[field] != intent[field]:
            return _result("transition", "valid", "conflict", _issue("agent_runtime_state.local_state_mismatch", f"/{field}"))
    if state["agent_profile_ref"] != intent["agent_profile_ref"] or state["agent_profile_ref"] != intent["expected_profile_ref"]:
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.profile_ref_mismatch", "/expected_profile_ref"))
    if state["state_id"] != intent["expected_state_ref"]["state_id"] or state["state_revision"] != intent["expected_state_ref"]["state_revision"]:
        return _result("transition", "valid", "conflict", _issue("agent_runtime_state.stale_state_ref", "/expected_state_ref"))
    status = state["status"]
    if operation == "rebind_profile":
        target = intent["target_profile_ref"]
        if target["id"] != state["agent_profile_ref"]["id"]:
            return _invalid("transition", "agent_runtime_state.invalid_rebind", "/target_profile_ref", "rejected")
        if status != "dormant":
            return _result("transition", "valid", "rejected", _issue("agent_runtime_state.forbidden_transition", "/operation"))
        disposition = "no_change" if target == state["agent_profile_ref"] else "change"
        return _result("transition", "valid", "succeeded", plan=_plan(intent, state, "dormant", disposition, target))
    table = {
        "summon": {"dormant": ("active", "change"), "active": ("active", "no_change")},
        "close": {"active": ("dormant", "change"), "dormant": ("dormant", "no_change")},
        "archive": {"dormant": ("archived", "change"), "archived": ("archived", "no_change")},
        "restore": {"archived": ("dormant", "change"), "dormant": ("dormant", "no_change")},
    }
    target = table[operation].get(status)
    if target is None:
        return _result("transition", "valid", "rejected", _issue("agent_runtime_state.forbidden_transition", "/operation"))
    return _result("transition", "valid", "succeeded", plan=_plan(intent, state, *target))

def state_summary(state: Any, contract_root: Path | str | None = None) -> dict:
    validation = validate_state(state, contract_root)
    if validation["object_result"] not in ("valid", "compatible_read"):
        return {"validation": validation, "summary": None}
    assert isinstance(state, dict)
    return {"validation": validation, "summary": {"state_id": state["state_id"], "state_revision": state["state_revision"], "status": state["status"], "activation_epoch": state["activation_epoch"]}}

def aggregate_visible_states(aggregate_input: Any, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    if not _object(aggregate_input) or not _scalar(aggregate_input) or not _limits(aggregate_input) or set(aggregate_input) != {"contract_version", "visible_states"} or _version(aggregate_input.get("contract_version")) != "exact" or not isinstance(aggregate_input.get("visible_states"), list):
        return _invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", "")
    seen: set[str] = set(); counts = {"active": 0, "dormant": 0, "archived": 0}
    for index, state in enumerate(aggregate_input["visible_states"]):
        validation = validate_state(state, contract_root)
        if validation["object_result"] != "valid":
            return _invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", f"/visible_states/{index}")
        assert isinstance(state, dict)
        if state["state_id"] in seen:
            return _invalid("aggregate", "agent_runtime_state.duplicate_visible_state", f"/visible_states/{index}")
        seen.add(state["state_id"]); counts[state["status"]] += 1
    return _result("aggregate", "valid", "succeeded", aggregate={"contract_version": "1.0.0", "visible_state_count": len(aggregate_input["visible_states"]), "active_count": counts["active"], "dormant_count": counts["dormant"], "archived_count": counts["archived"]})

def _record_state(value: Any) -> bool:
    required = {"state_id", "state_revision", "status", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref"}
    return _object(value) and set(value) == required and isinstance(value["state_id"], str) and UUIDV7.fullmatch(value["state_id"]) is not None and _integer(value["state_revision"], 1) and value["status"] in STATUSES and _opaque(value["authority_scope_ref"]) and _opaque(value["runtime_context_ref"]) and _profile_ref(value["agent_profile_ref"])

def validate_transition_record(record: Any, contract_root: Path | str | None = None) -> dict:
    _loaded(contract_root)
    if not _object(record) or not _scalar(record) or not _limits(record) or set(record) != set(RECORD_FIELDS):
        return _invalid("record", "agent_runtime_state.invalid_transition_record", "")
    if _version(record["contract_version"]) != "exact" or not all(isinstance(record[field], str) and UUIDV7.fullmatch(record[field]) is not None for field in ("record_id", "request_id", "agent_profile_id")) or record["operation"] not in OPERATIONS or record["outcome"] not in {"applied", "no_change", "conflict", "rejected"} or not _opaque(record["authority_scope_ref"]) or not _opaque(record["runtime_context_ref"]) or not _opaque(record["provenance_ref"]) or not (record["before_state"] is None or _record_state(record["before_state"])) or not (record["after_state"] is None or _record_state(record["after_state"])):
        return _invalid("record", "agent_runtime_state.invalid_transition_record", "")
    before, after = record["before_state"], record["after_state"]
    for path, value in (("/before_state", before), ("/after_state", after)):
        if value is not None and (value["authority_scope_ref"] != record["authority_scope_ref"] or value["runtime_context_ref"] != record["runtime_context_ref"] or value["agent_profile_ref"]["id"] != record["agent_profile_id"]):
            return _invalid("record", "agent_runtime_state.record_local_mismatch", path)
    if before is not None and after is not None:
        if before["state_id"] != after["state_id"]:
            return _invalid("record", "agent_runtime_state.record_local_mismatch", "/after_state/state_id")
        if record["operation"] == "rebind_profile" and before["agent_profile_ref"]["id"] != after["agent_profile_ref"]["id"]:
            return _invalid("record", "agent_runtime_state.record_local_mismatch", "/after_state")
        if record["outcome"] == "applied" and after["state_revision"] != before["state_revision"] + 1:
            return _invalid("record", "agent_runtime_state.record_state_mismatch", "/after_state/state_revision")
    return _result("record", "valid", "succeeded")

def _case_result(case: Any, root: Path) -> dict:
    data = case.get("input") if _object(case) else None
    if not _object(data):
        return _invalid("state", "agent_runtime_state.invalid_json", "/input")
    mode = data.get("mode")
    if mode == "raw":
        try:
            return parse_and_validate_transport(bytes.fromhex(data["raw_hex"]), root)
        except Exception:
            return _invalid("transport", "agent_runtime_state.invalid_json", "/input/raw_hex")
    if mode == "state":
        return validate_state(data.get("state"), root)
    if mode == "transition":
        return plan_transition(data.get("state"), data.get("intent"), root)
    if mode == "aggregate":
        return aggregate_visible_states(data.get("aggregate_input"), root)
    if mode == "record":
        return validate_transition_record(data.get("record"), root)
    return _invalid("state", "agent_runtime_state.invalid_json", "/input/mode")

def execute_fixture_suite(contract_root: Path | str) -> list[dict]:
    loaded = _loaded(contract_root); suite = loaded["documents"]["fixtures/cases.json"]
    return [{"case_id": case["case_id"], "actual": _case_result(case, loaded["root"]), "expected": copy.deepcopy(case["expected"])} for case in suite["cases"]]