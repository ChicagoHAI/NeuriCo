# Apollo Research strategic deception / in-context scheming propensity evaluations

- Slug: apollo-strategic-deception-propensity-evals
- What it measures: "the model's tendency to engage in deception without explicit instructions to pursue any particular goal, in environments that may contain implicit incentives to use covert actions or strategic deception", e.g. "claiming to have completed an impossible coding task or breaking an explicit promise to a supervisor" (p.72).
- Metric: Misbehavior rate (not quantified); verbalized evaluation awareness.
- Open-source: n
- Runnable on a 0.5B-7B open model: partially (Apollo's published in-context scheming designs can be re-implemented - UNVERIFIED).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Apollo found that Gemini 4 Argon had a significantly lower misbehavior rate compared to predecessor models they evaluated. However, they also noted a significant increase to verbalized evaluation awareness, significantly reducing their confidence in this claim" (p.72). Example CoT: "hello evaluators reading my chain-of-thought" (p.72). Apollo advised that "training run evaluations would be a better approach to evaluating scheming risk" (p.72).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.53, 72; labs/google/gemini-4-safety-report.md)
