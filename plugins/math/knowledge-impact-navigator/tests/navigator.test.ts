import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { projectKnowledge } from "../../../../packages/knowledge-units/src/knowledge-unit/project.ts";
import { createKnowledgeImpactNavigator } from "../navigator.ts";

const cases = JSON.parse(
  readFileSync(new URL("../fixtures/demo-cases.json", import.meta.url), "utf8"),
);
const knowledgeUnitRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../packages/knowledge-units");
const knowledgeUnitContractRoot = resolve(knowledgeUnitRoot, "contracts/knowledge-unit/1.0.0");
const knowledgeProjectionFixtures = JSON.parse(
  readFileSync(resolve(knowledgeUnitRoot, "tests/fixtures/project-projection-cases.json"), "utf8"),
);

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

test("keeps a real blocked projection with missing prerequisites and evidence navigable", () => {
  const source = knowledgeProjectionFixtures.unit_catalog[1];
  const available = knowledgeProjectionFixtures.cases.find((item: any) => item.case_id === "missing-prerequisite").available_node_refs;
  const projection = projectKnowledge([clone(source)], available, [], knowledgeUnitContractRoot);
  const focus_ref = { id: source.id, revision: source.revision };
  const request = {
    focus_ref,
    projection,
    flow: {
      steps: [
        { step_id: "analysis-linear", kind: "analysis", knowledge_unit_refs: [clone(focus_ref)] },
        {
          step_id: "operation-linear",
          kind: "operation",
          knowledge_unit_refs: [],
          behavior_ref: { knowledge_unit_ref: clone(focus_ref) },
        },
      ],
    },
  };

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(projection.units[0].status, "blocked");
  assert.deepEqual(projection.units[0].missing_prerequisite_refs, [{ id: "10000000-0000-4000-8000-000000000001", revision: 1 }]);
  assert.deepEqual(projection.units[0].missing_evidence_node_refs, [{ id: "20000000-0000-4000-8000-000000000002", revision: 1 }]);
  assert.equal(result.state, "blocked");
  assert.equal(result.navigation, "先完成缺失前置知识，再继续受影响的 analysis / operation 步骤。");
  assert.deepEqual(result.impacted_steps.map((step) => step.step_id), ["analysis-linear", "operation-linear"]);
  assert.deepEqual(result.reasons, [{
    knowledge_unit_ref: focus_ref,
    status: "blocked",
    missing_prerequisite_refs: [{ id: "10000000-0000-4000-8000-000000000001", revision: 1 }],
    missing_evidence_node_refs: [{ id: "20000000-0000-4000-8000-000000000002", revision: 1 }],
  }]);
});

test("navigates a blocked unit to its analysis and operation impacts", () => {
  const request = clone(cases.blocked);
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "blocked",
    focus: { id: "10000000-0000-4000-8000-000000000001", revision: 1 },
    navigation: "先完成缺失前置知识，再继续受影响的 analysis / operation 步骤。",
    impacted_steps: [
      {
        step_id: "a-operation",
        reasons: [
          {
            knowledge_unit_ref: { id: "10000000-0000-4000-8000-000000000001", revision: 1 },
            status: "blocked",
            missing_prerequisite_refs: [{ id: "10000000-0000-4000-8000-000000000011", revision: 1 }],
            missing_evidence_node_refs: [],
          },
        ],
      },
      {
        step_id: "z-analysis",
        reasons: [
          {
            knowledge_unit_ref: { id: "10000000-0000-4000-8000-000000000001", revision: 1 },
            status: "blocked",
            missing_prerequisite_refs: [{ id: "10000000-0000-4000-8000-000000000011", revision: 1 }],
            missing_evidence_node_refs: [],
          },
        ],
      },
    ],
    reasons: [
      {
        knowledge_unit_ref: { id: "10000000-0000-4000-8000-000000000001", revision: 1 },
        status: "blocked",
        missing_prerequisite_refs: [{ id: "10000000-0000-4000-8000-000000000011", revision: 1 }],
        missing_evidence_node_refs: [],
      },
    ],
  });
  assert.deepEqual(request, before);
});

test("navigates a needs-evidence unit only to verification impacts", () => {
  const request = clone(cases.needs_evidence);
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.mode, "preview");
  assert.equal(result.side_effects, "forbidden");
  assert.equal(result.state, "needs_evidence");
  assert.equal(result.navigation, "返回 verification 步骤补充缺失证据。");
  assert.deepEqual(result.impacted_steps.map((step) => step.step_id), ["verification-evidence"]);
  assert.deepEqual(result.reasons, [
    {
      knowledge_unit_ref: { id: "10000000-0000-4000-8000-000000000002", revision: 1 },
      status: "needs_evidence",
      missing_prerequisite_refs: [],
      missing_evidence_node_refs: [{ id: "20000000-0000-4000-8000-000000000001", revision: 1 }],
    },
  ]);
  assert.deepEqual(request, before);
});

test("reports a ready focus without inventing a navigation action", () => {
  const request = clone(cases.ready);
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "ready");
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});

test("rejects a ready focus when an unreferenced projection unit has contradictory blocked state", () => {
  const request = clone(cases.ready);
  request.projection.units.push({
    ref: { id: "10000000-0000-4000-8000-000000000099", revision: 1 },
    status: "blocked",
    missing_prerequisite_refs: [],
    missing_evidence_node_refs: [],
  });
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  });
  assert.deepEqual(request, before);
});
test("reports an empty focus association without inventing an impact", () => {
  const request = clone(cases.empty);
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "empty");
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});

test("rejects an invalid focus ref without navigation or impacted steps", () => {
  const request = clone(cases.blocked);
  request.focus_ref = { id: "not-a-uuid", revision: 1 };
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  });
  assert.deepEqual(request, before);
});

test("rejects an indeterminate upstream impact projection without navigation", () => {
  const request = clone(cases.blocked);
  request.projection.object_result = "invalid";
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "invalid_input");
  assert.equal(result.focus, null);
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});

test("sorts blocked navigation independently of source step order", () => {
  const forward = clone(cases.blocked);
  const reverse = clone(cases.blocked);
  reverse.flow.steps.reverse();

  const forwardResult = createKnowledgeImpactNavigator(forward);
  const reverseResult = createKnowledgeImpactNavigator(reverse);

  assert.deepEqual(forwardResult, reverseResult);
  assert.deepEqual(forwardResult.impacted_steps.map((step) => step.step_id), ["a-operation", "z-analysis"]);
});

test("rejects duplicate projection unit refs before reporting a ready focus", () => {
  const request = clone(cases.empty);
  request.projection.units.push(clone(request.projection.units[1]));
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  });
  assert.deepEqual(request, before);
});
test("rejects a focus that is absent from the canonical projection", () => {
  const request = clone(cases.ready);
  request.focus_ref = { id: "10000000-0000-4000-8000-000000000009", revision: 1 };
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "invalid_input");
  assert.equal(result.focus, null);
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(request, before);
});

test("reports a blocked focus with no flow steps as empty", () => {
  const request = clone(cases.blocked);
  request.flow.steps = [];
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "empty");
  assert.deepEqual(result.focus, request.focus_ref);
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});

test("reports a blocked focus with only a verification step as empty", () => {
  const request = clone(cases.blocked);
  request.flow.steps = [
    {
      step_id: "verification-only",
      kind: "verification",
      knowledge_unit_refs: [clone(request.focus_ref)],
    },
  ];
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "empty");
  assert.deepEqual(result.focus, request.focus_ref);
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});
test("rejects a needs-evidence reason that also carries missing prerequisites", () => {
  const request = clone(cases.needs_evidence);
  request.projection.units[0].missing_prerequisite_refs = [
    { id: "10000000-0000-4000-8000-000000000011", revision: 1 },
  ];
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.deepEqual(result, {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  });
  assert.deepEqual(request, before);
});

test("treats a ready focus referenced only by analysis behavior as empty", () => {
  const request = clone(cases.ready);
  request.flow.steps = [
    {
      step_id: "analysis-behavior-only",
      kind: "analysis",
      knowledge_unit_refs: [],
      behavior_ref: { knowledge_unit_ref: clone(request.focus_ref), behavior_id: "solve-linear-equation" },
    },
  ];
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "empty");
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});

test("keeps a ready focus referenced by operation behavior as a valid association", () => {
  const request = clone(cases.ready);
  request.flow.steps = [
    {
      step_id: "operation-behavior-only",
      kind: "operation",
      knowledge_unit_refs: [],
      behavior_ref: { knowledge_unit_ref: clone(request.focus_ref), behavior_id: "solve-linear-equation" },
    },
  ];
  const before = clone(request);

  const result = createKnowledgeImpactNavigator(request);

  assert.equal(result.state, "ready");
  assert.equal(result.navigation, null);
  assert.deepEqual(result.impacted_steps, []);
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(request, before);
});
