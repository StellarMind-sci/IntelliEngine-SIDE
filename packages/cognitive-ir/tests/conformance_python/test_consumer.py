from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROFILE_ROOT = REPOSITORY_ROOT / "packages/cognitive-ir/contracts/profile/1.0.0"
PYTHON_ROOT = REPOSITORY_ROOT / "packages/cognitive-ir/python"

sys.path.insert(0, str(PYTHON_ROOT))

from intelliengine_conformance.consumer import (  # noqa: E402
    ConformanceConsumer,
    ConsumerError,
    run_case_document,
)
from intelliengine_conformance.json_codec import (  # noqa: E402
    JsonInputError,
    canonicalize,
    parse_json_bytes,
)
from intelliengine_conformance.regex_profile import RegexProfileError, parse_pattern  # noqa: E402
from intelliengine_conformance.schema_validation import is_valid  # noqa: E402


class JsonCodecTests(unittest.TestCase):
    def test_strict_parser_rejects_transport_ambiguity(self) -> None:
        invalid_inputs = (
            b"\xef\xbb\xbf{}",
            b'{"a":1,"a":2}',
            b'{"a":"\\q"}',
            b'{"a":"\\ud800"}',
            b'{"n":9007199254740992}',
            b'{"n":1e400}',
            b"\xff",
        )
        for raw in invalid_inputs:
            with self.subTest(raw=raw):
                with self.assertRaises(JsonInputError):
                    parse_json_bytes(raw)

    def test_jcs_uses_utf16_key_order_and_ecmascript_number_spelling(self) -> None:
        self.assertEqual(canonicalize({"\ue000": 1, "😀": 2}), '{"😀":2,"\ue000":1}'.encode("utf-8"))
        vectors = (
            (b"1e-6", b"0.000001"),
            (b"1e-7", b"1e-7"),
            (b"1.2345678901234567", b"1.2345678901234567"),
            (b"-0.0", b"0"),
            (b"1.234567890123456e20", b"123456789012345600000"),
            (b"1.0000000000000002e20", b"100000000000000020000"),
            (b"9007199254740991.0", b"9007199254740991"),
            (b"1e21", b"1e+21"),
            (b"9.999999999999997e-7", b"9.999999999999997e-7"),
            (b"1.0000000000000002e-6", b"0.0000010000000000000002"),
            (b"5e-324", b"5e-324"),
            (b"1.7976931348623157e308", b"1.7976931348623157e+308"),
            (b"333333333.33333329", b"333333333.3333333"),
            (b"2e-3", b"0.002"),
            (b"1e-27", b"1e-27"),
        )
        for raw, spelling in vectors:
            with self.subTest(raw=raw):
                self.assertEqual(canonicalize(parse_json_bytes(raw)), spelling)


class RegexProfileTests(unittest.TestCase):
    def test_declared_boundary_vectors(self) -> None:
        for accepted in ("a{4}", "a{1,4}", r"\.", "^[a-z]+$", "(ab)+"):
            with self.subTest(accepted=accepted):
                self.assertGreater(parse_pattern(accepted, maximum_repeat=10_000), 0)
        for rejected in ("a{4,1}", r"\q", "(a|b)+", "a+?", "(?=a)"):
            with self.subTest(rejected=rejected):
                with self.assertRaises(RegexProfileError):
                    parse_pattern(rejected, maximum_repeat=10_000)
        with self.assertRaises(RegexProfileError):
            parse_pattern("a" * 1025, maximum_repeat=10_000)


class SchemaValidationTests(unittest.TestCase):
    def test_integer_and_multiple_of_use_exact_binary64_semantics(self) -> None:
        with self.subTest(rule="mathematical integer"):
            self.assertTrue(is_valid(0.0, {"type": "integer"}))
        with self.subTest(rule="exact multiple"):
            self.assertTrue(is_valid(0.5, {"multipleOf": 0.25}))
        with self.subTest(rule="no epsilon acceptance"):
            self.assertFalse(is_valid(0.30000000000000004, {"multipleOf": 0.1}))


class ConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.consumer = ConformanceConsumer(PROFILE_ROOT)

    def test_all_manifest_cases_match_normative_projection(self) -> None:
        results = self.consumer.run_all()
        manifest = json.loads((PROFILE_ROOT / "fixtures/manifest.json").read_text(encoding="utf-8"))
        expected = {}
        for entry in manifest["cases"]:
            case = json.loads((PROFILE_ROOT / "fixtures" / entry["path"]).read_text(encoding="utf-8"))
            expected[case["case_id"]] = {"case_id": case["case_id"], **case["expected"]}
        for actual in results:
            with self.subTest(case_id=actual["case_id"]):
                self.assertEqual(actual, expected[actual["case_id"]])

    def test_expected_is_not_a_calculation_input(self) -> None:
        case_path = PROFILE_ROOT / "fixtures/annotation-propagation/case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        baseline = run_case_document(PROFILE_ROOT, case)
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            copied_case_path = copied / "fixtures/annotation-propagation/case.json"
            tampered = json.loads(copied_case_path.read_text(encoding="utf-8"))
            tampered["expected"]["raw_sha256"] = "0" * 64
            tampered["expected"]["work_units_consumed"] = 999
            copied_case_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8", newline="\n")

            lock_path = copied / "lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            portable = "profile/1.0.0/fixtures/annotation-propagation/case.json"
            for entry in lock["entries"]:
                if entry["path"] == portable:
                    entry["sha256"] = hashlib.sha256(canonicalize(tampered)).hexdigest()
                    break
            lock_path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8", newline="\n")
            calculated = next(
                result for result in ConformanceConsumer(copied).run_all() if result["case_id"] == case["case_id"]
            )
            self.assertEqual(calculated, baseline)

    def test_profile_corruption_is_fatal_instead_of_a_fixture_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            profile = copied / "profile.json"
            document = json.loads(profile.read_text(encoding="utf-8"))
            document["profile_version"] = "9.9.9"
            profile.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8", newline="\n")
            with self.assertRaises(ConsumerError):
                ConformanceConsumer(copied).run_all()

        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            nested = copied / "fixtures/nested/lock.json"
            nested.parent.mkdir()
            nested.write_text("{}", encoding="utf-8", newline="\n")
            with self.assertRaises(ConsumerError):
                ConformanceConsumer(copied).run_all()

    def test_paths_and_mutation_targets_are_confined(self) -> None:
        case = json.loads(
            (PROFILE_ROOT / "fixtures/sorting-utf16-vs-utf8/case.json").read_text(encoding="utf-8")
        )
        case["input"]["primary"] = "profile/1.0.0/../../../../outside.json"
        with self.assertRaises(ConsumerError):
            run_case_document(PROFILE_ROOT, case)

        tamper = json.loads(
            (PROFILE_ROOT / "fixtures/lock-digest-tamper/case.json").read_text(encoding="utf-8")
        )
        tamper["input"]["primary"] = "profile/1.0.0/profile.json"
        with self.assertRaises(ConsumerError):
            run_case_document(PROFILE_ROOT, tamper)

        append = json.loads(
            (PROFILE_ROOT / "fixtures/lock-self-inclusion/case.json").read_text(encoding="utf-8")
        )
        del append["action"]["entry"]["sha256"]
        with self.assertRaises(ConsumerError):
            run_case_document(PROFILE_ROOT, append)

        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            input_lock = copied / "fixtures/lock-self-inclusion/input-lock.json"
            existing = json.loads(input_lock.read_text(encoding="utf-8"))
            existing["entries"].append(append["action"]["entry"] | {"sha256": "0" * 64})
            input_lock.write_text(json.dumps(existing), encoding="utf-8", newline="\n")
            case = json.loads(
                (copied / "fixtures/lock-self-inclusion/case.json").read_text(encoding="utf-8")
            )
            case["action"]["entry"]["path"] = "profile/1.0.0/profile.json"
            with self.assertRaises(ConsumerError):
                run_case_document(copied, case)

    def test_full_run_reads_only_beneath_profile_root(self) -> None:
        original = Path.read_bytes
        original_resolve = Path.resolve
        reads: list[Path] = []

        def guarded(path: Path) -> bytes:
            resolved = path.resolve()
            resolved.relative_to(PROFILE_ROOT.resolve())
            reads.append(resolved)
            return original(path)

        with mock.patch.object(Path, "read_bytes", guarded):
            self.consumer.run_all()
        self.assertGreater(len(reads), 24)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            copied = workspace / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            external = workspace / "outside-profile.json"
            external.write_bytes((copied / "profile.json").read_bytes())
            consumer = ConformanceConsumer(copied)
            profile_path = consumer.profile_root / "profile.json"
            external = external.resolve()
            attempted_reads: list[Path] = []

            def simulate_escape(path: Path, *args: object, **kwargs: object) -> Path:
                if path == profile_path:
                    return external
                return original_resolve(path, *args, **kwargs)

            def record_attempt(path: Path) -> bytes:
                if path == profile_path:
                    attempted_reads.append(path)
                return original(path)

            with mock.patch.object(Path, "resolve", simulate_escape), mock.patch.object(
                Path, "read_bytes", record_attempt
            ):
                with self.assertRaises(ConsumerError):
                    consumer.run_all()
            self.assertEqual(attempted_reads, [])

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            copied = workspace / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            external = workspace / "outside-resource.json"
            external.write_text('{"type":"string"}', encoding="utf-8", newline="\n")
            sibling = copied / "fixtures/cross-resource-dag/outside.json"
            sibling.write_text('{"type":"string"}', encoding="utf-8", newline="\n")
            sibling = copied.resolve() / "fixtures/cross-resource-dag/outside.json"
            external = external.resolve()
            case = json.loads(
                (copied / "fixtures/cross-resource-dag/case.json").read_text(encoding="utf-8")
            )

            def simulate_sibling_escape(path: Path, *args: object, **kwargs: object) -> Path:
                if path == sibling:
                    return external
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", simulate_sibling_escape):
                with self.assertRaises(ConsumerError):
                    run_case_document(copied, case)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            copied = workspace / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            external = workspace / "outside-profile.json"
            external.write_bytes((copied / "profile.json").read_bytes())
            (copied / "profile.json").unlink()
            try:
                (copied / "profile.json").symlink_to(external)
            except OSError:
                pass
            else:
                external_reads: list[Path] = []

                def detect_external(path: Path) -> bytes:
                    if path.resolve() == external.resolve():
                        external_reads.append(path)
                    return original(path)

                with mock.patch.object(Path, "read_bytes", detect_external):
                    with self.assertRaises(ConsumerError):
                        ConformanceConsumer(copied).run_all()
                self.assertEqual(external_reads, [])

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            copied = workspace / "1.0.0"
            shutil.copytree(PROFILE_ROOT, copied)
            external = workspace / "outside-resource.json"
            external.write_text('{"type":"string"}', encoding="utf-8", newline="\n")
            sibling = copied / "fixtures/cross-resource-dag/outside.json"
            try:
                sibling.symlink_to(external)
            except OSError:
                pass
            else:
                case = json.loads(
                    (copied / "fixtures/cross-resource-dag/case.json").read_text(encoding="utf-8")
                )
                with self.assertRaises(ConsumerError):
                    run_case_document(copied, case)

    def test_cli_emits_sorted_closed_ndjson(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(PYTHON_ROOT)
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "intelliengine_conformance.cli",
                "--profile-root",
                str(PROFILE_ROOT),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        rows = [json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()]
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            [row["case_id"] for row in rows],
            sorted((row["case_id"] for row in rows), key=lambda value: value.encode("utf-8")),
        )
        required = {
            "case_id",
            "contract_id",
            "contract_version",
            "issues",
            "mode",
            "object_result",
            "operation_outcome",
            "profile_version",
            "raw_sha256",
            "work_units_consumed",
        }
        for row in rows:
            self.assertIn(set(row), (required, required | {"jcs_sha256"}))

    def test_package_does_not_reference_normative_verifier_or_typescript(self) -> None:
        package = PYTHON_ROOT / "intelliengine_conformance"
        source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
        self.assertNotIn("verify_profile", source)
        self.assertNotIn("typescript", source.lower())


if __name__ == "__main__":
    unittest.main()
