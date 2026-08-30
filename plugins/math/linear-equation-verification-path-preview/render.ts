import type { LinearEquationVerificationPathPreview } from "./verification-path-preview.ts";

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]!);
}

function ref(value: { id: string; revision: number } | null): string {
  return value === null ? "无" : `${escapeHtml(value.id)} @ r${escapeHtml(value.revision)}`;
}

function item(label: string, value: unknown): string {
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
}

function list(items: readonly { id: string; revision: number }[]): string {
  if (items.length === 0) return "<p>无</p>";
  return `<ul>${items.map((item) => `<li>${ref(item)}</li>`).join("")}</ul>`;
}

function message(preview: LinearEquationVerificationPathPreview): string {
  if (preview.state === "needs_evidence") {
    return "已形成未持久化 KnowledgeUnit 草案，并仅在关联的 verification 预览上下文中提示补充缺失证据。";
  }
  if (preview.knowledge_unit_ref !== null) {
    return "KnowledgeUnit 草案存在，但当前预览工程上下文没有关联 verification 步骤；不伪造下一步。";
  }
  if (preview.state === "empty") return "上游输入为空：未形成 KnowledgeUnit、Thoughtflow 上下文或导航。";
  return "上游输入无效：未形成 KnowledgeUnit、Thoughtflow 上下文或导航。";
}

export function renderVerificationPathPreviewHtml(preview: LinearEquationVerificationPathPreview): string {
  const context = preview.flow_context === null
    ? "无（未形成 Thoughtflow 预览）"
    : preview.flow_context.steps.length === 0
      ? "not_persisted；无关联步骤"
      : "not_persisted；仅关联 verification-linear-equation";
  const navigation = preview.navigation === null ? "无" : preview.navigation;
  const impacts = preview.impacted_steps.length === 0 ? "无" : preview.impacted_steps.map((step) => step.step_id).join("、");
  const evidence = list(preview.missing_evidence_node_refs);
  const diagnostic = preview.diagnostic === null ? "无" : preview.diagnostic;
  const title = `线性方程验证路径预览：${preview.state}`;
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
:root { color-scheme: light; font-family: "Microsoft YaHei", system-ui, sans-serif; background: #f4f7fb; color: #17253d; }
body { margin: 0; } main { max-width: 1020px; margin: 0 auto; padding: 36px 24px 56px; }
h1 { font-size: 29px; margin: 0 0 8px; } h2 { font-size: 18px; margin: 0 0 12px; }
.card { background: #fff; border: 1px solid #d7e0ec; border-radius: 14px; padding: 20px; margin-top: 18px; box-shadow: 0 4px 18px #16233d0b; }
.notice { border-left: 5px solid #285ea8; background: #edf5ff; font-size: 17px; line-height: 1.7; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0 0; } .badge { background: #e7eef8; color: #174276; border-radius: 999px; padding: 4px 10px; font: 600 13px ui-monospace, monospace; }
dl { display: grid; grid-template-columns: minmax(185px, 32%) 1fr; gap: 10px 18px; margin: 0; } dt { color: #53667e; } dd { margin: 0; overflow-wrap: anywhere; }
ul { margin: 0; padding-left: 22px; } .boundary { color: #6c3140; background: #fff2f3; border-color: #f0c8cf; } .foot { color: #53667e; font-size: 14px; line-height: 1.65; }
</style>
</head>
<body>
<main>
  <h1>线性方程 KnowledgeUnit → verification 路径预览</h1>
  <p>固定案例的只读、离线验收输出。</p>
  <section class="card notice"><strong>${escapeHtml(message(preview))}</strong>
    <div class="badges"><span class="badge">${escapeHtml(preview.mode)}</span><span class="badge">${escapeHtml(preview.side_effects)}</span><span class="badge">${escapeHtml(preview.flow_context?.persistence ?? "not_persisted")}</span><span class="badge">${escapeHtml(preview.state)}</span></div>
  </section>
  <section class="card"><h2>真实桥接结果</h2><dl>
    ${item("来源", preview.source_ref ?? "无")}
    <dt>KnowledgeUnit 引用</dt><dd>${ref(preview.knowledge_unit_ref)}</dd>
    ${item("Thoughtflow 预览上下文", context)}
    ${item("导航提示", navigation)}
    ${item("受影响步骤", impacts)}
    ${item("诊断", diagnostic)}
  </dl></section>
  <section class="card"><h2>缺失证据节点</h2>${evidence}</section>
  <section class="card boundary"><h2>严格边界</h2><p>这是 <code>preview</code>，副作用为 <code>forbidden</code>。页面不保存 Thoughtflow，不执行代码或模型，不写入任何数据；它也不表示掌握、验证完成或可进入完成状态。</p></section>
  <p class="foot">此页面由限定 CLI 调用实际 bridge 生成；输入不是用户路径，也不访问网络。</p>
</main>
</body>
</html>
`;
}