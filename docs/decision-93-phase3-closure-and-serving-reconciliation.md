# Decision #93 — reconcile Phase 3 closure and serving authority before Phase 4

**DECIDED 2026-07-31 on instruction.** This is an evidence and serving-lineage repair. It changes
no forecast value, acceptance threshold, source fingerprint, or Decision #92 capability boundary.

## Evidence at decision time

The completed implementation reports 122 contract tests, 52 datagen tests plus 8 subtests, 180
ingestion tests, 187 ML tests with 1 skip, the DB schema test, all Go packages, 11 UI tests, and
clean import boundaries across 102 files. PostgreSQL migration
`0007_activation_and_coverage` is applied and the active view returns exactly one verifier-v5
authority:

* run `fr_b2ef3d33f398095b`;
* version `fv_23722eff8e3b8995`;
* activation event 7;
* publication `fa1bf8834ee9db3111be35ffde5d6b77d4af79c9b4523475e35e462b7a2b02a0`;
* feature fingerprint `c72ebd9c679fbba4ff8e6f5a9c5f134b02733504ef3d73aa2a7629b9bf229e78`.

Four reconciliation defects remain:

1. event 7 has `prior_event_id = NULL`;
2. Go resolves only the configured activation-scope fingerprint and can miss a competitor;
3. no Decision-#73 source-selection lifecycle is discoverable;
4. `forecast-closure-record.json` mixes the current ids with v4/report-only/open and
   self-supersession metadata.

## Decision

### 1. Repair event 7 append-only

Event 7 is immutable incident evidence and is never updated or deleted. Under the forecast
authority advisory lock, a one-time governed repair command must transactionally:

1. assert that event 7 is the sole active event and still identifies
   `fr_b2ef3d33f398095b` / `fv_23722eff8e3b8995`;
2. append a `superseded` event for the same run/version with `prior_event_id = 7` and reason
   `DECISION_93_LINEAGE_REPAIR`;
3. append an `active` event for the same run/version whose `prior_event_id` is the new supersession
   event;
4. assert that exactly one active authority remains.

This is reactivation of identical immutable content, not publication of a new forecast. It needs no
schema migration. A repeat after the valid same-version chain exists is an idempotent no-op. Every
later activation, including the Decision-#92 field-withheld replacement, supersedes the repaired
active event and continues the chain.

### 2. Go validates authority before configuration

For the current PoC schema, Go must read the entire verifier-eligible
`retail_serving.active_forecast_versions` projection at startup and on per-request revalidation.
Exactly one row must exist. Zero or more than one returns governed unavailable; a configured
`activation_scope_fingerprint` is checked only after uniqueness is proven and must match that sole
row.

When retailer, tenant and environment are added to forecast serving state, the same rule applies per
Decision-#90 authority tuple. Configuration may locate a proven authority; it may never hide a
competing row. Tests cover zero, one matching, one mismatching, and two-active cases.

### 3. Adopt the current publication through Decision #73

Create three immutable `retail-publication-selection/v1` documents—`candidate`, `approved`, and
`active`—with one stable derived `selectionId` and a `lifecycle.recordId` chain. The selected scope
is:

* `retailerId: retailer-demo`;
* `tenantId: tenant-demo`;
* `capability: demand_forecast_non_pit`;
* `environment: local`.

The documents bind source snapshot `e010c549…`, Gate A `59456631…`, Gate B `cdb41e02…`, publication
`fa1bf883…`, object count 2,069, and the real retained readiness fingerprint. The readiness
fingerprint must be read from evidence; it is never invented to complete the record.

The prior pin had no Decision-#73 selection, so no historical `superseded` selection is fabricated.
Instead, the reconciliation evidence names it as `legacy_unselected_predecessor`. Future selection
changes append an ordinary `superseded` lifecycle record.

### 4. Correct the closure record without upgrading claims silently

`forecast-closure-record.json` remains a current closure ledger, while immutable run artifacts and
historical rejection evidence remain unchanged. Reconcile it as follows:

* name acceptance-v5, verifier-v5, hard `A2_per_cohort`, migration 0007, the current run/version,
  and hashes from `forecast_run_final`;
* remove the current run/version from `supersededIdentities`; retain each of the five earlier run
  ids and four earlier version ids exactly once with retained/missing-byte status;
* replace stale `stillRequired` and `openEvidence` entries with explicit dispositions:
  * Windows portability — `attested_complete`, upgraded to `locally_verified` only when its retained
    host-run artifact is linked;
  * Linux portability — the same rule;
  * Demand Forecast visual approval — `user_attested_complete` from the 2026-07-31 instruction;
  * Phase 3 retrospective and PP3 go-ahead — `user_attested_complete` from that instruction;
  * Decision-#85 interval entry work — `transferred_to_phase4_p4_1`, because #92 is decided but its
    served-field contract is not implemented; it is not falsely marked Phase 3 complete;
  * Track-A runtime integration — `attested_complete`, upgraded to `locally_verified` only when its
    retained end-to-end artifact is linked;
* record the user's 2026-07-31 statement that Phases 1–3 and Post-Phase 3 are complete and Phase 4
  is ready as the human visual approval and retrospective/go-ahead attestation;
* record Windows/Linux and Track-A items as `attested_complete` when their completion is supplied by
  that statement, and as `locally_verified` only when an actual retained execution artifact exists;
* retain all historical blockers, rejected candidates, report-only history and the event-7 incident
  as history rather than deleting them from the record.

An empty `openEvidence` array is valid only after every former item has a linked artifact, an
explicit attestation classification, or the governed `P4-1` transfer above. Removing text without
that replacement is forbidden.

## Ordering and Phase 4 effect

Decision #93 is implemented in `P4-0`. The event repair, Go authority check, Decision-#73 lifecycle,
and closure reconciliation may proceed together, but all four must pass before `P4-0` exits.

After that, Phase 4 is authorized to proceed to source-only contract work under the approved
sequence. Interval-consuming or result-bearing work remains blocked on `P4-1`, because Decision
#92 acceptance currently reports H5–H26 as withheld while the served current artifact still carries
numeric P90/confidence there. Decision #93 does not waive or conceal that separate field-contract
gap.

## Acceptance evidence

* append-only event sequence retains event 7 and ends in exactly one same-version active event with
  a non-null predecessor;
* Go zero/one/mismatch/two-active tests and PostgreSQL-backed revalidation pass;
* candidate→approved→active selection documents validate, share one derived selection id, and chain
  distinct lifecycle record ids;
* the selection publication, readiness and scope agree with the active input bundle;
* the closure record contains no unclassified open item, no v4-as-current claim, and no current id
  under superseded identities;
* current immutable bundle hashes and all historical supersession evidence remain unchanged;
* the complete stateful local verification suite passes after reconciliation.

## Not decided here

This decision does not implement Decision #92 field withholding, add Phase 4 engines, change the H4
boundary, select a new source publication, or authorize mutable replenishment actions.
