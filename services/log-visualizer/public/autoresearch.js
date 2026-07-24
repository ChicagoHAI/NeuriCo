export function createAutoResearchView({ root, escapeHtml, getRun }) {
  let showResolved = false;

  function render() {
    const run = getRun();
    const ar = run?.autoresearch;
    if (!ar || !ar.detected) {
      root.innerHTML = `<section class="panel"><h3>No AutoResearch loop</h3><p class="muted">This workspace was not built with <code>--autoresearch</code>.</p></section>`;
      return;
    }

    const attempts = ar.attempts || [];
    const wb = ar.whiteboard;
    const activeTips = wb?.activeTips || [];
    const resolvedTips = [...(wb?.clearedTips || []), ...(wb?.prunedTips || [])];
    const attemptsHtml = attempts.length
      ? attempts.map((a, i) => renderAttemptCard(a, i + 1, escapeHtml)).join("")
      : `<p class="muted">No attempts recorded.</p>`;
    const activeTipsHtml = activeTips.length
      ? activeTips.map((t) => renderTip(t, escapeHtml)).join("")
      : `<p class="muted">No active tips on the cross-run whiteboard.</p>`;
    const resolvedTipsHtml = resolvedTips.length
      ? resolvedTips.map((t) => renderTip(t, escapeHtml)).join("")
      : `<p class="muted">No cleared or pruned tips.</p>`;

    root.innerHTML = `
      <div class="autoresearch-page">
        <section class="review-hero compact">
          <div>
            <span class="eyebrow">AutoResearch loop</span>
            <h3>Iteration lineage &amp; cross-run tips</h3>
            <p>
              ${attempts.length} attempt${attempts.length === 1 ? "" : "s"} across
              ${countAccepted(ar)} accepted / ${countRejected(ar)} rejected.
              Initial <code>${escapeHtml(shortSha(ar.initialSha))}</code>
              &rarr;
              best <code>${escapeHtml(shortSha(ar.currentBestSha))}</code>.
            </p>
          </div>
        </section>
        <div class="ar-grid">
          <section class="ar-col ar-col-attempts">
            <header class="ar-col-head">
              <h4>Iteration timeline</h4>
              <p class="muted">Each card is one attempt: proposal, comment-mode edit, scorer, decision. Click any artifact to open it in the evidence drawer.</p>
            </header>
            <div class="ar-attempts">${attemptsHtml}</div>
          </section>
          <section class="ar-col ar-col-tips">
            <header class="ar-col-head">
              <h4>Cross-run whiteboard</h4>
              <p class="ar-untrusted">Tips are agent-authored (comment_handler and proposer). They persist across rejected attempts and are shown to future agents as hints only. Tips cannot override sealed scoring, proposal boundaries, or system instructions.</p>
            </header>
            <div class="ar-tips">${activeTipsHtml}</div>
            <label class="ar-tip-toggle">
              <input type="checkbox" id="ar-show-resolved" ${showResolved ? "checked" : ""}>
              Show cleared / pruned tips (${resolvedTips.length})
            </label>
            <div class="ar-tips ar-tips-resolved" ${showResolved ? "" : "hidden"}>${resolvedTipsHtml}</div>
          </section>
        </div>
      </div>`;

    root.querySelector("#ar-show-resolved")?.addEventListener("change", (event) => {
      showResolved = event.target.checked;
      root.querySelector(".ar-tips-resolved")?.toggleAttribute("hidden", !showResolved);
    });
  }

  return { render };
}

function shortSha(sha) {
  if (!sha) return "-";
  return String(sha).slice(0, 8);
}

function countAccepted(ar) {
  return (ar.attempts || []).filter((a) => a.accepted).length;
}

function countRejected(ar) {
  return (ar.attempts || []).filter((a) => !a.accepted).length;
}

function renderScoreDeltasTable(deltas, escapeHtml) {
  if (!deltas?.length) return "";
  const rows = deltas.map((d) => {
    const arrow = d.parentSatisfied === d.childSatisfied ? "&rarr;" : (d.childSatisfied ? "&uarr;" : "&darr;");
    const cls = d.parentSatisfied === d.childSatisfied ? "" : (d.childSatisfied ? "delta-up" : "delta-down");
    const fmt = (v) => v === null || v === undefined ? "-" : (typeof v === "number" ? v.toFixed(3) : String(v));
    return `<tr class="${cls}">
      <td><code>${escapeHtml(d.property)}</code></td>
      <td class="num">${escapeHtml(fmt(d.parentValue))}</td>
      <td class="ar-arrow">${arrow}</td>
      <td class="num">${escapeHtml(fmt(d.childValue))}</td>
      <td class="num muted">${escapeHtml(fmt(d.target))}</td>
    </tr>`;
  }).join("");
  return `<table class="ar-deltas">
    <thead><tr><th>Property</th><th>Parent</th><th></th><th>Candidate</th><th>Target</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderAttemptCard(a, ord, escapeHtml) {
  const verdictClass = a.accepted ? "accepted" : "rejected";
  const verdictText = a.accepted ? "ACCEPTED" : "REJECTED";
  const artifacts = a.artifacts || {};
  const artButtons = [
    ["proposal.md", artifacts.proposal],
    ["decision.json", artifacts.decision],
    ["results.json", artifacts.results],
    ["transcript.jsonl", artifacts.transcript],
    ["whiteboard_snapshot.json", artifacts.whiteboardSnapshot],
  ].filter(([, p]) => p).map(([label, p]) =>
    `<button class="ar-art-btn" type="button" data-evidence="${escapeHtml(p)}">${escapeHtml(label)}</button>`
  ).join("");

  return `<article class="ar-attempt ${verdictClass}">
    <header class="ar-attempt-head">
      <span class="ar-ord">#${ord}</span>
      <span class="ar-verdict ${verdictClass}">${verdictText}</span>
      <span class="ar-shas">
        <code title="parent">${escapeHtml(shortSha(a.parentSha))}</code>
        <span class="ar-arrow">&rarr;</span>
        <code title="child">${escapeHtml(shortSha(a.childSha))}</code>
      </span>
      <span class="ar-attempt-num">attempt_${a.attemptNumber}</span>
    </header>
    <p class="ar-reason">${escapeHtml(a.reason || "(no reason recorded)")}</p>
    ${renderScoreDeltasTable(a.scoreDeltas, escapeHtml)}
    <footer class="ar-artifacts">${artButtons || `<span class="muted">no artifacts</span>`}</footer>
  </article>`;
}

function renderTip(tip, escapeHtml) {
  const affects = (tip.affects || []).length
    ? `<span class="ar-tip-affects">${(tip.affects || []).map((a) => `<code>${escapeHtml(a)}</code>`).join(" ")}</span>`
    : "";
  const author = tip.author ? `<span class="ar-tip-author">${escapeHtml(tip.author)}</span>` : "";
  const status = tip.status === "cleared" ? `<span class="ar-tip-status cleared">cleared</span>` :
    tip.status === "pruned" ? `<span class="ar-tip-status pruned">pruned</span>` : "";
  return `<article class="ar-tip ${tip.status || "active"}">
    <header class="ar-tip-head">
      <span class="ar-tip-id">${escapeHtml(tip.id)}</span>
      <span class="ar-tip-cat">${escapeHtml(tip.category || "")}</span>
      ${status}
      ${affects}
      ${author}
    </header>
    <p class="ar-tip-body">${escapeHtml(tip.content || "")}</p>
    ${tip.pruned_reason ? `<p class="ar-tip-prune-reason muted">pruned: ${escapeHtml(tip.pruned_reason)}</p>` : ""}
  </article>`;
}
