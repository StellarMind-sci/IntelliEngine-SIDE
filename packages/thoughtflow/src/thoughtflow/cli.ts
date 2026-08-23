import { realpathSync, readFileSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { strictParse } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";
import { graphSummary, nextCandidates, simulateBounded, validateReferences, validateRevisionTransition } from "./runtime.ts";
import { materialize, validateGraph } from "./validation.ts";

function safeFixture(rootValue: string, fixturePath: string) {
  const parts = fixturePath.split("/");
  if (!fixturePath || fixturePath.includes("\\") || isAbsolute(fixturePath) || /^[A-Za-z]:\//u.test(fixturePath) || fixturePath.startsWith("//") || parts.some((part) => !part || part === "." || part === "..")) throw new Error("unsafe fixture path");
  const root = realpathSync(rootValue);
  const candidate = realpathSync(resolve(root, ...parts));
  const rel = relative(root, candidate);
  if (rel.startsWith("..") || isAbsolute(rel) || rel.split(sep).includes("..")) throw new Error("fixture escapes contract root");
  return candidate;
}

function queryProjection(flow: any) {
  const queries: any[] = [];
  for (const step of flow.steps) {
    const stepId = step.step_id;
    queries.push({ input: { step_id: stepId }, result: nextCandidates(flow, stepId) });
    const outgoing = flow.transitions.filter((item: any) => item.from_step_id === stepId);
    if (["decision", "iteration"].includes(step.kind)) {
      for (const transition of outgoing.filter((item: any) => item.kind === "branch")) {
        queries.push({
          input: { selected_branch: transition.branch_label, step_id: stepId },
          result: nextCandidates(flow, stepId, { selectedBranch: transition.branch_label }),
        });
      }
    }
    if (step.kind === "verification") {
      const seen = new Set<string>();
      for (const transition of outgoing) {
        if (transition.outcome !== undefined && !seen.has(transition.outcome)) {
          seen.add(transition.outcome);
          queries.push({
            input: { observed_outcome: transition.outcome, step_id: stepId },
            result: nextCandidates(flow, stepId, { observedOutcome: transition.outcome }),
          });
        }
      }
    }
  }
  return queries;
}

function scenarioInputs(flow: any, chooseLast: boolean) {
  const observations: Record<string, string[]> = {}, branchSelections: Record<string, string[]> = {};
  for (const step of flow.steps) {
    const outgoing = flow.transitions.filter((item: any) => item.from_step_id === step.step_id);
    if (["decision", "iteration"].includes(step.kind)) {
      const values = outgoing.filter((item: any) => item.kind === "branch").map((item: any) => item.branch_label);
      if (values.length) branchSelections[step.step_id] = Array(100).fill(values[chooseLast ? values.length - 1 : 0]);
    }
    if (step.kind === "verification") {
      const values = [...new Set(outgoing.filter((item: any) => item.outcome !== undefined).map((item: any) => item.outcome))] as string[];
      if (values.length) observations[step.step_id] = Array(100).fill(values[chooseLast ? values.length - 1 : 0]);
    }
  }
  return { observations, branchSelections };
}

function simulationProjection(flow: any) {
  const first = scenarioInputs(flow, false), last = scenarioInputs(flow, true);
  const scenarios = [
    { scenario_id: "missing_inputs", observations: {}, branchSelections: {}, maxSteps: 40 },
    { scenario_id: "first_options", ...first, maxSteps: 40 },
    { scenario_id: "last_options", ...last, maxSteps: 40 },
    { scenario_id: "max_steps_one", observations: {}, branchSelections: {}, maxSteps: 1 },
  ];
  return scenarios.map(({ scenario_id, observations, branchSelections, maxSteps }) => ({
    scenario_id,
    input: { branch_selections: branchSelections, max_steps: maxSteps, observations },
    result: simulateBounded(flow, { observations, branchSelections, maxSteps }),
  }));
}

export function projection(rootValue: string, fixturePath = "fixtures/cases.json") {
  const suite: any = strictParse(readFileSync(safeFixture(rootValue, fixturePath)));
  const fixtures = suite.cases.map((caseValue: any) => {
    const value = materialize(caseValue, suite);
    let actual, summary = null, queries: any[] = [], simulations: any[] = [];
    if (value.mode === "revision") actual = validateRevisionTransition(value.previous, value.candidate);
    else {
      actual = validateGraph(value.flow);
      if (actual.object_result === "valid" && value.mode === "reference") actual = validateReferences(value.flow, value.snapshot);
      if (actual.object_result === "valid") {
        summary = graphSummary(value.flow);
        queries = queryProjection(value.flow);
        simulations = simulationProjection(value.flow);
      }
    }
    return { case_id: caseValue.case_id, actual, expected: structuredClone(caseValue.expected), summary, queries, simulations };
  });
  return { contract_version: suite.contract_version, fixtures };
}

function argument(name: string, fallback?: string) {
  const index = process.argv.indexOf(name);
  if (index < 0) {
    if (fallback !== undefined) return fallback;
    throw new Error(`missing ${name}`);
  }
  return process.argv[index + 1];
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const root = argument("--contract-root");
    const fixture = argument("--fixture-path", "fixtures/cases.json");
    process.stdout.write(JSON.stringify(projection(root, fixture)));
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    process.exitCode = 2;
  }
}