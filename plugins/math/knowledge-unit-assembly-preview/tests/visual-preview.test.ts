import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createLinearEquationIntakePreview } from "../../linear-equation-intake-preview/intake.ts";
import { createLinearEquationKnowledgeUnitAssemblyPreview } from "../assembly.ts";
import { renderLinearEquationKnowledgeUnitAssemblyPreviewHtml } from "../render.ts";

function preview(text: string) {
  return createLinearEquationKnowledgeUnitAssemblyPreview({
    intake_preview: createLinearEquationIntakePreview({ text, source_ref: "prov:source:algebra-example-1" }),
  });
}

function cli(args: string[]) {
  return spawnSync(process.execPath, [fileURLToPath(new URL("../cli.ts", import.meta.url)), ...args], {
    cwd: fileURLToPath(new URL("../../../../", import.meta.url)),
    encoding: "utf8",
  });
}

test("renders the valid draft as needs_evidence without treating it as learner mastery", () => {
  const output = renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(preview("2x + 3 = 11"));

  assert.match(output, /state：needs_evidence/);
  assert.match(output, /解一元一次方程：2\*x \+ 3 = 11/);
  assert.match(output, /core/);
  assert.match(output, /evidence/);
  assert.match(output, /example/);
  assert.match(output, /representation/);
  assert.match(output, /missing evidence ref/);
  assert.match(output, /不表示用户已掌握/);
  assert.match(output, /mode.*preview/);
  assert.match(output, /side_effects.*forbidden/);
  assert.doesNotMatch(output, /<script\b|<iframe\b|\son\w+\s*=/i);
});

test("HTML-escapes all dynamic diagnostic content", () => {
  const invalid = {
    ...preview("x^2 = 4"),
    diagnostic: '<unsafe&"\' value>',
  };
  const output = renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(invalid);

  assert.match(output, /&lt;unsafe&amp;&quot;&#39; value&gt;/);
  assert.doesNotMatch(output, /<unsafe/);
});

test("renders empty and invalid_input without a fabricated draft, nodes, or projection", () => {
  for (const input of [preview("  \t"), preview("x^2 = 4")]) {
    const output = renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(input);
    assert.match(output, /当前状态不生成 KnowledgeUnit 草案、候选节点或投影。/);
    assert.doesNotMatch(output, /解一元一次方程：/);
    assert.doesNotMatch(output, /missing evidence ref/);
  }
});

test("CLI generates all fixed states from the real intake to assembly path", () => {
  for (const caseId of ["needs-evidence", "empty", "invalid"]) {
    const json = cli(["--case", caseId, "--format", "json"]);
    const html = cli(["--case", caseId, "--format", "html"]);
    const expectedState = caseId === "needs-evidence" ? "needs_evidence" : caseId === "invalid" ? "invalid_input" : "empty";
    assert.equal(json.status, 0, json.stderr);
    assert.equal(json.stderr, "");
    assert.equal(html.status, 0, html.stderr);
    assert.equal(html.stderr, "");
    assert.match(html.stdout, new RegExp(`state：${expectedState}`));
    assert.equal(JSON.parse(json.stdout).state, expectedState);
  }
});

test("CLI rejects unknown options and prototype-like case identifiers without stdout", () => {
  for (const [args, error] of [
    [["--case", "missing", "--format", "html"], "unknown demo case: missing"],
    [["--case", "__proto__", "--format", "json"], "unknown demo case: __proto__"],
    [["--case", "empty", "--format", "text"], "unknown output format: text"],
    [["--format", "html", "--case", "empty"], "expected --case <id> --format <json|html>"],
  ] as Array<[string[], string]>) {
    const result = cli(args);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, `${error}\n`);
  }
});

test("committed HTML artifacts reproduce the CLI output exactly", () => {
  for (const caseId of ["needs-evidence", "empty", "invalid"]) {
    const result = cli(["--case", caseId, "--format", "html"]);
    assert.equal(result.status, 0, result.stderr);
    const committed = readFileSync(new URL(`../../../../docs/demos/artifacts/knowledge-unit-assembly-preview/${caseId}.html`, import.meta.url), "utf8");
    assert.equal(committed, result.stdout);
  }
});
test("escapes constructed needs_evidence fields without producing executable markup", () => {
  const injected = structuredClone(preview("2x + 3 = 11"));
  const token = "<>& onerror=alert(1)";
  injected.source_ref = `source${token}`;
  const unit = injected.knowledge_unit!;
  unit.title = `title${token}`;
  unit.id = `unit${token}`;
  for (const [index, node] of injected.candidate_nodes.entries()) {
    const mutable = node as unknown as { id: string; type_id: string; data: { name?: string; expression?: string; symbols?: string[] } };
    mutable.id = `node-${index}${token}`;
    mutable.type_id = `type-${index}${token}`;
    mutable.data = { name: `data-${index}${token}` };
  }
  for (const [index, binding] of unit.node_bindings.entries()) binding.node_ref.id = `binding-${index}${token}`;
  (unit.validations[0] as unknown as { description: string; validation_id: string }).description = `validation${token}`;
  (unit.validations[0] as unknown as { description: string; validation_id: string }).validation_id = `validation-id${token}`;
  (unit.mastery_criteria[0] as unknown as { statement: string; criterion_id: string }).statement = `mastery${token}`;
  (unit.mastery_criteria[0] as unknown as { statement: string; criterion_id: string }).criterion_id = `mastery-id${token}`;
  injected.projection!.missing_evidence_node_refs[0].id = `missing${token}`;
  injected.navigation = `navigation${token}` as typeof injected.navigation;

  const output = renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(injected);

  for (const escaped of [
    "source&lt;&gt;&amp; onerror=alert(1)", "title&lt;&gt;&amp; onerror=alert(1)", "unit&lt;&gt;&amp; onerror=alert(1)",
    "binding-0&lt;&gt;&amp; onerror=alert(1)", "type-0&lt;&gt;&amp; onerror=alert(1)", "data-0&lt;&gt;&amp; onerror=alert(1)",
    "validation&lt;&gt;&amp; onerror=alert(1)", "mastery&lt;&gt;&amp; onerror=alert(1)", "missing&lt;&gt;&amp; onerror=alert(1)",
    "navigation&lt;&gt;&amp; onerror=alert(1)",
  ]) assert.equal(output.includes(escaped), true, escaped);
  assert.doesNotMatch(output, /<script\b|<iframe\b|<[^>]*\sonerror\s*=/i);
});