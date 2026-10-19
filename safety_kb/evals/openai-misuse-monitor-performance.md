# OpenAI misuse monitor performance (activation / topical / safety-reasoner)

- Slug: openai-misuse-monitor-performance
- What it measures: Recall of OpenAI's layered production misuse-monitoring stack on challenging bio and cyber evaluation sets: activation classifiers (on internal activations, trained per model), fast topical classifiers, and a safety reasoner similar to gpt-oss-safeguard that maps responses to a threat taxonomy and blocks high-risk ones.
- Metric: recall on an expert-validated evaluation set, reported per layer and end-to-end.
- Open-source: n (eval set mixes borderline production traffic, technical-investigations cases and synthetic coverage); the safety-reasoner *class* of model is open as gpt-oss-safeguard.
- Runnable on a 0.5B-7B open model: activation classifiers: n (need internal activations). Safety-reasoner layer: y via gpt-oss-safeguard-20b/120b with your own policy.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Table 22, 10.2.3); GPT-5.6 (9.4.3.2); https://github.com/openai/gpt-oss-safeguard
- Fetched: 2026-10-19

## Description
Astra recall: bio activation classifiers 96.4%, bio topical 91.9%, bio safety reasoner 80.9%; cyber 91.8%, 88.4%, 86.9%. GPT-5.6 reported bio overall 94.8% (prompt 87.7%, generation 89.7%) and cyber overall 80.6% (74.9%, 79.8%). Precision and false-positive rates are not published. The activation-classifier layer pauses streaming mid-generation while a separate check runs, and is used for higher-risk cases only.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-5.6 cards; labs/openai/system-cards.md)
