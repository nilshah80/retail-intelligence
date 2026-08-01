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
import {
  REFERENCE_SCREENS,
  REFERENCE_SCREEN_BY_ID
} from "./generated/inventoryScreenLayout";

const PAGE_IDS = Object.keys(inventoryScreens) as InventoryPageId[];

/**
 * The row table specifically. A screen now renders the reference's card kinds --
 * a `rows` table alongside a headerless `breakdown` aggregation -- so asking for
 * "the table" is ambiguous, and the ambiguity is the correct structure rather
 * than a fault.
 */
async function findRowsTable(): Promise<HTMLElement> {
  const tables = await screen.findAllByRole("table");
  const rows = tables.find(
    (table) => table.getAttribute("data-card-kind") === "rows"
  );
  if (!rows) throw new Error("no rows-kind table rendered");
  return rows;
}

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
    expect(INVENTORY_SCREEN_CONTRACTS).toHaveLength(14);
    expect(INVENTORY_CONTRACT_SET_ID).toBe("inventoryReplenishment");

    for (const contract of INVENTORY_SCREEN_CONTRACTS) {
      const declared = inventoryScreens[contract.screenId as InventoryPageId];
      expect(declared, `no component screen for ${contract.screenId}`)
        .toBeDefined();
      expect(declared.title).toBe(contract.title);
      expect(declared.endpoint).toBe(contract.endpoint);
    }
    // And nothing extra: a destination the contract never approved must not
    // exist in the component either.
    expect(new Set(PAGE_IDS)).toEqual(
      new Set(INVENTORY_SCREEN_CONTRACTS.map((c) => c.screenId))
    );
  });

  it("takes every action label from the reference document", () => {
    // Actions are no longer declared in the component at all -- they come from
    // `inventoryScreenLayout`, generated from the reference HTML. That change was
    // forced by finding the labels I had hand-written were invented: the reference
    // gives Stock Health "Assign Owner" and "Create Action" while the component
    // claimed "Stock Health Export". Nothing retypes them now, so nothing can
    // drift.
    expect(REFERENCE_SCREENS).toHaveLength(14);
    expect(new Set(REFERENCE_SCREENS.map((s) => s.screenId))).toEqual(
      new Set(PAGE_IDS)
    );
    const stockHealth = REFERENCE_SCREEN_BY_ID.stockHealth;
    expect(stockHealth.actions).toEqual(["Assign Owner", "Create Action"]);
    for (const reference of REFERENCE_SCREENS) {
      expect(reference.actions.length).toBeGreaterThan(0);
    }
  });

  it("renders the action strip in the reference's order", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderPage("inventoryOverview");

    const strip = await screen.findByLabelText("inventoryOverview actions");
    const labels = [...strip.querySelectorAll("button")].map(
      (button) => button.textContent
    );
    expect(labels).toEqual([
      ...REFERENCE_SCREEN_BY_ID.inventoryOverview.actions
    ]);
  });

  it("renders every reference table column, in order, headers included", async () => {
    // A column the platform cannot fill still renders with its header and a
    // governed cell. Dropping it would silently change the approved layout, which
    // is the failure this whole rebuild was for.
    const payload = {...partialPayload, items: [partialPayload.items[0]]};
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => payload
    }));
    renderPage("safetyStock");

    const table = await findRowsTable();
    const headers = [...table.querySelectorAll("th")].map((th) => th.textContent);
    const referenceColumns =
      REFERENCE_SCREEN_BY_ID.safetyStock.cards.find((c) => c.kind === "rows")!
        .columns;
    expect(headers).toEqual([...referenceColumns]);
  });

  it("renders the reference's five KPI captions where it has them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => partialPayload
    }));
    renderPage("safetyStock");

    await findRowsTable();
    const captions = [...document.querySelectorAll(".kpi small")].map(
      (node) => node.textContent
    );
    expect(captions).toEqual([
      ...REFERENCE_SCREEN_BY_ID.safetyStock.kpiCaptions
    ]);
  });

  it("shows no KPI grid on a destination the reference gives none", async () => {
    // Stock Health is a toolbar and one table in the reference. Inventing five
    // tiles for it would be as wrong as omitting them where they exist.
    expect(REFERENCE_SCREEN_BY_ID.stockHealth.kpiCaptions).toHaveLength(0);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 503}));
    renderPage("stockHealth");
    await screen.findByText("Live inventory data is unavailable.");
    expect(document.querySelector(".kpi-grid")).not.toBeInTheDocument();
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

    const toolbar = screen.getByLabelText("suggestedOrders actions");
    const buttons = within(toolbar).getAllByRole("button");
    // The reference's labels, not the ones an earlier version invented.
    expect(buttons.map((button) => button.textContent)).toEqual([
      ...REFERENCE_SCREEN_BY_ID.suggestedOrders.actions
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

    const table = await findRowsTable();
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

    const table = await findRowsTable();
    // More than one, and that is the point: the reference's Stock Health table has
    // columns this platform cannot fill (Ageing, Financial Exposure) alongside the
    // genuinely absent cover. Every one renders the governed treatment, and the
    // column keeps its header rather than being dropped from the approved layout.
    const governed = within(table).getAllByText("Not available");
    expect(governed.length).toBeGreaterThanOrEqual(3);
    for (const cell of governed) {
      expect(cell).toHaveAttribute("data-unavailable", "true");
    }
    expect(within(table).getByText("DEAD_STOCK_DEASSORTED")).toBeInTheDocument();
    // Never a zero standing in for an absent value.
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

    const table = await findRowsTable();
    const withheld = within(table).getAllByText("Manual judgment required");
    // Two withheld rows x the three interval-derived columns the reference gives
    // Safety Stock: Service Target, Current Value and Recommended Value.
    expect(withheld).toHaveLength(6);
    // The forbidden renderings, all four of them.
    expect(within(table).queryByText("0")).not.toBeInTheDocument();
    expect(within(table).queryByText("0.0")).not.toBeInTheDocument();
    expect(within(table).queryByText("null")).not.toBeInTheDocument();
    expect(within(table).queryByText("undefined")).not.toBeInTheDocument();
  });

  it("keeps a fully assessed row fully rendered beside a withheld one", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await findRowsTable();
    // Service Target renders as a percentage because that is the reference's
    // column; the buffer appears in both Current and Recommended Value.
    expect(within(table).getByText("97.0%")).toBeInTheDocument();
    expect(within(table).getAllByText("19").length).toBeGreaterThan(0);
    // Three rows plus the header: a withheld row must not be collapsed away.
    expect(within(table).getAllByRole("row")).toHaveLength(4);
  });

  it("distinguishes the two governed reasons on the row itself", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await findRowsTable();
    const coldStart = table.querySelectorAll(
      '[data-reason-code="COLD_START_INTERVAL_UNCALIBRATED"]'
    );
    const unresolved = table.querySelectorAll(
      '[data-reason-code="SUPPLY_ROUTE_UNRESOLVED"]'
    );
    expect(coldStart).toHaveLength(3);
    expect(unresolved).toHaveLength(3);
    // The titles must not be interchangeable: one resolves as the product ages,
    // the other needs somebody to declare a route.
    expect(coldStart[0].getAttribute("title")).toContain("horizon 4");
    expect(unresolved[0].getAttribute("title")).toContain("service lane");
  });

  it("marks the partial rows without hiding them", async () => {
    stubPartial();
    renderPage("safetyStock");

    const table = await findRowsTable();
    expect(table.querySelectorAll('tr[data-partial="true"]')).toHaveLength(2);
  });

  it("discloses partial coverage through the reference's own KPI tile", async () => {
    // An earlier version added a bespoke notice card above the table. The
    // reference has no such element, so it is gone: deviating from the approved
    // layout in order to carry a disclosure is still deviating. Safety Stock's own
    // "Policy Coverage" tile is the reference-native place for it.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => partialPayload
    }));
    renderPage("safetyStock");

    await findRowsTable();
    expect(document.querySelector('[data-testid="partial-notice"]'))
      .not.toBeInTheDocument();
    const coverage = document.querySelector('[data-kpi="Policy Coverage"]');
    expect(coverage).toBeInTheDocument();
    expect(coverage).toHaveTextContent("Cells with an available interval");
  });

  it("leaves non-interval columns alone on a withheld row", async () => {
    // The withholding is scoped to interval-DERIVED values. A withheld row still
    // has a real market, location and SKU, and blanking them would destroy the
    // only thing that makes the row actionable by a human.
    stubPartial();
    renderPage("safetyStock");

    const table = await findRowsTable();
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
