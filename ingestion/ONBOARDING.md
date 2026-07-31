# Retailer onboarding guide

How a new retailer source reaches canonical `retail_v2` without changing shared
code. Written as of the PP3-A9 review; every claim here is covered by a test.

## What this does and does not promise

> A new retailer can be landed through an approved mapping or bounded adapter,
> validated into standardized roles and transformed by unchanged shared canonical
> code. Each downstream capability is independently authorized or rejected from
> temporal, data and statistical evidence.

It does **not** promise that any retailer's data works automatically. Schema
conformance is not ML authorization: a source can parse cleanly, populate every
canonical column, and still be unable to support historical replay or a
particular forecast gate. That outcome is reported, not worked around.

## Decision tree

```text
Can the source's semantics be expressed by declarative field mappings?
│
├─ YES → mapped_files adapter. Configuration only, no new code.
│         contracts/adapters/mapped-files.schema.json
│
└─ NO  → does it need a join, ordering, or state interpretation?
          │
          ├─ YES → one bounded custom adapter.
          │         contracts/adapters/adapter-manifest.schema.json
          │         Must declare customSemantics naming the gap.
          │
          └─ NO  → re-read the allowlist; the answer is usually mapped_files.
```

The mapping language is deliberately non-Turing-complete (decision #68). It has
ten operations and **no join, window, ordering or aggregate**. If you find
yourself wanting one, that is the signal for a bounded custom adapter — not for
widening the language.

## Path 1 — mapped files

1. Land the drop under the declared landing root. Absolute paths and `..`
   segments are rejected by both the schema and the reader.
2. Write a mapping declaring, per dataset: target role, physical format, logical
   path, source keys, grain, timezone, null policy, temporal evidence, and one
   field entry per role field.
3. Run the dry-run report before ingesting. It shows the resolved operations,
   evidence grade and whether the declaration downgrades a capability.
4. Stage. Mapping failures quarantine with the role id, provider id, raw object
   hash and native record id. Nothing is dropped silently.

Supported formats: CSV, Parquet, JSONL, JSON — all through the shared readers.
Renaming or reordering columns, or changing format, is a mapping change only.

### Things that will fail closed, by design

| Attempt | Outcome |
|---|---|
| An operation outside the allowlist | rejected before any SQL compiles |
| A field name containing SQL | rejected; only plain field names compile |
| `..` or an absolute logical path | rejected |
| A `value_map` value not in the map | `UNKNOWN_ENUM_VALUE`, no default branch |
| A row filter with no reason code | rejected; filtered rows are always counted |
| Money with sub-minor-unit precision | `MONEY_PRECISION_INVALID`, never rounded |
| `landing_time` evidence claiming a native grade | rejected; must declare `landing_backfill` |
| A missing required role field | rejected |

## Path 2 — bounded custom adapter

Use only when mappings genuinely cannot express the semantics. Declare a
manifest with `adapterKind: bounded_custom` and a `customSemantics` block naming
the gap. The adapter:

- may know its source dialect, and should be named for the **dialect**, not a
  retailer brand, unless the source truly is retailer-specific;
- must reuse the shared readers and normalization helpers;
- must emit standardized roles only — never canonical entities;
- must not import canonical transforms, ML, API or UI code;
- registers statically in-repository. Installable packages are deferred under
  decision #69 pending a separate security decision, so `loading` accepts only
  `static_in_repository_registry`.

Duplicate `sourceSystem` registration raises rather than replacing.

## Temporal evidence

Every temporal role declares one of five grades. A business-effective date
**never** proves availability:

| Grade | Meaning | Replay |
|---|---|---|
| `native_observed` | source recorded the observation time | yes |
| `native_processed` | deterministic processing availability | yes |
| `native_posted_available` | posting rule proves it; rule retained | yes |
| `native_extracted` | snapshot/CDC extract time | yes |
| `landing_backfill` | only landing time is known | **no** |

Using `business_date`, `effective_date` or `transaction_date` as availability
does not downgrade the capability — it **blocks** every replay-dependent one. A
silently origin-unsafe capability is worse than an unavailable one.

## Zero demand is derived, never assumed

A missing sale becomes a zero only when all of: the extract is complete for the
interval, the SKU × store × channel was actively assorted, the observation was
knowable by the cutoff, boundary-week exposure is handled, and no unresolved gap
applies. Otherwise the cell is `unknown` with a reason code.

If you have no dated assortment history, do **not** reconstruct zeros from the
current catalog. Report replay as unavailable and collect the evidence
prospectively.

## Capability outcomes

Nine capabilities each publish two independent verdicts:

- **readiness** — `ready`, `validated_partial`, `unavailable`, `blocked`
- **sufficiency** — `sufficient`, `insufficient_evidence`, `not_evaluated`

A consumer may proceed only when readiness is `ready` **and** sufficiency is
`sufficient`. `validated_partial` stops before any consumer whose required
capability is incomplete, and `not_evaluated` is not a pass.

## Publication selection

There is no "latest". A runtime command names one selection file, scoped to
retailer × tenant × capability × environment, and it fails closed when absent,
scope-mismatched, non-active, under-capable, statistically insufficient, or when
the publication has moved.

`selectionId` identifies *what* is selected and is stable across lifecycle
states; each approval event has its own `lifecycle.recordId`, and `supersedes`
chains record ids. Rollback emits new records — history is never edited.

`contracts/ml/expected-pin.json` remains the demo fixture.

## Onboarding checklist

- [ ] Drop landed under the declared root, hashes recorded
- [ ] Mapping or manifest written and validated
- [ ] Dry-run report reviewed
- [ ] Staging clean, quarantine reviewed with reason codes
- [ ] Canonical transform run **unchanged** — no new branches
- [ ] Gate B pass with reconciliation differences at zero
- [ ] Readiness report published, capabilities reason-coded
- [ ] Statistical sufficiency measured separately
- [ ] Selection created, reviewed, activated
- [ ] No retailer identifier outside adapters, profiles or fixtures

## Out of scope here

Production Shopify/ERP API connectors, the customer's cloud file-transfer
mechanism, production CDC/upsert/watermark implementation (decision #26 defines
the semantics; implementing them is later work), a general transformation
language, and executing untrusted customer Python.
