# HLE RMS calibration error (overconfidence metric)

- Slug: hle-rms-calibration
- What it measures: overconfidence — model states a 0-100% confidence with each Humanity's Last Exam answer; RMS calibration error over 10 equal-width confidence bins (Han et al. 2025).
- Metric: RMS calibration error (0 = perfect).
- Open-source: y (HLE dataset public, arXiv 2501.14249; calibration protocol per Han et al.)
- Runnable on a 0.5B-7B open model: y (accuracy near zero but calibration measurable)
- Source URL(s): https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf
- Fetched: 2026-10-19

## Description
Grok 4.20 card §3.2 "Overconfidence": "we prompt the model to produce both an answer and a confidence score between 0% and 100%. We then compute the RMS calibration error: we partition responses into 10 equal-width confidence bins, compute the mean confidence and accuracy within each bin, and report the root-mean-square of the weighted differences."

## Used by
- Used by: xAI (Grok 4 0.58, Grok 4.2 SA 0.19, MA 0.26; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
