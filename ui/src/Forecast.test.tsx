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
      accuracyGrain: "series_key" as const,
      portfolioAccuracy: 92.8,
      portfolioBias: -.054,
      portfolioBaselineAccuracy: 90.4,
      portfolioFvaVsMa13Pct: 25.3,
      portfolioAccuracyGrain: "market_portfolio" as const,
      baselineAccuracyGrain: "series_key" as const,
      fvaGrain: "series_key" as const,
      accuracy: 91.2,
      bias: .01,
      p90Coverage: .89,
      baselineAccuracy: 78.1,
      fvaVsMa13Pct: 31.4,
      demandAtRiskMinor: 175_857_036_449,
      demandAtRiskUnits: 168_537.33,
      demandAtRiskCells: 3174,
      demandAtRiskLocations: 13,
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
    })),
    seriesCoverage: {covered: 73_513, series: 76_824, ratio: .956901},
    horizonRange: {min: 1, max: 2, cap: 4}
  },
  horizons: {
    ...envelope,
    schemaVersion: "retail-forecast-horizons/v1",
    metricGrain: "market_portfolio",
    metricSemantics: "exact_horizon_additive",
    coverageGrain: "series_key",
    coverageNote: "P90 coverage is measured at SeriesKey grain because quantiles do not aggregate; a sum of P90 bounds is not the P90 of the sum.",
    slowMoverThreshold: .60,
    slowMoverDefinition: "origin-visible zero_share_52w > 0.60" as const,
    items: Array.from({length: 26}, (_, index) => ({
      horizon: index + 1,
      metricGrain: "market_portfolio",
      coverageGrain: "series_key",
      grainCells: 26,
      absErrorSum: 5,
      signedErrorSum: 1,
      actualSum: 100,
      coverageHits: 90,
      n: 100,
      wape: .05,
      bias: .01,
      accuracy: 95,
      p90Coverage: .9,
      slowMover: {
        horizon: index + 1,
        grainCells: 10,
        absErrorSum: 3,
        signedErrorSum: -2.5,
        actualSum: 10,
        wape: .3,
        bias: -.25,
        accuracy: 70
      }
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
      p90Coverage: .9,
      demandAtRiskMinor: 12_500_000,
      demandAtRiskUnits: 25,
      demandAtRiskCells: 3,
      stockoutRisk: "Medium"
    }]
  },
  series: {
    ...envelope,
    schemaVersion: "retail-forecast-series/v1",
    items: [{
      rowId: "forecast_0123456789abcdef0123",
      marketId: "india-west",
      skuId: "FOODS_1_001",
      storeId: "india-west:mumbai-bandra",
      channelId: "store",
      departmentId: "FOODS_1",
      category: "FOODS",
      productName: "Whole Wheat Bread",
      channelType: "marketplace",
      storeName: "Bandra Flagship",
      storeCity: "Mumbai",
      horizonWeeks: 4,
      baseline: 40,
      aiForecast: 44,
      aiForecastP90: 51,
      plannerForecast: null,
      lastActual: 10,
      lastActualWeek: "2026-07-20",
      wape: .2,
      accuracyState: "measured" as const,
      accuracyGrain: "series_key" as const,
      demandSharePct: 1.5,
      accuracy: 94,
      bias: .02,
      confidence: .88,
      // A clean 4-week window: nothing withheld, so both interval cells stay
      // numeric. The mixed-window branch has its own fixture below.
      confidenceState: "measured" as const,
      confidenceCoveredWindowMean: .88,
      aiForecastP90State: "available" as const,
      intervalCoveredFromHorizon: 1,
      intervalCoveredThroughHorizon: 4,
      intervalWithheldWeeks: 0,
      intervalUnavailableReason: null,
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

/**
 * Resolve each endpoint independently, so a test can hold ONE query pending (or
 * fail it) while the rest land. Immediately-resolved mocks cannot express the
 * states that matter here -- they were why a page-level gate looked harmless.
 */
function deferredFetch(options: {
  hold?: string[];
  reject?: string[];
} = {}) {
  const holds = new Map<string, () => void>();
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(responses).find((candidate) =>
      url.includes(`/forecast/${candidate}`)
    ) ?? "summary";
    const held = options.hold?.find((name) => url.includes(`/forecast/${name}`));
    if (held) {
      await new Promise<void>((resolve) => holds.set(held, resolve));
    }
    if (options.reject?.some((name) => url.includes(`/forecast/${name}`))) {
      throw new Error(`${key} is unavailable`);
    }
    return {ok: true, json: async () => responses[key]};
  }));
  return {release: (name: string) => holds.get(name)?.()};
}

function renderForecast(channelType = "") {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <DemandForecast
        dashboard={dashboard}
        storeId=""
        onStoreId={() => undefined}
        channelType={channelType}
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
    expect(screen.queryByLabelText("Comparison basis")).not.toBeInTheDocument();
    expect(screen.getByText(
      "Last 8 comparable weeks · freshest forecast within h1–h4 · 95.7% P90 coverage across 76,824 series-weeks"
    )).toBeInTheDocument();
    // Scoped to the KPI: this figure also appears in a metric row, so a bare
    // getByText is ambiguous and asserts nothing about which element carries it.
    expect(
      screen.getByText("Demand at Risk").closest(".kpi")?.querySelector(".value")?.textContent
    ).toBe("₹175.86 Cr");
    expect(screen.getByText("Potential unserved sales exposure across 13 distributors"))
      .toBeInTheDocument();
    const actionLabels = within(screen.getByLabelText("Forecast actions"))
      .getAllByRole("button")
      .map((button) => button.childNodes[0]?.textContent?.trim());
    expect(actionLabels).toEqual([
      "Accept Forecast",
      "Add Planner Adjustment",
      "Compare Versions",
      "Scenario Planning",
      "Forecast Action Center",
      "Export"
    ]);
    const acceptTrigger = screen.getByRole("button", {name: /^Accept Forecast/});
    expect(acceptTrigger).toBeEnabled();
    expect(acceptTrigger).toHaveTextContent("Accept Forecast");
    expect(acceptTrigger).toHaveTextContent("Accept Forecast");
    fireEvent.click(acceptTrigger);
    let dialog = screen.getByRole("dialog", {name: "Accept Forecast"});
    expect(within(dialog).getByRole("heading", {name: "Accept Forecast"})).toHaveFocus();
    expect(Array.from(dialog.querySelectorAll(".metric-row > span")).map((node) => node.textContent)).toEqual(["Selected Forecasts", "Average Confidence", "Forecast Demand (units)"]);
    expect(within(dialog).getByRole("button", {name: "Confirm Acceptance"})).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", {name: "Cancel"}));
    expect(acceptTrigger).toHaveFocus();

    fireEvent.click(screen.getByRole("button", {name: /^Add Planner Adjustment/}));
    dialog = screen.getByRole("dialog", {name: "Add Planner Adjustment"});
    expect(Array.from((within(dialog).getByRole("combobox", {name: "Adjustment Reason"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["Local event", "Promotion change", "Competitor event", "Operational constraint", "Commercial judgement"]);
    expect(Array.from((within(dialog).getByRole("combobox", {name: "Effective Period"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["Next Week", "Next 4 Weeks", "Specific Date Range"]);
    expect(within(dialog).getByRole("button", {name: "Save Adjustment"})).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", {name: "Cancel"}));
    // Every FVA surface reads portfolio grain, so all of them must show the same
    // value: the "Forecast Value Add" KPI, the "Net FVA" row inside that card,
    // and "Forecast value add (vs MA13)" in Business Impact. Pinning the count is
    // the consistency check -- a surface that disagreed would drop out of it.
    expect(screen.getAllByText("+25.3%")).toHaveLength(3);
    expect(screen.getByText("Slow / intermittent: -25.0% · 10.0% of actual volume"))
      .toBeInTheDocument();
    // This used to require MORE than four bare "Not available" tokens, which is
    // the opposite of the contract the page now holds: a governed absence renders
    // an honest short label with the reason on the title (see `advisory` in
    // Forecast.tsx), and the bare token appears nowhere.
    expect(screen.queryAllByText("Not available", {exact: true})).toHaveLength(0);

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
        "AI Forecast (P50)",
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
    expect(within(workbench).getByText("Marketplace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: "Compare Versions"}));
    dialog = screen.getByRole("dialog", {name: "Compare Forecast Versions"});
    expect(within(dialog).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Version", "Created By", "Accuracy", "Bias", "Demand Units", "Status"]);
    fireEvent.click(within(dialog).getByRole("button", {name: "Close"}));

    fireEvent.click(screen.getByRole("button", {name: /^Forecast Action Center/}));
    dialog = screen.getByRole("dialog", {name: "Forecast Action Center"});
    expect(within(dialog).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Action Queue", "Items", "Owner", "Business Exposure"]);
    expect(within(dialog).getAllByRole("row").slice(1).map((row) => row.firstElementChild?.textContent)).toEqual(["Under-forecast review", "Over-forecast review", "Data-quality correction", "Model retraining"]);
    fireEvent.click(within(dialog).getByRole("button", {name: "Close"}));

    fireEvent.click(screen.getByRole("tab", {name: "Store View"}));
    fireEvent.click(screen.getByRole("button", {name: "Open Store Drilldown"}));
    dialog = screen.getByRole("dialog", {name: "Store Forecast Drilldown"});
    expect(Array.from((within(dialog).getByRole("combobox", {name: "Period"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["Next 4 Weeks", "Next 8 Weeks"]);
    expect(within(dialog).getByText("Store Forecast Health")).toBeInTheDocument();
    expect(within(dialog).getByText("Recommended Actions")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", {name: "Open Store Forecasts"})).toBeEnabled();
  });

  it("runs a tuple-pinned scenario with dirty-key-only overrides", async () => {
    const context = {
      schemaVersion: "retail-forecast-scenario-context-bootstrap/v1",
      forecastVersion: envelope.versionId,
      scenarioContextVersion: "a".repeat(64),
      inventory: null,
      scenarioDecisionAsOf: envelope.decisionAsOf
    };
    const coverage = {numerator: 1, denominator: 1, grain: "series_key", pct: 100};
    const floatMetric = {
      current: {availability: "available", value: 100, reasonCodes: []},
      scenario: {availability: "available", value: 102, reasonCodes: []},
      impact: {availability: "available", value: 2, reasonCodes: []},
      impactPct: 2,
      coverage
    };
    const unavailableMoney = {
      currencyCode: null,
      rateMapContentFingerprint: null,
      current: {availability: "unavailable", valueMinor: null, reasonCodes: ["REPORTING_FX_UNAVAILABLE"]},
      scenario: {availability: "unavailable", valueMinor: null, reasonCodes: ["REPORTING_FX_UNAVAILABLE"]},
      impact: {availability: "unavailable", valueMinor: null, reasonCodes: ["REPORTING_FX_UNAVAILABLE"]},
      coverage: {numerator: 0, denominator: 1, grain: "money_fact", pct: 0}
    };
    const localMoney = {
      marketId: "india-west",
      currencyCode: "INR",
      current: {availability: "available", valueMinor: 16_400_000_000, reasonCodes: []},
      scenario: {availability: "available", valueMinor: 18_600_000_000, reasonCodes: []},
      impact: {availability: "available", valueMinor: 2_200_000_000, reasonCodes: []},
      coverage: {numerator: 1, denominator: 1, grain: "money_fact", pct: 100}
    };
    const scenarioResponse = {
      schemaVersion: "retail-forecast-scenario-assumption/v1",
      dataMode: "assumption_projection",
      authority: {
        forecastVersion: context.forecastVersion,
        scenarioContextVersion: context.scenarioContextVersion,
        inventory: null
      },
      scenarioDecisionAsOf: context.scenarioDecisionAsOf,
      assumptionSetId: "approved-v1",
      assumptionVersion: "1",
      assumptionSemanticFingerprint: "b".repeat(64),
      assumptionApprovalEventId: 1,
      assumptionApprovalSemanticFingerprint: "c".repeat(64),
      presetId: "expected_demand",
      resolvedVector: {
        demandAdjustmentPct: 0,
        priceChangePct: 2,
        promotionUpliftPct: 0,
        competitorAvailability: "normal",
        weatherEvent: "normal",
        atpAdjustment: 0
      },
      factorBasis: Object.fromEntries([
        "demandAdjustment",
        "promotionUplift",
        "priceResponse",
        "competitorSensitivity",
        "weatherSensitivity",
        "atpAdjustment"
      ].map((factor) => [factor, {
        valueSource: factor === "priceResponse" ? "user_override" : "preset",
        coefficientSource: factor === "priceResponse"
          ? "assumption_bundle"
          : "not_applicable_direct_input"
      }])),
      projectionBasis: "assumption_set",
      evidenceClass: "synthetic_scenario",
      statisticalGateStatus: "not_applicable",
      disclosure: "Assumption-based projection; not fitted or causal.",
      priceSnapshotContentFingerprint: "d".repeat(64),
      priceProvenance: [],
      calculation: {
        demandUnits: floatMetric,
        revenuePotential: [localMoney],
        reportingRevenuePotential: unavailableMoney,
        requiredInventoryUnits: floatMetric,
        requiredInventoryValue: [localMoney],
        reportingRequiredInventoryValue: unavailableMoney,
        demandWeightedSeriesStockoutRiskPct: {...floatMetric, impactPct: undefined, impactPoints: 2},
        appliedPrices: [],
        appliedPriceSummaries: [{
          marketId: "india-west",
          currencyCode: "INR",
          availability: "available",
          requestedPriceChangePct: 2,
          baselineValueWeightedAppliedPriceChangePct: 2,
          reasonCodes: [],
          coverage
        }]
      }
    };
    let posted: unknown;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input);
      if (url.includes("/forecast/scenario/context")) {
        return {ok: true, status: 200, json: async () => context};
      }
      if (url.endsWith("/forecast/scenario") && init?.method === "POST") {
        posted = JSON.parse(String(init.body));
        return {ok: true, status: 200, json: async () => scenarioResponse};
      }
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      return {ok: true, status: 200, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast("marketplace");
    await screen.findByText("Forecast vs Actual");
    fireEvent.click(screen.getByRole("button", {name: "Scenario Planning"}));
    const dialog = await screen.findByRole("dialog", {name: "Demand Scenario Planning"});
    fireEvent.change(await within(dialog).findByLabelText("Price Change (%)"), {
      target: {value: "2"}
    });
    fireEvent.click(within(dialog).getByRole("button", {name: "Run Scenario"}));
    expect(await within(dialog).findByRole("heading", {name: "Scenario Results"})).toBeInTheDocument();
    const comparison = within(dialog).getByRole("table", {name: "Scenario comparison"});
    expect(within(comparison).getByText("Current Forecast")).toBeInTheDocument();
    expect(within(comparison).getByText("Revenue Potential · India West")).toBeInTheDocument();
    expect(within(dialog).getAllByText("₹18.6 Cr").length).toBeGreaterThan(0);
    expect(within(comparison).getAllByText("+₹2.2 Cr").length).toBeGreaterThan(0);
    expect(within(dialog).queryByText(/Assumption-based projection; not fitted or causal/))
      .not.toBeInTheDocument();
    expect(posted).toMatchObject({
      presetId: "expected_demand",
      userOverrides: {priceChangePct: 2},
      businessScope: {channelId: "", channelType: "marketplace"},
      expectedAuthority: {inventory: null}
    });
    expect((posted as {userOverrides: Record<string, unknown>}).userOverrides)
      .toEqual({priceChangePct: 2});
		fireEvent.keyDown(document, {key: "Escape"});
		expect(screen.queryByRole("dialog", {name: "Scenario Results"}))
		  .not.toBeInTheDocument();
		expect(screen.getByRole("button", {name: "Scenario Planning"}))
		  .toHaveFocus();
  });

  it("always renders four exact-horizon health rows in reference order", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      return {ok: true, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast();

    await screen.findByText("Forecast Health by Horizon");
    const table = screen.getByText("Forecast Health by Horizon")
      .closest(".card")!
      .querySelector("table")!;
    const rows = [...table.querySelectorAll("tbody tr")];

    // Decision #80: exactly four rows, reference labels, reference order — and
    // the toolbar still defaults to Next 4 Weeks, which must not hide h8/h13.
    expect(rows).toHaveLength(4);
    expect(rows.map((row) => row.querySelector("td")!.textContent)).toEqual([
      "1 week",
      "4 weeks",
      "8 weeks",
      "13 weeks"
    ]);
    expect(rows.map((row) => row.getAttribute("data-horizon"))).toEqual([
      "1",
      "4",
      "8",
      "13"
    ]);
    // h26 stays diagnostic and is never a fifth default row.
    expect(table.textContent).not.toContain("26 weeks");
    // Cumulative labelling is gone.
    expect(table.textContent).not.toContain("Weeks 1–");
  });

  it("keeps the four health rows when the operational horizon cap changes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      return {ok: true, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast();

    await screen.findByText("Forecast Health by Horizon");
    const horizonSelect = document.querySelector("#forecastHorizonFilter")!;
    fireEvent.change(horizonSelect, {target: {value: "Next 26 Weeks"}});
    // Changing the cap refetches, so wait for the panel to come back.
    await screen.findByText("Forecast Health by Horizon");

    const table = screen.getByText("Forecast Health by Horizon")
      .closest(".card")!
      .querySelector("table")!;
    expect(table.querySelectorAll("tbody tr")).toHaveLength(4);
    expect(table.textContent).not.toContain("26 weeks");
  });

  it("derives health status from the governed matrix, not coverage alone", async () => {
    // Every horizon here is 95% accurate with 1% bias and 0.90 coverage. Under
    // market/portfolio targets (90/88/85/82) that is Strong at h1 only when the
    // margin reaches +5; h4/h8/h13 have larger margins and stay Strong too.
    // Coverage 0.90 sits inside the Strong band, so a coverage-only rule could
    // not distinguish these rows at all.
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      return {ok: true, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast();

    await screen.findByText("Forecast Health by Horizon");
    const table = screen.getByText("Forecast Health by Horizon")
      .closest(".card")!
      .querySelector("table")!;
    const statuses = [...table.querySelectorAll("tbody tr")].map((row) =>
      row.querySelectorAll("td")[4].textContent
    );

    // 95% accuracy against a 90 target is +5 => Strong; the vocabulary must be
    // the reference four-state set, never the old two-state coverage badge.
    expect(statuses).toEqual(["Strong", "Strong", "Strong", "Strong"]);
    for (const status of statuses) {
      expect(["Strong", "Healthy", "Watch", "Action", "Not available"])
        .toContain(status);
    }
  });

  it("never renders the HTML sample values when a forecast route fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderForecast();
    expect(await screen.findByText("Live forecast data is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("87.6%")).not.toBeInTheDocument();
    expect(screen.queryByText("Phoenix Market City")).not.toBeInTheDocument();
  });

  // Decision #64 Q19 / parity amendment P4-0P-A1.
  //
  // The screen offers 4/8/13/26 weeks and decision #92 withholds the cold-start
  // interval from h5, so every selection except the default mixes horizons that
  // carry an interval with horizons that do not. The server sends the
  // arithmetically corrected covered-window mean; the cell must still not show it,
  // because an h1-h4 figure under a "Confidence" heading beside a whole-window
  // forecast states a scope this table never displays.
  it("marks workbench confidence unavailable when the selected window is mixed", async () => {
    const workbench = responses.series as {items: Record<string, unknown>[]};
    const mixed = {
      ...workbench.items[0],
      horizonWeeks: 26,
      confidence: null,
      confidenceState: "unavailable_mixed_window",
      // Present and honest, and still not rendered: the corrected figure exists
      // so the absence is explicable, not so the cell can quietly show it.
      confidenceCoveredWindowMean: .5817,
      aiForecastP90: null,
      aiForecastP90State: "unavailable_mixed_window",
      intervalCoveredFromHorizon: 1,
      intervalCoveredThroughHorizon: 4,
      intervalWithheldWeeks: 22,
      intervalUnavailableReason: "COLD_START_INTERVAL_UNCALIBRATED"
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const key = Object.keys(responses).find((candidate) =>
        url.includes(`/forecast/${candidate}`)
      );
      if (key === "series" && url.includes("view=workbench")) {
        return {ok: true, json: async () => ({...workbench, items: [mixed]})};
      }
      return {ok: true, json: async () => responses[key ?? "summary"]};
    }));
    renderForecast();

    await screen.findByText("Forecast vs Actual");
    fireEvent.click(screen.getByRole("tab", {name: "SKU View"}));
    const table = await screen.findByRole("table");
    const headers = within(table).getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    const confidenceIndex = headers.indexOf("Confidence");
    expect(confidenceIndex).toBeGreaterThan(-1);

    const cells = within(table).getAllByRole("cell");
    const confidenceCell = cells[confidenceIndex];
    // Parity amendment P4-0P-A1: the approved unavailable state NAMES the window
    // it would have covered rather than emitting the bare "Not available" token
    // (see `advisory` in Forecast.tsx, which exists precisely to avoid it). So
    // the cell must read the covered window, carry the .unavailable marker for
    // styling and audit, and must NOT show the bare token.
    expect(confidenceCell).toHaveTextContent("Weeks 1–4");
    expect(confidenceCell).not.toHaveTextContent("Not available");
    expect(confidenceCell.querySelector(".unavailable")).not.toBeNull();
    // The corrected value must not leak into the cell under an unqualified
    // heading. 58.2% is the honest covered-window figure and still the wrong
    // thing to show here.
    expect(confidenceCell).not.toHaveTextContent("58.2%");
    // The absence has to be explicable, so the covered window is named.
    expect(confidenceCell.querySelector(".unavailable")?.getAttribute("title"))
      .toContain("weeks 1-4");
  });

  it("keeps a loaded Overview when an inactive tab's query fails", async () => {
    // The workbench request feeds SKU View and the modals only. When pending was
    // tab-scoped but errors were still aggregated across all eight queries, this
    // failure replaced a fully-rendered Overview with the fatal card.
    deferredFetch({reject: ["series"]});
    renderForecast();

    expect(await screen.findByText("Forecast vs Actual")).toBeInTheDocument();
    expect(screen.queryByText("Live forecast data is unavailable.")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", {name: "Overview"})).toBeInTheDocument();

    // The failure is reported on the tab that actually reads it, not swallowed.
    fireEvent.click(screen.getByRole("tab", {name: "SKU View"}));
    expect(await screen.findByText("This view is unavailable.")).toBeInTheDocument();
    // ...and the shell survives it, so the user can navigate back.
    expect(screen.getByRole("tab", {name: "Overview"})).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", {name: "Overview"}));
    expect(screen.getByText("Forecast vs Actual")).toBeInTheDocument();
  });

  it("tells the user why a modal is empty when its source failed", async () => {
    // Reachable only because a failed query no longer kills the page: the
    // Compare Versions dialog reads `versions`, which no tab renders.
    deferredFetch({reject: ["versions"]});
    renderForecast();

    expect(await screen.findByText("Forecast vs Actual")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: /^Compare Versions/}));
    const dialog = await screen.findByRole("dialog", {name: "Compare Forecast Versions"});
    expect(within(dialog).getByText("This view is unavailable.")).toBeInTheDocument();
    expect(within(dialog).getByText(/versions is unavailable/)).toBeInTheDocument();
    // EXCLUSIVE: the normal body must not render underneath the explanation, or
    // the dialog says "no fallback values are displayed" directly above a table
    // of blanks.
    expect(within(dialog).queryByRole("table")).not.toBeInTheDocument();
  });

  it("replaces the modal body with the explanation rather than layering it", async () => {
    // The Adjustment dialog reads workbench, so a workbench failure is the case
    // where a non-exclusive error leaves blank Product/Store/forecast fields
    // sitting under the message.
    deferredFetch({reject: ["series"]});
    renderForecast();

    expect(await screen.findByText("Forecast vs Actual")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: /^Add Planner Adjustment/}));
    const dialog = await screen.findByRole("dialog", {name: "Add Planner Adjustment"});
    expect(within(dialog).getByText("This view is unavailable.")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Product / SKU")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Workflow unavailable")).not.toBeInTheDocument();
  });

  it("keeps the shell mounted while a newly selected tab is still loading", async () => {
    const {release} = deferredFetch({hold: ["series"]});
    renderForecast();

    expect(await screen.findByText("Forecast vs Actual")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", {name: "SKU View"}));
    // The panel shows the loading state; the toolbar, KPI row and tab strip stay.
    expect(screen.getByText("Loading the accepted forecast…")).toBeInTheDocument();
    expect(screen.getByLabelText("Forecast actions")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(screen.getByText("Forecast Accuracy")).toBeInTheDocument();

    release("series");
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
