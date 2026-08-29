type JsonObject = Record<string, any>;
type RefKey = string;

const unitFields = ["missing_evidence_node_refs", "missing_prerequisite_refs", "ref", "status"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function compareBytes(left: string, right: string) {
  return Buffer.compare(Buffer.from(left), Buffer.from(right));
}

function issue(code: string, path: string) {
  return { code, path, severity: "error" };
}

function notEvaluated(code: string, path: string) {
  return { object_result: "not_evaluated", operation_outcome: "indeterminate", issues: [issue(code, path)], impacted_steps: [] };
}

function refKey(value: unknown): RefKey | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== "id,revision") return undefined;
  if (typeof value.id !== "string" || !UUID.test(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1) return undefined;
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}

function refFromKey(key: RefKey) {
  const [id, revision] = key.split("\u0000");
  return { id, revision: Number(revision) };
}

function refList(value: unknown): RefKey[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const keys = value.map(refKey);
  return keys.some((key) => key === undefined) ? undefined : keys as RefKey[];
}

function canonicalKeys(keys: RefKey[]) {
  const sorted = [...keys].sort(compareBytes);
  return new Set(keys).size === keys.length && keys.every((key, index) => key === sorted[index]);
}

function canonicalRefSet(value: unknown): RefKey[] | undefined {
  const keys = refList(value);
  return keys === undefined || !canonicalKeys(keys) ? undefined : keys;
}

function projectionReasons(projection: unknown): Map<RefKey, JsonObject> | undefined {
  if (!object(projection) || projection.object_result !== "valid" || projection.operation_outcome !== "succeeded" || !Array.isArray(projection.issues) || projection.issues.length !== 0 || !Array.isArray(projection.units)) return undefined;
  const reasons = new Map<RefKey, JsonObject>(), unitRefs: RefKey[] = [];
  for (const unit of projection.units) {
    if (!object(unit) || Object.keys(unit).sort().join(",") !== unitFields.join(",")) return undefined;
    const key = refKey(unit.ref), prerequisites = canonicalRefSet(unit.missing_prerequisite_refs), evidence = canonicalRefSet(unit.missing_evidence_node_refs);
    if (key === undefined || prerequisites === undefined || evidence === undefined || !["blocked", "needs_evidence", "ready"].includes(unit.status) || reasons.has(key)) return undefined;
    unitRefs.push(key);
    reasons.set(key, {
      knowledge_unit_ref: refFromKey(key), status: unit.status,
      missing_prerequisite_refs: prerequisites.map(refFromKey),
      missing_evidence_node_refs: evidence.map(refFromKey),
    });
  }
  return canonicalKeys(unitRefs) ? reasons : undefined;
}

export function projectKnowledgeImpacts(flow: unknown, projection: unknown) {
  const reasonsByRef = projectionReasons(projection);
  if (reasonsByRef === undefined) return notEvaluated("thoughtflow.knowledge_impact.invalid_projection", "/projection");
  if (!object(flow) || !Array.isArray(flow.steps)) return notEvaluated("thoughtflow.knowledge_impact.invalid_flow", "/flow/steps");

  const impacts = new Map<string, Map<RefKey, JsonObject>>();
  for (let index = 0; index < flow.steps.length; index += 1) {
    const step = flow.steps[index], path = `/flow/steps/${index}`;
    if (!object(step) || typeof step.step_id !== "string" || typeof step.kind !== "string") return notEvaluated("thoughtflow.knowledge_impact.invalid_flow", path);
    const refs = refList(step.knowledge_unit_refs);
    if (refs === undefined) return notEvaluated("thoughtflow.knowledge_impact.invalid_flow", `${path}/knowledge_unit_refs`);
    if (step.kind === "operation") {
      const behaviorRef = object(step.behavior_ref) ? refKey(step.behavior_ref.knowledge_unit_ref) : undefined;
      if (behaviorRef === undefined) return notEvaluated("thoughtflow.knowledge_impact.invalid_flow", `${path}/behavior_ref/knowledge_unit_ref`);
      refs.push(behaviorRef);
    }
    const expectedStatus = ["analysis", "operation"].includes(step.kind) ? "blocked" : step.kind === "verification" ? "needs_evidence" : undefined;
    if (expectedStatus === undefined) continue;
    for (const ref of new Set(refs)) {
      const reason = reasonsByRef.get(ref);
      if (reason?.status === expectedStatus) {
        if (!impacts.has(step.step_id)) impacts.set(step.step_id, new Map());
        impacts.get(step.step_id)!.set(ref, reason);
      }
    }
  }
  const impacted_steps = [...impacts.entries()].sort(([left], [right]) => compareBytes(left, right)).map(([step_id, byRef]) => ({
    step_id,
    reasons: [...byRef.entries()].sort(([left], [right]) => compareBytes(left, right)).map(([, reason]) => reason),
  }));
  return { object_result: "valid", operation_outcome: "succeeded", issues: [], impacted_steps };
}