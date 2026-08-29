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
  assert.deepEqual(preview.proposal?.solution, { variable: "x", value: "4" });
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
test("withholds a proposal and sorts evidence reasons when the matching unit needs evidence", () => {
  const request = clone(cases["needs-evidence"]);
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.mode, "preview");
  assert.equal(preview.side_effects, "forbidden");
  assert.equal(preview.state, "needs_evidence");
  assert.equal(preview.proposal, null);
  assert.deepEqual(preview.impacted_steps, [
    { step_id: "solve-equation", kind: "operation" },
    { step_id: "verify-solution", kind: "verification" },
  ]);
  assert.deepEqual(preview.reasons, [
    {
      knowledge_unit_ref: { id: "linear-equation-unit", revision: 1 },
      status: "needs_evidence",
      missing_prerequisite_refs: [],
      missing_evidence_node_refs: [
        { id: "evidence-a", revision: 2 },
        { id: "evidence-z", revision: 1 },
      ],
    },
  ]);
  assert.deepEqual(request, before);
});

const negativeGates = [
  {
    name: "revision mismatch",
    arrange(request: typeof cases.ready) {
      request.flow.steps.find((step: { kind: string }) => step.kind === "operation").behavior_ref.knowledge_unit_ref.revision = 2;
    },
  },
  {
    name: "absent projection",
    arrange(request: typeof cases.ready) {
      request.projection.units = [];
    },
  },
  {
    name: "wrong behavior kind",
    arrange(request: typeof cases.ready) {
      request.knowledge_units[0].behaviors[0].kind = "transformation";
    },
  },
  {
    name: "wrong behavior capability",
    arrange(request: typeof cases.ready) {
      request.knowledge_units[0].behaviors[0].capability = "runtime.math.numeric";
    },
  },
];

for (const { name, arrange } of negativeGates) {
  test(`withholds a proposal for ${name}`, () => {
    const request = clone(cases.ready);
    arrange(request);
    const before = clone(request);

    const preview = createLinearEquationPreview(request);

    assert.equal(preview.mode, "preview");
    assert.equal(preview.side_effects, "forbidden");
    assert.equal(preview.state, "invalid_input");
    assert.equal(preview.proposal, null);
    assert.deepEqual(request, before);
  });
}

test("chooses the matching operation by step_id so input order cannot change the preview", () => {
  const validOperation = clone(cases.ready.flow.steps.find((step: { kind: string }) => step.kind === "operation"));
  validOperation.step_id = "z-valid-operation";
  const invalidOperation = clone(validOperation);
  invalidOperation.step_id = "a-invalid-operation";
  invalidOperation.behavior_ref.knowledge_unit_ref.revision = 2;
  const verification = clone(cases.ready.flow.steps.find((step: { kind: string }) => step.kind === "verification"));
  const validFirst = clone(cases.ready);
  validFirst.flow.steps = [verification, validOperation, invalidOperation];
  const invalidFirst = clone(cases.ready);
  invalidFirst.flow.steps = [verification, invalidOperation, validOperation];
  const validFirstBefore = clone(validFirst);
  const invalidFirstBefore = clone(invalidFirst);

  const validFirstPreview = createLinearEquationPreview(validFirst);
  const invalidFirstPreview = createLinearEquationPreview(invalidFirst);

  assert.deepEqual(validFirstPreview, invalidFirstPreview);
  assert.equal(validFirstPreview.state, "invalid_input");
  assert.equal(validFirstPreview.proposal, null);
  assert.deepEqual(validFirst, validFirstBefore);
  assert.deepEqual(invalidFirst, invalidFirstBefore);
});

const malformedRequests = [
  {
    name: "null equation",
    arrange(request: typeof cases.ready) {
      request.equation = null;
    },
  },
  {
    name: "null flow steps",
    arrange(request: typeof cases.ready) {
      request.flow.steps = null;
    },
  },
  {
    name: "non-array knowledge units",
    arrange(request: typeof cases.ready) {
      request.knowledge_units = {};
    },
  },
  {
    name: "non-array behaviors",
    arrange(request: typeof cases.ready) {
      request.knowledge_units[0].behaviors = {};
    },
  },
  {
    name: "non-array projection units",
    arrange(request: typeof cases.ready) {
      request.projection.units = {};
    },
  },
];

for (const { name, arrange } of malformedRequests) {
  test(`returns a renderer-safe invalid preview for ${name}`, () => {
    const request = clone(cases.ready);
    arrange(request);
    const before = clone(request);
    let preview: ReturnType<typeof createLinearEquationPreview> | undefined;

    assert.doesNotThrow(() => {
      preview = createLinearEquationPreview(request);
    });

    assert.equal(preview?.mode, "preview");
    assert.equal(preview?.side_effects, "forbidden");
    assert.equal(preview?.state, "invalid_input");
    assert.equal(preview?.proposal, null);
    assert.deepEqual(request, before);
  });
}
test("rejects duplicate matching operation step_ids independently of source order", () => {
  const fixture = cases["duplicate-step-id"];
  const readyFirst = clone(cases.ready);
  readyFirst.flow.steps = [
    clone(fixture.verification_step),
    clone(fixture.ready_operation),
    clone(fixture.absent_operation),
  ];
  const absentFirst = clone(cases.ready);
  absentFirst.flow.steps = [
    clone(fixture.verification_step),
    clone(fixture.absent_operation),
    clone(fixture.ready_operation),
  ];
  const readyFirstBefore = clone(readyFirst);
  const absentFirstBefore = clone(absentFirst);

  const readyFirstPreview = createLinearEquationPreview(readyFirst);
  const absentFirstPreview = createLinearEquationPreview(absentFirst);

  assert.deepEqual(readyFirstPreview, absentFirstPreview);
  assert.equal(readyFirstPreview.mode, "preview");
  assert.equal(readyFirstPreview.side_effects, "forbidden");
  assert.equal(readyFirstPreview.state, "invalid_input");
  assert.equal(readyFirstPreview.proposal, null);
  assert.deepEqual(readyFirst, readyFirstBefore);
  assert.deepEqual(absentFirst, absentFirstBefore);
});
test("rejects duplicate KnowledgeUnit and projection refs independently of source order", () => {
  const duplicateKnowledgeUnit = clone(cases.ready.knowledge_units[0]);
  duplicateKnowledgeUnit.title = "Conflicting duplicate unit";
  const duplicateProjection = clone(cases.ready.projection.units[0]);
  duplicateProjection.status = "blocked";
  duplicateProjection.missing_prerequisite_refs = [{ id: "required-unit", revision: 1 }];

  const unitFirst = clone(cases.ready);
  unitFirst.knowledge_units = [clone(cases.ready.knowledge_units[0]), duplicateKnowledgeUnit];
  unitFirst.projection.units = [clone(cases.ready.projection.units[0]), duplicateProjection];
  const duplicateFirst = clone(cases.ready);
  duplicateFirst.knowledge_units = [duplicateKnowledgeUnit, clone(cases.ready.knowledge_units[0])];
  duplicateFirst.projection.units = [duplicateProjection, clone(cases.ready.projection.units[0])];
  const unitFirstBefore = clone(unitFirst);
  const duplicateFirstBefore = clone(duplicateFirst);

  const unitFirstPreview = createLinearEquationPreview(unitFirst);
  const duplicateFirstPreview = createLinearEquationPreview(duplicateFirst);

  assert.deepEqual(unitFirstPreview, duplicateFirstPreview);
  assert.equal(unitFirstPreview.state, "invalid_input");
  assert.equal(unitFirstPreview.proposal, null);
  assert.deepEqual(unitFirst, unitFirstBefore);
  assert.deepEqual(duplicateFirst, duplicateFirstBefore);
});

const inconsistentProjectionGates = [
  {
    name: "ready status with missing references",
    arrange(request: typeof cases.ready) {
      request.projection.units[0].missing_prerequisite_refs = [{ id: "required-unit", revision: 1 }];
    },
  },
  {
    name: "needs-evidence status without missing evidence",
    arrange(request: typeof cases.ready) {
      request.projection.units[0].status = "needs_evidence";
    },
  },
  {
    name: "needs-evidence status carrying prerequisites",
    arrange(request: typeof cases.ready) {
      request.projection.units[0].status = "needs_evidence";
      request.projection.units[0].missing_prerequisite_refs = [{ id: "required-unit", revision: 1 }];
      request.projection.units[0].missing_evidence_node_refs = [{ id: "evidence-unit", revision: 1 }];
    },
  },
  {
    name: "blocked status without missing prerequisites",
    arrange(request: typeof cases.ready) {
      request.projection.units[0].status = "blocked";
    },
  },
];

for (const { name, arrange } of inconsistentProjectionGates) {
  test(`rejects an inconsistent projection: ${name}`, () => {
    const request = clone(cases.ready);
    arrange(request);
    const before = clone(request);

    const preview = createLinearEquationPreview(request);

    assert.equal(preview.state, "invalid_input");
    assert.equal(preview.proposal, null);
    assert.deepEqual(request, before);
  });
}

test("uses exact SymPy rationals in verification assertions for non-integer solutions", () => {
  const request = clone(cases.ready);
  request.equation = { variable: "x", coefficient: 49, constant: 0, right_hand_side: 1 };
  const before = clone(request);

  const preview = createLinearEquationPreview(request);

  assert.equal(preview.state, "ready");
  assert.deepEqual(preview.proposal?.solution, { variable: "x", value: "1/49" });
  assert.equal(preview.proposal?.verification_assertion, "49 * sp.Rational(1, 49) + 0 == 1");
  assert.match(preview.proposal?.sympy_source ?? "", /sp\.Rational\(1, 49\)/);
  assert.doesNotMatch(preview.proposal?.verification_assertion ?? "", /\(1\/49\)/);
  assert.deepEqual(request, before);
});

test("normalizes negative rational solutions and accepts safe-integer boundaries exactly", () => {
  const negativeRequest = clone(cases.ready);
  negativeRequest.equation = { variable: "x", coefficient: 2, constant: 1, right_hand_side: 0 };
  const boundaryRequest = clone(cases.ready);
  boundaryRequest.equation = {
    variable: "x",
    coefficient: 1,
    constant: -9007199254740991,
    right_hand_side: 9007199254740991,
  };
  const negativeBefore = clone(negativeRequest);
  const boundaryBefore = clone(boundaryRequest);

  const negativePreview = createLinearEquationPreview(negativeRequest);
  const boundaryPreview = createLinearEquationPreview(boundaryRequest);

  assert.deepEqual(negativePreview.proposal?.solution, { variable: "x", value: "-1/2" });
  assert.equal(negativePreview.proposal?.verification_assertion, "2 * sp.Rational(-1, 2) + 1 == 0");
  assert.doesNotMatch(negativePreview.proposal?.verification_assertion ?? "", /\(-1\/2\)/);
  assert.deepEqual(boundaryPreview.proposal?.solution, { variable: "x", value: "18014398509481982" });
  assert.equal(
    boundaryPreview.proposal?.verification_assertion,
    "1 * 18014398509481982 - 9007199254740991 == 9007199254740991",
  );
  assert.deepEqual(negativeRequest, negativeBefore);
  assert.deepEqual(boundaryRequest, boundaryBefore);
});
