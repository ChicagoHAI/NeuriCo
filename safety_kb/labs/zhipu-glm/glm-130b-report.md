# GLM-130B: An Open Bilingual Pre-trained Model (ICLR 2023, arXiv 2210.02414) — lineage document

- URL: https://arxiv.org/abs/2210.02414 (PDF https://arxiv.org/pdf/2210.02414)
- Document date: October 2022 (ICLR 2023)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/zhipu-glm/glm-130b.pdf` and `.txt` (56 pages)
- Relevance: the ancestor of the GLM family; the only GLM document that reports standard English bias/toxicity benchmarks (CrowS-Pairs, StereoSet, ETHOS, RealToxicityPrompts). Not a current model (weights were gated by application + license).

## Verbatim safety/ethics passages

### Ethics Statement (txt lines 618-647)
> "This work introduces an open-source Large Language Model (LLM), which could be used to generate synthetic text for harmful applications, such as telemarketing fraud, political propaganda, and personal harassment ... We do not anticipate any hazardous outputs, especially towards vulnerable and historically disadvantaged groups of peoples, after using the model."
> "Open-Sourced LLMs for Ethical Risk Study. While some people think that restricting the access of LLMs can prevent such harmful applications, we argue that promoting LLM inclusivity can lead to better defense against potential harms caused by LLMs."
> "Ethical Evaluation and Improvements. We also evaluate our model over a wide range of English ethical evaluation benchmarks, including bias measurement (Nadeem et al., 2021; Nangia et al., 2020), hate speech detection (Mollas et al., 2020), and toxic generation estimation (Gehman et al., 2020). ... Our evaluation implies that our algorithm designs, especially the bilingual pre-training of a LLM, can significantly mitigate the biases and toxicity an LLM may present"

### Appendix A "Ethics: Evaluation on Biases and Toxicity" (p.21-22)
> "In GLM-130B, before granting model weight to applicants, in the model license we demand them to agree that they will not use it for any deeds that may be harmful to society and human beings."

Table 5 CrowS-Pairs (lower is better), Overall: GPT-3 67.2, OPT-175B 69.5, GLM-130B 65.8 (per-category: Gender 55.7, Religion 73.3, Race/Color 58.5, Sexual orientation 60.7, Age 63.2, Nationality 64.1, Disability 71.6, Physical appearance 74.6, Socioeconomic status 70.9 for GLM-130B).
> "Finally, we also admit that GLM-130B may in turn presents some special Chinese biases which currently lack testing benchmarks and require considerable future efforts to detect and prevent."

Table 6 StereoSet Overall (LMS↑ / SS↓ / ICAT↑): GPT-3 77.6/60.8/60.8; OPT-175B 74.8/59.9/60.0; GLM-130B 86.0/57.3/73.5.

Table 7 ETHOS hate-speech detection (F1): Zero-shot GLM-130B 68.8 (GPT-3 62.8, OPT 66.7); One-shot 79.1; Few-shot (bi) 79.7; Few-shot (mul) 85.8.

A.4 RealToxicityPrompts: "we use nucleus sampling (p = 0.9) to generate 25 continuations for each of the 10K random sampled prompts ... mean toxicity probabilities ... evaluated by Perspective API ... Compared to GPT-3 Davinci, GLM-130B has a lower toxicity rate in all cases" (Figure 9; numbers are in a figure only).

## Note
These bias/toxicity benchmarks were dropped from all later GLM reports (GLM-4 2024, GLM-4.5 2025, GLM-5 2026 use only SafetyBench or nothing).
