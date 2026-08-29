import type { LinearEquationIntakePreview } from "./intake.ts";

function escapeHtml(value: unknown): string {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function stateClass(state: unknown): string {
  return state === "ready" ? "state-ready" : state === "empty" ? "state-empty" : "state-invalid-input";
}

function candidateHtml(preview: LinearEquationIntakePreview): string {
  if (preview.candidate_node === null) return "<p>当前状态不生成候选节点。</p>";
  const node = preview.candidate_node;
  return `<dl><dt>id</dt><dd><code>${escapeHtml(node.id)}</code></dd><dt>type</dt><dd><code>${escapeHtml(node.type_id)}@${escapeHtml(node.type_version)}</code></dd><dt>data</dt><dd><code>${escapeHtml(JSON.stringify(node.data))}</code></dd><dt>provenance</dt><dd><code>${escapeHtml(node.provenance_refs[0])}</code></dd></dl>`;
}

export function renderLinearEquationIntakePreviewHtml(preview: LinearEquationIntakePreview): string {
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>线性方程文本摄入预览</title><style>
:root{font-family:system-ui,sans-serif;color:#172033;background:#f5f7fa}body{margin:0}main{max-width:54rem;margin:2rem auto;padding:1.5rem;background:#fff;border:1px solid #d7ddea;border-radius:.75rem}section{margin-top:1rem;padding-top:1rem;border-top:1px solid #d7ddea}.state{padding:1rem;border-left:.4rem solid}.state-ready{background:#e8f7ee;border-color:#167a3f}.state-empty{background:#edf2f7;border-color:#526170}.state-invalid-input{background:#fdeceb;border-color:#b42318}dl{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1rem}dt{font-weight:700}dd{margin:0}code{font-family:ui-monospace,Consolas,monospace;overflow-wrap:anywhere}.notice{color:#526170}
</style></head><body><main>
<h1>线性方程文本摄入预览</h1><p class="notice">只读 preview；不接受或读取用户指定文件；候选验证只读使用固定仓库契约资源；不执行、不写入、不联网、不调用 Agent 或 ChangeSet。</p>
<section><dl><dt>mode</dt><dd><code>${escapeHtml(preview.mode)}</code></dd><dt>side_effects</dt><dd><code>${escapeHtml(preview.side_effects)}</code></dd></dl></section>
<section class="state ${stateClass(preview.state)}"><h2>状态：${escapeHtml(preview.state)}</h2><p>${escapeHtml(preview.diagnostic ?? "候选已通过固定 CognitiveNode 语义校验。")}</p></section>
<section><h2>原文与来源</h2><dl><dt>text</dt><dd><code>${escapeHtml(preview.source.text)}</code></dd><dt>source_ref</dt><dd><code>${escapeHtml(preview.source.source_ref ?? "无")}</code></dd></dl></section>
<section><h2>数学提取</h2><dl><dt>规范方程</dt><dd><code>${escapeHtml(preview.normalized_equation ?? "无")}</code></dd><dt>变量</dt><dd><code>${escapeHtml(preview.variable ?? "无")}</code></dd></dl></section>
<section><h2>候选 CognitiveNode</h2><p class="notice">候选尚未写入工程。</p>${candidateHtml(preview)}</section>
</main></body></html>`;
}
