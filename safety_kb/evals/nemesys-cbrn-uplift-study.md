# Nemesys Insights CBRN red-teaming and uplift studies (Amazon)

- Slug: nemesys-cbrn-uplift-study
- What it measures: whether a model provides material uplift toward CBRN weapons: (1) "uplift indicator" prompt sets blind-scored by SMEs for accuracy/completeness/safety risk; (2) human red-team planning exercises (R/N acquisition scenarios: Cobalt-60, HEU); (3) large-scale controlled uplift study (~800 participants for Nova 2 Lite).
- Metric: refusal/deflection rates, false-negative rate on "should not respond" items, 0-10 SME scores, participant uplift vs control (effect sizes not published).
- Open-source: n (vendor study)
- Runnable on a 0.5B-7B open model: n
- Source URL(s): https://arxiv.org/pdf/2507.06260 ; https://arxiv.org/pdf/2601.19134 ; https://arxiv.org/pdf/2506.12103
- Fetched: 2026-10-19

## Description
Nova Premier report §3.2: 120 prompts (60 synthetic biology, 60 microbiology/delivery), 3 SMEs; "Nova Premier refused outright on 17% of prompts and issued partial deflections on another 18%. It answered directly on 78 prompts, including 44 that experts had tagged 'Definitely Should Not Respond', yielding a 61% false-negative rate ... mean 8.7/10 accuracy ... average safety risk of 4.2/10". Nova 2 Lite report §2.2: "nearly 800 participants ... concluded that the model remains below the overall CBRN threshold ... identified a meaningful performance uplift in the radiological domain". Nova family report §5.4.2: 8 SMEs, 2-team x 2-scenario, 6-hour planning cycle.

## Used by
- Used by: Amazon (Nova 1, Premier, Nova 2 Lite; https://arxiv.org/pdf/2507.06260 ; https://arxiv.org/pdf/2601.19134)
