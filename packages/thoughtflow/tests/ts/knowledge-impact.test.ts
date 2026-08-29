import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { projectKnowledgeImpacts } from "../../src/thoughtflow/knowledge-impact.ts";

const cases = JSON.parse(readFileSync(new URL("../fixtures/knowledge-impact-cases.json", import.meta.url), "utf8")).cases;

test("projects every hand-authored knowledge impact case", () => {
  for (const caseValue of cases) {
    assert.deepEqual(projectKnowledgeImpacts(caseValue.flow, caseValue.projection), caseValue.expected, caseValue.case_id);
  }
});

test("leaves inputs untouched and never reports execution or selection", () => {
  const caseValue = structuredClone(cases[0]);
  const flow = structuredClone(caseValue.flow), projection = structuredClone(caseValue.projection);
  const result = projectKnowledgeImpacts(flow, projection);
  assert.deepEqual(flow, caseValue.flow);
  assert.deepEqual(projection, caseValue.projection);
  for (const field of ["executed_operations", "selected_branch", "branch_selection", "mastery", "write"]) assert.equal(field in result, false);
});