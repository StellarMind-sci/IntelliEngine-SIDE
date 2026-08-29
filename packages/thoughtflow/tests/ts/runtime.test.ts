import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { canonicalize } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";
import {
  executeFixtureSuite,
  graphSummary,
  nextCandidates,
  parseAndValidateTransport,
  simulateBounded,
  validateReferences,
  validateRevisionTransition,
} from "../../src/thoughtflow/runtime.ts";

const root = new URL("../../contracts/thoughtflow/1.0.0/", import.meta.url);
const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", root), "utf8"));
const runtimeCases = JSON.parse(readFileSync(new URL("../fixtures/runtime-cases.json", import.meta.url), "utf8"));
const validFlow = () => structuredClone(suite.cases[0].input.flow);
const validSnapshot = () => structuredClone(suite.cases[0].input.snapshot);

function renameStep(flow: any, previous: string, next: string) {
  for (const step of flow.steps) {
    if (step.step_id === previous) step.step_id = next;
    if (step.kind === "iteration") step.verification_step_ids = step.verification_step_ids.map((id: string) => id === previous ? next : id);
  }
  if (flow.entry_step_id === previous) flow.entry_step_id = next;
  for (const transition of flow.transitions) {
    if (transition.from_step_id === previous) transition.from_step_id = next;
    if (transition.to_step_id === previous) transition.to_step_id = next;
  }
}

const transitionTuple = (item: any) => [item.from_step_id, item.kind, item.branch_label ?? item.outcome ?? "", item.to_step_id, item.transition_id];
function compareTuple(left: any, right: any) {
  const a = transitionTuple(left), b = transitionTuple(right);
  for (let index = 0; index < a.length; index++) {
    const compared = Buffer.compare(Buffer.from(a[index]), Buffer.from(b[index]));
    if (compared !== 0) return compared;
  }
  return 0;
}

function collisionFlow() {
  const flow = validFlow(), collision = runtimeCases.nul_tuple_collision;
  renameStep(flow, "s04-operation", collision.target_step_ids[0]);
  renameStep(flow, "s07-success", collision.target_step_ids[1]);
  flow.steps.sort((left: any, right: any) => Buffer.compare(Buffer.from(left.step_id), Buffer.from(right.step_id)));
  flow.transitions.push(...structuredClone(collision.transitions));
  flow.transitions.sort(compareTuple);
  return flow;
}

function sizedFlow(targetBytes: number) {
  const ref = { id: "018f0c20-7a8b-7c1d-8a2e-333333333333", revision: 1 }, steps: any[] = [];
  steps.push({ step_id: "s0000", kind: "goal", title: "g", description: "x", knowledge_unit_refs: [], cognitive_node_refs: [], success_statement: "done" });
  for (let index = 1; index <= 600; index++) steps.push({ step_id: `s${String(index).padStart(4, "0")}`, kind: "analysis", title: "a", description: "x", knowledge_unit_refs: [], cognitive_node_refs: [] });
  steps.push({ step_id: "s0601", kind: "verification", title: "v", description: "x", knowledge_unit_refs: [], cognitive_node_refs: [ref], acceptance_statement: "ok", evidence_node_refs: [ref] });
  steps.push({ step_id: "s0602", kind: "goal", title: "z", description: "x", knowledge_unit_refs: [], cognitive_node_refs: [], success_statement: "done" });
  const transitions: any[] = [];
  for (let index = 0; index < 601; index++) transitions.push({ transition_id: `t${String(index).padStart(4, "0")}`, kind: "sequence", from_step_id: `s${String(index).padStart(4, "0")}`, to_step_id: `s${String(index + 1).padStart(4, "0")}` });
  transitions.push({ transition_id: "t0601", kind: "verification_feedback", from_step_id: "s0601", to_step_id: "s0602", outcome: "passed" });
  const flow: any = { contract_version: "1.0.0", id: "018f0c20-7a8b-7c1d-8a2e-111111111111", revision: 1, title: "sized", entry_step_id: "s0000", steps, transitions, knowledge_unit_refs: [], cognitive_node_refs: [ref], provenance_refs: ["p"] };
  let remaining = targetBytes - Buffer.byteLength(canonicalize(flow), "utf8");
  assert.ok(remaining >= 0);
  for (const step of steps) { const added = Math.min(8191, remaining); step.description += "x".repeat(added); remaining -= added; }
  assert.equal(remaining, 0);
  assert.equal(Buffer.byteLength(canonicalize(flow), "utf8"), targetBytes);
  return flow;
}

test("executes all machine fixtures without replaying expected", () => {
  const results = executeFixtureSuite(root);
  assert.equal(results.length, 18);
  assert.ok(results.every((item) => JSON.stringify(item.actual) === JSON.stringify(item.expected)));
});

test("rejects available knowledge unit with mismatched document identity", () => {
  const snapshot = validSnapshot();
  snapshot.knowledge_units[0].document.id = "018f0c20-7a8b-7c1d-8a2e-666666666666";

  const result = validateReferences(validFlow(), snapshot);

  assert.equal(result.object_result, "invalid");
  assert.equal(result.issues[0].code, "thoughtflow.dangling_reference");
  assert.equal(result.issues[0].path, "/knowledge_unit_refs/0");
});

test("raw transport rejects duplicate members", () => {
  const result = parseAndValidateTransport(Buffer.from('{"contract_version":"1.0.0","contract_version":"1.0.0"}'));
  assert.equal(result.issues[0].code, "thoughtflow.invalid_json");
});

test("raw transport enforces locked schema and size boundary", () => {
  const extra = validFlow();
  extra.unknown = true;
  const missing = validFlow();
  delete missing.title;
  for (const flow of [extra, missing]) {
    const result = parseAndValidateTransport(Buffer.from(JSON.stringify(flow)));
    assert.equal(result.object_result, "invalid");
    assert.equal(result.issues[0].code, "thoughtflow.invalid_json");
  }
  assert.equal(parseAndValidateTransport(Buffer.from(JSON.stringify(sizedFlow(4194303)))).object_result, "valid");
  assert.equal(parseAndValidateTransport(Buffer.from(JSON.stringify(sizedFlow(4194304)))).object_result, "valid");
  assert.equal(parseAndValidateTransport(Buffer.from(JSON.stringify(sizedFlow(4194305)))).object_result, "invalid");
});

test("future same-major minor is compatible read and cannot drive control", () => {
  const flow = validFlow();
  flow.contract_version = "1.1.0";
  const compatibleResult = {
    object_result: "not_evaluated", operation_outcome: "indeterminate",
    issues: [{ code: "thoughtflow.unsupported_contract_version", path: "/contract_version", severity: "error" }],
  };
  assert.deepEqual(parseAndValidateTransport(Buffer.from(JSON.stringify(flow))), compatibleResult);
  const longVersion = validFlow();
  longVersion.contract_version = `1.${"9".repeat(5000)}.0`;
  assert.deepEqual(parseAndValidateTransport(Buffer.from(JSON.stringify(longVersion))), compatibleResult);
  assert.equal(nextCandidates(flow, "s03-iteration").status, "compatible_read");
  assert.equal(simulateBounded(flow, { observations: {}, branchSelections: {}, maxSteps: 10 }).status, "compatible_read");
  const candidate = structuredClone(flow);
  candidate.revision = 2;
  candidate.title = "future mutation";
  assert.equal(validateRevisionTransition(flow, candidate).object_result, "not_evaluated");
});

test("transition tuple comparison cannot collide across NUL field boundaries", () => {
  assert.equal(parseAndValidateTransport(Buffer.from(JSON.stringify(collisionFlow()))).object_result, "valid");
});

test("graph summary is deterministic", () => {
  assert.deepEqual(graphSummary(validFlow()), {
    entry_step_id: "s01-goal",
    step_count: 7,
    transition_count: 8,
    step_kinds: { analysis: 1, artifact: 1, goal: 2, iteration: 1, operation: 1, verification: 1 },
    loop_controllers: [{ max_iterations: 3, step_id: "s03-iteration" }],
    reachable_step_count: 7,
    reachable_step_ids: ["s01-goal", "s02-analysis", "s03-iteration", "s04-operation", "s05-artifact", "s06-verification", "s07-success"],
  });
});

test("iteration requires explicit branch selection", () => {
  const result = nextCandidates(validFlow(), "s03-iteration");
  assert.equal(result.status, "requires_selection");
  assert.deepEqual(result.candidates.map((item) => item.branch_label), ["retry", "stop"]);
});

test("verification outcome selects explicit feedback", () => {
  assert.deepEqual(nextCandidates(validFlow(), "s06-verification", { observedOutcome: "failed" }), {
    status: "ready",
    candidates: [{ kind: "loop", outcome: "failed", to_step_id: "s03-iteration", transition_id: "t08" }],
  });
});

test("simulation stops at declared iteration limit", () => {
  const result = simulateBounded(validFlow(), {
    observations: { "s06-verification": ["failed", "failed", "failed", "failed"] },
    branchSelections: { "s03-iteration": ["retry", "retry", "retry", "retry"] },
    maxSteps: 40,
  });
  assert.equal(result.status, "iteration_limit_reached");
  assert.deepEqual(result.iteration_counts, { "s03-iteration": 3 });
  assert.equal("executed_operations" in result, false);
});

test("revision-only change is rejected", () => {
  const previous = validFlow();
  const candidate = structuredClone(previous);
  candidate.revision = 2;
  const result = validateRevisionTransition(previous, candidate);
  assert.equal(result.issues[0].code, "thoughtflow.revision_without_change");
});

test("raw transport rejects a self transition", () => {
  const flow = validFlow();
  flow.transitions[0].to_step_id = flow.transitions[0].from_step_id;
  const result = parseAndValidateTransport(Buffer.from(JSON.stringify(flow)));
  assert.equal(result.object_result, "invalid");
  assert.equal(result.issues[0].code, "thoughtflow.invalid_transition");
});

test("simulation never chooses first of multiple control successors", () => {
  const flow = validFlow();
  flow.transitions.push({
    transition_id: "t99", kind: "sequence",
    from_step_id: "s01-goal", to_step_id: "s03-iteration",
  });
  const result = simulateBounded(flow, { observations: {}, branchSelections: {}, maxSteps: 5 });
  assert.equal(result.status, "ambiguous_control");
  assert.equal(result.current_step_id, "s01-goal");
});

test("tampered expected cannot change actual", () => {
  const caseValue = structuredClone(suite.cases[0]);
  const originalExpected = structuredClone(caseValue.expected);
  caseValue.expected = {
    object_result: "invalid",
    operation_outcome: "succeeded",
    issues: [{ code: "thoughtflow.invalid_json", path: "", severity: "error" }],
  };
  const actual = parseAndValidateTransport(Buffer.from(JSON.stringify(caseValue.input.flow)));
  assert.deepEqual(actual, originalExpected);
  assert.notDeepEqual(actual, caseValue.expected);
});
test("missing verification observation is indeterminate", () => {
  const result = simulateBounded(validFlow(), {
    observations: {}, branchSelections: { "s03-iteration": ["retry"] }, maxSteps: 10,
  });
  assert.equal(result.status, "requires_observation");
  assert.equal(result.object_result, "not_evaluated");
  assert.equal(result.operation_outcome, "indeterminate");
});