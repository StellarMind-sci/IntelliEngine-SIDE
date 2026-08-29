from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_thoughtflow.knowledge_impact import project_knowledge_impacts


CASES_PATH = PACKAGE_ROOT / "tests" / "fixtures" / "knowledge-impact-cases.json"
TS_MODULE = PACKAGE_ROOT / "src" / "thoughtflow" / "knowledge-impact.ts"
TS_RUNNER = """import { readFileSync } from 'node:fs'; import { pathToFileURL } from 'node:url'; const { projectKnowledgeImpacts } = await import(pathToFileURL(process.argv[1]).href); const cases = JSON.parse(readFileSync(0, 'utf8')).cases; process.stdout.write(JSON.stringify(cases.map((item) => ({case_id: item.case_id, actual: projectKnowledgeImpacts(item.flow, item.projection)}))));"""


class KnowledgeImpactDifferentialTests(unittest.TestCase):
    def test_python_and_typescript_match_each_fixture_field_for_field(self) -> None:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
        python_result = [{"case_id": case["case_id"], "actual": project_knowledge_impacts(case["flow"], case["projection"])} for case in cases]
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", TS_RUNNER, str(TS_MODULE)],
            input=json.dumps({"cases": cases}), text=True, capture_output=True, check=True,
        )
        self.assertEqual(python_result, json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main(verbosity=2)