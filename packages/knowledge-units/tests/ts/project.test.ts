import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { projectKnowledge } from "../../src/knowledge-unit/project.ts";


const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const contractRoot = resolve(packageRoot, "contracts/knowledge-unit/1.0.0");
const fixturePath = resolve(packageRoot, "tests/fixtures/project-projection-cases.json");
const prerequisiteRef = { id: "10000000-0000-4000-8000-000000000001", revision: 1 };
const dependentRef = { id: "10000000-0000-4000-8000-000000000002", revision: 1 };
const evidenceRef = { id: "20000000-0000-4000-8000-000000000002", revision: 1 };


function loadCase(caseId: string) {
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
  const candidate = fixture.cases.find((item: any) => item.case_id === caseId);
  const units = candidate.unit_indexes.map((index: number) => structuredClone(fixture.unit_catalog[index]));
  if (candidate.cycle) units[0].prerequisite_unit_refs = [structuredClone(dependentRef)];
  return { units, available: candidate.available_node_refs, evidence: candidate.evidence_node_refs };
}


function projectCase(caseId: string) {
  const { units, available, evidence } = loadCase(caseId);
  return projectKnowledge(units, available, evidence, contractRoot);
}


test("empty evidence marks the dependent unit as needs_evidence", () => {
  const result = projectCase("empty-evidence");

  assert.equal(result.object_result, "valid");
  assert.equal(result.operation_outcome, "succeeded");
  assert.deepEqual(result.issues, []);
  assert.deepEqual(result.units[1], {
    unit_ref: dependentRef,
    status: "needs_evidence",
    missing_prerequisite_unit_refs: [],
  });
});


test("missing prerequisite blocks the dependent unit and lists its ref", () => {
  const result = projectCase("missing-prerequisite");

  assert.deepEqual(result.units, [{
    unit_ref: dependentRef,
    status: "blocked",
    missing_prerequisite_unit_refs: [prerequisiteRef],
  }]);
});


test("evidence node reports the two direct unit dependents", () => {
  const result = projectCase("full-evidence");

  const entry = result.node_dependents.find((item: any) => item.node_ref.id === evidenceRef.id);
  assert.deepEqual(entry, {
    node_ref: evidenceRef,
    unit_refs: [prerequisiteRef, dependentRef],
  });
});


test("prerequisite ref reports transitive reverse unit dependents", () => {
  const result = projectCase("full-evidence");

  const entry = result.unit_dependents.find((item: any) => item.unit_ref.id === prerequisiteRef.id);
  assert.deepEqual(entry, {
    unit_ref: prerequisiteRef,
    dependent_unit_refs: [dependentRef],
  });
});


test("prerequisite cycle is invalid", () => {
  const result = projectCase("prerequisite-cycle");

  assert.equal(result.object_result, "invalid");
  assert.deepEqual(result.issues, [{
    code: "knowledge_project.prerequisite_cycle",
    path: "/units",
    severity: "error",
  }]);
});


test("duplicate unit ref is invalid", () => {
  const { units, available, evidence } = loadCase("full-evidence");
  const result = projectKnowledge([...units, structuredClone(units[1])], available, evidence, contractRoot);

  assert.equal(result.object_result, "invalid");
  assert.deepEqual(result.issues, [{
    code: "knowledge_project.duplicate_unit_ref",
    path: "/units/2",
    severity: "error",
  }]);
});
