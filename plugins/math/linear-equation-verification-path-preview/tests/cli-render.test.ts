import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import test from "node:test";

import { renderVerificationPathPreviewHtml } from "../render.ts";
import { createLinearEquationVerificationPathPreview } from "../verification-path-preview.ts";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const artifactRoot = resolve(root, "../../../docs/demos/artifacts/linear-equation-verification-path-preview");
const cli = resolve(root, "cli.ts");
const cases = ["verification", "unmapped", "empty", "invalid"] as const;

function runCli(...args: string[]) {
  return spawnSync(process.execPath, ["--no-warnings", "--experimental-strip-types", cli, ...args], { encoding: "utf8" });
}

test("renders all fixed bridge states as inert, escaped HTML", () => {
  const inputs = [
    { source: { text: "2x + 3 = 11", source_ref: "prov:source:algebra-example-1" }, flow_context: "verification" },
    { source: { text: "2x + 3 = 11", source_ref: "prov:source:algebra-example-1" }, flow_context: "none" },
    { source: { text: "  \t", source_ref: "prov:source:algebra-example-1" }, flow_context: "verification" },
    { source: { text: "x^2 = 4", source_ref: "prov:source:algebra-example-1" }, flow_context: "verification" },
  ] as const;

  for (const input of inputs) {
    const html = renderVerificationPathPreviewHtml(createLinearEquationVerificationPathPreview(input));
    assert.match(html, /preview/);
    assert.match(html, /forbidden/);
    assert.match(html, /not_persisted|未形成 KnowledgeUnit/);
    assert.doesNotMatch(html, /<script/i);
    assert.doesNotMatch(html, /<iframe/i);
    assert.doesNotMatch(html, /\son[a-z]+\s*=/i);
  }
});

test("fixed CLI emits checked-in HTML artifacts byte-for-byte and valid JSON for every state", () => {
  for (const name of cases) {
    const html = runCli("--case", name, "--format", "html");
    assert.equal(html.status, 0, html.stderr);
    assert.equal(html.stderr, "");
    const artifact = resolve(artifactRoot, `${name}.html`);
    assert.ok(existsSync(artifact), artifact);
    assert.equal(html.stdout, readFileSync(artifact, "utf8"));

    const json = runCli("--case", name, "--format", "json");
    assert.equal(json.status, 0, json.stderr);
    assert.equal(json.stderr, "");
    assert.equal(JSON.parse(json.stdout).state, name === "verification" ? "needs_evidence" : name === "invalid" ? "invalid_input" : "empty");
  }
});

test("CLI rejects unknown and prototype-like fixed-case or format values without stdout", () => {
  for (const args of [
    ["--case", "other", "--format", "json"],
    ["--case", "__proto__", "--format", "json"],
    ["--case", "verification", "--format", "other"],
    ["--case", "verification", "--format", "__proto__"],
  ]) {
    const result = runCli(...args);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /^错误：/);
  }
});
test("browser acceptance screenshots are valid 1440 by 1800 PNG files for every fixed state", () => {
  for (const name of cases) {
    const artifact = resolve(artifactRoot, `${name}.png`);
    assert.ok(existsSync(artifact), artifact);
    const png = readFileSync(artifact);
    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), 1440);
    assert.equal(png.readUInt32BE(20), 1800);
  }
});
test("escapes dynamic source, reference, and diagnostic values before rendering", () => {
  const preview = createLinearEquationVerificationPathPreview({
    source: { text: "2x + 3 = 11", source_ref: "prov:source:algebra-example-1" },
    flow_context: "verification",
  });
  const hostile = {
    ...preview,
    source_ref: "<script>alert(1)</script>",
    knowledge_unit_ref: { id: "<img src=x onerror=alert(1)>", revision: 1 },
    diagnostic: "<iframe src=bad>",
  };
  const html = renderVerificationPathPreviewHtml(hostile);
  assert.doesNotMatch(html, /<script>alert/i);
  assert.doesNotMatch(html, /<iframe src=bad/i);
  assert.doesNotMatch(html, /<img src=x onerror=/i);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /&lt;iframe src=bad&gt;/);
});