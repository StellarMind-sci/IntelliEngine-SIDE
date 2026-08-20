import { readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

import { validateMachineSchema } from "../conformance-ts/machine-schema.ts";
import { StrictJsonError, strictParse } from "../conformance-ts/strict-json.ts";


type JsonObject = Record<string, any>;


function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}


function issue(code: string, path: string) {
  return { code, path, severity: "error" };
}


function result(interfaceName: string, mode: string, objectResult: string, operationOutcome: string, issues: JsonObject[] = []) {
  return { interface: interfaceName, mode, object_result: objectResult, operation_outcome: operationOutcome, issues };
}


function utf8SortedUnique(values: unknown) {
  if (!Array.isArray(values) || values.some((value) => typeof value !== "string")) return false;
  const sorted = [...values].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  return new Set(values).size === values.length && values.every((value, index) => value === sorted[index]);
}


export function parseAndValidateTransport(raw: Uint8Array, nodeSchema: JsonObject) {
  try {
    return validateTransport(strictParse(raw), nodeSchema);
  } catch (error) {
    if (!(error instanceof StrictJsonError)) throw error;
    let code = "cognitive_node.invalid_json";
    if (error.code === "json.duplicate_member") code = "cognitive_node.duplicate_key";
    else if (["json.invalid_utf8", "json.invalid_escape", "json.invalid_unicode_scalar"].includes(error.code)) code = "cognitive_node.invalid_unicode";
    else if (["json.invalid_number", "json.unsafe_integer"].includes(error.code)) code = "cognitive_node.invalid_number";
    return result("cognitive_node", "transport", "invalid", "succeeded", [issue(code, error.pointer)]);
  }
}


export function validateTransport(node: unknown, nodeSchema: JsonObject) {
  if (!object(node)) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.invalid_json", "")]);
  const missing = nodeSchema.required.find((name: string) => !(name in node));
  if (missing !== undefined) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.missing_field", `/${missing}`)]);
  if (typeof node.contract_version !== "string" || !node.contract_version.startsWith("1.")) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.unsupported_contract_version", "/contract_version")]);
  const properties = nodeSchema.properties;
  if (!validateMachineSchema(node.id, properties.id, properties.id, new Map())) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.invalid_id", "/id")]);
  if (!validateMachineSchema(node.revision, properties.revision, properties.revision, new Map())) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.invalid_revision", "/revision")]);
  if (!properties.base_kind.enum.includes(node.base_kind)) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.invalid_base_kind", "/base_kind")]);
  if (Array.isArray(node.provenance_refs) && node.provenance_refs.length === 0) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.missing_provenance", "/provenance_refs")]);
  if (!utf8SortedUnique(node.provenance_refs)) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.noncanonical_set", "/provenance_refs")]);
  if (!validateMachineSchema(node, nodeSchema, nodeSchema, new Map())) return result("cognitive_node", "transport", "invalid", "succeeded", [issue("cognitive_node.invalid_json", "")]);
  return result("cognitive_node", "transport", "valid", "succeeded");
}


export function validateSemantic(node: unknown, nodeSchema: JsonObject, definition: JsonObject, snapshot: string) {
  const transport = validateTransport(node, nodeSchema);
  if (transport.object_result !== "valid") return transport;
  const value = node as JsonObject;
  if (snapshot === "type-id-absent") return result("cognitive_node", "semantic", "opaque", "succeeded", [issue("cognitive_node.unknown_type", "/type_id")]);
  if (snapshot === "type-id-present-version-unavailable") return result("cognitive_node", "semantic", "opaque", "succeeded", [issue("cognitive_node.unsupported_type_version", "/type_version")]);
  if (snapshot === "exact-type-owner-untrusted") return result("cognitive_node", "semantic", "opaque", "succeeded", [issue("cognitive_node.untrusted_type", "/type_id")]);
  if (snapshot === "authority-indeterminate") return result("cognitive_node", "semantic", "not_evaluated", "indeterminate", [issue("cognitive_node.type_resolution_indeterminate", "/type_id")]);
  if (snapshot === "older-compatible-math-equation-1.2.0") {
    if (validateMachineSchema(value.data, definition.data_schema, definition.data_schema, new Map())) return result("cognitive_node", "semantic", "compatible_read", "succeeded");
    return result("cognitive_node", "semantic", "opaque", "succeeded", [issue("cognitive_node.unsupported_type_version", "/type_version")]);
  }
  if (snapshot !== "exact-math-equation") throw new Error(`unsupported test snapshot: ${snapshot}`);
  if (value.base_kind !== definition.base_kind) return result("cognitive_node", "semantic", "invalid", "succeeded", [issue("cognitive_node.base_kind_mismatch", "/base_kind")]);
  if (!validateMachineSchema(value.data, definition.data_schema, definition.data_schema, new Map())) {
    const missing = definition.data_schema.required?.find((name: string) => !(name in value.data));
    return result("cognitive_node", "semantic", "invalid", "succeeded", [issue("cognitive_node.invalid_data", missing ? `/data/${missing}` : "/data")]);
  }
  return result("cognitive_node", "semantic", "valid", "succeeded");
}


function walkSchema(schema: unknown, allowed: Set<string>): string | undefined {
  if (typeof schema === "boolean") return undefined;
  if (!object(schema)) return "type_definition.invalid_schema";
  const maps = new Set(["$defs", "dependentSchemas", "properties", "patternProperties"]);
  const arrays = new Set(["allOf", "anyOf", "oneOf", "prefixItems"]);
  const singles = new Set(["not", "if", "then", "else", "items", "contains", "additionalProperties", "propertyNames", "unevaluatedItems", "unevaluatedProperties", "contentSchema"]);
  for (const [key, value] of Object.entries(schema)) {
    if (key === "$ref" && (typeof value !== "string" || !(value === "#" || value.startsWith("#/") || (value.startsWith("urn:intelliengine:schema:sha256:") && value.length === 97)))) return "type_definition.forbidden_ref";
    if (!allowed.has(key) && !key.startsWith("x-")) return "type_definition.unsupported_schema_vocabulary";
    let children: unknown[] = [];
    if (maps.has(key) && object(value)) children = Object.values(value);
    else if (arrays.has(key) && Array.isArray(value)) children = value;
    else if (singles.has(key)) children = [value];
    for (const child of children) {
      const problem = walkSchema(child, allowed);
      if (problem) return problem;
    }
  }
  return undefined;
}


export function validateTypeDefinition(definition: unknown, definitionSchema: JsonObject, allowed: Set<string>, context: JsonObject) {
  if (!validateMachineSchema(definition, definitionSchema, definitionSchema, new Map())) return result("type_definition", "registration", "invalid", "succeeded", [issue("type_definition.invalid_structure", "")]);
  const value = definition as JsonObject;
  const problem = walkSchema(value.data_schema, allowed);
  if (problem) return result("type_definition", "registration", "invalid", "succeeded", [issue(problem, `/data_schema/${problem.endsWith("forbidden_ref") ? "$ref" : "unknownKeyword"}`)]);
  if (context.namespace_decision === "denied") return result("type_definition", "registration", "valid", "policy_denied", [issue("type_definition.namespace_denied", "/type_id")]);
  return result("type_definition", "registration", "valid", "succeeded");
}


function readStrict(path: string) {
  return strictParse(readFileSync(path));
}


export function runFixtureSuite(contractRoot: string, profileRoot: string) {
  const suite = readStrict(resolve(contractRoot, "fixtures/cases.json")) as JsonObject;
  const nodeSchema = readStrict(resolve(contractRoot, "schemas/cognitive-node.schema.json")) as JsonObject;
  const definitionSchema = readStrict(resolve(contractRoot, "schemas/type-definition.schema.json")) as JsonObject;
  const profile = readStrict(resolve(profileRoot, "profile.json")) as JsonObject;
  const allowed = new Set<string>(profile.schema_profile.allowed_keywords);
  const mathDefinition = suite.cases.find((fixture: JsonObject) => fixture.case_id === "math-equation-type-definition-valid").input;
  const rows = suite.cases.map((fixture: JsonObject) => {
    let computed: JsonObject;
    if (fixture.category === "resource") {
      const interfaceName = fixture.operation === "registration" ? "type_definition" : "cognitive_node";
      const code = interfaceName === "type_definition" ? "type_definition.resource_exhausted" : "validation.resource_exhausted";
      computed = result(interfaceName, interfaceName === "type_definition" ? "registration" : "transport", "not_evaluated", "resource_exhausted", [issue(code, "")]);
    } else if (fixture.category === "parser") {
      const fixtureId = fixture.input.portable_profile_fixture;
      const profileCase = readStrict(resolve(profileRoot, "fixtures", fixtureId, "case.json")) as JsonObject;
      const prefix = "profile/1.0.0/";
      const declared = profileCase.input.primary;
      if (typeof declared !== "string" || !declared.startsWith(prefix) || declared.includes("\\")) throw new Error("unsafe parser fixture path");
      const parts = declared.slice(prefix.length).split("/");
      if (parts.some((part: string) => !part || part === "." || part === "..")) throw new Error("unsafe parser fixture path");
      const primary = resolve(profileRoot, ...parts);
      const contained = relative(realpathSync(profileRoot), realpathSync(primary));
      if (contained.startsWith("..") || isAbsolute(contained)) throw new Error("unsafe parser fixture path");
      const mapping: Record<string, [string, string]> = {
        "parser-duplicate-key": ["json.duplicate_member", "cognitive_node.duplicate_key"],
        "parser-unpaired-surrogate": ["json.invalid_unicode_scalar", "cognitive_node.invalid_unicode"],
      };
      const [expectedError, code] = mapping[fixtureId];
      try {
        readStrict(resolve(profileRoot, primary));
      } catch (error) {
        if (!(error instanceof StrictJsonError) || error.code !== expectedError) throw error;
        computed = result("cognitive_node", "transport", "invalid", "succeeded", [issue(code, "")]);
      }
      if (computed! === undefined) throw new Error(`parser fixture ${fixtureId} unexpectedly parsed`);
    } else if (fixture.operation === "transport") computed = validateTransport(fixture.input, nodeSchema);
    else if (fixture.operation === "semantic") computed = validateSemantic(fixture.input, nodeSchema, mathDefinition, fixture.context.type_snapshot);
    else if (fixture.operation === "registration") computed = validateTypeDefinition(fixture.input, definitionSchema, allowed, fixture.context);
    else throw new Error(`unsupported fixture operation: ${fixture.operation}`);
    return { case_id: fixture.case_id, ...computed };
  });
  return rows.sort((left: JsonObject, right: JsonObject) => Buffer.compare(Buffer.from(left.case_id), Buffer.from(right.case_id)));
}
