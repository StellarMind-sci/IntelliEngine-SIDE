import { readFileSync } from "node:fs";

import { createKnowledgeEvidencePreview, fixedKnowledgeUnitContractRoot } from "./navigator.ts";
import { renderKnowledgeEvidencePreviewHtml } from "./render.ts";

const fixtures = JSON.parse(readFileSync(new URL("./fixtures/demo-cases.json", import.meta.url), "utf8")) as Record<string, unknown>;
const cases = new Set(["blocked", "needs-evidence", "ready", "empty", "invalid"]);
const formats = new Set(["json", "html"]);

function fail(message: string): never { process.stderr.write(`${message}\n`); process.exit(1); }
function options(args: string[]): { caseId: string; format: string } {
  if (args.length !== 4 || args[0] !== "--case" || args[2] !== "--format") fail("expected --case <id> --format <json|html>");
  return { caseId: args[1], format: args[3] };
}

const { caseId, format } = options(process.argv.slice(2));
if (!cases.has(caseId)) fail(`unknown demo case: ${caseId}`);
if (!formats.has(format)) fail(`unknown output format: ${format}`);
const source = caseId === "invalid" ? {} : fixtures[caseId];
if (source === undefined) fail(`unknown demo case: ${caseId}`);
const request = caseId === "invalid" ? source : { ...(source as Record<string, unknown>), contract_root: fixedKnowledgeUnitContractRoot() };
const result = createKnowledgeEvidencePreview(request);
process.stdout.write(format === "json" ? `${JSON.stringify(result, null, 2)}\n` : renderKnowledgeEvidencePreviewHtml(result));
