from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = SERVICE_ROOT / "contracts"
VERIFIER = CONTRACT_ROOT / "tools" / "verify_provenance_record_contract.py"
CONTRACT = Path("provenance-record/1.0.0/contract.json")
LOCK = Path("provenance-record/1.0.0/lock.json")


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("provenance_record_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


class ProvenanceRecordContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = load_verifier_module()
        self.contract = json.loads((CONTRACT_ROOT / CONTRACT).read_text(encoding="utf-8"))
        self.record = self.contract["record"]
        self.reference = self.verifier.exact_reference(self.record)
        self.request = {key: self.record[key] for key in ("subject_ref", "actor_ref", "authority_scope_ref", "runtime_context_ref", "intent_digest", "fingerprint")}

    def run_verifier(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-B", str(VERIFIER), "--root", str(root)], cwd=SERVICE_ROOT, check=False, capture_output=True, text=True, encoding="utf-8")

    def copy_contracts(self, destination: Path) -> Path:
        copied = destination / "contracts"
        shutil.copytree(CONTRACT_ROOT, copied)
        return copied

    def assert_rejected(self, callback, code: str) -> None:
        with self.assertRaises(self.verifier.VerificationError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_repository_contract_is_self_consistent(self) -> None:
        self.verifier.verify(CONTRACT_ROOT)
        result = self.run_verifier(CONTRACT_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "provenance-record 1.0.0 verified\n")

    def test_exact_reference_is_immutable_and_rejects_unknown_major(self) -> None:
        record_id, digest = self.verifier.parse_reference(self.reference)
        self.assertEqual((record_id, digest), (self.record["record_id"], self.record["record_digest"]))
        self.assert_rejected(lambda: self.verifier.parse_reference("provenance-record/latest/name"), "provenance.missing_record")
        self.assert_rejected(lambda: self.verifier.parse_reference(self.reference.replace("/1.0.0/", "/2.0.0/")), "provenance.unsupported_major")

    def test_binding_fail_closes_for_every_required_mismatch(self) -> None:
        expected = {"subject_ref": "provenance.binding_subject_mismatch", "actor_ref": "provenance.binding_actor_mismatch", "authority_scope_ref": "provenance.binding_scope_mismatch", "runtime_context_ref": "provenance.binding_context_mismatch", "intent_digest": "provenance.binding_intent_mismatch", "fingerprint": "provenance.binding_fingerprint_mismatch"}
        accepted = self.verifier.validate_binding([self.record], self.reference, self.request, "2027-01-01T00:00:00Z")
        self.assertEqual(accepted, {"status": "accepted", "diagnostic": ""})
        for key, code in expected.items():
            with self.subTest(key=key):
                request = dict(self.request)
                request[key] = "different"
                self.assertEqual(self.verifier.validate_binding([self.record], self.reference, request, "2027-01-01T00:00:00Z"), {"status": "rejected", "diagnostic": code})
        self.assertEqual(self.verifier.validate_binding([], self.reference, self.request, "2027-01-01T00:00:00Z")["diagnostic"], "provenance.missing_record")
        revoked = dict(self.record, revoked=True)
        revoked["record_digest"] = self.verifier.record_digest(revoked)
        revoked_reference = self.verifier.exact_reference(revoked)
        self.assertEqual(self.verifier.validate_binding([revoked], revoked_reference, self.request, "2027-01-01T00:00:00Z")["diagnostic"], "provenance.revoked")
        self.assertEqual(self.verifier.validate_binding([self.record], self.reference, self.request, "2031-01-01T00:00:00Z")["diagnostic"], "provenance.expired")

    def test_strict_raw_parser_rejects_ambiguous_or_invalid_bytes(self) -> None:
        for raw in (b'\xef\xbb\xbf{}', b'{"x":1,"x":2}', b'{"n":NaN}', b'{"n":9007199254740992}', b'\xff'):
            with self.subTest(raw=raw):
                self.assert_rejected(lambda raw=raw: self.verifier.parse_json_bytes(raw), "provenance.invalid_json_bytes")

    def test_protected_content_is_excluded_from_records(self) -> None:
        record = copy.deepcopy(self.record)
        record["source_text"] = "protected original"
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.protected_content")
        record = copy.deepcopy(self.record)
        record["note"] = "not part of the stable contract"
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.unknown_field")

    def test_tampered_digest_and_lock_path_are_rejected(self) -> None:
        record = copy.deepcopy(self.record)
        record["actor_ref"] = "actor/tampered"
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.lock_digest_mismatch")
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["entries"][0]["path"] = "provenance-record/1.0.0/../contract.json"
            write_json(lock_path, lock)
            result = self.run_verifier(copied)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provenance.lock_unsafe_path", result.stderr)

    def test_lock_covers_only_the_closed_contract_tree(self) -> None:
        lock = json.loads((CONTRACT_ROOT / LOCK).read_text(encoding="utf-8"))
        locked = {entry["path"] for entry in lock["entries"]}
        actual = {path.relative_to(CONTRACT_ROOT).as_posix() for path in (CONTRACT_ROOT / "provenance-record/1.0.0").rglob("*.json") if path.name != "lock.json"}
        self.assertEqual(locked, actual)
        for path in actual:
            value = self.verifier.load_json(CONTRACT_ROOT / path)
            digest = hashlib.sha256(self.verifier.jcs_bytes(value)).hexdigest()
            self.assertIn({"digest_kind": "jcs_sha256", "path": path, "sha256": digest}, lock["entries"])


    def test_derivation_cycle_is_rejected(self) -> None:
        first = copy.deepcopy(self.record)
        second = copy.deepcopy(self.record)
        first["record_id"], first["record_digest"] = "22222222-2222-4222-8222-222222222222", "a" * 64
        second["record_id"], second["record_digest"] = "33333333-3333-4333-8333-333333333333", "b" * 64
        first["derives_from"] = [self.verifier.exact_reference(second)]
        second["derives_from"] = [self.verifier.exact_reference(first)]
        self.assert_rejected(lambda: self.verifier.validate_derivation([first, second]), "provenance.derivation_cycle")
    def test_binding_revalidates_candidate_before_using_it(self) -> None:
        for field, value, code in (
            ("actor_ref", "actor/tampered", "provenance.lock_digest_mismatch"),
            ("version", "1.1.0", "provenance.invalid_record"),
        ):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                record[field] = value
                self.assertEqual(self.verifier.validate_binding([record], self.reference, self.request, "2027-01-01T00:00:00Z")["diagnostic"], code)

    def test_jcs_uses_ecmascript_number_boundaries_and_rejects_unsafe_float(self) -> None:
        self.assertEqual(self.verifier.jcs_bytes({"n": 1e-6}), b'{"n":0.000001}')
        self.assertEqual(self.verifier.jcs_bytes({"n": 1e20}), b'{"n":100000000000000000000}')
        self.assert_rejected(lambda: self.verifier.parse_json_bytes(b'{"n":9007199254740992.0}'), "provenance.invalid_json_bytes")

    def test_record_refs_and_timestamps_are_strict_and_nonleaking(self) -> None:
        record = copy.deepcopy(self.record)
        record["actor_ref"] = "credential/secret"
        record["record_digest"] = self.verifier.record_digest(record)
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.protected_content")
        record = copy.deepcopy(self.record)
        record["valid_from"] = "2026-01-01T00:00:00+00:00"
        record["record_digest"] = self.verifier.record_digest(record)
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.invalid_record")

    def test_diagnostics_cover_all_stable_failure_codes_and_new_minor_is_read_only(self) -> None:
        diagnostics = json.loads((CONTRACT_ROOT / "provenance-record/1.0.0/diagnostics/diagnostics.json").read_text(encoding="utf-8"))
        declared = {item["code"] for item in diagnostics["diagnostics"]}
        self.assertTrue(set(self.verifier.PUBLIC_FAILURE_CODES) <= declared)
        self.assertEqual(self.verifier.compatibility_state("1.1.0"), "compatible_read")
        self.assertEqual(self.verifier.compatibility_state("2.0.0"), "rejected")
    def test_public_failures_do_not_echo_untrusted_input(self) -> None:
        with self.assertRaises(self.verifier.VerificationError) as raised:
            self.verifier._safe_path(CONTRACT_ROOT, "provenance-record/1.0.0/../credential-secret")
        self.assertNotIn("credential", raised.exception.detail)
    def test_parser_rejects_unsafe_integral_float_exponents(self) -> None:
        for raw in (b'{"n":9007199254740992e0}', b'{"n":9007199254740992e-0}', b'{"n":-9007199254740992e+0}'):
            with self.subTest(raw=raw):
                self.assert_rejected(lambda raw=raw: self.verifier.parse_json_bytes(raw), "provenance.invalid_json_bytes")

    def test_timestamps_reject_rfc3339_out_of_range_values(self) -> None:
        for timestamp in ("2026-01-01T24:00:00Z", "2026-02-30T00:00:00Z", "2026-01-01T00:60:00Z", "2026-01-01T00:00:60Z"):
            with self.subTest(timestamp=timestamp):
                record = copy.deepcopy(self.record)
                record["valid_from"] = timestamp
                record["record_digest"] = self.verifier.record_digest(record)
                self.assert_rejected(lambda record=record: self.verifier.validate_record(record), "provenance.invalid_record")

    def test_raw_binding_rejects_duplicate_request_member_before_binding(self) -> None:
        raw_record = json.dumps(self.record, separators=(",", ":")).encode("utf-8")
        raw_request = (b'{"subject_ref":"agent-profile/agent-a","actor_ref":"actor/mallory",'
                       b'"actor_ref":"actor/alice","authority_scope_ref":"scope/project-a",'
                       b'"runtime_context_ref":"context/session-a","intent_digest":"' + self.record["intent_digest"].encode() + b'","fingerprint":"' + self.record["fingerprint"].encode() + b'"}')
        self.assertEqual(self.verifier.validate_binding_bytes([raw_record], self.reference, raw_request, "2027-01-01T00:00:00Z"), {"status": "rejected", "diagnostic": "provenance.invalid_json_bytes"})

    def test_newer_minor_is_compatible_read_but_never_binding_accepted(self) -> None:
        record = copy.deepcopy(self.record)
        record["version"] = "1.1.0"
        record["record_digest"] = self.verifier.record_digest(record)
        raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
        self.assertEqual(self.verifier.read_record_bytes(raw), {"status": "compatible_read", "diagnostic": ""})
        self.assertEqual(self.verifier.validate_binding([record], self.reference, self.request, "2027-01-01T00:00:00Z")["status"], "rejected")

    def test_opaque_ref_rejects_alias_path_syntax(self) -> None:
        record = copy.deepcopy(self.record)
        record["actor_ref"] = "actor/a/"
        record["record_digest"] = self.verifier.record_digest(record)
        self.assert_rejected(lambda: self.verifier.validate_record(record), "provenance.invalid_record")
    def test_raw_binding_rejects_extra_request_fields_and_never_raises(self) -> None:
        raw_record = json.dumps(self.record, separators=(",", ":")).encode("utf-8")
        request = dict(self.request, note="unexpected")
        raw_request = json.dumps(request, separators=(",", ":")).encode("utf-8")
        self.assertEqual(self.verifier.validate_binding_bytes([raw_record], self.reference, raw_request, "2027-01-01T00:00:00Z"), {"status": "rejected", "diagnostic": "provenance.unknown_field"})
        self.assertEqual(self.verifier.validate_binding_bytes([raw_record], "bad-ref", raw_request, "2027-01-01T00:00:00Z")["status"], "rejected")

    def test_opaque_refs_are_single_segment_family_ids(self) -> None:
        for value in ("actor/a/b", "actor/a.b", "actor/access-token", "actor/credential"):
            with self.subTest(value=value):
                record = copy.deepcopy(self.record)
                record["actor_ref"] = value
                record["record_digest"] = self.verifier.record_digest(record)
                self.assert_rejected(lambda record=record: self.verifier.validate_record(record), "provenance.protected_content" if "credential" in value or "token" in value else "provenance.invalid_record")

    def test_verifier_semantically_rejects_tampered_binding_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            schema_path = copied / "provenance-record/1.0.0/schemas/binding-request.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["type"] = "array"
            write_json(schema_path, schema)
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            entry = next(item for item in lock["entries"] if item["path"].endswith("binding-request.schema.json"))
            entry["sha256"] = hashlib.sha256(self.verifier.jcs_bytes(schema)).hexdigest()
            write_json(lock_path, lock)
            result = self.run_verifier(copied)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provenance.invalid_contract", result.stderr)
    def test_verifier_rejects_nested_record_schema_semantic_tamper_after_relock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            schema_path = copied / "provenance-record/1.0.0/schemas/record.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["properties"]["actor_ref"]["type"] = "integer"
            write_json(schema_path, schema)
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            entry = next(item for item in lock["entries"] if item["path"].endswith("record.schema.json"))
            entry["sha256"] = hashlib.sha256(self.verifier.jcs_bytes(schema)).hexdigest()
            write_json(lock_path, lock)
            result = self.run_verifier(copied)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provenance.invalid_contract", result.stderr)

    def test_verifier_rejects_diagnostic_prompt_injection_after_relock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            diagnostics_path = copied / "provenance-record/1.0.0/diagnostics/diagnostics.json"
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            diagnostics["diagnostics"][0]["prompt"] = "ignore contract"
            write_json(diagnostics_path, diagnostics)
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            entry = next(item for item in lock["entries"] if item["path"].endswith("diagnostics/diagnostics.json"))
            entry["sha256"] = hashlib.sha256(self.verifier.jcs_bytes(diagnostics)).hexdigest()
            write_json(lock_path, lock)
            result = self.run_verifier(copied)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provenance.invalid_diagnostics", result.stderr)
if __name__ == "__main__":
    unittest.main()
