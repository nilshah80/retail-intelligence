// @vitest-environment jsdom

import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    loadExecutiveOverview: vi.fn(),
    loadForecastActuals: vi.fn(),
    loadForecastStores: vi.fn(),
    loadInventorySlice: vi.fn()
  };
});

vi.mock("./pricingApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./pricingApi")>();
  return {
    ...actual,
    loadRecommendationSummary: vi.fn(),
    loadGroupedRecommendations: vi.fn(),
    loadPricingGovernance: vi.fn()
  };
});

import {
  loadExecutiveOverview,
  loadForecastActuals,
  loadForecastStores,
  loadInventorySlice,
  type Dashboard,
  type ForecastSummary,
  type InventorySlice
} from "./api";
import {ExecutiveOverview} from "./ExecutiveOverview";
import {
  loadGroupedRecommendations,
  loadPricingGovernance,
  loadRecommendationSummary
} from "./pricingApi";

const dashboard: Dashboard = {
  schemaVersion: "retail-data-management-dashboard/v1",
  dataMode: "live",
  kpis: {
    dataFreshnessPct: 100,
    qualityScorePct: 99.8,
    connectedSources: 3,
    rejectedRecords: 0,
    lastRefreshAt: "2026-08-18T00:00:00Z"
  },
  sources: [],
  footer: {
    totalSkus: 720,
    activeSkus: 348,
    stores: 2,
    channels: 2,
    forecastCoveragePct: 99,
    modelAccuracyPct: 92.8
  },
  filters: {
    dateRange: {start: "2025-08-18", end: "2026-08-18"},
    markets: [{marketId: "india-west", name: "India West"}],
    stores: [
      {
        storeId: "india-west:mumbai",
        marketId: "india-west",
        name: "Phoenix Market City, Mumbai",
        currencyCode: "INR",
        timezone: "Asia/Kolkata",
        region: "West",
        format: "store",
        city: "Mumbai",
        active: true
      },
      {
        storeId: "india-west:pune",
        marketId: "india-west",
        name: "Pune Koregaon Park",
        currencyCode: "INR",
        timezone: "Asia/Kolkata",
        region: "West",
        format: "store",
        city: "Pune",
        active: true
      }
    ],
    channelTypes: [{type: "store", name: "Store", marketIds: ["india-west"]}],
    channels: [{channelId: "store", marketId: "india-west", name: "Store", type: "store"}],
    categories: [
      {categoryId: "footwear", name: "Footwear"},
      {categoryId: "apparel", name: "Apparel"}
    ],
    currencies: ["INR"]
  }
};

const forecastSummary = {
  schemaVersion: "retail-forecast-summary/v1",
  dataMode: "live",
  versionId: "fv-1",
  forecastRunId: "fr-1",
  semanticFingerprint: "semantic",
  publicationFingerprint: "publication",
  activationScopeFingerprint: "scope",
  decisionAsOf: "2026-08-18",
  markets: ["india-west"],
  items: [{
    accuracy: 72.3,
    accuracyGrain: "series_key",
    portfolioAccuracy: 92.8,
    portfolioBias: 0.5,
    portfolioBaselineAccuracy: 68.5,
    portfolioFvaVsMa13Pct: 24.3,
    portfolioAccuracyGrain: "market_portfolio",
    baselineAccuracyGrain: "series_key",
    fvaGrain: "series_key",
    bias: 0.5,
    p90Coverage: 91,
    baselineAccuracy: 68.5,
    fvaVsMa13Pct: 24.3,
    demandUnits: 1000,
    seriesCount: 100,
    exceptionCount: 8,
    exceptionCounts: {under_forecast: 8},
    qualityCounts: {measured: 100},
    forecastCoveragePct: 99,
    backtestCoveragePct: 96,
    demandAtRiskMinor: 132_400_000_000,
    demandAtRiskUnits: 400,
    demandAtRiskCells: 18,
    demandAtRiskLocations: 2,
    categories: ["footwear", "apparel"]
  }]
} as ForecastSummary;

function inventorySlice(
  summary: Record<string, number | string | null> = {},
  cards: Record<string, Array<Record<string, unknown>>> = {},
  items: Array<Record<string, unknown>> = []
) {
  return {
    schemaVersion: "retail-inventory-page/v1",
    dataMode: "live",
    inventoryRunId: "ir-1",
    inventoryVersionId: "iv-1",
    semanticFingerprint: "inventory-semantic",
    forecastAuthority: {forecastRunId: "fr-1", forecastVersionId: "fv-1"},
    policyVersion: "inventory-policy/2.0.0",
    markets: ["india-west"],
    reportingCurrency: "INR",
    summary,
    cards,
    items
  } as InventorySlice;
}

const locationCards = [
  {
    locationId: "india-west:mumbai",
    locationName: "Phoenix Market City, Mumbai",
    valueMinor: 97_830_000_000,
    availabilityPct: 0.96,
    daysOfSupply: 42,
    overstockPct: 0.08,
    understockPct: 0.04,
    stockoutRisk: "Low",
    priorityAction: "Protect price"
  },
  {
    locationId: "india-west:pune",
    locationName: "Pune Koregaon Park",
    valueMinor: 62_000_000_000,
    availabilityPct: 0.81,
    daysOfSupply: 64,
    overstockPct: 0.24,
    understockPct: 0.12,
    stockoutRisk: "High",
    priorityAction: "Transfer inventory"
  }
];

const authority = {
  retailerId: "retailer",
  tenantId: "tenant",
  environment: "prod",
  activationSetId: "activation",
  bundleId: "bundle",
  bundleSemanticFingerprint: "bundle-semantic",
  sourcePublicationFingerprint: "source-publication",
  sourceRunId: "source-run",
  sourceAsOf: "2026-08-18",
  selectionIds: ["selection"],
  priceMargin: {available: true, minMarginPct: "0.2"},
  priceMarginActive: true
};

function installMocks() {
  vi.mocked(loadExecutiveOverview).mockResolvedValue({
    schemaVersion: "retail-executive-overview/v1",
    dataMode: "live",
    inventoryRunId: "ir-1",
    inventoryVersionId: "iv-1",
    semanticFingerprint: "inventory-semantic",
    forecastAuthority: {forecastRunId: "fr-1", forecastVersionId: "fv-1"},
    policyVersion: "inventory-policy/2.0.0",
    markets: ["india-west"],
    reportingCurrency: "INR",
    decisionAsOf: "2026-08-18T00:00:00Z",
    periods: {
      ltm: {start: "2025-08-19", end: "2026-08-18"},
      prior_ltm: {start: "2024-08-19", end: "2025-08-18"},
      month_to_date: {start: "2026-08-01", end: "2026-08-18"},
      prior_year_month_to_date: {start: "2025-08-01", end: "2025-08-18"},
      quarter_to_date: {start: "2026-07-01", end: "2026-08-18"},
      prior_year_quarter_to_date: {start: "2025-07-01", end: "2025-08-18"}
    },
    summary: {
      ltmRevenueMinor: 1_526_000_000_000,
      ltmPriorRevenueMinor: 1_404_000_000_000,
      ltmGrowthPct: 8.7,
      ltmGrossMarginPct: 28.4,
      ltmPriorGrossMarginPct: 26.3,
      ltmNetUnits: 2_000_000,
      ltmCostCoveragePct: 100,
      grossMarginDeltaPts: 2.1,
      monthRevenueMinor: 128_000_000_000,
      monthPriorRevenueMinor: 120_000_000_000,
      monthGrowthPct: 6.7,
      monthGrossMarginPct: 28.4,
      monthPriorGrossMarginPct: 27.8,
      monthNetUnits: 170_000,
      monthCostCoveragePct: 100,
      inventoryValueMinor: 159_830_000_000,
      overstockValueMinor: 63_000_000_000,
      inventoryDays: 54,
      sellThroughPct: 62.7,
      stockoutRatePct: 5.4,
      stockoutCells: 54,
      inventoryCells: 1000,
      forecastAccuracyPct: 92.8
    },
    stores: dashboard.filters.stores.map((store, index) => ({
      storeId: store.storeId,
      monthRevenueMinor: index ? 52_000_000_000 : 76_000_000_000,
      monthPriorRevenueMinor: index ? 55_000_000_000 : 69_000_000_000,
      monthGrowthPct: index ? -5.5 : 10.1,
      monthGrossMarginPct: index ? 25.8 : 30.2,
      monthPriorGrossMarginPct: index ? 26.1 : 29.4,
      monthNetUnits: index ? 70_000 : 100_000,
      monthCostCoveragePct: 100,
      inventoryValueMinor: index ? 62_000_000_000 : 97_830_000_000,
      overstockValueMinor: index ? 20_000_000_000 : 8_000_000_000,
      inventoryDays: index ? 64 : 42,
      sellThroughPct: index ? 58 : 68,
      stockoutRatePct: index ? 8 : 2,
      stockoutCells: index ? 40 : 10,
      inventoryCells: 500
    })),
    regions: [{
      region: "West",
      quarterRevenueMinor: 390_000_000_000,
      quarterPriorRevenueMinor: 355_000_000_000,
      quarterGrowthPct: 9.9,
      quarterGrossMarginPct: 28.7,
      quarterPriorGrossMarginPct: 27.9,
      quarterNetUnits: 510_000,
      quarterCostCoveragePct: 100,
      inventoryValueMinor: 159_830_000_000,
      overstockValueMinor: 28_000_000_000,
      inventoryDays: 50.5,
      sellThroughPct: 64,
      stockoutRatePct: 5,
      stockoutCells: 50,
      inventoryCells: 1000,
      forecastAccuracyPct: 88.6
    }],
    categories: [
      {
        category: "footwear", quarterRevenueMinor: 326_000_000_000,
        quarterPriorRevenueMinor: 300_000_000_000, quarterGrowthPct: 8.7,
        quarterGrossMarginPct: 29.8, quarterPriorGrossMarginPct: 28.9,
        quarterNetUnits: 300_000, quarterCostCoveragePct: 100,
        inventoryValueMinor: 100_000_000_000, overstockValueMinor: 10_000_000_000,
        inventoryDays: 47, sellThroughPct: 76, stockoutRatePct: 4,
        stockoutCells: 20, inventoryCells: 500
      },
      {
        category: "apparel", quarterRevenueMinor: 284_000_000_000,
        quarterPriorRevenueMinor: 278_000_000_000, quarterGrowthPct: 2.2,
        quarterGrossMarginPct: 27.4, quarterPriorGrossMarginPct: 27,
        quarterNetUnits: 280_000, quarterCostCoveragePct: 100,
        inventoryValueMinor: 59_830_000_000, overstockValueMinor: 18_000_000_000,
        inventoryDays: 62, sellThroughPct: 69, stockoutRatePct: 6,
        stockoutCells: 30, inventoryCells: 500
      }
    ],
    basis: {
      revenue: "Canonical net sales after typed financial refunds.",
      grossMargin: "Net sales less net fulfilled units valued at current WAC.",
      comparison: "Prior-year comparison.",
      inventory: "Current positions.",
      forecastAccuracy: "Exact additive WAPE."
    },
    scopeNotes: {
      inventoryChannelScope: true,
      inventoryChannelScopeReason: "Inventory has no channel grain."
    }
  });
  vi.mocked(loadForecastActuals).mockResolvedValue({
    schemaVersion: "retail-forecast-actuals/v1",
    dataMode: "live",
    versionId: "fv-1",
    forecastRunId: "fr-1",
    semanticFingerprint: "semantic",
    publicationFingerprint: "publication",
    activationScopeFingerprint: "scope",
    decisionAsOf: "2026-08-18",
    markets: ["india-west"],
    items: Array.from({length: 8}, (_, index) => ({
      targetWeekStart: `2026-0${index + 1}-01`,
      forecast: 100 + index * 10,
      actual: 96 + index * 11
    }))
  });
  vi.mocked(loadForecastStores).mockResolvedValue({
    schemaVersion: "retail-forecast-stores/v1",
    dataMode: "live",
    versionId: "fv-1",
    forecastRunId: "fr-1",
    semanticFingerprint: "semantic",
    publicationFingerprint: "publication",
    activationScopeFingerprint: "scope",
    decisionAsOf: "2026-08-18",
    markets: ["india-west"],
    items: dashboard.filters.stores.map((store, index) => ({
      ...store,
      accuracy: index ? 78.9 : 91.6,
      bias: index ? -4.2 : 0.8,
      p90Coverage: 90,
      demandAtRiskMinor: index ? 90_000_000_000 : 42_400_000_000,
      demandAtRiskUnits: index ? 250 : 150,
      demandAtRiskCells: index ? 11 : 7,
      stockoutRisk: index ? "High" : "Low"
    }))
  });
  vi.mocked(loadInventorySlice).mockImplementation(async (endpoint) => {
    if (endpoint.includes("/inventory/overview")) {
      return inventorySlice(
        {
          onHandValueMinor: 307_140_000_000,
          atRiskValueMinor: 8_400_000_000,
          stockTurn: 13.1
        },
        {
          locations: locationCards,
          categories: [
            {category: "footwear", categoryLabel: "Footwear", valueMinor: 190_000_000_000, daysOfSupply: 47, riskClass: "Watch", riskAction: "Protect full-price sales"},
            {category: "apparel", categoryLabel: "Apparel", valueMinor: 117_140_000_000, daysOfSupply: 62, riskClass: "High", riskAction: "Targeted promotion"}
          ]
        }
      );
    }
    if (endpoint.includes("/inventory/stores")) {
      return inventorySlice({onHandValueMinor: 159_830_000_000}, {locations: locationCards});
    }
    if (endpoint.includes("/inventory/valuation")) {
      return inventorySlice({provisionMarkdownMinor: 1_640_000_000});
    }
    if (endpoint.includes("/inventory/expiry-waste")) {
      return inventorySlice({nearExpiryValueMinor: 900_000_000});
    }
    if (endpoint.includes("/inventory/transfers")) {
      return inventorySlice({rows: 5, transferValueMinor: 399_900_000, expectedBenefitMinor: 388_900_000});
    }
    return inventorySlice({rows: 7, warnings: 3}, {}, [{exceptionLabel: "Forecast gap", severity: "Warning"}]);
  });
  vi.mocked(loadRecommendationSummary).mockResolvedValue({
    schemaVersion: "retail-pricing-page/v1",
    dataMode: "live",
    authority,
    capabilities: {},
    filters: {stores: [], channels: [], categories: []},
    kpis: {
      openRecommendations: 1093,
      revenueOpportunityMinor: 474_300_000,
      marginOpportunityMinor: 46_400_000,
      marginReasonCode: null,
      recommendationsAtRisk: 46,
      competitorCovered: 900,
      recommendationAdoption: {adopted: 765, total: 1093, sharePct: 70}
    },
    recommendationMix: [
      {label: "Increase price", count: 120},
      {label: "Reduce price", count: 420},
      {label: "Hold price", count: 500},
      {label: "Manual review", count: 53}
    ],
    approvalPipeline: [
      {label: "Pending analyst review", count: 203},
      {label: "Rejected", count: 59}
    ],
    exceptions: [{label: "Outside guardrails", count: 46}],
    decisionQuality: {
      highConfidencePct: 91,
      withinGuardrailCount: 1047,
      withinGuardrailPct: 95.8,
      realizedCycles: 0,
      needingOverride: 46
    },
    businessValueByDriver: [],
    portfolioScenarios: []
  });
  vi.mocked(loadGroupedRecommendations).mockImplementation(async (dimension) => ({
    schemaVersion: "retail-pricing-page/v1",
    dataMode: "live",
    authority,
    dimension: dimension === "store-view" ? "store" : "category",
    items: dimension === "store-view"
      ? [
        {store: "india-west:mumbai", storeName: "Phoenix Market City, Mumbai", recommendations: 600, revenueOpportunityMinor: 260_000_000, marginOpportunityMinor: 28_000_000, risk: 12, priorityAction: "Protect price"},
        {store: "india-west:pune", storeName: "Pune Koregaon Park", recommendations: 493, revenueOpportunityMinor: 214_300_000, marginOpportunityMinor: 18_400_000, risk: 34, priorityAction: "Review pricing + demand"}
      ]
      : [
        {category: "footwear", categoryLabel: "Footwear", recommendations: 600, revenueOpportunityMinor: 300_000_000, marginOpportunityMinor: 30_000_000, priorityAction: "Protect full-price sales"},
        {category: "apparel", categoryLabel: "Apparel", recommendations: 493, revenueOpportunityMinor: 174_300_000, marginOpportunityMinor: 16_400_000, priorityAction: "Targeted promotion"}
      ]
  }));
  vi.mocked(loadPricingGovernance).mockResolvedValue({
    schemaVersion: "retail-pricing-page/v1",
    dataMode: "live",
    authority,
    approvalSLA: {available: false, reason: "Approval workflow evidence is not available."},
    controls: []
  });
}

/**
 * Hold the executive/inventory/pricing sources pending, so the tests can observe
 * what the page states BEFORE any evidence has arrived. Immediately-resolved
 * mocks cannot see this window, which is why removing the page-level gate looked
 * free.
 */
function installPendingMocks() {
  const never = () => new Promise(() => undefined);
  vi.mocked(loadExecutiveOverview).mockImplementation(never as never);
  vi.mocked(loadForecastStores).mockImplementation(never as never);
  vi.mocked(loadInventorySlice).mockImplementation(never as never);
  vi.mocked(loadRecommendationSummary).mockImplementation(never as never);
  vi.mocked(loadGroupedRecommendations).mockImplementation(never as never);
}

function renderOverview(onNavigate = vi.fn(), summaryPending = false, storeId = "") {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ExecutiveOverview
          dashboard={dashboard}
          storeId={storeId}
          channelType=""
          forecastSummary={summaryPending ? undefined : forecastSummary}
          forecastSummaryPending={summaryPending}
          forecastSummaryError={null}
          onNavigate={onNavigate}
        />
      </QueryClientProvider>
    ),
    onNavigate
  };
}

beforeEach(() => {
  installMocks();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("Executive Overview parity", () => {
  it("states no verdict before its evidence arrives", async () => {
    installPendingMocks();
    // The forecast summary arrives as a PROP, so holding only the queries pending
    // would leave it loaded and make verdicts derived from it legitimate. Hold it
    // too, so the test describes a genuine nothing-has-loaded state.
    const {container} = renderOverview(vi.fn(), true);

    // The shell paints immediately -- that is the point of having no page gate.
    expect(screen.getByRole("button", {name: "Open Action Center"})).toBeInTheDocument();

    // But nothing may state a conclusion yet. These rows are always rendered, so
    // without their own pending signal they resolved their ternaries against
    // undefined data and read as findings: "New", "Watch", "Observed",
    // "Unavailable". A verdict derived from data that has not loaded is not a
    // governed absence, it is a fabricated one.
    // Every verdict this page can state from an empty ternary. Enumerated rather
    // than sampled: the earlier version of this test omitted "Review", "Pending"
    // and "High", and each omission was a live gap.
    const fabricated = [
      "New", "Ahead", "Watch", "Observed", "Unavailable", "Improving",
      "High", "Action", "Pending", "Review", "In Progress", "Escalated",
      "No signal", "At Risk", "Healthy", "Overstock", "Strong"
    ];
    const badges = Array.from(container.querySelectorAll(".badge"), (n) => n.textContent?.trim());
    for (const label of fabricated) {
      expect(badges, `"${label}" was stated before its data loaded`).not.toContain(label);
    }
    expect(badges.filter((b) => b === "Loading…").length).toBeGreaterThan(0);

    // The two prop-derived tables must route through their loading row rather
    // than rendering a full body of defaulted measures.
    expect(screen.queryAllByText("No signal")).toHaveLength(0);
    expect(screen.queryAllByText("Review store detail")).toHaveLength(0);
    expect(screen.getAllByText("Loading live data…").length).toBeGreaterThan(0);

    // "4 live signals" is a claim about data, and the four decision statements
    // beneath it must not read as governed absences while merely loading.
    expect(screen.queryByText("4 live signals")).not.toBeInTheDocument();

    // The strong invariant: while NOTHING has resolved, nothing can be governed-
    // absent. `UnavailableValue` always carries data-unavailable="true", so the
    // weaker "every Not available has a cause" check passed even when the real
    // state was "still loading" -- which is how the AI Value Realization metrics
    // slipped through. A governed absence asserts the platform cannot produce a
    // value; that cannot be known before the request that would establish it has
    // come back.
    const governedAbsences = Array.from(
      container.querySelectorAll("[data-unavailable=\"true\"]"),
      (n) => n.getAttribute("title") ?? n.textContent?.trim()
    );
    expect(
      governedAbsences,
      "a governed absence was asserted before its source resolved"
    ).toEqual([]);
    expect(screen.queryAllByText("Not available", {exact: true})).toHaveLength(0);

    // Not a value cell but the same error: this note reads
    // `!data?.approvalSLA.available`, which is true while the request is still in
    // flight, so it asserted "no SLA is configured" before asking.
    expect(screen.queryByText(/no time-based approval SLA is configured/)).not.toBeInTheDocument();
  });

  it("never claims live signals while any one decision statement is loading", async () => {
    // One leg at a time. The header flag has to cover all four statements, and a
    // flag missing ANY leg is only visible in the partial state where that leg
    // alone is pending -- which is reachable here: per-route holds for the three
    // query-backed legs, and the independent summary prop for the fourth.
    const never = () => new Promise(() => undefined);
    const holdSlice = (path: string) => {
      const real = vi.mocked(loadInventorySlice).getMockImplementation()!;
      vi.mocked(loadInventorySlice).mockImplementation(((endpoint: string, ...rest: never[]) =>
        String(endpoint).includes(path)
          ? never()
          : real(endpoint as never, ...rest)) as never);
    };
    const legs: Array<{leg: string; hold?: () => void; summaryPending?: boolean}> = [
      {leg: "markdown provision (inventoryValuation)", hold: () => holdSlice("/inventory/valuation")},
      {leg: "demand at risk (forecast summary)", summaryPending: true},
      {leg: "price recommendations (pricingSummary)",
        hold: () => vi.mocked(loadRecommendationSummary).mockImplementation(never as never)},
      {leg: "worst store (forecastStores)",
        hold: () => vi.mocked(loadForecastStores).mockImplementation(never as never)}
    ];

    for (const {leg, hold, summaryPending} of legs) {
      cleanup();
      installMocks();
      hold?.();
      renderOverview(vi.fn(), summaryPending ?? false);
      await screen.findByText("Critical Decisions Required");
      await waitFor(() => {
        const statements = Array.from(
          document.querySelectorAll(".alert span"), (n) => n.textContent?.trim());
        expect(statements, `${leg}: its own statement should read Loading…`).toContain("Loading…");
      });
      expect(
        screen.queryByText("4 live signals"),
        `${leg}: the header claimed 4 live signals while that statement was loading`
      ).toBeNull();
    }
  });

  it("does not fabricate values in a dialog opened during load", async () => {
    // The toolbar is interactive from first paint, so these are reachable while
    // their measures are in flight. Their bodies are fixed rows, so without a
    // guard they state "0" open items and a bare "Not available" value at risk.
    installPendingMocks();
    const {container} = renderOverview(vi.fn(), true);

    for (const [button, title] of [
      ["Open Action Center", "Executive Action Center"],
      ["Store-Level Drilldown", "Store-Level Drilldown"],
      ["Business-Level Drilldown", "Business-Level Drilldown"]
    ] as const) {
      fireEvent.click(screen.getByRole("button", {name: button}));
      const dialog = await screen.findByRole("dialog", {name: title});
      expect(within(dialog).getByText(/Loading the accepted executive measures/))
        .toBeInTheDocument();
      // EXCLUSIVE: no fixed-row body underneath the message.
      expect(within(dialog).queryByRole("table"), `${title} rendered a body while loading`)
        .not.toBeInTheDocument();
      expect(within(dialog).queryAllByText("Not available", {exact: true})).toHaveLength(0);
      fireEvent.keyDown(document, {key: "Escape"});
    }
    // And nothing leaked into the page behind them.
    expect(container.querySelectorAll("[data-unavailable=\"true\"]")).toHaveLength(0);
  });

  it("does not show portfolio demand-at-risk while a scoped store is loading", async () => {
    // With a filter active, demandAtRisk switches source to forecastStores. If
    // only the portfolio summary is awaited, the scoped view silently falls back
    // to PORTFOLIO numbers -- the wrong scope, which is worse than a blank.
    installMocks();
    vi.mocked(loadForecastStores).mockImplementation((() => new Promise(() => undefined)) as never);
    renderOverview(vi.fn(), false, "india-west:mumbai-flagship");
    await screen.findByText("Critical Decisions Required");

    const rowValue = (label: string) =>
      screen.getByText(label).closest("tr")?.cells[1]?.textContent?.trim();
    expect(rowValue("Near stock-out"), "scoped demand-at-risk must not fall back to portfolio")
      .toBe("Loading…");
    const statements = Array.from(
      document.querySelectorAll(".alert span"), (n) => n.textContent?.trim());
    expect(statements, "the stock-out decision must not state a portfolio figure for a scoped view")
      .toContain("Loading…");
  });

  it("does not substitute portfolio demand-at-risk when a filter resolves empty", async () => {
    // The RESOLVED-empty case, not the pending one: a filtered request that comes
    // back with items: [] must read as a governed absence for that scope, never
    // as the portfolio total under a scoped heading.
    installMocks();
    vi.mocked(loadForecastStores).mockResolvedValue({
      schemaVersion: "retail-forecast-stores/v1",
      dataMode: "live",
      authority,
      items: []
    } as never);
    renderOverview(vi.fn(), false, "india-west:mumbai-flagship");
    await screen.findByText("Critical Decisions Required");

    const rowValue = (label: string) =>
      screen.getByText(label).closest("tr")?.cells[1]?.textContent?.trim();
    await waitFor(() => expect(rowValue("Near stock-out")).not.toBe("Loading…"));
    expect(rowValue("Near stock-out"), "an empty filtered scope must not show the portfolio total")
      .toBe("Not available");
    const kpi = Array.from(document.querySelectorAll(".executive-kpi"))
      .find((k) => k.querySelector("small")?.textContent === "Stock-out Loss (Est.)");
    expect(kpi?.querySelector(".value")?.textContent,
      "the KPI must not show the portfolio total for an empty filtered scope")
      .toBe("Not available");
  });

  it("waits for forecast stores before the Business drilldown states a verdict", async () => {
    // Unfiltered, demandAtRiskPending tracks only the summary, so the dialog's
    // "Model retraining" line -- which reads worstStore from forecastStores --
    // could state "No signal" while those rows were still in flight.
    installMocks();
    vi.mocked(loadForecastStores).mockImplementation((() => new Promise(() => undefined)) as never);
    renderOverview();
    await screen.findByText("Executive Business Health");

    // The Action Tracker row reads the same source for its VERDICT while taking
    // its value from demandAtRisk, so one flag for both let it state "Review"
    // here. Checked before opening the dialog, on the page itself.
    const trackerRow = screen.getByText("Resolve forecast underperformance").closest("tr");
    expect(trackerRow?.cells[5]?.textContent,
      "the forecast verdict reads worstStore, which is still loading")
      .toBe("Loading…");

    fireEvent.click(screen.getByRole("button", {name: "Business-Level Drilldown"}));
    const dialog = await screen.findByRole("dialog", {name: "Business-Level Drilldown"});
    expect(within(dialog).getByText(/Loading the accepted executive measures/)).toBeInTheDocument();
    expect(within(dialog).queryByText("No signal")).not.toBeInTheDocument();
  });

  it("shows Loading only on the cells whose own source is still pending", async () => {
    // STAGGERED, not all-pending. Holding every source at once cannot detect a
    // cell wired to the wrong query's flag -- both the right and the wrong flag
    // read pending. Holding ONE source and letting the rest resolve is what
    // separates them, and it is how the real page behaves: these requests return
    // at different times.
    const hold = <T,>(fn: T) => fn as never;
    const rowValue = (label: string) => {
      const cell = screen.getByText(label).closest("tr")?.cells[1];
      return cell?.textContent?.trim();
    };

    // (1) Hold ONLY the pricing-governance route. The approval-pipeline and
    // guardrail figures are derived from pricingSummary, so they must be REAL
    // here; keying them to pricingGovernance would show "Loading…" forever.
    installMocks();
    vi.mocked(loadPricingGovernance).mockImplementation(hold(() => new Promise(() => undefined)));
    const first = renderOverview();
    await screen.findByText("Pricing Governance");
    // waitFor is the discriminator: keyed to pricingSummary these resolve as soon
    // as it lands, but keyed to the held pricingGovernance they never would.
    for (const label of ["Under review", "Needs override", "Outside guardrails"]) {
      await waitFor(() =>
        expect(rowValue(label), `${label} is derived from pricingSummary, not pricingGovernance`)
          .not.toBe("Loading…"));
    }
    first.unmount();

    // (2) Hold ONLY the executive route. overstockValue and stockoutRate come
    // from executiveSummary, so they MUST be loading; keying them to
    // inventoryOverview would print a verdict from data that has not arrived.
    installMocks();
    vi.mocked(loadExecutiveOverview).mockImplementation(hold(() => new Promise(() => undefined)));
    renderOverview();
    await screen.findByText("Executive Business Health");
    // Wait until a row whose source DID resolve is populated, so the assertions
    // below describe a settled staggered state rather than t=0.
    await waitFor(() => expect(rowValue("At-risk inventory")).not.toBe("Loading…"));
    expect(rowValue("Stock-out cell rate"), "stockoutRate comes from executiveSummary").toBe("Loading…");
    expect(rowValue("Overstock"), "overstockValue comes from executiveSummary").toBe("Loading…");
    // ...while a sibling row fed by a source that DID resolve must not be.
    expect(rowValue("At-risk inventory"), "atRiskValue comes from inventoryOverview").not.toBe("Loading…");

    // (3) Hold ONLY /inventory/stores. worstStore reads forecastStores alone, so
    // its decision statement must already be settled -- guarding it on the whole
    // storeMeasuresPending set would make it wait on three unrelated queries and
    // give back the progressive-render gain.
    cleanup();
    installMocks();
    const realSlice = vi.mocked(loadInventorySlice).getMockImplementation()!;
    vi.mocked(loadInventorySlice).mockImplementation(((endpoint: string, ...rest: never[]) =>
      String(endpoint).includes("/inventory/stores")
        ? new Promise(() => undefined)
        : realSlice(endpoint as never, ...rest)) as never);
    renderOverview();
    await screen.findByText("Critical Decisions Required");
    await waitFor(() => {
      const statements = Array.from(
        document.querySelectorAll(".alert span"), (n) => n.textContent?.trim());
      expect(
        statements.some((s) => s?.includes("lowest measured store")),
        "the forecast-underperformance statement reads forecastStores only"
      ).toBe(true);
    });
  });

  it("keeps the original KPI and card order with governed live executive measures", async () => {
    const {container} = renderOverview();
    // The page deliberately has no page-level loading gate: waiting for all
    // thirteen sources meant first paint took MAX(latency) -- measured 1.30s,
    // spent on the one query that feeds a single chart -- while the headline KPI
    // query had already returned. The chrome now paints immediately and each
    // tile resolves on its own `pending` prop. What must STILL hold during that
    // window is the governed rule that nothing renders a bare "Not available".
    // There is no page-level loading gate any more: waiting on all thirteen
    // sources meant first paint cost MAX(latency) -- measured 1.30s, spent on the
    // one query feeding a single chart -- while the headline KPI query had
    // already returned at 0.53s. The chrome paints immediately instead.
    expect(screen.getByRole("button", {name: "Open Action Center"})).toBeInTheDocument();
    // The property that must hold now that tiles render before their data: a
    // pending KPI reads "Loading…", never "Not available". Conflating "still
    // loading" with "governed absent" is the specific way progressive rendering
    // could mislead, so it is asserted rather than assumed.
    for (const kpi of Array.from(container.querySelectorAll(".executive-kpi"))) {
      expect(kpi.querySelector(".value")?.textContent).not.toBe("Not available");
    }
    expect(await screen.findByText("Store Performance Heatmap")).toBeInTheDocument();

    expect(Array.from(container.querySelectorAll(".executive-kpi > small"), (node) => node.textContent)).toEqual([
      "Total Revenue (LTM)",
      "Gross Margin %",
      "Inventory Value",
      "Stock-out Loss (Est.)",
      "AI Forecast Accuracy"
    ]);
    expect(Array.from(container.querySelectorAll(".card-head > h3"), (node) => node.textContent)).toEqual([
      "Executive Business Health",
      "AI Value Realization",
      "Critical Decisions Required",
      "Store Performance Heatmap",
      "Regional Performance",
      "Category Performance",
      "Inventory Risk Exposure",
      "Pricing Governance",
      "Demand Forecast vs Actual",
      "Executive Action Tracker"
    ]);
    expect(await screen.findByText("₹307.14 Cr")).toBeInTheDocument();
    expect(await screen.findByText("92.8%")).toBeInTheDocument();
    expect(screen.getByText("Potential unserved-sales exposure; not realized loss")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-unavailable='true']")).toHaveLength(0);
    expect(document.getElementById("executiveStoreTable")).toBeInTheDocument();
    expect(document.getElementById("executiveActionTable")).toBeInTheDocument();
  });

  it("scopes live sources from the original region/category controls and routes card actions", async () => {
    const onNavigate = vi.fn();
    renderOverview(onNavigate);
    await screen.findByText("Store Performance Heatmap");

    fireEvent.change(screen.getByRole("combobox", {name: "Executive category"}), {
      target: {value: "footwear"}
    });
    await waitFor(() => expect(loadRecommendationSummary).toHaveBeenLastCalledWith(
      expect.objectContaining({category: "footwear"}),
      expect.anything()
    ));
    await waitFor(() => expect(loadInventorySlice).toHaveBeenCalledWith(
      "/api/v1/inventory/overview",
      expect.objectContaining({category: "footwear"}),
      expect.anything()
    ));
    const categoryCard = screen.getByRole("heading", {name: "Category Performance"})
      .closest(".card");
    expect(categoryCard).not.toBeNull();
    await waitFor(() => {
      expect(within(categoryCard as HTMLElement).getByRole("cell", {name: "Footwear"}))
        .toBeInTheDocument();
      expect(within(categoryCard as HTMLElement).queryByRole("cell", {name: "Apparel"}))
        .not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", {name: "View details"}));
    expect(onNavigate).toHaveBeenCalledWith("priceRecommendations");
  });

  it("provides the original dialogs and honest session-only review and print behavior", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    renderOverview();
    await screen.findByText("Store Performance Heatmap");

    const actionButton = screen.getByRole("button", {name: "Open Action Center"});
    fireEvent.click(actionButton);
    let dialog = screen.getByRole("dialog", {name: "Executive Action Center"});
    fireEvent.click(within(dialog).getByRole("button", {name: "Mark Reviewed"}));
    expect(within(dialog).getByRole("status")).toHaveTextContent("this browser session only");
    fireEvent.click(within(dialog).getByRole("button", {name: "Close"}));
    expect(actionButton).toHaveFocus();

    fireEvent.click(screen.getByRole("button", {name: "Store-Level Drilldown"}));
    dialog = screen.getByRole("dialog", {name: "Store-Level Drilldown"});
    expect(within(dialog).getByRole("combobox", {name: "Store"})).toBeInTheDocument();
    expect(within(dialog).getByText("Store KPIs")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", {name: "Close"}));

    fireEvent.click(screen.getByRole("button", {name: "Business-Level Drilldown"}));
    dialog = screen.getByRole("dialog", {name: "Business-Level Drilldown"});
    expect(within(dialog).getByText("Business Levers")).toBeInTheDocument();
    expect(within(dialog).getByText("Executive Decisions")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", {name: "Close"}));

    fireEvent.click(screen.getByRole("button", {name: "Export Executive Report"}));
    expect(print).toHaveBeenCalledOnce();
    expect(screen.getByRole("status")).toHaveTextContent("Choose Save as PDF");
  });
});
