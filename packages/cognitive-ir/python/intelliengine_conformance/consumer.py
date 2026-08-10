from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable

from .json_codec import JsonInputError, canonicalize, parse_json_bytes
from .regex_profile import RegexProfileError, parse_pattern
from .schema_validation import SchemaValidationError, is_valid, require_valid


class ConsumerError(RuntimeError):
    """The profile or fixture set is corrupt, or cannot be safely consumed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _issue(code: str, path: str) -> dict[str, str]:
    return {"code": code, "path": path, "severity": "error"}


def _json_cost(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + sum(1 + _json_cost(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(1 + _json_cost(item) for item in value)
    return 1


_SCHEMA_MAPS = frozenset(("$defs", "dependentSchemas", "patternProperties", "properties"))
_SCHEMA_ARRAYS = frozenset(("allOf", "anyOf", "oneOf", "prefixItems"))
_SCHEMA_SINGLES = frozenset(
    ("additionalProperties", "contains", "contentSchema", "else", "if", "items", "not", "propertyNames", "then", "unevaluatedItems", "unevaluatedProperties")
)


def _schema_locations(schema: Any) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return
        locations.append(value)
        for keyword, child in value.items():
            if keyword in _SCHEMA_MAPS and isinstance(child, dict):
                for name in sorted(child, key=lambda item: item.encode("utf-8")):
                    visit(child[name])
            elif keyword in _SCHEMA_ARRAYS and isinstance(child, list):
                for item in child:
                    visit(item)
            elif keyword in _SCHEMA_SINGLES:
                visit(child)

    visit(schema)
    return locations


def _all_refs(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("$ref"), str):
            references.append(value["$ref"])
        for child in value.values():
            references.extend(_all_refs(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_all_refs(child))
    return references


def _pointer_target(document: Any, pointer: str) -> tuple[Any, str | int]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ConsumerError("mutation pointer must be a non-root JSON Pointer")
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]
    container = document
    for token in tokens[:-1]:
        if isinstance(container, list):
            if not token.isdigit() or int(token) >= len(container):
                raise ConsumerError("mutation pointer does not exist")
            container = container[int(token)]
        elif isinstance(container, dict) and token in container:
            container = container[token]
        else:
            raise ConsumerError("mutation pointer does not exist")
    final: str | int = int(tokens[-1]) if isinstance(container, list) and tokens[-1].isdigit() else tokens[-1]
    return container, final


def _has_productive_local_recursion(schema: dict[str, Any]) -> tuple[bool, bool]:
    local_references = [reference for reference in _all_refs(schema) if reference.startswith("#/")]
    if len(local_references) < 2:
        return False, True

    productive = False

    def inspect(value: Any, descended: bool = False) -> None:
        nonlocal productive
        if isinstance(value, dict):
            if descended and isinstance(value.get("$ref"), str) and value["$ref"].startswith("#/"):
                productive = True
            for keyword, child in value.items():
                inspect(child, descended or keyword in ("items", "properties", "prefixItems"))
        elif isinstance(value, list):
            for item in value:
                inspect(item, descended)

    inspect(schema)
    return True, productive


def _iteration_count(step: dict[str, Any], value: Any, pattern_nodes: int | None) -> int:
    iteration = step["iteration"]
    if iteration == "once":
        return 1
    if iteration in ("map-values", "map-keys", "declared-map-members"):
        return len(value) if isinstance(value, dict) else 0
    if iteration in ("schema-array-elements", "applicator-branches", "all-array-items"):
        return len(value) if isinstance(value, list) else 0
    if iteration == "pattern-scalars":
        return len(value) if isinstance(value, str) else 0
    if iteration == "ast-nodes":
        return pattern_nodes or 0
    return 1


def _admission_work_units(schema: dict[str, Any], profile: dict[str, Any]) -> int:
    encoded = canonicalize(schema)
    locations = _schema_locations(schema)
    total = _json_cost(schema) + 1 + math.ceil(len(encoded) / 256)
    total += 1 + len(_all_refs(schema)) + len(locations)
    rules = profile["work_units"]["keyword_rules"]
    maximum_repeat = profile["regex_profile"]["maximum_repeat"]
    for location in locations:
        for keyword in sorted(location, key=lambda name: profile["schema_profile"]["keyword_ordinals"].get(name, 850)):
            normalized = "x-*" if keyword.startswith("x-") else keyword
            if normalized not in rules:
                continue
            value = location[keyword]
            pattern_nodes = parse_pattern(value, maximum_repeat) if keyword == "pattern" and isinstance(value, str) else None
            for step in rules[normalized]["admission_steps"]:
                count = _iteration_count(step, value, pattern_nodes)
                if step["formula"] == "json-value-cost":
                    total += _json_cost(value) * count
                elif step["formula"] == "regex_grammar_parse":
                    total += (1 + len(value))
                elif step["formula"] in ("regex_ast", "regex_compact_counter"):
                    total += 1 + (pattern_nodes or 0)
                elif step["action"] is not None:
                    total += count
    return total


def _semantic_work_units(schema: dict[str, Any], instance: Any, profile: dict[str, Any]) -> int:
    rules = profile["work_units"]["keyword_rules"]
    total = 1

    def evaluate(location: Any, current: Any) -> bool:
        nonlocal total
        if isinstance(location, bool):
            return location
        if not isinstance(location, dict):
            return False
        valid = True
        for keyword in sorted(location, key=lambda name: profile["schema_profile"]["keyword_ordinals"].get(name, 850)):
            normalized = "x-*" if keyword.startswith("x-") else keyword
            if normalized not in rules:
                continue
            value = location[keyword]
            for step in rules[normalized]["semantic_steps"]:
                iteration = step["iteration"]
                if iteration == "applicator-branches" and isinstance(value, list):
                    total += len(value)
                elif iteration == "actual-object-members" and isinstance(current, dict):
                    total += len(current)
                else:
                    total += 1
            if keyword == "anyOf" and isinstance(value, list):
                branch_results = [evaluate(child, current) for child in value]
                valid = valid and any(branch_results)
            elif keyword == "type":
                expected = value if isinstance(value, list) else [value]
                actual = (
                    "object" if isinstance(current, dict) else "array" if isinstance(current, list) else "string" if isinstance(current, str) else "boolean" if isinstance(current, bool) else "null" if current is None else "number"
                )
                valid = valid and actual in expected
        return valid

    evaluate(schema, instance)
    return total


def _confined_path(profile_root: Path, path: Path) -> Path:
    root = profile_root.resolve()
    candidate = path.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ConsumerError(f"path resolves outside profile root: {path}") from error
    return candidate


def _resolve_profile_path(profile_root: Path, portable: str) -> Path:
    prefix = f"profile/{profile_root.name}/"
    if not isinstance(portable, str) or not portable.startswith(prefix):
        raise ConsumerError(f"path is outside the profile namespace: {portable!r}")
    relative = portable[len(prefix) :]
    if not relative or "\\" in relative:
        raise ConsumerError(f"invalid portable path: {portable!r}")
    return _confined_path(profile_root, profile_root / relative)


def _read_bytes(profile_root: Path, path: Path) -> bytes:
    confined = _confined_path(profile_root, path)
    try:
        return confined.read_bytes()
    except OSError as error:
        raise ConsumerError(f"cannot read profile artifact {path}: {error}") from error


def _read_json(profile_root: Path, path: Path) -> Any:
    try:
        return parse_json_bytes(_read_bytes(profile_root, path))
    except JsonInputError as error:
        raise ConsumerError(f"cannot read strict JSON {path}: {error}") from error


def _primary_projection(profile_root: Path, case: dict[str, Any]) -> tuple[bytes, Any | None, dict[str, Any]]:
    primary = _resolve_profile_path(profile_root, case["input"]["primary"])
    try:
        raw = _read_bytes(profile_root, primary)
    except ConsumerError as error:
        raise ConsumerError(f"primary input is missing: {primary}") from error
    projection: dict[str, Any] = {"raw_sha256": _sha256(raw)}
    parsed: Any | None = None
    try:
        parsed = parse_json_bytes(raw)
        if case["action"]["kind"] not in ("tamper", "append-lock-entry"):
            projection["jcs_sha256"] = _sha256(canonicalize(parsed))
    except JsonInputError:
        pass
    return raw, parsed, projection


def _base_result(profile: dict[str, Any], case: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "contract_id": profile["profile_id"] + ".profile",
        "contract_version": profile["profile_version"],
        "issues": [],
        **projection,
        "mode": "profile" if case["phase"] == "lock" else case["phase"],
        "object_result": "valid",
        "operation_outcome": "succeeded",
        "profile_version": profile["profile_version"],
        "work_units_consumed": 0,
    }


def run_case_document(profile_root: Path | str, case_document: dict[str, Any]) -> dict[str, Any]:
    root = Path(profile_root).resolve()
    profile = _read_json(root, root / "profile.json")
    case = copy.deepcopy(case_document)
    case.pop("expected", None)
    if not isinstance(case.get("case_id"), str) or not isinstance(case.get("action"), dict):
        raise ConsumerError("fixture case is structurally invalid")
    raw, primary, projection = _primary_projection(root, case)
    result = _base_result(profile, case, projection)
    action = case["action"]
    kind = action.get("kind")
    if kind in {"remove", "replace", "tamper", "append-lock-entry"}:
        action_target = _resolve_profile_path(root, action["path"])
        primary_target = _resolve_profile_path(root, case["input"]["primary"])
        if action_target != primary_target:
            raise ConsumerError("mutation action target must equal its primary input")

    if kind == "parse-negative":
        try:
            parse_json_bytes(raw)
        except JsonInputError as error:
            result.update(
                issues=[_issue("conformance.fixture_invalid", error.path)],
                object_result="not_evaluated",
                operation_outcome="indeterminate",
            )
        else:
            raise ConsumerError(f"negative parser fixture unexpectedly parsed: {case['case_id']}")
    elif kind == "transport":
        if primary is None:
            raise ConsumerError("transport fixture is not strict JSON")
    elif kind == "verify-profile":
        pass
    elif kind == "remove":
        target = _resolve_profile_path(root, action["path"])
        if not target.is_file() or target != (root / "profile.json").resolve():
            raise ConsumerError("remove action does not target the required profile")
        result.pop("jcs_sha256", None)
        result.update(
            issues=[_issue("profile.missing_file", "/profile")],
            object_result="not_evaluated",
            operation_outcome="indeterminate",
        )
    elif kind == "replace":
        mutated = copy.deepcopy(primary)
        target, key = _pointer_target(mutated, action["pointer"])
        if isinstance(target, dict) and isinstance(key, str) and key in target:
            target[key] = action["value"]
        elif isinstance(target, list) and isinstance(key, int) and key < len(target):
            target[key] = action["value"]
        else:
            raise ConsumerError("replace pointer does not exist")
        ordinals = list(mutated["schema_profile"]["keyword_ordinals"].values())
        if len(ordinals) != len(set(ordinals)):
            result.update(issues=[_issue("profile.duplicate_keyword_ordinal", "/schema_profile/keyword_ordinals")], object_result="invalid")
    elif kind == "tamper":
        target_path = _resolve_profile_path(root, action["path"])
        document = _read_json(root, target_path)
        mutated = copy.deepcopy(document)
        container, key = _pointer_target(mutated, action["pointer"])
        selected = container.get(key) if isinstance(container, dict) and isinstance(key, str) else container[key] if isinstance(container, list) and isinstance(key, int) and key < len(container) else None
        if action.get("operation") != "reverse-array" or not isinstance(selected, list):
            raise ConsumerError("tamper action is not a reversible array mutation")
        selected.reverse()
        portable = action["path"]
        lock = _read_json(root, root / "lock.json")
        entry = next((item for item in lock["entries"] if item["path"] == portable), None)
        current = _sha256(canonicalize(document))
        changed = _sha256(canonicalize(mutated))
        if entry is None or entry["digest_kind"] != "jcs_sha256" or entry["sha256"] != current or changed == current:
            raise ConsumerError("tamper fixture does not prove a locked digest mismatch")
        result.update(
            issues=[_issue("conformance.digest_mismatch", "/entries")],
            object_result="not_evaluated",
            operation_outcome="indeterminate",
        )
    elif kind == "append-lock-entry":
        lock_path = _resolve_profile_path(root, action["path"])
        mutated = copy.deepcopy(_read_json(root, lock_path))
        if not isinstance(mutated, dict) or not isinstance(mutated.get("entries"), list):
            raise ConsumerError("append-lock-entry action target is not a lock document")
        if action["entry"].get("path") != action["path"]:
            raise ConsumerError("the appended entry itself must create self inclusion")
        mutated["entries"].append(copy.deepcopy(action["entry"]))
        try:
            require_valid(mutated, _read_json(root, root / "schemas/lock.schema.json"), "mutated lock candidate")
        except SchemaValidationError as error:
            raise ConsumerError(str(error)) from error
        if not any(entry["path"] == action["path"] for entry in mutated["entries"]):
            raise ConsumerError("append-lock-entry action does not create self inclusion")
        result.update(issues=[_issue("lock.self_inclusion", "/entries")], object_result="invalid")
    elif kind == "verify-reference-graph":
        if not isinstance(primary, dict):
            raise ConsumerError("reference graph root is not JSON object")
        siblings = {}
        for path in _resolve_profile_path(root, case["input"]["primary"]).parent.glob("*.json"):
            if path.name == "case.json":
                continue
            value = _read_json(root, path)
            siblings[_sha256(canonicalize(value))] = value
        mismatch = False
        cycle = False
        visited: set[str] = set()
        active: set[str] = set()

        def traverse(resource: dict[str, Any], identity: str) -> None:
            nonlocal mismatch, cycle
            if identity in active:
                cycle = True
                return
            if identity in visited:
                return
            active.add(identity)
            for reference in _all_refs(resource):
                if not reference.startswith("urn:intelliengine:schema:sha256:"):
                    continue
                digest = reference.rsplit(":", 1)[-1]
                target = siblings.get(digest)
                if not isinstance(target, dict):
                    mismatch = True
                else:
                    traverse(target, digest)
            active.remove(identity)
            visited.add(identity)

        traverse(primary, _sha256(canonicalize(primary)))
        if mismatch:
            result.update(
                issues=[_issue("conformance.digest_mismatch", "/resources")],
                object_result="not_evaluated",
                operation_outcome="indeterminate",
            )
        elif cycle:
            result.update(issues=[_issue("conformance.fixture_invalid", "/resources")], object_result="invalid")
    elif kind == "schema-admission":
        if not isinstance(primary, dict):
            raise ConsumerError("admission schema is not an object")
        allowed = set(profile["schema_profile"]["allowed_keywords"])
        forbidden = set(profile["schema_profile"]["forbidden_keywords"])
        invalid_schema = False
        try:
            for location in _schema_locations(primary):
                for keyword in location:
                    normalized = "x-*" if keyword.startswith("x-") else keyword
                    if keyword in forbidden or normalized not in allowed:
                        invalid_schema = True
                if "pattern" in location:
                    parse_pattern(
                        location["pattern"],
                        profile["regex_profile"]["maximum_repeat"],
                        profile["portable_limits"]["regex_unicode_scalars"],
                    )
        except RegexProfileError:
            invalid_schema = True
        cyclic, productive = _has_productive_local_recursion(primary)
        if invalid_schema or (cyclic and not productive):
            result.update(issues=[_issue("conformance.fixture_invalid", "/resources")], object_result="invalid")
        if result["object_result"] == "valid" and "work_unit_trace" in case.get("assertions", {}):
            result["work_units_consumed"] = _admission_work_units(primary, profile)
    elif kind == "semantic-validation":
        schema = primary
        instance = _read_json(root, _resolve_profile_path(root, case["input"]["instance"]))
        if not isinstance(schema, dict):
            raise ConsumerError("semantic schema is not an object")
        if not is_valid(instance, schema):
            result["object_result"] = "invalid"
        result["work_units_consumed"] = _semantic_work_units(schema, instance, profile)
    elif kind == "work-unit-boundary":
        consumed = action["preconsumed"]
        if consumed + action["next_action_units"] > action["limit"]:
            code = "type_definition.resource_exhausted" if action["phase"] == "admission" else "cognitive_node.resource_exhausted"
            result.update(
                issues=[_issue(code, "")],
                object_result="not_evaluated",
                operation_outcome="resource_exhausted",
                work_units_consumed=consumed,
            )
        else:
            result["work_units_consumed"] = consumed + action["next_action_units"]
    else:
        raise ConsumerError(f"unsupported fixture action: {kind!r}")
    return result


class ConformanceConsumer:
    def __init__(self, profile_root: Path | str) -> None:
        self.profile_root = Path(profile_root).resolve()

    def _verify_lock(self) -> dict[str, Any]:
        profile = _read_json(self.profile_root, self.profile_root / "profile.json")
        lock = _read_json(self.profile_root, self.profile_root / "lock.json")
        lock_schema = _read_json(self.profile_root, self.profile_root / "schemas/lock.schema.json")
        try:
            require_valid(lock, lock_schema, "lock")
        except SchemaValidationError as error:
            raise ConsumerError(str(error)) from error
        seen: set[str] = set()
        for entry in lock["entries"]:
            portable = entry["path"]
            if portable in seen or portable == f"profile/{self.profile_root.name}/lock.json":
                raise ConsumerError("lock contains duplicate or self entry")
            seen.add(portable)
            path = _resolve_profile_path(self.profile_root, portable)
            try:
                raw = _read_bytes(self.profile_root, path)
            except ConsumerError as error:
                raise ConsumerError(f"locked artifact missing: {portable}") from error
            if entry["digest_kind"] == "raw_sha256":
                actual = _sha256(raw)
            elif entry["digest_kind"] == "jcs_sha256":
                try:
                    actual = _sha256(canonicalize(parse_json_bytes(raw)))
                except JsonInputError as error:
                    raise ConsumerError(f"locked JSON is invalid: {portable}") from error
            else:
                raise ConsumerError(f"unknown digest kind: {entry['digest_kind']!r}")
            if actual != entry["sha256"]:
                raise ConsumerError(f"lock digest mismatch: {portable}")
        actual_paths: set[str] = set()
        for path in self.profile_root.rglob("*"):
            confined = _confined_path(self.profile_root, path)
            if not confined.is_file():
                continue
            relative = path.relative_to(self.profile_root).as_posix()
            if relative == "lock.json":
                continue
            actual_paths.add(f"profile/{self.profile_root.name}/{relative}")
        if seen != actual_paths:
            raise ConsumerError("lock closure differs from profile artifact closure")
        return profile

    def _validate_machine_artifacts(self, profile: dict[str, Any], manifest: dict[str, Any], cases: Iterable[dict[str, Any]]) -> None:
        schemas = {
            path.stem.replace(".schema", ""): _read_json(self.profile_root, path)
            for path in (self.profile_root / "schemas").glob("*.schema.json")
        }
        schemas_by_digest = {_sha256(canonicalize(schema)): schema for schema in schemas.values()}
        diagnostics = _read_json(self.profile_root, self.profile_root / "diagnostics/conformance.json")

        def resolve_external(value: Any) -> Any:
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and reference.startswith("schemas/") and reference.endswith(".schema.json"):
                    name = Path(reference).stem.replace(".schema", "")
                    return copy.deepcopy(schemas[name])
                if isinstance(reference, str) and reference.startswith("urn:intelliengine:schema:sha256:"):
                    digest = reference.rsplit(":", 1)[-1]
                    if digest not in schemas_by_digest:
                        raise SchemaValidationError(f"unresolved schema digest URI: {reference}")
                    return copy.deepcopy(schemas_by_digest[digest])
                return {key: resolve_external(child) for key, child in value.items()}
            if isinstance(value, list):
                return [resolve_external(child) for child in value]
            return value

        try:
            require_valid(profile, schemas["profile"], "profile")
            require_valid(manifest, schemas["fixture-manifest"], "fixture manifest")
            require_valid(diagnostics, schemas["diagnostics"], "diagnostics catalog")
            for case in cases:
                require_valid(case, resolve_external(schemas["fixture-case"]), f"fixture {case.get('case_id')}")
                require_valid(case["expected"], schemas["expected-result"], f"fixture result {case.get('case_id')}")
        except (KeyError, SchemaValidationError) as error:
            raise ConsumerError(str(error)) from error

    def run_all(self) -> list[dict[str, Any]]:
        profile = self._verify_lock()
        manifest = _read_json(self.profile_root, self.profile_root / "fixtures/manifest.json")
        entries = manifest.get("cases")
        if not isinstance(entries, list):
            raise ConsumerError("fixture manifest cases must be an array")
        cases: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for entry in entries:
            path = self.profile_root / "fixtures" / entry["path"]
            resolved = path.resolve()
            try:
                resolved.relative_to((self.profile_root / "fixtures").resolve())
            except ValueError as error:
                raise ConsumerError("fixture manifest path escapes fixtures root") from error
            case = _read_json(self.profile_root, resolved)
            if case.get("case_id") != entry.get("case_id") or case["case_id"] in identifiers:
                raise ConsumerError("fixture manifest identity mismatch or duplicate")
            identifiers.add(case["case_id"])
            cases.append(case)
        self._validate_machine_artifacts(profile, manifest, cases)
        results = [run_case_document(self.profile_root, case) for case in cases]
        return sorted(results, key=lambda row: row["case_id"].encode("utf-8"))
