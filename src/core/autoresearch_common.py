"""Behavior-neutral helpers shared by ordinary and HITL AutoResearch."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.hitl_util import atomic_write_json, atomic_write_text


def ensure_results_json(
    work_dir: Path,
    stage: str,
    scorer_result: Optional[Dict[str, Any]],
    *,
    created_at: str,
) -> Path:
    results_path = Path(work_dir) / "scoring" / "results.json"
    if results_path.exists():
        return results_path
    results_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "overall_satisfied": False,
        "error": f"AutoResearch {stage} scorer did not produce scoring/results.json",
        "scorer_result": scorer_result or {},
        "generated_by": "autoresearch",
        "created_at": created_at,
    }
    atomic_write_json(
        results_path,
        payload,
        indent=2,
        trailing_newline=False,
        fsync_parent=False,
    )
    return results_path


def idea_with_comments(idea: Dict[str, Any], proposal: str) -> Dict[str, Any]:
    idea_copy = json.loads(json.dumps(idea, default=str))
    idea_spec = idea_copy.setdefault("idea", {})
    idea_spec["comments"] = proposal
    return idea_copy


def clear_stale_results_json(work_dir: Path) -> None:
    results_path = Path(work_dir) / "scoring" / "results.json"
    if results_path.exists():
        results_path.unlink()


def attempt_id_for(history_root: Path, attempt_dir: Path) -> str:
    candidate = Path(attempt_dir)
    try:
        return str(candidate.relative_to(Path(history_root)))
    except ValueError:
        return candidate.name


def invoke_proposal_generator(
    generator: Callable[..., Any],
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    parent_sha: str,
    attempt_dir: Path,
    attempt_history: list[Dict[str, Any]],
    prompt_suffix: str = "",
    env_extra: Optional[Dict[str, str]] = None,
) -> Any:
    args = (idea, work_dir, parent_sha, attempt_dir, attempt_history)
    kwargs: Dict[str, Any] = {}
    if prompt_suffix or env_extra:
        signature = inspect.signature(generator)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if prompt_suffix:
            if "prompt_suffix" not in signature.parameters and not accepts_kwargs:
                raise TypeError(
                    "HITL proposal revision requires a proposal generator that "
                    "accepts prompt_suffix."
                )
            kwargs["prompt_suffix"] = prompt_suffix
        if env_extra:
            if "env_extra" not in signature.parameters and not accepts_kwargs:
                raise TypeError(
                    "HITL proposal idea reporting requires a proposal generator that "
                    "accepts env_extra."
                )
            kwargs["env_extra"] = env_extra
    return generator(*args, **kwargs)


def revert_whiteboard_attempt(whiteboard: Any, attempt_id: str) -> bool:
    if not attempt_id:
        return False
    return bool(whiteboard.revert_attempt(attempt_id))


def write_attempt_marker_file(path: Path, attempt_id: str) -> None:
    marker = Path(path)
    atomic_write_text(
        marker,
        attempt_id.strip() + "\n",
        fsync_parent=False,
    )


def read_attempt_marker_file(path: Path) -> str:
    marker = Path(path)
    if not marker.exists():
        return ""
    return marker.read_text(encoding="utf-8").strip()


def clear_attempt_marker_file(path: Path) -> None:
    Path(path).unlink(missing_ok=True)
