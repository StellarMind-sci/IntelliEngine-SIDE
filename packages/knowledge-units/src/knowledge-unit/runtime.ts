import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { validateMachineSchema } from "../../../cognitive-ir/src/conformance-ts/machine-schema.ts";
import { StrictJsonError, canonicalize, strictParse } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";


type JsonObject = Record<string, any>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const KNOWLEDGE_UNIT_JCS_BYTES = 1_048_576;
const CAPABILITIES = new Set([
  "runtime.math.numeric",
  "runtime.math.symbolic",
  "runtime.visualization.2d",
]);
const REQUIRED = [
  "contract_version", "id", "revision", "title", "concept_boundary",
  "learning_objectives", "node_bindings", "prerequisite_unit_refs",
  "behaviors", "validations", "mastery_criteria", "provenance_refs",
];


function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}


function issue(code: string, path: string) {
  return { code, path, severity: "error" };
}


function result(valid: boolean, problem?: JsonObject) {
  return {
    object_result: valid ? "valid" : "invalid",
    operation_outcome: "succeeded",
    issues: problem === undefined ? [] : [problem],
  };
}


function resourceExhausted() {
  return {
    object_result: "not_evaluated",
    operation_outcome: "resource_exhausted",
    issues: [issue("knowledge_unit.invalid_json", "")],
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


function sortedUnique(values: unknown, key: (value: unknown) => string | undefined) {
  if (!Array.isArray(values)) return false;
  const keys = values.map(key);
  if (keys.some((value) => value === undefined)) return false;
  const concrete = keys as string[];
  const sorted = [...concrete].sort(compareBytes);
  return new Set(concrete).size === concrete.length && concrete.every((value, index) => value === sorted[index]);
}


function bindingKey(value: unknown) {
  if (!object(value) || typeof value.role !== "string") return undefined;
  const reference = refKey(value.node_ref);
  return reference === undefined ? undefined : `${value.role}\u0000${reference}`;
}


function namedKey(field: string) {
  return (value: unknown) => object(value) && typeof value[field] === "string" ? value[field] : undefined;
}


function collectRefs(unit: JsonObject) {
  const values: unknown[] = [];
  if (object(unit.concept_boundary)) values.push(...(unit.concept_boundary.focus_node_refs ?? []));
  for (const objective of unit.learning_objectives ?? []) if (object(objective)) values.push(...(objective.target_node_refs ?? []));
  for (const binding of unit.node_bindings ?? []) if (object(binding)) values.push(binding.node_ref);
  for (const behavior of unit.behaviors ?? []) if (object(behavior)) {
    values.push(...(behavior.input_node_refs ?? []));
    values.push(...(behavior.output_node_refs ?? []));
  }
  for (const validation of unit.validations ?? []) if (object(validation)) {
    values.push(...(validation.subject_node_refs ?? []));
    values.push(...(validation.evidence_node_refs ?? []));
  }
  for (const criterion of unit.mastery_criteria ?? []) if (object(criterion)) values.push(...(criterion.evidence_node_refs ?? []));
  return values.map(refKey).filter((value): value is string => value !== undefined);
}


function readStrict(path: string) {
  return strictParse(readFileSync(path));
}


export function validateUnit(unit: unknown, availableNodeRefs: unknown, contractRoot: string) {
  if (!object(unit)) return result(false, issue("knowledge_unit.invalid_json", ""));
  const missing = REQUIRED.find((field) => !(field in unit));
  if (missing !== undefined) return result(false, issue("knowledge_unit.missing_field", `/${missing}`));
  if (typeof unit.contract_version !== "string" || !unit.contract_version.startsWith("1.")) return result(false, issue("knowledge_unit.unsupported_contract_version", "/contract_version"));
  if (typeof unit.id !== "string" || !UUID.test(unit.id)) return result(false, issue("knowledge_unit.invalid_id", "/id"));
  if (!Number.isSafeInteger(unit.revision) || unit.revision < 1) return result(false, issue("knowledge_unit.invalid_revision", "/revision"));
  if (!sortedUnique(unit.node_bindings, bindingKey)) return result(false, issue("knowledge_unit.noncanonical_set", "/node_bindings"));
  if (!sortedUnique(unit.prerequisite_unit_refs, refKey)) return result(false, issue("knowledge_unit.noncanonical_set", "/prerequisite_unit_refs"));
  if (!sortedUnique(unit.provenance_refs, (value) => typeof value === "string" && value.length > 0 ? value : undefined)) return result(false, issue("knowledge_unit.noncanonical_set", "/provenance_refs"));
  for (const [field, identifier] of [["learning_objectives", "objective_id"], ["behaviors", "behavior_id"], ["validations", "validation_id"], ["mastery_criteria", "criterion_id"]]) {
    if (!sortedUnique(unit[field], namedKey(identifier))) return result(false, issue("knowledge_unit.noncanonical_set", `/${field}`));
  }
  const identity = refKey({ id: unit.id, revision: unit.revision });
  for (let index = 0; index < unit.prerequisite_unit_refs.length; index += 1) {
    if (refKey(unit.prerequisite_unit_refs[index]) === identity) return result(false, issue("knowledge_unit.self_dependency", `/prerequisite_unit_refs/${index}`));
  }
  for (let index = 0; index < unit.mastery_criteria.length; index += 1) {
    const criterion = unit.mastery_criteria[index];
    if (!object(criterion) || !Array.isArray(criterion.evidence_node_refs) || criterion.evidence_node_refs.length === 0) return result(false, issue("knowledge_unit.mastery_without_evidence", `/mastery_criteria/${index}/evidence_node_refs`));
  }
  for (let index = 0; index < unit.behaviors.length; index += 1) {
    const behavior = unit.behaviors[index];
    if (!object(behavior) || !CAPABILITIES.has(behavior.capability)) return result(false, issue("knowledge_unit.invalid_behavior_capability", `/behaviors/${index}/capability`));
  }
  if (!sortedUnique(availableNodeRefs, refKey)) return result(false, issue("knowledge_unit.noncanonical_set", "/available_node_refs"));
  const available = new Set((availableNodeRefs as unknown[]).map(refKey));
  const refs = collectRefs(unit);
  if (refs.some((reference) => !available.has(reference))) return result(false, issue("knowledge_unit.dangling_node_ref", ""));
  const bound = new Set(unit.node_bindings.map((binding: JsonObject) => refKey(binding.node_ref)));
  if (refs.some((reference) => !bound.has(reference))) return result(false, issue("knowledge_unit.dangling_node_ref", "/node_bindings"));
  const nestedSets: Array<[string, unknown]> = [];
  if (object(unit.concept_boundary)) {
    nestedSets.push(["/concept_boundary/focus_node_refs", unit.concept_boundary.focus_node_refs]);
    if (!sortedUnique(unit.concept_boundary.out_of_scope_statements, (value) => typeof value === "string" && value.length > 0 ? value : undefined)) return result(false, issue("knowledge_unit.noncanonical_set", "/concept_boundary/out_of_scope_statements"));
  }
  unit.learning_objectives.forEach((value: JsonObject, index: number) => nestedSets.push([`/learning_objectives/${index}/target_node_refs`, value.target_node_refs]));
  unit.behaviors.forEach((value: JsonObject, index: number) => {
    nestedSets.push([`/behaviors/${index}/input_node_refs`, value.input_node_refs]);
    nestedSets.push([`/behaviors/${index}/output_node_refs`, value.output_node_refs]);
  });
  unit.validations.forEach((value: JsonObject, index: number) => {
    nestedSets.push([`/validations/${index}/subject_node_refs`, value.subject_node_refs]);
    nestedSets.push([`/validations/${index}/evidence_node_refs`, value.evidence_node_refs]);
  });
  unit.mastery_criteria.forEach((value: JsonObject, index: number) => nestedSets.push([`/mastery_criteria/${index}/evidence_node_refs`, value.evidence_node_refs]));
  for (const [path, references] of nestedSets) {
    if (!sortedUnique(references, refKey)) return result(false, issue("knowledge_unit.noncanonical_set", path));
  }
  const schema = readStrict(resolve(contractRoot, "schemas/knowledge-unit.schema.json")) as JsonObject;
  if (!validateMachineSchema(unit, schema, schema, new Map())) return result(false, issue("knowledge_unit.invalid_json", ""));
  if (Buffer.byteLength(canonicalize(unit)) > KNOWLEDGE_UNIT_JCS_BYTES) return resourceExhausted();
  return result(true);
}


export function parseAndValidate(raw: Uint8Array, availableNodeRefs: unknown, contractRoot: string) {
  try {
    return validateUnit(strictParse(raw), availableNodeRefs, contractRoot);
  } catch (error) {
    if (!(error instanceof StrictJsonError)) throw error;
    return result(false, issue("knowledge_unit.invalid_json", ""));
  }
}


function walk(document: any, pointer: string): [any, string | number] {
  const parts = pointer.slice(1).split("/").map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
  let current = document;
  for (const part of parts.slice(0, -1)) current = Array.isArray(current) ? current[Number(part)] : current[part];
  return [current, Array.isArray(current) ? Number(parts.at(-1)) : parts.at(-1)!];
}


function mutate(unit: JsonObject, mutation: JsonObject) {
  const value = structuredClone(unit);
  const [parent, leaf] = walk(value, mutation.path);
  if (mutation.kind === "remove") delete parent[leaf];
  else if (mutation.kind === "reverse") parent[leaf] = [...parent[leaf]].reverse();
  else if (mutation.kind === "clear") parent[leaf] = [];
  else if (mutation.kind === "replace") parent[leaf] = structuredClone(mutation.value);
  else if (mutation.kind === "append-self-dependency") parent[leaf].push({ id: value.id, revision: value.revision });
  else throw new Error(`unsupported fixture mutation: ${mutation.kind}`);
  return value;
}


export function runFixtureSuite(contractRoot: string) {
  const suite = readStrict(resolve(contractRoot, "fixtures/cases.json")) as JsonObject;
  const base = suite.cases.find((fixture: JsonObject) => "unit" in fixture.input);
  const available = base.input.available_node_refs;
  const rows = suite.cases.map((fixture: JsonObject) => {
    const unit = "unit" in fixture.input ? structuredClone(fixture.input.unit) : mutate(base.input.unit, fixture.input.mutation);
    return { case_id: fixture.case_id, ...validateUnit(unit, available, contractRoot) };
  });
  return rows.sort((left: JsonObject, right: JsonObject) => compareBytes(left.case_id, right.case_id));
}
