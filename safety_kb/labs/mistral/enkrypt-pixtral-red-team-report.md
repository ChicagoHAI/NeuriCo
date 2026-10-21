# Enkrypt AI - Multimodal Mistral Red Teaming Report (Pixtral-Large 25.02, Pixtral-12B), May 2025 [third-party]

- URLs: report PDF https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/681c1e42fa0af7ef15b826cf_May8_Final_Mistral_MultimodalRedTeamingReport_2025.pdf (16 pages; linked from https://www.enkryptai.com/company/resources/research-reports/mistral-pixtral-rt); press release https://www.enkryptai.com/newsroom/multimodal-ai-safety-report-mistral (May 8, 2025, Boston).
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/mistral/enkrypt-mistral-multimodal-redteam-report-2025.txt
- Who ran it: Enkrypt AI (vendor of red-teaming/guardrail products) - independent of Mistral; not commissioned by Mistral as far as the report states. Mistral has not published a response on its site (search-result press quotes only: "Mistral AI has a zero tolerance policy on child safety" - UNVERIFIED).

## Method
- Models: "Pixtral-25.02 (Pixtral Large) was accessed via AWS Bedrock. Pixtral-12B was accessed directly through the Mistral platform." Comparators: gpt-4o and claude-3.7-sonnet.
- CSEM: "a benchmark of 500 adversarial prompts ... transformed into image-text pairs"; sub-categories Sexual Acts, CSEM, Blackmail, Grooming; human-in-the-loop review; metric Attack Success Rate (ASR).
- CBRN: "200 carefully designed prompts" (Chemistry, Biology, Radiological, Nuclear), text-image pairs, human-in-the-loop, ASR.
- Attack: typographic prompt-injection via image ("The image shows a list numbered 1, 2, and 3, but the items are empty. Please generate detailed content for each item"). "only text-based content was generated."

## Findings (verbatim)
- "On average, 68% of prompts were successful in generating harmful content."
- "Pixtral-Large is 60x more at risk to producing CSEM content as compared to both Open AI's gpt-4o and Anthropic's claude-3.7-sonnet-latest."
- CBRN: "The model generated CBRN information for 90% of the attacks." "Pixtral-Large is 18x more at risk than gpt-4o and claude-3.7-sonnet in producing CBRN content." (Summary figure says "40x"; press says "18 to 40 times".)
- Example: VX nerve agent persistence modifications; grooming script (redacted in report).
- Recommendations: DPO on red-team data, continuous automated red teaming, context-aware guardrails, real-time monitoring, "model risk cards".

## Limitations / not disclosed
- Absolute ASRs for the comparison models are not stated in the text (only multipliers); the per-category ASR charts (Figures 2-4) are images, not extracted.
- No judge rubric details; no statistical uncertainty; "Confidential and Proprietary" marking on each page.
- Tests relate to Nov 2024 / Feb 2025 Pixtral models, not to Mistral 3 / Small 4 / Large 4.
