"""Executable acceptance tests for the ControlPolicy 1.0.0 machine contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "control-plane" / "contracts"
VERIFIER = CONTRACT_ROOT / "tools" / "verify_control_policy_contract.py"


class ControlPolicyContractTests(unittest.TestCase):
    def test_closed_offline_profile_verifies_a_valid_decision_binding(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(VERIFIER), "--root", str(CONTRACT_ROOT)],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "control-policy 1.0.0 verified\n")


    def verifier(self):
        spec = importlib.util.spec_from_file_location("control_policy_verifier", VERIFIER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def valid_inputs(self):
        suite = json.loads((CONTRACT_ROOT / "control-policy" / "1.0.0" / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        return suite["cases"][0]["input"]

    def test_binding_fail_closes_for_every_authority_relevant_mismatch(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        self.assertEqual(verifier.validate_binding(**value), {"status": "accepted", "diagnostic": ""})
        expected = {"actor_ref":"control_policy.binding_actor_mismatch", "authority_scope_ref":"control_policy.binding_scope_mismatch", "runtime_context_ref":"control_policy.binding_context_mismatch", "target_ref":"control_policy.binding_target_mismatch", "operation_class":"control_policy.binding_operation_mismatch", "command_fingerprint":"control_policy.binding_fingerprint_mismatch", "pure_plan_digest":"control_policy.binding_plan_mismatch", "provenance_record_ref":"control_policy.binding_provenance_mismatch"}
        for key, code in expected.items():
            request = dict(value["request"]); request[key] = "different"
            self.assertEqual(verifier.validate_binding(value["decisions"], value["reference"], request, value["validation_time"]), {"status": "rejected", "diagnostic": code})

    def test_deny_expiry_revocation_indeterminate_and_safety_caps_fail_closed(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        for field, changed, code in (("outcome", "deny", "control_policy.denied"), ("outcome", "indeterminate", "control_policy.indeterminate"), ("revoked", True, "control_policy.revoked")):
            decision = copy.deepcopy(value["decisions"][0]); decision[field] = changed; decision["decision_digest"] = verifier.decision_digest(decision)
            self.assertEqual(verifier.validate_binding([decision], verifier.exact_reference(decision), value["request"], value["validation_time"]), {"status":"rejected","diagnostic":code})
        self.assertEqual(verifier.validate_binding(value["decisions"], value["reference"], value["request"], "2031-01-01T00:00:00Z")["diagnostic"], "control_policy.expired")
        weak = copy.deepcopy(value["decisions"][0]); weak["constraints"]["platform_safety_caps"] = []
        with self.assertRaises(verifier.VerificationError) as raised: verifier.validate_decision(weak)
        self.assertEqual(raised.exception.code, "control_policy.safety_cap_mismatch")

    def test_transport_compatibility_and_sensitive_fields_are_closed(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        self.assertEqual(verifier.validate_binding_bytes([], value["reference"], b'{"actor_ref":"a","actor_ref":"b"}', value["validation_time"])["diagnostic"], "control_policy.invalid_json_bytes")
        newer = copy.deepcopy(value["decisions"][0]); newer["version"] = "1.1.0"
        self.assertEqual(verifier.read_decision_bytes(json.dumps(newer).encode()), {"status":"compatible_read","diagnostic":""})
        self.assertEqual(verifier.read_decision_bytes(json.dumps(dict(newer, version="2.0.0")).encode())["diagnostic"], "control_policy.unsupported_major")
        protected = copy.deepcopy(value["decisions"][0]); protected["prompt"] = "private"
        with self.assertRaises(verifier.VerificationError) as raised: verifier.validate_decision(protected)
        self.assertEqual(raised.exception.code, "control_policy.protected_content")
    def test_binding_never_accepts_newer_minor_decision_or_provenance_references(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        self.assertEqual(verifier.validate_binding(value["decisions"], value["reference"].replace("/1.0.0/", "/1.1.0/"), value["request"], value["validation_time"])["status"], "rejected")
        decision = copy.deepcopy(value["decisions"][0])
        decision["provenance_record_ref"] = decision["provenance_record_ref"].replace("/1.0.0/", "/1.1.0/")
        decision["decision_digest"] = verifier.decision_digest(decision)
        self.assertEqual(verifier.validate_binding([decision], verifier.exact_reference(decision), value["request"], value["validation_time"])["status"], "rejected")
if __name__ == "__main__":
    unittest.main(verbosity=2)
