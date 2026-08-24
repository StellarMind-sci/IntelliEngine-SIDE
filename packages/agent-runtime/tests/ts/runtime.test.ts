import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import test from "node:test";
import { executeFixtureSuite, loadLockedContract, parseAndValidateTransport, validateReferences, validateRevisionTransition } from "../../src/agent-profile/runtime.ts";
import { canonicalize } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";

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
test("object API rejects unpaired surrogate units recursively", () => {
  const value = profile(); value.display_name = "\uD800";
  const snapshot = { contract_version: "1.0.0", provenance: [{ ref: value.provenance_refs[0], object_result: "available" }] };
  const result = validateReferences(value, snapshot, root);
  assert.equal(result.object_result, "invalid");
  assert.equal(result.issues[0].code, "agent_profile.invalid_json");
});

test("locked contract rejects invalid and unlocked references", () => {
  for (const [reference, addUnlisted] of [["#/~2", false], ["../diagnostics/agent-profile.json", false], ["unlisted.json", true]] as const) {
    const directory = mkdtempSync(`${tmpdir()}/agent-profile-ref-`);
    try {
      const contract = `${directory}/agent-profile/1.0.0`; cpSync(new URL("../../contracts/agent-profile/1.0.0/", import.meta.url), contract, { recursive: true });
      const schemaPath = `${contract}/schemas/agent-profile.schema.json`, schema = JSON.parse(readFileSync(schemaPath, "utf8")); schema.$ref = reference; writeFileSync(schemaPath, JSON.stringify(schema));
      if (addUnlisted) writeFileSync(`${contract}/schemas/unlisted.json`, "{}");
      const lockPath = `${contract}/lock.json`, lock = JSON.parse(readFileSync(lockPath, "utf8"));
      lock.entries.find((entry: any) => entry.path === "schemas/agent-profile.schema.json").sha256 = createHash("sha256").update(canonicalize(schema)).digest("hex"); writeFileSync(lockPath, JSON.stringify(lock));
      assert.throws(() => loadLockedContract(contract));
    } finally { rmSync(directory, { recursive: true, force: true }); }
  }
});
test("profile object shapes match schema for persona and preferences", () => {
  for (const mutate of [
    (value: any) => { value.persona.principles = [""]; },
    (value: any) => { value.persona.principles = [1]; },
    (value: any) => { delete value.working_style.planning_preference; },
    (value: any) => { value.collaboration_preferences.extra = true; },
  ]) {
    const value = profile(); mutate(value);
    const result = validateReferences(value, { contract_version: "1.0.0", provenance: [{ ref: value.provenance_refs[0], object_result: "available" }] }, root);
    assert.equal(result.object_result, "invalid");
    assert.equal(result.issues[0].code, "agent_profile.invalid_profile_field");
  }
});

test("reference snapshot diagnostics use canonical Python-equivalent paths", () => {
  const value = profile(), entry = { ref: value.provenance_refs[0], object_result: "available" };
  const cases: Array<[any, string]> = [
    [{ contract_version: "1.0.0", provenance: [] }, "/provenance"],
    [{ contract_version: "1.0.0", provenance: [{ ...entry, extra: true }] }, "/provenance"],
    [{ contract_version: "1.0.0", provenance: [entry], z: true, a: true }, "/a"],
  ];
  for (const [snapshot, path] of cases) {
    const result = validateReferences(value, snapshot, root);
    assert.equal(result.object_result, "not_evaluated");
    assert.equal(result.issues[0].path, path);
  }
});
test("raw revision preserves integer lexical semantics", () => {
  assert.equal(validateReferences(profile(), { contract_version: "1.0.0", provenance: [{ ref: profile().provenance_refs[0], object_result: "available" }] }, root).object_result, "valid");
  const raw = JSON.stringify(profile());
  for (const token of ["1.0", "1e0", "-0"]) {
    const result = parseAndValidateTransport(Buffer.from(raw.replace('"revision":1', `"revision":${token}`)), root);
    assert.equal(result.object_result, "invalid");
    assert.deepEqual(result.issues[0], { code: "agent_profile.invalid_revision", path: "/revision", severity: "error" });
  }
});
test("raw escaped revision keys retain numeric tokens", () => {
  const raw = JSON.stringify(profile());
  for (const token of ["1.0", "1e0", "-0"]) {
    const escapedKey = raw.replace('"revision":1', `"\\u0072evision":${token}`);
    const result = parseAndValidateTransport(Buffer.from(escapedKey), root);
    assert.deepEqual(result.issues[0], { code: "agent_profile.invalid_revision", path: "/revision", severity: "error" });
  }
  const mention = profile(); mention.persona.summary = "A revision: 1.0 note is descriptive text.";
  const result = parseAndValidateTransport(Buffer.from(JSON.stringify(mention)), root);
  assert.equal(result.object_result, "valid");
});