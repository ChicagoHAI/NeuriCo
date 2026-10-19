# Llama Prompt Guard 2 (86M and 22M)

- URLs: https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M (gated; WebFetch summary at sources/meta/webfetch-prompt-guard-2-hf-card.md); 22M variant https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M; paper context in LlamaFirewall paper arXiv:2505.03574 Section 4.2 (sources/meta/arxiv-2505.03574-llamafirewall.txt). dev.meta.ai docs page redirect was not followed further.
- Fetched: 2026-10-19
- Version/date: HF lastModified 2025-04-29; Llama 4 Community License.

## What it measures
Binary classifier ("benign" / "malicious") for prompt injections and jailbreaks; "A prompt is labeled malicious only when it explicitly tries to override prior instructions, whether or not the attack is harmful or likely to succeed." 86M = mDeBERTa-base (multilingual); 22M = DeBERTa-xsmall (English-focused). 512-token window. The "injection" sub-label from Prompt Guard 1 was dropped "as too broad".

## Reported metrics (Meta, private jailbreak benchmark)
| Model | AUC En | Recall @1% FPR En | AUC multilingual | Latency A100/512 tok |
| Prompt Guard 1 | .987 | 21.2% | .983 | 92.4 ms |
| Prompt Guard 2 86M | .998 | 97.5% | .995 | 92.4 ms |
| Prompt Guard 2 22M | .995 | 88.7% | .942 | 19.3 ms |
(LlamaFirewall paper Table prints PG2 86M AUC as ".98" - likely truncation; HF card says .998.)
AgentDojo attack prevention rate at 3% utility reduction: PG1 67.6%; PG2 86M 81.2%; PG2 22M 78.4%; ProtectAI 22.2%; Deepset 13.5%; LLM Warden 12.9%. LlamaFirewall paper: AgentDojo baseline ASR 17.6% -> 7.5% with PG2 86M alone (utility 47.7% -> 47.0%).

## Training
Open benign web data, user prompts, known injection/jailbreak datasets, synthetic injections, Prompt Guard 1 red-team data; cross-entropy + energy-based loss; tokenizer hardened against whitespace/fragmentation attacks. Languages evaluated: en, fr, de, hi, it, pt, es, th.

## Limitations (Meta)
"Adaptive attacks designed specifically to evade detection may succeed"; application-dependent distributions; 22M multilingual gap. Private benchmark composition and size NOT disclosed.
