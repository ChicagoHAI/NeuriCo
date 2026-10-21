# Meta statements on third-party testing, external red teaming, and pre-deployment access

- Fetched: 2026-10-19. Sources are the documents listed in README.md; search for a dedicated Meta policy page on evaluator access returned nothing (web-search budget was exhausted mid-task; see "Not verified").

## What Meta commits to in its frameworks
- v1.1 (Feb 2025): threat modelling "with external experts with relevant domain expertise, where required"; red teaming "involving external experts when appropriate"; "working with government officials" for some risks. Transparency argument: open weights let "the broader community ... independently assess the capabilities of our models."
- v2.0 (Apr 2026): preparedness reports will state "access given to internal and external evaluators"; "Where appropriate, we work with external experts to complement and inform our evaluations"; internal-use risk report summaries to "relevant authorities". No commitment to pre-deployment government or independent evaluation; no named organisations.

## What Meta actually reports doing
- Llama 4 (Apr 2025): model card names no external evaluator; "We partner early with subject-matter experts in critical risk areas" (unnamed). Red team is internal ("experts in cybersecurity, adversarial machine learning, and integrity"). Bug bounty and output-reporting mechanism for post-release community testing.
- Muse Spark 1.0 (May 2026): named external parties - Apollo Research (alignment/evaluation-awareness), Scale AI (FORTRESS private split), HandshakeAI (human jailbreak red team, pre-release access, ~149 h), GraySwan (ART prompt-injection), Irregular (private cyber challenges, "independently measured"), SecureBio and Center for AI Safety (bio capability/refusal sets), Deloitte / Faculty / Frontier Design / SecureBio (chem-bio threat modeling consultants). Meta reports that evaluation-awareness findings from Apollo were "not a blocking concern for release" (per the report's own framing: "do not affect our alignment and risk determinations").
- Muse Spark 1.1 (Jul 2026): Scale AI, GraySwan "before the Muse Spark 1.1 launch", Irregular, SecureBio. Apollo not mentioned.
- Government institutes: the Muse Spark report cites UK AISI / US AISI 2024 joint testing only as a methodological reference for a bio evaluation ("replicate previous pre-deployment tests (US AISI and UK AISI, 2024)"). No statement that UK AISI / CAISI received pre-deployment access to Muse Spark or Llama 4 was found. UNVERIFIED.

## Gaps
- No standing commitment to independent pre-deployment evaluation of open-weight Llama releases; the external evaluations above are for the closed Muse Spark line.
- No disclosure of evaluator access conditions (chain-of-thought access, helpful-only checkpoints) beyond HandshakeAI "did not have access to the model's chain-of-thought".
- FLI AI Safety Index (Summer 2026, third party) grades Meta D+ overall and recommends "establish auditing mechanisms for the framework" (sources/mistral/webfetch-fli-ai-safety-index-summer-2026.md).
