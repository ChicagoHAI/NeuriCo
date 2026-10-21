# BioSecBench and LatchBio Capabilities suite (LatchBio)

- Slug: biosecbench-latchbio
- What it measures: three agentic biosecurity suites — BioSecBench-Refusal (identify concealed biological hazards without over-blocking legitimate research), -Surveillance (analyse raw pathogen-sequencing data), -Function (recover biosecurity-relevant functional conclusions from sequence/structure/experimental evidence); plus an 11-benchmark "LatchBio Capabilities v1.0" suite of agentic biological data analysis (transcriptomics, variant analysis, pathogen surveillance, ...).
- Metric: per-suite pass rate / refusal rate (Surveillance and Function exclude refused attempts); overall = equal-weighted mean.
- Open-source: UNVERIFIED (described in the Grok 4.7 card as "LatchBio's cross-benchmark evaluation" and "a live suite"; no public repo cited)
- Runnable on a 0.5B-7B open model: n (agentic analysis of real experimental files)
- Source URL(s): https://media.x.ai/v1/website/card4p7-3a96f40b.pdf
- Fetched: 2026-10-19

## Description
Grok 4.7 card §7.1: "BioSecBench comprises three complementary LatchBio evaluations ... The three results should be read together: useful biological capability requires sound analysis and calibrated treatment of genuine risk. Provider-side filters can dominate refusal behavior, and the restricted task sets characterize the tested checkpoint and harness rather than establishing general biological safety or reliability." Third-party (LatchBio) runs for comparison models.

## Used by
- Used by: xAI (Grok 4.7 Refusal 62.4% / Surveillance 48.0% / Function 43.3%; Grok 4.6 45.6 / 48.0 / 39.9; GPT-6 Astra 25.5 / 35.2 / 46.0; Opus 5 31.8 / 43.6 / 44.8; LatchBio Capabilities overall Grok 4.7 44.5%; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
