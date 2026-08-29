import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createKnowledgeImpactNavigator } from "../navigator.ts";
import { renderKnowledgeImpactNavigatorHtml } from "../render.ts";

const cases = JSON.parse(readFileSync(new URL("../fixtures/demo-cases.json", import.meta.url), "utf8"));
const cli = fileURLToPath(new URL("../cli.ts", import.meta.url));

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function runCli(...args: string[]) {
  return spawnSync(process.execPath, ["--no-warnings", cli, ...args], { encoding: "utf8" });
}

test("renders each navigator state as a static preview with the correct navigation gate", () => {
  for (const caseId of ["blocked", "needs_evidence", "ready", "empty"] as const) {
    const result = createKnowledgeImpactNavigator(clone(cases[caseId]));
    const html = renderKnowledgeImpactNavigatorHtml(result);

    assert.match(html, /mode: preview/);
    assert.match(html, /side_effects: forbidden/);
    assert.match(html, new RegExp(`state: ${result.state}`));
    assert.match(html, /仅导航提示，不执行、不写入/);
    assert.doesNotMatch(html, /<script\b|<iframe\b|<[^>]*\bon[a-z]+\s*=/i);
    if (caseId === "blocked" || caseId === "needs_evidence") {
      assert.match(html, /只读导航/);
    } else {
      assert.match(html, /没有待处理的工程影响/);
      assert.doesNotMatch(html, /只读导航/);
    }
  }

  const invalid = renderKnowledgeImpactNavigatorHtml(createKnowledgeImpactNavigator({}));
  assert.match(invalid, /state: invalid_input/);
  assert.match(invalid, /预览已封闭，不生成导航/);
  assert.doesNotMatch(invalid, /只读导航/);
});

test("renders blocked prerequisites and analysis operation impacts", () => {
  const html = renderKnowledgeImpactNavigatorHtml(createKnowledgeImpactNavigator(clone(cases.blocked)));

  assert.match(html, /10000000-0000-4000-8000-000000000011@1/);
  assert.match(html, /a-operation/);
  assert.match(html, /z-analysis/);
  assert.match(html, /<div class="state state-blocked">state: blocked<\/div>/);
});

test("renders needs-evidence verification gap with a distinct visual state", () => {
  const html = renderKnowledgeImpactNavigatorHtml(createKnowledgeImpactNavigator(clone(cases.needs_evidence)));

  assert.match(html, /20000000-0000-4000-8000-000000000001@1/);
  assert.match(html, /verification-evidence/);
  assert.match(html, /<div class="state state-needs-evidence">state: needs_evidence<\/div>/);
  assert.doesNotMatch(html, /<div class="state state-blocked">/);
});

test("escapes every dynamic value before static HTML output", () => {
  const html = renderKnowledgeImpactNavigatorHtml({
    mode: "preview",
    side_effects: "forbidden",
    state: "blocked",
    focus: { id: "<focus&>", revision: 1 },
    navigation: "<img src=x onerror=alert(1)>",
    impacted_steps: [{
      step_id: "<step&>",
      reasons: [{
        knowledge_unit_ref: { id: "<reason&>", revision: 2 },
        status: "blocked",
        missing_prerequisite_refs: [{ id: "<pre&>", revision: 3 }],
        missing_evidence_node_refs: [],
      }],
    }],
    reasons: [{
      knowledge_unit_ref: { id: "<reason&>", revision: 2 },
      status: "blocked",
      missing_prerequisite_refs: [{ id: "<pre&>", revision: 3 }],
      missing_evidence_node_refs: [],
    }],
  });

  assert.match(html, /&lt;focus&amp;&gt;@1/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /&lt;step&amp;&gt;/);
  assert.doesNotMatch(html, /<img\b|<script\b|<iframe\b|<[^>]*\bonerror\s*=/i);
});

test("CLI emits JSON and HTML for all five fixed demo states", () => {
  for (const caseId of ["blocked", "needs-evidence", "ready", "empty", "invalid"] as const) {
    const json = runCli("--case", caseId, "--format", "json");
    assert.equal(json.status, 0, json.stderr);
    assert.equal(json.stderr, "");
    const result = JSON.parse(json.stdout);
    assert.equal(result.mode, "preview");
    assert.equal(result.side_effects, "forbidden");

    const html = runCli("--case", caseId, "--format", "html");
    assert.equal(html.status, 0, html.stderr);
    assert.equal(html.stderr, "");
    assert.match(html.stdout, /<!doctype html>/i);
    assert.match(html.stdout, new RegExp(`state: ${result.state}`));
  }
});

test("CLI rejects unknown arguments and inherited demo keys without stdout", () => {
  for (const [args, message] of [
    [["--case", "missing", "--format", "json"], "unknown demo case: missing"],
    [["--case", "__proto__", "--format", "json"], "unknown demo case: __proto__"],
    [["--case", "constructor", "--format", "json"], "unknown demo case: constructor"],
    [["--case", "ready", "--format", "text"], "unknown output format: text"],
    [["--case", "ready"], "expected --case <id> --format <json|html>"],
  ] as const) {
    const result = runCli(...args);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, `${message}\n`);
  }
});


test("does not interpolate an unexpected runtime state into the CSS class attribute", () => {
  const html = renderKnowledgeImpactNavigatorHtml({
    mode: "preview",
    side_effects: "forbidden",
    state: "blocked\" onmouseover=alert(1)" as unknown as "blocked",
    focus: null,
    navigation: null,
    impacted_steps: [],
    reasons: [],
  });

  assert.match(html, /class="state state-invalid-input"/);
  assert.match(html, /state: blocked&quot; onmouseover=alert\(1\)/);
  assert.doesNotMatch(html, /<[^>]*\bonmouseover\s*=/i);
});
