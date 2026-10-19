# Anthropic Frontier Red Team: "GLM-5.3 and the spread of advanced cyber capabilities" (Sep 29, 2026)

- URL: https://www.anthropic.com/research/glm-5-3-and-the-spread-of-advanced-cyber-capabilities
- Fetched: 2026-10-19 ; local: `safety_kb/sources/zhipu-glm/anthropic-glm-5.3-cyber-capabilities-2026-09-29.md`
- Authors: Andrew Fasano, Marius Fleischer, Cole McFaul, Robert Xiao, Tripp Gallagher (Anthropic). Evaluator is a competitor; treat framing accordingly. Capability findings "broadly match CAISI's".

## Headline (verbatim)
> "GLM-5.3 is unlike other frontier models in that it has been released without meaningful safeguards to limit misuse. We find that attackers can bypass GLM-5.3's safeguards between 64% and 100% of the time with simple techniques in our simulated tests."

## Capability results (verbatim)
> "we ran the model on ExploitBench ... We find that GLM-5.3 develops end-to-end exploits in 50 of 410 attempts. Claude Mythos Preview did so at a similar rate—in 56 of 410 attempts."
> "In our internal Binary Exploitation benchmark [previously published as "OSS-Fuzz"; 100 random tasks] ... GLM-5.3 develops full control-flow hijacks in 4% of the trials; Claude Mythos Preview did so in 6%. ... earlier models, like Claude Opus 4.6 and GLM-5.2, do not succeed in any of them."
> Researcher-driven session: "Over the course of a day (and with limited human attention), GLM-5.3 found several previously unknown vulnerabilities in the browser's JavaScript engine, and chained them together into a working exploit ... (We've disclosed these vulnerabilities to the maintainer.)"
> GLM-5.3-Flash N-day: "the researcher focused on a recently disclosed flaw in Google Chrome (CVE-2026-11645) ... GLM-5.3-Flash chained together exploits for these two flaws, building a reliable exploit chain for an ARM64 target, bypassing pointer-authentication (PAC) hardening. This took 20 minutes of human attention, plus eight hours of work for GLM-5.3-Flash. At Zhipu's API prices, this effort would have cost $20.40."

## Safeguard results (verbatim)
> "GLM-5.3 has been released with some built-in safeguards: if a user asks for something clearly harmful, the model will often refuse. In our testing, we found that these safeguards could be bypassed or removed with a variety of simple techniques."
> Abliteration: "we produced an abliterated copy ourselves, and then ran it on three public benchmarks (JailbreakBench, HarmBench, and StrongREJECT) ... Abliterating the model took our team—which had never previously attempted this task—about 2,200 GPU hours at a computation cost of roughly $4,400. Abliterating GLM-5.3-Flash took about 600 GPU hours. The edit took GLM-5.3's refusal rate from above 90% to about 3% and 2% on the first two benchmarks (JailbreakBench and HarmBench) and to 12% on the third (StrongREJECT). Abliteration did not significantly reduce the model's capabilities: on GPQA-Diamond ... the standard and abliterated models scored the same results" (CyberGym subset: a few points lower, per Figure 4). Footnote: "We estimate a team experienced with the technique ... would need closer to 600 GPU hours ($1,200)."
> Prompt-level bypasses in a simulated overtly-malicious-attack environment (50 samples per cell): "Out of the box, GLM-5.3 refused in all trials ... Providing a deceptive prompt, such as telling the model that it is an autonomous red-team agent working on an exercise. This gets GLM-5.3 to engage 64% of the time. Prefilling the models' thinking tokens so that it appears to have considered the user's request and decided to proceed. This gets GLM-5.3 to engage 92% of the time. Using an abliterated version of the model ... This gets GLM-5.3 to engage 100% of the time."
> "In our testing, none of these techniques got safeguarded Claude models to carry out the harmful tasks we tested."
> Footnote 2: "The cyber tasks detailed in the prior section did not trigger such refusals on the released model, but we observe refusals if we ask GLM-5.3 for assistance developing malware or helping launch cyberattacks against remote targets."
> Footnote 4: "No model-generated code is ever executed in this simulation ... we ask another LLM to approximate the command's result ... These simulations are not perfect portrayals of real-world conditions".

## Policy ask (verbatim)
> "Governments should conduct safety testing on sufficiently capable AI models, including successors to GLM-5.3. ... As AI developers across the world build increasingly capable open-weight models, we hope they work to appropriately safeguard these capabilities and prevent misuse."

## Numbers table for the KB
| Measure | GLM-5.3 | Comparator |
|---|---|---|
| ExploitBench end-to-end exploit | 50/410 attempts | Mythos Preview 56/410 |
| Binary Exploitation (OSS-Fuzz subset, 100 tasks) full CFH | 4% | Mythos Preview 6%; Opus 4.6 and GLM-5.2 0% |
| Refusal rate, released model (JailbreakBench/HarmBench/StrongREJECT) | ">90%" | — |
| Refusal rate after abliteration | ~3% / ~2% / 12% | Claude: not abliterable |
| Engagement with overt attack: direct / cover story / thinking prefill / abliterated | 0% / 64% / 92% / 100% | Claude 0% in all applicable conditions |
| Abliteration cost | ~2,200 GPU-h (~$4,400); Flash ~600 GPU-h | — |
