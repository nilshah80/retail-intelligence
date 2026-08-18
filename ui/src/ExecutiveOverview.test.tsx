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

function renderOverview(onNavigate = vi.fn()) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ExecutiveOverview
          dashboard={dashboard}
          storeId=""
          channelType=""
          forecastSummary={forecastSummary}
          forecastSummaryPending={false}
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
  it("keeps the original KPI and card order with governed live executive measures", async () => {
    const {container} = renderOverview();
    expect(screen.getByRole("status")).toHaveTextContent("Loading Executive Overview");
    expect(screen.queryByText("Not available", {exact: true})).not.toBeInTheDocument();
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
