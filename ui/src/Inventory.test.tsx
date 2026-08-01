// @vitest-environment jsdom

import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {cleanup, render, screen, within} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, describe, expect, it, vi} from "vitest";
import {InventoryPage, inventoryScreens, type InventoryPageId} from "./Inventory";
import {
  INVENTORY_CONTRACT_SET_ID,
  INVENTORY_SCREEN_CONTRACTS
} from "./generated/inventoryScreenContracts";

const PAGE_IDS = Object.keys(inventoryScreens) as InventoryPageId[];

function renderPage(pageId: InventoryPageId) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <InventoryPage pageId={pageId} />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("inventory & replenishment destinations", () => {
  it("declares exactly fourteen destinations with unique endpoints", () => {
    expect(PAGE_IDS).toHaveLength(14);
    const endpoints = PAGE_IDS.map((id) => inventoryScreens[id].endpoint);
    expect(new Set(endpoints).size).toBe(14);
    for (const endpoint of endpoints) {
      expect(endpoint).toMatch(/^\/api\/v1\/(inventory|replenishment)\//);
    }
  });

  // -- parity with the frozen contract ----------------------------------------

  it("matches the approved parity contract screen for screen", () => {
    // Two hand-maintained lists of the same fourteen rows -- the component's
    // table and the parity YAML -- with nothing checking they agree is how a
    // screen ends up with a button label nobody approved. The contract side is
    // generated, so this compares the real thing rather than a copy of it.
    expect(INVENTORY_SCREEN_CONTRACTS).toHaveLength(14);
    expect(INVENTORY_CONTRACT_SET_ID).toBe("inventoryReplenishment");

    for (const contract of INVENTORY_SCREEN_CONTRACTS) {
      const declared = inventoryScreens[contract.screenId as InventoryPageId];
      expect(declared, `no component screen for ${contract.screenId}`)
        .toBeDefined();
      expect(declared.title).toBe(contract.title);
      expect(declared.endpoint).toBe(contract.endpoint);
      // Order matters: the toolbar renders in declaration order and the
      // contract's order is the approved one.
      expect(declared.actions).toEqual([...contract.actions]);
    }
    // And nothing extra: a destination the contract never approved must not
    // exist in the component either.
    expect(new Set(PAGE_IDS)).toEqual(
      new Set(INVENTORY_SCREEN_CONTRACTS.map((c) => c.screenId))
    );
  });

  it("renders the toolbar in the contract's declared order", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderPage("inventoryOverview");

    const toolbar = await screen.findByLabelText("Inventory Overview actions");
    const labels = [...toolbar.querySelectorAll("button")].map(
      (button) => button.textContent
    );
    const contract = INVENTORY_SCREEN_CONTRACTS.find(
      (entry) => entry.screenId === "inventoryOverview"
    );
    expect(labels).toEqual([...contract!.actions]);
  });

  it("renders the governed unavailable state on 503, never a sample table", async () => {
    // No accepted bundle is active, which is the honest current state. A screen
    // that filled itself with plausible numbers here is what the plan's no-go
    // list forbids.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderPage("storeInventory");

    expect(
      await screen.findByText("Live inventory data is unavailable.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("No sample or fallback values are displayed.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // Sample values from the reference HTML must never appear.
    for (const sample of ["₹1.42 Cr", "₹2.1 Cr", "87.6%"]) {
      expect(screen.queryByText(sample)).not.toBeInTheDocument();
    }
  });

  it("distinguishes a stale activation from an absent one", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 409}));
    renderPage("replenishmentPlanner");
    expect(
      await screen.findByText("The active inventory version is stale.")
    ).toBeInTheDocument();
  });

  it("keeps every action control visible and natively disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderPage("suggestedOrders");

    const toolbar = screen.getByLabelText("Suggested Orders actions");
    const buttons = within(toolbar).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Send to ERP", "Orders Export"
    ]);
    for (const button of buttons) {
      // P4-D11: the control renders and cannot fire. `disabled` is the native
      // attribute, not a class that only looks inert.
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "true");
    }
  });

  it("renders live rows bound to the served envelope when a bundle is active", async () => {
    const payload = {
      schemaVersion: "retail-inventory-positions/v1",
      dataMode: "live",
      inventoryRunId: "ir_0123456789abcdef",
      inventoryVersionId: "iv_0123456789abcdef",
      semanticFingerprint: "a".repeat(64),
      forecastAuthority: {
        forecastRunId: "fr_357575f586905b11",
        forecastVersionId: "fv_3d66e3bd9939430d"
      },
      policyVersion: "inventory-policy/2.0.0",
      markets: ["india-west"],
      items: [
        {
          marketId: "india-west",
          locationId: "india-west:mumbai-bandra",
          skuId: "sku-1",
          onHandUnits: 42,
          atpUnits: 40,
          residualOnly: false
        }
      ],
      pagination: {offset: 0, limit: 100, total: 1}
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => payload
    }));
    renderPage("storeInventory");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("42")).toBeInTheDocument();
    expect(within(table).getByText("india-west:mumbai-bandra")).toBeInTheDocument();
    // A false boolean renders as "No", never as a blank that reads like absence.
    expect(within(table).getByText("No")).toBeInTheDocument();
  });

  it("renders a null cell as Not available rather than blank or zero", async () => {
    const payload = {
      schemaVersion: "retail-inventory-stock-health/v1",
      dataMode: "live",
      inventoryRunId: "ir_0123456789abcdef",
      inventoryVersionId: "iv_0123456789abcdef",
      semanticFingerprint: "a".repeat(64),
      forecastAuthority: {
        forecastRunId: "fr_357575f586905b11",
        forecastVersionId: "fv_3d66e3bd9939430d"
      },
      policyVersion: "inventory-policy/2.0.0",
      markets: ["india-west"],
      // Dead stock: no demand, so cover is genuinely unavailable and carries a
      // reason. Zero would invert the meaning.
      items: [{
        marketId: "india-west", locationId: "dc", skuId: "sku-9",
        healthClass: "dead", coverDays: null,
        reasonCode: "DEAD_STOCK_DEASSORTED"
      }],
      pagination: {offset: 0, limit: 100, total: 1}
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => payload
    }));
    renderPage("stockHealth");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Not available")).toBeInTheDocument();
    expect(within(table).getByText("DEAD_STOCK_DEASSORTED")).toBeInTheDocument();
    expect(within(table).queryByText("0")).not.toBeInTheDocument();
  });

  it("shows a governed zero-row state without calling it a failure", async () => {
    const payload = {
      schemaVersion: "retail-inventory-transfers/v1",
      dataMode: "live",
      inventoryRunId: "ir_0123456789abcdef",
      inventoryVersionId: "iv_0123456789abcdef",
      semanticFingerprint: "a".repeat(64),
      forecastAuthority: {
        forecastRunId: "fr_357575f586905b11",
        forecastVersionId: "fv_3d66e3bd9939430d"
      },
      policyVersion: "inventory-policy/2.0.0",
      markets: ["india-west"],
      items: [],
      pagination: {offset: 0, limit: 100, total: 0}
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => payload
    }));
    renderPage("inventoryTransfers");

    expect(
      await screen.findByText("Zero rows is a governed result, not a failure.")
    ).toBeInTheDocument();
  });

  // -- P4-9 task 12: the withheld interval ------------------------------------

  const partialPayload = {
    schemaVersion: "retail-replenishment-safety-stock/v1",
    dataMode: "live",
    inventoryRunId: "ir_0123456789abcdef",
    inventoryVersionId: "iv_0123456789abcdef",
    semanticFingerprint: "a".repeat(64),
    forecastAuthority: {
      forecastRunId: "fr_357575f586905b11",
      forecastVersionId: "fv_3d66e3bd9939430d"
    },
    policyVersion: "inventory-policy/2.0.0",
    markets: ["india-west"],
    items: [
      // Current-pin H2 row: fully assessed, and it must stay that way. If the
      // withholding below also suppressed this one, the screen would understate
      // its own coverage.
      {
        marketId: "india-west", locationId: "india-west:mumbai-bandra",
        skuId: "sku-fast", abcClass: "A", serviceLevel: 0.97,
        safetyStockUnits: 18.5, intervalAvailable: true, reasonCode: null
      },
      // Varied-term H5+ cold-start row: visibly partial.
      {
        marketId: "india-west", locationId: "india-west:pune-overflow",
        skuId: "sku-new", abcClass: "C", serviceLevel: null,
        safetyStockUnits: null, intervalAvailable: false,
        reasonCode: "COLD_START_INTERVAL_UNCALIBRATED"
      },
      // No declared route: withheld for a DIFFERENT reason.
      {
        marketId: "india-west", locationId: "india-west:orphan-store",
        skuId: "sku-any", abcClass: null, serviceLevel: null,
        safetyStockUnits: null, intervalAvailable: false,
        reasonCode: "SUPPLY_ROUTE_UNRESOLVED"
      }
    ],
    pagination: {offset: 0, limit: 100, total: 3}
  };

  function stubPartial() {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => partialPayload
    }));
  }

  it("renders a withheld interval as manual judgment, never zero", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await screen.findByRole("table");
    const withheld = within(table).getAllByText("Manual judgment required");
    // Two withheld rows x two interval-derived columns (serviceLevel,
    // safetyStockUnits).
    expect(withheld).toHaveLength(4);
    // The forbidden renderings, all four of them.
    expect(within(table).queryByText("0")).not.toBeInTheDocument();
    expect(within(table).queryByText("0.0")).not.toBeInTheDocument();
    expect(within(table).queryByText("null")).not.toBeInTheDocument();
    expect(within(table).queryByText("undefined")).not.toBeInTheDocument();
  });

  it("keeps a fully assessed row fully rendered beside a withheld one", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("18.5")).toBeInTheDocument();
    expect(within(table).getByText("0.97")).toBeInTheDocument();
    // Three rows plus the header: a withheld row must not be collapsed away.
    expect(within(table).getAllByRole("row")).toHaveLength(4);
  });

  it("distinguishes the two governed reasons on the row itself", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await screen.findByRole("table");
    const coldStart = table.querySelectorAll(
      '[data-reason-code="COLD_START_INTERVAL_UNCALIBRATED"]'
    );
    const unresolved = table.querySelectorAll(
      '[data-reason-code="SUPPLY_ROUTE_UNRESOLVED"]'
    );
    expect(coldStart).toHaveLength(2);
    expect(unresolved).toHaveLength(2);
    // The titles must not be interchangeable: one resolves as the product ages,
    // the other needs somebody to declare a route.
    expect(coldStart[0].getAttribute("title")).toContain("horizon 4");
    expect(unresolved[0].getAttribute("title")).toContain("service lane");
  });

  it("marks the partial rows without hiding them", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await screen.findByRole("table");
    expect(table.querySelectorAll('tr[data-partial="true"]')).toHaveLength(2);
  });

  it("states the partial count above the table", async () => {
    // A screen that is partly unassessed and does not say so reads as fully
    // assessed, and nobody scrolls every row to find out.
    stubPartial();
    renderPage("safetyStock");

    const notice = await screen.findByTestId("partial-notice");
    expect(notice).toHaveTextContent("2 of 3 rows need manual judgment.");
    expect(notice).toHaveTextContent("remaining 1 rows are fully");
  });

  it("shows no partial notice when every row is assessed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...partialPayload,
        items: [partialPayload.items[0]],
        pagination: {offset: 0, limit: 100, total: 1}
      })
    }));
    renderPage("safetyStock");

    await screen.findByRole("table");
    expect(screen.queryByTestId("partial-notice")).not.toBeInTheDocument();
  });

  it("leaves non-interval columns alone on a withheld row", async () => {
    // The withholding is scoped to interval-DERIVED values. A withheld row still
    // has a real market, location and SKU, and blanking them would destroy the
    // only thing that makes the row actionable by a human.
    stubPartial();
    renderPage("safetyStock");

    const table = await screen.findByRole("table");
    expect(
      within(table).getByText("india-west:pune-overflow")
    ).toBeInTheDocument();
    expect(within(table).getByText("sku-new")).toBeInTheDocument();
    expect(within(table).getByText("C")).toBeInTheDocument();
  });

  it("refuses a payload whose envelope cannot be traced to an authority", async () => {
    // A response without the consumed forecast identity is not servable data:
    // a rendered number nobody can trace to a version is exactly what the
    // schema exists to stop reaching a component.
    const untraceable = {
      schemaVersion: "retail-inventory-positions/v1",
      dataMode: "live",
      inventoryRunId: "ir_0123456789abcdef",
      inventoryVersionId: "iv_0123456789abcdef",
      semanticFingerprint: "a".repeat(64),
      policyVersion: "inventory-policy/2.0.0",
      markets: ["india-west"],
      items: []
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => untraceable
    }));
    renderPage("inventoryOverview");

    expect(
      await screen.findByText("Live inventory data is unavailable.")
    ).toBeInTheDocument();
  });
});
