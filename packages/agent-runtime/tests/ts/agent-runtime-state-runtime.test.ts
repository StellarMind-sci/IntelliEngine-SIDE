import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import test from "node:test";
import {
  aggregateVisibleStates,
  executeFixtureSuite,
  parseAndValidateTransport,
  planTransition,
  validateState,
  loadLockedContract,
} from "../../src/agent-runtime-state/runtime.ts";

import { canonicalize } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";

const root = new URL("../../contracts/agent-runtime-state/1.0.0/", import.meta.url);
const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", root), "utf8"));
const caseById = (caseId: string) => structuredClone(suite.cases.find((item: any) => item.case_id === caseId));

test("executes every locked case using real runtime", () => {
  const results = executeFixtureSuite(root);
  assert.equal(results.length, 33);
  assert.ok(results.every((item: any) => JSON.stringify(item.actual) === JSON.stringify(item.expected)));
});

test("raw integer scanner ignores string contents", () => {
  const state = caseById("state-registered-not-dormant").input.state;
  state.last_transition_ref = 'agent-runtime-transition: "activation_epoch":1.0';
  assert.equal(parseAndValidateTransport(Buffer.from(JSON.stringify(state)), root).object_result, "valid");
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
test("same profile ref rebind ignores json member order", () => {
  const input = caseById("rebind-same-ref-no-change").input;
  const ref = input.intent.target_profile_ref;
  input.intent.target_profile_ref = { revision: ref.revision, id: ref.id };
  assert.equal(planTransition(input.state, input.intent, root).plan.disposition, "no_change");
});

test("raw state integer positions reject noninteger lexical tokens", () => {
  const state = caseById("state-registered-not-dormant").input.state;
  const raw = JSON.stringify(state);
  const positions: Array<[string, string, string]> = [
    ['"state_revision":2', "/state_revision", "agent_runtime_state.invalid_state_field"],
    ['"activation_epoch":1', "/activation_epoch", "agent_runtime_state.invalid_state_field"],
    ['"revision":1', "/agent_profile_ref/revision", "agent_runtime_state.invalid_profile_ref"],
  ];
  for (const [source, path, code] of positions) for (const token of ["1.0", "1e0", "-0"]) {
    const result = parseAndValidateTransport(Buffer.from(raw.replace(source, `${source.split(":", 1)[0]}:${token}`)), root);
    assert.equal(result.object_result, "invalid");
    assert.deepEqual(result.issues[0], { code, path, severity: "error" });
  }
});

test("locked contract rejects unsafe root and schema reference closure", () => {
  assert.throws(() => loadLockedContract(new URL("../../contracts/agent-runtime-state/", import.meta.url)));
  for (const reference of ["#/~2", "../diagnostics/agent-runtime-state.json", "file:///tmp/outside.json", "https://example.invalid/schema.json", "unlisted.json"]) {
    const directory = mkdtempSync(`${tmpdir()}/agent-runtime-state-ref-`);
    try {
      const contract = `${directory}/agent-runtime-state/1.0.0`;
      cpSync(root, contract, { recursive: true });
      const schemaPath = `${contract}/schemas/agent-runtime-state.schema.json`;
      const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
      schema.$ref = reference;
      writeFileSync(schemaPath, JSON.stringify(schema));
      const lockPath = `${contract}/lock.json`, lock = JSON.parse(readFileSync(lockPath, "utf8"));
      lock.entries.find((entry: any) => entry.path === "schemas/agent-runtime-state.schema.json").sha256 = createHash("sha256").update(canonicalize(schema)).digest("hex");
      writeFileSync(lockPath, JSON.stringify(lock));
      assert.throws(() => loadLockedContract(contract));
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }
});