import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  aggregateVisibleStates,
  executeFixtureSuite,
  parseAndValidateTransport,
  planTransition,
  validateState,
} from "../../src/agent-runtime-state/runtime.ts";

const root = new URL("../../contracts/agent-runtime-state/1.0.0/", import.meta.url);
const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", root), "utf8"));
const caseById = (caseId: string) => structuredClone(suite.cases.find((item: any) => item.case_id === caseId));

test("executes every locked case using real runtime", () => {
  const results = executeFixtureSuite(root);
  assert.equal(results.length, 33);
  assert.ok(results.every((item: any) => JSON.stringify(item.actual) === JSON.stringify(item.expected)));
});

test("transport rejects duplicate keys and invalid utf8", () => {
  assert.equal(parseAndValidateTransport(Buffer.from('{"contract_version":"1.0.0","contract_version":"1.0.0"}'), root).issues[0].code, "agent_runtime_state.invalid_json");
  assert.equal(parseAndValidateTransport(Buffer.from([0x7b, 0x22, 0x74, 0x22, 0x3a, 0x22, 0xed, 0xa0, 0x80, 0x22, 0x7d]), root).issues[0].code, "agent_runtime_state.invalid_json");
});

test("plan transition is pure and does not mutate inputs", () => {
  const input = caseById("summon-increases-local-epoch").input;
  const originalState = structuredClone(input.state), originalIntent = structuredClone(input.intent);
  const result = planTransition(input.state, input.intent, root);
  assert.equal(result.operation_outcome, "succeeded");
  assert.equal(result.plan.target_status, "active");
  assert.equal(result.plan.state_revision, input.state.state_revision + 1);
  assert.equal(result.plan.activation_epoch, input.state.activation_epoch + 1);
  assert.deepEqual(input.state, originalState);
  assert.deepEqual(input.intent, originalIntent);
});

test("aggregate counts only caller supplied visible states", () => {
  const input = caseById("aggregate-visible-authorized-only").input.aggregate_input;
  const result = aggregateVisibleStates(input, root);
  assert.deepEqual(result.aggregate, { contract_version: "1.0.0", visible_state_count: 3, active_count: 1, dormant_count: 1, archived_count: 1 });
  assert.equal("authority_scope_ref" in result.aggregate, false);
  assert.equal("runtime_context_ref" in result.aggregate, false);
});

test("compatible minor is read only not transitionable", () => {
  const input = caseById("summon-increases-local-epoch").input;
  const state = structuredClone(input.state); state.contract_version = "1.1.0";
  assert.equal(validateState(state, root).object_result, "compatible_read");
  const result = planTransition(state, input.intent, root);
  assert.equal(result.object_result, "invalid");
  assert.equal(result.operation_outcome, "rejected");
  assert.equal(result.issues[0].code, "agent_runtime_state.unsupported_contract_version");
});