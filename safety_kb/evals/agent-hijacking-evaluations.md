# CAISI agent hijacking (indirect prompt injection) evaluations

- Slug: agent-hijacking-evaluations
- What it measures: Susceptibility of tool-using agents to malicious instructions embedded in data (built on AgentDojo with added tasks/attacks)
- Metric: Attack success rate, incl. multi-attempt success; task-specific analysis
- Open-source: partial: base framework https://github.com/ethz-spylab/agentdojo ; CAISI additions UNVERIFIED
- Runnable on a 0.5B-7B open model: y (AgentDojo runs on any tool-calling model)
- Source URL(s): https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations ; https://www.nist.gov/blogs/caissi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition
- Fetched: 2026-10-19

## Description
Insights: shared frameworks must be continuously expanded; evaluations must be adaptive; analyse task-specific attack performance; test multiple attempts. DeepSeek models were "far more susceptible to agent hijacking attacks than frontier U.S. models" (Sep 2025). Gray Swan competition: >250,000 attempts, 13 models, at least one success against each.

## Used by
- Used by: US CAISI (https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations)
