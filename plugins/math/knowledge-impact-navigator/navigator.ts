import { projectKnowledgeImpacts } from "../../../packages/thoughtflow/src/thoughtflow/knowledge-impact.ts";

export type KnowledgeUnitRef = { id: string; revision: number };

export type KnowledgeImpactNavigatorRequest = {
  flow: unknown;
  projection: unknown;
  focus_ref: KnowledgeUnitRef;
};

export type KnowledgeImpactReason = {
  knowledge_unit_ref: KnowledgeUnitRef;
  status: "blocked" | "needs_evidence";
  missing_prerequisite_refs: KnowledgeUnitRef[];
  missing_evidence_node_refs: KnowledgeUnitRef[];
};

export type KnowledgeImpactNavigatorResult = {
  mode: "preview";
  side_effects: "forbidden";
  state: "blocked" | "needs_evidence" | "ready" | "empty" | "invalid_input";
  focus: KnowledgeUnitRef | null;
  navigation: string | null;
  impacted_steps: Array<{ step_id: string; reasons: KnowledgeImpactReason[] }>;
  reasons: KnowledgeImpactReason[];
};

type JsonObject = Record<string, unknown>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function ref(value: unknown): KnowledgeUnitRef | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== "id,revision") return undefined;
  if (typeof value.id !== "string" || !UUID.test(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1) return undefined;
  return { id: value.id, revision: value.revision };
}

function refKey(value: KnowledgeUnitRef): string {
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}

function copyRef(value: KnowledgeUnitRef): KnowledgeUnitRef {
  return { id: value.id, revision: value.revision };
}

function invalidResult(): KnowledgeImpactNavigatorResult {
  return {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  };
}

function requestFocus(value: unknown): KnowledgeUnitRef | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== "flow,focus_ref,projection") return undefined;
  return ref(value.focus_ref);
}

function succeededImpact(value: unknown): value is {
  object_result: "valid";
  operation_outcome: "succeeded";
  issues: [];
  impacted_steps: Array<{ step_id: string; reasons: unknown[] }>;
} {
  return (
    object(value) &&
    value.object_result === "valid" &&
    value.operation_outcome === "succeeded" &&
    Array.isArray(value.issues) &&
    value.issues.length === 0 &&
    Array.isArray(value.impacted_steps)
  );
}

type ProjectionUnit = {
  ref: KnowledgeUnitRef;
  status: "blocked" | "needs_evidence" | "ready";
};

const PROJECTION_UNIT_FIELDS = "missing_evidence_node_refs,missing_prerequisite_refs,ref,status";

function projectionUnits(projection: unknown): ProjectionUnit[] | undefined {
  if (!object(projection) || !Array.isArray(projection.units)) return undefined;

  const units: ProjectionUnit[] = [];
  const keys: string[] = [];
  for (const unit of projection.units) {
    if (!object(unit) || Object.keys(unit).sort().join(",") !== PROJECTION_UNIT_FIELDS) return undefined;

    const unitRef = ref(unit.ref);
    const prerequisites = canonicalRefs(unit.missing_prerequisite_refs);
    const evidence = canonicalRefs(unit.missing_evidence_node_refs);
    const status = unit.status;
    if (unitRef === undefined || prerequisites === undefined || evidence === undefined) return undefined;
    if (status === "ready" && (prerequisites.length !== 0 || evidence.length !== 0)) return undefined;
    if (status === "blocked" && prerequisites.length === 0) return undefined;
    if (status === "needs_evidence" && (prerequisites.length !== 0 || evidence.length === 0)) return undefined;
    if (status !== "blocked" && status !== "needs_evidence" && status !== "ready") return undefined;

    units.push({ ref: copyRef(unitRef), status });
    keys.push(refKey(unitRef));
  }

  const sorted = [...keys].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  if (new Set(keys).size !== keys.length || !keys.every((key, index) => key === sorted[index])) return undefined;
  return units;
}

function focusProjectionUnit(units: ProjectionUnit[], focusRef: KnowledgeUnitRef): { status: "blocked" | "needs_evidence" | "ready" } | undefined {
  const matching = units.filter((unit) => refKey(unit.ref) === refKey(focusRef));
  if (matching.length !== 1) return undefined;
  return { status: matching[0].status };
}

function focusAppearsInFlow(flow: unknown, focusRef: KnowledgeUnitRef): boolean {
  if (!object(flow) || !Array.isArray(flow.steps)) return false;
  const focusKey = refKey(focusRef);
  return flow.steps.some((step) => {
    if (!object(step) || !Array.isArray(step.knowledge_unit_refs)) return false;
    const direct = step.knowledge_unit_refs.some((candidate) => {
      const candidateRef = ref(candidate);
      return candidateRef !== undefined && refKey(candidateRef) === focusKey;
    });
    const behavior = step.kind === "operation" && object(step.behavior_ref) ? ref(step.behavior_ref.knowledge_unit_ref) : undefined;
    return direct || (behavior !== undefined && refKey(behavior) === focusKey);
  });
}

function canonicalRefs(value: unknown): KnowledgeUnitRef[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const refs = value.map(ref);
  if (refs.some((candidate) => candidate === undefined)) return undefined;
  const keys = (refs as KnowledgeUnitRef[]).map(refKey);
  const sorted = [...keys].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  if (new Set(keys).size !== keys.length || !keys.every((key, index) => key === sorted[index])) return undefined;
  return (refs as KnowledgeUnitRef[]).map(copyRef);
}

function reason(value: unknown): KnowledgeImpactReason | undefined {
  if (!object(value)) return undefined;
  const knowledgeUnitRef = ref(value.knowledge_unit_ref);
  if (knowledgeUnitRef === undefined || (value.status !== "blocked" && value.status !== "needs_evidence")) return undefined;
  const prerequisites = canonicalRefs(value.missing_prerequisite_refs);
  const evidence = canonicalRefs(value.missing_evidence_node_refs);
  if (prerequisites === undefined || evidence === undefined) return undefined;
  if (value.status === "blocked" && prerequisites.length === 0) return undefined;
  if (value.status === "needs_evidence" && (prerequisites.length !== 0 || evidence.length === 0)) return undefined;
  return {
    knowledge_unit_ref: copyRef(knowledgeUnitRef),
    status: value.status,
    missing_prerequisite_refs: prerequisites,
    missing_evidence_node_refs: evidence,
  };
}

function focusedImpacts(
  impacts: Array<{ step_id: string; reasons: unknown[] }>,
  focusRef: KnowledgeUnitRef,
): Array<{ step_id: string; reasons: KnowledgeImpactReason[] }> | undefined {
  const focusKey = refKey(focusRef);
  const focused = [] as Array<{ step_id: string; reasons: KnowledgeImpactReason[] }>;
  for (const impact of impacts) {
    if (!object(impact) || typeof impact.step_id !== "string" || !Array.isArray(impact.reasons)) return undefined;
    const reasons = impact.reasons.map(reason);
    if (reasons.some((candidate) => candidate === undefined)) return undefined;
    const matching = (reasons as KnowledgeImpactReason[]).filter((candidate) => refKey(candidate.knowledge_unit_ref) === focusKey);
    if (matching.length > 0) focused.push({ step_id: impact.step_id, reasons: matching });
  }
  return focused;
}

function distinctReasons(steps: Array<{ step_id: string; reasons: KnowledgeImpactReason[] }>): KnowledgeImpactReason[] {
  const byRef = new Map<string, KnowledgeImpactReason>();
  for (const step of steps) {
    for (const item of step.reasons) byRef.set(refKey(item.knowledge_unit_ref), item);
  }
  return [...byRef.entries()].sort(([left], [right]) => Buffer.compare(Buffer.from(left), Buffer.from(right))).map(([, item]) => item);
}

export function createKnowledgeImpactNavigator(request: KnowledgeImpactNavigatorRequest): KnowledgeImpactNavigatorResult;
export function createKnowledgeImpactNavigator(request: unknown): KnowledgeImpactNavigatorResult {
  const focusRef = requestFocus(request);
  if (focusRef === undefined || !object(request)) return invalidResult();

  const impact = projectKnowledgeImpacts(request.flow, request.projection);
  if (!succeededImpact(impact)) return invalidResult();

  const units = projectionUnits(request.projection);
  if (units === undefined) return invalidResult();

  const projectionUnit = focusProjectionUnit(units, focusRef);
  if (projectionUnit === undefined) return invalidResult();

  const impacts = focusedImpacts(impact.impacted_steps, focusRef);
  if (impacts === undefined) return invalidResult();

  if (projectionUnit.status === "ready") {
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: focusAppearsInFlow(request.flow, focusRef) ? "ready" : "empty",
      focus: copyRef(focusRef),
      navigation: null,
      impacted_steps: [],
      reasons: [],
    };
  }

  if (impacts.length === 0) {
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: "empty",
      focus: copyRef(focusRef),
      navigation: null,
      impacted_steps: [],
      reasons: [],
    };
  }

  const reasons = distinctReasons(impacts);
  if (reasons.length !== 1 || reasons[0].status !== projectionUnit.status) return invalidResult();

  return {
    mode: "preview",
    side_effects: "forbidden",
    state: projectionUnit.status,
    focus: copyRef(focusRef),
    navigation:
      projectionUnit.status === "blocked"
        ? "先完成缺失前置知识，再继续受影响的 analysis / operation 步骤。"
        : "返回 verification 步骤补充缺失证据。",
    impacted_steps: impacts,
    reasons,
  };
}
