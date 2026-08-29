import assert from "node:assert/strict";
import test from "node:test";

import { createLinearEquationIntakePreview, fixedCognitiveNodeContractRoot } from "../intake.ts";

function request(overrides: Record<string, unknown> = {}) {
  return { text: "2x + 3 = 11", source_ref: "source:algebra:example-1", ...overrides };
}

test("normalizes supported equations into a semantically valid unsaved CognitiveNode candidate", () => {
  const input = request();
  const before = structuredClone(input);
  const result = createLinearEquationIntakePreview(input);

  assert.equal(fixedCognitiveNodeContractRoot().replaceAll("\\", "/").endsWith("contracts/cognitive-node/1.0.0/"), true);
  assert.deepEqual(result.source, { text: "2x + 3 = 11", source_ref: "source:algebra:example-1" });
  assert.equal(result.state, "ready");
  assert.equal(result.normalized_equation, "2*x + 3 = 11");
  assert.equal(result.variable, "x");
  assert.deepEqual(result.validation, { transport: "valid", semantic: "valid" });
  assert.deepEqual(result.candidate_node?.data, { expression: "2*x + 3 = 11", symbols: ["x"] });
  assert.deepEqual(result.candidate_node?.provenance_refs, ["source:algebra:example-1"]);
  assert.match(result.candidate_node?.id ?? "", /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.deepEqual(input, before);
});

test("supports signs and optional multiplication while retaining a deterministic candidate", () => {
  const first = createLinearEquationIntakePreview(request({ text: "-x - 4 = 0" }));
  const second = createLinearEquationIntakePreview(request({ text: "-x - 4 = 0" }));
  const multiplied = createLinearEquationIntakePreview(request({ text: " 2*x=4 " }));

  assert.equal(first.normalized_equation, "-1*x - 4 = 0");
  assert.equal(first.candidate_node?.id, second.candidate_node?.id);
  assert.equal(multiplied.normalized_equation, "2*x + 0 = 4");
});

test("returns empty only for a string with no non-whitespace equation content", () => {
  const result = createLinearEquationIntakePreview(request({ text: " \t\n" }));

  assert.deepEqual(result, {
    mode: "preview", side_effects: "forbidden", state: "empty",
    source: { text: " \t\n", source_ref: "source:algebra:example-1" },
    normalized_equation: null, variable: null, candidate_node: null, validation: null, diagnostic: "输入为空。",
  });
});

test("fails closed for unsupported equations, unsafe numbers, zero coefficients, invalid provenance and extra fields", () => {
  const invalids = [
    request({ text: "x + y = 1" }), request({ text: "x^2 = 4" }), request({ text: "x = 1/2" }),
    request({ text: "0x = 1" }), request({ text: "9007199254740992x = 1" }), request({ text: "x = 1", source_ref: " source:bad" }),
    { text: "x = 1" }, { text: "x = 1", source_ref: "source:ok", unexpected: true }, { text: 12, source_ref: "source:ok" },
  ];
  for (const value of invalids) {
    const result = createLinearEquationIntakePreview(value);
    assert.equal(result.state, "invalid_input");
    assert.equal(result.candidate_node, null);
    assert.equal(result.validation, null);
  }
});
