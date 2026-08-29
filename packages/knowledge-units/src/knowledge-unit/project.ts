import { validateUnit } from "./runtime.ts";


type JsonObject = Record<string, any>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;


function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}


function issue(code: string, path: string) {
  return { code, path, severity: "error" };
}


function result(valid: boolean, issues: JsonObject[], units: JsonObject[] = [],
                nodeDependents: JsonObject[] = [], unitDependents: JsonObject[] = []) {
  return {
    object_result: valid ? "valid" : "invalid",
    operation_outcome: "succeeded",
    issues,
    units,
    node_dependents: nodeDependents,
    unit_dependents: unitDependents,
  };
}


function compareBytes(left: string, right: string) {
  return Buffer.compare(Buffer.from(left), Buffer.from(right));
}


function refKey(value: unknown): string | undefined {
  if (!object(value) || Object.keys(value).sort().join(",") !== "id,revision") return undefined;
  if (typeof value.id !== "string" || !UUID.test(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1) return undefined;
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}


function refFromKey(key: string) {
  const [id, revision] = key.split("\u0000");
  return { id, revision: Number(revision) };
}


function canonicalRefSet(values: unknown): string[] | undefined {
  if (!Array.isArray(values)) return undefined;
  const keys = values.map(refKey);
  if (keys.some((key) => key === undefined)) return undefined;
  const concrete = keys as string[];
  const sorted = [...concrete].sort(compareBytes);
  return new Set(concrete).size === concrete.length && concrete.every((key, index) => key === sorted[index])
    ? concrete
    : undefined;
}


function collectNodeRefs(unit: JsonObject) {
  const values: unknown[] = [];
  values.push(...unit.concept_boundary.focus_node_refs);
  for (const objective of unit.learning_objectives) values.push(...objective.target_node_refs);
  for (const binding of unit.node_bindings) values.push(binding.node_ref);
  for (const behavior of unit.behaviors) {
    values.push(...behavior.input_node_refs);
    values.push(...behavior.output_node_refs);
  }
  for (const validation of unit.validations) {
    values.push(...validation.subject_node_refs);
    values.push(...validation.evidence_node_refs);
  }
  for (const criterion of unit.mastery_criteria) values.push(...criterion.evidence_node_refs);
  return new Set(values.map(refKey).filter((key): key is string => key !== undefined));
}


function requiredEvidenceRefs(unit: JsonObject) {
  const values: unknown[] = [];
  for (const validation of unit.validations) values.push(...validation.evidence_node_refs);
  for (const criterion of unit.mastery_criteria) values.push(...criterion.evidence_node_refs);
  return new Set(values.map(refKey).filter((key): key is string => key !== undefined));
}


function hasCycle(edges: Map<string, Set<string>>) {
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (node: string): boolean => {
    if (visiting.has(node)) return true;
    if (visited.has(node)) return false;
    visiting.add(node);
    for (const child of edges.get(node) ?? []) if (visit(child)) return true;
    visiting.delete(node);
    visited.add(node);
    return false;
  };
  return [...edges.keys()].sort(compareBytes).some(visit);
}


function closure(start: string, edges: Map<string, Set<string>>) {
  const seen = new Set<string>();
  const pending = [...(edges.get(start) ?? [])];
  while (pending.length > 0) {
    const current = pending.pop()!;
    if (!seen.has(current)) {
      seen.add(current);
      for (const next of edges.get(current) ?? []) if (!seen.has(next)) pending.push(next);
    }
  }
  return [...seen].sort(compareBytes);
}


export function projectKnowledge(units: unknown, availableNodeRefs: unknown, evidenceNodeRefs: unknown,
                                 contractRoot: string) {
  const available = canonicalRefSet(availableNodeRefs);
  if (available === undefined) return result(false, [issue("knowledge_project.noncanonical_set", "/available_node_refs")]);
  const evidence = canonicalRefSet(evidenceNodeRefs);
  if (evidence === undefined) return result(false, [issue("knowledge_project.noncanonical_set", "/evidence_node_refs")]);
  if (!Array.isArray(units)) return result(false, [issue("knowledge_project.invalid_unit", "/units")]);

  const identities: string[] = [];
  const byRef = new Map<string, JsonObject>();
  for (let index = 0; index < units.length; index += 1) {
    const unit = units[index];
    if (validateUnit(unit, availableNodeRefs, contractRoot).object_result !== "valid") {
      return result(false, [issue("knowledge_project.invalid_unit", `/units/${index}`)]);
    }
    const record = unit as JsonObject;
    const identity = refKey({ id: record.id, revision: record.revision })!;
    if (byRef.has(identity)) return result(false, [issue("knowledge_project.duplicate_unit_ref", `/units/${index}`)]);
    identities.push(identity);
    byRef.set(identity, record);
  }
  if (!identities.every((key, index) => key === [...identities].sort(compareBytes)[index])) {
    return result(false, [issue("knowledge_project.noncanonical_set", "/units")]);
  }

  const prerequisiteEdges = new Map(identities.map((key) => [key, new Set<string>()]));
  const reverse = new Map(identities.map((key) => [key, new Set<string>()]));
  const missing = new Map(identities.map((key) => [key, [] as string[]]));
  for (const key of identities) {
    for (const reference of byRef.get(key)!.prerequisite_unit_refs) {
      const prerequisite = refKey(reference)!;
      if (byRef.has(prerequisite)) {
        prerequisiteEdges.get(key)!.add(prerequisite);
        reverse.get(prerequisite)!.add(key);
      } else {
        missing.get(key)!.push(prerequisite);
      }
    }
    missing.get(key)!.sort(compareBytes);
  }
  if (hasCycle(prerequisiteEdges)) {
    return result(false, [issue("knowledge_project.prerequisite_cycle", "/units")]);
  }

  const evidenceSet = new Set(evidence);
  const nodeUsers = new Map<string, Set<string>>();
  const projectedUnits = identities.map((key) => {
    const unit = byRef.get(key)!;
    for (const nodeRef of collectNodeRefs(unit)) {
      if (!nodeUsers.has(nodeRef)) nodeUsers.set(nodeRef, new Set());
      nodeUsers.get(nodeRef)!.add(key);
    }
    const status = missing.get(key)!.length > 0
      ? "blocked"
      : [...requiredEvidenceRefs(unit)].every((ref) => evidenceSet.has(ref))
        ? "ready"
        : "needs_evidence";
    return {
      unit_ref: refFromKey(key),
      status,
      missing_prerequisite_unit_refs: missing.get(key)!.map(refFromKey),
    };
  });

  const nodeDependents = [...nodeUsers.entries()]
    .sort(([left], [right]) => compareBytes(left, right))
    .map(([nodeRef, users]) => ({
      node_ref: refFromKey(nodeRef),
      unit_refs: [...users].sort(compareBytes).map(refFromKey),
    }));
  const unitDependents = identities.map((key) => ({
    unit_ref: refFromKey(key),
    dependent_unit_refs: closure(key, reverse).map(refFromKey),
  }));
  return result(true, [], projectedUnits, nodeDependents, unitDependents);
}
