import { canonicalize } from "./strict-json.ts";

type JsonObject = Record<string, unknown>;

export class SchemaError extends Error {
  pointer: string;
  constructor(pointer: string) {
    super(`schema validation failed at ${pointer}`);
    this.pointer = pointer;
  }
}

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function pointer(root: unknown, fragment: string) {
  if (fragment === "#") return root;
  if (!fragment.startsWith("#/")) throw new SchemaError("");
  let current = root;
  for (const raw of fragment.slice(2).split("/")) {
    const part = raw.replaceAll("~1", "/").replaceAll("~0", "~");
    if (!object(current) || !(part in current)) throw new SchemaError(fragment);
    current = current[part];
  }
  return current;
}

function typeMatches(value: unknown, type: string) {
  if (type === "null") return value === null;
  if (type === "array") return Array.isArray(value);
  if (type === "object") return object(value);
  if (type === "integer") return typeof value === "number" && Number.isInteger(value);
  if (type === "number") return typeof value === "number";
  return typeof value === type;
}

function equal(left: unknown, right: unknown) {
  return canonicalize(left) === canonicalize(right);
}

export function validateMachineSchema(
  value: unknown,
  schema: unknown,
  rootSchema: unknown,
  registry: Map<string, unknown>,
  at = "",
): boolean {
  if (typeof schema === "boolean") return schema;
  if (!object(schema)) return false;
  if (typeof schema.$ref === "string") {
    const target = schema.$ref.startsWith("#") ? pointer(rootSchema, schema.$ref) : registry.get(schema.$ref);
    if (target === undefined || !validateMachineSchema(value, target, schema.$ref.startsWith("#") ? rootSchema : target, registry, at)) return false;
  }
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => typeof type === "string" && typeMatches(value, type))) return false;
  }
  if ("const" in schema && !equal(value, schema.const)) return false;
  if (Array.isArray(schema.enum) && !schema.enum.some((item) => equal(value, item))) return false;
  if (typeof schema.pattern === "string" && (typeof value !== "string" || !new RegExp(schema.pattern, "u").test(value))) return false;
  if (typeof schema.minimum === "number" && (typeof value !== "number" || value < schema.minimum)) return false;
  if (typeof schema.maximum === "number" && (typeof value !== "number" || value > schema.maximum)) return false;
  if (Array.isArray(schema.allOf) && !schema.allOf.every((item) => validateMachineSchema(value, item, rootSchema, registry, at))) return false;
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some((item) => validateMachineSchema(value, item, rootSchema, registry, at))) return false;
  if (Array.isArray(schema.oneOf) && schema.oneOf.filter((item) => validateMachineSchema(value, item, rootSchema, registry, at)).length !== 1) return false;
  if (schema.not !== undefined && validateMachineSchema(value, schema.not, rootSchema, registry, at)) return false;
  if (schema.if !== undefined && validateMachineSchema(value, schema.if, rootSchema, registry, at)) {
    if (schema.then !== undefined && !validateMachineSchema(value, schema.then, rootSchema, registry, at)) return false;
  } else if (schema.else !== undefined && !validateMachineSchema(value, schema.else, rootSchema, registry, at)) return false;
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) return false;
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) return false;
    if (schema.uniqueItems === true && new Set(value.map(canonicalize)).size !== value.length) return false;
    if (schema.items !== undefined && !value.every((item, index) => validateMachineSchema(item, schema.items, rootSchema, registry, `${at}/${index}`))) return false;
  }
  if (object(value)) {
    const required = Array.isArray(schema.required) ? schema.required : [];
    if (!required.every((key) => typeof key === "string" && key in value)) return false;
    const properties = object(schema.properties) ? schema.properties : {};
    for (const [key, child] of Object.entries(properties)) {
      if (key in value && !validateMachineSchema(value[key], child, rootSchema, registry, `${at}/${key}`)) return false;
    }
    for (const key of Object.keys(value)) {
      if (key in properties) continue;
      if (schema.additionalProperties === false) return false;
      if (object(schema.additionalProperties) || typeof schema.additionalProperties === "boolean") {
        if (!validateMachineSchema(value[key], schema.additionalProperties, rootSchema, registry, `${at}/${key}`)) return false;
      }
    }
  }
  return true;
}

export function assertMachineSchema(value: unknown, schema: unknown, registry: Map<string, unknown>) {
  if (!validateMachineSchema(value, schema, schema, registry)) throw new SchemaError("");
}
