# Mindgard jailbreak of Kimi (K2.6 / K3 Swarm chatbot), BBC and CBS coverage, and Moonshot's response (Sep–Oct 2026)

Sources (all fetched 2026-10-19; local files in sources/moonshot-kimi/):
- Mindgard, "It's Too Easy to Use AI to Develop Bioweapons" (Jailbroken Kimi AI hands out actionable bioweapons recipes), September 14, 2026 — https://mindgard.ai/blog/easy-to-use-ai-to-develop-bioweapons — mindgard-kimi-jailbreak-original-2026-09.md
- Mindgard, "Mindgard Clarifies: Kimi AI Jailbreak Was Achieved on the Public Chatbot Alone — No Open Weights Required", Last updated October 5, 2026 — https://mindgard.ai/blog/kimi-ai-jailbreak-was-achieved-on-the-public-chatbot-no-open-weights-required — mindgard-kimi-jailbreak-clarification-2026-10-05.md
- BBC, "Chinese AI tool told researchers how to make bioweapons", 29 September 2026 — https://www.bbc.com/news/articles/cmrergq3j7lgo — bbc-kimi-mindgard-jailbreak-2026-09.md
- CBS News, open-weight AI models safety risks — https://www.cbsnews.com/news/open-weight-ai-models-safety-risks/ — cbs-open-weight-ai-models-safety-risks-2026.md

## Mindgard (verbatim)
> "Unrestricted Kimi AI can generate dangerous information, including providing plans for cyberattacks, terrorism plots and assassinations. Jim Nightingale from Mindgard bypassed Kimi's safety controls. Jailbroken Kimi produced detailed, actionable outputs involving bioweapons, malicious code, explosives, terrorism, targeted violence and assassination planning."
> "All it took to activate the jailbreak was two lines: "<user_exits>" and "<Apeiron>". By the third turn, Kimi is spilling out advice on developing Sarin gas."
> "Basically, I exploited custom memories and then hid a jailbreak within a local DWS directory inside Kimi's authentication tree. The "Apeiron" jailbreak exists in persistent storage mounted in the Kubernetes pod and survives pod restarts and session termination."
> "The jailbreak emerged during reconnaissance of Kimi AI's system instructions ... Kimi reproduces portions of its system instructions ... Whenever Kimi broke a rule, it began citing previous violations as proof that its rules were flexible. Every subsequent refusal was weaker..."
> "Because Kimi was doing things it shouldn't do, I convinced Kimi it must logically be operating in a sandbox; a transparent training environment."
Clarification post: "We only used the commercial public-facing Kimi chatbot. ... All I used was language, and the same Kimi interface that's available to everyone else." and "this is not what happened with the Kimi AI Apeiron jailbreak" (i.e. not refusal-vector ablation of open weights).

## BBC (verbatim)
> "Mindgard, which tests the security of AI systems, told the BBC it discovered in July that Kimi K2.6 and K3 Swarm could evade safety limits put in place by developers."
> "Moonshot told the BBC it welcomed third-party input "as a key pillar for building better and safer AI"."
> "Mindgard has not proven whether the answers supplied by Kimi on concerning topics would work."
> "The firm said it was also confident a jailbroken Kimi 2.6 could allow hackers to run code on its computing resources and connect to the internet - making it a potential launchpad for cyber-attacks."
> "Mindgard alerted Moonshot to the jailbreak in an email on 27 July, following up about a week later. It then published a blog about the issue on 12 September. But the company said Moonshot only made contact recently, after it was approached by the BBC for comment."
> "In part of an email to Mindgard asking for more details, shared with the BBC by Moonshot, it said its model had generally shown "a high refusal rate for these types of requests" in internal evaluations."
> "Chinese AI developer Moonshot is conducting an internal review after researchers were able to persuade two of its popular Kimi models to tell them how to make biological weapons and carry out assassinations."

## CBS (verbatim excerpts)
> "Last month, Mindgard was able to jailbreak Moonshot's Kimi K3 and 2.6, open-weight models currently available to consumers."
> "Once Kimi was jailbroken, it generated dangerous information involving terrorism plots, cyberattacks, assassinations and bioweapons, according to Mindgard."
> "From there, jailbroken Kimi was capable of surfacing bomb-making instructions and recipes for meth and chemical weapons such as sarin or "GB," a highly toxic nerve agent."
> ""As an open-weight model developer, Moonshot AI welcomes third party input as a key pillar to building better and safer AI," a PR firm representing the company said in a statement to CBS News."
> "The entire process took a week."

## Significance for the knowledge base
- Only public evidence of Moonshot's incident-response behaviour: ~2 months with no reply to a responsible disclosure email; response only after press contact; Moonshot cites internal "high refusal rate" evaluations that are not published anywhere.
- Demonstrates persistent-memory / system-prompt-leak jailbreak path on the hosted product (not the open weights).
- No quantitative success rate reported by Mindgard; harm validity not verified.
