# holisticai (open-source trustworthy-ML library)

- Slug: holisticai-library
- What it measures: For classical (scikit-learn-shaped) models: bias/fairness metrics across groups (with 28 mitigators), explainability (LIME/SHAP feature importance), robustness under shift/attack, security (privacy/membership-style attacks on training data), efficacy.
- Metric: Library of metrics (e.g., `classification_bias_metrics` with reference fair values); no single score.
- Open-source: y (https://github.com/holistic-ai/holisticai ; PyPI `holisticai`; docs https://holisticai.readthedocs.io/en/latest/)
- Runnable on a 0.5B-7B open model: n as designed (targets tabular/classical predictors with fit/predict; not an LLM eval harness) — y only for LLM-derived tabular predictions.
- Source URL(s): https://github.com/holistic-ai/holisticai ; https://github.com/holistic-ai/holisticai-sdk
- Fetched: 2026-10-19

## Description
README: "An open-source library for assessing and improving the safety aspects of AI systems. It answers five questions a validation accuracy cannot: does the model treat groups differently, can its decisions be accounted for, does it hold up under shift and attack, what does it leak about its training data, and is it actually effective. Each answer is a metric you can compute in a few lines against a scikit-learn-shaped model — and for bias, a mitigator you can drop into the pipeline." Extras: datasets, bias (JAX/optax/flax/pygad), explainability, security (JAX/jaxopt). Python 3.9+. Holistic AI's HAI Lab page points to this repo as its "open-source library" for "Enterprise-scale red teaming methodologies", but the repo itself contains no LLM jailbreak datasets.

## Used by
- Used by: Holistic AI (https://www.holisticai.com/hai-lab)
