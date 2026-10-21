"""NeuriCo safety engine: a continuously running AI-safety evaluation and research loop.

Modules
- kb: knowledge-base paths and YAML/JSON helpers (catalogs, campaigns, findings, runs).
- jobs: job specifications and the on-disk queue (pending/running/done/failed).
- daemon: scheduler loop with GPU/API slots, watchdog, retries, ingest and status.
- suites: deterministic evaluation suites run through the safety-evals skill scripts.
- ingest: turns finished workspaces and suite outputs into run records and findings.
- planner: launches the planner agent that proposes new jobs from the knowledge base.
- digest: periodic markdown digests and model-family scorecards.
"""
