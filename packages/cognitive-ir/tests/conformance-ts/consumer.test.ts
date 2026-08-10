import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { canonicalize, StrictJsonError, strictParse } from "../../src/conformance-ts/strict-json.ts";

const TEST_ROOT = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(TEST_ROOT, "../../../..");
const PROFILE_ROOT = join(REPO_ROOT, "packages/cognitive-ir/contracts/profile/1.0.0");
const CLI = join(REPO_ROOT, "packages/cognitive-ir/src/conformance-ts/cli.ts");
const RESULT_KEYS = [
  "case_id",
  "contract_id",
  "contract_version",
  "issues",
  "mode",
  "object_result",
  "operation_outcome",
  "profile_version",
  "raw_sha256",
  "work_units_consumed",
];

function runCli(profileRoot = PROFILE_ROOT) {
  return spawnSync(process.execPath, [CLI, "--profile-root", profileRoot], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  });
}

function parseLines(stdout: string) {
  return stdout.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

function expectedResults() {
  const fixtureRoot = join(PROFILE_ROOT, "fixtures");
  const manifest = JSON.parse(readFileSync(join(fixtureRoot, "manifest.json"), "utf8"));
  return manifest.cases.map((entry: { path: string }) => {
    const fixture = JSON.parse(readFileSync(join(fixtureRoot, entry.path), "utf8"));
    return { case_id: fixture.case_id, ...fixture.expected };
  }).sort((left: { case_id: string }, right: { case_id: string }) =>
    Buffer.compare(Buffer.from(left.case_id), Buffer.from(right.case_id))
  );
}

function withProfileCopy(callback: (profileRoot: string) => void) {
  const root = mkdtempSync(join(tmpdir(), "intelliengine-ts-consumer-"));
  const profileRoot = join(root, "profile", "1.0.0");
  cpSync(PROFILE_ROOT, profileRoot, { recursive: true });
  try {
    callback(profileRoot);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function writeJson(path: string, value: unknown) {
  writeFileSync(path, `${JSON.stringify(value)}\n`, "utf8");
}

function relockJson(profileRoot: string, relativePath: string) {
  const contractRoot = resolve(profileRoot, "../..");
  const targetPath = join(contractRoot, ...relativePath.split("/"));
  const value = JSON.parse(readFileSync(targetPath, "utf8"));
  const digest = createHash("sha256").update(canonicalize(value)).digest("hex");
  const lockPath = join(profileRoot, "lock.json");
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  const entry = lock.entries.find((item: { path: string }) => item.path === relativePath);
  assert.ok(entry, `missing lock entry for ${relativePath}`);
  entry.sha256 = digest;
  writeJson(lockPath, lock);
}

test("CLI independently executes all 24 locked fixtures as sorted closed NDJSON", () => {
  const result = runCli();
  assert.equal(result.status, 0, result.stderr);
  const actual = parseLines(result.stdout);
  assert.equal(actual.length, 24);
  assert.deepEqual(actual, expectedResults());
  for (const row of actual) {
    const keys = Object.keys(row).filter((key) => key !== "jcs_sha256").sort();
    assert.deepEqual(keys, [...RESULT_KEYS].sort());
  }
});

test("changing locked expected projections cannot change computed results", () => {
  const baseline = runCli();
  assert.equal(baseline.status, 0, baseline.stderr);
  const baselineRows = parseLines(baseline.stdout);
  withProfileCopy((profileRoot) => {
    const casePath = join(profileRoot, "fixtures/profile-baseline-valid/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    fixture.expected.object_result = "not_evaluated";
    fixture.expected.operation_outcome = "indeterminate";
    fixture.expected.work_units_consumed = 987654;
    fixture.expected.issues = [{ code: "tampered.expected", path: "/", severity: "error" }];
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/profile-baseline-valid/case.json");

    const tampered = runCli(profileRoot);
    assert.equal(tampered.status, 0, tampered.stderr);
    const tamperedRows = parseLines(tampered.stdout);
    assert.deepEqual(
      tamperedRows.find((row) => row.case_id === "profile-baseline-valid"),
      baselineRows.find((row) => row.case_id === "profile-baseline-valid"),
    );
  });
});

test("strict parser rejects ambiguous bytes before producing values", () => {
  const invalid = [
    [Buffer.from([0xef, 0xbb, 0xbf, 0x7b, 0x7d]), "json.bom"],
    [Buffer.from('{"a":1,"a":2}'), "json.duplicate_member"],
    [Buffer.from([0x7b, 0x22, 0x61, 0x22, 0x3a, 0x22, 0x80, 0x22, 0x7d]), "json.invalid_utf8"],
    [Buffer.from('{"a":"\\x"}'), "json.invalid_escape"],
    [Buffer.from('{"a":"\\ud800"}'), "json.invalid_unicode_scalar"],
  ] as const;
  for (const [bytes, code] of invalid) {
    assert.throws(() => strictParse(bytes), (error: unknown) =>
      error instanceof StrictJsonError && error.code === code
    );
  }
});

test("JCS uses ECMAScript numbers and unsigned UTF-16 key order", () => {
  assert.equal(canonicalize(strictParse(Buffer.from("1e-6"))), "0.000001");
  assert.equal(canonicalize(strictParse(Buffer.from("1e21"))), "1e+21");
  assert.equal(canonicalize(strictParse(Buffer.from("-0.0"))), "0");
  assert.equal(
    canonicalize(strictParse(Buffer.from('{"\\ue000":1,"😀":2}'))),
    '{"😀":2,"":1}',
  );
});

test("fixture path and mutation corruption fail closed without partial NDJSON", () => {
  withProfileCopy((profileRoot) => {
    const casePath = join(profileRoot, "fixtures/profile-baseline-valid/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    fixture.input.primary = "../../outside.json";
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/profile-baseline-valid/case.json");

    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /unsafe_path/);
  });

  withProfileCopy((profileRoot) => {
    const casePath = join(profileRoot, "fixtures/lock-digest-tamper/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    const primaryPath = join(profileRoot, "profile.json");
    fixture.input.primary = "profile/1.0.0/profile.json";
    fixture.expected.raw_sha256 = createHash("sha256").update(readFileSync(primaryPath)).digest("hex");
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/lock-digest-tamper/case.json");

    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /invalid_action/);
  });

  withProfileCopy((profileRoot) => {
    const candidatePath = join(profileRoot, "fixtures/lock-self-inclusion/input-lock.json");
    const candidate = JSON.parse(readFileSync(candidatePath, "utf8"));
    candidate.self_digest = "included";
    writeJson(candidatePath, candidate);
    relockJson(profileRoot, "profile/1.0.0/fixtures/lock-self-inclusion/input-lock.json");

    const casePath = join(profileRoot, "fixtures/lock-self-inclusion/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    fixture.expected.raw_sha256 = createHash("sha256").update(readFileSync(candidatePath)).digest("hex");
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/lock-self-inclusion/case.json");

    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /schema validation/);
  });
});

test("remove executes against an overlay instead of fabricating a missing profile", () => {
  withProfileCopy((profileRoot) => {
    const casePath = join(profileRoot, "fixtures/profile-missing/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    const target = "profile/1.0.0/diagnostics/conformance.json";
    fixture.input.primary = target;
    fixture.action.path = target;
    fixture.expected.raw_sha256 = createHash("sha256")
      .update(readFileSync(join(resolve(profileRoot, "../.."), ...target.split("/"))))
      .digest("hex");
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/profile-missing/case.json");

    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /integrity|missing_required/);
  });
});

test("regex declaration vectors are executed, not treated as commentary", () => {
  withProfileCopy((profileRoot) => {
    const casePath = join(profileRoot, "fixtures/regex-grammar-boundary/case.json");
    const fixture = JSON.parse(readFileSync(casePath, "utf8"));
    fixture.assertions.declaration_vectors[0].result = "reject";
    writeJson(casePath, fixture);
    relockJson(profileRoot, "profile/1.0.0/fixtures/regex-grammar-boundary/case.json");

    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /declaration/);
  });
});

test("regex grammar accepts recursively nested groups", () => {
  withProfileCopy((profileRoot) => {
    const relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json";
    const schemaPath = join(resolve(profileRoot, "../.."), ...relative.split("/"));
    const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
    schema.pattern = "((ab))";
    writeJson(schemaPath, schema);
    relockJson(profileRoot, relative);
    const result = runCli(profileRoot);
    assert.equal(result.status, 0, result.stderr);
  });
});

test("regex grammar rejects an isolated closing brace", () => {
  withProfileCopy((profileRoot) => {
    const relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json";
    const schemaPath = join(resolve(profileRoot, "../.."), ...relative.split("/"));
    const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
    schema.pattern = "}";
    writeJson(schemaPath, schema);
    relockJson(profileRoot, relative);
    const result = runCli(profileRoot);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /invalid_schema|regex/);
  });
});

test("consumer rejects any drift in the supported production program", () => {
  const mutations = [
    (grammar: any) => { grammar.productions[0].alternatives[0][0].name = "concatenation"; },
    (grammar: any) => { grammar.productions[3].alternatives[0][0].repeat = "one-or-more"; },
    (grammar: any) => { grammar.productions[5].alternatives.splice(1, 1); },
  ];
  for (const mutate of mutations) {
    withProfileCopy((profileRoot) => {
      const relative = "profile/1.0.0/profile.json";
      const profilePath = join(resolve(profileRoot, "../.."), ...relative.split("/"));
      const profile = JSON.parse(readFileSync(profilePath, "utf8"));
      mutate(profile.regex_profile);
      writeJson(profilePath, profile);
      relockJson(profileRoot, relative);
      const result = runCli(profileRoot);
      assert.notEqual(result.status, 0);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /invalid_regex_grammar/);
    });
  }
});

test("regex character ranges use ordered literal scalar endpoints", () => {
  for (const pattern of ["[z-a]", "[a-\\]]"]) {
    withProfileCopy((profileRoot) => {
      const relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json";
      const schemaPath = join(resolve(profileRoot, "../.."), ...relative.split("/"));
      const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
      schema.pattern = pattern;
      writeJson(schemaPath, schema);
      relockJson(profileRoot, relative);
      const result = runCli(profileRoot);
      assert.notEqual(result.status, 0);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /invalid_schema|regex/);
    });
  }
});

test("regex rejects dangerous nested quantification and private escapes directly", () => {
  for (const pattern of ["((a{2})){3}", "\\q"]) {
    withProfileCopy((profileRoot) => {
      const relative = "profile/1.0.0/fixtures/regex-grammar-boundary/schema.json";
      const schemaPath = join(resolve(profileRoot, "../.."), ...relative.split("/"));
      const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
      schema.pattern = pattern;
      writeJson(schemaPath, schema);
      relockJson(profileRoot, relative);
      const result = runCli(profileRoot);
      assert.notEqual(result.status, 0);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /invalid_schema|regex/);
    });
  }
});
