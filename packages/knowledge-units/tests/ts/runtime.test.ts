import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseAndValidate, runFixtureSuite, validateUnit } from "../../src/knowledge-unit/runtime.ts";


const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const contractRoot = resolve(packageRoot, "contracts/knowledge-unit/1.0.0");


test("executes all eight KnowledgeUnit contract cases exactly", () => {
  const suite = JSON.parse(readFileSync(resolve(contractRoot, "fixtures/cases.json"), "utf8"));
  const expected = new Map(suite.cases.map((fixture: any) => [fixture.case_id, fixture.expected]));

  const rows = runFixtureSuite(contractRoot);

  assert.deepEqual(rows.map((row: any) => row.case_id), [...expected.keys()].sort());
  assert.deepEqual(
    Object.fromEntries(rows.map(({ case_id, ...result }: any) => [case_id, result])),
    Object.fromEntries(expected),
  );
});


test("invalid unit identity returns stable diagnostics", () => {
  const suite = JSON.parse(readFileSync(resolve(contractRoot, "fixtures/cases.json"), "utf8"));
  const valid = suite.cases.find((fixture: any) => fixture.case_id === "linear-equation-valid").input;

  const invalidId = structuredClone(valid.unit);
  invalidId.id = 7;
  const idResult = validateUnit(invalidId, valid.available_node_refs, contractRoot);

  const invalidRevision = structuredClone(valid.unit);
  invalidRevision.revision = 0;
  const revisionResult = validateUnit(invalidRevision, valid.available_node_refs, contractRoot);

  assert.deepEqual(idResult.issues, [
    { code: "knowledge_unit.invalid_id", path: "/id", severity: "error" },
  ]);
  assert.deepEqual(revisionResult.issues, [
    { code: "knowledge_unit.invalid_revision", path: "/revision", severity: "error" },
  ]);
});
test("nested node ref sets require canonical order", () => {
  const suite = JSON.parse(readFileSync(resolve(contractRoot, "fixtures/cases.json"), "utf8"));
  const valid = suite.cases.find((fixture: any) => fixture.case_id === "linear-equation-valid").input;
  const unit = structuredClone(valid.unit);
  unit.learning_objectives[0].target_node_refs.reverse();

  const result = validateUnit(unit, valid.available_node_refs, contractRoot);

  assert.deepEqual(result.issues, [{
    code: "knowledge_unit.noncanonical_set",
    path: "/learning_objectives/0/target_node_refs",
    severity: "error",
  }]);
});

test("raw transport rejects duplicate members", () => {
  const result = parseAndValidate(
    Buffer.from('{"contract_version":"1.0.0","contract_version":"1.0.0"}'),
    [],
    contractRoot,
  );

  assert.equal(result.object_result, "invalid");
  assert.equal(result.issues[0].code, "knowledge_unit.invalid_json");
  const invalidUtf8 = parseAndValidate(Buffer.from([0xff]), [], contractRoot);

  assert.equal(invalidUtf8.object_result, "invalid");
  assert.equal(invalidUtf8.issues[0].code, "knowledge_unit.invalid_json");
});


test("does not replay fixture expected as computed output", () => {
  const temporary = mkdtempSync(resolve(tmpdir(), "knowledge-unit-ts-"));
  try {
    const copied = resolve(temporary, "1.0.0");
    cpSync(contractRoot, copied, { recursive: true });
    const path = resolve(copied, "fixtures/cases.json");
    const suite = JSON.parse(readFileSync(path, "utf8"));
    const target = suite.cases.find((fixture: any) => fixture.case_id === "linear-equation-valid");
    target.expected = {
      object_result: "invalid",
      operation_outcome: "succeeded",
      issues: [{ code: "knowledge_unit.invalid_json", path: "", severity: "error" }],
    };
    writeFileSync(path, `${JSON.stringify(suite)}\n`, "utf8");

    const row = runFixtureSuite(copied).find((candidate: any) => candidate.case_id === "linear-equation-valid");

    assert.equal(row?.object_result, "valid");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
