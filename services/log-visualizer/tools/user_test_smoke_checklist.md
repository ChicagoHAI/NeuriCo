# User-test smoke checklist

Start the app with:

```sh
NEURICO_AUTOBUILD=0 NEURICO_AUTOSPAWN_WORKER=0 npm start
```

Verify:

- Run list loads without a visible error.
- Next priority issue opens the first reviewable run, preferring completed, annotation_ready, fallback_review_ready, canonical_ready, literature_ready, then world_model_ready.
- Open on a run card opens that run exactly once.
- Completed and annotation_ready runs do not show an active retry control.
- Whiteboard Review on each card opens Steering with a valid issue or a paper fallback.
- Whiteboard Review on each top-global-crux item opens Steering for that issue.
- View all decisions opens Steering with the all-issues panel visible, or an empty state if no issues exist.
- Read paper opens Reports & Evidence, or shows a clear unavailable/failure state if no paper artifact is present.
