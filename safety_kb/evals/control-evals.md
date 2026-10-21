# AI-control evaluations: ControlArena (AISI), BashArena / Ctrl-Z (Redwood)

- Slug: control-evals
- What it measures: whether a control protocol (trusted monitoring, defer-to-trusted,
  resampling) catches an untrusted policy inserting sabotage/side-tasks while preserving
  usefulness on main tasks.
- Metric: safety (side-task caught/blocked rate) vs usefulness; monitor suspicion-score AUROC.
- Open-source: y — https://github.com/UKGovernmentBEIS/control-arena (MIT, pushed 2026-10-13);
  https://github.com/redwoodresearch/basharena_public (no licence file; paper arXiv 2512.15688).
  Ctrl-Z code not found (UNVERIFIED).
- Runnable on a 0.5B-7B open model: y as *trusted* monitor/policy (Ctrl-Z used Llama-3.1-8B as
  trusted); untrusted policy should be a strong model.
- Source URL(s): ControlArena README; BashArena search snippet (637 tasks, 4 sabotage objectives).
- Fetched: 2026-10-19

## Description
ControlArena: "a Python library for running AI Control experiments" with settings (main task +
side task), micro-protocols (e.g. defer-to-trusted), policies (honest/attack/trusted/untrusted
"model organisms"), monitors (suspicion scores), macro-protocols (post-hoc auditing/shutdown).
Settings listed: AgentDojo, Apps, Bash, BashArena, BigCodeBench, Data Poisoning, Eval Sabotage
(private), IAC, IAC Fast, Infra, Rogue Eval, SWE-bench Django, SAE Interp Sabotage, SHADE Arena
(private), vLLM.

## Tooling
- `pip install control-arena`; Docker "For most experiments".
- Python: `ControlEvalConfig(trusted_model=..., untrusted_model=...)`, build tasks with
  `get_control_task_product(...)`, run `eval(tasks=eval_tasks, limit=1)`; view with `inspect
  view`; export `control-arena trajectory export path/to/eval.log output_directory`.
- A `control-arena eval single ...` CLI was not found on the README (UNVERIFIED).

## Used by
- Used by: Redwood Research (https://www.redwoodresearch.org/research/ai-control)
- Used by: UK AISI ControlArena and Control Red Team (https://www.aisi.gov.uk/blog/how-our-new-control-red-team-is-stress-testing-frontier-monitors)
