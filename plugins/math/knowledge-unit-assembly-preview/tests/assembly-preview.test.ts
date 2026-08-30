import assert from "node:assert/strict";
import test from "node:test";

import { createLinearEquationIntakePreview } from "../../linear-equation-intake-preview/intake.ts";
import {
  createLinearEquationKnowledgeUnitAssemblyPreview,
  fixedKnowledgeUnitContractRoot,
} from "../assembly.ts";
import { validateUnit } from "../../../../packages/knowledge-units/src/knowledge-unit/runtime.ts";

function readyIntake() {
  return createLinearEquationIntakePreview({ text: "2x + 3 = 11", source_ref: "prov:source:algebra-example-1" });
}

function canonicalReferenceKey(reference: { id: string; revision: number }) {
  return `${reference.id}\u0000${String(reference.revision).padStart(16, "0")}`;
}

function assertCanonicalReferences(references: Array<{ id: string; revision: number }>) {
  const keys = references.map(canonicalReferenceKey);
  const expected = [...keys].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  assert.deepEqual(keys, expected);
  assert.equal(new Set(keys).size, keys.length);
}

test("assembles a deterministic valid KnowledgeUnit draft and projects its missing verification evidence", () => {
  const intake = readyIntake();
  const input = { intake_preview: intake };
  const before = structuredClone(input);
  const first = createLinearEquationKnowledgeUnitAssemblyPreview(input);
  const second = createLinearEquationKnowledgeUnitAssemblyPreview(input);

  assert.equal(fixedKnowledgeUnitContractRoot().replaceAll("\\", "/").endsWith("contracts/knowledge-unit/1.0.0/"), true);
  assert.deepEqual(first, second);
  assert.equal(first.mode, "preview");
  assert.equal(first.side_effects, "forbidden");
  assert.equal(first.state, "needs_evidence");
  assert.equal(first.source_ref, "prov:source:algebra-example-1");
  assert.equal(first.candidate_nodes.length, 4);
  assert.deepEqual(first.validation, { cognitive_nodes: "valid", knowledge_unit: "valid" });
  assert.equal(first.knowledge_unit?.title, "解一元一次方程：2*x + 3 = 11");
  assert.equal(first.projection?.status, "needs_evidence");
  assert.equal(first.projection?.missing_evidence_node_refs.length, 1);
  assert.equal(first.navigation, "完成方程求解与代入验证并记录证据后，再推进模型步骤。");
  assert.equal(first.diagnostic, null);

  const equation = first.candidate_nodes.find((node) => node.type_id === "org.intelliengine.math/equation");
  const variable = first.candidate_nodes.find((node) => node.type_id === "org.intelliengine.core/variable");
  const solution = first.candidate_nodes.find((node) => (node.data as { name?: string }).name?.startsWith("solution for"));
  const evidence = first.candidate_nodes.find((node) => (node.data as { name?: string }).name?.startsWith("substitution verification"));
  assert.deepEqual(equation, intake.candidate_node);
  assert.deepEqual(variable?.data, { name: "x" });
  assert.deepEqual(solution?.data, { name: "solution for 2*x + 3 = 11" });
  assert.deepEqual(evidence?.data, { name: "substitution verification for 2*x + 3 = 11" });
  assert.deepEqual(first.projection?.missing_evidence_node_refs, [{ id: evidence?.id, revision: 1 }]);

  const references = first.candidate_nodes.map(({ id, revision }) => ({ id, revision }));
  assertCanonicalReferences(references);
  assertCanonicalReferences(first.knowledge_unit?.concept_boundary.focus_node_refs ?? []);
  assertCanonicalReferences(first.knowledge_unit?.learning_objectives[0].target_node_refs ?? []);
  assertCanonicalReferences(first.knowledge_unit?.behaviors[0].input_node_refs ?? []);
  assertCanonicalReferences(first.knowledge_unit?.behaviors[0].output_node_refs ?? []);
  assert.equal(validateUnit(first.knowledge_unit, references, fixedKnowledgeUnitContractRoot()).object_result, "valid");
  assert.deepEqual(input, before);
});

test("returns empty only when a valid upstream empty preview has no equation candidate", () => {
  const intake = createLinearEquationIntakePreview({ text: "  \t", source_ref: "prov:source:algebra-example-1" });
  const input = { intake_preview: intake };
  const before = structuredClone(input);
  const result = createLinearEquationKnowledgeUnitAssemblyPreview(input);

  assert.equal(result.state, "empty");
  assert.equal(result.source_ref, "prov:source:algebra-example-1");
  assert.deepEqual(result.candidate_nodes, []);
  assert.equal(result.knowledge_unit, null);
  assert.equal(result.validation, null);
  assert.equal(result.projection, null);
  assert.equal(result.navigation, null);
  assert.equal(result.diagnostic, "上游没有可组装的方程候选。");
  assert.deepEqual(input, before);
});

test("fails closed for malformed, stale, or tampered upstream previews without emitting a draft", () => {
  const ready = readyIntake();
  const tamperedExpression = structuredClone(ready);
  tamperedExpression.candidate_node!.data.expression = "2*x + 3 = 12";
  const tamperedSource = structuredClone(ready);
  tamperedSource.source.source_ref = "prov:source:other";
  const tamperedValidation = structuredClone(ready);
  tamperedValidation.validation = { transport: "valid", semantic: "invalid" } as never;
  const extraField = structuredClone(ready) as Record<string, unknown>;
  extraField.unexpected = true;
  const invalid = createLinearEquationIntakePreview({ text: "x^2 = 4", source_ref: "prov:source:algebra-example-1" });
  const cases: unknown[] = [
    { intake_preview: tamperedExpression },
    { intake_preview: tamperedSource },
    { intake_preview: tamperedValidation },
    { intake_preview: extraField },
    { intake_preview: invalid },
    { intake_preview: ready, unexpected: true },
    { intake_preview: ready, extra: undefined },
    {},
    null,
  ];

  for (const value of cases) {
    const before = structuredClone(value);
    const result = createLinearEquationKnowledgeUnitAssemblyPreview(value);
    assert.equal(result.state, "invalid_input");
    assert.deepEqual(result.candidate_nodes, []);
    assert.equal(result.knowledge_unit, null);
    assert.equal(result.validation, null);
    assert.equal(result.projection, null);
    assert.equal(result.navigation, null);
    assert.equal(result.diagnostic, "上游方程预览不完整、已失效或未通过复核。");
    assert.deepEqual(value, before);
  }
});


test("rejects an inherited unexpected field on the strict request wrapper", () => {
  const input = Object.create({ unexpected: true }) as { intake_preview: ReturnType<typeof readyIntake> };
  input.intake_preview = readyIntake();

  const result = createLinearEquationKnowledgeUnitAssemblyPreview(input);

  assert.equal(result.state, "invalid_input");
  assert.deepEqual(result.candidate_nodes, []);
});

test("contains a throwing intake_preview getter as invalid input", () => {
  const input = {} as { intake_preview?: unknown };
  Object.defineProperty(input, "intake_preview", {
    enumerable: true,
    get() {
      throw new Error("getter must not escape");
    },
  });

  const result = createLinearEquationKnowledgeUnitAssemblyPreview(input);

  assert.equal(result.state, "invalid_input");
  assert.deepEqual(result.candidate_nodes, []);
});

test("contains an ownKeys proxy trap as invalid input", () => {
  const input = new Proxy({ intake_preview: readyIntake() }, {
    ownKeys() {
      throw new Error("ownKeys must not escape");
    },
  });

  const result = createLinearEquationKnowledgeUnitAssemblyPreview(input);

  assert.equal(result.state, "invalid_input");
  assert.deepEqual(result.candidate_nodes, []);
});
