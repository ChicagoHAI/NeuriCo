
(function () {
  console.log("[EventsTab] HARD-CANVAS version loaded 2026-06-30-1629");

  let panel = null;
  let button = null;
  let canonical = null;
  let currentLeft = 354;

  function esc(x) {
    return String(x ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c]));
  }

  function getRunId() {
    const p = new URLSearchParams(location.search);
    return p.get("runId") || "logit-lens-implicit-fbb4-codex";
  }

  function getUser() {
    const p = new URLSearchParams(location.search);
    return p.get("user") || "bella-demo";
  }

  function allEls() {
    return [...document.querySelectorAll("button, a, div, span")];
  }

  function findNavItem(name) {
    return allEls().find(el => {
      const text = (el.textContent || "").trim();
      const r = el.getBoundingClientRect();
      return text === name && r.left < 360 && r.top > 80 && r.width > 40 && r.height > 18;
    });
  }

  function computeLeft() {
    const items = ["Whiteboard", "Flow", "Decisions", "Search", "Events"]
      .map(findNavItem)
      .filter(Boolean)
      .map(el => el.getBoundingClientRect().right);

    currentLeft = Math.max(354, items.length ? Math.max(...items) + 22 : 354);
    return currentLeft;
  }

  function isRunPage() {
    return Boolean(
      findNavItem("Whiteboard") &&
      findNavItem("Flow") &&
      findNavItem("Decisions") &&
      findNavItem("Search")
    );
  }

  function setActive(active) {
    if (!button) return;

    if (active) {
      button.style.background = "#d9f0ef";
      button.style.color = "#064e4a";
      button.style.fontWeight = "700";
      button.style.borderRadius = "8px";
    } else {
      button.style.background = "";
      button.style.color = "";
      button.style.fontWeight = "";
    }
  }

  function hideEvents() {
    if (panel) panel.style.display = "none";
    setActive(false);
  }

  function ensurePanel() {
    if (panel) return panel;

    // Remove stale panels from older plugin versions.
    document.querySelectorAll("#events-tab-panel").forEach(x => x.remove());

    panel = document.createElement("div");
    panel.id = "events-tab-panel";
    panel.style.display = "none";
    panel.style.position = "fixed";
    panel.style.top = "0px";
    panel.style.right = "0px";
    panel.style.bottom = "0px";
    panel.style.left = `${computeLeft()}px`;
    panel.style.zIndex = "2147483000";
    panel.style.background = "#f8fafc";
    panel.style.overflow = "auto";
    panel.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    panel.style.borderLeft = "1px solid #e5e7eb";

    document.body.appendChild(panel);

    window.addEventListener("resize", () => {
      if (panel) panel.style.left = `${computeLeft()}px`;
    });

    return panel;
  }

  async function loadCanonical() {
    if (canonical) return canonical;

    const runId = getRunId();
    const res = await fetch(`/api/canonical-run?runId=${encodeURIComponent(runId)}`);

    if (!res.ok) throw new Error(await res.text());

    canonical = await res.json();
    return canonical;
  }

  async function saveAnnotation(eventId, eventIndex, act) {
    const res = await fetch("/api/annotations", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        runId: getRunId(),
        annotator: getUser(),
        annotationType: "canonical_event",
        eventId,
        eventIndex,
        labels: {
          should_update_user: act === "update" || act === "interrupt",
          interrupt_next_action: act === "interrupt",
          confidence: 3,
          annotator_rationale: `Demo label: ${act}`
        }
      })
    });

    const data = await res.json();
    alert(data.ok ? "Annotation saved" : "Save failed");
  }

  async function openEvents() {
    const p = ensurePanel();
    p.style.left = `${computeLeft()}px`;
    p.style.display = "block";
    setActive(true);

    p.innerHTML = '<div style="padding:32px;">Loading canonical events...</div>';

    try {
      const data = await loadCanonical();
      renderEvents(data);
    } catch (err) {
      p.innerHTML = `<pre style="padding:24px;color:red;">${esc(err.stack || err)}</pre>`;
    }
  }

  function renderEvents(data) {
    const events = data.events || [];
    const summary = data.summary || {};

    const phases = [...new Set(events.map(e => e.phase || "unknown"))].sort();
    const agents = [...new Set(events.map(e => e.agent || "unknown"))].sort();

    panel.innerHTML = `
      <style>
        #events-tab-panel * {
          box-sizing: border-box;
        }

        #events-tab-panel .page {
          min-height: 100%;
          padding: 36px 42px 54px;
        }

        #events-tab-panel .titleRow {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 20px;
          margin-bottom: 18px;
        }

        #events-tab-panel .header {
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 14px;
          padding: 22px 26px;
          margin-bottom: 18px;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }

        #events-tab-panel h1 {
          margin: 0;
          font-size: 32px;
          letter-spacing: -0.03em;
          color: #111827;
        }

        #events-tab-panel h2 {
          margin: 0 0 8px;
          font-size: 24px;
          letter-spacing: -0.02em;
          color: #111827;
        }

        #events-tab-panel .muted {
          color: #6b7280;
          font-size: 14px;
          line-height: 1.45;
        }

        #events-tab-panel .pill {
          display: inline-block;
          padding: 4px 10px;
          border-radius: 999px;
          background: #eef2ff;
          color: #3730a3;
          font-size: 12px;
          font-weight: 700;
          margin-right: 6px;
        }

        #events-tab-panel .filters {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
          align-items: center;
          margin-top: 14px;
        }

        #events-tab-panel select,
        #events-tab-panel input {
          height: 42px;
          padding: 8px 10px;
          border: 1px solid #d1d5db;
          border-radius: 9px;
          background: white;
          min-width: 180px;
          font-size: 14px;
        }

        #events-tab-panel input {
          min-width: 300px;
          flex: 1;
          max-width: 520px;
        }

        #events-tab-panel button {
          border: 1px solid #d1d5db;
          border-radius: 8px;
          background: white;
          padding: 6px 9px;
          cursor: pointer;
          margin: 0 4px 4px 0;
          font-size: 13px;
        }

        #events-tab-panel button.primary {
          height: 42px;
          background: #0f766e;
          border-color: #0f766e;
          color: white;
          font-weight: 700;
          padding: 0 18px;
        }

        #events-tab-panel .closeBtn {
          height: 38px;
          padding: 0 14px;
          border-radius: 999px;
        }

        #events-tab-panel .tableCard {
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 14px;
          overflow: hidden;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }

        #events-tab-panel .tableMeta {
          padding: 14px 18px;
          border-bottom: 1px solid #e5e7eb;
        }

        #events-tab-panel table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }

        #events-tab-panel th,
        #events-tab-panel td {
          border-bottom: 1px solid #eee;
          padding: 10px 12px;
          vertical-align: top;
        }

        #events-tab-panel th {
          background: #f3f4f6;
          text-align: left;
          position: sticky;
          top: 0;
          z-index: 2;
          color: #4b5563;
        }

        #events-tab-panel tr:hover {
          background: #f9fafb;
        }

        #events-tab-panel .summaryCell {
          max-width: 680px;
        }

        #events-tab-panel .preview {
          margin-top: 4px;
          color: #6b7280;
          line-height: 1.35;
        }
      </style>

      <div class="page">
        <div class="titleRow">
          <div>
            <div class="muted">Canonical data-layer trajectory</div>
            <h1>Events</h1>
          </div>
          <button class="closeBtn" id="evClose">Close Events</button>
        </div>

        <div class="header">
          <h2>All canonical trajectory events</h2>
          <p class="muted">
            This tab shows all canonical events from the data layer. Annotators can filter events and label whether the agent should inform or interrupt the user.
          </p>

          <p>
            <span class="pill">${esc(summary.eventCount || 0)} events</span>
            <span class="pill">${esc(summary.artifactCount || 0)} artifacts</span>
            <span class="pill">${esc(summary.annotationCandidateCount || 0)} candidates</span>
          </p>

          <div class="filters">
            <select id="evPhase">
              <option value="">All phases</option>
              ${phases.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("")}
            </select>

            <select id="evAgent">
              <option value="">All agents</option>
              ${agents.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}
            </select>

            <input id="evSearch" placeholder="Search events..." />
            <button id="evApply" class="primary">Apply</button>
          </div>
        </div>

        <div id="evTable" class="tableCard"></div>
      </div>
    `;

    panel.querySelector("#evClose").addEventListener("click", hideEvents);
    panel.querySelector("#evApply").addEventListener("click", () => renderTable(events));
    panel.querySelector("#evPhase").addEventListener("change", () => renderTable(events));
    panel.querySelector("#evAgent").addEventListener("change", () => renderTable(events));
    panel.querySelector("#evSearch").addEventListener("input", () => renderTable(events));

    renderTable(events);
  }

  function renderTable(events) {
    const phase = panel.querySelector("#evPhase").value;
    const agent = panel.querySelector("#evAgent").value;
    const q = panel.querySelector("#evSearch").value.toLowerCase();

    const rows = events.filter(e => {
      const text = `${e.eventIndex} ${e.phase} ${e.agent} ${e.eventType} ${e.summary} ${e.rawPreview}`.toLowerCase();
      return (!phase || e.phase === phase)
        && (!agent || e.agent === agent)
        && (!q || text.includes(q));
    });

    const box = panel.querySelector("#evTable");

    box.innerHTML = `
      <div class="tableMeta muted">
        <b>${rows.length}</b> matching events. Showing first 250 for browser performance.
      </div>

      <table>
        <thead>
          <tr>
            <th style="width: 60px;">#</th>
            <th style="width: 160px;">Phase</th>
            <th style="width: 140px;">Agent</th>
            <th style="width: 150px;">Type</th>
            <th>Summary / Preview</th>
            <th style="width: 230px;">Annotate</th>
          </tr>
        </thead>
        <tbody>
          ${rows.slice(0, 250).map(e => `
            <tr>
              <td>${esc(e.eventIndex)}</td>
              <td>${esc(e.phase)}</td>
              <td>${esc(e.agent)}</td>
              <td>${esc(e.eventType)}</td>
              <td class="summaryCell">
                <b>${esc(e.summary || "").slice(0, 180)}</b>
                <div class="preview">${esc(e.rawPreview || "").slice(0, 340)}</div>
              </td>
              <td>
                <button data-act="update" data-id="${esc(e.eventId)}" data-idx="${esc(e.eventIndex)}">inform user</button>
                <button data-act="interrupt" data-id="${esc(e.eventId)}" data-idx="${esc(e.eventIndex)}">interrupt</button>
                <button data-act="none" data-id="${esc(e.eventId)}" data-idx="${esc(e.eventIndex)}">no label</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    box.querySelectorAll("button[data-act]").forEach(btn => {
      btn.addEventListener("click", () => {
        saveAnnotation(btn.dataset.id, Number(btn.dataset.idx), btn.dataset.act);
      });
    });
  }

  function injectEventsButton() {
    if (!isRunPage()) return false;

    document.querySelectorAll("#events-sidebar-tab").forEach(x => x.remove());

    const search = findNavItem("Search");
    if (!search) return false;

    const btn = search.cloneNode(true);
    btn.id = "events-sidebar-tab";
    btn.textContent = "Events";
    btn.onclick = null;

    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await openEvents();
    });

    search.insertAdjacentElement("afterend", btn);
    button = btn;

    console.log("[EventsTab] injected after Search");
    return true;
  }

  // Hide Events when any native left nav item is clicked.
  document.addEventListener("pointerdown", function (e) {
    const path = e.composedPath ? e.composedPath() : [];
    for (const node of path) {
      if (!node || !node.getBoundingClientRect) continue;
      if (node.id === "events-sidebar-tab") return;

      const text = (node.textContent || "").trim();
      const r = node.getBoundingClientRect();

      if (["Whiteboard", "Flow", "Decisions", "Search"].includes(text) && r.left < 360) {
        hideEvents();
        return;
      }
    }
  }, true);

  function start() {
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (injectEventsButton() || tries > 80) clearInterval(timer);
    }, 250);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
