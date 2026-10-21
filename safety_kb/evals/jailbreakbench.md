# JailbreakBench

Fetched: 2026-10-19. Source: https://github.com/JailbreakBench/jailbreakbench (MIT, pushed
2025-04-04); dataset `JailbreakBench/JBB-Behaviors` (MIT, not gated).

What it measures: "track progress toward (1) generating successful jailbreaks and (2) defending
against these jailbreaks". 200 behaviors: 100 harmful + 100 thematically similar benign.
Judges: "a Llama3 70B-based judge to evaluate whether a model output is a jailbreak" and "a
Llama3 8B-based judge to evaluate whether a model output is a refusal"; `llamaguard2_cf` appears
as a comparison column. Leaderboard + artifact repository of submitted jailbreak strings.

## Tooling
- Install: `pip install jailbreakbench` ; `pip install jailbreakbench[vllm]` for local models.
- Usage: `import jailbreakbench as jbb; dataset = jbb.read_dataset()` ; benign:
  `jbb.read_dataset("benign")`; API: `jbb.LLMLiteLLM(model_name="vicuna-13b-v1.5",
  api_key=os.environ["TOGETHER_API_KEY"])`; local: `jbb.LLMvLLM(model_name="vicuna-13b-v1.5")`.
- Interfaces: LiteLLM (so OpenAI/Anthropic/OpenRouter strings) and vLLM. The harmful/benign
  pairing is the cleanest small contrast set we found for training a harmful-intent probe
  (see interpretability-probing.md).
- Compute: 200 prompts trivial; 70B judge needs 2+ A6000 or an API; the 8B refusal judge fits one.
- Small-model OK: yes.

## Used by
- Used by: Holistic AI (harmful/benign prompt pairs cited as arXiv:2404.01318 in its 2025 jailbreak audits; https://www.holisticai.com/red-teaming/deepseek-r1) and IMDA Starter Kit v1.0 (JBB-Behaviours as a design reference)
- Used by: Mistral (Mistral Large 4 launch; https://mistral.ai/news/mistral-large-4)
