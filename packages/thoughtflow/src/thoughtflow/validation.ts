import { readFileSync } from "node:fs";
import { canonicalize } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CONTROL = new Set(["sequence", "branch", "verification_feedback"]);
const FLOW_SCHEMA = JSON.parse(readFileSync(new URL("../../contracts/thoughtflow/1.0.0/schemas/thoughtflow.schema.json", import.meta.url), "utf8"));
const MAX_JCS_BYTES = 4194304;

const isObject = (value: any) => value !== null && typeof value === "object" && !Array.isArray(value);

function schemaValid(value: any, schema: any): boolean {
  if (!isObject(schema)) return false;
  if (schema.type === "object" && !isObject(value)) return false;
  if (schema.type === "array" && !Array.isArray(value)) return false;
  if (schema.type === "string" && typeof value !== "string") return false;
  if (schema.type === "integer" && !Number.isSafeInteger(value)) return false;
  if ("const" in schema && value !== schema.const) return false;
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) return false;
  if (typeof value === "string") {
    const length = Array.from(value).length;
    if (length < (schema.minLength ?? 0) || length > (schema.maxLength ?? Number.POSITIVE_INFINITY)) return false;
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern, "u").test(value)) return false;
  }
  if (typeof value === "number") {
    if (value < (schema.minimum ?? Number.NEGATIVE_INFINITY) || value > (schema.maximum ?? Number.POSITIVE_INFINITY)) return false;
  }
  if (Array.isArray(value)) {
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Number.POSITIVE_INFINITY)) return false;
    if (schema.items !== undefined && value.some((item) => !schemaValid(item, schema.items))) return false;
  }
  if (isObject(value)) {
    if ((schema.required ?? []).some((name: string) => !(name in value))) return false;
    const properties = schema.properties ?? {};
    for (const [name, item] of Object.entries(value)) {
      if (name in properties) {
        if (!schemaValid(item, properties[name])) return false;
      } else if (schema.additionalProperties === false) return false;
    }
  }
  if (Array.isArray(schema.oneOf) && schema.oneOf.filter((child: any) => schemaValid(value, child)).length !== 1) return false;
  return true;
}

function withinSizeLimit(value: any): boolean {
  try {
    return Buffer.byteLength(canonicalize(value), "utf8") <= MAX_JCS_BYTES;
  } catch {
    return false;
  }
}

export const issue = (code: string, path: string) => ({ code, path, severity: "error" });
export const verdict = (valid: boolean, diagnostic?: any) => ({
  object_result: valid ? "valid" : "invalid",
  operation_outcome: "succeeded",
  issues: diagnostic ? [diagnostic] : [],
});
export const indeterminate = (code: string, path: string) => ({
  object_result: "not_evaluated", operation_outcome: "indeterminate", issues: [issue(code, path)],
});

const refKey = (value: any) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "id,revision") return null;
  if (typeof value.id !== "string" || !UUID.test(value.id) || !Number.isSafeInteger(value.revision) || value.revision < 1) return null;
  return `${value.id}\0${String(value.revision).padStart(16, "0")}`;
};
const compareUtf8 = (left: string, right: string) => Buffer.compare(Buffer.from(left), Buffer.from(right));
const ordered = (values: any, key: (item: any) => string | null) => {
  if (!Array.isArray(values)) return false;
  const keys = values.map(key);
  return keys.every((item) => item !== null) && new Set(keys).size === keys.length &&
    keys.every((item, index) => index === 0 || compareUtf8(keys[index - 1]!, item!) <= 0);
};
const transitionKey = (value: any) => {
  if (!value || typeof value !== "object") return null;
  const parts = [value.from_step_id, value.kind, value.branch_label ?? value.outcome ?? "", value.to_step_id, value.transition_id];
  return parts.every((item) => typeof item === "string") ? parts.join("\0") : null;
};
const reachable = (start: string, edges: Map<string, string[]>) => {
  const seen = new Set<string>(), pending = [start];
  while (pending.length) {
    const current = pending.pop()!;
    if (!seen.has(current)) {
      seen.add(current);
      pending.push(...(edges.get(current) ?? []));
    }
  }
  return seen;
};

export function validateGraph(flow: any) {
  if (!flow || typeof flow !== "object" || Array.isArray(flow)) return verdict(false, issue("thoughtflow.invalid_json", ""));
  if (typeof flow.contract_version !== "string" || !flow.contract_version.startsWith("1.")) return verdict(false, issue("thoughtflow.unsupported_contract_version", "/contract_version"));
  if (typeof flow.id !== "string" || !UUID.test(flow.id)) return verdict(false, issue("thoughtflow.invalid_json", "/id"));
  if (!Number.isSafeInteger(flow.revision) || flow.revision < 1) return verdict(false, issue("thoughtflow.invalid_revision", "/revision"));
  if (!schemaValid(flow, FLOW_SCHEMA) || !withinSizeLimit(flow)) return verdict(false, issue("thoughtflow.invalid_json", ""));
  if (!ordered(flow.steps, (item) => item && typeof item.step_id === "string" ? item.step_id : null)) return verdict(false, issue("thoughtflow.noncanonical_set", "/steps"));
  if (!ordered(flow.transitions, transitionKey)) return verdict(false, issue("thoughtflow.noncanonical_set", "/transitions"));
  if (!ordered(flow.knowledge_unit_refs, refKey)) return verdict(false, issue("thoughtflow.noncanonical_set", "/knowledge_unit_refs"));
  if (!ordered(flow.cognitive_node_refs, refKey)) return verdict(false, issue("thoughtflow.noncanonical_set", "/cognitive_node_refs"));
  if (!ordered(flow.provenance_refs, (item) => typeof item === "string" && item ? item : null)) return verdict(false, issue("thoughtflow.noncanonical_set", "/provenance_refs"));
  const byId = new Map(flow.steps.map((step: any) => [step.step_id, step]));
  if (!byId.has(flow.entry_step_id)) return verdict(false, issue("thoughtflow.dangling_step", "/entry_step_id"));
  if (!flow.steps.some((step: any) => step.kind === "goal") || !flow.steps.some((step: any) => step.kind === "verification")) return verdict(false, issue("thoughtflow.invalid_step", "/steps"));

  const usedKu = new Set<string>(), usedCn = new Set<string>();
  const common = new Set(["step_id", "kind", "title", "description", "knowledge_unit_refs", "cognitive_node_refs"]);
  const extras: Record<string, string[]> = { goal: ["success_statement"], analysis: [], operation: ["behavior_ref"], decision: [], verification: ["acceptance_statement", "evidence_node_refs"], artifact: ["artifact_key"], iteration: ["max_iterations", "exit_condition", "verification_step_ids"] };
  for (let index = 0; index < flow.steps.length; index++) {
    const step = flow.steps[index], extra = extras[step.kind];
    if (!extra) return verdict(false, issue("thoughtflow.invalid_step", `/steps/${index}`));
    const expected = new Set([...common, ...extra]);
    if (Object.keys(step).length !== expected.size || Object.keys(step).some((key) => !expected.has(key))) return verdict(false, issue("thoughtflow.invalid_step", `/steps/${index}`));
    if (!ordered(step.knowledge_unit_refs, refKey) || !ordered(step.cognitive_node_refs, refKey)) return verdict(false, issue("thoughtflow.noncanonical_set", `/steps/${index}`));
    step.knowledge_unit_refs.forEach((item: any) => usedKu.add(refKey(item)!));
    step.cognitive_node_refs.forEach((item: any) => usedCn.add(refKey(item)!));
    if (step.kind === "operation") {
      if (!step.behavior_ref || !refKey(step.behavior_ref.knowledge_unit_ref) || !step.behavior_ref.behavior_id) return verdict(false, issue("thoughtflow.invalid_step", `/steps/${index}/behavior_ref`));
      usedKu.add(refKey(step.behavior_ref.knowledge_unit_ref)!);
    }
    if (step.kind === "verification") {
      if (!step.acceptance_statement || !ordered(step.evidence_node_refs, refKey) || !step.evidence_node_refs.length) return verdict(false, issue("thoughtflow.invalid_step", `/steps/${index}`));
      const evidence = new Set(step.evidence_node_refs.map(refKey)), nodes = new Set(step.cognitive_node_refs.map(refKey));
      if ([...evidence].some((item) => !nodes.has(item))) return verdict(false, issue("thoughtflow.reference_closure_mismatch", `/steps/${index}/evidence_node_refs`));
      evidence.forEach((item: any) => usedCn.add(item));
    }
    if (step.kind === "iteration") {
      if (!Number.isInteger(step.max_iterations) || step.max_iterations < 1 || step.max_iterations > 10000 || !step.exit_condition) return verdict(false, issue("thoughtflow.invalid_loop", `/steps/${index}`));
      if (!step.verification_step_ids.length || !ordered(step.verification_step_ids, (id: any) => typeof id === "string" ? id : null)) return verdict(false, issue("thoughtflow.invalid_loop", `/steps/${index}/verification_step_ids`));
      if (step.verification_step_ids.some((id: string) => !byId.has(id) || byId.get(id).kind !== "verification")) return verdict(false, issue("thoughtflow.dangling_step", `/steps/${index}/verification_step_ids`));
    }
  }
  if (JSON.stringify([...new Set(flow.knowledge_unit_refs.map(refKey))].sort()) !== JSON.stringify([...usedKu].sort())) return verdict(false, issue("thoughtflow.reference_closure_mismatch", "/knowledge_unit_refs"));
  if (JSON.stringify([...new Set(flow.cognitive_node_refs.map(refKey))].sort()) !== JSON.stringify([...usedCn].sort())) return verdict(false, issue("thoughtflow.reference_closure_mismatch", "/cognitive_node_refs"));

  const edges = new Map<string, string[]>(), reverse = new Map<string, string[]>(), indegree = new Map<string, number>(), outgoing = new Map<string, any[]>();
  for (const id of byId.keys()) { edges.set(id, []); reverse.set(id, []); indegree.set(id, 0); outgoing.set(id, []); }
  const baseTransition = new Set(["transition_id", "kind", "from_step_id", "to_step_id"]);
  const fields: Record<string, Set<string>> = {
    sequence: baseTransition, data_dependency: baseTransition,
    branch: new Set([...baseTransition, "branch_label", "condition_statement", "is_default"]),
    verification_feedback: new Set([...baseTransition, "outcome"]), loop: new Set([...baseTransition, "outcome"]),
  };
  for (let index = 0; index < flow.transitions.length; index++) {
    const transition = flow.transitions[index], expected = fields[transition.kind];
    if (!expected || Object.keys(transition).length !== expected.size || Object.keys(transition).some((key) => !expected.has(key))) return verdict(false, issue("thoughtflow.invalid_transition", `/transitions/${index}`));
    if (!byId.has(transition.from_step_id) || !byId.has(transition.to_step_id)) {
      const field = !byId.has(transition.from_step_id) ? "from_step_id" : "to_step_id";
      return verdict(false, issue("thoughtflow.dangling_step", `/transitions/${index}/${field}`));
    }
    if (transition.from_step_id === transition.to_step_id) return verdict(false, issue("thoughtflow.invalid_transition", `/transitions/${index}`));
    outgoing.get(transition.from_step_id)!.push({ index, transition });
    if (CONTROL.has(transition.kind)) {
      edges.get(transition.from_step_id)!.push(transition.to_step_id);
      reverse.get(transition.to_step_id)!.push(transition.from_step_id);
      indegree.set(transition.to_step_id, indegree.get(transition.to_step_id)! + 1);
    }
  }
  const counts = new Map(indegree), queue = [...counts].filter(([, count]) => count === 0).map(([id]) => id);
  let visited = 0;
  while (queue.length) {
    const current = queue.shift()!; visited++;
    for (const target of edges.get(current)!) {
      counts.set(target, counts.get(target)! - 1);
      if (counts.get(target) === 0) queue.push(target);
    }
  }
  if (visited !== byId.size) return verdict(false, issue("thoughtflow.unconstrained_cycle", "/transitions"));
  const seen = reachable(flow.entry_step_id, edges);
  for (let index = 0; index < flow.steps.length; index++) if (!seen.has(flow.steps[index].step_id)) return verdict(false, issue("thoughtflow.unreachable_step", `/steps/${index}`));
  const roots = [...byId.keys()].filter((id) => indegree.get(id) === 0);
  if (roots.length !== 1 || roots[0] !== flow.entry_step_id) return verdict(false, issue("thoughtflow.invalid_transition", "/entry_step_id"));

  for (let index = 0; index < flow.steps.length; index++) {
    const step = flow.steps[index], controls = outgoing.get(step.step_id)!.filter(({ transition }) => transition.kind !== "data_dependency");
    if (step.kind === "decision" || step.kind === "iteration") {
      const branches = controls.filter(({ transition }) => transition.kind === "branch").map(({ transition }) => transition);
      const labels = branches.map((item) => item.branch_label);
      if (branches.length < 2 || branches.length !== controls.length || new Set(labels).size !== labels.length || branches.filter((item) => item.is_default === true).length !== 1 || branches.some((item) => !item.condition_statement)) return verdict(false, issue("thoughtflow.invalid_branch_set", `/steps/${index}`));
    } else if (step.kind === "verification") {
      const feedback = controls.filter(({ transition }) => transition.kind === "verification_feedback").map(({ transition }) => transition);
      const loops = controls.filter(({ transition }) => transition.kind === "loop");
      if (!feedback.length || feedback.length + loops.length !== controls.length) return verdict(false, issue("thoughtflow.invalid_transition", `/steps/${index}`));
      for (const { index: transitionIndex, transition: loop } of loops) {
        const target = byId.get(loop.to_step_id);
        if (!["failed", "needs_evidence"].includes(loop.outcome) || target.kind !== "iteration" || !target.verification_step_ids.includes(step.step_id) || !reachable(loop.to_step_id, edges).has(loop.from_step_id)) {
          const suffix = !["failed", "needs_evidence"].includes(loop.outcome) ? "/outcome" : "";
          return verdict(false, issue("thoughtflow.invalid_loop", `/transitions/${transitionIndex}${suffix}`));
        }
        const forward = reachable(loop.to_step_id, edges), backward = reachable(loop.from_step_id, reverse);
        const component = [...forward].filter((id) => backward.has(id));
        if (component.filter((id) => byId.get(id).kind === "iteration").length !== 1 || !component.some((id) => byId.get(id).kind === "verification")) return verdict(false, issue("thoughtflow.invalid_loop", `/transitions/${transitionIndex}`));
      }
      const outcomes = [...feedback.map((item) => item.outcome), ...loops.map(({ transition }) => transition.outcome)];
      if (new Set(outcomes).size !== outcomes.length) return verdict(false, issue("thoughtflow.duplicate_outcome", `/steps/${index}`));
    } else if (controls.some(({ transition }) => ["branch", "verification_feedback", "loop"].includes(transition.kind))) {
      return verdict(false, issue("thoughtflow.invalid_transition", `/steps/${index}`));
    }
  }
  return verdict(true);
}

export function validateReferences(flow: any, snapshot: any) {
  const graph = validateGraph(flow);
  if (graph.object_result !== "valid") return graph;
  if (!snapshot || typeof snapshot !== "object") return indeterminate("thoughtflow.reference_snapshot_incomplete", "");
  const mapEntries = (entries: any) => ordered(entries, (item) => item && refKey(item.ref)) ? new Map(entries.map((item: any) => [refKey(item.ref), item])) : null;
  const cognitive = mapEntries(snapshot.cognitive_nodes), knowledge = mapEntries(snapshot.knowledge_units);
  if (!cognitive || !knowledge) return indeterminate("thoughtflow.reference_snapshot_incomplete", "");
  for (const [field, entries, table] of [["cognitive_node_refs", flow.cognitive_node_refs, cognitive], ["knowledge_unit_refs", flow.knowledge_unit_refs, knowledge]] as any) {
    for (let index = 0; index < entries.length; index++) {
      const item = table.get(refKey(entries[index])), path = `/${field}/${index}`;
      if (!item) return indeterminate("thoughtflow.reference_snapshot_incomplete", path);
      if (item.object_result === "invalid") return verdict(false, issue("thoughtflow.dangling_reference", path));
      if (["opaque", "compatible_read"].includes(item.object_result)) return indeterminate("thoughtflow.opaque_reference", path);
      if (item.object_result !== "available") return indeterminate("thoughtflow.reference_snapshot_incomplete", path);
    }
  }
  for (let index = 0; index < flow.steps.length; index++) {
    const step = flow.steps[index];
    if (step.kind !== "operation") continue;
    const entry: any = knowledge.get(refKey(step.behavior_ref.knowledge_unit_ref));
    const behavior = entry?.document?.behaviors?.find((item: any) => item.behavior_id === step.behavior_ref.behavior_id);
    if (!behavior) return verdict(false, issue("thoughtflow.unknown_behavior", `/steps/${index}/behavior_ref`));
    const required = new Set([...behavior.input_node_refs, ...behavior.output_node_refs].map(refKey)), actual = new Set(step.cognitive_node_refs.map(refKey));
    if ([...required].some((item) => !actual.has(item))) return verdict(false, issue("thoughtflow.behavior_node_coverage", `/steps/${index}/cognitive_node_refs`));
  }
  return verdict(true);
}

export function validateRevision(previous: any, candidate: any) {
  if (!previous || !candidate || previous.id !== candidate.id) return verdict(false, issue("thoughtflow.revision_identity_mismatch", "/id"));
  if (!Number.isInteger(candidate.revision) || candidate.revision <= previous.revision) return verdict(false, issue("thoughtflow.revision_not_increased", "/revision"));
  const old = structuredClone(previous), next = structuredClone(candidate); delete old.revision; delete next.revision;
  if (JSON.stringify(old) === JSON.stringify(next)) return verdict(false, issue("thoughtflow.revision_without_change", "/revision"));
  for (const [field, identity] of [["steps", "step_id"], ["transitions", "transition_id"]] as const) {
    const table = new Map(candidate[field].map((item: any) => [item[identity], item]));
    for (let index = 0; index < previous[field].length; index++) if (JSON.stringify(table.get(previous[field][index][identity])) !== JSON.stringify(previous[field][index])) return verdict(false, issue("thoughtflow.history_rewrite", `/${field}/${index}`));
  }
  return verdict(true);
}

export function applyMutation(document: any, mutation: any) {
  const value = structuredClone(document), parts = mutation.path.slice(1).split("/");
  let parent = value;
  for (const part of parts.slice(0, -1)) parent = Array.isArray(parent) ? parent[Number(part)] : parent[part];
  const rawLeaf = parts.at(-1)!, leaf: any = Array.isArray(parent) ? Number(rawLeaf) : rawLeaf;
  if (mutation.kind === "replace") parent[leaf] = structuredClone(mutation.value);
  else if (mutation.kind === "remove") Array.isArray(parent) ? parent.splice(leaf, 1) : delete parent[leaf];
  else if (mutation.kind === "reverse") parent[leaf].reverse();
  else if (mutation.kind === "append") parent[leaf].push(structuredClone(mutation.value));
  return value;
}

export function materialize(caseValue: any, suite: any): any {
  const value = caseValue.input;
  if (value.mode === "revision" && value.base_case_id) {
    const base = materialize(suite.cases.find((item: any) => item.case_id === value.base_case_id), suite);
    let candidate = structuredClone(base);
    for (const mutation of value.candidate_mutations) candidate = applyMutation(candidate, mutation);
    return { mode: "revision", previous: base.flow, candidate: candidate.flow };
  }
  if (value.base_case_id) return applyMutation(materialize(suite.cases.find((item: any) => item.case_id === value.base_case_id), suite), value.mutation);
  return structuredClone(value);
}
