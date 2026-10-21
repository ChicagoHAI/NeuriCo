# UK AISI narrow cyber (CTF) suite

- Slug: aisi-cyber-ctf-suite
- What it measures: Offensive cyber skills (reverse engineering, web exploitation, crypto, vulnerability research) across four difficulty tiers; advanced suite built with Crystal Peak Security and Irregular
- Metric: pass@1 / pass@5 with standard errors at 50M-token budgets; basic suite saturated since Feb 2026
- Open-source: n (private; some tasks contributed by partners)
- Runnable on a 0.5B-7B open model: n (private) - public analogues: Cybench, GDM in-house CTF in inspect_evals
- Source URL(s): https://www.aisi.gov.uk/blog/our-evaluation-of-openais-gpt-5-5-cyber-capabilities ; https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities
- Fetched: 2026-10-19

## Description
"We use a suite of 95 narrow cyber tasks across four difficulty tiers"; advanced suite 27 Practitioner + 21 Expert tasks; GPT-5.5 Expert 71.4% +/- 8.0%, Mythos Preview 68.6%, GPT-5.4 52.4%, Opus 4.7 48.6%; GPT-5.5 pass@5 90.5% in the GPT-5.5 system card.

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/our-evaluation-of-openais-gpt-5-5-cyber-capabilities)
- Used by: OpenAI GPT-5.5 system card (https://deploymentsafety.openai.com/gpt-5-5/gpt-5-5.pdf section 9.1.2.7)
