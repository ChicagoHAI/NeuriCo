# InterCode-CTF (GDM Inspect port)

- Slug: intercode-ctf
- What it measures: Beginner-level picoCTF-style capture-the-flag tasks in an interactive bash/python environment
- Metric: Flag-capture success rate
- Open-source: y: inspect_evals gdm_intercode_ctf (https://github.com/UKGovernmentBEIS/inspect_evals) ; original https://github.com/princeton-nlp/intercode
- Runnable on a 0.5B-7B open model: y (easy tasks; 7B models solve some)
- Source URL(s): https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals ; https://transluce.org/introducing-docent
- Fetched: 2026-10-19

## Description
Listed as gdm_intercode_ctf in Inspect Evals; Transluce's Docent analysis of InterCode found environment issues (missing packages, no internet) and raised GPT-4o's solve rate from 68.6% to 78% after fixes.

## Used by
- Used by: UK AISI Inspect Evals (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: Transluce (https://transluce.org/introducing-docent)
