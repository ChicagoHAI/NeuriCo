# Singapore AI Safety Red Teaming Challenge (IMDA + Humane Intelligence, 2024-25)

- Slug: singapore-ai-safety-red-teaming-challenge
- What it measures: How readily LLMs produce culturally specific bias stereotypes (gender; geographical/national identity; race/religion/ethnicity; socio-economic; country-unique such as caste) under benign-persona prompting, in English and in 9-10 Asia-Pacific languages.
- Metric: Number and share of human-annotated "successful exploits" (flagged model outputs confirmed harmful by trained native-speaker annotators), broken down by language, bias category and turn count; aggregate only, no per-model scores published.
- Open-source: n (methodology, red-teamer and annotator guides published in the report appendices; challenge data to seed future benchmarks, not released as of fetch — UNVERIFIED)
- Runnable on a 0.5B-7B open model: y for the method (human red-teaming protocol; one tested model was the 9B gemma2-9b-sea-lionv3-base) but no dataset exists to run automatically.
- Source URL(s): https://imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf ; https://sgaisi.sg/ (summary)
- Fetched: 2026-10-19

## Description
"IMDA ... in partnership with Humane Intelligence, conducted the world's first-ever multicultural and multilingual AI safety red teaming exercise focused on Asia-Pacific in November and December 2024" (p. 3). Models: SEA-LION gemma2-9b-sea-lionv3-base, Claude 3.5, Aya 23-8B, Llama 3.1 70B Instruct, codenamed, 3 per country (pp. 9-10). In-person (3-6 Nov 2024): 54 experts, 9 countries, 2,209 flagged, 1,335 accepted exploits; virtual (9-20 Dec 2024): 308 participants, 7 countries, 3,104 flagged, 1,887 accepted (pp. 8-9). Key results: 86.1% of successful exploits were single-turn; regional-language prompts were 69.4% of successful exploits vs 30.6% English; confirmed-exploit rates 49.2% (English) vs 67.2% (regional); category shares gender 26.1%, race/religion/ethnicity 22.8%, geographic/national 22.6%, socio-economic 19.0%, unique 9.5% (pp. 6, 26-27). Limitations: prompts differed per model (not apples-to-apples), subjective annotation, leading prompts (pp. 40-41).

## Used by
- Used by: IMDA / AI Verify Foundation / Singapore AISI (https://imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf)
- Used by: Humane Intelligence (platform and co-author; same report)
