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

export type DataSummary = z.infer<typeof summarySchema>;
export type Gates = z.infer<typeof gatesSchema>;
export type Reconciliation = z.infer<typeof reconciliationSchema>;
export type Dashboard = z.infer<typeof dashboardSchema>;
export type FxRates = z.infer<typeof fxSchema>;

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
