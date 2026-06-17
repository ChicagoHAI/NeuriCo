"""
AutoResearch support primitives.

This module contains the product-neutral pieces used by the AutoResearch loop:
Git checkpoints for workspace nodes and external attempt history. It does not
run agents or make proposal decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional
import json
import math
import re
import shutil
import tempfile
from datetime import datetime

from core.scorer import load_scoring_results
from core.scoring_seal import seal_scoring_files, unseal_scoring_files

try:
    from git import Repo, InvalidGitRepositoryError, NoSuchPathError
    from git.exc import GitCommandError

    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False


AUTORESEARCH_GIT_USER_NAME = "NeuriCo AutoResearch"
AUTORESEARCH_GIT_USER_EMAIL = "noreply@neurico.dev"

HIDDEN_SCORING_PATTERNS = (
    "scoring/eval.py",
    "scoring/targets.json",
    "scoring/rule_maker_log.md",
    "data/.test/",
    ".scoring_sealed/",
)

AUTORESEARCH_LOG_PATTERNS = ("logs/experiment-autoresearch/",)
AUTORESEARCH_STATE_PATTERNS = (".neurico/autoresearch_state.json",)
AGENT_LOCAL_PATTERNS = (".claude/", ".gemini/", ".codex/")
PAPER_OUTPUT_PATTERNS = (
    "paper/",
    "paper_draft/",
    "templates/paper_writing/",
    "logs/paper_writer_prompt.txt",
    "logs/paper_writer_*.log",
)

CHECKPOINT_EXCLUDE_PATTERNS = (
    HIDDEN_SCORING_PATTERNS
    + AUTORESEARCH_LOG_PATTERNS
    + AUTORESEARCH_STATE_PATTERNS
    + AGENT_LOCAL_PATTERNS
    + PAPER_OUTPUT_PATTERNS
)

COMPARISON_EPS = 1e-6

ProposalGeneratorHook = Callable[
    [Dict[str, Any], Path, str, Path, list[Dict[str, Any]]],
    Any,
]
CommentModeHook = Callable[[Dict[str, Any], Path], Dict[str, Any]]
ScorerHook = Callable[[Path], Dict[str, Any]]


@dataclass(frozen=True)
class Checkpoint:
    """A Git-backed AutoResearch node."""

    sha: str
    message: str

    @property
    def node_id(self) -> str:
        """Node id used in attempt history paths."""
        return self.sha


@dataclass(frozen=True)
class AutoResearchIterationResult:
    """Result for one AutoResearch candidate attempt."""

    iteration: int
    parent_sha: str
    child_sha: Optional[str]
    attempt_dir: Path
    accepted: bool
    reason: str
    proposal: str
    comment_result: Dict[str, Any]
    scorer_result: Dict[str, Any]
    parent_summary: ScoreSummary
    candidate_summary: ScoreSummary


@dataclass(frozen=True)
class AutoResearchRunResult:
    """Summary of an AutoResearch controller run."""

    success: bool
    initial_sha: str
    current_best_sha: str
    iterations: list[AutoResearchIterationResult] = field(default_factory=list)


class CheckpointManager:
    """
    Manages AutoResearch node checkpoints inside a workspace Git repository.

    If the workspace is not already a Git repository, this class initializes a
    local-only repository. It does not create remotes or push.
    """

    def __init__(self, work_dir: Path):
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython is required for AutoResearch checkpoints")

        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.repo = self._open_or_init_repo()
        self._ensure_local_git_identity()
        self._ensure_checkpoint_excludes()

    def _open_or_init_repo(self) -> "Repo":
        try:
            return Repo(self.work_dir)
        except (InvalidGitRepositoryError, NoSuchPathError):
            return Repo.init(self.work_dir)

    def _ensure_local_git_identity(self) -> None:
        with self.repo.config_writer() as config:
            try:
                config.get_value("user", "name")
            except Exception:
                config.set_value("user", "name", AUTORESEARCH_GIT_USER_NAME)
            try:
                config.get_value("user", "email")
            except Exception:
                config.set_value("user", "email", AUTORESEARCH_GIT_USER_EMAIL)

    def _ensure_checkpoint_excludes(self) -> None:
        exclude_path = self.work_dir / ".git" / "info" / "exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)

        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        existing_lines = {line.strip() for line in existing.splitlines()}

        additions = [
            pattern for pattern in CHECKPOINT_EXCLUDE_PATTERNS if pattern not in existing_lines
        ]
        if not additions:
            return

        with exclude_path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            if "# AutoResearch checkpoint excludes" not in existing_lines:
                f.write("\n# AutoResearch checkpoint excludes\n")
            for pattern in additions:
                f.write(f"{pattern}\n")

    @property
    def has_commits(self) -> bool:
        try:
            _ = self.repo.head.commit
            return True
        except ValueError:
            return False

    def create_checkpoint(self, message: str) -> Checkpoint:
        """
        Commit the current public experiment state and return the new node.

        Hidden scoring harness files and AutoResearch controller logs are
        excluded by .git/info/exclude for untracked files and explicitly
        removed from checkpoint commits for existing repositories.
        """
        self.repo.git.add(A=True)

        if self.has_commits:
            self._remove_checkpoint_excludes_from_index()

        if not self._has_staged_changes():
            if not self.has_commits:
                raise RuntimeError(
                    "Cannot create initial AutoResearch checkpoint: "
                    "workspace has no public files to commit"
                )
            head = self.repo.head.commit
            return Checkpoint(sha=head.hexsha, message=message)

        commit = self.repo.index.commit(message)
        return Checkpoint(sha=commit.hexsha, message=message)

    def restore_checkpoint(self, sha: str) -> None:
        """
        Restore tracked workspace files to a checkpoint.

        This intentionally avoids `git clean` so ignored datasets, venvs, and
        other local resources are preserved. AutoResearch controller logs are
        additionally preserved across reset so attempt history remains a
        permanent workspace log, not part of mutable experiment state.
        """
        preserved_paths = self._copy_preserved_paths_to_temp(
            AUTORESEARCH_LOG_PATTERNS + PAPER_OUTPUT_PATTERNS
        )
        try:
            self.repo.git.reset("--hard", sha)
        finally:
            if preserved_paths is not None:
                self._restore_preserved_paths_from_temp(preserved_paths)

    def current_sha(self) -> Optional[str]:
        if not self.has_commits:
            return None
        return self.repo.head.commit.hexsha

    def _remove_checkpoint_excludes_from_index(self) -> None:
        for rel_path in self._checkpoint_excludes_present_or_tracked():
            try:
                self.repo.git.rm("--cached", "--ignore-unmatch", "--", rel_path)
            except GitCommandError:
                pass

    def _checkpoint_excludes_present_or_tracked(self) -> Iterable[str]:
        seen = set()
        for pattern in CHECKPOINT_EXCLUDE_PATTERNS:
            if pattern.endswith("/"):
                root = self.work_dir / pattern.rstrip("/")
                if root.exists():
                    for path in root.rglob("*"):
                        if path.is_file():
                            rel = path.relative_to(self.work_dir).as_posix()
                            seen.add(rel)
                continue
            if (self.work_dir / pattern).exists():
                seen.add(pattern)

        if self.has_commits:
            try:
                tracked = self.repo.git.ls_files(*CHECKPOINT_EXCLUDE_PATTERNS)
                for line in tracked.splitlines():
                    if line.strip():
                        seen.add(line.strip())
            except GitCommandError:
                pass

        return sorted(seen)

    def _has_staged_changes(self) -> bool:
        try:
            self.repo.git.diff("--cached", "--quiet")
            return False
        except GitCommandError as e:
            return e.status == 1

    def _copy_preserved_paths_to_temp(self, patterns: Iterable[str]) -> Optional[Path]:
        temp_parent: Optional[Path] = None
        for rel_path in self._matching_workspace_paths(patterns):
            source = self.work_dir / rel_path
            if not source.exists():
                continue
            if temp_parent is None:
                temp_parent = Path(tempfile.mkdtemp(prefix="neurico-autoresearch-preserve-"))
            target = temp_parent / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif source.is_file():
                shutil.copy2(source, target)
        return temp_parent

    def _restore_preserved_paths_from_temp(self, temp_parent: Path) -> None:
        try:
            for source in sorted(temp_parent.rglob("*")):
                if source.is_dir():
                    continue
                rel_path = source.relative_to(temp_parent)
                target = self.work_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    def _matching_workspace_paths(self, patterns: Iterable[str]) -> list[Path]:
        matches: set[Path] = set()
        for pattern in patterns:
            if pattern.endswith("/"):
                rel_dir = Path(pattern.rstrip("/"))
                if (self.work_dir / rel_dir).exists():
                    matches.add(rel_dir)
                continue
            if "*" in pattern:
                matches.update(
                    path.relative_to(self.work_dir)
                    for path in self.work_dir.glob(pattern)
                    if path.exists()
                )
                continue
            rel_file = Path(pattern)
            if (self.work_dir / rel_file).exists():
                matches.add(rel_file)
        return sorted(matches)


class AttemptHistoryManager:
    """Stores AutoResearch attempt history under a NeuriCo logs directory."""

    def __init__(self, history_root: Path, idea_id: str):
        self.history_root = Path(history_root)
        self.idea_id = idea_id
        self.history_root.mkdir(parents=True, exist_ok=True)

    def next_attempt_dir(self, parent_sha: str) -> Path:
        parent_dir = self.parent_dir(parent_sha)
        existing = [
            self._attempt_number(path.name)
            for path in parent_dir.glob("attempt_*")
            if path.is_dir()
        ]
        next_number = (max(existing) + 1) if existing else 1
        attempt_dir = parent_dir / f"attempt_{next_number}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        return attempt_dir

    def parent_dir(self, parent_sha: str) -> Path:
        node_dir = self.history_root / self._safe_path_component(parent_sha)
        node_dir.mkdir(parents=True, exist_ok=True)
        return node_dir

    def record_attempt(
        self,
        parent_sha: str,
        child_sha: str,
        proposal: str,
        results_path: Path,
        decision: Dict[str, Any],
    ) -> Path:
        attempt_dir = self.next_attempt_dir(parent_sha)
        self.write_proposal(attempt_dir, proposal)
        self.complete_attempt(
            attempt_dir=attempt_dir,
            parent_sha=parent_sha,
            child_sha=child_sha,
            results_path=results_path,
            decision=decision,
        )
        return attempt_dir

    def write_proposal(self, attempt_dir: Path, proposal: str) -> Path:
        """Write the proposal as the first artifact of an attempt record."""
        attempt_dir = Path(attempt_dir)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = attempt_dir / "proposal.md"
        proposal_path.write_text(proposal, encoding="utf-8")
        return proposal_path

    def complete_attempt(
        self,
        attempt_dir: Path,
        parent_sha: str,
        child_sha: str,
        results_path: Path,
        decision: Dict[str, Any],
    ) -> Path:
        """Fill in the post-comment-mode artifacts for an existing attempt."""
        attempt_dir = Path(attempt_dir)
        attempt_dir.mkdir(parents=True, exist_ok=True)

        (attempt_dir / "child_pointer.txt").write_text(f"{child_sha}\n", encoding="utf-8")

        results_path = Path(results_path)
        if results_path.exists():
            shutil.copyfile(results_path, attempt_dir / "results.json")
        else:
            (attempt_dir / "results.json").write_text(
                json.dumps({"error": "results.json missing"}, indent=2),
                encoding="utf-8",
            )

        decision_payload = dict(decision)
        decision_payload.setdefault("parent_sha", parent_sha)
        decision_payload.setdefault("child_sha", child_sha)
        (attempt_dir / "decision.json").write_text(
            json.dumps(decision_payload, indent=2),
            encoding="utf-8",
        )
        return attempt_dir

    def list_attempts(self, parent_sha: str) -> list[Path]:
        parent_dir = self.parent_dir(parent_sha)
        return sorted(
            [path for path in parent_dir.glob("attempt_*") if path.is_dir()],
            key=lambda path: self._attempt_number(path.name),
        )

    def load_attempt_summaries(self, parent_sha: str) -> list[Dict[str, Any]]:
        summaries = []
        for attempt_dir in self.list_attempts(parent_sha):
            decision_path = attempt_dir / "decision.json"
            proposal_path = attempt_dir / "proposal.md"
            child_path = attempt_dir / "child_pointer.txt"

            decision: Dict[str, Any] = {}
            if decision_path.exists():
                try:
                    decision = json.loads(decision_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    decision = {"error": "invalid decision.json"}

            summaries.append(
                {
                    "attempt_dir": str(attempt_dir),
                    "proposal": proposal_path.read_text(encoding="utf-8")
                    if proposal_path.exists()
                    else "",
                    "child_sha": child_path.read_text(encoding="utf-8").strip()
                    if child_path.exists()
                    else "",
                    "decision": decision,
                }
            )
        return summaries

    @staticmethod
    def _attempt_number(name: str) -> int:
        match = re.fullmatch(r"attempt_(\d+)", name)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _safe_path_component(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
        return safe or "unknown"


@dataclass(frozen=True)
class ScoreSummary:
    """Normalized view of a scoring/results.json payload."""

    valid: bool
    source: str
    properties: Optional[Dict[str, Dict[str, Any]]] = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "source": self.source,
            "properties": self.properties,
            "error": self.error,
        }


@dataclass(frozen=True)
class ComparisonDecision:
    """Deterministic accept/reject decision for a candidate scoring result."""

    accepted: bool
    reason: str
    parent_summary: ScoreSummary
    candidate_summary: ScoreSummary


class ScoringResultComparator:
    """Compares AutoResearch parent/candidate scorer outputs."""

    def compare_files(
        self,
        parent_results_path: Path,
        candidate_results_path: Path,
    ) -> ComparisonDecision:
        parent = self.load_summary(parent_results_path, source="parent")
        candidate = self.load_summary(candidate_results_path, source="candidate")
        return self.compare(parent, candidate)

    def compare(
        self,
        parent: ScoreSummary,
        candidate: ScoreSummary,
    ) -> ComparisonDecision:
        if not candidate.valid:
            return ComparisonDecision(
                accepted=False,
                reason=f"Candidate scoring result is invalid: {candidate.error}",
                parent_summary=parent,
                candidate_summary=candidate,
            )

        if candidate.properties is None:
            return ComparisonDecision(
                accepted=False,
                reason="Candidate scoring result has no comparable properties.",
                parent_summary=parent,
                candidate_summary=candidate,
            )

        if parent.properties is None:
            return ComparisonDecision(
                accepted=False,
                reason="Parent scoring result has no comparable properties.",
                parent_summary=parent,
                candidate_summary=candidate,
            )

        return self._compare_properties(parent, candidate)

    def _compare_properties(
        self,
        parent: ScoreSummary,
        candidate: ScoreSummary,
    ) -> ComparisonDecision:
        assert parent.properties is not None
        assert candidate.properties is not None

        if not candidate.properties:
            return ComparisonDecision(
                accepted=False,
                reason="Candidate scoring result has no comparable properties.",
                parent_summary=parent,
                candidate_summary=candidate,
            )

        parent_keys = set(parent.properties)
        candidate_keys = set(candidate.properties)
        if parent_keys != candidate_keys:
            return ComparisonDecision(
                accepted=False,
                reason="Parent and candidate scoring properties do not match.",
                parent_summary=parent,
                candidate_summary=candidate,
            )

        for name in sorted(candidate_keys):
            parent_prop = parent.properties[name]
            candidate_prop = candidate.properties[name]
            if parent_prop["direction"] != candidate_prop["direction"]:
                return ComparisonDecision(
                    accepted=False,
                    reason=f"Scoring property direction changed for {name}.",
                    parent_summary=parent,
                    candidate_summary=candidate,
                )
            if abs(parent_prop["target"] - candidate_prop["target"]) > COMPARISON_EPS:
                return ComparisonDecision(
                    accepted=False,
                    reason=f"Scoring property target changed for {name}.",
                    parent_summary=parent,
                    candidate_summary=candidate,
                )

        parent_satisfied = {name for name, prop in parent.properties.items() if prop["satisfied"]}
        candidate_satisfied = {
            name for name, prop in candidate.properties.items() if prop["satisfied"]
        }
        lost_satisfied = sorted(parent_satisfied - candidate_satisfied)
        gained_satisfied = sorted(candidate_satisfied - parent_satisfied)

        if lost_satisfied:
            return ComparisonDecision(
                accepted=False,
                reason=(
                    "Candidate loses previously satisfied scoring properties: "
                    f"{', '.join(lost_satisfied)}."
                ),
                parent_summary=parent,
                candidate_summary=candidate,
            )

        if gained_satisfied:
            return ComparisonDecision(
                accepted=True,
                reason=(
                    "Candidate satisfies a strict superset of parent scoring "
                    f"properties: {', '.join(gained_satisfied)}."
                ),
                parent_summary=parent,
                candidate_summary=candidate,
            )

        improved_properties = []
        for name in sorted(candidate_keys):
            parent_prop = parent.properties[name]
            candidate_prop = candidate.properties[name]
            parent_margin = parent_prop["margin"]
            candidate_margin = candidate_prop["margin"]
            if candidate_margin < parent_margin - COMPARISON_EPS:
                return ComparisonDecision(
                    accepted=False,
                    reason=f"Candidate regressed normalized margin for scoring property {name}.",
                    parent_summary=parent,
                    candidate_summary=candidate,
                )
            if candidate_margin > parent_margin + COMPARISON_EPS:
                improved_properties.append(name)

        if improved_properties:
            return ComparisonDecision(
                accepted=True,
                reason=(
                    "Candidate keeps the same satisfied-property set, has no metric "
                    "normalized-margin regressions, and improves "
                    f"{', '.join(improved_properties)}."
                ),
                parent_summary=parent,
                candidate_summary=candidate,
            )

        return ComparisonDecision(
            accepted=False,
            reason=(
                "Candidate keeps the same satisfied-property set but does not improve any metric."
            ),
            parent_summary=parent,
            candidate_summary=candidate,
        )

    def load_summary(self, results_path: Path, source: str = "results") -> ScoreSummary:
        results_path = Path(results_path)
        payload = self._load_results_payload(results_path)
        if payload is not None:
            return self.summarize(payload, source=source)

        if not results_path.exists():
            return ScoreSummary(
                valid=False,
                source=source,
                error=f"results.json not found at {results_path}",
            )

        try:
            payload = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return ScoreSummary(
                valid=False,
                source=source,
                error=f"results.json is not valid JSON: {e}",
            )

        return self.summarize(payload, source=source)

    @staticmethod
    def _load_results_payload(results_path: Path) -> Optional[Dict[str, Any]]:
        if results_path.name == "results.json" and results_path.parent.name == "scoring":
            return load_scoring_results(results_path.parent.parent)
        return None

    def summarize(self, payload: Dict[str, Any], source: str = "results") -> ScoreSummary:
        if not isinstance(payload, dict):
            return ScoreSummary(
                valid=False, source=source, error="results payload is not an object"
            )

        properties = payload.get("properties")
        if isinstance(properties, dict):
            try:
                comparable_properties = {}
                for name, prop in properties.items():
                    if not isinstance(name, str):
                        raise ValueError("property name is not a string")
                    if not isinstance(prop, dict):
                        raise ValueError("property record is not an object")
                    comparable_prop = self._normalize_property(prop)
                    comparable_properties[name] = comparable_prop
                return ScoreSummary(
                    valid=True,
                    source=source,
                    properties=comparable_properties,
                )
            except (KeyError, TypeError, ValueError) as e:
                return ScoreSummary(
                    valid=False,
                    source=source,
                    error=f"invalid properties schema: {e}",
                )

        return ScoreSummary(
            valid=False,
            source=source,
            error="results payload has no properties",
        )

    @staticmethod
    def _finite_float(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} is not numeric")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{field_name} is not numeric") from e
        if not math.isfinite(numeric):
            raise ValueError(f"{field_name} is not finite")
        return numeric

    @classmethod
    def _normalize_property(cls, prop: Dict[str, Any]) -> Dict[str, Any]:
        direction = prop["direction"]
        if direction not in {"max", "min"}:
            raise ValueError(f"Unknown direction: {direction}")
        value = cls._finite_float(prop["value"], "value")
        target = cls._finite_float(prop["target"], "target")
        satisfied = prop["satisfied"]
        if not isinstance(satisfied, bool):
            raise ValueError("satisfied is not boolean")
        normalized = {
            "value": value,
            "target": target,
            "direction": direction,
        }
        return {
            "value": value,
            "target": target,
            "direction": direction,
            "satisfied": satisfied,
            "margin": normalized_margin(normalized),
        }


class AutoResearchController:
    """
    Runs the experiment-stage AutoResearch loop.

    The controller is intentionally thin: proposal generation, comment-mode
    modification, and scoring are injected callables. Phase 5 wires those
    callables to NeuriCo's existing agents; Phase 4 tests use fakes.
    """

    def __init__(
        self,
        idea: Dict[str, Any],
        idea_id: str,
        work_dir: Path,
        history_root: Path,
        proposal_generator: ProposalGeneratorHook,
        comment_mode: CommentModeHook,
        scorer: ScorerHook,
        checkpoint_manager: Optional[CheckpointManager] = None,
        history_manager: Optional[AttemptHistoryManager] = None,
        comparator: Optional[ScoringResultComparator] = None,
    ):
        self.idea = idea
        self.idea_id = idea_id
        self.work_dir = Path(work_dir)
        self.checkpoints = checkpoint_manager or CheckpointManager(self.work_dir)
        self.history = history_manager or AttemptHistoryManager(history_root, idea_id)
        self.comparator = comparator or ScoringResultComparator()
        self.proposal_generator = proposal_generator
        self.comment_mode = comment_mode
        self.scorer = scorer

    def run(self, iterations: int) -> AutoResearchRunResult:
        """
        Execute AutoResearch iterations from the current scored workspace state.

        The initial checkpoint is created from the already-scored public state.
        Each candidate checkpoint is created only after the scorer writes that
        candidate's own scoring/results.json.
        """
        if iterations < 0:
            raise ValueError("iterations must be non-negative")

        self._ensure_results_json("initial")
        initial = self.checkpoints.create_checkpoint("AutoResearch initial public scored state")
        current_best_sha = initial.sha
        iteration_results: list[AutoResearchIterationResult] = []

        for iteration in range(1, iterations + 1):
            result = self.run_iteration(iteration, current_best_sha)
            iteration_results.append(result)
            if result.accepted and result.child_sha:
                current_best_sha = result.child_sha

        self.checkpoints.restore_checkpoint(current_best_sha)
        return AutoResearchRunResult(
            success=True,
            initial_sha=initial.sha,
            current_best_sha=current_best_sha,
            iterations=iteration_results,
        )

    def run_iteration(
        self,
        iteration: int,
        parent_sha: str,
    ) -> AutoResearchIterationResult:
        """Run one proposal/comment/scorer/checkpoint/compare attempt."""
        self.checkpoints.restore_checkpoint(parent_sha)
        parent_results_path = self.work_dir / "scoring" / "results.json"
        parent_summary = self.comparator.load_summary(
            parent_results_path,
            source="parent",
        )

        attempt_history = self.history.load_attempt_summaries(parent_sha)
        attempt_dir = self.history.next_attempt_dir(parent_sha)

        sealed_dir = seal_scoring_files(self.work_dir)
        proposal = ""
        comment_result: Dict[str, Any] = {}
        pre_scoring_error: Optional[str] = None
        try:
            try:
                proposal_result = self.proposal_generator(
                    self.idea,
                    self.work_dir,
                    parent_sha,
                    attempt_dir,
                    attempt_history,
                )
                proposal = self._resolve_proposal_text(attempt_dir, proposal_result)
                self.history.write_proposal(attempt_dir, proposal)

                comment_idea = self._idea_with_comments(proposal)
                comment_result = self.comment_mode(comment_idea, self.work_dir)
            except Exception as e:
                pre_scoring_error = str(e)
                comment_result = {
                    "success": False,
                    "error": f"AutoResearch proposal/comment stage failed: {e}",
                }
        finally:
            unseal_scoring_files(self.work_dir, sealed_dir)

        if pre_scoring_error is not None:
            candidate_summary = ScoreSummary(
                valid=False,
                source="candidate",
                error=f"AutoResearch proposal/comment stage failed: {pre_scoring_error}",
            )
            decision_payload = {
                "parent_node_id": parent_sha,
                "parent_sha": parent_sha,
                "child_node_id": None,
                "child_sha": None,
                "accepted": False,
                "reason": candidate_summary.error,
                "parent_score_summary": parent_summary.as_dict(),
                "child_score_summary": candidate_summary.as_dict(),
                "comment_result": comment_result,
                "scorer_result": {},
            }
            self._record_failed_before_checkpoint(
                attempt_dir=attempt_dir,
                parent_sha=parent_sha,
                results_path=self.work_dir / "scoring" / "results.json",
                decision=decision_payload,
                failure_results={
                    "overall_satisfied": False,
                    "error": candidate_summary.error,
                    "generated_by": "autoresearch",
                    "created_at": datetime.now().isoformat(),
                },
            )
            self.checkpoints.restore_checkpoint(parent_sha)
            return AutoResearchIterationResult(
                iteration=iteration,
                parent_sha=parent_sha,
                child_sha=None,
                attempt_dir=attempt_dir,
                accepted=False,
                reason=candidate_summary.error,
                proposal=proposal,
                comment_result=comment_result,
                scorer_result={},
                parent_summary=parent_summary,
                candidate_summary=candidate_summary,
            )

        self._clear_stale_results_json()
        try:
            scorer_result = self.scorer(self.work_dir)
        except Exception as e:
            scorer_result = {
                "success": False,
                "error": f"AutoResearch scorer raised an exception: {e}",
            }
        results_path = self._ensure_results_json(
            stage="candidate",
            scorer_result=scorer_result,
        )

        candidate_checkpoint: Optional[Checkpoint] = None
        child_sha: Optional[str] = None
        checkpoint_error: Optional[str] = None
        try:
            candidate_checkpoint = self.checkpoints.create_checkpoint(
                f"AutoResearch candidate iteration {iteration}"
            )
            child_sha = candidate_checkpoint.sha
        except Exception as e:
            checkpoint_error = str(e)

        candidate_summary = self.comparator.load_summary(
            results_path,
            source="candidate",
        )
        decision = self.comparator.compare(parent_summary, candidate_summary)
        accepted = decision.accepted and child_sha is not None
        reason = decision.reason
        if checkpoint_error:
            accepted = False
            reason = f"Candidate could not be checkpointed: {checkpoint_error}"

        decision_payload = {
            "parent_node_id": parent_sha,
            "parent_sha": parent_sha,
            "child_node_id": child_sha,
            "child_sha": child_sha,
            "accepted": accepted,
            "reason": reason,
            "parent_score_summary": parent_summary.as_dict(),
            "child_score_summary": candidate_summary.as_dict(),
            "comment_result": comment_result,
            "scorer_result": scorer_result,
        }

        if child_sha:
            self.history.complete_attempt(
                attempt_dir=attempt_dir,
                parent_sha=parent_sha,
                child_sha=child_sha,
                results_path=results_path,
                decision=decision_payload,
            )
        else:
            self._record_failed_before_checkpoint(
                attempt_dir=attempt_dir,
                parent_sha=parent_sha,
                results_path=results_path,
                decision=decision_payload,
            )

        if not accepted:
            self.checkpoints.restore_checkpoint(parent_sha)

        return AutoResearchIterationResult(
            iteration=iteration,
            parent_sha=parent_sha,
            child_sha=child_sha,
            attempt_dir=attempt_dir,
            accepted=accepted,
            reason=reason,
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
        )

    def _ensure_results_json(
        self,
        stage: str,
        scorer_result: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Ensure a public scoring/results.json exists for node traceability.

        If the scorer fails before producing results.json, write a small public
        failure payload so the candidate state can still be checkpointed.
        """
        results_path = self.work_dir / "scoring" / "results.json"
        if results_path.exists():
            return results_path

        results_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "overall_satisfied": False,
            "error": f"AutoResearch {stage} scorer did not produce scoring/results.json",
            "scorer_result": scorer_result or {},
            "generated_by": "autoresearch",
            "created_at": datetime.now().isoformat(),
        }
        results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return results_path

    @staticmethod
    def _resolve_proposal_text(attempt_dir: Path, proposal_result: Any) -> str:
        proposal_path = Path(attempt_dir) / "proposal.md"
        if isinstance(proposal_result, str):
            return proposal_result
        if isinstance(proposal_result, dict):
            if isinstance(proposal_result.get("proposal"), str):
                return proposal_result["proposal"]
            path_value = proposal_result.get("proposal_path")
            if path_value and Path(path_value).exists():
                return Path(path_value).read_text(encoding="utf-8")
        if proposal_path.exists():
            return proposal_path.read_text(encoding="utf-8")
        raise RuntimeError("Proposal generator did not return or write proposal.md")

    def _idea_with_comments(self, proposal: str) -> Dict[str, Any]:
        idea_copy = json.loads(json.dumps(self.idea, default=str))
        idea_spec = idea_copy.setdefault("idea", {})
        idea_spec["comments"] = proposal
        return idea_copy

    def _clear_stale_results_json(self) -> None:
        results_path = self.work_dir / "scoring" / "results.json"
        if results_path.exists():
            results_path.unlink()

    def _record_failed_before_checkpoint(
        self,
        attempt_dir: Path,
        parent_sha: str,
        results_path: Path,
        decision: Dict[str, Any],
        failure_results: Optional[Dict[str, Any]] = None,
    ) -> None:
        attempt_dir = Path(attempt_dir)
        (attempt_dir / "child_pointer.txt").write_text("", encoding="utf-8")
        results_path = Path(results_path)
        if failure_results is not None:
            (attempt_dir / "results.json").write_text(
                json.dumps(failure_results, indent=2),
                encoding="utf-8",
            )
        elif results_path.exists():
            shutil.copyfile(results_path, attempt_dir / "results.json")
        else:
            (attempt_dir / "results.json").write_text(
                json.dumps({"error": "results.json missing"}, indent=2),
                encoding="utf-8",
            )
        decision_payload = dict(decision)
        decision_payload.setdefault("parent_sha", parent_sha)
        decision_payload.setdefault("child_sha", None)
        (attempt_dir / "decision.json").write_text(
            json.dumps(decision_payload, indent=2),
            encoding="utf-8",
        )


def run_autoresearch_loop(
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    history_root: Path,
    iterations: int,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    full_permissions: bool = True,
    proposal_timeout: int = 900,
    comment_timeout: int = 1800,
    scorer_timeout: int = 600,
) -> AutoResearchRunResult:
    """
    Run AutoResearch with NeuriCo's real proposer, comment handler, and scorer.

    This is the production integration point used by runner.py in Phase 6.
    """
    from agents.autoresearch_proposer import run_autoresearch_proposer
    from agents.comment_handler import run_comment_handler
    from core.scorer import run_scorer

    work_dir = Path(work_dir)
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    def proposal_generator(
        idea_payload: Dict[str, Any],
        proposal_work_dir: Path,
        parent_sha: str,
        attempt_dir: Path,
        attempt_history: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return run_autoresearch_proposer(
            idea=idea_payload,
            work_dir=proposal_work_dir,
            parent_sha=parent_sha,
            attempt_dir=attempt_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=proposal_timeout,
            full_permissions=full_permissions,
            attempt_history=attempt_history,
        )

    def comment_mode(comment_idea: Dict[str, Any], comment_work_dir: Path) -> Dict[str, Any]:
        return run_comment_handler(
            idea=comment_idea,
            work_dir=comment_work_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=comment_timeout,
            full_permissions=full_permissions,
        )

    def scorer(score_work_dir: Path) -> Dict[str, Any]:
        return run_scorer(
            work_dir=score_work_dir,
            timeout=scorer_timeout,
        )

    controller = AutoResearchController(
        idea=idea,
        idea_id=idea_id,
        work_dir=work_dir,
        history_root=history_root,
        proposal_generator=proposal_generator,
        comment_mode=comment_mode,
        scorer=scorer,
    )
    return controller.run(iterations=iterations)


def normalized_margin(prop: Dict[str, Any]) -> float:
    """
    Relative target margin for one scorer property.

    For max properties the margin is (value - target) / max(abs(target), 1).
    For min properties the margin is (target - value) / max(abs(target), 1).
    Higher margin is better.
    """
    value = ScoringResultComparator._finite_float(prop["value"], "value")
    target = ScoringResultComparator._finite_float(prop["target"], "target")
    direction = prop["direction"]
    denom = max(abs(target), 1.0)
    if direction == "max":
        return (value - target) / denom
    if direction == "min":
        return (target - value) / denom
    raise ValueError(f"Unknown direction: {direction}")
