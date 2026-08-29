import type { PreviewReason, PreviewResult, Ref } from "./preview.ts";

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function refText(ref: Ref): string {
  return `${ref.id}@${ref.revision}`;
}

function refList(refs: Ref[]): string {
  if (refs.length === 0) return "<span>无</span>";
  return `<ul>${refs.map((ref) => `<li><code>${escapeHtml(refText(ref))}</code></li>`).join("")}</ul>`;
}

function reasonHtml(reason: PreviewReason): string {
  return `<article class="reason">
  <h3>${escapeHtml(reason.status)}</h3>
  <p>KnowledgeUnit：<code>${escapeHtml(refText(reason.knowledge_unit_ref))}</code></p>
  <dl>
    <dt>缺失前置</dt><dd>${refList(reason.missing_prerequisite_refs)}</dd>
    <dt>缺失证据</dt><dd>${refList(reason.missing_evidence_node_refs)}</dd>
  </dl>
</article>`;
}

function stateClass(state: PreviewResult["state"]): string {
  const classes: Record<PreviewResult["state"], string> = {
    ready: "state-ready",
    blocked: "state-blocked",
    needs_evidence: "state-needs-evidence",
    empty: "state-empty",
    invalid_input: "state-invalid-input",
  };
  return classes[state];
}

function stateMessage(state: PreviewResult["state"]): string {
  const messages: Record<PreviewResult["state"], string> = {
    ready: "模型建议已生成；它仍是只读预览。",
    blocked: "工程状态被阻断；请先补齐前置条件。",
    needs_evidence: "工程状态缺少证据；请先补齐验证证据。",
    empty: "没有可编译的线性方程行为。",
    invalid_input: "输入不满足受限线性方程预览的要求。",
  };
  return messages[state];
}

function equationText(preview: PreviewResult): string {
  const equation = preview.equation;
  const constant = equation.constant < 0 ? `- ${Math.abs(equation.constant)}` : `+ ${equation.constant}`;
  return `${equation.coefficient}*${equation.variable} ${constant} = ${equation.right_hand_side}`;
}

function impactedStepsHtml(preview: PreviewResult): string {
  if (preview.impacted_steps.length === 0) return "<p>无受影响步骤。</p>";
  return `<ul>${preview.impacted_steps
    .map((step) => `<li><code>${escapeHtml(step.step_id)}</code>（${escapeHtml(step.kind)}）</li>`)
    .join("")}</ul>`;
}

function proposalHtml(preview: PreviewResult): string {
  if (preview.state !== "ready" || preview.proposal === null) {
    return "<p>当前工程状态不提供代码建议。</p>";
  }
  const proposal = preview.proposal;
  return `<dl>
  <dt>规范方程</dt><dd><code>${escapeHtml(proposal.canonical_equation)}</code></dd>
  <dt>解</dt><dd><code>${escapeHtml(proposal.solution.variable)} = ${escapeHtml(proposal.solution.value)}</code></dd>
  <dt>验证断言</dt><dd><code>${escapeHtml(proposal.verification_assertion)}</code></dd>
</dl>
<h3>SymPy 建议（未执行）</h3>
<pre><code>${escapeHtml(proposal.sympy_source)}</code></pre>`;
}

export function renderLinearEquationPreviewHtml(preview: PreviewResult): string {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>线性方程模型预览</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #f5f7fa; color: #172033; }
    main { max-width: 54rem; margin: 2rem auto; padding: 1.5rem; background: #fff; border: 1px solid #d7ddea; border-radius: .75rem; }
    h1, h2, h3 { margin-top: 0; }
    section { margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #d7ddea; }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: .45rem 1rem; }
    dt { font-weight: 700; } dd { margin: 0; }
    .state { padding: 1rem; border-left: .4rem solid; border-radius: .35rem; }
    .state-ready { background: #e8f7ee; border-color: #167a3f; }
    .state-blocked { background: #fff3df; border-color: #b45f06; }
    .state-needs-evidence { background: #f1edff; border-color: #6941c6; }
    .state-empty { background: #edf2f7; border-color: #526170; }
    .state-invalid-input { background: #fdeceb; border-color: #b42318; }
    .reason { margin-top: .75rem; padding: .75rem; background: #fafbfc; border: 1px solid #d7ddea; border-radius: .35rem; }
    pre { overflow-x: auto; padding: 1rem; background: #172033; color: #f4f7fb; border-radius: .35rem; white-space: pre-wrap; }
    code { font-family: ui-monospace, Consolas, monospace; }
    .notice { color: #526170; }
    @media print { body { background: #fff; } main { max-width: none; margin: 0; border: 0; } pre { color: #172033; background: #f4f4f4; } }
  </style>
</head>
<body>
  <main>
    <h1>线性方程模型预览</h1>
    <p class="notice">只读 preview；不执行 Python、SymPy 或验证。</p>
    <section aria-label="预览元数据">
      <dl>
        <dt>mode</dt><dd><code>${escapeHtml(preview.mode)}</code></dd>
        <dt>side_effects</dt><dd><code>${escapeHtml(preview.side_effects)}</code></dd>
      </dl>
    </section>
    <section class="state ${stateClass(preview.state)}" aria-label="工程状态">
      <h2>工程状态：${escapeHtml(preview.state)}</h2>
      <p>${escapeHtml(stateMessage(preview.state))}</p>
    </section>
    <section>
      <h2>方程</h2>
      <p><code>${escapeHtml(equationText(preview))}</code></p>
    </section>
    <section>
      <h2>受影响步骤</h2>
      ${impactedStepsHtml(preview)}
    </section>
    <section>
      <h2>阻断原因</h2>
      ${preview.reasons.length === 0 ? "<p>无阻断原因。</p>" : preview.reasons.map(reasonHtml).join("")}
    </section>
    <section>
      <h2>模型建议</h2>
      ${proposalHtml(preview)}
    </section>
  </main>
</body>
</html>`;
}
