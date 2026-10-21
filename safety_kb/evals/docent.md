# Transluce Docent (transcript analysis) and investigator agents

- Slug: docent
- What it measures: not an eval; "a behavior analysis platform for agents" — search and
  clustering over transcripts, rubric/LLM-judge scoring, tracing, sharing.
- Open-source: y — https://github.com/TransluceAI/docent (LICENSE file: Apache-2.0; GitHub API
  shows NOASSERTION), docs https://docs.transluce.org ; hosted at docent.transluce.org or
  self-host.
- Runnable on a 0.5B-7B open model: n/a (consumes logs).
- Source URL(s): https://docs.transluce.org/installation.md ;
  https://docs.transluce.org/ingestion/integrations/inspect.md ; https://docs.transluce.org/llms.txt ;
  https://transluce.org/automated-elicitation ; https://arxiv.org/abs/2502.01236
- Fetched: 2026-10-19

## Description
Install: `uvx docent@latest setup` (installs SDK + coding-agent plugin, saves API key) or
`uv add docent` (PyPI `docent`; `docent-python` is a redirect). Inspect ingestion helpers:
`convert_inspect_eval_file_to_agent_runs(file_path)`,
`convert_inspect_directory_to_agent_runs(root)`,
`Docent().recursively_ingest_inspect_logs(collection_id, "/path/to/inspect/logs")`,
`client.add_agent_runs(collection_id, agent_runs)`. Each Inspect sample → one `AgentRun`; scores
normalised into `agent_run.metadata["scores"]`.
Investigator agents (Transluce, 2024-10-23/2025-02-03): Llama-3.1-8B investigators trained with
SFT + DPO to elicit rubric-specified behaviours; "95.5% attack success rate against Llama-3.1
405B" on AdvBench harmful strings; "Using an LM to verify yields scalable elicitation
algorithms, but also raises concerns about reward hacking"; their GPT-4 judge "produced some
false positives". Code release UNVERIFIED.

## Tooling
- Use Docent as the review layer over `./logs/*.eval` from every Inspect run; self-host if
  transcripts must stay local (self-host guide at docs.transluce.org/self_hosting/self_host_docent/).

## Used by
- Used by: Transluce pre-release o3 testing (https://transluce.org/investigating-o3-truthfulness) and coding-agent misalignment study (https://transluce.org/docent/blog/coding-agent-behaviors)
