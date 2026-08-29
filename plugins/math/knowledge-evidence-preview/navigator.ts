import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { projectKnowledge } from "../../../packages/knowledge-units/src/knowledge-unit/project.ts";
import { validateUnit } from "../../../packages/knowledge-units/src/knowledge-unit/runtime.ts";
import { projectKnowledgeImpacts } from "../../../packages/thoughtflow/src/thoughtflow/knowledge-impact.ts";

export type KnowledgeUnitRef = { id: string; revision: number };
type EvidenceStatus = "satisfied" | "missing";

type ValidationPreview = {
  validation_id: string;
  description: string;
  evidence_node_refs: KnowledgeUnitRef[];
  missing_evidence_node_refs: KnowledgeUnitRef[];
  status: EvidenceStatus;
};

type MasteryCriterionPreview = {
  criterion_id: string;
  statement: string;
  evidence_node_refs: KnowledgeUnitRef[];
  missing_evidence_node_refs: KnowledgeUnitRef[];
  status: EvidenceStatus;
};

export type KnowledgeEvidencePreviewResult = {
  mode: "preview";
  side_effects: "forbidden";
  state: "blocked" | "needs_evidence" | "ready" | "empty" | "invalid_input";
  focus: KnowledgeUnitRef | null;
  navigation: string | null;
  validations: ValidationPreview[];
  mastery_criteria: MasteryCriterionPreview[];
  verification_steps: string[];
  impacted_steps: string[];
};

type JsonObject = Record<string, unknown>;
type RefKey = string;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const REQUEST_FIELDS = "available_node_refs,contract_root,evidence_node_refs,flow,focus_ref,unit";
const FIXED_CONTRACT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../packages/knowledge-units/contracts/knowledge-unit/1.0.0");

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function compareBytes(left: string, right: string) {
  return Buffer.compare(Buffer.from(left), Buffer.from(right));
}

function ref(value: unknown): KnowledgeUnitRef | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== "id,revision") return undefined;
  if (typeof value.id !== "string" || !UUID.test(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1) return undefined;
  return { id: value.id, revision: value.revision };
}

function refKey(value: KnowledgeUnitRef): RefKey {
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}

function copyRef(value: KnowledgeUnitRef): KnowledgeUnitRef {
  return { id: value.id, revision: value.revision };
}

function canonicalRefs(value: unknown): KnowledgeUnitRef[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const refs = value.map(ref);
  if (refs.some((item) => item === undefined)) return undefined;
  const concrete = refs as KnowledgeUnitRef[];
  const keys = concrete.map(refKey);
  const sorted = [...keys].sort(compareBytes);
  if (new Set(keys).size !== keys.length || !keys.every((key, index) => key === sorted[index])) return undefined;
  return concrete.map(copyRef);
}

function invalidResult(): KnowledgeEvidencePreviewResult {
  return {
    mode: "preview", side_effects: "forbidden", state: "invalid_input", focus: null,
    navigation: null, validations: [], mastery_criteria: [], verification_steps: [], impacted_steps: [],
  };
}

function requestParts(value: unknown): {
  unit: JsonObject; available: KnowledgeUnitRef[]; evidence: KnowledgeUnitRef[]; flow: unknown; focus: KnowledgeUnitRef;
} | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== REQUEST_FIELDS) return undefined;
  if (!object(value.unit) || typeof value.contract_root !== "string" || resolve(value.contract_root) !== FIXED_CONTRACT_ROOT) return undefined;
  const available = canonicalRefs(value.available_node_refs);
  const evidence = canonicalRefs(value.evidence_node_refs);
  const focus = ref(value.focus_ref);
  if (available === undefined || evidence === undefined || focus === undefined) return undefined;
  return { unit: value.unit, available, evidence, flow: value.flow, focus };
}

function producedProjection(value: unknown, focus: KnowledgeUnitRef): { status: "blocked" | "needs_evidence" | "ready" } | undefined {
  if (!object(value) || value.object_result !== "valid" || value.operation_outcome !== "succeeded" || !Array.isArray(value.issues) || value.issues.length !== 0 || !Array.isArray(value.units) || value.units.length !== 1) return undefined;
  const unit = value.units[0];
  if (!object(unit) || Object.keys(unit).sort().join(",") !== "missing_evidence_node_refs,missing_prerequisite_refs,ref,status") return undefined;
  const projectedRef = ref(unit.ref);
  const prerequisites = canonicalRefs(unit.missing_prerequisite_refs);
  const evidence = canonicalRefs(unit.missing_evidence_node_refs);
  if (projectedRef === undefined || refKey(projectedRef) !== refKey(focus) || prerequisites === undefined || evidence === undefined) return undefined;
  if (unit.status === "blocked" && prerequisites.length > 0) return { status: "blocked" };
  if (unit.status === "needs_evidence" && prerequisites.length === 0 && evidence.length > 0) return { status: "needs_evidence" };
  if (unit.status === "ready" && prerequisites.length === 0 && evidence.length === 0) return { status: "ready" };
  return undefined;
}

function canonicalFlow(value: unknown): boolean {
  if (!object(value) || !Array.isArray(value.steps)) return false;
  for (const step of value.steps) {
    if (!object(step) || typeof step.step_id !== "string" || typeof step.kind !== "string" || canonicalRefs(step.knowledge_unit_refs) === undefined) return false;
    if (step.kind === "operation" && (!object(step.behavior_ref) || ref(step.behavior_ref.knowledge_unit_ref) === undefined)) return false;
  }
  return true;
}
function validImpact(value: unknown): value is { impacted_steps: Array<{ step_id: string; reasons: unknown[] }> } {
  return object(value) && value.object_result === "valid" && value.operation_outcome === "succeeded" && Array.isArray(value.issues) && value.issues.length === 0 && Array.isArray(value.impacted_steps);
}

function focusedStepIds(impact: { impacted_steps: Array<{ step_id: string; reasons: unknown[] }> }, focus: KnowledgeUnitRef): string[] | undefined {
  const steps: string[] = [];
  for (const step of impact.impacted_steps) {
    if (!object(step) || typeof step.step_id !== "string" || !Array.isArray(step.reasons)) return undefined;
    for (const reason of step.reasons) {
      if (!object(reason) || ref(reason.knowledge_unit_ref) === undefined) return undefined;
      if (refKey(ref(reason.knowledge_unit_ref)!) === refKey(focus)) {
        steps.push(step.step_id);
        break;
      }
    }
  }
  return [...new Set(steps)].sort(compareBytes);
}

function missingRefs(evidenceRefs: KnowledgeUnitRef[], evidence: Set<RefKey>): KnowledgeUnitRef[] {
  return evidenceRefs.filter((item) => !evidence.has(refKey(item))).map(copyRef);
}

function evidenceRows(unit: JsonObject, evidence: Set<RefKey>): { validations: ValidationPreview[]; mastery_criteria: MasteryCriterionPreview[] } | undefined {
  if (!Array.isArray(unit.validations) || !Array.isArray(unit.mastery_criteria)) return undefined;
  const validations: ValidationPreview[] = [];
  for (const validation of unit.validations) {
    if (!object(validation) || typeof validation.validation_id !== "string" || typeof validation.description !== "string") return undefined;
    const refs = canonicalRefs(validation.evidence_node_refs);
    if (refs === undefined) return undefined;
    const missing = missingRefs(refs, evidence);
    validations.push({ validation_id: validation.validation_id, description: validation.description, evidence_node_refs: refs, missing_evidence_node_refs: missing, status: missing.length === 0 ? "satisfied" : "missing" });
  }
  const mastery_criteria: MasteryCriterionPreview[] = [];
  for (const criterion of unit.mastery_criteria) {
    if (!object(criterion) || typeof criterion.criterion_id !== "string" || typeof criterion.statement !== "string") return undefined;
    const refs = canonicalRefs(criterion.evidence_node_refs);
    if (refs === undefined) return undefined;
    const missing = missingRefs(refs, evidence);
    mastery_criteria.push({ criterion_id: criterion.criterion_id, statement: criterion.statement, evidence_node_refs: refs, missing_evidence_node_refs: missing, status: missing.length === 0 ? "satisfied" : "missing" });
  }
  return { validations, mastery_criteria };
}

export function fixedKnowledgeUnitContractRoot(): string {
  return FIXED_CONTRACT_ROOT;
}

export function createKnowledgeEvidencePreview(request: unknown): KnowledgeEvidencePreviewResult {
  try {
    const parts = requestParts(request);
    if (parts === undefined) return invalidResult();
    if (validateUnit(parts.unit, parts.available, FIXED_CONTRACT_ROOT).object_result !== "valid") return invalidResult();
    const unitIdentity = ref({ id: parts.unit.id, revision: parts.unit.revision });
    if (unitIdentity === undefined || refKey(unitIdentity) !== refKey(parts.focus)) return invalidResult();

    if (!canonicalFlow(parts.flow)) return invalidResult();
    const projection = projectKnowledge([parts.unit], parts.available, parts.evidence, FIXED_CONTRACT_ROOT);
    const status = producedProjection(projection, parts.focus);
    if (status === undefined) return invalidResult();
    const impact = projectKnowledgeImpacts(parts.flow, projection);
    if (!validImpact(impact)) return invalidResult();
    const impactedSteps = focusedStepIds(impact, parts.focus);
    const rows = evidenceRows(parts.unit, new Set(parts.evidence.map(refKey)));
    if (impactedSteps === undefined || rows === undefined) return invalidResult();

    if (status.status === "ready") {
      return { mode: "preview", side_effects: "forbidden", state: "ready", focus: copyRef(parts.focus), navigation: null, ...rows, verification_steps: [], impacted_steps: [] };
    }
    if (impactedSteps.length === 0) {
      return { mode: "preview", side_effects: "forbidden", state: "empty", focus: copyRef(parts.focus), navigation: null, ...rows, verification_steps: [], impacted_steps: [] };
    }
    if (status.status === "blocked") {
      return { mode: "preview", side_effects: "forbidden", state: "blocked", focus: copyRef(parts.focus), navigation: "先完成缺失前置知识，再继续查看验证要求。", ...rows, verification_steps: [], impacted_steps: impactedSteps };
    }
    return { mode: "preview", side_effects: "forbidden", state: "needs_evidence", focus: copyRef(parts.focus), navigation: "返回 verification 步骤补充缺失工程证据。", ...rows, verification_steps: impactedSteps, impacted_steps: impactedSteps };
  } catch {
    return invalidResult();
  }
}
