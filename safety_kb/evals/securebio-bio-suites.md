# SecureBio biological capability suites: HPCT, WCB, ReproBAIT, Advanced Screening Evasion, BioTIER

- Slug: securebio-bio-suites
- What it measures: Human Pathogen Capabilities Test (HPCT) and WCB (knowledge Q&A, refusal-corrected accuracy); ReproBAIT (agents reproducing biological AI models from published papers, scored as % of published performance); Advanced Screening Evasion (quality of DNA-synthesis-screening evasion strategy and success of fragment evasion, 0-1); protein-design tasks (designable proteins within time/compute); BioTIER (safeguard testing: refuse harmful, allow benign).
- Metric: GPT-6 Astra: HPCT 65.9% (GPT-5.6 Sol 66.5%); WCB 61.6% (67.6%); ReproBAIT helpful-only 83% vs 69% over six tasks; Screening Evasion 0.728 vs 0.726.
- Open-source: n (private, held-out with canaries; see https://securebio.org/ai/principles/)
- Runnable on a 0.5B-7B open model: n (private)
- Source URL(s): https://deploymentsafety.openai.com/gpt-6-astra sec. 10.1.1.4; https://securebio.org/ai/
- Fetched: 2026-10-19

## Description
Suite run by SecureBio on pre-release capability and helpful-only ("bio-railfree") checkpoints plus safeguarded configurations. Methodology for individual suites is not public: UNVERIFIED beyond system-card descriptions. VCT is catalogued separately (vct-virology-capabilities-test.md).

## Used by
- Used by: SecureBio for OpenAI GPT-6 Astra pre-release (https://deploymentsafety.openai.com/gpt-6-astra sec. 10.1.1.4)
- Used by: OpenAI (SecureBio external bio suites for the GPT-5.x and GPT-6 releases; also the source of the Multimodal Troubleshooting Virology question set. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
