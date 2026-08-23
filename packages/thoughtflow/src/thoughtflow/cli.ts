import { realpathSync, readFileSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { graphSummary, nextCandidates, validateReferences, validateRevisionTransition } from "./runtime.ts";
import { materialize, validateGraph } from "./validation.ts";

function safeFixture(rootValue: string, fixturePath: string) {
  if (fixturePath.includes("\\") || isAbsolute(fixturePath) || fixturePath.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("unsafe fixture path");
  const root = realpathSync(rootValue);
  const candidate = realpathSync(resolve(root, ...fixturePath.split("/")));
  const rel = relative(root, candidate);
  if (rel.startsWith("..") || isAbsolute(rel) || rel.split(sep).includes("..")) throw new Error("fixture escapes contract root");
  return candidate;
}

export function projection(rootValue: string, fixturePath = "fixtures/cases.json") {
  const suite = JSON.parse(readFileSync(safeFixture(rootValue, fixturePath), "utf8"));
  const fixtures = suite.cases.map((caseValue: any) => {
    const value = materialize(caseValue, suite);
    let actual, summary = null, queries: any[] = [];
    if (value.mode === "revision") actual = validateRevisionTransition(value.previous, value.candidate);
    else {
      actual = validateGraph(value.flow);
      if (actual.object_result === "valid" && value.mode === "reference") actual = validateReferences(value.flow, value.snapshot);
      if (actual.object_result === "valid") {
        summary = graphSummary(value.flow);
        queries = value.flow.steps.map((step: any) => ({ step_id: step.step_id, result: nextCandidates(value.flow, step.step_id) }));
      }
    }
    return { case_id: caseValue.case_id, actual, summary, queries };
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
