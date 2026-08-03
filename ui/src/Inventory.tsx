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
  readonly format: "units" | "money" | "count" | "percent" | "days" | "turns";
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
  NRV_UNAVAILABLE: {
    why: "the resolved inventory policy declares valuation.nrvAndProvisions as unavailable_pending_markdown_policy, so net realizable value has no approved basis on this bundle -- and the platform holds acquisition cost rather than the expected recovery price NRV is measured against",
    when: "when a markdown and NRV policy is approved and resolved into the policy bundle; a ledger figure is not estimated ahead of the approval that governs it"
  },
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
  PROVISION_PENDING_MARKDOWN_POLICY: {
    why: "the resolved inventory policy declares valuation.nrvAndProvisions as unavailable_pending_markdown_policy -- the ageing ladder's 10 per cent is a recommended markdown depth, not an approved provisioning rate, and a provision posted against an unapproved rate is a ledger figure nobody signed off",
    when: "when a markdown provisioning rate is approved and resolved into the policy bundle; the underlying cells and their SKU-grain cost are already published, so only the approval is outstanding"
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
  BUDGET_NOT_APPLIED: {
    why: "the market budget ceiling is declared in policy but not yet applied to recommendations",
    when: "when the budget cap is enforced in the replenishment engine"
  },
  DRIVER_COMPONENTS_NOT_PUBLISHED: {
    why: "the safety-stock artifact publishes the buffer the policy produced and the class it was sized under, not the demand and lead-time terms that went into it",
    when: "when the engine emits its per-cell inputs alongside its output"
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
      {caption: "Inventory in Transit", field: "inTransitValueMinor",
       format: "money", note: "Received against a declared lane"},
      // Rupees and a share of on-hand value, as the reference shows it. The
      // scope is the reference's own note: everything the health engine did not
      // class healthy -- overstock, ageing, expiry.
      {caption: "Inventory at Risk", field: "atRiskValueMinor", format: "money",
       of: "onHandValueMinor",
       note: "Overstock, ageing and expiry, valued at accepted unit cost"},
      // Turn is a year over days of supply, and days of supply is on-hand over
      // daily demand. Both became computable once trailing demand was published.
      {caption: "Stock Turn", field: "stockTurn", format: "turns",
       note: "Trailing demand over units on hand, annualised"}
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
       note: "Outbound need fillable from own stock"}
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
      {caption: "Net Realizable Value", field: null, format: "money",
       unavailableReason: "NRV_UNAVAILABLE",
       note: "Needs an approved markdown policy"},
      {caption: "Markdown Provision", field: null, format: "money",
       unavailableReason: "PROVISION_PENDING_MARKDOWN_POLICY",
       note: "2,128 cells are marked for markdown; costing them needs SKU-grain value"},
      {caption: "Obsolescence Provision", field: null, format: "money",
       unavailableReason: "PROVISION_PENDING_MARKDOWN_POLICY",
       note: "Residual-only cells are identified; costing them needs SKU-grain value"},
      {caption: "Inventory Variance", field: "varianceValueMinor", format: "money",
       note: "Absolute ERP-versus-WMS discrepancy"}
    ],
    breakdown: [
      // "Financial Control Exceptions".
      // Money, as the reference's badge shows it -- Rs 0.18 Cr. The unit count is
      // the same variance unpriced, and a finance control reads in currency.
      {label: "ERP vs WMS variance", field: "varianceValueMinor", format: "money"},
      {label: "Unposted markdown provision", field: null, format: "money",
       unavailableReason: "PROVISION_PENDING_MARKDOWN_POLICY"},
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
        {header: "NRV", field: null, unavailableReason: "NRV_UNAVAILABLE"},
        {header: "Provision", field: null,
         unavailableReason: "PROVISION_PENDING_MARKDOWN_POLICY"},
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
      {caption: "Waste This Month", field: "wasteValueMinor", format: "money",
       note: "Written off in the trailing window"},
      {caption: "Waste Reduction", field: null, format: "percent",
       unavailableReason: "PRIOR_PERIOD_NOT_COMPARED",
       note: "Needs a prior-period comparison"},
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
        // Both columns on the NEAR-EXPIRY basis, which is what the page is about
        // and what its headline tile totals. Units was the already-expired count
        // while Value was the expiring holding, so the two disagreed on the same
        // row; and Value read `exposureMinor`, which the artifact publishes NULL
        // on every row, so the column was blank on every row.
        {header: "Units", field: "expiringUnits", format: "units"},
        {header: "Value", field: "valueMinor", format: "money"},
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
      // Units, under a caption the reference words as "Value". Withholding a
      // figure the platform can compute would be worse than labelling it, so
      // the note says plainly which one this is.
      {caption: "Suggested Replenishment Value", field: "recommendedUnits",
       format: "units",
       note: "Units, not money -- a recommendation carries no costed line"},
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
      // Benefit. Every one of these is a candidate-versus-incumbent claim.
      {label: "Lost-sales reduction", field: null, format: "units",
       unavailableReason: "REPLAY_UNAVAILABLE"},
      {label: "Stock-out reduction", field: null, format: "count",
       unavailableReason: "REPLAY_UNAVAILABLE"},
      {label: "Inventory turn improvement", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE"},
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
      {label: "Orders within budget", field: null, format: "percent",
       unavailableReason: "BUDGET_NOT_APPLIED"},
      {label: "Supplier capacity confirmed",
       field: "supplierMeanCapacityConfirmedPct", format: "percent"}
    ],
    tables: [
      {heading: "Priority Replenishment Recommendations", columns: [
        {header: "select", field: null},
        {header: "Priority", field: "reasonCode"},
        {header: "SKU / Product", field: "productName"},
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
      {caption: "Order Value", field: "orderValueMinor", format: "money",
       note: "Recommended units at the destination's accepted cost"},
      {caption: "High Priority", field: "highPriorityCells", format: "count",
       of: "cellsToOrder",
       note: "Ordering into a destination that is stocked out"},
      {caption: "Within Budget", field: null, format: "percent",
       unavailableReason: "BUDGET_NOT_APPLIED",
       note: "Market budget ceiling is not yet applied"},
      {caption: "Expected Fill Rate", field: null, format: "percent",
       unavailableReason: "REPLAY_UNAVAILABLE",
       note: "Needs a reproducing weekly replay"}
    ],
    tables: [
      {heading: null, columns: [
        {header: "Order", field: "productName"},
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
    breakdown: [
      // "Safety Stock Drivers". The buffer is published; its terms are not.
      {label: "Demand variability", field: null, format: "count",
       unavailableReason: "DRIVER_COMPONENTS_NOT_PUBLISHED"},
      {label: "Lead-time variability", field: null, format: "count",
       unavailableReason: "DRIVER_COMPONENTS_NOT_PUBLISHED"},
      {label: "Service-level target", field: "meanServiceLevel",
       format: "percent"},
      {label: "Promotion / seasonality", field: null, format: "count",
       unavailableReason: "DRIVER_COMPONENTS_NOT_PUBLISHED"}
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
        {header: "Product", field: "productName"},
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
        {header: "Order / SKU", field: "productName"},
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
        // The denominator names itself. Hardcoding "of on-hand" was right for
        // the position tiles it was written for and wrong everywhere it spread
        // to: "Stores at Risk 4 / 50.0% of on-hand" is four of eight LOCATIONS.
        <span className="delta up">
          {(share * 100).toFixed(1)}% {shareBasis(spec.of)}
        </span>
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
            // A `rows` card is EITHER a grouped card or a row table. The
            // reference's Inventory Overview is three grouped cards and no row
            // table at all; consuming both lists in the same order keeps the
            // reference's card sequence authoritative.
            const index = rowsIndex++;
            const grouped = screen.grouped?.[index];
            if (grouped) {
              return (
                <GroupedCard
                  key={key}
                  spec={{...grouped, heading: card.heading ?? grouped.heading}}
                  slice={slice}
                />
              );
            }
            const table = screen.tables[index - (screen.grouped?.length ?? 0)];
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
