# Indigo one-case user-test smoke checklist

Start the app with:

```sh
ssh bellahe@indigo.cs.uchicago.edu '~/start-neurico-user-test.sh'
ssh -N -L 5200:127.0.0.1:5174 bellahe@indigo.cs.uchicago.edu
```

Verify:

- `http://localhost:5200/api/runs` returns `logit-lens-implicit-fbb4-codex`.
- The run appears in the queue/list and opens exactly once.
- The status pill shows `completed`.
- Steering opens with a valid review issue.
- The left Paper pane renders `paper_draft/main.pdf`, not only reconstructed Abstract/Method cards.
- A highlight/comment annotation can be loaded, edited, saved, and seen again after refresh.
- Journey loads the expected event/log-derived trajectory for the run.
- Journey phase cards are readable on a laptop viewport, including `Literature / evidence`, `Hypothesis generation`, and `Experiment design`.
- Evidence loads the Main Paper and other artifacts without `/api/file` failures.
- Refreshing `localhost:5200` preserves saved annotations for the same reviewer.
