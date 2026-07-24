let run = null;
let currentRunId = null;
let userEmail = localStorage.getItem("steerbench-user-email") || "";
let currentScreen = userEmail ? "list" : "entry";
let currentView = "overview";
let selectedTargetKey = "";
let selectedRegion = "abstract";
let selectedRegionText = "";
let selectedArtifactPath = "";
let reportQuery = "";
let selectedJourneyStage = 0;
let selectedJourneyNodeId = "";
let journeyFilter = "all";
let journeyZoom = 1;
const collapsedJourneyPhases = new Set();
let showAllSteeringCandidates = false;
let developerMode = new URLSearchParams(location.search).get("dev") === "1";
let assistantDraft = null;
let assistantResponse = null;
let selectedReviewSource = "ranked_queue";
let openedJourney = false;
let openedReports = false;
let sidebarExpandedOverride = false;
let annotationTool = "comment";
let selectedAnnotationAnchor = null;
let activeCommentId = "";
let showAllReviewIssues = false;
let reviewIssueFilter = "all";
let editingPrelabel = false;
let selectedWhiteboardCard = "";
let pdfjsReady = null;
let renderedPdfToken = 0;
let currentRole = new URLSearchParams(location.search).get("role") || "reviewer";

const root = document.querySelector("#view-root");
const title = document.querySelector("#run-title");
const status = document.querySelector("#run-status");
const runEyebrow = document.querySelector("#run-eyebrow");
const backToList = document.querySelector("#back-to-list");
const userChip = document.querySelector("#user-chip");
const sidebarToggle = document.querySelector("#steering-sidebar-toggle");
const navButtons = [...document.querySelectorAll(".nav-item")];

const PROCESSING_STATUSES = [
  "raw_only",
  "processing_needed",
  "git_sync_failed",
  "raw_synced",
  "canonical_ready",
  "literature_ready",
  "world_model_ready",
  "world_model_failed",
  "fallback_review_ready",
  "annotation_ready",
  "completed",
  "failed",
];

const STEERING_DECISIONS = ["", "continue", "update_user", "interrupt_redirect", "request_clarification"];
const CRUX_TYPES = ["", "missing_evidence", "wrong_assumption", "weak_hypothesis", "bad_experiment_plan", "execution_failure", "unsupported_claim", "user_intent_drift", "agent_handoff_failure", "memory_context_failure", "other"];
const SUPPORT_LEVELS = ["", "supported", "partially_supported", "unsupported", "unclear"];
const YES_NO_UNCERTAIN = ["", "yes", "no", "uncertain"];
const LEVELS = ["", "low", "medium", "high"];
const RATER_ROLES = ["reviewer", "expert", "developer"];
const WORKFLOW_STATUSES = ["", "unannotated", "annotated", "needs_second_rater", "disagreement", "needs_expert_adjudication", "adjudicated", "benchmark_ready", "excluded"];
const ISSUE_TYPES = ["missing evidence", "unsupported claim", "weak experiment", "wrong assumption", "unclear writing", "needs user update", "should interrupt", "other"];
const SUGGESTED_ACTIONS = ["continue", "update user", "interrupt / redirect", "request clarification", "gather more evidence", "revise paper/output"];
const IMPACT_TYPES = [
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
  "cost_or_resource_metric",
  "writing_only",
  "formatting_only",
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
const FIX_TYPES = ["clarity", "wording", "citation", "table-caption", "explanation", "minor consistency"];
const ROUTES = ["fix_request", "benchmark_annotation", "expert_escalation", "dismissed"];
const MANUAL_SOURCES = {
  manual_crux: "manual_crux",
  llm_missed_issue: "llm_missed_issue",
  expert_review: "manual_crux",
};

const ANCHOR_TYPES = {
  SECTION: "section_anchor",
  TEXT: "text_span_anchor",
  BOX: "box_anchor",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function compactText(value, limit = 180) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function humanList(items, fallback = "not enough information available") {
  const values = (Array.isArray(items) ? items : [items]).map((item) => String(item || "").trim()).filter(Boolean);
  return values.length ? values : [fallback];
}

function runQuery(prefix = "&") {
  return currentRunId ? `${prefix}runId=${encodeURIComponent(currentRunId)}` : "";
}

function withRun(body) {
  return { ...body, runId: currentRunId, user: userEmail, raterId: userEmail || "anonymous" };
}

function reviewHeavyView() {
  return ["overview", "steering", "trajectory", "artifacts"].includes(currentView);
}

function updateSidebarState() {
  const collapsed = currentScreen === "viewer" && reviewHeavyView() && !sidebarExpandedOverride;
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  if (sidebarToggle) {
    sidebarToggle.hidden = currentScreen !== "viewer";
    sidebarToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    sidebarToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    const label = sidebarToggle.querySelector(".sidebar-label");
    if (label) label.textContent = collapsed ? "Expand sidebar" : "Collapse sidebar";
  }
}

function sectionPage(candidate, sectionKey = selectedRegion) {
  const label = outputSections().find(([key]) => key === sectionKey)?.[1] || sectionKey;
  const normalized = String(label || sectionKey || "").toLowerCase();
  const highlight = candidate?.targetId && run?.paperHighlights?.[candidate.targetId];
  if (highlight && String(highlight.section || "").toLowerCase() === normalized && Number(highlight.page)) {
    return Number(highlight.page);
  }
  const mapping = run?.paperSectionPages || run?.sectionPageMap || run?.paperPageMap || {};
  const mapped = mapping[sectionKey] || mapping[label] || mapping[normalized];
  return Number(mapped) || null;
}

function paperPdfUrlFor(candidate) {
  const base = paperPdfUrl();
  if (!base) return "";
  const page = sectionPage(candidate);
  return page ? `${base}#toolbar=0&navpanes=0&view=FitH&page=${page}` : `${base}#toolbar=0&navpanes=0&view=FitH`;
}

function artifactPath(artifact) {
  return artifact?.path || artifact?.name || "";
}

function selectedSectionLabel() {
  return outputSections().find(([key]) => key === selectedRegion)?.[1] || "Selected section";
}

function sectionAnchor() {
  return {
    type: ANCHOR_TYPES.SECTION,
    page: sectionPage(selectedCandidate()) || null,
    selectedText: selectedRegionText || outputSections().find(([key]) => key === selectedRegion)?.[2] || "",
    selectedSection: selectedRegion,
    section: selectedRegion,
  };
}

function currentAnchor() {
  return selectedAnnotationAnchor || sectionAnchor();
}

function normalizeRect(rect, bounds) {
  return {
    x: clampNumber((rect.left - bounds.left) / bounds.width),
    y: clampNumber((rect.top - bounds.top) / bounds.height),
    width: clampNumber(rect.width / bounds.width),
    height: clampNumber(rect.height / bounds.height),
  };
}

function clampNumber(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, Number(value.toFixed(5))));
}

function annotationComments(candidate) {
  const anno = annotationFor(candidate.key);
  const individuals = Array.isArray(anno.individualAnnotations) ? anno.individualAnnotations : [];
  const comments = [];
  for (const item of individuals) {
    const anchor = item.anchor || item.paperAnchor || item.reviewerVerification?.anchor;
    const text = item.reviewerComment || item.quickComment || item.comment || item.rationale || "";
    if (!anchor && !text) continue;
    comments.push({
      id: item.annotationId || `${candidate.key}:${comments.length}`,
      text,
      author: item.raterId || item.raterMetadata?.raterId || "anonymous",
      role: item.raterRole || item.raterMetadata?.raterRole || "reviewer",
      timestamp: item.updatedAt || item.createdAt || item.timestamp || "",
      status: item.needsExpertReview || item.needsExpertAdjudication ? "escalated" : (item.resolved ? "resolved" : "open"),
      linkedIssue: item.selectedIssue || candidate.title,
      selectedSection: item.selectedSection || item.selectedRegion || selectedRegion,
      anchorType: anchor?.type || ANCHOR_TYPES.SECTION,
      anchor,
    });
  }
  return comments;
}

function allReviewIssues() {
  const manual = Object.keys(annotationMap())
    .filter((key) => key.startsWith("manual_crux:") || key.startsWith("llm_missed_issue:"))
    .map((key) => manualCandidate(key));
  const seen = new Set();
  return [...priorityCandidates(true), ...manual].filter((item) => {
    if (!item?.key || seen.has(item.key)) return false;
    seen.add(item.key);
    return true;
  });
}

function artifactByPath(path) {
  return (run?.artifacts || []).find((artifact) => artifactPath(artifact) === path)
    || outputArtifacts().find((artifact) => artifactPath(artifact) === path)
    || { path };
}

function artifactLabel(refOrPath) {
  const path = typeof refOrPath === "string" ? refOrPath : refOrPath?.path || "";
  const note = typeof refOrPath === "string" ? "" : refOrPath?.note || "";
  const allowed = ["Main Paper", "Candidate Vocabulary Table", "Split Counts Summary", "Experiment Config Summary", "Accuracy Figure", "Final Report", "Hidden-State Extraction Summary"];
  if (allowed.includes(note)) return note;
  return humanTitle(path);
}

function paperPdfUrl() {
  return run?.paperPdf ? `/api/file?path=${encodeURIComponent(run.paperPdf)}${runQuery()}` : "";
}

function mainPaperPath() {
  if (run?.paperPdf) return run.paperPdf;
  const paper = (run?.artifacts || []).find((artifact) => /(^|\/)(main|paper|report).*\.(pdf|md|tex)$/i.test(artifactPath(artifact)));
  return artifactPath(paper) || "paper_draft/main.pdf";
}

function firstSentence(text) {
  return compactText(String(text || "").split(/(?<=[.!?])\s+/)[0] || text, 220);
}

function researchState() {
  return run?.researchState || {};
}

function findings() {
  return researchState().findings || [];
}

function decisions() {
  return run?.decisionPoints || [];
}

function canonicalEvents() {
  const data = run?.canonicalTrajectory || {};
  if (Array.isArray(data.events)) return data.events;
  if (Array.isArray(data.traceEvents)) return data.traceEvents;
  return [];
}

function eventId(event, index) {
  return String(event.event_id || event.eventId || event._id || event.id || `event-${index + 1}`);
}

function eventText(event) {
  return compactText(event.summary || event._text || event.text || event.message || event.rawPreview || event.type || "", 260);
}

function eventStage(event) {
  return String(event.stage || event.phase || event.pipeline_stage || event.eventType || event.type || "unknown");
}

function failedEvents() {
  return canonicalEvents().filter((event) => {
    const text = JSON.stringify(event).toLowerCase();
    return /failed|failure|exception|traceback|retry|retried|timeout|error/.test(text);
  });
}

function outputArtifacts() {
  const output = run?.outputArtifacts || [];
  if (output.length) return output.filter((artifact) => isHumanReadableOutput(artifact));
  return (run?.artifacts || []).filter((artifact) => isHumanReadableOutput(artifact));
}

function isHumanReadableOutput(artifact) {
  const path = artifactPath(artifact).toLowerCase();
  if (!path) return false;
  if (isRawDeveloperArtifact(artifact)) return false;
  if (isSystemReferencePath(path) || isRunLiteraturePath(path)) return true;
  return /^paper_draft\/main\.pdf$/.test(path)
    || /(^|\/)(report|paper|abstract|method|results|discussion|limitations|summary|table|figure|diagram|chart|metric|evaluation|comparison|outline|draft|config|split|vocab|candidate|literature_review|resources|citation|bibliography|references|hidden)[^/]*\.(pdf|md|txt|tex|csv|json|bib|png|jpg|jpeg|svg)$/i.test(path)
    || /^(paper_draft|results|figures|tables|papers|sources|literature|downloads|web_sources)\//.test(path);
}

function isRawDeveloperArtifact(artifact) {
  const path = artifactPath(artifact).toLowerCase();
  return !path
    || path.includes("/.claude/")
    || path.startsWith(".claude/")
    || path.includes("node_modules/")
    || path.includes("__pycache__/")
    || path.includes(".git/")
    || /\.(py|js|ts|sh|lock|toml|yaml|yml|jsonl)$/i.test(path)
    || /(^|\/)(package|cache|log|script|server|app|style|readme)/i.test(path)
    || /(^|\/)config\.(json|yaml|yml|toml)$/i.test(path);
}

function evidenceRefsForFinding(finding) {
  const refs = [];
  for (const ref of finding?.evidence || []) {
    if (ref?.path) refs.push({ path: ref.path, note: ref.note || ref.itemId || "", anchor: ref.anchor || "" });
  }
  for (const path of finding?.basedOn || []) refs.push({ path, note: `finding ${finding.id}`, anchor: "" });
  return dedupeRefs(refs);
}

function evidenceRefsForDecision(decision) {
  const refs = [];
  for (const ref of decision?.sourceRefs || decision?.evidence || []) {
    const path = ref.path || ref.file;
    if (path) refs.push({ path, note: ref.note || ref.itemId || "", anchor: ref.anchor || decision.choice || "" });
  }
  const finding = findingForDecision(decision);
  refs.push(...evidenceRefsForFinding(finding));
  if (decision.paperRef || run?.paperHighlights?.[decision.id]) refs.push({ path: "paper_draft/main.pdf", note: "paper/output region", anchor: decision.paperRef?.anchor || "" });
  return dedupeRefs(refs);
}

function dedupeRefs(refs) {
  const seen = new Set();
  return refs.filter((ref) => {
    const key = `${ref.path}:${ref.anchor || ""}:${ref.note || ""}`;
    if (!ref.path || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function findingForDecision(decision) {
  return findings().find((finding) => finding.id === decision?.finding) || null;
}

function decisionTitle(decision) {
  return decision?.title || decision?.question || decision?.choice || decision?.chosen || decision?.id || "Reconstructed decision";
}

function annotationMap() {
  return run?.visualizerData?.annotations || {};
}

function annotationFor(key) {
  return annotationMap()[key] || annotationMap()[key.replace(/^decision:/, "dp:")] || {};
}

function latestAnnotation(targetKey) {
  const raw = annotationFor(targetKey);
  const list = Array.isArray(raw.individualAnnotations) ? raw.individualAnnotations : [];
  const latest = list[list.length - 1] || {};
  return {
    ...raw,
    ...(latest.labels || {}),
    raterRole: latest.raterRole || raw.raterRole || "",
    expertiseArea: latest.expertiseArea || raw.expertiseArea || "",
    guidelineVersion: latest.guidelineVersion || raw.guidelineVersion || "v0.1",
    annotationRound: latest.annotationRound || raw.annotationRound || 1,
    confidence: latest.confidence || raw.confidence || "",
    severity: latest.severity || raw.severity || "",
    rationale: latest.rationale || raw.rationale || "",
    reviewerChecklist: latest.reviewerChecklist || raw.reviewerChecklist || {},
    reviewerComment: latest.reviewerComment || raw.reviewerComment || "",
    benchmarkDraft: latest.benchmarkDraft || raw.benchmarkDraft || {},
    needsSecondRater: Boolean(latest.needsSecondRater || raw.benchmarkStatus?.needsSecondRater),
    needsExpertAdjudication: Boolean(latest.needsExpertAdjudication || raw.benchmarkStatus?.needsExpertAdjudication),
    includeInBenchmark: Boolean(latest.includeInBenchmark || raw.includeInBenchmark),
    mustAnnotate: Boolean(latest.mustAnnotate || raw.mustAnnotate),
    autoFixCandidate: Boolean(latest.autoFixCandidate || raw.autoFixCandidate),
    needsExpertReview: Boolean(latest.needsExpertReview || raw.needsExpertReview),
    impactType: latest.impactType || raw.impactType || latest.impactTypes || raw.impactTypes || [],
    impactReason: latest.impactReason || raw.impactReason || "",
    affectedOutput: latest.affectedOutput || raw.affectedOutput || [],
    fixability: latest.fixability || raw.fixability || "",
    annotationRoute: latest.annotationRoute || raw.annotationRoute || "",
    dismissedReason: latest.dismissedReason || raw.dismissedReason || "",
    fixRequest: latest.fixRequest || raw.fixRequest || null,
    editedFields: latest.editedFields || raw.editedFields || {},
  };
}

function priorityCandidates(includeAll = false) {
  const front = new Set(run?.frontPageDecisions || []);
  const items = decisions().map((decision) => {
    const finding = findingForDecision(decision);
    const evidence = evidenceRefsForDecision(decision);
    let score = 0;
    if (front.has(decision.id)) score += 40;
    if (decision.importance === "critical") score += 30;
    if (decision.importance === "high") score += 22;
    if (decision.shouldEngage || decision.pass1ShouldEngage) score += 18;
    if (finding?.kind === "result" || finding?.show_by_default !== false) score += 12;
    score += Math.min(12, evidence.length * 3);
    return {
      key: `decision:${decision.id}`,
      legacyKey: `dp:${decision.id}`,
      targetType: "decision",
      targetId: decision.id,
      title: decisionTitle(decision),
      summary: decision.rationale || decision.choice || decision.situation || "",
      finding,
      findingId: finding?.id || "",
      evidence,
      decision,
      score,
      stage: decision.layer || decision.phase || "reconstructed decision",
    };
  }).sort((a, b) => b.score - a.score);
  return includeAll || showAllSteeringCandidates ? items : items.slice(0, 18);
}

function selectedCandidate() {
  const candidates = priorityCandidates();
  if (selectedTargetKey) {
    const exact = candidates.find((candidate) => candidate.key === selectedTargetKey || candidate.legacyKey === selectedTargetKey);
    if (exact) return exact;
    if (selectedTargetKey.startsWith("manual_crux:") || selectedTargetKey.startsWith("llm_missed_issue:")) {
      return manualCandidate(selectedTargetKey);
    }
    if (selectedTargetKey.startsWith("artifact:")) {
      return artifactCandidate(selectedTargetKey.slice("artifact:".length));
    }
  }
  return candidates[0] || artifactCandidate(mainPaperPath());
}

function applyCandidatePaperAnchor(key) {
  const candidate = priorityCandidates(true).find((item) => item.key === key || item.legacyKey === key);
  const section = candidate?.decision?.paperRef?.section || candidate?.decision?.affectedOutput || "";
  if (!section) return;
  const normalized = String(section).toLowerCase().replace(/\s+/g, "_");
  const known = outputSections().map(([sectionKey]) => sectionKey);
  selectedRegion = known.includes(normalized) ? normalized : known.find((item) => item === normalized.replace(/s$/, "")) || selectedRegion;
  selectedAnnotationAnchor = sectionAnchor();
}

function manualCandidate(key) {
  const anno = annotationFor(key);
  const individual = Array.isArray(anno.individualAnnotations) ? anno.individualAnnotations.at(-1) || {} : {};
  const selectedArtifact = anno.selectedArtifact || individual.selectedArtifact || mainPaperPath();
  const comment = individual.reviewerComment || anno.reviewerComment || anno.quickComment || "Manual crux created by reviewer.";
  return {
    key,
    legacyKey: "",
    targetType: "manual_crux",
    targetId: key,
    title: anno.title || individual.selectedIssue || (key.startsWith("llm_missed_issue:") ? "LLM missed issue" : "Manual crux"),
    summary: comment,
    finding: null,
    findingId: "",
    evidence: [{ path: selectedArtifact, note: humanTitle(selectedArtifact), anchor: anno.selectedRegion || selectedRegion }],
    decision: {},
    score: 0,
    stage: individual.autoCapturedContext?.stage || anno.autoCapturedContext?.stage || "manual review",
  };
}

function annotationSourceFor(candidate) {
  if (candidate.key.startsWith("llm_missed_issue:")) return "llm_missed_issue";
  if (candidate.key.startsWith("manual_crux:")) return "manual_crux";
  if (selectedReviewSource) return selectedReviewSource;
  if (candidate.key.startsWith("artifact:")) return selectedArtifactPath && selectedArtifactPath !== mainPaperPath() ? "report_review" : "section_comment";
  return "ranked_queue";
}

function artifactCandidate(path) {
  return {
    key: `artifact:${path}#${selectedRegion || "span"}`,
    targetType: "artifact",
    targetId: `${path}#${selectedRegion || "span"}`,
    title: `${humanTitle(path)} - ${selectedSectionLabel()}`,
    summary: selectedRegionText || "Output-driven annotation target.",
    finding: null,
    findingId: "",
    evidence: [{ path, note: humanTitle(path), anchor: selectedRegionText }],
    stage: "Report",
  };
}

function updateChrome() {
  const inRun = currentScreen === "viewer" && run;
  document.body.classList.toggle("no-run", !inRun);
  updateSidebarState();
  backToList.hidden = !inRun;
  userChip.hidden = !userEmail;
  userChip.textContent = userEmail || "";
  runEyebrow.textContent = inRun ? "SteerBench Annotator" : "SteerBench Annotator";
  navButtons.forEach((button) => {
    const auto = button.dataset.autoresearchTab;
    if (auto) button.hidden = !run?.autoresearch?.detected;
    if (button.dataset.view === "advanced") button.hidden = !developerMode;
    button.classList.toggle("active", button.dataset.view === currentView);
  });
  if (!inRun) {
    title.textContent = currentScreen === "entry" ? "Sign in" : "Choose a run";
    status.textContent = "";
    status.className = "status-pill";
  }
}

function setRunStatus() {
  const value = run?.runStatus?.status || "raw_only";
  status.textContent = conciseProcessingStatus().label;
  status.className = `status-pill status-${escapeHtml(value)}`;
}

function conciseProcessingStatus() {
  const st = run?.runStatus?.status || "raw_only";
  if (st === "git_sync_failed") return { state: "failed", label: "Git sync failed", detail: "Retry sync." };
  if (st === "failed") return { state: "failed", label: "failed", detail: "Processing failed." };
  if (st === "completed" || st === "annotation_ready") return { state: "completed", label: "completed", detail: "Annotation data is ready." };
  const signals = run?.runStatus?.signals || {};
  const missing = [];
  if (!signals.canonicalTrajectory && !run?.canonicalTrajectory) missing.push("missing canonical trajectory");
  if (!signals.worldModel && !run?.researchState) missing.push("missing world model");
  if (!run?.paperPdf && !(run?.artifacts || []).some((a) => /report|paper|main\.pdf/i.test(artifactPath(a)))) missing.push("missing paper");
  return { state: "not-ready", label: "not ready", detail: missing.join(", ") || "Required annotation inputs are still incomplete." };
}

function renderApp() {
  updateChrome();
  if (currentScreen === "entry") return renderEntry();
  if (currentScreen === "list") return renderRunList();
  return render();
}

function renderEntry() {
  root.innerHTML = `
    <section class="entry-screen">
      <div class="entry-panel">
        <span class="eyebrow">SteerBench Annotator</span>
        <h2>Event-Level Steering review</h2>
        <p>Enter a rater ID or email. It is used only to label saved annotations.</p>
        <form id="email-form" class="entry-form">
          <input id="email-input" type="email" required autocomplete="email" placeholder="rater@example.edu">
          <button type="submit">Continue</button>
        </form>
      </div>
    </section>`;
  root.querySelector("#email-form").addEventListener("submit", (event) => {
    event.preventDefault();
    userEmail = root.querySelector("#email-input").value.trim().toLowerCase();
    if (!userEmail) return;
    localStorage.setItem("steerbench-user-email", userEmail);
    currentScreen = "list";
    renderApp();
  });
}

async function renderRunList() {
  root.innerHTML = `<section class="panel"><p class="muted">Loading runs...</p></section>`;
  let runs = [];
  try {
    runs = await (await fetch("/api/runs")).json();
  } catch (error) {
    root.innerHTML = `<section class="panel"><h3>Could not load runs</h3><p>${escapeHtml(error.message)}</p></section>`;
    return;
  }
  runs.sort((a, b) => statusRank(a) - statusRank(b) || (a.annotatorCount || 0) - (b.annotatorCount || 0));
  root.innerHTML = `
    <section class="run-list-screen">
      <div class="run-list-head">
        <span class="eyebrow">Review Queue</span>
        <h3>All Ideas / Submissions</h3>
        <div class="run-list-controls">
          <button data-next-priority>Next priority issue</button>
          <button data-mark-reviewed>Mark run reviewed</button>
          <button data-skip-low-quality>Skip low-quality run</button>
          <button data-needs-expert>Needs expert review</button>
          <button data-assign-second>Assign second rater</button>
        </div>
      </div>
      <div class="run-cards">
        ${runs.map((item) => renderRunCard(item)).join("") || `<p class="muted">No runs found.</p>`}
      </div>
    </section>`;
  root.querySelectorAll("[data-open-run]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (event.target.closest("summary, details")) return;
      openRun(button.dataset.openRun);
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") openRun(button.dataset.openRun);
    });
  });
  root.querySelectorAll("[data-retry-run]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      button.disabled = true;
      const label = button.textContent;
      button.textContent = "Retrying...";
      try {
        await fetch("/api/retry-processing", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ runId: button.dataset.retryRun }),
        });
        button.textContent = "Retry started";
      } catch {
        button.textContent = label;
        button.disabled = false;
      }
    });
  });
}

function statusRank(item) {
  const status = item.runStatus?.status || "raw_only";
  if (status === "completed") return 0;
  if (status === "annotation_ready") return 1;
  if (status === "fallback_review_ready") return 2;
  if (status === "canonical_ready" || status === "literature_ready" || status === "world_model_ready") return 3;
  if (status === "raw_only" || status === "raw_synced") return 4;
  if (status === "git_sync_failed") return 5;
  if (status === "processing_needed") return 5;
  if (status === "world_model_failed") return 6;
  if (status === "failed") return 5;
  return 7;
}

function runWorkflowStatus(item) {
  const status = item.runStatus?.status || "raw_only";
  if (status === "completed") return "completed";
  if (status === "annotation_ready") return "Annotation ready";
  if (status === "fallback_review_ready") return "Fallback review ready";
  if (status === "canonical_ready") return "Canonical ready";
  if (status === "literature_ready") return "Literature ready";
  if (status === "world_model_failed") return "World model failed";
  if (status === "git_sync_failed") return "Git sync failed";
  if (status === "raw_only") return "raw only";
  if (status === "raw_synced") return "raw synced";
  if (status === "failed") return "failed";
  if (status === "processing_needed" || status === "world_model_ready") return "not ready";
  if ((item.annotationCount || 0) === 0 && (item.decisionCount || 0) > 0) return "priority annotations pending";
  if ((item.annotatorCount || 0) === 1) return "needs second rater";
  return "needs review";
}

function reviewItemCount(item) {
  return item.decisionCount || item.annotationCandidateCount || 0;
}

function renderRunCard(item) {
  const commit = item.commit ? String(item.commit).slice(0, 12) : "none";
  const lastProcessed = item.lastProcessedAt ? new Date(item.lastProcessedAt).toLocaleString() : "not processed";
  const retryLabel = item.runStatus?.status === "git_sync_failed" ? "Retry sync" : "Retry processing";
  return `
    <article class="run-card" role="button" tabindex="0" data-open-run="${escapeHtml(item.runId)}">
      <div class="run-card-head">
        <span>${escapeHtml(runWorkflowStatus(item))}</span>
        <b>${escapeHtml(runWorkflowStatus(item))}</b>
      </div>
      <strong>${escapeHtml(compactText(item.title || item.runId, 120))}</strong>
      <p>${escapeHtml(compactText(item.summary || "", 180))}</p>
      <div class="run-card-metrics">
        <span>${escapeHtml(item.annotationCount || 0)} annotations</span>
        <span>${escapeHtml(reviewItemCount(item))} review items</span>
        <span>${escapeHtml(item.literatureSourceCount || 0)} literature sources</span>
      </div>
      <div class="run-card-actions">
        <button type="button" data-open-run="${escapeHtml(item.runId)}">Open</button>
        <button type="button" data-retry-run="${escapeHtml(item.runId)}">${escapeHtml(retryLabel)}</button>
      </div>
      <details class="run-card-details">
        <summary>Details</summary>
        <small>Run ID: ${escapeHtml(item.runId)}</small>
        <small>${escapeHtml(item.runStatus?.modeLabel || `Processing status: ${item.runStatus?.status || "raw_only"}`)}</small>
        <small>Last processed: ${escapeHtml(lastProcessed)}</small>
        <small>Commit: ${escapeHtml(commit)}</small>
        <small>Annotation readiness: ${escapeHtml(item.annotationReady ? "ready" : "limited view")}</small>
        <small>${escapeHtml(item.eventCount || 0)} trace events</small>
      </details>
    </article>`;
}

async function openRun(runId) {
  currentRunId = runId;
  currentScreen = "viewer";
  currentView = "overview";
  selectedTargetKey = "";
  selectedRegion = "abstract";
  selectedRegionText = "";
  selectedArtifactPath = "";
  run = null;
  root.innerHTML = `<section class="panel"><p class="muted">Loading run...</p></section>`;
  updateChrome();
  try {
    run = await (await fetch(`/api/run?runId=${encodeURIComponent(runId)}&user=${encodeURIComponent(userEmail || "")}`)).json();
  } catch (error) {
    root.innerHTML = `<section class="panel"><h3>Failed to load run</h3><p>${escapeHtml(error.message)}</p></section>`;
    return;
  }
  title.textContent = researchState().title || run.idea?.title || run.runId || "Run";
  selectedArtifactPath = mainPaperPath();
  setRunStatus();
  render();
}

function render() {
  if (!run) return;
  updateChrome();
  if (currentView === "overview") return renderWhiteboard();
  if (currentView === "steering") return renderSteering();
  if (currentView === "trajectory") return renderJourney();
  if (currentView === "artifacts") return renderReports();
  if (currentView === "autoresearch") return renderAutoResearch();
  if (currentView === "advanced") return developerMode ? renderAdvanced() : renderWhiteboard();
}

function statusCard() {
  const concise = conciseProcessingStatus();
  return `
    <div class="status-card">
      <span class="eyebrow">Processing status</span>
      <strong>${escapeHtml(concise.label)}</strong>
    </div>`;
}

function annotationCounts() {
  const entries = Object.values(annotationMap());
  const annotated = entries.filter((entry) => (entry.individualAnnotations || []).length).length;
  const unresolved = entries.filter((entry) => /unresolved|needs|disagreement/.test(JSON.stringify(entry.benchmarkStatus || entry.status || ""))).length;
  const second = entries.filter((entry) => entry.benchmarkStatus?.needsSecondRater).length;
  const expert = entries.filter((entry) => entry.benchmarkStatus?.needsExpertAdjudication).length;
  const ready = entries.filter((entry) => entry.includeInBenchmark || entry.benchmarkStatus?.workflowStatus === "benchmark_ready").length;
  return { annotated, unresolved, second, expert, ready };
}

function qualityMetrics() {
  const anns = annotationCounts();
  const failures = failedEvents();
  const promoted = priorityCandidates().filter((candidate) => candidate.evidence.some((ref) => /failed|retry|error/i.test(`${ref.note} ${ref.path}`))).length;
  return [
    ["priority issues", priorityCandidates().length],
    ["annotated issues", anns.annotated],
    ["unresolved issues", anns.unresolved],
    ["needs second rater", anns.second],
    ["needs expert adjudication", anns.expert],
    ["benchmark-ready labels", anns.ready],
    ["trace events", canonicalEvents().length || run.liveSummary?.eventCount || 0],
    ["reconstructed decisions", decisions().length],
    ["failed/retried trace steps", failures.length],
    ["promoted failures", promoted],
    ["output artifacts", outputArtifacts().length],
    ["final report exists?", (run.artifacts || []).some((a) => /(^|\/)REPORT\.md$/i.test(artifactPath(a))) ? "yes" : "no"],
  ];
}

function runMetrics() {
  const source = run?.runMetrics || run?.metrics || run?.liveSummary || {};
  const values = [];
  const pick = (...keys) => keys.map((key) => source[key] ?? run?.[key]).find((value) => value !== undefined && value !== null && value !== "");
  const runtime = pick("runtime", "runtimeSeconds", "durationSeconds", "elapsedSeconds");
  const tokens = pick("tokenUsage", "tokens", "totalTokens");
  const cost = pick("cost", "estimatedCost", "usdCost");
  const pressure = pick("contextPressure", "memoryPressure", "contextMemoryPressure");
  if (runtime !== undefined) values.push(["runtime", typeof runtime === "number" ? `${runtime}s` : runtime]);
  if (tokens !== undefined) values.push(["token usage", tokens]);
  if (cost !== undefined) values.push(["cost", typeof cost === "number" ? `$${cost.toFixed(4)}` : cost]);
  if (pressure !== undefined) values.push(["context/memory pressure", pressure]);
  return values;
}

function queueStatus(candidate) {
  const anno = latestAnnotation(candidate.key);
  const workflow = anno.workflowStatus || anno.benchmarkStatus?.workflowStatus || "";
  if (anno.annotationRoute === "fix_request") return "fix request";
  if (anno.annotationRoute === "dismissed") return "dismissed";
  if (anno.includeInBenchmark || workflow === "benchmark_ready") return "benchmark-ready";
  if (anno.needsExpertAdjudication || /expert/.test(workflow)) return "needs expert review";
  if (anno.quickComment || anno.rationale || anno.comment || (annotationFor(candidate.key).individualAnnotations || []).length) return "annotated";
  return "unannotated";
}

function routeLabel(route) {
  return {
    fix_request: "fix request",
    benchmark_annotation: "benchmark annotation",
    expert_escalation: "expert escalation",
    dismissed: "dismissed",
  }[route] || "benchmark annotation";
}

function normalizeImpactTypes(value) {
  const items = Array.isArray(value) ? value : String(value || "").split(",");
  const out = items.map((item) => String(item || "").trim()).filter((item) => IMPACT_TYPES.includes(item));
  return out.length ? [...new Set(out)] : ["writing_only"];
}

function candidateImpactDefaults(candidate, checklist = {}) {
  const text = `${candidate.title || ""} ${candidate.summary || ""} ${candidate.finding?.text || ""} ${affectedOutput(candidate)} ${reviewReason(candidate)}`.toLowerCase();
  const impactType = [];
  if (/result|accuracy|metric|evaluation|finding|primary/.test(text) || checklist.mayAffectResult) impactType.push("results");
  if (/abstract/.test(text)) impactType.push("abstract_claim");
  if (/main claim|headline|claim|conclusion/.test(text)) impactType.push("main_claim");
  if (/method|validity|dataset|split|protocol|metric/.test(text)) impactType.push("method_validity");
  if (/experiment|design|setup/.test(text)) impactType.push("experiment_design");
  if (/statistic|significance|paired|p-value|confidence/.test(text)) impactType.push("statistical_inference");
  if (/baseline|control|ablation/.test(text)) impactType.push("baseline_control");
  if (/reproduc|seed|code|data availability/.test(text)) impactType.push("reproducibility");
  if (/direction|hypothesis|future/.test(text)) impactType.push("research_direction");
  if (/cost|resource|token|runtime|budget/.test(text)) impactType.push("cost_or_resource_metric");
  if (!impactType.length) impactType.push(/format|typo|caption|wording|clarity|grammar/.test(text) ? "writing_only" : "results");
  return [...new Set(impactType)];
}

function eligibilityFor(candidate, anno = {}, checklist = {}) {
  const impactType = normalizeImpactTypes(anno.impactType?.length ? anno.impactType : candidateImpactDefaults(candidate, checklist));
  const highImpact = impactType.some((item) => HIGH_IMPACT_TYPES.has(item));
  const lowImpactOnly = impactType.every((item) => item === "writing_only" || item === "formatting_only");
  const uncertaintyHigh = /uncertain|unclear|no|not enough|expert/i.test(`${anno.evidenceSufficient || ""} ${anno.confidence || ""} ${anno.reviewerComment || ""} ${anno.rationale || ""}`)
    || checklist.needsMoreEvidence;
  const mustAnnotate = highImpact;
  const autoFixCandidate = lowImpactOnly && !highImpact;
  const needsExpertReview = Boolean(anno.needsExpertReview || anno.needsExpertAdjudication || (mustAnnotate && uncertaintyHigh && !autoFixCandidate));
  const route = anno.annotationRoute || (needsExpertReview ? "expert_escalation" : autoFixCandidate ? "fix_request" : mustAnnotate ? "benchmark_annotation" : "dismissed");
  return {
    impactType,
    mustAnnotate,
    autoFixCandidate,
    needsExpertReview,
    fixability: needsExpertReview ? "needs_expert_judgment" : autoFixCandidate ? "llm_fixable" : "needs_human_judgment",
    annotationRoute: ROUTES.includes(route) ? route : "benchmark_annotation",
    affectedOutput: humanList(anno.affectedOutput?.length ? anno.affectedOutput : [affectedOutput(candidate)], "Main Paper"),
    impactReason: anno.impactReason || reviewReason(candidate),
  };
}

function affectedOutput(candidate) {
  if (isSplitAllocationIssue(candidate)) return "Abstract";
  const section = candidate.decision?.paperRef?.section || candidate.decision?.affectedOutput || selectedRegion || "";
  if (section) return titleCaseLabel(String(section).replaceAll("_", " "));
  const text = `${candidate.title || ""} ${candidate.summary || ""}`.toLowerCase();
  const sections = [];
  if (/abstract|claim|headline/.test(text)) sections.push("Abstract");
  if (/method|dataset|split|vocab|baseline|setup|allocation/.test(text)) sections.push("Method");
  if (/result|accuracy|metric|evaluation/.test(text)) sections.push("Results");
  if (/limitation|leakage|risk|validity|caveat/.test(text)) sections.push("Limitations");
  return sections.length ? sections.join(" / ") : "Main Paper";
}

function titleCaseLabel(value) {
  return String(value || "").replace(/\b\w/g, (char) => char.toUpperCase());
}

function reviewReason(candidate) {
  const text = candidate.finding?.show_reason || candidate.decision?.importanceRationale || candidate.summary || candidate.finding?.text || "";
  if (text) return compactText(text, 140);
  return "affects whether the generated paper is reliable.";
}

function relatedFiles(candidate) {
  if (isSplitAllocationIssue(candidate)) {
    const wanted = [
      ["Main Paper", /(^|\/)main\.(pdf|md|tex)$|paper|report/i],
      ["Split Counts Summary", /split.*count|count.*split|summary/i],
      ["Experiment Config Summary", /config.*summary|summary.*config|experiment.*config|planning/i],
      ["Candidate Vocabulary Table", /candidate.*vocab|vocab.*candidate/i],
    ];
    return wanted.map(([note, pattern]) => {
      const artifact = outputArtifacts().find((item) => pattern.test(artifactPath(item))) || {};
      return { path: artifactPath(artifact) || (note === "Main Paper" ? mainPaperPath() : ""), note };
    }).filter((ref) => ref.path);
  }
  const refs = dedupeRefs([
    { path: mainPaperPath(), note: "Main Paper" },
    ...(candidate.evidence || []),
  ]);
  const byLabel = [
    ["Candidate Vocabulary Table", /candidate.*vocab|vocab.*candidate/i],
    ["Split Counts Summary", /split.*count|counts.*split/i],
    ["Experiment Config Summary", /config.*summary|summary.*config|experiment.*config/i],
    ["Accuracy Figure", /accuracy|figure|plot|chart/i],
    ["Final Report", /report/i],
  ];
  for (const [note, pattern] of byLabel) {
    const artifact = outputArtifacts().find((item) => pattern.test(artifactPath(item)));
    if (artifact) refs.push({ path: artifactPath(artifact), note });
  }
  return dedupeRefs(refs).slice(0, 6);
}

async function createManualIssue(kind = "manual_crux", stage = "") {
  if (!run) return;
  const defaultComment = kind === "llm_missed_issue"
    ? "LLM missed an issue that should be reviewed."
    : kind === "expert_review"
      ? "Needs expert review."
      : "Manual crux created by reviewer.";
  const titleText = window.prompt("Issue title", kind === "llm_missed_issue" ? "LLM missed a crux" : "New review issue") || (kind === "llm_missed_issue" ? "LLM missed a crux" : "New review issue");
  const comment = window.prompt("Reviewer comment", root.querySelector?.('[name="reviewerComment"]')?.value || defaultComment) || defaultComment;
  const reason = window.prompt("Reason", defaultComment) || defaultComment;
  const severity = window.prompt("Severity: low, medium, or high", "medium") || "medium";
  const key = `${MANUAL_SOURCES[kind] || "manual_crux"}:${Date.now()}`;
  const now = new Date().toISOString();
  const anchor = currentAnchor();
  const payload = {
    key,
    targetKey: key,
    targetType: "manual_crux",
    source: kind === "llm_missed_issue" ? "llm_missed_issue" : "manual_crux",
    stage: stage || journeyStages()[selectedJourneyStage]?.name || selectedRegion || "Whiteboard",
    affectedOutput: selectedArtifactPath || mainPaperPath(),
    title: titleText,
    comment,
    reasonForEscalation: reason,
    severity,
    needsExpertReview: kind === "expert_review",
    needsExpertAdjudication: kind === "expert_review",
    reviewerComment: comment,
    quickComment: comment,
    selectedRegion,
    selectedArtifact: selectedArtifactPath || mainPaperPath(),
    anchor,
    paperAnchor: anchor,
    relatedFiles: [{ path: selectedArtifactPath || mainPaperPath(), note: humanTitle(selectedArtifactPath || mainPaperPath()) }],
    benchmarkStatus: { workflowStatus: kind === "expert_review" ? "needs_expert_adjudication" : "annotated", mode: "manual" },
    autoCapturedContext: {
      runId: currentRunId,
      source: kind === "llm_missed_issue" ? "llm_missed_issue" : "manual_crux",
      stage: stage || journeyStages()[selectedJourneyStage]?.name || selectedRegion || "Whiteboard",
      affectedOutput: selectedArtifactPath || mainPaperPath(),
      anchor,
      raterId: userEmail || "anonymous",
      timestamp: now,
    },
    benchmarkDraft: {
      issueType: "other",
      suggestedAction: kind === "expert_review" ? "request clarification" : "revise paper/output",
      evidenceSufficient: "uncertain",
      includeInBenchmark: false,
      severity,
    },
    humanConfirmedLabels: {
      comment,
      needsExpertReview: kind === "expert_review",
    },
    reviewerVerification: {
      selectedIssue: titleText,
      selectedSection: selectedRegion,
      anchor,
      reviewerComment: comment,
      needsExpertReview: kind === "expert_review",
      verifiedAt: now,
    },
    createdAt: now,
    updatedAt: now,
  };
  await fetch("/api/annotation", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(withRun(payload)),
  });
  selectedTargetKey = key;
  currentView = "steering";
  await openRun(currentRunId);
  selectedTargetKey = key;
  currentView = "steering";
  render();
}

function renderWhiteboard() {
  const ws = researchState();
  const idea = run.idea?.hypothesis || run.idea?.description || ws.narrative || ws.headline || "";
  const mainClaim = ws.headline || ws.currentBest || firstSentence(ws.abstract || ws.narrative || "");
  const primaryResult = ws.currentBest || findings().find((finding) => finding.kind === "result")?.text || ws.conclusion || "";
  const abstract = ws.abstract || ws.narrative || "";
  const cards = [
    ["hypothesis", "Research idea / hypothesis", idea || "No research idea reconstructed."],
    ["claim", "Main claim", mainClaim || "No main claim reconstructed."],
    ["result", "Primary result", primaryResult || "No primary result reconstructed."],
    ["abstract", "Abstract", abstract || "No abstract reconstructed."],
  ];
  const queue = topGlobalCruxes();
  root.innerHTML = `
    <div class="whiteboard-page">
      <section class="whiteboard-hero">
        <div class="hero-main">
          <div class="whiteboard-header-row">
            <div>
              <span class="eyebrow">Whiteboard</span>
            </div>
            <div class="hero-actions compact-actions">
              <button data-read-report>Read paper</button>
              <button data-view-all-decisions>View all decisions</button>
            </div>
          </div>
          <div class="claim-lanes four">
            ${cards.map(([key, label, text]) => `
              <article role="button" tabindex="0" data-open-whiteboard-card="${escapeHtml(key)}">
                <span>${escapeHtml(label)}</span>
                <p>${escapeHtml(text)}</p>
                <button type="button" data-review-whiteboard-target="${escapeHtml(key)}">Review</button>
              </article>`).join("")}
          </div>
          ${selectedWhiteboardCard ? renderWhiteboardCardDrawer(cards.find(([key]) => key === selectedWhiteboardCard) || cards[0]) : ""}
        </div>
        <aside>
          <div class="output-card">
            <span class="eyebrow">Processing</span>
            <strong>${escapeHtml(conciseProcessingStatus().label)}</strong>
            <small>${escapeHtml(processingStatusDetail())}</small>
          </div>
          <div class="output-card">
            <span class="eyebrow">Annotation</span>
            <strong>${escapeHtml(annotationCounts().annotated)} / ${escapeHtml(priorityCandidates(true).length)} reviewed</strong>
          </div>
        </aside>
      </section>

      <section class="panel annotation-queue">
        <div class="panel-head">
          <div>
            <h3>Top global cruxes</h3>
          </div>
          <button data-view-all-decisions>View all decisions</button>
        </div>
        <div class="annotation-queue-list">
          ${queue.map((candidate, index) => `
            <article class="annotation-queue-item">
              <div>
                <strong>#${index + 1} ${escapeHtml(compactText(candidate.title, 120))}</strong>
                <p><b>Global impact:</b> ${escapeHtml(reviewReason(candidate))}</p>
                <small>Affected output: ${escapeHtml(affectedOutput(candidate))}</small>
                <small>Status: ${escapeHtml(queueStatus(candidate))}</small>
              </div>
              <button data-open-target="${escapeHtml(candidate.key)}">Review</button>
            </article>`).join("") || `<p class="muted">No priority annotation issue reconstructed yet.</p>`}
        </div>
      </section>
    </div>`;
  wireWhiteboard();
}

function renderWhiteboardCardDrawer(card) {
  const [key, label, text] = card;
  return `
    <aside class="whiteboard-card-drawer">
      <div class="panel-head compact">
        <div><span class="eyebrow">${escapeHtml(label)}</span></div>
        <button type="button" data-close-whiteboard-card>Close</button>
      </div>
      <p>${escapeHtml(text)}</p>
      <div class="context-actions compact-row">
        <button type="button" data-review-whiteboard-target="${escapeHtml(key)}">Review</button>
      </div>
    </aside>`;
}

function processingStatusDetail() {
  const statusValue = run?.runStatus?.status || "raw_only";
  if (statusValue === "failed") return run?.runStatus?.error || run?.runStatus?.message || "Brief error unavailable.";
  if (statusValue === "completed" || statusValue === "annotation_ready") return "";
  return run?.runStatus?.progress || run?.runStatus?.modeLabel || conciseProcessingStatus().detail || "running";
}

function topGlobalCruxes() {
  return priorityCandidates(true)
    .filter((candidate) => {
      const text = `${candidate.title} ${candidate.summary} ${reviewReason(candidate)} ${affectedOutput(candidate)}`.toLowerCase();
      return candidate.score >= 25 || /abstract|claim|headline|validity|reliability|dataset|split|result|method|limitation|evidence/.test(text);
    })
    .slice(0, 10);
}

function renderQueueChain(candidate) {
  const finding = candidate.finding;
  const evidence = candidate.evidence[0];
  return `
    <article class="queue-chain">
      <button data-open-finding="${escapeHtml(finding?.id || "")}" ${finding ? "" : "disabled"}>
        <span>Finding</span><strong>${escapeHtml(finding?.id || "run")}</strong><small>${escapeHtml(compactText(finding?.text || researchState().headline || "", 90))}</small>
      </button>
      <i></i>
      <button data-open-target="${escapeHtml(candidate.key)}">
        <span>Decision</span><strong>${escapeHtml(candidate.targetId)}</strong><small>${escapeHtml(compactText(candidate.title, 90))}</small>
      </button>
      <i></i>
      <button data-open-report="${escapeHtml(evidence?.path || mainPaperPath())}">
        <span>Evidence / Output</span><strong>${escapeHtml(evidence?.path || mainPaperPath())}</strong><small>${escapeHtml(evidence?.note || "paper/report region")}</small>
      </button>
      <i></i>
      <div class="chain-actions">
        <button data-open-target="${escapeHtml(candidate.key)}">Open in Steering</button>
        <button data-open-journey-target="${escapeHtml(candidate.targetId)}">Open in Journey</button>
        <button data-open-report="${escapeHtml(evidence?.path || mainPaperPath())}">Open Report/Table/Figure</button>
      </div>
    </article>`;
}

function wireWhiteboard() {
  root.querySelectorAll("[data-read-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = mainPaperPath();
    openedReports = true;
    currentView = "artifacts";
    render();
  }));
  root.querySelector("[data-toggle-abstract]")?.addEventListener("click", () => {
    const el = root.querySelector("#abstract-drawer");
    if (el) el.open = !el.open;
  });
  root.querySelectorAll("[data-open-whiteboard-card]").forEach((card) => card.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    selectedWhiteboardCard = card.dataset.openWhiteboardCard || "";
    renderWhiteboard();
  }));
  root.querySelector("[data-close-whiteboard-card]")?.addEventListener("click", () => {
    selectedWhiteboardCard = "";
    renderWhiteboard();
  });
  root.querySelectorAll("[data-review-whiteboard-target]").forEach((button) => button.addEventListener("click", () => {
    const target = button.dataset.reviewWhiteboardTarget;
    selectedRegion = target === "result" ? "results" : target === "hypothesis" ? "method" : "abstract";
    const candidates = priorityCandidates(true);
    const found = candidates.find((candidate) => {
      const text = `${candidate.title} ${candidate.summary} ${affectedOutput(candidate)}`.toLowerCase();
      if (target === "hypothesis") return /hypothesis|idea|direction|research/.test(text);
      if (target === "claim") return /claim|support|abstract|conclusion/.test(text);
      if (target === "result") return /result|accuracy|metric|evaluation/.test(text);
      return /abstract|paper|claim/.test(text);
    }) || candidates[0];
    selectedTargetKey = found?.key || "";
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-open-steering]").forEach((button) => button.addEventListener("click", () => {
    selectedTargetKey = priorityCandidates()[0]?.key || "";
    sidebarExpandedOverride = false;
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-view-all-decisions]").forEach((button) => button.addEventListener("click", () => {
    showAllReviewIssues = true;
    showAllSteeringCandidates = true;
    selectedTargetKey = priorityCandidates(true)[0]?.key || "";
    sidebarExpandedOverride = false;
    currentView = "steering";
    render();
  }));
  root.querySelector("[data-open-journey]")?.addEventListener("click", () => {
    selectedReviewSource = "journey_escalation";
    openedJourney = true;
    sidebarExpandedOverride = false;
    currentView = "trajectory";
    render();
  });
  root.querySelectorAll("[data-open-target]").forEach((button) => button.addEventListener("click", () => {
    selectedTargetKey = button.dataset.openTarget;
    applyCandidatePaperAnchor(selectedTargetKey);
    selectedReviewSource = "ranked_queue";
    sidebarExpandedOverride = false;
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-open-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.openReport;
    openedReports = true;
    sidebarExpandedOverride = false;
    currentView = "artifacts";
    render();
  }));
  root.querySelectorAll("[data-open-journey-target]").forEach((button) => button.addEventListener("click", () => {
    selectedTargetKey = `decision:${button.dataset.openJourneyTarget}`;
    selectedReviewSource = "journey_escalation";
    openedJourney = true;
    currentView = "trajectory";
    render();
  }));
}

function outputSections() {
  const ws = researchState();
  return [
    ["abstract", "Abstract", ws.abstract || ws.narrative || ""],
    ["method", "Method", sectionText("method") || (ws.methodology || []).join(" ")],
    ["results", "Results", ws.currentBest || findings().map((f) => f.text || f.insight).filter(Boolean).slice(0, 3).join(" ")],
    ["discussion", "Discussion", ws.headline || ws.crux || ""],
    ["limitations", "Limitations", (ws.openQuestions || []).map((q) => q.text || q).join(" ") || (ws.consistencyWarnings || []).join(" ")],
  ];
}

function sectionText(key) {
  const sections = researchState().sections || {};
  return sections[key] || sections[key.charAt(0).toUpperCase() + key.slice(1)] || "";
}

function renderSteering() {
  const candidate = selectedCandidate();
  selectedTargetKey = candidate.key;
  root.innerHTML = `
    <div class="steering-page">
      <section class="steering-panel output-panel">
        ${renderOutputViewer(candidate)}
      </section>
      <section class="steering-panel annotation-panel steering-right" data-anno-key="${escapeHtml(candidate.key)}" data-legacy-key="${escapeHtml(candidate.legacyKey || "")}">
        ${renderAnnotationWorkspace(candidate)}
      </section>
      ${showAllReviewIssues ? renderAllReviewIssuesPanel(candidate) : ""}
    </div>`;
  wireSteering(candidate);
  renderPdfViewer(candidate);
}

function renderOutputViewer(candidate) {
  const pdfUrl = paperPdfUrlFor(candidate);
  const sections = outputSections();
  const fallback = sections.map(([key, label, text]) => `
    <button class="doc-section ${key === selectedRegion ? "active" : ""}" data-select-region="${escapeHtml(key)}" data-region-text="${escapeHtml(text || label)}">
      <span>${escapeHtml(label)}</span>
      <p>${escapeHtml(compactText(text || "No section text reconstructed.", 240))}</p>
    </button>`).join("");
  return `
    <div class="paper-head compact">
      <div>
        <h3>Paper</h3>
        <small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(mainPaperPath())}</small>
      </div>
    </div>
    <div class="sticky-section-toolbar paper-toolbar compact-paper-toolbar">
      <div class="annotation-tools" aria-label="Paper annotation tools">
        ${[
          ["highlight", "Highlight"],
          ["comment", "Comment"],
          ["box", "Box comment"],
          ["ask", "Ask"],
          ["escalate", "Escalate"],
        ].map(([tool, label]) => `<button type="button" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}" class="${annotationTool === tool ? "active" : ""}" data-tool="${tool}">${escapeHtml(label)}</button>`).join("")}
      </div>
    </div>
    <div class="pdfjs-viewer" data-pdf-url="${escapeHtml(pdfUrl ? paperPdfUrl() : "")}" data-target-key="${escapeHtml(candidate.key)}">
      ${pdfUrl ? `<div class="pdf-loading">Loading paper...</div>` : `<div class="paper-text-view">${fallback}</div>`}
    </div>
    <div class="paper-anchor-status" aria-live="polite">${escapeHtml(anchorStatusText())}</div>`;
}

function renderAnnotationWorkspace(candidate) {
  const anno = latestAnnotation(candidate.key);
  const suggestions = benchmarkDraft(candidate, anno);
  const summary = reviewSummaryFor(candidate);
  const checklist = reviewerChecklistValues(anno, suggestions);
  const eligibility = eligibilityFor(candidate, { ...suggestions, ...anno }, checklist);
  const comments = annotationComments(candidate);
  const role = currentRole === "expert" || developerMode ? currentRole : "reviewer";
  return `
    <div class="annotation-workspace">
      <div class="panel-head">
        <div>
          <span class="eyebrow">Reviewer panel</span>
          <h3>Review issue</h3>
        </div>
      </div>
      <form id="annotation-form" class="annotation-form">
        <section class="issue-question-section">
          <h4>Issue</h4>
          <p class="issue-question">${escapeHtml(summary.decision || summary.issueTitle || "Should this output be trusted as written?")}</p>
          <h4>Why it matters</h4>
          <p class="affected-output-line">It affects: ${escapeHtml(summary.affected)}.</p>
          <p class="issue-why">${escapeHtml(summary.why)}</p>
          <h4>What NeuriCo chose</h4>
          <p class="issue-choice">${escapeHtml(summary.chosen)}</p>
          <details class="review-summary-section compact-context">
            <summary>More context</summary>
            ${renderReviewSummary(summary)}
          </details>
        </section>

        <section class="reviewer-check">
          <h4>Reviewer check</h4>
          <div class="check-row reviewer-checklist">
            ${checkboxField("choiceReasonable", "This looks reasonable", checklist.choiceReasonable)}
            ${checkboxField("needsMoreEvidence", "Needs more evidence", checklist.needsMoreEvidence)}
            ${checkboxField("paperExplainBetter", "Paper should explain this better", checklist.paperExplainBetter)}
            ${checkboxField("mayAffectResult", "This may affect the result", checklist.mayAffectResult)}
            ${checkboxField("userShouldBeUpdated", "User should be updated", checklist.userShouldBeUpdated)}
            ${checkboxField("agentShouldRevise", "Agent should revise / rerun", checklist.agentShouldRevise)}
            ${checkboxField("notCoveredCreateIssue", "Not covered by this issue / create new issue", checklist.notCoveredCreateIssue)}
          </div>
        </section>

        <section class="quick-annotation">
          ${textField("reviewerComment", "Write your review comment", anno.reviewerComment || anno.quickComment || anno.rationale || anno.comment, 7)}
          <div class="fix-request-fields ${eligibility.autoFixCandidate || anno.annotationRoute === "fix_request" ? "" : "muted-box"}">
            <div class="form-grid two">
              ${selectField("fixType", "Fix type", ["", ...FIX_TYPES], anno.fixRequest?.fixType || "")}
              ${textField("proposedFix", "Proposed fix", anno.fixRequest?.proposedFix || "", 2)}
            </div>
          </div>
          <div class="dismiss-fields ${anno.annotationRoute === "dismissed" ? "" : "dev-hidden"}">
            ${textField("dismissedReason", "Dismiss reason", anno.dismissedReason || "", 2)}
          </div>
          <div class="form-actions quick-actions action-row compact-row">
            <button type="submit" data-route-action="fix_request">Ask NeuriCo to fix</button>
            <button type="submit" data-route-action="benchmark_annotation">Save benchmark annotation</button>
            <button type="submit" data-route-action="expert_escalation">Needs expert review</button>
            <button type="submit" data-route-action="dismissed">Dismiss / not important</button>
            <span id="save-status"></span>
          </div>
        </section>

        <section class="prefilled-label">
          <div class="section-title-row">
            <h4>Pre-filled label to verify</h4>
            <div class="suggestion-actions">
              <button type="button" data-accept-prefill>Accept</button>
              <button type="button" data-edit-prefill>Edit</button>
              <button type="button" data-escalate-section>Escalate</button>
            </div>
          </div>
          ${renderPreFilledLabel({ ...suggestions, annotationRoute: eligibility.annotationRoute }, anno)}
          <div class="prefill-edit ${editingPrelabel ? "" : "dev-hidden"}">
            <div class="form-grid three">
              ${selectField("suggestedAction", "Suggested action", SUGGESTED_ACTIONS, anno.suggestedAction || suggestions.suggestedAction)}
              ${selectField("cruxType", "Crux", CRUX_TYPES, anno.cruxType || suggestions.cruxType)}
              ${selectField("evidenceSufficient", "Evidence sufficiency", YES_NO_UNCERTAIN, anno.evidenceSufficient || suggestions.evidenceSufficient)}
              ${selectField("severity", "Severity", ["", "low", "medium", "high"], anno.severity || suggestions.severity)}
              ${selectField("confidence", "Confidence", LEVELS, anno.confidence || suggestions.confidence)}
              ${selectField("annotationRoute", "Suggested route", ROUTES, anno.annotationRoute || eligibility.annotationRoute)}
            </div>
          </div>
        </section>

        <section class="comment-thread-panel">
          <h4>Paper comments</h4>
          ${comments.map((comment) => renderCommentThreadItem(comment)).join("") || `<p class="muted">No paper-linked comments saved yet.</p>`}
        </section>

        <section class="missing-issue-panel">
          <h4>Something important missing?</h4>
          <div class="form-actions compact-row secondary-actions">
            <button type="button" data-create-manual="manual_crux">New issue</button>
            <button type="button" data-create-manual="llm_missed_issue">LLM missed crux</button>
            <button type="button" data-create-manual="expert_review">Escalate section</button>
            <button type="button" data-escalate-whole-paper>Escalate paper</button>
          </div>
        </section>

        ${renderReviewAssistant(candidate, anno)}

        ${role === "expert" ? renderExpertQueue(candidate) : ""}

        <details class="benchmark-labels ${developerMode ? "" : "dev-hidden"}" ${developerMode ? "open" : ""}>
          <summary>Developer details</summary>
          <section>
            <div class="form-grid three">
              ${selectField("steeringDecision", "steeringDecision", STEERING_DECISIONS, anno.steeringDecision || suggestions.steeringDecision)}
              ${selectField("claimSupported", "Claim supported", SUPPORT_LEVELS, anno.claimSupported || suggestions.claimSupported)}
            </div>
            <div class="form-grid two">
              ${textField("rationale", "rationale", anno.rationale || suggestions.rationale, 3)}
              ${textField("missingInfo", "missingInfo / uncertainty", anno.missingInfo || anno.uncertainty || anno.surfaceContextToUser, 2)}
            </div>
            <div class="check-row">
              ${checkboxField("includeInBenchmark", "includeInBenchmark", anno.includeInBenchmark || suggestions.includeInBenchmark)}
            </div>
            <div class="form-grid three">
              ${selectField("impactType", "impactType", IMPACT_TYPES, eligibility.impactType[0] || "")}
              ${selectField("fixability", "fixability", ["", "llm_fixable", "needs_human_judgment", "needs_expert_judgment"], anno.fixability || eligibility.fixability)}
              ${selectField("annotationRoute", "annotationRoute", ROUTES, anno.annotationRoute || eligibility.annotationRoute)}
            </div>
            <div class="form-grid three">
              ${selectField("finalLabel", "final label", ["", "valid", "invalid", "unclear", "needs_more_evidence"], anno.finalLabel || "")}
              ${selectField("adjudicationStatus", "gold label status", ["", "not_gold", "candidate_gold", "gold", "excluded"], anno.adjudicationStatus || "")}
              ${selectField("includeInBenchmarkDecision", "include in benchmark", ["", "yes", "no"], anno.includeInBenchmark ? "yes" : "")}
            </div>
          </section>
          <input type="hidden" name="issueType" value="${escapeHtml(anno.issueType || suggestions.issueType)}">
          <input type="hidden" name="suggestedAction" value="${escapeHtml(anno.suggestedAction || suggestions.suggestedAction)}">
          <input type="hidden" name="suggestedUserUpdate" value="${escapeHtml(anno.suggestedUserUpdate || suggestions.suggestedUserUpdate)}">
          <input type="hidden" name="suggestedAgentFeedback" value="${escapeHtml(anno.suggestedAgentFeedback || suggestions.suggestedAgentFeedback)}">
          <input type="hidden" name="workflowStatus" value="${escapeHtml(anno.workflowStatus || anno.benchmarkStatus?.workflowStatus || "")}">
          <input type="hidden" name="needsExpertAdjudication" value="${anno.needsExpertAdjudication ? "on" : ""}">
          <label><span>Rater role</span><select name="raterRole">${RATER_ROLES.map((item) => `<option value="${escapeHtml(item)}" ${item === (anno.raterRole || role) ? "selected" : ""}>${escapeHtml(item)}</option>`).join("")}</select></label>
          <input type="hidden" name="expertiseArea" value="${escapeHtml(anno.expertiseArea || "")}">
          <input type="hidden" name="guidelineVersion" value="${escapeHtml(anno.guidelineVersion || "v0.1")}">
          <input type="hidden" name="annotationRound" value="${escapeHtml(anno.annotationRound || 1)}">
          ${renderBenchmarkPreview(candidate, anno)}
        </details>
        <input type="hidden" name="raterRole" value="${escapeHtml(role)}">
      </form>
    </div>`;
}

function selectField(name, label, options, current) {
  return `<label><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}">${options.map((option) => `<option value="${escapeHtml(option)}" ${option === current ? "selected" : ""}>${escapeHtml(option || "unspecified")}</option>`).join("")}</select></label>`;
}

function inputField(name, label, current, type = "text") {
  return `<label><span>${escapeHtml(label)}</span><input name="${escapeHtml(name)}" type="${escapeHtml(type)}" value="${escapeHtml(current || "")}"></label>`;
}

function textField(name, label, current, rows = 2) {
  return `<label><span>${escapeHtml(label)}</span><textarea name="${escapeHtml(name)}" rows="${rows}">${escapeHtml(current || "")}</textarea></label>`;
}

function checkboxField(name, label, current) {
  return `<label class="check-field"><input name="${escapeHtml(name)}" type="checkbox" ${current ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
}

function renderPreFilledLabel(suggestions, anno = {}) {
  const route = anno.annotationRoute || suggestions.annotationRoute || "benchmark_annotation";
  const rows = [
    ["Suggested route", routeLabel(route)],
    ["Suggested action", anno.suggestedAction || suggestions.suggestedAction],
    ["Crux", anno.cruxType || suggestions.cruxType],
    ["Evidence sufficiency", anno.evidenceSufficient || suggestions.evidenceSufficient],
    ["Severity", anno.severity || suggestions.severity],
    ["Confidence", anno.confidence || suggestions.confidence],
  ];
  return `<dl class="prefill-grid">${rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(humanLabelValue(value) || "unspecified")}</dd>`).join("")}</dl>`;
}

function humanLabelValue(value) {
  return String(value || "").replaceAll("_", " ").replace(/\s*\/\s*/g, " / ").trim();
}

function renderCommentThreadItem(comment) {
  return `
    <button type="button" class="comment-thread-item ${comment.id === activeCommentId ? "active" : ""}" data-focus-anchor="${escapeHtml(comment.id)}">
      <span>${escapeHtml(comment.status)}</span>
      <strong>${escapeHtml(compactText(comment.text || "Paper annotation", 140))}</strong>
      <small>${escapeHtml(comment.author)} · ${escapeHtml(comment.role)} · ${escapeHtml(comment.selectedSection || "")} · ${escapeHtml(comment.anchorType || "")}</small>
    </button>`;
}

function renderExpertQueue(candidate) {
  const pending = allReviewIssues().filter((item) => {
    const anno = latestAnnotation(item.key);
    return anno.needsExpertAdjudication || anno.needsExpertReview || anno.adjudicationStatus === "pending" || queueStatus(item) === "needs expert review";
  });
  return `
    <section class="expert-queue-panel">
      <h4>Expert adjudication</h4>
      <div class="expert-case-list">
        ${pending.map((item) => {
          const anno = latestAnnotation(item.key);
          const eligibility = eligibilityFor(item, anno, reviewerChecklistValues(anno, {}));
          return `<button type="button" class="${item.key === candidate.key ? "active" : ""}" data-context-target="${escapeHtml(item.key)}">
          <strong>${escapeHtml(compactText(item.title, 120))}</strong>
          <span>Affected output: ${escapeHtml(eligibility.affectedOutput[0] || affectedOutput(item))}</span>
          <span>Why it matters: ${escapeHtml(compactText(eligibility.impactReason, 140))}</span>
          <span>Prelabel: ${escapeHtml(routeLabel(eligibility.annotationRoute))} · ${escapeHtml(anno.severity || "severity unset")}</span>
        </button>`;
        }).join("") || `<p class="muted">No pending expert cases.</p>`}
      </div>
      <div class="form-grid three">
        ${selectField("finalLabel", "Final label", ["", "valid", "invalid", "unclear", "needs_more_evidence"], latestAnnotation(candidate.key).finalLabel || "")}
        ${selectField("adjudicationStatus", "Gold label status", ["", "pending", "candidate_gold", "gold", "excluded"], latestAnnotation(candidate.key).adjudicationStatus || "pending")}
        ${selectField("includeInBenchmarkDecision", "Include benchmark", ["", "yes", "no"], latestAnnotation(candidate.key).includeInBenchmark ? "yes" : "")}
      </div>
    </section>`;
}

function anchorStatusText() {
  const anchor = currentAnchor();
  if (anchor.type === ANCHOR_TYPES.TEXT) return `Text anchor selected on page ${anchor.page || "?"}: ${compactText(anchor.selectedText, 90)}`;
  if (anchor.type === ANCHOR_TYPES.BOX) return `Box anchor selected on page ${anchor.page || "?"}`;
  return `Section anchor: ${selectedSectionLabel()}`;
}

function aiSuggestedLabels(candidate) {
  if (isSplitAllocationIssue(candidate)) {
    return {
      issueType: "missing evidence",
      suggestedAction: "update user",
      steeringDecision: "update_user",
      cruxType: "missing_evidence",
      claimSupported: "unclear",
      evidenceSufficient: "uncertain",
      confidence: "medium",
      severity: "high",
      impactType: ["results", "method_validity", "statistical_inference"],
      annotationRoute: "benchmark_annotation",
      suggestedUserUpdate: "Tell the user the validation budget may make the layer-5 result sensitive to the small validation set.",
      suggestedAgentFeedback: "Add evidence or rerun with a larger validation allocation before relying on the headline layer-selection result.",
    };
  }
  const text = `${candidate.title || ""} ${candidate.summary || ""} ${candidate.finding?.text || ""}`.toLowerCase();
  const missingEvidence = /evidence|support|prove|validate|baseline|ablation/.test(text);
  const unsupported = /claim|overclaim|conclusion|result/.test(text);
  const experiment = /experiment|metric|dataset|baseline|run|evaluation/.test(text);
  const shouldInterrupt = Boolean(candidate.decision?.shouldEngage || candidate.decision?.pass1ShouldEngage || candidate.score > 55);
  return {
    issueType: missingEvidence ? "missing evidence" : unsupported ? "unsupported claim" : experiment ? "weak experiment" : "unclear writing",
    suggestedAction: shouldInterrupt ? "interrupt / redirect" : missingEvidence ? "gather more evidence" : unsupported ? "revise paper/output" : "continue",
    steeringDecision: shouldInterrupt ? "interrupt_redirect" : missingEvidence ? "request_clarification" : unsupported ? "update_user" : "continue",
    cruxType: missingEvidence ? "missing_evidence" : unsupported ? "unsupported_claim" : experiment ? "bad_experiment_plan" : "other",
    claimSupported: unsupported || missingEvidence ? "unclear" : "partially_supported",
    evidenceSufficient: missingEvidence || unsupported ? "uncertain" : "yes",
    confidence: candidate.score > 55 ? "medium" : "low",
    severity: shouldInterrupt ? "high" : unsupported || missingEvidence ? "medium" : "low",
    impactType: candidateImpactDefaults(candidate, {}),
    annotationRoute: shouldInterrupt || unsupported || missingEvidence || experiment ? "benchmark_annotation" : "fix_request",
    suggestedUserUpdate: shouldInterrupt ? "Tell the user this output region may affect the research conclusion before continuing." : "",
    suggestedAgentFeedback: missingEvidence ? "Gather or cite stronger evidence for this claim before relying on it." : unsupported ? "Revise the output so the claim matches the evidence." : "",
  };
}

function benchmarkDraft(candidate, anno = {}) {
  const suggestions = aiSuggestedLabels(candidate);
  const checklist = reviewerChecklistValues(anno, suggestions);
  const eligibility = eligibilityFor(candidate, { ...suggestions, ...anno }, checklist);
  return {
    ...suggestions,
    ...eligibility,
    claimSupported: checklist.needsMoreEvidence || checklist.inspectProvenance ? "unclear" : suggestions.claimSupported,
    evidenceSufficient: checklist.needsMoreEvidence ? "no" : suggestions.evidenceSufficient,
    includeInBenchmark: Boolean(anno.includeInBenchmark),
    rationale: anno.rationale || anno.reviewerComment || anno.quickComment || reviewReason(candidate),
  };
}

function reviewerChecklistValues(anno = {}, suggestions = {}) {
  const raw = anno.reviewerChecklist || {};
  const text = `${anno.issueType || suggestions.issueType || ""} ${anno.suggestedAction || suggestions.suggestedAction || ""} ${anno.rationale || anno.quickComment || ""}`.toLowerCase();
  return {
    choiceReasonable: Boolean(raw.choiceReasonable),
    needsMoreEvidence: Boolean(raw.needsMoreEvidence || /evidence|support|uncertain/.test(text)),
    paperExplainBetter: Boolean(raw.paperExplainBetter || /explain|writing|unsupported|unclear/.test(text)),
    mayAffectResult: Boolean(raw.mayAffectResult || /result|evaluation|metric|validity|baseline|dataset|split/.test(text)),
    userShouldBeUpdated: Boolean(raw.userShouldBeUpdated || /update user|interrupt/.test(text)),
    agentShouldRevise: Boolean(raw.agentShouldRevise || /revise|rerun|gather/.test(text)),
    inspectProvenance: Boolean(raw.inspectProvenance),
    notCoveredCreateIssue: Boolean(raw.notCoveredCreateIssue || raw.inspectProvenance),
  };
}

function reviewSummaryFor(candidate) {
  const decision = candidate.decision || {};
  const finding = candidate.finding || findingForDecision(decision) || {};
  const alternatives = decision.alternatives || (decision.options || [])
    .filter((opt) => opt && opt.status !== "chosen")
    .map((opt) => opt.text || opt.label || opt.choice || opt)
    .filter(Boolean);
  const splitIssue = isSplitAllocationIssue(candidate);
  const chosen = splitIssue
    ? "10 train / 2 validation / 4 test per word."
    : decision.choice || decision.chosen || decision.choiceVerbatim || candidate.summary || "not enough information available";
  const why = splitIssue
    ? "The 2-validation-examples-per-word budget directly limits the reliability of validation-based layer selection, making the headline result at layer 5 sensitive to the unusually small validation set."
    : decision.importanceRationale || decision.reviewer?.rationale || finding.text || finding.insight || reviewReason(candidate);
  return {
    issueTitle: candidate.title || decisionTitle(decision) || "Review generated output",
    decision: splitIssue ? "How many occurrences per word to allocate to each of the train, validation, and test splits?" : decisionTitle(decision) || candidate.title || "Should this output be trusted as written?",
    chosen,
    alternatives: splitIssue ? ["Larger per-word allocation, e.g. 20/5/10", "Different train/test ratio", "Higher minimum occurrence threshold"] : humanList(alternatives),
    why,
    affected: affectedOutput(candidate),
    files: relatedFiles(candidate),
    traceTarget: decision.id ? `decision:${decision.id}` : candidate.key,
  };
}

function renderReviewSummary(summary) {
  return `
    <dl class="review-summary">
      <dt>Alternatives:</dt><dd><ol>${summary.alternatives.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></dd>
      <dt>Related files:</dt><dd>
        <div class="related-file-list">
          ${summary.files.map((ref) => `
            <span class="related-file-row">
              <button type="button" class="related-file-link" data-open-related-report-file="${escapeHtml(ref.path)}">${escapeHtml(artifactLabel(ref))}</button>
              <small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(ref.path)}</small>
            </span>`).join("") || `<em>not enough information available</em>`}
        </div>
      </dd>
      <dt class="dev-secondary ${developerMode ? "" : "dev-hidden"}">Decision trace:</dt><dd class="dev-secondary ${developerMode ? "" : "dev-hidden"}"><button type="button" class="related-file-link" data-open-journey>${escapeHtml(summary.traceTarget || "Trace in Journey")}</button></dd>
    </dl>`;
}

function isSplitAllocationIssue(candidate) {
  const text = `${candidate.title || ""} ${candidate.summary || ""} ${candidate.decision?.choice || ""} ${candidate.decision?.rationale || ""}`.toLowerCase();
  return /split|allocation|train|validation|test/.test(text) && /word|occurrence|example/.test(text);
}

function renderReviewAssistant(candidate, anno) {
  const draft = assistantDraft?.targetKey === candidate.key ? assistantDraft : null;
  const response = assistantResponse?.targetKey === candidate.key ? assistantResponse : null;
  return `
    <section class="review-assistant">
      <h4>Review Assistant</h4>
      <div class="assistant-prompts">
        ${["Why is this issue important?", "What evidence supports this?", "What alternatives did NeuriCo have?", "What should I check?", "Turn my comment into annotation"].map((prompt) => `<button type="button" data-assistant-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
      </div>
      <textarea id="assistant-input" rows="3" placeholder="Ask about this issue or describe your concern..."></textarea>
      <div class="form-actions compact-row"><button type="button" data-create-assistant-draft>Save this as draft</button></div>
      ${response ? `<article class="assistant-answer">
        <h5>${escapeHtml(response.title)}</h5>
        ${response.lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
      </article>` : ""}
      ${draft ? `<article class="assistant-draft">
        <h5>Annotation draft from your comment</h5>
        <dl>
          <dt>Suggested decision</dt><dd>${escapeHtml(draft.suggestedDecision)}</dd>
          <dt>Crux</dt><dd>${escapeHtml(draft.crux)}</dd>
          <dt>Evidence sufficiency</dt><dd>${escapeHtml(draft.evidenceSufficiency)}</dd>
          <dt>Suggested action</dt><dd>${escapeHtml(draft.suggestedAction)}</dd>
          <dt>Needs expert review?</dt><dd>${escapeHtml(draft.needsExpertReview ? "yes" : "no")}</dd>
        </dl>
        <div class="form-actions">
          <button type="button" data-accept-assistant-draft>Accept</button>
          <button type="button" data-edit-assistant-draft>Edit</button>
          <button type="button" data-save-assistant-draft>Save</button>
        </div>
      </article>` : ""}
    </section>`;
}

function renderSuggestionRows(suggestions) {
  const rows = [
    ["steeringDecision", "Steering decision", suggestions.steeringDecision],
    ["cruxType", "Crux type", suggestions.cruxType],
    ["claimSupported", "Claim supported", suggestions.claimSupported],
    ["evidenceSufficient", "Evidence sufficient", suggestions.evidenceSufficient],
    ["confidence", "Confidence", suggestions.confidence],
    ["severity", "Severity", suggestions.severity],
  ];
  return `<div class="suggestion-list">${rows.map(([name, label, value]) => `
    <article>
      <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "unspecified")}</strong></div>
      <div class="suggestion-actions">
        <button type="button" data-suggestion-action="accept" data-suggestion-name="${escapeHtml(name)}" data-suggestion-value="${escapeHtml(value)}">Accept</button>
        <button type="button" data-suggestion-action="edit" data-suggestion-name="${escapeHtml(name)}">Edit</button>
        <button type="button" data-suggestion-action="reject" data-suggestion-name="${escapeHtml(name)}">Reject</button>
      </div>
    </article>`).join("")}</div>`;
}

function relatedContext(candidate) {
  const relatedDecisions = candidate.targetType === "decision"
    ? [candidate]
    : priorityCandidates().filter((item) => item.findingId && item.findingId === candidate.findingId).slice(0, 4);
  const relatedFindings = candidate.finding ? [candidate.finding] : findings().slice(0, 3);
  const eventNeedles = [candidate.targetId, candidate.findingId, candidate.title].filter(Boolean).map((x) => String(x).toLowerCase());
  const relatedEvents = canonicalEvents().filter((event) => {
    const text = JSON.stringify(event).toLowerCase();
    return eventNeedles.some((needle) => needle && text.includes(needle));
  }).slice(0, 5);
  return { relatedDecisions, relatedFindings, relatedEvents, evidence: candidate.evidence || [] };
}

function renderRelatedContext(candidate, related) {
  const tokenAvailable = canonicalEvents().some((event) => event.token_ref || event.tokenRefs || event.chunk_refs || event.chunkRefs);
  const selected = related.relatedDecisions[0] || candidate;
  return `
    <div class="panel-head related-head">
      <div>
        <span class="eyebrow">Related Decisions + Provenance</span>
        <h3>Decision detail</h3>
      </div>
      <button data-toggle-candidates>${showAllSteeringCandidates ? "Priority only" : "All candidates"}</button>
    </div>
    ${renderExpandedDecisionCard(selected)}
    <section class="context-block">
      <h4>Other review items</h4>
      <div class="decision-tabs">
        ${priorityCandidates().slice(0, showAllSteeringCandidates ? 30 : 8).map((item) => `<button class="${item.key === candidate.key ? "active" : ""}" data-context-target="${escapeHtml(item.key)}">${escapeHtml(compactText(item.title, 42))}</button>`).join("") || `<p class="muted">No related reconstructed decisions.</p>`}
      </div>
    </section>
    <section class="context-block">
      <h4>Related run notes</h4>
      ${related.relatedFindings.map((finding) => `<article class="context-row static"><b>Related finding</b><span>${escapeHtml(compactText(finding.text || finding.insight || "", 140))}</span><small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(finding.id || "")}</small></article>`).join("") || `<p class="muted">No related findings.</p>`}
    </section>
    <section class="context-block">
      <h4>Related files</h4>
      ${related.evidence.map((ref) => `<button class="evidence-chip" data-open-evidence="${escapeHtml(ref.path)}">${escapeHtml(humanTitle(ref.path))}${ref.note ? ` - ${escapeHtml(ref.note)}` : ""}</button>`).join("") || `<p class="muted">No evidence refs linked.</p>`}
    </section>
    <section class="context-block">
      <h4>Related journey stages</h4>
      ${related.relatedEvents.length ? related.relatedEvents.map((event, index) => `<article class="context-row static"><b>Research stage</b><span>${escapeHtml(eventText(event))}</span><small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(eventId(event, index))}</small></article>`).join("") : `<p class="muted">No related trace events promoted for this target.</p>`}
    </section>
    <section class="context-actions">
      <button data-open-journey>Trace in Journey</button>
      <button data-traceback>View provenance</button>
      <button data-open-journey>Open related stage</button>
      <button data-open-reports>Open in Reports</button>
    </section>
    <details class="${developerMode ? "" : "dev-hidden"}">
      <summary>Journey context</summary>
      <pre>${escapeHtml(JSON.stringify({ target: candidate.key, related }, null, 2))}</pre>
    </details>
    <p class="traceback-note">${tokenAvailable ? "Token/chunk references detected for this run." : "Open Journey to inspect available provenance."}</p>`;
}

function renderExpandedDecisionCard(item) {
  const decision = item?.decision || decisions().find((d) => d.id === item?.targetId) || {};
  const finding = item?.finding || findingForDecision(decision);
  const alternatives = decision.alternatives || (decision.options || []).filter((opt) => opt.status !== "chosen").map((opt) => opt.text || opt.label || opt).filter(Boolean);
  const chosen = decision.choice || decision.chosen || decision.choiceVerbatim || "";
  const rationale = decision.rationale || decision.reviewer?.rationale || decision.situation || item?.summary || "";
  const whyMatters = decision.importanceRationale || decision.reviewer?.rationale || finding?.text || "This decision may affect the generated paper or the benchmark label for this output region.";
  const affected = decision.paperRef?.section || selectedRegion || "selected output region";
  return `
    <article class="expanded-decision-card">
      <div class="expanded-decision-head">
        <span class="target-badge">${escapeHtml(developerMode ? (item?.targetId || decision.id || "decision") : "Decision summary")}</span>
        <span>${escapeHtml(decision.layer || decision.phase || item?.stage || "reconstructed decision")}</span>
      </div>
      <dl>
        <dt>Full question</dt><dd>${escapeHtml(decisionTitle(decision) || item?.title || "No question reconstructed.")}</dd>
        <dt>Chosen option</dt><dd>${escapeHtml(chosen || "No chosen option reconstructed.")}</dd>
        <dt>Alternatives/options</dt><dd>${escapeHtml(alternatives.length ? alternatives.join(" | ") : "No alternatives reconstructed.")}</dd>
        <dt>Why NeuriCo chose it</dt><dd>${escapeHtml(rationale || "No rationale reconstructed.")}</dd>
        <dt>Why it matters</dt><dd>${escapeHtml(whyMatters)}</dd>
        <dt>Affected output section</dt><dd>${escapeHtml(affected)}</dd>
        <dt>Related finding</dt><dd>${escapeHtml(finding ? compactText(finding.text || finding.insight || "", 240) : "No related finding linked.")}</dd>
        <dt>Related files</dt><dd>${escapeHtml((item?.evidence || evidenceRefsForDecision(decision)).map((ref) => humanTitle(ref.path)).filter(Boolean).join(", ") || "No related files linked.")}</dd>
      </dl>
      <div class="context-actions">
        <button data-open-journey>Open in Journey</button>
        <button data-open-reports>Open in Reports</button>
      </div>
    </article>`;
}

function renderBenchmarkPreview(candidate, anno) {
  const rows = [
    ["interrupt_prediction.jsonl", anno.steeringDecision || ""],
    ["crux_identification.jsonl", anno.cruxType || ""],
    ["update_generation.jsonl", anno.suggestedUserUpdate || ""],
    ["feedback_incorporation.jsonl", anno.feedbackIncorporation || ""],
  ];
  return `
    <div class="benchmark-preview">
      ${rows.map(([task, label]) => `
        <article>
          <b>${escapeHtml(task)}</b>
          <span>${escapeHtml(run.runId)} · ${escapeHtml(candidate.key)}</span>
          <small>${escapeHtml(selectedArtifactPath || mainPaperPath())} / ${escapeHtml(selectedRegion)}</small>
          <p>${escapeHtml(compactText(candidate.summary || candidate.title, 140))}</p>
          <em>label: ${escapeHtml(label || "not set")} · confidence: ${escapeHtml(anno.confidence || "not set")} · includeInBenchmark: ${anno.includeInBenchmark ? "yes" : "no"}</em>
        </article>`).join("")}
    </div>`;
}

function renderAllReviewIssuesPanel(candidate) {
  const filters = [
    ["all", "all"],
    ["must annotate", "must annotate"],
    ["affects results", "affects results"],
    ["affects abstract/main claim", "affects abstract/main claim"],
    ["affects method/statistics", "affects method/statistics"],
    ["LLM-fixable", "LLM-fixable"],
    ["needs expert review", "needs expert review"],
    ["missing crux", "missing crux"],
    ["completed", "completed"],
  ];
  const rows = allReviewIssues().filter((item) => {
    const status = queueStatus(item);
    const latest = latestAnnotation(item.key);
    const eligibility = eligibilityFor(item, latest, reviewerChecklistValues(latest, {}));
    const impact = eligibility.impactType;
    if (reviewIssueFilter === "all") return true;
    if (reviewIssueFilter === "must annotate") return eligibility.mustAnnotate;
    if (reviewIssueFilter === "affects results") return impact.includes("results");
    if (reviewIssueFilter === "affects abstract/main claim") return impact.includes("abstract_claim") || impact.includes("main_claim");
    if (reviewIssueFilter === "affects method/statistics") return impact.some((type) => ["method_validity", "experiment_design", "statistical_inference", "baseline_control", "reproducibility"].includes(type));
    if (reviewIssueFilter === "LLM-fixable") return eligibility.autoFixCandidate || eligibility.fixability === "llm_fixable";
    if (reviewIssueFilter === "needs expert review") return eligibility.needsExpertReview || status === "needs expert review";
    if (reviewIssueFilter === "missing crux") return item.key.startsWith("manual_crux:") || item.key.startsWith("llm_missed_issue:");
    if (reviewIssueFilter === "completed") return status === "annotated" || status === "benchmark-ready";
    return true;
  });
  return `
    <aside class="all-issues-panel">
      <div class="panel-head">
        <div><h3>All Review Issues</h3></div>
        <button type="button" data-close-all-issues>Close</button>
      </div>
      <div class="issue-filter-tabs">
        ${filters.map(([key, label]) => `<button type="button" class="${reviewIssueFilter === key ? "active" : ""}" data-issue-filter="${escapeHtml(key)}">${escapeHtml(label)}</button>`).join("")}
      </div>
      <div class="all-issue-list">
        ${rows.map((item, index) => `
          <article class="all-issue-row ${item.key === candidate.key ? "active" : ""}">
            <b>${index + 1}</b>
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <p>${escapeHtml(compactText(reviewReason(item), 150))}</p>
              <small>Affected output: ${escapeHtml(affectedOutput(item))}</small>
              <small>Route: ${escapeHtml(routeLabel(eligibilityFor(item, latestAnnotation(item.key), {}).annotationRoute))}</small>
              <small>Status: ${escapeHtml(queueStatus(item))}</small>
            </div>
            <button type="button" data-context-target="${escapeHtml(item.key)}">Review</button>
          </article>`).join("") || `<p class="muted">No issues match this filter.</p>`}
      </div>
    </aside>`;
}

async function ensurePdfJs() {
  if (pdfjsReady) return pdfjsReady;
  pdfjsReady = import("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs").then((mod) => {
    mod.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";
    return mod;
  });
  return pdfjsReady;
}

async function renderPdfViewer(candidate) {
  const viewer = root.querySelector(".pdfjs-viewer");
  if (!viewer || !viewer.dataset.pdfUrl) return;
  const token = ++renderedPdfToken;
  const url = viewer.dataset.pdfUrl;
  try {
    const pdfjs = await ensurePdfJs();
    if (token !== renderedPdfToken) return;
    const pdf = await pdfjs.getDocument(url).promise;
    viewer.innerHTML = `
      <div class="pdf-pages"></div>
      `;
    const pages = viewer.querySelector(".pdf-pages");
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      if (token !== renderedPdfToken) return;
      const viewport = page.getViewport({ scale: Math.min(1.45, Math.max(1, viewer.clientWidth / 760)) });
      const pageEl = document.createElement("div");
      pageEl.className = "pdf-page";
      pageEl.dataset.page = String(pageNumber);
      pageEl.style.width = `${viewport.width}px`;
      pageEl.style.height = `${viewport.height}px`;
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.className = "pdf-canvas-layer";
      const textLayer = document.createElement("div");
      textLayer.className = "pdf-text-layer";
      const overlay = document.createElement("div");
      overlay.className = "pdf-annotation-layer";
      const pins = document.createElement("div");
      pins.className = "pdf-pin-layer";
      pageEl.append(canvas, textLayer, overlay, pins);
      pages.append(pageEl);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      await renderTextLayer(page, viewport, textLayer);
    }
    renderSavedAnchors(candidate);
    wirePdfAnnotationInteractions(candidate);
    const targetPage = sectionPage(candidate);
    if (targetPage) viewer.querySelector(`.pdf-page[data-page="${targetPage}"]`)?.scrollIntoView({ block: "start" });
  } catch (error) {
    viewer.innerHTML = `<div class="pdf-error"><h4>Could not load PDF.js viewer</h4><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function renderTextLayer(page, viewport, textLayer) {
  const text = await page.getTextContent();
  for (const item of text.items || []) {
    const tx = pdfTransform(viewport.transform, item.transform);
    const span = document.createElement("span");
    span.textContent = item.str;
    span.style.left = `${tx[4]}px`;
    span.style.top = `${tx[5] - Math.abs(tx[3])}px`;
    span.style.fontSize = `${Math.max(8, Math.abs(tx[3]))}px`;
    span.style.transform = `scaleX(${item.width ? Math.max(.75, (item.width * viewport.scale) / Math.max(1, span.textContent.length * Math.abs(tx[3]) * .55)) : 1})`;
    textLayer.append(span);
  }
}

function pdfTransform(m1, m2) {
  return [
    m1[0] * m2[0] + m1[2] * m2[1],
    m1[1] * m2[0] + m1[3] * m2[1],
    m1[0] * m2[2] + m1[2] * m2[3],
    m1[1] * m2[2] + m1[3] * m2[3],
    m1[0] * m2[4] + m1[2] * m2[5] + m1[4],
    m1[1] * m2[4] + m1[3] * m2[5] + m1[5],
  ];
}

function wirePdfAnnotationInteractions(candidate) {
  const viewer = root.querySelector(".pdfjs-viewer");
  if (!viewer) return;
  viewer.addEventListener("mouseup", () => {
    if (annotationTool === "box") return;
    const selection = window.getSelection();
    const text = String(selection || "").trim();
    if (!text) return;
    const range = selection.getRangeAt(0);
    const pageEl = range.commonAncestorContainer.parentElement?.closest?.(".pdf-page") || viewer.querySelector(".pdf-page");
    if (!pageEl) return;
    const bounds = pageEl.getBoundingClientRect();
    const rects = [...range.getClientRects()].filter((rect) => rect.width > 1 && rect.height > 1);
    selectedAnnotationAnchor = {
      type: ANCHOR_TYPES.TEXT,
      page: Number(pageEl.dataset.page || 1),
      selectedText: text,
      selectedSection: selectedRegion,
      section: selectedRegion,
      rects: rects.map((rect) => normalizeRect(rect, bounds)),
      normalizedBoundingBox: rects.length ? normalizeRect(rects[0], bounds) : null,
    };
    if (annotationTool === "highlight") handleSelectionAction(candidate, "highlight");
    else if (annotationTool === "ask") handleSelectionAction(candidate, "ask");
    else if (annotationTool === "escalate") handleSelectionAction(candidate, "escalate");
    else root.querySelector('[name="reviewerComment"]')?.focus();
  });
  viewer.querySelectorAll("[data-selection-action]").forEach((button) => button.addEventListener("click", () => handleSelectionAction(candidate, button.dataset.selectionAction)));
  let drag = null;
  viewer.querySelectorAll(".pdf-page").forEach((pageEl) => {
    pageEl.addEventListener("pointerdown", (event) => {
      if (annotationTool !== "box") return;
      const bounds = pageEl.getBoundingClientRect();
      drag = { pageEl, bounds, startX: event.clientX, startY: event.clientY };
      pageEl.setPointerCapture(event.pointerId);
      let box = pageEl.querySelector(".draft-box");
      if (!box) {
        box = document.createElement("div");
        box.className = "draft-box";
        pageEl.querySelector(".pdf-annotation-layer").append(box);
      }
    });
    pageEl.addEventListener("pointermove", (event) => {
      if (!drag || drag.pageEl !== pageEl) return;
      const box = pageEl.querySelector(".draft-box");
      const left = Math.min(event.clientX, drag.startX) - drag.bounds.left;
      const top = Math.min(event.clientY, drag.startY) - drag.bounds.top;
      const width = Math.abs(event.clientX - drag.startX);
      const height = Math.abs(event.clientY - drag.startY);
      Object.assign(box.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
    });
    pageEl.addEventListener("pointerup", (event) => {
      if (!drag || drag.pageEl !== pageEl) return;
      const rect = {
        left: Math.min(event.clientX, drag.startX),
        top: Math.min(event.clientY, drag.startY),
        width: Math.abs(event.clientX - drag.startX),
        height: Math.abs(event.clientY - drag.startY),
      };
      if (rect.width > 12 && rect.height > 12) {
        selectedAnnotationAnchor = {
          type: ANCHOR_TYPES.BOX,
          page: Number(pageEl.dataset.page || 1),
          selectedSection: selectedRegion,
          section: selectedRegion,
          normalizedBoundingBox: normalizeRect(rect, drag.bounds),
          nearbyTextSnippet: selectedRegionText || "",
        };
        root.querySelector('[name="reviewerComment"]')?.focus();
      }
      drag = null;
    });
  });
}

function showSelectionMenu(rect) {
  return;
}

function showBoxPopover(point) {
  return;
}

function handleSelectionAction(candidate, action) {
  root.querySelector(".floating-action-menu")?.setAttribute("hidden", "");
  root.querySelector(".box-comment-popover")?.setAttribute("hidden", "");
  if (action === "highlight") {
    saveAnnotation(candidate, "highlight");
    return;
  }
  if (action === "ask") {
    const input = root.querySelector("#assistant-input");
    if (input) input.value = `Ask about: ${compactText(currentAnchor().selectedText || selectedSectionLabel(), 120)}`;
    createAssistantResponse(candidate, "What should I check?");
    return;
  }
  if (action === "escalate") {
    markNeedsExpert("Selected paper anchor marked for expert review; save to persist.");
    root.querySelector('[name="reviewerComment"]')?.focus();
    return;
  }
  root.querySelector('[name="reviewerComment"]')?.focus();
}

function renderSavedAnchors(candidate) {
  const comments = annotationComments(candidate);
  for (const comment of comments) {
    if (!comment.anchor) continue;
    const pageEl = root.querySelector(`.pdf-page[data-page="${comment.anchor.page || 1}"]`);
    if (!pageEl) continue;
    const overlay = pageEl.querySelector(".pdf-annotation-layer");
    const pins = pageEl.querySelector(".pdf-pin-layer");
    const rects = comment.anchor.rects || [comment.anchor.normalizedBoundingBox].filter(Boolean);
    for (const rect of rects) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `saved-anchor ${comment.anchor.type === ANCHOR_TYPES.BOX ? "box" : "highlight"} ${comment.id === activeCommentId ? "active" : ""}`;
      Object.assign(el.style, normalizedStyle(rect));
      el.dataset.pinComment = comment.id;
      overlay.append(el);
    }
    const first = rects[0];
    if (first) {
      const pin = document.createElement("button");
      pin.type = "button";
      pin.className = `comment-pin ${comment.id === activeCommentId ? "active" : ""}`;
      pin.textContent = "●";
      pin.title = "Open comment";
      pin.dataset.pinComment = comment.id;
      Object.assign(pin.style, { left: `${(first.x + first.width + .012) * 100}%`, top: `${first.y * 100}%` });
      pins.append(pin);
    }
  }
  root.querySelectorAll("[data-pin-comment]").forEach((button) => button.addEventListener("click", () => focusComment(candidate, button.dataset.pinComment)));
}

function normalizedStyle(rect) {
  return {
    left: `${rect.x * 100}%`,
    top: `${rect.y * 100}%`,
    width: `${rect.width * 100}%`,
    height: `${rect.height * 100}%`,
  };
}

function focusComment(candidate, commentId) {
  activeCommentId = commentId;
  renderSteering();
  setTimeout(() => root.querySelector(`[data-focus-anchor="${CSS.escape(commentId)}"]`)?.scrollIntoView({ block: "center" }), 0);
}

function wireSteering(candidate) {
  root.querySelectorAll("[data-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      annotationTool = button.dataset.tool;
      if (annotationTool === "ask") handleSelectionAction(candidate, "ask");
      if (annotationTool === "escalate") handleSelectionAction(candidate, "escalate");
      renderSteering();
    });
  });
  root.querySelectorAll("[data-select-region]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedRegion = button.dataset.selectRegion;
      selectedRegionText = button.dataset.regionText || "";
      selectedArtifactPath = mainPaperPath();
      selectedReviewSource = "section_comment";
      selectedAnnotationAnchor = sectionAnchor();
      if (!candidate.key.startsWith("decision:")) selectedTargetKey = `artifact:${mainPaperPath()}#${selectedRegion}`;
      renderSteering();
    });
  });
  root.querySelector("[data-select-current-section]")?.addEventListener("click", () => {
    selectedArtifactPath = mainPaperPath();
    selectedReviewSource = "section_comment";
    if (!candidate.key.startsWith("decision:")) selectedTargetKey = `artifact:${mainPaperPath()}#${selectedRegion}`;
    renderSteering();
  });
  root.querySelectorAll("[data-comment-section]").forEach((button) => button.addEventListener("click", () => {
    selectedReviewSource = "section_comment";
    root.querySelector('[name="reviewerComment"]')?.focus();
  }));
  root.querySelectorAll("[data-ask-section]").forEach((button) => button.addEventListener("click", () => {
    selectedReviewSource = "section_comment";
    const input = root.querySelector("#assistant-input");
    if (input) {
      input.value = `Ask about the ${selectedSectionLabel()} section`;
      input.focus();
    }
    createAssistantResponse(candidate, "What should I check?");
  }));
  root.querySelectorAll("[data-escalate-section]").forEach((button) => button.addEventListener("click", () => {
    selectedReviewSource = "section_comment";
    markNeedsExpert(`${selectedSectionLabel()} marked for expert review; save to persist.`);
  }));
  root.querySelector("[data-save-section]")?.addEventListener("click", async () => {
    await saveAnnotation(candidate, "benchmark");
  });
  root.querySelectorAll("[data-context-target]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTargetKey = button.dataset.contextTarget;
      applyCandidatePaperAnchor(selectedTargetKey);
      renderSteering();
    });
  });
  root.querySelector("[data-toggle-candidates]")?.addEventListener("click", () => {
    showAllSteeringCandidates = !showAllSteeringCandidates;
    renderSteering();
  });
  root.querySelector("[data-close-all-issues]")?.addEventListener("click", () => {
    showAllReviewIssues = false;
    renderSteering();
  });
  root.querySelectorAll("[data-issue-filter]").forEach((button) => button.addEventListener("click", () => {
    reviewIssueFilter = button.dataset.issueFilter || "all";
    renderSteering();
  }));
  root.querySelectorAll("[data-open-journey]").forEach((button) => button.addEventListener("click", () => {
    selectedReviewSource = "journey_escalation";
    openedJourney = true;
    currentView = "trajectory";
    render();
  }));
  root.querySelectorAll("[data-open-reports]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = selectedArtifactPath || mainPaperPath();
    selectedReviewSource = "direct_output_review";
    openedReports = true;
    currentView = "artifacts";
    render();
  }));
  root.querySelector("[data-open-related-report]")?.addEventListener("click", () => {
    selectedArtifactPath = relatedFiles(candidate)[0]?.path || mainPaperPath();
    selectedReviewSource = "report_review";
    openedReports = true;
    currentView = "artifacts";
    render();
  });
  root.querySelectorAll("[data-open-related-report-file]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.openRelatedReportFile || mainPaperPath();
    selectedReviewSource = "report_review";
    openedReports = true;
    currentView = "artifacts";
    render();
  }));
  root.querySelectorAll("[data-trace-related-file]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.traceRelatedFile || mainPaperPath();
    selectedReviewSource = "journey_escalation";
    openedJourney = true;
    currentView = "trajectory";
    render();
  }));
  root.querySelector("[data-traceback]")?.addEventListener("click", () => {
    currentView = "trajectory";
    openedJourney = true;
    render();
  });
  root.querySelectorAll("[data-suggestion-action]").forEach((button) => button.addEventListener("click", () => {
    const name = button.dataset.suggestionName;
    const field = root.querySelector(`[name="${name}"]`);
    if (!field) return;
    if (button.dataset.suggestionAction === "accept") field.value = button.dataset.suggestionValue || "";
    if (button.dataset.suggestionAction === "reject") field.value = "";
    if (button.dataset.suggestionAction === "edit") field.focus();
  }));
  root.querySelectorAll("[data-open-evidence]").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.openEvidence)));
  root.querySelector("#annotation-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveAnnotation(candidate, event.submitter?.dataset.routeAction || event.submitter?.dataset.saveMode || "quick");
  });
  root.querySelector("[data-expert-review]")?.addEventListener("click", () => {
    markNeedsExpert("Marked for expert review; save to persist.");
  });
  root.querySelector("[data-accept-prefill]")?.addEventListener("click", () => {
    const suggestions = benchmarkDraft(candidate, latestAnnotation(candidate.key));
    setFormValue("suggestedAction", suggestions.suggestedAction);
    setFormValue("cruxType", suggestions.cruxType);
    setFormValue("evidenceSufficient", suggestions.evidenceSufficient);
    setFormValue("severity", suggestions.severity);
    setFormValue("confidence", suggestions.confidence);
    setFormValue("annotationRoute", suggestions.annotationRoute);
    root.querySelector("#annotation-form").dataset.acceptedPrelabel = "true";
    root.querySelector("#save-status").textContent = "Pre-filled label accepted; save to persist.";
  });
  root.querySelector("[data-edit-prefill]")?.addEventListener("click", () => {
    editingPrelabel = !editingPrelabel;
    renderSteering();
  });
  root.querySelectorAll("[data-create-manual]").forEach((button) => button.addEventListener("click", () => {
    createManualIssue(button.dataset.createManual || "manual_crux");
  }));
  root.querySelector("[data-escalate-whole-paper]")?.addEventListener("click", () => {
    selectedAnnotationAnchor = { ...sectionAnchor(), selectedSection: "whole_paper", section: "whole_paper", selectedText: "Whole paper" };
    createManualIssue("expert_review", "whole paper");
  });
  root.querySelectorAll("[data-focus-anchor]").forEach((button) => button.addEventListener("click", () => {
    activeCommentId = button.dataset.focusAnchor || "";
    const comment = annotationComments(candidate).find((item) => item.id === activeCommentId);
    if (comment?.anchor?.page) {
      root.querySelector(`.pdf-page[data-page="${comment.anchor.page}"]`)?.scrollIntoView({ block: "center" });
    }
    renderSteering();
  }));
  root.querySelector("[data-toggle-dev]")?.addEventListener("click", () => {
    developerMode = !developerMode;
    renderSteering();
  });
  root.querySelector("[data-ask-assistant]")?.addEventListener("click", () => {
    root.querySelector("#assistant-input")?.focus();
  });
  root.querySelectorAll("[data-assistant-prompt]").forEach((button) => button.addEventListener("click", () => {
    const input = root.querySelector("#assistant-input");
    const prompt = button.dataset.assistantPrompt || "";
    if (input) input.value = prompt;
    createAssistantResponse(candidate, prompt);
  }));
  root.querySelector("[data-create-assistant-draft]")?.addEventListener("click", () => {
    createAssistantDraft(candidate);
  });
  root.querySelector("[data-accept-assistant-draft]")?.addEventListener("click", () => {
    applyAssistantDraft();
  });
  root.querySelector("[data-edit-assistant-draft]")?.addEventListener("click", () => {
    root.querySelector("#assistant-input")?.focus();
  });
  root.querySelector("[data-save-assistant-draft]")?.addEventListener("click", async () => {
    applyAssistantDraft();
    await saveAnnotation(candidate, "benchmark");
  });
  root.querySelector("[data-include-benchmark]")?.addEventListener("click", () => {
    root.querySelector('[name="includeInBenchmark"]').checked = true;
    root.querySelector('[name="workflowStatus"]').value = "benchmark_ready";
  });
  root.querySelector("[data-skip-target]")?.addEventListener("click", () => {
    root.querySelector('[name="workflowStatus"]').value = "excluded";
  });
}

function setFormValue(name, value) {
  const field = root.querySelector(`[name="${name}"]`);
  if (field) field.value = value || "";
}

function markNeedsExpert(message) {
  const needs = root.querySelector('[name="needsExpertAdjudication"]');
  if (needs) needs.value = "on";
  const workflow = root.querySelector('[name="workflowStatus"]');
  if (workflow) workflow.value = "needs_expert_adjudication";
  const adjudication = root.querySelector('[name="adjudicationStatus"]');
  if (adjudication) adjudication.value = "pending";
  const status = root.querySelector("#save-status");
  if (status) status.textContent = message;
}

function createAssistantDraft(candidate) {
  const input = root.querySelector("#assistant-input");
  const text = input?.value || root.querySelector('[name="reviewerComment"]')?.value || "";
  const lower = text.toLowerCase();
  const summary = reviewSummaryFor(candidate);
  const needsExpertReview = /expert|uncertain|not sure|unclear|gold|adjudicat/.test(lower);
  assistantDraft = {
    targetKey: candidate.key,
    issueType: /evidence|support|citation/.test(lower) ? "missing evidence" : /result|metric|accuracy|affect/.test(lower) ? "weak experiment" : /explain|unclear|paper/.test(lower) ? "unclear writing" : "other",
    suggestedDecision: /reasonable|ok|fine|sufficient/.test(lower) ? "Reviewer verifies this section as acceptable" : "Reviewer flags this section for follow-up",
    suggestedAction: /rerun|revise|fix/.test(lower) ? "revise paper/output" : /evidence|check/.test(lower) ? "gather more evidence" : "continue",
    crux: compactText(text || summary.why || reviewReason(candidate), 160),
    evidenceSufficiency: /not enough|missing|weak|unclear/.test(lower) ? "uncertain" : "yes",
    userShouldBeUpdated: /user|update|notify|affect/.test(lower),
    agentShouldRevise: /revise|rerun|fix|change/.test(lower),
    needsExpertReview,
  };
  assistantResponse = {
    targetKey: candidate.key,
    title: "Annotation draft from your comment",
    lines: [
      `Suggested decision: ${assistantDraft.suggestedDecision}.`,
      `Crux: ${assistantDraft.crux}.`,
      `Evidence sufficiency: ${assistantDraft.evidenceSufficiency}.`,
      `Suggested action: ${assistantDraft.suggestedAction}.`,
      `Needs expert review? ${assistantDraft.needsExpertReview ? "yes" : "no"}.`,
    ],
  };
  renderSteering();
}

function createAssistantResponse(candidate, prompt) {
  const summary = reviewSummaryFor(candidate);
  const comment = root.querySelector('[name="reviewerComment"]')?.value || "";
  const files = summary.files.map((ref) => artifactLabel(ref)).filter(Boolean).join(", ") || "no related files linked";
  if (prompt === "Turn my comment into annotation") {
    createAssistantDraft(candidate);
    return;
  }
  const responses = {
    "Why is this issue important?": [
      `It affects the ${selectedSectionLabel()} section for the issue "${summary.issueTitle}".`,
      summary.why || "May affect whether the reported result is reliable.",
      `What NeuriCo chose: ${summary.chosen}.`,
    ],
    "What evidence supports this?": [
      `Related files: ${files}.`,
      `Selected section context: ${compactText(selectedRegionText || outputSections().find(([key]) => key === selectedRegion)?.[2] || "No reconstructed section text is available.", 220)}`,
      comment ? `Reviewer comment considered: ${compactText(comment, 180)}` : "No reviewer comment has been entered yet.",
    ],
    "What alternatives did NeuriCo have?": [
      `NeuriCo chose: ${summary.chosen}.`,
      `Alternatives: ${summary.alternatives.join("; ")}.`,
      "Check whether the selected alternative would have changed the paper claim, method, result, or limitation text.",
    ],
    "What should I check?": [
      `Check whether the ${selectedSectionLabel()} wording is supported by the linked files.`,
      "Verify whether the checklist needs more evidence, paper explanation, provenance inspection, expert review, or a revise/rerun action.",
      `Use related files: ${files}.`,
    ],
  };
  assistantResponse = {
    targetKey: candidate.key,
    title: prompt,
    lines: responses[prompt] || [
      `Issue: ${summary.issueTitle}.`,
      `Selected section: ${selectedSectionLabel()}.`,
      `Reviewer comment: ${comment || "none yet"}.`,
    ],
  };
  renderSteering();
}

function applyAssistantDraft() {
  if (!assistantDraft) return;
  const set = (name, value) => {
    const field = root.querySelector(`[name="${name}"]`);
    if (field) field.value = value || "";
  };
  set("issueType", assistantDraft.issueType);
  set("suggestedAction", assistantDraft.suggestedAction);
  set("evidenceSufficient", assistantDraft.evidenceSufficiency === "yes" ? "yes" : "uncertain");
  const expert = root.querySelector('[name="needsExpertAdjudication"]');
  if (expert && assistantDraft.needsExpertReview) expert.value = "on";
  const checklistMap = {
    needsMoreEvidence: assistantDraft.evidenceSufficiency !== "yes",
    userShouldBeUpdated: assistantDraft.userShouldBeUpdated,
    agentShouldRevise: assistantDraft.agentShouldRevise,
    mayAffectResult: /result|metric|experiment/.test(assistantDraft.issueType),
  };
  Object.entries(checklistMap).forEach(([name, checked]) => {
    const field = root.querySelector(`[name="${name}"]`);
    if (field) field.checked = checked;
  });
  const comment = root.querySelector('[name="reviewerComment"]');
  if (comment && !comment.value.trim()) comment.value = assistantDraft.crux;
}

async function saveAnnotation(candidate, mode = "quick") {
  const form = root.querySelector("#annotation-form");
  const data = new FormData(form);
  const related = relatedContext(candidate);
  const get = (name) => data.get(name) || "";
  const suggestions = benchmarkDraft(candidate, latestAnnotation(candidate.key));
  const selectedText = selectedRegionText || outputSections().find(([key]) => key === selectedRegion)?.[2] || candidate.summary || "";
  const anchor = currentAnchor();
  const routeMode = ROUTES.includes(mode) ? mode : (get("annotationRoute") || suggestions.annotationRoute || "benchmark_annotation");
  const includeBenchmark = routeMode === "benchmark_annotation" || mode === "benchmark" || data.get("includeInBenchmark") === "on";
  const now = new Date().toISOString();
  const reviewerChecklist = {
    choiceReasonable: data.get("choiceReasonable") === "on",
    needsMoreEvidence: data.get("needsMoreEvidence") === "on",
    paperExplainBetter: data.get("paperExplainBetter") === "on",
    mayAffectResult: data.get("mayAffectResult") === "on",
    userShouldBeUpdated: data.get("userShouldBeUpdated") === "on",
    agentShouldRevise: data.get("agentShouldRevise") === "on",
    inspectProvenance: data.get("inspectProvenance") === "on",
    notCoveredCreateIssue: data.get("notCoveredCreateIssue") === "on",
  };
  const reviewSummary = reviewSummaryFor(candidate);
  const reviewerComment = get("reviewerComment") || get("quickComment");
  if (routeMode === "dismissed" && !get("dismissedReason").trim()) {
    const reason = window.prompt("Dismiss reason required", "Not important for this paper/output");
    if (!reason) {
      root.querySelector("#save-status").textContent = "Dismiss reason required.";
      return;
    }
    const field = root.querySelector('[name="dismissedReason"]');
    if (field) field.value = reason;
  }
  const files = relatedFiles(candidate);
  const needsExpertReview = data.get("needsExpertAdjudication") === "on" || routeMode === "expert_escalation";
  const preEligibility = eligibilityFor(candidate, {
    ...suggestions,
    annotationRoute: routeMode,
    evidenceSufficient: get("evidenceSufficient") || suggestions.evidenceSufficient,
    confidence: get("confidence") || suggestions.confidence,
    reviewerComment,
  }, reviewerChecklist);
  const autoCapturedContext = {
    runId: currentRunId,
    targetKey: candidate.key,
    selectedArtifact: selectedArtifactPath || mainPaperPath(),
    selectedRegion,
    selectedSection: selectedRegion,
    selectedSectionLabel: selectedSectionLabel(),
    selectedText,
    anchor,
    pageOrSection: selectedRegion,
    relatedDecisionIds: related.relatedDecisions.map((item) => item.targetId).filter(Boolean),
    relatedFindingIds: related.relatedFindings.map((item) => item.id).filter(Boolean),
    relatedEventIds: related.relatedEvents.map(eventId),
    evidenceRefs: related.evidence,
    reviewSummary,
    raterId: userEmail || "anonymous",
    timestamp: now,
  };
  const benchmarkDraftPayload = {
    steeringDecision: get("steeringDecision") || suggestions.steeringDecision,
    cruxType: get("cruxType") || suggestions.cruxType,
    claimSupported: get("claimSupported") || suggestions.claimSupported,
    evidenceSufficient: get("evidenceSufficient") || suggestions.evidenceSufficient,
    confidence: get("confidence") || suggestions.confidence,
    severity: get("severity") || suggestions.severity,
    impactType: preEligibility.impactType,
    annotationRoute: routeMode,
    rationale: get("rationale") || reviewerComment || suggestions.rationale,
    includeInBenchmark: includeBenchmark,
    finalLabel: get("finalLabel"),
    adjudicationStatus: get("adjudicationStatus"),
    includeInBenchmarkDecision: get("includeInBenchmarkDecision"),
  };
  const humanConfirmedLabels = {
    comment: reviewerComment,
    reviewerChecklist,
    finalSteeringDecision: benchmarkDraftPayload.steeringDecision,
    keyCrux: get("keyCrux"),
    rationale: benchmarkDraftPayload.rationale,
    claimSupported: benchmarkDraftPayload.claimSupported,
    evidenceSufficient: benchmarkDraftPayload.evidenceSufficient,
    includeInBenchmark: includeBenchmark,
    finalLabel: get("finalLabel"),
    adjudicationStatus: get("adjudicationStatus"),
    includeInBenchmarkDecision: get("includeInBenchmarkDecision"),
  };
  const workflowStatus = needsExpertReview
    ? "needs_expert_adjudication"
    : routeMode === "dismissed" ? "excluded"
    : routeMode === "fix_request" ? "fix_request_open"
    : includeBenchmark ? "benchmark_ready" : (get("workflowStatus") || "annotated");
  const adjudicationStatus = needsExpertReview ? "pending" : get("adjudicationStatus");
  const finalEligibility = {
    ...preEligibility,
    needsExpertReview,
    annotationRoute: routeMode,
    fixability: routeMode === "fix_request" ? "llm_fixable" : preEligibility.fixability,
  };
  const dismissedReason = routeMode === "dismissed" ? (get("dismissedReason") || root.querySelector('[name="dismissedReason"]')?.value || "") : "";
  const fixRequest = routeMode === "fix_request" ? {
    selectedPaperAnchor: anchor,
    reviewerComment,
    fixType: get("fixType") || "clarity",
    proposedFix: get("proposedFix"),
    linkedIssue: candidate.key,
    includeInBenchmark: includeBenchmark && finalEligibility.mustAnnotate,
    status: "open",
  } : null;
  const editedFields = editingPrelabel ? {
    suggestedAction: get("suggestedAction"),
    cruxType: get("cruxType"),
    evidenceSufficient: get("evidenceSufficient"),
    severity: get("severity"),
    confidence: get("confidence"),
    annotationRoute: routeMode,
  } : {};
  const payload = {
    key: candidate.key,
    targetKey: candidate.key,
    runId: currentRunId,
    targetType: candidate.targetType,
    source: annotationSourceFor(candidate),
    selectedIssue: candidate.title,
    selectedArtifact: selectedArtifactPath || mainPaperPath(),
    selectedArtifactHumanName: humanTitle(selectedArtifactPath || mainPaperPath()),
    selectedArtifactPath: selectedArtifactPath || mainPaperPath(),
    selectedRegion,
    selectedSection: selectedRegion,
    selectedSectionLabel: selectedSectionLabel(),
    selectedText,
    anchor,
    paperAnchor: anchor,
    checklist: reviewerChecklist,
    reviewSummary,
    reviewerChecklist,
    reviewerComment,
    openedJourney,
    openedReports,
    needsExpertReview,
    mustAnnotate: finalEligibility.mustAnnotate,
    autoFixCandidate: finalEligibility.autoFixCandidate,
    impactType: finalEligibility.impactType,
    impactReason: finalEligibility.impactReason,
    affectedOutput: finalEligibility.affectedOutput,
    fixability: finalEligibility.fixability,
    annotationRoute: finalEligibility.annotationRoute,
    dismissedReason,
    fixRequest,
    relatedFiles: files,
    autoCapturedContext,
    llmPrelabel: benchmarkDraftPayload,
    reviewerVerification: {
      selectedIssue: candidate.title,
      selectedSection: selectedRegion,
      anchor,
      checklist: reviewerChecklist,
      reviewerComment,
      needsExpertReview,
      acceptedPrelabel: root.querySelector("#annotation-form")?.dataset.acceptedPrelabel === "true",
      editedFields,
      verifiedAt: now,
    },
    expertAdjudication: {
      status: adjudicationStatus || "",
      finalLabel: get("finalLabel"),
      includeInBenchmark: get("includeInBenchmarkDecision"),
    },
    benchmarkTaskTargets: {
      targetKey: candidate.key,
      anchor,
      decisionIds: autoCapturedContext.relatedDecisionIds,
      findingIds: autoCapturedContext.relatedFindingIds,
      evidenceRefs: related.evidence,
    },
    targetKey: candidate.key,
    decisionIds: autoCapturedContext.relatedDecisionIds,
    findingIds: autoCapturedContext.relatedFindingIds,
    provenanceUsage: {
      openedJourney,
      openedReports,
      source: annotationSourceFor(candidate),
    },
    benchmarkDraft: benchmarkDraftPayload,
    humanConfirmedLabels,
    benchmarkStatus: {
      workflowStatus,
      mode,
      exportJsonlTargets: ["interrupt_prediction.jsonl", "crux_identification.jsonl", "update_generation.jsonl", "feedback_incorporation.jsonl"],
    },
    raterMetadata: {
      raterId: userEmail || "anonymous",
      raterRole: get("raterRole") || "reviewer",
      expertiseArea: get("expertiseArea"),
      guidelineVersion: get("guidelineVersion") || "v0.1",
      annotationRound: get("annotationRound") || "1",
    },
    createdAt: now,
    updatedAt: now,
    quickComment: reviewerComment,
    issueType: get("issueType"),
    suggestedAction: get("suggestedAction"),
    source: annotationSourceFor(candidate),
    targetIssue: candidate.title,
    raterId: userEmail || "anonymous",
    timestamp: now,
    anchor,
    paperAnchor: anchor,
    sourceText: selectedText,
    pageOrSection: selectedRegion,
    relatedDecisionIds: autoCapturedContext.relatedDecisionIds.join(","),
    relatedFindingIds: autoCapturedContext.relatedFindingIds.join(","),
    relatedEventIds: autoCapturedContext.relatedEventIds.join(","),
    evidenceRefs: JSON.stringify(related.evidence),
    snapshot: `${candidate.title} ${candidate.summary || ""}`.trim(),
    steeringDecision: benchmarkDraftPayload.steeringDecision,
    cruxType: benchmarkDraftPayload.cruxType,
    claimSupported: benchmarkDraftPayload.claimSupported,
    evidenceSufficient: benchmarkDraftPayload.evidenceSufficient,
    confidence: benchmarkDraftPayload.confidence,
    severity: benchmarkDraftPayload.severity,
    keyCrux: get("keyCrux"),
    missingInfo: get("missingInfo"),
    uncertainty: get("missingInfo"),
    surfaceContextToUser: get("surfaceContextToUser"),
    suggestedUserUpdate: get("suggestedUserUpdate"),
    suggestedAgentFeedback: get("suggestedAgentFeedback"),
    rationale: benchmarkDraftPayload.rationale,
    raterRole: get("raterRole") || "reviewer",
    expertiseArea: get("expertiseArea"),
    guidelineVersion: get("guidelineVersion") || "v0.1",
    annotationRound: get("annotationRound") || "1",
    workflowStatus,
    needsSecondRater: data.get("needsSecondRater") === "on",
    needsExpertAdjudication: needsExpertReview,
    mustAnnotate: finalEligibility.mustAnnotate,
    autoFixCandidate: finalEligibility.autoFixCandidate,
    impactType: finalEligibility.impactType,
    impactReason: finalEligibility.impactReason,
    affectedOutput: finalEligibility.affectedOutput,
    fixability: finalEligibility.fixability,
    annotationRoute: finalEligibility.annotationRoute,
    dismissedReason,
    fixRequest,
    includeInBenchmark: includeBenchmark,
    finalLabel: get("finalLabel"),
    adjudicationStatus,
    includeInBenchmarkDecision: get("includeInBenchmarkDecision"),
  };
  const saveStatus = root.querySelector("#save-status");
  saveStatus.textContent = "Saving...";
  const response = await fetch("/api/annotation", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(withRun(payload)),
  });
  run.visualizerData.annotations = await response.json();
  saveStatus.textContent = "Saved";
}

function journeyStages() {
  const stageNames = ["Idea", "Literature / Evidence", "Hypothesis / Plan", "Experiment Design", "Experiment Run", "Result Analysis", "Report Writing"];
  const events = canonicalEvents();
  return stageNames.map((name, index) => {
    const key = name.toLowerCase().replace(/ \/ .*/, "").split(" ")[0];
    const matchingEvents = events.filter((event) => eventStage(event).toLowerCase().includes(key)).slice(0, 8);
    const relatedDecisions = decisions().filter((decision) => {
      const text = `${decision.layer || ""} ${decision.phase || ""} ${decision.title || ""}`.toLowerCase();
      return text.includes(key) || (index === 6 && /paper|report|writing/.test(text));
    }).slice(0, 4);
    const outputs = outputArtifacts().filter((artifact) => {
      const path = artifactPath(artifact).toLowerCase();
      return index === 6 ? /paper|report|draft/.test(path) : path.includes(key) || (index === 5 && /result|metric|table|figure/.test(path));
    }).slice(0, 5);
    return { name, key, matchingEvents, relatedDecisions, outputs };
  });
}

function trajectoryPhaseDefinitions() {
  return [
    ["idea", "User idea from Hypogenic Hub", /idea|intent|user|hypogenic|submission/],
    ["refinement", "Idea refinement", /refine|scope|clarify|direction|hypothesis/],
    ["literature", "Literature/evidence search", /literature|evidence|search|related|paper|citation|review/],
    ["hypothesis", "Hypothesis generation", /hypothesis|claim|candidate/],
    ["design", "Experiment design", /design|protocol|split|evaluation|baseline|method|plan/],
    ["data", "Data/config preparation", /data|dataset|config|vocab|prepar|table/],
    ["execution", "Experiment execution", /run|execute|train|eval|model|experiment|job/],
    ["analysis", "Result analysis", /result|metric|accuracy|analysis|figure|plot|summary/],
    ["writing", "Report writing", /write|report|paper|draft|abstract|claim/],
    ["revision", "Revision/final output", /revision|final|validate|complete|finish/],
  ];
}

function phaseForText(text, fallbackIndex = 0) {
  const lower = String(text || "").toLowerCase();
  const found = trajectoryPhaseDefinitions().find(([, , pattern]) => pattern.test(lower));
  return found?.[1] || trajectoryPhaseDefinitions()[Math.min(fallbackIndex, trajectoryPhaseDefinitions().length - 1)][1];
}

function trajectoryNodes() {
  const explicit = run?.trajectoryNodes || run?.visualizerData?.trajectoryNodes || run?.trajectoryJourney?.nodes;
  if (Array.isArray(explicit) && explicit.length) return normalizeTrajectoryNodes(explicit);
  const phaseDefs = trajectoryPhaseDefinitions();
  const events = canonicalEvents();
  const nodes = phaseDefs.map(([key, phase], index) => {
    const matchingEvents = events.filter((event) => phaseForText(`${eventStage(event)} ${eventText(event)}`, index) === phase).slice(0, 8);
    const phaseDecisions = decisions().filter((decision) => phaseForText(`${decision.layer || ""} ${decision.phase || ""} ${decisionTitle(decision)} ${decision.rationale || ""}`, index) === phase).slice(0, 5);
    const phaseFindings = findings().filter((finding) => phaseForText(`${finding.kind || ""} ${finding.text || ""} ${finding.insight || ""}`, index) === phase).slice(0, 4);
    const phaseArtifacts = outputArtifacts().filter((artifact) => phaseForText(`${artifactPath(artifact)} ${artifact.summary || ""}`, index) === phase).slice(0, 5);
    const decision = phaseDecisions[0] || {};
    const event = matchingEvents[0] || {};
    const inputSummary = index === 0
      ? (run.idea?.description || run.idea?.hypothesis || researchState().headline || "User-submitted research idea")
      : `${phaseDefs[Math.max(0, index - 1)][1]} output`;
    const outputSummary = phaseArtifacts[0] ? artifactLabel(phaseArtifacts[0]) : (phaseFindings[0]?.text || decision.choice || event.output || event.result || `${phase} output`);
    return {
      nodeId: key,
      phase,
      title: phase,
      inputSummary: compactText(inputSummary, 150),
      outputSummary: compactText(outputSummary, 150),
      activitySummary: compactText(eventText(event) || decision.rationale || `NeuriCo worked on ${phase.toLowerCase()}.`, 220),
      howItWorkedSummary: compactText(decision.choice || event.action || event.command || phaseHowItWorked(phase), 220),
      assumptions: humanList(decision.assumptions || researchState().assumptions || [], "No explicit assumptions reconstructed."),
      constraints: humanList(decision.constraints || researchState().constraints || [], "No explicit constraints reconstructed."),
      decisions: phaseDecisions.map((item) => decisionTitle(item)),
      alternatives: humanList(decision.alternatives || (decision.options || []).map((opt) => opt.text || opt.label || opt.choice || opt), "No alternatives reconstructed."),
      evidenceUsed: dedupeRefs([...phaseDecisions.flatMap(evidenceRefsForDecision), ...phaseFindings.flatMap(evidenceRefsForFinding), ...phaseArtifacts.map((artifact) => ({ path: artifactPath(artifact), note: artifactLabel(artifact) }))]),
      uncertaintyCrux: compactText(decision.importanceRationale || decision.rationale || phaseFindings[0]?.text || "Reviewer should verify whether this step supports downstream claims.", 180),
      humanCheck: "Verify whether the step is adequately supported, whether a crux was missed, and whether expert adjudication is needed.",
      relatedArtifacts: phaseArtifacts.map((artifact) => ({ path: artifactPath(artifact), name: artifactLabel(artifact) })),
      relatedFindings: phaseFindings,
      relatedDecisions: phaseDecisions,
      sourceEvents: matchingEvents,
      parentNodeIds: index ? [phaseDefs[index - 1][0]] : [],
      childNodeIds: index < phaseDefs.length - 1 ? [phaseDefs[index + 1][0]] : [],
      provenanceTree: provenanceTreeForPhase(phase, phaseDecisions, phaseFindings, phaseArtifacts),
      tokenTraceAvailable: matchingEvents.some(hasTokenTrace),
      anchors: phaseDecisions.map((item) => item.paperRef).filter(Boolean),
      status: phaseDecisions.length ? "crux" : matchingEvents.length || phaseArtifacts.length ? "completed" : "sparse",
    };
  });
  return nodes;
}

function normalizeTrajectoryNodes(nodes) {
  return nodes.map((node, index) => ({
    nodeId: node.nodeId || node.id || `node-${index + 1}`,
    phase: node.phase || phaseForText(node.title || node.summary, index),
    title: node.title || node.name || phaseForText(node.summary, index),
    inputSummary: node.inputSummary || node.input || "Run context",
    outputSummary: node.outputSummary || node.output || "Step output",
    activitySummary: node.activitySummary || node.summary || node.whatItDid || "",
    howItWorkedSummary: node.howItWorkedSummary || node.howItWorked || node.does || "",
    assumptions: humanList(node.assumptions),
    constraints: humanList(node.constraints),
    decisions: humanList(node.decisions),
    alternatives: humanList(node.alternatives),
    evidenceUsed: Array.isArray(node.evidenceUsed) ? node.evidenceUsed : [],
    uncertaintyCrux: node.uncertaintyCrux || node.crux || "",
    humanCheck: node.humanCheck || "Reviewer verification needed.",
    relatedArtifacts: node.relatedArtifacts || [],
    relatedFindings: node.relatedFindings || [],
    relatedDecisions: node.relatedDecisions || [],
    sourceEvents: node.sourceEvents || [],
    parentNodeIds: node.parentNodeIds || [],
    childNodeIds: node.childNodeIds || [],
    provenanceTree: node.provenanceTree || [],
    tokenTraceAvailable: Boolean(node.tokenTraceAvailable),
    anchors: node.anchors || [],
    status: node.status || (node.uncertaintyCrux ? "crux" : "completed"),
  }));
}

function phaseHowItWorked(phase) {
  if (/Idea refinement/i.test(phase)) return "Turns a rough user idea into an executable research direction.";
  if (/Experiment design/i.test(phase)) return "Chooses the experimental setup and evaluation protocol.";
  if (/execution/i.test(phase)) return "Runs the selected experiment or model workflow.";
  if (/analysis/i.test(phase)) return "Converts outputs into metrics, tables, figures, and claims.";
  if (/writing/i.test(phase)) return "Turns research outputs into paper and report text.";
  return "Transforms upstream context into the next research artifact.";
}

function hasTokenTrace(event) {
  return Boolean(event?.token_ref || event?.tokenRefs || event?.chunk_refs || event?.chunkRefs || event?.promptSpan || event?.prompt_span);
}

function provenanceTreeForPhase(phase, phaseDecisions, phaseFindings, phaseArtifacts) {
  const decision = phaseDecisions[0] || {};
  const artifact = phaseArtifacts[0] || {};
  const finding = phaseFindings[0] || {};
  return [{
    label: "User input",
    summary: run?.idea?.description || run?.idea?.hypothesis || "User-submitted research idea.",
    children: [{
      label: "Generated idea(s)",
      summary: researchState().headline || phaseHowItWorked(phase),
      children: [{
        label: "Selected hypothesis",
        summary: researchState().currentBest || finding.text || finding.insight || phase,
        children: [{
          label: "Decision",
          summary: decisionTitle(decision) || "Decision reconstructed from review data.",
          targetKey: decision.id ? `decision:${decision.id}` : "",
          children: [{
            label: "Artifact / table / result",
            summary: artifactLabel(artifact) || "Generated artifact.",
            path: artifactPath(artifact) || "",
            children: [{
              label: "Paper claim",
              summary: selectedSectionLabel(),
              path: mainPaperPath(),
            }],
          }],
        }],
      }],
    }],
  }];
}

function filteredTrajectoryNodes() {
  const nodes = trajectoryNodes();
  return nodes.filter((node) => {
    if (journeyFilter === "all") return true;
    if (journeyFilter === "decisions") return node.relatedDecisions.length || node.decisions.length;
    if (journeyFilter === "cruxes") return /crux|failure|risk|uncertain/i.test(`${node.status} ${node.uncertaintyCrux}`);
    if (journeyFilter === "artifacts") return node.relatedArtifacts.length || node.evidenceUsed.length;
    if (journeyFilter === "failures") return /fail|error|retry|traceback|timeout/i.test(JSON.stringify(node.sourceEvents));
    if (journeyFilter === "paper-writing steps") return /report|paper|writing|abstract|claim/i.test(`${node.phase} ${node.title}`);
    return true;
  });
}

function renderJourney() {
  const nodes = filteredTrajectoryNodes();
  const allNodes = trajectoryNodes();
  const selected = allNodes.find((node) => node.nodeId === selectedJourneyNodeId);
  const tokenAvailable = allNodes.some((node) => node.tokenTraceAvailable);
  root.innerHTML = `
    <div class="journey-page trajectory-page">
      <section class="journey-head">
        <span class="eyebrow">Journey</span>
        <h2>Understand the trajectory</h2>
        <p>High-level map of where the research process went, with step-level transformation details available on click.</p>
        ${tokenAvailable ? "" : `<p class="provenance-warning">Token-level trace is not available for this run. Showing semantic and log-level provenance.</p>`}
      </section>
      <section class="trajectory-shell">
        <div class="trajectory-controls">
          <div class="issue-filter-tabs">
            ${["all", "decisions", "cruxes", "artifacts", "failures", "paper-writing steps"].map((filter) => `<button type="button" class="${journeyFilter === filter ? "active" : ""}" data-journey-filter="${escapeHtml(filter)}">${escapeHtml(filter)}</button>`).join("")}
          </div>
          <div class="trajectory-zoom">
            <button type="button" data-journey-zoom="out">-</button>
            <button type="button" data-journey-zoom="fit">Fit</button>
            <button type="button" data-journey-zoom="in">+</button>
          </div>
        </div>
        <div class="trajectory-canvas" style="--journey-zoom:${journeyZoom}">
          <div class="trajectory-track">
            ${nodes.map((node, index) => renderTrajectoryNode(node, index, nodes.length)).join("")}
          </div>
        </div>
        <div class="trajectory-minimap">
          ${trajectoryPhaseDefinitions().map(([, phase]) => `<button type="button" data-toggle-phase="${escapeHtml(phase)}" class="${collapsedJourneyPhases.has(phase) ? "collapsed" : ""}">${escapeHtml(phase)}</button>`).join("")}
        </div>
        ${selected ? renderTrajectoryDrawer(selected) : ""}
      </section>
    </div>`;
  root.querySelectorAll("[data-journey-node]").forEach((button) => button.addEventListener("click", () => {
    selectedJourneyNodeId = button.dataset.journeyNode;
    renderJourney();
  }));
  root.querySelector("[data-close-journey-drawer]")?.addEventListener("click", () => {
    selectedJourneyNodeId = "";
    renderJourney();
  });
  root.querySelectorAll("[data-journey-filter]").forEach((button) => button.addEventListener("click", () => {
    journeyFilter = button.dataset.journeyFilter;
    renderJourney();
  }));
  root.querySelectorAll("[data-journey-zoom]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.journeyZoom;
    if (action === "fit") journeyZoom = 1;
    if (action === "in") journeyZoom = Math.min(1.45, journeyZoom + .15);
    if (action === "out") journeyZoom = Math.max(.75, journeyZoom - .15);
    renderJourney();
  }));
  root.querySelectorAll("[data-toggle-phase]").forEach((button) => button.addEventListener("click", () => {
    const phase = button.dataset.togglePhase;
    if (collapsedJourneyPhases.has(phase)) collapsedJourneyPhases.delete(phase);
    else collapsedJourneyPhases.add(phase);
    renderJourney();
  }));
  root.querySelectorAll("[data-open-steering-target]").forEach((button) => button.addEventListener("click", () => {
    selectedTargetKey = button.dataset.openSteeringTarget;
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-open-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.openReport;
    openedReports = true;
    currentView = "artifacts";
    render();
  }));
  root.querySelectorAll("[data-create-stage-issue]").forEach((button) => button.addEventListener("click", () => {
    createManualIssue("manual_crux", button.dataset.createStageIssue);
  }));
  root.querySelectorAll("[data-escalate-stage]").forEach((button) => button.addEventListener("click", () => {
    createManualIssue("expert_review", button.dataset.escalateStage);
  }));
}

function renderTrajectoryNode(node, index) {
  if (collapsedJourneyPhases.has(node.phase)) {
    return `<button class="trajectory-cluster collapsed" type="button" data-toggle-phase="${escapeHtml(node.phase)}">${escapeHtml(node.phase)}</button>`;
  }
  const x = 70 + index * 220;
  const y = index % 2 ? 168 : 54;
  const crux = /crux|failure|risk|uncertain/i.test(`${node.status} ${node.uncertaintyCrux}`);
  return `
    <button type="button" class="trajectory-node ${selectedJourneyNodeId === node.nodeId ? "active" : ""} ${crux ? "crux" : ""}" data-journey-node="${escapeHtml(node.nodeId)}" style="left:${x}px;top:${y}px">
      <span class="node-dot"></span>
      <small>Phase: ${escapeHtml(compactText(node.phase, 42))}</small>
      <strong>${escapeHtml(compactText(node.title, 54))}</strong>
      <small>Input: ${escapeHtml(compactText(node.inputSummary, 82))}</small>
      <small>Output: ${escapeHtml(compactText(node.outputSummary, 82))}</small>
      <small>${escapeHtml(compactText(node.activitySummary, 82))}</small>
      <em>${escapeHtml(crux ? "crux" : node.status || "step")}</em>
    </button>`;
}

function renderTrajectoryDrawer(node) {
  return `
    <aside class="trajectory-drawer">
      <div class="panel-head">
        <div><span class="eyebrow">Step detail</span><h3>${escapeHtml(node.title)}</h3></div>
        <button type="button" data-close-journey-drawer>Close</button>
      </div>
      <dl class="trajectory-detail-list">
        <dt>Input</dt><dd>${escapeHtml(node.inputSummary)}</dd>
        <dt>Output</dt><dd>${escapeHtml(node.outputSummary)}</dd>
        <dt>What NeuriCo did</dt><dd>${escapeHtml(node.activitySummary)}</dd>
        <dt>How it did it</dt><dd>${escapeHtml(node.howItWorkedSummary)}</dd>
        <dt>Assumptions / constraints</dt><dd>${escapeHtml([...humanList(node.assumptions), ...humanList(node.constraints)].join(" | "))}</dd>
        <dt>Decisions</dt><dd>${escapeHtml(humanList(node.decisions).join(" | "))}</dd>
        <dt>Alternatives considered</dt><dd>${escapeHtml(humanList(node.alternatives).join(" | "))}</dd>
        <dt>Evidence used</dt><dd>${renderEvidenceButtons(node.evidenceUsed)}</dd>
        <dt>Uncertainty / crux</dt><dd>${escapeHtml(node.uncertaintyCrux || "No crux reconstructed.")}</dd>
        <dt>Human check</dt><dd>${escapeHtml(node.humanCheck)}</dd>
        <dt>Related files</dt><dd>${renderArtifactButtons(node.relatedArtifacts)}</dd>
      </dl>
      <section class="provenance-tree-section">
        <h4>Provenance tree</h4>
        ${renderProvenanceTree(node.provenanceTree)}
      </section>
      <div class="context-actions">
        <button data-create-stage-issue="${escapeHtml(node.title)}">Comment on this step</button>
        <button data-open-steering-target="${escapeHtml(node.relatedDecisions[0]?.id ? `decision:${node.relatedDecisions[0].id}` : selectedCandidate().key)}">Ask NeuriCo to fix</button>
        <button data-open-steering-target="${escapeHtml(node.relatedDecisions[0]?.id ? `decision:${node.relatedDecisions[0].id}` : selectedCandidate().key)}">Save benchmark annotation</button>
        <button data-escalate-stage="${escapeHtml(node.title)}">Escalate</button>
        <button data-open-report="${escapeHtml(node.relatedArtifacts[0]?.path || node.evidenceUsed[0]?.path || mainPaperPath())}">Open related report/source</button>
        <button data-traceback-stage>Traceback</button>
      </div>
      <details class="${developerMode ? "" : "dev-hidden"}">
        <summary>Log/event provenance</summary>
        <pre>${escapeHtml(JSON.stringify({ sourceEvents: node.sourceEvents, anchors: node.anchors }, null, 2))}</pre>
      </details>
    </aside>`;
}

function renderEvidenceButtons(refs = []) {
  const items = refs.slice(0, 8);
  return items.length ? `<div class="related-file-list">${items.map((ref) => `<button type="button" class="related-file-link" data-open-report="${escapeHtml(ref.path)}">${escapeHtml(artifactLabel(ref))}</button>`).join("")}</div>` : "No evidence file linked.";
}

function renderArtifactButtons(refs = []) {
  const items = refs.slice(0, 8);
  return items.length ? `<div class="related-file-list">${items.map((ref) => `<button type="button" class="related-file-link" data-open-report="${escapeHtml(ref.path)}">${escapeHtml(ref.name || artifactLabel(ref))}</button>`).join("")}</div>` : "No related file linked.";
}

function renderProvenanceTree(tree = []) {
  const nodes = tree.length ? tree : defaultProvenanceTree();
  const renderNode = (node) => `
    <li>
      <button type="button" class="provenance-node" ${node.path ? `data-open-report="${escapeHtml(node.path)}"` : node.targetKey ? `data-open-steering-target="${escapeHtml(node.targetKey)}"` : ""}>
        <strong>${escapeHtml(node.label || "Activity")}</strong>
        <span>${escapeHtml(compactText(node.summary || "", 120))}</span>
      </button>
      ${node.children?.length ? `<ul>${node.children.map(renderNode).join("")}</ul>` : ""}
    </li>`;
  return `<ul class="provenance-tree">${nodes.map(renderNode).join("")}</ul>`;
}

function defaultProvenanceTree() {
  return [{
    label: "User input",
    summary: run?.idea?.description || run?.idea?.hypothesis || "User-submitted research idea.",
    children: [{
      label: "Generated idea(s)",
      summary: researchState().headline || "Research direction reconstructed from the run.",
      children: [{
        label: "Selected hypothesis",
        summary: researchState().currentBest || researchState().headline || "Selected hypothesis or claim.",
        children: [{
          label: "Decision",
          summary: selectedCandidate().title || "Review decision.",
          targetKey: selectedCandidate().key,
          children: [{
            label: "Artifact / table / result",
            summary: humanTitle(selectedArtifactPath || mainPaperPath()),
            path: selectedArtifactPath || mainPaperPath(),
            children: [{
              label: "Paper claim",
              summary: selectedSectionLabel(),
              path: mainPaperPath(),
            }],
          }],
        }],
      }],
    }],
  }];
}

function stageDetailValues(stage) {
  const event = stage.matchingEvents[0] || {};
  const decision = stage.relatedDecisions[0] || {};
  const output = stage.outputs[0] || {};
  const fallback = "Agent activity summary is not available for this stage. Showing available input/output and linked artifacts.";
  return {
    "Input": stageInput(stage),
    "Output": stageOutput(stage),
    "Agent working process": compactText(event.action || event.command || eventText(event) || fallback, 220),
    "Evidence used": compactText(stage.outputs.map((artifact) => humanTitle(artifactPath(artifact))).join(", ") || "Evidence is linked when available.", 180),
    "Uncertainty / crux": compactText(decision.rationale || decision.choice || event.current_plan || "Check whether this stage supports the final output.", 180),
    "Human check": "Should an annotator steer, request missing context, or challenge the claim before downstream work continues?",
  };
}

function stageInput(stage) {
  const event = stage.matchingEvents[0] || {};
  return compactText(event.input || event.prompt || (stage.name === "Idea" ? researchState().headline || run?.idea?.title : stage.name), 120) || "Run context";
}

function stageOutput(stage) {
  const output = stage.outputs[0];
  const event = stage.matchingEvents[0] || {};
  return compactText(humanTitle(artifactPath(output || {})) || event.output || event.result || "No linked output yet.", 120);
}

function renderStageDetail(stage) {
  const values = stageDetailValues(stage);
  return `
    <div class="panel-head">
      <div><span class="eyebrow">Stage detail</span><h3>${escapeHtml(stage.name)}</h3></div>
      <button data-open-steering-target="${escapeHtml(priorityCandidates()[0]?.key || "")}">Open in Steering</button>
    </div>
    <div class="stage-grid">
      ${Object.entries(values).map(([label, value]) => `<article><span>${escapeHtml(label)}</span><p>${escapeHtml(value)}</p></article>`).join("")}
    </div>
    <div class="stage-related">
      <section>
        <h4>Related decisions</h4>
        ${stage.relatedDecisions.map((decision) => `<button data-open-steering-target="decision:${escapeHtml(decision.id)}">${escapeHtml(compactText(decisionTitle(decision), 100))}</button>`).join("") || `<p class="muted">No related reconstructed decisions.</p>`}
      </section>
      <section>
        <h4>Related reports/tables/figures</h4>
        ${stage.outputs.map((artifact) => `<button data-open-report="${escapeHtml(artifactPath(artifact))}">${escapeHtml(humanTitle(artifactPath(artifact)))}</button>`).join("") || `<p class="muted">No related output artifacts.</p>`}
      </section>
      <section>
        <h4>Available provenance</h4>
        ${stage.matchingEvents.map((event, index) => `<article><b>Research stage</b><span>${escapeHtml(eventText(event))}</span><small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">Raw trace: ${escapeHtml(eventId(event, index))}</small></article>`).join("") || `<p class="muted">Token-level trace is not available for this run. Showing stage/file-level provenance.</p>`}
      </section>
    </div>
    <div class="context-actions">
      <button data-open-report="${escapeHtml(artifactPath(stage.outputs[0] || {}) || mainPaperPath())}">Open related report</button>
      <button data-traceback-stage>Traceback</button>
      <button data-create-stage-issue="${escapeHtml(stage.name)}">Create issue from this stage</button>
      <button data-escalate-stage="${escapeHtml(stage.name)}">Escalate</button>
      <button data-open-steering-target="${escapeHtml(priorityCandidates()[0]?.key || "")}">Return to Steering</button>
    </div>`;
}

function renderTraceback() {
  const candidate = selectedCandidate();
  const tokenAvailable = canonicalEvents().some((event) => event.token_ref || event.tokenRefs || event.chunk_refs || event.chunkRefs);
  const stageAvailable = Boolean(relatedContext(candidate).relatedEvents[0] || candidate.evidence[0] || candidate.findingId);
  const chain = [
    `Output section: ${selectedSectionLabel()}`,
    candidate.findingId ? "Related finding" : "Related finding not linked",
    "Decision summary",
    relatedContext(candidate).relatedEvents[0] ? "Research stage" : "Research stage not linked",
    candidate.evidence[0]?.path ? `Reference file: ${humanTitle(candidate.evidence[0].path)}` : "Reference file not linked",
    developerMode ? "Raw trace" : "",
  ];
  return `
    <div class="traceback-chain">
      ${chain.filter(Boolean).map((item) => `<span>${escapeHtml(item)}</span>`).join("<i></i>")}
    </div>
    <p><strong>Available provenance.</strong> ${tokenAvailable ? "Token/chunk references detected for this run." : "Token-level trace is not available for this run. Showing stage/file-level provenance."}</p>`;
}

function reportItems() {
  const artifacts = dedupeArtifacts(outputArtifacts()).filter((artifact) => !isRunLiteraturePath(artifactPath(artifact)));
  const reviewItems = [
    { path: "review://open-comments", name: "Open comments", summary: "Reviewer comments that still need attention." },
    { path: "review://fix-requests", name: "NeuriCo fix requests", summary: "Low-impact issues routed to NeuriCo for a fix." },
    { path: "review://resolved-comments", name: "Resolved comments", summary: "Reviewer comments marked completed or dismissed." },
    { path: "review://escalated-issues", name: "Escalated issues", summary: "Issues awaiting expert/professor adjudication." },
  ];
  const priority = [
    "Main Paper",
    "Final Report",
    "Report Draft",
    "Literature Review Notes",
    "Candidate Vocabulary Table",
    "Split Counts Summary",
    "Validation Checks",
    "Experiment Result Summary",
    "Hidden-State Extraction Summary",
    "Accuracy Figure",
    "Layer Accuracy Plot",
    "Pipeline Diagram",
    "Experiment Config Summary",
  ];
  return [...artifacts, ...reviewItems].sort((a, b) => {
    const ai = priority.indexOf(humanTitle(artifactPath(a)));
    const bi = priority.indexOf(humanTitle(artifactPath(b)));
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || humanTitle(artifactPath(a)).localeCompare(humanTitle(artifactPath(b)));
  });
}

function dedupeArtifacts(artifacts) {
  const seen = new Set();
  const seenGeneric = new Set();
  return artifacts.filter((artifact) => {
    const path = artifactPath(artifact);
    const title = humanTitle(path);
    if (!path || seen.has(path)) return false;
    if (/^Report Draft$/i.test(title)) {
      if (seenGeneric.has(title)) return false;
      seenGeneric.add(title);
    }
    seen.add(path);
    return true;
  });
}

function renderReports() {
  const items = reportItems().filter((artifact) => !reportQuery || `${humanTitle(artifactPath(artifact))} ${artifactPath(artifact)}`.toLowerCase().includes(reportQuery.toLowerCase()));
  const selected = selectedArtifactPath || mainPaperPath();
  const selectedTitle = humanTitle(selected);
  const grouped = groupedReportItems(items);
  root.innerHTML = `
    <div class="reports-page">
      <section class="reports-head">
        <div>
          <span class="eyebrow">Reports & Evidence</span>
          <h2>Research outputs and evidence</h2>
        </div>
        <input id="report-search" type="search" placeholder="Filter outputs" value="${escapeHtml(reportQuery)}">
      </section>
      <section class="reports-layout">
        <div class="report-list">
          ${grouped.map(([group, artifacts]) => `
            <section class="report-group">
              <h3>${escapeHtml(group)}</h3>
              ${artifacts.map((artifact) => renderReportCard(artifact, selected)).join("")}
            </section>`).join("") || `<p class="muted">No human-readable report/table/figure artifacts found.</p>`}
          ${renderRunLiteratureGroup(selected)}
        </div>
        <section class="report-preview" id="report-preview">
          <div class="panel-head compact">
            <div>
              <span class="eyebrow">Artifact viewer</span>
              <h3>${escapeHtml(selectedTitle)}</h3>
              <small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(selected)}</small>
            </div>
            <button data-return-steering>Back to Steering</button>
          </div>
          ${renderReportPreview(selected)}
          <section class="missing-issue-panel">
            <h4>Something important missing?</h4>
            <div class="form-actions">
              <button type="button" data-report-manual="manual_crux">Create new issue</button>
              <button type="button" data-report-manual="llm_missed_issue">Mark LLM missed a crux</button>
              <button type="button" data-report-manual="expert_review">Escalate artifact</button>
            </div>
          </section>
        </section>
      </section>
    </div>`;
  loadReportPreview(selected);
  root.querySelector("#report-search")?.addEventListener("input", (event) => {
    reportQuery = event.target.value;
    renderReports();
  });
  root.querySelectorAll("[data-select-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.selectReport;
    renderReports();
  }));
  root.querySelectorAll("[data-open-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.openReport;
    renderReports();
  }));
  root.querySelectorAll("[data-annotate-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.annotateReport;
    selectedTargetKey = `artifact:${selectedArtifactPath}#${selectedRegion || "span"}`;
    selectedReviewSource = "report_review";
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-open-file]").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.openFile)));
  root.querySelectorAll("[data-select-source]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.selectSource;
    renderReports();
  }));
  root.querySelectorAll("[data-open-source]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.openSource;
    renderReports();
  }));
  root.querySelectorAll("[data-annotate-source]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.annotateSource;
    selectedTargetKey = `artifact:${selectedArtifactPath}#${selectedRegion || "span"}`;
    selectedReviewSource = "run_literature_review";
    currentView = "steering";
    render();
  }));
  root.querySelectorAll("[data-trace-source]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.traceSource;
    selectedTargetKey = `artifact:${selectedArtifactPath}#${selectedRegion || "span"}`;
    selectedReviewSource = "run_literature_trace";
    openedJourney = true;
    currentView = "trajectory";
    render();
  }));
  root.querySelectorAll("[data-trace-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.traceReport;
    selectedTargetKey = `artifact:${selectedArtifactPath}#${selectedRegion || "span"}`;
    selectedReviewSource = "journey_escalation";
    openedJourney = true;
    currentView = "trajectory";
    render();
  }));
  root.querySelectorAll("[data-ask-report]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = button.dataset.askReport;
    selectedTargetKey = `artifact:${selectedArtifactPath}#${selectedRegion || "span"}`;
    selectedReviewSource = "report_review";
    assistantDraft = null;
    currentView = "steering";
    render();
    setTimeout(() => root.querySelector("#assistant-input")?.focus(), 0);
  }));
  root.querySelectorAll("[data-report-manual]").forEach((button) => button.addEventListener("click", () => {
    selectedArtifactPath = selected;
    selectedReviewSource = "report_review";
    createManualIssue(button.dataset.reportManual || "manual_crux", humanTitle(selected));
  }));
  root.querySelector("[data-return-steering]")?.addEventListener("click", () => {
    currentView = "steering";
    render();
  });
}

function humanTitle(path) {
  if (path === "review://open-comments") return "Open comments";
  if (path === "review://fix-requests") return "NeuriCo fix requests";
  if (path === "review://resolved-comments") return "Resolved comments";
  if (path === "review://escalated-issues") return "Escalated issues";
  const name = path.split("/").pop() || path;
  if (/^paper_draft\/main\.pdf$/i.test(path)) return "Main Paper";
  if (/planning\.md$/i.test(path)) return "Experiment Config Summary";
  if (/results\/candidate_vocab\.json$/i.test(path)) return "Candidate Vocabulary Table";
  if (/results\/summary\.json$/i.test(path)) return "Split Counts Summary";
  if (/report\.md$/i.test(path)) return "Final Report";
  if (/literature[_-]?review\.(md|txt|pdf)$/i.test(path)) return "Literature Review Notes";
  if (/resources\.(md|txt)$/i.test(path)) return "Literature Review Notes";
  if (/hidden.*states.*qwen|hidden[-_ ]?state/i.test(path)) return "Hidden-State Extraction Summary";
  if (/candidate.*vocab|vocab.*candidate/i.test(path)) return "Candidate Vocabulary Table";
  if (/split.*count|count.*split/i.test(path)) return "Split Counts Summary";
  if (/validation.*check|check.*validation/i.test(path)) return "Validation Checks";
  if (/layer.*accuracy|accuracy.*layer/i.test(path)) return "Layer Accuracy Plot";
  if (/top[-_ ]?1.*accuracy|accuracy.*top[-_ ]?1/i.test(path)) return "Top-1 Accuracy Figure";
  if (/top[-_ ]?5.*accuracy|accuracy.*top[-_ ]?5/i.test(path)) return "Top-5 Accuracy Figure";
  if (/accuracy|figure|plot|chart/i.test(path) && /\.(png|jpg|jpeg|svg)$/i.test(path)) return "Accuracy Figure";
  if (/diagram|pipeline/i.test(path)) return "Pipeline Diagram";
  if (/config.*summary|summary.*config|experiment.*config/i.test(path)) return "Experiment Config Summary";
  if (/summary/i.test(path)) return "Experiment Result Summary";
  if (/table|\.csv$/i.test(path)) return "Results Table";
  if (/draft|outline/i.test(path)) return "Report Draft";
  if (/crux.*open|open.*world.*eval/i.test(path)) return "CRUX Open-World Evaluations";
  if (/crux.*long|long.*horizon|r.?d.*eval/i.test(path)) return "CRUX Long-Horizon AI R&D Evals";
  if (/log.*analysis|agent.*evaluation/i.test(path)) return "Log Analysis for Agent Evaluation";
  if (/after.*science/i.test(path)) return "After Science";
  if (/could.*ai.*slow.*science|slow.*science/i.test(path)) return "Could AI Slow Science";
  if (/overnight.*agent/i.test(path)) return "Overnight Agent Note";
  if (/shepherd/i.test(path)) return "SHEPHERD";
  if (/dreamcoder/i.test(path)) return "DreamCoder";
  if (/strace|bonsai/i.test(path)) return "strace-ui / Bonsai term";
  if (isRunLiteraturePath(path) && /^source[-_ ]?\d+/i.test(name)) return `Source Paper ${name.match(/\d+/)?.[0] || ""}`.trim();
  return name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function reportType(path) {
  if (String(path || "").startsWith("review://")) return "review";
  if (/hidden.*states.*qwen|hidden[-_ ]?state/i.test(path)) return "experiment summary";
  if (isRunLiteraturePath(path)) return "source";
  if (isSystemReferencePath(path)) return "system reference";
  if (/\.pdf$/i.test(path) || /paper/i.test(path)) return "paper";
  if (/config|summary/i.test(path)) return "report";
  if (/table|\.(csv|json)$/i.test(path)) return "table";
  if (/diagram|pipeline/i.test(path)) return "diagram";
  if (/figure|plot|chart|\.(png|jpg|jpeg|svg)$/i.test(path)) return "figure";
  if (/draft|outline/i.test(path)) return "draft";
  return "report";
}

function reportGroup(path) {
  const title = humanTitle(path);
  if (String(path || "").startsWith("review://")) return "Reviewer Comments / Fix Requests";
  if (isSystemReferencePath(path)) return "Related Work / System References";
  if (/Main Paper|Final Report|Report Draft/i.test(title)) return "Generated Outputs";
  if (/Vocabulary|Split Counts|Validation Checks|Result Summary|Results Table|Config Summary|Hidden-State Extraction/i.test(title) || /\.(csv|json)$/i.test(path)) return "Tables & Results";
  if (/Figure|Plot|Diagram/i.test(title) || /\.(png|jpg|jpeg|svg)$/i.test(path)) return "Figures & Diagrams";
  return "Generated Outputs";
}

function groupedReportItems(items) {
  const groups = ["Generated Outputs", "Tables & Results", "Figures & Diagrams", "Reviewer Comments / Fix Requests", "Related Work / System References"];
  return groups.map((name) => [name, items.filter((artifact) => reportGroup(artifactPath(artifact)) === name)])
    .filter(([, groupItems]) => groupItems.length);
}

function runLiteratureData() {
  return run?.literatureSources || null;
}

function runLiteratureSources() {
  const sources = runLiteratureData()?.sources;
  return Array.isArray(sources) ? sources : [];
}

function runLiteratureSourceCount() {
  const data = runLiteratureData();
  if (!data) return null;
  return Number.isFinite(Number(data.sourceCount)) ? Number(data.sourceCount) : runLiteratureSources().length;
}

function sourcePath(source) {
  return source?.localFile || source?.localPath || source?.url || "";
}

function sourceTitle(source) {
  return source?.title || humanTitle(sourcePath(source)) || source?.sourceId || "Untitled source";
}

function sourceUsedFor(source) {
  return humanList(source?.howNeuricoUsedIt || source?.usedFor, "not specified").join(", ");
}

function filteredRunLiteratureSources() {
  const query = reportQuery.toLowerCase();
  return runLiteratureSources().filter((source) => {
    if (!query) return true;
    return `${sourceTitle(source)} ${source.type || source.sourceType || ""} ${sourceUsedFor(source)} ${source.relevanceSummary || ""} ${sourcePath(source)}`.toLowerCase().includes(query);
  });
}

function renderRunLiteratureGroup(selected) {
  const data = runLiteratureData();
  const count = runLiteratureSourceCount();
  const sources = filteredRunLiteratureSources();
  let body = "";
  if (!data) {
    body = `<p class="muted">Run literature has not been extracted yet.</p>`;
  } else if (count === 0) {
    body = `<p class="muted">Only 0 literature sources were found in this run.</p>`;
  } else if (!sources.length) {
    body = `<p class="muted">No run literature sources match the current filter.</p>`;
  } else {
    body = `<p class="muted">Only ${escapeHtml(count)} literature sources were found in this run.</p>` + sources.map((source) => renderLiteratureSourceCard(source, selected)).join("");
  }
  return `
    <section class="report-group run-literature-group">
      <h3>Run Literature / Sources Reviewed</h3>
      ${body}
    </section>`;
}

function renderLiteratureSourceCard(source, selected) {
  const path = sourcePath(source);
  const active = path && path === selected;
  const disabled = path ? "" : " disabled";
  return `
    <article class="report-card literature-source-card ${active ? "active" : ""}">
      <button data-select-source="${escapeHtml(path)}"${disabled}>
        <strong>${escapeHtml(sourceTitle(source))}</strong>
        <em>${escapeHtml(source.type || source.sourceType || "source")}</em>
        <dl class="artifact-mini-summary">
          <dt>Used for</dt><dd>${escapeHtml(compactText(sourceUsedFor(source), 140))}</dd>
        </dl>
        ${path ? `<small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(path)}</small>` : ""}
      </button>
      <div class="report-actions">
        <button data-open-source="${escapeHtml(path)}"${disabled}>Open source</button>
        <button data-trace-source="${escapeHtml(path)}"${disabled}>Trace in Journey</button>
        <button data-annotate-source="${escapeHtml(path || source.sourceId || sourceTitle(source))}">Annotate source</button>
      </div>
    </article>`;
}

function renderReportCard(artifact, selected) {
  const path = artifactPath(artifact);
  const isSource = isRunLiteraturePath(path);
  const isHiddenState = /hidden.*states.*qwen|hidden[-_ ]?state/i.test(path);
  const sourceMeta = sourceMetadata(artifact, path);
  return `
    <article class="report-card ${path === selected ? "active" : ""}">
      <button data-select-report="${escapeHtml(path)}">
        <strong>${escapeHtml(humanTitle(path))}</strong>
        <em>${escapeHtml(reportType(path))}</em>
        ${isSource ? renderSourceSummary(sourceMeta) : isHiddenState ? renderHiddenStateSummary(path) : `<span>${escapeHtml(compactText(reportCardSummary(artifact, path), 180))}</span>`}
        <small class="dev-secondary ${developerMode ? "" : "dev-hidden"}">${escapeHtml(path)}</small>
      </button>
      <div class="report-actions">
        <button data-select-report="${escapeHtml(path)}">${isSource ? "Open source" : "Preview"}</button>
        <button data-trace-report="${escapeHtml(path)}">Trace in Journey</button>
        <button data-annotate-report="${escapeHtml(path)}">${isSource ? "Annotate this source" : "Annotate this"}</button>
      </div>
    </article>`;
}

function isRunLiteraturePath(path) {
  const lower = String(path || "").toLowerCase();
  if (isSystemReferencePath(path)) return false;
  if (/(^|\/)\.(gemini|claude|codex)\/skills\//.test(lower)) return false;
  return /(^|\/)(literature_review|resources)\.(md|txt|pdf)$/.test(lower)
    || /^(papers|paper_search_results|sources|literature|downloads|web_sources)\//.test(lower)
    || /^papers\/pages\/.*_manifest\.txt$/.test(lower)
    || /\.(bib)$/i.test(lower);
}

function isSystemReferencePath(path) {
  return /crux|open.?world|long.?horizon|r.?d.?eval|log.?analysis|agent.?evaluation|after.?science|slow.?science|overnight.?agent|shepherd|dreamcoder|strace|bonsai/i.test(String(path || ""));
}

function reportCardSummary(artifact, path) {
  if (isRunLiteraturePath(path)) return artifact.summary || "Run literature source found or used by NeuriCo.";
  if (isSystemReferencePath(path)) return artifact.summary || "Reference used to frame CruxLens / SteerBench.";
  return artifact.summary || artifact.group || "Human-readable generated output.";
}

function sourceUsageSummary(artifact) {
  return artifact.usedFor || artifact.howUsed || artifact.note || "How NeuriCo used it: source available in the run artifacts.";
}

function sourceMetadata(artifact, path) {
  return {
    authorsYear: [artifact.authors || artifact.author, artifact.year].filter(Boolean).join(", "),
    relevance: artifact.relevance || artifact.summary || "Available literature source from this run.",
    used: sourceUsageSummary(artifact),
    title: artifact.title || humanTitle(path),
  };
}

function renderSourceSummary(meta) {
  return `<dl class="artifact-mini-summary">
    ${meta.authorsYear ? `<dt>Authors/year</dt><dd>${escapeHtml(meta.authorsYear)}</dd>` : ""}
    <dt>Relevance</dt><dd>${escapeHtml(compactText(meta.relevance, 140))}</dd>
    <dt>How used</dt><dd>${escapeHtml(compactText(meta.used, 140))}</dd>
  </dl>`;
}

function renderHiddenStateSummary(path) {
  const text = path.replace(/[\/_.-]+/g, " ");
  const model = /qwen2?p?5|qwen/i.test(text) ? "Qwen2.5-0.5B" : "not specified";
  const vocab = text.match(/words?\s*(\d+)|vocab(?:ulary)?\s*(\d+)/i);
  const examples = text.match(/ex(?:amples?)?\s*(\d+)/i);
  const seed = text.match(/seed\s*(\d+)/i);
  const length = text.match(/len(?:gth)?\s*(\d+)/i);
  return `<dl class="artifact-mini-summary">
    <dt>Model</dt><dd>${escapeHtml(model)}</dd>
    <dt>Vocabulary size</dt><dd>${escapeHtml(vocab?.[1] || vocab?.[2] || "128")} words</dd>
    <dt>Examples</dt><dd>${escapeHtml(examples?.[1] || "2048")}</dd>
    <dt>Seed</dt><dd>${escapeHtml(seed?.[1] || "42")}</dd>
    <dt>Sequence length</dt><dd>${escapeHtml(length?.[1] || "96")}</dd>
  </dl>`;
}

function renderReportPreview(path) {
  if (!path) return `<p class="muted">Select a report, table, figure, or diagram.</p>`;
  if (String(path).startsWith("review://")) return renderReviewArtifact(path);
  if (/^https?:\/\//i.test(path)) return `<section class="artifact-human-summary"><h4>Source</h4><p>${escapeHtml(path)}</p></section>`;
  if (/hidden.*states.*qwen|hidden[-_ ]?state/i.test(path)) {
    return `<section class="artifact-human-summary">
      <h4>Hidden-State Extraction Summary</h4>
      ${renderHiddenStateSummary(path)}
      <h4>Linked files</h4>
      ${renderArtifactButtons([{ path, name: "Hidden-State Extraction Summary" }])}
      <h4>Related results</h4>
      ${renderArtifactButtons(outputArtifacts().filter((artifact) => /accuracy|result|summary|validation/i.test(artifactPath(artifact))).slice(0, 6).map((artifact) => ({ path: artifactPath(artifact), name: humanTitle(artifactPath(artifact)) })))}
      <h4>Related decision / crux</h4>
      <div class="related-file-list">${priorityCandidates(true).filter((candidate) => /hidden|state|qwen|model|extraction/i.test(`${candidate.title} ${candidate.summary}`)).slice(0, 3).map((candidate) => `<button type="button" class="related-file-link" data-annotate-report="${escapeHtml(path)}">${escapeHtml(candidate.title)}</button>`).join("") || "<p class=\"muted\">No related decision linked.</p>"}</div>
    </section>`;
  }
  const url = `/api/file?path=${encodeURIComponent(path)}${runQuery()}`;
  if (/\.(png|jpg|jpeg|svg)$/i.test(path)) return `<img src="${url}" alt="${escapeHtml(path)}">`;
  if (/\.pdf$/i.test(path)) return `<div class="pdfjs-viewer report-pdf-viewer" data-readonly-pdf="${escapeHtml(url)}"><div class="pdf-loading">Loading paper...</div></div>`;
  return `<div class="artifact-content" data-artifact-content="${escapeHtml(path)}"><p class="muted">Loading full content...</p></div>`;
}

function reviewArtifactsFor(path) {
  const entries = allReviewIssues().map((candidate) => ({ candidate, anno: latestAnnotation(candidate.key) }));
  if (path === "review://fix-requests") return entries.filter(({ anno }) => anno.annotationRoute === "fix_request" || anno.fixRequest);
  if (path === "review://escalated-issues") return entries.filter(({ anno }) => anno.needsExpertReview || anno.needsExpertAdjudication || anno.annotationRoute === "expert_escalation");
  if (path === "review://resolved-comments") return entries.filter(({ anno }) => anno.annotationRoute === "dismissed" || anno.workflowStatus === "benchmark_ready" || anno.benchmarkStatus?.workflowStatus === "benchmark_ready");
  return entries.filter(({ anno }) => (anno.reviewerComment || anno.quickComment) && !["dismissed"].includes(anno.annotationRoute));
}

function renderReviewArtifact(path) {
  const rows = reviewArtifactsFor(path);
  return `<section class="artifact-human-summary">
    <h4>${escapeHtml(humanTitle(path))}</h4>
    ${rows.map(({ candidate, anno }) => {
      const eligibility = eligibilityFor(candidate, anno, reviewerChecklistValues(anno, {}));
      return `<article class="review-artifact-row">
        <strong>${escapeHtml(compactText(candidate.title, 130))}</strong>
        <p>${escapeHtml(compactText(anno.reviewerComment || anno.quickComment || eligibility.impactReason, 220))}</p>
        <small>Route: ${escapeHtml(routeLabel(anno.annotationRoute || eligibility.annotationRoute))} · Affects: ${escapeHtml(eligibility.affectedOutput[0] || affectedOutput(candidate))}</small>
        <button type="button" data-annotate-report="${escapeHtml(selectedArtifactPath || mainPaperPath())}">Review in Steering</button>
      </article>`;
    }).join("") || `<p class="muted">No items in this group yet.</p>`}
  </section>`;
}

async function loadReportPreview(path) {
  const reportPdf = root.querySelector("[data-readonly-pdf]");
  if (reportPdf) {
    renderReadOnlyPdf(reportPdf, reportPdf.dataset.readonlyPdf);
    return;
  }
  const body = root.querySelector(".artifact-content");
  if (!body || !path) return;
  try {
    const artifact = await (await fetch(`/api/artifact?path=${encodeURIComponent(path)}${runQuery()}`)).json();
    if (artifact.previewType === "csv") body.innerHTML = renderCsv(artifact.csv);
    else if (/\.json$/i.test(path)) body.innerHTML = renderJsonTable(artifact.content || "");
    else body.innerHTML = renderMarkdownish(artifact.content || "");
  } catch {
    body.innerHTML = `<p>Could not load ${escapeHtml(humanTitle(path))}.</p>`;
  }
}

async function renderReadOnlyPdf(container, url) {
  try {
    const pdfjs = await ensurePdfJs();
    const pdf = await pdfjs.getDocument(url).promise;
    container.innerHTML = `<div class="pdf-pages"></div>`;
    const pages = container.querySelector(".pdf-pages");
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const viewport = page.getViewport({ scale: Math.min(1.3, Math.max(.9, container.clientWidth / 760)) });
      const pageEl = document.createElement("div");
      pageEl.className = "pdf-page readonly";
      pageEl.style.width = `${viewport.width}px`;
      pageEl.style.height = `${viewport.height}px`;
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      pageEl.append(canvas);
      pages.append(pageEl);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
    }
  } catch (error) {
    container.innerHTML = `<p>Could not load ${escapeHtml(url)}.</p>`;
  }
}

function renderJsonTable(content) {
  try {
    const value = JSON.parse(content || "{}");
    const rows = Array.isArray(value) ? value : Object.entries(value).map(([key, val]) => ({ key, value: typeof val === "object" ? JSON.stringify(val) : val }));
    if (!rows.length) return `<p class="muted">No rows.</p>`;
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 12);
    return `<table><thead><tr>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 500).map((row) => `<tr>${columns.map((c) => `<td>${escapeHtml(typeof row[c] === "object" ? JSON.stringify(row[c]) : row[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  } catch {
    return `<pre>${escapeHtml(content || "")}</pre>`;
  }
}

function renderMarkdownish(content) {
  const escaped = escapeHtml(content || "");
  if (!escaped.trim()) return `<p class="muted">No content available.</p>`;
  return `<div class="rendered-markdown">${escaped
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h2>$1</h2>")
    .split(/\n{2,}/)
    .map((block) => /^<h[234]>/.test(block) ? block : `<p>${block.replace(/\n/g, "<br>")}</p>`)
    .join("")}</div>`;
}

function renderAdvanced() {
  const rawFiles = (run.artifacts || []).filter((artifact) => !isHumanReadableOutput(artifact) || isRawDeveloperArtifact(artifact));
  root.innerHTML = `
    <div class="advanced-page">
      <section class="panel">
        <span class="eyebrow">Advanced</span>
        <h2>Raw/debug/internal views</h2>
        <p>Raw events, reconstructed data, old graph material, files, logs, scripts, and internal debug views live here.</p>
      </section>
      <section class="advanced-grid">
        <details open><summary>Benchmark Export</summary>
          <p class="muted">Developer-only export surface. Normal reviewers do not see JSONL or export fields.</p>
          <pre>python3 tools/export_annotations.py --format jsonl --out benchmark.jsonl</pre>
        </details>
        <details open><summary>Raw events</summary><pre>${escapeHtml(JSON.stringify(canonicalEvents().slice(0, 200), null, 2))}</pre></details>
        <details><summary>Raw decisions</summary><pre>${escapeHtml(JSON.stringify(decisions(), null, 2))}</pre></details>
        <details><summary>Old flow graph</summary><pre>${escapeHtml(JSON.stringify(run.visualizerData?.flowGraph || {}, null, 2))}</pre></details>
        <details><summary>Raw trajectory</summary><pre>${escapeHtml(JSON.stringify(run.canonicalTrajectory || {}, null, 2))}</pre></details>
        <details><summary>world_model.json</summary><pre>${escapeHtml(JSON.stringify({ researchState: run.researchState, worldModelGraph: run.worldModelGraph }, null, 2))}</pre></details>
        <details><summary>canonical_trajectory.json</summary><pre>${escapeHtml(JSON.stringify(run.canonicalTrajectory || {}, null, 2))}</pre></details>
        <details><summary>Raw files</summary>${rawFiles.slice(0, 500).map((artifact) => `<button data-open-file="${escapeHtml(artifactPath(artifact))}">${escapeHtml(artifactPath(artifact))}</button>`).join("") || `<p class="muted">No raw files listed.</p>`}</details>
        <details><summary>Debug search</summary><pre>${escapeHtml(JSON.stringify(annotationMap(), null, 2))}</pre></details>
      </section>
    </div>`;
  root.querySelectorAll("[data-open-file]").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.openFile)));
}

function renderAutoResearch() {
  root.innerHTML = `
    <section class="panel">
      <h2>AutoResearch</h2>
      ${run?.autoresearch?.detected ? `<pre>${escapeHtml(JSON.stringify(run.autoresearch, null, 2))}</pre>` : `<p class="muted">AutoResearch data is not available for this run.</p>`}
    </section>`;
}

async function openEvidence(path) {
  if (!path) return;
  let drawer = document.querySelector("#evidence-drawer");
  if (!drawer) {
    drawer = document.createElement("div");
    drawer.id = "evidence-drawer";
    drawer.innerHTML = `<div class="drawer-backdrop" data-close-drawer></div><aside><header><strong></strong><button data-close-drawer>Close</button></header><div class="drawer-body"></div></aside>`;
    document.body.appendChild(drawer);
    drawer.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-drawer]")) drawer.classList.remove("open");
    });
  }
  drawer.classList.add("open");
  drawer.querySelector("strong").textContent = path;
  const body = drawer.querySelector(".drawer-body");
  body.innerHTML = `<p class="muted">Loading...</p>`;
  try {
    const artifact = await (await fetch(`/api/artifact?path=${encodeURIComponent(path)}${runQuery()}`)).json();
    if (artifact.previewType === "image") body.innerHTML = `<img src="${artifact.url}" alt="${escapeHtml(path)}">`;
    else if (artifact.previewType === "binary") body.innerHTML = `<iframe src="${artifact.url}" title="${escapeHtml(path)}"></iframe>`;
    else if (artifact.previewType === "csv") body.innerHTML = renderCsv(artifact.csv);
    else body.innerHTML = `<pre>${escapeHtml(artifact.content || "")}</pre>`;
  } catch (error) {
    body.innerHTML = `<p>Could not load ${escapeHtml(path)}.</p>`;
  }
}

function renderCsv(csv) {
  if (!csv?.columns?.length) return `<p class="muted">No rows.</p>`;
  return `<table><thead><tr>${csv.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${csv.rows.slice(0, 200).map((row) => `<tr>${csv.columns.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.autoresearchTab && !run?.autoresearch?.detected) return;
    if (button.dataset.view === "advanced" && !developerMode) return;
    if (button.dataset.view === "trajectory") openedJourney = true;
    if (button.dataset.view === "artifacts") openedReports = true;
    sidebarExpandedOverride = false;
    currentView = button.dataset.view;
    render();
  });
});

sidebarToggle?.addEventListener("click", () => {
  sidebarExpandedOverride = !sidebarExpandedOverride;
  updateSidebarState();
});

backToList?.addEventListener("click", () => {
  run = null;
  currentRunId = null;
  currentScreen = "list";
  renderApp();
});

userChip?.addEventListener("click", () => {
  localStorage.removeItem("steerbench-user-email");
  userEmail = "";
  run = null;
  currentRunId = null;
  currentScreen = "entry";
  renderApp();
});

renderApp();
