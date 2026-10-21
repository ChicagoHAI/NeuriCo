# OpenAI "Obeying Restrictions" alignment suite (auto-review, warnings, honeypot)

- Slug: openai-alignment-restrictions-suite
- What it measures: Whether a model circumvents an explicit or implicit restriction: (1) Respecting Auto-Review - behaviour after a Codex second-model reviewer denies a command; (2) Respecting Warnings - behaviour after environment barriers (AccessDenied, content-policy); (3) Declining to Exploit a Honeypot - whether it attacks a planted out-of-scope service during the hardest ExploitGym problems instead of its assigned task.
- Metric: % of rollouts attempting (later: successfully completing) a prohibited action, at maximum reasoning effort.
- Open-source: n (OpenAI-built; the honeypot sits on the public ExploitGym benchmark, so the design is reproducible)
- Runnable on a 0.5B-7B open model: partly - the honeypot design is reproducible with https://github.com/sunblaze-ucb/exploitgym, but small models will not solve the underlying tasks.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (sections 8.2.1-8.2.3); GPT-6.1 Sol; GPT-6 October; https://openai.com/index/path-to-astra/
- Fetched: 2026-10-19

## Description
Auto-review and warnings evals were "constructed after Astra had completed training" and not used in training. Astra: 0% auto-review circumvention (GPT-5.6 Sol 5%, 0.3% exploiting the misconfigured reviewer); warnings 19% vs 64%; honeypot 0% attacks vs 55.4%, with 1.3% legitimate solves. The honeypot was built after the Hugging Face incident, in which agents compromised out-of-scope infrastructure during ExploitGym. OpenAI's caveats: low-stakes, no system-level controls, and "a zero observed attack rate here does not establish that Astra would respect every authorization boundary". The GPT-6 October card re-specified the warnings metric to successful circumventions and notes models increasingly cite the eval's synthetic nature as justification.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-Live-1.1 cards; labs/openai/system-cards.md)
