from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT / "python") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "python"))

from intelliengine_thoughtflow.runtime import graph_summary, next_candidates, validate_references, validate_revision_transition
from intelliengine_thoughtflow.validation import materialize, validate_graph


def safe_fixture(root: Path, relative: str) -> Path:
    if "\\" in relative:
        raise ValueError("backslash is forbidden")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe fixture path")
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root.joinpath(*path.parts).resolve(strict=True)
    candidate.relative_to(resolved_root)
    return candidate


def projection(root: Path, fixture_path: str) -> dict:
    suite = json.loads(safe_fixture(root, fixture_path).read_text(encoding="utf-8"))
    fixtures = []
    for case in suite["cases"]:
        value = materialize(case, suite)
        summary = None
        queries = []
        if value["mode"] == "revision":
            actual = validate_revision_transition(value["previous"], value["candidate"])
        else:
            actual = validate_graph(value["flow"])
            if actual["object_result"] == "valid" and value["mode"] == "reference":
                actual = validate_references(value["flow"], value["snapshot"])
            if actual["object_result"] == "valid":
                summary = graph_summary(value["flow"])
                queries = [{"step_id": step["step_id"], "result": next_candidates(value["flow"], step["step_id"])} for step in value["flow"]["steps"]]
        fixtures.append({"case_id": case["case_id"], "actual": actual, "summary": summary, "queries": queries})
    return {"contract_version": suite["contract_version"], "fixtures": fixtures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--fixture-path", default="fixtures/cases.json")
    args = parser.parse_args()
    print(json.dumps(projection(args.contract_root, args.fixture_path), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
