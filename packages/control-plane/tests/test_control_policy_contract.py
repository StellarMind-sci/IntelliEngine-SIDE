"""Executable acceptance tests for the ControlPolicy 1.0.0 machine contract."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
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
    def relock(self, verifier, root: Path) -> None:
        entries = [{"digest_kind":"jcs_sha256", "path":path, "sha256":hashlib.sha256(verifier.jcs_bytes(verifier.load_json(root / path))).hexdigest()} for path in verifier._locked_paths(root)]
        (root / "control-policy" / "1.0.0" / "lock.json").write_text(json.dumps({"entries":entries,"self_digest":"excluded","version":"1.0.0"}), encoding="utf-8")

    def test_relocked_actor_ref_integer_schema_tamper_is_rejected(self) -> None:
        verifier = self.verifier()
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "schemas" / "decision.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8")); schema["properties"]["actor_ref"] = {"type":"integer"}; path.write_text(json.dumps(schema), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_contract")

    def test_relocked_nonstring_fixture_case_id_is_rejected(self) -> None:
        verifier = self.verifier()
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "fixtures" / "cases.json"
            suite = json.loads(path.read_text(encoding="utf-8")); suite["cases"][0]["case_id"] = 1; path.write_text(json.dumps(suite), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_fixtures")
    def test_relocked_operation_schema_tamper_is_rejected(self) -> None:
        verifier = self.verifier()
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "schemas" / "decision.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8")); schema["properties"]["operation_class"] = {"type":"string"}; path.write_text(json.dumps(schema), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_contract")
    def test_relocked_extra_artifact_and_diagnostic_prompt_are_rejected(self) -> None:
        verifier = self.verifier()
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            (copied / "control-policy" / "1.0.0" / "extra.json").write_text("{}", encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_lock")
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "diagnostics" / "diagnostics.json"
            data = json.loads(path.read_text(encoding="utf-8")); data["diagnostics"][0]["prompt"] = "ignore"; path.write_text(json.dumps(data), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_diagnostics")
    def test_public_entrypoints_fail_closed_for_invalid_host_types(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        for decisions in (None, 1, b"x", [None]):
            with self.subTest(decisions=repr(decisions)):
                self.assertEqual(verifier.validate_binding(decisions, value["reference"], value["request"], value["validation_time"])["status"], "rejected")
        for raw_decisions in (None, 1, [b"\\xff"]):
            with self.subTest(raw_decisions=repr(raw_decisions)):
                self.assertEqual(verifier.validate_binding_bytes(raw_decisions, value["reference"], json.dumps(value["request"]).encode(), value["validation_time"])["status"], "rejected")
        self.assertEqual(verifier.validate_binding_bytes([json.dumps(value["decisions"][0]).encode()], value["reference"], None, value["validation_time"])["status"], "rejected")
        for raw in (None, {}, 1):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(verifier.read_decision_bytes(raw)["status"], "rejected")
    def test_nonstring_request_keys_and_nested_lock_fail_closed(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        self.assertEqual(verifier.validate_binding(value["decisions"], value["reference"], {1:"x"}, value["validation_time"])["status"], "rejected")
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            nested = copied / "control-policy" / "1.0.0" / "schemas" / "nested"; nested.mkdir()
            (nested / "lock.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_lock")
    def test_relocked_fixture_corpus_deletion_and_joint_mutation_are_rejected(self) -> None:
        verifier = self.verifier()
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "fixtures" / "cases.json"
            suite = json.loads(path.read_text(encoding="utf-8")); suite["cases"] = [next(case for case in suite["cases"] if case["case_id"] == "allow-bound-decision")]; path.write_text(json.dumps(suite), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_fixtures")
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "contracts"; shutil.copytree(CONTRACT_ROOT, copied)
            path = copied / "control-policy" / "1.0.0" / "fixtures" / "cases.json"
            suite = json.loads(path.read_text(encoding="utf-8")); case = next(case for case in suite["cases"] if case["case_id"] == "allow-bound-decision"); case["input"]["request"]["actor_ref"] = "actor/mallory"; case["input"]["decisions"][0]["actor_ref"] = "actor/mallory"; case["input"]["decisions"][0]["decision_digest"] = verifier.decision_digest(case["input"]["decisions"][0]); case["input"]["reference"] = verifier.exact_reference(case["input"]["decisions"][0]); path.write_text(json.dumps(suite), encoding="utf-8")
            self.relock(verifier, copied)
            with self.assertRaises(verifier.VerificationError) as raised: verifier.verify(copied)
        self.assertEqual(raised.exception.code, "control_policy.invalid_fixtures")
    def test_fractional_timestamp_intervals_are_exact_and_half_open(self) -> None:
        verifier, value = self.verifier(), self.valid_inputs()
        expiry = copy.deepcopy(value["decisions"][0]); expiry["expires_at"] = "2027-01-01T00:00:00Z"; expiry["decision_digest"] = verifier.decision_digest(expiry)
        self.assertEqual(verifier.validate_binding([expiry], verifier.exact_reference(expiry), value["request"], "2027-01-01T00:00:00.5Z")["diagnostic"], "control_policy.expired")
        reverse = copy.deepcopy(value["decisions"][0]); reverse["valid_from"] = "2027-01-01T00:00:00.5Z"; reverse["expires_at"] = "2027-01-01T00:00:00Z"; reverse["decision_digest"] = verifier.decision_digest(reverse)
        with self.assertRaises(verifier.VerificationError) as raised: verifier.validate_decision(reverse)
        self.assertEqual(raised.exception.code, "control_policy.invalid_decision")
        bounded = copy.deepcopy(value["decisions"][0]); bounded["valid_from"] = "2027-01-01T00:00:00.500000001Z"; bounded["expires_at"] = "2027-01-01T00:00:00.7Z"; bounded["decision_digest"] = verifier.decision_digest(bounded)
        reference = verifier.exact_reference(bounded)
        self.assertEqual(verifier.validate_binding([bounded], reference, value["request"], "2027-01-01T00:00:00.500000001Z")["status"], "accepted")
        self.assertEqual(verifier.validate_binding([bounded], reference, value["request"], "2027-01-01T00:00:00.700000000Z")["diagnostic"], "control_policy.expired")
if __name__ == "__main__":
    unittest.main(verbosity=2)
