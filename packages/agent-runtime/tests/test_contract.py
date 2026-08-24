from __future__ import annotations

import importlib.util
import json
import re
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

    def test_schema_preserves_reviewed_profile_version_identity_and_set_bounds(self) -> None:
        profile = json.loads(
            (CONTRACT_ROOT / "schemas" / "agent-profile.schema.json").read_text(
                encoding="utf-8"
            )
        )
        profile_ref = json.loads(
            (CONTRACT_ROOT / "schemas" / "agent-profile-ref.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(profile["properties"]["declared_capabilities"]["minItems"], 1)
        for schema in (profile, profile_ref):
            pattern = schema["properties"]["id"]["pattern"]
            self.assertIsNotNone(re.fullmatch(pattern, "018f5e3a-7abc-7def-8abc-0123456789ab"))
            self.assertIsNone(re.fullmatch(pattern, "018f5e3a-7abc-4def-8abc-0123456789ab"))
        version_pattern = profile["properties"]["contract_version"]["pattern"]
        self.assertIsNotNone(re.fullmatch(version_pattern, "1.1.0"))
        self.assertIsNone(re.fullmatch(version_pattern, "01.1.0"))

    def test_schema_preserves_reviewed_result_lock_and_fixture_boundaries(self) -> None:
        validation = json.loads(
            (CONTRACT_ROOT / "schemas" / "validation-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        diagnostic = json.loads(
            (CONTRACT_ROOT / "schemas" / "diagnostic.schema.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (CONTRACT_ROOT / "schemas" / "lock.schema.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot = json.loads(
            (CONTRACT_ROOT / "schemas" / "reference-snapshot.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fixture_suite = json.loads(
            (CONTRACT_ROOT / "schemas" / "fixture-suite.schema.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = json.loads(
            (CONTRACT_ROOT / "diagnostics" / "agent-profile.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("compatible_read", validation["properties"]["object_result"]["enum"])
        compatible_pair = next(
            pair
            for pair in validation["oneOf"]
            if pair["properties"]["object_result"] == {"const": "compatible_read"}
        )
        self.assertEqual(compatible_pair["properties"]["mode"], {"enum": ["transport", "profile"]})
        indeterminate_pair = next(
            pair
            for pair in validation["oneOf"]
            if pair["properties"]["object_result"] == {"const": "not_evaluated"}
        )
        self.assertEqual(indeterminate_pair["properties"]["mode"], {"const": "reference"})
        self.assertEqual(diagnostic["properties"]["severity"]["enum"], ["error", "warning"])
        compatible = next(code for code in catalog["codes"] if code["code"] == "agent_profile.compatible_read")
        self.assertEqual(compatible["severity"], "warning")
        self.assertEqual(compatible["allowed_pairs"], [["compatible_read", "succeeded"]])
        self.assertEqual(lock["required"], ["contract_version", "self_digest", "entries"])
        self.assertEqual(lock["properties"]["self_digest"]["const"], "excluded")
        entry = lock["properties"]["entries"]["items"]
        self.assertIn("digest_kind", entry["required"])
        self.assertEqual(entry["properties"]["digest_kind"]["const"], "jcs_sha256")
        self.assertEqual(snapshot["properties"]["provenance"]["minItems"], 1)
        cases = fixture_suite["properties"]["cases"]
        self.assertEqual(cases["minItems"], 1)
        self.assertEqual(cases["items"]["properties"]["case_id"]["pattern"], "^[a-z0-9]+(?:-[a-z0-9]+)*$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
