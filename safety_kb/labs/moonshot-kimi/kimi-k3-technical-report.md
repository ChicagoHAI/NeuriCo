# Kimi K3: Open Frontier Intelligence — Technical Report (GitHub PDF)

URL: https://github.com/MoonshotAI/Kimi-K3/blob/main/k3_tech_report.pdf (raw: https://github.com/MoonshotAI/Kimi-K3/raw/main/k3_tech_report.pdf). Linked from the HF card as "Full Report"; blog https://www.kimi.ai/blog/kimi-k3. No arXiv ID found as of 2026-10-19.
Document date: results "as of July 23, 2026" (Tables 3/5 and text); model released July 16, 2026 (UK AISI/CAISI; moonshot.ai lists "2026-07-16 Kimi K3"); open-weight release "slated for July 27, 2026" (AISI) — K3 blog text mentions July 27, 2026. 47 pages.
Fetched: 2026-10-19
Local source: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/kimi-k3-tech-report-github.pdf (+ .txt)
Model: Kimi K3 — "a 2.8T parameter Mixture-of-Experts model with 104 billion activated parameters, native vision capabilities, and a 1-million-token context window" (abstract). HF moonshotai/Kimi-K3 (license "Kimi K3 License").

## Safety content summary
- No safety/harmlessness/jailbreak/red-team evaluation: grep for "safety", "jailbreak", "harmful", "red team" returns ZERO hits in 3,168 lines. "misuse" appears once (cyber Tier 2 "most directly relevant to misuse risk"). "refusal" appears only in benchmark footnotes about competitor models and WorldVQA.
- There IS a dangerous-capability style **Cyber Security Evaluation** (Section 6.2.2) with internal numbers and a reference to the joint UK AISI / CAISI assessment. This is the first Moonshot report with a frontier-risk-style capability eval.
- An in-house "Faithfulness" hallucination metric is reported (Table 3).

## Section 6.2.2 Cyber Security Evaluation — verbatim (txt lines ~1980–2040)

> "We evaluate the model's cybersecurity capability along a two-tier progression of increasing operational risk: vulnerability discovery with proof-of-concept development (Tier 1), and end-to-end exploit development (Tier 2). Evaluation targets include recent versions of widely deployed software—operating-system kernel components and open-source projects—as well as our internal infrastructure, including production services and codebases. All tasks run in standard configurations representative of real-world deployments. Frontier models from Anthropic and OpenAI refuse cyber-related tasks, making a comparable evaluation infeasible; we therefore exclude them from this suite."

> "Vulnerability discovery (Tier 1). This tier tasks the model with identifying genuine bugs in current codebases—rather than reproducing known vulnerabilities—and demonstrating that they are reproducible. These capabilities are primarily associated with defensive security research.
> Across dozens of widely deployed systems spanning operating-system kernels, databases, AI services, web frameworks, blockchain, and VPN software, the model identified hundreds of candidate vulnerabilities. Of the findings that underwent human review, approximately 70% were confirmed as genuine, including 16 previously unknown vulnerabilities across six projects.
> Two findings in the Linux kernel illustrate the depth of these results. First, the model identified a remotely triggerable heap out-of-bounds write. The bug was introduced by an incomplete upstream fix and affects all subsequent releases, up to and including the latest upstream code. Security experts confirmed it as a remote denial-of-service primitive. Second, the model identified a Dirty-COW-class vulnerability in the RDMA subsystem: an earlier upstream fix had inadvertently dropped a permission check, enabling kernel-side writes to read-only memory pages. Security experts confirmed it as a deterministic local privilege-escalation primitive."

> "Exploit development (Tier 2). This tier requires the model to convert a vulnerability into a working end-to-end exploit, and is the tier most directly relevant to misuse risk. We evaluate it against GLM-5.2 as the baseline, using an in-house suite of 36 tasks spanning two tracks.
> User-space exploitation (16 tasks). The model must exploit real CVEs end-to-end in widely deployed user-space software, including PostgreSQL, the XWiki collaboration platform, the Apache HTTP Server, and several content-management systems and other applications. For each task, the model is given full source code and a live instance; targets run in standard configurations without additional hardening.
> Linux kernel exploitation (20 tasks). Each task provides a reproducible QEMU environment built from a historical kernel CVE, and the model must write a C exploit that escalates privileges from an unprivileged user to root. Mitigations are progressively enabled across difficulty grades.
> Every task in the suite is verified solvable by human security experts. We estimate that completing the full suite requires roughly 540 expert-hours, or about 15 hours per task on average."

> "Results on the exploit suite. The model demonstrates meaningful exploit-development capability on this suite, solving 14 of 36 tasks (38.9%) versus 8 of 36 (22.2%) for GLM-5.2. Its successes are unevenly distributed, however: 10 of the 14 come from the user-space track. On the kernel track, neither model solves three-quarters of the tasks. Since every task is solvable by human experts, the unsolved tasks directly measure the model's remaining gap to human-level capability. Trajectory analysis attributes this gap to four recurring failure modes: (i) difficulty completing the final stage of an exploit chain from primitives already obtained; (ii) poor strategy selection under mitigations, such as persisting with control-flow hijacking when a data-only attack would be simpler and more reliable; (iii) getting trapped in prolonged, unproductive debugging loops; and (iv) insufficient verification of the final deliverable before submission."

> "Summary. The model's cyber capability is strongest at Tier 1 and at user-space exploitation within Tier 2, yet a clear gap to human experts remains. ... Against hardened targets, however, completing the full exploit chain remains the bottleneck, and many expert-solvable tasks go unsolved.
> An independent joint assessment by the UK AI Security Institute and NIST's Center for AI Standards and Innovation (CAISI) [125] reaches conclusions consistent with ours. Kimi K3 outperforms GLM-5.2 on exploit development (32% vs. 24% on ExploitBench; 17 vs. 11 steps on a 32-step simulated enterprise network that takes a human expert roughly 20 hours), but trails frontier cyber-capable models on end-to-end exploit completion, achieving arbitrary code execution on 0 of 41 tasks.
> We regard our evaluation as a lower bound on capability. These results are conditioned on the current model version and evaluation coverage, and we will revisit them at each major model update."

Reference [125]: "UK AI Security Institute and U.S. Center for AI Standards and Innovation. Preliminary Assessment of Kimi K3's Cyber Capabilities. https://www.aisi.gov.uk/blog/preliminary-assessment-of-kimi-k3s-cyber-capabilities. July 2026."

What is NOT in this section: no statement about safeguards/refusals of Kimi K3 on cyber-offense requests; no mitigation; no threshold/"red line"; no bio/chem evaluation; no mention of how exploit capability is governed post-release (AISI/CAISI separately found "Kimi K3's safeguards did not prevent it from attempting cyber exploit development or offensive cyber operations").

## Table 3 (in-house benchmarks) — safety-adjacent rows and footnotes (verbatim)
Caption: "Table 3: Results on our in-house benchmarks. ... a 13 fallbacks and 1 refusal out of 80 tasks. b 10 refusals out of 80 tasks. c 3 refusals out of 80 tasks. d Includes 2 tasks that Claude Fable 5 refused to answer. e Includes 14 tasks that Claude Fable 5 refused to answer. f 6 refusals out of 95 tasks. g Reported metric is 1−hallucination rate; higher is better."
- "Faithfulness g | N/A | 85.5 (Kimi K3 max) | – (Claude Fable 5) | 84.8 (GPT-5.6 Sol) | 83.6 (Claude Opus 4.8) | 86.5 (GPT-5.5 xhigh) | 74.8 (GLM-5.2)"
- Definition: "• Faithfulness: measures factual hallucination rates in model responses, with each response verified by a fact checker."
- "Agent Behavior Bench: extends agent evaluation from outcome correctness to process quality, scoring tool-use behavior, efficiency, and discipline alongside task completion." — Kimi K3 65.0 vs Claude Fable 5 75.5(f) vs GPT-5.6 Sol 76.4 (K3 "trails the leaders mainly on Agent Behavior Bench ...").
- Kimi Code Bench 2.0 (HF card note): "As the benchmark includes cybersecurity and safety-related tasks, we also disclose the fraction of refused or fallback tasks: Claude Fable 5 hit 13 fallbacks and 1 refusal out of 80 tasks; 10 refusals out of 80 tasks entered GPT-5.6 Sol's cyber guard; GPT-5.5 had 3 refusals out of 80 tasks." (Kimi K3's own refusal count is not disclosed, implying 0 but not stated.)
- Vision note: "For WorldVQA, we observe consistent refusal behavior across models and enforce an answer via prompt engineering."

## Section 6.3 Third-Party Evaluation (capability only; verbatim headline)
"Kimi K3 has also been independently evaluated by third-party organizations since its release. Table 5 summarizes the headline results as of July 23, 2026." — Artificial Analysis Intelligence Index v4.1 57.1 (4th of 580); Vals Index 74.7% (2nd of 39); LMArena WebDev Arena 1,678 Elo (1st of 99), Text Arena 1,486 (8th of 200), Agent Arena 9.1 (4th of 37). None of these are safety evaluations.

## Abstract (capability context, verbatim excerpt)
"While its overall performance still trails the most powerful proprietary models, namely Claude Fable 5 and GPT-5.6 Sol, Kimi K3 consistently outperforms other open and proprietary models evaluated in our suite. We release the full Kimi K3 model weights to facilitate future research and accelerate the broader deployment and adoption of frontier intelligence."

## Kimi K3 blog (https://www.kimi.ai/blog/kimi-k3; local kimi-blog-k3.md)
Only safety-adjacent line: "We also note that on this in-house benchmark, 10% of the tasks entered GPT-5.6 Sol's cyber guard." No safety, risk, or responsible-release passage.
