import type { KnowledgeProjectMapPreview, KnowledgeUnitRef } from "./project-map-preview.ts";

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]!);
}

function ref(value: KnowledgeUnitRef | null): string {
  return value === null ? "无" : `${escapeHtml(value.id)} @ r${escapeHtml(value.revision)}`;
}

function unitLabel(value: KnowledgeUnitRef): string {
  if (value.id === "10000000-0000-4000-8000-000000000001") return "等式变形";
  if (value.id === "10000000-0000-4000-8000-000000000002") return "一元一次方程求解";
  return `KnowledgeUnit ${ref(value)}`;
}

function nodeLabel(value: KnowledgeUnitRef | null): string {
  return value === null ? "无选中节点" : `CognitiveNode ${ref(value)}`;
}

function listRefs(items: readonly KnowledgeUnitRef[], empty: string): string {
  return items.length === 0 ? `<p class="none">${escapeHtml(empty)}</p>` : `<ul>${items.map((item) => `<li>${ref(item)}</li>`).join("")}</ul>`;
}

function statusText(status: "blocked" | "needs_evidence" | "ready"): string {
  return status === "blocked" ? "blocked（缺少先修）" : status === "needs_evidence" ? "needs_evidence（缺少证据）" : "ready（投影就绪）";
}

function unitCards(preview: KnowledgeProjectMapPreview): string {
  if (preview.units.length === 0) return '<p class="none">未形成工程图单元。</p>';
  return `<div class="units">${preview.units.map((unit) => `<article class="unit ${escapeHtml(unit.status)}">
    <h3>${unitLabel(unit.ref)}</h3><p class="ref">${ref(unit.ref)}</p>
    <p><span class="status">${escapeHtml(statusText(unit.status))}</span></p>
    <h4>缺失证据</h4>${listRefs(unit.missing_evidence_node_refs, "无")}
    <h4>缺失先修</h4>${listRefs(unit.missing_prerequisite_refs, "无")}
  </article>`).join("")}</div>`;
}

function edges(preview: KnowledgeProjectMapPreview): string {
  if (preview.prerequisite_edges.length === 0) return '<p class="none">无已加载单元之间的先修边。</p>';
  return `<ol class="edges">${preview.prerequisite_edges.map((edge) => `<li><span>${unitLabel(edge.prerequisite_unit_ref)}</span><b aria-hidden="true"> → </b><span>${unitLabel(edge.dependent_unit_ref)}</span><small>${ref(edge.prerequisite_unit_ref)} → ${ref(edge.dependent_unit_ref)}</small></li>`).join("")}</ol>`;
}

function externalPrerequisites(preview: KnowledgeProjectMapPreview): string {
  if (preview.external_prerequisite_refs.length === 0) return '<p class="none">无未加载的外部先修。</p>';
  return `<div class="external">${preview.external_prerequisite_refs.map((item) => `<article><h3>未加载的外部先修</h3><p>${ref(item)}</p><p>此引用来自投影的缺失先修；它不是本次预览中伪造出的 KnowledgeUnit。</p></article>`).join("")}</div>`;
}

function reverseImpact(preview: KnowledgeProjectMapPreview): string {
  if (preview.selected_node_ref === null) return '<p class="none">无选中 CognitiveNode；不形成反向影响。</p>';
  const units = preview.affected_unit_refs.length === 0
    ? '<p class="none">该节点没有固定工程图中的受影响 KnowledgeUnit；不伪造影响。</p>'
    : `<ol class="impact">${preview.affected_unit_refs.map((item) => `<li><span>${nodeLabel(preview.selected_node_ref)}</span><b aria-hidden="true"> → </b><span>${unitLabel(item)}</span><small>${ref(preview.selected_node_ref)} → ${ref(item)}</small></li>`).join("")}</ol>`;
  return `<p><strong>已选：</strong>${nodeLabel(preview.selected_node_ref)}</p>${units}`;
}

function message(preview: KnowledgeProjectMapPreview): string {
  if (preview.state === "invalid_input") return "输入不在固定案例集合内；未形成工程图、先修边、证据缺口或反向影响。";
  if (preview.state === "empty") return "工程图已投影，但当前选中的 CognitiveNode 没有反向影响；不伪造受影响 KnowledgeUnit。";
  if (preview.external_prerequisite_refs.length > 0) return "工程图显示一个未加载的外部先修。它是阻断证据，不是可在此页面创建或补齐的单元。";
  return "工程图显示内部先修、缺失证据，以及所选 CognitiveNode 到受影响 KnowledgeUnit 的反向影响。";
}

export function renderKnowledgeProjectMapPreviewHtml(preview: KnowledgeProjectMapPreview): string {
  const title = `KnowledgeUnit 工程知识图谱预览：${preview.state}`;
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
:root { color-scheme: light; font-family: "Microsoft YaHei", system-ui, sans-serif; background: #f5f8fc; color: #17253d; } body { margin: 0; } main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 58px; } h1 { font-size: 30px; margin: 0 0 8px; } h2 { font-size: 19px; margin: 0 0 12px; } h3 { margin: 0; font-size: 17px; } h4 { color: #53667e; font-size: 13px; margin: 14px 0 5px; } .card { background: #fff; border: 1px solid #d7e0ec; border-radius: 14px; padding: 20px; margin-top: 17px; box-shadow: 0 4px 18px #16233d0b; } .notice { border-left: 5px solid #285ea8; background: #edf5ff; font-size: 17px; line-height: 1.7; } .badges { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; } .badge { background: #e7eef8; color: #174276; border-radius: 999px; padding: 4px 10px; font: 600 13px ui-monospace, monospace; } .units { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 14px; } .unit { border: 1px solid #d8e1ed; border-radius: 11px; padding: 16px; } .unit.ready { border-left: 5px solid #25735a; } .unit.needs_evidence { border-left: 5px solid #b77216; background: #fffaf1; } .unit.blocked { border-left: 5px solid #b54151; background: #fff5f6; } .ref, small { color: #53667e; font: 12px ui-monospace, monospace; overflow-wrap: anywhere; } .status { border-radius: 8px; padding: 3px 7px; background: #e7eef8; font: 600 13px ui-monospace, monospace; } ul { margin: 0; padding-left: 20px; } .edges, .impact { margin: 0; padding-left: 25px; } .edges li, .impact li { margin: 8px 0; } .edges small, .impact small { display: block; margin-top: 3px; } .external { border: 2px dashed #b54151; background: #fff5f6; border-radius: 11px; padding: 14px; } .external p { margin: 8px 0 0; } .boundary { color: #6c3140; background: #fff2f3; border-color: #f0c8cf; } .none { color: #53667e; margin: 0; } .foot { color: #53667e; font-size: 14px; line-height: 1.65; }
</style>
</head>
<body>
<main>
  <h1>KnowledgeUnit 工程知识图谱预览</h1>
  <p>固定线性方程工程案例的只读、离线、可审查投影。</p>
  <section class="card notice"><strong>${escapeHtml(message(preview))}</strong><div class="badges"><span class="badge">${escapeHtml(preview.mode)}</span><span class="badge">${escapeHtml(preview.side_effects)}</span><span class="badge">not_persisted</span><span class="badge">${escapeHtml(preview.state)}</span></div></section>
  <section class="card"><h2>KnowledgeUnit 状态卡</h2>${unitCards(preview)}</section>
  <section class="card"><h2>内部先修边</h2>${edges(preview)}</section>
  <section class="card"><h2>外部先修（阻断）</h2>${externalPrerequisites(preview)}</section>
  <section class="card"><h2>CognitiveNode → KnowledgeUnit 反向影响</h2>${reverseImpact(preview)}</section>
  <section class="card"><h2>投影诊断</h2><p>${escapeHtml(preview.diagnostic)}</p></section>
  <section class="card boundary"><h2>严格边界</h2><p>这是 <code>preview</code>，副作用为 <code>forbidden</code>，结果为 <code>not_persisted</code>。页面不保存 KnowledgeUnit、Thoughtflow、证据或 ChangeSet；不执行代码、模型或 Agent，不写入数据，也不表示个人掌握、验证完成或工程完成。</p></section>
  <p class="foot">页面由限定 CLI 调用实际 KnowledgeUnit 投影图谱生成；不接受路径输入、不访问网络。</p>
</main>
</body>
</html>
`;
}