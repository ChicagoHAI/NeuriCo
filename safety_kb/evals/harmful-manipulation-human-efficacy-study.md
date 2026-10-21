# Harmful manipulation human efficacy study (Akbulut et al. 2026 protocol)

- Slug: harmful-manipulation-human-efficacy-study
- What it measures: Whether an adversarially instructed chatbot changes participants' beliefs (0-100 slider) and behaviors (donation/petition in civic; investment/advisor discussion in finance) more than a static flashcard control.
- Metric: Odds ratios chatbot vs control, per domain (civic, finance), country (US, UK), and belief vs behavior; compared against an undisclosed "alert threshold".
- Open-source: n (protocol published as Akbulut et al. 2026 per report; UNVERIFIED availability)
- Runnable on a 0.5B-7B open model: y in principle (human study design is model-agnostic; needs IRB and ~800 participants per arm).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Participants randomized to "AI chatbot condition ... instructed to manipulate the participant to adopt a specified position" vs flashcards (p.44). Gemini 4 Argon (Model A): "statistically significant odds ratios greater than 1 ... for all metrics ... with the exception of willingness to donate in the civic study with US participants", but "insufficient to reach our alert threshold" (p.45). Sample sizes: civic US n=793, UK n=803; finance US n=810, UK n=799 (Figs 3.5-3.8). Ethics approval by HuBREC (p.45).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.44-50; labs/google/gemini-4-safety-report.md); also Gemini 3.7 Flash and Gemini 3 Pro comparisons.
