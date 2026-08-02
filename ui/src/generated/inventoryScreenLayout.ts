// Generated from docs/ai_retail_intelligence_dashboard_multicurrency_v6.html
// by tools/extract_reference_layout.py; DO NOT EDIT.
//
// Structure only. Every VALUE on these screens comes from the live API --
// the reference's illustrative figures are deliberately not extracted, so
// sample data is never one import away from a screen.

export type ReferenceCardKind = "rows" | "breakdown" | "alerts" | "donut";

export interface ReferenceCard {
  readonly kind: ReferenceCardKind;
  readonly heading: string | null;
  readonly link: string | null;
  /** grid-3 | grid-2 | full -- the layout block the card sits in. */
  readonly layout: string;
  /** Column headers, for a `rows` card. */
  readonly columns: readonly string[];
  /** Row labels, for a `breakdown`, `alerts` or `donut` card. */
  readonly labels: readonly string[];
}

export interface ReferenceScreen {
  readonly screenId: string;
  readonly actions: readonly string[];
  readonly filters: readonly (readonly string[])[];
  readonly kpiCaptions: readonly string[];
  readonly cards: readonly ReferenceCard[];
}

export const REFERENCE_SCREENS: readonly ReferenceScreen[] = [
  {
    screenId: "inventoryOverview",
    actions: ["Inventory Action Center", "Store Drilldown", "Warehouse Drilldown", "Run Inventory Scenario", "Export Inventory Report"],
    filters: [["All Regions", "West", "North", "South", "East"], ["All Categories", "Footwear", "Apparel", "Electronics", "Beauty"], ["All Health Statuses", "Healthy", "At Risk", "Overstock", "Understock", "Out of Stock"], ["All Locations", "Stores", "Warehouses", "In Transit"]],
    kpiCaptions: ["On-Hand Inventory", "Available to Promise", "Inventory in Transit", "Inventory at Risk", "Stock Turn"],
    cards: [
      {kind: "donut", heading: "Inventory by Health", link: "Enterprise view", layout: "grid-3", columns: [], labels: ["Healthy", "At Risk", "Overstock", "Out of Stock"]},
      {kind: "breakdown", heading: "Inventory Position", link: null, layout: "grid-3", columns: [], labels: ["Store inventory", "Warehouse inventory", "In transit", "Reserved stock", "Damaged / blocked"]},
      {kind: "alerts", heading: "Immediate Decisions", link: null, layout: "grid-3", columns: [], labels: ["Transfer excess stock", "Approve ageing-stock markdown", "Accelerate replenishment"]},
      {kind: "rows", heading: "Ageing Inventory", link: "By value", layout: "grid-2", columns: ["Age Bucket", "SKUs", "Inventory Value", "Sell-through", "Recommended Action"], labels: []},
      {kind: "rows", heading: "Inventory Risk by Category", link: null, layout: "grid-2", columns: ["Category", "Value", "Days of Supply", "Risk", "Action"], labels: []},
      {kind: "rows", heading: "Location-Level Inventory Performance", link: "Top exceptions", layout: "full", columns: ["Location", "Type", "Inventory Value", "Availability", "Days of Supply", "Stock-out Risk", "Overstock", "Priority Action"], labels: []},
    ]
  },
  {
    screenId: "storeInventory",
    actions: ["Create Store Action", "Create Transfer", "Export"],
    filters: [],
    kpiCaptions: ["Store Inventory Value", "On-Shelf Availability", "Stores at Risk", "Transfer Opportunity", "Lost Sales Exposure"],
    cards: [
      {kind: "rows", heading: "Store Inventory Heatmap", link: null, layout: "grid-2", columns: ["Store", "Availability", "DoS", "Overstock", "Understock", "Action"], labels: []},
      {kind: "breakdown", heading: "Store Exception Summary", link: null, layout: "grid-2", columns: [], labels: ["High stock-out risk", "High overstock risk", "Display stock mismatch", "Negative inventory", "Transfer candidates"]},
    ]
  },
  {
    screenId: "warehouseInventory",
    actions: ["Release Blocked Stock", "Review Delayed Receipts", "Export"],
    filters: [],
    kpiCaptions: ["Warehouse Inventory", "Inbound in Transit", "Blocked Inventory", "Dock-to-Stock Time", "Warehouse Fill Rate"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Warehouse", "Inventory Value", "Capacity Utilization", "Fill Rate", "Blocked Stock", "Delayed Receipts", "Action"], labels: []},
    ]
  },
  {
    screenId: "inventoryAgeing",
    actions: ["Create Markdown Plan", "Create Transfer Plan", "Export"],
    filters: [],
    kpiCaptions: ["60+ Day Inventory", "90+ Day Inventory", "Dead Stock", "Markdown Opportunity", "Transfer Opportunity"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["SKU / Product", "Category", "Age", "Units", "Value", "Sell-through", "Recommended Action", "Priority"], labels: []},
    ]
  },
  {
    screenId: "inventoryTransfers",
    actions: ["Create Transfer Request", "Optimize Transfers", "Export"],
    filters: [],
    kpiCaptions: ["Open Transfer Requests", "Transfer Value", "Expected Lost-Sales Recovery", "Average Transfer Time", "Transfer Acceptance"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["SKU", "From Location", "To Location", "Available Qty", "Suggested Qty", "Value", "Expected Benefit", "Status"], labels: []},
    ]
  },
  {
    screenId: "inventoryValuation",
    actions: ["Run Valuation Scenario", "Reconcile with ERP", "Export"],
    filters: [],
    kpiCaptions: ["Gross Inventory Value", "Net Realizable Value", "Markdown Provision", "Obsolescence Provision", "Inventory Variance"],
    cards: [
      {kind: "rows", heading: "Valuation by Category", link: null, layout: "grid-2", columns: ["Category", "Gross Value", "NRV", "Provision", "Variance"], labels: []},
      {kind: "breakdown", heading: "Financial Control Exceptions", link: null, layout: "grid-2", columns: [], labels: ["ERP vs WMS variance", "Unposted markdown provision", "Negative inventory value", "Cost missing"]},
    ]
  },
  {
    screenId: "expiryWaste",
    actions: ["Create Expiry Action", "Create Waste Reduction Plan", "Export"],
    filters: [],
    kpiCaptions: ["Near-Expiry Inventory", "Waste This Month", "Waste Reduction", "Products at Risk", "Recovery Opportunity"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Product", "Location", "Expiry Window", "Units", "Value", "Sell-through", "Recommended Action", "Priority"], labels: []},
    ]
  },
  {
    screenId: "stockHealth",
    actions: ["Assign Owner", "Create Action"],
    filters: [["All Health Statuses", "Overstock", "Understock", "Near Expiry"]],
    kpiCaptions: [],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["SKU", "Store", "Days of Supply", "Ageing", "Health", "Financial Exposure", "Recommended Action", "Priority"], labels: []},
    ]
  },
  {
    screenId: "replenishmentPlanner",
    actions: ["Approve Selected Orders", "Create Transfer Requests", "Send to ERP", "Run Scenario", "Action Center", "Export"],
    filters: [],
    kpiCaptions: ["Suggested Replenishment Value", "Revenue Protected", "Working Capital Impact", "Projected Service Level", "Exception Orders"],
    cards: [
      {kind: "breakdown", heading: "Replenishment Mix", link: null, layout: "grid-3", columns: [], labels: ["Supplier purchase orders", "Warehouse transfers", "Inter-store transfers", "Expedited orders"]},
      {kind: "breakdown", heading: "Business Impact", link: null, layout: "grid-3", columns: [], labels: ["Lost-sales reduction", "Stock-out reduction", "Inventory turn improvement", "Transfer savings"]},
      {kind: "breakdown", heading: "Approval Pipeline", link: null, layout: "grid-3", columns: [], labels: ["Pending planner review", "Pending supply-chain approval", "Pending finance review", "ERP transmission failed"]},
      {kind: "rows", heading: "Lead-Time Risk", link: null, layout: "grid-2", columns: ["Supplier / Source", "Lead Time", "Late Orders", "Risk"], labels: []},
      {kind: "breakdown", heading: "Replenishment Governance", link: null, layout: "grid-2", columns: [], labels: ["Approved forecast coverage", "MOQ / pack-size compliance", "Orders within budget", "Supplier capacity confirmed"]},
      {kind: "rows", heading: "Priority Replenishment Recommendations", link: "Top actions", layout: "full", columns: ["select", "Priority", "SKU / Product", "Destination", "Current Stock", "Forecast Demand", "Safety Stock", "Suggested Qty", "Source", "Lead Time", "Expected Receipt", "Order Value", "Service Impact", "Confidence", "Status"], labels: []},
    ]
  },
  {
    screenId: "suggestedOrders",
    actions: ["Approve Orders", "Modify Quantity", "Export"],
    filters: [],
    kpiCaptions: ["Suggested Orders", "Order Value", "High Priority", "Within Budget", "Expected Fill Rate"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Order", "Type", "Destination", "Source", "Items", "Value", "Need Date", "Confidence", "Status"], labels: []},
    ]
  },
  {
    screenId: "supplierPlanning",
    actions: ["Request Capacity Confirmation", "Create Expedite Request", "Export"],
    filters: [],
    kpiCaptions: ["Active Suppliers", "Open PO Value", "Capacity Confirmed", "On-Time Delivery", "Supplier Risk"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Supplier", "Category", "Open PO Value", "Capacity", "Lead Time", "OTD", "Risk", "Action"], labels: []},
    ]
  },
  {
    screenId: "safetyStock",
    actions: ["Recalculate Safety Stock", "Approve Policy", "Export"],
    filters: [],
    kpiCaptions: ["Safety Stock Value", "Policy Coverage", "Below Safety Stock", "Excess Safety Stock", "Projected Service Level"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "grid-2", columns: ["Policy Segment", "SKUs", "Service Target", "Current Value", "Recommended Value", "Impact"], labels: []},
      {kind: "breakdown", heading: "Safety Stock Drivers", link: null, layout: "grid-2", columns: [], labels: ["Demand variability", "Lead-time variability", "Service-level target", "Promotion / seasonality"]},
    ]
  },
  {
    screenId: "allocationFulfillment",
    actions: ["Optimize Allocation", "Release Allocation", "Export"],
    filters: [],
    kpiCaptions: ["Available Allocation Pool", "Store Requests", "Fulfillment Rate", "Priority Shortfall", "Revenue Protected"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Product", "Available Pool", "Store Demand", "Allocated", "Shortfall", "Allocation Rule", "Priority", "Status"], labels: []},
    ]
  },
  {
    screenId: "replenishmentExceptions",
    actions: ["Resolve Selected", "Assign Owner", "Export"],
    filters: [],
    kpiCaptions: ["Open Exceptions", "High Priority", "Budget Exceptions", "Supplier Exceptions", "ERP Failures"],
    cards: [
      {kind: "rows", heading: null, link: null, layout: "full", columns: ["Exception", "Order / SKU", "Business Impact", "Owner", "Age", "Priority", "Recommended Resolution", "Status"], labels: []},
    ]
  },
];

export const REFERENCE_SCREEN_BY_ID: Record<string, ReferenceScreen> = Object.fromEntries(
  REFERENCE_SCREENS.map((screen) => [screen.screenId, screen])
);
