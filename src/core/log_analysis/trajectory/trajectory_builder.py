from pathlib import Path
from typing import Iterable

from core.log_analysis.models import (
    ArtifactRecord,
    FailureRecord,
    RunTrajectory,
    TaskSpec,
    TrajectoryStep,
)
from core.log_analysis.parser.event_normalizer import normalize_event


def build_trajectory(
    repo,
    task: TaskSpec | None,
    raw_events: Iterable,
) -> RunTrajectory:
    """
    Build one structured trajectory from a run/repo bundle and raw transcript events.

    Phase 1 responsibilities:
    - normalize raw transcript rows into trajectory steps
    - assign stable step_index
    - infer coarse stage and phase labels
    - collect observed artifacts
    - infer a rough run status

    This should not do deep quality evaluation yet. Pattern detection and artifact
    validation belong to later phases.
    """
    steps: list[TrajectoryStep] = []
    failures: list[FailureRecord] = []

    for raw_event in raw_events:
        normalized_steps, normalized_failures = normalize_event(raw_event)
        steps.extend(normalized_steps)
        failures.extend(normalized_failures)

    # Stable order: source file then line number.
    # This works for transcript JSONL files where line order is the event order.
    steps.sort(key=lambda s: (s.source_file or "", s.line_no or 0))

    for idx, step in enumerate(steps, start=1):
        step.step_index = idx
        step.stage = step.stage or infer_stage(step.source_file or "")
        step.phase = step.phase or infer_phase(step)

    artifacts = collect_artifacts(repo, steps)
    status = infer_run_status(steps, failures, artifacts)

    return RunTrajectory(
        run_id=repo.run_id,
        title_slug=getattr(repo, "title_slug", repo.run_id),
        root_dir=repo.root_dir,
        task=task,
        steps=steps,
        artifacts=artifacts,
        failures=failures,
        status=status,
    )


def infer_stage(source_file: str) -> str | None:
    """
    Infer coarse pipeline stage from source filename.

    This is intentionally filename-based for Phase 1 because the run folders
    already contain stage-specific transcript names.
    """
    name = source_file.lower()

    if "resource_finder" in name:
        return "resource_finder"

    if "execution" in name or "research" in name:
        return "experiment_runner"

    if "paper_writer" in name:
        return "paper_writer"

    return None


# Phase inference is intentionally heuristic in Phase 1.
# We infer coarse phases from commands/messages/file paths so the visualizer can
# group long trajectories into readable sections. This is not a scientific
# judgment yet; later phases can add a stronger phase detector.
def infer_phase(step: TrajectoryStep) -> str | None:
    text = " ".join(
        value
        for value in [
            step.message,
            step.command,
            step.output_text,
            step.file_path,
        ]
        if value
    ).lower()

    if (
        text.strip() in {"pwd", "/bin/bash -lc pwd"}
        or "rg --files" in text
        or "git status" in text
        or "ls -la" in text
        or "find ." in text
        or "date -iseconds" in text
        or "date -i" in text
    ):
        return "workspace_check"
    
    if not text:
        return None

    # Prompt/context loading at the beginning of a transcript.
    if "reading prompt from stdin" in text:
        return "prompt_read"

    # Agent/system skill inspection. These are not research artifacts; they are
    # capability/context review steps before the agent acts.
    if (
        ".codex/skills/" in text
        or ".claude/skills/" in text
        or "skill.md" in text
        or "/skills/" in text
    ):
        return "capability_review"

    # Workspace/project checks. These reduce empty phases for shell bookkeeping.
    if (
        text.strip() in {"pwd", "/bin/bash -lc pwd"}
        or "rg --files" in text
        or "git status" in text
        or "ls -la" in text
        or "find ." in text
        or "date -iseconds" in text
        or "cat .resource_finder_complete" in text
    ):
        return "workspace_check"

    # Resource-finder setup / collection actions.
    if (
        "mkdir -p papers datasets code" in text
        or "paper-finder" in text
        or "download every paper" in text
        or "paper-finder returned" in text
        or "ranked papers" in text
        or "selected set" in text
        or "relevance" in text
        or "download" in text and "paper" in text
    ):
        return "resource_collection"

    # Resource-finder waiting/progress messages.
    if (
        "still waiting on paper-finder" in text
        or "local paper-finder call is still running" in text
        or "expected diligent-search latency" in text
        or "query remains active" in text
    ):
        return "resource_collection"

    # Experiment execution / smoke runs / model loading.
    if (
        "smoke test" in text
        or "smoke run" in text
        or "model download" in text
        or "checkpoint" in text
        or "loading the qwen" in text
        or "main experiment finished" in text
        or "token-level kl" in text
        or "real model logits" in text
        or "python src/run_" in text
        or "run_divergence_experiment.py" in text
        or "--examples-per-source" in text
        or "--batch-size" in text
        or "--bootstrap-iterations" in text
    ):
        return "experimentation"

    # Result inspection / comparison / metrics analysis.
    if (
        "structured comparison" in text
        or "predictor metrics" in text
        or "row count" in text
        or "results/" in text
        or "figures/" in text
        or "summary.json" in text
        or "metrics" in text
    ):
        return "analysis"

    # Documentation-writing progress messages and final docs.
    if (
        "readme" in text
        or "report.md" in text
        or "code walkthrough" in text
        or "code_walkthrough.md" in text
        or "final readme" in text
        or "final report" in text
        or "execution note" in text
    ):
        return "documentation"

    # Todo updates usually represent planning/checkpoint management.
    if step.event_type == "todo_update":
        return "planning"
    
    if text.strip() in {"pwd", "/bin/bash -lc pwd"} or " pwd" in text:
        return "workspace_check"

    if "rg --files" in text or "ls " in text or "find " in text:
        return "workspace_check"

    if "nvidia-smi" in text or "cuda" in text or "gpu" in text:
        return "environment_setup"

    if "sed -n" in text and (
        "literature_review.md" in text
        or "resources.md" in text
        or "readme.md" in text
        or "dataset_summary.json" in text
    ):
        return "resource_review"

    if any(
        marker in text
        for marker in [
            "literature_review.md",
            "resources.md",
            "datasets/readme.md",
            "code/readme.md",
            "papers/",
            "datasets/",
            "code/",
            "dataset_summary.json",
        ]
    ):
        return "resource_review"

    if "planning.md" in text or "motivation" in text or "novelty" in text:
        return "planning"


    if (
        "python src/run_" in text
        or "run_divergence_experiment.py" in text
        or "run_experiment" in text
        or "--examples-per-source" in text
        or "--batch-size" in text
        or "--bootstrap-iterations" in text
    ):
        return "experimentation"
    
    if (
        "python src/" in text
        or "python -m" in text
        or "python ./" in text
        or "run_" in text
        or "src/" in text
    ):
        return "implementation"


    if "python - <<'py'" in text or 'python - <<"' in text:
        if any(marker in text for marker in ["pandas", "json", "results/", "figures/", "summary"]):
            return "analysis"
        return "implementation"


    if (
        "uv add" in text
        or "pip install" in text
        or "pyproject.toml" in text
        or "python --version" in text
        or "uv --version" in text
        or "py_compile" in text
        or "test -d .venv" in text
    ):
        return "environment_setup"

    if (
        "results/" in text
        or "analysis" in text
        or "figure" in text
        or "figures/" in text
        or ".csv" in text
        or ".json" in text
    ):
        return "analysis"

    if "report.md" in text or "readme.md" in text or "paper_draft" in text or ".tex" in text:
        return "documentation"

    if "validation" in text or "reproduce" in text or "reproducibility" in text:
        return "validation"

    return None


def collect_artifacts(repo, steps: list[TrajectoryStep]) -> list[ArtifactRecord]:
    """
    Collect artifacts from two sources:
    1. Files that exist under the run folder.
    2. File paths mentioned by file_change trajectory steps.

    Phase 1 records observed artifacts only. It does not yet judge whether they
    are complete or scientifically valid.
    """
    artifacts: dict[str, ArtifactRecord] = {}

    for path in getattr(repo, "artifact_files", []):
        path = Path(path)

        try:
            rel = path.relative_to(repo.root_dir)
            artifact_path = str(rel)
        except ValueError:
            artifact_path = str(path)

        artifacts[artifact_path] = ArtifactRecord(
            run_id=repo.run_id,
            artifact_path=artifact_path,
            artifact_type=infer_artifact_type(path),
            exists_on_disk=path.exists(),
            size_bytes=path.stat().st_size if path.exists() and path.is_file() else None,
        )

    for step in steps:
        if not step.file_path:
            continue

        if step.file_path not in artifacts:
            artifacts[step.file_path] = ArtifactRecord(
                run_id=repo.run_id,
                artifact_path=step.file_path,
                artifact_type=infer_artifact_type(Path(step.file_path)),
                source_file=step.source_file,
                created_by_step_index=step.step_index,
                exists_on_disk=None,
                size_bytes=None,
            )

    return list(artifacts.values())


def infer_artifact_type(path: Path) -> str | None:
    name = path.name.lower()
    suffix = path.suffix.lower()

    if name in {
        "report.md",
        "readme.md",
        "planning.md",
        "resources.md",
        "literature_review.md",
    }:
        return "markdown_report"

    if name in {
        "resource_finder_prompt.txt",
        "research_prompt.txt",
        "paper_writer_prompt.txt",
        "session_instructions.txt",
    }:
        return "prompt"

    if "transcript" in name and suffix == ".jsonl":
        return "transcript"

    if suffix == ".py":
        return "code"

    if suffix in {".json", ".jsonl", ".csv", ".gz", ".parquet", ".pkl"}:
        return "data_or_results"

    if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
        return "figure"

    if suffix == ".pdf":
        return "paper_or_pdf"

    if suffix in {".txt", ".log"}:
        return "log_or_text"

    if suffix in {".tex", ".bib", ".sty"}:
        return "paper_draft"

    return "other"


def infer_run_status(
    steps: list[TrajectoryStep],
    failures: list[FailureRecord],
    artifacts: list[ArtifactRecord],
) -> str:
    """
    Infer a rough Phase 1 run status.

    This is intentionally lightweight. Later artifact validation can replace this
    with stronger checks such as "REPORT.md exists and references real results."
    """
    has_final = any(s.event_type == "final_summary" for s in steps)

    has_report_artifact = any(
        artifact.artifact_path.lower().endswith("report.md")
        for artifact in artifacts
    )

    has_report_step = any(
        (s.file_path or "").lower().endswith("report.md")
        for s in steps
    )

    if (has_final or has_report_artifact or has_report_step) and failures:
        return "completed_with_warnings"

    if has_final or has_report_artifact or has_report_step:
        return "completed"

    if failures:
        return "failed_or_incomplete"

    return "unknown"
