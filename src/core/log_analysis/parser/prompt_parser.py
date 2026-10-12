import re
from core.log_analysis.models import TaskSpec

DEFAULT_PHASES = [
    "motivation_novelty",
    "planning",
    "implementation",
    "analysis",
    "documentation",
    "validation",
]

DEFAULT_DELIVERABLES = [
    "planning.md",
    "REPORT.md",
    "README.md",
    "resources.md",
    "literature_review.md",
    "papers/",
    "datasets/",
    "code/",
    "results/",
    "figures/",
]

def _extract_after_heading(text: str, headings: list[str]) -> str | None:
    for heading in headings:
        pattern = rf"{re.escape(heading)}\s*:?\s*\n+(.+?)(?:\n\n|\Z)"
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None

def parse_task_spec(run_id: str, prompt_texts: dict[str, str]) -> TaskSpec:
    combined = "\n\n".join(prompt_texts.values())
    title = _extract_after_heading(
        combined,
        ["RESEARCH TITLE", "## RESEARCH TITLE", "Research Title"],
    )
    domain = _extract_after_heading(
        combined,
        ["RESEARCH DOMAIN", "## RESEARCH DOMAIN", "Research Domain"],
    )
    hypothesis = _extract_after_heading(
        combined,
        [
            "RESEARCH HYPOTHESIS",
            "HYPOTHESIS / RESEARCH QUESTION",
            "## HYPOTHESIS / RESEARCH QUESTION",
        ],
    )
    expected_phases = [
        phase for phase in DEFAULT_PHASES
        if phase.replace("_", " ").lower() in combined.lower()
        or phase.lower() in combined.lower()
    ]
    if not expected_phases:
        expected_phases = DEFAULT_PHASES
    expected_deliverables = [
        item for item in DEFAULT_DELIVERABLES
        if item.lower() in combined.lower()
    ]
    return TaskSpec(
        run_id=run_id,
        title=title,
        domain=domain,
        hypothesis=hypothesis,
        expected_phases=expected_phases,
        expected_deliverables=expected_deliverables,
        source_files=list(prompt_texts.keys()),
    )
