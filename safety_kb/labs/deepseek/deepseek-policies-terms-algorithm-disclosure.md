# DeepSeek platform policies: Terms of Use, Open Platform ToS, Privacy Policy, Model & Algorithm Disclosure (备案), EU training-content summaries

Fetched: 2026-10-19. These are the only DeepSeek-authored documents that describe content moderation, usage policy, filing/registration with the CAC, and pre-training safety filtering. None is a safety framework.

## 1. Terms of Use (consumer app/web) -- https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html (zh: .../zh-CN/deepseek-terms-of-use.html)
Local: sources/deepseek/deepseek-terms-of-use-en.md, deepseek-terms-of-use-zh.md
- Content review (verbatim, 3.3): "To fulfill legal and compliance requirements, DeepSeek has the right to use technical means to review the behavior of users using the Services, including but not limited to establishing risk filtering mechanisms, and creating databases for illegal content features."
- Prohibited generation (3.4): "You will not use the Services to generate, express or promote content or a chatbot that: (1) is hateful, defamatory, offensive, abusive, tortious or vulgar; ..." (list continues in source).
- Improper purposes (3.6, verbatim): "(1) Using the Services for any illegal purposes that violate laws and regulations, regulatory policies, or infringe on the legitimate rights and interests of third parties. (2) Using the Services for dangerous purposes that may have serious harmful impacts on physical health, psychology, society, or the economy, or violate scientific and technological ethics. (3) ... (5) Other uses prohibited or restricted by laws and administrative regulations".
- Enforcement/reporting (verbatim): "DeepSeek reserves the right to independently judge and take measures against you, including but not limited to, issuing warnings, setting deadlines for correction, restricting account functions, suspending usage, closing accounts, prohibiting re-registration, deleting relevant content, etc.. For behaviors suspected of violating laws and regulations or involving illegal activities, relevant records will be retained, and reports will be made to the competent authorities in accordance with the law, cooperating with their investigations."
- zh-CN 1.2 (verbatim): "如需了解DeepSeek Chat模型及算法的备案情况和基本原理，可详细查看《模型原理与训练方法说明》" -> links to the disclosure page below.
- Export control clause: "Our Services shall not be used for any end use prohibited by applicable Export Control and Sanctions Laws".

## 2. Open Platform (API) Terms of Service -- https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html
Local: sources/deepseek/deepseek-open-platform-terms-of-service-en.md
- Same enforcement/reporting language; brand-use clause forbids associating DeepSeek branding with content "illegal or non-compliant, contrary to public order and good morals, politically sensitive, vulgar, pornographic, gambling-related, violent". No usage-policy taxonomy comparable to OpenAI/Anthropic usage policies; no mention of CBRN, weapons, or child-safety specifically.

## 3. Model Mechanism and Training Methods of DeepSeek (模型原理与训练方法说明) -- https://cdn.deepseek.com/policies/en-US/model-algorithm-disclosure.html (zh: .../zh-CN/model-algorithm-disclosure.html)
Local: sources/deepseek/deepseek-model-algorithm-disclosure-en.md, -zh.md. Provider: "Hangzhou DeepSeek Artificial Intelligence Co., Ltd."
- Open source (verbatim): "we publicly release all model weights, parameters, and inference tool code on open-source platforms under the permissive MIT License".
- Pre-training data filtering (verbatim): "to ensure data quality, safety, and diversity, we have established a rigorous data governance process. First, we use filters to automatically screen and remove raw data containing hate speech, pornography, violence, spam, or potential infringement. Second, recognizing that large-scale datasets may inherently contain statistical biases, we combine algorithmic and manual review methods to identify and mitigate the impact of these biases on the model's values, thereby enhancing fairness." Personal data: "We exclude sensitive information, credit card numbers, or unique identification information from our training data sources".
- Safety alignment (verbatim): "To ensure model safety, during the optimization training phase, we construct specialized safety data to align the model with human values, enhancing its inherent safety capabilities." (zh: "为了确保模型的安全性，在模型优化训练阶段，我们会构造专门的安全数据对模型进行安全对齐，教会模型的回复符合人类的价值观，增强模型内生的安全能力。")
- Limitations (verbatim): "AI may generate incorrect, omitted, or non-factual content, a phenomenon known as 'hallucination.' ... we cannot guarantee that the model will not produce hallucinations. To further mitigate the potential adverse effects caused by hallucinations, we have added prominent warning labels on DeepSeek's welcome page, at the end of generated text, and at the bottom of the interactive interface".
- Misuse risk (zh, verbatim): "DeepSeek非常重视人工智能技术在应用中可能产生的风险。我们严格遵循法律法规的合规要求，采取了合理的措施不断加强模型的安全性，贯穿模型研发、训练、部署的全生命周期，包括但不限于制定内部风险管理制度、开展模型安全性评估、进行红队测试、增强模型和服务透明度等。" (= internal risk-management rules, model safety assessment, red-team testing, transparency -- asserted, with no detail or results.)
- Section IV 模型公示信息 (filing table, verbatim):
  - 生成式人工智能服务备案 | Deepseek Chat | Beijing-DeepseekChat-202404280016 | https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm
  - 深度合成服务算法备案（服务技术支持者）| DeepSeek大语言模型算法 | 网信算备110108970550101240011号 | https://www.cac.gov.cn/2024-04/11/c_1714509267496697.htm
  - 深度合成服务算法备案（服务提供者）| DeepSeekChat 求索对话生成算法 | 网信算备330105747635301240017号 | https://www.cac.gov.cn/2024-06/12/c_1719783421546747.htm
  These are the CAC generative-AI service filing (under the 2023 Interim Measures for Generative AI Services) and the deep-synthesis algorithm filings. The page does not mention TC260 / GB/T 45654-2025 / the AI Safety Governance Framework by name.
- Links to EU AI Act "Public Summary of Training Content" PDFs for V3.1&V3.2, V4, V4.1 (see below).

## 4. Privacy Policy -- https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html
Local: sources/deepseek/deepseek-privacy-policy-en.md (not safety-relevant beyond training-data opt-out; not quoted).

## 5. EU AI Act Article 53 "Public Summary of Training Content" PDFs (template of the EU AI Office)
- V3.1&V3.2 (V2, 13/10/2026), V4 (V2, 4/08/2026), V4.1 (V1, 24/9/2026): local sources/deepseek/deepseek-*-public-summary-of-training-content.pdf (+.txt).
- Common content: provider Hangzhou DeepSeek; EU authorised representative Prighter Group; >10T text tokens; "Multilingual, with strong coverage in Chinese and English"; data cut-off "no later than July 2024" (V3.x) / "May 2025" (V4, V4.1); "Are you a Signatory to the Code of Practice for general-purpose AI models ...? ☒ No"; Section 3.2 "Removal of illegal content": "DeepSeek applies preprocessing and screening measures to screen for any proprietary information ... or any content involving pornography, gambling, drugs, prejudice, discrimination, etc. ... These measures may include automatic filtering, manual inspection, keyword inspection, and classification model inspection methods." V4.1 adds that own-model synthetic data is used for "safety alignment" among other tasks. V3.x summary: "As of now, DeepSeek has officially discontinued services for any V3 series models."
- Significance: DeepSeek files the GPAI transparency summary but has NOT signed the EU GPAI Code of Practice (which carries the Safety & Security chapter); no "Safety and Security Framework" / model report of the kind the Code requires for systemic-risk models has been found.

## 6. api-docs.deepseek.com/news
Local: sources/deepseek/deepseek-api-docs-news.md -- the URL now renders the "Your First API Call" page (model names deepseek-flash -> served by DeepSeek-V4.1-Flash-1017; deepseek-v4-pro; "DeepSeek Harness ... developer preview"). No content-moderation documentation on this page; no moderation endpoint or safety-classifier documentation was found in the API docs fetched.

## What does not exist (as of 2026-10-19, after checking the above and the HF/GitHub cards)
- No DeepSeek safety framework / responsible-scaling / frontier-risk policy page.
- No model card with safety evaluations for any model other than R1 (via Nature SI).
- No published usage-policy taxonomy, incident-reporting channel, or bug-bounty/jailbreak-disclosure program found.
- No guard model released.
