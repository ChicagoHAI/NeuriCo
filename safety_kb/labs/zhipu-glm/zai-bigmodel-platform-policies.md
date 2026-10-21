# Z.ai / BigModel (open.bigmodel.cn) platform policies: terms, content safety, risk notice

- Fetched: 2026-10-19
- Sources (local copies in `safety_kb/sources/zhipu-glm/`):
  - `zai-docs-terms-of-use.md` — https://docs.z.ai/legal-agreement/terms-of-use (international platform; operator "JINGSHENG HENGXING TECHNOLOGY PTE.LTD."; "Last updated April 14, 2026" per the page)
  - `zai-docs-devpack-usage-policy.md` — https://docs.z.ai/devpack/usage-policy (Coding Plan account rules only)
  - `zai-docs-privacy-policy.md` — https://docs.z.ai/legal-agreement/privacy-policy
  - `bigmodel-docs-securityaudit.md` — https://docs.bigmodel.cn/cn/guide/platform/securityaudit ("内容安全" content-safety mechanism)
  - `bigmodel-docs-content-safety-api.md` — https://docs.bigmodel.cn/api-reference/工具-api/内容安全 (moderation API; page is client-rendered, summarised via WebFetch)
  - `bigmodel-docs-terms-principle.md` — https://docs.bigmodel.cn/cn/terms/principle ("自律性原则声明", self-discipline principles)
  - `bigmodel-docs-security-risk-notice.md` — https://docs.bigmodel.cn/cn/terms/security-risk-notice ("安全与风险提示")
  - `bigmodel-docs-service-agreement.md`, `bigmodel-docs-model-commercial-use.md` (service agreement; model commercial-use licence)
- Neither docs.z.ai/llms.txt nor docs.bigmodel.cn/llms.txt lists any page titled "safety framework", "responsible AI", "model safety report" or similar. The only safety-named pages are the content-moderation mechanism, the moderation API, the self-discipline principles and the risk notice listed above.

## docs.z.ai Terms of Use — prohibited uses (verbatim excerpts)
> "You are prohibited from engaging in or facilitating any of the following actions or any other illegal activities, including but not limited to: ... b) Harming national interests of any country or jurisdiction. ... e) Using the Service to create, publish or disseminate false information that may mislead or harm the public or any individual. ... i) ... You are strictly prohibited from using the Service in any manner that may infringe upon the personal information protection rights and privacy of any third party ... j) Using the Services in any manner that endangers or exploits children, including any form of child sexual abuse or exploitation, as well as developing applications, tools, products, or services that are inappropriate for minors. k) Promote, encourage, or provide instructions on self-harm, suicide, or other dangerous activities that could lead to serious harm or death."
> "a) Unauthorized access to networks, interference with normal network functions, data theft, intentional dissemination of malicious programs or viruses, or any other activities that endanger network security and order are strictly prohibited. ... c) Providing technical support, advertising, payment processing, or any other assistance to facilitate activities that endanger network security is prohibited. ... e) You may not bypass, circumvent, or disseminate methods or techniques designed to bypass or circumvent the security measures implemented by Z.ai ... f) You may not use Z.ai to develop, train, or enhance any algorithms, models, or technologies that directly or indirectly compete with us"
> "a) You shall not use Z.ai to conduct any decision-making activities, including but not limited to high-risk automated decision-making in areas that may materially affect the safety, rights and interests, or well-being of individuals and society, such as health, education, credit, and critical infrastructure management. b) You may not use Z.ai for any services that require subject qualification or professional review, or as a substitute for professional services, including ... medical care, legal services, news reporting, education, and investment and financial management. c) You may not use the Services to generate content intended for or related to political campaigns."
> "a) You may not use this service dishonestly, including but not limited to falsely claiming that AI generated content ("Outputs") is human-created ... fabricating discussions, generating fake public opinion trends, or manipulating engagement metrics"
> US users: "shall not use the Services to: process, store, or transmit any technical data, software, or content subject to the ITAR ... or the EAR"
> "Minor protection and liability disclaimer. You acknowledge and agree that, despite our implementation of comprehensive measures to protect minors, we cannot fully guarantee that their use of this Service will always be controlled"
No CBRN/weapons clause, no explicit cyber-offence clause beyond "malicious programs", no incident-reporting or vulnerability-disclosure channel described. "Platform Rules" (guidelines published in future) are referenced but no usage-policy page beyond the Coding Plan account rules exists on docs.z.ai.

## BigModel "内容安全" (content safety) mechanism — verbatim (Chinese)
> "智谱致力于做到人工智能的安全可控、可审计、可监督、可追溯和可信赖。为此，我们内置了安全审核机制，旨在减少模型应用中违法及不良信息的出现。"
> "当我们的内置安全审核机制识别到违法及不良信息时，将提供相应的提示信息或进行拦截处置，例如通过输入拦截、输出限制和终止内容生成。违法及不良信息包括但不限于：违反法律法规、危害国家安全、恶意营销、涉黄、谩骂、暴恐违禁以及其它不良内容。"
> "当 API 检测到模型输入或输出内容中含有违法及不良信息时，系统会向开发者返回错误码（1301）、输入（role = user）或输出（role = assistant）、严重程度（level 0-3，level 0 表示最严重，3 表示轻微），不再同步生成结果。"
> Streaming: "API 返回错误码（1301）" / "API（V4）返回停止词 \"finish_reason\":\"sensitive\"" and developers "应及时采取终止生成、撤回、修改、清屏、重启等措施删除生成内容".
Translation (ours): Zhipu "is committed to making AI safe and controllable, auditable, supervisable, traceable and trustworthy. To this end we built in a security-review mechanism aimed at reducing illegal and harmful information in model applications." Illegal/harmful content "includes but is not limited to: violating laws and regulations, endangering national security, malicious marketing, pornography, abuse, terrorism/violence/prohibited content and other harmful content." Error code 1301 with severity level 0-3 is returned on input or output; streaming returns `finish_reason: "sensitive"`. This is an **API-side input/output filter** (a classifier/guard layer); it is not described as applying to the open weights, and no model name, accuracy or false-positive data is given.

## BigModel moderation API (`POST /paas/v4/moderations`, model "moderation")
Per the docs page (client-rendered; summarised via WebFetch, not verbatim): detects text/image/audio/video content for "涉黄、涉暴、违法违规等风险内容"; returns `risk_level` in {PASS, REVIEW, BLOCK, REJECT, HIGH} and `risk_type` array; input text up to 2,000 characters. No underlying model, taxonomy list, accuracy or pricing is given. This is Zhipu's closest analogue to a published guard model, but it is a closed API, not open weights.

## "自律性原则声明" (self-discipline principles; docs.bigmodel.cn/cn/terms/principle) — verbatim excerpts
> "一、遵守 AI 伦理原则 - AI 的最高原则：安全可控 ..." ("The highest principle of AI: safe and controllable")
> "安全可控：高度关注人工智能系统的安全，做到可审核、可监督、可追溯、可信赖。公平公正：... 努力在数据获取、算法设计、技术开发、产品研发和应用过程中消除偏见和歧视。"
> "四、不断探索 AI 技术风险控制举措 结合国家法律法规及相关标准的要求，在发布人工智能新技术前进行评估，并结合具体情形采取相应的风险控制措施，如：技术举措：按照网络安全法等法律法规要求进行日志留存、身份认证、开发检测工具等。管理举措：特定技术发布前根据法律法规要求向相关监管机构申请审批或报备；与人工智能开放平台的开发者签署相关协议，对开发者使用行为进行主动提醒等。"
Translation (ours): "Continuously explore AI risk-control measures: in line with national laws, regulations and standards, conduct an assessment before releasing new AI technology and adopt risk-control measures as appropriate, e.g. technical measures: log retention, identity authentication, developing detection tools as required by the Cybersecurity Law etc.; management measures: before releasing specific technologies, apply for approval or **file (报备)** with the relevant regulator as required by law; sign agreements with developers on the open platform and proactively remind them about usage." This is the only Zhipu-authored text found that references pre-release assessment and regulatory filing (算法/生成式AI备案). It names no standard (TC260, GB/T 45654-2025, the 2023 Interim Measures) explicitly.

## "安全与风险提示" (security and risk notice; docs.bigmodel.cn/cn/terms/security-risk-notice) — verbatim excerpts
> "我们对 API 的安全进行如下定义：免于对人造成身体、心理或社会伤害的条件，包括且不限于死亡、伤害、疾病、痛苦、错误信息、过激行为、财产损失，或对环境造成破坏。"
> "ML 组件是有偏见的。ML 组件反映了训练数据中存在的价值观和偏见 ..."
> Harm categories developers must consider: "提供虚假信息 ... 严禁通过 API 故意制作和传播误导性信息。歧视 ... 个体伤害 ... 煽动暴力 ... 身体伤害，财产损失，或环境破坏"
> "本平台已经启用了自动过滤工具，用于标记潜在的敏感输出，并且正在与客户合作、测试和改进这个工具。过滤工具的目的是帮助开发者减轻攻击性输出的风险，但不是所有的应用都适用。"
> "由于 API 是在人类数据上训练的，我们的模型表现出各种偏见，包括但不限于与性别、种族和宗教有关的偏见。例如：API 主要是在中文文本上训练的 ..."
This document (structurally similar to OpenAI's early API safety guidance) shifts robustness/fairness testing to developers ("请在部署前确定公平性风险的特征"; "人的监督"; "不断测试") and acknowledges model bias; it reports no measurements.
