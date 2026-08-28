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

    @staticmethod
    def canonical_digest(value: object) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def policy_bound_input(self) -> dict:
        value = copy.deepcopy(self.value)
        change_set = value["change_sets"][0]
        request = value["request"]
        decision = {
            "actor_ref": request["actor_ref"],
            "authority_scope_ref": request["authority_scope_ref"],
            "command_fingerprint": request["command_fingerprint"],
            "constraints": {
                "platform_safety_caps": ["no-device", "no-file", "no-final-commit", "no-model", "no-network", "no-runtime-lease"],
                "requires_changeset": True,
                "requires_fence": True,
            },
            "decision_id": "22222222-2222-4222-8222-222222222222",
            "expires_at": "2028-01-01T00:00:00Z",
            "family": "control-policy",
            "operation_class": request["operation_class"],
            "outcome": "allow",
            "policy_digest": "b" * 64,
            "policy_id": "11111111-1111-4111-8111-111111111111",
            "provenance_record_ref": request["provenance_record_ref"],
            "pure_plan_digest": request["pure_plan"]["plan_digest"],
            "revoked": False,
            "runtime_context_ref": request["runtime_context_ref"],
            "target_ref": request["target_ref"],
            "valid_from": "2026-01-01T00:00:00Z",
            "version": "1.0.0",
        }
        request["policy_snapshot"] = {"decision": decision, "decision_ref": ""}
        self.resign_policy_and_change_set(value)
        return value

    def resign_policy_and_change_set(self, value: dict) -> None:
        decision = value["request"]["policy_snapshot"]["decision"]
        decision.pop("decision_digest", None)
        decision["decision_digest"] = self.canonical_digest(decision)
        decision_ref = f'control-policy/1.0.0/decision/{decision["decision_id"]}@sha256:{decision["decision_digest"]}'
        value["request"]["policy_snapshot"]["decision_ref"] = decision_ref
        value["request"]["control_policy_ref"] = decision_ref
        change_set = value["change_sets"][0]
        change_set["control_policy_ref"] = decision_ref
        change_set.pop("change_set_digest", None)
        change_set["change_set_digest"] = self.canonical_digest(change_set)
        value["reference"] = f'change-set/1.0.0/{change_set["change_set_id"]}@sha256:{change_set["change_set_digest"]}'

    def test_closed_offline_profile_verifies_repository_contract(self) -> None:
        result = self.run_verifier(CONTRACT_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "change-set 1.0.0 verified\n")

    def test_approved_binding_is_exact_for_every_authority_input(self) -> None:
        value = self.policy_bound_input()
        self.assertEqual(self.verifier.validate_binding(**value), {"status": "not_evaluated", "diagnostic": "change_set.approval_resolution_required"})
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
                request = copy.deepcopy(value["request"])
                request[key] = "different"
                self.assertEqual(self.verifier.validate_binding(value["change_sets"], value["reference"], request, value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})
        for key, diagnostic in (("before_digest", "change_set.binding_before_mismatch"), ("after_digest", "change_set.binding_after_mismatch"), ("plan_digest", "change_set.binding_plan_mismatch")):
            with self.subTest(plan_key=key):
                request = copy.deepcopy(value["request"])
                request["pure_plan"][key] = "f" * 64
                self.assertEqual(self.verifier.validate_binding(value["change_sets"], value["reference"], request, value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})

    def test_policy_snapshot_must_be_exact_current_allow_evidence(self) -> None:
        for field, invalid, diagnostic in (
            ("outcome", "deny", "change_set.policy_denied"),
            ("outcome", "indeterminate", "change_set.policy_indeterminate"),
            ("revoked", True, "change_set.policy_revoked"),
            ("expires_at", "2027-01-01T00:00:00Z", "change_set.policy_expired"),
            ("valid_from", "2027-01-01T00:00:00.000000001Z", "change_set.policy_not_yet_valid"),
            ("actor_ref", "actor/other", "change_set.binding_actor_mismatch"),
            ("authority_scope_ref", "scope/other", "change_set.binding_scope_mismatch"),
            ("runtime_context_ref", "context/other", "change_set.binding_context_mismatch"),
            ("target_ref", "agent-profile/other", "change_set.binding_target_mismatch"),
            ("operation_class", "different", "change_set.binding_operation_mismatch"),
            ("command_fingerprint", "d" * 64, "change_set.binding_fingerprint_mismatch"),
            ("provenance_record_ref", "provenance-record/1.0.0/55555555-5555-4555-8555-555555555555@sha256:" + "a" * 64, "change_set.binding_provenance_mismatch"),
            ("pure_plan_digest", "d" * 64, "change_set.binding_plan_mismatch"),
        ):
            with self.subTest(field=field, invalid=invalid):
                value = self.policy_bound_input()
                value["request"]["policy_snapshot"]["decision"][field] = invalid
                self.resign_policy_and_change_set(value)
                self.assertEqual(self.verifier.validate_binding(**value), {"status": "rejected", "diagnostic": diagnostic})

        for mutate, diagnostic in (
            (lambda decision: decision.__setitem__("version", "1.1.0"), "change_set.invalid_policy_snapshot"),
            (lambda decision: decision.__setitem__("family", "change-set"), "change_set.invalid_policy_snapshot"),
            (lambda decision: decision["constraints"].__setitem__("requires_fence", False), "change_set.policy_safety_cap_mismatch"),
            (lambda decision: decision["constraints"].__setitem__("platform_safety_caps", []), "change_set.policy_safety_cap_mismatch"),
        ):
            with self.subTest(diagnostic=diagnostic):
                value = self.policy_bound_input()
                mutate(value["request"]["policy_snapshot"]["decision"])
                self.resign_policy_and_change_set(value)
                self.assertEqual(self.verifier.validate_binding(**value), {"status": "rejected", "diagnostic": diagnostic})

        value = self.policy_bound_input()
        value["request"]["policy_snapshot"]["decision"]["decision_digest"] = "0" * 64
        self.assertEqual(self.verifier.validate_binding(**value), {"status": "rejected", "diagnostic": "change_set.policy_digest_mismatch"})

        value = self.policy_bound_input()
        value["request"]["policy_snapshot"]["decision_ref"] = value["request"]["policy_snapshot"]["decision_ref"].replace("22222222", "44444444")
        self.assertEqual(self.verifier.validate_binding(**value), {"status": "rejected", "diagnostic": "change_set.binding_policy_mismatch"})

    def test_caller_claimed_approval_never_becomes_fence_ready(self) -> None:
        value = self.policy_bound_input()
        old = value["change_sets"][0]
        revoked = copy.deepcopy(old)
        revoked["status"] = "revoked"
        revoked.pop("change_set_digest")
        revoked["change_set_digest"] = self.canonical_digest(revoked)
        expected = {"status": "not_evaluated", "diagnostic": "change_set.approval_resolution_required"}
        self.assertEqual(self.verifier.validate_binding([old], value["reference"], value["request"], value["validation_time"]), expected)
        self.assertEqual(self.verifier.validate_binding([old, revoked], value["reference"], value["request"], value["validation_time"]), expected)

        forged = self.policy_bound_input()
        forged["request"]["actor_ref"] = "actor/self-asserted"
        forged["request"]["policy_snapshot"]["decision"]["actor_ref"] = "actor/self-asserted"
        forged["change_sets"][0]["actor_ref"] = "actor/self-asserted"
        self.resign_policy_and_change_set(forged)
        self.assertEqual(self.verifier.validate_binding(**forged), expected)


    def test_only_current_approved_status_can_prepare_a_future_fence(self) -> None:
        for status, diagnostic in (("proposed", "change_set.not_approved"), ("rejected", "change_set.rejected"), ("revoked", "change_set.revoked"), ("expired", "change_set.expired"), ("indeterminate", "change_set.indeterminate")):
            change_set = copy.deepcopy(self.value["change_sets"][0])
            change_set["status"] = status
            change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
            self.assertEqual(self.verifier.validate_binding([change_set], self.verifier.exact_reference(change_set), self.value["request"], self.value["validation_time"]), {"status": "rejected", "diagnostic": diagnostic})
        self.assertEqual(self.verifier.validate_binding(self.value["change_sets"], self.value["reference"], self.value["request"], "2031-01-01T00:00:00Z")["diagnostic"], "change_set.expired")

    def test_validity_is_nanosecond_exact_start_inclusive_expiry_exclusive(self) -> None:
        value = self.policy_bound_input()
        change_set = copy.deepcopy(value["change_sets"][0])
        change_set["valid_from"], change_set["expires_at"] = "2027-01-01T00:00:00.500000001Z", "2027-01-01T00:00:00.7Z"
        change_set["change_set_digest"] = self.verifier.change_set_digest(change_set)
        reference = self.verifier.exact_reference(change_set)
        self.assertEqual(self.verifier.validate_binding([change_set], reference, value["request"], "2027-01-01T00:00:00.500000001Z")["status"], "not_evaluated")
        self.assertEqual(self.verifier.validate_binding([change_set], reference, value["request"], "2027-01-01T00:00:00.700000000Z")["diagnostic"], "change_set.expired")
        self.assertEqual(self.verifier.validate_binding([change_set], reference, value["request"], "2027-01-01T00:00:00.5Z")["diagnostic"], "change_set.not_yet_valid")
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

        value = self.policy_bound_input()
        for path, invalid in (
            (("policy_snapshot",), None),
            (("policy_snapshot", "decision"), []),
            (("policy_snapshot", "decision", "revoked"), []),
            (("policy_snapshot", "decision", "constraints", "platform_safety_caps"), [{}]),
        ):
            with self.subTest(policy_path=path):
                request = copy.deepcopy(value["request"])
                target = request
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = invalid
                self.assertEqual(
                    self.verifier.validate_binding(value["change_sets"], value["reference"], request, value["validation_time"]),
                    {"status": "rejected", "diagnostic": "change_set.invalid_policy_snapshot"},
                )

        raw_change_set = json.dumps(value["change_sets"][0], separators=(",", ":")).encode()
        raw_request = json.dumps(dict(value["request"], policy_snapshot=None), separators=(",", ":")).encode()
        self.assertEqual(
            self.verifier.validate_binding_bytes([raw_change_set], value["reference"], raw_request, value["validation_time"]),
            {"status": "rejected", "diagnostic": "change_set.invalid_policy_snapshot"},
        )

if __name__ == "__main__":
    unittest.main(verbosity=2)
