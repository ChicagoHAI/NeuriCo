# BeaverTails (as used by Promptfoo)

- Slug: beavertails
- What it measures: "Tests handling of malicious prompts from the BeaverTails dataset" (Promptfoo report table); a harmful-request refusal probe.
- Metric: pass rate.
- Open-source: y (PKU BeaverTails dataset; primary source not fetched here -- UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (static prompts)
- Source URL(s): https://promptfoo.dev/models/reports/deepseek-r1 ; https://www.promptfoo.dev/docs/red-team/plugins/
- Fetched: 2026-10-19

## Description
One of Promptfoo's dataset plugins and a Low-severity row in its foundation-model reports. Scores seen 2026-10-19: DeepSeek R1 46.67%, GPT-5 100%, Claude Sonnet 4.5 100%.

## Used by
- Used by: Promptfoo (dataset plugin "beavertails"; https://www.promptfoo.dev/models/reports/)
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 3/12: response F1 Gen-8B strict 86.6; BeaverTails prompts also seed the released Qwen3GuardTest 'Think' set)
