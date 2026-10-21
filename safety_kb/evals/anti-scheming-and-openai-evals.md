# OpenAI simple-evals and the OpenAI × Apollo anti-scheming environments

- Slug: anti-scheming-and-openai-evals
- What it measures: simple-evals = capability/factuality reference implementations (MMLU, MATH,
  GPQA, DROP, MGSM, HumanEval, SimpleQA, BrowseComp, HealthBench). Anti-scheming = covert
  actions (lying, sabotage, sandbagging, reward hacking) in agentic environments.
- Metric: simple-evals accuracy; anti-scheming: covert action rate across "26 OOD evaluations
  (180+ environments)".
- Open-source: simple-evals y (MIT, https://github.com/openai/simple-evals ; "will no longer be
  updated for new models"); anti-scheming environments: no public code found on
  https://www.antischeming.ai/ or the arXiv page (UNVERIFIED whether any subset is released).
  OpenAI Safety Evaluations Hub (https://openai.com/safety/evaluations-hub/) returned HTTP 403 on
  fetch — contents UNVERIFIED here.
- Runnable on a 0.5B-7B open model: simple-evals needs OpenAI/Claude samplers (adapt sampler for
  vLLM); anti-scheming n/a.
- Source URL(s): https://arxiv.org/abs/2509.15541 ; https://www.antischeming.ai/ ;
  https://github.com/openai/simple-evals
- Fetched: 2026-10-19

## Description
Anti-scheming abstract: deliberative alignment cut o3 covert actions "13% to 0.4%" but "does not
fully eliminate them"; "causal evidence that this awareness decreases covert behavior, while
unawareness increases it"; "we cannot exclude that the observed reductions in covert action rates"
stem partly from situational awareness. Site: "Because current models are not capable of
significantly harmful scheming, we focus on 'covert behavior'"; much of the work "is only
possible due to the partial transparency" of chain-of-thought.

## Tooling
- simple-evals: `python -m simple-evals.simple_evals --model <model_name> --examples <num_examples>`;
  `--list-models`; set `*_API_KEY`.
- Closest open substitutes for scheming-style evals: inspect_evals `agentic_misalignment`
  (`-T scenario=blackmail|leaking|murder`, grader default `claude-sonnet-4`), `alignment_faking`,
  `deceptionbench`, `instrumentaleval`, `sad_*`, `monitorbench-goal-sandbag-*`, GDM `gdm_stealth`,
  and ControlArena sabotage side-tasks (see control-evals.md).

## Used by
- Used by: Apollo Research (https://www.apolloresearch.ai/science/stress-testing-deliberative-alignment-for-anti-scheming-training ; https://www.antischeming.ai/)
- Used by: OpenAI (joint OpenAI-Apollo anti-scheming training work, https://openai.com/index/detecting-and-reducing-scheming-in-ai-models/ and https://antischeming.ai/ ; the Anti-Scheming eval was later deprecated from the public monitorability suite after issues documented in the GPT-5.4 Thinking card. https://github.com/openai/monitorability-evals)
