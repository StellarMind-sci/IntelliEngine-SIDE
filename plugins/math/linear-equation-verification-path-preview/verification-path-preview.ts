import { types } from "node:util";

import { createLinearEquationIntakePreview } from "../linear-equation-intake-preview/intake.ts";
import {
  createLinearEquationKnowledgeUnitAssemblyPreview,
  fixedKnowledgeUnitContractRoot,
  type LinearEquationKnowledgeUnitAssemblyPreview,
} from "../knowledge-unit-assembly-preview/assembly.ts";
import { projectKnowledge } from "../../../packages/knowledge-units/src/knowledge-unit/project.ts";
import { createKnowledgeImpactNavigator } from "../knowledge-impact-navigator/navigator.ts";

type KnowledgeUnitRef = { id: string; revision: number };
type NodeRef = { id: string; revision: number };
type FlowStep = {
  step_id: "verification-linear-equation";
  kind: "verification";
  knowledge_unit_refs: [KnowledgeUnitRef];
};

type PreviewFlowContext = {
  persistence: "not_persisted";
  steps: FlowStep[];
};

type VerificationPathRequest = {
  source: { text: string; source_ref: string };
  flow_context: "verification" | "none";
};

export type LinearEquationVerificationPathPreview = {
  mode: "preview";
  side_effects: "forbidden";
  state: "needs_evidence" | "empty" | "invalid_input";
  source_ref: string | null;
  knowledge_unit_ref: KnowledgeUnitRef | null;
  assembly: LinearEquationKnowledgeUnitAssemblyPreview | null;
  flow_context: PreviewFlowContext | null;
  navigation: string | null;
  impacted_steps: Array<{ step_id: string; reasons: unknown[] }>;
  missing_evidence_node_refs: NodeRef[];
  diagnostic: string | null;
};

type JsonObject = Record<string, unknown>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function plainObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && !types.isProxy(value) && Object.getPrototypeOf(value) === Object.prototype;
}

function ownData(value: JsonObject, key: string): unknown | undefined {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor !== undefined && descriptor.enumerable && "value" in descriptor ? descriptor.value : undefined;
}

function exactDataObject(value: unknown, keys: readonly string[]): value is JsonObject {
  if (!plainObject(value)) return false;
  const actual = Reflect.ownKeys(value);
  return actual.length === keys.length
    && actual.every((key) => typeof key === "string" && keys.includes(key))
    && keys.every((key) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      return descriptor !== undefined && descriptor.enumerable && "value" in descriptor;
    });
}

function strictRequest(value: unknown): VerificationPathRequest | null {
  if (!exactDataObject(value, ["source", "flow_context"])) return null;
  const source = ownData(value, "source");
  const flowContext = ownData(value, "flow_context");
  if (!exactDataObject(source, ["text", "source_ref"])) return null;
  const text = ownData(source, "text");
  const sourceRef = ownData(source, "source_ref");
  if (typeof text !== "string" || typeof sourceRef !== "string") return null;
  if (flowContext !== "verification" && flowContext !== "none") return null;
  return { source: { text, source_ref: sourceRef }, flow_context: flowContext };
}

function ref(value: unknown): KnowledgeUnitRef | null {
  if (!exactDataObject(value, ["id", "revision"])) return null;
  const id = ownData(value, "id");
  const revision = ownData(value, "revision");
  return typeof id === "string" && UUID.test(id) && Number.isSafeInteger(revision) && revision >= 1 ? { id, revision } : null;
}

function refKey(value: KnowledgeUnitRef): string {
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}

function canonicalRefs(value: unknown): NodeRef[] | null {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype || types.isProxy(value)) return null;
  const refs = value.map(ref);
  if (refs.some((item) => item === null)) return null;
  const concrete = refs as NodeRef[];
  const keys = concrete.map(refKey);
  const sorted = [...keys].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  if (new Set(keys).size !== keys.length || !keys.every((key, index) => key === sorted[index])) return null;
  return concrete.map((item) => ({ ...item }));
}

function emptyResult(
  state: "empty" | "invalid_input",
  sourceRef: string | null,
  diagnostic: string,
  assembly: LinearEquationKnowledgeUnitAssemblyPreview | null = null,
): LinearEquationVerificationPathPreview {
  return {
    mode: "preview",
    side_effects: "forbidden",
    state,
    source_ref: sourceRef,
    knowledge_unit_ref: null,
    assembly,
    flow_context: null,
    navigation: null,
    impacted_steps: [],
    missing_evidence_node_refs: [],
    diagnostic,
  };
}

function validProjection(projection: unknown, focus: KnowledgeUnitRef): NodeRef[] | null {
  if (!plainObject(projection)
    || ownData(projection, "object_result") !== "valid"
    || ownData(projection, "operation_outcome") !== "succeeded") return null;
  const issues = ownData(projection, "issues");
  const units = ownData(projection, "units");
  if (!Array.isArray(issues) || issues.length !== 0 || !Array.isArray(units) || units.length !== 1) return null;
  const unit = units[0];
  if (!exactDataObject(unit, ["ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"])) return null;
  const projectedRef = ref(ownData(unit, "ref"));
  const prerequisites = canonicalRefs(ownData(unit, "missing_prerequisite_refs"));
  const evidence = canonicalRefs(ownData(unit, "missing_evidence_node_refs"));
  if (projectedRef === null || refKey(projectedRef) !== refKey(focus)
    || ownData(unit, "status") !== "needs_evidence"
    || prerequisites === null || prerequisites.length !== 0
    || evidence === null || evidence.length === 0) return null;
  return evidence;
}

function exactDataArray(value: unknown, length: number): unknown[] | null {
  if (!Array.isArray(value) || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length !== length) return null;
  const keys = Reflect.ownKeys(value);
  if (keys.length !== length + 1 || !keys.includes("length")) return null;
  for (let index = 0; index < length; index += 1) {
    if (!keys.includes(String(index))) return null;
    const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
    if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) return null;
  }
  return value;
}

function sameRefs(left: unknown, right: unknown): boolean {
  const leftRefs = canonicalRefs(left);
  const rightRefs = canonicalRefs(right);
  return leftRefs !== null && rightRefs !== null
    && leftRefs.length === rightRefs.length
    && leftRefs.every((item, index) => refKey(item) === refKey(rightRefs[index]!));
}

function validNeedsEvidenceReason(value: unknown, focus: KnowledgeUnitRef, missingEvidence: NodeRef[]): boolean {
  if (!exactDataObject(value, ["knowledge_unit_ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"])) return false;
  const reasonRef = ref(ownData(value, "knowledge_unit_ref"));
  const prerequisites = canonicalRefs(ownData(value, "missing_prerequisite_refs"));
  const evidence = canonicalRefs(ownData(value, "missing_evidence_node_refs"));
  return reasonRef !== null
    && refKey(reasonRef) === refKey(focus)
    && ownData(value, "status") === "needs_evidence"
    && prerequisites !== null && prerequisites.length === 0
    && evidence !== null && sameRefs(evidence, missingEvidence);
}

function equivalentNeedsEvidenceReasons(left: unknown, right: unknown): boolean {
  if (!exactDataObject(left, ["knowledge_unit_ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"])
    || !exactDataObject(right, ["knowledge_unit_ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"])) return false;
  const leftRef = ref(ownData(left, "knowledge_unit_ref"));
  const rightRef = ref(ownData(right, "knowledge_unit_ref"));
  return leftRef !== null && rightRef !== null
    && refKey(leftRef) === refKey(rightRef)
    && ownData(left, "status") === ownData(right, "status")
    && sameRefs(ownData(left, "missing_prerequisite_refs"), ownData(right, "missing_prerequisite_refs"))
    && sameRefs(ownData(left, "missing_evidence_node_refs"), ownData(right, "missing_evidence_node_refs"));
}

function validNavigatorEnvelope(value: unknown, state: "needs_evidence" | "empty", focus: KnowledgeUnitRef): value is JsonObject {
  if (!exactDataObject(value, ["mode", "side_effects", "state", "focus", "navigation", "impacted_steps", "reasons"])) return false;
  const navigatorFocus = ref(ownData(value, "focus"));
  return ownData(value, "mode") === "preview"
    && ownData(value, "side_effects") === "forbidden"
    && ownData(value, "state") === state
    && navigatorFocus !== null && refKey(navigatorFocus) === refKey(focus);
}

export function validVerificationNavigatorResult(value: unknown, focus: KnowledgeUnitRef, missingEvidence: NodeRef[]): boolean {
  try {
    if (!validNavigatorEnvelope(value, "needs_evidence", focus)
      || ownData(value, "navigation") !== "返回 verification 步骤补充缺失证据。") return false;
    const reasons = exactDataArray(ownData(value, "reasons"), 1);
    const impacts = exactDataArray(ownData(value, "impacted_steps"), 1);
    if (reasons === null || impacts === null || !validNeedsEvidenceReason(reasons[0], focus, missingEvidence)) return false;
    const impact = impacts[0];
    if (!exactDataObject(impact, ["step_id", "reasons"])
      || ownData(impact, "step_id") !== "verification-linear-equation") return false;
    const impactReasons = exactDataArray(ownData(impact, "reasons"), 1);
    return impactReasons !== null
      && validNeedsEvidenceReason(impactReasons[0], focus, missingEvidence)
      && equivalentNeedsEvidenceReasons(reasons[0], impactReasons[0]);
  } catch {
    return false;
  }
}

export function validEmptyNavigatorResult(value: unknown, focus: KnowledgeUnitRef): boolean {
  try {
    if (!validNavigatorEnvelope(value, "empty", focus) || ownData(value, "navigation") !== null) return false;
    return exactDataArray(ownData(value, "reasons"), 0) !== null
      && exactDataArray(ownData(value, "impacted_steps"), 0) !== null;
  } catch {
    return false;
  }
}

function completePreview(request: VerificationPathRequest): LinearEquationVerificationPathPreview {
  const intake = createLinearEquationIntakePreview({ text: request.source.text, source_ref: request.source.source_ref });
  const assembly = createLinearEquationKnowledgeUnitAssemblyPreview({ intake_preview: intake });
  if (assembly.state === "empty") {
    return emptyResult("empty", assembly.source_ref, assembly.diagnostic ?? "上游没有可组装的方程候选。", null);
  }
  if (assembly.state !== "needs_evidence" || assembly.knowledge_unit === null) {
    return emptyResult("invalid_input", assembly.source_ref, assembly.diagnostic ?? "方程候选未能形成有效 KnowledgeUnit。", null);
  }

  const focus = ref({ id: assembly.knowledge_unit.id, revision: assembly.knowledge_unit.revision });
  const candidates = canonicalRefs(assembly.candidate_nodes.map(({ id, revision }) => ({ id, revision })));
  if (focus === null || candidates === null) {
    return emptyResult("invalid_input", assembly.source_ref, "KnowledgeUnit 预览引用无效。", null);
  }

  const projection = projectKnowledge([assembly.knowledge_unit], candidates, [], fixedKnowledgeUnitContractRoot());
  const missingEvidence = validProjection(projection, focus);
  if (missingEvidence === null) {
    return emptyResult("invalid_input", assembly.source_ref, "KnowledgeUnit 预览投影未确认缺失验证证据。", null);
  }

  const steps: FlowStep[] = request.flow_context === "verification"
    ? [{ step_id: "verification-linear-equation", kind: "verification", knowledge_unit_refs: [{ ...focus }] }]
    : [];
  const flowContext: PreviewFlowContext = { persistence: "not_persisted", steps };
  const navigator = createKnowledgeImpactNavigator({ flow: flowContext, projection, focus_ref: focus });
  if (request.flow_context === "verification") {
    if (!validVerificationNavigatorResult(navigator, focus, missingEvidence)) {
      return emptyResult("invalid_input", assembly.source_ref, "预览工程上下文未能只定位 verification 步骤。", null);
    }
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: "needs_evidence",
      source_ref: assembly.source_ref,
      knowledge_unit_ref: { ...focus },
      assembly,
      flow_context: flowContext,
      navigation: navigator.navigation,
      impacted_steps: navigator.impacted_steps,
      missing_evidence_node_refs: missingEvidence,
      diagnostic: null,
    };
  }
  if (!validEmptyNavigatorResult(navigator, focus)) {
    return emptyResult("invalid_input", assembly.source_ref, "预览工程上下文不应生成未关联的 navigation。", null);
  }
  return {
    mode: "preview",
    side_effects: "forbidden",
    state: "empty",
    source_ref: assembly.source_ref,
    knowledge_unit_ref: { ...focus },
    assembly,
    flow_context: flowContext,
    navigation: null,
    impacted_steps: [],
    missing_evidence_node_refs: missingEvidence,
    diagnostic: "当前预览工程上下文没有关联 verification 步骤；不伪造下一步。",
  };
}
export function createLinearEquationVerificationPathPreview(input: unknown): LinearEquationVerificationPathPreview {
  try {
    const request = strictRequest(input);
    if (request === null) return emptyResult("invalid_input", null, "请求必须只包含 plain data source 与 flow_context。", null);
    return completePreview(request);
  } catch {
    return emptyResult("invalid_input", null, "请求未能安全形成验证路径预览。", null);
  }
}
