import crypto from "node:crypto";
import path from "node:path";

export const ANNOTATION_SCHEMA_VERSION = "annotation-v1";
export const VISUALIZER_VERSION = "neurico-platform-v1";
export const WORLD_MODEL_VERSION = "wm-v3";

export const JOB_STATUSES = new Set([
  "queued",
  "running",
  "partially_ready",
  "ready",
  "degraded",
  "failed_retryable",
  "failed_permanent",
  "cancelled",
]);

export const WORLD_MODEL_STAGES = [
  "inventory",
  "chronological_segmentation",
  "decisions",
  "hypotheses",
  "findings",
  "failures_validity_risks",
  "relationships",
  "final_assembly_validation",
];

export const FAILURE_LABELS = [
  "unsupported_claim",
  "premature_conclusion",
  "insufficient_evidence",
  "ignored_evidence",
  "weak_experimental_design",
  "data_leakage_risk",
  "evaluation_mismatch",
  "incorrect_metric",
  "missing_baseline",
  "insufficient_alternatives",
  "unnecessary_tool_use",
  "repeated_failed_action",
  "resource_waste",
  "context_loss",
  "contradictory_reasoning",
  "failed_recovery",
  "unsafe_action",
  "unclear_decision",
  "reconstruction_error",
  "other",
];

export const HUMAN_INTERVENTION_VALUES = new Set([
  "not_needed",
  "inform_only",
  "helpful",
  "required",
  "uncertain",
]);

export const SCALE_VALUES = new Set([1, 2, 3, 4, 5, "not_applicable", "insufficient_evidence"]);

export function inside(base, candidate) {
  const relative = path.relative(base, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export function assertRunId(runId) {
  const value = String(runId || "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)) {
    throw Object.assign(new Error("Invalid run_id"), { status: 400, code: "invalid_run_id" });
  }
  return value;
}

export function parseWorkspaceUri(workspaceUri) {
  const raw = String(workspaceUri || "").trim();
  if (!raw) throw Object.assign(new Error("workspace_uri is required"), { status: 400, code: "workspace_required" });
  if (raw.startsWith("file://")) {
    return decodeURIComponent(new URL(raw).pathname);
  }
  if (raw.startsWith("/")) return raw;
  throw Object.assign(new Error("Only file:// or absolute workspace paths are supported"), { status: 400, code: "unsupported_workspace_uri" });
}

export function safeArtifactPath(relativePath) {
  const value = String(relativePath || "").replace(/^\/+/, "");
  if (!value || value.includes("\0") || path.isAbsolute(value)) {
    throw Object.assign(new Error("Invalid artifact path"), { status: 400, code: "invalid_artifact_path" });
  }
  const parts = value.split(/[\\/]+/);
  if (parts.some((part) => part === ".." || part === "." || !part)) {
    throw Object.assign(new Error("Invalid artifact path"), { status: 400, code: "invalid_artifact_path" });
  }
  if (/^(\.env|.*secret.*|.*credential.*|.*token.*|id_rsa|id_dsa|id_ed25519)$/i.test(path.basename(value))) {
    throw Object.assign(new Error("Artifact is not servable"), { status: 403, code: "artifact_denied" });
  }
  return value;
}

export function sha256Json(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function contentFingerprint(parts) {
  return sha256Json({
    input_checksums: parts.inputChecksums || {},
    pipeline_state: parts.pipelineState || null,
    pipeline_results: parts.pipelineResults || null,
    transcript_digest: parts.transcriptDigest || "",
    report_digest: parts.reportDigest || "",
    prompt_version: parts.promptVersion || "",
    code_version: parts.codeVersion || "",
    schema_version: parts.schemaVersion || "",
  });
}

export function validateWorldModelStage(stage) {
  const name = String(stage?.stage || "");
  const status = String(stage?.status || "");
  if (!WORLD_MODEL_STAGES.includes(name)) {
    throw Object.assign(new Error(`Unknown world-model stage: ${name}`), { status: 400, code: "invalid_stage" });
  }
  if (!JOB_STATUSES.has(status)) {
    throw Object.assign(new Error(`Invalid stage status: ${status}`), { status: 400, code: "invalid_stage_status" });
  }
  return true;
}

export function userFromHeaders(headers = {}) {
  const get = (name) => headers[name] || headers[name.toLowerCase()];
  const id = String(get("x-neurico-user") || get("x-forwarded-user") || get("x-auth-request-email") || "").trim().toLowerCase();
  const role = String(get("x-neurico-role") || get("x-forwarded-role") || "participant").trim().toLowerCase();
  return {
    id: id || "anonymous",
    role: ["administrator", "admin"].includes(role) ? "administrator" : role === "researcher" ? "researcher" : "participant",
  };
}

export function canAccessRun(user, runRecord, assignments = []) {
  if (user.role === "administrator") return true;
  if (user.role === "researcher" && runRecord?.researcher_id && runRecord.researcher_id === user.id && runRecord.researcher_access !== false) return true;
  return assignments.some((assignment) =>
    assignment.run_id === runRecord?.run_id &&
    assignment.participant_id === user.id &&
    assignment.status !== "revoked"
  );
}

export function validateAnnotation(annotation = {}) {
  const errors = [];
  for (const field of ["assignment_id", "participant_id", "run_id", "decision_id"]) {
    if (!String(annotation[field] || "").trim()) errors.push(`${field} is required`);
  }
  for (const field of ["reasonableness", "evidence_support", "timing_quality", "alternative_consideration", "outcome_alignment", "confidence"]) {
    const value = annotation[field];
    if (value !== undefined && value !== null && value !== "" && !SCALE_VALUES.has(value)) errors.push(`${field} must be 1-5, not_applicable, or insufficient_evidence`);
  }
  if (annotation.human_intervention && !HUMAN_INTERVENTION_VALUES.has(annotation.human_intervention)) {
    errors.push("human_intervention is invalid");
  }
  const labels = Array.isArray(annotation.failure_labels) ? annotation.failure_labels : [];
  for (const label of labels) {
    if (!FAILURE_LABELS.includes(label)) errors.push(`unknown failure label: ${label}`);
  }
  const refs = Array.isArray(annotation.evidence_refs) ? annotation.evidence_refs : [];
  for (const ref of refs) {
    if (!ref || typeof ref !== "object" || !ref.type || !ref.artifact_id) errors.push("evidence_refs entries require type and artifact_id");
  }
  if (errors.length) {
    throw Object.assign(new Error(errors.join("; ")), { status: 400, code: "invalid_annotation", errors });
  }
  return true;
}
