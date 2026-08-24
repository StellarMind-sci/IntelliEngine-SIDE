from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "agent-profile" / "1.0.0"
VERIFIER = PACKAGE_ROOT / "contracts" / "tools" / "verify_contract.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("agent_profile_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier at {VERIFIER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentProfileContractTests(unittest.TestCase):
    def test_contract_declares_all_agent_profile_schemas_and_diagnostics(self) -> None:
        verifier = load_verifier()

        report = verifier.verify_contract(CONTRACT_ROOT)

        self.assertEqual(report["contract_version"], "1.0.0")
