from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_agent_runtime.runtime import (  # noqa: E402
    execute_fixture_suite,
    parse_and_validate_transport,
    validate_references,
    validate_revision_transition,
)

CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "agent-profile" / "1.0.0"

def suite() -> dict:
    return json.loads((CONTRACT_ROOT / "fixtures" / "cases.json").read_text(encoding="utf-8"))

def profile() -> dict:
    return copy.deepcopy(next(case for case in suite()["cases"] if case["case_id"] == "valid-algebra-mentor")["input"]["profile"])

class AgentProfilePythonRuntimeTests(unittest.TestCase):
    def test_executes_every_locked_case_without_replaying_expected(self) -> None:
        results = execute_fixture_suite(CONTRACT_ROOT)
        self.assertEqual(len(results), 35)
        self.assertTrue(all(item["actual"] == item["expected"] for item in results))

    def test_raw_transport_is_strict_and_not_fixture_driven(self) -> None:
        expected = next(case for case in suite()["cases"] if case["case_id"] == "valid-algebra-mentor")["expected"]
        raw = json.dumps(profile(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        expected["mode"] = "transport"
        self.assertEqual(parse_and_validate_transport(raw, CONTRACT_ROOT), expected)
        for malformed in (b'\xef\xbb\xbf{}', b'{"id":1,"id":2}', b'{"x":"\xed\xa0\x80"}'):
            with self.subTest(raw=malformed):
                self.assertEqual(parse_and_validate_transport(malformed, CONTRACT_ROOT)["issues"][0]["code"], "agent_profile.invalid_json")

    def test_reference_closure_distinguishes_invalid_and_indeterminate(self) -> None:
        cases = {item["case_id"]: item for item in suite()["cases"]}
        dangling = cases["dangling-provenance"]["input"]
        opaque = cases["compatible-provenance"]["input"]
        self.assertEqual(validate_references(dangling["profile"], dangling["snapshot"], CONTRACT_ROOT), cases["dangling-provenance"]["expected"])
        self.assertEqual(validate_references(opaque["profile"], opaque["snapshot"], CONTRACT_ROOT), cases["compatible-provenance"]["expected"])

    def test_revision_transition_requires_identity_growth_and_content_change(self) -> None:
        previous = profile()
        same = copy.deepcopy(previous)
        same["revision"] = 2
        changed = copy.deepcopy(same)
        changed["display_name"] = "Changed identity description"
        self.assertEqual(validate_revision_transition(previous, same, CONTRACT_ROOT)["issues"][0]["code"], "agent_profile.revision_without_change")
        self.assertEqual(validate_revision_transition(previous, changed, CONTRACT_ROOT)["object_result"], "valid")

if __name__ == "__main__":
    unittest.main(verbosity=2)