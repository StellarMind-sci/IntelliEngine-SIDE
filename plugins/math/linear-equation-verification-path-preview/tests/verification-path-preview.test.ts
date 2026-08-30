import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createLinearEquationVerificationPathPreview } from "../verification-path-preview.ts";

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
