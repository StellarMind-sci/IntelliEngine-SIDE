import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createKnowledgeEvidencePreview } from "../navigator.ts";
import { renderKnowledgeEvidencePreviewHtml } from "../render.ts";

const cli = fileURLToPath(new URL("../cli.ts", import.meta.url));
function runCli(...args: string[]) { return spawnSync(process.execPath, ["--no-warnings", cli, ...args], { encoding: "utf8" }); }

test("renders static readonly evidence previews for all five states", () => {
  for (const caseId of ["blocked", "needs-evidence", "ready", "empty", "invalid"] as const) {
    const output = runCli("--case", caseId, "--format", "html");
    assert.equal(output.status, 0, output.stderr);
    assert.equal(output.stderr, "");
    assert.match(output.stdout, /<!doctype html>/i);
    assert.match(output.stdout, /mode: preview/);
    assert.match(output.stdout, /side_effects: forbidden/);
    assert.match(output.stdout, /仅验证解释与导航提示，不执行、不写入/);
    assert.doesNotMatch(output.stdout, /<script\b|<iframe\b|<[^>]*\bon[a-z]+\s*=/i);
  }
});

test("renders direct verification navigation only for needs-evidence", () => {
  const evidence = runCli("--case", "needs-evidence", "--format", "html");
  const blocked = runCli("--case", "blocked", "--format", "html");
  const empty = runCli("--case", "empty", "--format", "html");

  assert.match(evidence.stdout, /verification-linear/);
  assert.match(evidence.stdout, /返回 verification 步骤补充缺失工程证据/);
  assert.doesNotMatch(blocked.stdout, /关联 verification 步骤/);
  assert.match(empty.stdout, /没有可安全定位的受影响步骤/);
  assert.doesNotMatch(empty.stdout, /只读导航/);
});

test("escapes dynamic evidence strings and unknown state CSS values", () => {
  const html = renderKnowledgeEvidencePreviewHtml({
    mode: "preview", side_effects: "forbidden", state: "blocked\" onmouseover=alert(1)" as unknown as "blocked",
    focus: { id: "<focus&>", revision: "1</span><img src=x onerror=alert(1)>" as unknown as number },
    navigation: "<img src=x onerror=alert(1)>", verification_steps: ["<step&>"],
    validations: [{ validation_id: "<validation&>", description: "<description&>", evidence_node_refs: [{ id: "<evidence&>", revision: 1 }], missing_evidence_node_refs: [], status: "missing" }],
    mastery_criteria: [{ criterion_id: "<criterion&>", statement: "<statement&>", evidence_node_refs: [{ id: "<evidence&>", revision: 1 }], missing_evidence_node_refs: [], status: "missing" }],
  });

  assert.match(html, /&lt;focus&amp;&gt;@1&lt;\/span&gt;&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /&lt;validation&amp;&gt;/);
  assert.match(html, /class="state state-invalid-input"/);
  assert.doesNotMatch(html, /<img\b|<script\b|<iframe\b|<[^>]*\bonerror\s*=/i);
});

test("CLI has stable stderr and no stdout for invalid options", () => {
  for (const [args, message] of [
    [["--case", "missing", "--format", "json"], "unknown demo case: missing"],
    [["--case", "ready", "--format", "text"], "unknown output format: text"],
    [["--case", "ready"], "expected --case <id> --format <json|html>"],
  ] as const) {
    const output = runCli(...args);
    assert.notEqual(output.status, 0);
    assert.equal(output.stdout, "");
    assert.equal(output.stderr, `${message}\n`);
  }
});

test("invalid input is closed before any evidence rows can be emitted", () => {
  const result = createKnowledgeEvidencePreview({});
  assert.deepEqual(result, {
    mode: "preview", side_effects: "forbidden", state: "invalid_input", focus: null,
    navigation: null, validations: [], mastery_criteria: [], verification_steps: [],
  });
});
