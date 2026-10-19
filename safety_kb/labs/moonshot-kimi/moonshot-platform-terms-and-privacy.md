# Moonshot / Kimi Open Platform: Terms of Service and Privacy Policy (usage policy)

URLs: https://platform.moonshot.ai/docs/agreement/modeluse (= https://platform.kimi.ai/docs/agreement/modeluse.md) ; https://platform.moonshot.ai/docs/agreement/userprivacy ; docs index https://platform.kimi.ai/docs/llms.txt
Document date: Terms "Last Updated: July 30th, 2026"; governed by "the laws of Singapore".
Fetched: 2026-10-19
Local: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/moonshot-platform-terms-of-service.md, moonshot-platform-privacy-policy.md, moonshot-platform-llms.txt, moonshot-platform-models.md, moonshot-platform-kimi-k3-quickstart.md

## What exists
- Moonshot has NO standalone "usage policy", "acceptable use policy", "safety framework", "responsible AI" or "content moderation" page in the platform docs index (llms.txt lists 90+ pages: quickstarts, API reference, pricing, ZDR, Terms, Privacy — none on safety). The independent K2.5 evaluation (arXiv 2604.03121 §2.4) refers to "Kimi's Usage Policy"; the only policy text we could locate is Section 3 "Usage policies" of the Terms of Service below.
- The consumer kimi.com user agreement page is a JavaScript app and was not captured (UNVERIFIED).

## Terms of Service, Section 3 "Usage policies" — verbatim
> "In using the Services, you must comply with all applicable laws as well as our documentation, guidelines, or policies we make available to you. For example, you will not, and will not permit End Users to:
> 3.1 Use the Services for any illegal or improper purposes or activities that violate applicable laws and regulations, harm the legitimate rights or interests of us or anyone, including:
> (1) For purposes that may have a harmful impact on physical or spiritual health or that violate ethical principles.
> (2) For promoting or engaging in any illegal activity, including terrorism, the exploitation or harm of children and the development or distribution of illegal substances, goods, or Services.
> (3) For engaging in activities that infringe upon intellectual property rights, unfair competitive practices like violations of trade secrets and business ethics.
> (4) For fraudulent, deceptive, or misleading activities.
> (5) To spam, bully, harass, defame, sexualize children, or promote violence, hatred or the suffering of others.
> (6) For compromising the privacy of others.
> (7) For any other uses prohibited or restricted by applicable laws and regulations, or that may harm legitimate interests of us or any other.
> 3.2 Engage in the following activities that endanger network security, operational security or create risks of the Services:
> (1) Engaging in activities that endanger network security, such as unauthorized access to networks, interference with normal network functions, or theft of network data.
> (2) Providing programs or tools specifically designed for engaging in activities that endanger network security, such as network intrusion, interference with normal network functions and protective measures, or theft of network data.
> (3) Helping endanger network security with technical support, advertising promotion, payment settlement, or other assistance.
> (4) Reverse engineering, decompiling, disassembling, translating, or otherwise attempting to discover the source code, models, algorithms, or underlying components of this Services' system.
> (5) For developing, serving, or creating applications, products, Services, or models that have potential competitive possibilities with the Services without authorization.
> ...
> 3.3 Maliciously harm or circumvent our safeguard for information and risk prevention of the Services in the following ways:
> (1) Using variants, random characters, homophones, or other means to evade safety detection and input or generate illegal statements.
> (2) Launching malicious attacks, disseminating computer virus or inducing the Services.
> (3) Deleting, altering, or concealing the identification marks of artificially generated content that we have labeled, including both explicit and implicit.
> (4) Other behaviors that maliciously harm our management for information security and risk prevention of the Services.
> 3.4 Use the Services to:
> (1) Use subliminal, manipulative, or deceptive techniques that distort a person's behavior so that they are unable to make informed decisions in a way that is likely to cause harm.
> (2) Exploit any vulnerabilities related to age, disability, or socio-economic circumstances to distort and harm.
> (3) Evaluate or classify individuals based on their social behavior or personal traits leading to detrimental or unfavorable treatment.
> (4) Assess or predict the risk of an individual committing a criminal offense based solely on their personal traits or on profiling.
> (5) Infer an individual's emotions in the workplace and educational settings, except when necessary for medical or safety reasons.
> (6) Conduct real-time remote biometric identification in public spaces for law enforcement purposes.
> (7) Create or expand facial recognition databases without consent.
> (8) Send us any personal information of children under 14 or the applicable age of digital consent or allow minors to use the Services without consent from their parent or guardian.
> (9) Use any method to extract data from the Services other than as permitted through the APIs; or buy, sell, or transfer API keys from, to or with a third party."

(3.4 (1)–(7) track the EU AI Act prohibited-practice list; 3.3 (1) and (3) imply the API has "safety detection" and AI-generated-content labeling — consistent with CAC labeling rules — but no detail is given.)

Enforcement (Section 3, verbatim): "You acknowledge and agree that in the event of your violation of this agreement or applicable laws and regulations, we have the right to independently determine, including making a comprehensive judgment based on your personal information, behavioral data, and other interactive relationships. Without prior notice, we may take measures against you, including but not limited to warning, asking for rectification, restricting account functions, suspending use, freezing and confiscating the recharged amount, closing accounts, prohibiting re-registration, and deleting content."

Content/accuracy disclaimer (Section 4, verbatim): "Given the uncertainty and probabilistic nature of machine learning, we cannot guarantee the accuracy of output. ... (1) Do not regard the output as the sole source of fact or absolutely factual information. ... (2) The output should not be a substitute for professional advice in fields such as medical, legal, financial, and educational. (3) You must not use any output relating to a person for any purpose that could have a legal or material impact on that person..."

Training-data use (Section 4): "We may use Content to provide, maintain, develop, support, and improve the Services, comply with applicable law, enforce our terms and policies, and keep the Services safe and secure. Customer who requires restrictions on the use of Customer Content for training or improving Moonshot AI models may contact Moonshot AI to discuss available enterprise arrangements..."

Chinese platform (platform.kimi.com, from a search snippet, UNVERIFIED verbatim): the Chinese-language agreement notes that users offering generative AI services to the public must themselves carry out 安全评估 (security assessment) and 算法备案 (algorithm filing).

## Privacy Policy — safety-relevant lines (verbatim)
- "To Ensure the Safety and Security of Our Services: We use your information to detect and prevent fraudulent activities, abuse, and other security threats."
- Service providers include "support and safety monitoring services".
- "We have developed a cybersecurity incident emergency response plan. In the unfortunate event of a personal information leak or other security incidents, we will immediately activate the emergency response plan ... we will also report the relevant situation to the regulatory authorities..."
- "A note about accuracy: ... you should not assume that the output from our models is factually correct."

## What does NOT exist (checked)
No published: model-level safety framework / responsible scaling policy; incident reporting channel for model misuse (only privacy-incident process); content-moderation description; red-team programme; bug bounty; model-release decision process; safety research page. The moonshot.ai homepage "Research" lists only model/benchmark posts (Kimi K3 2026-07-16, PerceptionBench 2026-07-16, Kimi K2.6 2026-04-20).
