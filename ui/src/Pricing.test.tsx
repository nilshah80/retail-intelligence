// @vitest-environment jsdom

import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, describe, expect, it, vi} from "vitest";
import {formatAggregateMoneyMinor, formatMoneyMinor, PricingPage, type PricingPageId} from "./Pricing";
import {categoryNameFromLabel} from "./dimensionLabels";

const authority = {
  retailerId: "gulf-oil-india",
  tenantId: "retail-demo",
  environment: "local",
  activationSetId: "pact_0123456789abcdef",
  bundleId: "pb_0123456789abcdef0123",
  bundleSemanticFingerprint: "a".repeat(64),
  sourcePublicationFingerprint: "b".repeat(64),
  sourceRunId: "run-2b0a15521a760e70",
  inputAuthorityId: "ia_0123456789abcdef",
  sourceAsOf: "2026-08-01T00:00:00Z",
  selectionIds: ["rsel_0123456789abcdef"],
  priceMargin: {available: true, reasonCode: null, minMarginPct: "12"},
  priceMarginActive: true
};

const recommendation = {
  recommendationId: "pr_0123456789abcdef0123",
  recordKind: "recommendation",
  selectable: true,
  marketId: "gulf-india",
  skuId: "gulf-india:sku-1",
  productName: "Gulf Formula GX 5W-30",
  category: "gulf-mco",
  categoryLabel: "Motorcycle Oils",
  storeId: "gulf-india:mumbai",
  storeName: "Mumbai Distributor",
  channelId: "gulf-india:gulf-online",
  channelName: "Gulf Direct Online",
  action: "Increase",
  currentPriceMinor: 20000,
  proposedPriceMinor: 20500,
  currencyCode: "INR",
  changePct: 2.5,
  competitorPriceMinor: 20700,
  stockCoverDays: 24.5,
  forecastDemand: "High",
  forecastUnits: "410",
  currentMarginPct: null,
  expectedMarginPct: null,
  revenueImpactMinor: 56000,
  marginImpactMinor: null,
  marginReasonCode: "COST_NOT_CLIENT_ACTUAL",
  aiReason: "[\"Inelastic demand supports a higher price\"]",
  confidence: 0.96,
  priority: "High",
  risk: "Low",
  firstFailureReason: null,
  status: null,
  owner: null,
  details: {
    clearance_context_available: true,
    forecast_scenario_semantics:
      "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
  },
  legalCandidatePricesMinor: [20000, 20500]
};

const secondRecommendation = {
  ...recommendation,
  recommendationId: "pr_abcdef0123456789abcd",
  skuId: "gulf-india:sku-2",
  productName: "Gulf Pride 4T Plus",
  action: "Decrease",
  proposedPriceMinor: 19500,
  changePct: -2.5,
  confidence: 0.93,
  priority: "Medium"
};

const recommendationSummary = {
  schemaVersion: "retail-pricing-page/v1",
  dataMode: "live",
  authority,
  capabilities: {},
  filters: {
    stores: ["gulf-india:mumbai"],
    channels: ["store"],
    categories: ["gulf-mco"]
  },
  kpis: {
    openRecommendations: 2,
    revenueOpportunityMinor: 92000,
    marginOpportunityMinor: null,
    marginReasonCode: "COST_NOT_CLIENT_ACTUAL",
    recommendationsAtRisk: 0,
    riskReason: "No approved non-blocking recommendation warning is present.",
    recommendationAdoption: null,
    adoptionReason: "Approval workflow evidence is not available."
  },
  recommendationMix: [
    {label: "Increase price", count: 1},
    {label: "Reduce price", count: 1},
    {label: "Hold price", count: 0},
    {label: "Manual review", count: 1}
  ],
  approvalPipeline: {
    available: false,
    reason: "Approval workflow evidence is not available.",
    labels: [
      "Pending analyst review",
      "Pending category manager",
      "Pending finance approval",
      "Approved, not scheduled",
      "Scheduled for publishing"
    ]
  }
};

const recommendationPage = {
  schemaVersion: "retail-pricing-page/v1",
  dataMode: "live",
  authority,
  items: [recommendation, secondRecommendation],
  pagination: {offset: 0, limit: 200, total: 2, ranking: "priority"}
};

const simulationResult = {
  schemaVersion: "retail-price-simulation/v1",
  scope: {
    market_id: "gulf-india",
    sku_id: recommendation.skuId,
    store_id: recommendation.storeId,
    channel_id: "store"
  },
  currencyCode: "INR",
  simulationPeriod: "Next 4 Weeks",
  demandAssumption: "Expected",
  demandScenarioSemantics:
    "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles",
  inventoryObjective: "Clearance",
  columns: {
    current: {priceMinor: 20000, units: 400, revenueMinor: 8000000, grossMarginMinor: null, grossMarginReasonCode: "COST_NOT_CLIENT_ACTUAL", endingStockUnits: 100},
    proposed: {priceMinor: 20500, units: 389, revenueMinor: 7974500, grossMarginMinor: null, grossMarginReasonCode: "COST_NOT_CLIENT_ACTUAL", endingStockUnits: 111},
    aiOptimal: {priceMinor: 20500, units: 389, revenueMinor: 7974500, grossMarginMinor: null, grossMarginReasonCode: "COST_NOT_CLIENT_ACTUAL", endingStockUnits: 111}
  },
  metricOrder: ["Units", "Revenue", "Gross Margin", "Ending Stock"],
  recommendation: {priceMinor: 20500, revenueImpactMinor: -25500, marginImpactMinor: 106500, marginReasonCode: null, stockOutRisk: "Low", confidence: 0.96},
  competitorEvidence: {included: true, reasonCode: null},
  mutated: false
};

const competitorMatch = {
  matchId: "match-1",
  skuId: recommendation.skuId,
  ourProduct: recommendation.productName,
  competitorName: "Licensed Market Feed",
  matchedProduct: "Synthetic comparable 5W-30",
  ourPriceMinor: 20000,
  competitorPriceMinor: 19800,
  priceGapPct: -1,
  currencyCode: "INR",
  availability: "In Stock",
  lastUpdated: "2026-08-01T00:00:00Z",
  confidence: 0.94,
  status: "Matched",
  freshness: "Fresh",
  firstExclusionReason: null,
  recommendedResponse: "Validate targeted reduction",
  details: {
    competitor_brand: "Synthetic demo",
    evidence_class: "synthetic",
    synthetic_label: "Synthetic demo"
  }
};

function response(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    blob: async () => new Blob([JSON.stringify(payload)]),
    headers: new Headers()
  };
}

function installFetchMock(
  exportHandler?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
  promotionsPayload?: (surface: string) => unknown
) {
  const mock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/api/v1/pricing/export")) {
      if (!exportHandler) throw new Error("Unexpected pricing export request.");
      return exportHandler(input, init);
    }
    if (path.includes("/api/v1/pricing/simulations:run")) return response(simulationResult);
    if (path.includes("/api/v1/pricing/recommendations/") &&
      !path.includes("summary") && !path.includes("store-view") &&
      !path.includes("category-view") && !path.includes("governance")) {
      return response({
        schemaVersion: "retail-pricing-page/v1",
        dataMode: "live",
        authority,
        item: recommendation
      });
    }
    if (path.includes("/api/v1/pricing/recommendations/summary")) {
      return response(recommendationSummary);
    }
    if (path.includes("/api/v1/pricing/recommendations/store-view")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, dimension: "store", items: [{store: recommendation.storeId, recommendations: 2, revenueOpportunityMinor: 92000, marginOpportunityMinor: null, risk: 1, priorityAction: "Review targeted reductions"}]});
    }
    if (path.includes("/api/v1/pricing/recommendations/category-view")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, dimension: "category", items: [{category: recommendation.category, recommendations: 2, revenueOpportunityMinor: 92000, marginOpportunityMinor: null, risk: 1, priorityAction: "Protect high-demand prices"}]});
    }
    if (path.includes("/api/v1/pricing/recommendations/governance")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, approvalSLA: {available: false, reason: "Approval workflow evidence is not available."}, controls: []});
    }
    if (path.includes("/api/v1/pricing/recommendations")) return response(recommendationPage);
    if (path.includes("/api/v1/competitors/summary")) {
      return response({
        schemaVersion: "retail-pricing-page/v1",
        dataMode: "live",
        authority,
        kpis: {
          productsMonitored: 1,
          aboveMarket: 1,
          belowMarket: 0,
          competitorOutOfStock: 0,
          matchesNeedingReview: 0
        },
        quality: {
          autoAccepted: 1,
          manualReview: 0,
          rejected: 0,
          averageConfidencePct: 94
        }
      });
    }
    if (path.includes("/api/v1/competitors/matches/match-1")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, item: competitorMatch});
    }
    if (path.includes("/api/v1/competitors/matches")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, items: [competitorMatch], pagination: {offset: 0, limit: 200, total: 1}});
    }
    if (path.includes("/api/v1/competitors/alert-rules")) {
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, available: false, reasonCode: "ALERT_WORKFLOW_UNAVAILABLE", message: "Persisted competitor alert rules are not available.", items: []});
    }
    if (path.includes("/api/v1/promotions/")) {
      const surface = path.split("/api/v1/promotions/")[1].split("?")[0];
      if (promotionsPayload) return response(promotionsPayload(surface));
      return response({schemaVersion: "retail-pricing-page/v1", dataMode: "live", authority, surface, plannerAvailable: false, reasonCode: "NO_ORIGIN_VISIBLE_PROMOTION_PLAN", message: "Origin-visible promotion planning evidence is not available.", disposition: {}, items: []});
    }
    throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderPricing(pageId: PricingPageId, channelType = "") {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <PricingPage
        pageId={pageId}
        dashboard={{
          schemaVersion: "retail-data-management-dashboard/v1",
          dataMode: "live",
          kpis: {dataFreshnessPct: 100, qualityScorePct: 100, connectedSources: 3, rejectedRecords: 0, lastRefreshAt: "2026-08-01T00:00:00Z"},
          sources: [],
          footer: {totalSkus: 1, activeSkus: 1, stores: 1, channels: 1, forecastCoveragePct: null, modelAccuracyPct: null},
          filters: {
            dateRange: {start: "2016-08-01", end: "2026-08-01"},
            markets: [{marketId: "gulf-india", name: "India — National"}],
            stores: [{storeId: recommendation.storeId, marketId: "gulf-india", name: "Mumbai Distributor", currencyCode: "INR", timezone: "Asia/Kolkata", region: "MH", format: "store", city: "Mumbai", active: true}],
            channelTypes: [{type: "online", name: "E-commerce", marketIds: ["gulf-india"]}],
            channels: [{channelId: recommendation.channelId, marketId: "gulf-india", name: "Gulf Direct Online", type: "online"}],
            categories: [{categoryId: "gulf-mco", name: "Motorcycle Oils"}],
            currencies: ["INR"]
          }
        }}
        storeId=""
        onStoreId={() => undefined}
        channelType={channelType}
        onNavigate={() => undefined}
      />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("pricing UI parity", () => {
  it("formats local amounts using the reference compact currency notation", () => {
    expect(formatMoneyMinor(12_480_000_000, "INR")).toBe("₹12.48 Cr");
    expect(formatMoneyMinor(380_000_000, "INR")).toBe("₹38L");
    expect(formatMoneyMinor(20_500, "INR")).toBe("₹205");
    expect(formatMoneyMinor(9_210_000, "USD")).toBe("$92.1K");
    expect(formatAggregateMoneyMinor(8_620_914, "INR")).toBe("₹0.86L");
    expect(categoryNameFromLabel("Gulf - Hydraulic")).toBe("Hydraulic Oils");
  });
  it("forwards only the closed local demo-state vocabulary from the page URL", async () => {
    window.history.replaceState({}, "", "/?demoState=panel&demoPanel=%2Fapi%2Fv1%2Fcompetitors%2Fsummary");
    const fetchMock = installFetchMock();
    renderPricing("priceRecommendations");

    await screen.findByText("SKU-Level Price Recommendations");
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((url) => url.includes("demoState=panel"))).toBe(true);
    expect(urls.every((url) => url.includes("demoPanel=%2Fapi%2Fv1%2Fcompetitors%2Fsummary"))).toBe(true);

    window.history.replaceState({}, "", "/?demoState=arbitrary");
    cleanup();
    const secondFetch = installFetchMock();
    renderPricing("priceRecommendations");
    await screen.findByText("SKU-Level Price Recommendations");
    expect(secondFetch.mock.calls.every(([input]) => !String(input).includes("demoState"))).toBe(true);
  });

  it("sends the shared channel type without collapsing channel identities", async () => {
    const fetchMock = installFetchMock();
    renderPricing("priceRecommendations", "online");

    await screen.findByText("SKU-Level Price Recommendations");
    const pricingRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((path) => path.includes("/api/v1/pricing/recommendations"));
    expect(pricingRequests.length).toBeGreaterThan(0);
    expect(pricingRequests.every((path) => path.includes("channelType=online"))).toBe(true);
    expect(pricingRequests.every((path) => !path.includes("channelId=online"))).toBe(true);
  });

  it("renders recommendation possibilities, exact columns, and read-only workflow previews", async () => {
    installFetchMock();
    renderPricing("priceRecommendations");

    await screen.findByText("SKU-Level Price Recommendations");
    expect(document.querySelectorAll(".pricing-kpi-grid .pricing-kpi")).toHaveLength(5);
    expect(screen.getByRole("combobox", {name: "Recommendation status"})).toBeDisabled();
    const table = document.querySelector(".recommendation-table") as HTMLTableElement;
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "", "Priority", "SKU / Product", "Category", "Store", "Action",
      "Current", "AI Price", "Change", "Competitor", "Stock Cover",
      "Forecast Demand", "Current Margin", "Expected Margin", "Revenue Impact",
      "Margin Impact", "AI Reason", "Confidence", "Status", "Owner"
    ]);
    expect(within(table).getAllByText("Inelastic demand supports a higher price")).toHaveLength(2);
    expect(within(table).queryByText('["Inelastic demand supports a higher price"]')).not.toBeInTheDocument();

    fireEvent.click(within(table).getByRole("checkbox", {name: /Gulf Formula/}));
    fireEvent.click(within(table).getByRole("checkbox", {name: /Gulf Pride/}));
    fireEvent.click(screen.getByRole("button", {name: "Compare Selected"}));
    const compare = await screen.findByRole("dialog", {name: "Compare Selected Recommendations"});
    expect(within(compare).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Product", "Action", "Price Change", "Revenue Impact", "Margin Impact", "Confidence"
    ]);
    fireEvent.click(within(compare).getByRole("button", {name: /Close Compare/}));

    fireEvent.click(screen.getByRole("button", {name: /Approve Selected/}));
    const approve = await screen.findByRole("dialog", {name: "Approve Price Recommendations"});
    expect(within(approve).getByRole("heading", {name: "Approve Price Recommendations"})).toHaveFocus();
    fireEvent.keyDown(document, {key: "Tab"});
    expect(within(approve).getByRole("button", {name: /Close Approve/})).toHaveFocus();
    expect(within(approve).getByRole("button", {name: "Confirm Approval"})).toBeDisabled();
    expect(Array.from(approve.querySelectorAll(".modal-foot button")).map((button) => button.textContent)).toEqual(["Confirm Approval", "Cancel"]);
    expect(within(approve).getByText("Products selected")).toBeInTheDocument();
    expect(within(approve).getByText("Approval validation")).toBeInTheDocument();
    fireEvent.click(within(approve).getByRole("button", {name: /Close Approve/}));

    fireEvent.click(screen.getByRole("button", {name: /Send for Review/}));
    const review = await screen.findByRole("dialog", {name: "Send Recommendations for Review"});
    expect(Array.from((within(review).getByRole("combobox", {name: "Priority"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["High", "Medium", "Low"]);
    expect(Array.from((within(review).getByRole("combobox", {name: "Review Reason"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual([
      "Price movement exceeds approval limit", "Margin impact requires review",
      "Competitor data validation", "Strategic product review"
    ]);
    expect(within(review).getByRole("button", {name: "Send for Review"})).toBeDisabled();
    fireEvent.click(within(review).getByRole("button", {name: /Close Send/}));

    fireEvent.click(screen.getByRole("button", {name: /Schedule Price Change/}));
    const schedule = await screen.findByRole("dialog", {name: "Schedule Price Changes"});
    expect(Array.from((within(schedule).getByRole("combobox", {name: "Channels"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["All Channels", "Stores Only", "E-commerce Only"]);
    expect(Array.from((within(schedule).getByRole("combobox", {name: "Rollback Rule"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["Rollback on integration failure", "Manual rollback only"]);
    fireEvent.click(within(schedule).getByRole("button", {name: /Close Schedule/}));

    fireEvent.click(screen.getByRole("button", {name: /Pricing Action Center/}));
    const actionCenter = await screen.findByRole("dialog", {name: "Pricing Action Center"});
    expect(within(actionCenter).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Decision Queue", "Items", "Owner", "Value"]);
    expect(within(actionCenter).getAllByRole("row").slice(1).map((row) => row.firstElementChild?.textContent)).toEqual(["Senior approval required", "Category review", "Approved but unscheduled"]);
    fireEvent.click(within(actionCenter).getByRole("button", {name: /Close Pricing Action Center/}));

    fireEvent.click(screen.getByRole("button", {name: "Export"}));
    const exportDialog = await screen.findByRole("dialog", {name: "Export Price Recommendations"});
    const format = within(exportDialog).getByRole("combobox", {name: "Format"}) as HTMLSelectElement;
    expect(Array.from(format.options).map((option) => option.text)).toEqual(["CSV", "Excel-compatible CSV", "PDF / Print"]);
    const filename = within(exportDialog).getByRole("textbox", {name: "File Name"});
    fireEvent.change(filename, {target: {value: "CON"}});
    expect(within(exportDialog).getByRole("button", {name: "Export"})).toBeDisabled();
    expect(Array.from(exportDialog.querySelectorAll(".modal-foot button")).map((button) => button.textContent)).toEqual(["Export", "Cancel"]);
    fireEvent.click(within(exportDialog).getByRole("button", {name: /Close Export/}));

    fireEvent.click(screen.getByRole("button", {name: /Gulf Formula GX 5W-30/}));
    const detail = await screen.findByRole("dialog", {name: "Price Recommendation Detail"});
    await within(detail).findByText("AI explanation");
    expect(within(detail).queryByText("Lineage & Capability")).not.toBeInTheDocument();
    expect(within(detail).queryByText("Evidence disposition")).not.toBeInTheDocument();
    expect(within(detail).queryByText("Store / Channel")).not.toBeInTheDocument();
    expect(within(detail).getByText("AI explanation")).toBeInTheDocument();
    expect(Array.from(detail.querySelectorAll(".modal-foot button")).map((button) => button.textContent)).toEqual(["Open Simulation", "Cancel"]);
    fireEvent.click(within(detail).getByRole("button", {name: /Close Price Recommendation Detail/}));

    fireEvent.click(screen.getByRole("tab", {name: "Category View"}));
    expect(await screen.findByText("Category Pricing Effectiveness")).toBeInTheDocument();
    expect(screen.getByText("Category Opportunity Matrix")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", {name: "Store View"}));
    const drilldownTrigger = await screen.findByRole("button", {name: "Open Store Drilldown"});
    await waitFor(() => expect(drilldownTrigger).toBeEnabled());
    fireEvent.click(drilldownTrigger);
    const drilldown = await screen.findByRole("dialog", {name: "Store Pricing Drilldown"});
    expect(within(drilldown).getByRole("combobox", {name: "Store"})).toHaveValue(recommendation.storeId);
    expect(within(drilldown).getByText("Top Pricing Issues")).toBeInTheDocument();
    expect(within(drilldown).getByText("Recommended Actions")).toBeInTheDocument();
    expect(Array.from(drilldown.querySelectorAll(".modal-foot button")).map((button) => button.textContent)).toEqual(["Open Store Recommendations", "Cancel"]);
  });

  it("runs the bounded price scenario and keeps the result modal to its exact four metrics", async () => {
    installFetchMock();
    renderPricing("priceSimulation");

    await screen.findByText("Price Scenario Builder");
    await waitFor(() => expect(document.querySelectorAll(".scenario-builder .pricing-field")).toHaveLength(8));
    const run = screen.getByRole("button", {name: "Run Simulation"});
    await waitFor(() => expect(run).toBeEnabled());
    const proposed = screen.getByRole("textbox", {name: "Proposed Price"});
    fireEvent.change(proposed, {target: {value: "205.001"}});
    expect(run).toBeDisabled();
    fireEvent.change(proposed, {target: {value: "204.99"}});
    expect(run).toBeDisabled();
    fireEvent.change(proposed, {target: {value: "205.00"}});
    expect(run).toBeEnabled();
    fireEvent.click(run);
    const dialog = await screen.findByRole("dialog", {name: "Simulation Result"});
    expect(Array.from(dialog.querySelectorAll(".pricing-kpi > small")).map((node) => node.textContent)).toEqual([
      "Revenue", "Margin", "Stock Risk", "Confidence"
    ]);
    expect(within(dialog).queryByRole("table")).not.toBeInTheDocument();
    expect(within(dialog).getByText("AI Recommendation")).toBeInTheDocument();
  });

  it("cancels an in-flight recommendation export when its dialog closes", async () => {
    let exportSignal: AbortSignal | null | undefined;
    installFetchMock(async (_input, init) => {
      exportSignal = init?.signal;
      return new Promise<Response>((_resolve, reject) => {
        exportSignal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        }, {once: true});
      });
    });
    renderPricing("priceRecommendations");

    await screen.findByText("SKU-Level Price Recommendations");
    fireEvent.click(screen.getByRole("button", {name: "Export"}));
    const dialog = await screen.findByRole("dialog", {name: "Export Price Recommendations"});
    fireEvent.click(within(dialog).getByRole("button", {name: "Export"}));
    await waitFor(() => expect(within(dialog).getByRole("button", {name: "Exporting…"})).toBeDisabled());
    fireEvent.click(within(dialog).getByRole("button", {name: "Cancel"}));

    expect(exportSignal?.aborted).toBe(true);
    expect(screen.queryByRole("dialog", {name: "Export Price Recommendations"})).not.toBeInTheDocument();
  });

  it("renders the exact competitor KPI/table vocabulary and a non-mutating review workspace", async () => {
    installFetchMock();
    renderPricing("competitorMonitor");

    await screen.findByText("Competitor Product Matches");
    expect(Array.from(document.querySelectorAll(".pricing-kpi-grid .pricing-kpi small")).map((node) => node.textContent)).toEqual([
      "Products Monitored", "Above Market", "Below Market",
      "Competitor Out of Stock", "Matches Needing Review"
    ]);
    expect(screen.getByText("Competitor intelligence")).toBeInTheDocument();
    expect(screen.getByText("Matching guardrail")).toBeInTheDocument();
    expect(screen.getByText("Synthetic demo")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: /Add Competitor/}));
    const add = await screen.findByRole("dialog", {name: "Add Competitor"});
    expect(add.querySelectorAll(".pricing-field")).toHaveLength(9);
    expect(Array.from((within(add).getByRole("combobox", {name: "Data Collection Method"}) as HTMLSelectElement).options).map((option) => [option.text, option.disabled])).toEqual([
      ["API Feed", false], ["Approved Web Collection", true],
      ["CSV / SFTP Feed", false], ["Manual Upload", false]
    ]);
    fireEvent.click(within(add).getByRole("button", {name: /Close Add Competitor/}));

    fireEvent.click(screen.getByRole("button", {name: /Create Alert Rule/}));
    const rule = await screen.findByRole("dialog", {name: "Create Competitor Alert Rule"});
    expect(rule.querySelectorAll(".pricing-field")).toHaveLength(11);
    expect(within(rule).queryByText("Connection validation")).not.toBeInTheDocument();
    expect(Array.from((within(rule).getByRole("combobox", {name: "Trigger Type"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual([
      "Competitor price changes", "Price gap exceeds threshold",
      "Competitor promotion detected", "Competitor becomes out of stock",
      "Competitor returns to stock", "New competitor product detected"
    ]);
    expect(within(rule).getByRole("combobox", {name: "Notify"})).toBeDisabled();
    fireEvent.click(within(rule).getByRole("button", {name: /Close Create Competitor/}));

    const table = document.querySelector(".competitor-table") as HTMLTableElement;
    expect(within(table).getAllByRole("columnheader")).toHaveLength(12);
    fireEvent.click(within(table).getByRole("checkbox", {name: /Select match/}));
    fireEvent.click(screen.getByRole("button", {name: "Review Matches"}));
    const dialog = await screen.findByRole("dialog", {name: "Review Competitor Product Match"});
    expect(within(dialog).getByText(/Review item 1 of 1/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", {name: /Previous|Next/})).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", {name: "Accept Match"})).toBeDisabled();
    expect(within(dialog).getByRole("button", {name: "Reject Match"})).toBeDisabled();
    const reviewFooter = dialog.querySelector(".modal-foot") as HTMLElement;
    expect(within(reviewFooter).getAllByRole("button").map((button) => button.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      "Reject Match", "Link Different Product", "Accept Match", "Cancel"
    ]);
    fireEvent.click(within(dialog).getByRole("button", {name: /Link Different Product/}));
    expect(await screen.findByRole("dialog", {name: "Review Competitor Product Match"})).toBe(dialog);
    await waitFor(() => expect(within(dialog).getByRole("heading", {name: "Review Competitor Product Match"})).toHaveFocus());
    expect(within(dialog).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Select", "Candidate Product", "Price", "Confidence"]);
    expect(within(dialog).getByRole("button", {name: "Save New Match"})).toBeDisabled();
  });

  it("keeps the full promotion composition visible while numeric planning remains unavailable", async () => {
    const fetchMock = installFetchMock();
    renderPricing("promotionPlanner");

    await screen.findByText("Promotion Performance Forecast");
    expect(document.querySelectorAll(".pricing-kpi-grid .pricing-kpi")).toHaveLength(5);
    expect(screen.getByText("AI promotion planning")).toBeInTheDocument();
    const portfolio = document.querySelector(".promotion-table") as HTMLTableElement;
    expect(within(portfolio).getAllByRole("columnheader")).toHaveLength(13);

    fireEvent.click(screen.getByRole("button", {name: /Create Promotion/}));
    const create = await screen.findByRole("dialog", {name: "Create Promotion"});
    expect(create.querySelectorAll(".pricing-field")).toHaveLength(13);
    expect(Array.from((within(create).getByRole("combobox", {name: "Promotion Objective"}) as HTMLSelectElement).options).map((option) => [option.text, option.disabled])).toEqual([
      ["Revenue Growth", false], ["Inventory Clearance", false],
      ["Customer Acquisition", true], ["Basket Size Growth", true],
      ["Loyalty Engagement", true]
    ]);
    expect(Array.from((within(create).getByRole("combobox", {name: "Promotion Type"}) as HTMLSelectElement).options).map((option) => [option.text, option.disabled])).toEqual([
      ["Percentage Discount", false], ["Fixed Price", false],
      ["Bundle Offer", true], ["Buy One Get One", true],
      ["Loyalty Member Price", true], ["Clearance", false]
    ]);
    expect(within(create).getByRole("combobox", {name: "Customer Segment"})).toBeDisabled();
    expect(within(create).getByRole("combobox", {name: "Approval Route"})).toBeDisabled();
    expect(Array.from(create.querySelectorAll(".modal-foot button")).map((button) => button.textContent)).toEqual(["Create Draft", "Cancel"]);
    fireEvent.click(within(create).getByRole("button", {name: /Close Create Promotion/}));

    fireEvent.click(screen.getByRole("button", {name: "Promotion Calendar"}));
    const calendar = await screen.findByRole("dialog", {name: "Promotion Calendar"});
    expect(within(calendar).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
    ]);
    expect(within(calendar).getAllByRole("gridcell")).toHaveLength(35);
    expect(within(calendar).getAllByRole("gridcell").map((cell) => cell.textContent)).toEqual([
      "", "", ...Array.from({length: 31}, (_, index) => String(index + 1)), "", ""
    ]);
    expect(within(calendar).getByRole("button", {name: "List View"})).toBeDisabled();
    expect(Array.from((within(calendar).getByRole("combobox", {name: "Calendar month"}) as HTMLSelectElement).options).map((option) => option.text)).toEqual(["July 2026", "August 2026"]);
    expect(within(calendar).getByText("Calendar controls")).toBeInTheDocument();
    fireEvent.click(within(calendar).getByRole("button", {name: /Close Promotion Calendar/}));

    fireEvent.click(screen.getByRole("button", {name: /Simulate Promotion/}));
    const simulation = await screen.findByRole("dialog", {name: "Simulate Promotion"});
    expect(simulation.querySelectorAll(".pricing-field")).toHaveLength(8);
    expect(within(simulation).getByRole("button", {name: "Run Simulation"})).toBeDisabled();
    fireEvent.click(within(simulation).getByRole("button", {name: /Preview Results/}));
    const results = await screen.findByRole("dialog", {name: "Promotion Simulation Results"});
    expect(within(results).getAllByText("Not available").length).toBeGreaterThanOrEqual(6);
    expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).includes("promotions/simulations:run") && init?.method === "POST"
    )).toBe(false);
  });

  it("renders the accepted promotions in the portfolio when the planner is available", async () => {
    const acceptedPromotions = [
      {
        promoId: "gulf-diwali-trade-2016",
        promoName: "Diwali distributor trade scheme 2016",
        promoType: "campaign",
        expectedDemandUplift: 3.6608552346257266,
        upliftLow: 2.1898560413065637,
        upliftHigh: 5.898107481151053,
        revenueUpliftMinor: 5735451880,
        marginImpactMinor: 1874982330,
        confidence: 1.0,
        cannibalisationRisk: "PRIVACY_RESTRICTED",
        currencyCode: "INR"
      },
      {
        promoId: "gulf-summer-ride-2019",
        promoName: "Summer ride bonus 2019",
        promoType: "campaign",
        expectedDemandUplift: 0.2372,
        upliftLow: 0.11,
        upliftHigh: 0.42,
        revenueUpliftMinor: 1382468246,
        marginImpactMinor: 406097935,
        confidence: 0.96,
        cannibalisationRisk: "PRIVACY_RESTRICTED",
        currencyCode: "INR"
      }
    ];
    installFetchMock(undefined, (surface) => ({
      schemaVersion: "retail-pricing-page/v1",
      dataMode: "live",
      authority,
      surface,
      plannerAvailable: true,
      reasonCode: "NO_ORIGIN_VISIBLE_PROMOTION_PLAN",
      message: "Accepted promotion uplift is available in the portfolio; write, calendar and aggregate tiles remain governed-unavailable.",
      disposition: {plannerAvailable: true, acceptedPromotionCount: acceptedPromotions.length, acceptedPromotions},
      items: acceptedPromotions
    }));
    renderPricing("promotionPlanner");

    await screen.findByText("Promotion Performance Forecast");
    const portfolio = document.querySelector(".promotion-table") as HTMLTableElement;
    // The 13 governed columns are unchanged on the positive branch.
    expect(within(portfolio).getAllByRole("columnheader")).toHaveLength(13);
    // The header count reflects the served promotions, not a hardcoded zero.
    expect(screen.getByText("2 promotions")).toBeInTheDocument();
    const body = portfolio.querySelector("tbody") as HTMLElement;
    // Both accepted promotions render by name.
    expect(within(body).getByText("Diwali distributor trade scheme 2016")).toBeInTheDocument();
    expect(within(body).getByText("Summer ride bonus 2019")).toBeInTheDocument();
    // Fractional demand uplift shows as a signed percentage.
    expect(within(body).getByText("+366.1%")).toBeInTheDocument();
    // Revenue uplift and margin impact format as compact INR (never a bare number).
    expect(within(body).getAllByText(/Cr$/).length).toBeGreaterThanOrEqual(2);
    // Cannibalisation risk is the privacy-restricted chip — one per row, never a number.
    expect(within(body).getAllByText("Privacy restricted")).toHaveLength(2);
    // No bare "Not available" leaks into the populated portfolio body.
    expect(within(body).queryByText("Not available")).toBeNull();
  });
});
