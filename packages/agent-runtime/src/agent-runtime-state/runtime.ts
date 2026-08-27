import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { canonicalize, strictParse } from "../../../cognitive-ir/src/conformance-ts/strict-json.ts";

const SAFE = 9007199254740991, MAX = 1048576, MAX_STRING = 262144, MAX_ARRAY = 10000, MAX_DEPTH = 64, MAX_MEMBERS = 100000;
const UUIDV7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const STATE_FIELDS = ["contract_version", "state_id", "state_revision", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "status", "activation_epoch", "last_transition_ref"];
const INTENT_FIELDS = ["contract_version", "request_id", "operation", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref", "expected_state", "expected_state_ref", "expected_profile_ref", "target_profile_ref", "reason_ref"];
const RECORD_FIELDS = ["contract_version", "record_id", "request_id", "authority_scope_ref", "runtime_context_ref", "agent_profile_id", "operation", "outcome", "before_state", "after_state", "provenance_ref"];
const OPERATIONS = new Set(["create_state", "summon", "close", "archive", "restore", "rebind_profile"]);
const STATUSES = new Set(["active", "dormant", "archived"]);
const FORBIDDEN = new Set(["persona", "goals", "role", "capability", "capabilities", "memory", "private_memory", "model", "model_binding", "permission", "permissions", "team", "project", "task", "process", "output", "ui_state"]);

export class ContractLoadError extends Error {}
const object = (value: any): value is Record<string, any> => value !== null && typeof value === "object" && !Array.isArray(value);
const pointer = (value: string) => value.replaceAll("~", "~0").replaceAll("/", "~1");
const issue = (code: string, path: string) => ({ code, path, severity: code === "agent_runtime_state.compatible_read" ? "warning" : "error" });
const result = (mode: string, object_result: string, operation_outcome: string, item?: any, extra: Record<string, any> = {}) => ({ interface: "agent_runtime_state", mode, object_result, operation_outcome, issues: item ? [item] : [], ...extra });
const invalid = (mode: string, code: string, path: string, operation_outcome = "succeeded") => result(mode, "invalid", operation_outcome, issue(code, path));
const semver = (value: any): number[] | undefined => {
  const match = typeof value === "string" && /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(value);
  if (!match || match.slice(1).some((part) => part.length > 18)) return undefined;
  return match.slice(1).map(Number);
};
const version = (value: any) => { const parsed = semver(value); return !parsed || parsed[0] !== 1 ? "invalid" : parsed[1] === 0 && parsed[2] === 0 ? "exact" : "compatible"; };
const integer = (value: any, minimum = 0) => Number.isSafeInteger(value) && value >= minimum;
const scalar = (value: any): boolean => {
  if (typeof value === "string") {
    for (let index = 0; index < value.length; index++) {
      const code = value.charCodeAt(index);
      if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(++index); if (next < 0xdc00 || next > 0xdfff) return false; }
      else if (code >= 0xdc00 && code <= 0xdfff) return false;
    }
    return true;
  }
  if (Array.isArray(value)) return value.every(scalar);
  if (object(value)) return Object.entries(value).every(([key, child]) => scalar(key) && scalar(child));
  return value === null || typeof value === "boolean" || typeof value === "number";
};
const limits = (value: any) => {
  const stack: Array<[any, number]> = [[value, 1]], seen = new Set<any>(); let count = 0;
  while (stack.length) {
    const [current, depth] = stack.pop()!;
    if (depth > MAX_DEPTH) return false;
    if (typeof current === "string") { if (Buffer.byteLength(current) > MAX_STRING) return false; }
    else if (Array.isArray(current)) { if (seen.has(current) || current.length > MAX_ARRAY) return false; seen.add(current); count += current.length; if (count > MAX_MEMBERS) return false; current.forEach((item) => stack.push([item, depth + 1])); }
    else if (object(current)) { if (seen.has(current)) return false; seen.add(current); const entries = Object.entries(current); count += entries.length; if (count > MAX_MEMBERS) return false; entries.forEach(([key, item]) => { stack.push([key, depth], [item, depth + 1]); }); }
    else if (current !== null && typeof current !== "boolean" && typeof current !== "number") return false;
  }
  try { return Buffer.byteLength(canonicalize(value)) <= MAX; } catch { return false; }
};
const rootPath = (source: URL | string) => realpathSync(typeof source === "string" ? source : fileURLToPath(source)).replaceAll("\\", "/");
const safe = (root: string, relative: string) => {
  if (!relative || relative.includes("\\") || !relative.endsWith(".json") || relative.startsWith("/") || relative.split("/").some((part) => !part || part === "." || part === "..")) throw new ContractLoadError("unsafe artifact");
  const path = realpathSync(`${root}/${relative}`).replaceAll("\\", "/"); if (!path.startsWith(`${root}/`)) throw new ContractLoadError("artifact escape"); return path;
};
const walkJson = (root: string, relative = ""): string[] => {
  const current = relative ? `${root}/${relative}` : root; const paths: string[] = [];
  for (const entry of readdirSync(current, { withFileTypes: true })) { const child = relative ? `${relative}/${entry.name}` : entry.name; if (entry.isDirectory()) paths.push(...walkJson(root, child)); else if (entry.isFile() && child.endsWith(".json")) paths.push(child); }
  return paths.sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
};
export function loadLockedContract(contractRoot: URL | string) {
  const root = rootPath(contractRoot);
  if (!root.endsWith("/agent-runtime-state/1.0.0") || lstatSync(root).isSymbolicLink()) throw new ContractLoadError("unsafe contract root");
  const lock = strictParse(readFileSync(safe(root, "lock.json"))) as any;
  if (!object(lock) || lock.contract_version !== "1.0.0" || lock.self_digest !== "excluded" || !Array.isArray(lock.entries)) throw new ContractLoadError("invalid lock");
  const documents: Record<string, any> = {}, paths: string[] = [];
  for (const entry of lock.entries) {
    if (!object(entry) || Object.keys(entry).length !== 3 || entry.digest_kind !== "jcs_sha256" || typeof entry.path !== "string" || !/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path === "lock.json" || paths.includes(entry.path)) throw new ContractLoadError("invalid lock entry");
    const target = safe(root, entry.path); if (lstatSync(target).isSymbolicLink()) throw new ContractLoadError("symlink artifact");
    const value = strictParse(readFileSync(target)); if (createHash("sha256").update(canonicalize(value)).digest("hex") !== entry.sha256) throw new ContractLoadError("lock mismatch");
    paths.push(entry.path); documents[entry.path] = value;
  }
  const actual = walkJson(root).filter((path) => path !== "lock.json"); if (JSON.stringify(paths) !== JSON.stringify(actual)) throw new ContractLoadError("lock closure mismatch");
  const manifest = documents["contract.json"];
  if (!object(manifest) || manifest.contract_family !== "agent-runtime-state" || manifest.contract_version !== "1.0.0" || manifest.side_effects !== "forbidden") throw new ContractLoadError("invalid manifest");
  return { root, documents, manifest };
}
const defaultRoot = () => new URL("../../contracts/agent-runtime-state/1.0.0/", import.meta.url);
const loaded = (root?: URL | string) => loadLockedContract(root ?? defaultRoot());
const profileRef = (value: any) => object(value) && Object.keys(value).length === 2 && typeof value.id === "string" && UUIDV7.test(value.id) && integer(value.revision, 1);
const stateRef = (value: any) => object(value) && Object.keys(value).length === 2 && typeof value.state_id === "string" && UUIDV7.test(value.state_id) && integer(value.state_revision, 1);
const opaque = (value: any) => typeof value === "string" && Buffer.byteLength(value) >= 1 && Buffer.byteLength(value) <= 256;

export function validateState(state: any, contractRoot?: URL | string): any {
  loaded(contractRoot);
  if (!object(state) || !scalar(state) || !limits(state)) return invalid("state", "agent_runtime_state.invalid_json", "");
  const missing = STATE_FIELDS.find((field) => !(field in state)); if (missing) return invalid("state", "agent_runtime_state.missing_field", `/${missing}`);
  const extra = Object.keys(state).filter((field) => !STATE_FIELDS.includes(field)).sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  if (extra.length) return invalid("state", FORBIDDEN.has(extra[0]) ? "agent_runtime_state.forbidden_state_field" : "agent_runtime_state.invalid_state_field", `/${pointer(extra[0])}`);
  const stateVersion = version(state.contract_version); if (stateVersion === "invalid") return invalid("state", "agent_runtime_state.unsupported_contract_version", "/contract_version");
  if (typeof state.state_id !== "string" || !UUIDV7.test(state.state_id)) return invalid("state", "agent_runtime_state.invalid_state_id", "/state_id");
  if (!integer(state.state_revision, 1)) return invalid("state", "agent_runtime_state.invalid_state_field", "/state_revision");
  if (!opaque(state.authority_scope_ref)) return invalid("state", "agent_runtime_state.invalid_opaque_ref", "/authority_scope_ref");
  if (!opaque(state.runtime_context_ref)) return invalid("state", "agent_runtime_state.invalid_opaque_ref", "/runtime_context_ref");
  if (!profileRef(state.agent_profile_ref)) return invalid("state", "agent_runtime_state.invalid_profile_ref", "/agent_profile_ref");
  if (!STATUSES.has(state.status)) return invalid("state", "agent_runtime_state.invalid_status", "/status");
  if (!integer(state.activation_epoch)) return invalid("state", "agent_runtime_state.invalid_state_field", "/activation_epoch");
  if (!opaque(state.last_transition_ref)) return invalid("state", "agent_runtime_state.invalid_opaque_ref", "/last_transition_ref");
  return stateVersion === "compatible" ? result("state", "compatible_read", "succeeded", issue("agent_runtime_state.compatible_read", "/contract_version")) : result("state", "valid", "succeeded");
}
export function parseAndValidateTransport(raw: Uint8Array, contractRoot?: URL | string): any {
  loaded(contractRoot); if (!(raw instanceof Uint8Array) || raw.length > MAX) return invalid("transport", "agent_runtime_state.invalid_json", "");
  try { return { ...validateState(strictParse(raw), contractRoot), mode: "transport" }; } catch { return invalid("transport", "agent_runtime_state.invalid_json", ""); }
}
const validateIntent = (intent: any): [any | undefined, string] => {
  if (!object(intent) || !scalar(intent) || !limits(intent)) return [invalid("transition", "agent_runtime_state.invalid_transition_intent", "", "rejected"), ""];
  const missing = ["contract_version", "request_id", "operation", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref"].find((field) => !(field in intent)); const extra = Object.keys(intent).filter((field) => !INTENT_FIELDS.includes(field)).sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  if (missing || extra.length) return [invalid("transition", "agent_runtime_state.invalid_transition_intent", missing ? `/${missing}` : `/${pointer(extra[0])}`, "rejected"), ""];
  if (version(intent.contract_version) !== "exact") return [invalid("transition", "agent_runtime_state.unsupported_contract_version", "/contract_version", "rejected"), ""];
  const operation = intent.operation;
  if (!OPERATIONS.has(operation) || typeof intent.request_id !== "string" || !UUIDV7.test(intent.request_id) || !opaque(intent.authority_scope_ref) || !opaque(intent.runtime_context_ref) || !profileRef(intent.agent_profile_ref)) return [invalid("transition", "agent_runtime_state.invalid_transition_intent", "/operation", "rejected"), ""];
  if (operation === "create_state") {
    if (intent.expected_state !== "absent" || ["expected_state_ref", "expected_profile_ref", "target_profile_ref"].some((field) => field in intent)) return [invalid("transition", "agent_runtime_state.invalid_transition_intent", "/expected_state", "rejected"), ""];
  } else {
    if (!stateRef(intent.expected_state_ref)) return [invalid("transition", "agent_runtime_state.invalid_state_ref", "/expected_state_ref", "rejected"), ""];
    if (!profileRef(intent.expected_profile_ref)) return [invalid("transition", "agent_runtime_state.invalid_profile_ref", "/expected_profile_ref", "rejected"), ""];
    if (operation === "rebind_profile" && !profileRef(intent.target_profile_ref)) return [invalid("transition", "agent_runtime_state.invalid_rebind", "/target_profile_ref", "rejected"), ""];
    if (operation !== "rebind_profile" && "target_profile_ref" in intent) return [invalid("transition", "agent_runtime_state.invalid_transition_intent", "/target_profile_ref", "rejected"), ""];
  }
  return [undefined, operation];
};
const plan = (intent: any, state: any, target_status: string, disposition: string, target_profile_ref?: any) => {
  const change = disposition === "change"; const value: any = { operation: intent.operation, disposition, authority_scope_ref: intent.authority_scope_ref, runtime_context_ref: intent.runtime_context_ref, agent_profile_ref: structuredClone(intent.agent_profile_ref), state_ref: state === null ? null : { state_id: state.state_id, state_revision: state.state_revision }, target_status, state_revision: state === null ? 1 : state.state_revision + (change ? 1 : 0), activation_epoch: state === null ? 0 : state.activation_epoch + (change && target_status === "active" ? 1 : 0) };
  if (target_profile_ref !== undefined) value.target_profile_ref = structuredClone(target_profile_ref); return value;
};
export function planTransition(state: any, intent: any, contractRoot?: URL | string): any {
  loaded(contractRoot); const [intentError, operation] = validateIntent(intent); if (intentError) return intentError;
  if (operation === "create_state") {
    if (state === null || state === undefined) return result("transition", "valid", "succeeded", undefined, { plan: plan(intent, null, "dormant", "change") });
    const validation = validateState(state, contractRoot); if (validation.object_result === "invalid") return { ...validation, mode: "transition", operation_outcome: "rejected" };
    return result("transition", "valid", "conflict", issue("agent_runtime_state.local_state_exists", "/expected_state"));
  }
  const validation = validateState(state, contractRoot);
  if (validation.object_result !== "valid") return validation.object_result === "compatible_read" ? invalid("transition", "agent_runtime_state.unsupported_contract_version", "/contract_version", "rejected") : { ...validation, mode: "transition", operation_outcome: "rejected" };
  for (const field of ["authority_scope_ref", "runtime_context_ref"]) if (state[field] !== intent[field]) return result("transition", "valid", "conflict", issue("agent_runtime_state.local_state_mismatch", `/${field}`));
  if (JSON.stringify(state.agent_profile_ref) !== JSON.stringify(intent.agent_profile_ref) || JSON.stringify(state.agent_profile_ref) !== JSON.stringify(intent.expected_profile_ref)) return result("transition", "valid", "conflict", issue("agent_runtime_state.profile_ref_mismatch", "/expected_profile_ref"));
  if (state.state_id !== intent.expected_state_ref.state_id || state.state_revision !== intent.expected_state_ref.state_revision) return result("transition", "valid", "conflict", issue("agent_runtime_state.stale_state_ref", "/expected_state_ref"));
  if (operation === "rebind_profile") {
    const target = intent.target_profile_ref; if (target.id !== state.agent_profile_ref.id) return invalid("transition", "agent_runtime_state.invalid_rebind", "/target_profile_ref", "rejected");
    if (state.status !== "dormant") return result("transition", "valid", "rejected", issue("agent_runtime_state.forbidden_transition", "/operation"));
    return result("transition", "valid", "succeeded", undefined, { plan: plan(intent, state, "dormant", JSON.stringify(target) === JSON.stringify(state.agent_profile_ref) ? "no_change" : "change", target) });
  }
  const table: Record<string, Record<string, [string, string]>> = { summon: { dormant: ["active", "change"], active: ["active", "no_change"] }, close: { active: ["dormant", "change"], dormant: ["dormant", "no_change"] }, archive: { dormant: ["archived", "change"], archived: ["archived", "no_change"] }, restore: { archived: ["dormant", "change"], dormant: ["dormant", "no_change"] } };
  const target = table[operation][state.status]; if (!target) return result("transition", "valid", "rejected", issue("agent_runtime_state.forbidden_transition", "/operation"));
  return result("transition", "valid", "succeeded", undefined, { plan: plan(intent, state, ...target) });
}
export function stateSummary(state: any, contractRoot?: URL | string) {
  const validation = validateState(state, contractRoot); return ["valid", "compatible_read"].includes(validation.object_result) ? { validation, summary: { state_id: state.state_id, state_revision: state.state_revision, status: state.status, activation_epoch: state.activation_epoch } } : { validation, summary: null };
}
export function aggregateVisibleStates(aggregate_input: any, contractRoot?: URL | string): any {
  loaded(contractRoot);
  if (!object(aggregate_input) || !scalar(aggregate_input) || !limits(aggregate_input) || Object.keys(aggregate_input).length !== 2 || !("contract_version" in aggregate_input) || !("visible_states" in aggregate_input) || version(aggregate_input.contract_version) !== "exact" || !Array.isArray(aggregate_input.visible_states)) return invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", "");
  const seen = new Set<string>(), counts: Record<string, number> = { active: 0, dormant: 0, archived: 0 };
  for (let index = 0; index < aggregate_input.visible_states.length; index++) { const state = aggregate_input.visible_states[index], validation = validateState(state, contractRoot); if (validation.object_result !== "valid") return invalid("aggregate", "agent_runtime_state.invalid_aggregate_input", `/visible_states/${index}`); if (seen.has(state.state_id)) return invalid("aggregate", "agent_runtime_state.duplicate_visible_state", `/visible_states/${index}`); seen.add(state.state_id); counts[state.status]++; }
  return result("aggregate", "valid", "succeeded", undefined, { aggregate: { contract_version: "1.0.0", visible_state_count: aggregate_input.visible_states.length, active_count: counts.active, dormant_count: counts.dormant, archived_count: counts.archived } });
}
const recordState = (value: any) => object(value) && Object.keys(value).length === 6 && ["state_id", "state_revision", "status", "authority_scope_ref", "runtime_context_ref", "agent_profile_ref"].every((field) => field in value) && typeof value.state_id === "string" && UUIDV7.test(value.state_id) && integer(value.state_revision, 1) && STATUSES.has(value.status) && opaque(value.authority_scope_ref) && opaque(value.runtime_context_ref) && profileRef(value.agent_profile_ref);
export function validateTransitionRecord(record: any, contractRoot?: URL | string): any {
  loaded(contractRoot);
  if (!object(record) || !scalar(record) || !limits(record) || Object.keys(record).length !== RECORD_FIELDS.length || !RECORD_FIELDS.every((field) => field in record)) return invalid("record", "agent_runtime_state.invalid_transition_record", "");
  if (version(record.contract_version) !== "exact" || !["record_id", "request_id", "agent_profile_id"].every((field) => typeof record[field] === "string" && UUIDV7.test(record[field])) || !OPERATIONS.has(record.operation) || !["applied", "no_change", "conflict", "rejected"].includes(record.outcome) || !opaque(record.authority_scope_ref) || !opaque(record.runtime_context_ref) || !opaque(record.provenance_ref) || !(record.before_state === null || recordState(record.before_state)) || !(record.after_state === null || recordState(record.after_state))) return invalid("record", "agent_runtime_state.invalid_transition_record", "");
  for (const [path, state] of [["/before_state", record.before_state], ["/after_state", record.after_state]] as const) if (state !== null && (state.authority_scope_ref !== record.authority_scope_ref || state.runtime_context_ref !== record.runtime_context_ref || state.agent_profile_ref.id !== record.agent_profile_id)) return invalid("record", "agent_runtime_state.record_local_mismatch", path);
  const before = record.before_state, after = record.after_state;
  if (before !== null && after !== null) { if (before.state_id !== after.state_id) return invalid("record", "agent_runtime_state.record_local_mismatch", "/after_state/state_id"); if (record.operation === "rebind_profile" && before.agent_profile_ref.id !== after.agent_profile_ref.id) return invalid("record", "agent_runtime_state.record_local_mismatch", "/after_state"); if (record.outcome === "applied" && after.state_revision !== before.state_revision + 1) return invalid("record", "agent_runtime_state.record_state_mismatch", "/after_state/state_revision"); }
  return result("record", "valid", "succeeded");
}
const caseResult = (item: any, root: string): any => {
  const data = item?.input; if (!object(data)) return invalid("state", "agent_runtime_state.invalid_json", "/input");
  if (data.mode === "raw") { try { return parseAndValidateTransport(Buffer.from(data.raw_hex, "hex"), root); } catch { return invalid("transport", "agent_runtime_state.invalid_json", "/input/raw_hex"); } }
  if (data.mode === "state") return validateState(data.state, root);
  if (data.mode === "transition") return planTransition(data.state, data.intent, root);
  if (data.mode === "aggregate") return aggregateVisibleStates(data.aggregate_input, root);
  if (data.mode === "record") return validateTransitionRecord(data.record, root);
  return invalid("state", "agent_runtime_state.invalid_json", "/input/mode");
};
export function executeFixtureSuite(contractRoot: URL | string) { const current = loaded(contractRoot), suite = current.documents["fixtures/cases.json"]; return suite.cases.map((item: any) => ({ case_id: item.case_id, actual: caseResult(item, current.root), expected: structuredClone(item.expected) })); }