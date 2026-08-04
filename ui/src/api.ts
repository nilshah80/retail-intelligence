import { z } from "zod";

const capabilitySchema = z.object({
  available: z.boolean(),
  reasonCode: z.string().nullish(),
  limitation: z.string().nullish(),
  evidence: z.string().nullish()
}).passthrough();

export const summarySchema = z.object({
  schemaVersion: z.literal("retail-data-management/v1"),
  dataMode: z.literal("live"),
  sourceSnapshotId: z.string().min(1),
  nativeSnapshotId: z.string().nullable().optional(),
  gateAStatus: z.string(),
  gateBStatus: z.string(),
  sourceDatasetCount: z.number().int().nonnegative(),
  canonicalEntityCount: z.number().int().nonnegative(),
  curatedObjectCount: z.number().int().nonnegative(),
  publicationFingerprint: z.string().min(1),
  capabilityMask: z.record(z.string(), capabilitySchema)
});

export const ruleSchema = z.object({
  ruleId: z.string(),
  outcome: z.string(),
  summary: z.string(),
  reasonCode: z.string().optional(),
  affectedCapability: z.string().optional()
}).passthrough();

export const gatesSchema = z.object({
  schemaVersion: z.literal("retail-quality-gates/v1"),
  gateA: z.object({
    status: z.string(),
    rules: z.array(ruleSchema)
  }).passthrough(),
  gateB: z.object({
    status: z.string(),
    rules: z.array(ruleSchema)
  }).passthrough()
});

export const reconciliationSchema = z.array(z.object({
  currencyCode: z.string(),
  difference: z.array(z.number()),
  canonical: z.object({
    grossMinor: z.number(),
    netMinor: z.number(),
    taxMinor: z.number(),
    units: z.number()
  })
}));

const sourceRowSchema = z.object({
  sourceSystem: z.string(),
  name: z.string(),
  type: z.string(),
  lastRefreshAt: z.string().datetime(),
  records: z.number().int().nonnegative(),
  qualityPct: z.number().min(0).max(100),
  status: z.enum(["Healthy", "Needs attention"]),
  action: z.literal("View mapping"),
  datasetCount: z.number().int().nonnegative(),
  objectCount: z.number().int().nonnegative()
});

const storeFilterSchema = z.object({
  storeId: z.string(),
  marketId: z.string(),
  name: z.string(),
  currencyCode: z.string(),
  timezone: z.string(),
  region: z.string(),
  format: z.string(),
  city: z.string(),
  active: z.boolean()
});

const marketFilterSchema = z.object({
  marketId: z.string(),
  name: z.string()
});

const channelTypeFilterSchema = z.object({
  name: z.string(),
  type: z.string(),
  marketIds: z.array(z.string()).min(1)
});

export const dashboardSchema = z.object({
  schemaVersion: z.literal("retail-data-management-dashboard/v1"),
  dataMode: z.literal("live"),
  kpis: z.object({
    dataFreshnessPct: z.number().min(0).max(100),
    qualityScorePct: z.number().min(0).max(100),
    connectedSources: z.number().int().nonnegative(),
    rejectedRecords: z.number().int().nonnegative(),
    lastRefreshAt: z.string().datetime()
  }),
  sources: z.array(sourceRowSchema),
  footer: z.object({
    totalSkus: z.number().int().nonnegative(),
    activeSkus: z.number().int().nonnegative(),
    stores: z.number().int().nonnegative(),
    channels: z.number().int().nonnegative(),
    forecastCoveragePct: z.number().min(0).max(100).nullable(),
    modelAccuracyPct: z.number().min(0).max(100).nullable()
  }),
  filters: z.object({
    dateRange: z.object({
      start: z.string(),
      end: z.string()
    }),
    markets: z.array(marketFilterSchema),
    stores: z.array(storeFilterSchema),
    channelTypes: z.array(channelTypeFilterSchema),
    currencies: z.array(z.string())
  })
});

export const fxSchema = z.object({
  schemaVersion: z.literal("retail-fx-rates/v1"),
  dataMode: z.literal("live"),
  reportingCurrency: z.string().length(3),
  coverage: z.object({
    start: z.string(),
    end: z.string(),
    observations: z.number().int().positive()
  }),
  rates: z.array(z.object({
    baseCurrency: z.string().length(3),
    quoteCurrency: z.string().length(3),
    rate: z.string().regex(/^[0-9]+(?:\.[0-9]+)?$/),
    rateDate: z.string()
  })).min(1)
});

const forecastEnvelope = {
  dataMode: z.literal("live"),
  versionId: z.string(),
  forecastRunId: z.string(),
  semanticFingerprint: z.string(),
  publicationFingerprint: z.string(),
  activationScopeFingerprint: z.string(),
  decisionAsOf: z.string(),
  markets: z.array(z.string())
};

const nullableNumber = z.number().nullable();

export const forecastSummarySchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-summary/v1"),
  items: z.array(z.object({
    accuracy: nullableNumber,
    accuracyGrain: z.literal("series_key"),
    // Decision #77 portfolio-grain figures. The stored SeriesKey accuracy stays
    // published beside them; neither may be read as the other.
    portfolioAccuracy: nullableNumber,
    portfolioBias: nullableNumber,
    portfolioBaselineAccuracy: nullableNumber,
    portfolioFvaVsMa13Pct: nullableNumber,
    portfolioAccuracyGrain: z.literal("market_portfolio"),
    baselineAccuracyGrain: z.literal("series_key"),
    fvaGrain: z.literal("series_key"),
    bias: nullableNumber,
    p90Coverage: nullableNumber,
    baselineAccuracy: nullableNumber,
    fvaVsMa13Pct: nullableNumber,
    demandUnits: z.number(),
    seriesCount: z.number().int(),
    exceptionCount: z.number().int(),
    exceptionCounts: z.record(z.string(), z.number().int()),
    qualityCounts: z.record(z.string(), z.number().int()),
    forecastCoveragePct: nullableNumber,
    backtestCoveragePct: nullableNumber,
    // Phase 4 measures the forecast screen has always asked for: forecast
    // demand the inventory position cannot serve.
    demandAtRiskMinor: z.number().optional(),
    demandAtRiskUnits: z.number().optional(),
    demandAtRiskCells: z.number().int().optional(),
    demandAtRiskLocations: z.number().int().optional(),
    categories: z.array(z.string())
  }))
});

export const forecastActualsSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-actuals/v1"),
  items: z.array(z.object({
    targetWeekStart: z.string(),
    forecast: z.number(),
    // The P90. Optional so a bundle published before the read model served it
    // still validates rather than blanking the chart.
    forecastP90: z.number().optional(),
    actual: z.number()
  }))
});

export const forecastHorizonsSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-horizons/v1"),
  // Decision #77 grain, resolved server-side so the metric and the target it is
  // compared against always come from the same rule evaluation.
  metricGrain: z.enum(["series_key", "store_category", "market_portfolio"]),
  metricSemantics: z.literal("exact_horizon_additive"),
  coverageGrain: z.literal("series_key"),
  coverageNote: z.string(),
  items: z.array(z.object({
    horizon: z.number().int(),
    metricGrain: z.enum(["series_key", "store_category", "market_portfolio"]),
    coverageGrain: z.literal("series_key"),
    grainCells: z.number().int(),
    absErrorSum: z.number(),
    signedErrorSum: z.number(),
    actualSum: z.number(),
    coverageHits: z.number().int(),
    n: z.number().int(),
    wape: nullableNumber,
    bias: nullableNumber,
    accuracy: nullableNumber,
    p90Coverage: nullableNumber
  }))
});

export const forecastStoresSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-stores/v1"),
  items: z.array(z.object({
    storeId: z.string(),
    marketId: z.string(),
    name: z.string(),
    city: z.string(),
    region: z.string(),
    timezone: z.string(),
    currencyCode: z.string(),
    format: z.string(),
    active: z.boolean(),
    accuracy: nullableNumber,
    bias: nullableNumber,
    p90Coverage: nullableNumber,
    demandAtRiskMinor: z.number().nullish(),
    demandAtRiskUnits: z.number().nullish(),
    demandAtRiskCells: z.number().int().nullish(),
    stockoutRisk: z.string().nullish()
  }))
});

export const forecastWorkbenchSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-series/v1"),
  items: z.array(z.object({
    marketId: z.string(),
    skuId: z.string(),
    storeId: z.string(),
    channelId: z.string(),
    departmentId: z.string(),
    category: z.string(),
    productName: z.string(),
    channelType: z.string(),
    storeName: z.string(),
    storeCity: z.string(),
    horizonWeeks: z.number().int(),
    baseline: nullableNumber,
    aiForecast: nullableNumber,
    aiForecastP90: nullableNumber,
    plannerForecast: nullableNumber,
    lastActual: nullableNumber,
    lastActualWeek: z.string().nullable(),
    accuracy: nullableNumber,
    // Withheld when absolute error exceeds demand, which is routine on sparse
    // SKUs. `accuracyState` says which case a null is.
    wape: nullableNumber,
    accuracyState: z.enum(["measured", "error_exceeds_demand", "insufficient_evidence"]),
    accuracyGrain: z.literal("series_key"),
    demandSharePct: nullableNumber,
    bias: nullableNumber,
    // Decision #92 withholds the cold-start interval beyond the calibrated horizon, and
    // confidence is derived from that interval, so both can legitimately be absent. A
    // non-nullable schema would have rejected the payload outright.
    confidence: nullableNumber,
    // Decision #64 Q19 / parity amendment P4-0P-A1. Every field below must be
    // declared here or it never reaches a component: this is a plain `z.object`,
    // so Zod strips unknown keys and a field added only server-side is discarded
    // silently. That is why the scope fields land in the schema in the same change
    // as the read model rather than after it.
    //
    // The selected window is cumulative from h1, and withholding starts at h5, so
    // the 4-week default is clean while 8, 13 and 26 are mixed. In a mixed window
    // both `confidence` and `aiForecastP90` are null by contract and the state
    // fields say why -- never read the absence as zero spread.
    confidenceState: z.enum(["measured", "unavailable_mixed_window"]),
    // Diagnostic only. The corrected covered-window mean, restricted to the weeks
    // that carry an interval on both sides of the ratio. Never rendered: the
    // Confidence cell is unavailable when the window is mixed.
    confidenceCoveredWindowMean: nullableNumber,
    aiForecastP90State: z.enum(["available", "unavailable_mixed_window"]),
    intervalCoveredFromHorizon: z.number().int().nullable(),
    intervalCoveredThroughHorizon: z.number().int().nullable(),
    intervalWithheldWeeks: z.number().int(),
    intervalUnavailableReason: z.string().nullable(),
    primaryDriver: z.string().nullable(),
    dataQuality: z.string(),
    priority: z.string(),
    exceptionClass: z.string().nullable(),
    status: z.string()
  })),
  pagination: z.object({
    offset: z.number().int(),
    limit: z.number().int(),
    total: z.number().int()
  })
});

export const forecastDriversSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-drivers/v1"),
  items: z.array(z.object({
    scope: z.string(),
    driver: z.string(),
    contributionPct: z.string(),
    direction: z.string(),
    confidence: z.string()
  })),
  unavailableItems: z.array(z.object({
    driver: z.string(),
    label: z.string(),
    reasonCode: z.string()
  }))
});

export const forecastSignalsSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-signals/v1"),
  freshnessBaseline: z.string(),
  items: z.array(z.object({
    signal: z.string(),
    label: z.string(),
    status: z.string(),
    reasonCode: z.string(),
    knownAsOf: z.string().nullable()
  }))
});

export const forecastVersionsSchema = z.object({
  ...forecastEnvelope,
  schemaVersion: z.literal("retail-forecast-versions/v1"),
  items: z.array(z.object({
    versionId: z.string(),
    kind: z.string(),
    originDate: z.string(),
    horizonWeeks: z.number().int(),
    createdBy: z.string(),
    accuracy: z.number(),
    bias: z.number(),
    demandUnits: z.number(),
    semanticFingerprint: z.string(),
    artifactStatus: z.string(),
    lifecycleStatus: z.string()
  }))
});

export type DataSummary = z.infer<typeof summarySchema>;
export type Gates = z.infer<typeof gatesSchema>;
export type Reconciliation = z.infer<typeof reconciliationSchema>;
export type Dashboard = z.infer<typeof dashboardSchema>;
export type FxRates = z.infer<typeof fxSchema>;
export type ForecastSummary = z.infer<typeof forecastSummarySchema>;
export type ForecastActuals = z.infer<typeof forecastActualsSchema>;
export type ForecastHorizons = z.infer<typeof forecastHorizonsSchema>;
export type ForecastStores = z.infer<typeof forecastStoresSchema>;
export type ForecastWorkbench = z.infer<typeof forecastWorkbenchSchema>;
export type ForecastDrivers = z.infer<typeof forecastDriversSchema>;
export type ForecastSignals = z.infer<typeof forecastSignalsSchema>;
export type ForecastVersions = z.infer<typeof forecastVersionsSchema>;

async function get<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(path, {headers: {Accept: "application/json"}});
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return schema.parse(await response.json());
}

export const loadSummary = () =>
  get("/api/v1/data-management/summary", summarySchema);
export const loadGates = () =>
  get("/api/v1/data-management/gates", gatesSchema);
export const loadReconciliation = () =>
  get("/api/v1/data-management/reconciliation", reconciliationSchema);
export const loadDashboard = () =>
  get("/api/v1/data-management/dashboard", dashboardSchema);
export const loadFx = () =>
  get("/api/v1/fx/rates", fxSchema);

export type ForecastFilters = {
  marketId?: string;
  region?: string;
  storeId?: string;
  channelType?: string;
  category?: string;
  search?: string;
  horizonWeeks?: number;
};

function forecastQuery(filters: ForecastFilters, extra?: Record<string, string | number>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({...filters, ...extra})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const loadForecastSummary = () =>
  get("/api/v1/forecast/summary", forecastSummarySchema);
export const loadForecastActuals = (filters: ForecastFilters) =>
  get(
    `/api/v1/forecast/actuals${forecastQuery(filters, {view: "weekly", limit: 8})}`,
    forecastActualsSchema
  );
export const loadForecastHorizons = (filters: ForecastFilters) =>
  get(`/api/v1/forecast/horizons${forecastQuery(filters)}`, forecastHorizonsSchema);
export const loadForecastStores = (filters: ForecastFilters) =>
  get(`/api/v1/forecast/stores${forecastQuery(filters)}`, forecastStoresSchema);
export const loadForecastWorkbench = (filters: ForecastFilters) =>
  get(
    `/api/v1/forecast/series${forecastQuery(filters, {view: "workbench", limit: 100})}`,
    forecastWorkbenchSchema
  );
export const loadForecastDrivers = () =>
  get("/api/v1/forecast/drivers", forecastDriversSchema);
export const loadForecastSignals = () =>
  get("/api/v1/forecast/signals", forecastSignalsSchema);
export const loadForecastVersions = () =>
  get("/api/v1/forecast/versions", forecastVersionsSchema);

/**
 * The inventory/replenishment live envelope (P4-8/P4-9).
 *
 * `items` is deliberately a permissive record: fourteen destinations serve
 * fourteen different row shapes, and enumerating each here would duplicate
 * the parity contract that already freezes them per screen. What IS pinned is
 * the envelope -- the identity, the consumed forecast authority and the policy
 * version -- because those are what make a rendered number traceable. A
 * response missing any of them is not servable data.
 */
export const inventorySliceSchema = z.object({
  schemaVersion: z.string(),
  dataMode: z.literal("live"),
  inventoryRunId: z.string(),
  inventoryVersionId: z.string(),
  semanticFingerprint: z.string(),
  forecastAuthority: z.object({
    forecastRunId: z.string(),
    forecastVersionId: z.string()
  }),
  policyVersion: z.string(),
  markets: z.array(z.string()),
  // The currency every money figure in the payload is already converted to.
  reportingCurrency: z.string().optional(),
  items: z.array(z.record(z.string(), z.unknown())),
  // SQL aggregates over every scoped row of the active version, for the KPI
  // tiles. Optional because a projection may declare none, and validated rather
  // than passed through: a tile whose value arrived unchecked is a tile nobody
  // can trace. Absent it entirely and Zod strips it, which renders five
  // "Not available" tiles over a working API -- which is exactly what happened.
  summary: z.record(z.string(), z.union([z.number(), z.string(), z.null()]))
    .optional(),
  pagination: z.object({
    offset: z.number().int(),
    limit: z.number().int(),
    total: z.number().int()
  }).optional(),
  // How the route decided which rows made the page, in the words the screen
  // shows. A capped table is only honest if the reader knows what it is capped
  // to: "20 of 4,741" alone does not say whether those twenty are the worst
  // offenders or the first twenty SKU codes alphabetically.
  ranking: z.string().optional(),
  // Cards the reference draws at a grain that is NOT the projection's row grain
  // -- one row per category, per location, per age bucket, per ABC segment. The
  // read model groups them in SQL under the page's own scope and returns them
  // here, so a screen stays one request and its cards cannot disagree with its
  // table.
  cards: z.record(
    z.string(),
    z.array(z.record(z.string(), z.unknown()))
  ).optional()
});

export type InventorySlice = z.infer<typeof inventorySliceSchema>;

export const loadInventorySlice = (endpoint: string, marketId?: string) =>
  get(
    marketId
      ? `${endpoint}${endpoint.includes("?") ? "&" : "?"}marketId=${encodeURIComponent(marketId)}`
      : endpoint,
    inventorySliceSchema
  );
