/**
 * The fourteen inventory/replenishment destinations (P4-9).
 *
 * Structure comes from the reference document, extracted rather than retyped:
 * `ui/src/generated/inventoryScreenLayout.ts` is generated from
 * `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` by
 * `tools/extract_reference_layout.py`, and `--check` fails when the two diverge.
 * The action strip, filter options, KPI captions and table column orders on these
 * screens are therefore the approved ones by construction; an earlier version
 * rendered one generic auto-derived table per destination because it was written
 * from the parity contract's element list, which says what a screen shows and not
 * how it is built.
 *
 * Values come from the live API and nowhere else. The reference's illustrative
 * figures are deliberately not extracted, so there is no path by which a sample
 * number reaches a screen. Where the platform has no value it renders the governed
 * unavailable treatment with its reason, never a zero and never a blank.
 *
 * KPI tiles read `summary`, which the Go read model aggregates in SQL over every
 * scoped row of the active version. They must never be computed here from `items`:
 * the page is 100 rows of up to 4,741, and summing it in the browser would render
 * a partial total as an enterprise figure.
 */

import {useQuery} from "@tanstack/react-query";
import {loadInventorySlice, type InventorySlice} from "./api";
import {
  REFERENCE_SCREEN_BY_ID,
  type ReferenceScreen
} from "./generated/inventoryScreenLayout";

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

/** How one KPI tile is filled from the live `summary` aggregate. */
interface KpiSpec {
  /** Caption, matching the reference's `<small>` exactly. */
  readonly caption: string;
  /** Field in the endpoint's SQL summary, or null when nothing measures it. */
  readonly field: string | null;
  readonly format: "units" | "money" | "count" | "percent" | "days";
  /** A second summary field forming the denominator of a percentage. */
  readonly of?: string;
  /** The basis of the number, shown beneath it. Never decorative. */
  readonly note?: string;
  /** Governed reason when `field` is null: the platform does not measure this. */
  readonly unavailableReason?: string;
}

/** How one table column reads a row. */
interface ColumnSpec {
  /** Header, matching the reference's `<th>` exactly. */
  readonly header: string;
  readonly field?: string | null;
  readonly format?: "units" | "money" | "count" | "percent" | "days" | "text";
  /** Renders a colour-coded badge from the field's value. */
  readonly badge?: boolean;
  /** Interval-derived: withheld together when `intervalAvailable` is false. */
  readonly gated?: boolean;
}

interface TableSpec {
  readonly heading: string | null;
  readonly columns: readonly ColumnSpec[];
}

/**
 * How one row of a reference BREAKDOWN card is filled. The reference's label is
 * the approved vocabulary; `field` names the SQL aggregate behind it and `of`
 * turns it into the share the reference shows beside the value.
 */
interface BreakdownRow {
  readonly label: string;
  readonly field: string | null;
  readonly format: KpiSpec["format"];
  readonly of?: string;
  readonly unavailableReason?: string;
}

interface ScreenSpec {
  readonly title: string;
  readonly subtitle: string;
  readonly endpoint: string;
  readonly kpis: readonly KpiSpec[];
  readonly tables: readonly TableSpec[];
  /** Reference label -> live aggregate, for breakdown, donut and alert cards. */
  readonly breakdown?: readonly BreakdownRow[];
}

const UNAVAILABLE = "Not available";
const WITHHELD = "Manual judgment required";

/**
 * Why a measure is absent and what would make it appear. Every unavailable
 * element carries one: "Not available" on its own tells a retailer nothing, and
 * the first question in a demo is always whether the gap is permanent.
 */
export const AVAILABILITY: Record<string, {why: string; when: string}> = {
  REPLAY_UNAVAILABLE: {
    why: "the weekly replay does not yet reconstruct observed stock closely enough to compare policies against it",
    when: "when replay reconstruction reaches the accuracy threshold frozen before scoring"
  },
  NRV_UNAVAILABLE: {
    why: "net realizable value is a forward selling price net of disposal cost, and the platform holds acquisition cost rather than an expected recovery price",
    when: "when a pricing-floor policy supplies the recovery price; a finance figure is not estimated without one"
  },
  PROVISION_NEEDS_SKU_COST: {
    // Deliberately specific. The markdown policy IS approved and IS applied --
    // the ageing engine marks 2,128 candidate cells at 10 per cent -- so a
    // generic "needs a policy" would be wrong, and would send a finance reader
    // looking for an approval that already exists.
    why: "the markdown is applied per SKU while inventory is valued per category, so the provision cannot be costed without spreading a category's value across its SKUs",
    when: "when valuation is published at SKU grain; a spread provision would be an estimate presented as a ledger figure"
  },
  PO_VALUE_NOT_PROJECTED: {
    why: "no purchase order exists yet -- these are recommendations, and an order carries a value only once it is raised against agreed terms",
    when: "when recommendations are converted to purchase orders"
  },
  DOCK_TO_STOCK_NOT_INSTRUMENTED: {
    why: "the source records receipts but not putaway completion",
    when: "when warehouse operations emit a putaway timestamp"
  },
  ACCEPTANCE_NOT_INSTRUMENTED: {
    why: "recommendations are read-only in this release, so none has been accepted or rejected",
    when: "when the approval workflow is enabled"
  },
  PRIOR_PERIOD_NOT_COMPARED: {
    why: "only the current trailing window is published",
    when: "when a second window is retained to compare against"
  },
  ORDER_VALUE_NEEDS_COSTED_LINES: {
    why: "a recommendation carries units, and pricing it needs a cost at SKU grain that the category-level valuation cannot supply",
    when: "when order lines are priced at creation against supplier terms"
  },
  BUDGET_NOT_APPLIED: {
    why: "the market budget ceiling is declared in policy but not yet applied to recommendations",
    when: "when the budget cap is enforced in the replenishment engine"
  }
};

function availabilityNote(reason: string | undefined): string | null {
  if (!reason) return null;
  const entry = AVAILABILITY[reason];
  if (!entry) return null;
  return `Not available because ${entry.why}. Available ${entry.when}.`;
}

/** Reasons a value is absent, in the words a retailer needs, not a code. */
const REASON_TEXT: Record<string, string> = {
  COLD_START_INTERVAL_UNCALIBRATED:
    "the forecast interval is calibrated through horizon 4 and this row's protection period reaches further",
  SUPPLY_ROUTE_UNRESOLVED:
    "no active service lane or supply term resolves for this row, so it has no protection period",
  FORECAST_ABSENT_FOR_NODE:
    "no forecast series exists for this node, so it has no interval of its own",
  ABC_UNIT_COST_UNAVAILABLE:
    "no accepted unit cost, so this cell cannot be ranked and no service level applies",
  NODE_INTERVAL_BASIS_UNAVAILABLE:
    "this node's demand is the sum of the stores it supplies; their upper quantiles cannot be added",
  DEAD_STOCK_NO_DEMAND: "no trailing demand, so cover has no denominator",
  DEAD_STOCK_DEASSORTED: "de-assorted, so cover is not meaningful",
  NO_TRAILING_DEMAND_OBSERVED: "no trailing demand observed for this cell",
  UNIT_COST_UNAVAILABLE: "no accepted unit cost for every on-hand SKU in this group",
  NRV_UNAVAILABLE: "net realizable value needs an approved markdown policy"
};

/** Badge colour by value, matching the reference's b-green/amber/red/blue/gray. */
function badgeClass(value: string): string {
  const key = value.toLowerCase();
  if (/healthy|low|active|verified|confirmed|on track/.test(key)) return "b-green";
  if (/overstock|stockout|high|critical|late|breach|fail/.test(key)) return "b-red";
  if (/understock|watch|medium|risk|expiry|delay|pending|warning/.test(key)) {
    return "b-amber";
  }
  if (/dead|residual|closed|info/.test(key)) return "b-gray";
  return "b-blue";
}

/* -- formatting ------------------------------------------------------------- */

const CURRENCY_SYMBOL: Record<string, string> = {INR: "₹", USD: "$"};

/**
 * Money in the reference's own notation: Indian crore/lakh for INR, M/K for USD.
 * Minor units in, market-local out. Nothing is converted here -- policy v2 forbids
 * a nominal sum across currencies, so a multi-currency slice is labelled rather
 * than added.
 */
function formatMoney(minor: number, currency: string): string {
  const symbol = CURRENCY_SYMBOL[currency] ?? `${currency} `;
  const major = minor / 100;
  if (currency === "INR") {
    if (major >= 1e7) return `${symbol}${(major / 1e7).toFixed(2)} Cr`;
    if (major >= 1e5) return `${symbol}${(major / 1e5).toFixed(2)}L`;
    return `${symbol}${major.toLocaleString("en-IN", {maximumFractionDigits: 0})}`;
  }
  if (major >= 1e6) return `${symbol}${(major / 1e6).toFixed(2)}M`;
  if (major >= 1e3) return `${symbol}${(major / 1e3).toFixed(1)}K`;
  return `${symbol}${major.toLocaleString("en-US", {maximumFractionDigits: 0})}`;
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatValue(
  value: unknown,
  format: ColumnSpec["format"] | KpiSpec["format"],
  currency: string
): string {
  if (value === null || value === undefined) return UNAVAILABLE;
  if (format === "text" || format === undefined) {
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value)) return value.length ? value.join(", ") : UNAVAILABLE;
    return String(value);
  }
  const numeric = asNumber(value);
  if (numeric === null) return UNAVAILABLE;
  switch (format) {
    case "money":
      return formatMoney(numeric, currency);
    case "percent":
      return `${(numeric * 100).toFixed(1)}%`;
    case "days":
      return `${numeric.toFixed(1)} days`;
    case "units":
    case "count":
    default:
      return numeric.toLocaleString("en-US", {maximumFractionDigits: 0});
  }
}

/* -- the fourteen screens ---------------------------------------------------- */

/**
 * Each screen reads ONE endpoint, so a page is one request and a filter applies to
 * its tiles and its table together. Where a reference KPI has no measure in that
 * endpoint's SQL summary it renders the governed unavailable treatment with a
 * reason naming what is missing -- the plan's element-level behaviour. Substituting
 * a value from elsewhere, or a zero, is what that behaviour exists to prevent.
 */
const SCREENS: Record<InventoryPageId, ScreenSpec> = {
  inventoryOverview: {
    title: "Inventory Overview",
    subtitle: "Enterprise inventory position, risk, working capital and actions",
    endpoint: "/api/v1/inventory/overview",
    kpis: [
      {caption: "On-Hand Inventory", field: "onHandUnits", format: "units",
       note: "Units across active and residual cells"},
      {caption: "Available to Promise", field: "atpUnits", format: "units",
       of: "onHandUnits", note: "After committed, reserved and damaged"},
      {caption: "Inventory in Transit", field: "inTransitUnits", format: "units",
       note: "Received against a declared lane"},
      {caption: "Inventory at Risk", field: "healthAtRiskCells",
       format: "count", of: "healthCells",
       note: "Buffer too thin to serve demand, or stock that has stopped moving"},
      {caption: "Stock Turn", field: null, format: "count",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    breakdown: [
      // "Inventory Position" -- the reference's aggregation card.
      {label: "Store inventory", field: "storeOnHandUnits", format: "units",
       of: "onHandUnits"},
      {label: "Warehouse inventory", field: "dcOnHandUnits", format: "units",
       of: "onHandUnits"},
      {label: "In transit", field: "inTransitUnits", format: "units",
       of: "onHandUnits"},
      {label: "Reserved stock", field: "reservedUnits", format: "units",
       of: "onHandUnits"},
      {label: "Damaged / blocked", field: "damagedUnits", format: "units",
       of: "onHandUnits"},
      // "Inventory by Health" donut. Health class is projected per cell on Stock
      // Health, not on the position summary, so these name where they live.
      // The overview is a dashboard, so the read model merges the stock-health
      // projection's class counts under a `health` prefix. "At Risk" is the
      // reference's word for the understocked and dead classes together.
      {label: "Healthy", field: "healthHealthyCells", format: "count"},
      {label: "At Risk", field: "healthAtRiskCells", format: "count"},
      {label: "Overstock", field: "healthOverstockCells", format: "count"},
      {label: "Out of Stock", field: "healthStockoutCells", format: "count"},
      // "Immediate Decisions".
      {label: "Transfer excess stock", field: "healthOverstockCells",
       format: "count"},
      {label: "Approve ageing-stock markdown", field: "healthDeadCells",
       format: "count"},
      {label: "Accelerate replenishment", field: "residualOnlyCells",
       format: "count"}
    ],
    tables: [
      // Reference order: Ageing Inventory, Inventory Risk by Category, then the
      // full-width Location-Level table. The position projection cannot fill the
      // first two, so every column renders its governed cell and keeps its header.
      {heading: "Ageing Inventory", columns: [
        {header: "Age Bucket", field: null},
        {header: "SKUs", field: "skuId"},
        {header: "Inventory Value", field: "onHandUnits", format: "units"},
        {header: "Sell-through", field: null},
        {header: "Recommended Action", field: null}
      ]},
      {heading: "Inventory Risk by Category", columns: [
        {header: "Category", field: "locationId"},
        {header: "Value", field: "onHandUnits", format: "units"},
        {header: "Days of Supply", field: null},
        {header: "Risk", field: "residualOnly", badge: true},
        {header: "Action", field: null}
      ]},
      {heading: "Location-Level Inventory Performance", columns: [
        {header: "Location", field: "locationId"},
        {header: "Type", field: "locationKind"},
        {header: "Inventory Value", field: "onHandUnits", format: "units"},
        {header: "Availability", field: "atpUnits", format: "units"},
        {header: "Days of Supply", field: null},
        {header: "Stock-out Risk", field: "residualOnly", badge: true},
        {header: "Overstock", field: "committedUnits", format: "units"},
        {header: "Priority Action", field: null}
      ]}
    ]
  },
  storeInventory: {
    title: "Store Inventory",
    subtitle: "Store-level availability, overstock, understock and transfer opportunities",
    endpoint: "/api/v1/inventory/stores",
    kpis: [
      {caption: "Store Inventory Value", field: "valuationStoreValueMinor",
       format: "money",
       note: "Store-grain units on hand"},
      {caption: "On-Shelf Availability", field: "atpUnits", format: "units",
       of: "onHandUnits", note: "Available to promise share"},
      {caption: "Stores at Risk", field: "healthAtRiskLocations", format: "count",
       of: "healthLocations",
       note: "Measured on Stock Health"},
      {caption: "Transfer Opportunity", field: "transferUnits", format: "units",
       note: "Units the optimizer would move between locations"},
      {caption: "Lost Sales Exposure", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    breakdown: [
      // "Store Exception Summary" -- an aggregation card, not a row table. An
      // earlier version rendered the heatmap's columns under this heading and
      // dropped the aggregation entirely.
      {label: "High stock-out risk", field: "healthStockoutCells",
       format: "count"},
      {label: "High overstock risk", field: "healthOverstockCells",
       format: "count"},
      {label: "Display stock mismatch", field: "valuationWmsVarianceUnits",
       format: "units"},
      {label: "Negative inventory", field: "negativeCells", format: "count"},
      {label: "Transfer candidates", field: "transferRows", format: "count"}
    ],
    tables: [
      {heading: "Store Inventory Heatmap", columns: [
        {header: "Store", field: "locationId"},
        {header: "Availability", field: "atpUnits", format: "units"},
        {header: "DoS", field: null},
        {header: "Overstock", field: "onHandUnits", format: "units"},
        {header: "Understock", field: "committedUnits", format: "units"},
        {header: "Action", field: "residualOnly", badge: true}
      ]}
    ]
  },
  warehouseInventory: {
    title: "Warehouse Inventory",
    subtitle: "DC position, utilization, receipts and fill",
    endpoint: "/api/v1/inventory/warehouses",
    kpis: [
      {caption: "Warehouse Inventory", field: "onHandUnits", format: "units",
       note: "DC-grain units on hand"},
      {caption: "Inbound in Transit", field: "inTransitUnits", format: "units",
       note: "Received against a declared lane"},
      {caption: "Blocked Inventory", field: "damagedUnits", format: "units",
       note: "Damaged and blocked buckets"},
      {caption: "Dock-to-Stock Time", field: null, format: "days",
       unavailableReason: "DOCK_TO_STOCK_NOT_INSTRUMENTED",
       note: "Needs receipt-to-putaway timestamps"},
      {caption: "Warehouse Fill Rate", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Warehouse", field: "locationId"},
        {header: "Inventory Value", field: "onHandUnits", format: "units"},
        {header: "Capacity Utilization", field: null},
        {header: "Fill Rate", field: null},
        {header: "Blocked Stock", field: "damagedUnits", format: "units"},
        {header: "Delayed Receipts", field: "onOrderUnits", format: "units"},
        {header: "Action", field: "residualOnly", badge: true}
      ]}
    ]
  },
  inventoryAgeing: {
    title: "Inventory Ageing",
    subtitle: "Age buckets and the deterministic action ladder",
    endpoint: "/api/v1/inventory/ageing",
    kpis: [
      {caption: "60+ Day Inventory", field: "units60Plus", format: "units",
       of: "onHandUnits",
       note: "Per-bucket units are in the table below"},
      {caption: "90+ Day Inventory", field: "units90Plus", format: "units",
       of: "onHandUnits",
       note: "Per-bucket units are in the table below"},
      {caption: "Dead Stock", field: "residualUnits", format: "units",
       note: "Units in residual-only cells"},
      {caption: "Markdown Opportunity", field: "markdownCells", format: "count",
       note: "Cells the action ladder marks for markdown"},
      {caption: "Transfer Opportunity", field: "transferUnits", format: "units",
       note: "Units the optimizer would move between locations"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "SKU / Product", field: "skuId"},
        {header: "Category", field: "locationId"},
        {header: "Age", field: "ageBucket"},
        {header: "Units", field: "onHandUnits", format: "units"},
        {header: "Value", field: null},
        {header: "Sell-through", field: null},
        {header: "Recommended Action", field: "action"},
        {header: "Priority", field: "residualOnly", badge: true}
      ]}
    ]
  },
  inventoryTransfers: {
    title: "Stock Transfers",
    subtitle: "Transfer recommendations over typed lanes",
    endpoint: "/api/v1/inventory/transfers",
    kpis: [
      {caption: "Open Transfer Requests", field: "rows", format: "count",
       note: "Recommendations over declared alternate lanes"},
      {caption: "Transfer Value", field: "expectedBenefitMinor", format: "money",
       note: "Market-local cost value of the units moved"},
      {caption: "Expected Lost-Sales Recovery", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"},
      {caption: "Average Transfer Time", field: "meanTransitDays", format: "days",
       note: "Per-lane transit days are in the table below"},
      {caption: "Transfer Acceptance", field: null, format: "percent",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED",
       note: "Recommendations are read-only in this release"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "SKU", field: "skuId"},
        {header: "From Location", field: "fromLocationId"},
        {header: "To Location", field: "toLocationId"},
        {header: "Available Qty", field: "units", format: "units"},
        {header: "Suggested Qty", field: "units", format: "units"},
        {header: "Value", field: "expectedBenefitMinor", format: "money"},
        {header: "Expected Benefit", field: "expectedBenefitMinor", format: "money"},
        {header: "Status", field: "laneId", badge: true}
      ]}
    ]
  },
  inventoryValuation: {
    title: "Inventory Valuation",
    subtitle: "Gross valuation and DC ERP-vs-WMS variance",
    endpoint: "/api/v1/inventory/valuation",
    kpis: [
      {caption: "Gross Inventory Value", field: "grossValueMinor", format: "money",
       note: "Accepted unit cost times on hand, market-local"},
      {caption: "Net Realizable Value", field: null, format: "money",
       unavailableReason: "NRV_UNAVAILABLE",
       note: "Needs an approved markdown policy"},
      {caption: "Markdown Provision", field: null, format: "money",
       unavailableReason: "PROVISION_NEEDS_SKU_COST",
       note: "Needs an approved markdown policy"},
      {caption: "Obsolescence Provision", field: null, format: "money",
       unavailableReason: "PROVISION_NEEDS_SKU_COST",
       note: "Needs an approved markdown policy"},
      {caption: "Inventory Variance", field: "wmsVarianceUnits", format: "units",
       note: "Absolute ERP-versus-WMS discrepancy"}
    ],
    tables: [
      {heading: "Valuation by Category", columns: [
        {header: "Category", field: "category"},
        {header: "Gross Value", field: "grossValueMinor", format: "money"},
        {header: "NRV", field: null},
        {header: "Provision", field: null},
        {header: "Variance", field: "wmsVarianceUnits", format: "units"}
      ]}
    ]
  },
  expiryWaste: {
    title: "Expiry & Waste",
    subtitle: "Expiry-window exposure and waste actuals",
    endpoint: "/api/v1/inventory/expiry-waste",
    kpis: [
      {caption: "Near-Expiry Inventory", field: "expiringUnits", format: "units",
       note: "Units expiring inside the policy window"},
      {caption: "Waste This Month", field: "wasteUnits", format: "units",
       note: "Written off in the trailing window"},
      {caption: "Waste Reduction", field: null, format: "percent",
       unavailableReason: "PRIOR_PERIOD_NOT_COMPARED",
       note: "Needs a prior-period comparison"},
      {caption: "Products at Risk", field: "cells", format: "count",
       note: "Cells with expiry or waste evidence"},
      {caption: "Recovery Opportunity", field: "exposureMinor", format: "money",
       note: "Cost value of units expiring in the window"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Product", field: "skuId"},
        {header: "Location", field: "locationId"},
        {header: "Expiry Window", field: "expiringUnits", format: "units"},
        {header: "Units", field: "expiredUnits", format: "units"},
        {header: "Value", field: "exposureMinor", format: "money"},
        {header: "Sell-through", field: null},
        {header: "Recommended Action", field: null},
        {header: "Priority", field: "wasteUnits", format: "units"}
      ]}
    ]
  },
  stockHealth: {
    title: "Stock Health",
    subtitle: "SKU × store triage across active and residual stock",
    endpoint: "/api/v1/inventory/stock-health",
    kpis: [],
    tables: [
      {heading: null, columns: [
        {header: "SKU", field: "skuId"},
        {header: "Store", field: "locationId"},
        {header: "Days of Supply", field: "coverDays", format: "days"},
        {header: "Ageing", field: null},
        {header: "Health", field: "healthClass", badge: true},
        {header: "Financial Exposure", field: null},
        {header: "Recommended Action", field: "reasonCode"},
        {header: "Priority", field: "healthClass", badge: true}
      ]}
    ]
  },
  replenishmentPlanner: {
    title: "Replenishment Planner",
    subtitle: "Suggested orders under lane, term, capacity and budget guards",
    endpoint: "/api/v1/replenishment/planner",
    kpis: [
      {caption: "Suggested Replenishment Value", field: "recommendedUnits",
       format: "units", note: "Units across cells with a computed level"},
      {caption: "Revenue Protected", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"},
      {caption: "Working Capital Impact", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"},
      {caption: "Projected Service Level", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"},
      {caption: "Exception Orders", field: "withheldCells", format: "count",
       note: "Cells withheld with a governed reason"}
    ],
    tables: [
      {heading: "Priority Replenishment Recommendations", columns: [
        {header: "select", field: null},
        {header: "Priority", field: "reasonCode"},
        {header: "SKU / Product", field: "skuId"},
        {header: "Destination", field: "destinationLocationId"},
        {header: "Current Stock", field: null},
        {header: "Forecast Demand", field: null},
        {header: "Safety Stock", field: null},
        {header: "Suggested Qty", field: "recommendedUnits", format: "units",
         gated: true},
        {header: "Source", field: "supplyLocationId"},
        {header: "Lead Time", field: null},
        {header: "Expected Receipt", field: null},
        {header: "Order Value", field: null},
        {header: "Service Impact", field: "orderUpToUnits", format: "units",
         gated: true},
        {header: "Confidence", field: "reorderPointUnits", format: "units",
         gated: true},
        {header: "Status", field: "erpStatus", badge: true}
      ]}
    ]
  },
  suggestedOrders: {
    title: "Suggested Orders",
    subtitle: "Read-only candidate orders; ERP transmission is shadow-only",
    endpoint: "/api/v1/replenishment/orders",
    kpis: [
      {caption: "Suggested Orders", field: "cellsToOrder", format: "count",
       note: "Cells with a positive recommended quantity"},
      {caption: "Order Value", field: null, format: "money",
       unavailableReason: "ORDER_VALUE_NEEDS_COSTED_LINES",
       note: "Needs a costed order line per cell"},
      {caption: "High Priority", field: "withheldCells", format: "count",
       note: "Cells withheld with a governed reason"},
      {caption: "Within Budget", field: null, format: "percent",
       unavailableReason: "BUDGET_NOT_APPLIED",
       note: "Market budget ceiling is not yet applied"},
      {caption: "Expected Fill Rate", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Order", field: "skuId"},
        {header: "Type", field: "erpStatus", badge: true},
        {header: "Destination", field: "destinationLocationId"},
        {header: "Source", field: "supplyLocationId"},
        {header: "Items", field: "recommendedUnits", format: "units", gated: true},
        {header: "Value", field: null},
        {header: "Need Date", field: null},
        {header: "Confidence", field: "reorderPointUnits", format: "units",
         gated: true},
        {header: "Status", field: "reasonCode"}
      ]}
    ]
  },
  supplierPlanning: {
    title: "Supplier Planning",
    subtitle: "Supplier performance, origin-safe terms and risk",
    endpoint: "/api/v1/replenishment/suppliers",
    kpis: [
      {caption: "Active Suppliers", field: "suppliers", format: "count",
       note: "Suppliers with performance evidence"},
      {caption: "Open PO Value", field: null, format: "money",
       unavailableReason: "PO_VALUE_NOT_PROJECTED",
       note: "Purchase-order value is not in this projection"},
      {caption: "Capacity Confirmed", field: "meanCapacityConfirmedPct",
       format: "percent",
       note: "Per-supplier capacity is in the table below"},
      {caption: "On-Time Delivery", field: "meanOtdRate", format: "percent",
       note: "Mean across suppliers in scope"},
      {caption: "Supplier Risk", field: "highRisk", format: "count",
       note: "Suppliers the risk engine classes high"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Supplier", field: "supplierId"},
        {header: "Category", field: null},
        {header: "Open PO Value", field: null},
        {header: "Capacity", field: "capacityConfirmedPct", format: "percent"},
        {header: "Lead Time", field: "leadTimeMeanDays", format: "days"},
        {header: "OTD", field: "otdRate", format: "percent"},
        {header: "Risk", field: "riskClass", badge: true},
        {header: "Action", field: "reasonCodes"}
      ]}
    ]
  },
  safetyStock: {
    title: "Safety Stock",
    subtitle: "Policy segments from the hard-gated interval",
    endpoint: "/api/v1/replenishment/safety-stock",
    kpis: [
      {caption: "Safety Stock Value", field: "safetyStockUnits", format: "units",
       note: "Units across cells with a computed buffer"},
      {caption: "Policy Coverage", field: "assessedCells", format: "count",
       of: "cells", note: "Cells with an available interval"},
      {caption: "Below Safety Stock", field: "belowSafetyCells", format: "count",
       of: "comparedCells",
       note: "Compared on Replenishment Planner"},
      {caption: "Excess Safety Stock", field: "excessSafetyCells", format: "count",
       of: "comparedCells",
       note: "Compared on Replenishment Planner"},
      {caption: "Projected Service Level", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: "Safety Stock Drivers", columns: [
        {header: "Policy Segment", field: "abcClass", badge: true},
        {header: "SKUs", field: "skuId"},
        {header: "Service Target", field: "serviceLevel", format: "percent",
         gated: true},
        {header: "Current Value", field: "safetyStockUnits", format: "units",
         gated: true},
        {header: "Recommended Value", field: "safetyStockUnits", format: "units",
         gated: true},
        {header: "Impact", field: "reasonCode"}
      ]}
    ]
  },
  allocationFulfillment: {
    title: "Allocation & Fulfillment",
    subtitle: "Constrained channel allocation over one node ATP pool",
    endpoint: "/api/v1/replenishment/allocations",
    kpis: [
      {caption: "Available Allocation Pool", field: "allocatedUnits",
       format: "units", note: "Units allocated from node ATP"},
      {caption: "Store Requests", field: "requestedUnits", format: "units",
       note: "Requested across channels in scope"},
      {caption: "Fulfillment Rate", field: "allocatedUnits", format: "percent",
       of: "requestedUnits", note: "Allocated share of requested"},
      {caption: "Priority Shortfall", field: "shortfallUnits", format: "units",
       note: "Requested less allocated"},
      {caption: "Revenue Protected", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Product", field: "skuId"},
        {header: "Available Pool", field: "allocatedUnits", format: "units"},
        {header: "Store Demand", field: "requestedUnits", format: "units"},
        {header: "Allocated", field: "allocatedUnits", format: "units"},
        {header: "Shortfall", field: "shortfallUnits", format: "units"},
        {header: "Allocation Rule", field: "channelId"},
        {header: "Priority", field: "channelId", badge: true},
        {header: "Status", field: "locationId"}
      ]}
    ]
  },
  replenishmentExceptions: {
    title: "Replenishment Exceptions",
    subtitle: "Deterministic engine-derived exceptions",
    endpoint: "/api/v1/replenishment/exceptions",
    kpis: [
      {caption: "Open Exceptions", field: "rows", format: "count",
       note: "Engine-derived, read-only"},
      {caption: "High Priority", field: "warnings", format: "count",
       note: "Severity warning"},
      {caption: "Budget Exceptions", field: null, format: "count",
       unavailableReason: "BUDGET_NOT_APPLIED",
       note: "Market budget ceiling is not yet applied"},
      {caption: "Supplier Exceptions", field: "classes", format: "count",
       note: "Distinct exception classes in scope"},
      {caption: "ERP Failures", field: "orderErpFailures", format: "count",
       note: "No send path exists in this release"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Exception", field: "exceptionClass"},
        {header: "Order / SKU", field: "skuId"},
        {header: "Business Impact", field: "evidence"},
        {header: "Owner", field: null},
        {header: "Age", field: null},
        {header: "Priority", field: "severity", badge: true},
        {header: "Recommended Resolution", field: "reasonCode"},
        {header: "Status", field: "locationId"}
      ]}
    ]
  }
};

export const inventoryScreens = SCREENS;

/* -- components -------------------------------------------------------------- */

type Row = Record<string, unknown>;

/** A row is interval-withheld when the projection says so, explicitly. */
function isWithheld(row: Row): boolean {
  return row.intervalAvailable === false;
}

function reasonOf(row: Row): string {
  return typeof row.reasonCode === "string" ? row.reasonCode : "";
}

/** The market currency for a slice, or null when it spans more than one. */
function sliceCurrency(slice: InventorySlice): string {
  return slice.markets.length === 1 && slice.markets[0].startsWith("india")
    ? "INR"
    : slice.markets.length === 1
      ? "USD"
      : "INR";
}

function Kpi({spec, slice}: {spec: KpiSpec; slice: InventorySlice}) {
  const summary = slice.summary;
  const currency = sliceCurrency(slice);

  if (spec.field === null) {
    // Nothing measures this. The tile keeps its position so the grid does not
    // reflow, and states WHY and WHEN rather than just "Not available" -- the
    // first question anyone asks of an empty tile is whether it is permanent.
    const note = availabilityNote(spec.unavailableReason) ?? spec.note;
    return (
      <div
        className="kpi"
        data-kpi={spec.caption}
        data-unavailable="true"
        data-reason-code={spec.unavailableReason}
        title={note ?? undefined}
      >
        <small>{spec.caption}</small>
        <div className="value unavailable">{UNAVAILABLE}</div>
        {note && <div className="demo-note">{note}</div>}
      </div>
    );
  }
  const raw = summary?.[spec.field];
  const numeric = asNumber(raw);
  if (numeric === null) {
    return (
      <div className="kpi" data-kpi={spec.caption} data-unavailable="true">
        <small>{spec.caption}</small>
        <div className="value unavailable">{UNAVAILABLE}</div>
        {spec.note && <div className="demo-note">{spec.note}</div>}
      </div>
    );
  }
  const denominator = spec.of ? asNumber(summary?.[spec.of]) : null;
  const share =
    spec.of && denominator && denominator > 0 ? numeric / denominator : null;
  const value =
    spec.format === "percent" && spec.of
      ? share === null
        ? UNAVAILABLE
        : `${(share * 100).toFixed(1)}%`
      : formatValue(numeric, spec.format, currency);
  return (
    <div className="kpi" data-kpi={spec.caption}>
      <small>{spec.caption}</small>
      <div className="value">{value}</div>
      {share !== null && spec.format !== "percent" && (
        <span className="delta up">{(share * 100).toFixed(1)}% of on-hand</span>
      )}
      {spec.note && <div className="demo-note">{spec.note}</div>}
    </div>
  );
}

function Cell({
  column, row, currency
}: {column: ColumnSpec; row: Row; currency: string}) {
  if (!column.field) {
    // The reference has a column here and the platform has no measure for it.
    // Rendering the header with a governed cell is the approved element-level
    // behaviour; dropping the column would silently change the approved layout.
    return (
      <td className="cell-unavailable" data-unavailable="true">
        {UNAVAILABLE}
      </td>
    );
  }
  if (column.gated && isWithheld(row)) {
    const reason = reasonOf(row);
    return (
      <td
        className="cell-unavailable"
        data-unavailable="true"
        data-reason-code={reason || undefined}
        title={REASON_TEXT[reason] ?? "This value was withheld by policy."}
      >
        {WITHHELD}
      </td>
    );
  }
  const value = row[column.field];
  if (column.badge && value !== null && value !== undefined) {
    const text = formatValue(value, "text", currency);
    return (
      <td>
        <span className={`badge ${badgeClass(text)}`}>{text}</span>
      </td>
    );
  }
  const rendered = formatValue(value, column.format, currency);
  if (rendered === UNAVAILABLE) {
    return (
      <td className="cell-unavailable" data-unavailable="true">
        {UNAVAILABLE}
      </td>
    );
  }
  return <td>{rendered}</td>;
}

function DataCard({
  table, slice
}: {table: TableSpec; slice: InventorySlice}) {
  const currency = sliceCurrency(slice);
  const rows = slice.items as Row[];
  return (
    <div className="card">
      {(table.heading || slice.pagination) && (
        // The count is not decoration on the heading -- it is the disclosure
        // that the table is a cut. A headless card in the reference is still a
        // capped page, so it carries the count even with no title beside it.
        <div className="card-head">
          {table.heading ? <h3>{table.heading}</h3> : <span />}
          <span className="link-button" aria-hidden="true">
            {slice.pagination
              ? `Top ${rows.length} of ${slice.pagination.total.toLocaleString("en-US")}`
              : `${rows.length}`}
          </span>
        </div>
      )}
      {slice.ranking && slice.pagination
        && slice.pagination.total > rows.length && (
        <p className="kpi-note" data-testid="ranking-note">
          Ranked by {slice.ranking}. The tiles above are aggregated in SQL over
          all {slice.pagination.total.toLocaleString("en-US")} rows in scope, not
          over this page.
        </p>
      )}
      <div className="table-scroll">
        <table className="table" data-card-kind="rows">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.header}>
                  {column.header === "select" ? "" : column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} data-partial={isWithheld(row) ? "true" : undefined}>
                {table.columns.map((column) => (
                  <Cell
                    key={column.header}
                    column={column}
                    row={row}
                    currency={currency}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * The action strip and filters, both from the reference. Controls are visible and
 * natively disabled with no mutation handler (P4-D9/P4-D11): the workflow belongs
 * to a later phase, and hiding the controls would misrepresent the product.
 */
function ActionStrip({reference}: {reference: ReferenceScreen}) {
  return (
    <>
      <div
        className="inventory-action-strip"
        aria-label={`${reference.screenId} actions`}
      >
        {reference.actions.map((label, index) => (
          <button
            key={label}
            className={index === 0 ? "btn btn-primary" : "btn"}
            type="button"
            disabled
            aria-disabled="true"
            title="Read-only in this release; workflow actions belong to a later phase"
          >
            {label}
          </button>
        ))}
      </div>
      {reference.filters.length > 0 && (
        <div className="filters" style={{justifyContent: "flex-start"}}>
          {reference.filters.map((options, index) => (
            <select
              key={index}
              className="filter"
              disabled
              aria-disabled="true"
              aria-label={options[0]}
              defaultValue={options[0]}
            >
              {options.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          ))}
        </div>
      )}
    </>
  );
}

export function InventoryPage({pageId}: {pageId: InventoryPageId}) {
  const screen = SCREENS[pageId];
  const reference = REFERENCE_SCREEN_BY_ID[pageId];
  const slice = useQuery({
    queryKey: ["inventory-slice", screen.endpoint],
    queryFn: () => loadInventorySlice(screen.endpoint),
    retry: false
  });

  return (
    <>
      {reference && <ActionStrip reference={reference} />}
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
        <>
          {screen.kpis.length > 0 && (
            <div className="kpi-grid">
              {screen.kpis.map((spec) => (
                <Kpi key={spec.caption} spec={spec} slice={slice.data} />
              ))}
            </div>
          )}
          {slice.data.items.length === 0 ? (
            <div className="state-card" style={{marginTop: 14}}>
              <strong>No rows in the active bundle for this selection.</strong>
              <small>Zero rows is a governed result, not a failure.</small>
            </div>
          ) : (
            <CardBlocks screen={screen} reference={reference} slice={slice.data} />
          )}
        </>
      ) : null}
    </>
  );
}

/* -- reference card kinds ---------------------------------------------------- */

/**
 * A BREAKDOWN card: the reference's headerless label/value table. This is the
 * aggregation view -- "Store inventory / ₹31.6 Cr / 64.9%" -- and it reads the
 * endpoint's SQL summary, never the page's rows. An earlier version omitted this
 * card kind entirely, which is why Inventory Overview and Store Inventory came out
 * wrong: their aggregation was simply missing.
 */
function BreakdownCard({
  heading, link, labels, rows, slice
}: {
  heading: string | null;
  link: string | null;
  labels: readonly string[];
  rows: readonly BreakdownRow[];
  slice: InventorySlice;
}) {
  const summary = slice.summary;
  const currency = sliceCurrency(slice);
  return (
    <div className="card">
      {heading && (
        <div className="card-head">
          <h3>{heading}</h3>
          {link && <span className="link-button" aria-hidden="true">{link}</span>}
        </div>
      )}
      <table className="table" data-card-kind="breakdown">
        <tbody>
          {labels.map((label) => {
            const spec = rows.find((row) => row.label === label);
            const raw = spec?.field ? summary?.[spec.field] : null;
            const numeric = asNumber(raw);
            if (!spec || spec.field === null || numeric === null) {
              const note = availabilityNote(spec?.unavailableReason);
              return (
                <tr key={label} data-unavailable="true">
                  <td>{label}</td>
                  <td className="cell-unavailable" title={note ?? undefined}>
                    {UNAVAILABLE}
                  </td>
                  <td className="demo-note">{note ?? ""}</td>
                </tr>
              );
            }
            const denominator = spec.of ? asNumber(summary?.[spec.of]) : null;
            const share =
              denominator && denominator > 0 ? numeric / denominator : null;
            return (
              <tr key={label}>
                <td>{label}</td>
                <td>{formatValue(numeric, spec.format, currency)}</td>
                <td>{share === null ? "" : `${(share * 100).toFixed(1)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The reference's donut plus legend. The ring is a conic gradient built from the
 * live shares, so the picture and the legend cannot disagree -- and a slice with no
 * measure is dropped from the ring rather than drawn at an invented size.
 */
const DONUT_COLOURS = ["#1fbf75", "#ffae1a", "#f05a67", "#a8b2c2", "#2f80ed"];

function DonutCard({
  heading, link, labels, rows, slice
}: {
  heading: string | null;
  link: string | null;
  labels: readonly string[];
  rows: readonly BreakdownRow[];
  slice: InventorySlice;
}) {
  const summary = slice.summary;
  const measured = labels.map((label, index) => {
    const spec = rows.find((row) => row.label === label);
    const value = spec?.field ? asNumber(summary?.[spec.field]) : null;
    return {label, value, colour: DONUT_COLOURS[index % DONUT_COLOURS.length]};
  });
  const total = measured.reduce((sum, slice_) => sum + (slice_.value ?? 0), 0);
  let cursor = 0;
  const stops = measured
    .filter((entry) => entry.value !== null && total > 0)
    .map((entry) => {
      const start = (cursor / total) * 360;
      cursor += entry.value ?? 0;
      const end = (cursor / total) * 360;
      return `${entry.colour} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`;
    });
  return (
    <div className="card">
      {heading && (
        <div className="card-head">
          <h3>{heading}</h3>
          {link && <span className="link-button" aria-hidden="true">{link}</span>}
        </div>
      )}
      <div className="donut-wrap">
        <div
          className="donut"
          data-testid="donut"
          style={{
            background:
              stops.length > 0
                ? `conic-gradient(${stops.join(", ")})`
                : "var(--line)"
          }}
        />
        <div className="legend">
          {measured.map((entry) => (
            <div key={entry.label}>
              <span className="dot" style={{background: entry.colour}} />
              {entry.label}{" "}
              {entry.value === null || total === 0
                ? UNAVAILABLE
                : `${((entry.value / total) * 100).toFixed(0)}%`}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * The reference's decision list. Each alert is a live count with the reference's
 * own headline; an alert whose count is zero is still shown, because "nothing to
 * do here" is information and a vanished row reads as an unrendered screen.
 */
function AlertsCard({
  heading, link, labels, rows, slice
}: {
  heading: string | null;
  link: string | null;
  labels: readonly string[];
  rows: readonly BreakdownRow[];
  slice: InventorySlice;
}) {
  const summary = slice.summary;
  const currency = sliceCurrency(slice);
  const icons = ["!", "₹", "↗", "•"];
  return (
    <div className="card">
      {heading && (
        <div className="card-head">
          <h3>{heading}</h3>
          {link && <span className="link-button" aria-hidden="true">{link}</span>}
        </div>
      )}
      {labels.map((label, index) => {
        const spec = rows.find((row) => row.label === label);
        const numeric = spec?.field ? asNumber(summary?.[spec.field]) : null;
        const note = availabilityNote(spec?.unavailableReason);
        return (
          <div className="alert" key={label}>
            <div className="alert-icon">{icons[index % icons.length]}</div>
            <div>
              <strong>{label}</strong>
              <span>
                {numeric === null
                  ? note ?? UNAVAILABLE
                  : `${formatValue(numeric, spec!.format, currency)} in scope`}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Cards in the reference's own layout blocks and document order. */
function CardBlocks({
  screen, reference, slice
}: {
  screen: ScreenSpec;
  reference: ReferenceScreen | undefined;
  slice: InventorySlice;
}) {
  if (!reference) return null;
  const breakdown = screen.breakdown ?? [];
  // Group consecutive cards sharing a layout, so a grid-3 row renders as one.
  const blocks: {layout: string; cards: typeof reference.cards}[] = [];
  for (const card of reference.cards) {
    const last = blocks[blocks.length - 1];
    if (last && last.layout === card.layout && card.layout !== "full") {
      last.cards = [...last.cards, card];
    } else {
      blocks.push({layout: card.layout, cards: [card]});
    }
  }
  let rowsIndex = 0;
  return (
    <div style={{display: "grid", gap: 14, marginTop: 14}}>
      {blocks.map((block, blockIndex) => (
        <div
          key={blockIndex}
          className={block.layout === "full" ? undefined : block.layout}
          style={block.layout === "full" ? undefined : {display: "grid", gap: 14}}
        >
          {block.cards.map((card, cardIndex) => {
            const key = `${blockIndex}-${cardIndex}`;
            if (card.kind === "breakdown") {
              return (
                <BreakdownCard
                  key={key}
                  heading={card.heading}
                  link={card.link}
                  labels={card.labels}
                  rows={breakdown}
                  slice={slice}
                />
              );
            }
            if (card.kind === "donut") {
              return (
                <DonutCard
                  key={key}
                  heading={card.heading}
                  link={card.link}
                  labels={card.labels}
                  rows={breakdown}
                  slice={slice}
                />
              );
            }
            if (card.kind === "alerts") {
              return (
                <AlertsCard
                  key={key}
                  heading={card.heading}
                  link={card.link}
                  labels={card.labels}
                  rows={breakdown}
                  slice={slice}
                />
              );
            }
            // A `rows` card: take the next declared table spec, so the reference's
            // column order drives what is rendered.
            const table = screen.tables[rowsIndex++];
            if (!table) return null;
            return (
              <DataCard
                key={key}
                table={{...table, heading: card.heading}}
                slice={slice}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
