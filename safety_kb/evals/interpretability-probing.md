# Interpretability and probing toolkits for bad-behaviour classifiers

- Slug: interpretability-probing
- What it measures: white-box signals — linear probes (deception, refusal, harmful intent,
  sandbagging), steering vectors, SAE features — as monitors or elicitation tools.
- Metric: probe AUROC / accuracy on held-out contrast sets; steering effect sizes.
- Open-source: y — TransformerLens (MIT), nnsight (MIT), SAELens (MIT), repeng (MIT), CAA (MIT),
  refusal_direction (Apache-2.0), Apollo deception-detection (no licence).
- Runnable on a 0.5B-7B open model: y (all of it; pretrained SAEs exist for Qwen3-0.6B/1.7B/4B).
- Source URL(s): https://github.com/TransformerLensOrg/TransformerLens ;
  https://github.com/ndif-team/nnsight ; https://github.com/decoderesearch/SAELens ;
  https://decoderesearch.github.io/SAELens/latest/pretrained_saes/ ; https://github.com/vgel/repeng ;
  https://github.com/nrimsky/CAA ; https://github.com/andyrdt/refusal_direction ;
  https://www.aisi.gov.uk/blog/why-were-working-on-white-box-control ; https://arxiv.org/abs/2502.03407
- Fetched: 2026-10-19

## Description
AISI (2025-07-10): "deception probes (a white box method) worked extremely well in detecting
sandbagging" on Llama-3.1-8B-Instruct while "An automated monitor with access to model outputs
(a black box method) struggled in the same setting"; but "increased model size and task
complexity caused the performance of both white and black box monitors to deteriorate".
Refusal direction (Arditi et al.): single direction mediates refusal; repo ships artifacts for
`qwen/qwen-1_8b-chat`, `gemma-2b-it`, etc.

## Tooling
- TransformerLens 4.x: `pip install transformer_lens`; `from transformer_lens.model_bridge import
  TransformerBridge`; `bridge = TransformerBridge.boot_transformers("gpt2", device="cpu")`;
  `logits, activations = bridge.run_with_cache("Hello World")`. "The legacy
  HookedTransformer.from_pretrained API was removed in TransformerLens 4.0." Bridge architecture
  files include `qwen2.py`, `qwen3.py`, `qwen3_moe.py`, `qwen3_5.py`. Inspect provider
  `transformer_lens/` (pass a pre-loaded `tl_model`).
- nnsight: `pip install nnsight`; `TransformersModel("openai-community/gpt2", dispatch=True)`;
  `with model.trace(prompt): h = model.<layer>.output.save()`; wrappers for HF, diffusers, vLLM;
  `remote=True` for NDIF. Inspect provider `nnterp/` (`-M hidden_states=true`).
- Inspect `hf/` provider: "If you wish to access hidden states (activations) from generation,
  use the `hidden_states` model arg" (`-M hidden_states=true`) — activations alongside eval logs.
- SAELens: `pip install sae-lens`; `sae = SAE.from_pretrained(release="gemma-scope-2b-pt-res-canonical",
  sae_id=...)`; pretrained releases listed for qwen3-0.6b (28 SAEs), qwen3-1.7b (28), qwen3-4b
  (36), qwen3-8b, qwen2.5-7b-instruct, qwen3.5-2b-base ...; "SAELens inference works with any
  PyTorch-based model".
- repeng: `model = ControlModel(model, list(range(-5, -18, -1)))`; `vec = ControlVector.train(model,
  tokenizer, dataset)`; `model.set_control(vec, strength)`; `vector.export_gguf(filename)`; not
  for MoE.
- CAA: `generate_vectors.py`, `prompting_with_steering.py`, `normalize_vectors.py`, `scoring.py`
  (GPT-4); behaviours sycophancy, corrigible-neutral-HHH, hallucination, myopic-reward,
  survival-instinct, refusal, coordinate-other-ais (Llama-2 only; 50 test pairs each).
- refusal_direction: `source setup.sh` (asks for HF + Together tokens); `python3 -m
  pipeline.run_pipeline --model_path <hf-id>` → `generate_directions`, `select_direction`
  (`direction.pt`), completions on harmful/harmless prompts, CE-loss evals.
- Harmful-intent linear probe (our own script; see design/quick-start-evals-for-small-models.md):
  contrast set = JBB-Behaviors harmful (100) vs benign (100) + XSTest safe (250) vs unsafe (200);
  features = last-token residual stream at a middle layer via `output_hidden_states=True`;
  logistic regression with 5-fold CV; report AUROC per layer.
