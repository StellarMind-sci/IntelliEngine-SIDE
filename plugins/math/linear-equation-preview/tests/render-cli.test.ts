import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createLinearEquationPreview } from "../preview.ts";

const cases = JSON.parse(
  readFileSync(new URL("../fixtures/demo-cases.json", import.meta.url), "utf8"),
);
const repositoryRoot = new URL("../../../../", import.meta.url);

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

async function render(preview: unknown): Promise<string> {
  const renderer = await import("../render.ts");
  return renderer.renderLinearEquationPreviewHtml(preview as never);
}

function runCli(caseId: string, format: string) {
  return spawnSync(
    process.execPath,
    ["plugins/math/linear-equation-preview/cli.ts", "--case", caseId, "--format", format],
    { cwd: repositoryRoot, encoding: "utf8" },
  );
}

test("renders a ready preview with its equation, solution, and SymPy suggestion", async () => {
  const html = await render(createLinearEquationPreview(clone(cases.ready)));

  assert.match(html, /工程状态：ready/);
  assert.match(html, /2\*x \+ 3 = 11/);
  assert.match(html, /x = 4/);
  assert.match(html, /import sympy as sp/);
  assert.match(html, /2 \* 4 \+ 3 == 11/);
  assert.doesNotMatch(html, /<script/i);
});

test("renders a blocked preview with missing prerequisites but no code proposal", async () => {
  const html = await render(createLinearEquationPreview(clone(cases.blocked)));

  assert.match(html, /工程状态：blocked/);
  assert.match(html, /缺失前置/);
  assert.match(html, /equality-transformations-unit@1/);
  assert.doesNotMatch(html, /from sympy import/);
  assert.doesNotMatch(html, /import sympy as sp/);
});

test("renders a needs-evidence preview without a code proposal", async () => {
  const html = await render(createLinearEquationPreview(clone(cases["needs-evidence"])));

  assert.match(html, /工程状态：needs_evidence/);
  assert.match(html, /缺失证据/);
  assert.match(html, /evidence-a@2/);
  assert.doesNotMatch(html, /from sympy import/);
  assert.doesNotMatch(html, /import sympy as sp/);
});

test("renders the empty-state explanation without a code proposal", async () => {
  const html = await render(createLinearEquationPreview(clone(cases.empty)));

  assert.match(html, /工程状态：empty/);
  assert.match(html, /没有可编译的线性方程行为/);
  assert.doesNotMatch(html, /from sympy import/);
  assert.doesNotMatch(html, /import sympy as sp/);
});

test("renders invalid input without a code proposal", async () => {
  const html = await render(createLinearEquationPreview(clone(cases["invalid-equation"])));

  assert.match(html, /工程状态：invalid_input/);
  assert.doesNotMatch(html, /from sympy import/);
  assert.doesNotMatch(html, /import sympy as sp/);
});

test("HTML-escapes every dynamic preview value", async () => {
  const html = await render({
    mode: "preview",
    side_effects: "forbidden",
    state: "blocked",
    equation: { variable: "<x&", coefficient: 2, constant: 3, right_hand_side: 11 },
    proposal: null,
    impacted_steps: [{ step_id: "<step&", kind: "operation&<" }],
    reasons: [
      {
        knowledge_unit_ref: { id: "<unit&", revision: 1 },
        status: "blocked",
        missing_prerequisite_refs: [{ id: "<prerequisite&", revision: 2 }],
        missing_evidence_node_refs: [{ id: "<evidence&", revision: 3 }],
      },
    ],
  });

  assert.match(html, /&lt;x&amp;/);
  assert.match(html, /&lt;step&amp;/);
  assert.match(html, /operation&amp;&lt;/);
  assert.match(html, /&lt;unit&amp;@1/);
  assert.match(html, /&lt;prerequisite&amp;@2/);
  assert.match(html, /&lt;evidence&amp;@3/);
  assert.doesNotMatch(html, /<x&/);
  assert.doesNotMatch(html, /<step&/);
});

test("CLI renders the fixed ready fixture as HTML", () => {
  const result = runCli("ready", "html");

  assert.equal(result.status, 0);
  assert.match(result.stdout, /2\*x \+ 3 = 11/);
  assert.match(result.stdout, /工程状态：ready/);
  assert.equal(result.stderr, "");
});

test("CLI renders the fixed ready fixture as JSON", () => {
  const result = runCli("ready", "json");

  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), createLinearEquationPreview(clone(cases.ready)));
  assert.equal(result.stderr, "");
});

test("CLI withholds SymPy from blocked, empty, and invalid fixture output", () => {
  for (const caseId of ["blocked", "empty", "invalid-equation"]) {
    const result = runCli(caseId, "html");

    assert.equal(result.status, 0, caseId);
    assert.doesNotMatch(result.stdout, /from sympy import/, caseId);
    assert.doesNotMatch(result.stdout, /import sympy as sp/, caseId);
    assert.equal(result.stderr, "", caseId);
  }
});

test("CLI reports unknown case and format with stable nonzero stderr", () => {
  const missingCase = runCli("missing", "html");
  const missingFormat = runCli("ready", "text");

  assert.notEqual(missingCase.status, 0);
  assert.equal(missingCase.stdout, "");
  assert.equal(missingCase.stderr, "unknown demo case: missing\n");
  assert.notEqual(missingFormat.status, 0);
  assert.equal(missingFormat.stdout, "");
  assert.equal(missingFormat.stderr, "unknown output format: text\n");
});

test("CLI rejects inherited fixture property names as unknown demo cases", () => {
  for (const caseId of ["__proto__", "constructor"]) {
    const result = runCli(caseId, "json");

    assert.notEqual(result.status, 0, caseId);
    assert.equal(result.stdout, "", caseId);
    assert.equal(result.stderr, `unknown demo case: ${caseId}\n`, caseId);
  }
});

test("renders blocked and needs-evidence with distinct status CSS rules", async () => {
  const blockedHtml = await render(createLinearEquationPreview(clone(cases.blocked)));
  const needsEvidenceHtml = await render(createLinearEquationPreview(clone(cases["needs-evidence"])));
  const blockedStyle = blockedHtml.match(/\.state-blocked \{([^}]+)\}/)?.[1];
  const needsEvidenceStyle = needsEvidenceHtml.match(/\.state-needs-evidence \{([^}]+)\}/)?.[1];

  assert.ok(blockedStyle);
  assert.ok(needsEvidenceStyle);
  assert.notEqual(blockedStyle, needsEvidenceStyle);
  assert.doesNotMatch(blockedHtml, /import sympy as sp/);
  assert.doesNotMatch(needsEvidenceHtml, /import sympy as sp/);
});
