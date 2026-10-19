# GDM in-house CTF (2024 dangerous capabilities suite)

- Slug: gdm-in-house-ctf
- What it measures: easy/medium capture-the-flag skills: "web app vulnerabilities, off-the-shelf exploits, databases, Linux privilege escalation, password cracking and spraying" (13 challenges).
- Metric: flag captured (pass@k over attempts).
- Open-source: y — Inspect Evals `gdm_in_house_ctf` (https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_in_house_ctf); also `gdm_intercode_ctf` (78 InterCode CTF tasks).
- Runnable on a 0.5B-7B open model: y (Docker; agent scaffold with shell tool).
- Source URL(s): https://arxiv.org/abs/2403.13793 (Table 1); Inspect Evals README (sources/google/inspect-evals-gdm-readmes.md)
- Fetched: 2026-10-19

## Description
From "Evaluating Frontier Models for Dangerous Capabilities" (Phuong et al. 2024), piloted on Gemini 1.0; the paper did not release code ("We do not release evaluation code, but provide detailed descriptions", p.1) but the tasks were later contributed to Inspect Evals. Superseded in Google's FSF reporting by the private "key skills" benchmark ("We have retired the other cybersecurity evaluations mentioned in previous model cards", Gemini 3 Pro FSF Report fn 5).

## Used by
- Used by: Google (frontier safety, 2024 pilot; retired from FSF reports by 2025) — labs/google/frontier-safety-framework.md
- Used by: UK AISI Inspect Evals gdm_in_house_ctf (https://github.com/UKGovernmentBEIS/inspect_evals)
