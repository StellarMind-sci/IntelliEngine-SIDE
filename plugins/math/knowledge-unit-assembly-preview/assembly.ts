import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  createLinearEquationIntakePreview,
  fixedCognitiveNodeContractRoot,
  type CognitiveNode,
  type LinearEquationIntakePreview,
} from "../linear-equation-intake-preview/intake.ts";
import { validateSemantic, validateTransport } from "../../../packages/cognitive-ir/src/cognitive-node/runtime.ts";
import { projectKnowledge } from "../../../packages/knowledge-units/src/knowledge-unit/project.ts";
import { validateUnit } from "../../../packages/knowledge-units/src/knowledge-unit/runtime.ts";

type JsonObject = Record<string, unknown>;
type NodeRef = { id: string; revision: 1 };
type CandidateNode = CognitiveNode | {
  contract_version: "1.0.0";
  id: string;
  revision: 1;
  base_kind: "entity" | "variable";
  type_id: "org.intelliengine.core/entity" | "org.intelliengine.core/variable";
  type_version: "1.0.0";
  data: { name: string };
  provenance_refs: [string];
};

type KnowledgeUnitDraft = {
  contract_version: "1.0.0";
  id: string;
  revision: 1;
  title: string;
  concept_boundary: {
    focus_node_refs: NodeRef[];
    out_of_scope_statements: ["不包含二次及更高次方程"];
  };
  learning_objectives: Array<{
    objective_id: "solve-linear-equation";
    statement: "能够求解一元一次方程并说明等价变换。";
    target_node_refs: NodeRef[];
  }>;
  node_bindings: Array<{ role: "core" | "evidence" | "example" | "representation"; node_ref: NodeRef }>;
  prerequisite_unit_refs: [];
  behaviors: Array<{
    behavior_id: "solve-linear-equation";
    kind: "calculation";
    capability: "runtime.math.symbolic";
    input_node_refs: NodeRef[];
    output_node_refs: NodeRef[];
  }>;
  validations: Array<{
    validation_id: "substitution-check";
    description: "将解代回原方程后等式成立。";
    subject_node_refs: NodeRef[];
    evidence_node_refs: NodeRef[];
  }>;
  mastery_criteria: Array<{
    criterion_id: "explain-and-verify";
    statement: "能够解释求解步骤并用代入法验证结果。";
    evidence_node_refs: NodeRef[];
  }>;
  provenance_refs: [string];
};

export type LinearEquationKnowledgeUnitAssemblyPreview = {
  mode: "preview";
  side_effects: "forbidden";
  state: "needs_evidence" | "empty" | "invalid_input";
  source_ref: string | null;
  candidate_nodes: CandidateNode[];
  knowledge_unit: KnowledgeUnitDraft | null;
  validation: { cognitive_nodes: "valid"; knowledge_unit: "valid" } | null;
  projection: {
    status: "needs_evidence";
    missing_evidence_node_refs: NodeRef[];
  } | null;
  navigation: "完成方程求解与代入验证并记录证据后，再推进模型步骤。" | null;
  diagnostic: string | null;
};

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function plainObject(value: unknown): value is JsonObject {
  return isRecord(value) && Object.getPrototypeOf(value) === Object.prototype;
}

function ownData(value: JsonObject, key: string): unknown {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor !== undefined && "value" in descriptor ? descriptor.value : undefined;
}

function exactKeys(value: unknown, keys: readonly string[]) {
  if (!plainObject(value)) return false;
  const actual = Reflect.ownKeys(value);
  if (actual.length !== keys.length || actual.some((key) => typeof key !== "string" || !keys.includes(key))) return false;
  return keys.every((key) => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor !== undefined && descriptor.enumerable && "value" in descriptor;
  });
}

function matchesPlainData(expected: unknown, actual: unknown): boolean {
  if (expected === null || typeof expected !== "object") return Object.is(expected, actual);
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || Object.getPrototypeOf(actual) !== Array.prototype) return false;
    const keys = Reflect.ownKeys(actual);
    const expectedKeys = new Set<PropertyKey>(["length", ...expected.map((_, index) => String(index))]);
    if (keys.length !== expectedKeys.size || keys.some((key) => !expectedKeys.has(key))) return false;
    return expected.every((entry, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(actual, String(index));
      return descriptor !== undefined && "value" in descriptor && matchesPlainData(entry, descriptor.value);
    });
  }
  if (!plainObject(actual) || !isRecord(expected)) return false;
  const expectedKeys = Object.keys(expected);
  if (!exactKeys(actual, expectedKeys)) return false;
  return expectedKeys.every((key) => matchesPlainData(expected[key], ownData(actual, key)));
}

function compareBytes(left: string, right: string) {
  return Buffer.compare(Buffer.from(left), Buffer.from(right));
}

function referenceKey(reference: NodeRef) {
  return `${reference.id}\u0000${String(reference.revision).padStart(16, "0")}`;
}

function canonicalRefs(references: NodeRef[]) {
  return [...references].sort((left, right) => compareBytes(referenceKey(left), referenceKey(right)));
}

function candidateRef(node: CandidateNode): NodeRef {
  return { id: node.id, revision: 1 };
}

function deterministicUuid(domain: string, sourceRef: string, canonical: string) {
  const bytes = createHash("sha256").update(`${domain}\n${sourceRef}\n${canonical}`, "utf8").digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function cognitiveSchema(contractRoot: string): JsonObject {
  return JSON.parse(readFileSync(join(contractRoot, "schemas", "cognitive-node.schema.json"), "utf8")) as JsonObject;
}

function mathDefinition(contractRoot: string): JsonObject {
  const suite = JSON.parse(readFileSync(join(contractRoot, "fixtures", "cases.json"), "utf8")) as { cases: Array<{ case_id?: unknown; input?: unknown }> };
  const fixture = suite.cases.find((entry) => entry.case_id === "math-equation-type-definition-valid");
  if (fixture === undefined || !isRecord(fixture.input)) throw new Error("math equation type definition is unavailable");
  return fixture.input;
}

export function fixedKnowledgeUnitContractRoot() {
  return fileURLToPath(new URL("../../../packages/knowledge-units/contracts/knowledge-unit/1.0.0/", import.meta.url));
}

function result(
  state: LinearEquationKnowledgeUnitAssemblyPreview["state"],
  sourceRef: string | null,
  diagnostic: string | null,
): LinearEquationKnowledgeUnitAssemblyPreview {
  return {
    mode: "preview",
    side_effects: "forbidden",
    state,
    source_ref: sourceRef,
    candidate_nodes: [],
    knowledge_unit: null,
    validation: null,
    projection: null,
    navigation: null,
    diagnostic,
  };
}

function strictPreview(value: unknown): LinearEquationIntakePreview | null {
  if (!isRecord(value) || !exactKeys(value, ["intake_preview"])) return null;
  const preview = ownData(value, "intake_preview");
  if (!isRecord(preview) || !exactKeys(preview, [
    "mode", "side_effects", "state", "source", "normalized_equation", "variable", "candidate_node", "validation", "diagnostic",
  ])) return null;
  const source = ownData(preview, "source");
  if (!isRecord(source)
    || !exactKeys(source, ["text", "source_ref"])) return null;
  const text = ownData(source, "text");
  const sourceRef = ownData(source, "source_ref");
  if (typeof text !== "string" || typeof sourceRef !== "string") return null;

  const rebuilt = createLinearEquationIntakePreview({ text, source_ref: sourceRef });
  if (!matchesPlainData(rebuilt, preview)) return null;
  return rebuilt;
}

function buildCandidates(preview: LinearEquationIntakePreview): CandidateNode[] {
  const sourceRef = preview.source.source_ref!;
  const equation = preview.candidate_node!;
  const normalized = preview.normalized_equation!;
  const variableName = preview.variable!;
  const variable: CandidateNode = {
    contract_version: "1.0.0",
    id: deterministicUuid("knowledge-unit-assembly/variable", sourceRef, `${normalized}\n${variableName}`),
    revision: 1,
    base_kind: "variable",
    type_id: "org.intelliengine.core/variable",
    type_version: "1.0.0",
    data: { name: variableName },
    provenance_refs: [sourceRef],
  };
  const solution: CandidateNode = {
    contract_version: "1.0.0",
    id: deterministicUuid("knowledge-unit-assembly/solution", sourceRef, normalized),
    revision: 1,
    base_kind: "entity",
    type_id: "org.intelliengine.core/entity",
    type_version: "1.0.0",
    data: { name: `solution for ${normalized}` },
    provenance_refs: [sourceRef],
  };
  const evidence: CandidateNode = {
    contract_version: "1.0.0",
    id: deterministicUuid("knowledge-unit-assembly/verification-evidence", sourceRef, normalized),
    revision: 1,
    base_kind: "entity",
    type_id: "org.intelliengine.core/entity",
    type_version: "1.0.0",
    data: { name: `substitution verification for ${normalized}` },
    provenance_refs: [sourceRef],
  };
  return [structuredClone(equation), variable, solution, evidence]
    .sort((left, right) => compareBytes(referenceKey(candidateRef(left)), referenceKey(candidateRef(right))));
}

function cognitiveNodesAreValid(candidates: CandidateNode[]) {
  try {
    const root = fixedCognitiveNodeContractRoot();
    const schema = cognitiveSchema(root);
    if (candidates.some((node) => validateTransport(node, schema).object_result !== "valid")) return false;
    const equation = candidates.find((node) => node.type_id === "org.intelliengine.math/equation");
    return equation !== undefined
      && validateSemantic(equation, schema, mathDefinition(root), "exact-math-equation").object_result === "valid";
  } catch {
    return false;
  }
}

function buildKnowledgeUnit(candidates: CandidateNode[], preview: LinearEquationIntakePreview): KnowledgeUnitDraft {
  const sourceRef = preview.source.source_ref!;
  const normalized = preview.normalized_equation!;
  const equation = candidates.find((node) => node.type_id === "org.intelliengine.math/equation")!;
  const variable = candidates.find((node) => node.type_id === "org.intelliengine.core/variable")!;
  const solution = candidates.find((node) => node.data.name === `solution for ${normalized}`)!;
  const evidence = candidates.find((node) => node.data.name === `substitution verification for ${normalized}`)!;
  const equationRef = candidateRef(equation);
  const variableRef = candidateRef(variable);
  const solutionRef = candidateRef(solution);
  const evidenceRef = candidateRef(evidence);
  return {
    contract_version: "1.0.0",
    id: deterministicUuid("knowledge-unit-assembly/knowledge-unit", sourceRef, normalized),
    revision: 1,
    title: `解一元一次方程：${normalized}`,
    concept_boundary: {
      focus_node_refs: canonicalRefs([equationRef]),
      out_of_scope_statements: ["不包含二次及更高次方程"],
    },
    learning_objectives: [{
      objective_id: "solve-linear-equation",
      statement: "能够求解一元一次方程并说明等价变换。",
      target_node_refs: canonicalRefs([solutionRef]),
    }],
    node_bindings: [
      { role: "core", node_ref: equationRef },
      { role: "evidence", node_ref: evidenceRef },
      { role: "example", node_ref: solutionRef },
      { role: "representation", node_ref: variableRef },
    ],
    prerequisite_unit_refs: [],
    behaviors: [{
      behavior_id: "solve-linear-equation",
      kind: "calculation",
      capability: "runtime.math.symbolic",
      input_node_refs: canonicalRefs([equationRef, variableRef]),
      output_node_refs: canonicalRefs([solutionRef]),
    }],
    validations: [{
      validation_id: "substitution-check",
      description: "将解代回原方程后等式成立。",
      subject_node_refs: canonicalRefs([solutionRef]),
      evidence_node_refs: canonicalRefs([evidenceRef]),
    }],
    mastery_criteria: [{
      criterion_id: "explain-and-verify",
      statement: "能够解释求解步骤并用代入法验证结果。",
      evidence_node_refs: canonicalRefs([evidenceRef]),
    }],
    provenance_refs: [sourceRef],
  };
}

function assembleLinearEquationKnowledgeUnitPreview(input: unknown): LinearEquationKnowledgeUnitAssemblyPreview {
  const preview = strictPreview(input);
  if (preview === null || preview.state === "invalid_input") {
    return result("invalid_input", null, "上游方程预览不完整、已失效或未通过复核。");
  }
  if (preview.state === "empty") {
    return result("empty", preview.source.source_ref, "上游没有可组装的方程候选。");
  }
  if (preview.state !== "ready" || preview.candidate_node === null || preview.source.source_ref === null) {
    return result("invalid_input", null, "上游方程预览不完整、已失效或未通过复核。");
  }

  const candidateNodes = buildCandidates(preview);
  if (!cognitiveNodesAreValid(candidateNodes)) {
    return result("invalid_input", preview.source.source_ref, "上游方程预览不完整、已失效或未通过复核。");
  }
  const unit = buildKnowledgeUnit(candidateNodes, preview);
  const availableNodeRefs = canonicalRefs(candidateNodes.map(candidateRef));
  try {
    if (validateUnit(unit, availableNodeRefs, fixedKnowledgeUnitContractRoot()).object_result !== "valid") {
      return result("invalid_input", preview.source.source_ref, "KnowledgeUnit 草案未通过固定合同校验。");
    }
    const projected = projectKnowledge([unit], availableNodeRefs, [], fixedKnowledgeUnitContractRoot());
    const first = projected.units[0] as { status?: unknown; missing_evidence_node_refs?: unknown } | undefined;
    if (projected.object_result !== "valid"
      || first?.status !== "needs_evidence"
      || !Array.isArray(first.missing_evidence_node_refs)
      || first.missing_evidence_node_refs.length !== 1) {
      return result("invalid_input", preview.source.source_ref, "KnowledgeUnit 草案未通过固定合同校验。");
    }
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: "needs_evidence",
      source_ref: preview.source.source_ref,
      candidate_nodes: candidateNodes,
      knowledge_unit: unit,
      validation: { cognitive_nodes: "valid", knowledge_unit: "valid" },
      projection: {
        status: "needs_evidence",
        missing_evidence_node_refs: first.missing_evidence_node_refs as NodeRef[],
      },
      navigation: "完成方程求解与代入验证并记录证据后，再推进模型步骤。",
      diagnostic: null,
    };
  } catch {
    return result("invalid_input", preview.source.source_ref, "KnowledgeUnit 草案未通过固定合同校验。");
  }
}

export function createLinearEquationKnowledgeUnitAssemblyPreview(input: unknown): LinearEquationKnowledgeUnitAssemblyPreview {
  try {
    return assembleLinearEquationKnowledgeUnitPreview(input);
  } catch {
    return result("invalid_input", null, "上游方程预览不完整、已失效或未通过复核。");
  }
}
