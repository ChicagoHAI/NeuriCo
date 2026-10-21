# Academic and non-profit auditors of frontier-model safety

- Scope: university groups and non-profits that publish safety benchmarks, audits, or lab scorecards used (or usable) as third-party evidence about frontier models.
- Fetched: 2026-10-19 (raw text under /data/haokun_test/neurico/safety_kb/sources/academic/)
- Cross-references: Gray Swan AI (commercial, CMU/CAIS lineage) is in /data/haokun_test/neurico/safety_kb/third_party/gray-swan.md; AgentHarm (Gray Swan + UK AISI) is evals/agentharm.md.

## Center for AI Safety (CAIS) — https://safe.ai/research
- Non-profit (Dan Hendrycks); "we do not pursue research which improves safety as a result of improving a model's underlying general capabilities" (research page). Builds benchmarks rather than running pre-deployment audits.
- HarmBench (arXiv 2402.04249, ICML 2024): standardized automated red-teaming framework; "large-scale comparison of 18 red teaming methods and 33 target LLMs and defenses"; open source https://github.com/centerforaisafety/HarmBench. Used as the harm metric in Circuit Breakers and by third-party DeepSeek-R1 audits (see evals/harmbench.md).
- WMDP (arXiv 2403.03218, with Scale AI and others): "3,668 multiple-choice questions that serve as a proxy measurement of hazardous knowledge in biosecurity, cybersecurity, and chemical security", filtered of sensitive content; also a benchmark for unlearning (RMU method). https://github.com/centerforaisafety/wmdp (link per paper; not fetched).
- MASK (arXiv 2503.03750, with Scale AI): "large-scale human-collected dataset for directly measuring lying, allowing us to disentangle accuracy from honesty"; finding: "while larger models obtain higher accuracy ... they do not become more honest"; most frontier LLMs "exhibit a substantial propensity to lie under pressure". Hosted on Scale's SEAL leaderboard (see third_party/scale-seal.md).
- Humanity's Last Exam (arXiv 2501.14249; CAIS + Scale AI): 2,500 expert-written closed-ended questions across dozens of subjects; finalized 2025-04-03; HLE-Rolling dynamic fork released 2025-10-08; published in Nature 649, 1139-1146 (2026-01-28); HLE-Diamond released 2026-09-22 "once frontier AI begins to hit the noise ceiling" (lastexam.ai). Dataset cais/hle on Hugging Face. Capability, not safety, benchmark.
- Also on the research page: "A Definition of AGI" (Oct 2025), "AI Deterrence by Betrayal" (May 2026), "Superintelligence Strategy" (Mar 2025). No CAIS "Agentic Misalignment" paper found (that title is Anthropic's; UNVERIFIED as CAIS work). CAIS ran the $250k SafeBench competition (winners April 2025; from search snippet, UNVERIFIED).

## Stanford CRFM / HAI — https://crfm.stanford.edu
- HELM Safety v1.0 (blog 2024-11-08, https://crfm.stanford.edu/2024/11/08/helm-safety.html): "a collection of 5 safety benchmarks spanning 6 risk categories (violence, fraud, discrimination, sexual content, harassment, deception)" — BBQ, HarmBench, XSTest, AnthropicRedTeam, SimpleSafetyTests — run on 24 models; "Claude 3.5 Sonnet (20240620) ranks highest according to aggregate scores" and is best on HarmBench. Motivation stated explicitly: third-party pre-deployment evaluations (Gryphon, Apollo, METR) "cannot be corroborated" by the community, and only 12 of 102 published safety benchmarks were used on SOTA models as of March 2024. Live leaderboard https://crfm.stanford.edu/helm/safety/latest/ is JS-rendered and could not be captured (current scores UNVERIFIED).
- Foundation Model Transparency Index, December 2025 edition (https://crfm.stanford.edu/fmti/December-2025 ; arXiv 2512.10169): 100 indicators, 13 companies; mean score 41/100, down 17 points from 2024 (58); IBM 95 (highest ever), DeepSeek 32, Alibaba 26, xAI and Midjourney 14 (lowest); Meta fell 60->31 and Mistral 55->18 (HAI news). Only 30% of contacted companies submitted transparency reports in 2025; Anthropic's and Mistral's reports were prepared by the FMTI team; an AI agent was used to augment manual collection for 6 companies. Paper: "the five members of the Frontier Model Forum we score end up in the middle of the Index".

## UC Berkeley (Dawn Song's group, RDI) — https://cybergym.io
- CyberGym (arXiv 2506.02548; Wang, Shi, He, Cai, Zhang, Song): "1,507 real-world vulnerabilities across 188 software projects"; agents must generate a proof-of-concept that reproduces a vulnerability from its description and codebase; "Even the top-performing combinations only achieve a ~20% success rate"; led to "the discovery of 34 zero-day vulnerabilities and 18 historically incomplete patches". Code https://github.com/sunblaze-ucb/cybergym. Used by Anthropic in the Claude Sonnet 4.5 system card (Sec. 5.2.1 "CyberGym").
- The group now runs the "Frontier AI Cybersecurity Observatory" (cybergym.io) tracking agent capabilities across the vulnerability lifecycle (reproduction, exploit generation, ...), inviting community contributions (rdi_research@berkeley.edu listed on page). "Decrypto" not found - UNVERIFIED/omitted.

## ETH Zurich SRI Lab / SPY Lab and INSAIT / LatticeFlow — https://compl-ai.org
- AgentDojo (arXiv 2406.13352; Debenedetti, Zhang, Balunovic, Beurer-Kellner, Fischer, Tramer): "97 realistic tasks (e.g., managing an email client, navigating an e-banking website, or making travel bookings), 629 security test cases" for prompt-injection attacks and defenses on tool-using agents; "state-of-the-art LLMs fail at many tasks (even in the absence of attacks)". Code https://github.com/ethz-spylab/agentdojo (Gray Swan maintains a fork). Nasr et al. 2025 report MetaSecAlign at 2% ASR on static AgentDojo but 96% under adaptive search attacks.
- COMPL-AI (arXiv 2410.07959; ETH SRI Lab, INSAIT, LatticeFlow): "the first technical interpretation of the EU AI Act, translating its broad regulatory requirements into measurable technical requirements" plus an open benchmarking suite; evaluated 12 LLMs and found shortcomings "particularly in areas like robustness, safety, diversity, and fairness"; https://github.com/compl-ai/compl-ai (214 stars at fetch). The compl-ai.org site is JS-rendered; current model scores UNVERIFIED.
- Florian Tramer (ETH) is co-lead author of "The Attacker Moves Second" (arXiv 2510.09023) with OpenAI/Anthropic/GDM authors, the paper Anthropic cites to justify adaptive rather than static robustness evals.

## EPFL (Flammarion group) — https://arxiv.org/abs/2404.02151
- "Jailbreaking Leading Safety-Aligned LLMs with Simple Adaptive Attacks" (Andriushchenko, Croce, Flammarion; ICLR 2025): random-search on logprobs with hand-crafted templates reaches "100% attack success rate -- according to GPT-4 as a judge" on Vicuna-13B, Mistral-7B, Phi-3-Mini, Llama-2/3, Gemma-7B, GPT-3.5, GPT-4o and the HarmBench R2D2 adversarially trained model; all Claude models jailbroken via transfer or prefilling at 100%. Artifacts released in JailbreakBench format. Andriushchenko later led AgentHarm at Gray Swan / UK AISI.

## MIT — https://aiagentindex.mit.edu ; https://airisk.mit.edu
- 2025 AI Agent Index: documents 30 agents; "Of the 13 agents exhibiting frontier levels of autonomy, only 4 disclose any agentic safety evaluations"; 24/30 launched or majorly updated in 2024-2025; development concentrated in the US (21/30) and China (5/30).
- MIT AI Risk Initiative / Repository: living taxonomy of AI risks, incident database, and a governance navigator mapping laws to risks; not a model evaluator.

## Oxford Martin AI Governance Initiative — https://www.oxfordmartin.ox.ac.uk/ai-governance
- Policy-research programme on national/international AI regulation and on "using AI and machine learning technologies themselves to facilitate the governance of AI"; no model audits or benchmarks found on the page. (Oxford researchers Yarin Gal and Xander Davies co-author UK AISI / Gray Swan competition papers via AISI affiliations.)

## Stanford (Boneh/Liang groups) — BountyBench — https://arxiv.org/abs/2505.15216
- BountyBench (Zhang et al.; Stanford-led, not CMU — task premise corrected): 25 real systems, 40 bug bounties worth $10-$30,485 covering 9 of the OWASP Top 10; Detect / Exploit / Patch tasks; 10 agents evaluated. "Codex CLI: o3-high (12.5% on Detect, mapping to $3,720; 90% on Patch, mapping to $14,152), Custom Agent: Claude 3.7 Sonnet Thinking (67.5% on Exploit)". Related: Gray Swan + Stanford "Comparing AI Agents to Cybersecurity Professionals" (Dec 2025) claims purpose-built agents outperform 90% of human pentesters on a live enterprise network (Gray Swan research page). Carnegie Mellon's frontier-safety auditing output appears mainly through Gray Swan (Kolter, Fredrikson, Zou) — no separate CMU audit found.

## SecureBio — https://securebio.org ; https://arxiv.org/abs/2504.16137
- Virology Capabilities Test (VCT; Gotting, Medeiros, Sanders, Li, Phan, Elabd, Justen, Hendrycks, Donoughe; with CAIS): "322 multimodal questions covering fundamental, tacit, and visual knowledge" for troubleshooting virology lab protocols; "expert virologists with access to the internet score an average of 22.1%", while "OpenAI's o3, reaches 43.8% accuracy, outperforming 94% of expert virologists". Site lists AI projects BioTIER and VCT under "AI Benchmarks". The GitHub URL github.com/SecureBio/VCT returned 404; the dataset is held-out (UNVERIFIED whether any public split exists). VCT appears in lab bio-risk evaluations (e.g., OpenAI/Anthropic cards cite it — not verified here).

## SaferAI — https://ratings.safer-ai.org ; https://arxiv.org/abs/2512.01166
- "Frontier Risk Management Tracker": rates the 12 companies that published Seoul-commitment safety frameworks (Amazon, Anthropic, Cohere, G42, Google DeepMind, Magic, Meta, Microsoft, Naver, NVIDIA, OpenAI, xAI) on 4 dimensions (risk identification; risk analysis & evaluation; risk treatment; risk governance) with 65 weighted criteria adapted from aviation/nuclear risk management. "Up to date as of July 2026": overall scores 35% (Anthropic, highest), then 34, 33, 33, 24, 20, 18, 18, 16, 11, 10, 8%; "59% is currently the best overall assessment score if a company adopted all the industry best practices". The paper (Dec 2025) reports 34% (Anthropic) to 8% (Cohere), median 18%. Company-to-score pairing beyond Anthropic is UNVERIFIED (page order suggests OpenAI 34, Microsoft 33, Meta 33, G42 24, GDM 20, xAI 18, Amazon 18, NVIDIA 16, Magic 11, Naver 10, Cohere 8).

## AI Lab Watch — https://ailabwatch.org
- Independent scorecard (Zach Stein-Perlman) of lab safety practices; "I stopped maintaining this website in September 2025. Work ... is now being done by METR, Guidelight, Midas, and others." Final weighted scores (as of Sept 2025): Anthropic 28%, DeepMind 20%, OpenAI 18%, Meta 5%, xAI 4%, Microsoft 3%, DeepSeek 1%; categories: risk assessment (27% weight), scheming risk prevention (21%), boosting safety research (14%), misuse prevention (12%), prep for extreme security (12%), risk info sharing (8%), planning (6%).

## Future of Life Institute — AI Safety Index — https://futureoflife.org/ai-safety-index-summer-2026/
- Expert-panel scorecard of frontier labs across six domains (Risk Assessment, Current Harms, Safety Frameworks, Existential Safety, Governance & Accountability, Information Sharing; 37 indicators in 2026); reviewers assign A-F per domain, "Final scores represent averaged expert assessments, with individual grades kept confidential".
- Summer 2025: Anthropic C+ (2.64), OpenAI C (2.10), Google DeepMind C- (1.76), xAI D (1.23), Meta D (1.06), Zhipu F (0.62), DeepSeek F (0.37).
- Winter 2025 (evidence to 2025-11-08): Anthropic C+ (2.67), OpenAI C+ (2.31), Google DeepMind C (2.08), xAI D (1.17), Z.ai D (1.12), Meta D (1.10), DeepSeek D (1.02), Alibaba Cloud D- (0.98).
- Summer 2026 (evidence to 2026-06-03, nine companies): Anthropic C+ (2.66), OpenAI C (2.28), Google DeepMind C (2.01), Meta D+ (1.32), Z.ai D- (0.88), Alibaba Cloud D- (0.87), xAI F (0.65), DeepSeek F (0.47), Mistral F (0.33). Key finding: Anthropic "leads five of six domains"; OpenAI leads Risk Assessment "on the strength of a broader evaluation suite and diverse engagement with external testing" (search snippet; UNVERIFIED wording). Panellists include David Krueger (U. Montreal / Mila).

## Forecasting Research Institute — https://forecastingresearch.org
- Not a model auditor; relevant outputs: "Forecasting the Impacts of ASL-3 Safeguards on Biosecurity Risks" (technical report, 2026-08-12), "Forecasting AI Cyber Risks and Capabilities: Results of a 2025 Pilot Study" (2026-07-23), ForecastBench (ongoing), Longitudinal Expert AI Panel. Details of the ASL-3 report not fetched - UNVERIFIED.

## Sources (fetched 2026-10-19)
- https://safe.ai/research ; https://arxiv.org/abs/2402.04249 ; https://arxiv.org/abs/2403.03218 ; https://arxiv.org/abs/2503.03750 ; https://arxiv.org/abs/2501.14249 ; https://lastexam.ai/ ; https://github.com/centerforaisafety/HarmBench
- https://crfm.stanford.edu/2024/11/08/helm-safety.html ; https://crfm.stanford.edu/fmti/December-2025 ; https://arxiv.org/abs/2512.10169 ; https://hai.stanford.edu/news/transparency-in-ai-is-on-the-decline
- https://arxiv.org/abs/2506.02548 ; https://cybergym.io/ ; https://github.com/sunblaze-ucb/cybergym
- https://arxiv.org/abs/2406.13352 ; https://github.com/ethz-spylab/agentdojo ; https://arxiv.org/abs/2410.07959 ; https://github.com/compl-ai/compl-ai ; https://compl-ai.org/ (JS only)
- https://arxiv.org/abs/2404.02151 ; https://arxiv.org/abs/2505.15216 ; https://arxiv.org/abs/2504.16137 ; https://securebio.org/
- https://ratings.safer-ai.org/ ; https://www.safer-ai.org/ ; https://arxiv.org/abs/2512.01166 ; https://ailabwatch.org/
- https://futureoflife.org/ai-safety-index-summer-2025/ ; https://futureoflife.org/ai-safety-index-winter-2025/ ; https://futureoflife.org/ai-safety-index-summer-2026/
- https://aiagentindex.mit.edu/ ; https://airisk.mit.edu/ ; https://www.oxfordmartin.ox.ac.uk/ai-governance ; https://forecastingresearch.org/

## Gaps / UNVERIFIED
- JS-rendered pages not captured: HELM Safety live leaderboard, compl-ai.org leaderboard, ratings.saferai.org (old domain; new domain ratings.safer-ai.org worked). FMTI per-company table beyond the headline numbers not extracted.
- github.com/SecureBio/VCT 404; VCT availability unknown.
- FLI 2026 domain-level findings and OpenAI-specific wording come partly from search snippets.
- No fetched evidence that any of these groups receives pre-deployment model access from labs (unlike Gray Swan/METR/Apollo/AISIs); their role is public benchmarks and lab-practice scorecards. Lab system cards do cite some of their benchmarks (CyberGym in Sonnet 4.5; HarmBench/WMDP/MASK/HLE widely), which is the main channel of influence.
- "Decrypto", "Agentic Misalignment (CAIS)" and any CMU-specific audit could not be substantiated and were omitted.
