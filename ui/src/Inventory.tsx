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

import {useEffect, useRef, useState, type ReactNode} from "react";
import {useQuery} from "@tanstack/react-query";
import {loadInventorySlice, type InventorySlice} from "./api";
import {DIRECT_EXPORT_LIMIT, downloadDirectExport} from "./directExport";
import {formatAggregateMoneyMinor} from "./currencyFormat";
import {categoryNameFromLabel} from "./dimensionLabels";
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

interface InventoryExportSpec {
  readonly exportId: string;
  readonly card?: string;
}

const INVENTORY_EXPORTS: Partial<Record<InventoryPageId, InventoryExportSpec>> = {
  inventoryOverview: {exportId: "inventoryExportBtn", card: "locations"},
  storeInventory: {exportId: "storeInventoryExportBtn", card: "locations"},
  warehouseInventory: {exportId: "warehouseExportBtn", card: "warehouses"},
  inventoryAgeing: {exportId: "ageingExportBtn"},
  inventoryTransfers: {exportId: "transferExportBtn"},
  inventoryValuation: {exportId: "valuationExportBtn", card: "categories"},
  expiryWaste: {exportId: "expiryExportBtn"},
  replenishmentPlanner: {exportId: "replenishmentExportBtn"},
  suggestedOrders: {exportId: "suggestedExportBtn"},
  supplierPlanning: {exportId: "supplierExportBtn"},
  safetyStock: {exportId: "safetyStockExportBtn"},
  allocationFulfillment: {exportId: "allocationExportBtn"},
  replenishmentExceptions: {exportId: "exceptionExportBtn"}
};

type InventoryActionDialogKind =
  | "inventory"
  | "replenishment"
  | "stock_owner"
  | "stock_action";

interface InventoryActionDialogSpec {
  readonly id: string;
  readonly title: string;
  readonly metric: string;
  readonly decision: string;
  readonly kind: InventoryActionDialogKind;
  readonly surfaceId?: string;
}

const INVENTORY_ACTION_DIALOGS: Partial<
  Record<InventoryPageId, Readonly<Record<string, InventoryActionDialogSpec>>>
> = {
  inventoryOverview: {
    "Inventory Action Center": {id: "inventoryActionCenterBtn", title: "Inventory Action Center", metric: "Value at Risk", decision: "Review enterprise actions", kind: "inventory"},
    "Store Drilldown": {id: "inventoryStoreDrilldownBtn", title: "Store Inventory Drilldown", metric: "Stores at Risk", decision: "Open store actions", kind: "inventory"},
    "Warehouse Drilldown": {id: "inventoryWarehouseDrilldownBtn", title: "Warehouse Inventory Drilldown", metric: "Blocked Inventory", decision: "Release or reallocate", kind: "inventory"},
    "Run Inventory Scenario": {id: "inventoryScenarioBtn", title: "Inventory Scenario", metric: "Working Capital Opportunity", decision: "Simulate inventory reduction", kind: "inventory"}
  },
  storeInventory: {
    "Create Store Action": {id: "storeInventoryActionBtn", title: "Create Store Action", metric: "Lost Sales Exposure", decision: "Assign store action", kind: "inventory"},
    "Create Transfer": {id: "storeInventoryTransferBtn", title: "Create Store Transfer", metric: "Transfer Opportunity", decision: "Create transfer", kind: "inventory"}
  },
  warehouseInventory: {
    "Release Blocked Stock": {id: "warehouseReleaseBtn", title: "Release Blocked Stock", metric: "Blocked Inventory", decision: "Release stock", kind: "inventory"},
    "Review Delayed Receipts": {id: "warehouseReceiptBtn", title: "Review Delayed Receipts", metric: "Delayed Receipts", decision: "Expedite receipts", kind: "inventory"}
  },
  inventoryAgeing: {
    "Create Markdown Plan": {id: "ageingMarkdownBtn", title: "Create Markdown Plan", metric: "90+ Day Inventory", decision: "Apply controlled markdown", kind: "inventory"},
    "Create Transfer Plan": {id: "ageingTransferBtn", title: "Create Ageing Transfer Plan", metric: "Transfer Opportunity", decision: "Rebalance inventory", kind: "inventory"}
  },
  inventoryTransfers: {
    "Create Transfer Request": {id: "createInventoryTransferBtn", title: "Create Transfer Request", metric: "Open Transfer Value", decision: "Create transfer", kind: "inventory"},
    "Optimize Transfers": {id: "optimizeTransferBtn", title: "Optimize Transfers", metric: "Expected Recovery", decision: "Run optimization", kind: "inventory"}
  },
  inventoryValuation: {
    "Run Valuation Scenario": {id: "valuationScenarioBtn", title: "Run Valuation Scenario", metric: "Net Realizable Value", decision: "Recalculate provisions", kind: "inventory"},
    "Reconcile with ERP": {id: "valuationReconcileBtn", title: "Reconcile with ERP", metric: "Inventory Variance", decision: "Start reconciliation", kind: "inventory"}
  },
  expiryWaste: {
    "Create Expiry Action": {id: "expiryActionBtn", title: "Create Expiry Action", metric: "Near-Expiry Inventory", decision: "Create expiry response", kind: "inventory"},
    "Create Waste Reduction Plan": {id: "wasteReductionBtn", title: "Create Waste Reduction Plan", metric: "Recovery Opportunity", decision: "Create recovery plan", kind: "inventory"}
  },
  replenishmentPlanner: {
    "Approve Selected Orders": {id: "approveReplenishmentBtn", title: "Approve Replenishment Orders", metric: "Suggested Value", decision: "Approve selected orders", kind: "replenishment"},
    "Create Transfer Requests": {id: "createTransferRequestsBtn", title: "Create Transfer Requests", metric: "Transfer Opportunity", decision: "Create optimized transfers", kind: "replenishment"},
    "Send to ERP": {id: "sendReplenishmentErpBtn", title: "Send to ERP", metric: "Approved Orders", decision: "Transmit approved orders", kind: "replenishment"},
    "Run Scenario": {id: "replenishmentScenarioBtn", title: "Replenishment Scenario", metric: "Working Capital Impact", decision: "Run service-level scenario", kind: "replenishment"},
    "Action Center": {id: "replenishmentActionCenterBtn", title: "Replenishment Action Center", metric: "Open Exceptions", decision: "Review priority actions", kind: "replenishment"}
  },
  suggestedOrders: {
    "Approve Orders": {id: "suggestedApproveBtn", title: "Approve Suggested Orders", metric: "Order Value", decision: "Approve order batch", kind: "replenishment"},
    "Modify Quantity": {id: "suggestedModifyBtn", title: "Modify Suggested Quantity", metric: "Suggested Orders", decision: "Adjust order quantity", kind: "replenishment"}
  },
  supplierPlanning: {
    "Request Capacity Confirmation": {id: "supplierCapacityBtn", title: "Supplier Capacity Confirmation", metric: "Unconfirmed Capacity", decision: "Request confirmation", kind: "replenishment"},
    "Create Expedite Request": {id: "supplierExpediteBtn", title: "Create Expedite Request", metric: "Revenue at Risk", decision: "Expedite order", kind: "replenishment"}
  },
  safetyStock: {
    "Recalculate Safety Stock": {id: "recalculateSafetyStockBtn", title: "Recalculate Safety Stock", metric: "Current Safety Stock", decision: "Recalculate policy", kind: "replenishment"},
    "Approve Policy": {id: "approveSafetyStockBtn", title: "Approve Safety Stock Policy", metric: "Policy Coverage", decision: "Approve policy", kind: "replenishment"}
  },
  allocationFulfillment: {
    "Optimize Allocation": {id: "optimizeAllocationBtn", title: "Optimize Allocation", metric: "Allocation Pool", decision: "Run optimization", kind: "replenishment"},
    "Release Allocation": {id: "releaseAllocationBtn", title: "Release Allocation", metric: "Fulfillment Rate", decision: "Release allocation", kind: "replenishment"}
  },
  replenishmentExceptions: {
    "Resolve Selected": {id: "resolveReplenishmentExceptionBtn", title: "Resolve Exceptions", metric: "Open Exceptions", decision: "Resolve selected", kind: "replenishment"},
    "Assign Owner": {id: "assignReplenishmentExceptionBtn", title: "Assign Exceptions", metric: "High Priority", decision: "Assign owner", kind: "replenishment"}
  },
  stockHealth: {
    "Assign Owner": {id: "stockHealthAssignOwnerBtn", title: "Assign Owner", metric: "Owner", decision: "Assign owner", kind: "stock_owner", surfaceId: "stock-health.assign-owner"},
    "Create Action": {id: "stockHealthCreateActionBtn", title: "Create Stock Action", metric: "Action", decision: "Create action", kind: "stock_action", surfaceId: "stock-health.create-action"}
  }
};

interface InventorySelection {
  readonly selected: ReadonlySet<string>;
  readonly onToggle: (rowId: string) => void;
  readonly onToggleAll: () => void;
}

/** How one KPI tile is filled from the live `summary` aggregate. */
interface KpiSpec {
  /** Caption, matching the reference's `<small>` exactly. */
  readonly caption: string;
  /** Field in the endpoint's SQL summary, or null when nothing measures it. */
  readonly field: string | null;
  readonly format: "units" | "money" | "count" | "percent" | "days" | "turns";
  /** A second summary field forming the denominator of a percentage. */
  readonly of?: string;
  /**
   * A companion figure on the reference's delta line, in its own words --
   * "4,286 recommendations" beside a money total. Distinct from `of`, which
   * renders a SHARE of a denominator; this is a second measure entirely.
   */
  readonly delta?: {
    readonly field: string;
    readonly format: KpiSpec["format"];
    readonly suffix: string;
  };
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
  readonly format?:
    | "units" | "money" | "count" | "percent" | "days" | "turns" | "text";
  /** Renders a colour-coded badge from the field's value. */
  readonly badge?: boolean;
  /** Interval-derived: withheld together when `intervalAvailable` is false. */
  readonly gated?: boolean;
  /**
   * Why this column has no value, keyed into REASON_TEXT. Required reading for
   * any column the reference shows and the platform cannot fill: without it the
   * cell renders the bare words with an empty tooltip, which is the single thing
   * a demo reader asks about first. Five pages were shipping 20 bare cells each.
   */
  readonly unavailableReason?: string;
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

/**
 * A card the reference draws at a grain that is NOT the projection's row grain.
 *
 * "Inventory Risk by Category" has one row per category. "Location-Level
 * Inventory Performance" has one row per LOCATION, as its title says. "Ageing
 * Inventory" has one row per age bucket with a SKU COUNT in it. Rendering the
 * projection's rows under those headers put a location id under a Category
 * header and a SKU under a Location header -- not a layout slip, a different
 * table. The read model groups them in SQL; `card` names which group to read.
 */
interface GroupedSpec {
  readonly heading: string | null;
  /** Key in the slice's `cards` map. */
  readonly card: string;
  readonly columns: readonly ColumnSpec[];
}

interface ScreenSpec {
  readonly title: string;
  readonly subtitle: string;
  readonly endpoint: string;
  readonly kpis: readonly KpiSpec[];
  readonly tables: readonly TableSpec[];
  /** Reference label -> live aggregate, for breakdown, donut and alert cards. */
  readonly breakdown?: readonly BreakdownRow[];
  /** Grouped cards, consumed in the order the reference's `rows` cards appear. */
  readonly grouped?: readonly GroupedSpec[];
}

const UNAVAILABLE = "Not available";
const WITHHELD = "Manual judgment required";

/**
 * Why a measure is absent and what would make it appear. Every unavailable
 * element carries one: "Not available" on its own tells a retailer nothing, and
 * the first question in a demo is always whether the gap is permanent.
 */
export const AVAILABILITY: Record<string, {why: string; when: string}> = {
  // Used by a KPI as well as a column now, so it needs a cause and a condition
  // and not only the column-level sentence.
  FILL_RATE_NEEDS_REPLAY: {
    why: "a fulfilment rate is served units over demanded units within one period, which only the weekly replay produces; the allocation projection's requested_units is trailing sales over 91 days, so dividing by it compares today's stock with a quarter of demand",
    when: "when a replay reproduces and its policy comparison is accepted, publishing fillRate per market and cohort"
  },
  REPLAY_UNAVAILABLE: {
    // The publisher distinguishes two causes -- REPLAY_ORACLE_DID_NOT_REPRODUCE
    // and REPLAY_NO_CANDIDATE_IMPROVEMENT -- but that code rides on the
    // capability in the run manifest and does not reach the slice, whose
    // dataMode is pinned to "live". So this text has to hold for both, and the
    // previous wording did not: it asserted the replay reproduces, which is true
    // of the loose source data and false once the network is tight enough for
    // stores to run short. Naming the weaker of the two conditions keeps it true
    // either way rather than claiming a reproduction that may not hold.
    why: "the weekly replay has not published an accepted policy comparison for this bundle: either the reconstruction did not reproduce observed stock inside its frozen tolerance, or it did and no candidate strictly beat the incumbent, which the acceptance rule frozen before scoring treats as a failure",
    when: "when the reconstruction reproduces observed stock and a candidate strictly improves on the incumbent"
  },
  // NRV_UNAVAILABLE was removed: NRV and provisions are now derived and served
  // (Bucket A #15/#20), so nothing withholds on this code any more. A declared
  // availability entry no element reaches is a claim about the platform that no
  // screen makes -- which is what the parity test enforces. The REASON_TEXT
  // fallback for the code is deliberately kept: that map is a defensive lookup
  // with a default, not a governed claim.
  // Two distinct absences, not one. The waste artifact's `exposure_minor` is
  // NULL on every row -- so there is no published figure to show -- AND what
  // could be recovered from near-expiry stock needs a recovery price the
  // platform does not hold. Filling it from acquisition cost would answer
  // "what did this cost us" under a caption asking "what can we get back".
  RECOVERY_VALUE_NOT_PUBLISHED: {
    why: "the waste artifact publishes an exposure column that is empty on every row, and a recovery figure needs an expected recovery price rather than the acquisition cost the platform holds",
    when: "when the waste engine populates exposure, or a pricing-floor policy supplies a recovery price for expiring stock"
  },
  // Not a costing gap. The figure is computable and was measured: 1,873 ageing
  // cells are marked markdown_candidate, 1,749 of them carry a SKU-grain cost,
  // and the depth is published per row -- Rs 6.49 Cr nominal. What is missing is
  // the APPROVAL. The earlier text said the markdown policy "IS approved and IS
  // applied", which inverted the one fact that governs this tile: markdownPct is
  // the ageing ladder's recommended depth, not an approved provisioning rate,
  // and the resolved policy withholds provisions explicitly.
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
  // Sharpened after reading the engine rather than the policy text. The resolved
  // policy's `safetyStock.formula` describes a demand-variance plus lead-time-
  // variance expression, and the implementation does not compute either term: the
  // buffer is the root-sum-square of the forecast's weekly P90-P50 spreads over
  // the protection window, scaled by the service-level z against z(0.90). So
  // lead-time variability has no contribution to report -- lead time only sets
  // how many weeks of spread accumulate -- and promotion/seasonality is absent
  // from the expression entirely.
  // Was the reason for the demand and lead-time drivers too, until migration 0020
  // published both. What remains withheld is a driver the policy's formula does not
  // contain at all, which is a different claim and needed its own reason.
  DRIVER_COMPONENTS_NOT_PUBLISHED: {
    why: "the buffer is sized from the forecast interval and lead-time variability, and promotion or seasonality uplift is not a term in the policy's safety-stock formula, so no such contribution exists to report",
    when: "when a policy revision adds an uplift term and the engine emits it per cell"
  },
};

/**
 * What a share is a share OF, in the reader's words. Read from the denominator
 * field rather than assumed, so a ratio can never be captioned against a base
 * it was not computed over.
 */
const SHARE_BASIS: Record<string, string> = {
  onHandUnits: "of on-hand",
  healthCells: "of assessed cells",
  healthLocations: "of locations",
  comparedCells: "of cells compared",
  cellsToOrder: "of cells to order",
  // The same base reached through the `order` companion prefix, so the Planner's
  // share reads "of cells to order" rather than falling back to a generic total.
  moqAttemptedCells: "of orders attempted",
  cells: "of cells",
  requestedUnits: "of requested units",
  rows: "of rows"
};

function shareBasis(field: string | undefined): string {
  return (field && SHARE_BASIS[field]) || "of the scoped total";
}

function availabilityNote(reason: string | undefined): string | null {
  if (!reason) return null;
  const entry = AVAILABILITY[reason];
  if (!entry) return null;
  return `Not available because ${entry.why}. Available ${entry.when}.`;
}

/** Reasons a value is absent, in the words a retailer needs, not a code. */
export const REASON_TEXT: Record<string, string> = {
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
  NRV_UNAVAILABLE:
    "the resolved policy declares NRV and provisions unavailable pending an approved markdown policy, and NRV needs an expected recovery price the platform does not hold",
  // Not a withheld interval -- the forecast was there and the order solver still
  // refused, because the supplier's minimum and the cover cap cannot both hold.
  // The engine refuses rather than silently overriding one of them.
  MOQ_EXCEEDS_MAX_COVER:
    "the supplier's minimum order exceeds the cover cap, so no quantity satisfies both policies",
  // Column-level absences. Each names what the active bundle does or does not
  // publish -- checked against ARTIFACT_COLUMNS rather than guessed, because a
  // plausible-sounding wrong reason is worse than none.
  NO_RECEIPT_DATE_TO_AGE:
    "this cell's on-hand carries no recorded receipt date, and an age is published only for stock the source recorded arriving",
  AGEING_VALUE_NOT_PUBLISHED:
    "the ageing artifact publishes units per age bucket and no costed value, so a value here would be computed off-contract",
  RECOVERY_VALUE_NOT_PUBLISHED:
    "the waste artifact publishes an exposure column that is empty on every row, and what could be recovered from near-expiry stock needs a recovery price the platform does not hold",
  SERVICE_IMPACT_NEEDS_REPLAY:
    "a service-level delta is the difference between two policies measured over the same weeks, which only the weekly replay produces",
  INCUMBENT_BUFFER_NOT_PUBLISHED:
    "the engine publishes the buffer it recommends; the buffer currently in force belongs to the incumbent policy and is not carried, so there is nothing to compare it against",
  EXCEPTION_OWNER_NOT_PUBLISHED:
    "exceptions are published as evidence rows with no assignment and no raised timestamp, so neither an owner nor an age is carried",
  INTERNAL_NODE_HAS_NO_RISK_CLASS:
    "the risk engine classifies SUPPLIERS on on-time delivery, lead-time variability and confirmed capacity, and an internal warehouse publishes none of the three, so it carries no risk class of its own",
  FILL_RATE_NEEDS_REPLAY:
    "fill rate is served units over demanded units per period, which only the weekly replay produces, and the replay capability is not available on this bundle",
  PROVISION_PENDING_MARKDOWN_POLICY:
    "the resolved policy declares NRV and provisions unavailable pending an approved markdown policy; the marked cells and their costs are published, so only the approval is missing"
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

/**
 * Money in the reference's own notation: Indian crore/lakh for INR, M/K for USD.
 * Minor units in, market-local out. Nothing is converted here -- policy v2 forbids
 * a nominal sum across currencies, so a multi-currency slice is labelled rather
 * than added.
 */
function formatMoney(minor: number, currency: string): string {
  return formatAggregateMoneyMinor(minor, currency);
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
    case "turns":
      return `${numeric.toFixed(1)}x`;
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
    // Every one of these is rupees in the reference. They rendered unit counts
    // until the SKU dimension published a cost to multiply by.
    kpis: [
      {caption: "On-Hand Inventory", field: "onHandValueMinor", format: "money",
       note: "Accepted unit cost times units on hand"},
      {caption: "Available to Promise", field: "atpValueMinor", format: "money",
       of: "onHandValueMinor", note: "After committed, reserved and damaged"},
      // The reference's delta is "2,420 shipments". A shipment COUNT is not
      // derivable -- the projection carries in-transit units per cell and no
      // shipment identity -- so the delta names what is counted: cells with stock
      // inbound. Borrowing the word "shipments" for a cell count would be the
      // one thing the parity rules forbid.
      {caption: "Inventory in Transit", field: "inTransitValueMinor",
       format: "money",
       delta: {field: "inTransitCells", format: "count", suffix: "cells inbound"},
       note: "Received against a declared lane"},
      // Rupees and a share of on-hand value, as the reference shows it. The
      // scope is the reference's own note: everything the health engine did not
      // class healthy -- overstock, ageing, expiry.
      {caption: "Inventory at Risk", field: "atRiskValueMinor", format: "money",
       of: "onHandValueMinor",
       note: "Overstock, ageing and expiry, valued at accepted unit cost"},
      // Turn is a year over days of supply, and days of supply is on-hand over
      // daily demand. Both became computable once trailing demand was published.
      {caption: "Stock Turn", field: "stockTurn", format: "turns",
       note: "Last 91 days of customer demand over enterprise on-hand, annualised"}
    ],
    breakdown: [
      // "Inventory Position" -- rupees and a share, exactly as the reference.
      {label: "Store inventory", field: "storeValueMinor", format: "money",
       of: "onHandValueMinor"},
      {label: "Warehouse inventory", field: "dcValueMinor", format: "money",
       of: "onHandValueMinor"},
      {label: "In transit", field: "inTransitValueMinor", format: "money",
       of: "onHandValueMinor"},
      {label: "Reserved stock", field: "reservedValueMinor", format: "money",
       of: "onHandValueMinor"},
      {label: "Damaged / blocked", field: "damagedValueMinor", format: "money",
       of: "onHandValueMinor"},
      // "Inventory by Health" donut. Four slices that partition the population.
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
    // The three cards the reference draws at their own grain.
    grouped: [
      {heading: "Ageing Inventory", card: "buckets", columns: [
        {header: "Age Bucket", field: "ageBucket"},
        {header: "SKUs", field: "skus", format: "count"},
        {header: "Inventory Value", field: "valueMinor", format: "money"},
        {header: "Sell-through", field: "sellThroughPct", format: "percent"},
        {header: "Recommended Action", field: "recommendedAction"}
      ]},
      {heading: "Inventory Risk by Category", card: "categories", columns: [
        {header: "Category", field: "categoryLabel"},
        {header: "Value", field: "valueMinor", format: "money"},
        {header: "Days of Supply", field: "daysOfSupply", format: "days"},
        {header: "Risk", field: "riskClass", badge: true},
        {header: "Action", field: "riskAction"}
      ]},
      {heading: "Location-Level Inventory Performance", card: "locations",
       columns: [
        {header: "Location", field: "locationName"},
        {header: "Type", field: "locationType", badge: true},
        {header: "Inventory Value", field: "valueMinor", format: "money"},
        {header: "Availability", field: "availabilityPct", format: "percent"},
        {header: "Days of Supply", field: "daysOfSupply", format: "days"},
        {header: "Stock-out Risk", field: "stockoutRisk", badge: true},
        {header: "Overstock", field: "overstockPct", format: "percent"},
        {header: "Priority Action", field: "priorityAction"}
      ]}
    ],
    tables: []
  },
  storeInventory: {
    title: "Store Inventory",
    subtitle: "Store-level availability, overstock, understock and transfer opportunities",
    endpoint: "/api/v1/inventory/stores",
    kpis: [
      // The SAME measure the overview's "Inventory Position" row shows, so the two
      // screens agree. It used to read the valuation artifact, which is a governed
      // finance figure at category grain that withholds any row without an accepted
      // cost -- 68 of 326 here -- so this tile said Rs 14.79L where the overview
      // said Rs 17.60L for what the caption calls the same thing. Valuation stays
      // the source for the Inventory Valuation page, where the withholding is the
      // point.
      {caption: "Store Inventory Value", field: "onHandValueMinor",
       format: "money",
       note: "Gross value of stock held at store locations"},
      // In-stock rate over the assorted range, not ATP over on-hand: the latter
      // is 1 by construction at a store and read 100% for every store.
      {caption: "On-Shelf Availability", field: "inStockAssortedCells",
       format: "percent", of: "assortedCells",
       note: "Assorted SKUs available to sell"},
      {caption: "Stores at Risk", field: "healthAtRiskStores", format: "count",
       of: "healthStores",
       note: "Stores holding at least one over- or understocked cell"},
      {caption: "Transfer Opportunity", field: "transferTransferValueMinor",
       format: "money",
       note: "Value of the stock the optimizer would move between locations"},
      {caption: "Lost Sales Exposure", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    // The heatmap is one row per STORE, not per SKU: Availability, DoS,
    // Overstock and Understock are all shares of a store's own cells, and the
    // Action is what to do about that store.
    grouped: [
      {heading: "Store Inventory Heatmap", card: "locations", columns: [
        {header: "Store", field: "locationName"},
        {header: "Availability", field: "availabilityPct", format: "percent"},
        {header: "DoS", field: "daysOfSupply", format: "days"},
        {header: "Overstock", field: "overstockPct", format: "percent"},
        {header: "Understock", field: "understockPct", format: "percent"},
        {header: "Action", field: "priorityAction"}
      ]}
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
    tables: []
  },
  warehouseInventory: {
    title: "Warehouse Inventory",
    subtitle: "DC position, utilization, receipts and fill",
    endpoint: "/api/v1/inventory/warehouses",
    kpis: [
      {caption: "Warehouse Inventory", field: "onHandValueMinor", format: "money",
       note: "DC-grain units on hand"},
      {caption: "Inbound in Transit", field: "inTransitValueMinor", format: "money",
       note: "Received against a declared lane"},
      {caption: "Blocked Inventory", field: "damagedValueMinor", format: "money",
       note: "Damaged and blocked buckets"},
      {caption: "Dock-to-Stock Time", field: null, format: "days",
       unavailableReason: "DOCK_TO_STOCK_NOT_INSTRUMENTED",
       note: "Needs receipt-to-putaway timestamps"},
      {caption: "Warehouse Fill Rate", field: "warehouseFillRate", format: "percent",
       note: "Served units ÷ demand · trailing 91 days"}
    ],
    // The reference's table is one row per WAREHOUSE -- three of them -- with
    // money in Inventory Value and Blocked Stock. This was the positions
    // projection at its own market x location x SKU grain, so a SKU sat under a
    // Warehouse header and both money columns printed unit counts. Which is why
    // this screen has no ungrouped table: the warehouse roll-up IS the card.
    tables: [],
    grouped: [
      {heading: null, card: "warehouses", columns: [
        {header: "Warehouse", field: "locationName"},
        {header: "Inventory Value", field: "valueMinor", format: "money"},
        {header: "Capacity Utilization", field: "capacityUtilization",
         format: "percent"},
        {header: "Fill Rate", field: "fillRate", format: "percent"},
        {header: "Blocked Stock", field: "blockedValueMinor", format: "money"},
        // Receipts that arrived late, from the published shipment lifecycle.
        {header: "Delayed Receipts", field: "delayedReceipts", format: "count"},
        {header: "Action", field: "warehouseAction"}
      ]}
    ]
  },
  inventoryAgeing: {
    title: "Inventory Ageing",
    subtitle: "Age buckets and the deterministic action ladder",
    endpoint: "/api/v1/inventory/ageing",
    kpis: [
      // Share of the AGED VALUE, not of the unit count: both tiles are money, and
      // dividing paise by units rendered "56006431.5% of on-hand" beside them.
      {caption: "60+ Day Inventory", field: "value60PlusMinor", format: "money",
       of: "ageingValueMinor",
       note: "Cumulative across the 60-90, 90-180 and 180-plus buckets"},
      {caption: "90+ Day Inventory", field: "value90PlusMinor", format: "money",
       of: "ageingValueMinor",
       note: "Cumulative across the 90-180 and 180-plus buckets"},
      {caption: "Dead Stock", field: "deadStockValueMinor", format: "money",
       note: "Units in residual-only cells"},
      {caption: "Markdown Opportunity", field: "markdownValueMinor", format: "money",
       note: "Cells the action ladder marks for markdown"},
      {caption: "Transfer Opportunity", field: "transferTransferValueMinor",
       format: "money",
       note: "Value of the stock the optimizer would move between locations"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "SKU / Product", field: "productName"},
        {header: "Category", field: "categoryLabel"},
        {header: "Age", field: "ageBucket"},
        {header: "Units", field: "onHandUnits", format: "units"},
        {header: "Value", field: "valueMinor", format: "money"},
        {header: "Sell-through", field: "sellThroughPct", format: "percent"},
        // `action` is the engine's own code -- `markdown_candidate`. The read
        // model composes the reference's sentence, markdown depth included.
        {header: "Recommended Action", field: "actionLabel"},
        {header: "Priority", field: "ageingPriority", badge: true}
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
      // Value is units at cost. Expected BENEFIT is the projected recovery, and
      // the reference shows them as different columns and different KPIs.
      {caption: "Transfer Value", field: "transferValueMinor", format: "money",
       note: "Market-local cost value of the units moved"},
      // The grid's own Expected Benefit column reads this per row, so withholding
      // the total told a reader the page could not add up what it was showing.
      {caption: "Expected Lost-Sales Recovery", field: "expectedBenefitMinor",
       format: "money", note: "Lost-sales recovery the optimizer projects"},
      {caption: "Average Transfer Time", field: "meanTransitDays", format: "days",
       note: "Per-lane transit days are in the table below"},
      {caption: "Transfer Acceptance", field: null, format: "percent",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED",
       note: "Recommendations are read-only in this release"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "SKU", field: "productName"},
        {header: "From Location", field: "fromLocationName"},
        {header: "To Location", field: "toLocationName"},
        {header: "Available Qty", field: "availableUnits", format: "units"},
        {header: "Suggested Qty", field: "units", format: "units"},
        {header: "Value", field: "transferValueMinor", format: "money"},
        {header: "Expected Benefit", field: "expectedBenefitMinor", format: "money"},
        {header: "Status", field: "transferStatus", badge: true}
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
      {caption: "Net Realizable Value", field: "nrvMinor", format: "money",
       note: "Gross value less markdown and obsolescence provisions"},
      {caption: "Markdown Provision", field: "provisionMarkdownMinor", format: "money",
       note: "Markdown-candidate cells at SKU cost times the recommended depth"},
      {caption: "Obsolescence Provision", field: "provisionObsolescenceMinor", format: "money",
       note: "Residual/dead-stock cells fully provisioned at SKU cost"},
      {caption: "Inventory Variance", field: "varianceValueMinor", format: "money",
       note: "Absolute ERP-versus-WMS discrepancy"}
    ],
    breakdown: [
      // "Financial Control Exceptions".
      // Money, as the reference's badge shows it -- Rs 0.18 Cr. The unit count is
      // the same variance unpriced, and a finance control reads in currency.
      {label: "ERP vs WMS variance", field: "varianceValueMinor", format: "money"},
      {label: "Unposted markdown provision", field: "provisionMarkdownMinor", format: "money"},
      {label: "Negative inventory value", field: "negativeValueRows",
       format: "count", of: "rows"},
      {label: "Cost missing", field: "unvaluedRows", format: "count", of: "rows"}
    ],
    // One row per CATEGORY, as the heading says and the reference shows -- four
    // rows, Footwear through Beauty. This read the valuation projection at its
    // own market x location x category grain, so "Footwear" appeared once per
    // location down 326 rows and no row was the category total the header
    // promised. The card the endpoint already serves is that roll-up.
    tables: [],
    grouped: [
      {heading: "Valuation by Category", card: "categories", columns: [
        {header: "Category", field: "categoryLabel"},
        {header: "Gross Value", field: "valueMinor", format: "money"},
        {header: "NRV", field: "nrvMinor", format: "money"},
        {header: "Provision", field: "provisionMinor", format: "money"},
        {header: "Variance", field: "varianceValueMinor", format: "money"}
      ]}
    ]
  },
  expiryWaste: {
    title: "Expiry & Waste",
    subtitle: "Expiry-window exposure and waste actuals",
    endpoint: "/api/v1/inventory/expiry-waste",
    kpis: [
      {caption: "Near-Expiry Inventory", field: "nearExpiryValueMinor", format: "money",
       note: "Units expiring inside the policy window"},
      {caption: "Waste · Last 91 Days", field: "wasteValueMinor", format: "money",
       note: "Realised write-offs from the exact 91-day trailing window"},
      {caption: "Waste Reduction", field: "wasteReductionPct", format: "percent",
       unavailableReason: "PRIOR_PERIOD_NOT_COMPARED",
       note: "Versus the prior 91-day window"},
      {caption: "Products at Risk", field: "cells", format: "count",
       note: "Cells with expiry or waste evidence"},
      // exposure_minor is published NULL on every row of this artifact, so a summed
      // money aggregate reported a confident Rs 0.00 for something never measured.
      {caption: "Recovery Opportunity", field: null, format: "money",
       unavailableReason: "RECOVERY_VALUE_NOT_PUBLISHED",
       note: "Cost value of units expiring in the window"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Product", field: "productName"},
        {header: "Location", field: "locationName"},
        {header: "Expiry Window", field: "expiryWindow"},
        // Forward exposure and realised loss are independent facts. A cell can
        // carry both; separate columns prevent a status-priority branch from
        // hiding either quantity or valuing realised waste as zero.
        {header: "Near-Expiry Units", field: "expiringUnits", format: "units"},
        {header: "Near-Expiry Value", field: "nearExpiryValueMinor", format: "money"},
        {header: "Waste Units · 91 Days", field: "wasteUnits", format: "units"},
        {header: "Waste Value · 91 Days", field: "wasteValueMinor", format: "money"},
        {header: "Sell-through", field: "sellThroughPct", format: "percent"},
        {header: "Recommended Action", field: "wasteAction"},
        {header: "Priority", field: "wastePriority", badge: true}
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
        {header: "SKU", field: "productName"},
        {header: "Store", field: "locationName"},
        {header: "Days of Supply", field: "coverDays", format: "days"},
        {header: "Ageing", field: "ageingBand",
         unavailableReason: "NO_RECEIPT_DATE_TO_AGE"},
        {header: "Health", field: "healthClass", badge: true},
        {header: "Financial Exposure", field: "exposureMinor", format: "money"},
        {header: "Recommended Action", field: "recommendedAction"},
        {header: "Priority", field: "priority", badge: true}
      ]}
    ]
  },
  replenishmentPlanner: {
    title: "Replenishment Planner",
    subtitle: "Suggested orders under lane, term, capacity and budget guards",
    endpoint: "/api/v1/replenishment/planner",
    kpis: [
      // MONEY in the reference -- Rs 18.4 Cr. It carried a unit count and a note
      // explaining that a recommendation has no costed line, which stopped being
      // true when the dimension published a cost: this is the same figure the
      // grid below now values per row.
      // The reference pairs this money total with the COUNT behind it:
      // "Rs 18.4 Cr / 4,286 recommendations".
      {caption: "Suggested Replenishment Value", field: "orderValueMinor",
       format: "money",
       delta: {field: "cellsToOrder", format: "count", suffix: "recommendations"},
       note: "Recommended units at the destination's cost"},
      // Revenue Protected needs a selling price the replay does not publish (it
      // measures units, not money), so it stays a governed absence even when the
      // replay is accepted -- unlike Working Capital, which values a held-unit
      // reduction at cost the dimension does carry.
      {caption: "Revenue Protected", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"},
      // Real figures once the weekly replay accepts the candidate policy; a
      // governed absence while it does not (the field resolves to null).
      {caption: "Working Capital Impact", field: "workingCapitalImpactMinor",
       format: "money", unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Held-unit reduction valued at cost, vs the incumbent policy"},
      {caption: "Projected Service Level", field: "projectedServiceLevelPct",
       format: "percent", unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Candidate policy fill rate on the holdout cohort"},
      // The reference's delta here is "Rs 1.4 Cr at risk", and that figure is NOT
      // available: demand-at-risk withholds its VALUE on exactly the cells whose
      // interval was withheld, so the exposure on an exception order is null by
      // construction rather than merely unpublished. The share of the assessed
      // network these represent is published, is the same order of information,
      // and is true.
      {caption: "Exception Orders", field: "withheldCells", format: "count",
       of: "cells", note: "Cells withheld with a governed reason"}
    ],
    breakdown: [
      // Order mix, by where the recommendation would be sourced from.
      {label: "Supplier purchase orders", field: "fromSupplier",
       format: "count", of: "cellsToOrder"},
      {label: "Warehouse transfers", field: "fromWarehouse", format: "count",
       of: "cellsToOrder"},
      {label: "Inter-store transfers", field: "fromStore", format: "count",
       of: "cellsToOrder"},
      {label: "Expedited orders", field: null, format: "count",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED"},
      // Benefit. Every one of these is a candidate-versus-incumbent claim, so
      // each resolves to a real figure only when the replay accepted the
      // candidate AND that specific benefit is positive; otherwise governed.
      {label: "Lost-sales reduction", field: "lostSalesReductionUnits",
       format: "units", unavailableReason: "REPLAY_UNAVAILABLE"},
      {label: "Stock-out reduction", field: "stockoutReductionCount",
       format: "count", unavailableReason: "REPLAY_UNAVAILABLE"},
      {label: "Inventory turn improvement", field: "inventoryTurnImprovementPct",
       format: "percent", unavailableReason: "REPLAY_UNAVAILABLE"},
      // Transfer savings is not a replay output (no transfer-cost model), so it
      // stays governed regardless of acceptance.
      {label: "Transfer savings", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE"},
      // Approval queue. Read-only release, so nothing is pending anything.
      {label: "Pending planner review", field: null, format: "count",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED"},
      {label: "Pending supply-chain approval", field: null, format: "count",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED"},
      {label: "Pending finance review", field: null, format: "count",
       unavailableReason: "ACCEPTANCE_NOT_INSTRUMENTED"},
      {label: "ERP transmission failed", field: "erpFailures", format: "count"},
      // Compliance.
      {label: "Approved forecast coverage", field: "assessedCells",
       format: "count", of: "cells"},
      {label: "MOQ / pack-size compliance", field: "moqCompliantCells",
       format: "count", of: "moqAttemptedCells"},
      // Measured against the ceiling the market policy declares and the run now
      // publishes, consumed in the plan's own priority order.
      {label: "Orders within budget", field: "withinBudgetCells",
       format: "count", of: "cellsToOrder"},
      {label: "Supplier capacity confirmed",
       field: "supplierMeanCapacityConfirmedPct", format: "percent"}
    ],
    // The reference's second rows card, which had no spec at all -- so the
    // recommendations grid was rendered into its slot and this card vanished.
    grouped: [
      {heading: "Lead-Time Risk", card: "leadTime", columns: [
        // The NAME of the node this plan draws on. Keyed on suppliers this
        // printed a UUID -- the source carries a supplier_id and no supplier
        // name at all -- and described suppliers none of the 720 orders use.
        {header: "Supplier / Source", field: "sourceName"},
        {header: "Lead Time", field: "leadTimeDays", format: "days"},
        {header: "Late Orders", field: "lateOrderRate", format: "percent"},
        {header: "Risk", field: null,
         unavailableReason: "INTERNAL_NODE_HAS_NO_RISK_CLASS"}
      ]}
    ],
    tables: [
      {heading: "Priority Replenishment Recommendations", columns: [
        {header: "select"},
        {header: "Priority", field: "replenishmentPriority", badge: true},
        {header: "SKU / Product", field: "productName"},
        {header: "Destination", field: "destinationName"},
        // On-hand at the node being replenished, so a planner can see what the
        // suggested quantity is being added to. Not gated: the holding is
        // published whether or not an interval was available to order against.
        {header: "Current Stock", field: "currentStockUnits", format: "units"},
        // Policy v2 defines order_up_to as reorder_point plus expected demand
        // over the review period, so the difference IS the published demand.
        {header: "Forecast Demand", field: "forecastDemandUnits",
         format: "units", gated: true},
        {header: "Safety Stock", field: "safetyStockUnits", format: "units",
         gated: true},
        {header: "Suggested Qty", field: "recommendedUnits", format: "units",
         gated: true},
        {header: "Source", field: "sourceName"},
        // The lead time the supply term resolved to, published by the run that
        // already computed it to size the protection period.
        {header: "Lead Time", field: "leadTimeDays", format: "days"},
        {header: "Expected Receipt", field: "expectedReceiptDate"},
        {header: "Order Value", field: "orderValueMinor", format: "money",
         gated: true},
        // Service Impact and Confidence were bound to order_up_to and the
        // reorder point -- two unit counts under a points-delta and a percentage.
        {header: "Service Impact", field: null,
         unavailableReason: "SERVICE_IMPACT_NEEDS_REPLAY"},
        // The forecast projection already publishes this derivation per series
        // and horizon, scoped to the version this bundle consumed.
        {header: "Confidence", field: "forecastConfidence", format: "percent"},
        {header: "Status", field: "erpStatusLabel", badge: true}
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
      {caption: "Order Value", field: "orderValueMinor", format: "money",
       note: "Recommended units at the destination's accepted cost"},
      {caption: "High Priority", field: "highPriorityCells", format: "count",
       of: "cellsToOrder",
       note: "Ordering into a destination that is stocked out"},
      {caption: "Within Budget", field: "withinBudgetCells", format: "count",
       of: "cellsToOrder", note: "Against the market's weekly ceiling"},
      {caption: "Expected Fill Rate", field: "projectedServiceLevelPct",
       format: "percent", unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Candidate policy fill rate on the holdout cohort"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Order", field: "productName"},
        // Type and Status were each showing the other's answer: Type read
        // erp_status ("Shadow (not sent)") and Status read a reason code.
        {header: "Type", field: "orderType", badge: true},
        {header: "Destination", field: "destinationName"},
        {header: "Source", field: "sourceName"},
        {header: "Items", field: "recommendedUnits", format: "units", gated: true},
        {header: "Value", field: "orderValueMinor", format: "money", gated: true},
        {header: "Need Date", field: "expectedReceiptDate"},
        // The forecast projection already publishes this derivation per series
        // and horizon, scoped to the version this bundle consumed.
        {header: "Confidence", field: "forecastConfidence", format: "percent"},
        {header: "Status", field: "erpStatusLabel", badge: true}
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
      // The SOURCE's open purchase orders, not ours: the position projection's
      // on_order bucket is inbound the ERP has already raised. The old reason
      // read this as "no purchase order exists yet", which is true of our own
      // shadow recommendations and not of the 645 cells with inbound on order.
      {caption: "Open PO Value", field: "positionOnOrderValueMinor",
       format: "money", note: "Inbound already on order, at accepted cost"},
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
        // The vendor master's own name. This printed a UUID because the
        // dimension landed and was never staged into canonical.
        {header: "Supplier", field: "supplierName"},
        // The scope this supplier serves. 239 of 280 serve more than one, so the
        // row also carries scopeCount and the cell is not read as exclusive.
        {header: "Category", field: "categoryLabel"},
        // Inbound still on order from this supplier, at the accepted cost for the
        // receiving cell. It was withheld because no inbound row named its vendor.
        {header: "Open PO Value", field: "openPoValueMinor", format: "money"},
        {header: "Capacity", field: "capacityConfirmedPct", format: "percent"},
        {header: "Lead Time", field: "leadTimeMeanDays", format: "days"},
        {header: "OTD", field: "otdRate", format: "percent"},
        {header: "Risk", field: "riskClass", badge: true},
        {header: "Action", field: "supplierAction"}
      ]}
    ]
  },
  safetyStock: {
    title: "Safety Stock",
    subtitle: "Policy segments from the hard-gated interval",
    endpoint: "/api/v1/replenishment/safety-stock",
    kpis: [
      // MONEY in the reference -- Rs 6.4 Cr -- and the segments table beside it
      // already valued the same buffer, so tile and table disagreed on units.
      {caption: "Safety Stock Value", field: "safetyStockValueMinor",
       format: "money", note: "The recommended buffer at accepted cost"},
      {caption: "Policy Coverage", field: "assessedCells", format: "count",
       of: "cells", note: "Cells with an available interval"},
      {caption: "Below Safety Stock", field: "belowSafetyCells", format: "count",
       of: "comparedCells",
       note: "Compared on Replenishment Planner"},
      {caption: "Excess Safety Stock", field: "excessSafetyCells", format: "count",
       of: "comparedCells",
       note: "Compared on Replenishment Planner"},
      {caption: "Projected Service Level", field: "projectedServiceLevelPct",
       format: "percent", unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Candidate policy fill rate on the holdout cohort"}
    ],
    breakdown: [
      // "Safety Stock Drivers", now with a source. Policy v2's formula names two
      // terms and the engine implemented only the first, so this was withheld for
      // want of an addend rather than a column. The two combine in quadrature, so
      // they deliberately do not sum to the buffer.
      {label: "Demand variability", field: "safetyStockDemandUnits",
       format: "count"},
      // Zero on every row of THIS network, and the reason is structural rather
      // than missing data: a cell has a buffer only if it has a forecast interval,
      // which only stores do, and measurable lead-time variability only if an
      // external supplier serves it, which only DCs have. The two never coincide.
      {label: "Lead-time variability", field: "safetyStockLeadTimeUnits",
       format: "count"},
      {label: "Service-level target", field: "meanServiceLevel",
       format: "percent"},
      {label: "Promotion / seasonality", field: null, format: "count",
       unavailableReason: "DRIVER_COMPONENTS_NOT_PUBLISHED"}
    ],
    // The reference's own six columns, kept as a ROWS table on purpose: this is
    // the page where a withheld interval is visible per row, and an aggregated
    // card has no interval to withhold on. What was wrong was the bindings --
    // "SKUs" printed one SKU IDENTIFIER under a count header, and Current and
    // Recommended Value were the SAME field, so the table showed one number
    // twice and called it a comparison.
    tables: [
      {heading: null, columns: [
        {header: "Policy Segment", field: "segmentLabel", badge: true},
        {header: "SKUs", field: "productName"},
        {header: "Service Target", field: "serviceLevel", format: "percent",
         gated: true},
        // The engine publishes the buffer it RECOMMENDS. The buffer in force is
        // the incumbent policy's and is not carried, so neither the current
        // value nor the impact delta built on it has anything to stand on.
        {header: "Current Value", field: null,
         unavailableReason: "INCUMBENT_BUFFER_NOT_PUBLISHED"},
        {header: "Recommended Value", field: "safetyStockValueMinor",
         format: "money", gated: true},
        {header: "Impact", field: null,
         unavailableReason: "INCUMBENT_BUFFER_NOT_PUBLISHED"}
      ]}
    ]
  },
  allocationFulfillment: {
    title: "Allocation & Fulfillment",
    subtitle: "Constrained channel allocation over one node ATP pool",
    endpoint: "/api/v1/replenishment/allocations",
    kpis: [
      // The pool is the ATP the optimizer had to distribute, in money as the
      // reference shows it -- not the units it managed to allocate out of it.
      // Withheld, and both candidates are why. Bound to allocatedUnits it was a
      // unit count under a money caption AND a duplicate of the Allocated column
      // beside it. Reached through positions it became Rs 204 Cr of ENTERPRISE
      // ATP across eight nodes, above rows whose own pools are hundreds of units
      // at the four stores that actually allocate. The per-cell pool is published
      // per row instead, where the node it belongs to is named.
      // Summed over DISTINCT allocation cells, so a node's stock counts once
      // however many channels compete for it, and only over the cells that
      // actually allocate rather than all eight nodes.
      {caption: "Available Allocation Pool", field: "poolPoolValueMinor",
       format: "money",
       delta: {field: "poolPoolCells", format: "count", suffix: "cells"},
       note: "Available to promise at the allocating cells"},
      // A COUNT of requests, as the reference's 2,486 is. Bound to
      // requestedUnits this read 790,745 -- the units inside them.
      {caption: "Store Requests", field: "rows", format: "count",
       note: "Channel requests in scope"},
      // Withheld, not computed. Bound to allocatedUnits under a percent format
      // this rendered 1744700.0%, and the obvious repair -- allocated over
      // requested -- is not a fulfilment rate either: requested_units is trailing
      // SALES over 91 days while allocated is what today's ATP covers, so the
      // ratio compares stock to a quarter of demand and reads 2.2%.
      {caption: "Fulfillment Rate", field: null, format: "percent",
       unavailableReason: "FILL_RATE_NEEDS_REPLAY",
       note: "Served over demanded per period is a replay output"},
      // Requests carrying an unmet balance. Summing shortfall_units inherits the
      // trailing-sales base and reads 773,298, which is not a queue of work.
      {caption: "Priority Shortfall", field: "shortfallRows", format: "count",
       of: "rows", note: "Requests with an unmet balance"},
      {caption: "Revenue Protected", field: null, format: "money",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Product", field: "productName"},
        // The pool is the ATP the optimizer had to distribute. This was bound to
        // allocatedUnits -- the same field as the Allocated column beside it --
        // so the page showed one number under two headers and no reader could
        // see how much was available in the first place.
        {header: "Available Pool", field: "availablePoolUnits", format: "units"},
        {header: "Store Demand", field: "requestedUnits", format: "units"},
        {header: "Allocated", field: "allocatedUnits", format: "units"},
        {header: "Shortfall", field: "shortfallUnits", format: "units"},
        // Rule, Priority and Status were all bound to channel_id or location_id.
        {header: "Allocation Rule", field: "allocationRule"},
        {header: "Priority", field: "allocationPriority", badge: true},
        {header: "Status", field: "allocationStatus", badge: true}
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
      {caption: "Budget Exceptions", field: "orderOverBudgetCells",
       format: "count", note: "Orders past their market's weekly ceiling"},
      // Exceptions whose cause is the supply side. This was bound to `classes`,
      // the number of DISTINCT exception classes -- a three-item taxonomy count
      // under a caption a planner reads as a workload. It is zero on this bundle:
      // the engine published forecast and interval gaps and one order-constraint
      // conflict, and no supply-side exception at all.
      {caption: "Supplier Exceptions", field: "supplierExceptions",
       format: "count", note: "Supply-side causes in scope"},
      {caption: "ERP Failures", field: "orderErpFailures", format: "count",
       note: "No send path exists in this release"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Exception", field: "exceptionLabel"},
        {header: "Order / SKU", field: "productName"},
        {header: "Business Impact", field: "evidence"},
        {header: "Owner", field: "owner",
         unavailableReason: "EXCEPTION_OWNER_NOT_PUBLISHED"},
        {header: "Age", field: null,
         unavailableReason: "EXCEPTION_OWNER_NOT_PUBLISHED"},
        {header: "Priority", field: "severity", badge: true},
        {header: "Recommended Resolution", field: "exceptionResolution"},
        {header: "Status", field: "exceptionStatus", badge: true}
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
/**
 * The currency the served rows are actually denominated in.
 *
 * Read from the aggregate the read model published, not guessed from the
 * market list -- `markets` names every market the BUNDLE covers, which is both
 * of them, while the request is scoped to one. Guessing from that list rendered
 * a rupee symbol over a figure the database had summed in dollars.
 */
function sliceCurrency(slice: InventorySlice): string {
  // The reporting currency the read model already converted every money figure
  // into, using the publication's approved FX. Not inferred from the market
  // list: `markets` names every market the BUNDLE covers, which is both of
  // them, and guessing from it put a rupee symbol over a dollar sum.
  if (slice.reportingCurrency) return slice.reportingCurrency;
  const declared = slice.summary?.currencyCode;
  if (typeof declared === "string" && declared.length === 3) return declared;
  return "INR";
}

/** A grouped card: one row per category, per location, per bucket, per segment. */
function GroupedCard({
  spec, slice
}: {spec: GroupedSpec; slice: InventorySlice}) {
  const currency = sliceCurrency(slice);
  const rows = (slice.cards?.[spec.card] ?? []) as Row[];
  return (
    <div className="card">
      {spec.heading && (
        <div className="card-head">
          <h3>{spec.heading}</h3>
          <span className="link-button" aria-hidden="true">
            {`${rows.length} ${rows.length === 1 ? "group" : "groups"}`}
          </span>
        </div>
      )}
      <div className="table-scroll">
        <table className="table" data-card-kind="grouped">
          <thead>
            <tr>
              {spec.columns.map((column) => (
                <th key={column.header}>{column.header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {spec.columns.map((column) => (
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
    // A measured field can still resolve to nothing for a given bundle (e.g. no
    // prior window to compare against). When it carries a governed reason, state
    // WHY and WHEN with the reason code -- same treatment as a field that nothing
    // measures -- rather than a bare "Not available".
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
        // The denominator names itself. Hardcoding "of on-hand" was right for
        // the position tiles it was written for and wrong everywhere it spread
        // to: "Stores at Risk 4 / 50.0% of on-hand" is four of eight LOCATIONS.
        <span className="delta up">
          {(share * 100).toFixed(1)}% {shareBasis(spec.of)}
        </span>
      )}
      {!spec.of && spec.delta && (() => {
        const companion = asNumber(summary?.[spec.delta.field]);
        if (companion === null) return null;
        return (
          <span className="delta up">
            {formatValue(companion, spec.delta.format, currency)}{" "}
            {spec.delta.suffix}
          </span>
        );
      })()}
      {spec.note && <div className="demo-note">{spec.note}</div>}
    </div>
  );
}

function Cell({
  column, row, currency, selection
}: {
  column: ColumnSpec;
  row: Row;
  currency: string;
  selection?: InventorySelection;
}) {
  if (column.header === "select") {
    const rowId = typeof row.rowId === "string" ? row.rowId : "";
    return (
      <td>
        <input
          type="checkbox"
          aria-label={`Select ${String(row.productName ?? "replenishment row")}`}
          checked={Boolean(rowId && selection?.selected.has(rowId))}
          disabled={!rowId || !selection}
          onChange={() => rowId && selection?.onToggle(rowId)}
        />
      </td>
    );
  }
  if (!column.field) {
    // The reference has a column here and the platform has no measure for it.
    // Rendering the header with a governed cell is the approved element-level
    // behaviour; dropping the column would silently change the approved layout.
    return <UnavailableCell reason={column.unavailableReason} />;
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
  if (column.field === "categoryLabel" && typeof value === "string") {
    return <td>{categoryNameFromLabel(value)}</td>;
  }
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
    // The column has a field and this row's value is absent. Not the same thing
    // as a column with no measure at all, but it owes the reader a reason just
    // the same -- Stock Health's Ageing is null on precisely the stock-out rows,
    // which have no receipt to age from.
    return <UnavailableCell reason={column.unavailableReason} />;
  }
  return <td>{rendered}</td>;
}

/**
 * One governed empty cell. Carries the reason as both a tooltip and an attribute
 * so a reader can hover it and a test can assert on it.
 */
function UnavailableCell({reason}: {reason?: string}) {
  return (
    <td
      className="cell-unavailable"
      data-unavailable="true"
      data-reason-code={reason || undefined}
      title={
        (reason && REASON_TEXT[reason]) ??
        "This value is not published by the active bundle."
      }
    >
      {UNAVAILABLE}
    </td>
  );
}

function DataCard({
  table, slice, selection
}: {table: TableSpec; slice: InventorySlice; selection?: InventorySelection}) {
  const currency = sliceCurrency(slice);
  const rows = slice.items as Row[];
  const selectable = table.columns.some((column) => column.header === "select");
  const visibleIds = rows.flatMap((row) =>
    typeof row.rowId === "string" ? [row.rowId] : []
  );
  const selectedVisible = visibleIds.filter((rowId) =>
    selection?.selected.has(rowId)
  ).length;
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
      <div className="table-scroll">
        <table className="table" data-card-kind="rows">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.header}>
                  {column.header === "select" ? (
                    <InventoryMasterCheckbox
                      checked={visibleIds.length > 0 && selectedVisible === visibleIds.length}
                      indeterminate={selectedVisible > 0 && selectedVisible < visibleIds.length}
                      disabled={!selectable || !selection || visibleIds.length === 0}
                      onChange={() => selection?.onToggleAll()}
                    />
                  ) : column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={typeof row.rowId === "string" ? row.rowId : index}
                data-partial={isWithheld(row) ? "true" : undefined}
              >
                {table.columns.map((column) => (
                  <Cell
                    key={column.header}
                    column={column}
                    row={row}
                    currency={currency}
                    selection={selection}
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

function InventoryMasterCheckbox({
  checked,
  indeterminate,
  disabled,
  onChange
}: {
  checked: boolean;
  indeterminate: boolean;
  disabled: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label="Select all visible replenishment rows"
      checked={checked}
      disabled={disabled}
      onChange={onChange}
    />
  );
}

/**
 * The action strip and filters, both from the reference. Controls are visible and
 * natively disabled with no mutation handler (P4-D9/P4-D11): the workflow belongs
 * to a later phase, and hiding the controls would misrepresent the product.
 */
function filterValues(
  caption: string,
  options: InventorySlice["filterOptions"]
): readonly string[] {
  if (!options) return [];
  if (caption.includes("Region")) return options.regions;
  if (caption.includes("Categor")) return options.categories.map(categoryNameFromLabel);
  if (caption.includes("Health")) {
    return options.healthStatuses.map((value) => ({
      healthy: "Healthy",
      understock: "Understock",
      overstock: "Overstock",
      stockout: "Out of Stock",
      dead: "Dead Stock"
    })[value] ?? value);
  }
  if (caption.includes("Location")) {
    return options.locationKinds.map((value) => ({
      store: "Stores",
      dc: "Warehouses",
      "3pl": "Warehouses (3PL)"
    })[value] ?? value);
  }
  return [];
}

function InventoryPreviewField({label, children}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="pricing-field">
      <label>
        <span>{label}</span>
        {children}
      </label>
    </div>
  );
}

function InventoryActionDialog({spec, returnFocus, onClose}: {
  spec: InventoryActionDialogSpec;
  returnFocus: HTMLElement | null;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = `inventory-dialog-${spec.id}`;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    titleRef.current?.focus();
    const container = containerRef.current;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !container) return;
      const controls = Array.from(container.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
      ));
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === titleRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === titleRef.current) {
        event.preventDefault();
        first.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocus?.focus();
    };
  }, [returnFocus]);

  const unavailableMetric = (
    <span className="cell-unavailable" title="A governed workflow summary is not published by the active inventory read model.">
      Not available
    </span>
  );
  const footerLabel = spec.kind.startsWith("stock_") ? "Save" : "Create Action";
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section
        ref={containerRef}
        className="modal pricing-modal inventory-preview-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={`modal.${spec.surfaceId ?? spec.id}.preview`}
      >
        <div className="modal-head">
          <div>
            <h3 ref={titleRef} id={titleId} tabIndex={-1}>{spec.title}</h3>
            <p>Read-only workflow preview</p>
          </div>
          <button className="modal-close" type="button" aria-label={`Close ${spec.title}`} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="callout compact-callout">
            <strong>Workflow unavailable</strong>
            <p>The operational workflow and governed identities are not configured. Exploring this dialog does not create a request or action.</p>
          </div>
          {spec.kind === "stock_owner" ? (
            <div className="pricing-form-grid two">
              <InventoryPreviewField label="Owner">
                <select className="filter" defaultValue="unavailable" disabled title="Governed user identities are unavailable.">
                  <option value="unavailable">Identity unavailable</option>
                </select>
              </InventoryPreviewField>
              <InventoryPreviewField label="Priority">
                <select className="filter" defaultValue="High">
                  <option>High</option><option>Medium</option><option>Low</option>
                </select>
              </InventoryPreviewField>
              <InventoryPreviewField label="Due Date">
                <input className="filter" type="date" readOnly aria-readonly="true" />
              </InventoryPreviewField>
            </div>
          ) : spec.kind === "stock_action" ? (
            <div className="pricing-form-grid two">
              <InventoryPreviewField label="Action">
                <select className="filter" defaultValue="Markdown">
                  <option>Markdown</option><option>Transfer</option><option>Replenish</option><option>Stop Replenishment</option>
                </select>
              </InventoryPreviewField>
              <InventoryPreviewField label="Approval Route">
                <select className="filter" defaultValue="Category Manager">
                  <option>Category Manager</option><option>Pricing Manager</option><option>Business Head</option>
                </select>
              </InventoryPreviewField>
            </div>
          ) : (
            <>
              <div className="simulation-metrics inventory-preview-summary">
                <div><small>{spec.metric}</small><strong>{unavailableMetric}</strong></div>
                <div><small>Priority</small><strong>{unavailableMetric}</strong></div>
                <div><small>{spec.kind === "inventory" ? "Decision" : "Action"}</small><strong>{spec.decision}</strong></div>
              </div>
              {spec.kind === "inventory" ? (
                <div className="pricing-form-grid two">
                  <InventoryPreviewField label="Owner">
                    <select className="filter" defaultValue="Inventory Manager">
                      <option>Inventory Manager</option><option>Supply Chain Lead</option><option>Category Manager</option><option>Finance Controller</option>
                    </select>
                  </InventoryPreviewField>
                  <InventoryPreviewField label="Action Note">
                    <textarea className="filter" readOnly aria-readonly="true" />
                  </InventoryPreviewField>
                </div>
              ) : (
                <InventoryPreviewField label="Comment">
                  <textarea className="filter" readOnly aria-readonly="true" />
                </InventoryPreviewField>
              )}
            </>
          )}
        </div>
        <div className="modal-foot">
          <button className="modal-action" type="button" disabled title="The operational workflow is not configured.">{footerLabel}</button>
          <button className="filter" type="button" onClick={onClose}>Cancel</button>
        </div>
      </section>
    </div>
  );
}

function ActionStrip({
  pageId,
  reference,
  options,
  exportSpec,
  exportDisabledReason,
  exporting,
  onExport,
  onPreview
}: {
  pageId: InventoryPageId;
  reference: ReferenceScreen;
  options?: InventorySlice["filterOptions"];
  exportSpec?: InventoryExportSpec;
  exportDisabledReason: string;
  exporting: boolean;
  onExport: () => void;
  onPreview: (spec: InventoryActionDialogSpec, trigger: HTMLElement) => void;
}) {
  return (
    <>
      <div
        className="inventory-action-strip"
        aria-label={`${reference.screenId} actions`}
      >
        {reference.actions.map((label, index) => {
          const isExport = Boolean(exportSpec && label.includes("Export"));
          const preview = INVENTORY_ACTION_DIALOGS[pageId]?.[label];
          const disabledReason = isExport
            ? exportDisabledReason
            : preview
              ? ""
              : "This governed workflow is not enabled";
          return (
            <button
              id={isExport ? exportSpec?.exportId : preview?.id}
              data-surface-id={preview?.surfaceId}
              data-testid={preview ? `trigger.${preview.surfaceId ?? preview.id}` : undefined}
              key={label}
              className={index === 0 ? "btn btn-primary" : "btn"}
              type="button"
              disabled={isExport ? Boolean(disabledReason) : !preview}
              aria-disabled={isExport ? Boolean(disabledReason) : !preview}
              title={isExport
                ? disabledReason || "Download the reviewed rows from the server"
                : preview
                  ? "This action does not create or change a workflow record."
                  : disabledReason}
              onClick={isExport
                ? onExport
                : preview
                  ? (event) => onPreview(preview, event.currentTarget)
                  : undefined}
            >
              {isExport && exporting ? "Exporting…" : label}
            </button>
          );
        })}
      </div>
      {reference.filters.length > 0 && (
        <div className="filters" style={{justifyContent: "flex-start"}}>
          {reference.filters.map((caption) => (
            <select
              key={caption}
              className="filter"
              disabled
              aria-disabled="true"
              aria-label={caption}
              value={caption}
            >
              {[caption, ...filterValues(caption, options)].map((option) => (
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
  const exportSpec = INVENTORY_EXPORTS[pageId];
  const [selectedRows, setSelectedRows] = useState<Set<string>>(() => new Set());
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState("");
  const [actionDialog, setActionDialog] = useState<InventoryActionDialogSpec | null>(null);
  const actionDialogTrigger = useRef<HTMLElement | null>(null);
  const slice = useQuery({
    queryKey: ["inventory-slice", screen.endpoint],
    queryFn: () => loadInventorySlice(screen.endpoint),
    retry: false
  });
  useEffect(() => {
    setSelectedRows(new Set());
    setExportStatus("");
    setActionDialog(null);
  }, [pageId, slice.data?.semanticFingerprint]);

  const visibleRowIds = (slice.data?.items ?? []).flatMap((row) =>
    typeof row.rowId === "string" ? [row.rowId] : []
  );
  const groupedCount = exportSpec?.card
    ? slice.data?.cards?.[exportSpec.card]?.length ?? 0
    : null;
  const currentFilteredCount = groupedCount ??
    slice.data?.pagination?.total ?? slice.data?.items.length ?? 0;
  const selectionApplies = pageId === "replenishmentPlanner" && selectedRows.size > 0;
  const exportCount = selectionApplies ? selectedRows.size : currentFilteredCount;
  const exportDisabledReason = !slice.data
    ? "Live data must load before export"
    : exporting
      ? "Preparing the governed export…"
      : exportCount === 0
        ? "No rows available to export"
        : exportCount > DIRECT_EXPORT_LIMIT
          ? `Export limit is ${DIRECT_EXPORT_LIMIT} rows; narrow filters or selection`
          : "";

  function toggleRow(rowId: string) {
    setSelectedRows((current) => {
      const next = new Set(current);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });
    setExportStatus("");
  }

  function toggleAllRows() {
    setSelectedRows((current) => {
      const allSelected = visibleRowIds.length > 0 &&
        visibleRowIds.every((rowId) => current.has(rowId));
      const next = new Set(current);
      for (const rowId of visibleRowIds) {
        if (allSelected) next.delete(rowId);
        else next.add(rowId);
      }
      return next;
    });
    setExportStatus("");
  }

  async function runExport() {
    if (!slice.data || !exportSpec || exportDisabledReason) return;
    setExporting(true);
    setExportStatus("");
    try {
      const selected = selectionApplies ? [...selectedRows].sort() : [];
      const result = await downloadDirectExport({
        exportId: exportSpec.exportId,
        scope: selectionApplies ? "selected_visible" : "current_filtered",
        expectedCount: exportCount,
        ids: selected,
        currency: sliceCurrency(slice.data)
      });
      setExportStatus(`Downloaded ${result.count.toLocaleString("en-US")} rows as ${result.filename}.`);
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  const selection: InventorySelection = {
    selected: selectedRows,
    onToggle: toggleRow,
    onToggleAll: toggleAllRows
  };

  return (
    <>
      {reference && (
        <ActionStrip
          pageId={pageId}
          reference={reference}
          options={slice.data?.filterOptions}
          exportSpec={exportSpec}
          exportDisabledReason={exportDisabledReason}
          exporting={exporting}
          onExport={runExport}
          onPreview={(spec, trigger) => {
            actionDialogTrigger.current = trigger;
            setActionDialog(spec);
          }}
        />
      )}
      {exportStatus && <div className="export-status" role="status">{exportStatus}</div>}
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
            <CardBlocks
              screen={screen}
              reference={reference}
              slice={slice.data}
              selection={pageId === "replenishmentPlanner" ? selection : undefined}
            />
          )}
        </>
      ) : null}
      {actionDialog && (
        <InventoryActionDialog
          spec={actionDialog}
          returnFocus={actionDialogTrigger.current}
          onClose={() => setActionDialog(null)}
        />
      )}
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
  // The reference's "12 open" is a count of its own illustrative alerts. The
  // extractor now drops any link carrying a digit, and the live count is how
  // many of this card's decisions actually have something in scope.
  const open = labels.filter((label) => {
    const spec = rows.find((row) => row.label === label);
    const value = spec?.field ? asNumber(summary?.[spec.field]) : null;
    return value !== null && value > 0;
  }).length;
  return (
    <div className="card">
      {heading && (
        <div className="card-head">
          <h3>{heading}</h3>
          <span className="link-button" aria-hidden="true">
            {link ?? `${open} open`}
          </span>
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
  screen, reference, slice, selection
}: {
  screen: ScreenSpec;
  reference: ReferenceScreen | undefined;
  slice: InventorySlice;
  selection?: InventorySelection;
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
  // Which declared spec fills each of the reference's `rows` cards, resolved by
  // HEADING before position.
  //
  // Position alone was wrong wherever a page has more than one rows card. The
  // Replenishment Planner has two -- "Lead-Time Risk" in the grid-2 block and
  // "Priority Replenishment Recommendations" in the full-width block -- and the
  // generated layout orders cards by LAYOUT, so Lead-Time Risk is the first rows
  // card in the sequence. Consuming `tables` positionally therefore rendered the
  // recommendations grid into the Lead-Time Risk slot, complete with that card's
  // heading, and left the recommendations card itself with no spec at all: one
  // grid appeared twice as far as a reader could tell, and one vanished.
  //
  // Headings are the reference's own identifiers, so matching on them keeps the
  // approved layout authoritative no matter what order the blocks fall in. A spec
  // with no heading -- the single-table pages -- still resolves positionally from
  // whatever is left over.
  const rowsCards = reference.cards.filter((card) => card.kind === "rows");
  const claimedGrouped = new Set<number>();
  const claimedTables = new Set<number>();
  const rowsPlan = rowsCards.map((card) => {
    if (card.heading) {
      const g = (screen.grouped ?? []).findIndex(
        (spec, i) => !claimedGrouped.has(i) && spec.heading === card.heading
      );
      if (g >= 0) {
        claimedGrouped.add(g);
        return {kind: "grouped" as const, index: g};
      }
      const r = screen.tables.findIndex(
        (spec, i) => !claimedTables.has(i) && spec.heading === card.heading
      );
      if (r >= 0) {
        claimedTables.add(r);
        return {kind: "table" as const, index: r};
      }
    }
    return null;
  });
  // Anything the headings did not claim falls back to declaration order, grouped
  // cards first, which is what the single-rows-card pages rely on.
  rowsPlan.forEach((slot, position) => {
    if (slot) return;
    const g = (screen.grouped ?? []).findIndex((_, i) => !claimedGrouped.has(i));
    if (g >= 0) {
      claimedGrouped.add(g);
      rowsPlan[position] = {kind: "grouped", index: g};
      return;
    }
    const r = screen.tables.findIndex((_, i) => !claimedTables.has(i));
    if (r >= 0) {
      claimedTables.add(r);
      rowsPlan[position] = {kind: "table", index: r};
    }
  });
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
            // A `rows` card is EITHER a grouped card or a row table. The
            // reference's Inventory Overview is three grouped cards and no row
            // table at all; consuming both lists in the same order keeps the
            // reference's card sequence authoritative.
            const slot = rowsPlan[rowsIndex++];
            if (!slot) return null;
            if (slot.kind === "grouped") {
              const grouped = (screen.grouped ?? [])[slot.index];
              return (
                <GroupedCard
                  key={key}
                  spec={{...grouped, heading: card.heading ?? grouped.heading}}
                  slice={slice}
                />
              );
            }
            const table = screen.tables[slot.index];
            if (!table) return null;
            return (
              <DataCard
                key={key}
                table={{...table, heading: card.heading}}
                slice={slice}
                selection={selection}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
