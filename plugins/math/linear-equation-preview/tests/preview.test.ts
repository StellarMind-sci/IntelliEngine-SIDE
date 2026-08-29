import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createLinearEquationPreview } from "../preview.ts";

const cases = JSON.parse(
  readFileSync(new URL("../fixtures/demo-cases.json", import.meta.url), "utf8"),
);

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

test("compiles a ready symbolic calculation into a hand-checked proposal", () => {
  const request = clone(cases.ready);
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "ready");
  assert.deepEqual(preview.proposal?.solution, { variable: "x", value: 4 });
  assert.equal(preview.proposal?.canonical_equation, "2*x + 3 = 11");
  assert.equal(preview.proposal?.verification_assertion, "2 * 4 + 3 == 11");
  assert.deepEqual(preview.impacted_steps.map((step) => step.step_id), ["solve-equation", "verify-solution"]);
  assert.deepEqual(request, before);
});

test("withholds a proposal when the matching unit is blocked by a prerequisite", () => {
  const request = clone(cases.blocked);
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "blocked");
  assert.equal(preview.proposal, null);
  assert.deepEqual(preview.reasons, [
    {
      knowledge_unit_ref: { id: "linear-equation-unit", revision: 1 },
      status: "blocked",
      missing_prerequisite_refs: [{ id: "equality-transformations-unit", revision: 1 }],
      missing_evidence_node_refs: [],
    },
  ]);
  assert.deepEqual(request, before);
});

test("reports an empty preview when the flow has no matching operation", () => {
  const request = clone(cases.empty);
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "empty");
  assert.equal(preview.proposal, null);
  assert.deepEqual(request, before);
});

test("rejects a zero coefficient without offering code", () => {
  const request = clone(cases["invalid-equation"]);
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "invalid_input");
  assert.equal(preview.proposal, null);
  assert.deepEqual(request, before);
});
test("rejects an unsafe numeric coefficient without offering code", () => {
  const request = clone(cases.ready);
  request.equation.coefficient = 9007199254740992;
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "invalid_input");
  assert.equal(preview.proposal, null);
  assert.deepEqual(request, before);
});
