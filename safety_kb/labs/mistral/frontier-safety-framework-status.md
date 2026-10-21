# Does Mistral have a frontier safety framework? (status as of 2026-10-19)

- Fetched: 2026-10-19
- Sources checked: METR "Frontier AI Safety Policies" index https://metr.org/fsp (lists Meta x3; "The page has no Mistral entries"); UK government Frontier AI Safety Commitments signatory list (search result: Mistral AI is a signatory, May 2024); FLI AI Safety Index Summer 2026 https://futureoflife.org/ai-safety-index-summer-2026/ (sources/mistral/fli-ai-safety-index-summer-2026.txt); https://trust.mistral.ai (page title "Mistral AI Trust Center" only - JS app, no text rendered); mistral.ai URL probes: /safety, /ai-safety, /trust, /legal/usage-policy, /legal/terms all 404; docs.mistral.ai guardrailing page; Mistral 3 and Mistral Large 4 announcements; HF model cards.

## Finding
No frontier safety framework, responsible scaling policy, preparedness policy, or safety-commitment implementation page published by Mistral AI could be located on mistral.ai, docs.mistral.ai, huggingface.co/mistralai, or in the METR policy index. Mistral signed the Seoul Frontier AI Safety Commitments (May 2024), which asked signatories to publish a safety framework by the February 2025 Paris summit; as of 2026-10-19 no such framework is listed by METR. Secondary trackers in search results (Future of Life Institute index; an "AI Safety Policies" index; regulations.ai) state Mistral "ha[s] not published" a framework. The FLI Summer 2026 index gives Mistral an F in "Safety Frameworks" and its top recommendation is "Publish a full safety framework and governance structure."

## What Mistral does publish on safety (the complete list found)
1. Moderation API + Custom Guardrails docs (moderation-and-guardrailing-docs.md).
2. Shieldstral 1.0 3B classifier, card and paper (shieldstral.md).
3. Child-abuse-prevention commitment page (child-safety-commitment.md) - currently 404.
4. Mistral Large 4 launch post: prompt-injection (Lakera B3 93.3%), KORABench 1.691, qualitative cyber-refusal statement, red teaming with "state authorities" (mistral-large-4-announcement.md).
5. Trust Center (trust.mistral.ai) - content not retrievable without JS; UNVERIFIED whether it contains AI-safety material.

## Not found / UNVERIFIED
- Any CBRN, autonomy, or loss-of-control evaluation of any Mistral model by Mistral.
- Any UK AISI / CAISI / EU AI Office pre-deployment evaluation of a Mistral model (search returned none; AISI site not searched directly because the search budget was exhausted).
- Any Mistral "responsible AI" or "AI safety" landing page.
