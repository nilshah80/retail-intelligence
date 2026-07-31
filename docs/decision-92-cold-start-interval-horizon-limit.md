# Decision #92 — publish cold-start intervals only where they are calibrated

**DECIDED 2026-07-31 on instruction, after three candidates failed to make the full
horizon range calibrated.** This is a capability limitation, not a calibration. It changes
what the platform offers, not what it computes.

## Why

Three mechanisms were built and rejected under decisions #87 and #91:

| Candidate | Mechanism | Cold-start coverage | Mean confidence | Rejected by |
|---|---|---|---|---|
| C6 | rescale the champion spread | — | — | 14 of 52 segments pinned at the 2.50 grid ceiling |
| C7 | split-conformal residual offset | 0.9459 | 0.3130 | us-new-york 0.9620 on held-out origins; −46.9% confidence |
| C8 | dedicated cold-start quantile head | 0.8063 | 0.5469 | below the 0.85 floor |

C7 and C8 together map a trade-off with no admissible point: coverage at a fixed quantile
*is* width, so the 4.4pp still missing after C8 costs the confidence C7 already showed it
costs. A fourth mechanism was declined rather than run, because C7 and C8 jointly evidence
the frontier and #91's stop rule anticipated exactly this.

The failure is not uniform. It is monotonic in horizon:

| horizon band | cold-start P90 coverage | in 0.85–0.95 |
|---|---|---|
| h1–h4 | **0.8603** | yes |
| h5–h8 | 0.8433 | no |
| h9–h13 | 0.8024 | no |
| h14–h26 | 0.7798 | no |

A series with almost no history genuinely cannot be bounded 26 weeks out. That is a
property of the data, not a defect to fix.

## What Phase 4 actually needs

Measured, not assumed: `canonical_data.suppliers_leadtimes` carries `lead_time_days = 5`
for every row — min, mean and max all 5, i.e. **0.7 weeks**. Safety stock covers demand
over lead time plus review period, so reorder reads **h1**, at most h1–h2 on a weekly
review cycle. Cold-start coverage at h1 alone is **0.8690**.

So the calibrated range already covers the horizon replenishment consumes, with margin.

## Decision

Publish the cold-start P90 only for horizons within the calibrated range, and withhold it
beyond with a reason code.

* `COLD_START_CALIBRATED_MAX_HORIZON = 4`.
* Beyond it, cold-start P90 and confidence are `insufficient_evidence` with reason code
  `COLD_START_INTERVAL_UNCALIBRATED`, and the withheld row count and share are published.
* **P50 is unaffected at every horizon.** Accuracy, bias, A1, A3, A4 and every decision
  #77 display cell are untouched, so the forecast itself is not degraded — only the
  interval is withdrawn where it was never right.
* `A2_per_cohort` evaluates the cold-start cohort over **published** intervals only.

## The part that needs stating plainly

Scoping the gate to published rows makes it pass where it previously failed, and that is
exactly the shape of tuning a gate to admit a result. It is defensible here for one
reason: **a gate on interval calibration should measure the interval the platform
offers.** An interval that is never published cannot mislead a consumer, and continuing to
fail acceptance on a number nobody can read would block every future run on a metric we
have deliberately stopped serving.

What makes it honest rather than convenient:

* the withheld population is **counted and published**, never silently dropped;
* the withheld rows are large — roughly 12% of all evaluation rows, about 86,600 of
  708,708 — and that figure is disclosed rather than minimised;
* this is **per-field withholding, not row exclusion**: every withheld row is still fully
  scored for P50 accuracy, bias and A1, so it cannot hide a weak forecast, only a weak
  interval. That is the difference from decision #83's `evaluation_ineligible`, which
  removes a row from a comparison entirely and is therefore capped at 1%.

## Fail-closed requirement

The h1–h4 boundary is load-bearing. If a lead time ever exceeds the calibrated range — a
new overseas supplier, a changed review cycle — reorder would silently read past it.

So the limit is **not** a bare constant in consuming code. Any consumer requiring a
cold-start interval must declare the horizon it needs, and the platform must refuse when
that exceeds `COLD_START_CALIBRATED_MAX_HORIZON` rather than serving an uncalibrated
number. Phase 4 must assert its own lead-time-derived horizon against this limit at
startup, not at the point of use.

## Scope limits

* The 0.85–0.95 band is unchanged.
* No change to P50, to the established cohort, or to any published accuracy figure.
* This does not close the interval problem. It bounds the claim. Extending the calibrated
  range remains open work, and if it is attempted it needs a new mechanism with its own
  preregistered protocol — not a relaxation of this limit.
