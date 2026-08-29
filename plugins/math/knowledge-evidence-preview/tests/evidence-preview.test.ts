import assert from "node:assert/strict";
import test from "node:test";

import { createKnowledgeEvidencePreview, fixedKnowledgeUnitContractRoot } from "../navigator.ts";

const refs = {
  concept: { id: "20000000-0000-4000-8000-000000000001", revision: 1 },
  evidence: { id: "20000000-0000-4000-8000-000000000002", revision: 1 },
  target: { id: "20000000-0000-4000-8000-000000000003", revision: 1 },
  prerequisite: { id: "10000000-0000-4000-8000-000000000001", revision: 1 },
};

const unit = {
  contract_version: "1.0.0",
  id: "10000000-0000-4000-8000-000000000002",
  revision: 1,
  title: "resolve-linear-equation",
  concept_boundary: { focus_node_refs: [refs.target], out_of_scope_statements: ["quadratic-equations"] },
  learning_objectives: [{ objective_id: "resolve-linear", statement: "Resolve a linear equation.", target_node_refs: [refs.target] }],
  node_bindings: [{ role: "core", node_ref: refs.target }, { role: "evidence", node_ref: refs.evidence }],
  prerequisite_unit_refs: [refs.prerequisite],
  behaviors: [{ behavior_id: "resolve", kind: "calculation", capability: "runtime.math.symbolic", input_node_refs: [refs.target], output_node_refs: [refs.target] }],
  validations: [{ validation_id: "check-resolution", description: "Verify a resolved equation.", subject_node_refs: [refs.target], evidence_node_refs: [refs.evidence] }],
  mastery_criteria: [{ criterion_id: "show-resolution", statement: "Provide evidence for resolution.", evidence_node_refs: [refs.evidence] }],
  provenance_refs: ["source:algebra:linear"],
};

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }

function request(overrides: Record<string, unknown> = {}) {
  return {
    unit: clone(unit),
    available_node_refs: [clone(refs.concept), clone(refs.evidence), clone(refs.target)],
    evidence_node_refs: [],
    flow: { steps: [{ step_id: "analysis-linear", kind: "analysis", knowledge_unit_refs: [{ id: unit.id, revision: unit.revision }] }] },
    focus_ref: { id: unit.id, revision: unit.revision },
    contract_root: fixedKnowledgeUnitContractRoot(),
    ...overrides,
  };
}

test("uses validateUnit and projectKnowledge to describe a blocked unit without mutating input", () => {
  const value = request();
  const before = clone(value);
  const result = createKnowledgeEvidencePreview(value);

  assert.equal(result.state, "blocked");
  assert.equal(result.navigation, "先完成缺失前置知识，再继续查看验证要求。");
  assert.deepEqual(result.verification_steps, []);
  assert.deepEqual(result.validations, [{
    validation_id: "check-resolution",
    description: "Verify a resolved equation.",
    evidence_node_refs: [refs.evidence],
    missing_evidence_node_refs: [refs.evidence],
    status: "missing",
  }]);
  assert.equal(result.mastery_criteria[0].status, "missing");
  assert.deepEqual(value, before);
});

test("navigates needs-evidence only to direct verification Thoughtflow steps", () => {
  const value = request({
    unit: { ...clone(unit), prerequisite_unit_refs: [] },
    flow: { steps: [
      { step_id: "analysis-not-verification", kind: "analysis", knowledge_unit_refs: [{ id: unit.id, revision: unit.revision }] },
      { step_id: "verification-linear", kind: "verification", knowledge_unit_refs: [{ id: unit.id, revision: unit.revision }] },
      { step_id: "verification-other", kind: "verification", knowledge_unit_refs: [refs.prerequisite] },
    ] },
  });
  const result = createKnowledgeEvidencePreview(value);

  assert.equal(result.state, "needs_evidence");
  assert.equal(result.navigation, "返回 verification 步骤补充缺失工程证据。");
  assert.deepEqual(result.verification_steps, ["verification-linear"]);
  assert.equal(result.validations[0].status, "missing");
});

test("returns ready when all evidence is present, even without verification steps", () => {
  const value = request({
    unit: { ...clone(unit), prerequisite_unit_refs: [] },
    evidence_node_refs: [clone(refs.evidence)],
    flow: { steps: [] },
  });
  const result = createKnowledgeEvidencePreview(value);

  assert.equal(result.state, "ready");
  assert.equal(result.navigation, null);
  assert.deepEqual(result.verification_steps, []);
  assert.equal(result.validations[0].status, "satisfied");
  assert.equal(result.mastery_criteria[0].status, "satisfied");
});

test("returns empty when blocked or needs-evidence has no safe direct step category", () => {
  const blocked = createKnowledgeEvidencePreview(request({ flow: { steps: [] } }));
  const evidence = createKnowledgeEvidencePreview(request({
    unit: { ...clone(unit), prerequisite_unit_refs: [] },
    flow: { steps: [{ step_id: "analysis-only", kind: "analysis", knowledge_unit_refs: [{ id: unit.id, revision: unit.revision }] }] },
  }));

  assert.equal(blocked.state, "empty");
  assert.deepEqual(blocked.focus, { id: unit.id, revision: 1 });
  assert.equal(blocked.navigation, null);
  assert.equal(evidence.state, "empty");
  assert.equal(evidence.navigation, null);
  assert.deepEqual(evidence.verification_steps, []);
});

test("fails closed for noncanonical, contradictory, or identity-mismatched input", () => {
  const noncanonical = request({ available_node_refs: [clone(refs.evidence), clone(refs.concept), clone(refs.target)] });
  const mismatch = request({ focus_ref: refs.prerequisite });
  const extra = request({ unexpected: true });
  const unsafeRoot = request({ contract_root: "C:\\untrusted-contract-root" });
  const noncanonicalFlow = request({ flow: { steps: [{ step_id: "duplicate-ref", kind: "analysis", knowledge_unit_refs: [{ id: unit.id, revision: 1 }, { id: unit.id, revision: 1 }] }] } });

  for (const value of [noncanonical, mismatch, extra, unsafeRoot, noncanonicalFlow]) {
    assert.deepEqual(createKnowledgeEvidencePreview(value), {
      mode: "preview", side_effects: "forbidden", state: "invalid_input", focus: null,
      navigation: null, validations: [], mastery_criteria: [], verification_steps: [],
    });
  }
});
