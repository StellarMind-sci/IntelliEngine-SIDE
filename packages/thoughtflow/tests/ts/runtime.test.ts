import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  executeFixtureSuite,
  graphSummary,
  nextCandidates,
  parseAndValidateTransport,
  simulateBounded,
  validateRevisionTransition,
} from "../../src/thoughtflow/runtime.ts";

const root = new URL("../../contracts/thoughtflow/1.0.0/", import.meta.url);
const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", root), "utf8"));
const validFlow = () => structuredClone(suite.cases[0].input.flow);

test("executes all machine fixtures without replaying expected", () => {
  const results = executeFixtureSuite(root);
  assert.equal(results.length, 18);
  assert.ok(results.every((item) => JSON.stringify(item.actual) === JSON.stringify(item.expected)));
});

test("raw transport rejects duplicate members", () => {
  const result = parseAndValidateTransport(Buffer.from('{"contract_version":"1.0.0","contract_version":"1.0.0"}'));
  assert.equal(result.issues[0].code, "thoughtflow.invalid_json");
});

test("graph summary is deterministic", () => {
  assert.deepEqual(graphSummary(validFlow()), {
    entry_step_id: "s01-goal",
    step_count: 7,
    transition_count: 8,
    step_kinds: { analysis: 1, artifact: 1, goal: 2, iteration: 1, operation: 1, verification: 1 },
    loop_controllers: [{ max_iterations: 3, step_id: "s03-iteration" }],
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
    candidates: [{ kind: "loop", to_step_id: "s03-iteration", transition_id: "t08" }],
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
