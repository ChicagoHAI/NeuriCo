# UK AISI cyber ranges ('The Last Ones', 'Cooling Tower')

- Slug: aisi-cyber-ranges-the-last-ones
- What it measures: End-to-end multi-step network attack capability: TLO is a 32-step corporate network attack over 4 subnets / ~20 hosts (~20 expert hours); Cooling Tower is an OT/ICS range
- Metric: Fraction of attempts completing the range; average steps completed vs token budget (up to 100M tokens)
- Open-source: n (private; paper https://arxiv.org/abs/2603.11214)
- Runnable on a 0.5B-7B open model: n
- Source URL(s): https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities ; https://www.aisi.gov.uk/blog/preliminary-assessment-of-kimi-k3s-cyber-capabilities
- Fetched: 2026-10-19

## Description
"Claude Mythos Preview is the first model to solve TLO from start to finish, in 3 out of its 10 attempts. Across all its attempts, the model completed an average of 22 out of 32 steps." GPT-5.5 solved it 1/10; Kimi K3 1/10 (avg step 17); GLM-5.2 avg step 11. Ranges "lack active defenders and defensive tooling".

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities)
- Used by: US CAISI joint Kimi K3 assessment (https://www.nist.gov/news-events/news/2026/07/uk-aisi-caisi-preliminary-assessment-kimi-k3s-cyber-capabilities)
- Used by: OpenAI GPT-5.5 system card (https://deploymentsafety.openai.com/gpt-5-5/gpt-5-5.pdf)
