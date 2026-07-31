// Generated from contracts/ml/forecast-health-policy.json; DO NOT EDIT.

export type ForecastHealthGrain =
  | "market_portfolio"
  | "store_category"
  | "series_key";

export type ForecastHealthStatus =
  | "Strong"
  | "Healthy"
  | "Watch"
  | "Action"
  | "unavailable";

export const FORECAST_HEALTH_POLICY_ID = "retail-forecast-health/v1";
export const FORECAST_HEALTH_POLICY_FINGERPRINT =
  "569dd287b494fd1b9f5968032e3a2f8073feafea1fb00bf497d1c040d0488a80";

export const FORECAST_HEALTH_DISPLAY_HORIZONS = [1, 4, 8, 13] as const;

export const FORECAST_HEALTH_DIAGNOSTIC_HORIZONS = [26] as const;

export const FORECAST_HEALTH_ACCURACY_TARGETS: Record<
  ForecastHealthGrain,
  Record<number, number>
> = {
  market_portfolio: {1: 90, 4: 88, 8: 85, 13: 82, 26: 78},
  store_category: {1: 85, 4: 82, 8: 78, 13: 75, 26: 70},
  series_key: {1: 80, 4: 78, 8: 75, 13: 72, 26: 68},
};

export const FORECAST_HEALTH_TIERS: readonly {
  status: ForecastHealthStatus;
  accuracyVsTargetMinPoints: number;
  absoluteBiasMaxPct: number;
  coverageMinRatio: number;
  coverageMaxRatio: number;
}[] = [
  {status: "Strong", accuracyVsTargetMinPoints: 5, absoluteBiasMaxPct: 3, coverageMinRatio: 0.87, coverageMaxRatio: 0.93},
  {status: "Healthy", accuracyVsTargetMinPoints: 0, absoluteBiasMaxPct: 5, coverageMinRatio: 0.85, coverageMaxRatio: 0.95},
  {status: "Watch", accuracyVsTargetMinPoints: -10, absoluteBiasMaxPct: 10, coverageMinRatio: 0.80, coverageMaxRatio: 0.98},
];

export const FORECAST_HEALTH_FALLBACK_STATUS: ForecastHealthStatus = "Action";
export const FORECAST_HEALTH_UNAVAILABLE_STATUS: ForecastHealthStatus = "unavailable";
