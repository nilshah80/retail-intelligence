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

interface ScreenSpec {
  readonly title: string;
  readonly subtitle: string;
  readonly endpoint: string;
  readonly kpis: readonly KpiSpec[];
  readonly tables: readonly TableSpec[];
}

const UNAVAILABLE = "Not available";
const WITHHELD = "Manual judgment required";

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
      {caption: "Inventory at Risk", field: null, format: "units",
       unavailableReason: "RISK_ON_ANOTHER_MEASURE",
       note: "Measured on Stock Health and Expiry & Waste"},
      {caption: "Stock Turn", field: null, format: "count",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
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
      {caption: "Store Inventory Value", field: "onHandUnits", format: "units",
       note: "Store-grain units on hand"},
      {caption: "On-Shelf Availability", field: "atpUnits", format: "units",
       of: "onHandUnits", note: "Available to promise share"},
      {caption: "Stores at Risk", field: null, format: "count",
       unavailableReason: "RISK_ON_ANOTHER_MEASURE",
       note: "Measured on Stock Health"},
      {caption: "Transfer Opportunity", field: null, format: "units",
       unavailableReason: "TRANSFER_ON_ANOTHER_MEASURE",
       note: "Measured on Stock Transfers"},
      {caption: "Lost Sales Exposure", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: "Store Exception Summary", columns: [
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
      {caption: "60+ Day Inventory", field: null, format: "units",
       unavailableReason: "BUCKET_SPLIT_ON_TABLE",
       note: "Per-bucket units are in the table below"},
      {caption: "90+ Day Inventory", field: null, format: "units",
       unavailableReason: "BUCKET_SPLIT_ON_TABLE",
       note: "Per-bucket units are in the table below"},
      {caption: "Dead Stock", field: "residualUnits", format: "units",
       note: "Units in residual-only cells"},
      {caption: "Markdown Opportunity", field: "markdownCells", format: "count",
       note: "Cells the action ladder marks for markdown"},
      {caption: "Transfer Opportunity", field: null, format: "units",
       unavailableReason: "TRANSFER_ON_ANOTHER_MEASURE",
       note: "Measured on Stock Transfers"}
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
      {caption: "Average Transfer Time", field: null, format: "days",
       unavailableReason: "TRANSIT_SPLIT_ON_TABLE",
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
       unavailableReason: "NRV_UNAVAILABLE",
       note: "Needs an approved markdown policy"},
      {caption: "Obsolescence Provision", field: null, format: "money",
       unavailableReason: "NRV_UNAVAILABLE",
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
      {caption: "Capacity Confirmed", field: null, format: "percent",
       unavailableReason: "CAPACITY_SPLIT_ON_TABLE",
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
      {caption: "Below Safety Stock", field: null, format: "count",
       unavailableReason: "POSITION_COMPARISON_ON_ANOTHER_MEASURE",
       note: "Compared on Replenishment Planner"},
      {caption: "Excess Safety Stock", field: null, format: "count",
       unavailableReason: "POSITION_COMPARISON_ON_ANOTHER_MEASURE",
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
      {caption: "ERP Failures", field: null, format: "count",
       unavailableReason: "ERP_SHADOW_ONLY",
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
    // reflow, and says what is missing rather than showing a zero.
    return (
      <div className="kpi" data-kpi={spec.caption} data-unavailable="true">
        <small>{spec.caption}</small>
        <div className="value unavailable">{UNAVAILABLE}</div>
        {spec.note && <div className="demo-note">{spec.note}</div>}
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
      {table.heading && (
        <div className="card-head">
          <h3>{table.heading}</h3>
          <span className="link-button" aria-hidden="true">
            {slice.pagination
              ? `${rows.length} of ${slice.pagination.total.toLocaleString("en-US")}`
              : `${rows.length}`}
          </span>
        </div>
      )}
      <div className="table-scroll">
        <table className="table">
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
            <div style={{display: "grid", gap: 14, marginTop: 14}}>
              {screen.tables.map((table, index) => (
                <DataCard key={index} table={table} slice={slice.data} />
              ))}
            </div>
          )}
        </>
      ) : null}
    </>
  );
}
