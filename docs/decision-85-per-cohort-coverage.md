# Decision #85 — per-cohort P90 coverage (DECIDED 2026-07-31; REPORT-ONLY until Phase 4 entry)

Decided on instruction after being surfaced as a separate finding in the decision #84 proposal §8.
Kept out of #84 deliberately: bundling a gate change with a model change would confound them, the same
reason quality policy v2 changed grain only and left every threshold alone.

## 1. The defect

Decision #82 split A1 into an established-history cohort and a cold-start cohort, because pooling them
let a strong seasonal-naive result mask a weak short-history one. **A2 was left whole-population.**

Measured on `fr_a5b88c2ef23091ee`:

| Scope | P90 coverage | Against the 0.85–0.95 band |
|---|---|---|
| global, all rows (what A2 reports) | 0.8887 | pass |
| us-new-york, all rows | 0.8851 | pass |
| india-west, all rows | 0.8925 | pass |
| **global, cold-start cohort** | **0.7937** | **below floor** |
| **us-new-york, cold-start cohort** | **0.7785** | **below floor** |
| **india-west, cold-start cohort** | **0.8114** | **below floor** |

A2 reports 0.8887 passing while every cold-start scope sits below the floor. The established cohort
carries the pooled number. This is the same class of defect as A5 — a failure hidden by aggregation —
and the intervals published for short-history series are materially less reliable than the gate says.

## 1a. Amendment 2026-07-31: report-only, with a hard deadline

Decided report-only for the current version on instruction, after C5 measurement showed the cohort
already fails and that C5 moves it 1.12pp further out. Per-cohort coverage is **computed, published and
visible**, but it does not fail acceptance for this version.

**This is a phased introduction, not a repeal.** The distinction is real: no forecast version has ever
been evaluated against a per-cohort coverage gate, so nothing that previously passed is being excused.

**Hard-gate deadline: Phase 4 entry.** Not a date — a dependency. Phase 4's reorder and safety-stock
engine is specified as quantile-spread × service level, so a P90 that covers 78% while claiming 90%
feeds a silently under-stocked reorder point straight into replenishment. Interval calibration stops
being a reporting concern and becomes a correctness one at exactly that boundary. The gate turns hard
before the first Phase 4 consumer reads an interval, and Phase 4 may not start until it does.

Consequences while report-only:

- the acceptance document publishes every cell with its verdict, and `coverageGateMode: report_only`
  plus the deadline, so no reader can mistake a published failure for a pass;
- decision #86 §2.7 bounds how far a candidate may push it — already outside band, ≤2pp, published;
- the honest fix is the cold-start quantile model, not a width multiplier. A measured 2.39× multiplier
  lands all six cells inside the band and costs a third of displayed cold-start confidence
  (0.6030 → 0.4065); it is recorded as evidence and rejected as a remedy, because a P90 covering 78%
  is miscalibrated rather than narrow.

## 2. Decision

**A2 is evaluated per cohort, using the same 0.85–0.95 band, at the same scopes as today.**

- Cohorts are exactly those decisions #82/#83 already assign: `established_history` and `cold_start`.
  `evaluation_ineligible` rows are not scored and carry no coverage verdict, consistent with their
  exclusion from A1.
- Scopes: globally and per supported market, for each cohort. Six cells at the current market count.
- The band is **unchanged at 0.85–0.95**. Introducing a per-cohort gate and simultaneously choosing a
  looser floor for the cohort that fails it would be threshold tuning against a visible result, which
  decision #75 already forbids.
- A cell whose actual sum is zero, or which falls below decision #52's sufficiency rule, is
  `insufficient_evidence` — never a pass. A cohort that cannot be measured has not been cleared.
- The whole-population A2 number is still published. It is not removed, because removing it would
  hide that pooling was ever misleading; it simply no longer decides the gate alone.
- Acceptance requires **every** scored cohort cell inside the band. A single failing cell fails A2.

## 3. Consequence, stated plainly

**This adds a second blocker to Phase 3 acceptance, effective immediately.** Before this decision the
sole failure was `us-new-york × cold_start` A1 non-inferiority. Now the cold-start cohort also fails A2
in all three scopes.

That is the correct outcome, not an accident of the change. The intervals were already this
under-covered; the gate simply could not see it. The precedent is established: decision #82 introduced
cohorted A1 and thereby invalidated three previously self-declared accepted runs, and decision #83
invalidated a fourth. A correct gate that fails closed on real evidence is the intended behaviour of
this programme.

## 4. Interaction with decision #84

#84's candidate C5 blends the cold-start P50 toward `cold_start_mean` while **preserving the champion's
absolute interval width**. Both estimators under-forecast (−23.50% and −15.00%), and the comparator
less so, so blending raises the centre while the interval width is held constant. Coverage should
therefore move **up**.

That is a prediction from the mechanism, not an assumption, and it is **not** a reason to treat #85 as
already handled. Three outcomes are possible and all must be reported:

1. C5 lifts every cold-start cell to ≥0.85 and both blockers close together.
2. C5 fixes A1 non-inferiority but coverage stays below 0.85, leaving #85 open and Phase 3 still NO-GO.
3. C5 raises coverage past 0.95 at some horizon, failing A2 from the other side.

Outcome 3 is a real risk precisely because the width is held fixed while the centre moves. **#84's stop
rules already forbid widening or narrowing intervals to rescue coverage**, so if outcome 3 occurs the
candidate is rejected and the interval model needs its own decision rather than an adjustment.

**Measured outcome: none of the three.** Coverage moved *down*, 0.7937 → 0.7847 global and
0.7785 → 0.7673 in us-new-york. The §4 prediction above was wrong, and the reason is instructive: the
comparator sits above the champion on only 51.2% of rows while carrying more volume (median 8.15 against
10.09). WAPE is volume-weighted and coverage is row-counted, so blending toward a higher-variance
estimator lowers the many small predictions and lowers P90 with them. Under the §1a amendment this is a
published report-only regression bounded by decision #86 §2.7, not an acceptance failure.

## 5. What this does not authorize

- changing the 0.85–0.95 band, for any cohort or scope;
- deriving a cohort-specific band from an observed result;
- dropping the whole-population A2 figure;
- treating a `insufficient_evidence` cell as a pass;
- re-cohorting rows to move a failing cell — cohort assignment stays exactly as #82/#83 define it.

## 6. Implementation

- `ACCEPTANCE_SCHEMA_VERSION` advances to `retail-forecast-acceptance/v4`.

  **Correction 2026-07-31.** This section originally said the recomputation and verifier ids advance
  in step "so a prior bundle cannot silently satisfy the new gate". That did not happen and could
  not have: both were already at v4 from decision #82, so there was no step to take, and migration
  0006 continues to admit verifier-v4 materialisations. The promised fail-closed boundary was
  therefore never created, and an older verifier-v4 materialisation stays eligible for activation.

  This is acceptable only because #85 is report-only: it changes what is published, not what
  passes, so an older bundle satisfying the old gate is not satisfying a gate it should have failed.
  **When #85 becomes a hard gate at Phase 4 entry, the version boundary must be created at the same
  time** -- a new recomputation and verifier generation plus a migration that refuses the previous
  one -- or a pre-#85 bundle will pass a coverage gate it was never evaluated against. That
  obligation is recorded here rather than left implied by the original wording.
- Prior bundles remain immutable. No bundle is edited or deleted.

  **They do NOT become ineligible for new activation**, and the sentence that previously claimed they
  did contradicted the correction above. #82 and #83 could make prior bundles ineligible because they
  moved the recomputation and verifier generations; #85 moved neither, so an older verifier-v4
  materialisation stays activatable. What does exclude a pre-#86 bundle in practice is the separate
  requirement that every manifest declare a `candidateClass`, which is a decision #86 effect rather
  than anything #85 achieved.
- The acceptance document publishes, per cohort per scope: coverage, row count, actual sum, the band,
  the verdict, and `insufficient_evidence` with its reason code where applicable.
