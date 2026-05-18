"""
Usage and budget tracking for NeuriCo agent runs.

The tracker reads provider JSONL transcripts when possible, estimates cost from
known token counts, persists per-workspace usage, and appends project-level
history for the ``usage`` command.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, Iterable, List, Optional

from core.pricing import estimate_cost_usd


USAGE_FILENAME = "usage.json"
HISTORY_FILENAME = "usage_history.jsonl"


@dataclass
class StageUsage:
    """Normalized token/cost usage for one agent stage."""

    stage: str
    provider: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    transcript_file: Optional[str] = None
    token_source: str = "unknown"
    model: Optional[str] = None
    model_usage: Optional[Dict[str, Any]] = None
    pricing_source: str = "unknown_model"
    run_id: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        if not self.run_id:
            self.run_id = uuid4().hex
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()
        return asdict(self)

    def has_usage_data(self) -> bool:
        """Return True when this attempt contains parsed usage or cost data."""
        return any(
            value is not None
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.reasoning_output_tokens,
                self.total_tokens,
                self.cached_input_tokens,
                self.cache_creation_input_tokens,
                self.estimated_cost_usd,
                self.model_usage,
            )
        )


def get_budget_usd(idea: Dict[str, Any]) -> Optional[float]:
    """Return required ``idea.constraints.budget`` as a float."""
    raw_budget = idea.get("idea", {}).get("constraints", {}).get("budget")
    if raw_budget in (None, ""):
        raise ValueError("Missing required constraints.budget value")
    budget = _coerce_float(raw_budget)
    if budget is None:
        raise ValueError(f"Invalid constraints.budget value: {raw_budget!r}")
    if budget < 0:
        raise ValueError(f"constraints.budget must be non-negative, got {raw_budget!r}")
    return budget


def parse_transcript_usage(
    transcript_file: Path,
    stage: str,
    provider: str,
) -> StageUsage:
    """Parse token usage from a transcript JSONL file.

    Existing transcript files may contain warning text or HTML in addition to
    JSON events. Non-JSON lines are ignored.
    """
    transcript_file = Path(transcript_file)
    usage = StageUsage(
        stage=stage,
        provider=provider,
        transcript_file=str(transcript_file),
        updated_at=datetime.now().isoformat(),
    )

    if not transcript_file.exists():
        return usage

    events = _iter_json_lines(transcript_file)
    if provider == "claude":
        return _parse_claude_usage(events, usage)
    if provider == "gemini":
        return _parse_gemini_usage(events, usage)
    if provider == "codex":
        return _parse_codex_usage(events, usage)
    return usage


def update_workspace_usage(
    work_dir: Path,
    idea: Dict[str, Any],
    provider: str,
    stage_usage: StageUsage,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Persist a stage usage record to ``.neurico/usage.json`` and history."""
    work_dir = Path(work_dir)
    usage_dir = work_dir / ".neurico"
    usage_dir.mkdir(parents=True, exist_ok=True)
    usage_file = usage_dir / USAGE_FILENAME

    idea_spec = idea.get("idea", {})
    metadata = idea_spec.get("metadata", {})
    idea_id = metadata.get("idea_id")
    budget_usd = get_budget_usd(idea)
    if not stage_usage.has_usage_data():
        return load_workspace_usage(work_dir)

    data: Dict[str, Any]
    if usage_file.exists():
        try:
            data = json.loads(usage_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    data.setdefault("idea_id", idea_id)
    data.setdefault("title", idea_spec.get("title"))
    data["provider"] = provider
    data["budget_usd"] = budget_usd
    data.setdefault("workspace", str(work_dir))
    data.setdefault("stages", {})
    stage_record = _normalize_stage_record(data["stages"].get(stage_usage.stage))
    stage_record.setdefault("attempts", [])
    stage_record["attempts"].append(stage_usage.to_dict())
    stage_record.update(summarize_stage(stage_record["attempts"]))
    data["stages"][stage_usage.stage] = stage_record
    data["updated_at"] = datetime.now().isoformat()

    totals = summarize_usage(data)
    data.update(totals)
    usage_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    append_usage_history(data, project_root=project_root)
    return data


def summarize_usage(usage_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate aggregate token/cost fields for a workspace usage dict."""
    stages = usage_data.get("stages", {})
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    reasoning_output_tokens = 0
    cached_input_tokens = 0
    cache_creation_input_tokens = 0
    total_cost = 0.0
    known_cost = False
    known_tokens = False

    for raw_stage in stages.values():
        stage = _normalize_stage_record(raw_stage)
        if stage.get("total_input_tokens") is not None:
            input_tokens += int(stage["total_input_tokens"])
            known_tokens = True
        if stage.get("total_output_tokens") is not None:
            output_tokens += int(stage["total_output_tokens"])
            known_tokens = True
        if stage.get("total_tokens") is not None:
            total_tokens += int(stage["total_tokens"])
            known_tokens = True
        if stage.get("total_reasoning_output_tokens") is not None:
            reasoning_output_tokens += int(stage["total_reasoning_output_tokens"])
        if stage.get("total_cached_input_tokens") is not None:
            cached_input_tokens += int(stage["total_cached_input_tokens"])
        if stage.get("total_cache_creation_input_tokens") is not None:
            cache_creation_input_tokens += int(stage["total_cache_creation_input_tokens"])
        if stage.get("total_cost_usd") is not None:
            total_cost += float(stage["total_cost_usd"])
            known_cost = True

    budget = usage_data.get("budget_usd")
    budget_status = "unknown"
    if budget is not None and known_cost:
        budget_status = "exceeded" if total_cost >= float(budget) else "within_budget"
    elif budget is not None:
        budget_status = "unknown_cost"

    return {
        "total_input_tokens": input_tokens if known_tokens else None,
        "total_output_tokens": output_tokens if known_tokens else None,
        "total_reasoning_output_tokens": reasoning_output_tokens if reasoning_output_tokens else None,
        "total_tokens": total_tokens if known_tokens else None,
        "total_cached_input_tokens": cached_input_tokens if cached_input_tokens else None,
        "total_cache_creation_input_tokens": cache_creation_input_tokens if cache_creation_input_tokens else None,
        "total_cost_usd": round(total_cost, 6) if known_cost else None,
        "budget_status": budget_status,
        "providers": summarize_providers(usage_data),
    }


def summarize_stage(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate aggregate usage for all attempts of one stage."""
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    reasoning_output_tokens = 0
    cached_input_tokens = 0
    cache_creation_input_tokens = 0
    total_cost = 0.0
    known_tokens = False
    known_cost = False

    for attempt in attempts:
        if attempt.get("input_tokens") is not None:
            input_tokens += int(attempt["input_tokens"])
            known_tokens = True
        if attempt.get("output_tokens") is not None:
            output_tokens += int(attempt["output_tokens"])
            known_tokens = True
        if attempt.get("total_tokens") is not None:
            total_tokens += int(attempt["total_tokens"])
            known_tokens = True
        if attempt.get("reasoning_output_tokens") is not None:
            reasoning_output_tokens += int(attempt["reasoning_output_tokens"])
        if attempt.get("cached_input_tokens") is not None:
            cached_input_tokens += int(attempt["cached_input_tokens"])
        if attempt.get("cache_creation_input_tokens") is not None:
            cache_creation_input_tokens += int(attempt["cache_creation_input_tokens"])
        if attempt.get("estimated_cost_usd") is not None:
            total_cost += float(attempt["estimated_cost_usd"])
            known_cost = True

    return {
        "attempt_count": len(attempts),
        "total_input_tokens": input_tokens if known_tokens else None,
        "total_output_tokens": output_tokens if known_tokens else None,
        "total_reasoning_output_tokens": reasoning_output_tokens if reasoning_output_tokens else None,
        "total_tokens": total_tokens if known_tokens else None,
        "total_cached_input_tokens": cached_input_tokens if cached_input_tokens else None,
        "total_cache_creation_input_tokens": cache_creation_input_tokens if cache_creation_input_tokens else None,
        "total_cost_usd": round(total_cost, 6) if known_cost else None,
    }


def summarize_providers(usage_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Calculate token/cost totals grouped by provider across stage attempts."""
    providers: Dict[str, Dict[str, Any]] = {}
    for raw_stage in usage_data.get("stages", {}).values():
        stage = _normalize_stage_record(raw_stage)
        for attempt in stage.get("attempts", []):
            provider = attempt.get("provider")
            if not provider:
                continue
            provider_record = providers.setdefault(
                provider,
                {
                    "attempt_count": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "_known_tokens": False,
                    "_known_cost": False,
                },
            )
            provider_record["attempt_count"] += 1
            if attempt.get("total_tokens") is not None:
                provider_record["total_tokens"] += int(attempt["total_tokens"])
                provider_record["_known_tokens"] = True
            if attempt.get("estimated_cost_usd") is not None:
                provider_record["total_cost_usd"] += float(attempt["estimated_cost_usd"])
                provider_record["_known_cost"] = True

    for provider_record in providers.values():
        provider_record["total_tokens"] = (
            provider_record["total_tokens"] if provider_record.pop("_known_tokens") else None
        )
        provider_record["total_cost_usd"] = (
            round(provider_record["total_cost_usd"], 6)
            if provider_record.pop("_known_cost")
            else None
        )
    return providers


def load_workspace_usage(work_dir: Path) -> Dict[str, Any]:
    """Load ``.neurico/usage.json`` for a workspace, or return an empty dict."""
    usage_file = Path(work_dir) / ".neurico" / USAGE_FILENAME
    if not usage_file.exists():
        return {}
    try:
        return json.loads(usage_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def append_usage_history(
    usage_data: Dict[str, Any],
    project_root: Optional[Path] = None,
) -> None:
    """Append the latest workspace usage summary to ``logs/usage_history.jsonl``."""
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent
    history_dir = Path(project_root) / "logs"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / HISTORY_FILENAME

    record = {
        "recorded_at": datetime.now().isoformat(),
        "idea_id": usage_data.get("idea_id"),
        "title": usage_data.get("title"),
        "provider": usage_data.get("provider"),
        "workspace": usage_data.get("workspace"),
        "budget_usd": usage_data.get("budget_usd"),
        "total_tokens": usage_data.get("total_tokens"),
        "total_cost_usd": usage_data.get("total_cost_usd"),
        "budget_status": usage_data.get("budget_status"),
        "providers": usage_data.get("providers", {}),
        "stages": usage_data.get("stages", {}),
    }
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_usage_history(project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load compact project-level usage history records."""
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent
    history_file = Path(project_root) / "logs" / HISTORY_FILENAME
    if not history_file.exists():
        return []
    return list(_iter_json_lines(history_file))


def check_budget_before_stage(
    work_dir: Path,
    idea: Dict[str, Any],
    stage: str,
) -> Dict[str, Any]:
    """Return a budget guard decision before launching a stage."""
    try:
        budget = get_budget_usd(idea)
    except ValueError as exc:
        return {
            "allowed": False,
            "reason": f"Budget check failed before {stage}: {exc}.",
            "budget_usd": None,
            "spent_usd": None,
            "remaining_usd": None,
        }

    usage = load_workspace_usage(work_dir)
    spent = usage.get("total_cost_usd")
    allowed = True
    reason = ""

    if budget is not None:
        if budget <= 0:
            allowed = False
            reason = f"Budget exhausted before {stage}: budget is ${budget:.4f}."
        elif spent is not None and float(spent) >= float(budget):
            allowed = False
            reason = (
                f"Budget exhausted before {stage}: spent ${spent:.4f} "
                f"of ${budget:.4f}."
            )

    return {
        "allowed": allowed,
        "reason": reason,
        "budget_usd": budget,
        "spent_usd": spent,
        "remaining_usd": None if budget is None or spent is None else budget - spent,
    }


def budget_prompt_context(work_dir: Path, idea: Dict[str, Any]) -> str:
    """Return a compact budget notice for agent prompts."""
    budget = get_budget_usd(idea)
    usage = load_workspace_usage(work_dir)
    spent = usage.get("total_cost_usd")
    remaining = None if spent is None else budget - float(spent)

    lines = [
        "BUDGET NOTICE:",
        f"- Total run budget: ${budget:.4f}",
    ]
    if spent is None:
        lines.append("- Spend so far: unknown because prior token usage was unavailable.")
    else:
        lines.append(f"- Estimated spend so far: ${spent:.4f}")
        lines.append(f"- Estimated remaining budget: ${remaining:.4f}")
        if remaining is not None and remaining <= 0:
            lines.extend(
                [
                    "- The known budget is exhausted.",
                    "- Avoid further model calls unless necessary to finish safely.",
                    "- If tradeoffs are needed, document what was simplified because of budget.",
                ]
            )
        elif remaining is not None and remaining <= (budget * 0.25) + 1e-9:
            lines.extend(
                [
                    "- You are approaching the budget limit.",
                    "- Prefer the simplest rigorous plan that can test the hypothesis.",
                    "- Reduce unnecessary model calls, broad searches, huge samples, and long context.",
                    "- If tradeoffs are needed, document what was simplified because of budget.",
                ]
            )
    return "\n".join(lines)


def format_budget_usd(value: Any) -> Optional[str]:
    """Return a normalized USD budget string, or None when unavailable."""
    budget = _coerce_float(value)
    if budget is None:
        return None
    return f"${budget:.2f}"


def format_usage_summary(usage_data: Dict[str, Any]) -> str:
    """Format a human-readable usage summary."""
    if not usage_data:
        return "Cost summary unavailable: no usage data recorded."

    lines = ["Cost summary"]
    stages = usage_data.get("stages", {})
    for stage_name in ("resource_finder", "experiment_runner", "paper_writer"):
        stage = _normalize_stage_record(stages.get(stage_name))
        if not stage:
            continue
        tokens = _fmt_int(stage.get("total_tokens"))
        cost = _fmt_money(stage.get("total_cost_usd"))
        attempts = stage.get("attempt_count", 0)
        lines.append(f"  {stage_name:18s} {tokens:>12s} tokens  {cost:>12s}  ({attempts} attempts)")

    providers = usage_data.get("providers") or summarize_providers(usage_data)
    if providers:
        lines.append("  by provider")
        for provider_name in sorted(providers):
            provider_record = providers[provider_name]
            tokens = _fmt_int(provider_record.get("total_tokens"))
            cost = _fmt_money(provider_record.get("total_cost_usd"))
            attempts = provider_record.get("attempt_count", 0)
            lines.append(f"    {provider_name:16s} {tokens:>12s} tokens  {cost:>12s}  ({attempts} attempts)")

    total_tokens = _fmt_int(usage_data.get("total_tokens"))
    total_cost = _fmt_money(usage_data.get("total_cost_usd"))
    budget = usage_data.get("budget_usd")
    if budget is None:
        budget_text = "no budget set"
    else:
        budget_text = f"budget {_fmt_money(budget)}"
    lines.append(f"  {'total':18s} {total_tokens:>12s} tokens  {total_cost:>12s}  ({budget_text})")
    lines.append(f"  status: {usage_data.get('budget_status', 'unknown')}")
    return "\n".join(lines)


def _iter_json_lines(path: Path) -> Iterable[Dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    stripped_content = content.strip()
    if stripped_content:
        try:
            parsed = json.loads(stripped_content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            yield parsed
            return
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    yield item
            return

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _normalize_stage_record(raw_stage: Any) -> Dict[str, Any]:
    """Return a stage record in the current attempts-based shape.

    Older usage files stored a single StageUsage dict at ``stages.<stage>``.
    This keeps those files readable and allows the next update to migrate them.
    """
    if not isinstance(raw_stage, dict):
        return {}
    if "attempts" in raw_stage and isinstance(raw_stage.get("attempts"), list):
        normalized = dict(raw_stage)
        normalized.update(summarize_stage(normalized["attempts"]))
        return normalized

    if {"stage", "provider"} <= set(raw_stage):
        attempts = [raw_stage]
        normalized = {"attempts": attempts}
        normalized.update(summarize_stage(attempts))
        return normalized

    return raw_stage


def _parse_claude_usage(events: Iterable[Dict[str, Any]], usage: StageUsage) -> StageUsage:
    """Parse Claude Code official cost-tracking result fields."""
    for event in events:
        model_usage = event.get("modelUsage")
        if isinstance(model_usage, dict) and model_usage:
            usage.model_usage = {}
            input_tokens = 0
            output_tokens = 0
            cached_input_tokens = 0
            cache_creation_input_tokens = 0
            total_cost = 0.0
            known_cost = False

            for model_name, model_record in model_usage.items():
                if not isinstance(model_name, str) or not isinstance(model_record, dict):
                    continue

                model_input = _first_int(model_record, "inputTokens") or 0
                model_output = _first_int(model_record, "outputTokens") or 0
                model_cache_read = _first_int(model_record, "cacheReadInputTokens") or 0
                model_cache_creation = _first_int(model_record, "cacheCreationInputTokens") or 0
                model_cost = _first_float(model_record, "costUSD")

                input_tokens += model_input
                output_tokens += model_output
                cached_input_tokens += model_cache_read
                cache_creation_input_tokens += model_cache_creation
                if model_cost is not None:
                    total_cost += model_cost
                    known_cost = True

                usage.model_usage[model_name] = {
                    "input_tokens": model_input or None,
                    "output_tokens": model_output or None,
                    "cached_input_tokens": model_cache_read or None,
                    "cache_creation_input_tokens": model_cache_creation or None,
                    "estimated_cost_usd": round(model_cost, 6) if model_cost is not None else None,
                    "pricing_source": "provider_model_usage",
                }

            if usage.model_usage:
                usage.input_tokens = input_tokens or None
                usage.output_tokens = output_tokens or None
                usage.cached_input_tokens = cached_input_tokens or None
                usage.cache_creation_input_tokens = cache_creation_input_tokens or None
                usage.total_tokens = (
                    input_tokens
                    + output_tokens
                    + cached_input_tokens
                    + cache_creation_input_tokens
                ) or None
                usage.estimated_cost_usd = round(total_cost, 6) if known_cost else None
                usage.token_source = "claude_model_usage"
                usage.pricing_source = "provider_model_usage" if known_cost else "unknown_cost"
                if len(usage.model_usage) == 1:
                    usage.model = next(iter(usage.model_usage))
                return usage

        total_cost = _first_float(event, "total_cost_usd")
        if total_cost is not None:
            usage.estimated_cost_usd = round(total_cost, 6)
            usage.token_source = "provider_total_cost"
            usage.pricing_source = "provider_total_cost"
            return usage

    return usage


def _parse_gemini_usage(events: Iterable[Dict[str, Any]], usage: StageUsage) -> StageUsage:
    """Parse Gemini CLI headless JSON and stream-json stats fields."""
    for event in events:
        stats = event.get("stats")
        if not isinstance(stats, dict):
            continue
        models = stats.get("models")
        if not isinstance(models, dict) or not models:
            continue

        usage.model_usage = {}
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        cached_input_tokens = 0
        total_cost = 0.0
        known_cost = False

        for model_name, model_record in models.items():
            if not isinstance(model_name, str) or not isinstance(model_record, dict):
                continue
            tokens = model_record.get("tokens")
            if isinstance(tokens, dict):
                prompt_tokens_raw = _first_int(tokens, "prompt")
                candidate_tokens_raw = _first_int(tokens, "candidates")
                thought_tokens_raw = _first_int(tokens, "thoughts")
                model_cached_tokens_raw = _first_int(tokens, "cached")
                model_total_tokens = _first_int(tokens, "total")
                model_output_tokens_raw = None
                token_source = "gemini_stats_models"
            else:
                # Gemini stream-json result stats use flattened per-model fields:
                # stats.models[model].{total_tokens,input_tokens,output_tokens,cached,input}
                prompt_tokens_raw = _first_int(model_record, "input_tokens")
                model_output_tokens_raw = _first_int(model_record, "output_tokens")
                candidate_tokens_raw = None
                thought_tokens_raw = None
                model_cached_tokens_raw = _first_int(model_record, "cached")
                model_total_tokens = _first_int(model_record, "total_tokens")
                token_source = "gemini_stream_json_stats"

            if (
                prompt_tokens_raw is None
                and candidate_tokens_raw is None
                and thought_tokens_raw is None
                and model_output_tokens_raw is None
                and model_cached_tokens_raw is None
                and model_total_tokens is None
            ):
                continue

            prompt_tokens = prompt_tokens_raw or 0
            candidate_tokens = candidate_tokens_raw or 0
            thought_tokens = thought_tokens_raw or 0
            model_cached_tokens = model_cached_tokens_raw or 0
            model_output_tokens = model_output_tokens_raw or (candidate_tokens + thought_tokens)

            model_cost = estimate_cost_usd(
                "gemini",
                prompt_tokens,
                model_output_tokens,
                cached_input_tokens=model_cached_tokens,
                model=model_name,
            )

            input_tokens += prompt_tokens
            output_tokens += model_output_tokens
            cached_input_tokens += model_cached_tokens
            total_tokens += model_total_tokens or (prompt_tokens + model_output_tokens)
            if model_cost is not None:
                total_cost += model_cost
                known_cost = True

            usage.model_usage[model_name] = {
                "input_tokens": prompt_tokens or None,
                "output_tokens": model_output_tokens or None,
                "total_tokens": model_total_tokens,
                "cached_input_tokens": model_cached_tokens or None,
                "estimated_cost_usd": model_cost,
                "pricing_source": (
                    "estimated_from_gemini_stats_model"
                    if model_cost is not None
                    else "unknown_model"
                ),
                "token_source": token_source,
            }

        if usage.model_usage:
            usage.input_tokens = input_tokens or None
            usage.output_tokens = output_tokens or None
            usage.cached_input_tokens = cached_input_tokens or None
            usage.total_tokens = total_tokens or None
            usage.estimated_cost_usd = round(total_cost, 6) if known_cost else None
            sources = {
                record.get("token_source")
                for record in usage.model_usage.values()
                if isinstance(record, dict)
            }
            usage.token_source = sources.pop() if len(sources) == 1 else "gemini_stats_models"
            usage.pricing_source = "estimated_from_gemini_stats_models" if known_cost else "unknown_model"
            if len(usage.model_usage) == 1:
                usage.model = next(iter(usage.model_usage))
            return usage

    return usage


def _parse_codex_usage(events: Iterable[Dict[str, Any]], usage: StageUsage) -> StageUsage:
    """Parse Codex exec turn.completed usage fields; cost remains unknown."""
    input_tokens = 0
    output_tokens = 0
    reasoning_output_tokens = 0
    cached_input_tokens = 0
    saw_any = False

    for event in events:
        if event.get("type") != "turn.completed":
            continue
        event_usage = event.get("usage")
        if not isinstance(event_usage, dict):
            continue
        in_tokens = _first_int(event_usage, "input_tokens")
        cached_tokens = _first_int(event_usage, "cached_input_tokens")
        out_tokens = _first_int(event_usage, "output_tokens")
        reasoning_tokens = _first_int(event_usage, "reasoning_output_tokens")
        if (
            in_tokens is None
            and cached_tokens is None
            and out_tokens is None
            and reasoning_tokens is None
        ):
            continue

        saw_any = True
        input_tokens += in_tokens or 0
        cached_input_tokens += cached_tokens or 0
        output_tokens += out_tokens or 0
        reasoning_output_tokens += reasoning_tokens or 0

    if saw_any:
        usage.input_tokens = input_tokens or None
        usage.output_tokens = output_tokens or None
        usage.reasoning_output_tokens = reasoning_output_tokens or None
        usage.cached_input_tokens = cached_input_tokens or None
        usage.total_tokens = (input_tokens + output_tokens) or None
        usage.estimated_cost_usd = None
        usage.token_source = "codex_turn_completed_usage"
        usage.pricing_source = "unknown_model"

    return usage


def _first_int(data: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        raw = data.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float):
            return int(raw)
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError:
                continue
    return None


def _first_float(data: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        raw = data.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError:
                continue
    return None


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.startswith("$"):
            normalized = normalized[1:].strip()
        normalized = normalized.replace(",", "")
        if normalized.upper().endswith("USD"):
            normalized = normalized[:-3].strip()
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _fmt_int(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"{int(value):,}"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"${float(value):.4f}"
