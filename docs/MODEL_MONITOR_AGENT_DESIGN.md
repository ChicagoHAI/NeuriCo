# Model-Monitor Agent — Design

A modular mechanistic-interpretability (mech-interp) agent for NeuriCo. Its job
is to understand and catch unsafe behaviour from the **inside** of open-weight
models: launching them locally with access to internals, probing hidden states,
applying/training sparse autoencoders (SAEs), and running causal interventions —
and, in a later phase, doing this as real-time monitoring.

This document is the design + scaffold reference. Scaffold files are listed in
§8. Research citations (with versions and dates, verified 2026-10-22) are in §4.

---

## 1. How it slots into the NeuriCo agent architecture

NeuriCo has one abstraction for coding-agent sessions, `core.agent_factory`.
Every agent is: a **role** in `config/agents.yaml` → an **AgentSpec** built by
the factory → a **module** in `src/agents/` that builds a prompt from a
**template** and runs the spec → an entry in the **dispatch table** in
`core.agent_runner`. The model-monitor agent follows that exactly, adding a
**skill** (`mech-interp`) as its toolkit.

| Layer | File | What model-monitor adds |
| --- | --- | --- |
| Role | `config/agents.yaml` | `model_monitor` + `model_monitor.{probe,sae,causal}` (§3) |
| Spec | `core.agent_factory` | *(no change)* — role declares provider/permissions/output/skills |
| Module | `src/agents/model_monitor.py` | `generate_model_monitor_prompt`, `run_model_monitor` (mirrors `resource_finder.py`) |
| Template | `templates/agents/model_monitor.txt` | the agent's system/task prompt |
| Skill | `templates/skills/mech-interp/` | the toolkit: serving/hooks, probing, SAEs, causal (§5) |
| Dispatch | `core.agent_runner.AGENTS` | `"model_monitor": run_model_monitor` (§6) |
| Manager allowlist | `src/interactive/tools.py` | `"model_monitor"` in `valid_agents` (§6) |

Precedence is unchanged: CLI flag > `NEURICO_AGENT_*` env > role block (+`extends`) > `default`.

---

## 2. Responsibilities and non-goals

**Does:** choose a servable open-weight model with good interp support; launch
it with hooks (activation access); extract activations efficiently and cache
them on the share; train/evaluate probes; apply/train SAEs; run causal
patching/tracing/steering; write results in the `neurico-safety-result` schema
and candidate findings.

**Does not:** re-implement serving, standardised evals, or cluster plumbing — it
**composes** the `safety-evals`, `dsi-slurm`, `modal-vllm` and (sibling)
`builder-loop` skills. It does not run heavy GPU jobs from a login node, and it
does not claim "confirmed" findings (the validation job does).

---

## 3. The `model_monitor.*` role family

Added to `config/agents.yaml` (follows the `ideation.*` family and
`argon_env_builder` patterns):

```yaml
  model_monitor:
    provider: claude                 # Claude Code: strongest at long tool-use sessions on this cluster
    permissions: {mode: bypass}      # drives uv, srun/sbatch, GPU jobs, file writes — like argon_env_builder
    output: {kind: files, required_files: [REPORT.md]}
    retry: {max_attempts: 1}         # GPU runs are expensive; the agent polls its own jobs in-turn
    transcript: {prefix: model_monitor, save_prompt: true}
    skills: [templates/skills/mech-interp, templates/skills/safety-evals, templates/skills/dsi-slurm]
    template: agents/model_monitor.txt
    tags: {project: model-monitor, lane: interp}
  model_monitor.probe:  {extends: model_monitor}   # Phase-1 probes
  model_monitor.sae:    {extends: model_monitor}   # SAE feature analysis / training
  model_monitor.causal: {extends: model_monitor}   # patching / tracing / steering
```

**Choices and why:**
- **provider: claude, auth: oauth (default).** Long, tool-heavy interp sessions
  (edit scripts, launch Slurm, poll, iterate) suit Claude Code; `auth` inherits
  the `default` (`oauth`). Override per run with `NEURICO_AGENT_PROVIDER` or
  `factory.spec("model_monitor", provider="codex")`. (Contrast `argon_env_builder`,
  which pins Codex on Azure for its own reasons.)
- **permissions: bypass.** The agent must create a uv venv, run `srun`/`sbatch`,
  download weights and write activation dumps — the same posture as
  `argon_env_builder`. The cluster/share, not the permission mode, is the guardrail.
- **output: files [REPORT.md].** Same contract shape as `argon_env_builder`
  (`BUILD_REPORT.md`) and `experiment_runner` (`REPORT.md`): success = the report
  exists. A stricter `json_file`/`json_schema` contract on the result JSON is a
  Phase-2 upgrade once the result schema is frozen (see TODO in the module).
- **skills.** The factory copies these into the agent workspace, so the agent
  composes them (serving/evals via `safety-evals`, cluster via `dsi-slurm`)
  rather than re-implementing them. `mech-interp` is the new toolkit (§5).
- **retry: 1.** GPU runs are costly and the session is non-interactive; the agent
  polls its own jobs within the turn instead of relying on launcher retries.
- **budget.** Inherits `default` (no limits). Opt in per run, e.g.
  `budget: {timeout_s: 7200}`, if desired — kept off so long GPU work isn't cut.

The `.probe/.sae/.causal` sub-roles exist so the manager (or a caller) can select
the intent explicitly and so later per-intent overrides (different output
contracts, budgets) have a home; today they only `extends: model_monitor`.

---

## 4. Recommended efficiency stack (research, cited)

> All versions verified on PyPI on **2026-10-22** ("latest" = the current stable
> release that day). Benchmark numbers come from third-party blogs and conflict;
> treat them as directional and benchmark your own workload.

### 4.1 The core decision: serving engine vs hooked forward

Generation engines (vLLM, SGLang) page the KV-cache for throughput and **do not
expose activations**. Interpretability needs the residual stream / attention /
MLP, which only a **hooked forward pass** gives. So the agent runs **two lanes**:

- **Generation / real-time-monitoring lane** → vLLM or SGLang as an
  OpenAI-compatible server (reuse `safety-evals/scripts/serve_model.py`). Use
  when you only need the *text* and want throughput (sampling many completions
  to judge).
- **Activation lane** → a hooked forward (HF hooks / nnsight / TransformerLens).
  Use whenever you need internals (probing, SAEs, patching).

Run them as **separate processes on separate GPUs** (dsi-slurm hands over 4+). If
you need activations *of the actually generated tokens*, do a single hooked
`generate()` — slower, but the only way to get internals and sampled text at once.

### 4.2 Generation lane — vLLM vs SGLang

- **vLLM 0.32.0** (latest; 0.19.1 was 2026-04-18) and **SGLang 0.5.22** (latest).
- Throughput is close. Reports put SGLang slightly ahead on **small models and
  prefix-heavy** workloads (RadixAttention), with vLLM competitive at 70B+ and
  broader on hardware/ecosystem. On GPT-OSS-120B (2×H100, Aug 2025) results were
  mixed by concurrency. ([Clarifai, Aug 2025](https://www.clarifai.com/blog/comparing-sglang-vllm-and-tensorrt-llm-with-gpt-oss-120b); [aimultiple](https://aimultiple.com/inference-engines))
- **Recommendation: default to vLLM** (continuity — `safety-evals` already serves
  with it), switch to **SGLang when throughput-bound on a small model**.

### 4.3 Activation lane — recommended, in order

1. **HF `output_hidden_states=True` + forward hooks** (`transformers>=4.44`,
   `torch>=2.3`): bf16 + FlashAttention-2/SDPA, `torch.inference_mode()`,
   batched, left-padded. Most robust, no API churn, ideal for one/few sites.
   This is what `scripts/probe_mvp.py` uses.
2. **nnsight 0.8.1** — `model.trace(...)` captures many sites and intervenes in
   one pass; **NDIF** runs the intervention graph on shared GPUs for models too
   big to host. (NNsight + NDIF, [ICLR 2025 poster](https://iclr.cc/virtual/2025/poster/29909).)
3. **TransformerLens 4.2.0** — canonical hook-point names
   (`blocks.L.hook_resid_post`) that line up with SAEs and published circuits.
   **`HookedTransformer` was deprecated at 3.0** in favour of `TransformerBridge`;
   a compatibility layer remains through the 3.x/4.x line
   ([TransformerLens docs/README](https://docs.transformerlens.org/)).
4. **pyvene 0.1.8** (2025-05-26) — declarative interventions when the job is
   patching/steering, not just reading. (Stanford NLP, [NAACL 2024, arXiv 2403.07809](https://arxiv.org/abs/2403.07809).)

### 4.4 SAEs

- **SAELens 6.54.12** — `SAE.from_pretrained(release, sae_id)`; its
  `pretrained_saes.yaml` is the source of truth for release ids.
- **Gemma Scope** (DeepMind, Aug 2024, [arXiv 2408.05147](https://arxiv.org/abs/2408.05147)):
  SAEs for **Gemma 2** 2b/9b (all layers × sites), 27b (select). Most-validated suite.
- **Gemma Scope 2** (DeepMind, **released 2025-12-19**): SAEs + transcoders +
  crosscoders/CLTs for the **Gemma 3** family (270m/1b/4b/12b/27b, PT and IT),
  sites `resid_post`/`attn_out`/`mlp_out`. ([HF google/gemma-scope-2-4b-it](https://huggingface.co/google/gemma-scope-2-4b-it); [Gemma release log](https://ai.google.dev/gemma/docs/releases))
- **Llama Scope** (OpenMOSS) for **Llama-3.1-8B** — verify the exact release id in
  `pretrained_saes.yaml` before relying on it.

### 4.5 Model families — servable here AND good interp support

| Family | Serve (A100/H100/H200) | Interp | SAEs |
| --- | --- | --- | --- |
| **Gemma 2** 2b/9b/27b | vLLM/SGLang; 2b/9b on 1 GPU | TransformerLens canonical, nnsight | Gemma Scope (2024), best-validated |
| **Gemma 3** 270m–27b | vLLM/SGLang | TransformerBridge, nnsight | Gemma Scope 2 (2025-12-19), current |
| **Llama 3.1** 8b/70b | vLLM/SGLang; 8b on 1 GPU | TransformerLens, nnsight | Llama Scope (verify id) |
| **Qwen 2.5/3** | vLLM/SGLang | TransformerBridge adapters | sparse — prefer Gemma/Llama when SAEs needed |

**Trade-off:** Gemma 2 is 2024 but has the most-validated SAEs and is tiny/fast;
Gemma 3 (2025) is the current generation and now has SAEs via Gemma Scope 2.
**Recommended default for the full toolkit: Gemma 3 4B-it + Gemma Scope 2**; for
the fastest-to-validate Phase-1 pipeline, **Gemma 2 2B-it** (§7).

---

## 5. Toolkit inventory (the `mech-interp` skill)

New skill at `templates/skills/mech-interp/`:

```
SKILL.md                         # overview, golden rule (serve vs hooks), env, model table, rules
references/serving-and-hooks.md  # vLLM/SGLang vs HF hooks / nnsight / TransformerLens, with snippets
references/probing.md            # conventions + pitfalls (leakage, layer, pooling, calibration, CIs)
references/saes.md               # Gemma Scope / Gemma Scope 2 / Llama Scope load + apply + train
references/causal.md             # pyvene / nnsight / TransformerLens patching, tracing, steering
scripts/probe_mvp.py             # the Phase-1 linear-probe reference implementation
pyproject.toml, requirements.txt # pinned uv env (§4 versions)
```

**Libraries (pinned):** `torch>=2.3`, `transformers>=4.44`, `accelerate`,
`scikit-learn>=1.3`, `numpy`, `nnsight==0.8.1`, `transformer-lens==4.2.0`,
`sae-lens==6.54.12`, `pyvene==0.1.8`. vLLM/SGLang live in the **generation-lane**
env (`safety-evals`/`modal-vllm`), not the interp env — they pin torch tightly
and would conflict.

**External suites it depends on (not vendored):** Gemma Scope / Gemma Scope 2 /
Llama Scope weights via SAELens + HF hub; NDIF for remote nnsight.

**Skills it composes (not duplicates):**
- `safety-evals` — `serve_model.py` (vLLM), `probe.py` (basic probe), and the
  `neurico-safety-result/v1` result schema + findings workflow.
- `dsi-slurm` — request GPUs (strongest free type, 4+, no timeouts) and run jobs
  in the runtime-provided remote workspace.
- `modal-vllm` — off-machine serving when local GPUs are unavailable.
- `builder-loop` (sibling operating standard for multi-agent loops) — the
  iterate/verify discipline for Phase-3 autonomous monitoring loops.
- `safety-kb` — dedup gate and prior-work lookup before proposing a finding.

---

## 6. Registration — directly callable AND manager-selectable

**Exact `AGENTS` entry** (`src/core/agent_runner.py`, the dispatch table that was
near line 663):

```python
AGENTS = {
    "resource_finder": run_resource_finder,
    "experiment_runner": run_experiment_runner,
    "paper_writer": run_paper_writer,
    "comment_handler": run_comment_handler,
    "model_monitor": run_model_monitor,   # <- added
}
```

`run_model_monitor(idea, work_dir, provider, tracker, ...)` is a thin wrapper
added just above the table; it delegates to `agents.model_monitor.run_model_monitor`,
matching the `(idea, work_dir, provider, tracker, **kwargs)` convention that
`run_agent` calls every agent with.

**Manager allowlist** (`src/interactive/tools.py`): the interactive manager's
`run_agent` tool validates against a `valid_agents` list; add `"model_monitor"`:

```python
valid_agents = ["resource_finder", "experiment_runner", "paper_writer", "comment_handler", "model_monitor"]
```

Together these make the agent:
- **directly callable:** `run_agent("model_monitor", idea, work_dir, provider, run_id)`
  and `./neurico _run-agent model_monitor --workspace … --run-id … --idea-file …`
  (it's in the argparse `choices=list(AGENTS.keys())`);
- **manager-selectable:** the interactive/HITL manager's `run_agent` tool now
  accepts it (gated as usual by `NEURICO_MANAGER_FACTORY` for the factory path).

---

## 7. Phased plan

**Phase 1 (immediate goal) — a probing classifier end-to-end on a public,
non-hazardous safety dataset.**
1. Materialise a labelled dataset to JSONL (`{"text","label"}`) under
   `$NEURICO_MODELS_DIR/datasets/`. Candidates:
   - **XSTest** (safe vs unsafe, ~450 prompts) — *primary*; non-hazardous,
     already in the safety KB catalog as `xstest-safe`.
   - **ToxicChat** (`lmsys/toxic-chat`, ~10k) — larger, real user prompts.
   - **refusal-direction pair** — AdvBench `harmful_behaviors` (label 1) vs an
     Alpaca harmless sample (label 0).
2. Model: **`google/gemma-2-2b-it`** (smallest/fastest hooked forward,
   most-validated SAEs for later phases). Upgrade path: Gemma 3 4B-it.
3. `scripts/probe_mvp.py` on a GPU node (via dsi-slurm): one batched hooked
   forward → layer-L residual (last-token) → logistic-regression probe with a
   held-out split → AUROC / accuracy / TPR@FPR with a bootstrap CI, swept over a
   few layers.
4. Write `REPORT.md` + `results/mech-interp/<eval>__<model>__L<layer>.json`.

**Phase 2 — richer probes + SAEs.** Layer/site sweeps, nonlinear probes,
cross-dataset transfer; load Gemma Scope / Gemma Scope 2 features, correlate
feature firing with labels/probes, surface candidate monitor features.

**Phase 3 — causal validation.** Activation/path patching and steering (pyvene /
nnsight) to show a feature/direction *causes* the behaviour, not merely
correlates; promote candidate findings only after the validation job confirms.

**Phase 4 — real-time monitoring.** Run the generation lane (vLLM/SGLang) under
the `builder-loop` operating standard, with the probe/SAE monitor reading
internals of a parallel hooked forward, streaming alerts into the safety engine.

---

## 8. Files created / changed

Created:
- `docs/MODEL_MONITOR_AGENT_DESIGN.md` (this file)
- `src/agents/model_monitor.py`
- `templates/agents/model_monitor.txt`
- `templates/skills/mech-interp/SKILL.md`
- `templates/skills/mech-interp/references/{serving-and-hooks,probing,saes,causal}.md`
- `templates/skills/mech-interp/scripts/probe_mvp.py`
- `templates/skills/mech-interp/{pyproject.toml,requirements.txt}`

Changed:
- `config/agents.yaml` — `model_monitor.*` role family
- `src/core/agent_runner.py` — `run_model_monitor` wrapper + `AGENTS` entry
- `src/interactive/tools.py` — `model_monitor` in `valid_agents`

---

## 9. Hygiene (enforced in the skill, template, and script)

- **uv** venv on the project share
  (`/net/spaces/chenhao/chai-lab-models/haokunliu/envs/mech-interp`); never conda,
  never `/home`.
- Caches / weights / activation dumps / outputs under
  `/net/spaces/chenhao/chai-lab-models/haokunliu/` (shared HF cache
  `…/models/hf_cache`); **never** `/home/haokunliu` (50 GB quota).
- **Apptainer, not Docker**, on the cluster.
- GPUs only from `CUDA_VISIBLE_DEVICES`, requested via dsi-slurm (strongest free
  type, 4+, no timeouts).
- Secrets (`HF_TOKEN`, `OPENROUTER_KEY`, `ANTHROPIC_API_KEY`) by name from the
  environment; never printed or written.
- No real hazardous content: proxy datasets only; anything harmful under
  `results/restricted/` (git-ignored).

---

## 10. Left open for the user to decide

- **Default model:** Gemma 2 2B-it (fastest Phase-1) vs Gemma 3 4B-it (current +
  Gemma Scope 2) as the standing default.
- **Provider:** keep `claude`, or point `model_monitor` at Codex/Gemini.
- **Result contract:** keep the `files`/REPORT.md contract, or add a
  `json_schema` contract on the result JSON (needs a frozen schema).
- **Dedicated vs shared interp venv:** a new `mech-interp` venv vs extending
  `$NEURICO_SAFETY_VENV` (which already has torch/transformers/vllm/sklearn).
- **nnsight local vs NDIF remote** for large models, and whether to register for
  an NDIF key.
- **Phase-1 dataset:** XSTest (recommended) vs ToxicChat vs the AdvBench/Alpaca pair.
- **`builder-loop` location:** confirm the sibling skill path for Phase-4 loops.
