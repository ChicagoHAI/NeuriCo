(() => {
  "use strict";

  const app = document.querySelector("#app");
  const initialRoute = location.pathname === "/research" ? "research" : "conversation";
  const initialProvider = "claude";
  const state = {
    snapshot: null, route: initialRoute, view: "understanding", drawer: null,
    tab: "overview", composer: "", provider: initialProvider,
    notice: "", thinking: false, stale: "", selectedOption: "", requestFeedback: "",
    runPanel: false, snapshotSig: "", scrollToBottom: false,
    graphScroll: {}, drawerScroll: {}, sidebarCollapsed: false,
    conversationScroll: { top: 0, nearBottom: true, captured: false },
    runDraft: { iterations: 2, writePaper: true, paperStyle: "auto", github: false },
  };
  let refreshPromise = null;
  let refreshPending = false;
  let composerObserver = null;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const q = (tag, attrs = {}, children = []) => {
    const element = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (key === "class") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key.startsWith("on")) element[key] = value;
      else element.setAttribute(key, value);
    });
    [].concat(children).filter(Boolean).forEach((child) => element.append(child));
    return element;
  };
  const svg = (tag, attrs = {}, children = []) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (key === "class") element.setAttribute("class", value);
      else if (key === "text") element.textContent = value;
      else if (key.startsWith("on")) element[key] = value;
      else element.setAttribute(key, value);
    });
    [].concat(children).filter(Boolean).forEach((child) => element.append(child));
    return element;
  };
  const icon = (symbol, title, action, className = "") => q("button", { class: `icon-button ${className}`, title, "aria-label": title, onclick: action, text: symbol });
  const humanize = (value) => String(value || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const shortSha = (sha) => String(sha || "").slice(0, 7);
  function autoSizeTextarea(area) {
    const resize = () => {
      if (!area.isConnected) return;
      area.style.height = "auto";
      const maxHeight = Number.parseFloat(getComputedStyle(area).maxHeight);
      const height = Number.isFinite(maxHeight) ? Math.min(area.scrollHeight, maxHeight) : area.scrollHeight;
      area.style.height = `${height}px`;
      area.style.overflowY = area.scrollHeight > height ? "auto" : "hidden";
    };
    if (area.isConnected) resize();
    else requestAnimationFrame(resize);
  }
  const ideaById = (id) => state.snapshot?.ideas?.find((idea) => idea.idea_id === id);
  const requestDraftKey = (request) => `neurico-hitl-request:${request?.request_key || "none"}`;
  function loadRequestDraft(request) { try { return JSON.parse(sessionStorage.getItem(requestDraftKey(request)) || "{}"); } catch (_) { return {}; } }
  function saveRequestDraft(request, patch) { const draft = { ...loadRequestDraft(request), ...patch }; sessionStorage.setItem(requestDraftKey(request), JSON.stringify(draft)); }
  function clearRequestDraft(request) { sessionStorage.removeItem(requestDraftKey(request)); state.selectedOption = ""; state.requestFeedback = ""; }
  function captureGraphScroll() { const scroller = document.querySelector(".graph-scroll"); if (scroller) state.graphScroll[state.view] = { left: scroller.scrollLeft, top: scroller.scrollTop }; }
  function captureFocusedControl() {
    const element = document.activeElement;
    const key = element instanceof HTMLElement ? element.dataset.focusKey : "";
    if (!key) return null;
    let selectionStart = null; let selectionEnd = null; let selectionDirection = null;
    try {
      selectionStart = typeof element.selectionStart === "number" ? element.selectionStart : null;
      selectionEnd = typeof element.selectionEnd === "number" ? element.selectionEnd : null;
      selectionDirection = element.selectionDirection || null;
    } catch (_) {}
    return { key, selectionStart, selectionEnd, selectionDirection, scrollTop: element.scrollTop, scrollLeft: element.scrollLeft };
  }
  function restoreFocusedControl(snapshot) {
    if (!snapshot) return;
    const element = [...document.querySelectorAll("[data-focus-key]")].find((candidate) => candidate.dataset.focusKey === snapshot.key);
    if (!(element instanceof HTMLElement)) return;
    element.focus({ preventScroll: true });
    if (snapshot.selectionStart !== null && typeof element.setSelectionRange === "function") {
      try { element.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd, snapshot.selectionDirection); } catch (_) {}
    }
    element.scrollTop = snapshot.scrollTop || 0;
    element.scrollLeft = snapshot.scrollLeft || 0;
  }
  function captureDrawerScroll() {
    const panel = document.querySelector(".drawer[data-drawer-key]");
    if (panel?.dataset.drawerKey) state.drawerScroll[panel.dataset.drawerKey] = panel.scrollTop;
  }
  function drawerKey() {
    if (!state.drawer) return "";
    const { kind, source } = state.drawer;
    const id = kind === "idea" ? source.idea_id : kind === "whiteboard" ? source.id : source.node_sha;
    return `${kind}:${id || "unknown"}:${state.tab}`;
  }

  function captureConversationScroll() {
    if (state.route !== "conversation") return;
    state.conversationScroll = {
      top: window.scrollY,
      nearBottom: window.innerHeight + window.scrollY >= document.body.scrollHeight - 80,
      captured: true,
    };
  }

  function navigate(route) {
    const previousRoute = state.route;
    if (previousRoute === "conversation" && route !== "conversation") captureConversationScroll();
    state.route = route;
    state.drawer = null;
    state.runPanel = false;
    const path = route === "research" ? "/research" : "/";
    if (location.pathname !== path) history.pushState({}, "", path);
    render({ restoreConversation: route === "conversation" && previousRoute !== "conversation" });
  }

  function markdown(value) {
    const lines = String(value || "").replace(/\r/g, "").split("\n");
    const blocks = []; let paragraph = []; let list = []; let orderedList = []; let code = []; let fenced = false;
    const flushParagraph = () => { if (paragraph.length) { blocks.push(`<p>${paragraph.join("<br>")}</p>`); paragraph = []; } };
    const flushList = () => { if (list.length) { blocks.push(`<ul>${list.map((item) => `<li>${item}</li>`).join("")}</ul>`); list = []; } if (orderedList.length) { blocks.push(`<ol>${orderedList.map((item) => `<li>${item}</li>`).join("")}</ol>`); orderedList = []; } };
    const inline = (text) => esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
    lines.forEach((raw) => {
      if (raw.startsWith("```")) { if (fenced) { blocks.push(`<pre><code>${code.join("\n")}</code></pre>`); code = []; } fenced = !fenced; return; }
      if (fenced) { code.push(esc(raw)); return; }
      const heading = raw.match(/^(#{1,3})\s+(.*)$/);
      const item = raw.match(/^\s*[-*+]\s+(.*)$/);
      const numberedItem = raw.match(/^\s*\d+\.\s+(.*)$/);
      if (heading) { flushParagraph(); flushList(); const level = heading[1].length + 1; blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`); }
      else if (item) { flushParagraph(); if (orderedList.length) flushList(); list.push(inline(item[1])); }
      else if (numberedItem) { flushParagraph(); if (list.length) flushList(); orderedList.push(inline(numberedItem[1])); }
      else if (!raw.trim()) { flushParagraph(); flushList(); }
      else { flushList(); paragraph.push(inline(raw)); }
    });
    flushParagraph(); flushList();
    if (fenced) blocks.push(`<pre><code>${code.join("\n")}</code></pre>`);
    return blocks.join("");
  }
  function md(value, className = "") { const element = q("div", { class: `markdown ${className}` }); element.innerHTML = markdown(value); return element; }
  async function copy(text) { try { await navigator.clipboard.writeText(text); } catch (_) {} }

  function topbar() {
    const workspace = state.snapshot?.workspace || "NeuriCo workspace";
    const live = state.snapshot?.live || {};
    const runIsActive = Boolean(live.active);
    const runCanLaunch = Boolean(live.can_launch);
    const runActionTitle = state.snapshot?.autoresearch?.mode === "continue"
      ? "Continue AutoResearch"
      : "Start AutoResearch";
    const runControl = runIsActive
      ? q("button", { class: "icon-button toolbar-action run-active", title: live.title || "AutoResearch is running", "aria-label": live.title || "AutoResearch is running", disabled: "disabled", text: "■" })
      : runCanLaunch
        ? icon("▶", runActionTitle, () => { state.runPanel = !state.runPanel; render(); }, "toolbar-action")
        : null;
    return q("header", { class: "topbar" }, [
      q("div", { class: "brand" }, [q("span", { class: "workspace-mark", text: "▱" }), q("span", { class: "workspace-title", text: workspace }), q("span", { class: "page-label", text: state.route === "conversation" ? "Conversation" : "Research" })]),
      q("div", { class: "topbar-spacer" }),
      workspaceStatus(),
      q("span", { class: `connection ${state.stale ? "warning" : ""}`, text: state.stale ? "Workspace data unavailable" : "Connected" }),
      state.route === "conversation" ? runControl : null,
      icon(state.route === "conversation" ? "▦" : "←", state.route === "conversation" ? "Research views" : "Back to conversation", () => navigate(state.route === "conversation" ? "research" : "conversation"), "toolbar-action"),
    ]);
  }

  function focusPendingRequest() {
    if (state.route !== "conversation") navigate("conversation");
    requestAnimationFrame(() => document.querySelector(".resolution-controls")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  function formatElapsed(startedAt) {
    const started = Date.parse(String(startedAt || ""));
    if (!Number.isFinite(started)) return "";
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return hours > 0
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
      : `${minutes}:${String(remainder).padStart(2, "0")}`;
  }
  function updatePhaseTimer() {
    document.querySelectorAll("[data-phase-started-at]").forEach((element) => {
      element.textContent = formatElapsed(element.dataset.phaseStartedAt);
    });
  }
  function workspaceStatus() {
    const live = state.snapshot?.live;
    const stateName = live?.state || "unavailable";
    const title = live?.title || "Unavailable";
    const stage = live?.stage_label || "";
    const step = live?.phase_label || "";
    const label = live?.label || title;
    const tooltip = [live?.detail, live?.next_action].filter(Boolean).join(" ");
    const text = stage
      ? [q("span", { class: "workspace-state-stage", text: stage }), step ? q("span", { class: "workspace-state-step", text: step }) : null]
      : [q("span", { class: "workspace-state-stage", text: label })];
    const timer = live?.active && live?.phase_started_at
      ? q("span", { class: "workspace-state-time", "data-phase-started-at": live.phase_started_at, text: formatElapsed(live.phase_started_at) })
      : null;
    const content = [q("span", { class: "workspace-state-dot", "aria-hidden": "true" }), q("span", { class: "workspace-state-text" }, text), timer];
    const attrs = { class: `workspace-state ${stateName}`, title: tooltip || label, "aria-label": label, "aria-live": stateName === "review_needed" ? "assertive" : "polite" };
    return stateName === "review_needed"
      ? q("button", { ...attrs, onclick: focusPendingRequest, "aria-label": `${label}. Open review request.` }, content)
      : q("div", attrs, content);
  }

  function requestControls(request) {
    const draft = loadRequestDraft(request);
    const selectedOption = state.selectedOption || draft.selectedOption || "";
    const requestFeedback = state.requestFeedback || draft.requestFeedback || "";
    const controls = q("div", { class: "resolution-controls" });
    const options = q("div", { class: "resolution-options" });
    (request.options || []).forEach((option) => options.append(q("button", {
      class: `resolution-option ${selectedOption === option.id ? "selected" : ""}`,
      "aria-pressed": selectedOption === option.id ? "true" : "false",
      "data-focus-key": `request-option:${request.request_key}:${option.id}`,
      onclick: () => {
        state.selectedOption = option.id;
        saveRequestDraft(request, { selectedOption: option.id });
        render({ preserveScroll: true });
      },
    }, [q("span", { class: "option-mark", text: selectedOption === option.id ? "✓" : "" }), q("span", { text: option.text })])));
    const feedback = q("textarea", { class: "resolution-feedback", placeholder: "Add feedback", "data-focus-key": `request-feedback:${request.request_key}` });
    feedback.value = requestFeedback;
    autoSizeTextarea(feedback);
    feedback.oninput = () => {
      state.requestFeedback = feedback.value;
      saveRequestDraft(request, { requestFeedback: feedback.value });
      autoSizeTextarea(feedback);
    };
    const feedbackRow = q("div", { class: "resolution-feedback-row" }, [
      feedback,
      icon("↑", "Submit request reply", () => submitRequest(request, feedback.value), "send"),
    ]);
    controls.append(options, feedbackRow);
    return controls;
  }
  function message(record, request = null) {
    const human = record.speaker === "human";
    const article = q("article", { class: `message ${human ? "human" : "manager"}` });
    article.append(human ? q("div", { class: "bubble", text: record.content }) : md(record.content, "bubble"));
    if (request) article.append(requestControls(request));
    article.append(icon("⧉", "Copy message", () => copy(record.content), "message-copy"));
    return article;
  }
  function openNotificationIdea(ideaId) {
    const idea = ideaById(ideaId);
    if (!idea) return;
    state.route = "research";
    state.view = "ideas";
    state.drawer = { kind: "idea", source: idea };
    state.tab = "overview";
    state.runPanel = false;
    if (location.pathname !== "/research") history.pushState({}, "", "/research");
    render({ preserveScroll: true });
  }
  function systemNotification(notification) {
    const row = q("aside", {
      class: `system-event ${notification.kind || "phase"} tone-${notification.tone || "neutral"}`,
      "aria-label": `${notification.title || "Research update"}. ${notification.summary || ""}`,
    });
    const heading = q("div", { class: "system-event-heading" }, [
      q("span", { class: "system-event-dot", "aria-hidden": "true" }),
      q("strong", { class: "system-event-title", text: notification.title || "Research update" }),
    ]);
    if (notification.idea_id) {
      heading.append(q("button", {
        class: "system-event-idea",
        text: notification.idea_id,
        title: `Open ${notification.idea_id}`,
        onclick: () => openNotificationIdea(notification.idea_id),
      }));
    }
    row.append(heading);
    if (notification.summary) row.append(q("p", { class: "system-event-summary", text: notification.summary }));
    return row;
  }
  function visibleConversation(records) {
    return (records || []).filter((record) => {
      const text = String(record.content || "").trim();
      return text && text.toLowerCase() !== "null";
    });
  }
  function conversationTimeline() {
    const messages = visibleConversation(state.snapshot?.conversation).map((record, index) => ({
      kind: "message", record, timestamp: String(record.created_at || ""), order: index,
    }));
    const notifications = (state.snapshot?.notifications || []).map((notification, index) => ({
      kind: "notification", notification, timestamp: String(notification.created_at || ""), order: messages.length + index,
    }));
    return [...messages, ...notifications].sort((left, right) => {
      if (!left.timestamp && !right.timestamp) return left.order - right.order;
      if (!left.timestamp) return -1;
      if (!right.timestamp) return 1;
      return left.timestamp.localeCompare(right.timestamp) || left.order - right.order;
    });
  }
  function queueView() {
    const queue = state.snapshot?.inbox?.queue || [];
    if (!queue.length) return null;
    const list = q("div", { class: "queue" });
    queue.forEach((item) => {
      const input = q("input", { class: "queue-editor", value: item.text, readonly: "readonly" });
      list.append(q("div", { class: "queue-row" }, [input, icon("✎", "Edit queued message", () => editQueued(item), "small-icon"), icon("×", "Remove queued message", () => removeQueued(item.id), "small-icon")]));
    });
    return list;
  }
  function composer() {
    const context = state.snapshot?.context || {}; const percent = Math.max(0, Math.min(100, Number(context.percent) || 0));
    const area = q("textarea", { placeholder: "Message NeuriCo", "data-focus-key": "composer" }); area.value = state.composer; autoSizeTextarea(area); area.oninput = () => { state.composer = area.value; autoSizeTextarea(area); }; area.onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submitConversation(); } };
    const provider = q("select", { class: "provider", title: "Choose conversation model", "data-focus-key": "composer-provider" }); [["codex", "Codex"], ["claude", "Claude"]].forEach(([value, label]) => provider.append(q("option", { value, text: label }))); provider.value = state.provider; provider.onchange = () => { state.provider = provider.value; };
    const meter = q("span", { class: "meter" }, [q("span")]); meter.firstChild.style.width = `${Math.max(2, percent)}%`;
    const usedTokens = Number(context.used_tokens || 0);
    const limitTokens = Number(context.limit_tokens || 300000);
    const usage = `${usedTokens.toLocaleString()} / ${limitTokens.toLocaleString()} tokens`;
    const contextDetails = `${usage} used; ${(Math.max(0, limitTokens - usedTokens)).toLocaleString()} remaining`;
    const contextMeter = q("div", { class: "context-meter", title: contextDetails, tabindex: "0", "aria-label": `Conversation context: ${contextDetails}` }, [meter, q("span", { text: `${percent}% context` }), q("span", { class: "context-tooltip", text: contextDetails })]);
    return q("div", { class: "composer-wrap" }, [queueView(), q("div", { class: "composer" }, [area, q("div", { class: "composer-foot" }, [provider, contextMeter, icon("↑", state.thinking ? "Queue message" : "Send message", submitConversation, "send")])])]);
  }
  function runPanel() {
    if (!state.runPanel || state.snapshot?.live?.active) return null;
    const mode = state.snapshot?.autoresearch?.mode === "continue" ? "continue" : "fresh";
    const title = mode === "continue" ? "Continue AutoResearch" : "Fresh AutoResearch";
    const provider = q("select", { id: "run-provider", "data-focus-key": "run-provider" }); [["codex", "Codex"], ["claude", "Claude"]].forEach(([value, label]) => provider.append(q("option", { value, text: label }))); provider.value = state.provider; provider.onchange = () => { state.provider = provider.value; };
    const iterations = q("input", { id: "run-iterations", type: "number", min: "1", max: "100", value: state.runDraft.iterations, "data-focus-key": "run-iterations" }); iterations.oninput = () => { state.runDraft.iterations = iterations.value; };
    const paper = q("input", { id: "run-paper", type: "checkbox", "data-focus-key": "run-paper" }); paper.checked = state.runDraft.writePaper; paper.onchange = () => { state.runDraft.writePaper = paper.checked; };
    const github = q("input", { id: "run-github", type: "checkbox", "data-focus-key": "run-github" }); github.checked = state.runDraft.github; github.onchange = () => { state.runDraft.github = github.checked; };
    const style = q("select", { id: "run-style", "data-focus-key": "run-style" }); [["auto", "Automatic"], ["neurips", "NeurIPS"], ["icml", "ICML"], ["acl", "ACL"]].forEach(([value, label]) => style.append(q("option", { value, text: label }))); style.value = state.runDraft.paperStyle; style.onchange = () => { state.runDraft.paperStyle = style.value; };
    const row = (label, control) => q("label", { class: "run-row" }, [q("span", { text: label }), control]);
    return q("section", { class: "run-panel" }, [q("div", { class: "run-title" }, [q("h2", { text: title }), icon("×", "Close AutoResearch setup", () => { state.runPanel = false; render(); })]), row("Model", provider), row("Iterations", iterations), q("label", { class: "check-row" }, [paper, q("span", { text: "Write paper" })]), row("Style", style), q("label", { class: "check-row" }, [github, q("span", { text: "Publish to GitHub" })]), q("div", { class: "run-actions" }, [icon("▶", `Start ${title}`, () => launchRun({ provider: provider.value, iterations: Number(iterations.value), write_paper: paper.checked, paper_style: style.value, github: github.checked }), "run-start")])]);
  }
  function conversation() {
    const shell = q("main", { class: "conversation-shell" }); const thread = q("div", { class: "thread" }); const request = state.snapshot?.inbox?.pending_request; const requestId = String(request?.conversation_record_id || "");
    conversationTimeline().forEach((entry) => {
      if (entry.kind === "notification") {
        thread.append(systemNotification(entry.notification));
        return;
      }
      const record = entry.record;
      thread.append(message(record, requestId && String(record.record_id || record.id || "") === requestId ? request : null));
    });
    if (state.thinking) thread.append(q("div", { class: "thinking", text: "NeuriCo is thinking " }, [q("i"), q("i"), q("i")]));
    shell.append(thread); if (state.notice) shell.append(q("p", { class: "notice", text: state.notice }));
    return q("div", { class: `conversation-page ${state.runPanel ? "run-open" : ""}` }, [shell, runPanel(), composer()]);
  }

  function observeComposerSpace() {
    composerObserver?.disconnect();
    const page = document.querySelector(".conversation-page");
    const wrap = document.querySelector(".composer-wrap");
    if (!page || !wrap) return;
    const update = () => {
      const wasAtEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 80;
      page.style.setProperty("--composer-space", `${Math.ceil(wrap.getBoundingClientRect().height) + 38}px`);
      if (wasAtEnd) requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight }));
    };
    composerObserver = new ResizeObserver(update);
    composerObserver.observe(wrap);
    update();
  }

  function sidebar() { const nav = [["understanding", "U", "Understanding"], ["ideas", "I", "Ideas"], ["nodes", "N", "Nodes"], ["whiteboard", "W", "Whiteboard"], ["activity", "A", "Activity"]]; return q("aside", { class: `research-sidebar ${state.sidebarCollapsed ? "collapsed" : ""}` }, [q("div", { class: "sidebar-head" }, [q("div", { class: "sidebar-top", text: "Research" }), q("button", { class: "sidebar-toggle", title: state.sidebarCollapsed ? "Expand research panel" : "Collapse research panel", "aria-label": state.sidebarCollapsed ? "Expand research panel" : "Collapse research panel", onclick: () => { state.sidebarCollapsed = !state.sidebarCollapsed; render({ preserveScroll: true }); }, text: state.sidebarCollapsed ? "→" : "←" })]), ...nav.map(([id, key, label]) => q("button", { class: `nav-item ${state.view === id ? "active" : ""}`, title: label, onclick: () => { state.view = id; state.drawer = null; render(); } }, [q("span", { class: "nav-key", text: key }), q("span", { class: "nav-label", text: label })]))]); }
  function title(main, label) { main.append(q("div", { class: "view-heading" }, [q("h1", { text: label })])); }
  function research() { const main = q("main", { class: "research-main" }); ({understanding: renderUnderstanding, ideas: renderIdeas, nodes: renderNodes, whiteboard: renderWhiteboard, activity: renderActivity}[state.view])(main); return q("div", { class: `research ${state.sidebarCollapsed ? "sidebar-collapsed" : ""}` }, [sidebar(), main]); }
  function renderUnderstanding(main) { title(main, "Research Understanding"); const r = state.snapshot?.research || {}; let rendered = false; [["Where the research stands", r.narrative], ["Current crux", r.crux]].forEach(([name, value]) => { if (value) { rendered = true; main.append(q("section", { class: "section" }, [q("h2", { text: name }), md(value)])); } }); if (r.hypotheses?.length) { rendered = true; main.append(q("section", { class: "section" }, [q("h2", { text: "Hypotheses" }), ...r.hypotheses.map((item) => md(typeof item === "string" ? item : item.statement || ""))])); } if (r.open_questions?.length) { rendered = true; main.append(q("section", { class: "section" }, [q("h2", { text: "Open questions" }), ...r.open_questions.map((item) => md(item))])); } if (!rendered) main.append(q("p", { class: "empty", text: "Research understanding has not been synthesized yet." })); }
  function graphLegend(items) {
    return q("div", { class: "graph-legend" }, items.map(([color, label]) => {
      const mark = label.startsWith("arrows:")
        ? q("i", { class: "graph-legend-arrow", text: "→" })
        : q("i", { class: "graph-legend-dot", style: `background:${color}` });
      return q("span", { class: "graph-legend-item" }, [mark, q("span", { text: label })]);
    }));
  }
  function drawGraph(main, entries, label, legendItems = []) {
    const seenEntries = new Set();
    entries = entries.filter((entry) => {
      if (seenEntries.has(entry.id)) return false;
      seenEntries.add(entry.id);
      return true;
    });
    if (!entries.length) { main.append(q("p", { class: "empty", text: `No ${label.toLowerCase()} records yet.` })); return; }
    const byId = new Map(entries.map((entry) => [entry.id, entry])); const layer = new Map(); const visiting = new Set();
    const depth = (entry) => { if (layer.has(entry.id)) return layer.get(entry.id); if (visiting.has(entry.id)) return 0; visiting.add(entry.id); const parents = (entry.parents || []).map((id) => byId.get(id)).filter(Boolean).map(depth); visiting.delete(entry.id); const value = parents.length ? Math.max(...parents) + 1 : 0; layer.set(entry.id, value); return value; };
    entries.forEach(depth); const columns = new Map(); entries.forEach((entry) => { const index = layer.get(entry.id) || 0; if (!columns.has(index)) columns.set(index, []); columns.get(index).push(entry); }); const maxColumn = Math.max(...[...columns.values()].map((values) => values.length)); const levels = Math.max(...layer.values()) + 1; const height = 620; const rowSlot = maxColumn > 1 ? (height - 132) / (maxColumn - 1) : height - 132; const radius = Math.max(18, Math.min(38, Math.floor(Math.min(48 - Math.sqrt(entries.length) * 3.5, rowSlot * .26)))); const topMargin = radius + 34; const bottomMargin = radius + 48; const columnGap = Math.max(170, radius * 5.2); const width = Math.max(1040, levels * columnGap + radius * 4);
    const graph = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": `${label} graph` });
    const defs = svg("defs");
    const marker = svg("marker", { id: "arrow", markerWidth: "8", markerHeight: "8", refX: "7", refY: "4", orient: "auto" }, [svg("path", { d: "M0,0 L8,4 L0,8z", fill: "#65756f" })]);
    defs.append(marker); graph.append(defs);
    const position = new Map(); columns.forEach((column, col) => column.forEach((entry, row) => position.set(entry.id, { x: radius * 2 + col * ((width - radius * 4) / Math.max(1, levels - 1)), y: topMargin + row * ((height - topMargin - bottomMargin) / Math.max(1, column.length - 1)) })));
    entries.forEach((entry) => (entry.parents || []).forEach((parent) => { const a = position.get(parent); const b = position.get(entry.id); if (a && b) { const startX = a.x + radius; const endX = b.x - radius - 4; const bend = Math.max(36, (endX - startX) * .42); graph.append(svg("path", { d: `M ${startX} ${a.y} C ${startX + bend} ${a.y}, ${endX - bend} ${b.y}, ${endX} ${b.y}`, fill: "none", stroke: "#65756f", "stroke-width": "2", "marker-end": "url(#arrow)" })); } }));
    entries.forEach((entry) => { const p = position.get(entry.id); const group = svg("g", { class: "graph-node", onclick: () => openDrawer(entry.kind, entry.source) }); group.append(svg("circle", { cx: p.x, cy: p.y, r: radius, fill: entry.color, stroke: entry.selected ? "#eef3f1" : "#c9d6d2", "stroke-width": entry.selected ? 4 : 2 }), svg("text", { x: p.x, y: p.y + 5, "text-anchor": "middle", text: entry.label }), svg("text", { class: "graph-node-meta", x: p.x, y: p.y + radius + 21, "text-anchor": "middle", text: entry.meta || "" })); graph.append(group); }); const scroller = q("div", { class: "graph-scroll" }, [graph]); scroller.addEventListener("scroll", () => { state.graphScroll[state.view] = { left: scroller.scrollLeft, top: scroller.scrollTop }; }); const saved = state.graphScroll[state.view]; if (saved) requestAnimationFrame(() => { scroller.scrollLeft = saved.left || 0; scroller.scrollTop = saved.top || 0; }); const children = [scroller]; if (legendItems.length) children.push(graphLegend(legendItems)); main.append(q("div", { class: "graph" }, children));
  }
  function renderIdeas(main) { title(main, "Ideas"); const typeMark = { proposal: "P", decision: "D", evidence: "E" }; drawGraph(main, (state.snapshot?.ideas || []).map((idea) => ({ id: idea.idea_id, label: idea.idea_id, meta: `${typeMark[idea.idea_type] || "I"} ${idea.level || ""}`.trim(), parents: idea.premises || [], kind: "idea", source: idea, color: idea.level === "A" ? "#e88e7c" : idea.level === "B" ? "#e5b95e" : "#76cbb1" })), "Idea", [["#76cbb1", "C research"], ["#e5b95e", "B reviewed"], ["#e88e7c", "A human"], ["#65756f", "arrows: premise to idea"]]); }
  function renderNodes(main) {
    title(main, "Nodes");
    const attempts = state.snapshot?.attempts || [];
    const nodeState = (node) => node.selected ? "selected" : node.active ? "frontier" : "retained";
    const entries = (state.snapshot?.nodes || []).map((node) => ({
      id: `node:${node.node_sha}`,
      label: shortSha(node.node_sha),
      parents: node.parent_node_sha ? [`node:${node.parent_node_sha}`] : [],
      kind: "node",
      source: node,
      selected: node.selected,
      meta: nodeState(node),
      color: node.selected ? "#76cbb1" : node.active ? "#8eb9e9" : node.parent_node_sha ? "#71807b" : "#d8c679",
    }));
    // Accepted candidates are materialized as nodes. Rejected candidates remain attempts.
    attempts.filter((attempt) => !attempt.accepted).forEach((attempt) => entries.push({
      id: `attempt:${attempt.node_sha}`,
      label: shortSha(attempt.node_sha),
      parents: attempt.parent_node_sha ? [`node:${attempt.parent_node_sha}`] : [],
      kind: "attempt",
      source: attempt,
      meta: "rejected",
      color: "#e88e7c",
    }));
    drawGraph(main, entries, "Node", [["#76cbb1", "selected"], ["#8eb9e9", "frontier"], ["#71807b", "retained"], ["#e88e7c", "rejected attempt"]]);
  }
  function renderWhiteboard(main) { title(main, "Whiteboard"); const tips = state.snapshot?.whiteboard?.tips || []; if (!tips.length) { main.append(q("p", { class: "empty", text: "No cross-attempt notes recorded." })); return; } tips.forEach((tip) => main.append(q("section", { class: "section whiteboard-tip" }, [q("h2", { text: `${tip.id} ${tip.status || "active"} ${tip.category || "note"}` }), md(tip.content), ...(tip.affects?.length ? [q("div", { class: "artifact-inline", text: tip.affects.join(" · ") })] : [])]))); }
  function optionText(record) { const choice = String(record?.decision || "").trim(); const selected = (record?.options || []).find((option) => { const id = typeof option === "string" ? option : option.option_id; const text = typeof option === "string" ? option : option.text; return choice && (choice === id || choice === text); }); return typeof selected === "string" ? selected : selected?.text || ""; }
  function formatActivityTime(value) { const date = new Date(value); if (Number.isNaN(date.getTime())) return String(value || "").replace("T", " ").replace("Z", ""); return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date).replace(",", " at"); }
  function activityMeta(entry) { const r = entry.record || {}; if (entry.kind === "idea") return `${r.idea_id || ""} ${r.idea_type || "idea"} - Level ${r.level || "?"}`.trim(); if (entry.kind === "attempt") return `${shortSha(r.node_sha)} from ${shortSha(r.parent_node_sha)}`; if (entry.kind === "node") return `${shortSha(r.node_sha)}${r.selected ? " - selected" : r.active ? " - active" : ""}`; return `${r.id || "tip"} ${r.category || "note"}`; }
  function activitySummary(entry) { const r = entry.record || {}; if (entry.kind === "idea") { if (r.idea_type === "decision") return optionText(r) || r.decision_needed || r.context || "Decision recorded."; return r.evidence || r.proposal || r.context || "Finalized idea."; } return entry.kind === "attempt" ? r.reason_for_acceptance || r.reason_for_rejection || r.proposal_idea_id || "AutoResearch attempt." : entry.kind === "node" ? r.reason_for_acceptance || "Frontier node retained." : r.content || "Whiteboard update."; }
  function activityTitle(entry) { const r = entry.record || {}; return entry.kind === "attempt" ? `${r.accepted ? "Accepted" : "Rejected"} ${r.proposal_type || "research"}` : entry.kind === "node" ? "Frontier node retained" : entry.kind === "whiteboard" ? "Whiteboard updated" : `${humanize(r.idea_type || "idea")} recorded`; }
  function renderActivity(main) { title(main, "Research activity"); const list = q("div", { class: "activity timeline" }); (state.snapshot?.activity || []).forEach((entry) => list.append(q("button", { class: "activity-row", onclick: () => openDrawer(entry.kind === "whiteboard" ? "whiteboard" : entry.kind, entry.record) }, [q("time", { class: "activity-time", text: formatActivityTime(entry.timestamp) }), q("span", { class: "activity-marker", "aria-hidden": "true" }), q("div", { class: "activity-content" }, [q("div", { class: "activity-title", text: activityTitle(entry) }), q("div", { class: "activity-meta", text: activityMeta(entry) }), q("div", { class: "activity-summary", text: activitySummary(entry) })])]))); main.append(list); }

  function openDrawer(kind, source) { captureGraphScroll(); state.drawer = { kind, source }; state.tab = "overview"; render({ preserveScroll: true }); }
  function detail(label, value) { return q("section", { class: "detail-section" }, [q("h2", { text: label }), value instanceof HTMLElement ? value : md(value)]); }
  function tabs(drawer, values) { drawer.append(q("div", { class: "tabbar" }, values.map((value) => q("button", { class: `tab ${state.tab === value ? "active" : ""}`, text: humanize(value), onclick: () => { state.tab = value; render(); } })))); }
  function links(ids) { const row = q("div", { class: "link-row" }); ids.forEach((id) => row.append(q("button", { class: "idea-link", text: id, onclick: () => { const idea = ideaById(id); if (idea) openDrawer("idea", idea); } }))); return row; }
  function artifactList(items) { return q("div", { class: "artifact-list" }, (items || []).map((item) => q("div", { class: "artifact-item" }, [q("code", { class: "artifact-path", text: item.path || String(item) }), item.description ? q("span", { class: "artifact-desc", text: item.description }) : null]))); }
  function renderIdeaDrawer(drawer, idea) { const source = String(idea.actor || "").toLowerCase() === "human" ? "Human" : "NeuriCo"; const verb = idea.idea_type === "decision" ? "Resolved" : "Recorded"; drawer.append(q("h1", { text: `${idea.idea_id} · ${idea.level || "?"} ${idea.idea_type}` }), q("p", { class: "detail-meta", text: `${verb} by ${source}.` })); const selectedDecision = idea.idea_type === "decision" ? optionText(idea) || idea.decision : ""; const content = idea.idea_type === "decision" ? selectedDecision || idea.decision_needed || idea.context || "" : idea.idea_type === "proposal" ? displayProposal(idea.proposal || idea.context) : idea.evidence || idea.proposal || idea.context || ""; drawer.append(detail(idea.idea_type === "decision" ? "Decision" : "Content", content)); if (idea.idea_type === "decision" && idea.decision_needed && content !== idea.decision_needed) drawer.append(detail("Question", idea.decision_needed)); if (idea.context && content !== idea.context) drawer.append(detail("Context", idea.context)); if (idea.options?.length) { const options = q("div", { class: "option-list" }); idea.options.forEach((option) => { const text = typeof option === "string" ? option : option.text || option.option_id || ""; const id = typeof option === "string" ? option : option.option_id; options.append(q("div", { class: `option-card ${idea.decision === id || idea.decision === text ? "selected" : ""}`, text })); }); drawer.append(detail("Options", options)); } if (idea.premises?.length) drawer.append(detail("Premises", links(idea.premises))); if (idea.related_artifacts?.length) drawer.append(detail("Artifacts", artifactList(idea.related_artifacts))); }
  function scoreRows(score) { const root = score?.results || score?.scorer_result?.results || score || {}; if (root.properties && typeof root.properties === "object") return Object.entries(root.properties).map(([metric, value]) => ({ metric, ...(value || {}) })); if (Array.isArray(root.metrics)) return root.metrics; return Object.entries(root).filter(([, value]) => value && typeof value === "object" && !Array.isArray(value)).map(([metric, value]) => ({ metric, ...value })); }
  function scoreTable(score) { const rows = scoreRows(score); if (!rows.length) return md("No structured objective score is available."); const table = q("table", { class: "score-table" }); table.append(q("thead", {}, [q("tr", {}, ["Metric", "Value", "Target", "Direction", "Result"].map((name) => q("th", { text: name })))])); const body = q("tbody"); rows.forEach((row) => { const result = row.result ?? row.passed ?? row.satisfied ?? row.status ?? ""; const pass = result === true || ["pass", "passed", "met", "true"].includes(String(result).toLowerCase()); const fail = result === false || ["fail", "failed", "not met", "false"].includes(String(result).toLowerCase()); body.append(q("tr", {}, [q("td", { text: row.metric || row.name || "metric" }), q("td", { text: String(row.value ?? row.score ?? row.actual ?? "") }), q("td", { text: String(row.target ?? row.threshold ?? "") }), q("td", { text: String(row.direction || "") }), q("td", { class: pass ? "score-good" : fail ? "score-bad" : "", text: typeof result === "boolean" ? (result ? "Met" : "Not met") : String(result) })])); }); table.append(body); return table; }
  function displayPlan(plan) { return String(plan || "").replace(/^\s*#?\s*EXPERIMENT RUNNER PLAN(?:\s*(?::|[—-])\s*[^\n]*)?\s*\n+/i, "").trim() || "No saved plan."; }
  function displayProposal(proposal) { return String(proposal || "").replace(/^\s*#?\s*AUTORESEARCH PROPOSAL\s*\n+/i, "").trim() || "Proposal record unavailable."; }
  function renderNodeDrawer(drawer, item, attempt) { const accepted = attempt ? item.accepted : true; drawer.append(q("h1", { text: attempt ? `${accepted ? "Accepted" : "Rejected"} ${item.proposal_type || "research"}` : item.selected ? "Selected research node" : "Research node" }), q("p", { class: "detail-meta", text: attempt ? `Candidate ${shortSha(item.node_sha)} from ${shortSha(item.parent_node_sha)}` : `${item.active ? "Active frontier" : "Retained"} · ${shortSha(item.node_sha)}${item.parent_node_sha ? ` · from ${shortSha(item.parent_node_sha)}` : ""}` })); tabs(drawer, attempt ? ["overview", "proposal", "score"] : ["overview", "plan", "score"]); if (state.tab === "overview") { const reason = item.reason_for_acceptance || item.reason_for_rejection; if (reason) drawer.append(detail(item.accepted === false ? "Reason for rejection" : "Reason for acceptance", reason)); if (attempt && item.proposal_idea_id) drawer.append(detail("Proposal", links([item.proposal_idea_id]))); if (!attempt) { const attempts = (state.snapshot?.attempts || []).filter((a) => a.parent_node_sha === item.node_sha); if (attempts.length) drawer.append(detail("Attempts from this node", q("div", { class: "attempt-list" }, attempts.map((a) => q("button", { class: "attempt-link", text: `${a.accepted ? "Accepted" : "Rejected"} ${a.proposal_type || "research"}${a.proposal_idea_id ? ` · ${a.proposal_idea_id}` : ""}`, onclick: () => openDrawer("attempt", a) }))))); } } else if (state.tab === "plan") drawer.append(detail("Experiment plan", displayPlan(item.plan))); else if (state.tab === "proposal") { const proposal = ideaById(item.proposal_idea_id); drawer.append(detail("Proposal", displayProposal(proposal?.proposal || proposal?.content))); } else drawer.append(detail("Objective score", scoreTable(item.objective_score))); }
  function renderWhiteboardDrawer(drawer, tip) { drawer.append(q("h1", { text: `${tip.id} ${tip.category || "note"}` }), q("p", { class: "detail-meta", text: tip.status || "active" }), detail("Note", tip.content)); if (tip.affects?.length) drawer.append(detail("Artifacts", artifactList(tip.affects))); }
  function drawer() { if (!state.drawer) return []; const shade = q("div", { class: "drawer-shade", onclick: () => { state.drawer = null; render(); } }); const panel = q("aside", { class: "drawer", "data-drawer-key": drawerKey() }); panel.append(icon("×", "Close details", () => { state.drawer = null; render(); }, "drawer-close")); const { kind, source } = state.drawer; if (kind === "idea") renderIdeaDrawer(panel, source); else if (kind === "whiteboard") renderWhiteboardDrawer(panel, source); else renderNodeDrawer(panel, source, kind === "attempt"); return [shade, panel]; }

  async function post(path, payload) { const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Could not submit."); return data; }
  async function submitConversation() { const text = state.composer.trim(); if (!text) return; const queueWasIdle = !state.thinking && !(state.snapshot?.inbox?.queue || []).length; state.composer = ""; state.notice = ""; state.scrollToBottom = true; render(); try { await post("/input", { text, input_kind: "conversation", provider: state.provider, client_turn_id: crypto.randomUUID() }); if (queueWasIdle) setTimeout(refresh, 650); else await refresh(); } catch (error) { state.notice = error.message; render(); } }
  async function submitRequest(request, feedback) { const draft = loadRequestDraft(request); const selectedOption = state.selectedOption || draft.selectedOption || ""; const text = String(feedback || draft.requestFeedback || "").trim(); if (!selectedOption && !text) { state.notice = "Choose an option or add feedback before submitting."; render(); return; } try { await post("/input", { text, input_kind: "resolution_reply", request_key: request.request_key, option_id: selectedOption, provider: state.provider, client_turn_id: crypto.randomUUID() }); clearRequestDraft(request); await refresh(); } catch (error) { state.notice = error.message; render(); } }
  async function removeQueued(id) { try { await post("/api/queue", { action: "remove", id }); await refresh(); } catch (error) { state.notice = error.message; render(); } }
  async function editQueued(item) {
    try {
      await post("/api/queue", { action: "remove", id: item.id });
      state.composer = String(item.text || "");
      state.notice = "";
      await refresh();
      requestAnimationFrame(() => {
        const area = document.querySelector('textarea[data-focus-key="composer"]');
        if (!(area instanceof HTMLTextAreaElement)) return;
        area.focus();
        area.setSelectionRange(area.value.length, area.value.length);
        autoSizeTextarea(area);
      });
    } catch (error) { state.notice = error.message; render(); }
  }
  async function cancelTurn() { state.notice = "Cancellation is not available yet."; render(); }
  async function launchRun(payload) { try { await post("/api/run", payload); state.runPanel = false; state.notice = ""; await refresh(); } catch (error) { state.notice = error.message; render(); } }
  function render(options = {}) {
    captureGraphScroll();
    captureDrawerScroll();
    const focusedControl = captureFocusedControl();
    const preserveScroll = Boolean(options.preserveScroll);
    const restoreConversation = Boolean(options.restoreConversation);
    const previousY = window.scrollY;
    const wasNearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 80;
    document.querySelectorAll(".drawer-shade,.drawer").forEach((element) => element.remove());
    app.replaceChildren(topbar(), state.route === "conversation" ? conversation() : research());
    if (state.route === "conversation") observeComposerSpace();
    else composerObserver?.disconnect();
    drawer().forEach((element) => document.body.append(element));
    const activeDrawer = document.querySelector(".drawer[data-drawer-key]");
    if (activeDrawer?.dataset.drawerKey && Object.prototype.hasOwnProperty.call(state.drawerScroll, activeDrawer.dataset.drawerKey)) {
      activeDrawer.scrollTop = state.drawerScroll[activeDrawer.dataset.drawerKey];
    }
    if (restoreConversation && state.conversationScroll.captured) {
      window.scrollTo({ top: state.conversationScroll.nearBottom ? document.body.scrollHeight : state.conversationScroll.top });
    } else if (state.scrollToBottom || (preserveScroll && state.route === "conversation" && wasNearBottom)) {
      window.scrollTo({ top: document.body.scrollHeight });
      state.scrollToBottom = false;
    } else if (preserveScroll) {
      window.scrollTo({ top: previousY });
    }
    restoreFocusedControl(focusedControl);
    updatePhaseTimer();
  }
  window.addEventListener("popstate", () => {
    const previousRoute = state.route;
    const nextRoute = location.pathname === "/research" ? "research" : "conversation";
    if (previousRoute === "conversation" && nextRoute !== "conversation") captureConversationScroll();
    state.route = nextRoute;
    state.drawer = null;
    state.runPanel = false;
    render({ restoreConversation: nextRoute === "conversation" && previousRoute !== "conversation" });
  });
  async function drainRefreshes() {
    while (refreshPending) {
      refreshPending = false;
      let result;
      try {
        const response = await fetch("/api/snapshot", { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Workspace data unavailable.");
        result = { data, signature: JSON.stringify(data), error: "" };
      } catch (error) {
        result = { data: null, signature: "", error: error.message };
      }
      if (refreshPending) continue;
      const changed = result.error
        ? state.stale !== result.error
        : result.signature !== state.snapshotSig || Boolean(state.stale);
      if (result.error) {
        state.stale = result.error;
      } else {
        state.snapshot = result.data;
        state.snapshotSig = result.signature;
        state.stale = "";
      }
      if (changed) render({ preserveScroll: true });
    }
  }
  function refresh() {
    refreshPending = true;
    if (!refreshPromise) {
      refreshPromise = drainRefreshes().finally(() => { refreshPromise = null; });
    }
    return refreshPromise;
  }
  const events = new EventSource("/stream"); events.addEventListener("status", (event) => { try { const thinking = Boolean(JSON.parse(event.data).thinking); if (state.thinking !== thinking) { state.thinking = thinking; render({ preserveScroll: true }); } } catch (_) {} }); ["message", "refresh", "workspace_changed", "resolution_cleared"].forEach((name) => events.addEventListener(name, refresh)); setInterval(refresh, 5000); setInterval(updatePhaseTimer, 1000); refresh();
})();
