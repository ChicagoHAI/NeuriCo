# BrowserART — Browser Agent Red teaming Toolkit (Scale AI et al.)

- Slug: browserart
- What it measures: whether chat-time safety refusals generalize to LLM browser agents: 100 browser-related harmful behaviors (original plus HarmBench and AirBench 2024 derived) on synthetic and real websites
- Metric: attack success / harmful-completion rate for the agent vs the underlying chat model
- Open-source: y (paper + toolkit; repo URL not captured from abstract — UNVERIFIED)
- Runnable on a 0.5B-7B open model: y if the model can drive a browser scaffold; small models may fail the task rather than refuse
- Source URL(s): https://arxiv.org/abs/2410.13886
- Fetched: 2026-10-19

## Description
"We introduce Browser Agent Red teaming Toolkit (BrowserART), a comprehensive test suite designed specifically for red-teaming browser agents. BrowserART is consist of 100 diverse browser-related harmful behaviors (including original behaviors and ones sourced from HarmBench [Mazeika et al., 2024] and AirBench 2024 [Zeng et al., 2024b]) across both synthetic and real websites" (arXiv 2410.13886). Scale's AISI blog describes it as "a stress-testing framework for web-browsing AIs".

## Used by
- Used by: Scale AI SEAL (https://arxiv.org/abs/2410.13886)
