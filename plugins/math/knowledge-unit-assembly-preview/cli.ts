import { readFileSync } from "node:fs";

import { createLinearEquationIntakePreview } from "../linear-equation-intake-preview/intake.ts";
import { createLinearEquationKnowledgeUnitAssemblyPreview } from "./assembly.ts";
import { renderLinearEquationKnowledgeUnitAssemblyPreviewHtml } from "./render.ts";

type DemoInput = { text: string; source_ref: string };

const cases = new Set(["needs-evidence", "empty", "invalid"]);
const formats = new Set(["json", "html"]);
const fixtures = JSON.parse(readFileSync(new URL("./fixtures/demo-cases.json", import.meta.url), "utf8")) as { cases?: unknown };

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function options(args: string[]): { caseId: string; format: string } {
  if (args.length !== 4 || args[0] !== "--case" || args[2] !== "--format") fail("expected --case <id> --format <json|html>");
  return { caseId: args[1], format: args[3] };
}

function fixtureFor(caseId: string): DemoInput {
  if (!Array.isArray(fixtures.cases)) fail(`unknown demo case: ${caseId}`);
  const matched = fixtures.cases.find((entry) => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry) || Object.getPrototypeOf(entry) !== Object.prototype) return false;
    return Object.hasOwn(entry, "case_id") && (entry as { case_id?: unknown }).case_id === caseId;
  });
  if (typeof matched !== "object" || matched === null || Array.isArray(matched) || !Object.hasOwn(matched, "input")) fail(`unknown demo case: ${caseId}`);
  return (matched as { input: DemoInput }).input;
}

const { caseId, format } = options(process.argv.slice(2));
if (!cases.has(caseId)) fail(`unknown demo case: ${caseId}`);
if (!formats.has(format)) fail(`unknown output format: ${format}`);
const intake = createLinearEquationIntakePreview(fixtureFor(caseId));
const result = createLinearEquationKnowledgeUnitAssemblyPreview({ intake_preview: intake });
process.stdout.write(format === "json" ? `${JSON.stringify(result, null, 2)}\n` : renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(result));