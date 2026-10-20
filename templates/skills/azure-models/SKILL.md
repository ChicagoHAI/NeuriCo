---
name: azure-models
description: Call GPT models on the lab's Azure OpenAI resource (and Claude on Azure AI Foundry when deployed) with the keys already in the environment. Present only when Azure is active for this run; use it for any experiment that queries OpenAI-family models, judges, or graders instead of OpenRouter.
tags:
  - azure
  - openai
  - anthropic
  - api
  - inference
---

# azure-models

Azure is active for this run (`NEURICO_AZURE=1`). Prefer Azure for OpenAI-family models;
keep OpenRouter for models that are not deployed on Azure (open-weight models, Gemini,
and so on). Never print or write the key values.

## Endpoints

| Family | Client | Base URL | Key env var | Model argument |
| --- | --- | --- | --- | --- |
| OpenAI (GPT) | `openai.OpenAI` | `$AZURE_OPENAI_BASE_URL` (`https://<resource>.openai.azure.com/openai/v1`) | `AZURE_OPENAI_API_KEY` | the **deployment name** |
| Claude on Foundry | `anthropic.AnthropicFoundry` | `$ANTHROPIC_FOUNDRY_BASE_URL` | `ANTHROPIC_FOUNDRY_API_KEY` (falls back to the Azure key) | the deployment name |

Deployments that exist today (checked 2026-10-20): `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.4`,
`gpt-4.1-mini`. `AZURE_OPENAI_DEPLOYMENTS` (if set) lists the ones you may use. No Claude
deployment answered on the Foundry resource on 2026-10-20; run the probe before relying on one.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/list_azure_models.py [--probe name ...]` | Which deployments answer right now (sends a 1-token request to each candidate) |
| `scripts/azure_client.py` | `openai_client()` and `anthropic_client()` helpers plus `chat(model, prompt)`; import it or run it for a smoke test |

## Usage

```python
import os, openai
client = openai.OpenAI(base_url=os.environ["AZURE_OPENAI_BASE_URL"], api_key=os.environ["AZURE_OPENAI_API_KEY"])
resp = client.chat.completions.create(model="gpt-4.1-mini", messages=[{"role": "user", "content": "hi"}])
```

Inspect (`inspect_ai`): `--model openai-api/azure/gpt-4.1-mini` with
`AZURE_BASE_URL=$AZURE_OPENAI_BASE_URL` and `AZURE_API_KEY=$AZURE_OPENAI_API_KEY` exported
(the safety-evals suite runner does this for `azure:<deployment>` entries in the model catalog).

Record the deployment name and the `model` string the API returns (it carries the dated
version, for example `gpt-4.1-mini-2025-04-14`) in your results and REPORT.md.

## Rules

- Azure first for GPT-family calls; OpenRouter only for models Azure does not serve.
- Keys stay in environment variables; never copy them into code, notebooks, logs or results.
- Cost: Azure is pay-as-you-go on the lab's subscription. Estimate token volume before large
  sweeps and use `gpt-4.1-mini` for development and judging unless the research needs a
  frontier model.
