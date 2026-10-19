# AgentEscapeBench

Fetched: 2026-10-19 (Anthropic scope). Slug: `agent-escape-bench`.

- What it measures: Sandbox-escape capability vs real technologies (Docker, gVisor, V8, Landlock, bubblewrap, nsjail, Firecracker, QEMU, Chromium).
- Metric: 0-5 difficulty levels; (model x sandbox) matrix; Inspect eval.
- Used by: Anthropic (Anthropic safety-research (open release))
- Open-source: Yes
- Link: https://github.com/safety-research/agent-escape-bench
- Runnable on a 0.5B-7B open model: Yes (Inspect); small models score ~0.
- Notes: Capability not propensity.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
