import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { projectKnowledge } from "../../../packages/knowledge-units/src/knowledge-unit/project.ts";

type JsonObject = Record<string, unknown>;
export type KnowledgeUnitRef = { id: string; revision: number };
type ProjectedUnit = {
  ref: KnowledgeUnitRef;
  status: "blocked" | "needs_evidence" | "ready";
  missing_prerequisite_refs: KnowledgeUnitRef[];
  missing_evidence_node_refs: KnowledgeUnitRef[];
};
type PrerequisiteEdge = { prerequisite_unit_ref: KnowledgeUnitRef; dependent_unit_ref: KnowledgeUnitRef };
export type KnowledgeProjectMapPreview = {
  mode: "preview";
  side_effects: "forbidden";
  state: "valid" | "empty" | "invalid_input";
  units: ProjectedUnit[];
  prerequisite_edges: PrerequisiteEdge[];
  external_prerequisite_refs: KnowledgeUnitRef[];
  selected_node_ref: KnowledgeUnitRef | null;
  affected_unit_refs: KnowledgeUnitRef[];
  diagnostic: string;
};
type DemoCase = {
  units: JsonObject[];
  available_node_refs: KnowledgeUnitRef[];
  evidence_node_refs: KnowledgeUnitRef[];
  default_selected_node_ref: KnowledgeUnitRef;
};
type DemoSuite = { cases: Record<"normal" | "blocked" | "empty", DemoCase> };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CONTRACT_ROOT = fileURLToPath(new URL("../../../packages/knowledge-units/contracts/knowledge-unit/1.0.0/", import.meta.url));
const FIXTURE_PATH = fileURLToPath(new URL("./fixtures/demo-cases.json", import.meta.url));

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function plainObject(value: unknown): value is JsonObject {
  return object(value) && Object.getPrototypeOf(value) === Object.prototype;
}

function ownData(value: JsonObject, key: string): unknown {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor !== undefined && descriptor.enumerable && "value" in descriptor ? descriptor.value : undefined;
}

function exactKeys(value: unknown, keys: readonly string[]): value is JsonObject {
  if (!plainObject(value)) return false;
  const actual = Reflect.ownKeys(value);
  return actual.length === keys.length
    && actual.every((key) => typeof key === "string" && keys.includes(key))
    && keys.every((key) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      return descriptor !== undefined && descriptor.enumerable && "value" in descriptor;
    });
}

function compareBytes(left: string, right: string): number {
  return Buffer.compare(Buffer.from(left), Buffer.from(right));
}

function ref(value: unknown): KnowledgeUnitRef | null {
  if (!exactKeys(value, ["id", "revision"])) return null;
  const id = ownData(value, "id");
  const revision = ownData(value, "revision");
  if (typeof id !== "string" || !UUID.test(id) || !Number.isSafeInteger(revision) || revision < 1) return null;
  return { id, revision };
}

function refKey(value: KnowledgeUnitRef): string {
  return `${value.id}\u0000${String(value.revision).padStart(16, "0")}`;
}

function copyRef(value: KnowledgeUnitRef): KnowledgeUnitRef {
  return { id: value.id, revision: value.revision };
}

function plainArray(value: unknown): value is unknown[] {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) return false;
  const keys = Reflect.ownKeys(value);
  return keys.length === value.length + 1
    && keys.every((key) => key === "length" || (typeof key === "string" && /^(0|[1-9][0-9]*)$/.test(key)))
    && Array.from({ length: value.length }, (_, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      return descriptor !== undefined && descriptor.enumerable && "value" in descriptor;
    }).every(Boolean);
}

function refs(value: unknown): KnowledgeUnitRef[] | null {
  if (!plainArray(value)) return null;
  const copied = value.map(ref);
  if (copied.some((item) => item === null)) return null;
  const concrete = copied as KnowledgeUnitRef[];
  const keys = concrete.map(refKey);
  const sorted = [...keys].sort(compareBytes);
  if (new Set(keys).size !== keys.length || !keys.every((key, index) => key === sorted[index])) return null;
  return concrete.map(copyRef);
}

function plainDataEqual(expected: unknown, actual: unknown): boolean {
  if (expected === null || typeof expected !== "object") return Object.is(expected, actual);
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || Object.getPrototypeOf(actual) !== Array.prototype || expected.length !== actual.length) return false;
    const keys = Reflect.ownKeys(actual);
    if (keys.length !== expected.length + 1 || keys.some((key) => key !== "length" && (typeof key !== "string" || !/^(0|[1-9][0-9]*)$/.test(key)))) return false;
    return expected.every((item, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(actual, String(index));
      return descriptor !== undefined && "value" in descriptor && plainDataEqual(item, descriptor.value);
    });
  }
  if (!plainObject(expected) || !plainObject(actual)) return false;
  const keys = Object.keys(expected);
  return exactKeys(actual, keys) && keys.every((key) => plainDataEqual(ownData(expected, key), ownData(actual, key)));
}

function suite(): DemoSuite {
  return JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as DemoSuite;
}

function demo(caseId: "normal" | "blocked" | "empty"): DemoCase | null {
  try {
    const candidate = suite().cases?.[caseId];
    if (!candidate || !Array.isArray(candidate.units) || refs(candidate.available_node_refs) === null
      || refs(candidate.evidence_node_refs) === null || ref(candidate.default_selected_node_ref) === null) return null;
    return structuredClone(candidate);
  } catch {
    return null;
  }
}

type Projection = {
  object_result: "valid";
  operation_outcome: "succeeded";
  issues: [];
  units: ProjectedUnit[];
  node_dependents: Array<{ node_ref: KnowledgeUnitRef; unit_refs: KnowledgeUnitRef[] }>;
  unit_dependents: Array<{ unit_ref: KnowledgeUnitRef; dependent_unit_refs: KnowledgeUnitRef[] }>;
};

function validProjection(value: unknown): value is Projection {
  if (!exactKeys(value, ["object_result", "operation_outcome", "issues", "units", "node_dependents", "unit_dependents"])
    || ownData(value, "object_result") !== "valid" || ownData(value, "operation_outcome") !== "succeeded") return false;
  const issues = ownData(value, "issues");
  const units = projectedUnits(ownData(value, "units"));
  const nodeDependents = ownData(value, "node_dependents");
  const unitDependents = ownData(value, "unit_dependents");
  if (!plainArray(issues) || issues.length !== 0 || units === null || !plainArray(nodeDependents) || !plainArray(unitDependents)) return false;

  const unitKeys = units.map((unit) => refKey(unit.ref));
  const unitSet = new Set(unitKeys);
  if (units.some((unit) => unit.missing_prerequisite_refs.some((candidate) => unitSet.has(refKey(candidate))))) return false;

  const nodeKeys: string[] = [];
  for (const item of nodeDependents) {
    if (!exactKeys(item, ["node_ref", "unit_refs"])) return false;
    const node = ref(ownData(item, "node_ref"));
    const users = refs(ownData(item, "unit_refs"));
    if (node === null || users === null || users.length === 0 || users.some((user) => !unitSet.has(refKey(user)))) return false;
    nodeKeys.push(refKey(node));
  }
  const sortedNodes = [...nodeKeys].sort(compareBytes);
  if (new Set(nodeKeys).size !== nodeKeys.length || !nodeKeys.every((key, index) => key === sortedNodes[index])) return false;

  const dependentKeys: string[] = [];
  for (const item of unitDependents) {
    if (!exactKeys(item, ["unit_ref", "dependent_unit_refs"])) return false;
    const unit = ref(ownData(item, "unit_ref"));
    const dependents = refs(ownData(item, "dependent_unit_refs"));
    if (unit === null || dependents === null || !unitSet.has(refKey(unit))
      || dependents.some((dependent) => !unitSet.has(refKey(dependent))) || dependents.some((dependent) => refKey(dependent) === refKey(unit))) return false;
    dependentKeys.push(refKey(unit));
  }
  return dependentKeys.length === unitKeys.length
    && new Set(dependentKeys).size === dependentKeys.length
    && dependentKeys.every((key, index) => key === unitKeys[index]);
}
export function validProjectionForDemo(caseId: "normal" | "blocked" | "empty", candidate: unknown): boolean {
  try {
    const selected = demo(caseId);
    if (selected === null) return false;
    const actual = projectKnowledge(selected.units, selected.available_node_refs, selected.evidence_node_refs, CONTRACT_ROOT);
    return validProjection(actual) && validProjection(candidate) && plainDataEqual(actual, candidate);
  } catch {
    return false;
  }
}

function invalidResult(): KnowledgeProjectMapPreview {
  return {
    mode: "preview", side_effects: "forbidden", state: "invalid_input", units: [], prerequisite_edges: [], external_prerequisite_refs: [],
    selected_node_ref: null, affected_unit_refs: [], diagnostic: "请求必须是固定案例与可选的现有 CognitiveNode plain data。",
  };
}

function request(value: unknown): { caseId: "normal" | "blocked" | "empty" | "invalid"; selected: KnowledgeUnitRef | null } | null {
  if (!plainObject(value)) return null;
  const keys = Reflect.ownKeys(value);
  if (keys.some((key) => typeof key !== "string") || (keys.length !== 1 && keys.length !== 2) || !keys.includes("case")
    || (keys.length === 2 && !keys.includes("selected_node_ref"))) return null;
  const caseId = ownData(value, "case");
  if (caseId !== "normal" && caseId !== "blocked" && caseId !== "empty" && caseId !== "invalid") return null;
  const selected = keys.length === 2 ? ref(ownData(value, "selected_node_ref")) : null;
  if (keys.length === 2 && selected === null) return null;
  return { caseId, selected };
}

function prerequisiteEdges(projection: Projection): PrerequisiteEdge[] | null {
  const descendants = new Map(projection.unit_dependents.map((item) => [refKey(item.unit_ref), new Set(item.dependent_unit_refs.map(refKey))]));
  if (descendants.size !== projection.units.length) return null;
  const edges: PrerequisiteEdge[] = [];
  for (const source of projection.unit_dependents) {
    const sourceKey = refKey(source.unit_ref);
    const sourceDescendants = descendants.get(sourceKey);
    if (sourceDescendants === undefined) return null;
    for (const target of source.dependent_unit_refs) {
      const targetKey = refKey(target);
      const indirect = [...sourceDescendants].some((intermediateKey) => intermediateKey !== targetKey && (descendants.get(intermediateKey)?.has(targetKey) ?? false));
      if (!indirect) edges.push({ prerequisite_unit_ref: copyRef(source.unit_ref), dependent_unit_ref: copyRef(target) });
    }
  }
  return edges.sort((left, right) => compareBytes(`${refKey(left.prerequisite_unit_ref)}\u0000${refKey(left.dependent_unit_ref)}`, `${refKey(right.prerequisite_unit_ref)}\u0000${refKey(right.dependent_unit_ref)}`));
}

function externalPrerequisiteRefs(units: ProjectedUnit[]): KnowledgeUnitRef[] {
  const byKey = new Map<string, KnowledgeUnitRef>();
  for (const unit of units) for (const prerequisite of unit.missing_prerequisite_refs) byKey.set(refKey(prerequisite), copyRef(prerequisite));
  return [...byKey.entries()].sort(([left], [right]) => compareBytes(left, right)).map(([, prerequisite]) => prerequisite);
}
function projectedUnits(value: unknown): ProjectedUnit[] | null {
  if (!Array.isArray(value)) return null;
  const result: ProjectedUnit[] = [];
  for (const item of value) {
    if (!exactKeys(item, ["ref", "status", "missing_prerequisite_refs", "missing_evidence_node_refs"])) return null;
    const unitRef = ref(ownData(item, "ref"));
    const prerequisiteRefs = refs(ownData(item, "missing_prerequisite_refs"));
    const evidenceRefs = refs(ownData(item, "missing_evidence_node_refs"));
    const status = ownData(item, "status");
    if (unitRef === null || prerequisiteRefs === null || evidenceRefs === null
      || (status !== "blocked" && status !== "needs_evidence" && status !== "ready")
      || (status === "blocked" && prerequisiteRefs.length === 0)
      || (status === "needs_evidence" && (prerequisiteRefs.length !== 0 || evidenceRefs.length === 0))
      || (status === "ready" && (prerequisiteRefs.length !== 0 || evidenceRefs.length !== 0))) return null;
    result.push({ ref: unitRef, status, missing_prerequisite_refs: prerequisiteRefs, missing_evidence_node_refs: evidenceRefs });
  }
  const keys = result.map((item) => refKey(item.ref));
  const sorted = [...keys].sort(compareBytes);
  return new Set(keys).size === keys.length && keys.every((key, index) => key === sorted[index]) ? result : null;
}

function affectedUnits(projection: { node_dependents: Array<{ node_ref: KnowledgeUnitRef; unit_refs: KnowledgeUnitRef[] }> }, selected: KnowledgeUnitRef): KnowledgeUnitRef[] | null {
  for (const item of projection.node_dependents) {
    if (!exactKeys(item, ["node_ref", "unit_refs"])) return null;
    const node = ref(ownData(item, "node_ref"));
    const units = refs(ownData(item, "unit_refs"));
    if (node === null || units === null) return null;
    if (refKey(node) === refKey(selected)) return units;
  }
  return [];
}

function diagnostic(caseId: "normal" | "blocked" | "empty", isEmpty: boolean): string {
  if (isEmpty) return "所选 CognitiveNode 不在固定工程图谱的反向影响中；不伪造受影响的 KnowledgeUnit。";
  if (caseId === "blocked") return "固定线性方程工程图谱包含缺失的外部先修 KnowledgeUnit。";
  return "固定线性方程工程图谱已投影；状态来自 KnowledgeUnit 投影，不表示个人掌握或工程完成。";
}

export function createKnowledgeProjectMapPreview(input: unknown): KnowledgeProjectMapPreview {
  try {
    const parsed = request(input);
    if (parsed === null || parsed.caseId === "invalid") return invalidResult();
    const selectedDemo = demo(parsed.caseId);
    if (selectedDemo === null) return invalidResult();
    const selected = parsed.selected ?? ref(selectedDemo.default_selected_node_ref);
    const available = refs(selectedDemo.available_node_refs);
    if (selected === null || available === null || !available.some((item) => refKey(item) === refKey(selected))) return invalidResult();
    const projection = projectKnowledge(selectedDemo.units, selectedDemo.available_node_refs, selectedDemo.evidence_node_refs, CONTRACT_ROOT);
    if (!validProjectionForDemo(parsed.caseId, projection) || !validProjection(projection)) return invalidResult();
    const units = projectedUnits(projection.units);
    const edges = prerequisiteEdges(projection);
    const affected = affectedUnits(projection, selected);
    if (units === null || edges === null || affected === null) return invalidResult();
    const state = affected.length === 0 ? "empty" : "valid";
    return {
      mode: "preview", side_effects: "forbidden", state, units, prerequisite_edges: edges, external_prerequisite_refs: externalPrerequisiteRefs(units),
      selected_node_ref: copyRef(selected), affected_unit_refs: affected, diagnostic: diagnostic(parsed.caseId, state === "empty"),
    };
  } catch {
    return invalidResult();
  }
}