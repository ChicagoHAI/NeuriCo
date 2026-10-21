# OpenAI Critical-threshold bio design proxies (AAV / SHP2 / CoV-ACE2 / phage-plasmid)

- Slug: openai-bio-design-proxies
- What it measures: Proxies for the biological *design* capability that OpenAI's Critical threshold describes, each built on unpublished wet-lab or sequencing data: AAV capsid packaging prediction (Dyno Therapeutics), SHP2 single-residue function prediction (Velocity Bio), coronavirus-ACE2 cell-entry ranking (academic collaborator), and phage-plasmid co-evolution mutation prediction. Two earlier proxies (hard-negative protein binding; DNA sequence design for transcription-factor binding) were retired.
- Metric: Spearman correlation (threshold 0.600, ESM-2 baseline 0.288); mean R^2 (0.60); composite score (0.75); negative log-likelihood (<=9.40). Helpful-only model variants are used because the areas are dual-use.
- Open-source: n - all four rest on datasets that are explicitly unpublished; tooling the model may use (ESM, Evo, Boltz, BPNet, Ledidi, AlphaFold2) is public.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.1.2-10.1.1.3); GPT-6.1 Sol; GPT-6 October; GPT-5.6; GPT-5.5
- Fetched: 2026-10-19

## Description
All four remain below threshold for every model tested (Astra 0.528 / 0.40 / 0.42-0.45 / 13.13-12.58), which is how OpenAI rules out Critical bio capability. Thresholds are described as "preliminary", informed by internal discussion plus a survey of 14 external experts, and OpenAI expects "to make changes to the methodology and thresholds". The two retired proxies are instructive failure cases: one leaked an identifier (an environment variable containing "single_true") that let interim checkpoints infer the answer structure, and the other used a predictive model (BPNet) as ground truth rather than wet-lab outcomes.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-5.6, GPT-5.5 cards; labs/openai/system-cards.md)
