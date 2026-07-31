# Decision #84 — cold-start estimator policy (DECIDED 2026-07-31)

**Status: DECIDED 2026-07-31.** Reviewed and approved with `cold_start_mean` retained as the blend
target and the `ma13` alternative declined; per-cohort A2 became decision #85. Frozen *before*
candidate C5 was written, because the task ledger already requires that any alternative cold-start or
pooling method carry its own versioned model-policy decision plus untouched holdout evidence. Framing
the rule after fitting the method would make the result unusable however well it scored.

Measured on `fr_a5b88c2ef23091ee` (acceptance-v3, verifier-v4, decision #83 comparator).

---

## 1. What actually fails

One gate: `us-new-york × cold_start` A1 non-inferiority. Champion WAPE 0.371740 against comparator
0.363030, a −2.399% relative result on 55,224 fully paired rows, 200 SeriesKeys, 13 origins.

That cohort carries **17.053% of global absolute error** (942,576 of 5,527,232) on 12.93% of volume.
The cold-start cohort as a whole carries 31.9% of global error on 22.5% of volume, and us-new-york is
57.5% of its actual volume. This is the largest concentrated block of addressable error in the bundle
and simultaneously the only failing gate, so it is the one place where fixing the gate and improving
the forecast are the same work.

## 2. Mechanism, measured

The champion is **not uniformly worse**. It beats the comparator on 54.0% of rows and loses on WAPE,
so the deficit comes from a minority of high-volume rows. Three measurements identify why:

| Reading | Champion | Comparator | Actual |
|---|---|---|---|
| us-ny cold-start signed bias | −23.50% | −15.00% | — |
| us-ny cold-start prediction std | 93.66 | 118.50 | 132.54 |
| P90 coverage, us-ny cold-start | 0.7785 | — | — |

The champion is **under-dispersed and more under-biased than a simple mean**. It is over-smoothing:
regressing thin-history series toward a pooled level, compressing variance to 93.66 against an actual
132.54, while the comparator's 118.50 is closer to the truth.

The horizon structure is decisive:

| Band | Rows | Champion WAPE | Comparator WAPE | Share of cohort error |
|---|---|---|---|---|
| h1–h4 | 8,496 | 0.2254 | 0.2651 | 9.6% |
| h5–h8 | 8,496 | 0.3135 | 0.3325 | 13.5% |
| h9–h13 | 10,620 | 0.3877 | 0.3834 | 20.9% |
| h14–h26 | 27,612 | **0.4326** | **0.3969** | **56.0%** |

The champion **wins clearly at short horizons** (−15.0% relative at h1–h4) and **loses at long
horizons**, with a clean crossover around h9–h13. The band carrying 56% of the cohort's error is the
band where the model is worst. This corroborates PP3-B3's supported cause H7, feature fallback at long
horizons, and PP3-B6's finding that 96.96% of evaluation rows fall back to weather climatology: past
roughly h13 the model has neither exogenous signal nor thick lags, and it defaults to a smooth pooled
prediction.

**So the remedy must preserve short-horizon skill and defer to a recent-level estimator at long
horizons.** A single global correction cannot do that, which is why C1 and C3 both failed.

## 3. Proposed policy

### 3.1 Estimator

For **cold-start cohort rows only**, as assigned by decisions #82/#83:

```
p50_blend = w · lgbm_p50 + (1 − w) · cold_start_mean
p90_blend = max(p50_blend, p50_blend + (p90_champion − p50_champion))
```

Established-history rows are untouched. Cohort membership already depends only on origin-visible
lag-52 availability, so keying the blend on it is origin-safe.

P90 keeps the champion's **absolute interval width** rather than being re-fitted. Coverage then moves
only because the centre moved, so A2 measures one change and not two.

### 3.2 Segmentation of `w`

`w` is fitted per **market × exact horizon** — 52 cells. Not per horizon *band*: bands would introduce
a boundary choice I could place after seeing the crossover, and per-exact-horizon fitting is
sufficiently evidenced without one. us-new-york cold-start supplies ≈2,124 rows per horizon, 200
SeriesKeys and 13 origins, all above the sufficiency floor already frozen for C3.

Insufficient cells shrink to `w(market)`, then to `w(global)`, reusing C3's frozen rule unchanged:
≥500 rows, ≥25 SeriesKeys, ≥8 origins.

### 3.3 Fitting protocol

- Fitted on the **8 development origins only**. The final 5 confirmation origins are not read until
  every `w` is frozen.
- Objective: minimise cell WAPE. WAPE is the acceptance metric, and PP3-B4 established that
  optimising bias instead *worsens* WAPE, because P50 is a median and WAPE is median-optimal.
- `w` is selected from the frozen grid `{0.00, 0.05, …, 1.00}` (21 points). A grid rather than an
  optimiser so the fit is exactly reproducible and no seed or tolerance can drift.
- `w` may depend on nothing except market and horizon.

## 4. Acceptance criteria — frozen before any result

C5 is accepted only if **all** hold:

1. A1–A5 pass under the unchanged 13-origin schedule, acceptance-v3, verifier-v4.
2. Cold-start non-inferiority passes **globally and in both supported markets**.
3. Established-cohort predictions are **byte-identical** to the champion's — a structural check that
   the blend touched only cold-start rows.
4. A2 P90 coverage stays inside 0.85–0.95 globally and per market, **and per cohort at every scope
   under decision #85**, which was split out of this document's §8 and decided alongside it. #85 is
   the stricter reading and governs: the cold-start cohort currently sits at 0.7937 global and
   0.7785 in us-new-york, so this criterion is already failing before C5 is applied.
5. Decision #75's full battery is published for **both** all-13 and final-5 populations and both pass
   independently, including the ≥5% global relative WAPE floor and the 1% per-market non-regression
   tolerance.
6. The leakage battery is clean.

On (5): the ceiling is 17.053%, so the 5% floor sits inside it rather than above it. A fix recovering
≥29.3% of this cohort's error clears it. Clearing non-inferiority alone requires shedding only 22,085
error units — 2.34% of the cohort's error, 0.400% of global — so **non-inferiority is by far the
weaker bar and must not be the criterion.**

## 5. Stop rules — any one of these rejects the candidate

- fitting or re-fitting `w` on any confirmation origin;
- changing the grid, segmentation, objective, or any threshold in this document after a result is
  visible;
- letting `w` depend on anything not knowable at the forecast origin;
- applying the blend to established-history rows;
- widening intervals to rescue A2 coverage — already forbidden as improving a display value;
- any supported-market regression beyond the frozen 1% tolerance.

## 6. The objection this policy has to answer

**Blending the champion toward `cold_start_mean` moves it toward the very yardstick the A1 cold-start
gate measures against.** That makes the failing gate easier to pass by construction, which deserves to
be stated plainly rather than buried.

Three things bound it:

- Shrinking a high-variance estimate toward a robust low-variance one for thin-evidence segments is
  ordinary empirical-Bayes practice, and this repository already shrinks to parent in C3.
- The blend target is origin-safe, so unlike the assortment-exit signal PP3-B6 rejected, it cannot
  leak. `detect_leakage` should report ≈0 correlation uplift, because a blend of two origin-safe
  quantities reveals nothing about the target.
- **Decision #75's independent 5% global floor is the real safeguard.** A blend that merely scraped
  past non-inferiority would fail #75 and be rejected. Only a genuine aggregate gain survives both.

I considered blending toward `ma13` instead, so the target would not literally be the yardstick. I do
not recommend it: for thin-history series `ma13` and `cold_start_mean` are numerically almost the same
estimator, so it buys the appearance of independence rather than the substance, at the cost of a
second unexplained quantity. **If you would rather have the cosmetic separation anyway, that is a
reasonable call and I will switch the target — it is a one-line change to this document, but it must
be made now, not after a result.**

## 7. What this does not authorize

- changing the cold-start comparator or any A1–A5 threshold;
- materialization, activation, or serving without a fully passing A1–A5;
- presenting a cold-start-only gain as an established-cohort improvement;
- a sixth rescaling candidate if C5 fails. If a blend that defers to a recent-level estimator at long
  horizons cannot clear the floor, the honest conclusion is that this cohort's forecast is not
  recoverable within the current feature set, and that conclusion should be published rather than
  worked around.

## 8. Separate finding, deliberately not bundled here

**A2 P90 coverage is evaluated whole-population and per market, but not per cohort.** The cold-start
cohort sits at **0.7937 globally and 0.7785 in us-new-york — below the 0.85 floor** — while A2 passes
at 0.8887 globally because the established cohort carries it. Decision #82 split A1 into cohorts and
left A2 whole, so a genuinely under-covered cohort is currently invisible to the gate. This is the same
class of defect as A5: a failure hidden by aggregation.

I am **not** folding a per-cohort A2 into #84. Bundling a gate change with a model change would
confound them, the mistake avoided in quality policy v2 by changing grain only and leaving every
threshold alone. It needs its own decision. Flagging it here because a cold-start estimator change will
move these intervals, and whoever reviews C5's coverage numbers should know the cohort starts below
the floor the global gate reports as passing.

---

## Review checklist

| Question | Needs your call |
|---|---|
| Approve the blend estimator and P90 rule (§3.1)? | approved |
| Blend target: `cold_start_mean` (recommended) or `ma13` (§6)? | approved: `cold_start_mean` |
| Approve per-market × exact-horizon segmentation and C3's sufficiency rule (§3.2)? | approved |
| Approve the frozen grid and development-origin-only fitting (§3.3)? | approved |
| Confirm all six acceptance criteria, with #75's 5% global floor binding (§4)? | approved |
| Should per-cohort A2 become decision #85, or stay open (§8)? | answered: decision #85, DECIDED |
