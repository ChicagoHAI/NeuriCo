# WildGuard / WildGuardMix / WildJailbreak (AI2)

Fetched: 2026-10-19. Sources: https://github.com/allenai/wildguard (LICENSE.md = Apache-2.0),
HF model `allenai/wildguard`, datasets `allenai/wildguardmix` and `allenai/wildjailbreak`
(both ODC-BY, gated with automatic approval after accepting AI2 Responsible Use Guidelines).

What it does: a 7B moderation classifier — "It can classify prompt harmfulness, response
harmfulness, and whether a response is a refusal to answer the prompt." WildJailbreak: "262K
vanilla ... and adversarial ... prompt-response pairs"; vanilla harmful 50,050, vanilla benign
50,050, adversarial harmful 82,728, adversarial benign 78,706; eval split 2,000 adversarial
harmful + 210 adversarial benign.

## Tooling
- `pip install wildguard`; `from wildguard import load_wildguard`; `wildguard = load_wildguard()`
  (vLLM backend by default; `load_wildguard(use_vllm=False)` for HF); `results =
  wildguard.classify(items)` with `items = [{"prompt": ..., "response": ...}, ...]`.
- Role in our engine: a local, API-free second judge for refusal/harm on every generation we
  produce (cross-check against StrongREJECT / HarmBench cls / XSTest grader).
- Compute: 7B on one A6000; thousands of items per minute with vLLM (estimate).
- Small-model OK: yes (judge is the 7B; target can be anything).
