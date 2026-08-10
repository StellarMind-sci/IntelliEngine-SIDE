from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts"
VERIFIER = CONTRACT_ROOT / "tools" / "verify_profile.py"
PROFILE = Path("profile/1.0.0/profile.json")
DIAGNOSTICS = Path("profile/1.0.0/diagnostics/conformance.json")
LOCK = Path("profile/1.0.0/lock.json")
CYCLE_CASE = Path(
    "profile/1.0.0/fixtures/cross-resource-cycle-attempt/case.json"
)
PROFILE_ROOT = Path("profile/1.0.0")


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("portable_profile_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


class PortableProfileContractTests(unittest.TestCase):
    def run_verifier(self, contract_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--root", str(contract_root)],
            cwd=PACKAGE_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def copy_contracts(self, destination: Path) -> Path:
        copied = destination / "contracts"
        if CONTRACT_ROOT.exists():
            shutil.copytree(CONTRACT_ROOT, copied)
        else:
            copied.mkdir()
        return copied

    def assert_rejected(self, result: subprocess.CompletedProcess[str], code: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(code, result.stderr)

    def test_repository_profile_is_self_consistent(self) -> None:
        result = self.run_verifier(CONTRACT_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "portable profile 1.0.0 verified\n")

    def test_git_checkout_policy_preserves_contract_bytes(self) -> None:
        paths = [
            "packages/cognitive-ir/contracts/profile/1.0.0/profile.json",
            "packages/cognitive-ir/contracts/profile/1.0.0/fixtures/raw/invalid-utf8.raw",
            "packages/cognitive-ir/contracts/tools/verify_profile.py",
        ]
        result = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", *paths],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{paths[0]}: text: set",
                f"{paths[0]}: eol: lf",
                f"{paths[1]}: text: unset",
                f"{paths[1]}: eol: unspecified",
                f"{paths[2]}: text: set",
                f"{paths[2]}: eol: lf",
            ],
        )

    def test_contract_json_and_python_worktree_bytes_are_lf_only(self) -> None:
        candidates = sorted(CONTRACT_ROOT.rglob("*.json")) + sorted(
            CONTRACT_ROOT.rglob("*.py")
        )
        carriage_returns = [
            path.relative_to(CONTRACT_ROOT).as_posix()
            for path in candidates
            if b"\r" in path.read_bytes()
        ]

        self.assertEqual(carriage_returns, [])

    def test_missing_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            (copied / PROFILE).unlink(missing_ok=True)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "profile.missing_file")

    def test_duplicate_keyword_ordinal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            if profile_path.exists():
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                profile["schema_profile"]["keyword_ordinals"]["$ref"] = profile[
                    "schema_profile"
                ]["keyword_ordinals"]["$schema"]
                write_json(profile_path, profile)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "profile.duplicate_keyword_ordinal")

    def test_digest_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "parser-bom" / "case.json"
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["purpose"] += " Tampered after lock creation."
                write_json(case_path, case)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "conformance.digest_mismatch")

    def test_lock_cannot_include_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            lock_path = copied / LOCK
            if lock_path.exists():
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                lock["entries"].append(
                    {
                        "digest_kind": "raw_sha256",
                        "path": LOCK.as_posix(),
                        "sha256": "0" * 64,
                    }
                )
                write_json(lock_path, lock)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "lock.self_inclusion")

    def test_lock_mutation_cases_validate_primary_raw_before_action(self) -> None:
        case_ids = ("lock-digest-tamper", "lock-self-inclusion")
        for case_id in case_ids:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as directory:
                copied = self.copy_contracts(Path(directory))
                case_relative = PROFILE_ROOT / "fixtures" / case_id / "case.json"
                case_path = copied / case_relative
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["expected"]["raw_sha256"] = "0" * 64
                write_json(case_path, case)

                verifier = load_verifier_module()
                case_digest = __import__("hashlib").sha256(
                    verifier.jcs_bytes(case)
                ).hexdigest()
                lock_path = copied / LOCK
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                lock_entry = next(
                    entry
                    for entry in lock["entries"]
                    if entry["path"] == case_relative.as_posix()
                )
                lock_entry["sha256"] = case_digest
                write_json(lock_path, lock)

                result = self.run_verifier(copied)

            self.assert_rejected(result, "fixture.invalid_expected")

    def test_tamper_action_target_must_equal_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_relative = PROFILE_ROOT / "fixtures" / "lock-digest-tamper" / "case.json"
            case_path = copied / case_relative
            case = json.loads(case_path.read_text(encoding="utf-8"))
            separate_primary = copied / PROFILE
            case["input"]["primary"] = PROFILE.as_posix()
            case["expected"]["raw_sha256"] = __import__("hashlib").sha256(
                separate_primary.read_bytes()
            ).hexdigest()
            write_json(case_path, case)

            verifier = load_verifier_module()
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_entry = next(
                entry
                for entry in lock["entries"]
                if entry["path"] == case_relative.as_posix()
            )
            lock_entry["sha256"] = __import__("hashlib").sha256(
                verifier.jcs_bytes(case)
            ).hexdigest()
            write_json(lock_path, lock)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "fixture.invalid_action")

    def test_append_lock_entry_validates_complete_candidate_schema(self) -> None:
        invalid_values = {
            "profile_version": "2.0.0",
            "self_digest": "included",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                copied = self.copy_contracts(Path(directory))
                candidate_relative = (
                    PROFILE_ROOT / "fixtures" / "lock-self-inclusion" / "input-lock.json"
                )
                candidate_path = copied / candidate_relative
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                candidate[field] = value
                write_json(candidate_path, candidate)

                case_relative = PROFILE_ROOT / "fixtures" / "lock-self-inclusion" / "case.json"
                case_path = copied / case_relative
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["expected"]["raw_sha256"] = __import__("hashlib").sha256(
                    candidate_path.read_bytes()
                ).hexdigest()
                write_json(case_path, case)

                verifier = load_verifier_module()
                lock_path = copied / LOCK
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                values = {
                    candidate_relative.as_posix(): candidate,
                    case_relative.as_posix(): case,
                }
                for entry in lock["entries"]:
                    if entry["path"] in values:
                        entry["sha256"] = __import__("hashlib").sha256(
                            verifier.jcs_bytes(values[entry["path"]])
                        ).hexdigest()
                write_json(lock_path, lock)

                result = self.run_verifier(copied)

            self.assert_rejected(result, "profile.machine_schema_validation")

    def test_cross_resource_cycle_cannot_be_declared_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / CYCLE_CASE
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["expected"]["object_result"] = "valid"
                case["expected"]["operation_outcome"] = "succeeded"
                case["expected"]["issues"] = []
                write_json(case_path, case)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "fixture.cross_resource_cycle_expectation")

    def test_normative_json_uses_jcs_lock_and_raw_is_parser_negative_only(self) -> None:
        lock = json.loads((CONTRACT_ROOT / LOCK).read_text(encoding="utf-8"))
        entries = lock["entries"]

        self.assertTrue(any(entry["digest_kind"] == "raw_sha256" for entry in entries))
        for entry in entries:
            if entry["digest_kind"] == "raw_sha256":
                self.assertIn("/raw/", entry["path"])
                self.assertFalse(entry["path"].endswith(".json"))
            else:
                self.assertEqual(entry["digest_kind"], "jcs_sha256")
                self.assertTrue(entry["path"].endswith(".json"))

    def test_jcs_known_vectors_are_hand_fixed(self) -> None:
        verifier = load_verifier_module()
        self.assertTrue(hasattr(verifier, "jcs_bytes"), "verifier must expose jcs_bytes")

        vectors = [
            (b'{"z":3,"a":1}', b'{"a":1,"z":3}', "de513c7e1b16d1dc9de132dff4ee4128c1565ec9a6754b5523f539e6dc8b6c60"),
            (
                '{"\\ue000":1,"😀":2}'.encode("utf-8"),
                '{"😀":2,"":1}'.encode("utf-8"),
                "28c95d1bbb2209223307e62f489020e8f9e0cfa16adf2daf6d88127a1e8dd22a",
            ),
            (b"1e-6", b"0.000001", "159fb29a827ad04b260aa6c8ab6d8637f8f2b38af5c4f3cb49d6a21205e040f8"),
            (b"1e-7", b"1e-7", "5b33e02f2c5103a05d32f6ba9cb058294452bfbf393967f68bb30c1bdcbbab22"),
            (b"1.2345678901234567", b"1.2345678901234567", "05c9e796f4a020a2e0cb1008d3a7432483f1b77b0dea768399adcee66d90ac8e"),
            (b"-0.0", b"0", "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9"),
            (b"1.234567890123456e20", b"123456789012345600000", "811918518c582aa9611e25bb262fba736fe8b589a695a58e879c459313d9af1c"),
            (b"1.0000000000000002e20", b"100000000000000020000", "c6b869ec5e956ba59630e8a46434b66968e24495cd3bfdd23a599453b572c6a8"),
            (b"9007199254740991.0", b"9007199254740991", "f40b423c2dd95ff2b2f027e22208f438cf7242862e5e746860e697308c9add26"),
            (b"1e21", b"1e+21", "241c4643fa70b1dcde1205b71be4e3bebb17e9f880c8e1a33d0ead6c27271d3c"),
            (b"9.999999999999997e-7", b"9.999999999999997e-7", "2ace34b29d30d300aeacd4f2bb83367fa186f11a3f02ed461f35f00fd741a242"),
            (b"1.0000000000000002e-6", b"0.0000010000000000000002", "1e50936073755327eade67e6e2f63fbc584f58fb5117e4c3d748ebe554e1ebd1"),
            (b"5e-324", b"5e-324", "c46e7ca1be4c8734f373a56530787288fa2058d73d07855e9247e949f811a42a"),
            (b"1.7976931348623157e308", b"1.7976931348623157e+308", "c2784e1abd6317452708f3fbf9641c16b959561bc621a1d408c23a20aa2cb585"),
            (b"333333333.33333329", b"333333333.3333333", "6bd9be1c141028789cc35db62f1b43e80d5d4ee24d6d542e775deb16799ff4c7"),
            (b"2e-3", b"0.002", "8d938122d3904436fd32a463678148c7b7595bf667f263a65ab79059e5833a21"),
            (b"1e-27", b"1e-27", "26baf4828d488c0744642cf36f23d01ce4b66afd61a9a689d96e1c3f9015a3d9"),
        ]
        for raw, expected_bytes, expected_digest in vectors:
            value = verifier.parse_json_bytes(raw, Path("hand-fixed-vector.json"))
            actual = verifier.jcs_bytes(value)
            self.assertEqual(actual, expected_bytes)
            self.assertEqual(__import__("hashlib").sha256(actual).hexdigest(), expected_digest)

    def test_machine_schema_catalog_is_complete_and_case_schema_references_it(self) -> None:
        schema_root = CONTRACT_ROOT / PROFILE_ROOT / "schemas"
        names = {path.name for path in schema_root.glob("*.json")}
        self.assertEqual(
            names,
            {
                "diagnostics.schema.json",
                "expected-result.schema.json",
                "fixture-case.schema.json",
                "fixture-manifest.schema.json",
                "lock.schema.json",
                "profile.schema.json",
            },
        )
        case_schema = json.loads(
            (schema_root / "fixture-case.schema.json").read_text(encoding="utf-8")
        )
        expected_ref = case_schema["properties"]["expected"]["$ref"]
        self.assertTrue(expected_ref.startswith("urn:intelliengine:schema:sha256:"))
        self.assertEqual(len(expected_ref.rsplit(":", 1)[1]), 64)

    def test_expected_projection_is_complete_and_closes_state_pairs(self) -> None:
        schema_path = CONTRACT_ROOT / PROFILE_ROOT / "schemas" / "expected-result.schema.json"
        self.assertTrue(schema_path.is_file(), "expected-result schema is required")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "contract_id",
                "contract_version",
                "issues",
                "mode",
                "object_result",
                "operation_outcome",
                "profile_version",
                "raw_sha256",
                "work_units_consumed",
            },
        )
        self.assertIn("allOf", schema)

    def test_fixture_coverage_includes_required_portable_boundaries(self) -> None:
        manifest = json.loads(
            (CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(all("category" in entry for entry in manifest["cases"]))
        categories = {entry["category"] for entry in manifest["cases"]}
        self.assertTrue(
            {
                "parser",
                "recursion",
                "reference-dag",
                "annotation",
                "work-unit",
                "regex",
                "sorting",
                "lock",
                "profile",
            }.issubset(categories)
        )
        parser_cases = {
            entry["case_id"]
            for entry in manifest["cases"]
            if entry["category"] == "parser"
        }
        self.assertTrue(
            {
                "parser-bom",
                "parser-duplicate-key",
                "parser-invalid-utf8",
                "parser-invalid-escape",
                "parser-unpaired-surrogate",
            }.issubset(parser_cases)
        )

    def test_cross_resource_cycle_uses_real_bytes_with_a_false_digest_claim(self) -> None:
        case = json.loads((CONTRACT_ROOT / CYCLE_CASE).read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(case["resources"]), 2)
        for resource in case["resources"]:
            self.assertTrue(
                {"path", "claimed_sha256", "actual_sha256"}.issubset(resource)
            )
            raw_path = CONTRACT_ROOT / resource["path"]
            self.assertTrue(raw_path.is_file())
        self.assertTrue(
            any(resource["claimed_sha256"] != resource["actual_sha256"] for resource in case["resources"])
        )

    def test_regex_and_work_units_are_machine_tables_not_prose_lists(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        regex = profile["regex_profile"]
        self.assertIn("productions", regex)
        self.assertIn("ast_nodes", regex)
        work_units = profile["work_units"]
        self.assertIn("json_value_cost", work_units)
        self.assertIn("keyword_rules", work_units)
        self.assertIn("precharge_and_stop", work_units)
        for keyword in ["if", "contains", "properties", "enum"]:
            self.assertIn(keyword, work_units["keyword_rules"])

    def test_unsafe_integer_is_rejected_before_lock_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["unsafe_integer_probe"] = 9007199254740992
            write_json(profile_path, profile)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "profile.unsafe_integer")

    def test_unpaired_surrogate_is_rejected_before_lock_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            raw = profile_path.read_bytes().rstrip()[:-1] + b',"probe":"\\ud800"}'
            profile_path.write_bytes(raw)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "profile.invalid_unicode_scalar")

    def test_illegal_expected_state_pair_is_rejected_before_lock_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "profile-baseline-valid" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["expected"]["object_result"] = "valid"
            case["expected"]["operation_outcome"] = "indeterminate"
            write_json(case_path, case)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "fixture.illegal_state_pair")

    def test_case_id_must_match_manifest_and_directory_before_lock_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "profile-baseline-valid" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["case_id"] = "wrong-id"
            write_json(case_path, case)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "fixture.id_path_mismatch")

    def test_machine_decision_drift_is_rejected_before_lock_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["publication"]["mode"] = "first-consumer-wins"
            write_json(profile_path, profile)

            result = self.run_verifier(copied)

        self.assert_rejected(result, "profile.machine_decision_drift")

    def test_parser_negative_raw_vectors_are_exact(self) -> None:
        raw_root = CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / "raw"
        vectors = {
            "bom.raw": b"\xef\xbb\xbf{}",
            "duplicate-key.raw": b'{"a":1,"a":2}',
            "invalid-utf8.raw": b'{"a":"\x80"}',
            "invalid-escape.raw": b'{"a":"\\x"}',
            "unpaired-surrogate.raw": b'{"a":"\\ud800"}',
        }
        for name, expected in vectors.items():
            path = raw_root / name
            self.assertTrue(path.is_file(), f"missing raw vector: {name}")
            self.assertEqual(path.read_bytes(), expected)

    def test_sorting_fixture_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "sorting-utf16-vs-utf8" / "case.json"
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["assertions"]["jcs_key_order"] = case["assertions"]["validator_key_order"]
                write_json(case_path, case)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "fixture.sorting_boundary_drift")

    def test_recursion_fixture_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "local-object-recursion" / "case.json"
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["assertions"]["instance_location"] = "unchanged"
                write_json(case_path, case)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "fixture.recursion_boundary_drift")

    def test_cross_resource_dag_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "cross-resource-dag" / "case.json"
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding="utf-8"))
                case["assertions"]["graph"] = "cycle"
                write_json(case_path, case)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "fixture.reference_dag_drift")

    def test_unknown_lock_digest_kind_is_rejected_with_stable_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["entries"][0]["digest_kind"] = "sha1"
            write_json(lock_path, lock)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "lock.invalid_digest_kind")

    def test_overflow_number_is_rejected_before_value_construction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            raw = profile_path.read_bytes().rstrip()[:-1] + b',"probe":1e400}'
            profile_path.write_bytes(raw)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.invalid_json_number")

    def test_lock_schema_closes_digest_kind_to_path_extension(self) -> None:
        schema = json.loads(
            (CONTRACT_ROOT / PROFILE_ROOT / "schemas" / "lock.schema.json").read_text(
                encoding="utf-8"
            )
        )
        entry_schema = schema["properties"]["entries"]["items"]
        self.assertFalse(entry_schema["additionalProperties"])
        self.assertIn("allOf", entry_schema)
        self.assertEqual(len(entry_schema["allOf"]), 2)
        serialized = json.dumps(entry_schema["allOf"], sort_keys=True)
        self.assertIn("jcs_sha256", serialized)
        self.assertIn("raw_sha256", serialized)
        self.assertIn("fixtures/raw", serialized)
        self.assertIn(".raw", serialized)

    def test_all_fixtures_use_closed_machine_input_and_action_dsl(self) -> None:
        manifest = json.loads(
            (CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for entry in manifest["cases"]:
            case = json.loads(
                (
                    CONTRACT_ROOT
                    / PROFILE_ROOT
                    / "fixtures"
                    / entry["path"]
                ).read_text(encoding="utf-8")
            )
            self.assertIn("input", case, entry["case_id"])
            self.assertIn("action", case, entry["case_id"])
            self.assertIsInstance(case["input"], dict, entry["case_id"])
            self.assertIsInstance(case["action"], dict, entry["case_id"])
            self.assertEqual(
                set(case["input"]),
                {"bundle", "instance", "primary", "schema"},
                entry["case_id"],
            )
            self.assertIn("kind", case["action"], entry["case_id"])

    def test_work_unit_boundaries_are_six_executable_cases(self) -> None:
        manifest = json.loads(
            (CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        ids = {entry["case_id"] for entry in manifest["cases"]}
        self.assertTrue(
            {
                "work-unit-admission-limit-minus-one",
                "work-unit-admission-limit",
                "work-unit-admission-limit-plus-one",
                "work-unit-semantic-limit-minus-one",
                "work-unit-semantic-limit",
                "work-unit-semantic-limit-plus-one",
            }.issubset(ids)
        )

    def test_annotation_fixture_has_instance_and_expected_evaluated_sets(self) -> None:
        case = json.loads(
            (
                CONTRACT_ROOT
                / PROFILE_ROOT
                / "fixtures"
                / "annotation-propagation"
                / "case.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIsInstance(case["input"], dict)
        self.assertIsNotNone(case["input"]["instance"])
        self.assertEqual(case["assertions"]["evaluated_properties"], ["kept"])
        self.assertEqual(case["assertions"]["evaluated_items"], [])

    def test_regex_grammar_has_no_undefined_symbols(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        regex = profile["regex_profile"]
        self.assertIn("terminals", regex)
        terminals = {entry["name"] for entry in regex["terminals"]}
        productions = {entry["name"] for entry in regex["productions"]}
        referenced = {
            symbol["name"]
            for production in regex["productions"]
            for alternative in production["alternatives"]
            for symbol in alternative
        }
        self.assertTrue(referenced.issubset(terminals | productions))
        self.assertTrue(
            {"literal", "escape", "start-anchor", "end-anchor", "class-open", "class-close", "range-separator", "negation"}.issubset(terminals)
        )

    def test_keyword_rules_exhaust_every_allowed_keyword(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        allowed = set(profile["schema_profile"]["allowed_keywords"])
        rules = profile["work_units"]["keyword_rules"]
        self.assertEqual(set(rules), allowed)
        for keyword, rule in rules.items():
            self.assertEqual(
                set(rule),
                {"admission_steps", "annotation_rule", "evaluated_set_rule", "semantic_steps"},
                keyword,
            )

    def test_canonical_machine_decision_drift_is_rejected_before_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["canonical_json"]["jcs_key_order"] = "unicode-code-point"
            write_json(profile_path, profile)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.machine_decision_drift")

    def test_unsafe_fixture_path_is_rejected_before_file_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "annotation-propagation" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["input"] = "../outside.json"
            write_json(case_path, case)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "fixture.unsafe_path")

    def test_lock_schema_machine_conflict_is_rejected_before_lock_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            schema_path = copied / PROFILE_ROOT / "schemas" / "lock.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["properties"]["entries"]["items"]["allOf"] = []
            write_json(schema_path, schema)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.lock_schema_conflict")

    def test_regex_grammar_has_disjoint_lexically_closed_symbols(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        regex = profile["regex_profile"]
        terminals = {item["name"] for item in regex["terminals"]}
        productions = {item["name"] for item in regex["productions"]}
        self.assertFalse(terminals & productions)
        for terminal in regex["terminals"]:
            self.assertEqual(
                set(terminal), {"lexeme", "machine_predicate", "name", "token_kind"}
            )
            self.assertTrue(terminal["lexeme"] or terminal["machine_predicate"])

    def test_keyword_rules_are_closed_step_programs(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        rules = profile["work_units"]["keyword_rules"]
        for keyword, rule in rules.items():
            self.assertEqual(
                set(rule),
                {"admission_steps", "annotation_rule", "evaluated_set_rule", "semantic_steps"},
                keyword,
            )
            for phase in ("admission_steps", "semantic_steps"):
                self.assertIsInstance(rule[phase], list)
                self.assertGreater(len(rule[phase]), 0)
                for step in rule[phase]:
                    self.assertEqual(
                        set(step), {"action", "condition", "formula", "iteration", "order"}
                    )
                    self.assertNotEqual(step["action"] is None, step["formula"] is None)
        fixed = {
            "properties": ("declared-map-members", "unsigned-utf8-bytes", "evaluated-properties"),
            "patternProperties": ("actual-members-x-declared-patterns", "member-then-pattern-utf8", "evaluated-properties"),
            "dependentRequired": ("dependency-array-elements", "array-index", "none"),
            "contains": ("matched-array-elements", "array-index", "evaluated-items-on-count-success"),
            "enum": ("enum-candidates", "schema-array-order", "none"),
            "if": ("once", "if-then-else", "propagate-selected-success"),
            "then": ("selected-conditional", "if-then-else", "propagate-selected-success"),
            "else": ("selected-conditional", "if-then-else", "propagate-selected-success"),
        }
        for keyword, (iteration, order, annotation) in fixed.items():
            step = rules[keyword]["semantic_steps"][-1]
            self.assertEqual((step["iteration"], step["order"], rules[keyword]["annotation_rule"]), (iteration, order, annotation))

    def _run_expected_schema_mutation(self, mutate) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            schema_path = copied / PROFILE_ROOT / "schemas" / "expected-result.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            mutate(schema)
            write_json(schema_path, schema)
            verifier = load_verifier_module()
            digest = __import__("hashlib").sha256(verifier.jcs_bytes(schema)).hexdigest()
            case_schema_path = copied / PROFILE_ROOT / "schemas" / "fixture-case.schema.json"
            case_schema = json.loads(case_schema_path.read_text(encoding="utf-8"))
            case_schema["properties"]["expected"]["$ref"] = f"urn:intelliengine:schema:sha256:{digest}"
            write_json(case_schema_path, case_schema)
            lock_path = copied / LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            for entry in lock["entries"]:
                target = copied / Path(entry["path"])
                if entry["path"] in {
                    "profile/1.0.0/schemas/expected-result.schema.json",
                    "profile/1.0.0/schemas/fixture-case.schema.json",
                }:
                    value = json.loads(target.read_text(encoding="utf-8"))
                    entry["sha256"] = __import__("hashlib").sha256(verifier.jcs_bytes(value)).hexdigest()
            write_json(lock_path, lock)
            return self.run_verifier(copied)

    def test_expected_schema_cannot_delete_a_legal_state_pair(self) -> None:
        result = self._run_expected_schema_mutation(
            lambda schema: schema["allOf"][0]["oneOf"].pop(1)
        )
        self.assert_rejected(result, "profile.expected_schema_conflict")

    def test_expected_schema_cannot_loosen_a_legal_state_pair(self) -> None:
        def loosen(schema):
            schema["allOf"][0]["oneOf"][0]["properties"]["operation_outcome"] = {
                "enum": ["succeeded", "indeterminate"]
            }
        result = self._run_expected_schema_mutation(loosen)
        self.assert_rejected(result, "profile.expected_schema_conflict")

    def test_expected_schema_cannot_swap_a_legal_state_pair(self) -> None:
        def swap(schema):
            schema["allOf"][0]["oneOf"][0]["properties"]["object_result"]["const"] = "invalid"
        result = self._run_expected_schema_mutation(swap)
        self.assert_rejected(result, "profile.expected_schema_conflict")

    def test_normative_artifacts_have_no_rewriter_scripts(self) -> None:
        tools = CONTRACT_ROOT / "tools"
        forbidden = {
            "generate_lock.py", "generate_profile_schema_details.py",
            "generate_profile_tables.py", "generate_raw_fixtures.py",
            "upgrade_fixture_dsl.py",
        }
        self.assertFalse(forbidden & {path.name for path in tools.glob("*.py")})

    def test_verifier_rejects_ambiguous_or_open_regex_grammar(self) -> None:
        mutations = {
            "overlap": lambda profile: profile["regex_profile"]["terminals"][8].update({"name": "range"}),
            "undefined": lambda profile: profile["regex_profile"]["productions"][0]["alternatives"][0][0].update({"name": "undefined-symbol"}),
            "no-lexeme": lambda profile: profile["regex_profile"]["terminals"][2].update({"lexeme": None, "machine_predicate": None}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                copied = self.copy_contracts(Path(directory))
                profile_path = copied / PROFILE
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                mutate(profile)
                write_json(profile_path, profile)
                result = self.run_verifier(copied)
                self.assert_rejected(result, "profile.machine_decision_drift")

    def test_verifier_rejects_fixed_keyword_step_drift(self) -> None:
        for keyword in ("properties", "patternProperties", "dependentRequired", "contains", "enum", "if", "then", "else"):
            with self.subTest(keyword=keyword), tempfile.TemporaryDirectory() as directory:
                copied = self.copy_contracts(Path(directory))
                profile_path = copied / PROFILE
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                profile["work_units"]["keyword_rules"][keyword]["semantic_steps"][-1]["order"] = "keyword-ordinal"
                write_json(profile_path, profile)
                result = self.run_verifier(copied)
                self.assert_rejected(result, "profile.machine_decision_drift")

    def test_regex_repeat_and_escape_declarations_are_closed(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        terminals = {item["name"]: item for item in profile["regex_profile"]["terminals"]}
        self.assertEqual(
            terminals["bounded-repeat"]["machine_predicate"],
            {"kind": "bounded-repeat", "values": ["{m}", "{m,n}", "0<=m<=n<=10000"]},
        )
        self.assertEqual(
            terminals["escape"]["machine_predicate"]["values"],
            [".", "*", "+", "?", "[", "]", "(", ")", "{", "}", "|", "^", "$", "\\"],
        )
        case = json.loads(
            (CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / "regex-grammar-boundary" / "case.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            case["assertions"]["declaration_vectors"],
            [
                {"pattern": "a{4}", "result": "accept"},
                {"pattern": "a{1,4}", "result": "accept"},
                {"pattern": "a{4,1}", "result": "reject"},
                {"pattern": "\\.", "result": "accept"},
                {"pattern": "\\q", "result": "reject-private-escape"},
            ],
        )

    def test_keyword_steps_match_hand_fixed_rfc_tables(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        rules = profile["work_units"]["keyword_rules"]
        step = lambda action, condition, iteration, order, formula=None: {
            "action": action, "condition": condition, "formula": formula,
            "iteration": iteration, "order": order,
        }
        expected = {
            "properties": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("map_member_visit", "each-declared-property", "declared-map-members", "unsigned-utf8-bytes"),
                step("property_presence_or_membership_check", "each-declared-property", "declared-map-members", "unsigned-utf8-bytes"),
                step("object_member_or_array_element_visit", "declared-property-present", "declared-map-members", "unsigned-utf8-bytes"),
                step("schema_instance_pair", "declared-property-present", "declared-map-members", "unsigned-utf8-bytes"),
                step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "declared-map-members", "unsigned-utf8-bytes"),
            ],
            "patternProperties": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("map_member_visit", "each-declared-pattern", "declared-map-members", "unsigned-utf8-bytes"),
                step("object_member_or_array_element_visit", "each-actual-member", "actual-object-members", "unsigned-utf8-bytes"),
                step(None, "each-actual-member-times-each-pattern", "actual-members-x-declared-patterns", "member-then-pattern-utf8", "regex_attempt"),
                step("schema_instance_pair", "pattern-matched", "actual-members-x-declared-patterns", "member-then-pattern-utf8"),
                step("evaluated_set_new_marker", "subschema-succeeded-new-marker", "actual-members-x-declared-patterns", "member-then-pattern-utf8"),
            ],
            "dependentRequired": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("map_member_visit", "each-dependent-declaration", "declared-map-members", "unsigned-utf8-bytes"),
                step("property_presence_or_membership_check", "trigger-property", "declared-map-members", "unsigned-utf8-bytes"),
                step("object_member_or_array_element_visit", "trigger-present-each-dependency", "dependency-array-elements", "array-index"),
                step("required_name_presence_check", "trigger-present-each-dependency", "dependency-array-elements", "array-index"),
            ],
            "contains": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("object_member_or_array_element_visit", "each-actual-array-element", "actual-array-elements", "array-index"),
                step("schema_instance_pair", "each-actual-array-element", "actual-array-elements", "array-index"),
                step("evaluated_set_new_marker", "contains-count-succeeded-new-marker", "matched-array-elements", "array-index"),
            ],
            "enum": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("object_member_or_array_element_visit", "each-enum-candidate", "enum-candidates", "schema-array-order"),
                step(None, "each-enum-candidate-full-scan", "enum-candidates", "schema-array-order", "const_or_enum_jcs_compare"),
            ],
            "if": [
                step("keyword_visit", "always", "once", "keyword-ordinal"),
                step("applicator_branch_entry", "evaluate-if-schema", "once", "if-then-else"),
                step("schema_instance_pair", "evaluate-if-schema", "once", "if-then-else"),
            ],
            "contentSchema": [step("keyword_visit", "always", "once", "keyword-ordinal")],
        }
        for keyword, semantic_steps in expected.items():
            self.assertEqual(rules[keyword]["semantic_steps"], semantic_steps, keyword)
        self.assertEqual(
            rules["contentSchema"]["admission_steps"],
            [
                step("schema_keyword_visit", "always", "once", "keyword-ordinal"),
                step("single_schema_descent", "keyword-selects-schema", "once", "keyword-ordinal"),
            ],
        )

    def test_not_annotation_rule_is_hand_fixed(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        rule = profile["work_units"]["keyword_rules"]["not"]
        self.assertEqual(rule["annotation_rule"], "discard-always")

    def test_verifier_rejects_not_annotation_rule_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["work_units"]["keyword_rules"]["not"]["annotation_rule"] = "propagate-success-only"
            write_json(profile_path, profile)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.machine_decision_drift")

    def test_dependent_schemas_rule_is_hand_fixed(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        rule = profile["work_units"]["keyword_rules"]["dependentSchemas"]
        step = lambda action, condition, iteration, order: {
            "action": action, "condition": condition, "formula": None,
            "iteration": iteration, "order": order,
        }
        self.assertEqual(
            rule,
            {
                "admission_steps": [
                    step("schema_keyword_visit", "always", "once", "keyword-ordinal"),
                    step("schema_map_member", "keyword-value-is-map", "map-values", "unsigned-utf8-bytes"),
                ],
                "annotation_rule": "propagate-success-only",
                "evaluated_set_rule": "none",
                "semantic_steps": [
                    step("keyword_visit", "always", "once", "keyword-ordinal"),
                    step("map_member_visit", "each-dependent-declaration", "declared-map-members", "unsigned-utf8-bytes"),
                    step("property_presence_or_membership_check", "trigger-property", "declared-map-members", "unsigned-utf8-bytes"),
                    step("applicator_branch_entry", "trigger-present", "declared-map-members", "unsigned-utf8-bytes"),
                    step("schema_instance_pair", "trigger-present", "declared-map-members", "unsigned-utf8-bytes"),
                ],
            },
        )

    def test_verifier_rejects_dependent_schemas_rule_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            rule = profile["work_units"]["keyword_rules"]["dependentSchemas"]
            rule["semantic_steps"] = [
                {"action": "keyword_visit", "condition": "always", "formula": None, "iteration": "once", "order": "keyword-ordinal"},
                {"action": "applicator_branch_entry", "condition": "keyword-applicable", "formula": None, "iteration": "applicator-branches", "order": "schema-array-order"},
                {"action": "schema_instance_pair", "condition": "each-selected-subschema", "formula": None, "iteration": "applicator-branches", "order": "schema-array-order"},
                {"action": "evaluated_set_new_marker", "condition": "subschema-succeeded", "formula": None, "iteration": "map-values", "order": "unsigned-utf8-bytes"},
            ]
            rule["evaluated_set_rule"] = "properties-on-success"
            write_json(profile_path, profile)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.machine_decision_drift")

    def test_property_names_rule_is_hand_fixed(self) -> None:
        profile = json.loads((CONTRACT_ROOT / PROFILE).read_text(encoding="utf-8"))
        rule = profile["work_units"]["keyword_rules"]["propertyNames"]
        step = lambda action, condition: {
            "action": action, "condition": condition, "formula": None,
            "iteration": "actual-object-members", "order": "unsigned-utf8-bytes",
        }
        self.assertEqual(
            rule["semantic_steps"],
            [
                {"action": "keyword_visit", "condition": "always", "formula": None, "iteration": "once", "order": "keyword-ordinal"},
                step("object_member_or_array_element_visit", "each-actual-member"),
                step("applicator_branch_entry", "each-property-name"),
                step("schema_instance_pair", "property-name-instance"),
            ],
        )
        self.assertEqual(rule["annotation_rule"], "propagate-success-only")
        self.assertEqual(rule["evaluated_set_rule"], "none")

    def test_verifier_rejects_property_names_rule_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["work_units"]["keyword_rules"]["propertyNames"]["semantic_steps"] = [
                {"action": "keyword_visit", "condition": "always", "formula": None, "iteration": "once", "order": "keyword-ordinal"},
                {"action": "applicator_branch_entry", "condition": "keyword-applicable", "formula": None, "iteration": "applicator-branches", "order": "schema-array-order"},
                {"action": "schema_instance_pair", "condition": "each-selected-subschema", "formula": None, "iteration": "applicator-branches", "order": "schema-array-order"},
            ]
            write_json(profile_path, profile)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.machine_decision_drift")

    def test_small_fixtures_have_hand_fixed_nonzero_work_traces(self) -> None:
        expected_totals = {
            "regex-grammar-boundary": 32,
            "annotation-propagation": 16,
            "local-object-recursion": 37,
        }
        for case_id, total in expected_totals.items():
            case = json.loads((CONTRACT_ROOT / PROFILE_ROOT / "fixtures" / case_id / "case.json").read_text(encoding="utf-8"))
            trace = case["assertions"]["work_unit_trace"]
            self.assertGreater(len(trace), 0)
            self.assertEqual(sum(item["expected_units"] for item in trace), total)
            self.assertEqual(case["expected"]["work_units_consumed"], total)

    def test_verifier_rejects_regex_catalog_and_trace_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            profile_path = copied / PROFILE
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            escape = next(item for item in profile["regex_profile"]["terminals"] if item["name"] == "escape")
            escape["machine_predicate"]["values"].append("q")
            write_json(profile_path, profile)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "profile.machine_decision_drift")

        with tempfile.TemporaryDirectory() as directory:
            copied = self.copy_contracts(Path(directory))
            case_path = copied / PROFILE_ROOT / "fixtures" / "regex-grammar-boundary" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["assertions"]["work_unit_trace"][0]["expected_units"] += 1
            case["expected"]["work_units_consumed"] += 1
            write_json(case_path, case)
            result = self.run_verifier(copied)
        self.assert_rejected(result, "fixture.work_unit_trace_drift")


if __name__ == "__main__":
    unittest.main(verbosity=2)
