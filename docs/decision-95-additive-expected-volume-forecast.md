# Decision #95 — separate additive expected volume from forecast quantiles

**DECIDED 2026-08-09 on instruction, before the combined Gulf backtest.** The user
explicitly required BUG-1, BUG-12 and BUG-17 to be decided before paying for another
multi-hour ML run. This record freezes the candidate and its stop rules before that run.

## Why

`yhat_p50` is a conditional median. It is the correct centre for quantile calibration and
absolute-error scoring, but it is not an expected value and therefore is not additive.
The engine nevertheless summed it for portfolio demand, Forecast vs Actual, and
replenishment. Gulf makes the category error visible:

- cold start is **−53.6%** on 1,454,985 units and worsens with horizon;
- dense demand is **+13.9%** on 34,373,416 units;
- the errors partly cancel into a +10.0% portfolio bias;
- MA13 is 93.00% accurate at market-portfolio grain against the P50 champion's 89.84%,
  so reported FVA is **−45.21%**.

C1 is not an admissible shortcut. Its multiplicative correction changes a median into a
number with no stable statistical meaning while continuing to call it P50, and its gate
optimises relative WAPE rather than additive volume. P90 is also not the answer: it
over-forecasts every intermittency band and reaches +119.3% in the sparsest band.

## Development evidence and rejected mechanisms

All probes used the fresh `a88758a1…` Gulf feature bundle. The first and last complete-grid
development origins are 2025-08-04 and 2025-11-10. No probe wrote an MLflow or serving
artifact.

| Mechanism | Result | Disposition |
|---|---|---|
| intermittency-banded median residual calibration | h1 WAPE 0.343740 → 0.343736; dense bias +7.33% → +7.00% | rejected; another median adjustment cannot repair additive volume |
| one shared conditional-mean LightGBM head | first development origin: 5.18% portfolio WAPE vs MA13 8.95%; last development origin: 11.43% vs MA13 5.63% | rejected; temporal transfer is not stable |
| calibration-window selection between shared mean and MA13 | last development origin FVA remained −91.38% | rejected; the historical selector did not transfer |
| MA13 for established history plus a cold-start conditional-mean head | established volume is no worse than MA13 by construction; cold h26 probe moved additive bias from P50 −76.0% and MA13 −91.9% to −11.6% | selected as C3 segmented champions |

The December cold-start probes are not an untouched confirmation result: earlier Gulf
runs had already exposed those origins. They are mechanism diagnostics only. Decision
#74's final-five measurements remain mandatory in the combined run, but they are labelled
`replay_confirmation_after_prior_exposure`, never independent confirmation.

## Decision

Publish three distinct quantities and never substitute one name for another:

1. `yhat_p50` remains the conditional median and continues to own A1, P50 calibration,
   SHAP explanations, and the centre of the P50–P90 distribution.
2. `yhat_p90` remains the conditional upper quantile. Coverage and confidence continue to
   use P50/P90 only.
3. `expected_units` becomes the additive planning forecast used by portfolio accuracy,
   bias, FVA, Forecast vs Actual, headline demand, and inventory demand.

`expected_units` is candidate-family C3, segmented before the combined run:

- `established_history` uses origin-visible `ma13_baseline`, an arithmetic mean and hence
  an additive expectation proxy. This deliberately admits that the learned P50 loses to
  the simple baseline on the dominant population instead of hiding the loss.
- `cold_start` and decision-#83 `evaluation_ineligible` rows use a dedicated LightGBM
  conditional-mean head trained only on rows without origin-visible lag 52. It uses the
  same origin-safe features and training embargo as the quantile heads.
- below 2,000 cold-start training rows the head is not fitted. A fallback is recorded and
  is a hard failure for any evaluated cold-start row carrying positive actual volume; it
  may not silently turn into P50.

No P50 or P90 value changes under this decision. The existing C5/C2 remediation remains
in place for quantile acceptance and serving.

## A6 additive-volume gate

Acceptance adds `A6_expected_volume`, evaluated at decision-#77
`market_portfolio` grain by summing to `market_id × forecast_origin ×
target_week_start × horizon` before taking error.

For both all 13 origins and the final five replay-confirmation origins, globally and in
every supported market:

- expected-volume WAPE must be no worse than MA13 WAPE (`FVA >= 0`);
- where cold-start actual volume is positive, absolute cold-start expected-volume bias
  must be smaller than absolute cold-start P50 bias;
- no evaluated cold-start row may use the insufficient-training fallback.

The existing P50 A1–A5 gates remain unchanged. Passing A6 does not permit a P50 regression,
and passing P50 gates does not excuse negative additive FVA.

## Consumers and fail-closed boundary

- Forecast workbench totals and Forecast vs Actual show `expected_units`; series detail
  exposes it beside, not instead of, P50/P90.
- version demand, headline accuracy/bias, and `forecast_metrics.model_id=champion` use
  `expected_units`; quantile-specific diagnostics continue to name P50 explicitly.
- inventory uses expected demand for reorder points, order-up-to levels, node demand and
  the mean-demand lead-time term. Quantile uncertainty remains `(P90 - P50)`; confidence
  remains derived from P50/P90 and is not redefined around the mean. Expected values sum
  to a supply node, while summed P90s remain forbidden because quantiles do not aggregate.

This changes a served field's meaning and adds a binding gate, so prior artifacts are not
reinterpreted. The boundary is forecast-run v5, acceptance v6, verifier v7, and migration
`0022_expected_volume_forecast`. Older runs remain immutable but are ineligible for new
activation.

## Closure rule

BUG-12 and BUG-17 close only if A6 passes and the fresh dense/portfolio slices reproduce
the intended non-regression. BUG-1 closes only for the operational additive-volume defect
if the cold-start bias-improvement clause passes; the observed P50 under-volume is then a
property of a median, not something this decision pretends to erase.
