import type { LinearEquationKnowledgeUnitAssemblyPreview } from "./assembly.ts";

type NodeRef = { id: string; revision: number };

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function referenceHtml(reference: NodeRef): string {
  return `<code>${escapeHtml(reference.id)}@${escapeHtml(reference.revision)}</code>`;
}

function stateClass(state: LinearEquationKnowledgeUnitAssemblyPreview["state"]): string {
  if (state === "needs_evidence") return "state-needs-evidence";
  if (state === "empty") return "state-empty";
  return "state-invalid-input";
}

function draftHtml(preview: LinearEquationKnowledgeUnitAssemblyPreview): string {
  if (preview.state !== "needs_evidence" || preview.knowledge_unit === null || preview.projection === null || preview.validation === null) {
    return `<section><h2>草案与投影</h2><p>当前状态不生成 KnowledgeUnit 草案、候选节点或投影。</p></section>`;
  }
  const unit = preview.knowledge_unit;
  const bindings = unit.node_bindings.map((binding) => `<tr><td><code>${escapeHtml(binding.role)}</code></td><td>${referenceHtml(binding.node_ref)}</td></tr>`).join("");
  const candidates = preview.candidate_nodes.map((node) => `<tr><td>${referenceHtml(node)}</td><td><code>${escapeHtml(node.type_id)}@${escapeHtml(node.type_version)}</code></td><td><code>${escapeHtml(JSON.stringify(node.data))}</code></td></tr>`).join("");
  const missing = preview.projection.missing_evidence_node_refs.map(referenceHtml).join("、");
  return `<section><h2>KnowledgeUnit 草案</h2><dl><dt>title</dt><dd>${escapeHtml(unit.title)}</dd><dt>id</dt><dd>${referenceHtml(unit)}</dd><dt>source_ref</dt><dd><code>${escapeHtml(preview.source_ref ?? "无")}</code></dd><dt>合同校验</dt><dd><code>CognitiveNode: ${escapeHtml(preview.validation.cognitive_nodes)}; KnowledgeUnit: ${escapeHtml(preview.validation.knowledge_unit)}</code></dd></dl><p>草案仅在内存中生成，尚未写入工程。</p></section>
<section><h2>四类 CognitiveNode 角色</h2><table><thead><tr><th>role</th><th>node ref</th></tr></thead><tbody>${bindings}</tbody></table><details><summary>候选节点详情（只读）</summary><table><thead><tr><th>node ref</th><th>type</th><th>data</th></tr></thead><tbody>${candidates}</tbody></table></details></section>
<section><h2>工程验证与掌握证据</h2><p>validation：${escapeHtml(unit.validations[0]?.description ?? "无")}</p><p>mastery criterion：${escapeHtml(unit.mastery_criteria[0]?.statement ?? "无")}</p><p><strong>missing evidence ref：</strong>${missing}</p><p class="warning">合同结构有效，但代入验证证据尚未记录。此状态不表示用户已掌握，不表示验证已完成，也不是 ready。</p><p>${escapeHtml(preview.navigation ?? "")}</p></section>`;
}

export function renderLinearEquationKnowledgeUnitAssemblyPreviewHtml(preview: LinearEquationKnowledgeUnitAssemblyPreview): string {
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>一元一次方程 KnowledgeUnit 组装预览</title><style>
:root{font-family:system-ui,sans-serif;color:#172033;background:#f5f7fa}body{margin:0}main{max-width:68rem;margin:2rem auto;padding:1.5rem;background:#fff;border:1px solid #d7ddea;border-radius:.75rem}section{margin-top:1rem;padding-top:1rem;border-top:1px solid #d7ddea}.state{padding:1rem;border-left:.4rem solid}.state-needs-evidence{background:#f4edff;border-color:#6f42c1}.state-empty{background:#edf2f7;border-color:#526170}.state-invalid-input{background:#fdeceb;border-color:#b42318}.notice{color:#526170}.warning{color:#5c2d91;font-weight:650}dl{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1rem}dt{font-weight:700}dd{margin:0}code{font-family:ui-monospace,Consolas,monospace;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;margin-top:.75rem}th,td{padding:.5rem;border:1px solid #d7ddea;text-align:left;vertical-align:top}details{margin-top:1rem}summary{cursor:pointer}
</style></head><body><main>
<h1>一元一次方程 KnowledgeUnit 组装预览</h1>
<p class="notice">只读 preview；<code>mode: preview</code>；<code>side_effects: forbidden</code>。不写入、不执行、不联网、不调用 Agent 或 ChangeSet。组装与校验只读使用插件内部固定推导的 CognitiveNode 1.0.0 与 KnowledgeUnit 1.0.0 仓库合同资源；不接受或读取用户指定路径。</p>
<section><dl><dt>mode</dt><dd><code>${escapeHtml(preview.mode)}</code></dd><dt>side_effects</dt><dd><code>${escapeHtml(preview.side_effects)}</code></dd></dl></section>
<section class="state ${stateClass(preview.state)}"><h2>state：${escapeHtml(preview.state)}</h2><p>${escapeHtml(preview.diagnostic ?? "合同有效，等待工程验证证据。")}</p></section>
${draftHtml(preview)}
</main></body></html>`;
}