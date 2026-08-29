from __future__ import annotations

import re
from typing import Any


_REF_FIELDS = {"id", "revision"}
_UNIT_FIELDS = {"ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"}
_SAFE_INTEGER = 9007199254740991
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _issue(code: str, path: str) -> dict:
    return {"code": code, "path": path, "severity": "error"}


def _not_evaluated(code: str, path: str) -> dict:
    return {
        "object_result": "not_evaluated",
        "operation_outcome": "indeterminate",
        "issues": [_issue(code, path)],
        "impacted_steps": [],
    }


def _ref_key(value: Any) -> tuple[bytes, int] | None:
    if not isinstance(value, dict) or set(value) != _REF_FIELDS:
        return None
    identifier, revision = value.get("id"), value.get("revision")
    if not isinstance(identifier, str) or _UUID.fullmatch(identifier) is None or isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= _SAFE_INTEGER:
        return None
    return identifier.encode("utf-8"), revision


def _ref_from_key(key: tuple[bytes, int]) -> dict:
    return {"id": key[0].decode("utf-8"), "revision": key[1]}


def _ref_list(value: Any) -> list[tuple[bytes, int]] | None:
    if not isinstance(value, list):
        return None
    keys = [_ref_key(item) for item in value]
    if any(key is None for key in keys):
        return None
    return [key for key in keys if key is not None]


def _projection_reasons(projection: Any) -> dict[tuple[bytes, int], dict] | None:
    if not isinstance(projection, dict) or projection.get("object_result") != "valid" or not isinstance(projection.get("units"), list):
        return None
    reasons: dict[tuple[bytes, int], dict] = {}
    for unit in projection["units"]:
        if not isinstance(unit, dict) or set(unit) != _UNIT_FIELDS:
            return None
        key = _ref_key(unit.get("ref"))
        prerequisites = _ref_list(unit.get("missing_prerequisite_refs"))
        evidence = _ref_list(unit.get("missing_evidence_node_refs"))
        if key is None or prerequisites is None or evidence is None or unit.get("status") not in {"blocked", "needs_evidence", "ready"} or key in reasons:
            return None
        reasons[key] = {
            "knowledge_unit_ref": _ref_from_key(key),
            "status": unit["status"],
            "missing_prerequisite_refs": [_ref_from_key(ref) for ref in prerequisites],
            "missing_evidence_node_refs": [_ref_from_key(ref) for ref in evidence],
        }
    return reasons


def project_knowledge_impacts(flow: Any, projection: Any) -> dict:
    reasons_by_ref = _projection_reasons(projection)
    if reasons_by_ref is None:
        return _not_evaluated("thoughtflow.knowledge_impact.invalid_projection", "/projection")
    if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list):
        return _not_evaluated("thoughtflow.knowledge_impact.invalid_flow", "/flow/steps")

    impacts: dict[str, dict[tuple[bytes, int], dict]] = {}
    for index, step in enumerate(flow["steps"]):
        path = f"/flow/steps/{index}"
        if not isinstance(step, dict) or not isinstance(step.get("step_id"), str) or not isinstance(step.get("kind"), str):
            return _not_evaluated("thoughtflow.knowledge_impact.invalid_flow", path)
        refs = _ref_list(step.get("knowledge_unit_refs"))
        if refs is None:
            return _not_evaluated("thoughtflow.knowledge_impact.invalid_flow", f"{path}/knowledge_unit_refs")
        if step["kind"] == "operation":
            behavior = step.get("behavior_ref")
            behavior_ref = _ref_key(behavior.get("knowledge_unit_ref")) if isinstance(behavior, dict) else None
            if behavior_ref is None:
                return _not_evaluated("thoughtflow.knowledge_impact.invalid_flow", f"{path}/behavior_ref/knowledge_unit_ref")
            refs.append(behavior_ref)
        expected_status = "blocked" if step["kind"] in {"analysis", "operation"} else "needs_evidence" if step["kind"] == "verification" else None
        if expected_status is None:
            continue
        for ref in set(refs):
            reason = reasons_by_ref.get(ref)
            if reason is not None and reason["status"] == expected_status:
                impacts.setdefault(step["step_id"], {})[ref] = reason

    impacted_steps = [
        {"step_id": step_id, "reasons": [by_ref[ref] for ref in sorted(by_ref)]}
        for step_id, by_ref in sorted(impacts.items(), key=lambda item: item[0].encode("utf-8"))
    ]
    return {
        "object_result": "valid",
        "operation_outcome": "succeeded",
        "issues": [],
        "impacted_steps": impacted_steps,
    }