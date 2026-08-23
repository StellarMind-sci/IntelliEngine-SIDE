import { readFileSync } from "node:fs";
import { strictParse } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";
import { contractCompatibility, issue, materialize, validateGraph, validateReferences, validateRevision, verdict } from "./validation.ts";

export function parseAndValidateTransport(raw: Uint8Array) {
  try {
    return validateGraph(strictParse(raw));
  } catch {
    return verdict(false, issue("thoughtflow.invalid_json", ""));
  }
}

export { validateReferences };

export function validateRevisionTransition(previous: any, candidate: any) {
  return validateRevision(previous, candidate);
}

export function graphSummary(flow: any) {
  const kinds: Record<string, number> = {};
  for (const step of flow.steps) kinds[step.kind] = (kinds[step.kind] ?? 0) + 1;
  const step_kinds = Object.fromEntries(Object.keys(kinds).sort().map((key) => [key, kinds[key]]));
  const controlEdges = new Map<string, string[]>();
  for (const step of flow.steps) controlEdges.set(step.step_id, []);
  for (const transition of flow.transitions) {
    if (["sequence", "branch", "verification_feedback"].includes(transition.kind)) controlEdges.get(transition.from_step_id)!.push(transition.to_step_id);
  }
  const reachable = new Set<string>(), pending = [flow.entry_step_id];
  while (pending.length) {
    const current = pending.pop()!;
    if (!reachable.has(current)) {
      reachable.add(current);
      pending.push(...(controlEdges.get(current) ?? []));
    }
  }
  const reachable_step_ids = [...reachable].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  return {
    entry_step_id: flow.entry_step_id,
    step_count: flow.steps.length,
    transition_count: flow.transitions.length,
    step_kinds,
    loop_controllers: flow.steps.filter((step: any) => step.kind === "iteration").map((step: any) => ({ max_iterations: step.max_iterations, step_id: step.step_id })),
    reachable_step_count: reachable_step_ids.length,
    reachable_step_ids,
  };
}

const project = (transition: any) => {
  const result: any = { kind: transition.kind, to_step_id: transition.to_step_id, transition_id: transition.transition_id };
  for (const field of ["branch_label", "condition_statement", "is_default", "outcome"]) if (field in transition) result[field] = transition[field];
  return result;
};

export function nextCandidates(
  flow: any,
  stepId: string,
  options: { observedOutcome?: string; selectedBranch?: string } = {},
) {
  if (contractCompatibility(flow?.contract_version) === "compatible_read") {
    return { status: "compatible_read", candidates: [], object_result: "not_evaluated", operation_outcome: "indeterminate" };
  }
  const step = flow.steps.find((item: any) => item.step_id === stepId);
  if (!step) return { status: "unknown_step", candidates: [] };
  const outgoing = flow.transitions.filter((item: any) => item.from_step_id === stepId && item.kind !== "data_dependency");
  if (step.kind === "decision" || step.kind === "iteration") {
    const candidates = outgoing.filter((item: any) => item.kind === "branch").map(project);
    if (options.selectedBranch === undefined) return { status: "requires_selection", candidates };
    const chosen = candidates.filter((item: any) => item.branch_label === options.selectedBranch);
    return { status: chosen.length ? "ready" : "invalid_selection", candidates: chosen };
  }
  if (step.kind === "verification") {
    if (options.observedOutcome === undefined) return { status: "requires_observation", candidates: outgoing.map(project) };
    const chosen = outgoing.filter((item: any) => item.outcome === options.observedOutcome).map(project);
    return { status: chosen.length ? "ready" : "unknown_outcome", candidates: chosen };
  }
  return { status: "ready", candidates: outgoing.map(project) };
}

export function simulateBounded(
  flow: any,
  options: {
    observations: Record<string, string[]>;
    branchSelections: Record<string, string[]>;
    maxSteps: number;
  },
) {
  if (contractCompatibility(flow?.contract_version) === "compatible_read") {
    return { status: "compatible_read", path: [], iteration_counts: {}, object_result: "not_evaluated", operation_outcome: "indeterminate" };
  }
  if (options.maxSteps < 1) return { status: "max_steps_reached", path: [], iteration_counts: {} };
  const steps = new Map(flow.steps.map((step: any) => [step.step_id, step]));
  const observationIndex: Record<string, number> = {}, branchIndex: Record<string, number> = {}, iteration_counts: Record<string, number> = {};
  const path: string[] = [];
  let current = flow.entry_step_id;
  for (let count = 0; count < options.maxSteps; count++) {
    path.push(current);
    const step: any = steps.get(current);
    let observedOutcome: string | undefined, selectedBranch: string | undefined;
    if (step.kind === "verification") {
      const index = observationIndex[current] ?? 0, values = options.observations[current] ?? [];
      if (index < values.length) { observedOutcome = values[index]; observationIndex[current] = index + 1; }
    }
    if (step.kind === "decision" || step.kind === "iteration") {
      const index = branchIndex[current] ?? 0, values = options.branchSelections[current] ?? [];
      if (index < values.length) { selectedBranch = values[index]; branchIndex[current] = index + 1; }
    }
    const result = nextCandidates(flow, current, { observedOutcome, selectedBranch });
    if (result.status !== "ready") {
      const stopped: any = { status: result.status, path, current_step_id: current, candidates: result.candidates, iteration_counts };
      if (["requires_observation", "unknown_outcome"].includes(result.status)) Object.assign(stopped, { object_result: "not_evaluated", operation_outcome: "indeterminate" });
      return stopped;
    }
    if (result.candidates.length > 1) return { status: "ambiguous_control", path, current_step_id: current, candidates: result.candidates, iteration_counts };
    if (!result.candidates.length) return { status: "completed", path, current_step_id: current, iteration_counts };
    const transition: any = result.candidates[0];
    if (transition.kind === "loop") {
      const controller = transition.to_step_id;
      iteration_counts[controller] = (iteration_counts[controller] ?? 0) + 1;
      if (iteration_counts[controller] >= (steps.get(controller) as any).max_iterations) return { status: "iteration_limit_reached", path, current_step_id: current, iteration_counts };
    }
    current = transition.to_step_id;
  }
  return { status: "max_steps_reached", path, current_step_id: current, iteration_counts };
}

export function executeFixtureSuite(contractRoot: URL) {
  const suite = JSON.parse(readFileSync(new URL("fixtures/cases.json", contractRoot), "utf8"));
  return suite.cases.map((caseValue: any) => {
    const value = materialize(caseValue, suite);
    let actual;
    if (value.mode === "revision") actual = validateRevisionTransition(value.previous, value.candidate);
    else {
      actual = validateGraph(value.flow);
      if (actual.object_result === "valid" && value.mode === "reference") actual = validateReferences(value.flow, value.snapshot);
    }
    return { case_id: caseValue.case_id, actual, expected: structuredClone(caseValue.expected) };
  });
}
