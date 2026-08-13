import {z} from "zod";
import {ApiResponseError} from "./api";

const nullableNumber = z.preprocess(
  (value) => value === null || value === undefined || value === ""
    ? null
    : typeof value === "string"
      ? Number(value)
      : value,
  z.number().finite().nullable()
);

const authoritySchema = z.object({
  retailerId: z.string(),
  tenantId: z.string(),
  environment: z.string(),
  activationSetId: z.string(),
  bundleId: z.string(),
  bundleSemanticFingerprint: z.string(),
  sourcePublicationFingerprint: z.string(),
  sourceRunId: z.string(),
  sourceAsOf: z.string(),
  selectionIds: z.array(z.string()),
  priceMargin: z.object({
    available: z.boolean(),
    reasonCode: z.string().nullish(),
    minMarginPct: z.union([z.string(), z.number()])
  }).passthrough(),
  priceMarginActive: z.boolean()
}).passthrough();

const pricingEnvelope = {
  schemaVersion: z.literal("retail-pricing-page/v1"),
  dataMode: z.literal("live"),
  authority: authoritySchema
};

const recommendationItemSchema = z.object({
  recommendationId: z.string(),
  recordKind: z.enum(["recommendation", "withheld_assessment"]),
  selectable: z.boolean(),
  marketId: z.string(),
  skuId: z.string(),
  productName: z.string().nullish(),
  category: z.string().nullish(),
  categoryLabel: z.string().nullish(),
  storeId: z.string(),
  storeName: z.string().nullish(),
  channelId: z.string(),
  channelName: z.string().nullish(),
  action: z.enum(["Increase", "Decrease", "Hold"]).nullish(),
  currentPriceMinor: nullableNumber,
  proposedPriceMinor: nullableNumber,
  currencyCode: z.string(),
  changePct: nullableNumber.optional(),
  competitorPriceMinor: nullableNumber.optional(),
  stockCoverDays: nullableNumber.optional(),
  forecastDemand: z.enum(["High", "Medium", "Low"]).nullish(),
  forecastUnits: z.union([z.string(), z.number()]).nullish(),
  currentMarginPct: nullableNumber.optional(),
  expectedMarginPct: nullableNumber.optional(),
  revenueImpactMinor: nullableNumber,
  marginImpactMinor: nullableNumber,
  marginReasonCode: z.string().nullish(),
  aiReason: z.string().nullish(),
  confidence: nullableNumber,
  priority: z.string(),
  risk: z.string(),
  firstFailureReason: z.string().nullish(),
  status: z.string().nullish(),
  owner: z.string().nullish(),
  legalCandidatePricesMinor: z.array(z.number().int()).optional(),
  details: z.record(z.string(), z.unknown()).optional()
}).passthrough();

export const recommendationSummarySchema = z.object({
  ...pricingEnvelope,
  capabilities: z.record(z.string(), z.unknown()),
  filters: z.object({
    stores: z.array(z.string()),
    channels: z.array(z.string()),
    categories: z.array(z.string())
  }),
  kpis: z.object({
    openRecommendations: z.number().int().nonnegative(),
    revenueOpportunityMinor: nullableNumber,
    marginOpportunityMinor: nullableNumber,
    marginReasonCode: z.string().nullish(),
    recommendationsAtRisk: z.number().int().nonnegative(),
    riskReason: z.string(),
    recommendationAdoption: nullableNumber,
    adoptionReason: z.string()
  }),
  recommendationMix: z.array(z.object({
    label: z.enum([
      "Increase price", "Reduce price", "Hold price", "Manual review"
    ]),
    count: z.number().int().nonnegative()
  })),
  approvalPipeline: z.object({
    available: z.boolean(),
    reason: z.string(),
    labels: z.array(z.string())
  })
}).passthrough();

export const recommendationsSchema = z.object({
  ...pricingEnvelope,
  items: z.array(recommendationItemSchema),
  pagination: z.object({
    offset: z.number().int().nonnegative(),
    limit: z.number().int().positive(),
    total: z.number().int().nonnegative(),
    ranking: z.string().optional()
  })
}).passthrough();

export const recommendationDetailSchema = z.object({
  ...pricingEnvelope,
  item: recommendationItemSchema
}).passthrough();

export const groupedRecommendationsSchema = z.object({
  ...pricingEnvelope,
  dimension: z.enum(["store", "category"]),
  items: z.array(z.record(z.string(), z.unknown()))
}).passthrough();

export const governanceSchema = z.object({
  ...pricingEnvelope,
  approvalSLA: z.object({
    available: z.boolean(),
    reason: z.string()
  }).passthrough(),
  controls: z.array(z.object({
    label: z.string(),
    valuePct: nullableNumber,
    available: z.boolean()
  }).passthrough())
}).passthrough();

export const competitorSummarySchema = z.object({
  ...pricingEnvelope,
  kpis: z.object({
    productsMonitored: z.number().int().nonnegative(),
    aboveMarket: z.number().int().nonnegative(),
    belowMarket: z.number().int().nonnegative(),
    competitorOutOfStock: z.number().int().nonnegative(),
    matchesNeedingReview: z.number().int().nonnegative()
  }),
  quality: z.object({
    autoAccepted: z.number().int().nonnegative(),
    manualReview: z.number().int().nonnegative(),
    rejected: z.number().int().nonnegative(),
    averageConfidencePct: nullableNumber
  }).optional()
}).passthrough();

const competitorMatchSchema = z.object({
  matchId: z.string(),
  skuId: z.string(),
  ourProduct: z.string().nullish(),
  competitorName: z.string().nullish(),
  matchedProduct: z.string().nullish(),
  ourPriceMinor: nullableNumber,
  competitorPriceMinor: nullableNumber,
  priceGapPct: nullableNumber,
  currencyCode: z.string(),
  availability: z.string(),
  lastUpdated: z.string().nullish(),
  confidence: nullableNumber,
  status: z.string(),
  freshness: z.string(),
  firstExclusionReason: z.string().nullish(),
  recommendedResponse: z.string().optional(),
  details: z.record(z.string(), z.unknown()).optional()
}).passthrough();

export const competitorMatchesSchema = z.object({
  ...pricingEnvelope,
  items: z.array(competitorMatchSchema),
  pagination: z.object({
    offset: z.number().int().nonnegative(),
    limit: z.number().int().positive(),
    total: z.number().int().nonnegative()
  })
}).passthrough();

export const competitorDetailSchema = z.object({
  ...pricingEnvelope,
  item: competitorMatchSchema
}).passthrough();

export const alertRulesSchema = z.object({
  ...pricingEnvelope,
  available: z.boolean(),
  reasonCode: z.string(),
  message: z.string(),
  items: z.array(z.record(z.string(), z.unknown()))
}).passthrough();

export const promotionPayloadSchema = z.object({
  ...pricingEnvelope,
  surface: z.string(),
  plannerAvailable: z.boolean(),
  reasonCode: z.string(),
  message: z.string(),
  disposition: z.record(z.string(), z.unknown()),
  items: z.array(z.record(z.string(), z.unknown()))
}).passthrough();

const scenarioResultSchema = z.object({
  priceMinor: z.number(),
  units: z.number(),
  revenueMinor: z.number(),
  grossMarginMinor: nullableNumber,
  grossMarginReasonCode: z.string().nullish(),
  endingStockUnits: nullableNumber
}).passthrough();

export const priceSimulationSchema = z.object({
  schemaVersion: z.literal("retail-price-simulation/v1"),
  scope: z.object({
    market_id: z.string(),
    sku_id: z.string(),
    store_id: z.string(),
    channel_id: z.string()
  }),
  currencyCode: z.string(),
  simulationPeriod: z.literal("Next 4 Weeks"),
  demandAssumption: z.enum(["Expected", "Best Case", "Worst Case"]),
  demandScenarioSemantics: z.literal(
    "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
  ),
  inventoryObjective: z.enum(["Margin Protection", "Clearance"]),
  columns: z.object({
    current: scenarioResultSchema,
    proposed: scenarioResultSchema,
    aiOptimal: scenarioResultSchema
  }),
  metricOrder: z.tuple([
    z.literal("Units"), z.literal("Revenue"),
    z.literal("Gross Margin"), z.literal("Ending Stock")
  ]),
  recommendation: z.object({
    priceMinor: z.number(),
    revenueImpactMinor: z.number(),
    marginImpactMinor: nullableNumber,
    marginReasonCode: z.string().nullish(),
    stockOutRisk: z.string(),
    confidence: z.number()
  }).passthrough(),
  competitorEvidence: z.object({
    included: z.boolean(),
    reasonCode: z.string().nullish()
  }).passthrough(),
  mutated: z.literal(false)
}).passthrough();

export type PricingAuthority = z.infer<typeof authoritySchema>;
export type RecommendationSummary = z.infer<typeof recommendationSummarySchema>;
export type Recommendations = z.infer<typeof recommendationsSchema>;
export type Recommendation = z.infer<typeof recommendationItemSchema>;
export type RecommendationDetail = z.infer<typeof recommendationDetailSchema>;
export type GroupedRecommendations = z.infer<typeof groupedRecommendationsSchema>;
export type PricingGovernance = z.infer<typeof governanceSchema>;
export type CompetitorSummary = z.infer<typeof competitorSummarySchema>;
export type CompetitorMatches = z.infer<typeof competitorMatchesSchema>;
export type CompetitorMatch = z.infer<typeof competitorMatchSchema>;
export type AlertRules = z.infer<typeof alertRulesSchema>;
export type PromotionPayload = z.infer<typeof promotionPayloadSchema>;
export type PriceSimulation = z.infer<typeof priceSimulationSchema>;

export type PricingFilters = {
  storeId?: string;
  channelId?: string;
  channelType?: string;
  category?: string;
  action?: string;
  confidence?: string;
  search?: string;
  matchStatus?: string;
  competitorId?: string;
  freshness?: string;
  recordKind?: string;
  sort?: string;
  offset?: number;
  limit?: number;
};

export type PriceSimulationRequest = {
  recommendationId: string;
  proposedPriceMinor: number;
  simulationPeriod: "Next 4 Weeks";
  demandAssumption: "Expected" | "Best Case" | "Worst Case";
  inventoryObjective: "Margin Protection" | "Clearance";
  expectedActivationSetId: string;
};

export type PricingExportRequest = {
  scope: "selected" | "filtered" | "all";
  format: "csv" | "excel_csv";
  includeExplanation: boolean;
  filename: string;
  expectedCount: number;
  expectedActivationSetId: string;
  selectedIds: string[];
  filters: PricingFilters;
};

function withQuery(path: string, filters: PricingFilters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  // The API ignores these unless a developer explicitly enabled its local-only,
  // non-mutating demo adapter. Keeping the switch in the URL makes failure-state
  // captures reproducible without editing data or application code.
  const pageQuery = new URLSearchParams(window.location.search);
  const demoState = pageQuery.get("demoState");
  const demoPanel = pageQuery.get("demoPanel");
  if (["stale", "missing", "corrupt", "panel"].includes(demoState ?? "")) {
    query.set("demoState", demoState!);
    if (demoState === "panel" && demoPanel) query.set("demoPanel", demoPanel);
  }
  return query.size > 0 ? `${path}?${query}` : path;
}

async function get<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal) {
  const response = await fetch(path, {
    headers: {Accept: "application/json"},
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiResponseError(path, response.status, payload);
  return schema.parse(payload);
}

async function post<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
  signal?: AbortSignal
) {
  const response = await fetch(path, {
    method: "POST",
    headers: {Accept: "application/json", "Content-Type": "application/json"},
    body: JSON.stringify(body),
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiResponseError(path, response.status, payload);
  return schema.parse(payload);
}

export const loadRecommendationSummary = (
  filters: PricingFilters,
  signal?: AbortSignal
) => get(
  withQuery("/api/v1/pricing/recommendations/summary", filters),
  recommendationSummarySchema,
  signal
);

export const loadRecommendations = (filters: PricingFilters, signal?: AbortSignal) =>
  get(
    withQuery("/api/v1/pricing/recommendations", filters),
    recommendationsSchema,
    signal
  );

export const loadRecommendationDetail = (id: string, signal?: AbortSignal) =>
  get(
    `/api/v1/pricing/recommendations/${encodeURIComponent(id)}`,
    recommendationDetailSchema,
    signal
  );

export const loadGroupedRecommendations = (
  dimension: "store-view" | "category-view",
  filters: PricingFilters,
  signal?: AbortSignal
) => get(
  withQuery(`/api/v1/pricing/recommendations/${dimension}`, filters),
  groupedRecommendationsSchema,
  signal
);

export const loadPricingGovernance = (
  filters: PricingFilters,
  signal?: AbortSignal
) => get(
  withQuery("/api/v1/pricing/recommendations/governance", filters),
  governanceSchema,
  signal
);

export const loadCompetitorSummary = (
  filters: PricingFilters,
  signal?: AbortSignal
) => get(
  withQuery("/api/v1/competitors/summary", filters),
  competitorSummarySchema,
  signal
);

export const loadCompetitorMatches = (
  filters: PricingFilters,
  signal?: AbortSignal
) => get(
  withQuery("/api/v1/competitors/matches", filters),
  competitorMatchesSchema,
  signal
);

export const loadCompetitorDetail = (
  id: string,
  filters: PricingFilters,
  signal?: AbortSignal
) =>
  get(
    withQuery(`/api/v1/competitors/matches/${encodeURIComponent(id)}`, filters),
    competitorDetailSchema,
    signal
  );

export const loadAlertRules = (signal?: AbortSignal) =>
  get("/api/v1/competitors/alert-rules", alertRulesSchema, signal);

export const loadPromotionSurface = (
  surface: "summary" | "opportunities" | "portfolio" | "calendar",
  signal?: AbortSignal
) => get(`/api/v1/promotions/${surface}`, promotionPayloadSchema, signal);

export const runPriceSimulation = (
  request: PriceSimulationRequest,
  signal?: AbortSignal
) => post(
  "/api/v1/pricing/simulations:run",
  request,
  priceSimulationSchema,
  signal
);

export async function exportPriceRecommendations(
  request: PricingExportRequest,
  signal?: AbortSignal
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(request.filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  params.set("scope", request.scope);
  params.set("format", request.format);
  params.set("includeExplanation", request.includeExplanation ? "yes" : "no");
  params.set("filename", request.filename);
  params.set("expectedCount", String(request.expectedCount));
  params.set("expectedActivationSetId", request.expectedActivationSetId);
  if (request.selectedIds.length > 0) params.set("ids", request.selectedIds.join(","));
  const path = `/api/v1/pricing/export?${params}`;
  const response = await fetch(path, {headers: {Accept: "text/csv"}, signal});
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiResponseError(path, response.status, payload);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /^attachment; filename="([A-Za-z0-9_.-]+\.csv)"$/.exec(disposition);
  if (!match) throw new Error("Pricing export response has an invalid file name.");
  const count = Number(response.headers.get("X-Export-Count"));
  if (!Number.isInteger(count) || count !== request.expectedCount) {
    throw new Error("Pricing export response count differs from the reviewed scope.");
  }
  return {
    blob: await response.blob(),
    filename: match[1],
    exportId: response.headers.get("X-Export-ID"),
    scopeRevision: response.headers.get("X-Scope-Revision")
  };
}
