import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { validateSemantic, validateTransport } from "../../../packages/cognitive-ir/src/cognitive-node/runtime.ts";

export type CognitiveNode = {
  contract_version: "1.0.0";
  id: string;
  revision: 1;
  base_kind: "relation";
  type_id: "org.intelliengine.math/equation";
  type_version: "1.2.0";
  data: { expression: string; symbols: [string] };
  provenance_refs: [string];
};

export type LinearEquationIntakePreview = {
  mode: "preview";
  side_effects: "forbidden";
  state: "ready" | "empty" | "invalid_input";
  source: { text: string; source_ref: string | null };
  normalized_equation: string | null;
  variable: string | null;
  candidate_node: CognitiveNode | null;
  validation: { transport: "valid"; semantic: "valid" } | null;
  diagnostic: string | null;
};

type ParsedEquation = { coefficient: number; variable: string; constant: number; rightHandSide: number; normalized: string };
type JsonObject = Record<string, unknown>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function fixedCognitiveNodeContractRoot(): string {
  return fileURLToPath(new URL("../../../packages/cognitive-ir/contracts/cognitive-node/1.0.0/", import.meta.url));
}

function sourceOf(value: unknown): LinearEquationIntakePreview["source"] {
  if (!isRecord(value)) return { text: "", source_ref: null };
  return {
    text: typeof value.text === "string" ? value.text : "",
    source_ref: typeof value.source_ref === "string" ? value.source_ref : null,
  };
}

function result(
  state: LinearEquationIntakePreview["state"],
  source: LinearEquationIntakePreview["source"],
  diagnostic: string | null,
  equation: ParsedEquation | null = null,
  candidate: CognitiveNode | null = null,
): LinearEquationIntakePreview {
  return {
    mode: "preview",
    side_effects: "forbidden",
    state,
    source,
    normalized_equation: equation?.normalized ?? null,
    variable: equation?.variable ?? null,
    candidate_node: candidate,
    validation: state === "ready" ? { transport: "valid", semantic: "valid" } : null,
    diagnostic,
  };
}

function validRequest(value: unknown): value is { text: string; source_ref: string } {
  return (
    isRecord(value) &&
    Object.keys(value).length === 2 &&
    Object.prototype.hasOwnProperty.call(value, "text") &&
    Object.prototype.hasOwnProperty.call(value, "source_ref") &&
    typeof value.text === "string" &&
    typeof value.source_ref === "string" &&
    value.source_ref.length > 0 &&
    value.source_ref.trim() === value.source_ref
  );
}

function safeInteger(text: string): number | null {
  try {
    const parsed = BigInt(text);
    if (parsed < BigInt(Number.MIN_SAFE_INTEGER) || parsed > BigInt(Number.MAX_SAFE_INTEGER)) return null;
    return Number(parsed);
  } catch {
    return null;
  }
}

function canonicalEquation(coefficient: number, variable: string, constant: number, rightHandSide: number): string {
  return `${coefficient}*${variable} ${constant < 0 ? "-" : "+"} ${Math.abs(constant)} = ${rightHandSide}`;
}

function parseEquation(text: string): ParsedEquation | null {
  const compact = text.replace(/\s/g, "");
  const parts = compact.split("=");
  if (parts.length !== 2 || parts[0].length === 0 || parts[1].length === 0) return null;
  const left = /^([+-]?)(\d*)(\*?)([A-Za-z])([+-]\d+)?$/.exec(parts[0]);
  if (left === null || !/^[+-]?\d+$/.test(parts[1])) return null;
  const [, sign, coefficientText, multiply, variable, constantText] = left;
  if (multiply === "*" && coefficientText.length === 0) return null;
  const coefficientMagnitude = coefficientText.length === 0 ? 1 : safeInteger(coefficientText);
  const rightHandSide = safeInteger(parts[1]);
  const constant = constantText === undefined ? 0 : safeInteger(constantText);
  if (coefficientMagnitude === null || rightHandSide === null || constant === null) return null;
  const coefficient = sign === "-" ? -coefficientMagnitude : coefficientMagnitude;
  if (!Number.isSafeInteger(coefficient) || coefficient === 0) return null;
  return { coefficient, variable, constant, rightHandSide, normalized: canonicalEquation(coefficient, variable, constant, rightHandSide) };
}

function uuidFromCanonicalText(canonicalText: string, sourceRef: string): string {
  const bytes = createHash("sha256").update(`${canonicalText}\n${sourceRef}`, "utf8").digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function mathDefinition(contractRoot: string): JsonObject {
  const suite = JSON.parse(readFileSync(join(contractRoot, "fixtures", "cases.json"), "utf8")) as { cases: JsonObject[] };
  const fixture = suite.cases.find((candidate) => candidate.case_id === "math-equation-type-definition-valid");
  if (fixture === undefined || !isRecord(fixture.input)) throw new Error("math equation type definition is unavailable");
  return fixture.input;
}

function contractSchema(contractRoot: string): JsonObject {
  return JSON.parse(readFileSync(join(contractRoot, "schemas", "cognitive-node.schema.json"), "utf8")) as JsonObject;
}

export function createLinearEquationIntakePreview(request: unknown): LinearEquationIntakePreview {
  const source = sourceOf(request);
  if (!validRequest(request)) return result("invalid_input", source, "请求必须只包含 text 和 source_ref。" );
  if (request.text.trim().length === 0) return result("empty", source, "输入为空。" );
  const equation = parseEquation(request.text);
  if (equation === null) return result("invalid_input", source, "输入不符合受限的一元一次方程格式。" );

  const node: CognitiveNode = {
    contract_version: "1.0.0",
    id: uuidFromCanonicalText(equation.normalized, request.source_ref),
    revision: 1,
    base_kind: "relation",
    type_id: "org.intelliengine.math/equation",
    type_version: "1.2.0",
    data: { expression: equation.normalized, symbols: [equation.variable] },
    provenance_refs: [request.source_ref],
  };
  try {
    const root = fixedCognitiveNodeContractRoot();
    const transport = validateTransport(node, contractSchema(root));
    const semantic = validateSemantic(node, contractSchema(root), mathDefinition(root), "exact-math-equation");
    if (transport.object_result !== "valid" || semantic.object_result !== "valid") {
      return result("invalid_input", source, "候选节点未通过固定 CognitiveNode 校验。" );
    }
  } catch {
    return result("invalid_input", source, "候选节点未通过固定 CognitiveNode 校验。" );
  }
  return result("ready", source, null, equation, node);
}
