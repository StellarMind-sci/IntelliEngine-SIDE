from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "packages/cognitive-ir/contracts/profile/1.0.0"
RUNNER = ROOT / "scripts/conformance/differential.py"
SPEC = importlib.util.spec_from_file_location("differential_runner", RUNNER)
assert SPEC and SPEC.loader
DIFFERENTIAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIFFERENTIAL)


def jcs(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def normative_rows(profile: Path = PROFILE) -> list[dict[str, object]]:
    manifest = json.loads((profile / "fixtures/manifest.json").read_text(encoding="utf-8"))
    rows = []
    for entry in manifest["cases"]:
        case = json.loads((profile / "fixtures" / entry["path"]).read_text(encoding="utf-8"))
        rows.append({"case_id": case["case_id"], **case["expected"]})
    return sorted(rows, key=lambda row: str(row["case_id"]).encode())


class DifferentialRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.rows = root / "rows.json"
        self.rows.write_text(json.dumps(normative_rows(), ensure_ascii=False), encoding="utf-8")
        self.stub = root / "stub.py"
        self.stub.write_text(
            """import json,sys,time
rows=json.load(open(sys.argv[1],encoding='utf-8')); mode=sys.argv[2]
if mode=='crash': raise SystemExit(7)
if mode=='timeout': time.sleep(10)
if mode=='descendant-timeout':
 __import__('subprocess').Popen([sys.executable,'-c','import time; time.sleep(30)'])
 time.sleep(30)
if mode=='stderr': print('synthetic secret payload',file=sys.stderr)
if mode=='huge-stdout': print('x'*1048577); raise SystemExit(0)
if mode=='huge-stderr': print('x'*1048577,file=sys.stderr); raise SystemExit(0)
if mode=='unknown-secret': rows.append(dict(rows[0],case_id='SECRET-UNKNOWN-CASE'))
if mode=='nested-issue-drift': next(row for row in rows if row['issues'])['issues'][0]['code']='changed'
if mode=='unsafe-integer': rows[0]['work_units_consumed']=9007199254740992
if mode=='float-zero': next(row for row in rows if row['work_units_consumed']==0)['work_units_consumed']=0.0
if mode=='float-half': rows[0]['work_units_consumed']=0.5
if mode=='bool-units': rows[0]['work_units_consumed']=True
if mode=='env-poison' and any(k in __import__('os').environ for k in ('GITHUB_TOKEN','SECRET_TEST_TOKEN','NODE_OPTIONS')): print('environment leaked',file=sys.stderr)
if mode=='drift': rows[0]['work_units_consumed']+=1
if mode=='secret-drift': rows[0]['contract_id']='DO-NOT-LEAK-PAYLOAD'
if mode=='missing': rows=rows[:-1]
if mode=='duplicate': rows.append(rows[0])
if mode=='extra': rows.append(dict(rows[0],case_id='extra-case'))
if mode=='malformed': print('{'); raise SystemExit(0)
for index,row in enumerate(rows):
 print(json.dumps(row,ensure_ascii=False,sort_keys=index%2==0,separators=(',',':') if index%2 else None))
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self, mode: str) -> list[str]:
        return [sys.executable, "-B", str(self.stub), str(self.rows), mode]

    def run_runner(self, left: str, right: str, profile: Path = PROFILE, timeout: float = 2) -> tuple[int, dict[str, object]]:
        return DIFFERENTIAL.run_gate(
            profile,
            {"typescript": self.command(left), "python": self.command(right)},
            timeout_seconds=timeout,
        )

    def test_key_order_and_whitespace_do_not_affect_jcs_comparison(self) -> None:
        code, report = self.run_runner("good", "good")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["case_count"], 24)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(json.loads((PROFILE / "lock.json").read_text(encoding="utf-8"))["entries"]), 52)

    def test_one_or_both_consumers_drifting_from_machine_expected_fails(self) -> None:
        for left, right in (("drift", "good"), ("drift", "drift")):
            with self.subTest(left=left, right=right):
                code, report = self.run_runner(left, right)
                self.assertEqual(code, 1)
                self.assertEqual(report["issues"][0]["code"], "conformance.result_mismatch")
                self.assertEqual(report["issues"][0]["path"], "/annotation-propagation/work_units_consumed")

    def test_crash_timeout_and_stderr_are_stable_infrastructure_failures(self) -> None:
        expected = {"crash": ("conformance.consumer_crashed", "exit_nonzero"), "timeout": ("conformance.consumer_timeout", "timeout"), "stderr": ("conformance.consumer_crashed", "stderr_nonempty"), "huge-stdout": ("conformance.output_invalid", "stdout_limit"), "huge-stderr": ("conformance.consumer_crashed", "stderr_limit")}
        for mode, (expected_code, status) in expected.items():
            with self.subTest(mode=mode):
                code, report = self.run_runner(mode, "good", timeout=0.1 if mode == "timeout" else 2)
                self.assertEqual(code, 1)
                self.assertEqual(report["issues"][0]["code"], expected_code)
                self.assertEqual(report["issues"][0]["status"], status)
                self.assertNotIn("synthetic secret payload", json.dumps(report))

        started = __import__("time").monotonic()
        code, report = self.run_runner("descendant-timeout", "good", timeout=0.2)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "timeout")
        self.assertLess(__import__("time").monotonic() - started, 3.0)

    def test_malformed_missing_duplicate_and_extra_rows_fail_closed(self) -> None:
        expected = {"malformed": "conformance.output_invalid", "missing": "conformance.fixture_set_mismatch", "duplicate": "conformance.fixture_set_mismatch", "extra": "conformance.fixture_set_mismatch"}
        for mode, expected_code in expected.items():
            with self.subTest(mode=mode):
                code, report = self.run_runner(mode, "good")
                self.assertEqual(code, 1)
                self.assertEqual(report["issues"][0]["code"], expected_code)

    def test_failure_report_contains_only_code_consumer_and_minimal_path(self) -> None:
        code, report = self.run_runner("secret-drift", "good")
        self.assertEqual(code, 1)
        self.assertEqual(set(report), {"report_version", "profile_version", "status", "case_count", "issues"})
        self.assertLessEqual(set(report["issues"][0]), {"code", "status", "consumer", "case_id", "path", "details_sha256"})
        self.assertNotIn("DO-NOT-LEAK-PAYLOAD", json.dumps(report))

        code, report = self.run_runner("unknown-secret", "good")
        self.assertEqual(code, 1)
        self.assertNotIn("SECRET-UNKNOWN-CASE", json.dumps(report))

    def test_recursive_difference_reports_pointer_escaped_minimal_path(self) -> None:
        code, report = self.run_runner("nested-issue-drift", "good")
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["path"], "/cross-resource-cycle-attempt/issues/0/code")

    def test_child_environment_is_allowlisted(self) -> None:
        previous = {name: os.environ.get(name) for name in ("GITHUB_TOKEN", "SECRET_TEST_TOKEN", "NODE_OPTIONS")}
        os.environ.update({"GITHUB_TOKEN": "secret", "SECRET_TEST_TOKEN": "secret", "NODE_OPTIONS": "--trace-warnings"})
        try:
            code, report = self.run_runner("env-poison", "good")
            self.assertEqual(code, 0, report)
        finally:
            for name, value in previous.items():
                if value is None: os.environ.pop(name, None)
                else: os.environ[name] = value

    def test_unsafe_integer_output_is_rejected_before_value_construction(self) -> None:
        code, report = self.run_runner("unsafe-integer", "good")
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["code"], "conformance.output_invalid")

    def test_mathematical_integer_zero_is_jcs_equivalent_across_numeric_hosts(self) -> None:
        code, report = self.run_runner("float-zero", "good")
        self.assertEqual(code, 0, report)
        for mode in ("float-half", "bool-units"):
            code, report = self.run_runner(mode, "good")
            self.assertEqual(code, 1)
            self.assertEqual(report["issues"][0]["code"], "conformance.output_invalid")

    def test_json_surrogate_pairs_form_scalars_and_unpaired_orders_are_rejected(self) -> None:
        self.assertEqual(DIFFERENTIAL.strict_json(b'"\\ud83d\\ude00"', "/value"), "😀")
        for raw in (b'"\\ud800"', b'"\\udc00"', b'"\\udc00\\ud800"'):
            with self.assertRaises(DIFFERENTIAL.GateError):
                DIFFERENTIAL.strict_json(raw, "/value")

    def test_unlocked_files_are_rejected_before_consumers_start(self) -> None:
        copied = Path(self.temporary.name) / "unlocked" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        (copied / "unlocked.json").write_text("{}\n", encoding="utf-8")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["code"], "conformance.offline_boundary_violation")

    def test_manifest_path_escape_is_rejected_even_when_relocked(self) -> None:
        copied = Path(self.temporary.name) / "escape" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        manifest_path = copied / "fixtures/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cases"][0]["path"] = "../outside.json"
        manifest_path.write_bytes(jcs(manifest) + b"\n")
        lock_path = copied / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for entry in lock["entries"]:
            if entry["path"].endswith("fixtures/manifest.json"):
                entry["sha256"] = hashlib.sha256(jcs(manifest)).hexdigest()
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "unsafe_path")

    def test_external_reference_is_rejected_before_consumers_start(self) -> None:
        copied = Path(self.temporary.name) / "external" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json"
        schema_path = copied / "fixtures/regex-grammar-boundary/schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["$ref"] = "https://example.invalid/schema.json"
        schema_path.write_bytes(jcs(schema) + b"\n")
        lock_path = copied / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for entry in lock["entries"]:
            if entry["path"] == relative:
                entry["sha256"] = hashlib.sha256(jcs(schema)).hexdigest()
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "external_reference")

    def test_lock_schema_and_local_reference_syntax_are_enforced(self) -> None:
        copied = Path(self.temporary.name) / "bad-lock" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        lock_path = copied / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["entries"][0]["digest_kind"] = "unknown"
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["code"], "conformance.offline_boundary_violation")

        copied = Path(self.temporary.name) / "bad-ref" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json"
        schema_path = copied / "fixtures/regex-grammar-boundary/schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8")); schema["$ref"] = "#bad"
        schema_path.write_bytes(jcs(schema) + b"\n")
        lock_path = copied / "lock.json"; lock = json.loads(lock_path.read_text(encoding="utf-8"))
        next(entry for entry in lock["entries"] if entry["path"] == relative)["sha256"] = hashlib.sha256(jcs(schema)).hexdigest()
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "external_reference")

    def test_negative_fixture_claimed_digest_is_not_a_global_reference_registry(self) -> None:
        copied = Path(self.temporary.name) / "claimed" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json"
        schema_path = copied / "fixtures/regex-grammar-boundary/schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["$ref"] = "urn:intelliengine:schema:sha256:" + "b" * 64
        schema_path.write_bytes(jcs(schema) + b"\n")
        lock_path = copied / "lock.json"; lock = json.loads(lock_path.read_text(encoding="utf-8"))
        next(entry for entry in lock["entries"] if entry["path"] == relative)["sha256"] = hashlib.sha256(jcs(schema)).hexdigest()
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "external_reference")

    def test_negative_claim_cannot_register_a_schema_owned_by_another_fixture(self) -> None:
        copied = Path(self.temporary.name) / "claim-owner" / "profile" / "1.0.0"
        shutil.copytree(PROFILE, copied)
        case_relative = "profile/1.0.0/fixtures/cross-resource-cycle-attempt/case.json"
        schema_relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json"
        case_path = copied / "fixtures/cross-resource-cycle-attempt/case.json"
        schema_path = copied / "fixtures/regex-grammar-boundary/schema.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["resources"].append({
            "actual_sha256": "c" * 64, "claimed_sha256": "c" * 64,
            "path": schema_relative, "refs": [],
            "uri": "urn:intelliengine:schema:sha256:" + "c" * 64,
        })
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["$ref"] = "urn:intelliengine:schema:sha256:" + "c" * 64
        case_path.write_bytes(jcs(case) + b"\n"); schema_path.write_bytes(jcs(schema) + b"\n")
        lock_path = copied / "lock.json"; lock = json.loads(lock_path.read_text(encoding="utf-8"))
        next(entry for entry in lock["entries"] if entry["path"] == case_relative)["sha256"] = hashlib.sha256(jcs(case)).hexdigest()
        next(entry for entry in lock["entries"] if entry["path"] == schema_relative)["sha256"] = hashlib.sha256(jcs(schema)).hexdigest()
        lock_path.write_bytes(jcs(lock) + b"\n")
        code, report = self.run_runner("good", "good", copied)
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["status"], "external_reference")

    def test_merged_consumers_do_not_import_network_or_normative_peer_code(self) -> None:
        sources = [
            *list((ROOT / "packages/cognitive-ir/src/conformance-ts").glob("*.ts")),
            *list((ROOT / "packages/cognitive-ir/python/intelliengine_conformance").glob("*.py")),
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in sources).lower()
        for forbidden in ("node:http", "node:https", "fetch(", "import socket", "import urllib", "verify_profile"):
            self.assertNotIn(forbidden, text)

    def test_public_cli_rejects_nonpositive_and_nonfinite_timeout_as_usage(self) -> None:
        for value in ("0", "-1", "NaN", "inf"):
            completed = subprocess.run(
                [sys.executable, "-B", str(RUNNER), "--profile-root", str(PROFILE), "--timeout-seconds", value],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
