/**
 * The fourteen inventory/replenishment destinations (P4-9).
 *
 * One component serves all fourteen because their governed behavior is
 * identical and frozen by `contracts/screens/inventory-replenishment.parity.yaml`:
 * bind every rendered value to the live endpoint, render the approved
 * unavailable state on 503 and the governed stale state on 409, and never
 * substitute a sample value. What differs per destination -- title, endpoint,
 * action labels -- comes from the same table the parity contract was generated
 * from, so a screen cannot drift from its contract without failing the tests
 * that compare the two.
 *
 * Until an accepted bundle activates, every endpoint returns the governed 503
 * and every destination renders the unavailable state. That is the honest
 * screen: the alternative -- a sample table -- is exactly what the plan's
 * no-go list forbids.
 */

import {useQuery} from "@tanstack/react-query";
import {loadInventorySlice, type InventorySlice} from "./api";

export type InventoryPageId =
  | "inventoryOverview"
  | "storeInventory"
  | "warehouseInventory"
  | "inventoryAgeing"
  | "inventoryTransfers"
  | "inventoryValuation"
  | "expiryWaste"
  | "replenishmentPlanner"
  | "suggestedOrders"
  | "supplierPlanning"
  | "safetyStock"
  | "allocationFulfillment"
  | "replenishmentExceptions"
  | "stockHealth";

interface ScreenDefinition {
  title: string;
  subtitle: string;
  endpoint: string;
  /** Visible and natively disabled; no mutation handler exists (P4-D9/D11). */
  actions: string[];
}

export const inventoryScreens: Record<InventoryPageId, ScreenDefinition> = {
  inventoryOverview: {
    title: "Inventory Overview",
    subtitle: "Enterprise inventory position, risk, working capital and actions",
    endpoint: "/api/v1/inventory/overview",
    actions: [
      "Inventory Action Center", "Store Drilldown", "Warehouse Drilldown",
      "Run Inventory Scenario", "Export Inventory Report"
    ]
  },
  storeInventory: {
    title: "Store Inventory",
    subtitle: "Store-level availability, overstock, understock and transfer opportunities",
    endpoint: "/api/v1/inventory/stores",
    actions: ["Create Store Action", "Create Transfer", "Export"]
  },
  warehouseInventory: {
    title: "Warehouse Inventory",
    subtitle: "DC position, utilization, receipts and fill",
    endpoint: "/api/v1/inventory/warehouses",
    actions: ["Warehouse Export"]
  },
  inventoryAgeing: {
    title: "Inventory Ageing",
    subtitle: "Age buckets and the deterministic action ladder",
    endpoint: "/api/v1/inventory/ageing",
    actions: ["Ageing Export"]
  },
  inventoryTransfers: {
    title: "Stock Transfers",
    subtitle: "Transfer recommendations over typed lanes",
    endpoint: "/api/v1/inventory/transfers",
    actions: ["Create Transfer", "Transfer Export"]
  },
  inventoryValuation: {
    title: "Inventory Valuation",
    subtitle: "Gross valuation and DC ERP-vs-WMS variance",
    endpoint: "/api/v1/inventory/valuation",
    actions: ["Valuation Export"]
  },
  expiryWaste: {
    title: "Expiry & Waste",
    subtitle: "Expiry-window exposure and waste actuals",
    endpoint: "/api/v1/inventory/expiry-waste",
    actions: ["Expiry Export"]
  },
  replenishmentPlanner: {
    title: "Replenishment Planner",
    subtitle: "Suggested orders under lane, term, capacity and budget guards",
    endpoint: "/api/v1/replenishment/planner",
    actions: ["Approve Orders", "Adjust Parameters", "Planner Export"]
  },
  suggestedOrders: {
    title: "Suggested Orders",
    subtitle: "Read-only candidate orders; ERP transmission is shadow-only",
    endpoint: "/api/v1/replenishment/orders",
    actions: ["Send to ERP", "Orders Export"]
  },
  supplierPlanning: {
    title: "Supplier Planning",
    subtitle: "Supplier performance, origin-safe terms and risk",
    endpoint: "/api/v1/replenishment/suppliers",
    actions: ["Supplier Export"]
  },
  safetyStock: {
    title: "Safety Stock",
    subtitle: "Policy segments from the hard-gated interval",
    endpoint: "/api/v1/replenishment/safety-stock",
    actions: ["Safety Stock Export"]
  },
  allocationFulfillment: {
    title: "Allocation & Fulfillment",
    subtitle: "Constrained channel allocation over one node ATP pool",
    endpoint: "/api/v1/replenishment/allocations",
    actions: ["Allocation Export"]
  },
  replenishmentExceptions: {
    title: "Replenishment Exceptions",
    subtitle: "Deterministic engine-derived exceptions",
    endpoint: "/api/v1/replenishment/exceptions",
    actions: ["Assign", "Resolve", "Exceptions Export"]
  },
  stockHealth: {
    title: "Stock Health",
    subtitle: "SKU × store triage across active and residual stock",
    endpoint: "/api/v1/inventory/stock-health",
    actions: ["Stock Health Export"]
  }
};

function headingFor(key: string): string {
  const spaced = key.replace(/([A-Z])/g, " $1");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function LiveTable({slice}: {slice: InventorySlice}) {
  if (slice.items.length === 0) {
    return (
      <div className="state-card">
        <strong>No rows in the active bundle for this selection.</strong>
        <small>Zero rows is a governed result, not a failure.</small>
      </div>
    );
  }
  const columns = Object.keys(slice.items[0]);
  return (
    <div className="card" style={{overflowX: "auto"}}>
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{headingFor(column)}</th>)}</tr>
        </thead>
        <tbody>
          {slice.items.map((item: Record<string, unknown>, index: number) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column}>{renderValue(item[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InventoryPage({pageId}: {pageId: InventoryPageId}) {
  const screen = inventoryScreens[pageId];
  const slice = useQuery({
    queryKey: ["inventory-slice", screen.endpoint],
    queryFn: () => loadInventorySlice(screen.endpoint),
    retry: false
  });

  return (
    <>
      <div className="toolbar" aria-label={`${screen.title} actions`}>
        {screen.actions.map((label) => (
          // P4-D9/P4-D11: visible, natively disabled, no mutation handler.
          <button key={label} className="btn" type="button" disabled aria-disabled="true"
            title="Read-only in this release; workflow actions belong to a later phase">
            {label}
          </button>
        ))}
      </div>
      {slice.isPending ? (
        <div className="state-card">Loading live inventory data…</div>
      ) : slice.error ? (
        <div className="state-card error-state">
          <strong>
            {String(slice.error).includes("409")
              ? "The active inventory version is stale."
              : "Live inventory data is unavailable."}
          </strong>
          <span>
            No accepted inventory/replenishment bundle is active for this
            destination.
          </span>
          <small>No sample or fallback values are displayed.</small>
        </div>
      ) : slice.data ? (
        <LiveTable slice={slice.data} />
      ) : null}
    </>
  );
}
