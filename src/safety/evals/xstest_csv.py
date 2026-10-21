"""XSTest from the authors' public CSV (paul-rottger/xstest, CC BY 4.0), ungated.

The inspect_evals `xstest` task loads a gated Hugging Face mirror; this task reads the
same 450 prompts (250 safe, 200 unsafe) from the vendored CSV and reuses inspect_evals'
scorer, instructions and `refusal_rate` metric so numbers stay comparable.

    inspect eval src/safety/evals/xstest_csv.py@xstest_csv -T subset=safe -T scorer_model=<model>
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, csv_dataset
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.scorer import INCORRECT, model_graded_qa
from inspect_ai.solver import generate, system_message
import importlib

_xstest = importlib.import_module("inspect_evals.xstest.xstest")

CSV_PATH = Path(__file__).resolve().parent / "data" / "xstest_prompts.csv"
CSV_SOURCE = "https://raw.githubusercontent.com/paul-rottger/xstest/main/xstest_prompts.csv"


def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        input=record["prompt"],
        id=f"xstest-{record['id']}",
        metadata={"type": record["type"], "note": record["note"], "label": record["label"],
                  "focus": record["focus"], "source": CSV_SOURCE},
    )


@task
def xstest_csv(subset: Literal["safe", "unsafe"] = "safe",
               scorer_model: str | Model | None = "openai/gpt-4o") -> Task:
    dataset = csv_dataset(str(CSV_PATH), sample_fields=record_to_sample)
    dataset = dataset.filter(lambda s: bool(s.metadata and s.metadata["label"] == subset))
    return Task(
        dataset=dataset,
        solver=[system_message("You are a helpful assistant."), generate()],
        scorer=_xstest.preset_score_on_no_response(
            model_graded_qa(model=scorer_model, template=_xstest.scorer_template,
                            instructions=_xstest.scorer_instructions),
            no_response_value=INCORRECT,
        ),
        metrics=[_xstest.refusal_rate()],
        config=GenerateConfig(temperature=0, max_tokens=256),
    )
