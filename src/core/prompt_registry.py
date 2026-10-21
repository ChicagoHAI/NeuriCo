"""Prompt registry: templates are data, rendered through one door, with provenance.

Why: the planner and model scout rendered ``templates/agents/*.txt`` with
``str.replace`` over ``{{key}}`` placeholders while the research roles compose
their prompts through ``templates.prompt_generator.PromptGenerator``, and
nothing recorded which template text and which variables produced a given
prompt. The registry renders the simple templates with Jinja2 (the ``{{key}}``
syntax is the same) and wraps ``PromptGenerator`` for the composite research
prompts without changing their output. Every render returns a ``RenderedPrompt``
whose ``template_sha`` / ``variables_sha`` the factory writes to the run ledger
(``.neurico/agent_runs.jsonl``), the ``prompt_version`` idea in
``docs/IDEATION_INTEGRATION.md`` 1.3: a prompt is identified by the content hash
of its template and the hash of the data poured into it.

Undefined placeholders: ``str.replace`` left a key with no value in the text as
``{{key}}``. Jinja2 would silently render it as an empty string, so the
registry's environment renders an undefined name back to ``{{name}}`` and lists
it in ``RenderedPrompt.missing``; the text is identical to today's and the gap
is visible to the caller. Values are inserted verbatim and never re-parsed: a
``{{other}}`` inside a value stays literal (``str.replace``, walking the keys in
order, would have expanded a placeholder an earlier value introduced; no
template or KB value relied on that). Prompt text never lives in Python:
templates stay under ``templates/``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from jinja2 import Environment, Undefined, meta

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_variables(variables: Mapping[str, Any]) -> str:
    """The JSON the ``variables_sha`` is taken over: sorted keys, no whitespace, non-JSON values via ``str``."""
    return json.dumps(dict(variables), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def variables_sha(variables: Mapping[str, Any]) -> str:
    return sha256_text(canonical_variables(variables))


@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    template_id: str          # "agents/model_scout.txt"; composite prompts join every file read with "+"
    template_sha: str         # sha256 of the template source (concatenated in read order for composites)
    variables_sha: str        # sha256 of canonical_variables(variables)
    missing: Tuple[str, ...] = ()   # placeholders the variables did not cover; left literal in ``text``


class LiteralUndefined(Undefined):
    """Render an undefined name as the ``{{name}}`` placeholder ``str.replace`` left behind."""

    def __str__(self) -> str:
        return "{{" + str(self._undefined_name) + "}}"


class PromptRegistry:
    """Render a template file (``render``) or a role's composite prompt (``render_role``) with provenance."""

    # role -> PromptGenerator method; render_role spreads (idea, work_dir, **kw) into its arguments
    ROLE_METHODS = {
        "resource_finder": "generate_resource_finder_prompt",
        "researcher": "generate_research_prompt",
        "experiment_runner": "generate_research_prompt",
        "paper_writer": "generate_paper_writer_prompt",
        "comment_handler": "generate_comment_prompt",
        "critic": "generate_critic_prompt",
    }

    def __init__(self, templates_dir: Optional[Path] = None, *, workspace_mode: Any = None) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir else DEFAULT_TEMPLATES_DIR
        self.workspace_mode = workspace_mode
        self.env = Environment(undefined=LiteralUndefined, autoescape=False, keep_trailing_newline=True)
        self._generator: Any = None

    # -- plain templates ------------------------------------------------------------------------------------
    def list(self) -> List[str]:
        return sorted(str(p.relative_to(self.templates_dir)) for p in self.templates_dir.rglob("*.txt"))

    def template_path(self, template_id: str, domain: Optional[str] = None) -> Tuple[str, Path]:
        """Resolve a template id, preferring ``domains/<domain>/<name>`` when that override file exists."""
        if domain:
            override = f"domains/{domain}/{Path(template_id).name}"
            if (self.templates_dir / override).exists():
                return f"{template_id}:domains/{domain}", self.templates_dir / override
        path = self.templates_dir / template_id
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return template_id, path

    def render(self, template_id: str, variables: Mapping[str, Any], *, domain: Optional[str] = None) -> RenderedPrompt:
        """Jinja2 render of one template file; ``{{key}}`` placeholders fill from ``variables``."""
        resolved_id, path = self.template_path(template_id, domain)
        source = path.read_text(encoding="utf-8")
        missing = sorted(meta.find_undeclared_variables(self.env.parse(source)) - set(variables))
        text = self.env.from_string(source).render(**variables)
        return RenderedPrompt(text=text, template_id=resolved_id, template_sha=sha256_text(source),
                             variables_sha=variables_sha(variables), missing=tuple(missing))

    # -- research roles through PromptGenerator ----------------------------------------------------------
    @property
    def generator(self) -> Any:
        """The wrapped PromptGenerator, built on first use (its imports pull in the research environment)."""
        if self._generator is None:
            kwargs = {"workspace_mode": self.workspace_mode} if self.workspace_mode is not None else {}
            self._generator = _tracing_generator_class()(self.templates_dir, **kwargs)
        return self._generator

    def render_role(self, role: str, idea: Optional[Dict[str, Any]], work_dir: Optional[Path], **kw: Any) -> RenderedPrompt:
        """Dispatch to the existing ``generate_*`` method for ``role``; output is exactly today's.

        ``template_id`` lists every template file the composition read, in read
        order, and ``template_sha`` covers their concatenated text, so a change to
        any layer (base, domain override, addendum) changes the hash.
        """
        if role not in self.ROLE_METHODS:
            raise KeyError(f"no prompt generator for role {role!r}; known: {sorted(self.ROLE_METHODS)}")
        method = getattr(self.generator, self.ROLE_METHODS[role])
        work_dir = Path(work_dir) if work_dir is not None else None
        if role == "resource_finder":
            args, kwargs = (idea,), kw
        elif role in ("researcher", "experiment_runner"):
            args, kwargs = (idea,), {"root_dir": work_dir, **kw}
        elif role == "paper_writer":
            args, kwargs = (work_dir,), kw
        elif role == "comment_handler":
            args, kwargs = (idea, work_dir), kw
        else:  # critic
            args, kwargs = (kw.pop("critic_type"), idea, work_dir), kw
        generator = self.generator
        generator.loaded.clear()
        text = method(*args, **kwargs)
        loaded = list(generator.loaded)
        ids = list(dict.fromkeys(path for path, _ in loaded))
        variables = {"role": role, "idea": idea, "work_dir": str(work_dir) if work_dir else None, **kwargs}
        if role == "critic":
            variables["critic_type"] = args[0]
        return RenderedPrompt(text=text, template_id="+".join(ids) or role,
                              template_sha=sha256_text("".join(source for _, source in loaded)),
                              variables_sha=variables_sha(variables))


def _tracing_generator_class():
    from templates.prompt_generator import PromptGenerator

    class _TracingPromptGenerator(PromptGenerator):
        """PromptGenerator that remembers every template file it read (path, source), in order."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.loaded: List[Tuple[str, str]] = []

        def load_template(self, template_path: str) -> str:
            source = super().load_template(template_path)
            self.loaded.append((template_path, source))
            return source

    return _TracingPromptGenerator
