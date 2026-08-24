import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { executeFixtureSuite, parseAndValidateTransport, validateReferences, validateRevisionTransition } from "../../src/agent-profile/runtime.ts";

const root = new URL("../../contracts/agent-profile/1.0.0/", import.meta.url);
const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", root), "utf8"));
const profile = () => structuredClone(suite.cases.find((item: any) => item.case_id === "valid-algebra-mentor").input.profile);

test("executes every locked case without replaying expected", () => {
  const results = executeFixtureSuite(root);
  assert.equal(results.length, 35);
  assert.ok(results.every((item: any) => JSON.stringify(item.actual) === JSON.stringify(item.expected)));
});

test("raw transport is strict and not fixture driven", () => {
  const expected = structuredClone(suite.cases.find((item: any) => item.case_id === "valid-algebra-mentor").expected); expected.mode = "transport";
  assert.deepEqual(parseAndValidateTransport(Buffer.from(JSON.stringify(profile())), root), expected);
  for (const malformed of [Buffer.from([0xef, 0xbb, 0xbf, 0x7b, 0x7d]), Buffer.from('{"id":1,"id":2}'), Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xed, 0xa0, 0x80, 0x22, 0x7d])]) {
    assert.equal(parseAndValidateTransport(malformed, root).issues[0].code, "agent_profile.invalid_json");
  }
});

test("reference closure distinguishes invalid and indeterminate", () => {
  const cases = Object.fromEntries(suite.cases.map((item: any) => [item.case_id, item]));
  assert.deepEqual(validateReferences(cases["dangling-provenance"].input.profile, cases["dangling-provenance"].input.snapshot, root), cases["dangling-provenance"].expected);
  assert.deepEqual(validateReferences(cases["compatible-provenance"].input.profile, cases["compatible-provenance"].input.snapshot, root), cases["compatible-provenance"].expected);
});

test("revision transition requires identity growth and content change", () => {
  const previous = profile(), same = structuredClone(previous), changed = structuredClone(previous);
  same.revision = 2; changed.revision = 2; changed.display_name = "Changed identity description";
  assert.equal(validateRevisionTransition(previous, same, root).issues[0].code, "agent_profile.revision_without_change");
  assert.equal(validateRevisionTransition(previous, changed, root).object_result, "valid");
});