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
import App from "./App";

const liveDashboard = {
  schemaVersion: "retail-data-management-dashboard/v1",
  dataMode: "live",
  kpis: {
    dataFreshnessPct: 100,
    qualityScorePct: 100,
    connectedSources: 3,
    rejectedRecords: 0,
    lastRefreshAt: "2026-07-30T00:00:00Z"
  },
  sources: [
    {
      sourceSystem: "businessCentral",
      name: "Business Central ERP",
      type: "ERP / Parquet",
      lastRefreshAt: "2026-07-30T00:00:00Z",
      records: 47_702_932,
      qualityPct: 100,
      status: "Healthy",
      action: "View mapping",
      datasetCount: 56,
      objectCount: 3_764
    },
    {
      sourceSystem: "companion",
      name: "External & Companion",
      type: "External / Parquet",
      lastRefreshAt: "2026-07-30T00:00:00Z",
      records: 5_589_147,
      qualityPct: 100,
      status: "Healthy",
      action: "View mapping",
      datasetCount: 32,
      objectCount: 2_313
    },
    {
      sourceSystem: "shopify",
      name: "Shopify Commerce",
      type: "Commerce / Parquet",
      lastRefreshAt: "2026-07-30T00:00:00Z",
      records: 173_637_309,
      qualityPct: 100,
      status: "Healthy",
      action: "View mapping",
      datasetCount: 44,
      objectCount: 2_318
    }
  ],
  footer: {
    totalSkus: 720,
    activeSkus: 348,
    stores: 4,
    channels: 2,
    forecastCoveragePct: null,
    modelAccuracyPct: null
  },
  filters: {
    dateRange: {start: "2016-07-28", end: "2026-07-28"},
    markets: [
      {marketId: "india-west", name: "India West"},
      {marketId: "us-new-york", name: "US New York"}
    ],
    stores: [
      {
        storeId: "india-west:mumbai-bandra",
        marketId: "india-west",
        name: "Mumbai Bandra",
        currencyCode: "INR",
        timezone: "Asia/Kolkata",
        region: "MH",
        format: "store",
        city: "Mumbai",
        active: true
      },
      {
        storeId: "india-west:pune-koregaon",
        marketId: "india-west",
        name: "Pune Koregaon Park",
        currencyCode: "INR",
        timezone: "Asia/Kolkata",
        region: "MH",
        format: "store",
        city: "Pune",
        active: true
      },
      {
        storeId: "us-new-york:ny-brooklyn",
        marketId: "us-new-york",
        name: "Brooklyn",
        currencyCode: "USD",
        timezone: "America/New_York",
        region: "NY",
        format: "store",
        city: "New York",
        active: true
      },
      {
        storeId: "us-new-york:ny-manhattan",
        marketId: "us-new-york",
        name: "Manhattan",
        currencyCode: "USD",
        timezone: "America/New_York",
        region: "NY",
        format: "store",
        city: "New York",
        active: true
      }
    ],
    channelTypes: [
      {
        type: "online",
        name: "E-commerce",
        marketIds: ["india-west", "us-new-york"]
      },
      {
        type: "store",
        name: "Store",
        marketIds: ["india-west", "us-new-york"]
      }
    ],
    currencies: ["INR", "USD"]
  }
};

const liveFx = {
  schemaVersion: "retail-fx-rates/v1",
  dataMode: "live",
  reportingCurrency: "INR",
  coverage: {
    start: "2016-07-28",
    end: "2026-07-28",
    observations: 7306
  },
  rates: [
    {
      baseCurrency: "INR",
      quoteCurrency: "INR",
      rate: "1.000000000000000000",
      rateDate: "2026-07-28"
    },
    {
      baseCurrency: "USD",
      quoteCurrency: "INR",
      rate: "83.000000000000000000",
      rateDate: "2026-07-28"
    }
  ]
};

function renderApp() {
  window.history.replaceState({}, "", "/?page=dataManagement");
  const client = new QueryClient({
    defaultOptions: {queries: {retry: false}}
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Data Management screen contract", () => {
  it("renders the original screen vocabulary with live governed values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(
      async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () => String(input).includes("/api/v1/fx/rates")
          ? liveFx
          : liveDashboard
      })
    ));
    renderApp();

    expect(await screen.findByRole("heading", {name: "Data Management"}))
      .toBeInTheDocument();
    expect(screen.getByText(
      "Monitor source systems, data freshness and data quality"
    )).toBeInTheDocument();

    const sourceTable = await screen.findByRole("table");
    const headers = within(sourceTable)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "Source",
      "Type",
      "Last Refresh",
      "Records",
      "Quality",
      "Status",
      "Action"
    ]);
    expect(within(sourceTable).getByText("Business Central ERP"))
      .toBeInTheDocument();
    expect(within(sourceTable).getByText("External & Companion"))
      .toBeInTheDocument();
    expect(within(sourceTable).getByText("Shopify Commerce"))
      .toBeInTheDocument();
    expect(
      within(sourceTable).getAllByRole("button", {name: "View mapping"})
    ).toHaveLength(3);

    expect(document.querySelector('[data-kpi="data-freshness"]')?.textContent)
      .toContain("100.0%");
    expect(document.querySelector('[data-kpi="quality-score"]')?.textContent)
      .toContain("100.0%");
    expect(document.querySelector('[data-kpi="connected-sources"]')?.textContent)
      .toContain("3");
    expect(document.querySelector('[data-kpi="rejected-records"]')?.textContent)
      .toContain("0");
    expect(document.querySelector('[data-footer-kpi="total-skus"]')?.textContent)
      .toContain("720");
    expect(document.querySelector('[data-footer-kpi="active-skus"]')?.textContent)
      .toContain("348");
    expect(document.querySelector('[data-footer-kpi="forecast-coverage"]')?.textContent)
      .toContain("Not available");
    expect(document.querySelector('[data-footer-kpi="model-accuracy"]')?.textContent)
      .toContain("Not available");

    expect(screen.queryByText("PHASE 2 · GOVERNED INGESTION")).not
      .toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Add Data Source"})).not
      .toBeInTheDocument();
    expect(screen.queryByText("User Management")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", {name: "Store"}), {
      target: {value: "india-west:pune-koregaon"}
    });
    fireEvent.change(screen.getByRole("combobox", {name: "Channel"}), {
      target: {value: "online"}
    });
    expect(screen.getByRole("combobox", {name: "Store"})).toHaveValue(
      "india-west:pune-koregaon"
    );
    expect(screen.getByRole("combobox", {name: "Channel"})).toHaveValue(
      "online"
    );

    fireEvent.click(screen.getByRole("button", {name: "FX"}));
    const modal = await screen.findByRole("dialog", {
      name: "Multi-Currency Configuration"
    });
    expect(within(modal).getByText("Accepted FX rates")).toBeInTheDocument();
    expect(within(modal).getByText("$1 = ₹83")).toBeInTheDocument();
    expect(within(modal).getByText(
      "7,306 accepted daily observations from 2016-07-28 through 2026-07-28."
    )).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", {name: "Close"}));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("never substitutes sample data when the API fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503
    }));
    renderApp();

    await waitFor(() => {
      expect(screen.getByText("Live data is unavailable.")).toBeInTheDocument();
    });
    expect(screen.queryByText("12,842")).not.toBeInTheDocument();
    expect(screen.queryByText("Retail POS")).not.toBeInTheDocument();
  });
});
