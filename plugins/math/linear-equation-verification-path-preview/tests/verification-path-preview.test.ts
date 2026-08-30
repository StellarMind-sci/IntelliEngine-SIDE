import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  createLinearEquationVerificationPathPreview,
  validEmptyNavigatorResult,
  validVerificationNavigatorResult,
} from "../verification-path-preview.ts";
import { fixedKnowledgeUnitContractRoot } from "../../knowledge-unit-assembly-preview/assembly.ts";
import { projectKnowledge } from "../../../../packages/knowledge-units/src/knowledge-unit/project.ts";
import { createKnowledgeImpactNavigator } from "../../knowledge-impact-navigator/navigator.ts";

const cases = JSON.parse(readFileSync(new URL("../fixtures/demo-cases.json", import.meta.url), "utf8")) as Record<string, unknown>;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function assertNoDraft(result: ReturnType<typeof createLinearEquationVerificationPathPreview>) {
  assert.equal(result.knowledge_unit_ref, null);
  assert.equal(result.flow_context, null);
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.missing_evidence_node_refs, []);
}

test("bridges a valid equation through the real intake, assembly, projection, and verification navigator", () => {
  const input = clone(cases.verification);
  const before = clone(input);
  const first = createLinearEquationVerificationPathPreview(input);
  const second = createLinearEquationVerificationPathPreview(input);

  assert.deepEqual(first, second);
  assert.equal(first.mode, "preview");
  assert.equal(first.side_effects, "forbidden");
  assert.equal(first.state, "needs_evidence");
  assert.equal(first.source_ref, "prov:source:algebra-example-1");
  assert.equal(first.assembly?.state, "needs_evidence");
  assert.equal(first.assembly?.knowledge_unit?.title, "解一元一次方程：2*x + 3 = 11");
  assert.deepEqual(first.flow_context, {
    persistence: "not_persisted",
    steps: [{
      step_id: "verification-linear-equation",
      kind: "verification",
      knowledge_unit_refs: [first.knowledge_unit_ref],
    }],
  });
  assert.equal(first.navigation, "返回 verification 步骤补充缺失证据。");
  assert.deepEqual(first.impacted_steps.map((step) => step.step_id), ["verification-linear-equation"]);
  assert.equal(first.missing_evidence_node_refs.length, 1);
  assert.equal(first.diagnostic, null);
  assert.deepEqual(input, before);
});

test("keeps a valid unmapped knowledge unit in preview without inventing a verification destination", () => {
  const input = clone(cases.unmapped);
  const before = clone(input);
  const result = createLinearEquationVerificationPathPreview(input);

  assert.equal(result.state, "empty");
  assert.notEqual(result.knowledge_unit_ref, null);
  assert.deepEqual(result.flow_context, { persistence: "not_persisted", steps: [] });
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.equal(result.diagnostic, "当前预览工程上下文没有关联 verification 步骤；不伪造下一步。");
  assert.deepEqual(input, before);
});

test("does not leak a draft, flow, navigation, or impact for empty or invalid upstream input", () => {
  for (const name of ["empty", "invalid"] as const) {
    const input = clone(cases[name]);
    const before = clone(input);
    const result = createLinearEquationVerificationPathPreview(input);

    assert.equal(result.state, name === "empty" ? "empty" : "invalid_input");
    assertNoDraft(result);
    assert.deepEqual(input, before);
  }
});

test("fails closed without mutation for unexpected, inherited, accessor, symbol, or proxy input", () => {
  const valid = clone(cases.verification) as { source: { text: string; source_ref: string }; flow_context: "verification" };
  const inherited = Object.create({ unexpected: true }) as typeof valid;
  inherited.source = clone(valid.source);
  inherited.flow_context = "verification";
  const accessor = {} as typeof valid;
  Object.defineProperty(accessor, "source", { enumerable: true, get() { throw new Error("getter must not escape"); } });
  Object.defineProperty(accessor, "flow_context", { enumerable: true, value: "verification" });
  const symbol = { ...valid, [Symbol("unexpected")]: true };
  const proxy = new Proxy(valid, { ownKeys() { throw new Error("ownKeys must not escape"); } });
  const casesToReject: unknown[] = [
    { ...valid, unexpected: true },
    inherited,
    accessor,
    symbol,
    proxy,
    { source: { ...valid.source, extra: true }, flow_context: "verification" },
    { source: valid.source, flow_context: "analysis" },
    null,
  ];

  for (const input of casesToReject) {
    const before = input === proxy || input === accessor || input === symbol ? null : structuredClone(input);
    const result = createLinearEquationVerificationPathPreview(input);
    assert.equal(result.state, "invalid_input");
    assertNoDraft(result);
    if (before !== null) assert.deepEqual(input, before);
    if (input === symbol) assert.equal(symbol[Object.getOwnPropertySymbols(symbol)[0]!], true);
  }
});

function realVerificationNavigator() {
  const bridge = createLinearEquationVerificationPathPreview(clone(cases.verification));
  assert.equal(bridge.state, "needs_evidence");
  assert.notEqual(bridge.assembly?.knowledge_unit, null);
  assert.notEqual(bridge.knowledge_unit_ref, null);
  assert.notEqual(bridge.flow_context, null);
  const assembly = bridge.assembly!;
  const focus = bridge.knowledge_unit_ref!;
  const projection = projectKnowledge(
    [assembly.knowledge_unit],
    assembly.candidate_nodes.map(({ id, revision }) => ({ id, revision })),
    [],
    fixedKnowledgeUnitContractRoot(),
  );
  const missingEvidence = projection.units[0].missing_evidence_node_refs;
  const navigator = createKnowledgeImpactNavigator({ flow: bridge.flow_context, projection, focus_ref: focus });
  return { focus, projection, missingEvidence, navigator };
}

test("accepts only the complete real verification navigator result tied to the projected KnowledgeUnit", () => {
  const { focus, projection, missingEvidence, navigator } = realVerificationNavigator();

  assert.equal(projection.object_result, "valid");
  assert.equal(projection.operation_outcome, "succeeded");
  assert.equal(projection.units[0].status, "needs_evidence");
  assert.equal(validVerificationNavigatorResult(navigator, focus, missingEvidence), true);
  assert.deepEqual(navigator.focus, focus);
  assert.deepEqual(navigator.reasons, [{
    knowledge_unit_ref: focus,
    status: "needs_evidence",
    missing_prerequisite_refs: [],
    missing_evidence_node_refs: missingEvidence,
  }]);
  assert.deepEqual(navigator.impacted_steps, [{
    step_id: "verification-linear-equation",
    reasons: navigator.reasons,
  }]);
});

test("closes the verification navigator gate when focus, reason, impact, or preview envelope is malformed", () => {
  const { focus, missingEvidence, navigator } = realVerificationNavigator();
  const mutations: Array<(value: any) => void> = [
    (value) => { value.mode = "live"; },
    (value) => { value.side_effects = "allowed"; },
    (value) => { value.focus.revision = 2; },
    (value) => { value.reasons[0].status = "ready"; },
    (value) => { value.reasons[0].missing_prerequisite_refs = [focus]; },
    (value) => { value.reasons[0].missing_evidence_node_refs = []; },
    (value) => { value.impacted_steps[0].step_id = "analysis-linear-equation"; },
    (value) => { value.impacted_steps[0].reasons = []; },
    (value) => { value.navigation = "返回 analysis 步骤。"; },
  ];

  for (const mutate of mutations) {
    const malformed = structuredClone(navigator);
    mutate(malformed);
    assert.equal(validVerificationNavigatorResult(malformed, focus, missingEvidence), false);
  }
});

test("accepts only a complete empty navigator result for the unmapped preview context", () => {
  const bridge = createLinearEquationVerificationPathPreview(clone(cases.unmapped));
  assert.equal(bridge.state, "empty");
  const assembly = bridge.assembly!;
  const focus = bridge.knowledge_unit_ref!;
  const projection = projectKnowledge(
    [assembly.knowledge_unit],
    assembly.candidate_nodes.map(({ id, revision }) => ({ id, revision })),
    [],
    fixedKnowledgeUnitContractRoot(),
  );
  const navigator = createKnowledgeImpactNavigator({ flow: bridge.flow_context, projection, focus_ref: focus });

  assert.equal(validEmptyNavigatorResult(navigator, focus), true);
  const malformed = structuredClone(navigator);
  malformed.reasons = [{
    knowledge_unit_ref: focus,
    status: "needs_evidence",
    missing_prerequisite_refs: [],
    missing_evidence_node_refs: [],
  }];
  assert.equal(validEmptyNavigatorResult(malformed, focus), false);
});
