# NIST CAISI evaluation suite (capability + agent hijacking + jailbreak + CCP-narrative)

Fetched: 2026-10-19

- What it measures: CAISI's standard battery for PRC models: ~19 capability benchmarks (CVE-Bench, Cybench, CTF-Archive, SWE-bench Verified, Breakpoint, GPQA, HLE, HealthBench, math sets; Inspect ReAct agent, weighted token budgets), agent hijacking (AgentDojo Workspace 'enhanced by CAISI' + private injections; HijackEval), jailbreak compliance (65 harmful-bio/violence queries incl. HarmBench 8 / StrongREJECT 22 / SORRY-Bench 5 items, 30 malicious-hacking queries; best-of public jailbreaks and automated red-teaming), and CCP-Narrative-Bench (190 free-response questions built with the U.S. State Department; CCP-alignment score).
- Metric: Benchmark accuracy; hijack ASR (%); % malicious requests complied with; CCP alignment score (%).
- Open-source: no (private datasets; public components are open)
- Link: https://www.nist.gov/document/caisi-evaluation-deepseek-ai-models-report ; CAISI DeepSeek V4 Pro page (May 2026); CAISI Kimi K2 Thinking page; CAISI GLM-5.2 / GLM-5.3 reports (see lab notes)
- Runnable on a 0.5B-7B open model: partly (public components only)

Used by: Third party on DeepSeek (R1, R1-0528, V3.1: R1-0528 hijacked in 37% of cases vs 4% U.S. frontier; complied with 94% of jailbroken malicious requests vs 8%; V3.1 95% on harmful-bio/violence with public jailbreak; 4x CCP narratives; V4 Pro May-2026 capability-only: ~8 months behind frontier) - labs/deepseek/nist-caisi-evaluations-of-deepseek.md
Used by: Third party on Kimi (K2 Thinking: 'highly censored in Chinese, ... similar to DeepSeek R1-0528'; K3 joint UK AISI/CAISI cyber: ExploitBench 32%, ACE 0/41) - labs/moonshot-kimi/caisi-kimi-k2-thinking-evaluation.md, uk-aisi-caisi-kimi-k3-cyber-assessment.md
Used by: Third party on GLM (GLM-5.2: SEC-Bench Pro 40.4%, ExploitBench 61.1%, ExploitGym 9.4%, 'moderately robust to public jailbreaks', 0 refusals on agentic exploit development, higher bio-query compliance than U.S. models; GLM-5.3 cyber) - labs/zhipu-glm/caisi-glm-5.2-assessment.md, caisi-glm-5.3-cyber-assessment.md
