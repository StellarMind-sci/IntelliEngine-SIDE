from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .runtime import validate_unit


JsonObject = dict[str, Any]
SAFE_INTEGER = 9007199254740991
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _issue(code: str, path: str) -> JsonObject:
    return {"code": code, "path": path, "severity": "error"}


def _result(valid: bool, issues: list[JsonObject], units: list[JsonObject] | None = None,
            node_dependents: list[JsonObject] | None = None,
            unit_dependents: list[JsonObject] | None = None) -> JsonObject:
    return {
        "object_result": "valid" if valid else "invalid",
        "operation_outcome": "succeeded",
        "issues": issues,
        "units": [] if units is None else units,
        "node_dependents": [] if node_dependents is None else node_dependents,
        "unit_dependents": [] if unit_dependents is None else unit_dependents,
    }


def _ref_key(value: Any) -> tuple[bytes, int] | None:
    if not isinstance(value, dict) or set(value) != {"id", "revision"}:
        return None
    identifier = value.get("id")
    revision = value.get("revision")
    if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
        return None
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= SAFE_INTEGER:
        return None
    return identifier.encode("utf-8"), revision


def _ref_from_key(key: tuple[bytes, int]) -> JsonObject:
    return {"id": key[0].decode("utf-8"), "revision": key[1]}


def _canonical_ref_set(values: Any) -> list[tuple[bytes, int]] | None:
    if not isinstance(values, list):
        return None
    keys = [_ref_key(value) for value in values]
    if any(key is None for key in keys):
        return None
    concrete = [key for key in keys if key is not None]
    return concrete if len(concrete) == len(set(concrete)) and concrete == sorted(concrete) else None


def _collect_node_refs(unit: JsonObject) -> set[tuple[bytes, int]]:
    values: list[Any] = []
    boundary = unit["concept_boundary"]
    values.extend(boundary["focus_node_refs"])
    for objective in unit["learning_objectives"]:
        values.extend(objective["target_node_refs"])
    for binding in unit["node_bindings"]:
        values.append(binding["node_ref"])
    for behavior in unit["behaviors"]:
        values.extend(behavior["input_node_refs"])
        values.extend(behavior["output_node_refs"])
    for validation in unit["validations"]:
        values.extend(validation["subject_node_refs"])
        values.extend(validation["evidence_node_refs"])
    for criterion in unit["mastery_criteria"]:
        values.extend(criterion["evidence_node_refs"])
    return {key for value in values if (key := _ref_key(value)) is not None}


def _required_evidence_refs(unit: JsonObject) -> set[tuple[bytes, int]]:
    values: list[Any] = []
    for validation in unit["validations"]:
        values.extend(validation["evidence_node_refs"])
    for criterion in unit["mastery_criteria"]:
        values.extend(criterion["evidence_node_refs"])
    return {key for value in values if (key := _ref_key(value)) is not None}


def _has_cycle(edges: dict[tuple[bytes, int], set[tuple[bytes, int]]]) -> bool:
    visiting: set[tuple[bytes, int]] = set()
    visited: set[tuple[bytes, int]] = set()

    def visit(node: tuple[bytes, int]) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in edges[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in sorted(edges))


def _closure(start: tuple[bytes, int], edges: dict[tuple[bytes, int], set[tuple[bytes, int]]]) -> list[tuple[bytes, int]]:
    seen: set[tuple[bytes, int]] = set()
    pending = list(edges[start])
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(edges[current] - seen)
    return sorted(seen)


def project_knowledge(units: Any, available_node_refs: Any, evidence_node_refs: Any,
                      contract_root: Path) -> JsonObject:
    available = _canonical_ref_set(available_node_refs)
    if available is None:
        return _result(False, [_issue("knowledge_project.noncanonical_set", "/available_node_refs")])
    evidence = _canonical_ref_set(evidence_node_refs)
    if evidence is None:
        return _result(False, [_issue("knowledge_project.noncanonical_set", "/evidence_node_refs")])
    if not isinstance(units, list):
        return _result(False, [_issue("knowledge_project.invalid_unit", "/units")])

    identities: list[tuple[bytes, int]] = []
    for index, unit in enumerate(units):
        if validate_unit(unit, available_node_refs, contract_root)["object_result"] != "valid":
            return _result(False, [_issue("knowledge_project.invalid_unit", f"/units/{index}")])
        key = _ref_key({"id": unit["id"], "revision": unit["revision"]})
        assert key is not None
        if key in identities:
            return _result(False, [_issue("knowledge_project.duplicate_unit_ref", f"/units/{index}")])
        identities.append(key)
    if identities != sorted(identities):
        return _result(False, [_issue("knowledge_project.noncanonical_set", "/units")])

    by_ref = dict(zip(identities, units))
    reverse = {key: set() for key in identities}
    prerequisite_edges = {key: set() for key in identities}
    missing = {key: [] for key in identities}
    for key, unit in by_ref.items():
        for reference in unit["prerequisite_unit_refs"]:
            prerequisite = _ref_key(reference)
            assert prerequisite is not None
            if prerequisite in by_ref:
                prerequisite_edges[key].add(prerequisite)
                reverse[prerequisite].add(key)
            else:
                missing[key].append(prerequisite)
        missing[key].sort()
    if _has_cycle(prerequisite_edges):
        return _result(False, [_issue("knowledge_project.prerequisite_cycle", "/units")])

    evidence_set = set(evidence)
    projection_units = []
    node_users: dict[tuple[bytes, int], set[tuple[bytes, int]]] = {}
    for key in identities:
        unit = by_ref[key]
        for node_ref in _collect_node_refs(unit):
            node_users.setdefault(node_ref, set()).add(key)
        status = "blocked" if missing[key] else (
            "needs_evidence" if not _required_evidence_refs(unit) <= evidence_set else "ready"
        )
        projection_units.append({
            "unit_ref": _ref_from_key(key),
            "status": status,
            "missing_prerequisite_unit_refs": [_ref_from_key(ref) for ref in missing[key]],
        })

    node_dependents = [
        {"node_ref": _ref_from_key(node_ref), "unit_refs": [_ref_from_key(ref) for ref in sorted(users)]}
        for node_ref, users in sorted(node_users.items())
    ]
    unit_dependents = [
        {
            "unit_ref": _ref_from_key(key),
            "dependent_unit_refs": [_ref_from_key(ref) for ref in _closure(key, reverse)],
        }
        for key in identities
    ]
    return _result(True, [], projection_units, node_dependents, unit_dependents)
