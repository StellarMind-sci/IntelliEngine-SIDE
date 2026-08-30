import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import test from "node:test";

import { renderKnowledgeProjectMapPreviewHtml } from "../render.ts";
import { createKnowledgeProjectMapPreview } from "../project-map-preview.ts";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const artifactRoot = resolve(root, "../../../docs/demos/artifacts/knowledge-project-map-preview");
const cli = resolve(root, "cli.ts");
const cases = ["normal", "blocked", "empty", "invalid"] as const;

function runCli(...args: string[]) {
  return spawnSync(process.execPath, ["--no-warnings", "--experimental-strip-types", cli, ...args], { encoding: "utf8" });
}

test("renders each fixed project-map state as inert HTML with the graph facts visible", () => {
  for (const name of cases) {
    const html = renderKnowledgeProjectMapPreviewHtml(createKnowledgeProjectMapPreview({ case: name }));
    assert.match(html, /preview/);
    assert.match(html, /forbidden/);
    assert.match(html, /not_persisted/);
    assert.doesNotMatch(html, /<script/i);
    assert.doesNotMatch(html, /<iframe/i);
    assert.doesNotMatch(html, /\son[a-z]+\s*=/i);
  }
  const normal = renderKnowledgeProjectMapPreviewHtml(createKnowledgeProjectMapPreview({ case: "normal" }));
  assert.match(normal, /needs_evidence/);
  assert.match(normal, /CognitiveNode/);
  assert.match(normal, /先修/);
  const blocked = renderKnowledgeProjectMapPreviewHtml(createKnowledgeProjectMapPreview({ case: "blocked" }));
  assert.match(blocked, /未加载的外部先修/);
  const empty = renderKnowledgeProjectMapPreviewHtml(createKnowledgeProjectMapPreview({ case: "empty" }));
  assert.match(empty, /不伪造受影响/);
  const invalid = renderKnowledgeProjectMapPreviewHtml(createKnowledgeProjectMapPreview({ case: "invalid" }));
  assert.match(invalid, /未形成工程图/);
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
    const value = JSON.parse(json.stdout) as { state: string };
    assert.equal(value.state, name === "empty" ? "empty" : name === "invalid" ? "invalid_input" : "valid");
  }
});

test("CLI rejects unknown, prototype-like, path-like, and duplicate arguments without stdout", () => {
  for (const args of [
    ["--case", "other", "--format", "json"],
    ["--case", "__proto__", "--format", "json"],
    ["--case", "../normal", "--format", "json"],
    ["--case", "normal", "--format", "other"],
    ["--case", "normal", "--format", "__proto__"],
    ["--case", "normal", "--case", "blocked", "--format", "json"],
  ]) {
    const result = runCli(...args);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, "错误：仅支持 --case <normal|blocked|empty|invalid> --format <json|html>。\n");
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

test("escapes dynamic graph values before rendering", () => {
  const preview = createKnowledgeProjectMapPreview({ case: "normal" });
  const hostile = {
    ...preview,
    diagnostic: "<script>alert(1)</script>",
    selected_node_ref: { id: "<img src=x onerror=alert(1)>", revision: 1 },
  };
  const html = renderKnowledgeProjectMapPreviewHtml(hostile);
  assert.doesNotMatch(html, /<script>alert/i);
  assert.doesNotMatch(html, /<img src=x onerror=/i);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});