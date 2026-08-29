from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
PYTHON_ROOT = PACKAGE_ROOT / "python"
COGNITIVE_PYTHON = REPOSITORY_ROOT / "packages" / "cognitive-ir" / "python"
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "knowledge-unit" / "1.0.0"
FIXTURE_PATH = PACKAGE_ROOT / "tests" / "fixtures" / "project-projection-cases.json"
TS_MODULE_PATH = PACKAGE_ROOT / "src" / "knowledge-unit" / "project.ts"
sys.path[:0] = [str(PYTHON_ROOT), str(COGNITIVE_PYTHON)]

from intelliengine_knowledge_units.project import project_knowledge


def load_inputs(fixture: dict, case: dict) -> tuple[list[dict], list[dict], list[dict]]:
    units = [copy.deepcopy(fixture["unit_catalog"][index]) for index in case["unit_indexes"]]
    if case.get("cycle"):
        units[0]["prerequisite_unit_refs"] = [{
            "id": "10000000-0000-4000-8000-000000000002",
            "revision": 1,
        }]
    return units, case["available_node_refs"], case["evidence_node_refs"]


class KnowledgeUnitProjectDifferentialTests(unittest.TestCase):
    def test_python_and_typescript_match_each_project_fixture_field(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        python = {}
        for case in fixture["cases"]:
            units, available, evidence = load_inputs(fixture, case)
            python[case["case_id"]] = project_knowledge(units, available, evidence, CONTRACT_ROOT)

        node = shutil.which("node")
        self.assertIsNotNone(node)
        script = """
import { readFileSync } from "node:fs";
import { projectKnowledge } from %s;
const fixture = JSON.parse(readFileSync(%s, "utf8"));
const contractRoot = %s;
const results = {};
for (const candidate of fixture.cases) {
  const units = candidate.unit_indexes.map((index) => structuredClone(fixture.unit_catalog[index]));
  if (candidate.cycle) units[0].prerequisite_unit_refs = [{ id: "10000000-0000-4000-8000-000000000002", revision: 1 }];
  results[candidate.case_id] = projectKnowledge(units, candidate.available_node_refs, candidate.evidence_node_refs, contractRoot);
}
console.log(JSON.stringify(results));
""" % (json.dumps(TS_MODULE_PATH.as_uri()), json.dumps(str(FIXTURE_PATH)), json.dumps(str(CONTRACT_ROOT)))
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"COMSPEC", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
        }
        completed = subprocess.run(
            [str(node), "--input-type=module", "--eval", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
            env=environment,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout), python)


if __name__ == "__main__":
    unittest.main(verbosity=2)
