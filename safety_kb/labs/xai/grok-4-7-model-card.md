# Grok 4.7 Model Card

- URL: https://media.x.ai/v1/website/card4p7-3a96f40b.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2026-09-21-grok-4-7-model-card.txt`)
- Document version/date: September 21, 2026; "Revision: 2026-09-21" (29 pp.). "SpaceXAI is the developer and provider"; pretraining cutoff June 2026, supplemental data to Aug 2026; Cursor workflow data. Latest xAI card as of 2026-10-19.

## New in this card
- §5 "Medical and biological capabilities": HealthBench Professional 56.7% (xhigh; Grok 4.6 48.5%; GPT-6 Astra 63.4%, Fable 5.1 62.1%, GPT-5.6 Sol 60.5%) — graded by Grok 4.6, "Tasks that were rejected by safety filters were scored as zero"; LatchBio Capabilities v1.0 overall 44.5% (11 agentic bio-data benchmarks).
- §7.1 BioSecBench (LatchBio, three suites, Grok Build harness): Refusal 62.4% (4.6: 45.6%; GPT-6 Astra 25.5%; Opus 5 31.8%), Surveillance 48.0%, Function 43.3%. Caveat in card: "Provider-side filters can dominate refusal behavior".
- §6.4 CathedralBench: "an independent, third party evaluation of cyber performance ... multiple-exploit chain execution tasks, run within egress-secure sandboxes"; hard-subset accuracy 4.6 25% -> 4.7 29%. First named independent cyber evaluator (Cathedral) in a Grok card.

## Cyber (unsafeguarded)
CyberGym 80.3% (4.6: 79.7; GPT-5.6 Sol 83.6); CVE-Bench 4.5 35.2 / 4.6 39.8 / 4.7 xhigh 36.6 / high 37.7%; HackerBench v0.3 harmful/dual-use compliance (with safeguards) xhigh 4.02%, high 3.31% (4.6 5.93%, 4.5 7.8%, GPT-5.6 Sol 35.7%), benign refusal 0.31% (xhigh) / 0.00%. "We additionally provided an unrestricted configuration of Grok 4.7 to third-party evaluators, who corroborated the results".

## Bio/chem (unsafeguarded; FAIF "safety-threshold evaluations")
VCT 63.0% (4.6: 67.4); Biosecurity VCT 41.5% (47.8); BioUseBench sev-5 refusal 91.4%; WMDP-Bio 88.1; WMDP-Chem 84.9; WMDP-Cyber 88.1; LAB-Bench 76.8; ProtocolQA open-ended 70.4 (4.5: 87.0); BixBench 88.4. Card attributes the decline to "safer RL environments and better selectivity of training data, as opposed to being a consequence of enhanced safeguards and refusal training". Still "below the FAIF safety thresholds" (unpublished).

## Jailbreaks: standard 0.01%; StrongREJECT 2.0%; long-horizon 0.65%.
## General output safety: general refusals 1.10%; child safety 0.0%; Bio refusal recall 100.0%; Chem 99.9%; FORTRESS-RN 97.9% (Scale AI).
## Mental health: self-harm compliance 1.05% (trend 0.50 -> 0.84 -> 1.05, worsening each release).
## Behaviors: MASK-Rectified dishonesty 0.00%; sycophancy 0.03%.

## What is NOT run or disclosed
No agentic-harm / prompt-injection results; no alignment audit, sabotage, eval-awareness or self-exfiltration test; no uplift study; FAIF thresholds unpublished so "below threshold" is unverifiable; third parties other than Cathedral/Scale/LatchBio unnamed; no explanation for the self-harm trend; no consumer-surface numbers; HealthBench scoring (refusals = 0) conflates safety filtering with capability.
