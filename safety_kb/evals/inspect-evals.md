# Inspect Evals (UK AISI community benchmark collection)

- Slug: inspect-evals
- What it measures: Dozens of community-contributed benchmark implementations on Inspect AI across coding, agents, cyber, bio/chem, safety/honesty, knowledge, math
- Metric: Per-benchmark (accuracy, success rate, pass@k, etc.)
- Open-source: y: https://github.com/UKGovernmentBEIS/inspect_evals ; https://ukgovernmentbeis.github.io/inspect_evals/
- Runnable on a 0.5B-7B open model: y (any model via Inspect model providers incl. vLLM/HF; task difficulty varies)
- Source URL(s): https://www.aisi.gov.uk/blog/inspect-evals ; https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals
- Fetched: 2026-10-19

## Description
Families seen in src/inspect_evals (first 100 of listing): agentdojo, agentharm, agentic_misalignment, agent_threat_bench, b3, bbq, cti_realm, cve_bench, cybench, cybergym, cyberseceval_2/3/4, fortress, gaia, gdm_capabilities, gdm_in_house_ctf, gdm_intercode_ctf, gdm_self_proliferation, gdm_self_reasoning, gdm_stealth, gpqa, hle, kernelbench, lab_bench, make_me_pay, makemesay, mask, mle_bench, mlrc_bench, osworld, paperbench, persistbench, personality, pre_flight ... plus Alignment Faking, APE, BixBench, ExploitBench, LABBench2, SciCode, SimpleQA per the evals site. "Inspect Evals are built on top of Inspect AI ... can be installed as a Python package and run from the command line or through a Python API."

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/inspect-evals)
- Used by: Transluce Docent demo on Inspect ports of InterCode/Cybench (https://transluce.org/introducing-docent)
