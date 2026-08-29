import { readFileSync } from "node:fs";

import { createKnowledgeImpactNavigator } from "./navigator.ts";
import { renderKnowledgeImpactNavigatorHtml } from "./render.ts";
const FIXTURES = JSON.parse(readFileSync(new URL("./fixtures/demo-cases.json", import.meta.url), "utf8")) as Record<string, unknown>;
const CASE_IDS = new Set(["blocked", "needs-evidence", "ready", "empty", "invalid"]);
const FORMAT_IDS = new Set(["json", "html"]);

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function options(args: string[]): { caseId: string; format: string } {
  if (args.length !== 4 || args[0] !== "--case" || args[2] !== "--format") {
    fail("expected --case <id> --format <json|html>");
  }
  return { caseId: args[1], format: args[3] };
}

const { caseId, format } = options(process.argv.slice(2));
if (!CASE_IDS.has(caseId)) fail(`unknown demo case: ${caseId}`);
if (!FORMAT_IDS.has(format)) fail(`unknown output format: ${format}`);

const request = caseId === "needs-evidence"
  ? FIXTURES.needs_evidence
  : caseId === "invalid"
    ? {}
    : Object.hasOwn(FIXTURES, caseId) ? FIXTURES[caseId] : undefined;
if (request === undefined) fail(`unknown demo case: ${caseId}`);

const result = createKnowledgeImpactNavigator(request);
process.stdout.write(format === "json" ? `${JSON.stringify(result, null, 2)}\n` : renderKnowledgeImpactNavigatorHtml(result));