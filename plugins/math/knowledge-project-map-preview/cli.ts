import { renderKnowledgeProjectMapPreviewHtml } from "./render.ts";
import { createKnowledgeProjectMapPreview } from "./project-map-preview.ts";

type CaseName = "normal" | "blocked" | "empty" | "invalid";
type Format = "json" | "html";

const caseNames = new Set<CaseName>(["normal", "blocked", "empty", "invalid"]);
const formats = new Set<Format>(["json", "html"]);

function parseArguments(args: readonly string[]): { caseName: CaseName; format: Format } | null {
  if (args.length !== 4) return null;
  const values = new Map<string, string>();
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if ((key !== "--case" && key !== "--format") || value === undefined || values.has(key)) return null;
    values.set(key, value);
  }
  const caseName = values.get("--case");
  const format = values.get("--format");
  if (caseName === undefined || format === undefined || !caseNames.has(caseName as CaseName) || !formats.has(format as Format)) return null;
  return { caseName: caseName as CaseName, format: format as Format };
}

function usage(): string {
  return "错误：仅支持 --case <normal|blocked|empty|invalid> --format <json|html>。\n";
}

export function main(args: readonly string[]): number {
  const parsed = parseArguments(args);
  if (parsed === null) {
    process.stderr.write(usage());
    return 2;
  }
  const preview = createKnowledgeProjectMapPreview({ case: parsed.caseName });
  process.stdout.write(parsed.format === "json" ? `${JSON.stringify(preview, null, 2)}\n` : renderKnowledgeProjectMapPreviewHtml(preview));
  return 0;
}

process.exitCode = main(process.argv.slice(2));