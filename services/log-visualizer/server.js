import http from "node:http";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { autoresearchReader } from "./server_autoresearch.js";
import {
  ANNOTATION_SCHEMA_VERSION,
  FAILURE_LABELS,
  VISUALIZER_VERSION,
  WORLD_MODEL_STAGES,
  WORLD_MODEL_VERSION,
  assertRunId,
  canAccessRun,
  contentFingerprint,
  parseWorkspaceUri,
  safeArtifactPath,
  userFromHeaders,
  validateAnnotation,
} from "./platform_core.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");                 // neurico-log-visualizer/ — holds the run folders
const RUNS_ROOT = process.env.NEURICO_RUNS_ROOT ? path.resolve(process.env.NEURICO_RUNS_ROOT) : ROOT;

// A folder is a NeuriCo run if it has a .neurico/ or logs/ directory.
function looksLikeRun(dir) {
  return existsSync(path.join(dir, ".neurico")) || existsSync(path.join(dir, "logs"));
}

function listRuns() {
  try {
    return readdirSync(RUNS_ROOT, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && looksLikeRun(path.join(RUNS_ROOT, entry.name)))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return [];
  }
}

// Run selection: `node server.js <project-name-or-path>`, else NEURICO_RUN_DIR,
// else the first run found under RUNS_ROOT (no run is special-cased).
function resolveRunDir() {
  const arg = process.argv[2];
  if (arg) {
    return path.isAbsolute(arg) || arg.includes(path.sep)
      ? path.resolve(arg)
      : path.resolve(RUNS_ROOT, arg);
  }
  if (process.env.NEURICO_RUN_DIR) return path.resolve(process.env.NEURICO_RUN_DIR);
  const runs = listRuns();
  return runs.length ? path.resolve(RUNS_ROOT, runs[0]) : path.resolve(RUNS_ROOT);
}

const RUN_DIR = resolveRunDir();
if (!existsSync(RUN_DIR)) {
  console.error(`\n✗ Run folder not found: ${RUN_DIR}\n`);
  const runs = listRuns();
  if (runs.length) {
    console.error(`Available projects in ${RUNS_ROOT}:`);
    for (const name of runs) console.error(`    node server.js ${name}`);
  } else {
    console.error(`No run folders found in ${RUNS_ROOT}. Pass a full path, or set NEURICO_RUNS_ROOT.`);
  }
  console.error("");
  process.exit(1);
}

const PUBLIC_DIR = path.resolve(__dirname, "public");
const DATA_DIR = process.env.NEURICO_DATA_DIR ? path.resolve(process.env.NEURICO_DATA_DIR) : path.resolve(__dirname, "data");
const SERVICE_TOKEN = process.env.NEURICO_INTERNAL_TOKEN || process.env.NEURICO_SERVICE_TOKEN || "";
const AUTOSPAWN_WORKER = !/^(0|false|off)$/i.test(process.env.NEURICO_AUTOSPAWN_WORKER || "");
const RUN_ID = path.basename(RUN_DIR);
const PORT = Number(process.env.PORT || 5173);
// Bind to loopback by default so local dev works in restricted environments. Set
// NEURICO_HOST=0.0.0.0 only when intentionally exposing the server to the network.
const HOST = process.env.NEURICO_HOST || process.env.HOST || "127.0.0.1";

// Multi-run platform: every run-scoped helper takes a `run = { id, dir }` context.
// It defaults to the single run picked at startup so `node server.js <run>` (dev)
// still works unchanged; the platform passes an explicit run resolved per request.
const DEFAULT_RUN = { id: RUN_ID, dir: RUN_DIR };

async function readJsonBody(req) {
  let body = "";
  for await (const chunk of req) body += chunk;
  if (!body.trim()) return {};
  return JSON.parse(body);
}

function safeFilePart(value) {
  return String(value || "anonymous")
    .replace(/[^a-zA-Z0-9._@-]/g, "_")
    .slice(0, 120);
}


function uniquePaths(paths) {
  const seen = new Set();
  return paths.filter((item) => {
    const resolved = path.resolve(item);
    if (seen.has(resolved)) return false;
    seen.add(resolved);
    return true;
  });
}

function runCandidateDirs(runId) {
  const id = assertRunId(runId || DEFAULT_RUN.id);
  return uniquePaths([
    id === DEFAULT_RUN.id ? DEFAULT_RUN.dir : "",
    path.resolve(RUNS_ROOT, id),
    path.resolve(RUNS_ROOT, "hypogenic-runs", id),
    path.resolve(path.dirname(DEFAULT_RUN.dir), id),
    path.resolve(DATA_DIR, "runs", id),
    path.resolve(DATA_DIR, id),
  ].filter(Boolean));
}

function resolveRun(runId) {
  if (!runId) return DEFAULT_RUN;

  runId = assertRunId(runId);

  const candidateDirs = runCandidateDirs(runId);

  for (const dir of candidateDirs) {
    if (existsSync(dir)) {
      return { id: runId, dir };
    }
  }

  const catalog = readVisualizerJsonSync(catalogPath(), { runs: [] });
  const record = (catalog.runs || []).find((item) => item.run_id === runId);
  if (record?.source_workspace && existsSync(record.source_workspace)) {
    return { id: runId, dir: record.source_workspace };
  }

  throw Object.assign(new Error(`Unknown run: ${runId}`), { status: 404 });
}

const ELEMENT_LIBRARY = [
  // v3 entity graph: the Flow tab is the scientific graph of the world model.
  {
    type: "hypothesis",
    label: "Hypothesis",
    description: "A claim the run set out to test.",
    color: "#7b5aa6",
  },
  {
    type: "experiment",
    label: "Experiment",
    description: "An agent stage that ran to test a hypothesis.",
    color: "#3f6f8f",
  },
  {
    type: "finding",
    label: "Finding",
    description: "An atomic result the run produced — the spine of the model.",
    color: "#216869",
  },
  {
    type: "intent",
    label: "Intent",
    description: "The goal, hypothesis, or project state being established.",
    color: "#216869",
  },
  {
    type: "plan",
    label: "Plan",
    description: "A deliberate decomposition of the work.",
    color: "#7b5aa6",
  },
  {
    type: "constraint",
    label: "Constraint",
    description: "A requirement, assumption, or limit that shapes the work.",
    color: "#6b7280",
  },
  {
    type: "research",
    label: "Research",
    description: "Reading papers, resources, docs, or background context.",
    color: "#3f6f8f",
  },
  {
    type: "literature_search",
    label: "Literature Search",
    description: "Finding and screening relevant papers.",
    color: "#3f6f8f",
  },
  {
    type: "dataset_search",
    label: "Dataset Search",
    description: "Finding and screening candidate datasets.",
    color: "#2d7c8c",
  },
  {
    type: "data_inspection",
    label: "Data Inspection",
    description: "Checking dataset fields, schema, and suitability.",
    color: "#2d7c8c",
  },
  {
    type: "decision",
    label: "Decision",
    description: "A meaningful choice that changes the project path.",
    color: "#8c5b2d",
  },
  {
    type: "method_design",
    label: "Method Design",
    description: "Designing the experiment, protocol, or evaluation method.",
    color: "#7b5aa6",
  },
  {
    type: "branch",
    label: "Branch",
    description: "A logical split into multiple work tracks.",
    color: "#8c5b2d",
  },
  {
    type: "data",
    label: "Data",
    description: "Finding, checking, or preparing datasets.",
    color: "#2d7c8c",
  },
  {
    type: "implementation",
    label: "Implementation",
    description: "Building scripts, prompts, or project files.",
    color: "#56636d",
  },
  {
    type: "experiment_matrix",
    label: "Experiment Matrix",
    description: "A structured combination of models, datasets, regimes, prompts, or baselines.",
    color: "#6f5aa7",
  },
  {
    type: "model_run",
    label: "Model Run",
    description: "Running a model or automated experiment.",
    color: "#6f5aa7",
  },
  {
    type: "execution",
    label: "Execution",
    description: "Running models, experiments, or workflows.",
    color: "#6f5aa7",
  },
  {
    type: "parallel",
    label: "Multitask",
    description: "A side track worked on while another task runs.",
    color: "#a76013",
  },
  {
    type: "analysis",
    label: "Analysis",
    description: "Turning outputs into metrics, tables, or interpretation.",
    color: "#8c5b2d",
  },
  {
    type: "evaluation",
    label: "Evaluation",
    description: "Computing metrics, baselines, tests, or comparisons.",
    color: "#8c5b2d",
  },
  {
    type: "writing",
    label: "Writing",
    description: "Creating reports, drafts, or final documentation.",
    color: "#315f8f",
  },
  {
    type: "report_writing",
    label: "Report Writing",
    description: "Writing final reports, papers, or human-facing summaries.",
    color: "#315f8f",
  },
  {
    type: "validation",
    label: "Validation",
    description: "Checking that work completed correctly.",
    color: "#1f7a4d",
  },
  {
    type: "risk",
    label: "Risk",
    description: "Failures, caveats, or concerns that affect trust.",
    color: "#b42318",
  },
  {
    type: "result",
    label: "Result",
    description: "A finding or output that answers the project question.",
    color: "#1f7a4d",
  },
];

const TEXT_EXTENSIONS = new Set([
  ".md",
  ".txt",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".csv",
  ".py",
  ".toml",
  ".tex",
  ".bib",
]);

function inside(base, candidate) {
  const relative = path.relative(base, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function safeRunPath(relativePath = "", run = DEFAULT_RUN) {
  const normalized = relativePath ? safeArtifactPath(relativePath) : "";
  const full = path.resolve(run.dir, normalized);
  if (!inside(run.dir, full)) {
    throw Object.assign(new Error("Path outside run directory"), { status: 400 });
  }
  return full;
}

function resolveRunForArtifact(runId, relativePath) {
  const requested = runId ? assertRunId(runId) : DEFAULT_RUN.id;
  const normalized = safeArtifactPath(relativePath);
  const candidates = runCandidateDirs(requested);
  for (const dir of candidates) {
    const run = { id: requested, dir };
    const full = safeRunPath(normalized, run);
    if (existsSync(full)) return run;
  }
  return resolveRun(requested);
}

async function readJson(relativePath, fallback = null, run = DEFAULT_RUN) {
  try {
    return JSON.parse(await readFile(safeRunPath(relativePath, run), "utf8"));
  } catch {
    return fallback;
  }
}

async function readText(relativePath, fallback = "", run = DEFAULT_RUN) {
  try {
    return await readFile(safeRunPath(relativePath, run), "utf8");
  } catch {
    return fallback;
  }
}

function visualizerPath(...parts) {
  return path.resolve(DATA_DIR, ...parts);
}

const PLATFORM_DIRS = ["catalog", "manifests", "indexes", "world-models", "previews", "annotations", "assignments", "jobs", "audit", "exports"];

function platformRel(...parts) {
  return path.join(...parts);
}

function readVisualizerJsonSync(relativePath, fallback = null) {
  try {
    return JSON.parse(readFileSync(visualizerPath(relativePath), "utf8"));
  } catch {
    return fallback;
  }
}

async function ensurePlatformStorage() {
  await Promise.all(PLATFORM_DIRS.map((dir) => mkdir(visualizerPath(dir), { recursive: true })));
}

function catalogPath() {
  return platformRel("catalog", "runs.json");
}

function usersPath() {
  return platformRel("catalog", "users.json");
}

function assignmentsPath() {
  return platformRel("assignments", "assignments.json");
}

function jobsPath() {
  return platformRel("jobs", "jobs.json");
}

async function readCatalog() {
  const catalog = await readVisualizerJson(catalogPath(), { runs: [] });
  return { runs: Array.isArray(catalog?.runs) ? catalog.runs : [] };
}

async function writeCatalog(catalog) {
  await writeVisualizerJson(catalogPath(), { runs: Array.isArray(catalog.runs) ? catalog.runs : [] });
}

async function readAssignments() {
  const store = await readVisualizerJson(assignmentsPath(), { assignments: [] });
  return { assignments: Array.isArray(store?.assignments) ? store.assignments : [] };
}

async function writeAssignments(store) {
  await writeVisualizerJson(assignmentsPath(), { assignments: Array.isArray(store.assignments) ? store.assignments : [] });
}

async function readJobs() {
  const store = await readVisualizerJson(jobsPath(), { jobs: [] });
  return { jobs: Array.isArray(store?.jobs) ? store.jobs : [] };
}

async function writeJobs(store) {
  await writeVisualizerJson(jobsPath(), { jobs: Array.isArray(store.jobs) ? store.jobs : [] });
}

async function audit(eventType, actor, payload = {}) {
  const day = new Date().toISOString().slice(0, 10);
  const rel = platformRel("audit", `${day}.jsonl`);
  const full = visualizerPath(rel);
  await mkdir(path.dirname(full), { recursive: true });
  const event = {
    audit_id: `audit_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    event_type: eventType,
    actor: actor || "system",
    created_at: new Date().toISOString(),
    payload,
  };
  await writeFile(full, `${JSON.stringify(event)}\n`, { flag: "a" });
  return event;
}

function requireInternal(req) {
  if (!SERVICE_TOKEN) return;
  const token = String(req.headers["x-neurico-service-token"] || req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  if (token !== SERVICE_TOKEN) {
    throw Object.assign(new Error("Internal service credential required"), { status: 401, code: "unauthorized" });
  }
}

function requireAdmin(user) {
  if (user.role !== "administrator") {
    throw Object.assign(new Error("Administrator role required"), { status: 403, code: "forbidden" });
  }
}

function uuid(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

// Common LaTeX math/symbol commands → Unicode, so the abstract's "$\wedge$", "$7.8\times$",
// "$\alpha=100$", "$\approx$" render as ∧ / 7.8× / α=100 / ≈ instead of being dropped to gaps.
const LATEX_UNICODE = {
  "\\wedge": "∧", "\\vee": "∨", "\\approx": "≈", "\\times": "×", "\\cdot": "·",
  "\\leq": "≤", "\\le": "≤", "\\geq": "≥", "\\ge": "≥", "\\neq": "≠", "\\ne": "≠",
  "\\pm": "±", "\\mp": "∓", "\\sim": "∼", "\\propto": "∝", "\\infty": "∞",
  "\\rightarrow": "→", "\\to": "→", "\\leftarrow": "←", "\\Rightarrow": "⇒",
  "\\ll": "≪", "\\gg": "≫", "\\circ": "∘", "\\ast": "∗", "\\cap": "∩", "\\cup": "∪",
  "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ", "\\epsilon": "ε",
  "\\zeta": "ζ", "\\eta": "η", "\\theta": "θ", "\\kappa": "κ", "\\lambda": "λ",
  "\\mu": "μ", "\\nu": "ν", "\\xi": "ξ", "\\pi": "π", "\\rho": "ρ", "\\sigma": "σ",
  "\\tau": "τ", "\\phi": "φ", "\\chi": "χ", "\\psi": "ψ", "\\omega": "ω",
  "\\Delta": "Δ", "\\Sigma": "Σ", "\\Omega": "Ω", "\\Phi": "Φ", "\\Theta": "Θ", "\\Lambda": "Λ",
  "\\%": "%", "\\&": "&", "\\_": "_", "\\#": "#", "\\,": " ", "\\;": " ", "\\ ": " ",
};

// Parse the paper's no-argument \newcommand{\name}{body} macros (balanced braces), so
// paper-specific symbol macros can be expanded before stripping.
function parseNewcommands(tex) {
  const macros = {};
  const re = /\\newcommand\{\\([a-zA-Z]+)\}(\[\d+\])?\{/g;
  let m;
  while ((m = re.exec(String(tex || "")))) {
    if (m[2]) continue;                       // skip macros that take arguments
    let depth = 1, i = re.lastIndex, body = "";
    while (i < tex.length && depth > 0) {
      const ch = tex[i];
      if (ch === "{") depth++;
      else if (ch === "}") depth--;
      if (depth > 0) body += ch;
      i++;
    }
    macros["\\" + m[1]] = body;
  }
  return macros;
}
function expandMacros(text, macros) {
  let s = String(text || "");
  for (let pass = 0; pass < 3; pass++) {
    let changed = false;
    for (const [name, body] of Object.entries(macros)) {
      const re = new RegExp(name.replace(/\\/g, "\\\\") + "(?![a-zA-Z])", "g");
      if (re.test(s)) { s = s.replace(re, body); changed = true; }
    }
    if (!changed) break;
  }
  return s;
}

// Collect \newcommand macros from the paper's preamble: main.tex plus the non-section
// files it \input{}s (commands/macros.tex, commands/math.tex, …).
async function paperMacros(run) {
  let all = await readText("paper_draft/main.tex", "", run);
  for (const m of all.matchAll(/\\input\{([^}]+)\}/g)) {
    const inp = m[1];
    if (/^sections\//.test(inp)) continue;                  // skip section bodies
    const rel = inp.endsWith(".tex") ? inp : `${inp}.tex`;
    all += "\n" + await readText(`paper_draft/${rel}`, "", run);
  }
  return parseNewcommands(all);
}

// The paper's own \title{...} (balanced braces; \\ line-breaks flattened to a space),
// macro-expanded and LaTeX-stripped → the run's display title on the front page.
async function paperTitle(run, macros) {
  const tex = await readText("paper_draft/main.tex", "", run);
  const m = tex.match(/\\title\s*\{/);
  if (!m) return "";
  let depth = 1, i = m.index + m[0].length, body = "";
  while (i < tex.length && depth > 0) {
    const ch = tex[i];
    if (ch === "{") depth++;
    else if (ch === "}") depth--;
    if (depth > 0) body += ch;
    i++;
  }
  return stripLatex(expandMacros(body.replace(/\\\\/g, " "), macros));
}

// Strip LaTeX to plain prose so the paper's real abstract can render on the whiteboard.
// Best-effort: symbols → Unicode (above), keeps emphasized/math text, drops commands/cites.
function stripLatex(text) {
  let s = String(text || "");
  // Strip % line comments FIRST, while \% is still escaped — otherwise the symbol table
  // below turns the paper's "79\%" into "79%" and this regex deletes the rest of the line.
  s = s.replace(/(^|[^\\])%.*$/gm, "$1");
  for (const [cmd, ch] of Object.entries(LATEX_UNICODE)) s = s.split(cmd).join(ch);
  return s
    .replace(/\$([^$]*)\$/g, "$1")                                      // keep inline-math TEXT (symbols already converted)
    .replace(/---/g, "—").replace(/--/g, "–")                          // LaTeX em/en dashes
    .replace(/``/g, "“").replace(/''/g, "”").replace(/`/g, "‘") // LaTeX quotes “ ” ‘
    .replace(/\{,\}/g, ",")                                             // digit-group thin space: 1{,}050 → 1,050
    .replace(/\\begin\{[^}]*\}|\\end\{[^}]*\}/g, " ")                    // environments
    .replace(/\\(cite|citep|citet|ref|label|footnote)\s*\{[^}]*\}/g, " ") // refs/cites
    .replace(/\\(emph|textbf|textit|texttt|textsc|mathrm|mathbf|mathit|text|operatorname)\s*\{([^}]*)\}/g, "$2") // keep text
    .replace(/[_^]\{([^}]*)\}/g, "$1")                                  // sub/superscript braces
    .replace(/\\[a-zA-Z]+\*?\s*/g, " ")                                 // remaining commands
    .replace(/[{}]/g, " ")                                              // stray braces
    .replace(/~/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?)])/g, "$1")                                   // stray space before punctuation (from \xspace etc.)
    .trim();
}

async function readVisualizerJson(relativePath, fallback = null) {
  try {
    return JSON.parse(await readFile(visualizerPath(relativePath), "utf8"));
  } catch {
    return fallback;
  }
}

async function writeVisualizerJson(relativePath, value) {
  const full = visualizerPath(relativePath);
  await mkdir(path.dirname(full), { recursive: true });
  const body = `${JSON.stringify(value, null, 2)}\n`;
  await writeFile(full, body, "utf8");
}

async function writeVisualizerJsonIfMissing(relativePath, value) {
  const full = visualizerPath(relativePath);
  if (existsSync(full)) return;
  await writeVisualizerJson(relativePath, value);
}

// Per-user annotation storage: data/annotations/<user>/<runId>.json. The email is
// self-asserted, so sanitize it into a safe folder name and verify the resolved
// path stays inside data/annotations/ (defense in depth against path traversal).
function sanitizeUser(user) {
  const cleaned = String(user || "").trim().toLowerCase()
    .replace(/[^a-z0-9._@-]/g, "_")
    .replace(/\.\.+/g, "_")
    .replace(/^[._]+/, "");
  return cleaned || "anonymous";
}

function annotationRel(user, runId) {
  const rel = path.join("annotations", sanitizeUser(user), `${runId}.json`);
  if (!inside(visualizerPath("annotations"), visualizerPath(rel))) {
    throw Object.assign(new Error("Invalid annotation path"), { status: 400 });
  }
  return rel;
}

function feedbackRel(user, runId) {
  const rel = path.join("feedback", sanitizeUser(user), `${runId}.json`);
  if (!inside(visualizerPath("feedback"), visualizerPath(rel))) {
    throw Object.assign(new Error("Invalid feedback path"), { status: 400 });
  }
  return rel;
}

// Per-run annotation activity across all users — distinct reviewers + total
// annotations — so the run list can nudge people toward under-reviewed logs.
function annotationStats(runId) {
  const base = visualizerPath("annotations");
  let annotatorCount = 0;
  let annotationCount = 0;
  try {
    for (const entry of readdirSync(base, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const file = path.join(base, entry.name, `${runId}.json`);
      if (!existsSync(file)) continue;
      try {
        const data = JSON.parse(readFileSync(file, "utf8"));
        const n = Object.keys(data || {}).length;
        if (n > 0) { annotatorCount += 1; annotationCount += n; }
      } catch { /* skip unreadable file */ }
    }
  } catch { /* no annotations dir yet */ }
  return { annotatorCount, annotationCount };
}

async function readRequestJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = Buffer.concat(chunks).toString("utf8");
  return body ? JSON.parse(body) : {};
}

function parseIdeaYaml(text) {
  const field = (name) => {
    const match = text.match(new RegExp(`^\\s*${name}:\\s*(.*)$`, "m"));
    return match ? match[1].replace(/^['"]|['"]$/g, "").trim() : "";
  };
  const quotedMultilineField = (name) => {
    const match = text.match(new RegExp(`^\\s*${name}:\\s*'([\\s\\S]*?)'\\s*$`, "m"));
    return match ? match[1].replace(/\s+/g, " ").trim() : "";
  };
  const block = (name) => {
    const lines = text.split(/\r?\n/);
    const start = lines.findIndex((line) => line.trim() === `${name}:`);
    if (start === -1) return "";
    const out = [];
    for (let i = start + 1; i < lines.length; i += 1) {
      const line = lines[i];
      if (/^\s{2}\w/.test(line) && !line.includes(": '")) break;
      if (line.trim()) out.push(line.trim());
    }
    return out.join(" ").replace(/^['"]|['"]$/g, "").trim();
  };
  return {
    title: field("title"),
    domain: field("domain"),
    hypothesis: quotedMultilineField("hypothesis") || block("hypothesis") || field("hypothesis"),
    author: field("author"),
    source: field("source"),
    repoUrl: field("github_repo_url"),
  };
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length) return { columns: [], rows: [] };
  const split = (line) => {
    const cells = [];
    let cell = "";
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const char = line[i];
      if (char === '"' && line[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') {
        quoted = !quoted;
      } else if (char === "," && !quoted) {
        cells.push(cell);
        cell = "";
      } else {
        cell += char;
      }
    }
    cells.push(cell);
    return cells;
  };
  const columns = split(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const cells = split(line);
    return Object.fromEntries(columns.map((column, index) => [column, cells[index] ?? ""]));
  });
  return { columns, rows };
}

async function exists(relativePath, run = DEFAULT_RUN) {
  try {
    await stat(safeRunPath(relativePath, run));
    return true;
  } catch {
    return false;
  }
}

// Heavy / irrelevant directories that are never run artifacts but bloat the walk and can
// carry BROKEN SYMLINKS (e.g. a copied virtualenv's bin/python pointing at an interpreter
// that doesn't exist on this host) — skip them outright.
const LISTFILES_SKIP_DIRS = new Set([".git", ".venv", "venv", "node_modules", "__pycache__", ".idea-explorer"]);

async function listFiles(relativeDir = "", maxDepth = 4, run = DEFAULT_RUN) {
  const root = safeRunPath(relativeDir, run);
  const out = [];
  async function walk(dir, depth) {
    if (depth > maxDepth) return;
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (LISTFILES_SKIP_DIRS.has(entry.name)) continue;
      const full = path.join(dir, entry.name);
      const rel = path.relative(run.dir, full);
      if (entry.isDirectory()) {
        await walk(full, depth + 1);
      } else {
        // stat() follows symlinks; a broken one throws ENOENT. Skip it rather than let a
        // single dangling link crash the entire run summary.
        let info;
        try { info = await stat(full); } catch { continue; }
        out.push({
          path: rel,
          name: entry.name,
          group: rel.split(path.sep)[0],
          extension: path.extname(entry.name).toLowerCase(),
          size: info.size,
          mtimeMs: info.mtimeMs,
          modifiedAt: info.mtime.toISOString(),
        });
      }
    }
  }
  await walk(root, 0);
  return out.sort((a, b) => a.path.localeCompare(b.path));
}

async function runFileInfo(relativePath, run = DEFAULT_RUN) {
  try {
    const info = await stat(safeRunPath(relativePath, run));
    return {
      path: relativePath,
      exists: true,
      size: info.size,
      mtimeMs: info.mtimeMs,
      modifiedAt: info.mtime.toISOString(),
    };
  } catch {
    return { path: relativePath, exists: false, size: 0, mtimeMs: 0, modifiedAt: null };
  }
}

function pipelineStatusValue(pipeline = {}) {
  const text = JSON.stringify(pipeline || {}).toLowerCase();
  if (pipeline.failed === true || pipeline.status === "failed" || pipeline.state === "failed" || /"failed"|"error"|traceback|exception/.test(text)) return "failed";
  if (pipeline.completed === true || pipeline.status === "completed" || pipeline.state === "completed") return "completed";
  return "";
}

async function detectRunStatus(run = DEFAULT_RUN, artifacts = null) {
  const processingStatus = await readVisualizerJson(path.join("runs", run.id, "processing-status.json"), null);
  const hasRawRepoFolder = existsSync(run.dir);
  const hasIdea = await exists(".neurico/idea.yaml", run);
  const pipeline = await readJson(".neurico/pipeline_state.json", {}, run);
  const pipelineStatus = pipelineStatusValue(pipeline);
  const files = artifacts || await listFiles("", 3, run);
  const has = (name) => files.some((file) => file.path === name || file.path.endsWith(`/${name}`));
  const hasGroup = (group) => files.some((file) => file.group === group);
  const hasCanonical = await exists("canonical_trajectory.json", run)
    || existsSync(visualizerPath("runs", run.id, "canonical_trajectory.json"));
  const hasWorldModel = await exists("world_model.json", run)
    || existsSync(visualizerPath("runs", run.id, "world_model.json"));
  const hasReview = await exists("decision-review.json", run)
    || existsSync(visualizerPath("runs", run.id, "decision-review.json"));
  const annotationActivity = annotationStats(run.id);
  const hasAnnotations = annotationActivity.annotationCount > 0
    || existsSync(visualizerPath("runs", run.id, "annotations"))
    || existsSync(visualizerPath("runs", run.id, "annotations.json"));
  const hasFinalArtifacts = has("REPORT.md") || hasGroup("paper_draft") || hasGroup("results");
  const hasLogs = hasGroup("logs");
  const logText = (await Promise.all(
    files
      .filter((file) => file.group === "logs" && TEXT_EXTENSIONS.has(file.extension) && file.size < 200_000)
      .slice(-5)
      .map((file) => readText(file.path, "", run))
  )).join("\n").toLowerCase();

  let status = "raw_only";
  if (pipelineStatus === "failed") status = "failed";
  else if (hasCanonical && hasWorldModel && hasReview && hasFinalArtifacts && hasAnnotations) status = "completed";
  else if (hasCanonical && hasWorldModel && hasReview && hasFinalArtifacts) status = "annotation_ready";
  else if (hasCanonical && hasWorldModel) status = "world_model_ready";
  else if (hasCanonical) status = "canonical_ready";
  else if (/traceback|exception|failed|fatal error/.test(logText)) status = "failed";
  else if (hasRawRepoFolder && (hasIdea || Object.keys(pipeline || {}).length || hasLogs || hasFinalArtifacts)) status = "processing_needed";
  if (processingStatus?.status) status = processingStatus.status;

  return {
    status,
    modeLabel: status === "completed" ? "Processing status: completed"
      : status === "annotation_ready" ? "Annotation ready"
      : status === "fallback_review_ready" ? "Fallback review ready"
      : status === "git_sync_failed" ? "Git sync failed"
      : status === "world_model_failed" ? "World model failed"
      : status === "literature_ready" ? "Literature ready"
      : status === "raw_synced" ? "Raw synced"
      : status === "world_model_ready" ? "Processing status: world_model_ready"
      : status === "canonical_ready" ? "Canonical ready"
      : status === "processing_needed" ? "Processing status: processing_needed"
      : status === "raw_only" ? "Processing status: raw_only"
      : status === "failed" ? "Failed"
      : "Waiting for data",
    processingStatus,
    hasInterventionAdapter: Boolean(pipeline?.intervention_adapter || pipeline?.interventionAdapter || pipeline?.interactive_adapter),
    pipelineState: pipelineStatus || pipeline.status || pipeline.state || "",
    signals: {
      pipelineState: Object.keys(pipeline || {}).length > 0,
      rawRepoFolder: hasRawRepoFolder,
      ideaYaml: hasIdea,
      logs: hasGroup("logs"),
      paperDraft: hasGroup("paper_draft"),
      results: hasGroup("results"),
      canonicalTrajectory: Boolean(hasCanonical),
      worldModel: Boolean(hasWorldModel),
      decisionReview: Boolean(hasReview),
      findingReview: Boolean(existsSync(visualizerPath("runs", run.id, "finding-review.json"))),
      literatureSources: Boolean(existsSync(visualizerPath("runs", run.id, "literature-sources.json"))),
      annotations: Boolean(hasAnnotations),
    },
  };
}

function eventField(source = {}, keys = [], fallback = "") {
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && String(value).trim()) return value;
  }
  return fallback;
}

function normalizeEventObject(item = {}, index = 0, source = "live") {
  const raw = item.raw && typeof item.raw === "object" ? { ...item.raw, ...item } : item;
  const text = eventField(raw, ["summary", "_text", "message", "rawPreview", "content", "text"], "");
  const artifacts = raw.artifact_refs || raw.artifactRefs || raw.artifacts || raw.artifactIds || raw.artifact_ids || [];
  return {
    event_id: String(eventField(raw, ["event_id", "eventId", "_id", "id"], `${source}:${index + 1}`)),
    timestamp: eventField(raw, ["timestamp", "createdAt", "time", "ts"], ""),
    stage: eventField(raw, ["stage", "phase", "pipeline_stage"], "unknown"),
    agent: eventField(raw, ["agent", "agent_name", "actor", "role"], "unknown"),
    event_type: eventField(raw, ["event_type", "eventType", "_type", "type"], "event"),
    status: eventField(raw, ["status", "state"], ""),
    summary: String(text || eventField(raw, ["title", "name"], "Live event")).replace(/\s+/g, " ").slice(0, 600),
    current_plan: eventField(raw, ["current_plan", "currentPlan", "plan"], ""),
    recent_evidence: raw.recent_evidence || raw.recentEvidence || [],
    next_action: eventField(raw, ["next_action", "nextAction", "proposedNextAction"], ""),
    artifact_refs: Array.isArray(artifacts) ? artifacts : [artifacts].filter(Boolean),
    raw_trace_ref: eventField(raw, ["raw_trace_ref", "rawTraceRef", "relative_path", "path", "file"], source),
  };
}

function parseJsonl(text, source) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      try { return normalizeEventObject(JSON.parse(line), index, source); }
      catch { return normalizeEventObject({ summary: line, raw_trace_ref: source }, index, source); }
    });
}

async function normalizeLiveEvents(run = DEFAULT_RUN) {
  const events = [];
  const canonicalRaw = await readJson("canonical_trajectory.json", null, run);
  const canonicalViz = await readVisualizerJson(path.join("runs", run.id, "canonical_trajectory.json"), null);
  const canonical = canonicalRaw || canonicalViz;
  const canonicalEvents = Array.isArray(canonical?.events) ? canonical.events : [];
  canonicalEvents.forEach((event, index) => events.push(normalizeEventObject(event, index, "canonical_trajectory.json")));

  const explicitJsonl = await readText("events.jsonl", "", run);
  if (explicitJsonl) events.push(...parseJsonl(explicitJsonl, "events.jsonl"));

  const files = await listFiles("logs", 2, run).catch(() => []);
  for (const file of files.filter((entry) => entry.extension === ".jsonl").slice(-20)) {
    events.push(...parseJsonl(await readText(file.path, "", run), file.path));
  }

  const pipeline = await readJson(".neurico/pipeline_state.json", null, run);
  if (pipeline) {
    events.push(normalizeEventObject({
      id: "pipeline_state",
      timestamp: pipeline.updated_at || pipeline.updatedAt || pipeline.started_at || "",
      stage: pipeline.current_stage || pipeline.active_stage || pipeline.stage || "pipeline",
      agent: "neurico",
      type: "pipeline_state",
      status: pipeline.status || pipeline.state || "",
      summary: pipeline.message || pipeline.summary || pipeline.status || pipeline.state || "Pipeline state updated",
      current_plan: pipeline.current_plan || pipeline.plan || "",
      next_action: pipeline.next_action || "",
      raw_trace_ref: ".neurico/pipeline_state.json",
    }, events.length, ".neurico/pipeline_state.json"));
  }

  const seen = new Set();
  return events.filter((event) => {
    const key = `${event.event_id}::${event.raw_trace_ref}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isOutputArtifact(file = {}) {
  const p = String(file.path || "").toLowerCase();
  if (/^report\.md$|\/report\.md$/.test(p)) return true;
  return /^(paper_draft|results|figures|tables)\//.test(p)
    || /(^|\/)(metrics?|summary|result|report|draft|figure|plot|table)[^/]*\.(md|txt|json|csv|tex|pdf|png|jpg|jpeg|svg)$/i.test(file.path || "");
}

async function buildRunStatus(run = DEFAULT_RUN) {
  const artifacts = await listFiles("", 3, run);
  const runStatus = await detectRunStatus(run, artifacts);
  const liveEvents = await normalizeLiveEvents(run);
  const outputArtifacts = artifacts.filter(isOutputArtifact);
  const latestMtimeMs = Math.max(
    0,
    ...artifacts.map((file) => file.mtimeMs || 0),
    ...[
      await runFileInfo(".neurico/pipeline_state.json", run),
      await runFileInfo("canonical_trajectory.json", run),
      await runFileInfo("events.jsonl", run),
    ].map((file) => file.mtimeMs || 0)
  );
  return {
    runId: run.id,
    runStatus,
    liveEvents,
    liveSummary: {
      eventCount: liveEvents.length,
      artifactCount: outputArtifacts.length,
      latestEventId: liveEvents[liveEvents.length - 1]?.event_id || "",
      latestMtimeMs,
      checkedAt: new Date().toISOString(),
    },
    outputArtifacts,
  };
}

async function fileChecksum(relativePath, run = DEFAULT_RUN) {
  try {
    const data = await readFile(safeRunPath(relativePath, run));
    return crypto.createHash("sha256").update(data).digest("hex");
  } catch {
    return null;
  }
}

async function buildRunManifest(record, run = null, artifacts = null) {
  const ctx = run || { id: record.run_id, dir: record.source_workspace };
  const files = artifacts || await listFiles("", 4, ctx).catch(() => []);
  const has = (rel) => files.some((file) => file.path === rel || file.path.startsWith(`${rel.replace(/\/$/, "")}/`));
  const mapIf = (key, rel) => has(rel) || files.some((file) => file.path === rel) ? [key, rel] : null;
  const artifactPairs = [
    mapIf("idea", ".neurico/idea.yaml"),
    mapIf("pipeline_state", ".neurico/pipeline_state.json"),
    mapIf("pipeline_results", ".neurico/pipeline_results.json"),
    mapIf("report", "REPORT.md"),
    mapIf("planning", "planning.md"),
    mapIf("literature_review", "literature_review.md"),
    mapIf("resources", "resources.md"),
    mapIf("logs", "logs/"),
    mapIf("results", "results/"),
    mapIf("figures", "figures/"),
    mapIf("notebooks", "notebooks/"),
    mapIf("code", "code/"),
    mapIf("datasets", "datasets/"),
    mapIf("papers", "papers/"),
    mapIf("paper_draft", "paper_draft/"),
  ].filter(Boolean);
  const status = await detectRunStatus(ctx, files).catch(() => ({ status: "raw_only" }));
  return {
    schema_version: 1,
    run_id: record.run_id,
    idea_id: record.idea_id || "",
    provider: record.provider || "",
    source: record.source || "hypogenic-hub",
    source_workspace: ctx.dir,
    pipeline_status: record.pipeline_status || status.pipelineState || "",
    import_status: "ready",
    basic_index_status: "ready",
    world_model_status: record.world_model_status || "queued",
    imported_at: record.imported_at || new Date().toISOString(),
    updated_at: new Date().toISOString(),
    artifacts: Object.fromEntries(artifactPairs),
  };
}

function artifactPreviewType(file) {
  if (/\.(png|jpg|jpeg|gif|svg)$/i.test(file.path)) return "image";
  if (/\.pdf$/i.test(file.path)) return "pdf";
  if (TEXT_EXTENSIONS.has(file.extension)) return "text";
  return "binary";
}

async function buildBasicIndex(record, run = null) {
  const ctx = run || { id: record.run_id, dir: record.source_workspace };
  const artifacts = await listFiles("", 5, ctx).catch(() => []);
  const events = await normalizeLiveEvents(ctx).catch(() => []);
  const pipelineState = await readJson(".neurico/pipeline_state.json", {}, ctx);
  const pipelineResults = await readJson(".neurico/pipeline_results.json", {}, ctx);
  const ideaRaw = await readText(".neurico/idea.yaml", "", ctx);
  const reportRaw = await readText("REPORT.md", "", ctx);
  const transcriptDigest = events.map((event) => `${event.event_id} ${event.stage} ${event.event_type} ${event.summary}`).join("\n").slice(0, 50000);
  const keyInputs = [".neurico/idea.yaml", ".neurico/pipeline_state.json", ".neurico/pipeline_results.json", "REPORT.md"];
  const inputChecksums = {};
  for (const rel of keyInputs) {
    const checksum = await fileChecksum(rel, ctx);
    if (checksum) inputChecksums[rel] = checksum;
  }
  const fingerprint = contentFingerprint({
    inputChecksums,
    pipelineState,
    pipelineResults,
    transcriptDigest,
    reportDigest: crypto.createHash("sha256").update(reportRaw).digest("hex"),
    promptVersion: "deterministic-basic-index-v1",
    codeVersion: VISUALIZER_VERSION,
    schemaVersion: 1,
  });
  const index = {
    schema_version: 1,
    run_id: record.run_id,
    idea: parseIdeaYaml(ideaRaw),
    pipeline_state: pipelineState,
    pipeline_results: pipelineResults,
    events,
    artifacts: artifacts.map((file, index) => ({
      artifact_id: `artifact-${index + 1}`,
      path: file.path,
      name: file.name,
      group: file.group,
      extension: file.extension,
      size: file.size,
      modified_at: file.modifiedAt,
      preview_type: artifactPreviewType(file),
    })),
    errors: events.filter((event) => /error|failed|traceback|exception/i.test(`${event.status} ${event.summary} ${event.event_type}`)),
    reports: artifacts.filter((file) => /(^|\/)(REPORT|report|planning|literature_review|resources)\.(md|txt)$/i.test(file.path)),
    results: artifacts.filter((file) => /^(results|figures|paper_draft)\//.test(file.path)),
    generated_at: new Date().toISOString(),
    fingerprint,
  };
  await writeVisualizerJson(path.join("indexes", `${record.run_id}.json`), index);
  await writeVisualizerJson(path.join("runs", record.run_id, "canonical_trajectory.json"), {
    runId: record.run_id,
    summary: {
      eventCount: index.events.length,
      artifactCount: index.artifacts.length,
      annotationCandidateCount: 0,
      generatedAt: index.generated_at,
    },
    events: index.events,
    artifacts: index.artifacts,
  });
  return index;
}

async function enqueueProcessingJob(runId, jobType, options = {}) {
  const jobs = await readJobs();
  const active = jobs.jobs.find((job) => job.run_id === runId && job.job_type === jobType && ["queued", "running", "partially_ready", "failed_retryable"].includes(job.status));
  if (active && !options.force) return active;
  const now = new Date().toISOString();
  const job = {
    job_id: uuid("job"),
    run_id: runId,
    job_type: jobType,
    executor: process.env.NEURICO_EXECUTOR || "local",
    status: "queued",
    attempts: 0,
    max_attempts: Number(process.env.NEURICO_JOB_MAX_ATTEMPTS || 3),
    next_attempt_at: now,
    created_at: now,
    updated_at: now,
    stages: WORLD_MODEL_STAGES.map((stage) => ({ stage, status: "queued", attempts: 0 })),
  };
  jobs.jobs.push(job);
  await writeJobs(jobs);
  await audit("job_queued", "system", { run_id: runId, job_id: job.job_id, job_type: jobType });
  if (AUTOSPAWN_WORKER && jobType === "world_model") spawnProcessingWorker(job.job_id);
  return job;
}

function spawnProcessingWorker(jobId) {
  const script = path.join(__dirname, "tools", "processing_worker.js");
  if (!existsSync(script)) return;
  const child = spawn("node", [script, "--job-id", jobId], {
    cwd: __dirname,
    detached: true,
    stdio: "ignore",
    env: { ...process.env, NEURICO_DATA_DIR: DATA_DIR },
  });
  child.unref();
}

async function importRunEvent(req) {
  requireInternal(req);
  await ensurePlatformStorage();
  const body = await readJsonBody(req);
  const runId = assertRunId(body.run_id);
  const workspace = parseWorkspaceUri(body.workspace_uri);
  if (!existsSync(workspace)) throw Object.assign(new Error("Workspace does not exist"), { status: 400, code: "workspace_missing" });
  if (!looksLikeRun(workspace)) throw Object.assign(new Error("Workspace is missing .neurico/ or logs/"), { status: 400, code: "invalid_workspace" });

  const now = new Date().toISOString();
  const catalog = await readCatalog();
  const existing = catalog.runs.find((item) => item.run_id === runId);
  const next = {
    ...(existing || {}),
    run_id: runId,
    idea_id: String(body.idea_id || existing?.idea_id || ""),
    provider: String(body.provider || existing?.provider || ""),
    source: "hypogenic-hub",
    source_workspace: workspace,
    workspace_uri: body.workspace_uri,
    pipeline_status: String(body.pipeline_status || existing?.pipeline_status || ""),
    completed_at: body.completed_at || existing?.completed_at || null,
    import_status: "ready",
    basic_index_status: "ready",
    world_model_status: existing?.world_model_status || "queued",
    researcher_id: body.researcher_id || existing?.researcher_id || "",
    researcher_access: body.researcher_access ?? existing?.researcher_access ?? true,
    imported_at: existing?.imported_at || now,
    updated_at: now,
    last_event: body.event || "run.imported",
  };
  if (existing) Object.assign(existing, next);
  else catalog.runs.push(next);
  await writeCatalog(catalog);

  const run = { id: runId, dir: workspace };
  const artifacts = await listFiles("", 5, run);
  const manifest = await buildRunManifest(next, run, artifacts);
  await writeVisualizerJson(path.join("manifests", `${runId}.json`), manifest);
  const index = await buildBasicIndex(next, run);
  const job = await enqueueProcessingJob(runId, "world_model");
  await enqueueProcessingJob(runId, "paper_highlights");
  await audit("run_imported", "internal", { run_id: runId, event: body.event || "", idempotent_update: Boolean(existing) });
  return { ok: true, run: next, manifest, basic_index: { event_count: index.events.length, artifact_count: index.artifacts.length, fingerprint: index.fingerprint }, world_model_job: job };
}

function commandLabel(command = "") {
  const cleaned = command.replace(/^\/bin\/bash\s+-lc\s+/, "").replace(/^['"]|['"]$/g, "");
  const first = cleaned.trim().split(/\s+/)[0] || "command";
  const categories = [
    [/^(rg|grep|find|ls|pwd|du|wc|sed|cat|head|tail|nl)$/i, "inspect"],
    [/^(python|python3|uv|pip|node|npm)$/i, "execute"],
    [/^(curl|wget)$/i, "network"],
    [/^(git)$/i, "git"],
    [/^(mkdir|cp|mv|rm|touch|chmod)$/i, "filesystem"],
    [/^(source|test)$/i, "environment"],
  ];
  const match = categories.find(([pattern]) => pattern.test(first));
  return {
    label: first,
    category: match ? match[1] : "command",
    preview: cleaned.length > 140 ? `${cleaned.slice(0, 137)}...` : cleaned,
  };
}

function summarizeTranscriptItem(item = {}) {
  if (item.type === "agent_message") {
    const text = item.text || "";
    return {
      kind: "agent_message",
      group: "agent",
      label: text.split(/\s+/).slice(0, 10).join(" ") || "Agent message",
      detail: text,
    };
  }

  if (item.type === "command_execution") {
    const command = commandLabel(item.command || "");
    const output = item.aggregated_output || "";
    return {
      kind: "command_execution",
      group: command.category,
      label: command.label,
      detail: command.preview,
      outputPreview: output.length > 240 ? `${output.slice(0, 237)}...` : output,
      exitCode: item.exit_code,
    };
  }

  if (item.type === "file_change") {
    const paths = [
      item.path,
      item.file,
      item.file_path,
      item.relative_path,
      ...(Array.isArray(item.files) ? item.files : []),
    ].filter(Boolean);
    return {
      kind: "file_change",
      group: "artifact",
      label: paths[0] ? path.basename(String(paths[0])) : "File change",
      detail: paths.join(", ") || JSON.stringify(item).slice(0, 240),
    };
  }

  if (item.type === "web_search") {
    const query = item.query || item.search_query || item.text || "Web search";
    return {
      kind: "web_search",
      group: "research",
      label: "Web search",
      detail: String(query),
    };
  }

  if (item.type === "todo_list") {
    return {
      kind: "todo_list",
      group: "planning",
      label: "Todo update",
      detail: JSON.stringify(item.todos || item.items || item).slice(0, 240),
    };
  }

  return {
    kind: item.type || "item",
    group: "other",
    label: item.type || "Item",
    detail: JSON.stringify(item).slice(0, 240),
  };
}

async function parseTranscriptFlow(run = DEFAULT_RUN) {
  let entries = [];
  try {
    entries = await readdir(safeRunPath("logs", run), { withFileTypes: true });
  } catch {
    return { files: [], nodes: [], edges: [], stats: {} };
  }

  const pipelineState = await readJson(".neurico/pipeline_state.json", {}, run);
  const pipelineResults = await readJson(".neurico/pipeline_results.json", {}, run);
  const pipelineStages = {
    ...(pipelineState.stages || {}),
    ...(pipelineResults.stages || {}),
  };
  const stageTranscriptOrder = Object.values(pipelineStages)
    .filter((stage) => stage.outputs?.transcript_file || stage.transcript_file)
    .sort((a, b) => {
      const timeA = a.started_at || a.completed_at || "";
      const timeB = b.started_at || b.completed_at || "";
      return String(timeA).localeCompare(String(timeB));
    })
    .map((stage) => path.basename(stage.outputs?.transcript_file || stage.transcript_file));
  const transcriptRank = new Map(stageTranscriptOrder.map((name, index) => [name, index]));

  const transcriptFiles = entries
    .filter((entry) => entry.isFile() && /transcript.*\.jsonl$|.*transcript.*\.jsonl$/i.test(entry.name))
    .map((entry) => path.join("logs", entry.name))
    .sort((a, b) => {
      const rankA = transcriptRank.get(path.basename(a)) ?? Number.MAX_SAFE_INTEGER;
      const rankB = transcriptRank.get(path.basename(b)) ?? Number.MAX_SAFE_INTEGER;
      if (rankA !== rankB) return rankA - rankB;
      return a.localeCompare(b);
    });

  const nodes = [];
  const edges = [];
  const byItem = new Map();
  const stats = { files: transcriptFiles.length, eventTypes: {}, itemTypes: {}, statuses: {} };

  for (const relativePath of transcriptFiles) {
    const text = await readText(relativePath, "", run);
    let previousNodeId = null;
    let sequence = 0;
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim().startsWith("{")) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        continue;
      }

      stats.eventTypes[event.type] = (stats.eventTypes[event.type] || 0) + 1;
      const item = event.item;
      if (!item) continue;

      const summary = summarizeTranscriptItem(item);
      const status = item.status || (event.type.endsWith(".completed") ? "completed" : "recorded");
      stats.itemTypes[summary.kind] = (stats.itemTypes[summary.kind] || 0) + 1;
      stats.statuses[status] = (stats.statuses[status] || 0) + 1;

      const lifecycleKey = `${relativePath}:${item.id || `${summary.kind}:${sequence}`}`;
      if (event.type === "item.started") {
        byItem.set(lifecycleKey, nodes.length);
      }

      const nodeId = `${relativePath}:${sequence}:${item.id || nodes.length}`;
      nodes.push({
        id: nodeId,
        source: relativePath,
        sequence,
        eventType: event.type,
        itemId: item.id || null,
        status,
        ...summary,
      });

      if (previousNodeId) {
        edges.push({
          id: `${previousNodeId}->${nodeId}`,
          source: previousNodeId,
          target: nodeId,
          kind: "sequence",
          label: "next",
        });
      }

      if (event.type === "item.completed" && byItem.has(lifecycleKey)) {
        const startNode = nodes[byItem.get(lifecycleKey)];
        if (startNode && startNode.id !== nodeId) {
          edges.push({
            id: `${startNode.id}->${nodeId}:lifecycle`,
            source: startNode.id,
            target: nodeId,
            kind: "lifecycle",
            label: status,
          });
        }
      }

      previousNodeId = nodeId;
      sequence += 1;
    }
  }

  return { files: transcriptFiles, nodes, edges, stats };
}

function defaultLayoutFromElements(elements) {
  return {
    nodes: Object.fromEntries(elements.map((element) => [element.id, { x: element.x, y: element.y }])),
  };
}

async function buildVisualizerData(transcriptFlow, artifacts = [], run = DEFAULT_RUN) {
  const runDataDir = path.join("runs", run.id);
  await writeVisualizerJson("element-library.json", ELEMENT_LIBRARY);
  const elementLibrary = await readVisualizerJson("element-library.json", ELEMENT_LIBRARY);
  // The flow chart is generated by the reconstruction pass (from prompts/flow-chart-rules.md)
  // into flow-llm.json. Until that exists, the flow is empty — no deterministic skeleton.
  const llmFlow = await readVisualizerJson(path.join(runDataDir, "flow-llm.json"), null);
  const flowElements = llmFlow && Array.isArray(llmFlow.elements) ? llmFlow.elements : [];
  const flowGraph = { nodes: flowElements.map((element) => element.id), edges: (llmFlow && llmFlow.edges) || [] };
  const defaultLayout = defaultLayoutFromElements(flowElements);
  await writeVisualizerJson(path.join(runDataDir, "flow-elements.json"), flowElements);
  await writeVisualizerJson(path.join(runDataDir, "flow-graph.json"), flowGraph);
  const layoutPath = path.join(runDataDir, "layout.json");
  const existingLayout = await readVisualizerJson(layoutPath, null);
  const defaultIds = Object.keys(defaultLayout.nodes).sort().join("|");
  const existingIds = Object.keys(existingLayout?.nodes || {}).sort().join("|");
  if (!existingLayout || existingIds !== defaultIds) {
    await writeVisualizerJson(layoutPath, defaultLayout);
  }
  await writeVisualizerJsonIfMissing(path.join(runDataDir, "annotations.json"), {});
  return {
    runId: run.id,
    dataDir: path.join("data", runDataDir),
    elementLibrary,
    flowElements,
    flowGraph,
    layout: await readVisualizerJson(path.join(runDataDir, "layout.json"), defaultLayout),
    annotations: await readVisualizerJson(path.join(runDataDir, "annotations.json"), {}),
  };
}

async function updateVisualizerLayout(req) {
  const body = await readRequestJson(req);
  const run = resolveRun(body.runId);
  const runDataDir = path.join("runs", run.id);
  const layoutPath = path.join(runDataDir, "layout.json");

  if (body.reset) {
    const llmFlow = await readVisualizerJson(path.join(runDataDir, "flow-llm.json"), null);
    const elements = llmFlow && Array.isArray(llmFlow.elements) ? llmFlow.elements : [];
    const defaultLayout = defaultLayoutFromElements(elements);
    await writeVisualizerJson(layoutPath, defaultLayout);
    return defaultLayout;
  }

  const layout = await readVisualizerJson(layoutPath, { nodes: {} });
  if (body.nodeId && Number.isFinite(body.x) && Number.isFinite(body.y)) {
    layout.nodes = layout.nodes || {};
    layout.nodes[body.nodeId] = { x: body.x, y: body.y };
    await writeVisualizerJson(layoutPath, layout);
  }
  return layout;
}

// The five reviewer questions the PI wants every run graded against. Each
// reconstructed decision point is filed under exactly one of these.
const DECISION_QUESTIONS = {
  update_user: { key: "update_user", label: "Update the user?", detail: "A moment where the user arguably should have been told what was happening." },
  interrupt: { key: "interrupt", label: "Interrupt next action?", detail: "A moment where continuing without a human check risked wasted or misleading work." },
  uncertainty: { key: "uncertainty", label: "Surface uncertainty?", detail: "Missing information or an unverified assumption that should have been surfaced." },
  crux: { key: "crux", label: "Decision crux?", detail: "The factor that most affects whether the run's conclusion can be trusted." },
  feedback: { key: "feedback", label: "Feedback incorporated?", detail: "Whether a later step correctly took prior guidance or findings into account." },
};

function shortTitle(text) {
  const first = String(text || "").split(/(?<=[.!?])\s+/)[0] || String(text || "");
  const short = first.split(/\s+/).slice(0, 9).join(" ").replace(/[.,;:]$/, "");
  return short ? short.charAt(0).toUpperCase() + short.slice(1) : "Decision point";
}

function titleCasePhase(phase) {
  const cleaned = String(phase || "").replace(/_/g, " ").trim();
  return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : "Decision";
}

function buildWorldModelGraph(worldModel) {
  const collections = [
    ["hypotheses", "hypothesis", (item) => item.statement],
    ["experiments", "experiment", (item) => item.rationale || item.result],
    ["findings", "finding", (item) => item.text],
    ["decisions", "decision", (item) => item.question || item.chosen],
    ["assessments", "assessment", (item) => item.situation || item.decision_pending],
    ["incidents", "incident", (item) => item.detail],
  ];
  const items = [];
  for (const [collection, type, summary] of collections) {
    for (const item of worldModel[collection] || []) {
      if (!item?.id) continue;
      items.push({
        id: item.id,
        type,
        summary: summary(item) || item.id,
        status: item.status || item.kind || null,
        evidence: item.evidence || [],
        links: Array.isArray(item.links) ? item.links : [],
        incoming: [],
      });
    }
  }
  const byId = new Map(items.map((item) => [item.id, item]));
  for (const source of items) {
    for (const link of source.links) {
      const target = byId.get(link.target);
      if (target) target.incoming.push({ ...link, source: source.id });
    }
  }

  const active = items.some((item) => item.links.length);
  const gaps = [];
  if (active) {
    for (const item of items) {
      if (item.type === "hypothesis" && ["supported", "refuted"].includes(item.status)) {
        const expected = item.status === "supported" ? "supports" : "refutes";
        if (!item.incoming.some((link) => link.relation === expected)) {
          gaps.push({ entityId: item.id, code: "hypothesis_result_unlinked", message: `No finding ${expected} this hypothesis.` });
        }
      }
      if (item.type === "experiment" && item.status === "done" &&
          !item.incoming.some((link) => link.relation === "produced_by")) {
        gaps.push({ entityId: item.id, code: "experiment_output_unlinked", message: "Completed experiment has no linked finding or incident." });
      }
    }
  }
  return { active, items, gaps };
}

// Map a reconstructed world_model.json into the frontend's decision-card shape.
// `review` is the Pass-2 PI-review overlay (decision-review.json): an object
// {runQuality, decisions:[{decisionId, importance, importanceRationale}]}.
// importance is set ENTIRELY by the reviewer (paper-reading) — the extractor no longer
// assigns it. shouldEngage stays Pass-1's own call.
function mapWorldModelDecisions(worldModel, review = null) {
  const reviewById = new Map(((review && Array.isArray(review.decisions) ? review.decisions : [])).map((entry) => [entry.decisionId, entry]));
  return (worldModel.decisions || []).map((decision, index) => {
    const id = decision.id || `D${index + 1}`;
    const r = reviewById.get(id);
    return {
      id,
      clock: index + 1,
      source: "world_model",
      question: titleCasePhase(decision.phase),
      decisionType: decision.by === "agent" ? "agent decision" : (decision.by || "decision"),
      phase: decision.phase || "",
      // v3 spine: the finding this fork serves ("global" if cross-cutting) and the
      // layer it sits in. These are the primary axes the decisions page groups by.
      finding: decision.finding || "global",
      layer: decision.layer || "",
      // Within-finding causal order assigned by the graph/sequence review pass; null
      // when no review has run, in which case the UI falls back to layer-lifecycle order.
      sequence: (typeof decision.sequence === "number") ? decision.sequence : null,
      // importance comes from the PI reviewer overlay; falls back to any legacy value,
      // else "medium" when no review has run.
      importance: r?.importance || decision.importance || "medium",
      title: decision.question || decision.chosen || "Decision",
      situation: "",
      choice: decision.chosen || "",
      // Full option set (chosen + alternatives) with provenance, for the reviewer's
      // preference picker. `source` distinguishes evidence-backed from inferred.
      options: (decision.options || [])
        .filter((option) => option && (option.text || typeof option === "string"))
        .map((option) => (typeof option === "string"
          ? { text: option, status: "alternative", source: null }
          : { text: option.text, status: option.status || "alternative", source: option.source || null })),
      // The chosen option verbatim (often fuller than `chosen`), used as the
      // evidence-highlight anchor fallback before rebuilt anchors exist.
      choiceVerbatim: (decision.options || []).find((o) => o && o.status === "chosen")?.text || decision.chosen || "",
      alternatives: (decision.options || [])
        .filter((option) => option && option.status !== "chosen")
        .map((option) => option.text || option)
        .filter(Boolean),
      crux: "",
      uncertainty: "",
      rationale: decision.statedRationale || decision.inferredRationale || decision.rationale || "",
      // The PI reviewer's one-line reason for this decision's importance.
      reviewer: r ? { rationale: r.importanceRationale || "" } : null,
      reviewerDisagrees: false,
      pass1ShouldEngage: Boolean(decision.shouldEngage),
      ranSolo: (decision.by || "agent") === "agent",
      shouldEngage: Boolean(decision.shouldEngage),
      severity: decision.shouldEngage ? "warning" : "info",
      status: "not_yet_checked",
      sourceRefs: (decision.evidence || []).map((ref) => ({
        file: ref.path || null,
        itemId: ref.itemId || null,
        note: ref.note || ref.type || null,
        anchor: ref.anchor || null,
      })),
      // Where (if anywhere) this decision is discussed in the written paper. The
      // resolved highlight box lives in paper_highlights.json, keyed by this id.
      paperRef: decision.paperRef || null,
      relatedErrorIds: r?.relatedErrors || decision.relatedErrors || [],
      relatedFlowNodes: [],
    };
  });
}

const { readAutoResearchState } = autoresearchReader({ safeRunPath, exists, readJson });

// Map a world_model.json into the Whiteboard's researchState shape. Validity/
// mismatch findings and unresolved incidents become the "needs attention" list.
function mapWorldModelState(worldModel, findingReview = null) {
  const warnings = [
    ...(worldModel.findings || []).filter((finding) => finding.kind === "note").map((finding) => finding.text),
    ...(worldModel.incidents || []).filter((incident) => incident.kind === "unresolved").map((incident) => incident.detail),
  ];
  const decisions = worldModel.decisions || [];
  // Attach the finding filter's show_by_default + reason to each finding. Only when an
  // overlay is present — absent → the field stays undefined and the UI shows everything.
  const reviewById = new Map(
    (findingReview && Array.isArray(findingReview.findings) ? findingReview.findings : [])
      .filter((entry) => entry && entry.id)
      .map((entry) => [entry.id, entry]));
  const findings = (worldModel.findings || []).map((finding) => {
    const review = reviewById.get(finding.id);
    return review
      ? { ...finding, show_by_default: review.show_by_default !== false, show_reason: review.reason || "" }
      : finding;
  });
  return {
    narrative: worldModel.narrative || "",
    currentBest: worldModel.current_best || "",
    crux: worldModel.crux || "",
    hypotheses: worldModel.hypotheses || [],
    findings,
    experiments: worldModel.experiments || [],
    openQuestions: worldModel.open_questions || [],
    // Optional, hand-authored-quality fields emitted by reconstruction v2+. The
    // whiteboard prefers these and falls back to derived values when absent, so
    // older world models render without a rebuild.
    abstract: worldModel.abstract || "",
    headline: worldModel.headline || "",
    keyFacts: worldModel.keyFacts || [],
    methodology: worldModel.methodology || [],
    futureWork: worldModel.future_work || [],
    consistencyWarnings: warnings,
    decisions,
    sections: worldModel.sections || {},
    fromWorldModel: true,
    counts: {
      decisionPoints: decisions.length,
      shouldEngage: decisions.filter((decision) => decision.shouldEngage).length,
    },
  };
}

// The platform's run picker: every built run (has a world_model.json) whose raw
// folder is also present, with light metadata + how much annotation activity it has
// already drawn (so users can spread out, avoiding the popular ones). Counts come
// from the shared annotations.json for now; per-user storage lands in a later stage.
function listBuiltRunIds() {
  const ids = new Set();
  try {
    readdirSync(visualizerPath("runs"), { withFileTypes: true })
      .filter((entry) => entry.isDirectory()
        && (
          existsSync(visualizerPath("runs", entry.name, "world_model.json"))
          || existsSync(visualizerPath("runs", entry.name, "canonical_trajectory.json"))
          || existsSync(visualizerPath("runs", entry.name, "processing-status.json"))
        ))
      .forEach((entry) => ids.add(entry.name));
  } catch { /* no built visualizer runs yet */ }
  const catalog = readVisualizerJsonSync(catalogPath(), { runs: [] });
  for (const item of catalog.runs || []) {
    if (item?.run_id) ids.add(item.run_id);
  }
  for (const name of listRuns()) ids.add(name);
  return [...ids].sort();
}

// How many decisions a reviewer actually SEES by default on the decisions page — the
// number worth advertising on the run-list card, not the full extracted total. Mirrors the
// UI default: key (high/critical) decisions whose finding is shown (claim-level) or global.
// Falls back to the total when no decision-review overlay exists (so it can't read 0).
function countDisplayedDecisions(wm, decisionReview, findingReview) {
  const decisions = Array.isArray(wm?.decisions) ? wm.decisions : [];
  if (!decisions.length) return 0;
  const importanceById = new Map(
    ((decisionReview && decisionReview.decisions) || [])
      .filter((e) => e && e.decisionId)
      .map((e) => [e.decisionId, e.importance]));
  if (!importanceById.size) return decisions.length;   // unreviewed → keep the total
  const shownByFinding = new Map(
    ((findingReview && findingReview.findings) || [])
      .filter((e) => e && e.id)
      .map((e) => [e.id, e.show_by_default !== false]));
  const hasFindingFilter = shownByFinding.size > 0;
  let shown = 0;
  for (const d of decisions) {
    const imp = importanceById.get(d.id) || d.importance;
    if (imp !== "high" && imp !== "critical") continue;          // routine → hidden by default
    const f = d.finding;
    const groupVisible = !hasFindingFilter || f === "global" || !shownByFinding.has(f) || shownByFinding.get(f);
    if (groupVisible) shown += 1;
  }
  return shown;
}

async function listStudyRuns() {
  const out = [];
  for (const runId of listBuiltRunIds()) {
    const rel = (name) => path.join("runs", runId, name);
    const wm = await readVisualizerJson(rel("world_model.json"), null);
    const canonical = await readVisualizerJson(rel("canonical_trajectory.json"), null);
    const manifest = await readVisualizerJson(path.join("manifests", `${runId}.json`), null);
    const basicIndex = await readVisualizerJson(path.join("indexes", `${runId}.json`), null);
    const decisionReview = await readVisualizerJson(rel("decision-review.json"), null);
    const findingReview = await readVisualizerJson(rel("finding-review.json"), null);
    const processingStatus = await readVisualizerJson(rel("processing-status.json"), null);
    const literatureSources = await readVisualizerJson(rel("literature-sources.json"), null);
    const { annotatorCount, annotationCount } = annotationStats(runId);
    let runStatus = null;
    try {
      runStatus = await detectRunStatus(resolveRun(runId));
    } catch {
      runStatus = null;
    }

    out.push({
      runId,
      title: (wm && (wm.headline || wm.runId))
        || (canonical && canonical.runId)
        || basicIndex?.idea?.title
        || manifest?.idea_id
        || runId,
      summary: (wm && wm.narrative)
        || (canonical && `Canonical trajectory: ${canonical.summary?.eventCount || 0} trace events, ${canonical.summary?.artifactCount || 0} artifacts`)
        || basicIndex?.idea?.hypothesis
        || "",
      decisionCount: countDisplayedDecisions(wm, decisionReview, findingReview),
      eventCount: canonical?.summary?.eventCount || 0,
      artifactCount: canonical?.summary?.artifactCount || 0,
      annotationCandidateCount: canonical?.summary?.annotationCandidateCount || 0,
      lastProcessedAt: processingStatus?.updatedAt || null,
      commit: processingStatus?.commit || "",
      processingStatus,
      literatureSourceCount: literatureSources?.sourceCount || (Array.isArray(literatureSources?.sources) ? literatureSources.sources.length : 0),
      annotationReady: ["annotation_ready", "fallback_review_ready", "completed"].includes(runStatus?.status || processingStatus?.status || ""),
      hasWorldModel: Boolean(wm),
      hasCanonicalTrajectory: Boolean(canonical),
      runStatus,
      annotatorCount,
      annotationCount,
      manifest,
  });
  }
  return out;
}

async function buildRunSummary(run = DEFAULT_RUN, user = null) {
  const ideaText = await readText(".neurico/idea.yaml", "", run);
  const idea = parseIdeaYaml(ideaText);
  const pipeline = await readJson(".neurico/pipeline_state.json", {}, run);
  const metricCsv = parseCsv(await readText("results/analysis/metric_summary.csv", "", run));
  const pairedCsv = parseCsv(await readText("results/analysis/paired_tests.csv", "", run));
  const artifacts = await listFiles("", 3, run);
  const liveState = await buildRunStatus(run);
  const transcriptFlow = await parseTranscriptFlow(run);
  const visualizerData = await buildVisualizerData(transcriptFlow, artifacts, run);
  // Annotations are per-user: load this reviewer's file (their own progress/verdicts),
  // not the shared one. saveAnnotation writes back to the same per-user file.
  if (user) {
    visualizerData.annotations = (await readVisualizerJson(annotationRel(user, run.id), {})) || {};
  }

  // A reconstructed world_model.json is the canonical, domain-general source for
  // the Whiteboard, Decisions, and Errors. Visualizer-owned override files
  // (decision-points.json / research-state.json) take precedence if hand-authored.
  // Without any of these the reviewer surfaces stay empty and the UI shows a
  // "not generated yet" placeholder — the visualizer never guesses a run's domain.
  const wmRel = (name) => path.join("runs", run.id, name);
  const worldModel = await readVisualizerJson(wmRel("world_model.json"), null);
  const decisionReview = await readVisualizerJson(wmRel("decision-review.json"), null);
  // Finding filter overlay (finding-review.json): {findings:[{id, show_by_default, reason}]}.
  // Marks which findings are claim-level (shown by default) vs routine (hidden behind a
  // toggle). Absent → every finding renders (fail-open to today's behavior).
  const findingReview = await readVisualizerJson(wmRel("finding-review.json"), null);
  const literatureSources = await readVisualizerJson(wmRel("literature-sources.json"), null);
  // Paper highlights: per-decision page + box resolved from paper_draft/main.pdf by
  // build_paper_highlights.py. The PDF itself is fetched lazily via /api/file.
  const paperHighlights = await readVisualizerJson(wmRel("paper_highlights.json"), null);
  const paperPdf = (await exists("paper_draft/main.pdf", run)) ? "paper_draft/main.pdf" : null;
  const decisionOverride = await readVisualizerJson(wmRel("decision-points.json"), null);
  const stateOverride = await readVisualizerJson(wmRel("research-state.json"), null);
  const canonicalTrajectory = await readVisualizerJson(wmRel("canonical_trajectory.json"), null);
  const autoresearch = await readAutoResearchState(run);

  let finalDecisionPoints = Array.isArray(decisionOverride) ? decisionOverride : [];
  let researchState = stateOverride || null;
  if (worldModel && Array.isArray(worldModel.decisions)) {
    finalDecisionPoints = mapWorldModelDecisions(worldModel, decisionReview);
    researchState = mapWorldModelState(worldModel, findingReview);
  }
  // Prefer the paper's ACTUAL abstract (LaTeX-stripped) over the reconstruction's
  // LLM-written one; the reconstructed abstract stays as the fallback for runs with
  // no paper_draft. Read from the raw run at serve time — no rebuild needed.
  if (researchState) {
    // Expand the paper's own \newcommand macros (e.g. \egeo → \textsc{e-geodesic}) before
    // stripping, so paper-specific symbols don't drop to gaps. Macros usually live in
    // \input{commands/...} preamble files, so follow main.tex's \input directives.
    const macros = await paperMacros(run);
    const paperAbstract = stripLatex(expandMacros(await readText("paper_draft/sections/abstract.tex", "", run), macros));
    if (paperAbstract) researchState.abstract = paperAbstract;
    // Front-page title: the paper's own \title{}. Falls back to the reconstructed headline
    // (handled UI-side) for runs with no paper_draft.
    const title = await paperTitle(run, macros);
    if (title) researchState.title = title;
  }
  // Architecture-level readiness — true for any NeuriCo run regardless of domain.
  // (Avoid run-specific filenames here: a run names its own scripts/metrics.)
  const hasIn = (dir, ext) => artifacts.some((file) => file.group === dir && file.extension === ext);
  const checks = [
    ["Idea metadata", await exists(".neurico/idea.yaml", run)],
    ["Pipeline state", await exists(".neurico/pipeline_state.json", run)],
    ["Experiment code", hasIn("src", ".py") || hasIn("code", ".py")],
    ["Results", artifacts.some((file) => file.group === "results")],
    ["Report", await exists("REPORT.md", run)],
    ["Paper draft", await exists("paper_draft/main.tex", run)],
    ["Figures", artifacts.some((file) => file.group === "figures")],
  ];

  return {
    runId: run.id,
    runDir: run.dir,
    idea,
    pipeline,
    metricTable: metricCsv,
    pairedTable: pairedCsv,
    artifacts,
    runStatus: liveState.runStatus,
    liveEvents: liveState.liveEvents,
    liveSummary: liveState.liveSummary,
    outputArtifacts: liveState.outputArtifacts,
    transcriptFlow,
    visualizerData,
    decisionPoints: finalDecisionPoints,
    researchState,
    // PI-review summary: the run-quality verdict (Pass 2).
    reviewSummary: (decisionReview && !Array.isArray(decisionReview)) ? {
      runQuality: decisionReview.runQuality || null,
    } : null,
    // The ≤5 decisions a reviewer scrutinizes against the abstract to decide whether to
    // trust the run — chosen by the abstract-only front-page selection call (lives on the
    // world model). The UI uses these when present, else falls back to top by importance.
    frontPageDecisions: Array.isArray(worldModel?.frontPageDecisions) ? worldModel.frontPageDecisions : [],
    canonicalTrajectory,
    literatureSources,
    autoresearch,
    paperPdf,
    paperHighlights: paperHighlights?.items || {},
    worldModelGraph: worldModel ? buildWorldModelGraph(worldModel) : null,
    fromWorldModel: Boolean(worldModel && Array.isArray(worldModel.decisions)),
    decisionQuestions: DECISION_QUESTIONS,
    checks: checks.map(([label, pass]) => ({ label, status: pass ? "pass" : "warn" })),
  };
}

function stringField(body, previous, field) {
  return typeof body[field] === "string" ? body[field] : (previous?.[field] || "");
}

const STEERBENCH_CATEGORICAL_FIELDS = [
  "steeringDecision",
  "cruxType",
  "feedbackIncorporation",
  "claimSupported",
  "evidenceSufficient",
];

const HIGH_IMPACT_TYPES = new Set([
  "results",
  "main_claim",
  "abstract_claim",
  "method_validity",
  "experiment_design",
  "statistical_inference",
  "baseline_control",
  "reproducibility",
  "conclusion",
  "research_direction",
]);

function normalizeImpactTypes(value) {
  const items = Array.isArray(value) ? value : String(value || "").split(",");
  const cleaned = items.map((item) => String(item || "").trim()).filter(Boolean);
  return cleaned.length ? [...new Set(cleaned)] : ["writing_only"];
}

function annotationEligibility(body = {}, previous = {}) {
  const impactType = normalizeImpactTypes(body.impactType || previous.impactType);
  const mustAnnotate = impactType.some((type) => HIGH_IMPACT_TYPES.has(type));
  const lowImpactOnly = impactType.every((type) => type === "writing_only" || type === "formatting_only");
  const uncertaintyHigh = /uncertain|unclear|not enough|expert/i.test(`${body.evidenceSufficient || ""} ${body.confidence || ""} ${body.reviewerComment || ""} ${body.rationale || ""}`)
    || Boolean(body.reviewerChecklist?.needsMoreEvidence);
  const needsExpertReview = Boolean(body.needsExpertReview || body.needsExpertAdjudication || (mustAnnotate && uncertaintyHigh));
  const autoFixCandidate = lowImpactOnly && !mustAnnotate;
  const route = body.annotationRoute || (needsExpertReview ? "expert_escalation" : autoFixCandidate ? "fix_request" : mustAnnotate ? "benchmark_annotation" : "dismissed");
  return {
    impactType,
    mustAnnotate,
    autoFixCandidate,
    needsExpertReview,
    fixability: body.fixability || (needsExpertReview ? "needs_expert_judgment" : autoFixCandidate ? "llm_fixable" : "needs_human_judgment"),
    annotationRoute: ["fix_request", "benchmark_annotation", "expert_escalation", "dismissed"].includes(route) ? route : "benchmark_annotation",
    affectedOutput: Array.isArray(body.affectedOutput) ? body.affectedOutput : [body.affectedOutput || body.selectedArtifactHumanName || body.selectedSectionLabel || "Main Paper"].filter(Boolean),
    impactReason: body.impactReason || body.rationale || body.reviewerComment || "",
  };
}

const EXPERT_RATER_ROLES = new Set(["expert"]);

function targetParts(key, body = {}) {
  const [prefix, ...rest] = String(key || "").split(":");
  const id = rest.join(":");
  if (prefix === "dp") return { targetType: "decision", targetId: id || body.targetId || "" };
  if (["decision", "event", "failure", "finding", "artifact", "table", "figure"].includes(prefix)) {
    return { targetType: prefix, targetId: id || body.targetId || "" };
  }
  return { targetType: body.targetType || body.subjectKind || "target", targetId: id || key };
}

function compactObject(value) {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => {
    if (v === null || v === undefined) return false;
    if (typeof v === "string" && !v.trim()) return false;
    return true;
  }));
}

function majorityVote(values) {
  const counts = new Map();
  for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) || 0) + 1);
  if (!counts.size) return null;
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0][0];
}

function aggregateSteerBenchAnnotations(target) {
  const annotations = Array.isArray(target.individualAnnotations) ? target.individualAnnotations : [];
  const nonModel = annotations.filter((annotation) => annotation.raterRole !== "model_preannotation");
  const expert = annotations.find((annotation) => EXPERT_RATER_ROLES.has(annotation.raterRole) && annotation.adjudicationOverride);
  const aggregate = {};
  const disagreements = {};
  for (const field of STEERBENCH_CATEGORICAL_FIELDS) {
    const values = nonModel.map((annotation) => annotation.labels?.[field]).filter(Boolean);
    const unique = [...new Set(values)];
    if (unique.length) aggregate[field] = majorityVote(values);
    if (unique.length > 1) disagreements[field] = unique;
  }
  const highSeverityDisagreement = nonModel.some((annotation) => annotation.severity === "high") && Object.keys(disagreements).length > 0;
  const explicitExpertReview = Boolean(target.needsExpertReview || annotations.some((annotation) => annotation.needsExpertReview || annotation.needsExpertAdjudication || annotation.adjudicationStatus === "pending"));
  return {
    aggregateAnnotation: expert?.labels || aggregate,
    benchmarkStatus: {
      workflowStatus: target.adjudication?.status === "adjudicated" ? "adjudicated"
        : explicitExpertReview || highSeverityDisagreement ? "needs_expert_adjudication"
        : Object.keys(disagreements).length ? "disagreement"
        : target.benchmarkStatus?.workflowStatus && target.benchmarkStatus.workflowStatus !== "needs_second_rater"
          ? target.benchmarkStatus.workflowStatus
          : (nonModel.length === 1 ? "needs_second_rater"
          : nonModel.length > 1 ? "annotated"
          : "unannotated"),
      raterCount: nonModel.length,
      disagreementFields: Object.keys(disagreements),
      needsSecondRater: nonModel.length === 1,
      needsExpertAdjudication: explicitExpertReview || highSeverityDisagreement,
    },
    disagreement: disagreements,
  };
}

function feedbackActionFromBody(body = {}) {
  const explicit = String(body.steeringDecision || body.preferredAction || "").trim();
  const mapped = {
    interrupt: "interrupt_redirect",
    ask_user: "request_clarification",
    verify_claim: "gather_more_evidence",
  };
  const action = mapped[explicit] || explicit
    || (body.interruptAction === "yes" ? "interrupt_redirect"
      : body.updateNeeded === "yes" ? "update_user"
      : "continue");
  return ["continue", "update_user", "interrupt_redirect", "request_clarification", "gather_more_evidence", "revise_plan"].includes(action)
    ? action
    : "continue";
}

async function saveFeedbackPacket(user, run, key, target, body = {}) {
  const rel = feedbackRel(user, run.id);
  const store = (await readVisualizerJson(rel, null)) || { version: "neurico_feedback_packets_v1", runId: run.id, packets: [] };
  const now = new Date().toISOString();
  const packet = {
    feedbackId: body.feedbackId || `fb_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    runId: run.id,
    targetKey: key,
    eventId: target.targetType === "event" ? target.targetId : (body.eventId || ""),
    decisionId: target.targetType === "decision" ? target.targetId : (body.decisionId || ""),
    artifactKey: target.targetType === "artifact" ? target.targetId : (body.artifactKey || ""),
    action: feedbackActionFromBody(body),
    suggestedAgentFeedback: body.suggestedAgentFeedback || body.comment || body.rationale || "",
    suggestedUserUpdate: body.suggestedUserUpdate || "",
    rationale: body.rationale || body.note || body.comment || "",
    createdAt: now,
    status: body.feedbackStatus || (body.semiLiveMode ? "proposed" : "unknown"),
  };
  store.version = "neurico_feedback_packets_v1";
  store.runId = run.id;
  store.packets = [...(Array.isArray(store.packets) ? store.packets : []), packet];
  await writeVisualizerJson(rel, store);
  return packet;
}

// Persist a reviewer annotation for one subject (a decision point,
// world-model decision, or PI question). Upserts into
// data/annotations/<user>/<runId>.json; nothing here touches the raw run.
async function saveAnnotation(req) {
  const body = await readRequestJson(req);
  const key = String(body.key || "").trim();
  if (!key) {
    const error = new Error("Annotation requires a key");
    error.status = 400;
    throw error;
  }
  const run = resolveRun(body.runId);
  const annoPath = annotationRel(body.user, run.id);
  const annotations = (await readVisualizerJson(annoPath, {})) || {};
  const previous = annotations[key] || {};
  if (body.clear) {
    delete annotations[key];
  } else {
    const target = targetParts(key, body);
    const previousIndividuals = Array.isArray(previous.individualAnnotations)
      ? previous.individualAnnotations
      : [];
    const labels = compactObject({
      steeringDecision: body.steeringDecision || (
        body.interruptAction === "yes" ? "interrupt_redirect"
          : body.updateNeeded === "yes" ? "update_user"
          : body.preferredAction === "ask_user" ? "request_clarification"
          : body.preferredAction === "continue" ? "continue"
          : ""
      ),
      cruxType: body.cruxType,
      keyCrux: body.keyCrux || body.keyUnresolvedQuestion,
      keyUnresolvedQuestion: body.keyUnresolvedQuestion,
      whyCruxMatters: body.whyCruxMatters,
      surfaceContextToUser: body.surfaceContextToUser,
      suggestedUserUpdate: body.suggestedUserUpdate,
      suggestedAgentFeedback: body.suggestedAgentFeedback || body.comment || body.preferredAction,
      feedbackIncorporation: body.feedbackIncorporation || (
        body.feedbackIncorporatedLater === "yes" ? "incorporated"
          : body.feedbackIncorporatedLater === "no" ? "ignored"
          : body.feedbackIncorporatedLater === "unsure" ? "not_enough_evidence"
          : ""
      ),
      feedbackEventId: body.feedbackEventId,
      linkedLaterEventIds: body.linkedLaterEventIds,
      evidenceForIncorporation: body.evidenceForIncorporation,
      evidenceAgainstIncorporation: body.evidenceAgainstIncorporation,
      issueType: body.issueType,
      suggestedAction: body.suggestedAction,
      quickComment: body.quickComment,
      claimSupported: body.claimSupported,
      evidenceSufficient: body.evidenceSufficient,
      missingInfo: body.missingInfo,
      uncertainty: body.uncertainty,
      workflowStatus: body.workflowStatus,
      finalLabel: body.finalLabel,
      adjudicationStatus: body.adjudicationStatus,
      includeInBenchmarkDecision: body.includeInBenchmarkDecision,
      isFeedbackEvent: body.isFeedbackEvent,
    });
    const now = new Date().toISOString();
    const eligibility = annotationEligibility(body, previous);
    const needsExpertReview = eligibility.needsExpertReview;
    const adjudicationStatus = needsExpertReview && !body.adjudicationStatus ? "pending" : (body.adjudicationStatus || "");
    const individual = {
      annotationId: body.annotationId || `ann_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      raterId: body.raterId || body.user || "anonymous",
      raterRole: body.raterRole || "reviewer",
      expertiseArea: body.expertiseArea || "",
      guidelineVersion: body.guidelineVersion || "v0.1",
      annotationRound: Number(body.annotationRound || 1),
      labels,
      confidence: body.confidence || "",
      severity: body.severity || body.priority || "",
      difficulty: body.difficulty || "",
      rationale: body.rationale || body.note || body.comment || "",
      needsSecondRater: Boolean(body.needsSecondRater),
      needsExpertAdjudication: needsExpertReview,
      mustAnnotate: eligibility.mustAnnotate,
      autoFixCandidate: eligibility.autoFixCandidate,
      impactType: eligibility.impactType,
      impactReason: eligibility.impactReason,
      affectedOutput: eligibility.affectedOutput,
      fixability: eligibility.fixability,
      annotationRoute: eligibility.annotationRoute,
      dismissedReason: body.dismissedReason || "",
      fixRequest: body.fixRequest || null,
      includeInBenchmark: Boolean(body.includeInBenchmark),
      targetKey: key,
      selectedArtifact: body.selectedArtifact || "",
      selectedArtifactHumanName: body.selectedArtifactHumanName || "",
      selectedArtifactPath: body.selectedArtifactPath || body.selectedArtifact || "",
      selectedRegion: body.selectedRegion || "",
      selectedSection: body.selectedSection || body.selectedRegion || "",
      selectedSectionLabel: body.selectedSectionLabel || "",
      selectedText: body.selectedText || body.sourceText || "",
      anchor: body.anchor || body.paperAnchor || body.reviewerVerification?.anchor || {},
      paperAnchor: body.paperAnchor || body.anchor || body.reviewerVerification?.anchor || {},
      pageOrSection: body.pageOrSection || body.selectedRegion || "",
      relatedDecisionIds: body.relatedDecisionIds || "",
      relatedFindingIds: body.relatedFindingIds || "",
      relatedEventIds: body.relatedEventIds || "",
      evidenceRefs: body.evidenceRefs || "",
      quickComment: body.quickComment || body.comment || "",
      issueType: body.issueType || "",
      suggestedAction: body.suggestedAction || "",
      autoCapturedContext: body.autoCapturedContext || {},
      reviewSummary: body.reviewSummary || {},
      reviewerChecklist: body.reviewerChecklist || {},
      checklist: body.checklist || body.reviewerChecklist || {},
      reviewerComment: body.reviewerComment || body.quickComment || body.comment || "",
      commentThread: body.commentThread || {
        text: body.reviewerComment || body.quickComment || body.comment || "",
        author: body.raterId || body.user || "anonymous",
        role: body.raterRole || "reviewer",
        status: needsExpertReview ? "escalated" : "open",
        linkedIssue: body.selectedIssue || body.targetIssue || "",
        selectedSection: body.selectedSection || body.selectedRegion || "",
        anchorType: (body.anchor || body.paperAnchor || {}).type || "",
      },
      selectedIssue: body.selectedIssue || body.targetIssue || "",
      source: body.source || "",
      openedJourney: Boolean(body.openedJourney),
      openedReports: Boolean(body.openedReports),
      needsExpertReview,
      relatedFiles: body.relatedFiles || [],
      llmPrelabel: body.llmPrelabel || body.benchmarkDraft || {},
      reviewerVerification: body.reviewerVerification || {},
      editedFields: body.editedFields || body.reviewerVerification?.editedFields || {},
      expertAdjudication: body.expertAdjudication || {},
      benchmarkTaskTargets: body.benchmarkTaskTargets || {},
      decisionIds: body.decisionIds || body.relatedDecisionIds || [],
      findingIds: body.findingIds || body.relatedFindingIds || [],
      provenanceUsage: body.provenanceUsage || {},
      benchmarkDraft: body.benchmarkDraft || {},
      humanConfirmedLabels: body.humanConfirmedLabels || {},
      hiddenBenchmarkData: {
        llmPrelabel: body.llmPrelabel || body.benchmarkDraft || {},
        reviewerVerification: body.reviewerVerification || {},
        expertAdjudication: body.expertAdjudication || {},
        targetKey: key,
        decisionIds: body.decisionIds || body.relatedDecisionIds || [],
        findingIds: body.findingIds || body.relatedFindingIds || [],
        evidenceRefs: body.evidenceRefs || "",
        provenanceUsage: body.provenanceUsage || {},
        exportJsonlTargets: body.benchmarkStatus?.exportJsonlTargets || body.exportJsonlTargets || [],
        adjudicationStatus,
        includeInBenchmark: Boolean(body.includeInBenchmark),
        impactType: eligibility.impactType,
        annotationRoute: eligibility.annotationRoute,
      },
      finalLabel: body.finalLabel || "",
      adjudicationStatus,
      includeInBenchmarkDecision: body.includeInBenchmarkDecision || "",
      raterMetadata: body.raterMetadata || {},
      createdAt: now,
      updatedAt: now,
    };
    const nextTarget = {
      version: "steerbench_annotations_v1",
      runId: run.id,
      targetType: target.targetType,
      targetId: target.targetId,
      individualAnnotations: [...previousIndividuals, individual],
      adjudication: previous.adjudication || {},
      benchmarkStatus: {
        ...(previous.benchmarkStatus || {}),
        ...(body.benchmarkStatus && typeof body.benchmarkStatus === "object" ? body.benchmarkStatus : {}),
        workflowStatus: needsExpertReview ? "needs_expert_adjudication" : (body.workflowStatus || body.benchmarkStatus?.workflowStatus || previous.benchmarkStatus?.workflowStatus || ""),
      },
      // Backward-compatible flat fields used by older visualizer surfaces.
      verdict: body.verdict || "none",
      label: body.label || null,
      preferredOption: body.preferredOption || null,
      preferredText: body.preferredText || null,
      customAlternative: typeof body.customAlternative === "string" ? body.customAlternative : (previous.customAlternative || ""),
      informUser: body.informUser || null,
      interrupt: body.interrupt || null,
      title: stringField(body, previous, "title"),
      category: stringField(body, previous, "category"),
      status: stringField(body, previous, "status"),
      priority: stringField(body, previous, "priority"),
      updateNeeded: stringField(body, previous, "updateNeeded"),
      interruptAction: stringField(body, previous, "interruptAction"),
      missingInfo: stringField(body, previous, "missingInfo"),
      uncertainty: stringField(body, previous, "uncertainty"),
      keyCrux: stringField(body, previous, "keyCrux"),
      preferredAction: stringField(body, previous, "preferredAction"),
      feedbackIncorporatedLater: stringField(body, previous, "feedbackIncorporatedLater"),
      comment: stringField(body, previous, "comment"),
      note: typeof body.note === "string" ? body.note : (previous.note || ""),
      subjectKind: body.subjectKind || previous.subjectKind || null,
      snapshot: body.snapshot || previous.snapshot || "",
      selectedArtifact: stringField(body, previous, "selectedArtifact"),
      selectedArtifactHumanName: stringField(body, previous, "selectedArtifactHumanName"),
      selectedArtifactPath: stringField(body, previous, "selectedArtifactPath"),
      selectedRegion: stringField(body, previous, "selectedRegion"),
      selectedSection: stringField(body, previous, "selectedSection"),
      selectedSectionLabel: stringField(body, previous, "selectedSectionLabel"),
      sourceText: stringField(body, previous, "sourceText"),
      selectedText: stringField(body, previous, "selectedText"),
      anchor: body.anchor || body.paperAnchor || previous.anchor || {},
      paperAnchor: body.paperAnchor || body.anchor || previous.paperAnchor || {},
      pageOrSection: stringField(body, previous, "pageOrSection"),
      relatedFindingIds: stringField(body, previous, "relatedFindingIds"),
      relatedDecisionIds: stringField(body, previous, "relatedDecisionIds"),
      relatedEventIds: stringField(body, previous, "relatedEventIds"),
      evidenceRefs: stringField(body, previous, "evidenceRefs"),
      quickComment: stringField(body, previous, "quickComment"),
      issueType: stringField(body, previous, "issueType"),
      suggestedAction: stringField(body, previous, "suggestedAction"),
      autoCapturedContext: body.autoCapturedContext || previous.autoCapturedContext || {},
      reviewSummary: body.reviewSummary || previous.reviewSummary || {},
      reviewerChecklist: body.reviewerChecklist || previous.reviewerChecklist || {},
      checklist: body.checklist || body.reviewerChecklist || previous.checklist || {},
      reviewerComment: stringField(body, previous, "reviewerComment"),
      commentThread: body.commentThread || previous.commentThread || {},
      selectedIssue: stringField(body, previous, "selectedIssue"),
      source: stringField(body, previous, "source"),
      openedJourney: Boolean(body.openedJourney || previous.openedJourney),
      openedReports: Boolean(body.openedReports || previous.openedReports),
      needsExpertReview: Boolean(body.needsExpertReview || body.needsExpertAdjudication || previous.needsExpertReview),
      mustAnnotate: eligibility.mustAnnotate,
      autoFixCandidate: eligibility.autoFixCandidate,
      impactType: eligibility.impactType,
      impactReason: eligibility.impactReason || previous.impactReason || "",
      affectedOutput: eligibility.affectedOutput,
      fixability: eligibility.fixability,
      annotationRoute: eligibility.annotationRoute,
      dismissedReason: body.dismissedReason || previous.dismissedReason || "",
      fixRequest: body.fixRequest || previous.fixRequest || null,
      relatedFiles: body.relatedFiles || previous.relatedFiles || [],
      llmPrelabel: body.llmPrelabel || previous.llmPrelabel || body.benchmarkDraft || {},
      reviewerVerification: body.reviewerVerification || previous.reviewerVerification || {},
      editedFields: body.editedFields || body.reviewerVerification?.editedFields || previous.editedFields || {},
      expertAdjudication: body.expertAdjudication || previous.expertAdjudication || {},
      benchmarkTaskTargets: body.benchmarkTaskTargets || previous.benchmarkTaskTargets || {},
      decisionIds: body.decisionIds || previous.decisionIds || [],
      findingIds: body.findingIds || previous.findingIds || [],
      provenanceUsage: body.provenanceUsage || previous.provenanceUsage || {},
      benchmarkDraft: body.benchmarkDraft || previous.benchmarkDraft || {},
      humanConfirmedLabels: body.humanConfirmedLabels || previous.humanConfirmedLabels || {},
      hiddenBenchmarkData: {
        ...(previous.hiddenBenchmarkData || {}),
        llmPrelabel: body.llmPrelabel || previous.llmPrelabel || body.benchmarkDraft || {},
        reviewerVerification: body.reviewerVerification || previous.reviewerVerification || {},
        expertAdjudication: body.expertAdjudication || previous.expertAdjudication || {},
        targetKey: key,
        decisionIds: body.decisionIds || previous.decisionIds || [],
        findingIds: body.findingIds || previous.findingIds || [],
        evidenceRefs: body.evidenceRefs || previous.evidenceRefs || "",
        provenanceUsage: body.provenanceUsage || previous.provenanceUsage || {},
        exportJsonlTargets: body.benchmarkStatus?.exportJsonlTargets || body.exportJsonlTargets || previous.hiddenBenchmarkData?.exportJsonlTargets || [],
        adjudicationStatus: adjudicationStatus || previous.adjudicationStatus || "",
        includeInBenchmark: Boolean(body.includeInBenchmark || previous.includeInBenchmark),
        impactType: eligibility.impactType,
        annotationRoute: eligibility.annotationRoute,
      },
      finalLabel: stringField(body, previous, "finalLabel"),
      adjudicationStatus: adjudicationStatus || previous.adjudicationStatus || "",
      includeInBenchmarkDecision: stringField(body, previous, "includeInBenchmarkDecision"),
      raterMetadata: body.raterMetadata || previous.raterMetadata || {},
      createdAt: previous.createdAt || body.createdAt || now,
      updatedAt: now,
    };
    annotations[key] = { ...nextTarget, ...aggregateSteerBenchAnnotations(nextTarget) };
    if (body.semiLiveMode) {
      annotations[key].latestFeedbackPacket = await saveFeedbackPacket(body.user, run, key, target, body);
    }
  }
  await writeVisualizerJson(annoPath, annotations);
  return annotations;
}

function sendJson(res, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

function sendError(res, error) {
  res.writeHead(error.status || 500, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: error.message }));
}

async function serveStatic(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
  const full = path.resolve(PUBLIC_DIR, pathname.replace(/^\/+/, ""));
  if (!inside(PUBLIC_DIR, full)) throw Object.assign(new Error("Bad static path"), { status: 400 });
  const data = await readFile(full);
  const ext = path.extname(full);
  const types = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
  };
  // No-cache for the app shell so code/style edits always show on reload (these files are
  // small and local; aggressive browser caching of module JS otherwise hides every change).
  res.writeHead(200, {
    "content-type": types[ext] || "application/octet-stream",
    "cache-control": "no-store, must-revalidate",
  });
  res.end(data);
}

// Auto-build the world model on startup when this project doesn't have one yet.
// Runs the reconstruction harness as a child process; the browser polls
// /api/world-model-status to show progress.
const reconstruction = { state: "checking", message: "", log: [], startedAt: null };

function maybeStartReconstruction() {
  if (/^(0|false|off)$/i.test(process.env.NEURICO_AUTOBUILD || "")) {
    reconstruction.state = "disabled";
    return;
  }
  const wmPath = visualizerPath("runs", RUN_ID, "world_model.json");
  if (existsSync(wmPath)) {
    reconstruction.state = "present";
    return;
  }
  const script = path.join(__dirname, "tools", "reconstruct_world_model.py");
  if (!existsSync(script)) {
    reconstruction.state = "unavailable";
    reconstruction.message = "Reconstruction tool not found.";
    return;
  }
  reconstruction.state = "running";
  reconstruction.startedAt = Date.now();
  reconstruction.message = "Generating world model from the run's artifacts…";
  console.log(`\n[world-model] ${RUN_ID} has no world_model.json — generating it now (this can take 7-10 min: a reconstruction pass + an adversarial review pass)…\n`);

  // -u / PYTHONUNBUFFERED so the harness's progress streams live instead of
  // being stuck in a pipe buffer until the process exits.
  // CRITICAL: strip this process's Claude Code session/agent/MCP context so the
  // nested `claude` the tool spawns runs STANDALONE. If launched from a Claude
  // Code terminal, an inherited CLAUDE_CODE_SESSION_ID makes the reconstruction
  // join the user's live session and post into their chat/channel. The Python
  // tool scrubs again at the actual claude call; this is defense in depth.
  const childEnv = { ...process.env, PYTHONUNBUFFERED: "1" };
  for (const key of Object.keys(childEnv)) {
    if (key.startsWith("CLAUDE_CODE") || key.startsWith("CLAUDE_AGENT") ||
        key.startsWith("MCP_") || ["CLAUDECODE", "AI_AGENT", "CLAUDE_EFFORT"].includes(key)) {
      delete childEnv[key];
    }
  }
  // Use the fast parallel-section path (#2 fan-out + #4 prompt caching) for the
  // auto-build by default; set NEURICO_FANOUT=0 to fall back to the monolithic pass.
  const fanoutArgs = /^(0|false|off)$/i.test(process.env.NEURICO_FANOUT || "") ? [] : ["--fanout"];
  const child = spawn("python3", ["-u", script, "--run-dir", RUN_DIR, ...fanoutArgs], {
    cwd: __dirname,
    env: childEnv,
  });
  const onOutput = (chunk) => {
    const text = chunk.toString();
    process.stdout.write(text);
    for (const line of text.split(/\r?\n/)) {
      if (line.trim()) reconstruction.log.push(line.trim());
    }
    reconstruction.log = reconstruction.log.slice(-60);
  };
  child.stdout.on("data", onOutput);
  child.stderr.on("data", onOutput);
  child.on("error", (error) => {
    reconstruction.state = "error";
    reconstruction.message = `Could not start reconstruction: ${error.message}`;
    console.log(`[world-model] ${reconstruction.message}`);
  });
  child.on("exit", (code) => {
    const tookS = reconstruction.startedAt ? Math.round((Date.now() - reconstruction.startedAt) / 1000) : 0;
    const took = tookS >= 60 ? `${Math.floor(tookS / 60)}m ${tookS % 60}s` : `${tookS}s`;
    if (existsSync(wmPath)) {
      reconstruction.state = "done";
      reconstruction.message = `World model ready (took ${took}).`;
      console.log(`\n[world-model] done in ${took} — ${RUN_ID} is ready. Refresh the browser.\n`);
    } else {
      reconstruction.state = "failed";
      reconstruction.message = `World model could not be generated (exit ${code}, after ${took}). Decisions/Whiteboard stay empty; see terminal.`;
      console.log(`\n[world-model] failed (exit ${code}) after ${took}.\n`);
    }
  });
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname === "/api/runs") {
      sendJson(res, await listStudyRuns());
      return;
    }

    if (url.pathname === "/api/retry-processing" && req.method === "POST") {
      const body = await readJsonBody(req);
      const run = resolveRun(body.runId || url.searchParams.get("runId"));
      const script = "/Users/bellaho/neurico-workspace/scripts/sync_all_hypogenic_to_visualizer.sh";
      if (!existsSync(script)) {
        throw Object.assign(new Error("Sync script not found."), { status: 500 });
      }
      const child = spawn(script, ["--repo", run.id], {
        cwd: "/Users/bellaho/neurico-workspace",
        detached: true,
        stdio: "ignore",
      });
      child.unref();
      sendJson(res, { ok: true, runId: run.id, message: "Retry processing started." });
      return;
    }

    if (url.pathname === "/api/whiteboard-run") {
      const run = resolveRun(url.searchParams.get("runId"));
      const whiteboard = await readVisualizerJson(
        path.join("runs", run.id, "whiteboard_decisions.generated.json"),
        null
      );

      if (!whiteboard) {
        throw Object.assign(
          new Error(`No whiteboard_decisions.generated.json for run: ${run.id}`),
          { status: 404 }
        );
      }

      return sendJson(res, whiteboard);
    }

    if (url.pathname === "/api/annotations" && req.method === "POST") {
      const payload = await readJsonBody(req);
      const run = resolveRun(payload.runId || url.searchParams.get("runId"));
      const annotator = safeFilePart(
        payload.annotator || url.searchParams.get("user") || "anonymous"
      );

      const record = {
        ...payload,
        runId: run.id,
        annotator,
        createdAt: new Date().toISOString(),
      };

      const annDir = path.join(DATA_DIR, "runs", run.id, "annotations");
      await mkdir(annDir, { recursive: true });

      const annPath = path.join(annDir, `${annotator}.jsonl`);
      await writeFile(annPath, JSON.stringify(record) + "\n", { flag: "a" });

      return sendJson(res, { ok: true, saved: annPath, record });
    }

    if (url.pathname === "/api/annotations" && req.method === "GET") {
      const run = resolveRun(url.searchParams.get("runId"));
      const annotator = safeFilePart(url.searchParams.get("user") || "anonymous");
      const annPath = path.join(DATA_DIR, "runs", run.id, "annotations", `${annotator}.jsonl`);

      if (!existsSync(annPath)) return sendJson(res, { annotations: [] });

      const text = await readFile(annPath, "utf8");
      const annotations = text
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line));

      return sendJson(res, { annotations });
    }

    if (url.pathname === "/api/canonical-run") {
      const run = resolveRun(url.searchParams.get("runId"));
      const canonical = await readVisualizerJson(
        path.join("runs", run.id, "canonical_trajectory.json"),
        null
      );

      if (!canonical) {
        throw Object.assign(
        new Error(`No canonical_trajectory.json for run: ${run.id}`),
        { status: 404 }
      );
    }

    return sendJson(res, canonical);
  }
    if (url.pathname === "/api/run") {
      sendJson(res, await buildRunSummary(resolveRun(url.searchParams.get("runId")), url.searchParams.get("user")));
      return;
    }
    if (url.pathname === "/api/run-status") {
      sendJson(res, await buildRunStatus(resolveRun(url.searchParams.get("runId"))));
      return;
    }
    if (url.pathname === "/api/world-model-status") {
      sendJson(res, {
        runId: RUN_ID,
        state: reconstruction.state,
        message: reconstruction.message,
        log: reconstruction.log.slice(-12),
        elapsedMs: reconstruction.startedAt ? Date.now() - reconstruction.startedAt : 0,
      });
      return;
    }
    if (url.pathname === "/api/visualizer/layout" && req.method === "POST") {
      sendJson(res, await updateVisualizerLayout(req));
      return;
    }
    if (url.pathname === "/api/annotation" && req.method === "POST") {
      sendJson(res, await saveAnnotation(req));
      return;
    }
    if (url.pathname === "/api/artifact") {
      const relativePath = url.searchParams.get("path") || "";
      const run = resolveRunForArtifact(url.searchParams.get("runId"), relativePath);
      const runQuery = run === DEFAULT_RUN ? "" : `&runId=${encodeURIComponent(run.id)}`;
      const full = safeRunPath(relativePath, run);
      const info = await stat(full);
      const extension = path.extname(full).toLowerCase();
      if (!TEXT_EXTENSIONS.has(extension) || info.size > 1_000_000) {
        sendJson(res, {
          path: relativePath,
          previewType: extension.match(/\.(png|jpg|jpeg|gif|svg)$/) ? "image" : "binary",
          url: `/api/file?path=${encodeURIComponent(relativePath)}${runQuery}`,
          size: info.size,
        });
        return;
      }
      const text = await readFile(full, "utf8");
      sendJson(res, {
        path: relativePath,
        previewType: extension === ".csv" ? "csv" : "text",
        extension,
        content: text,
        csv: extension === ".csv" ? parseCsv(text) : null,
      });
      return;
    }
    if (url.pathname === "/api/file") {
      const relativePath = url.searchParams.get("path") || "";
      const full = safeRunPath(relativePath, resolveRunForArtifact(url.searchParams.get("runId"), relativePath));
      const data = await readFile(full);
      const extension = path.extname(full).toLowerCase();
      const type =
        extension === ".png" ? "image/png" :
        extension === ".jpg" || extension === ".jpeg" ? "image/jpeg" :
        extension === ".pdf" ? "application/pdf" :
        "application/octet-stream";
      res.writeHead(200, { "content-type": type });
      res.end(data);
      return;
    }
    await serveStatic(req, res);
  } catch (error) {
    console.error(`[request] ${req.method} ${req.url} failed:`, error);
    sendError(res, error);
  }
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE") {
    console.error(`\n✗ Port ${PORT} is already in use. Try: PORT=${PORT + 1} node server.js ${RUN_DIR}\n`);
  } else if (error.code === "EPERM" || error.code === "EACCES") {
    console.error(`\n✗ Cannot bind ${HOST}:${PORT} (${error.code}). Try: NEURICO_HOST=127.0.0.1 PORT=${PORT + 1} node server.js ${RUN_DIR}\n`);
  } else {
    console.error(`\n✗ Server failed to start on ${HOST}:${PORT}: ${error.message}\n`);
  }
  process.exit(1);
});

server.listen(PORT, HOST, () => {
  const builtRuns = listBuiltRunIds();
  console.log(`\nNeuriCo log visualizer — ${builtRuns.length} run(s) available, default: ${RUN_ID}`);
  console.log(`Run directory: ${RUN_DIR}  |  bind: ${HOST}:${PORT}`);
  maybeStartReconstruction();
  // The server now sits and serves (this is normal — it is not "stuck"). Make the
  // last line an explicit call to action so an idle, ready server isn't mistaken
  // for a hang. Reconstruction (if any) already printed its own progress above.
  const note = reconstruction.state === "running"
    ? "building the world model first — the page shows a progress bar and reloads when it's done (~7-10 min)"
    : "ready now — loads in under a second";
  console.log(`\n→ Open  http://localhost:${PORT}  in your browser (${note}).`);
  console.log(`  (Leave this window open. Press Control+C to stop the server.)\n`);
});
