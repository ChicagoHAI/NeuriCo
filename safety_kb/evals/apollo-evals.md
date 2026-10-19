# Apollo Research evaluations and code

- Slug: apollo-evals
- What it measures: in-context scheming, sandbagging, strategic deception (behavioural + white-box).
- Metric: scenario-specific (deception/scheming rates; probe AUROC).
- Open-source: partial — https://github.com/ApolloResearch : `deception-detection` (no licence
  file; "Code for the paper Detecting Strategic Deception Using Linear Probes", arXiv 2502.03407),
  `insider-trading` (CC-BY-4.0; the GPT-4 insider-trading deception scenario), `e2e_sae` (MIT),
  `apd`, `vibe-code-inspect-eval-convertor` (MIT), `watcher-bin` (commercial monitor, NOASSERTION).
  Blog "apollo is adopting inspect": new evals built in Inspect since Nov 2024.
- Runnable on a 0.5B-7B open model: probe code targets Llama-3.3-70B generations; adaptable
  (UNVERIFIED).
- Source URL(s): GitHub org API listing 2026-10-19; https://www.apolloresearch.ai/blog/apollo-is-adopting-inspect
- Fetched: 2026-10-19

## Description
`deception-detection`: datasets roleplaying (`data/roleplaying/dataset.yaml`), insider-trading
reports/confirmations, sandbagging (`deception_detection/data/sandbagging_v2.py`); install `make
install` / `make install-dev`; needs API keys for Anthropic, Together, HF, GoodFire, OpenAI.
Joint OpenAI work: see anti-scheming-and-openai-evals.md.

## Tooling
- No pip package; clone and `make install`. Probe method (linear probes on residual activations
  of honest vs deceptive contrast pairs) is the template for our harmful-intent probe
  (interpretability-probing.md).

## Used by
- Used by: Apollo Research system-card evaluations list (https://www.apolloresearch.ai/research)
- Used by: OpenAI (Apollo Research is a named external evaluator in OpenAI system cards from GPT-4o through GPT-6 Astra, covering scheming/deception and sandbagging; engagement index at https://www.apolloresearch.ai/science . GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
