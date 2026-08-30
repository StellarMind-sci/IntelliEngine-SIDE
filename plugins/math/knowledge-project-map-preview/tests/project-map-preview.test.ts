import assert from "node:assert/strict";
import test from "node:test";

import {
  createKnowledgeProjectMapPreview,
  validProjectionForDemo,
} from "../project-map-preview.ts";

const equalityUnit = { id: "10000000-0000-4000-8000-000000000001", revision: 1 };
const equationUnit = { id: "10000000-0000-4000-8000-000000000002", revision: 1 };
const equalityEvidenceNode = { id: "20000000-0000-4000-8000-000000000002", revision: 1 };
const equationEvidenceNode = { id: "20000000-0000-4000-8000-000000000004", revision: 1 };
const unrelatedNode = { id: "20000000-0000-4000-8000-000000000005", revision: 1 };

test("normal fixed math project projects two units, their prerequisite edge, evidence gap, and selected node dependents", () => {
  const result = createKnowledgeProjectMapPreview({ case: "normal", selected_node_ref: equationEvidenceNode });

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "valid",
    units: [
      { ref: equalityUnit, status: "ready", missing_prerequisite_refs: [], missing_evidence_node_refs: [] },
      { ref: equationUnit, status: "needs_evidence", missing_prerequisite_refs: [], missing_evidence_node_refs: [equationEvidenceNode] },
    ],
    prerequisite_edges: [{ prerequisite_unit_ref: equalityUnit, dependent_unit_ref: equationUnit }],
    selected_node_ref: equationEvidenceNode,
    affected_unit_refs: [equationUnit],
    diagnostic: "固定线性方程工程图谱已投影；状态来自 KnowledgeUnit 投影，不表示个人掌握或工程完成。",
  });
});

test("blocked fixed math project reports a real external prerequisite and selected node impact", () => {
  const result = createKnowledgeProjectMapPreview({ case: "blocked", selected_node_ref: equationEvidenceNode });

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "valid",
    units: [{
      ref: equationUnit,
      status: "blocked",
      missing_prerequisite_refs: [equalityUnit],
      missing_evidence_node_refs: [],
    }],
    prerequisite_edges: [],
    selected_node_ref: equationEvidenceNode,
    affected_unit_refs: [equationUnit],
    diagnostic: "固定线性方程工程图谱包含缺失的外部先修 KnowledgeUnit。",
  });
});

test("empty keeps a valid fixed graph but does not fabricate reverse impact for an existing unrelated node", () => {
  const result = createKnowledgeProjectMapPreview({ case: "empty", selected_node_ref: unrelatedNode });

  assert.equal(result.state, "empty");
  assert.deepEqual(result.selected_node_ref, unrelatedNode);
  assert.deepEqual(result.affected_unit_refs, []);
  assert.equal(result.diagnostic, "所选 CognitiveNode 不在固定工程图谱的反向影响中；不伪造受影响的 KnowledgeUnit。 ".trim());
  assert.equal(result.units.length, 2);
});

test("invalid and noncanonical requests fail closed without units, edges, or impacts", () => {
  const malformed = { case: "normal", selected_node_ref: equationEvidenceNode, ignored: true };
  const result = createKnowledgeProjectMapPreview(malformed);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    units: [],
    prerequisite_edges: [],
    selected_node_ref: null,
    affected_unit_refs: [],
    diagnostic: "请求必须是固定案例与可选的现有 CognitiveNode plain data。",
  });
});

test("inherited fields, accessors, symbols, and hostile proxies fail closed without throwing", () => {
  const inherited = Object.create({ case: "normal" });
  const accessor = Object.defineProperty({}, "case", { enumerable: true, get() { throw new Error("no getter"); } });
  const symbol = { case: "normal", [Symbol("extra")]: true };
  const hostile = new Proxy({}, { ownKeys() { throw new Error("no proxy"); } });

  for (const input of [inherited, accessor, symbol, hostile]) {
    const result = createKnowledgeProjectMapPreview(input);
    assert.equal(result.state, "invalid_input");
    assert.deepEqual(result.units, []);
    assert.deepEqual(result.affected_unit_refs, []);
  }
});

test("the request is not mutated and normal output is deterministically sorted", () => {
  const request = { case: "normal" as const, selected_node_ref: { ...equationEvidenceNode } };
  const before = structuredClone(request);
  const first = createKnowledgeProjectMapPreview(request);
  const second = createKnowledgeProjectMapPreview(request);

  assert.deepEqual(request, before);
  assert.deepEqual(first, second);
  assert.deepEqual(first.units.map((unit) => unit.ref), [equalityUnit, equationUnit]);
});

test("a projection-like result with altered units, node dependents, or closure cannot pass the fixed-demo verification gate", () => {
  const result = createKnowledgeProjectMapPreview({ case: "normal", selected_node_ref: equationEvidenceNode });
  const candidate = {
    object_result: "valid",
    operation_outcome: "succeeded",
    issues: [],
    units: structuredClone(result.units),
    node_dependents: [{ node_ref: equationEvidenceNode, unit_refs: [equalityUnit] }],
    unit_dependents: [{ unit_ref: equalityUnit, dependent_unit_refs: [] }, { unit_ref: equationUnit, dependent_unit_refs: [] }],
  };

  assert.equal(validProjectionForDemo("normal", candidate), false);
});