(() => {
  "use strict";

  const app = document.querySelector("#app");
  const state = {
    context: null,
    view: "form", // form | success
    preview: null, // {yaml, valid, errors, warnings}
    submitted: null, // {idea_id, path, warnings, next_steps, updated?}
    viewing: null, // {idea_id, status, editable, path, yaml, spec}
    editing: "", // idea_id currently loaded into the form, "" = new idea
    busy: false,
    notice: "",
    sections: { background: false, methodology: false, constraints: false },
    form: {
      title: "", domain: "", hypothesis: "",
      background_description: "",
      papers: [], datasets: [],
      approach: "", steps: [], baselines: [], metrics: [],
      compute: "", time_limit: "",
    },
  };

  const q = (tag, attrs = {}, children = []) => {
    const element = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === null || value === undefined) return;
      if (key === "class") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key.startsWith("on")) element[key] = value;
      else element.setAttribute(key, value);
    });
    [].concat(children).filter(Boolean).forEach((child) => element.append(child));
    return element;
  };
  const humanize = (value) => String(value || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  async function api(path, options) {
    const response = await fetch(path, options);
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const message = payload?.errors?.join(" ") || payload?.error || `Request failed (${response.status}).`;
      const error = new Error(message);
      error.payload = payload;
      throw error;
    }
    return payload;
  }
  const post = (path, body) => api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  function formPayload() {
    const f = state.form;
    return {
      idea_id: state.editing || null,
      title: f.title, domain: f.domain, hypothesis: f.hypothesis,
      background_description: f.background_description,
      papers: f.papers, datasets: f.datasets,
      approach: f.approach, steps: f.steps, baselines: f.baselines, metrics: f.metrics,
      compute: f.compute, time_limit: f.time_limit === "" ? null : f.time_limit,
    };
  }

  async function openPreview() {
    state.busy = true; state.notice = ""; render();
    try {
      state.preview = await post("/api/preview", formPayload());
    } catch (error) {
      state.notice = error.message;
    }
    state.busy = false; render();
  }

  async function submitIdea() {
    state.busy = true; state.notice = ""; render();
    try {
      const endpoint = state.editing ? `/api/ideas/${encodeURIComponent(state.editing)}` : "/api/submit";
      state.submitted = await post(endpoint, formPayload());
      state.preview = null;
      state.editing = "";
      state.view = "success";
      refreshContext();
    } catch (error) {
      state.notice = error.message;
    }
    state.busy = false; render();
  }

  async function openIdea(ideaId) {
    state.busy = true; state.notice = ""; render();
    try {
      state.viewing = await api(`/api/ideas/${encodeURIComponent(ideaId)}`);
    } catch (error) {
      state.notice = error.message;
    }
    state.busy = false; render();
  }

  function specToForm(spec) {
    const idea = spec?.idea || {};
    const background = idea.background || {};
    const methodology = idea.methodology || {};
    const constraints = idea.constraints || {};
    return {
      title: idea.title || "", domain: idea.domain || "", hypothesis: idea.hypothesis || "",
      background_description: background.description || "",
      papers: (background.papers || []).map((p) => ({ url: p.url || "", description: p.description || "" })),
      datasets: (background.datasets || []).map((d) => ({ name: d.name || "", source: d.source || "" })),
      approach: methodology.approach || "",
      steps: [...(methodology.steps || [])],
      baselines: [...(methodology.baselines || [])],
      metrics: [...(methodology.metrics || [])],
      compute: constraints.compute || "",
      time_limit: constraints.time_limit ?? "",
    };
  }

  function startEditing() {
    const v = state.viewing;
    if (!v?.editable) return;
    state.form = specToForm(v.spec);
    state.editing = v.idea_id;
    state.viewing = null;
    state.view = "form";
    state.submitted = null;
    state.notice = "";
    render();
    window.scrollTo({ top: 0 });
  }

  async function refreshContext() {
    try {
      state.context = await api("/api/context");
      if (!state.form.domain) state.form.domain = state.context.default_domain || "";
    } catch (error) {
      state.notice = error.message;
    }
    render();
  }

  function resetForm() {
    state.form = {
      title: "", domain: state.context?.default_domain || "", hypothesis: "",
      background_description: "",
      papers: [], datasets: [],
      approach: "", steps: [], baselines: [], metrics: [],
      compute: "", time_limit: "",
    };
    state.submitted = null; state.view = "form"; state.notice = ""; state.editing = "";
    render();
  }

  // ----- form controls (inputs mutate state directly; re-render only on structure changes)

  function field(labelText, control, hint) {
    return q("label", { class: "field" }, [
      q("span", { class: "field-label", text: labelText }),
      control,
      hint ? q("span", { class: "field-hint", text: hint }) : null,
    ]);
  }
  const textInput = (key, placeholder = "") => q("input", {
    type: "text", value: state.form[key], placeholder,
    oninput: (e) => { state.form[key] = e.target.value; },
  });
  const textArea = (key, placeholder = "", rows = 4) => q("textarea", {
    rows: String(rows), placeholder,
    oninput: (e) => { state.form[key] = e.target.value; },
  }, [state.form[key]]);

  function rowEditor(key, fields) {
    const rows = state.form[key];
    const wrap = q("div", { class: "row-editor" });
    rows.forEach((row, index) => {
      wrap.append(q("div", { class: "editor-row" }, [
        ...fields.map(([name, placeholder]) => q("input", {
          type: "text", value: row[name] || "", placeholder,
          oninput: (e) => { row[name] = e.target.value; },
        })),
        q("button", {
          class: "row-remove", type: "button", title: "Remove", "aria-label": "Remove row",
          onclick: () => { rows.splice(index, 1); render(); }, text: "✕",
        }),
      ]));
    });
    wrap.append(q("button", {
      class: "row-add", type: "button",
      onclick: () => { rows.push(Object.fromEntries(fields.map(([n]) => [n, ""]))); render(); },
      text: `+ Add ${fields.map(([n]) => n).join(" / ")}`,
    }));
    return wrap;
  }

  function listEditor(key, placeholder) {
    const values = state.form[key];
    const wrap = q("div", { class: "row-editor" });
    values.forEach((value, index) => {
      wrap.append(q("div", { class: "editor-row" }, [
        q("input", {
          type: "text", value, placeholder,
          oninput: (e) => { values[index] = e.target.value; },
        }),
        q("button", {
          class: "row-remove", type: "button", title: "Remove", "aria-label": "Remove row",
          onclick: () => { values.splice(index, 1); render(); }, text: "✕",
        }),
      ]));
    });
    wrap.append(q("button", {
      class: "row-add", type: "button",
      onclick: () => { values.push(""); render(); }, text: "+ Add item",
    }));
    return wrap;
  }

  function domainSelect() {
    const select = q("select", {
      onchange: (e) => { state.form.domain = e.target.value; },
    }, (state.context?.domains || []).map((domain) => q("option", {
      value: domain.id, text: `${domain.name} — ${domain.description}`,
    })));
    select.value = state.form.domain;
    return select;
  }

  function computeSelect() {
    const select = q("select", {
      onchange: (e) => { state.form.compute = e.target.value; },
    }, [
      q("option", { value: "", text: "Not specified" }),
      ...(state.context?.compute_options || []).map((option) =>
        q("option", { value: option, text: humanize(option) })),
    ]);
    select.value = state.form.compute;
    return select;
  }

  function advanced(key, summary, ...children) {
    const details = q("details", {
      class: "advanced",
      ontoggle: (e) => { state.sections[key] = e.target.open; },
    }, [
      q("summary", { text: summary }),
      q("div", { class: "advanced-body" }, children),
    ]);
    if (state.sections[key]) details.setAttribute("open", "");
    return details;
  }

  function renderForm(main) {
    if (state.editing) {
      main.append(q("h1", { text: "Edit idea" }));
      main.append(q("p", { class: "lede" }, [
        "Editing ", q("code", { text: state.editing }),
        ". Saving updates the fields shown here and keeps everything else in the file. ",
        q("button", { class: "link-button", type: "button", onclick: resetForm, text: "Cancel and start a new idea" }),
      ]));
    } else {
      main.append(q("h1", { text: "Submit a research idea" }));
      main.append(q("p", {
        class: "lede",
        text: "Only the title, domain, and hypothesis are required. The optional sections below let you add background, methodology, and constraints.",
      }));
    }
    const form = q("form", { class: "idea-form", onsubmit: (e) => { e.preventDefault(); openPreview(); } });
    form.append(
      field("Title", textInput("title", "Clear, descriptive title")),
      field("Domain", domainSelect()),
      field("Hypothesis", textArea("hypothesis", "A specific, testable hypothesis", 4)),
      advanced("background", "Background (optional)",
        field("Description", textArea("background_description", "Context and motivation", 3)),
        field("Papers", rowEditor("papers", [["url", "https://arxiv.org/abs/..."], ["description", "Why this paper is relevant"]])),
        field("Datasets", rowEditor("datasets", [["name", "Dataset name"], ["source", "Where to get it"]])),
      ),
      advanced("methodology", "Methodology (optional)",
        field("Approach", textArea("approach", "High-level strategy", 3)),
        field("Steps", listEditor("steps", "Step description")),
        field("Baselines", listEditor("baselines", "Baseline name")),
        field("Metrics", listEditor("metrics", "Metric name")),
      ),
      advanced("constraints", "Constraints (optional)",
        field("Compute", computeSelect()),
        field("Time limit (seconds)", q("input", {
          type: "number", min: "60", value: state.form.time_limit, placeholder: "3600",
          oninput: (e) => { state.form.time_limit = e.target.value; },
        })),
      ),
      q("div", { class: "form-actions" }, [
        state.notice ? q("span", { class: "notice", text: state.notice }) : null,
        q("button", {
          class: "primary", type: "submit", disabled: state.busy ? "" : null,
          text: state.busy ? "Working…" : state.editing ? "Preview changes" : "Preview YAML",
        }),
      ]),
    );
    main.append(form);
  }

  function renderPreview() {
    const p = state.preview;
    const messages = [
      ...p.errors.map((text) => q("p", { class: "error", text: `Error: ${text}` })),
      ...p.warnings.map((text) => q("p", { class: "warning", text: `Warning: ${text}` })),
    ];
    return [
      q("div", { class: "drawer-shade", onclick: () => { state.preview = null; render(); } }),
      q("aside", { class: "drawer" }, [
        q("button", { class: "drawer-close", "aria-label": "Close preview", onclick: () => { state.preview = null; render(); }, text: "✕" }),
        q("h1", { text: "Idea YAML preview" }),
        q("p", { class: "detail-meta", text: "This is exactly what will be written to ideas/submitted/." }),
        ...messages,
        yamlBlock(p.yaml),
        q("div", { class: "form-actions" }, [
          state.notice ? q("span", { class: "notice", text: state.notice }) : null,
          q("button", { class: "ghost", type: "button", onclick: () => { state.preview = null; render(); }, text: "Back to form" }),
          q("button", {
            class: "primary", type: "button",
            disabled: state.busy || !p.valid ? "" : null,
            onclick: submitIdea,
            text: state.busy
              ? "Saving…"
              : !p.valid
                ? "Fix errors to save"
                : state.editing ? "Save changes" : "Submit idea",
          }),
        ]),
      ]),
    ];
  }

  function renderViewer() {
    const v = state.viewing;
    return [
      q("div", { class: "drawer-shade", onclick: () => { state.viewing = null; render(); } }),
      q("aside", { class: "drawer" }, [
        q("button", { class: "drawer-close", "aria-label": "Close idea", onclick: () => { state.viewing = null; render(); }, text: "✕" }),
        q("h1", { text: v.spec?.idea?.title || v.idea_id }),
        q("p", { class: "detail-meta" }, [
          q("code", { text: v.idea_id }),
          copyButton(v.idea_id, "Copy idea_id"),
          ` · ${humanize(v.status)} · ${v.path}`,
        ]),
        v.editable
          ? q("div", { class: "form-actions viewer-actions" }, [
              q("button", { class: "primary", type: "button", onclick: startEditing, text: "Edit this idea" }),
            ])
          : q("p", { class: "warning", text: `This idea is ${humanize(v.status).toLowerCase()} and can no longer be edited here.` }),
        yamlBlock(v.yaml),
      ]),
    ];
  }

  // Lucide icons (lucide.dev, ISC license), inlined as SVG paths.
  const svgEl = (tag, attrs) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
  };
  function lucide(shapes) {
    const svg = svgEl("svg", {
      viewBox: "0 0 24 24", width: "14", height: "14", fill: "none",
      stroke: "currentColor", "stroke-width": "2",
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
    });
    shapes.forEach(([tag, attrs]) => svg.append(svgEl(tag, attrs)));
    return svg;
  }
  const copyIcon = () => lucide([
    ["rect", { width: "14", height: "14", x: "8", y: "8", rx: "2", ry: "2" }],
    ["path", { d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" }],
  ]);
  const checkIcon = () => lucide([["path", { d: "M20 6 9 17l-5-5" }]]);

  function copyButton(text, label = "Copy") {
    const button = q("button", {
      class: "copy", type: "button", "data-label": label, "aria-label": label,
      onclick: () => {
        navigator.clipboard?.writeText(text);
        button.replaceChildren(checkIcon());
        button.classList.add("copied");
        button.dataset.label = "Copied";
        setTimeout(() => {
          button.replaceChildren(copyIcon());
          button.classList.remove("copied");
          button.dataset.label = label;
        }, 1200);
      },
    }, [copyIcon()]);
    return button;
  }

  function yamlBlock(text) {
    return q("div", { class: "yaml-wrap" }, [
      copyButton(text, "Copy YAML"),
      q("pre", { class: "yaml-preview", text }),
    ]);
  }

  function commandBlock(label, command) {
    return q("div", { class: "command" }, [
      q("span", { class: "command-label", text: label }),
      q("div", { class: "command-row" }, [
        q("code", { text: command }),
        copyButton(command, "Copy command"),
      ]),
    ]);
  }

  function renderSuccess(main) {
    const s = state.submitted;
    main.append(q("h1", { text: s.updated ? "Idea updated" : "Idea submitted" }));
    main.append(q("p", { class: "lede" }, [
      s.updated ? "Updated " : "Saved as ", q("code", { text: s.idea_id }),
      copyButton(s.idea_id, "Copy idea_id"),
      " in ", q("code", { text: s.path }), ".",
    ]));
    s.warnings.forEach((text) => main.append(q("p", { class: "warning", text: `Warning: ${text}` })));
    main.append(q("h2", { text: "Next steps" }));
    s.next_steps.forEach((step) => {
      main.append(commandBlock(`${step.label} (native)`, step.native));
      main.append(commandBlock(`${step.label} (Docker)`, step.docker));
    });
    main.append(q("div", { class: "form-actions" }, [
      q("button", { class: "primary", type: "button", onclick: resetForm, text: "Submit another idea" }),
    ]));
  }

  function renderIdeas(main) {
    const ideas = state.context?.ideas || [];
    main.append(q("h2", { class: "ideas-heading", text: `Existing ideas (${ideas.length})` }));
    if (!ideas.length) {
      main.append(q("p", { class: "empty", text: "No ideas submitted yet." }));
      return;
    }
    const list = q("div", { class: "idea-list" });
    ideas.forEach((idea) => {
      list.append(q("button", {
        class: "idea-row", type: "button",
        title: "View idea",
        onclick: () => openIdea(idea.idea_id),
      }, [
        q("div", { class: "idea-main" }, [
          q("div", { class: "idea-title", text: idea.title }),
          q("code", { class: "idea-id", text: idea.idea_id }),
        ]),
        q("span", { class: "idea-domain", text: humanize(idea.domain) }),
        q("span", { class: `idea-status status-${idea.status}`, text: humanize(idea.status) }),
      ]));
    });
    main.append(list);
  }

  function render() {
    app.replaceChildren();
    app.append(q("header", { class: "topbar" }, [
      q("div", { class: "brand" }, [
        q("span", { class: "workspace-mark", text: "◆" }),
        q("span", { class: "workspace-title", text: "NeuriCo" }),
        q("span", { class: "page-label", text: "Submit an idea" }),
      ]),
    ]));
    const main = q("main", { class: "lobby" });
    if (!state.context) {
      main.append(q("p", { class: "empty", text: state.notice || "Loading…" }));
    } else if (state.view === "success") {
      renderSuccess(main);
      renderIdeas(main);
    } else {
      renderForm(main);
      renderIdeas(main);
    }
    app.append(main);
    if (state.preview) renderPreview().forEach((node) => app.append(node));
    else if (state.viewing) renderViewer().forEach((node) => app.append(node));
  }

  render();
  refreshContext();
})();
