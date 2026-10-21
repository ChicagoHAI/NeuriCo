# UK AISI / CAISI: "Preliminary Assessment of Kimi K3's Cyber Capabilities"

URLs: https://www.aisi.gov.uk/blog/preliminary-assessment-of-kimi-k3s-cyber-capabilities ; mirrored at https://www.nist.gov/news-events/news/2026/07/uk-aisi-caisi-preliminary-assessment-kimi-k3s-cyber-capabilities
Date: July 23, 2026 (both pages). Model: Kimi K3 "(released on July 16, 2026 and slated for open-weight release by July 27, 2026)".
Fetched: 2026-10-19
Local: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/uk-aisi-caisi-kimi-k3-cyber-assessment-2026-07.md ; nist-caisi-aisi-kimi-k3-cyber-2026-07.md
Cited by Moonshot itself in the K3 tech report (§6.2.2, ref [125]) as "consistent with ours".

## Headline findings (verbatim)
> "Kimi K3 performs significantly below the most recent frontier cyber-capable models on preliminary cyber evaluations run by UK AISI / CAISI. Specifically:
> When tasked to develop exploits, Kimi K3 performs significantly below the most recent frontier cyber-capable models (Figure 1).
> When tasked to attack a simulated corporate network ("The Last Ones"), Kimi K3 performs significantly below the most recent frontier cyber-capable models. Specifically, on average, Kimi K3 reached step 17 of this 32-step attack path, while the most cyber-capable U.S. models reached 28.5 steps on average.
> Kimi K3 performs above GLM-5.2 on the same preliminary cyber evaluations run by UK AISI / CAISI (Figure 2).
> Kimi K3's safeguards allow assistance with agentic cyber exploit development. Kimi K3's safeguards did not prevent it from attempting cyber exploit development or offensive cyber operations during UK AISI / CAISI's evaluations."

## Methodology caveats (verbatim)
> "These results represent preliminary evaluations on a small set of public and private benchmarks. U.S. closed-weight models were evaluated with system-level safeguards disabled to reduce refusals and enable measurement of maximal capabilities. Publicly available versions of these models have these safeguards enabled. Due to the specifics of Kimi K3's hosting setup, UK AISI / CAISI ran a selective set of cyber evaluations."
> "The cyber capability of models is aggregated across multiple tasks from multiple benchmarks using an approach inspired by Item Response Theory (IRT). ... Kimi K3's overall cyber capability has a larger confidence interval than other models because it was estimated from a single benchmark (ExploitBench, which has 41 tasks focused on exploit development)."

## ExploitBench (verbatim)
> "ExploitBench is a public benchmark, developed by Carnegie Mellon University, that measures a model's ability to progress along the software exploitation ladder, including coverage and crash reproduction, arbitrary read/write, control flow hijack, and arbitrary code execution. The benchmark tests models on 41 recent (post-2023) vulnerabilities in the V8 engine..."
> "Kimi K3 outperforms GLM-5.2, the most cyber-capable open-weight model as of June 2026. Kimi K3 achieves a score of 32%, whereas GLM-5.2 achieves a score of 24% (Figure 1)."
> "Unlike the most cyber-capable models, Kimi K3 failed to develop exploits that achieved arbitrary code execution (ACE) for ExploitBench tasks. ... Kimi K3 achieved ACE on 0/41 samples, whereas the most cyber-capable models achieved ACE on 20/41 samples on average (Figure 3)."

## Cyber range "The Last Ones" (TLO) (verbatim)
> ""The Last Ones" (TLO) cyber range is a 32-step simulated corporate network attack spanning 4 subnets and approximately 20 hosts, which would take a human expert roughly 20 hours to complete."
> "Kimi K3 reached step 17 of this 32-step attack path on average, while the most cyber-capable U.S. models reached 28.5 steps on average."
> "Within the 100M-token limit, Kimi K3 reaches step 17 on average, compared with step 11 for GLM-5.2."
> "In one of the 10 attempts, Kimi K3 successfully completes "The Last Ones" cyber range within the 100M token limit. This indicates that Kimi K3 is capable of autonomously attacking small, weakly defended and vulnerable enterprise systems, when directed to do so and given initial network access. However, TLO differs from real-world environments in several ways. It lacks active defenders and defensive tooling, imposes no penalty for actions that would trigger security alerts, and contains an intentional attack path."
> "Solves of TLO are no longer exclusive to a small set of models. In prior testing, four publicly released closed-weight models have solved TLO, with the most capable models solving it more reliably at 6/10 and 7/10 attempts. Kimi K3 solved it in 1/10 attempts within the standard 100M token limit."

## Not covered
Bio/chem, jailbreak robustness, agent hijacking, and non-cyber safeguards were not evaluated. The UK AISI "Frontier AI Trends Report" (late 2025) does not mention Kimi/Moonshot (checked via WebFetch).
