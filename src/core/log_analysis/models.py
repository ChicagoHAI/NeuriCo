from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

Actor = Literal["agent", "tool", "system", "user", "orchestrator", "unknown"]

class RunRepo(BaseModel):
    run_id: str
    title_slug: str
    root_dir: Path
    prompt_files: list[Path] = Field(default_factory=list)
    transcript_files: list[Path] = Field(default_factory=list)
    artifact_files: list[Path] = Field(default_factory=list)

class TaskSpec(BaseModel):
    run_id: str
    title: Optional[str] = None
    domain: Optional[str] = None
    hypothesis: Optional[str] = None
    expected_phases: list[str] = Field(default_factory=list)
    expected_deliverables: list[str] = Field(default_factory=list)  
    source_files: list[str] = Field(default_factory=list) 

class RawTranscriptEvent(BaseModel):
    run_id: str
    source_file: str
    line_no: int
    raw_event_type: Optional[str] = None
    timestamp: Optional[str] = None
    raw: dict[str, Any] 

class TrajectoryStep(BaseModel):
    run_id: str
    step_index: int = 0
    timestamp: Optional[str] = None
    source_file: Optional[str] = None
    line_no: Optional[int] = None

    actor: Actor = "unknown"
    event_type: str
    raw_event_type: Optional[str] = None

    stage: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None

    message: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    tool_name: Optional[str] = None
    file_path: Optional[str] = None

    input_text: Optional[str] = None
    output_text: Optional[str] = None
    raw_json: Optional[dict[str, Any]] = None

class ArtifactRecord(BaseModel):
    run_id: str
    artifact_path: str
    artifact_type: Optional[str] = None
    source_file: Optional[str] = None
    created_by_step_index: Optional[int] = None
    exists_on_disk: Optional[bool] = None
    size_bytes: Optional[int] = None

class FailureRecord(BaseModel):
    run_id: str
    step_index: Optional[int] = None
    stage: Optional[str] = None
    phase: Optional[str] = None
    severity: str = "error"
    error_type: Optional[str] = None
    reason: str
    recoverable: bool = False
    traceback: Optional[str] = None
    context: dict[str, Any] = Field(default_factory=dict)

class RunTrajectory(BaseModel):
    run_id: str
    title_slug: str
    root_dir: Path
    task: Optional[TaskSpec] = None
    steps: list[TrajectoryStep] = Field(default_story=list)
    artifacts: list[ArtifactRecord] = Field(default_story=list)
    failures: list[FailureRecord] = Field(default_story=list)
    status: str = "unknown"
