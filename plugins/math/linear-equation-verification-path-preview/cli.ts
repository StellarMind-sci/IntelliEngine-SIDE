import { readFileSync } from "node:fs";

import { renderVerificationPathPreviewHtml } from "./render.ts";
import { createLinearEquationVerificationPathPreview } from "./verification-path-preview.ts";

type CaseName = "verification" | "unmapped" | "empty" | "invalid";
type Format = "json" | "html";
type FixedInput = { source: { text: string; source_ref: string }; flow_context: "verification" | "none" };

const caseNames = new Set<CaseName>(["verification", "unmapped", "empty", "invalid"]);
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

function fixture(caseName: CaseName): FixedInput {
  const raw = JSON.parse(readFileSync(new URL("./fixtures/demo-cases.json", import.meta.url), "utf8")) as Record<CaseName, FixedInput>;
  return structuredClone(raw[caseName]);
}

function usage(): string {
  return "错误：仅支持 --case <verification|unmapped|empty|invalid> --format <json|html>。\n";
}

export function main(args: readonly string[]): number {
  const parsed = parseArguments(args);
  if (parsed === null) {
    process.stderr.write(usage());
    return 2;
  }
  const preview = createLinearEquationVerificationPathPreview(fixture(parsed.caseName));
  const output = parsed.format === "json"
    ? `${JSON.stringify(preview, null, 2)}\n`
    : renderVerificationPathPreviewHtml(preview);
  process.stdout.write(output);
  return 0;
}

process.exitCode = main(process.argv.slice(2));