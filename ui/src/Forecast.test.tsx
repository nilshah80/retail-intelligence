// @vitest-environment jsdom

import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {cleanup, fireEvent, render, screen, within} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, describe, expect, it, vi} from "vitest";
import {DemandForecast} from "./Forecast";
import type {Dashboard} from "./api";

const dashboard: Dashboard = {
  schemaVersion: "retail-data-management-dashboard/v1",
  dataMode: "live",
  kpis: {
    dataFreshnessPct: 100,
    qualityScorePct: 100,
    connectedSources: 3,
    rejectedRecords: 0,
    lastRefreshAt: "2026-07-30T00:00:00Z"
  },
  sources: [],
  footer: {
    totalSkus: 1440,
    activeSkus: 720,
    stores: 4,
    channels: 2,
    forecastCoveragePct: null,
    modelAccuracyPct: null
  },
  filters: {
    dateRange: {start: "2016-07-28", end: "2026-07-28"},
    markets: [{marketId: "india-west", name: "India West"}],
    stores: [{
      storeId: "india-west:mumbai-bandra",
      marketId: "india-west",
      name: "Bandra Flagship",
      currencyCode: "INR",
      timezone: "Asia/Kolkata",
      region: "MH",
      format: "store",
      city: "Mumbai",
      active: true
    }],
    channelTypes: [{
      type: "store",
      name: "Store",
      marketIds: ["india-west"]
    }],
    currencies: ["INR"]
  }
};

const envelope = {
  dataMode: "live",
  versionId: "fv_a00fe79a86768419",
  forecastRunId: "fr_b2f18d0e2999a36d",
  semanticFingerprint: "5".repeat(64),
  publicationFingerprint: "d".repeat(64),
  activationScopeFingerprint: "f".repeat(64),
  decisionAsOf: "2026-07-27T00:00:00Z",
  markets: ["india-west"]
};

const responses: Record<string, unknown> = {
  summary: {
    ...envelope,
    schemaVersion: "retail-forecast-summary/v1",
    items: [{
      accuracy: 91.2,
      bias: .01,
      p90Coverage: .89,
      baselineAccuracy: 78.1,
      fvaVsMa13Pct: 31.4,
      demandUnits: 1000,
      seriesCount: 1,
      exceptionCount: 2,
      exceptionCounts: {
        high_under_forecast_risk: 1,
        high_over_forecast_risk: 0,
        new_product_sparse_history: 1,
        data_quality_exception: 0
      },
      qualityCounts: {Good: 1},
      forecastCoveragePct: 100,
      backtestCoveragePct: 100,
      categories: ["FOODS"]
    }]
  },
  actuals: {
    ...envelope,
    schemaVersion: "retail-forecast-actuals/v1",
    items: Array.from({length: 8}, (_, index) => ({
      targetWeekStart: `2026-0${index < 4 ? "6" : "7"}-${String(1 + (index % 4) * 7).padStart(2, "0")}`,
      forecast: 100 + index,
      actual: 95 + index
    }))
  },
  horizons: {
    ...envelope,
    schemaVersion: "retail-forecast-horizons/v1",
    items: Array.from({length: 26}, (_, index) => ({
      horizon: index + 1,
      absErrorSum: 5,
      signedErrorSum: 1,
      actualSum: 100,
      coverageHits: 90,
      n: 100,
      wape: .05,
      bias: .01,
      accuracy: 95,
      p90Coverage: .9
    }))
  },
  stores: {
    ...envelope,
    schemaVersion: "retail-forecast-stores/v1",
    items: [{
      ...dashboard.filters.stores[0],
      name: "Bandra Flagship",
      city: "Mumbai",
      accuracy: 92,
      bias: .01,
      p90Coverage: .9
    }]
  },
  series: {
    ...envelope,
    schemaVersion: "retail-forecast-series/v1",
    items: [{
      marketId: "india-west",
      skuId: "FOODS_1_001",
      storeId: "india-west:mumbai-bandra",
      channelId: "store",
      departmentId: "FOODS_1",
      category: "FOODS",
      productName: "Whole Wheat Bread",
      channelType: "store",
      storeName: "Bandra Flagship",
      storeCity: "Mumbai",
      horizonWeeks: 4,
      baseline: 40,
      aiForecast: 44,
      aiForecastP90: 51,
      plannerForecast: null,
      lastActual: 10,
      lastActualWeek: "2026-07-20",
      accuracy: 94,
      bias: .02,
      confidence: .88,
      primaryDriver: "seasonality",
      dataQuality: "Good",
      priority: "Low",
      exceptionClass: null,
      status: "Active"
    }],
    pagination: {offset: 0, limit: 100, total: 1}
  },
  drivers: {
    ...envelope,
    schemaVersion: "retail-forecast-drivers/v1",
    items: [
      ["demand_trend", "25.0000"],
      ["seasonality", "25.0000"],
      ["price", "20.0000"],
      ["competitor_activity", "15.0000"],
      ["weather_local_events", "15.0000"]
    ].map(([driver, contributionPct]) => ({
      scope: "portfolio",
      driver,
      contributionPct,
      direction: "Up",
      confidence: ".8"
    })),
    unavailableItems: [{
      driver: "promo",
      label: "Promotion plan",
      reasonCode: "NO_ORIGIN_VISIBLE_PROMOTION_PLAN"
    }]
  },
  signals: {
    ...envelope,
    schemaVersion: "retail-forecast-signals/v1",
    freshnessBaseline: "2026-07-27T00:00:00Z",
    items: [
      ["promotion_calendar", "Promotion calendar", "NO_ORIGIN_VISIBLE_PROMOTION_PLAN"],
      ["competitor_pricing", "Competitor pricing", "SIGNAL_FRESHNESS_NOT_MATERIALIZED"],
      ["weather", "Weather feed", "SIGNAL_FRESHNESS_NOT_MATERIALIZED"],
      ["local_events", "Local event feed", "NO_ORIGIN_VISIBLE_LOCAL_EVENT_PLAN"],
      ["macro", "Macroeconomic index", "SIGNAL_FRESHNESS_NOT_MATERIALIZED"]
    ].map(([signal, label, reasonCode]) => ({
      signal,
      label,
      status: "unavailable",
      reasonCode,
      knownAsOf: null
    }))
  },
  versions: {
    ...envelope,
    schemaVersion: "retail-forecast-versions/v1",
    items: [{
      versionId: envelope.versionId,
      kind: "AI",
      originDate: "2026-07-27",
      horizonWeeks: 26,
      createdBy: "retail_ml",
      accuracy: 91.2,
      bias: .01,
      demandUnits: 1000,
      semanticFingerprint: envelope.semanticFingerprint,
      artifactStatus: "accepted",
      lifecycleStatus: "active"
    }]
  }
};

function renderForecast() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <DemandForecast
        dashboard={dashboard}
        storeId=""
        onStoreId={() => undefined}
        channelType=""
      />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Demand Forecast parity contract", () => {
  it("renders live values, exact action/tab order and governed unavailable states", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      return {ok: true, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast();

    expect(await screen.findByText("Forecast vs Actual")).toBeInTheDocument();
    const actionLabels = within(screen.getByLabelText("Forecast actions"))
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(actionLabels).toEqual([
      "Accept Forecast",
      "Add Planner Adjustment",
      "Compare Versions",
      "Scenario Planning",
      "Forecast Action Center",
      "Export"
    ]);
    expect(screen.getByRole("button", {name: "Accept Forecast"})).toBeDisabled();
    expect(screen.getAllByText("+31.4%")).toHaveLength(2);
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(4);

    const tabLabels = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabLabels).toEqual([
      "Overview",
      "Store View",
      "SKU View",
      "Demand Drivers",
      "Governance"
    ]);

    fireEvent.click(screen.getByRole("tab", {name: "SKU View"}));
    const workbench = screen.getByRole("table");
    expect(within(workbench).getAllByRole("columnheader").map((cell) => cell.textContent))
      .toEqual([
        "",
        "Priority",
        "SKU / Product",
        "Store",
        "Baseline",
        "AI Forecast",
        "Planner Forecast",
        "Last Actual",
        "Accuracy",
        "Bias",
        "Confidence",
        "Primary Driver",
        "Data Quality",
        "Status"
      ]);
    expect(within(workbench).getByText("Whole Wheat Bread")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: "Compare Versions"}));
    expect(screen.getByRole("dialog", {name: "Compare Versions"})).toBeInTheDocument();
  });

  it("never renders the HTML sample values when a forecast route fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderForecast();
    expect(await screen.findByText("Live forecast data is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("87.6%")).not.toBeInTheDocument();
    expect(screen.queryByText("Phoenix Market City")).not.toBeInTheDocument();
  });
});
