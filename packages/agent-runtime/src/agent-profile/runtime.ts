import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { canonicalize, strictParse } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";

const SAFE = 9007199254740991, MAX = 1048576, MAX_STRING = 262144, MAX_ARRAY = 10000, MAX_DEPTH = 64, MAX_MEMBERS = 100000;
const REQUIRED = ["contract_version", "id", "revision", "display_name", "persona", "goals", "working_style", "declared_capabilities", "collaboration_preferences", "provenance_refs"];
const FORBIDDEN = new Set(["runtime_state", "memory", "private_memory", "model", "model_binding", "permission", "permissions", "team", "project"]);
export class ContractLoadError extends Error {}
const pointer = (value: string) => value.replaceAll("~", "~0").replaceAll("/", "~1");
const issue = (code: string, path: string) => ({ code, path, severity: code === "agent_profile.compatible_read" ? "warning" : "error" });
const result = (mode: string, object_result: string, operation_outcome: string, item?: any) => ({ interface: "agent_profile", mode, object_result, operation_outcome, issues: item ? [item] : [] });
const invalid = (mode: string, code: string, path: string) => result(mode, "invalid", "succeeded", issue(code, path));
const unknown = (code: string, path: string) => result("reference", "not_evaluated", "indeterminate", issue(code, path));
const object = (value: any) => value !== null && typeof value === "object" && !Array.isArray(value);
const semver = (value: any): number[] | undefined => {
  const match = typeof value === "string" && /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(value);
  if (!match || match.slice(1).some((part) => part.length > 18)) return undefined;
  return match.slice(1).map(Number);
};
const versionGreater = (value: number[], target: number[]) => value.some((part, index) => part !== target[index] && part > target[index]);
const stringSet = (value: any, required: boolean): boolean | undefined => {
  if (!Array.isArray(value) || (required && !value.length)) return undefined;
  if (value.some((item) => typeof item !== "string" || !item.length)) return undefined;
  const data = value.map((item) => Buffer.from(item));
  return data.every((item, index) => index === 0 || Buffer.compare(data[index - 1], item) < 0);
};
const scalarString = (value: string) => {
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!Number.isInteger(next) || next < 0xdc00 || next > 0xdfff) return false;
      index++;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
};
const withinLimits = (value: any): boolean => {
  const stack: Array<[any, number]> = [[value, 1]], seen = new Set<any>(); let count = 0;
  while (stack.length) {
    const [current, depth] = stack.pop()!;
    if (depth > MAX_DEPTH) return false;
    if (typeof current === "string") { if (!scalarString(current) || Buffer.byteLength(current) > MAX_STRING) return false; }
    else if (Array.isArray(current)) { if (seen.has(current) || current.length > MAX_ARRAY) return false; seen.add(current); count += current.length; if (count > MAX_MEMBERS) return false; for (const child of current) stack.push([child, depth + 1]); }
    else if (object(current)) { if (seen.has(current)) return false; seen.add(current); const entries = Object.entries(current); count += entries.length; if (count > MAX_MEMBERS) return false; for (const [key, child] of entries) stack.push([key, depth], [child, depth + 1]); }
    else if (current !== null && typeof current !== "boolean" && typeof current !== "number") return false;
  }
  try { return Buffer.byteLength(canonicalize(value)) <= MAX; } catch { return false; }
};
const scalarJson = (value: any): boolean => {
  if (typeof value === "string") return scalarString(value);
  if (Array.isArray(value)) return value.every(scalarJson);
  if (object(value)) return Object.entries(value).every(([key, child]) => scalarString(key) && scalarJson(child));
  return true;
};const rootPath = (source: URL | string) => realpathSync(typeof source === "string" ? source : fileURLToPath(source)).replaceAll("\\", "/");
const safe = (root: string, relative: string) => {
  if (!relative || relative.includes("\\") || !relative.endsWith(".json") || relative.startsWith("/") || relative.split("/").some((item) => !item || item === "." || item === "..")) throw new ContractLoadError("unsafe artifact");
  const path = realpathSync(`${root}/${relative}`).replaceAll("\\", "/"); if (!(path === root || path.startsWith(`${root}/`))) throw new ContractLoadError("artifact escape"); return path;
};
const walkJson = (root: string, path = ""): string[] => {
  const current = path ? `${root}/${path}` : root; const rows: string[] = [];
  for (const entry of readdirSync(current, { withFileTypes: true })) {
    const relative = path ? `${path}/${entry.name}` : entry.name;
    if (entry.isDirectory()) rows.push(...walkJson(root, relative)); else if (entry.isFile() && relative.endsWith(".json")) rows.push(relative);
  }
  return rows.sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
};
const refsSafe = (value: any): boolean => {
  if (Array.isArray(value)) return value.every(refsSafe);
  if (!object(value)) return true;
  return Object.entries(value).every(([key, child]) => key !== "$ref" || (typeof child === "string" && (child === "#" || child.startsWith("#/") || ((!child.includes(":")) && !child.includes("\\") && (child.endsWith(".json") || child.includes(".json#"))))) && refsSafe(child));
};
const pointerExists = (document: any, fragment: string): boolean => {
  if (fragment === "") return true;
  if (!fragment.startsWith("/")) return false;
  let current = document;
  for (const token of fragment.slice(1).split("/")) {
    let decoded = "";
    for (let index = 0; index < token.length; index++) {
      if (token[index] !== "~") { decoded += token[index]; continue; }
      if (++index >= token.length || !["0", "1"].includes(token[index])) return false;
      decoded += token[index] === "0" ? "~" : "/";
    }
    if (Array.isArray(current) && /^(0|[1-9][0-9]*)$/.test(decoded) && Number(decoded) < current.length) current = current[Number(decoded)];
    else if (object(current) && decoded in current) current = current[decoded];
    else return false;
  }
  return true;
};
const validateRefs = (value: any, documents: Record<string, any>, source: string): void => {
  if (Array.isArray(value)) { value.forEach((child) => validateRefs(child, documents, source)); return; }
  if (!object(value)) return;
  if ("$ref" in value) {
    const reference = value.$ref;
    if (typeof reference !== "string") throw new ContractLoadError("invalid schema reference");
    let target: string, fragment: string;
    if (reference.startsWith("#")) { target = source; fragment = reference.slice(1); }
    else {
      const marker = reference.indexOf("#"), path = marker < 0 ? reference : reference.slice(0, marker); fragment = marker < 0 ? "" : reference.slice(marker + 1);
      if (!path || path.includes(":") || path.includes("\\") || path.startsWith("/") || path.split("/").some((part) => !part || part === "." || part === "..")) throw new ContractLoadError("invalid schema reference");
      const parent = source.split("/").slice(0, -1); target = [...parent, ...path.split("/")].join("/");
    }
    if (!(target in documents) || !pointerExists(documents[target], fragment)) throw new ContractLoadError("invalid schema reference");
  }
  Object.values(value).forEach((child) => validateRefs(child, documents, source));
};export function loadLockedContract(contractRoot: URL | string) {
  const root = rootPath(contractRoot);
  if (!root.endsWith("/agent-profile/1.0.0") || lstatSync(root).isSymbolicLink()) throw new ContractLoadError("unsafe contract root");
  const lock = strictParse(readFileSync(safe(root, "lock.json"))) as any;
  if (!object(lock) || lock.contract_version !== "1.0.0" || lock.self_digest !== "excluded" || !Array.isArray(lock.entries)) throw new ContractLoadError("invalid lock");
  const documents: Record<string, any> = {}, paths: string[] = [];
  for (const entry of lock.entries) {
    if (!object(entry) || Object.keys(entry).length !== 3 || entry.digest_kind !== "jcs_sha256" || typeof entry.path !== "string" || !/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path === "lock.json" || paths.includes(entry.path)) throw new ContractLoadError("invalid lock entry");
    const target = safe(root, entry.path); if (lstatSync(target).isSymbolicLink()) throw new ContractLoadError("symlink artifact");
    const value = strictParse(readFileSync(target)); const digest = createHash("sha256").update(canonicalize(value)).digest("hex");
    if (digest !== entry.sha256 || !refsSafe(value)) throw new ContractLoadError("unsafe locked contract");
    paths.push(entry.path); documents[entry.path] = value;
  }
  const actual = walkJson(root).filter((path) => path !== "lock.json");
  if (JSON.stringify(paths) !== JSON.stringify(actual)) throw new ContractLoadError("lock closure mismatch");
  for (const [source, document] of Object.entries(documents)) validateRefs(document, documents, source);
  const manifest = documents["contract.json"];
  if (!object(manifest) || manifest.contract_family !== "agent-profile" || manifest.contract_version !== "1.0.0" || manifest.side_effects !== "forbidden") throw new ContractLoadError("invalid manifest");
  return { root, documents, manifest };
}
const defaultRoot = () => new URL("../../contracts/agent-profile/1.0.0/", import.meta.url);
const loaded = (root?: URL | string) => loadLockedContract(root ?? defaultRoot());
export function validateProfile(profile: any, contractRoot?: URL | string): any {
  loaded(contractRoot);
  if (!object(profile) || !scalarJson(profile) || !withinLimits(profile)) return invalid("profile", "agent_profile.invalid_json", "");
  const missing = REQUIRED.find((field) => !(field in profile)); if (missing) return invalid("profile", "agent_profile.missing_field", `/${missing}`);
  const extra = Object.keys(profile).filter((field) => !REQUIRED.includes(field)).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  if (extra.length) return invalid("profile", FORBIDDEN.has(extra[0]) ? "agent_profile.forbidden_runtime_field" : "agent_profile.invalid_profile_field", `/${pointer(extra[0])}`);
  const version = semver(profile.contract_version); if (!version || version[0] !== 1) return invalid("profile", "agent_profile.unsupported_contract_version", "/contract_version");
  if (typeof profile.id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(profile.id)) return invalid("profile", "agent_profile.invalid_id", "/id");
  if (!Number.isSafeInteger(profile.revision) || profile.revision < 1) return invalid("profile", "agent_profile.invalid_revision", "/revision");
  for (const field of ["goals", "declared_capabilities", "provenance_refs"]) { const set = stringSet(profile[field], true); if (set === undefined) return invalid("profile", "agent_profile.invalid_profile_field", `/${field}`); if (!set) return invalid("profile", "agent_profile.noncanonical_set", `/${field}`); }
  const personaSet = object(profile.persona) && "principles" in profile.persona ? stringSet(profile.persona.principles, false) : undefined; if (personaSet === false) return invalid("profile", "agent_profile.noncanonical_set", "/persona/principles");
  const nonempty = (value: any) => typeof value === "string" && value.length > 0;
  if (!nonempty(profile.display_name)) return invalid("profile", "agent_profile.invalid_profile_field", "/display_name");
  if (!object(profile.persona) || !nonempty(profile.persona.summary) || !Array.isArray(profile.persona.principles) || !nonempty(profile.persona.communication_style) || Object.keys(profile.persona).some((key) => !["summary", "principles", "communication_style"].includes(key))) return invalid("profile", "agent_profile.invalid_profile_field", "/persona");
  if (!object(profile.working_style) || !["planning_preference", "reasoning_preference", "verification_preference"].every((key) => nonempty(profile.working_style[key])) || Object.keys(profile.working_style).some((key) => !["planning_preference", "reasoning_preference", "verification_preference"].includes(key))) return invalid("profile", "agent_profile.invalid_profile_field", "/working_style");
  if (!object(profile.collaboration_preferences) || !["interaction_preference", "feedback_preference"].every((key) => nonempty(profile.collaboration_preferences[key])) || Object.keys(profile.collaboration_preferences).some((key) => !["interaction_preference", "feedback_preference"].includes(key))) return invalid("profile", "agent_profile.invalid_profile_field", "/collaboration_preferences");
  if (profile.declared_capabilities.some((value: any) => typeof value !== "string" || !/^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*$/.test(value))) return invalid("profile", "agent_profile.invalid_profile_field", "/declared_capabilities");
  return versionGreater(version, [1, 0, 0]) ? result("profile", "compatible_read", "succeeded", issue("agent_profile.compatible_read", "/contract_version")) : result("profile", "valid", "succeeded");
}
export function parseAndValidateTransport(raw: Uint8Array, contractRoot?: URL | string) {
  loaded(contractRoot); if (!(raw instanceof Uint8Array) || raw.length > MAX) return invalid("transport", "agent_profile.invalid_json", "");
  try { const value = strictParse(raw); return { ...validateProfile(value, contractRoot), mode: "transport" }; } catch { return invalid("transport", "agent_profile.invalid_json", ""); }
}
export function validateReferences(profile: any, snapshot: any, contractRoot?: URL | string): any {
  const current = loaded(contractRoot), profileResult = validateProfile(profile, current.root);
  if (profileResult.object_result === "invalid") return { ...profileResult, mode: "reference" };
  if (profileResult.object_result === "compatible_read") return unknown("agent_profile.reference_snapshot_incomplete", "/contract_version");
  if (!object(snapshot) || !scalarJson(snapshot) || !withinLimits(snapshot)) return unknown("agent_profile.reference_snapshot_incomplete", "");
  const extra = Object.keys(snapshot).filter((key) => !["contract_version", "provenance"].includes(key)); if (extra.length || JSON.stringify(semver(snapshot.contract_version)) !== JSON.stringify([1,0,0]) || !Array.isArray(snapshot.provenance) || !snapshot.provenance.length) return unknown("agent_profile.reference_snapshot_incomplete", extra.length ? `/${pointer(extra[0])}` : "/contract_version");
  const entries = new Map<string, [number, string]>(); let previous: Buffer | undefined;
  for (let index = 0; index < snapshot.provenance.length; index++) { const entry = snapshot.provenance[index]; if (!object(entry) || Object.keys(entry).length !== 2 || typeof entry.ref !== "string" || !entry.ref || !["available", "invalid", "opaque", "compatible_read"].includes(entry.object_result)) return unknown("agent_profile.reference_snapshot_incomplete", `/provenance/${index}`); const key = Buffer.from(entry.ref); if (previous && Buffer.compare(previous,key) >= 0) return unknown("agent_profile.reference_snapshot_incomplete", `/provenance/${index}/ref`); previous = key; entries.set(entry.ref, [index, entry.object_result]); }
  for (let index = 0; index < profile.provenance_refs.length; index++) { const row = entries.get(profile.provenance_refs[index]); if (!row || row[1] === "invalid") return invalid("reference", "agent_profile.dangling_provenance_reference", `/provenance_refs/${index}`); if (["opaque", "compatible_read"].includes(row[1])) return unknown("agent_profile.opaque_provenance_reference", `/provenance_refs/${index}`); }
  const refs = new Set(profile.provenance_refs); for (const [key, [index]] of entries) if (!refs.has(key)) return invalid("reference", "agent_profile.dangling_provenance_reference", `/provenance/${index}/ref`);
  return result("reference", "valid", "succeeded");
}
export function validateRevisionTransition(previous: any, candidate: any, contractRoot?: URL | string): any {
  const current = loaded(contractRoot); for (const value of [previous, candidate]) { const validation = validateProfile(value, current.root); if (validation.object_result === "invalid") return { ...validation, mode: "revision_transition" }; if (validation.object_result === "compatible_read") return invalid("revision_transition", "agent_profile.unsupported_contract_version", "/contract_version"); }
  if (previous.id !== candidate.id) return invalid("revision_transition", "agent_profile.revision_identity_mismatch", "/id"); if (candidate.revision <= previous.revision) return invalid("revision_transition", "agent_profile.revision_not_increased", "/revision");
  const left = structuredClone(previous), right = structuredClone(candidate); delete left.revision; delete right.revision; return canonicalize(left) === canonicalize(right) ? invalid("revision_transition", "agent_profile.revision_without_change", "/revision") : result("revision_transition", "valid", "succeeded");
}
export function profileSummary(profile: any, contractRoot?: URL | string) { const validation = validateProfile(profile, contractRoot); return validation.object_result === "valid" || validation.object_result === "compatible_read" ? { validation, summary: { id: profile.id, revision: profile.revision, display_name: profile.display_name, goals: [...profile.goals], declared_capabilities: [...profile.declared_capabilities] } } : { validation, summary: null }; }
const caseResult = (item: any, root: string): any => { const data = item?.input; if (!object(data)) return invalid("profile", "agent_profile.invalid_json", "/input"); if (data.mode === "raw") { try { return parseAndValidateTransport(Buffer.from(data.raw_hex, "hex"), root); } catch { return invalid("transport", "agent_profile.invalid_json", "/input/raw_hex"); } } if (data.mode === "profile") return validateProfile(data.profile, root); if (data.mode === "reference") return validateReferences(data.profile, data.snapshot, root); if (data.mode === "revision_transition") return validateRevisionTransition(data.previous, data.candidate, root); return invalid("profile", "agent_profile.invalid_json", "/input/mode"); };
export function executeFixtureSuite(contractRoot: URL | string) { const current = loaded(contractRoot), suite = current.documents["fixtures/cases.json"]; return suite.cases.map((item: any) => ({ case_id: item.case_id, actual: caseResult(item, current.root), expected: structuredClone(item.expected) })); }
