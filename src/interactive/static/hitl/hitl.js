(() => {
  "use strict";

  const app = document.querySelector("#app");
  const initialRoute = location.pathname === "/research" ? "research" : "conversation";
  const initialProvider = "claude";
  const initialIdeaId = new URLSearchParams(location.search).get("idea") || "";
  const initialPortalSidebarCollapsed = localStorage.getItem("neurico-hitl-ideas-collapsed") === "1";
  const state = {
    snapshot: null, route: initialRoute, view: "understanding", drawer: null,
    tab: "overview", provider: initialProvider, providerTouched: false,
    thinking: false, stale: "",
    runPanel: false, snapshotSig: "", scrollToBottom: false,
    graphScroll: {}, drawerScroll: {}, sidebarCollapsed: false,
    conversationScroll: { top: 0, nearBottom: true, captured: false },
    managerStatusSeq: -1,
    runDraft: { iterations: 2, writePaper: true, paperStyle: "auto", github: false },
    portal: null, ideas: [], selectedIdeaId: initialIdeaId, catalogBusy: false,
    creatingIdea: false, ideaSchema: null, ideaDraft: {}, ideaSubmitError: "",
    renamingIdeaId: "", draggedIdeaId: "",
    portalSidebarCollapsed: initialPortalSidebarCollapsed,
  };
  let refreshPromise = null;
  let refreshPending = false;
  let composerObserver = null;
  let events = null;
  let workspaceGeneration = 0;
  const workspaceTransient = new Map();
  function workspaceKey(ideaId = state.selectedIdeaId, portal = state.portal) {
    return portal ? `idea:${String(ideaId || "")}` : "workspace";
  }
  function transientFor(key = workspaceKey()) {
    if (!workspaceTransient.has(key)) workspaceTransient.set(key, { composer: "", notice: "", selectedOption: "", requestFeedback: "" });
    return workspaceTransient.get(key);
  }
  function workspaceOperation(suffix) {
    const ideaId = state.selectedIdeaId;
    const portal = Boolean(state.portal);
    return {
      ideaId,
      key: workspaceKey(ideaId, portal),
      generation: workspaceGeneration,
      path: workspaceApi(suffix, ideaId, portal),
    };
  }
  function operationIsCurrent(operation) {
    return operation.generation === workspaceGeneration && operation.key === workspaceKey();
  }
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
  function applyManagerStatus(status) {
    if (!status || typeof status !== "object") return false;
    const seq = Number(status?.seq);
    if (Number.isFinite(seq) && seq < state.managerStatusSeq) return false;
    if (Number.isFinite(seq)) state.managerStatusSeq = seq;
    const thinking = Boolean(status?.thinking);
    if (state.thinking === thinking) return false;
    state.thinking = thinking;
    return true;
  }
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
  const requestDraftKey = (request, key = workspaceKey()) => `neurico-hitl-request:${key}:${request?.request_key || "none"}`;
  function loadRequestDraft(request, key = workspaceKey()) { try { return JSON.parse(sessionStorage.getItem(requestDraftKey(request, key)) || "{}"); } catch (_) { return {}; } }
  function saveRequestDraft(request, patch, key = workspaceKey()) { const draft = { ...loadRequestDraft(request, key), ...patch }; sessionStorage.setItem(requestDraftKey(request, key), JSON.stringify(draft)); }
  function clearRequestDraft(request, key = workspaceKey()) { sessionStorage.removeItem(requestDraftKey(request, key)); const transient = transientFor(key); transient.selectedOption = ""; transient.requestFeedback = ""; }
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
    const id = kind === "idea" || kind === "submitted_idea" ? source.idea_id : kind === "whiteboard" ? source.id : source.node_sha;
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
    const next = new URL(location.href);
    next.pathname = path;
    if (state.portal && state.selectedIdeaId) next.searchParams.set("idea", state.selectedIdeaId);
    if (location.pathname !== path) history.pushState({}, "", `${next.pathname}${next.search}`);
    render({ restoreConversation: route === "conversation" && previousRoute !== "conversation" });
  }

  const encodedIdeaId = (ideaId = state.selectedIdeaId) => encodeURIComponent(ideaId || "");
  function workspaceApi(suffix, ideaId = state.selectedIdeaId, portal = state.portal) {
    if (portal) return `/api/ideas/${encodedIdeaId(ideaId)}${suffix}`;
    if (suffix === "/snapshot") return "/api/snapshot";
    if (suffix === "/stream") return "/stream";
    if (suffix === "/queue") return "/api/queue";
    if (suffix === "/run") return "/api/run";
    return suffix;
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
  async function requestJson(path, payload, method = "POST") {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "Could not submit.");
      error.status = String(data.status || "");
      throw error;
    }
    return data;
  }

  const displayIdeaStatus = (idea) => idea.live?.label || humanize(idea.status || "submitted");
  function updateIdeaUrl(replace = false) {
    const next = new URL(location.href);
    if (state.selectedIdeaId) next.searchParams.set("idea", state.selectedIdeaId);
    else next.searchParams.delete("idea");
    const method = replace ? "replaceState" : "pushState";
    history[method]({}, "", `${next.pathname}${next.search}`);
  }
  function connectWorkspaceEvents() {
    events?.close();
    events = null;
    if (state.portal && !state.selectedIdeaId) return;
    const operation = workspaceOperation("/stream");
    events = new EventSource(operation.path);
    events.addEventListener("status", (event) => {
      if (!operationIsCurrent(operation)) return;
      try {
        if (applyManagerStatus(JSON.parse(event.data))) render({ preserveScroll: true });
      } catch (_) {}
    });
    ["message", "refresh", "workspace_changed", "resolution_cleared"].forEach((name) => events.addEventListener(name, async () => {
      if (!operationIsCurrent(operation)) return;
      await refresh();
    }));
  }
  async function loadCatalog(options = {}) {
    try {
      const response = await fetch("/api/ideas", { cache: "no-store" });
      if (response.status === 404) { state.portal = false; return false; }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Ideas unavailable.");
      state.portal = true;
      const priorLive = new Map(state.ideas.map((idea) => [idea.idea_id, idea.live || {}]));
      state.ideas = (Array.isArray(data.ideas) ? data.ideas : []).map((idea) => ({
        ...idea,
        live: Object.keys(idea.live || {}).length ? idea.live : priorLive.get(idea.idea_id) || {},
      }));
      const selectedExists = state.ideas.some((idea) => idea.idea_id === state.selectedIdeaId);
      if (!selectedExists) {
        workspaceGeneration += 1;
        state.selectedIdeaId = state.ideas[0]?.idea_id || "";
      }
      if (options.updateUrl) updateIdeaUrl(true);
      return true;
    } catch (error) {
      state.stale = error.message;
      return false;
    }
  }
  async function selectIdea(ideaId, replace = false) {
    const nextId = String(ideaId || "");
    if (!nextId) return;
    if (nextId === state.selectedIdeaId && !state.creatingIdea) return;
    captureConversationScroll();
    workspaceGeneration += 1;
    state.selectedIdeaId = nextId;
    state.snapshot = null;
    state.snapshotSig = "";
    state.thinking = false;
    state.managerStatusSeq = -1;
    state.stale = "";
    state.creatingIdea = false;
    state.drawer = null;
    updateIdeaUrl(replace);
    connectWorkspaceEvents();
    render();
    await refresh();
  }
  function ideaSidebar() {
    const sidebar = q("aside", { class: `portal-sidebar ${state.portalSidebarCollapsed ? "collapsed" : ""}` });
    sidebar.append(q("div", { class: "portal-sidebar-head" }, [
      q("strong", { text: "Ideas" }),
      q("div", { class: "portal-sidebar-actions" }, [
        icon("+", "New idea", async () => {
          state.creatingIdea = true;
          state.ideaSubmitError = "";
          if (!state.ideaSchema) await loadIdeaSchema();
          render();
        }, "portal-new"),
        icon("‹", "Hide ideas", () => {
          state.portalSidebarCollapsed = true;
          localStorage.setItem("neurico-hitl-ideas-collapsed", "1");
          render({ preserveScroll: true });
        }, "portal-collapse"),
      ]),
    ]));
    const list = q("div", { class: "portal-idea-list" });
    state.ideas.forEach((idea) => {
      const selected = idea.idea_id === state.selectedIdeaId && !state.creatingIdea;
      const dragDisabled = Boolean(state.renamingIdeaId);
      const row = q("div", {
        class: `portal-idea ${selected ? "selected" : ""} ${dragDisabled ? "drag-disabled" : ""}`,
        draggable: dragDisabled ? "false" : "true",
        ondragstart: (event) => {
          if (dragDisabled) { event.preventDefault(); return; }
          state.draggedIdeaId = idea.idea_id;
          event.dataTransfer.effectAllowed = "move";
        },
        ondragover: (event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; },
        ondrop: (event) => { event.preventDefault(); reorderIdeas(state.draggedIdeaId, idea.idea_id); },
        ondragend: () => { state.draggedIdeaId = ""; },
      });
      let content;
      if (state.renamingIdeaId === idea.idea_id) {
        content = q("div", { class: "portal-idea-select editing" });
        const input = q("input", { class: "portal-name-input", value: idea.display_name, maxlength: "160", "aria-label": "Idea name" });
        let finished = false;
        const finish = async () => {
          if (finished) return;
          finished = true;
          await renameIdea(idea.idea_id, input.value);
          state.renamingIdeaId = "";
          render();
        };
        input.onkeydown = (event) => {
          if (event.key === "Enter") { event.preventDefault(); finish(); }
          if (event.key === "Escape") { event.preventDefault(); finished = true; state.renamingIdeaId = ""; render(); }
        };
        input.onblur = finish;
        content.append(input);
        requestAnimationFrame(() => { input.focus(); input.select(); });
      } else {
        content = q("button", { class: "portal-idea-select", title: idea.title || idea.idea_id, onclick: () => selectIdea(idea.idea_id) });
        content.append(
          q("span", { class: "portal-idea-name", text: idea.display_name || idea.idea_id }),
          q("span", { class: "portal-idea-meta" }, [
            q("i", { class: `portal-status ${String(idea.live?.state || idea.status || "").toLowerCase()}` }),
            q("span", { text: displayIdeaStatus(idea) }),
          ]),
        );
      }
      row.append(
        q("span", { class: "portal-drag", title: "Reorder", text: "⠿" }),
        content,
        icon("▤", "View submitted idea", () => openSubmittedIdea(idea), "portal-view"),
        icon("✎", "Rename idea", () => { state.renamingIdeaId = idea.idea_id; render(); }, "portal-rename"),
      );
      list.append(row);
    });
    if (!state.ideas.length) list.append(q("p", { class: "portal-empty", text: "No ideas" }));
    sidebar.append(list);
    return sidebar;
  }
  async function openSubmittedIdea(idea) {
    try {
      if (!state.ideaSchema) state.ideaSchema = await fetchIdeaSchema();
      const response = await fetch(`/api/ideas/${encodeURIComponent(idea.idea_id)}/definition`, { cache: "no-store" });
      const definition = await response.json();
      if (!response.ok) throw new Error(definition.error || "Idea unavailable.");
      state.drawer = { kind: "submitted_idea", source: { ...idea, ...definition } };
      state.tab = "overview";
      render({ preserveScroll: true });
    } catch (error) { transientFor().notice = error.message; render({ preserveScroll: true }); }
  }
  async function renameIdea(ideaId, displayName) {
    try {
      await requestJson(`/api/ideas/${encodeURIComponent(ideaId)}/presentation`, { display_name: displayName }, "PATCH");
      await loadCatalog();
    } catch (error) { transientFor().notice = error.message; }
  }
  async function reorderIdeas(sourceId, targetId) {
    if (!sourceId || !targetId || sourceId === targetId) return;
    const order = state.ideas.map((idea) => idea.idea_id);
    const sourceIndex = order.indexOf(sourceId);
    const targetIndex = order.indexOf(targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    order.splice(targetIndex, 0, order.splice(sourceIndex, 1)[0]);
    const byId = new Map(state.ideas.map((idea) => [idea.idea_id, idea]));
    state.ideas = order.map((ideaId) => byId.get(ideaId));
    render({ preserveScroll: true });
    try { await requestJson("/api/ideas/order", { order }, "PUT"); }
    catch (error) { transientFor().notice = error.message; await loadCatalog(); render(); }
  }

  const sectionFields = [
    ["Idea", ["title", "domain", "hypothesis"]],
    ["Background", ["background"]],
    ["Method", ["methodology"]],
    ["Constraints", ["constraints"]],
    ["Outputs", ["expected_outputs"]],
    ["Evaluation", ["evaluation_criteria", "evaluation"]],
    ["Resources", ["local_resources"]],
    ["Metadata", ["metadata"]],
  ];
  const pathKey = (path) => path.join(".");
  function draftValue(path) {
    return path.reduce((value, key) => value == null ? undefined : value[key], state.ideaDraft);
  }
  function setDraftValue(path, value) {
    let current = state.ideaDraft;
    path.forEach((key, index) => {
      if (index === path.length - 1) current[key] = value;
      else {
        const arrayNext = typeof path[index + 1] === "number";
        if (current[key] == null || typeof current[key] !== "object") current[key] = arrayNext ? [] : {};
        current = current[key];
      }
    });
  }
  function emptyForSchema(schema) {
    if (schema?.type === "object") return {};
    if (schema?.type === "array") return [];
    if (schema?.type === "integer" || schema?.type === "number") return schema.default ?? "";
    if (schema?.type === "boolean") return Boolean(schema.default);
    return schema?.default ?? "";
  }
  function schemaItem(schema, current) {
    if (!schema?.oneOf) return schema || {};
    if (current && typeof current === "object" && current.path) return schema.oneOf.find((entry) => entry.properties?.path) || schema.oneOf[0];
    return schema.oneOf.find((entry) => entry.properties?.url) || schema.oneOf[0];
  }
  function fieldLabel(name) { return humanize(name).replace("Url", "URL"); }
  function arrayItemLabel(name) {
    const labels = {
      papers: "Paper", datasets: "Dataset", code_references: "Code reference",
      steps: "Step", baselines: "Baseline", metrics: "Metric",
      dependencies: "Dependency", expected_outputs: "Output",
      fields: "Field", evaluation_criteria: "Criterion", functions: "Function",
      objectives: "Objective", tags: "Tag", related_ideas: "Related idea",
    };
    if (labels[name]) return labels[name];
    const singular = name.endsWith("ies") ? `${name.slice(0, -3)}y` : name.endsWith("s") ? name.slice(0, -1) : name;
    return fieldLabel(singular || "Item");
  }
  function formField(name, schema, path, required = false) {
    const label = fieldLabel(name);
    const value = draftValue(path);
    if (schema.type === "object") {
      const body = q("div", { class: "idea-object" });
      Object.entries(schema.properties || {}).forEach(([childName, childSchema]) => body.append(formField(childName, childSchema, [...path, childName], (schema.required || []).includes(childName))));
      return q("fieldset", { class: "idea-fieldset" }, [q("legend", { text: label }), body]);
    }
    if (schema.type === "array") {
      const values = Array.isArray(value) ? value : [];
      const itemName = arrayItemLabel(name);
      const list = q("div", { class: "idea-array-list" });
      values.forEach((entry, index) => {
        const itemSchema = schemaItem(schema.items, entry);
        const item = q("div", { class: "idea-array-item" });
        item.append(q("div", { class: "idea-array-item-title", text: `${itemName} ${index + 1}` }));
        if (schema.items?.oneOf) {
          const variant = q("select", { class: "idea-variant", "aria-label": `${label} type` });
          schema.items.oneOf.forEach((option, optionIndex) => variant.append(q("option", { value: String(optionIndex), text: option.properties?.path ? "Local file" : "URL" })));
          variant.value = String(schema.items.oneOf.indexOf(itemSchema));
          variant.onchange = () => { setDraftValue([...path, index], emptyForSchema(schema.items.oneOf[Number(variant.value)])); render({ preserveScroll: true }); };
          item.append(variant);
        }
        if (itemSchema.type === "object") {
          Object.entries(itemSchema.properties || {}).forEach(([childName, childSchema]) => item.append(formField(childName, childSchema, [...path, index, childName], (itemSchema.required || []).includes(childName))));
        } else {
          item.append(formField(itemName, itemSchema, [...path, index], false));
        }
        item.append(icon("×", `Remove ${itemName}`, () => { const next = [...values]; next.splice(index, 1); setDraftValue(path, next); render({ preserveScroll: true }); }, "idea-remove"));
        list.append(item);
      });
      const add = q("button", { class: "idea-add", text: `+ ${itemName}`, onclick: () => { const next = [...values, emptyForSchema(schemaItem(schema.items, null))]; setDraftValue(path, next); render({ preserveScroll: true }); } });
      return q("div", { class: "idea-array" }, [list, add]);
    }
    const attrs = {
      class: "idea-control",
      "aria-label": label,
      "data-idea-path": pathKey(path),
      ...(required ? { required: "required" } : {}),
      ...(schema.minLength != null ? { minlength: String(schema.minLength) } : {}),
      ...(schema.maxLength != null ? { maxlength: String(schema.maxLength) } : {}),
      ...(schema.pattern ? { pattern: schema.pattern } : {}),
    };
    let control;
    if (schema.type === "boolean") {
      control = q("input", { ...attrs, type: "checkbox" });
      control.checked = Boolean(value);
      control.onchange = () => setDraftValue(path, control.checked);
      return q("label", { class: "idea-field idea-boolean" }, [control, q("span", { text: `${label}${required ? " *" : ""}` })]);
    } else if (name === "domain" && state.ideaSchema?.domains?.length) {
      control = q("select", attrs);
      control.append(q("option", { value: "", text: "Domain" }));
      state.ideaSchema.domains.forEach((domain) => control.append(q("option", { value: domain.id, text: domain.name })));
      control.value = value ?? "";
    } else if (schema.enum) {
      control = q("select", attrs);
      control.append(q("option", { value: "", text: label }));
      schema.enum.forEach((option) => control.append(q("option", { value: option, text: humanize(option) })));
      control.value = value ?? "";
    } else if (schema.type === "integer" || schema.type === "number") {
      control = q("input", { ...attrs, type: "number", min: schema.minimum ?? "", max: schema.maximum ?? "", step: schema.type === "integer" ? "1" : "any", placeholder: label, value: value ?? "" });
    } else if (["hypothesis", "description", "approach", "definition", "usage"].includes(name)) {
      control = q("textarea", { ...attrs, placeholder: label, rows: "3" }); control.value = value ?? "";
    } else {
      control = q("input", { ...attrs, type: schema.format === "uri" ? "url" : "text", placeholder: label, value: value ?? "" });
    }
    control.oninput = () => setDraftValue(path, schema.type === "integer" ? (control.value === "" ? "" : Number(control.value)) : schema.type === "number" ? (control.value === "" ? "" : Number(control.value)) : control.value);
    control.onchange = control.oninput;
    return q("label", { class: "idea-field" }, [q("span", { text: `${label}${required ? " *" : ""}` }), control]);
  }
  function hasIdeaContent(value) {
    if (value == null || value === "") return false;
    if (Array.isArray(value)) return value.some(hasIdeaContent);
    if (typeof value === "object") return Object.values(value).some(hasIdeaContent);
    return true;
  }
  function submittedScalar(name, schema, value) {
    let display = value;
    if (schema.type === "boolean") display = value ? "Yes" : "No";
    else if (name === "domain") {
      display = state.ideaSchema?.domains?.find((domain) => domain.id === value)?.name || value;
    } else if (schema.enum) display = humanize(value);
    const text = String(display ?? "");
    if (schema.format === "uri" && /^https?:\/\//i.test(text)) {
      return q("a", { class: "submitted-idea-value submitted-idea-link", href: text, target: "_blank", rel: "noreferrer", text });
    }
    return q("div", { class: "submitted-idea-value", text });
  }
  function submittedIdeaField(name, schema, value) {
    if (!hasIdeaContent(value)) return null;
    const label = fieldLabel(name);
    if (schema.type === "object") {
      const body = q("div", { class: "idea-object submitted-idea-object" });
      Object.entries(schema.properties || {}).forEach(([childName, childSchema]) => {
        const child = submittedIdeaField(childName, childSchema, value?.[childName]);
        if (child) body.append(child);
      });
      if (!body.childElementCount) return null;
      return q("fieldset", { class: "idea-fieldset submitted-idea-fieldset" }, [q("legend", { text: label }), body]);
    }
    if (schema.type === "array") {
      const values = Array.isArray(value) ? value : [];
      const itemName = arrayItemLabel(name);
      const list = q("div", { class: "idea-array-list" });
      values.forEach((entry, index) => {
        if (!hasIdeaContent(entry)) return;
        const itemSchema = schemaItem(schema.items, entry);
        const item = q("div", { class: "idea-array-item submitted-idea-array-item" }, [
          q("div", { class: "idea-array-item-title", text: `${itemName} ${index + 1}` }),
        ]);
        if (itemSchema.type === "object") {
          Object.entries(itemSchema.properties || {}).forEach(([childName, childSchema]) => {
            const child = submittedIdeaField(childName, childSchema, entry?.[childName]);
            if (child) item.append(child);
          });
        } else {
          item.append(submittedScalar(itemName, itemSchema, entry));
        }
        list.append(item);
      });
      if (!list.childElementCount) return null;
      return q("div", { class: "idea-array submitted-idea-array" }, [
        q("div", { class: "submitted-idea-group-label", text: label }),
        list,
      ]);
    }
    return q("div", { class: "idea-field submitted-idea-field" }, [
      q("span", { text: label }),
      submittedScalar(name, schema, value),
    ]);
  }
  function cleanIdeaValue(value) {
    if (Array.isArray(value)) return value.map(cleanIdeaValue).filter((entry) => !(entry === "" || entry == null || (Array.isArray(entry) && !entry.length) || (typeof entry === "object" && !Array.isArray(entry) && !Object.keys(entry).length)));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, cleanIdeaValue(entry)]).filter(([, entry]) => !(entry === "" || entry == null || (Array.isArray(entry) && !entry.length) || (typeof entry === "object" && !Array.isArray(entry) && !Object.keys(entry).length))));
    }
    return value;
  }
  async function fetchIdeaSchema() {
    const response = await fetch("/api/idea-schema", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Idea schema unavailable.");
    return data;
  }
  async function loadIdeaSchema() {
    try {
      state.ideaSchema = await fetchIdeaSchema();
      state.ideaDraft = {};
    } catch (error) { state.ideaSubmitError = error.message; }
  }
  async function submitIdea() {
    state.ideaSubmitError = "";
    const invalid = [...document.querySelectorAll(".idea-create .idea-control, .idea-create .idea-variant")]
      .find((control) => typeof control.checkValidity === "function" && !control.checkValidity());
    if (invalid) {
      invalid.reportValidity();
      return;
    }
    try {
      const result = await requestJson("/api/ideas", { idea: cleanIdeaValue(state.ideaDraft) }, "POST");
      await loadCatalog();
      state.creatingIdea = false;
      workspaceGeneration += 1;
      state.selectedIdeaId = result.idea_id;
      state.snapshot = null;
      state.snapshotSig = "";
      state.thinking = false;
      state.managerStatusSeq = -1;
      state.stale = "";
      updateIdeaUrl();
      connectWorkspaceEvents();
      render();
      await refresh();
    } catch (error) { state.ideaSubmitError = error.message; render({ preserveScroll: true }); }
  }
  function ideaCreationPage() {
    const main = q("main", { class: "idea-create" });
    main.append(q("header", { class: "idea-create-head" }, [q("h1", { text: "New idea" }), icon("×", "Close", () => { state.creatingIdea = false; render(); })]));
    if (!state.ideaSchema) {
      main.append(q("p", { class: "empty", text: state.ideaSubmitError || "Loading" }));
      return main;
    }
    const properties = state.ideaSchema.schema?.properties || {};
    const required = state.ideaSchema.schema?.required || [];
    sectionFields.forEach(([sectionName, names]) => {
      const visibleNames = names.filter((name) => properties[name] && Object.keys(properties[name].properties || { value: true }).length);
      if (!visibleNames.length) return;
      const section = q("section", { class: "idea-form-section" }, [q("h2", { text: sectionName })]);
      visibleNames.forEach((name) => section.append(formField(name, properties[name], [name], required.includes(name))));
      main.append(section);
    });
    if (state.ideaSubmitError) main.append(q("p", { class: "idea-form-error", text: state.ideaSubmitError }));
    main.append(q("div", { class: "idea-form-actions" }, [q("button", { class: "idea-cancel", text: "Cancel", onclick: () => { state.creatingIdea = false; render(); } }), q("button", { class: "idea-submit", text: "Submit idea", onclick: submitIdea })]));
    return main;
  }

  function topbar() {
    const selectedIdea = state.ideas.find((idea) => idea.idea_id === state.selectedIdeaId);
    const workspace = selectedIdea?.display_name || state.snapshot?.workspace || "NeuriCo workspace";
    const live = state.snapshot?.live || {};
    const runIsActive = Boolean(live.active);
    const runCanLaunch = Boolean(live.can_launch);
    const runActionTitle = state.snapshot?.autoresearch?.mode === "continue"
      ? "Continue AutoResearch"
      : "Start AutoResearch";
    const runControl = runIsActive
      ? q("button", {
          class: "icon-button toolbar-action run-active",
          title: live.state === "stopping" ? "Stopping AutoResearch" : "Stop AutoResearch",
          "aria-label": live.state === "stopping" ? "Stopping AutoResearch" : "Stop AutoResearch",
          ...(live.state === "stopping" ? { disabled: "disabled" } : { onclick: stopRun }),
          text: "■",
        })
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
    const transient = transientFor();
    const draft = loadRequestDraft(request);
    const selectedOption = transient.selectedOption || draft.selectedOption || "";
    const requestFeedback = transient.requestFeedback || draft.requestFeedback || "";
    const controls = q("div", { class: "resolution-controls" });
    const options = q("div", { class: "resolution-options" });
    (request.options || []).forEach((option) => options.append(q("button", {
      class: `resolution-option ${selectedOption === option.id ? "selected" : ""}`,
      "aria-pressed": selectedOption === option.id ? "true" : "false",
      "data-focus-key": `request-option:${request.request_key}:${option.id}`,
      onclick: () => {
        transient.selectedOption = option.id;
        saveRequestDraft(request, { selectedOption: option.id });
        render({ preserveScroll: true });
      },
    }, [q("span", { class: "option-mark", text: selectedOption === option.id ? "✓" : "" }), q("span", { text: option.text })])));
    const feedback = q("textarea", { class: "resolution-feedback", placeholder: "Add feedback", "data-focus-key": `request-feedback:${request.request_key}` });
    feedback.value = requestFeedback;
    autoSizeTextarea(feedback);
    feedback.oninput = () => {
      transient.requestFeedback = feedback.value;
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
    if (location.pathname !== "/research") {
      const next = new URL(location.href);
      next.pathname = "/research";
      history.pushState({}, "", `${next.pathname}${next.search}`);
    }
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
    const active = state.snapshot?.inbox?.active;
    const activeRecorded = active && messages.some(({ record }) => String(record.record_id || record.id || "") === String(active.id || ""));
    if (active && !activeRecorded) {
      messages.push({
        kind: "message",
        record: {
          record_id: active.id,
          speaker: "human",
          content: active.text,
          created_at: active.created_at,
          metadata: { client_turn_id: active.client_turn_id },
        },
        timestamp: active.created_at,
        order: messages.length,
      });
    }
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
    const transient = transientFor();
    const area = q("textarea", { placeholder: "Message NeuriCo", "data-focus-key": "composer" }); area.value = transient.composer; autoSizeTextarea(area); area.oninput = () => { transient.composer = area.value; autoSizeTextarea(area); }; area.onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submitConversation(); } };
    const providerLocked = Boolean(state.snapshot?.manager?.provider_locked);
    const providerTitle = providerLocked ? "The active run controls the manager model" : "Choose conversation model";
    const provider = q("select", { class: "provider", title: providerTitle, "aria-label": providerTitle, "data-focus-key": "composer-provider" }); [["codex", "Codex"], ["claude", "Claude"]].forEach(([value, label]) => provider.append(q("option", { value, text: label }))); provider.value = state.provider; provider.disabled = providerLocked; provider.onchange = () => { state.provider = provider.value; state.providerTouched = true; };
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
    const provider = q("select", { id: "run-provider", "data-focus-key": "run-provider" }); [["codex", "Codex"], ["claude", "Claude"]].forEach(([value, label]) => provider.append(q("option", { value, text: label }))); provider.value = state.provider; provider.onchange = () => { state.provider = provider.value; state.providerTouched = true; };
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
    const notice = transientFor().notice;
    shell.append(thread); if (notice) shell.append(q("p", { class: "notice", text: notice }));
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
  function renderSubmittedIdeaDrawer(drawer, record) {
    drawer.append(q("h1", { text: record.display_name || record.idea_id }), q("p", { class: "detail-meta", text: record.idea_id }));
    const idea = record.idea && typeof record.idea === "object" ? record.idea : {};
    const properties = state.ideaSchema?.schema?.properties || {};
    const sections = q("div", { class: "submitted-idea-sections" });
    sectionFields.forEach(([sectionName, names]) => {
      const fields = names.map((name) => properties[name] ? submittedIdeaField(name, properties[name], idea[name]) : null).filter(Boolean);
      if (!fields.length) return;
      sections.append(q("section", { class: "idea-form-section submitted-idea-section" }, [q("h2", { text: sectionName }), ...fields]));
    });
    drawer.append(sections.childElementCount ? sections : q("p", { class: "empty", text: "No submitted fields" }));
  }
  function scoreRows(score) { const root = score?.results || score?.scorer_result?.results || score || {}; if (root.properties && typeof root.properties === "object") return Object.entries(root.properties).map(([metric, value]) => ({ metric, ...(value || {}) })); if (Array.isArray(root.metrics)) return root.metrics; return Object.entries(root).filter(([, value]) => value && typeof value === "object" && !Array.isArray(value)).map(([metric, value]) => ({ metric, ...value })); }
  function scoreTable(score) { const rows = scoreRows(score); if (!rows.length) return md("No structured objective score is available."); const table = q("table", { class: "score-table" }); table.append(q("thead", {}, [q("tr", {}, ["Metric", "Value", "Target", "Direction", "Result"].map((name) => q("th", { text: name })))])); const body = q("tbody"); rows.forEach((row) => { const result = row.result ?? row.passed ?? row.satisfied ?? row.status ?? ""; const pass = result === true || ["pass", "passed", "met", "true"].includes(String(result).toLowerCase()); const fail = result === false || ["fail", "failed", "not met", "false"].includes(String(result).toLowerCase()); body.append(q("tr", {}, [q("td", { text: row.metric || row.name || "metric" }), q("td", { text: String(row.value ?? row.score ?? row.actual ?? "") }), q("td", { text: String(row.target ?? row.threshold ?? "") }), q("td", { text: String(row.direction || "") }), q("td", { class: pass ? "score-good" : fail ? "score-bad" : "", text: typeof result === "boolean" ? (result ? "Met" : "Not met") : String(result) })])); }); table.append(body); return table; }
  function displayPlan(plan) { return String(plan || "").replace(/^\s*#?\s*EXPERIMENT RUNNER PLAN(?:\s*(?::|[—-])\s*[^\n]*)?\s*\n+/i, "").trim() || "No saved plan."; }
  function displayProposal(proposal) { return String(proposal || "").replace(/^\s*#?\s*AUTORESEARCH PROPOSAL\s*\n+/i, "").trim() || "Proposal record unavailable."; }
  function renderNodeDrawer(drawer, item, attempt) { const accepted = attempt ? item.accepted : true; drawer.append(q("h1", { text: attempt ? `${accepted ? "Accepted" : "Rejected"} ${item.proposal_type || "research"}` : item.selected ? "Selected research node" : "Research node" }), q("p", { class: "detail-meta", text: attempt ? `Candidate ${shortSha(item.node_sha)} from ${shortSha(item.parent_node_sha)}` : `${item.active ? "Active frontier" : "Retained"} · ${shortSha(item.node_sha)}${item.parent_node_sha ? ` · from ${shortSha(item.parent_node_sha)}` : ""}` })); tabs(drawer, attempt ? ["overview", "proposal", "score"] : ["overview", "plan", "score"]); if (state.tab === "overview") { const reason = item.reason_for_acceptance || item.reason_for_rejection; if (reason) drawer.append(detail(item.accepted === false ? "Reason for rejection" : "Reason for acceptance", reason)); if (attempt && item.proposal_idea_id) drawer.append(detail("Proposal", links([item.proposal_idea_id]))); if (!attempt) { const attempts = (state.snapshot?.attempts || []).filter((a) => a.parent_node_sha === item.node_sha); if (attempts.length) drawer.append(detail("Attempts from this node", q("div", { class: "attempt-list" }, attempts.map((a) => q("button", { class: "attempt-link", text: `${a.accepted ? "Accepted" : "Rejected"} ${a.proposal_type || "research"}${a.proposal_idea_id ? ` · ${a.proposal_idea_id}` : ""}`, onclick: () => openDrawer("attempt", a) }))))); } } else if (state.tab === "plan") drawer.append(detail("Experiment plan", displayPlan(item.plan))); else if (state.tab === "proposal") { const proposal = ideaById(item.proposal_idea_id); drawer.append(detail("Proposal", displayProposal(proposal?.proposal || proposal?.content))); } else drawer.append(detail("Objective score", scoreTable(item.objective_score))); }
  function renderWhiteboardDrawer(drawer, tip) { drawer.append(q("h1", { text: `${tip.id} ${tip.category || "note"}` }), q("p", { class: "detail-meta", text: tip.status || "active" }), detail("Note", tip.content)); if (tip.affects?.length) drawer.append(detail("Artifacts", artifactList(tip.affects))); }
  function drawer() { if (!state.drawer) return []; const shade = q("div", { class: "drawer-shade", onclick: () => { state.drawer = null; render(); } }); const panel = q("aside", { class: "drawer", "data-drawer-key": drawerKey() }); panel.append(icon("×", "Close details", () => { state.drawer = null; render(); }, "drawer-close")); const { kind, source } = state.drawer; if (kind === "idea") renderIdeaDrawer(panel, source); else if (kind === "submitted_idea") renderSubmittedIdeaDrawer(panel, source); else if (kind === "whiteboard") renderWhiteboardDrawer(panel, source); else renderNodeDrawer(panel, source, kind === "attempt"); return [shade, panel]; }

  const post = (path, payload) => requestJson(path, payload, "POST");
  async function submitConversation() {
    const operation = workspaceOperation("/input");
    const transient = transientFor(operation.key);
    const text = transient.composer.trim();
    if (!text) return;
    const clientTurnId = crypto.randomUUID();
    transient.composer = "";
    transient.notice = "";
    state.scrollToBottom = true;
    render();
    try {
      await post(operation.path, { text, input_kind: "conversation", provider: state.provider, client_turn_id: clientTurnId });
      if (operationIsCurrent(operation)) await refresh();
    } catch (error) {
      if (!operationIsCurrent(operation)) return;
      if (!transient.composer.trim()) transient.composer = text;
      transient.notice = error.message;
      render();
    }
  }
  async function submitRequest(request, feedback) {
    const operation = workspaceOperation("/input");
    const transient = transientFor(operation.key);
    const draft = loadRequestDraft(request, operation.key);
    const selectedOption = transient.selectedOption || draft.selectedOption || "";
    const text = String(feedback || draft.requestFeedback || "").trim();
    if (!selectedOption && !text) {
      transient.notice = "Choose an option or add feedback before submitting.";
      render();
      return;
    }
    try {
      await post(operation.path, { text, input_kind: "resolution_reply", request_key: request.request_key, option_id: selectedOption, provider: state.provider, client_turn_id: crypto.randomUUID() });
      clearRequestDraft(request, operation.key);
      if (!operationIsCurrent(operation)) return;
      transient.notice = "";
      await refresh();
    } catch (error) {
      if (!operationIsCurrent(operation)) return;
      if (["stale", "already_resolved"].includes(String(error.status || ""))) {
        clearRequestDraft(request, operation.key);
        transient.notice = "";
        await refresh();
        return;
      }
      transient.notice = error.message;
      render();
    }
  }
  async function removeQueued(id) { const operation = workspaceOperation("/queue"); const transient = transientFor(operation.key); try { await post(operation.path, { action: "remove", id }); if (operationIsCurrent(operation)) await refresh(); } catch (error) { if (!operationIsCurrent(operation)) return; transient.notice = error.message; render(); } }
  async function editQueued(item) {
    const operation = workspaceOperation("/queue");
    const transient = transientFor(operation.key);
    try {
      await post(operation.path, { action: "remove", id: item.id });
      if (!operationIsCurrent(operation)) return;
      transient.composer = String(item.text || "");
      transient.notice = "";
      await refresh();
      requestAnimationFrame(() => {
        const area = document.querySelector('textarea[data-focus-key="composer"]');
        if (!(area instanceof HTMLTextAreaElement)) return;
        area.focus();
        area.setSelectionRange(area.value.length, area.value.length);
        autoSizeTextarea(area);
      });
    } catch (error) { if (!operationIsCurrent(operation)) return; transient.notice = error.message; render(); }
  }
  async function cancelTurn() { transientFor().notice = "Cancellation is not available yet."; render(); }
  async function launchRun(payload) { const operation = workspaceOperation("/run"); const transient = transientFor(operation.key); try { await post(operation.path, payload); if (!operationIsCurrent(operation)) return; state.runPanel = false; transient.notice = ""; await refresh(); } catch (error) { if (!operationIsCurrent(operation)) return; transient.notice = error.message; render(); } }
  async function stopRun() {
    const operation = workspaceOperation("/run/stop");
    const transient = transientFor(operation.key);
    try {
      await post(operation.path, {});
      if (!operationIsCurrent(operation)) return;
      transient.notice = "Stop requested. Restoring saved progress.";
      await refresh();
    } catch (error) {
      if (!operationIsCurrent(operation)) return;
      transient.notice = error.message;
      render();
    }
  }
  function portalWorkspace() {
    const workspace = q("section", { class: "portal-workspace" });
    if (state.portalSidebarCollapsed) {
      workspace.append(icon("☰", "Show ideas", () => {
        state.portalSidebarCollapsed = false;
        localStorage.setItem("neurico-hitl-ideas-collapsed", "0");
        render({ preserveScroll: true });
      }, "portal-expand"));
    }
    if (state.creatingIdea) {
      workspace.append(ideaCreationPage());
      return workspace;
    }
    if (!state.selectedIdeaId) {
      workspace.append(q("div", { class: "portal-empty-state", text: "No ideas" }));
      return workspace;
    }
    if (!state.snapshot) {
      if (state.stale) {
        const ownershipConflict = /already manages workspace/i.test(state.stale);
        workspace.append(q("div", {
          class: "portal-empty-state portal-workspace-error",
          role: "alert",
        }, [
          q("strong", {
            text: ownershipConflict ? "Open in another interface" : "Workspace unavailable",
          }),
          q("p", { text: state.stale }),
          q("span", {
            text: ownershipConflict
              ? "Continue in that interface, stop it, or select another idea."
              : "NeuriCo will retry automatically.",
          }),
        ]));
      } else {
        workspace.append(q("div", { class: "portal-loading", text: "Loading" }));
      }
      return workspace;
    }
    workspace.append(topbar(), state.route === "conversation" ? conversation() : research());
    return workspace;
  }
  function render(options = {}) {
    captureGraphScroll();
    captureDrawerScroll();
    const focusedControl = captureFocusedControl();
    const preserveScroll = Boolean(options.preserveScroll);
    const restoreConversation = Boolean(options.restoreConversation);
    const previousY = window.scrollY;
    const wasNearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 80;
    document.querySelectorAll(".drawer-shade,.drawer").forEach((element) => element.remove());
    if (state.portal) {
      app.replaceChildren(q("div", { class: `portal-shell ${state.portalSidebarCollapsed ? "portal-sidebar-collapsed" : ""}` }, [ideaSidebar(), portalWorkspace()]));
    }
    else app.replaceChildren(topbar(), state.route === "conversation" ? conversation() : research());
    if (state.route === "conversation" && !state.creatingIdea && state.snapshot) observeComposerSpace();
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
    const nextIdeaId = new URLSearchParams(location.search).get("idea") || "";
    if (previousRoute === "conversation" && nextRoute !== "conversation") captureConversationScroll();
    state.route = nextRoute;
    state.drawer = null;
    state.runPanel = false;
    if (state.portal && nextIdeaId && nextIdeaId !== state.selectedIdeaId) {
      workspaceGeneration += 1;
      state.selectedIdeaId = nextIdeaId;
      state.snapshot = null;
      state.snapshotSig = "";
      state.thinking = false;
      state.managerStatusSeq = -1;
      state.stale = "";
      state.creatingIdea = false;
      connectWorkspaceEvents();
      refresh();
    }
    render({ restoreConversation: nextRoute === "conversation" && previousRoute !== "conversation" });
  });
  async function drainRefreshes() {
    while (refreshPending) {
      refreshPending = false;
      const operation = workspaceOperation("/snapshot");
      let result;
      try {
        if (state.portal && !state.selectedIdeaId) {
          result = { data: null, signature: "", error: "" };
          continue;
        }
        const response = await fetch(operation.path, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Workspace data unavailable.");
        result = { data, signature: JSON.stringify(data), error: "" };
      } catch (error) {
        result = { data: null, signature: "", error: error.message };
      }
      if (!operationIsCurrent(operation)) {
        refreshPending = true;
        continue;
      }
      if (refreshPending) continue;
      const changed = result.error
        ? state.stale !== result.error
        : result.signature !== state.snapshotSig || Boolean(state.stale);
      if (result.error) {
        state.stale = result.error;
      } else {
        const activeInput = result.data?.inbox?.active;
        const durableThinking = Boolean(activeInput && String(activeInput.status || "pending") !== "failed");
        const thinkingChanged = applyManagerStatus({
          ...(result.data?.manager_status || {}),
          thinking: durableThinking,
        });
        const managerProvider = String(result.data?.manager?.provider || "").toLowerCase();
        if (["claude", "codex"].includes(managerProvider) && (result.data?.manager?.provider_locked || !state.providerTouched)) {
          state.provider = managerProvider;
        }
        state.snapshot = result.data;
        state.snapshotSig = result.signature;
        state.stale = "";
        if (state.portal) {
          const selectedIdea = state.ideas.find((idea) => idea.idea_id === operation.ideaId);
          if (selectedIdea) selectedIdea.live = result.data?.live || {};
        }
        if (thinkingChanged) state.scrollToBottom = true;
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
  async function boot() {
    await loadCatalog({ updateUrl: true });
    render();
    connectWorkspaceEvents();
    if (!state.portal || state.selectedIdeaId) await refresh();
  }
  setInterval(refresh, 5000);
  setInterval(updatePhaseTimer, 1000);
  boot();
})();
