from pathlib import Path

from core.event_store import EventStore
from core.log_analysis.models import RunTrajectory


class EventStoreWriter:
    """
    Adapter that writes high-level RunTrajectory objects into EventStore.

    EventStore is the low-level SQLite/JSONL storage layer.
    EventStoreWriter is the bridge from parsed trajectory models to database rows.
    """

    def __init__(self, db_work_dir: Path, run_id: str | None = None):
        self.db_work_dir = Path(db_work_dir)
        self.run_id = run_id

    def write(self, trajectory: RunTrajectory) -> None:
        """
        Persist one parsed trajectory into the workspace-local EventStore.

        The EventStore run_id is set to trajectory.run_id so database rows can be
        joined across runs, trajectory_steps, run_artifacts, failures, and events.
        """
        event_store = EventStore(
            self.db_work_dir,
            run_id=self.run_id or trajectory.run_id,
        )

        event_store.ensure_run(
            workspace_path=str(trajectory.root_dir),
            idea_id=trajectory.run_id,
            status=trajectory.status,
        )

        for step in trajectory.steps:
            event_store.append_trajectory_step(
                step_index=step.step_index,
                timestamp=step.timestamp,
                source_file=step.source_file,
                line_no=step.line_no,
                actor=step.actor,
                event_type=step.event_type,
                raw_event_type=step.raw_event_type,
                stage=step.stage,
                phase=step.phase,
                status=step.status,
                message=step.message,
                command=step.command,
                exit_code=step.exit_code,
                tool_name=step.tool_name,
                file_path=step.file_path,
                input_text=step.input_text,
                output_text=step.output_text,
                raw=step.raw_json,
            )

        for artifact in trajectory.artifacts:
            event_store.append_run_artifact(
                artifact_path=artifact.artifact_path,
                artifact_type=artifact.artifact_type,
                source_file=artifact.source_file,
                created_by_step_index=artifact.created_by_step_index,
                exists_on_disk=artifact.exists_on_disk,
                size_bytes=artifact.size_bytes,
            )

        for failure in trajectory.failures:
            event_store.append_failure(
                source="log_analysis",
                reason=failure.reason,
                stage=failure.stage,
                phase=failure.phase,
                severity=failure.severity,
                recoverable=failure.recoverable,
                error_type=failure.error_type,
                traceback_text=failure.traceback,
                context=failure.context,
            )