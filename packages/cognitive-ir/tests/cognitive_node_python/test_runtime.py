from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "cognitive-node" / "1.0.0"
PROFILE_ROOT = PACKAGE_ROOT / "contracts" / "profile" / "1.0.0"
PYTHON_ROOT = PACKAGE_ROOT / "python"

sys.path.insert(0, str(PYTHON_ROOT))


class CognitiveNodePythonRuntimeTests(unittest.TestCase):
    def test_raw_transport_api_maps_parser_failures_to_cognitive_codes(self) -> None:
        from intelliengine_cognitive_ir import runtime

        node_schema = json.loads(
            (CONTRACT_ROOT / "schemas" / "cognitive-node.schema.json").read_text(
                encoding="utf-8"
            )
        )

        result = runtime.parse_and_validate_transport(
            b'{"contract_version":"1.0.0","contract_version":"1.0.0"}',
            node_schema,
        )

        self.assertEqual(result["object_result"], "invalid")
        self.assertEqual(result["issues"][0]["code"], "cognitive_node.duplicate_key")

    def run_cli(self, contract_root: Path, profile_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "intelliengine_cognitive_ir.cli",
                "--contract-root",
                str(contract_root),
                "--profile-root",
                str(profile_root),
            ],
            cwd=REPOSITORY_ROOT,
            env={"PYTHONPATH": str(PYTHON_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_executes_all_locked_cases_exactly(self) -> None:
        expected = {
            case["case_id"]: case["expected"]
            for case in json.loads(
                (CONTRACT_ROOT / "fixtures" / "cases.json").read_text(
                    encoding="utf-8"
                )
            )["cases"]
        }
        completed = self.run_cli(CONTRACT_ROOT, PROFILE_ROOT)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([row["case_id"] for row in rows], sorted(expected))
        self.assertEqual(
            {row["case_id"]: {key: value for key, value in row.items() if key != "case_id"} for row in rows},
            expected,
        )

    def test_parser_cases_execute_the_locked_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_root = root / "cognitive-node" / "1.0.0"
            profile_root = root / "profile" / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, contract_root)
            shutil.copytree(PROFILE_ROOT, profile_root)
            (profile_root / "fixtures" / "raw" / "duplicate-key.raw").write_bytes(b"{}")

            completed = self.run_cli(contract_root, profile_root)

        self.assertNotEqual(completed.returncode, 0)

    def test_machine_expected_is_not_used_as_the_computed_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_root = root / "cognitive-node" / "1.0.0"
            profile_root = root / "profile" / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, contract_root)
            shutil.copytree(PROFILE_ROOT, profile_root)
            cases_path = contract_root / "fixtures" / "cases.json"
            suite = json.loads(cases_path.read_text(encoding="utf-8"))
            target = next(
                case
                for case in suite["cases"]
                if case["case_id"] == "core-entity-transport-valid"
            )
            target["expected"]["object_result"] = "invalid"
            cases_path.write_text(
                json.dumps(suite, ensure_ascii=False) + "\n", encoding="utf-8"
            )

            completed = self.run_cli(contract_root, profile_root)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = {row["case_id"]: row for row in map(json.loads, completed.stdout.splitlines())}
        self.assertEqual(rows["core-entity-transport-valid"]["object_result"], "valid")

    def test_parser_fixture_cannot_read_outside_profile_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_root = root / "cognitive-node" / "1.0.0"
            profile_root = root / "profile" / "1.0.0"
            shutil.copytree(CONTRACT_ROOT, contract_root)
            shutil.copytree(PROFILE_ROOT, profile_root)
            (root / "outside.raw").write_bytes(b'{"a":1,"a":2}')
            case_path = profile_root / "fixtures" / "parser-duplicate-key" / "case.json"
            profile_case = json.loads(case_path.read_text(encoding="utf-8"))
            profile_case["input"]["primary"] = "profile/1.0.0/../../outside.raw"
            case_path.write_text(json.dumps(profile_case) + "\n", encoding="utf-8")

            completed = self.run_cli(contract_root, profile_root)

        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
