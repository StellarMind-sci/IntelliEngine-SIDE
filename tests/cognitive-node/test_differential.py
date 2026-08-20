from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "cognitive-ir"
RUNNER = REPOSITORY_ROOT / "scripts" / "cognitive-node" / "differential.py"
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "cognitive-node" / "1.0.0"
PROFILE_ROOT = PACKAGE_ROOT / "contracts" / "profile" / "1.0.0"
NODE = Path(
    os.environ.get("NODE")
    or shutil.which("node")
    or r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
)


class CognitiveNodeDifferentialTests(unittest.TestCase):
    def run_gate(self, contract_root: Path, profile_root: Path) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["NODE"] = str(NODE)
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(RUNNER),
                "--contract-root",
                str(contract_root),
                "--profile-root",
                str(profile_root),
                "--node",
                str(NODE),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_real_consumers_match_all_machine_expected_results(self) -> None:
        completed = self.run_gate(CONTRACT_ROOT, PROFILE_ROOT)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {"case_count": 18, "status": "passed"},
        )

    def test_common_consumer_result_cannot_override_machine_expected(self) -> None:
        import tempfile

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
            cases_path.write_text(json.dumps(suite, ensure_ascii=False) + "\n", encoding="utf-8")

            completed = self.run_gate(contract_root, profile_root)

        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
