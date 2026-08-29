import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createLinearEquationIntakePreview } from "../intake.ts";
import { renderLinearEquationIntakePreviewHtml } from "../render.ts";

const cli = fileURLToPath(new URL("../cli.ts", import.meta.url));
function runCli(...args: string[]) { return spawnSync(process.execPath, [cli, ...args], { encoding: "utf8" }); }

test("renders static readonly intake previews for ready, empty and invalid cases", () => {
  for (const caseId of ["ready", "negative", "empty", "invalid"] as const) {
    const output = runCli("--case", caseId, "--format", "html");
    assert.equal(output.status, 0, output.stderr);
    assert.equal(output.stderr, "");
    assert.match(output.stdout, /<!doctype html>/i);
    assert.match(output.stdout, /preview/);
    assert.match(output.stdout, /forbidden/);
    assert.match(output.stdout, /候选尚未写入工程/);
    assert.doesNotMatch(output.stdout, /<script\b|<iframe\b|<[^>]*\bon[a-z]+\s*=/i);
  }
});

test("escapes dynamic source, candidate and diagnostic text", () => {
  const result = createLinearEquationIntakePreview({ text: "x = 1", source_ref: "<source&>" });
  const html = renderLinearEquationIntakePreviewHtml({ ...result, diagnostic: "<img src=x onerror=alert(1)>" });
  assert.match(html, /&lt;source&amp;&gt;/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
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
