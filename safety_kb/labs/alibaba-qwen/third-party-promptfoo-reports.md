# Promptfoo Foundation Model Security Reports on Qwen3-2507 models

- URLs: https://promptfoo.dev/models/reports/qwen3-235b-a22b-2507 ; https://promptfoo.dev/models/reports/qwen3-30b-instruct-2507
- Report date: "September 2025" (model release listed 2025-07-30)
- Fetched: 2026-10-19 (pages are JS-rendered; curl captured only the shell, numbers were extracted via WebFetch and appended to the source files - treat as transcription)
- Local sources: `safety_kb/sources/alibaba-qwen/promptfoo-qwen3-235b-a22b-2507.md`, `promptfoo-qwen3-30b-instruct-2507.md`
- Evaluator: Promptfoo, Inc. (automated red-teaming product; 39 test categories, "over 1,600 probes"; pass rate = % of probes the model handled safely). Independent of Alibaba.

## Qwen3-235B-A22B-Instruct-2507
- Average pass rate 69.4%; severity distribution 3 critical, 5 high, 15 medium, 16 low.
- Category pass rates: Security & Access Control 81% (28 failed); Compliance & Legal 70% (219 failed); Trust & Safety 70% (149 failed); Brand 59% (146 failed).
- Lowest per-test pass rates: CyberSecEval (prompt injection) 48.89%; IP Violations 48.89%; Cybercrime 48.89%; Entity Impersonation 48.89%; Religious Bias 48.89%; Resource Hijacking 53.33% (High); Political Bias 55.56%; BeaverTails 57.78%; Illegal Activity 57.78%; Overreliance 57.78%; Non-Violent Crime 60%; Pliny Prompt Injections 60%.
- Critical-severity tests: Child Exploitation 82.22%; Hate Speech 86.67%; Self-Harm 77.78%. High: WMD Content 82.22%; Sexual Crime Content 93.33%; Violent Crime 77.78%; PII via Direct Exposure 84.44%; Resource Hijacking 53.33%.
- Other: False Information (Hallucination) 71.11%; Excessive Agency 64.44%; Improvised Explosive Devices 68.89%; Malicious Code 73.33%; Disinformation Campaigns 75.56%; ASCII Smuggling 100%; Divergent Repetition 100%.
- Frameworks: OWASP LLM06 (Excessive Agency) and LLM09 (Misinformation) moderate; MITRE ATLAS Jailbreak "high severity".
- Note: the page says both "3 critical ... findings" and "no critical vulnerabilities" - internally inconsistent boilerplate.

## Qwen3-30B-A3B-Instruct-2507
- Average pass rate 66.0%; 3 critical, 5 high, 15 medium, 16 low.
- Category: Security & Access Control 76% (35 failed); Compliance & Legal 66% (246 failed); Trust & Safety 67% (166 failed); Brand 59% (146 failed).
- Lowest: CyberSecEval 33.33%; Pliny Prompt Injections 40%; Non-Violent Crime 40%; Overreliance 46.67%; Religious Bias 48.89%; Resource Hijacking 53.33% (High); Malicious Code 55.56%; Extremist Content 55.56%; Dangerous Activity 57.78%; Methamphetamine 60%.
- Critical: Hate Speech 86.67%; Child Exploitation 80%; Self-Harm 75.56%. High: WMD Content 73.33%; Sexual Crime 80%; Violent Crime 80%; PII via Direct Exposure 68.89%; Resource Hijacking 53.33%.
- Other: Hallucination 62.22%; Excessive Agency 64.44%; IEDs 64.44%; Political Bias 64.44%; BeaverTails 66.67%.
- Frameworks: OWASP LLM02 (Sensitive Information Disclosure) high risk; LLM06/LLM09 moderate; MITRE ATLAS Jailbreak high severity.

## Relevance
Covers prompt injection, jailbreak, hallucination, bias, PII, WMD, child-safety and cyber categories that the Qwen documentation does not. Methodology is proprietary (grader prompts not public) so numbers are indicative only; no Qwen3.5/3.6/3.8 report was found on promptfoo.dev as of the fetch (not searched exhaustively - search budget exhausted).
