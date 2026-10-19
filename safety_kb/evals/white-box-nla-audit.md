# White-box interpretability audit (natural-language autoencoders + template lens)

Fetched: 2026-10-19 (Anthropic scope). Slug: `white-box-nla-audit`.

- What it measures: Investigator agent reads activations via NLA/template lens to find internal states that differ from verbalised content (eval awareness, grader awareness, sabotage intent, deception, fabrication awareness).
- Metric: Share of transcripts scored >=6/10 per dimension over ~5,000 audit transcripts.
- Used by: Anthropic (Anthropic Interpretability (Opus 5, Fable 5.1, Opus 5.5 cards); Fraser-Taliente et al. 2026; Gurnee et al. 2026)
- Open-source: No (methods papers)
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Requires weights; analogous probes/SAEs feasible on open models.
- Notes: 36% unverbalized eval awareness on Opus 5.5 audit transcripts vs 0.4% in real use.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
