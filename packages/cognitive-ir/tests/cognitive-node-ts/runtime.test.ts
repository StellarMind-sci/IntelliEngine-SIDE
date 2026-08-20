import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import test from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { parseAndValidateTransport, runFixtureSuite } from "../../src/cognitive-node/runtime.ts";


const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const contractRoot = resolve(packageRoot, "contracts/cognitive-node/1.0.0");
const profileRoot = resolve(packageRoot, "contracts/profile/1.0.0");


test("raw transport API maps parser failures to CognitiveNode codes", () => {
  const nodeSchema = JSON.parse(
    readFileSync(resolve(contractRoot, "schemas/cognitive-node.schema.json"), "utf8"),
  );
  const result = parseAndValidateTransport(
    Buffer.from('{"contract_version":"1.0.0","contract_version":"1.0.0"}'),
    nodeSchema,
  );

  assert.equal(result.object_result, "invalid");
  assert.equal(result.issues[0].code, "cognitive_node.duplicate_key");
});


test("executes all CognitiveNode fixtures exactly", () => {
  const suite = JSON.parse(readFileSync(resolve(contractRoot, "fixtures/cases.json"), "utf8"));
  const expected = new Map(
    suite.cases.map((fixture: any) => [fixture.case_id, fixture.expected]),
  );

  const rows = runFixtureSuite(contractRoot, profileRoot);

  assert.deepEqual(rows.map((row) => row.case_id), [...expected.keys()].sort());
  assert.deepEqual(
    Object.fromEntries(rows.map(({ case_id, ...result }) => [case_id, result])),
    Object.fromEntries(expected),
  );
});


test("does not replay machine expected as the computed result", () => {
  const temporary = mkdtempSync(resolve(tmpdir(), "cognitive-node-ts-"));
  try {
    const copiedContract = resolve(temporary, "cognitive-node", "1.0.0");
    const copiedProfile = resolve(temporary, "profile", "1.0.0");
    cpSync(contractRoot, copiedContract, { recursive: true });
    cpSync(profileRoot, copiedProfile, { recursive: true });
    const casesPath = resolve(copiedContract, "fixtures/cases.json");
    const suite = JSON.parse(readFileSync(casesPath, "utf8"));
    const target = suite.cases.find((fixture: any) => fixture.case_id === "core-entity-transport-valid");
    target.expected.object_result = "invalid";
    writeFileSync(casesPath, `${JSON.stringify(suite)}\n`, "utf8");

    const row = runFixtureSuite(copiedContract, copiedProfile)
      .find((candidate) => candidate.case_id === "core-entity-transport-valid");

    assert.equal(row?.object_result, "valid");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});


test("parser fixture cannot read outside the profile root", () => {
  const temporary = mkdtempSync(resolve(tmpdir(), "cognitive-node-ts-path-"));
  try {
    const copiedContract = resolve(temporary, "cognitive-node", "1.0.0");
    const copiedProfile = resolve(temporary, "profile", "1.0.0");
    cpSync(contractRoot, copiedContract, { recursive: true });
    cpSync(profileRoot, copiedProfile, { recursive: true });
    writeFileSync(resolve(temporary, "outside.raw"), '{"a":1,"a":2}', "utf8");
    const casePath = resolve(copiedProfile, "fixtures/parser-duplicate-key/case.json");
    const profileCase = JSON.parse(readFileSync(casePath, "utf8"));
    profileCase.input.primary = "profile/1.0.0/../../outside.raw";
    writeFileSync(casePath, `${JSON.stringify(profileCase)}\n`, "utf8");

    assert.throws(() => runFixtureSuite(copiedContract, copiedProfile));
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
