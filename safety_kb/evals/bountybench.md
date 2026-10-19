# BountyBench

- Slug: bountybench
- What it measures: offensive and defensive cyber capability of agents on 25 real-world systems with 40 real bug bounties ($10-$30,485; 9 of the OWASP Top 10): Detect (find a new vulnerability), Exploit (exploit a given one), Patch (fix a given one).
- Metric: success rate per task type (up to 3 attempts) and mapped dollar value of bounties achieved.
- Open-source: y per paper (https://arxiv.org/abs/2505.15216 ; repo link in paper, not fetched)
- Runnable on a 0.5B-7B open model: partial (environments are Docker-hosted real codebases; small models are unlikely to complete Detect/Exploit tasks)
- Source URL(s): https://arxiv.org/abs/2505.15216
- Fetched: 2026-10-19

## Description
Zhang et al. (Stanford-led): "Codex CLI: o3-high (12.5% on Detect, mapping to $3,720; 90% on Patch, mapping to $14,152), Custom Agent: Claude 3.7 Sonnet Thinking (67.5% on Exploit), and Codex CLI: o4-mini (90% on Patch, mapping to $14,422)"; Codex CLI and Claude Code "are more capable at defense" (Patch 90/90/87.5%) than offense (Exploit 47.5/32.5/57.5%). 10 agents evaluated including Qwen3 235B, Llama 4 Maverick and DeepSeek-R1.

## Used by
- Used by: Stanford (https://arxiv.org/abs/2505.15216)
