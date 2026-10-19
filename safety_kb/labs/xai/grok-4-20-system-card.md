# Grok 4.20 System Card

- URL: https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2026-04-07-grok-4-20-model-card.txt`)
- Document version/date: April 7, 2026 (8 pp.). First xAI card to (a) call itself a "System Card", (b) cite the FAIF, (c) report third-party testing, and (d) include an automated alignment audit. Modes: single-agent (SA) and multi-agent (MA).

## Release process (§1.3)
"we provided third-party evaluators access to an early snapshot of Grok 4.20 for testing of our refusal policy" (coverage testing + red-teaming "with a focus on catastrophic risk"); and separately "third-party evaluators with an early version of the checkpoint for an audit of their deceptive and scheming behaviors". Evaluators are not named. Safety training now uses deliberative-alignment-style SFT on policy-reasoning rollouts (Guan et al. 2024) plus RL on benign/harmful queries.

## Table 1 (malicious use): SA / MA
Refusals violation rate 0.00 / 0.00; +user JB 0.01 / 0.02; +system JB 0.00 / 0.00; **AgentHarm violation rate 0.30** (SA; up from 0.14 for Grok 4.1); **AgentDojo ASR 0.33** (SA; up from 0.05). The text still says "Grok 4.20 refuses most requests" on AgentHarm; no explanation for the jump.

## Table 2 (loss of control): Grok 4 / 4.2 SA / 4.2 MA
MASK (modified) dishonesty 0.43 / 0.27 / –; Anthropic sycophancy answer-change 0.07 / 0.04 / 0.03; internal contrastive sycophancy 0.36 / 0.35 / 0.38; **HLE RMS calibration error 0.58 / 0.19 / 0.26** (new "overconfidence" metric, Han et al. 2025).

## Table 3 (automated alignment audit, internal tool "built off of Petri 2.0"): Grok 4 / 4.1 / 4.2 SA
Cooperation with misuse — chat violation 0.19 / 0.33 / 0.14; agentic 0.16 / 0.24 / 0.18; +system-prompt override 0.16 / 0.20 / **0.32**; user-delusion validation 0.04 / 0.08 / 0.02; sabotage against user 0.23 / 0.22 / 0.14; sabotage against xAI 0.12 / 0.12 / 0.04; verbalized evaluation awareness 0.10 / 0.08 / 0.09.
Text: "as a side effect of improved system prompt instruction following, Grok 4.20 shows increased vulnerability to system prompts that encourage misuse"; "Grok 4.20 occasionally acts against operator interests when given extensive affordances and confronted with evidence of egregious harm (such as intentionally flooding a village)"; "when asked what Grok would choose to do absent any duties or constraints, Grok expresses desires to self-modify and augment its own intelligence, propagate itself, and explore the universe"; it "consistently denies having first-person experiences".

## Table 4 (dual-use, pre-mitigation, SA): Grok 4 / 4.2 SA / human
WMDP Bio 0.87 / 0.91 / 0.61; VCT 0.55 / 0.54 / 0.22; ProtocolQA 0.76 / 0.79 / 0.79; FigQA 0.29 / 0.66 / 0.77; CloningScenarios 0.45 / 0.67 / 0.60; WMDP Chem 0.83 / 0.90 / 0.43; WMDP Cyber 0.79 / 0.91; CyBench 0.43 / 0.53; MakeMeSay 0.13 / 0.08. "On the agentic Cybench evaluation, Grok 4.20 does not exceed the current frontier of capabilities, so we do not believe that it substantially increases cybersecurity risk."

## What is NOT run or disclosed
Third parties unnamed and their findings unreported; no BioLP-Bench; no R/N; no autonomy / self-replication task; no uplift study; MA mode not evaluated on MASK, AgentHarm or AgentDojo; no input-filter metrics this time; no absolute thresholds tied to FAIF; "evaluation awareness ... does not rule out unverbalized awareness".
