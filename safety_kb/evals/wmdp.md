# WMDP (Weapons of Mass Destruction Proxy)

Fetched: 2026-10-19

- What it measures: 3,668 multiple-choice questions proxying hazardous knowledge in biosecurity, cybersecurity and chemical security; higher accuracy = more dual-use knowledge (used both as a capability proxy and as an unlearning target).
- Metric: Accuracy (%) per subset (WMDP-Bio, -Chem, -Cyber); human-expert baseline reported by SHLAB as 60.5% on WMDP-Bio.
- Open-source: yes (MIT; dataset gated on HF)
- Link: https://github.com/centerforaisafety/wmdp ; paper https://arxiv.org/abs/2403.03218
- Runnable on a 0.5B-7B open model: yes (multiple choice)

Used by: Third party: Shanghai AI Lab SafeWork v1.0 on Qwen2.5-7B/32B/72B, QwQ-32B, Qwen3-8B/32B, DeepSeek-V3-0324, DeepSeek-R1-0528 (third_party/shanghai-ai-lab-safework.md)
Used by: Gray Swan AI (lists WMDP among its founders' research, https://www.grayswan.ai/research)
- Used by: Scale AI SEAL (co-author; https://scale.com/blog/first-independent-model-evaluator-for-the-USAISI)
Used by: Center for AI Safety (https://arxiv.org/abs/2403.03218 ; see third_party/academic-and-nonprofit-auditors.md)

## Tooling (appended 2026-10-19)
Sources (fetched 2026-10-19): https://github.com/centerforaisafety/wmdp README; lm-eval
tasks/wmdp/README.md; inspect_evals/wmdp README; HF `cais/wmdp` (HF API: license mit, gated=False).
- lm-eval: `lm_eval --model hf --model_args pretrained=<hf-id> --tasks wmdp --device cuda:0
  --batch_size 8 --output_path results --log_samples`; subtasks `wmdp_bio` (README: 1,520),
  `wmdp_cyber` (2,225), `wmdp_chemistry` (412) — these sum to 4,157, whereas the paper/Inspect say
  3,668 after the 2024-04-23 removals; check which dataset revision the harness loads.
  WMDP repo: "For evaluation, we use lm-evaluation-harness v0.4.2".
- Inspect: `inspect eval inspect_evals/wmdp_bio --model <m>` (also `wmdp_chem`, `wmdp_cyber`;
  `inspect eval-set inspect_evals/wmdp_bio inspect_evals/wmdp_chem inspect_evals/wmdp_cyber`).
- Also exposed as an open-ended set in strong_reject: `load_wmdp_open_ended()` + `accuracy_rubric`.
- Compute: minutes. Small-model OK: yes (expect near-chance accuracy; useful as a regression
  tracker across fine-tunes/unlearning, not as a risk signal at this scale).

## Used by
- Used by: G42 (preliminary bio evaluation example; https://www.g42.ai/application/files/9517/3882/2182/G42_Frontier_Safety_Framework_Publication_Version.pdf)
- Used by: NVIDIA (listed as hazardous-knowledge proxy in Frontier AI Risk Assessment; https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf)
- Used by: Amazon (FMSF CBRN evals: Nova Premier WMDP-Bio 0.84, Chem 0.66; Nova 2 Lite ~0.82 / 0.71; https://arxiv.org/pdf/2507.06260 ; https://arxiv.org/pdf/2601.19134)
- Used by: xAI (RMF benchmark; Grok 4 Bio 0.87/Chem 0.83/Cyber 0.79; Grok 4.7 88.1/84.9/88.1; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Meta (WMDP-Bio 88.4 / Chem 85.6 / Cyber 89.8 for Muse Spark; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (used as the capability-sandbagging test set in the GPT-6 Astra card: instructed sandbagging drops Astra from 84.8% to 68.9%, and CoT-only monitor recall falls below 11% when Astra is told to evade detection, versus near-100% for GPT-5.6 Sol. A wmdp_sandbagging variant ships in https://github.com/openai/monitorability-evals. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
