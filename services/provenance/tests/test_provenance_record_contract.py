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
        self.assertEqual(self.verifier.validate_binding([revoked], self.reference, self.request, "2027-01-01T00:00:00Z")["diagnostic"], "provenance.revoked")
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
if __name__ == "__main__":
    unittest.main()