# Reviewed compact evidence indexes

This directory holds the only generated evidence that may be committed, under the retention policy
in `plans/local/post-phase3-implementation-plan.md` §1.7.

A file belongs here only when all of the following hold:

- it is a reviewed compact index required for a decision, an acceptance/no-go record or a
  reproducibility handoff;
- it references external artifacts by immutable URI/logical path, byte count, SHA-256 and semantic
  fingerprint rather than embedding them;
- it contains no raw or transformed retailer data, client extracts, credentials, secrets or
  unminimized quarantine payloads.

Full run bundles, Parquet datasets, DuckDB files, model binaries and MLflow artifacts stay in the
external artifact root (`ml/data/artifacts/`, ignored) and are referenced from here by hash.
Generated report output under `ml/reports/` is ignored and must not be resurrected.

At most one reviewed index exists per subject. A superseded index is replaced, not accumulated; its
external history remains linked by hash from its replacement.

## Naming

Name a record for the **subject it describes**, not for a work package, a phase, a plan section or a
verdict:

- `forecast-closure-record.json` — correct; the subject is durable.
- `pp3-p0-no-go-index.json` — wrong twice over. Work-package and phase ids are planning direction
  and stop meaning anything once the plan is archived, and a verdict in the filename goes stale the
  moment the verdict changes.

Run ids, fingerprints, verdicts and dates belong in the document, so a rerun replaces the same file
instead of accumulating a new one beside it.
