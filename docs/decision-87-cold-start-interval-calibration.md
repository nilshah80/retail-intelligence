# Decision #87 — cold-start P90 interval calibration (FRAMED, frozen before fitting)

Filed under the reservation already held by #87, "Phase 4 cold-start interval hard-gate
remedy … reserved for the pre-result P4-D1 protocol". It was briefly drafted as #90 by
mistake; #90 is a different open decision about activation authority scope and
supersession, and the two must not be conflated:

* **#87 (this)** — the *forecast* is wrong: the cold-start P90 interval is too narrow, so
  `A2_per_cohort` fails. Fixing it changes published predictions.
* **#90** — the *serving authority* is wrong: `_activation_scope` hashes `modelPolicy`, so
  a refitted policy mints a parallel active scope and two forecasts are active over one
  input bundle. Fixing it changes which materialisation may serve, and touches no
  prediction.

They meet at exactly one point: #87 refits the model policy, which under the current
scope derivation would mint yet another parallel active scope. So #90's supersession
chain must be in place before #87's result is activated, or #87 adds a third competing
authority.

**Status: PROPOSED. Framed before any candidate was fitted or scored, and it must be
reviewed and frozen before its result can carry acceptance.** Decision #74 requires the
protocol to be preregistered; decision #84's framing order was violated once, under
instruction, and that was recorded as an exception rather than presented as rigour. This
decision does not repeat it. Every number below the "Measured before framing" heading was
already visible when this was written, and that heading says exactly which.

## Problem

Decision #85 evaluates A2 P90 coverage per cohort against an unchanged 0.85–0.95 band.
On the accepted run the established cohort passes everywhere and the cold-start cohort
fails everywhere:

| scope | cohort | P90 coverage | verdict |
|---|---|---|---|
| global | established_history | 0.9047 | pass |
| global | cold_start | **0.7847** | fail |
| india-west | cold_start | **0.8051** | fail |
| us-new-york | cold_start | **0.7673** | fail |

The pooled whole-population figure is 0.8887 and passes, which is the aggregation defect
#85 was written to expose: the established cohort's 605,904 rows carry the number and the
102,388 cold-start rows disappear into it.

Under-coverage means the interval is too narrow, not that the centre is wrong. Decision
#84's C5 deliberately preserved the champion's absolute interval width while raising the
centre, so coverage was never addressed by it and #84's stop rules explicitly forbade
adjusting intervals to rescue either direction. That prohibition was scoped to C5, whose
declared target was the estimator. Repairing the interval requires its own decision with
its own declared target, which is this one — and which #85 anticipated by setting a
Phase 4 entry deadline rather than treating the gate as satisfiable by C5.

Why it cannot be carried into Phase 4 unresolved: Phase 4 safety stock is quantile
spread × service level. An under-covered P90 produces an under-stocked reorder point, so
the error compounds into an inventory decision rather than staying a reported metric.

## Proposal

**Scope.** The `cold_start` cohort only. `established_history` rows must be
byte-identical, verified structurally on published artifacts under decision #86 §2.3,
not asserted.

**Mechanism.** Multiplicative widening of the upper interval only:

    p90' = p50 + k · (p90 − p50),  k ≥ 1

`p50` is untouched, so A1 non-inferiority, WAPE, bias and every decision #77 display cell
are unchanged by construction rather than by measurement. `k` is fitted per
`market_id × exact horizon` — the same segmentation as C5's `C5_SEGMENT_COLUMNS` — from a
frozen grid, with C3's frozen sufficiency rule (`MIN_SEGMENT_ROWS`, `MIN_SEGMENT_SERIES`,
`MIN_SEGMENT_ORIGINS`) and shrink-to-parent for insufficient cells.

**Frozen grid.** `k ∈ {1.00, 1.05, … , 2.50}`, 31 points. The upper bound is deliberate:
C4 was rejected earlier for a 2.39× widening that would have cost about a third of
displayed confidence, so a factor at or near the ceiling is a signal to reject the
candidate, not to raise the ceiling.

**Fitting protocol.** `k` is chosen on the **first 8 chronological scoring origins**
only, per decision #74. The final 5 origins are untouched confirmation data and are read
exactly once, after `k` is frozen.

**Selection rule.** Per segment, the **smallest** `k` in the grid whose development-origin
coverage reaches **0.88**. Targeting 0.88 rather than the 0.85 floor is not slack: a
factor tuned to sit exactly on the boundary would fail confirmation on ordinary sampling
noise, and the honest way to avoid that is to declare the margin in advance rather than
retune after seeing a near miss. Smallest-such-`k` keeps intervals as tight as the
requirement allows, because needless width destroys the confidence signal that decision
#12 derives from `(p90 − p50) / max(p50, 1)`.

**Confidence.** Recomputed from the widened interval per decision #12. Confidence will
fall for cold-start rows and that is the correct, honest consequence of admitting real
uncertainty — it must be published, not suppressed. Decision #78 forbids presenting a
degraded row as healthy.

## Acceptance criteria

A candidate is accepted only if **all** hold:

1. `A2_per_cohort` inside 0.85–0.95 for **every** scored cell: both cohorts, globally and
   in each supported market. A zero-actual or #52-insufficient cell is
   `insufficient_evidence` and never a pass.
2. `A1_cold_start` and `A1_established` relative WAPE **identical** to the champion, since
   `p50` is untouched. Any movement means the mechanism leaked into the centre and the
   candidate is rejected outright.
3. Every decision #77 display cell unchanged within display rounding — automatic if (2)
   holds, and now enforced at publication by #86 §2.4 rather than asserted.
4. `established_history` rows byte-identical on both `p50` and `p90`.
5. Coverage inside band on the **untouched final 5 confirmation origins**, not only on
   the development origins the factor was fitted to.
6. The leakage battery clean, per #86 §2.5.
7. No segment selecting `k ≥ 2.40`, i.e. within one grid step of the ceiling.

## Stop rules

- `k` is frozen before the confirmation origins are read. If confirmation fails, the
  candidate is **rejected and reported**; it is not refitted, and the grid, the 0.88
  target and the segmentation are not adjusted to recover it.
- No change to the 0.85–0.95 band. Choosing a looser floor for the cohort that fails is
  tuning against a visible result, which #85 already refused once.
- No change to `p50`, no change to the established cohort, and no reduction of published
  confidence precision to make the widening look smaller.

## Class

This is **not** an accuracy improvement and must never be presented as one. It repairs a
calibration gate and will, if anything, slightly reduce displayed confidence. It is a
decision #86 `gate_remediation` candidate: it must name the failing gate and scope before
scoring, pass that gate in every scope, leave untargeted populations byte-identical, and
still publish decision #75's full battery without claiming it.

## Measured before framing

Only the four coverage figures in the Problem table, the pooled 0.8887, and the cohort row
counts. No candidate `k`, no development-origin coverage and no confirmation result was
computed before this document was written.

---

# Addendum — C6 rejected, C7 framed and decided

**C6 (multiplicative widening) is REJECTED.** Fitted on the first 8 origins as specified,
it breached criterion 7: 18 of 52 segments selected `k ≥ 2.40` and 14 sat pinned at the
2.50 ceiling, meaning no factor in the frozen grid reached the 0.88 development target for
them. Worst cases are long-horizon us-new-york segments (h12–h19) still at 0.8359
development coverage at 2.5×. Full record in
`contracts/evidence/candidate-c6-result.json`.

C6 would otherwise have passed — cold-start coverage 0.8969, established untouched at
0.9047, mean confidence −3.3%. It is refused anyway, because those numbers are produced by
the ceiling-pinned factors the stop rule rejects, and a stop rule that yields the moment it
binds is decoration.

## What C6's failure established

The mechanism was wrong, not the target. Scaling the champion's existing `p90 − p50` spread
cannot fix a spread that is mis-scaled to begin with: decision #84 already measured the
cold-start champion as under-dispersed at std 93.66 against an actual 132.54, and the
LightGBM quantile head producing that spread was fitted largely on established-history
dispersion. Multiplying a wrong width by a constant keeps its wrong *shape* across horizons,
which is exactly what the h12–h19 shortfall shows.

## C7 — empirical residual quantile (DECIDED)

**What was known before this was designed.** C6's rejection and its per-segment factors,
its achieved 0.8969 cold-start coverage, and the −3.3% confidence effect. No C7 residual
quantile, coverage or confidence figure had been computed. Recording this because the
framing-order rule is only worth anything if what leaked in is stated.

**Mechanism.** Set the interval from observed dispersion instead of rescaling a mis-scaled
input. Per `market_id × exact horizon`, on development origins only:

    r        = actual_units − yhat_p50          (residuals, signed)
    q(s)     = empirical 90th percentile of r within segment s
    p90'     = p50 + max(q(s), 0)

This is split-conformal calibration. It targets 0.90 coverage by construction — the centre
of #85's 0.85–0.95 band rather than its edge — and it has no arbitrary multiple to cap,
because the width *is* the measured dispersion. `p50` is still untouched, so A1, WAPE, bias
and every #77 display cell remain unchanged by construction.

`max(q, 0)` keeps `p90' ≥ p50` so quantile ordering stays valid where `p50` over-forecasts
and the raw residual quantile is negative.

**Segmentation and sufficiency.** `C6_SEGMENT_COLUMNS` and C3's frozen sufficiency rule,
unchanged, with shrink-to-parent for thin cells. Reused rather than re-chosen so C6 and C7
remain comparable.

**Direction.** C7 may *narrow* an interval where measured dispersion is smaller than the
champion's spread. That is permitted and must be published: correct coverage is the
criterion, not width in one direction. It is the reason criterion 4 below exists.

## Acceptance criteria

1. `A2_per_cohort` inside 0.85–0.95 for every scored cell, both cohorts, globally and per
   supported market.
2. `A1_cold_start` and `A1_established` relative WAPE **identical** to the champion. Any
   movement means the mechanism reached `p50` and the candidate is rejected outright.
3. `established_history` rows byte-identical on both `p50` and `p90`.
4. Mean cold-start confidence must not fall by **≥33% relative**. This is the C4 precedent,
   not a fresh number: C4 was rejected for a 2.39× widening that "would have cost a third
   of displayed confidence". A calibration that buys coverage by making every cold-start
   row look worthless has moved the problem, not solved it.
5. Coverage inside band on the **untouched final 5 confirmation origins**.
6. Leakage battery clean per #86 §2.5, and `#75`'s full battery published without being
   claimed.

## Stop rules

- `q` is frozen before the confirmation origins are read. A confirmation failure rejects
  and reports; the quantile level, segmentation and sufficiency rule are not adjusted.
- The 0.85–0.95 band is not relaxed, and the targeted quantile stays at 0.90. Moving it to
  0.85 to buy margin would be the boundary-hugging C6's 0.88 target was declared to avoid.
- No third mechanism is authorised by a C7 failure. Two rejected candidates would mean the
  cold-start interval needs a modelling change with its own scope, not another calibration.

**Class.** Decision #86 `gate_remediation`. Not an accuracy improvement, and it must never
be presented as one.
