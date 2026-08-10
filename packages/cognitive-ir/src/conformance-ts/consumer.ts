import { createHash } from "node:crypto";
import { existsSync, readFileSync, realpathSync, readdirSync } from "node:fs";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";

import { assertMachineSchema } from "./machine-schema.ts";
import { canonicalize, StrictJsonError, strictParse } from "./strict-json.ts";

type JsonObject = Record<string, any>;

// This fingerprint closes the complete machine grammar consumed below: every
// production alternative/reference/repeat, terminal lexeme/predicate/catalog,
// AST catalog, forbidden feature and repeat constraint is part of the JCS.
// The recursive-descent functions are the implementation projection of that
// exact program; a profile revision must therefore add a reviewed consumer.
const SUPPORTED_REGEX_GRAMMAR_SHA256 = "1d09112bef6db6add5479d259fe9360fa67ae8141f3a8536e1592bef168428c8";

export class ConsumerError extends Error {
  code: string;
  constructor(code: string, detail: string) {
    super(`${code}: ${detail}`);
    this.code = code;
  }
}

const SCHEMAS = [
  "diagnostics.schema.json",
  "expected-result.schema.json",
  "fixture-case.schema.json",
  "fixture-manifest.schema.json",
  "lock.schema.json",
  "profile.schema.json",
];
const SCHEMA_MAPS = new Set(["$defs", "dependentSchemas", "properties", "patternProperties"]);
const SCHEMA_ARRAYS = new Set(["allOf", "anyOf", "oneOf", "prefixItems"]);
const SCHEMA_SINGLES = new Set(["not", "if", "then", "else", "items", "contains", "additionalProperties", "propertyNames", "unevaluatedItems", "unevaluatedProperties", "contentSchema"]);

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sha256(value: Uint8Array | string) {
  return createHash("sha256").update(value).digest("hex");
}

function utf8Sort(values: string[]) {
  return values.sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function safePath(contractRoot: string, value: unknown, mustExist = true) {
  if (typeof value !== "string" || !value || isAbsolute(value) || value.includes("\\")) throw new ConsumerError("conformance.unsafe_path", String(value));
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..") || parts[0] !== "profile") throw new ConsumerError("conformance.unsafe_path", value);
  const path = resolve(contractRoot, ...parts);
  const rel = relative(contractRoot, path);
  if (rel.startsWith("..") || isAbsolute(rel)) throw new ConsumerError("conformance.unsafe_path", value);
  if (mustExist) {
    if (!existsSync(path)) throw new ConsumerError("profile.missing_file", value);
    const real = realpathSync(path);
    const realRel = relative(realpathSync(contractRoot), real);
    if (realRel.startsWith("..") || isAbsolute(realRel)) throw new ConsumerError("conformance.unsafe_path", value);
  }
  return path;
}

function readStrict(path: string) {
  return strictParse(readFileSync(path));
}

function profileFiles(contractRoot: string, directory: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...profileFiles(contractRoot, path));
    else if (entry.isFile()) files.push(relative(contractRoot, path).replaceAll("\\", "/"));
    else throw new ConsumerError("conformance.unsafe_path", path);
  }
  return files;
}

function issue(code: string, path: string) {
  return { code, path, severity: "error" };
}

function pointerReplace(document: unknown, pointer: string, value: unknown) {
  if (!pointer.startsWith("/")) throw new ConsumerError("fixture.invalid_action", pointer);
  const parts = pointer.slice(1).split("/").map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
  let current: any = document;
  for (const part of parts.slice(0, -1)) {
    if (!object(current) || !(part in current)) throw new ConsumerError("fixture.invalid_action", pointer);
    current = current[part];
  }
  current[parts.at(-1)!] = value;
}

function strictSchemaWalk(schema: unknown, profile: JsonObject) {
  const allowed = new Set(profile.schema_profile.allowed_keywords);
  function walk(value: unknown, root: boolean) {
    if (typeof value === "boolean") {
      if (root) throw new ConsumerError("fixture.invalid_schema", "boolean root");
      return;
    }
    if (!object(value)) throw new ConsumerError("fixture.invalid_schema", "subschema is not object or boolean");
    if (root && value.$schema !== profile.schema_draft) throw new ConsumerError("fixture.invalid_schema", "$schema");
    for (const key of Object.keys(value)) {
      if (!allowed.has(key) && !key.startsWith("x-")) throw new ConsumerError("fixture.invalid_schema", key);
      if (SCHEMA_MAPS.has(key)) {
        if (!object(value[key])) throw new ConsumerError("fixture.invalid_schema", key);
        for (const child of Object.values(value[key])) walk(child, false);
      } else if (SCHEMA_ARRAYS.has(key)) {
        if (!Array.isArray(value[key])) throw new ConsumerError("fixture.invalid_schema", key);
        for (const child of value[key]) walk(child, false);
      } else if (SCHEMA_SINGLES.has(key)) {
        walk(value[key], false);
      }
      if (key === "pattern" && typeof value[key] === "string") validateRegex(value[key], profile);
      if (key === "patternProperties") for (const pattern of Object.keys(value[key])) validateRegex(pattern, profile);
    }
  }
  walk(schema, true);
}

function validateRegex(pattern: string, profile: JsonObject) {
  const scalars = Array.from(pattern);
  if (scalars.length > 1024) throw new ConsumerError("fixture.invalid_schema", "regex limit");
  const machine = profile.regex_profile;
  if (!object(machine) || !Array.isArray(machine.productions) || !Array.isArray(machine.terminals)) throw new ConsumerError("profile.invalid_regex_grammar", "shape");
  if (sha256(canonicalize(machine)) !== SUPPORTED_REGEX_GRAMMAR_SHA256) throw new ConsumerError("profile.invalid_regex_grammar", "unsupported machine program");
  const productions = new Set(machine.productions.map((item: JsonObject) => item.name));
  for (const name of ["pattern", "alternation", "concatenation", "quantified-atom", "atom", "character-class", "group", "quantifier"]) {
    if (!productions.has(name)) throw new ConsumerError("profile.invalid_regex_grammar", name);
  }
  const terminals = new Map(machine.terminals.map((item: JsonObject) => [item.name, item]));
  const lexeme = (name: string, expected: string) => {
    if (terminals.get(name)?.lexeme !== expected) throw new ConsumerError("profile.invalid_regex_grammar", name);
    return expected;
  };
  for (const [name, value] of [["dot", "."], ["start-anchor", "^"], ["end-anchor", "$"], ["class-open", "["], ["class-close", "]"], ["pipe", "|"], ["group-open", "("], ["group-close", ")"], ["star", "*"], ["plus", "+"], ["question", "?"]] as const) lexeme(name, value);
  const escapeValues = terminals.get("escape")?.machine_predicate?.values;
  const excludedValues = terminals.get("literal")?.machine_predicate?.values;
  if (!Array.isArray(escapeValues) || !Array.isArray(excludedValues)) throw new ConsumerError("profile.invalid_regex_grammar", "terminal predicates");
  const escapes = new Set(escapeValues);
  const excluded = new Set(excludedValues);
  const maximum = machine.quantifier_constraints?.maximum;
  if (!Number.isInteger(maximum) || maximum !== machine.maximum_repeat) throw new ConsumerError("profile.invalid_regex_grammar", "repeat maximum");
  let index = 0;
  type Parsed = { nodes: number; alternation: boolean; quantifier: boolean; group: boolean };
  const combine = (parts: Parsed[]): Parsed => ({
    nodes: parts.reduce((sum, item) => sum + item.nodes, 0),
    alternation: parts.some((item) => item.alternation),
    quantifier: parts.some((item) => item.quantifier),
    group: parts.some((item) => item.group),
  });
  const parseEscape = () => {
    index++;
    const escaped = scalars[index++];
    if (!escaped || !escapes.has(escaped)) throw new ConsumerError("fixture.invalid_schema", "private regex escape");
  };
  const parseClass = (): Parsed => {
    index++;
    if (scalars[index] === "^") index++;
    let items = 0;
    while (index < scalars.length && scalars[index] !== "]") {
      if (scalars[index] === "\\") parseEscape();
      else {
        const first = scalars[index++];
        if (excluded.has(first) && first !== "-") throw new ConsumerError("fixture.invalid_schema", "regex class item");
        if (scalars[index] === "-" && scalars[index + 1] !== "]" && scalars[index + 1] !== undefined) {
          index++;
          if (scalars[index] === "\\") throw new ConsumerError("fixture.invalid_schema", "escaped regex range endpoint");
          const last = scalars[index++];
          if (excluded.has(last) || first.codePointAt(0)! > last.codePointAt(0)!) throw new ConsumerError("fixture.invalid_schema", "regex class range");
        }
      }
      items++;
    }
    if (scalars[index] !== "]" || items === 0) throw new ConsumerError("fixture.invalid_schema", "unterminated regex class");
    index++;
    return { nodes: 1, alternation: false, quantifier: false, group: false };
  };
  let parseAlternation: (closing?: string) => Parsed;
  const parseAtom = (): Parsed => {
    const ch = scalars[index];
    if (ch === "\\") { parseEscape(); return { nodes: 1, alternation: false, quantifier: false, group: false }; }
    if (ch === "[") return parseClass();
    if (ch === "(") {
      index++;
      const body = parseAlternation(")");
      if (scalars[index] !== ")") throw new ConsumerError("fixture.invalid_schema", "unterminated regex group");
      index++;
      return { ...body, nodes: body.nodes + 1, group: true };
    }
    if (ch === ".") { index++; return { nodes: 1, alternation: false, quantifier: false, group: false }; }
    if (ch === "^" || ch === "$") { index++; return { nodes: 0, alternation: false, quantifier: false, group: false }; }
    if (ch === undefined || excluded.has(ch) || ch === "]") throw new ConsumerError("fixture.invalid_schema", "regex atom");
    index++;
    return { nodes: 1, alternation: false, quantifier: false, group: false };
  };
  const parseQuantified = (): Parsed => {
    const atom = parseAtom();
    const ch = scalars[index];
    if (ch === undefined || !("*+?{".includes(ch))) return atom;
    if (atom.group && (atom.alternation || atom.quantifier)) throw new ConsumerError("fixture.invalid_schema", "quantified complex group");
    if (ch === "{") {
      const end = scalars.indexOf("}", index + 1);
      if (end < 0) throw new ConsumerError("fixture.invalid_schema", "regex repeat");
      const match = /^(\d+)(?:,(\d+))?$/.exec(scalars.slice(index + 1, end).join(""));
      if (!match) throw new ConsumerError("fixture.invalid_schema", "regex repeat");
      const minimum = Number(match[1]);
      const upper = match[2] === undefined ? minimum : Number(match[2]);
      if (minimum > upper || upper > maximum) throw new ConsumerError("fixture.invalid_schema", "regex repeat range");
      index = end + 1;
    } else index++;
    if (scalars[index] === "?" || scalars[index] === "+" || scalars[index] === "{" || scalars[index] === "*") throw new ConsumerError("fixture.invalid_schema", "forbidden quantifier");
    return { ...atom, nodes: atom.nodes + 1, quantifier: true };
  };
  parseAlternation = (closing?: string): Parsed => {
    const branches: Parsed[] = [];
    const sequence = (): Parsed => {
      const parts: Parsed[] = [];
      while (index < scalars.length && scalars[index] !== "|" && scalars[index] !== closing) parts.push(parseQuantified());
      return combine(parts);
    };
    branches.push(sequence());
    while (scalars[index] === "|") { index++; branches.push(sequence()); }
    const result = combine(branches);
    if (branches.length > 1) { result.nodes++; result.alternation = true; }
    return result;
  };
  const parsed = parseAlternation();
  if (index !== scalars.length) throw new ConsumerError("fixture.invalid_schema", "regex trailing punctuation");
  return { astNodes: 1 + parsed.nodes, patternScalars: scalars.length };
}

function jsonCost(value: unknown): number {
  if (Array.isArray(value)) return 1 + value.length + value.reduce((sum, item) => sum + jsonCost(item), 0);
  if (object(value)) return 1 + Object.keys(value).length + Object.values(value).reduce((sum, item) => sum + jsonCost(item), 0);
  return 1;
}

function allRefs(schema: unknown) {
  let count = 0;
  function walk(value: unknown) {
    if (typeof value === "boolean" || !object(value)) return;
    if (typeof value.$ref === "string") count++;
    for (const key of SCHEMA_MAPS) if (object(value[key])) Object.values(value[key]).forEach(walk);
    for (const key of SCHEMA_ARRAYS) if (Array.isArray(value[key])) value[key].forEach(walk);
    for (const key of SCHEMA_SINGLES) if (value[key] !== undefined) walk(value[key]);
  }
  walk(schema);
  return count;
}

function admissionUnits(schema: unknown, profile: JsonObject) {
  let units = jsonCost(schema) + 1 + Math.ceil(Buffer.byteLength(canonicalize(schema)) / 256) + 1 + allRefs(schema);
  function walk(value: unknown) {
    if (typeof value === "boolean") { units++; return; }
    if (!object(value)) throw new ConsumerError("fixture.invalid_schema", "schema value");
    units++;
    for (const key of utf8Sort(Object.keys(value))) {
      units++;
      const child = value[key];
      if (key === "$ref") units++;
      else if (SCHEMA_MAPS.has(key)) for (const name of utf8Sort(Object.keys(child))) { units++; walk(child[name]); }
      else if (SCHEMA_ARRAYS.has(key)) for (const item of child) { units++; walk(item); }
      else if (SCHEMA_SINGLES.has(key)) { units++; walk(child); }
      else {
        units += jsonCost(child);
        if (key === "pattern") {
          const regex = validateRegex(child, profile);
          units += 1 + regex.patternScalars + 1 + regex.astNodes + 1 + regex.astNodes;
        }
        if (key === "patternProperties") {
          for (const pattern of Object.keys(child)) {
            const regex = validateRegex(pattern, profile);
            units += 1 + regex.patternScalars + 1 + regex.astNodes + 1 + regex.astNodes;
          }
        }
      }
    }
  }
  walk(schema);
  return units;
}

function localCycleIsProductive(schema: JsonObject) {
  const definitions = object(schema.$defs) ? schema.$defs : {};
  const graph = new Map<string, { target: string; productive: boolean }[]>();
  function scan(owner: string, value: unknown, productive: boolean) {
    if (!object(value)) return;
    if (typeof value.$ref === "string" && value.$ref.startsWith("#/$defs/")) {
      const target = value.$ref.slice("#/$defs/".length).split("/")[0];
      const edges = graph.get(owner) ?? [];
      edges.push({ target, productive }); graph.set(owner, edges);
    }
    for (const [key, child] of Object.entries(value)) {
      const descends = productive || key === "properties" || key === "items" || key === "prefixItems" || key === "contains" || key === "additionalProperties" || key === "unevaluatedProperties" || key === "unevaluatedItems";
      if (key !== "$defs") {
        if (Array.isArray(child)) child.forEach((item) => scan(owner, item, descends));
        else if (object(child)) Object.values(child).forEach((item) => scan(owner, item, descends));
      }
    }
  }
  for (const [name, value] of Object.entries(definitions)) scan(name, value, false);
  const visiting = new Set<string>();
  function visit(name: string, productiveOnPath: boolean): boolean {
    if (visiting.has(name)) return productiveOnPath;
    visiting.add(name);
    for (const edge of graph.get(name) ?? []) if (!visit(edge.target, productiveOnPath || edge.productive)) return false;
    visiting.delete(name);
    return true;
  }
  return Object.keys(definitions).every((name) => visit(name, false));
}

function typeValid(instance: unknown, type: unknown) {
  const types = Array.isArray(type) ? type : [type];
  return types.some((candidate) => candidate === "object" ? object(instance) : candidate === "array" ? Array.isArray(instance) : candidate === "integer" ? Number.isInteger(instance) : candidate === "null" ? instance === null : typeof instance === candidate);
}

function semanticEvaluation(schema: any, instance: unknown): { valid: boolean; units: number; evaluated: Set<string> } {
  if (typeof schema === "boolean") return { valid: schema, units: 1, evaluated: new Set() };
  let valid = true;
  let units = 1;
  const evaluated = new Set<string>();
  const keys = Object.keys(schema).sort((left, right) => (left === "unevaluatedProperties" ? 1 : right === "unevaluatedProperties" ? -1 : 0));
  for (const key of keys) {
    units++;
    if (key === "type") valid = typeValid(instance, schema[key]) && valid;
    else if (key === "anyOf" || key === "allOf" || key === "oneOf") {
      const children = schema[key].map((child: unknown) => { const result = semanticEvaluation(child, instance); result.units++; return result; });
      units += children.reduce((sum: number, child: any) => sum + child.units, 0);
      const successes = children.filter((child: any) => child.valid);
      const branchValid = key === "allOf" ? successes.length === children.length : key === "anyOf" ? successes.length > 0 : successes.length === 1;
      if (branchValid) for (const child of successes) for (const name of child.evaluated) evaluated.add(name);
      valid = branchValid && valid;
    } else if (key === "unevaluatedProperties" && object(instance)) {
      for (const name of utf8Sort(Object.keys(instance))) {
        units += 2;
        if (evaluated.has(name)) continue;
        const child = semanticEvaluation(schema[key], instance[name]);
        units += child.units;
        if (child.valid) { units++; evaluated.add(name); } else valid = false;
      }
    } else if (key === "properties" && object(instance)) {
      for (const name of utf8Sort(Object.keys(schema[key]))) {
        units += 2;
        if (name in instance) {
          units++;
          const child = semanticEvaluation(schema[key][name], instance[name]); units += child.units;
          if (child.valid) { units++; evaluated.add(name); } else valid = false;
        }
      }
    } else if (key === "required" && object(instance)) {
      for (const name of schema[key]) { units += 2; if (!(name in instance)) valid = false; }
    } else if (key === "enum") {
      for (const candidate of schema[key]) { units++; units += 1 + Math.ceil(Buffer.byteLength(canonicalize(candidate)) / 256) + Math.ceil(Buffer.byteLength(canonicalize(instance)) / 256); }
      valid = schema[key].some((candidate: unknown) => canonicalize(candidate) === canonicalize(instance)) && valid;
    }
  }
  return { valid, units, evaluated };
}

interface Context {
  profileRoot: string;
  contractRoot: string;
  profile: JsonObject;
  lock: JsonObject;
  schemas: Map<string, unknown>;
  registry: Map<string, unknown>;
  resultConstants: JsonObject;
  lockedPaths: Set<string>;
}

function loadContext(profileRootInput: string): Context {
  const profileRoot = resolve(profileRootInput);
  if (basename(profileRoot) !== "1.0.0" || basename(dirname(profileRoot)) !== "profile") throw new ConsumerError("profile.invalid_root", profileRoot);
  const contractRoot = resolve(profileRoot, "../..");
  if (!existsSync(profileRoot) || !existsSync(contractRoot)) throw new ConsumerError("profile.missing_file", profileRoot);
  const lock = readStrict(safePath(contractRoot, "profile/1.0.0/lock.json")) as JsonObject;
  if (!object(lock) || !Array.isArray(lock.entries)) throw new ConsumerError("lock.invalid_manifest", "entries");
  const seen = new Set<string>();
  for (const entry of lock.entries) {
    if (!object(entry) || typeof entry.path !== "string" || typeof entry.sha256 !== "string" || seen.has(entry.path)) throw new ConsumerError("lock.invalid_manifest", "entry");
    seen.add(entry.path);
    if (entry.path === "profile/1.0.0/lock.json") throw new ConsumerError("lock.self_inclusion", entry.path);
    const path = safePath(contractRoot, entry.path);
    const bytes = readFileSync(path);
    const digest = entry.digest_kind === "raw_sha256" ? sha256(bytes) : entry.digest_kind === "jcs_sha256" ? sha256(canonicalize(strictParse(bytes))) : "";
    if (digest !== entry.sha256) throw new ConsumerError("conformance.digest_mismatch", entry.path);
  }
  const unlocked = profileFiles(contractRoot, profileRoot).filter((path) => path !== "profile/1.0.0/lock.json" && !seen.has(path));
  if (unlocked.length) throw new ConsumerError("lock.incomplete_manifest", utf8Sort(unlocked)[0]);
  const schemas = new Map<string, unknown>();
  const registry = new Map<string, unknown>();
  for (const name of SCHEMAS) {
    const schema = readStrict(safePath(contractRoot, `profile/1.0.0/schemas/${name}`));
    schemas.set(name, schema);
    registry.set(`urn:intelliengine:schema:sha256:${sha256(canonicalize(schema))}`, schema);
  }
  const profile = readStrict(safePath(contractRoot, "profile/1.0.0/profile.json")) as JsonObject;
  assertMachineSchema(profile, schemas.get("profile.schema.json"), registry);
  const ordinals = Object.values(profile.schema_profile.keyword_ordinals);
  if (new Set(ordinals).size !== ordinals.length) throw new ConsumerError("profile.duplicate_keyword_ordinal", "ordinals");
  const diagnostics = readStrict(safePath(contractRoot, "profile/1.0.0/diagnostics/conformance.json"));
  assertMachineSchema(diagnostics, schemas.get("diagnostics.schema.json"), registry);
  assertMachineSchema(lock, schemas.get("lock.schema.json"), registry);
  const resultConstants = {
    // The result schema constrains shape, while the portable profile owns the
    // concrete projection identity.
    contract_id: `${profile.profile_id}.profile`,
    contract_version: profile.profile_version,
  };
  return { profileRoot, contractRoot, profile, lock, schemas, registry, resultConstants, lockedPaths: seen };
}

function lockedPath(context: Context, value: unknown) {
  const path = safePath(context.contractRoot, value);
  if (value !== "profile/1.0.0/lock.json" && (typeof value !== "string" || !context.lockedPaths.has(value))) {
    throw new ConsumerError("lock.incomplete_manifest", String(value));
  }
  return path;
}

function outputBase(context: Context, fixture: JsonObject, primaryBytes: Buffer, parsed: unknown, includeJcs: boolean) {
  const result: JsonObject = {
    case_id: fixture.case_id,
    contract_id: context.resultConstants.contract_id,
    contract_version: context.resultConstants.contract_version,
    issues: [],
    mode: fixture.phase === "lock" ? "profile" : fixture.phase,
    object_result: "valid",
    operation_outcome: "succeeded",
    profile_version: fixture.profile_version,
    raw_sha256: sha256(primaryBytes),
    work_units_consumed: 0,
  };
  if (includeJcs) result.jcs_sha256 = sha256(canonicalize(parsed));
  return result;
}

function evaluateCase(context: Context, fixture: JsonObject) {
  if (!object(fixture.input) || !object(fixture.action)) throw new ConsumerError("fixture.invalid_case", fixture.case_id);
  const primaryPath = lockedPath(context, fixture.input.primary);
  const primaryBytes = readFileSync(primaryPath);
  let parsed: unknown;
  let parseError: StrictJsonError | undefined;
  try { parsed = strictParse(primaryBytes); } catch (error) { if (error instanceof StrictJsonError) parseError = error; else throw error; }
  const kind = fixture.action.kind;
  const includeJcs = !["parse-negative", "remove", "tamper", "append-lock-entry"].includes(kind) && !parseError;
  const result = outputBase(context, fixture, primaryBytes, parsed, includeJcs);

  if (kind === "parse-negative") {
    if (!parseError) throw new ConsumerError("fixture.invalid_case", "negative input parsed");
    result.object_result = "not_evaluated"; result.operation_outcome = "indeterminate";
    result.issues = [issue("conformance.fixture_invalid", parseError.pointer)];
  } else if (parseError) {
    throw new ConsumerError("conformance.fixture_invalid", parseError.code);
  } else if (kind === "transport" || kind === "verify-profile") {
    // Loading the context and strict primary bytes performs these actions.
  } else if (kind === "replace") {
    const changed = clone(parsed);
    pointerReplace(changed, fixture.action.pointer, fixture.action.value);
    const ordinals = Object.values((changed as JsonObject).schema_profile.keyword_ordinals);
    if (new Set(ordinals).size !== ordinals.length) {
      result.object_result = "invalid";
      result.issues = [issue("profile.duplicate_keyword_ordinal", "/schema_profile/keyword_ordinals")];
    }
  } else if (kind === "remove") {
    if (fixture.action.path !== fixture.input.primary) throw new ConsumerError("fixture.invalid_action", "remove target differs from primary");
    lockedPath(context, fixture.action.path);
    const overlay = new Set(context.lockedPaths);
    if (!overlay.delete(fixture.action.path)) throw new ConsumerError("fixture.invalid_action", "remove target absent");
    const profilePath = "profile/1.0.0/profile.json";
    if (overlay.has(profilePath)) throw new ConsumerError("profile.missing_required_artifact", String(fixture.action.path));
    delete result.jcs_sha256;
    result.object_result = "not_evaluated"; result.operation_outcome = "indeterminate";
    result.issues = [issue("profile.missing_file", "/profile")];
  } else if (kind === "tamper") {
    if (fixture.action.path !== fixture.input.primary) throw new ConsumerError("fixture.invalid_action", "tamper target differs from primary");
    const targetPath = lockedPath(context, fixture.action.path);
    const target = clone(readStrict(targetPath)) as JsonObject;
    const location = fixture.action.pointer === "/diagnostics" ? target.diagnostics : undefined;
    if (!Array.isArray(location) || fixture.action.operation !== "reverse-array") throw new ConsumerError("fixture.invalid_action", kind);
    location.reverse();
    const locked = context.lock.entries.find((entry: JsonObject) => entry.path === fixture.action.path);
    if (!locked || sha256(canonicalize(target)) !== locked.sha256) {
      result.object_result = "not_evaluated"; result.operation_outcome = "indeterminate";
      result.issues = [issue("conformance.digest_mismatch", "/entries")];
    }
  } else if (kind === "append-lock-entry") {
    if (fixture.action.path !== fixture.input.primary || fixture.action.entry?.path !== fixture.input.primary) {
      throw new ConsumerError("fixture.invalid_action", "self-inclusion paths differ");
    }
    const changed = clone(parsed) as JsonObject;
    if (!object(changed) || !Array.isArray(changed.entries)) throw new ConsumerError("lock.invalid_manifest", "candidate lock");
    changed.entries.push(fixture.action.entry);
    assertMachineSchema(changed, context.schemas.get("lock.schema.json"), context.registry);
    if (changed.entries.some((entry: JsonObject) => entry.path === fixture.input.primary)) {
      result.object_result = "invalid";
      result.issues = [issue("lock.self_inclusion", "/entries")];
    }
  } else if (kind === "verify-reference-graph") {
    let mismatch = false;
    const vertices = new Map<string, JsonObject>();
    for (const resource of fixture.resources) {
      const value = readStrict(lockedPath(context, resource.path));
      const actual = sha256(canonicalize(value));
      if (actual !== resource.claimed_sha256) mismatch = true;
      vertices.set(resource.uri, resource);
    }
    if (mismatch) {
      result.object_result = "not_evaluated"; result.operation_outcome = "indeterminate";
      result.issues = [issue("conformance.digest_mismatch", "/resources")];
    } else {
      const visiting = new Set<string>(); const visited = new Set<string>();
      const visit = (uri: string) => { if (visiting.has(uri)) return false; if (visited.has(uri)) return true; visiting.add(uri); const vertex = vertices.get(uri); if (!vertex || !vertex.refs.every(visit)) return false; visiting.delete(uri); visited.add(uri); return true; };
      if (![...vertices.keys()].every(visit)) { result.object_result = "invalid"; result.issues = [issue("conformance.fixture_invalid", "/resources")]; }
    }
  } else if (kind === "schema-admission") {
    if (Array.isArray(fixture.assertions?.declaration_vectors)) {
      for (const vector of fixture.assertions.declaration_vectors) {
        let accepted = true;
        try { validateRegex(vector.pattern, context.profile); } catch (error) {
          if (error instanceof ConsumerError && error.code === "fixture.invalid_schema") accepted = false;
          else throw error;
        }
        const declaredAccepted = vector.result === "accept";
        if (accepted !== declaredAccepted) throw new ConsumerError("fixture.regex_declaration_mismatch", vector.pattern);
      }
    }
    strictSchemaWalk(parsed, context.profile);
    if (!localCycleIsProductive(parsed as JsonObject)) {
      result.object_result = "invalid";
      result.issues = [issue("conformance.fixture_invalid", "/resources")];
    } else if (Array.isArray(fixture.assertions?.work_unit_trace)) {
      result.work_units_consumed = admissionUnits(parsed, context.profile);
    }
  } else if (kind === "semantic-validation") {
    strictSchemaWalk(parsed, context.profile);
    const instance = readStrict(lockedPath(context, fixture.input.instance));
    const evaluation = semanticEvaluation(parsed, instance);
    result.object_result = evaluation.valid ? "valid" : "invalid";
    result.work_units_consumed = evaluation.units;
  } else if (kind === "work-unit-boundary") {
    const { limit, preconsumed, next_action_units: next, phase } = fixture.action;
    if (preconsumed + next > limit) {
      result.object_result = "not_evaluated"; result.operation_outcome = "resource_exhausted";
      result.work_units_consumed = preconsumed;
      const code = phase === "admission" ? "type_definition.resource_exhausted" : "cognitive_node.resource_exhausted";
      result.issues = [issue(code, "")];
    } else {
      result.work_units_consumed = preconsumed + next;
    }
  } else {
    throw new ConsumerError("fixture.invalid_action", String(kind));
  }
  return result;
}

export function runConformance(profileRoot: string) {
  const context = loadContext(profileRoot);
  const manifest = readStrict(safePath(context.contractRoot, "profile/1.0.0/fixtures/manifest.json")) as JsonObject;
  assertMachineSchema(manifest, context.schemas.get("fixture-manifest.schema.json"), context.registry);
  const results: JsonObject[] = [];
  for (const entry of manifest.cases) {
    const relativeCase = `profile/1.0.0/fixtures/${entry.path}`;
    const fixture = readStrict(lockedPath(context, relativeCase)) as JsonObject;
    // Check path-bearing machine inputs before schema diagnostics so traversal
    // attempts are always identified as path-closure failures.
    if (object(fixture.input)) {
      for (const value of [fixture.input.primary, fixture.input.schema, fixture.input.instance, ...(Array.isArray(fixture.input.bundle) ? fixture.input.bundle : [])]) {
        if (typeof value === "string") lockedPath(context, value);
      }
    }
    if (object(fixture.action) && typeof fixture.action.path === "string") lockedPath(context, fixture.action.path);
    assertMachineSchema(fixture, context.schemas.get("fixture-case.schema.json"), context.registry);
    if (fixture.case_id !== entry.case_id) throw new ConsumerError("fixture.id_path_mismatch", entry.path);
    const result = evaluateCase(context, fixture);
    const { case_id: _caseId, ...projection } = result;
    assertMachineSchema(projection, context.schemas.get("expected-result.schema.json"), context.registry);
    results.push(result);
  }
  return results.sort((left, right) => Buffer.compare(Buffer.from(left.case_id), Buffer.from(right.case_id)));
}
