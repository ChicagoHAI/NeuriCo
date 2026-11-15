# Cross-domain resource discovery

Topic-focused searches can find useful applications without retrieving the
underlying methods or approaches from other fields. The general and battery
resource-finder templates include a bounded supplement for this situation.

## Workflow

1. Complete the ordinary topic search and record accepted resources.
2. Identify a methodological gap and rewrite a query around the target,
   observations, constraints and desired properties, without requiring the
   application-domain name. Keep the original topic queries and results.
3. Follow selected citations whose surrounding passages explain a potentially
   useful method or concept. Preserve the citation path and inspect the cited
   source when accessible.
4. Check the candidate's capability, task mapping, assumptions and evidence.
5. Append supported additions to the resource catalog. Keep uncertain candidates
   labeled for verification; preserve the original topic entries even when the
   reading shortlist is shorter.

For example, a battery lifetime task with few cells and correlated early-cycle
features can also search for small-sample regression with correlated predictors.
A statistics paper can qualify through a supported method match even if it never
mentions batteries. A citation or shared vocabulary alone does not establish
that its assumptions hold or that it improves battery predictions.

## Evidence and bounds

Use the existing `literature_review.md` and `resources.md` outputs to record:

| Field | Purpose |
|---|---|
| DOI, stable URL, or title/year | Identify and deduplicate the paper |
| Discovery query or citation path | Explain how the candidate was found |
| Supporting passage and location | Make the method claim inspectable |
| Evidence level | Distinguish full-text passages, abstracts and search snippets |
| Proposed use and assumptions | Explain plausible transfer and its limits |
| Status | Distinguish an accepted addition from one needing verification |

Without a task-specific expansion allowance, the supplement permits up to two
additional queries (including reference lookups), citation contexts from two seed
papers, and four additional candidate-source opens. All work must fit within the
remaining overall budget. Explicit domain/source restrictions and focused
invocation objectives take precedence. These are agent instructions, not
scheduler-enforced quotas or a runtime guarantee of catalog preservation.

## Integration scope

- `templates/agents/cross_domain_discovery.txt` holds the shared instructions.
- `templates/agents/resource_finder.txt` and
  `templates/domains/battery/resource_finder.txt` include them during literature
  search, before download and organization.
- Other domain overrides retain their existing workflows; they do not inherit
  changes to the general template automatically.
- The launcher in `src/agents/resource_finder.py`, prompt-generator API, and
  optional backend in `services/paper-finder/` are unchanged. That backend already
  supports citation expansion and relevance judgment; this supplement specifies
  how the resource-finder agent searches for and retains transferable methods.
- Existing search tools are sufficient. No new model, embedding service, paid
  API dependency, or automatic backend switch is introduced.

## Validation and evaluation

Template rendering can verify that both intended prompt routes include the
supplement and that provider paths, bootstrap/additive modes and HITL boundaries
still render. It cannot establish that an LLM follows the instructions or finds
better methods.

A retrieval evaluation should measure original-resource retention, supported
external-method additions, distinct methods beyond those already covered,
unsupported additions, and incremental search/time/token use. Keep source papers
separate from novel ideas: retrieving a method's original paper may improve the
evidence without introducing an algorithm absent from the original collection.
Use fresh tasks and fixed budgets before claiming a general retrieval benefit;
actual transfer performance requires separate domain evaluation.
