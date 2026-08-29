import type { KnowledgeEvidencePreviewResult, KnowledgeUnitRef } from "./navigator.ts";

function escapeHtml(value: unknown): string {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function reference(value: KnowledgeUnitRef): string {
  return `${escapeHtml(value.id)}@${escapeHtml(value.revision)}`;
}

function refs(values: KnowledgeUnitRef[]): string {
  return values.length === 0 ? "<li>无</li>" : values.map((value) => `<li><code>${reference(value)}</code></li>`).join("");
}

function evidenceRows(result: KnowledgeEvidencePreviewResult): string {
  const validations = result.validations.map((item) => `<li><strong>${escapeHtml(item.validation_id)}</strong> — ${escapeHtml(item.description)}<br>证据节点：<ul>${refs(item.evidence_node_refs)}</ul>缺失证据：<ul>${refs(item.missing_evidence_node_refs)}</ul><span class="status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></li>`).join("");
  const criteria = result.mastery_criteria.map((item) => `<li><strong>${escapeHtml(item.criterion_id)}</strong> — ${escapeHtml(item.statement)}<br>证据节点：<ul>${refs(item.evidence_node_refs)}</ul>缺失证据：<ul>${refs(item.missing_evidence_node_refs)}</ul><span class="status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></li>`).join("");
  return `<section><h2>验证要求</h2><ul>${validations || "<li>无</li>"}</ul></section><section><h2>工程证据标准</h2><ul>${criteria || "<li>无</li>"}</ul></section>`;
}

function impacts(result: KnowledgeEvidencePreviewResult): string {
  if (result.impacted_steps.length === 0) return "";
  return `<section><h2>受影响的工程步骤</h2><ul>${result.impacted_steps.map((step) => `<li><code>${escapeHtml(step)}</code></li>`).join("")}</ul></section>`;
}
function navigation(result: KnowledgeEvidencePreviewResult): string {
  if (result.navigation === null) {
    const message = result.state === "invalid_input" ? "输入或上游投影无效；预览已封闭，不生成导航。" : result.state === "empty" ? "当前工程流没有可安全定位的受影响步骤；不伪造下一步。" : "当前验证要求已满足；不伪造下一步。";
    return `<section class="no-navigation"><h2>无导航</h2><p>${message}</p></section>`;
  }
  const steps = result.verification_steps.length === 0 ? "" : `<section><h2>关联 verification 步骤</h2><ul>${result.verification_steps.map((step) => `<li><code>${escapeHtml(step)}</code></li>`).join("")}</ul></section>`;
  return `<section class="navigation"><h2>只读导航</h2><p>${escapeHtml(result.navigation)}</p></section>${steps}`;
}

export function renderKnowledgeEvidencePreviewHtml(result: KnowledgeEvidencePreviewResult): string {
  const stateClass = ({ blocked: "state-blocked", needs_evidence: "state-needs-evidence", ready: "state-ready", empty: "state-empty", invalid_input: "state-invalid-input" } as Record<string, string>)[result.state] ?? "state-invalid-input";
  const focus = result.focus === null ? "无" : reference(result.focus);
  return `<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>KnowledgeUnit 验证证据预览</title>
<style>
:root { color-scheme: light; font-family: "Segoe UI", sans-serif; background: #f5f7fb; color: #172033; } body { margin: 0; padding: 32px; } main { max-width: 860px; margin: 0 auto; background: #fff; border: 1px solid #d9e1ee; border-radius: 16px; padding: 28px; box-shadow: 0 12px 32px #1d2a4420; } h1 { margin-top: 0; } h2 { font-size: 1.05rem; margin-bottom: 8px; } section { border-top: 1px solid #e6ebf3; padding-top: 14px; margin-top: 18px; } code { overflow-wrap: anywhere; } ul { padding-left: 22px; } .meta { display: flex; flex-wrap: wrap; gap: 8px; } .pill { padding: 4px 8px; border-radius: 999px; background: #e8edf6; font-family: ui-monospace, monospace; } .state { display: inline-block; margin-top: 16px; padding: 8px 12px; border-radius: 8px; font-weight: 700; } .state-blocked { background: #ffe4e6; color: #9f1239; border: 1px solid #fda4af; } .state-needs-evidence { background: #f3e8ff; color: #6b21a8; border: 1px solid #d8b4fe; } .state-ready { background: #dcfce7; color: #166534; border: 1px solid #86efac; } .state-empty { background: #e5e7eb; color: #374151; border: 1px solid #9ca3af; } .state-invalid-input { background: #ffedd5; color: #9a3412; border: 1px solid #fdba74; } .navigation { background: #edf6ff; border: 1px solid #93c5fd; border-radius: 8px; padding: 14px; } .no-navigation { background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 14px; } .notice { color: #475569; font-size: .94rem; } .status { font-weight: 700; } .status-satisfied { color: #166534; } .status-missing { color: #9a3412; }
</style></head>
<body><main><h1>KnowledgeUnit 验证证据预览</h1><div class="meta"><span class="pill">mode: preview</span><span class="pill">side_effects: forbidden</span><span class="pill">focus: ${focus}</span></div><div class="state ${stateClass}">state: ${escapeHtml(result.state)}</div><p class="notice">仅验证解释与导航提示，不执行、不写入，不表达个人掌握结论。</p>${navigation(result)}${impacts(result)}${evidenceRows(result)}</main></body></html>`;
}
