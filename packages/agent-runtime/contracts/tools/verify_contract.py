from __future__ import annotations

import json
from pathlib import Path


REQUIRED_SCHEMA_PATHS = {
    "agent_profile": "schemas/agent-profile.schema.json",
    "agent_profile_ref": "schemas/agent-profile-ref.schema.json",
    "reference_snapshot": "schemas/reference-snapshot.schema.json",
    "diagnostic": "schemas/diagnostic.schema.json",
    "validation_result": "schemas/validation-result.schema.json",
    "fixture_suite": "schemas/fixture-suite.schema.json",
    "lock": "schemas/lock.schema.json",
}


def verify_contract(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "contract.json").read_text(encoding="utf-8"))
    if manifest.get("contract_family") != "agent-profile":
        raise ValueError("contract_family must be agent-profile")
    if manifest.get("contract_version") != "1.0.0":
        raise ValueError("contract_version must be 1.0.0")
    if manifest.get("side_effects") != "forbidden":
        raise ValueError("side_effects must be forbidden")
    if manifest.get("set_order") != "unsigned-utf8":
        raise ValueError("set_order must be unsigned-utf8")
    if manifest.get("schemas") != REQUIRED_SCHEMA_PATHS:
        raise ValueError("contract must declare every AgentProfile schema")
    diagnostics = manifest.get("diagnostics")
    if diagnostics != {"agent_profile": "diagnostics/agent-profile.json"}:
        raise ValueError("contract must declare the AgentProfile diagnostic catalog")
    for relative_path in [*REQUIRED_SCHEMA_PATHS.values(), *diagnostics.values()]:
        if not (root / relative_path).is_file():
            raise FileNotFoundError(f"declared contract artifact is missing: {relative_path}")
    fixture_path = root / manifest["fixtures"]
    if not fixture_path.is_file():
        raise NotImplementedError("fixture suite verification is not implemented")
    raise NotImplementedError("AgentProfile verifier behavior is not implemented")
