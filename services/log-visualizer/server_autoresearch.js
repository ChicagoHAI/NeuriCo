import { readdir, stat } from "node:fs/promises";
import path from "node:path";

const AR_HISTORY_ROOT_REL = path.join("logs", "experiment-autoresearch");
const AR_MAX_ATTEMPTS_PER_PARENT = 200;

export function autoresearchReader({ safeRunPath, exists, readJson }) {
  async function readAutoResearchState(run) {
    const state = await readJson(".neurico/autoresearch_state.json", null, run);
    if (!state) return null;
    if (!(await exists(AR_HISTORY_ROOT_REL, run))) return null;

    const parents = await listParentDirs(run);
    const attempts = [];
    for (const parentDirname of parents) {
      const parentSha = parentDirname;
      const attemptNames = await listAttemptDirs(run, parentDirname);
      for (const attemptName of attemptNames) {
        const attempt = await readAttempt(run, parentSha, parentDirname, attemptName);
        if (attempt) attempts.push(attempt);
      }
    }

    const initialSha = state.lineage_source_sha || null;
    attempts.sort(compareAttempts(attempts, initialSha));
    const whiteboard = summarizeWhiteboard(
      await readJson(path.join(AR_HISTORY_ROOT_REL, "whiteboard.json"), null, run)
    );

    return {
      detected: true,
      initialSha,
      currentBestSha: state.current_best_sha || null,
      lastIteration: state.last_iteration ?? attempts.length,
      updatedAt: state.updated_at || null,
      historyRootRel: AR_HISTORY_ROOT_REL,
      attempts,
      whiteboard,
    };
  }

  async function listParentDirs(run) {
    try {
      const root = safeRunPath(AR_HISTORY_ROOT_REL, run);
      const entries = await readdir(root, { withFileTypes: true });
      return entries
        .filter((e) => e.isDirectory() && /^[A-Za-z0-9_.-]+$/.test(e.name))
        .map((e) => e.name);
    } catch {
      return [];
    }
  }

  async function listAttemptDirs(run, parentDirname) {
    try {
      const parentRel = path.join(AR_HISTORY_ROOT_REL, parentDirname);
      const entries = await readdir(safeRunPath(parentRel, run), { withFileTypes: true });
      return entries
        .filter((e) => e.isDirectory() && /^attempt_\d+$/.test(e.name))
        .map((e) => e.name)
        .sort((a, b) => attemptNumber(a) - attemptNumber(b))
        .slice(0, AR_MAX_ATTEMPTS_PER_PARENT);
    } catch {
      return [];
    }
  }

  async function readAttempt(run, parentSha, parentDirname, attemptName) {
    const attemptRel = path.join(AR_HISTORY_ROOT_REL, parentDirname, attemptName);
    const decisionRel = path.join(attemptRel, "decision.json");
    const decision = await readJson(decisionRel, null, run);
    if (!decision) return null;
    const proposalRel = path.join(attemptRel, "proposal.md");
    const resultsRel = path.join(attemptRel, "results.json");
    const snapshotRel = path.join(attemptRel, "whiteboard_snapshot.json");
    const transcriptRel = await findFirstTranscript(run, attemptRel);
    const scoreDeltas = computeScoreDeltas(decision.parent_score_summary, decision.child_score_summary);

    let mtime = 0;
    try {
      mtime = (await stat(safeRunPath(decisionRel, run))).mtimeMs;
    } catch {
      // Keep deterministic per-parent ordering even if mtime cannot be read.
    }

    return {
      parentSha,
      attemptNumber: attemptNumber(attemptName),
      attemptDirRel: attemptRel,
      childSha: decision.child_sha || null,
      accepted: Boolean(decision.accepted),
      reason: decision.reason || "",
      scoreDeltas,
      artifacts: {
        proposal: (await exists(proposalRel, run)) ? proposalRel : null,
        decision: decisionRel,
        results: (await exists(resultsRel, run)) ? resultsRel : null,
        whiteboardSnapshot: (await exists(snapshotRel, run)) ? snapshotRel : null,
        transcript: transcriptRel,
      },
      mtime,
    };
  }

  async function findFirstTranscript(run, attemptRel) {
    try {
      const entries = await readdir(safeRunPath(attemptRel, run), { withFileTypes: true });
      const hits = entries
        .filter((e) => e.isFile() && /_transcript\.jsonl$/.test(e.name))
        .map((e) => e.name)
        .sort();
      return hits.length ? path.join(attemptRel, hits[0]) : null;
    } catch {
      return null;
    }
  }

  return { readAutoResearchState };
}

function attemptNumber(name) {
  const match = /^attempt_(\d+)$/.exec(name);
  return match ? parseInt(match[1], 10) : 0;
}

function computeScoreDeltas(parentSummary, childSummary) {
  const parent = parentSummary?.properties || {};
  const child = childSummary?.properties || {};
  const keys = new Set([...Object.keys(parent), ...Object.keys(child)]);
  const out = [];
  for (const key of keys) {
    const p = parent[key] || {};
    const c = child[key] || {};
    out.push({
      property: key,
      direction: p.direction || c.direction || null,
      target: p.target ?? c.target ?? null,
      parentValue: p.value ?? null,
      childValue: c.value ?? null,
      parentSatisfied: p.satisfied ?? null,
      childSatisfied: c.satisfied ?? null,
    });
  }
  out.sort((a, b) => a.property.localeCompare(b.property));
  return out;
}

function compareAttempts(attempts, initialSha) {
  const parentByAccepted = new Map();
  for (const a of attempts) {
    if (a.accepted && a.childSha) parentByAccepted.set(a.parentSha, a.childSha);
  }
  const chainOrder = new Map();
  let sha = initialSha;
  let idx = 0;
  const guard = new Set();
  while (sha && !guard.has(sha)) {
    chainOrder.set(sha, idx++);
    guard.add(sha);
    sha = parentByAccepted.get(sha) || null;
  }

  const parentMtimes = new Map();
  for (const a of attempts) {
    const cur = parentMtimes.get(a.parentSha);
    if (cur === undefined || a.mtime < cur) parentMtimes.set(a.parentSha, a.mtime);
  }
  const offchainBase = attempts.length + 1000000;

  return (a, b) => {
    const aChain = chainOrder.has(a.parentSha);
    const bChain = chainOrder.has(b.parentSha);
    const aRank = aChain ? chainOrder.get(a.parentSha) : offchainBase + (parentMtimes.get(a.parentSha) || 0);
    const bRank = bChain ? chainOrder.get(b.parentSha) : offchainBase + (parentMtimes.get(b.parentSha) || 0);
    if (aRank !== bRank) return aRank - bRank;
    if (a.accepted !== b.accepted) return a.accepted ? 1 : -1;
    return a.attemptNumber - b.attemptNumber;
  };
}

function summarizeWhiteboard(raw) {
  if (!raw || !Array.isArray(raw.tips)) return null;
  const active = [];
  const cleared = [];
  const pruned = [];
  for (const t of raw.tips) {
    const bucket = t.status === "cleared" ? cleared : t.status === "pruned" ? pruned : active;
    bucket.push(t);
  }
  return {
    schemaVersion: raw.schema_version ?? null,
    savedAt: raw.saved_at ?? null,
    counts: { active: active.length, cleared: cleared.length, pruned: pruned.length },
    activeTips: active,
    clearedTips: cleared,
    prunedTips: pruned,
  };
}
