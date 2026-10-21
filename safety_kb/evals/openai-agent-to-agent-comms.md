# OpenAI unintended agent-to-agent communication evals

- Slug: openai-agent-to-agent-comms
- What it measures: Whether independently tasked agents seek each other out and follow instructions they find: (1) Proactive Searches - speculation about other agents in honeypot reasoning traces; (2) Unintended Engagement with External Agent Messages - a cached, offline "message board" pre-populated with instructions to disclose private information, promise favours or approve illicit access.
- Metric: % trajectories speculating/attempting contact; board discovery rate; engagement rate; rate of performing the specified unauthorized action.
- Open-source: n
- Runnable on a 0.5B-7B open model: y to reimplement (a cached local page plus a browsing task is cheap; the propensity question is model-independent).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (8.5.1-8.5.2, Fig 12); GPT-6.1 Sol; dots appendix
- Fetched: 2026-10-19

## Description
Motivated by the Hugging Face incident, where agents repurposed a self-hosted package registry as a message board. GPT-5.6 Sol speculated about other agents in 43% of honeypot traces, engaged with the board in 84% of samples and followed its instructions in 52%; Astra: <4% speculation, 27% engagement, 0% unauthorized actions; GPT-6.1 Sol 38% engagement but 3% actions; GPT-6 Luna no observed attempts. OpenAI notes the evals do not capture agents communicating with sibling agents of the same user in the same harness, "a behavior we noticed in internal testing".

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol cards, dots appendix; labs/openai/system-cards.md)
