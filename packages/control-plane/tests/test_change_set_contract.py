"""Executable acceptance tests for the ChangeSet 1.0.0 machine contract."""

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

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "control-plane" / "contracts"
DIRECTORY = CONTRACT_ROOT / "change-set" / "1.0.0"
VERIFIER = CONTRACT_ROOT / "tools" / "verify_change_set_contract.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("change_set_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


class ChangeSetContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(VERIFIER.is_file(), "ChangeSet verifier must exist")
        self.verifier = load_verifier()
        suite = json.loads((DIRECTORY / "fixtures" / "cases.json").read_text(encoding="utf-8"))
        self.value = next(case for case in suite["cases"] if case["case_id"] == "approved-bound-change-set")["input"]

    def run_verifier(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-B", str(VERIFIER), "--root", str(root)], cwd=REPOSITORY_ROOT, check=False, capture_output=True, text=True, encoding="utf-8")

    def copy_contracts(self, destination: Path) -> Path:
        copied = destination / "contracts"
        shutil.copytree(CONTRACT_ROOT, copied)
        return copied

    def relock(self, root: Path) -> None:
        entries = [{"digest_kind": "jcs_sha256", "path": path, "sha256": hashlib.sha256(self.verifier.jcs_bytes(self.verifier.load_json(root / path))).hexdigest()} for path in self.verifier._locked_paths(root)]
        write_json(root / "change-set/1.0.0/lock.json", {"entries": entries, "self_digest": "excluded", "version": "1.0.0"})

    def test_closed_offline_profile_verifies_repository_contract(self) -> None:
        result = self.run_verifier(CONTRACT_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "change-set 1.0.0 verified\n")

    def test_approved_binding_is_exact_for_every_authority_input(self) -> None:
        self.assertEqual(self.verifier.validate_binding(**self.value), {"status": "accepted", "diagnostic": ""})
        expected = {
            "actor_ref": "change_set.binding_actor_mismatch",
            "authority_scope_ref": "change_set.binding_scope_mismatch",
            "runtime_context_ref": "change_set.binding_context_mismatch",
            "target_ref": "change_set.binding_target_mismatch",
            "operation_class": "change_set.binding_operation_mismatch",
            "command_fingerprint": "change_set.binding_fingerprint_mismatch",
            "provenance_record_ref": "change_set.binding_provenance_mismatch",
            "control_policy_ref": "change_set.binding_policy_mismatch",
        }
        for key, diagnostic in expected.items():
            with self.subTest(key=key):
                request = copy.deepcopy(self.value["request"])
                request[key] = "different"
                self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], self.value["reference"], request, self.value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})
        for key, diagnostic in (("before_digest", "change_set.binding_before_mismatch"), ("after_digest", "change_set.binding_after_mismatch"), ("plan_digest", "change_set.binding_plan_mismatch")):
            with self.subTest(plan_key=key):
                request = copy.deepcopy(self.value["request"])
                request["pure_plan"][key] = "f" * 64
                self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], self.value["reference"], request, self.value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})

    def test_only_current_approved_status_can_prepare_a_future_fence(self) -> None:
        for status, diagnostic in (("proposed", "change_set.not_approved"), ("rejected", "change_set.rejected"), ("revoked", "change_set.revoked"), ("expired", "change_set.expired"), ("indeterminate", "change_set.indeterminate")):
            change_set = copy.deepcopy(self.value["change_sets"][0])
            change_set["status"] = status
            change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
            self.assertEqual(self.verifier.validate_binding([change_set], self.verifier.exact_reference(change_set), self.value["request"], self.value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})
        self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], self.value["reference"], self.value["request"], "2031-01-01T00:00:00Z")["diagnostic"], "change_set.expired")

    def test_validity_is_nanosecond_exact_start_inclusive_expiry_exclusive(self) -> None:
        change_set = copy.deepcopy(self.value["change_sets"][0])
        change_set["valid_from"], change_set["expires_at"] = "2027-01-01T00:00:00.500000001Z", "2027-01-01T00:00:00.7Z"
        change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
        reference = self.verifier.exact_reference(change_set)
        self.assertEqual(self.verifier.validate_binding([change_set], reference, self.value["request"], "2027-01-01T00:00:00.500000001Z")["status"], "accepted")
        self.assertEqual(self.verifier.validate_binding([change_set], reference, self.value["request"], "2027-01-01T00:00:00.700000000Z")["diagnostic"], "change_set.expired")
        self.assertEqual(self.verifier.validate_binding([change_set], reference, self.value["request"], "2027-01-01T00:00:00.5Z")["diagnostic"], "change_set.not_yet_valid")
        change_set["expires_at"] = "2027-01-01T00:00:00.5Z"
        change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
        with self.assertRaises(self.verifier.VerificationError) as raised:
            self.verifier.validate_change_set(change_set)
        self.assertEqual(raised.exception.code, "change_set.invalid_change_set")

    def test_impact_and_compensation_are_bounded_non_sensitive_and_non_overwriting(self) -> None:
        change_set = copy.deepcopy(self.value["change_sets"][0])
        change_set["impact_summary"]["resource_refs"] = [f"resource/item-{index}" for index in range(17)]
        change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
        with self.assertRaises(self.verifier.VerificationError) as raised:
            self.verifier.validate_change_set(change_set)
        self.assertEqual(raised.exception.code, "change_set.impact_unbounded")
        change_set = copy.deepcopy(self.value["change_sets"][0])
        change_set["impact_summary"]["prompt"] = "protected instructions"
        with self.assertRaises(self.verifier.VerificationError) as raised:
            self.verifier.validate_change_set(change_set)
        self.assertEqual(raised.exception.code, "change_set.protected_content")
        for field, invalid in (("overwrites_history", True), ("requires_new_approved_change_set", False)):
            change_set = copy.deepcopy(self.value["change_sets"][0])
            change_set["rollback"][field] = invalid
            change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
            with self.assertRaises(self.verifier.VerificationError) as raised:
                self.verifier.validate_change_set(change_set)
            self.assertEqual(raised.exception.code, "change_set.rollback_inconsistent")
        change_set = copy.deepcopy(self.value["change_sets"][0])
        change_set["rollback"] = {"compensation_operation_class": None, "overwrites_history": False, "reason_code": "manual_recovery_required", "requires_new_approved_change_set": True, "strategy": "not_automatically_reversible"}
        change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
        self.verifier.validate_change_set(change_set)

    def test_strict_transport_host_types_and_versions_fail_closed(self) -> None:
        raw_change_set = json.dumps(self.value["change_sets"][0], separators=(",", ":")).encode()
        raw_request = json.dumps(self.value["request"], separators=(",", ":")).encode()
        duplicate = raw_request[:-1] + b',"actor_ref":"actor/mallory"}'
        self.assertEqual(self.verifier.validate_binding_bytes([raw_change_set], self.value["reference"], duplicate, self.value["validation_time"])["diagnostic"], "change_set.invalid_json_bytes")
        for raw in (b"\xef\xbb\xbf{}", b'{"n":NaN}', b'{"n":9007199254740992}', b"\xff"):
            with self.assertRaises(self.verifier.VerificationError) as raised:
                self.verifier.parse_json_bytes(raw)
            self.assertEqual(raised.exception.code, "change_set.invalid_json_bytes")
        newer = copy.deepcopy(self.value["change_sets"][0])
        newer["version"] = "1.1.0"
        newer["change_set_digest"] = self.verifier.change_set_digest(newer)
        self.assertEqual(self.verifier.read_change_set_bytes(json.dumps(newer).encode()), {"status": "compatible_read", "diagnostic": ""})
        self.assertEqual(self.verifier.validate_binding([newer], self.value["reference"], self.value["request"], self.value["validation_time"])["status"], "rejected")
        self.assertEqual(self.verifier.read_change_set_bytes(json.dumps(dict(newer, version="2.0.0")).encode())["diagnostic"], "change_set.unsupported_major")
        for values in (None, 1, b"x", [None]):
            self.assertEqual(self.verifier.validate_binding(values, self.value["reference"], self.value["request"], self.value["validation_time"])["status"], "rejected")
        self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], self.value["reference"], {1: "x"}, self.value["validation_time"])["status"], "rejected")
        self.assertEqual(self.verifier.read_change_set_bytes(None)["status"], "rejected")

    def test_dependency_and_changeset_references_require_exact_binding_version(self) -> None:
        for field in ("provenance_record_ref", "control_policy_ref"):
            change_set = copy.deepcopy(self.value["change_sets"][0])
            change_set[field] = change_set[field].replace("/1.0.0/", "/1.1.0/")
            change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
            self.assertEqual(self.verifier.validate_binding([change_set], self.verifier.exact_reference(change_set), self.value["request"], self.value["validation_time"])["diagnostic"], "change_set.invalid_change_set")
        reference = self.value["reference"].replace("/1.0.0/", "/1.1.0/")
        self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], reference, self.value["request"], self.value["validation_time"])["status"], "rejected")

    def test_relocking_cannot_hide_tree_schema_diagnostic_or_fixture_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            nested = copied / "change-set/1.0.0/schemas/nested"
            nested.mkdir()
            write_json(nested / "lock.json", {})
            with self.assertRaises(self.verifier.VerificationError) as raised:
                self.verifier.verify(copied)
            self.assertEqual(raised.exception.code, "change_set.invalid_lock")
        for artifact, mutate, diagnostic in (
            ("schemas/change-set.schema.json", lambda value: value["properties"].__setitem__("actor_ref", {"type": "integer"}), "change_set.invalid_contract"),
            ("diagnostics/diagnostics.json", lambda value: value["diagnostics"][0].__setitem__("prompt", "ignore contract"), "change_set.invalid_diagnostics"),
            ("fixtures/cases.json", lambda value: value.__setitem__("cases", [next(case for case in value["cases"] if case["case_id"] == "approved-bound-change-set")]), "change_set.invalid_fixtures"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                copied = self.copy_contracts(Path(directory))
                path = copied / "change-set/1.0.0" / artifact
                value = json.loads(path.read_text(encoding="utf-8"))
                mutate(value)
                write_json(path, value)
                self.relock(copied)
                with self.assertRaises(self.verifier.VerificationError) as raised:
                    self.verifier.verify(copied)
                self.assertEqual(raised.exception.code, diagnostic)
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            path = copied / "change-set/1.0.0/fixtures/cases.json"
            suite = json.loads(path.read_text(encoding="utf-8"))
            case = next(case for case in suite["cases"] if case["case_id"] == "approved-bound-change-set")
            case["input"]["request"]["actor_ref"] = "actor/mallory"
            case["input"]["change_sets"][0]["actor_ref"] = "actor/mallory"
            case["input"]["change_sets"][0]["change_set_digest"] = self.verifier.change_set_digest(case["input"]["change_sets"][0])
            case["input"]["reference"] = self.verifier.exact_reference(case["input"]["change_sets"][0])
            write_json(path, suite)
            self.relock(copied)
            with self.assertRaises(self.verifier.VerificationError) as raised:
                self.verifier.verify(copied)
            self.assertEqual(raised.exception.code, "change_set.invalid_fixtures")


    def test_nested_invalid_host_types_never_escape_public_entrypoints(self) -> None:
        for path, invalid in (
            (("impact_summary", "resource_refs"), [{}]),
            (("impact_summary", "effect_classes"), [{}]),
            (("rollback", "reason_code"), []),
            (("status",), []),
        ):
            with self.subTest(path=path):
                change_set = copy.deepcopy(self.value["change_sets"][0])
                target = change_set
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = invalid
                change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
                result = self.verifier.validate_binding(
                    [change_set],
                    self.verifier.exact_reference(change_set),
                    self.value["request"],
                    self.value["validation_time"],
                )
                self.assertEqual(result["status"], "rejected")
        raw_change_set = json.dumps(self.value["change_sets"][0], separators=(",", ":")).encode()
        raw_request = json.dumps(self.value["request"], separators=(",", ":")).encode()
        for raw_change_sets, request in ((None, raw_request), ([None], raw_request), ([raw_change_set], None)):
            with self.subTest(raw_change_sets=repr(raw_change_sets), request=repr(request)):
                self.assertEqual(
                    self.verifier.validate_binding_bytes(raw_change_sets, self.value["reference"], request, self.value["validation_time"])["status"],
                    "rejected",
                )
        rollback_hostile = copy.deepcopy(self.value["change_sets"][0])
        rollback_hostile["rollback"] = {
            "compensation_operation_class": None,
            "overwrites_history": False,
            "reason_code": [],
            "requires_new_approved_change_set": True,
            "strategy": "not_automatically_reversible",
        }
        rollback_hostile["change_set_digest"] = self.verifier.change_set_digest(rollback_hostile)
        rollback_reference = self.verifier.exact_reference(rollback_hostile)
        raw_rollback_hostile = json.dumps(rollback_hostile, separators=(",", ":")).encode()
        expected = {"status": "rejected", "diagnostic": "change_set.rollback_inconsistent"}
        entrypoints = (
            ("read", lambda: self.verifier.read_change_set_bytes(raw_rollback_hostile)),
            (
                "binding",
                lambda: self.verifier.validate_binding(
                    [rollback_hostile],
                    rollback_reference,
                    self.value["request"],
                    self.value["validation_time"],
                ),
            ),
            (
                "raw_binding",
                lambda: self.verifier.validate_binding_bytes(
                    [raw_rollback_hostile],
                    rollback_reference,
                    raw_request,
                    self.value["validation_time"],
                ),
            ),
        )
        for entrypoint, callback in entrypoints:
            with self.subTest(entrypoint=entrypoint):
                self.assertEqual(callback(), expected)

if __name__ == "__main__":
    unittest.main(verbosity=2)
