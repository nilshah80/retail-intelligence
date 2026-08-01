// Generated from docs/ai_retail_intelligence_dashboard_multicurrency_v6.html
// by tools/extract_reference_layout.py; DO NOT EDIT.
//
// Structure only. Every VALUE on these screens comes from the live API --
// the reference's illustrative figures are deliberately not extracted, so
// sample data is never one import away from a screen.

export interface ReferenceTable {
  readonly heading: string | null;
  readonly columns: readonly string[];
}

export interface ReferenceScreen {
  readonly screenId: string;
  readonly actions: readonly string[];
  readonly filters: readonly (readonly string[])[];
  readonly kpiCaptions: readonly string[];
  readonly tables: readonly ReferenceTable[];
}

export const REFERENCE_SCREENS: readonly ReferenceScreen[] = [
  {
    screenId: "inventoryOverview",
    actions: ["Inventory Action Center", "Store Drilldown", "Warehouse Drilldown", "Run Inventory Scenario", "Export Inventory Report"],
    filters: [["All Regions", "West", "North", "South", "East"], ["All Categories", "Footwear", "Apparel", "Electronics", "Beauty"], ["All Health Statuses", "Healthy", "At Risk", "Overstock", "Understock", "Out of Stock"], ["All Locations", "Stores", "Warehouses", "In Transit"]],
    kpiCaptions: ["On-Hand Inventory", "Available to Promise", "Inventory in Transit", "Inventory at Risk", "Stock Turn"],
    tables: [
      {heading: null, columns: []},
      {heading: "Ageing Inventory", columns: ["Age Bucket", "SKUs", "Inventory Value", "Sell-through", "Recommended Action"]},
      {heading: "Inventory Risk by Category", columns: ["Category", "Value", "Days of Supply", "Risk", "Action"]},
      {heading: "Location-Level Inventory Performance", columns: ["Location", "Type", "Inventory Value", "Availability", "Days of Supply", "Stock-out Risk", "Overstock", "Priority Action"]},
    ]
  },
  {
    screenId: "storeInventory",
    actions: ["Create Store Action", "Create Transfer", "Export"],
    filters: [],
    kpiCaptions: ["Store Inventory Value", "On-Shelf Availability", "Stores at Risk", "Transfer Opportunity", "Lost Sales Exposure"],
    tables: [
      {heading: "Store Inventory Heatmap", columns: ["Store", "Availability", "DoS", "Overstock", "Understock", "Action"]},
      {heading: null, columns: []},
    ]
  },
  {
    screenId: "warehouseInventory",
    actions: ["Release Blocked Stock", "Review Delayed Receipts", "Export"],
    filters: [],
    kpiCaptions: ["Warehouse Inventory", "Inbound in Transit", "Blocked Inventory", "Dock-to-Stock Time", "Warehouse Fill Rate"],
    tables: [
      {heading: null, columns: ["Warehouse", "Inventory Value", "Capacity Utilization", "Fill Rate", "Blocked Stock", "Delayed Receipts", "Action"]},
    ]
  },
  {
    screenId: "inventoryAgeing",
    actions: ["Create Markdown Plan", "Create Transfer Plan", "Export"],
    filters: [],
    kpiCaptions: ["60+ Day Inventory", "90+ Day Inventory", "Dead Stock", "Markdown Opportunity", "Transfer Opportunity"],
    tables: [
      {heading: null, columns: ["SKU / Product", "Category", "Age", "Units", "Value", "Sell-through", "Recommended Action", "Priority"]},
    ]
  },
  {
    screenId: "inventoryTransfers",
    actions: ["Create Transfer Request", "Optimize Transfers", "Export"],
    filters: [],
    kpiCaptions: ["Open Transfer Requests", "Transfer Value", "Expected Lost-Sales Recovery", "Average Transfer Time", "Transfer Acceptance"],
    tables: [
      {heading: null, columns: ["SKU", "From Location", "To Location", "Available Qty", "Suggested Qty", "Value", "Expected Benefit", "Status"]},
    ]
  },
  {
    screenId: "inventoryValuation",
    actions: ["Run Valuation Scenario", "Reconcile with ERP", "Export"],
    filters: [],
    kpiCaptions: ["Gross Inventory Value", "Net Realizable Value", "Markdown Provision", "Obsolescence Provision", "Inventory Variance"],
    tables: [
      {heading: "Valuation by Category", columns: ["Category", "Gross Value", "NRV", "Provision", "Variance"]},
      {heading: null, columns: []},
    ]
  },
  {
    screenId: "expiryWaste",
    actions: ["Create Expiry Action", "Create Waste Reduction Plan", "Export"],
    filters: [],
    kpiCaptions: ["Near-Expiry Inventory", "Waste This Month", "Waste Reduction", "Products at Risk", "Recovery Opportunity"],
    tables: [
      {heading: null, columns: ["Product", "Location", "Expiry Window", "Units", "Value", "Sell-through", "Recommended Action", "Priority"]},
    ]
  },
  {
    screenId: "stockHealth",
    actions: ["Assign Owner", "Create Action"],
    filters: [["All Health Statuses", "Overstock", "Understock", "Near Expiry"]],
    kpiCaptions: [],
    tables: [
      {heading: null, columns: ["SKU", "Store", "Days of Supply", "Ageing", "Health", "Financial Exposure", "Recommended Action", "Priority"]},
    ]
  },
  {
    screenId: "replenishmentPlanner",
    actions: ["Approve Selected Orders", "Create Transfer Requests", "Send to ERP", "Run Scenario", "Action Center", "Export"],
    filters: [],
    kpiCaptions: ["Suggested Replenishment Value", "Revenue Protected", "Working Capital Impact", "Projected Service Level", "Exception Orders"],
    tables: [
      {heading: null, columns: []},
      {heading: null, columns: []},
      {heading: null, columns: []},
      {heading: "Priority Replenishment Recommendations", columns: ["select", "Priority", "SKU / Product", "Destination", "Current Stock", "Forecast Demand", "Safety Stock", "Suggested Qty", "Source", "Lead Time", "Expected Receipt", "Order Value", "Service Impact", "Confidence", "Status"]},
      {heading: "Lead-Time Risk", columns: ["Supplier / Source", "Lead Time", "Late Orders", "Risk"]},
      {heading: null, columns: []},
    ]
  },
  {
    screenId: "suggestedOrders",
    actions: ["Approve Orders", "Modify Quantity", "Export"],
    filters: [],
    kpiCaptions: ["Suggested Orders", "Order Value", "High Priority", "Within Budget", "Expected Fill Rate"],
    tables: [
      {heading: null, columns: ["Order", "Type", "Destination", "Source", "Items", "Value", "Need Date", "Confidence", "Status"]},
    ]
  },
  {
    screenId: "supplierPlanning",
    actions: ["Request Capacity Confirmation", "Create Expedite Request", "Export"],
    filters: [],
    kpiCaptions: ["Active Suppliers", "Open PO Value", "Capacity Confirmed", "On-Time Delivery", "Supplier Risk"],
    tables: [
      {heading: null, columns: ["Supplier", "Category", "Open PO Value", "Capacity", "Lead Time", "OTD", "Risk", "Action"]},
    ]
  },
  {
    screenId: "safetyStock",
    actions: ["Recalculate Safety Stock", "Approve Policy", "Export"],
    filters: [],
    kpiCaptions: ["Safety Stock Value", "Policy Coverage", "Below Safety Stock", "Excess Safety Stock", "Projected Service Level"],
    tables: [
      {heading: null, columns: ["Policy Segment", "SKUs", "Service Target", "Current Value", "Recommended Value", "Impact"]},
      {heading: null, columns: []},
    ]
  },
  {
    screenId: "allocationFulfillment",
    actions: ["Optimize Allocation", "Release Allocation", "Export"],
    filters: [],
    kpiCaptions: ["Available Allocation Pool", "Store Requests", "Fulfillment Rate", "Priority Shortfall", "Revenue Protected"],
    tables: [
      {heading: null, columns: ["Product", "Available Pool", "Store Demand", "Allocated", "Shortfall", "Allocation Rule", "Priority", "Status"]},
    ]
  },
  {
    screenId: "replenishmentExceptions",
    actions: ["Resolve Selected", "Assign Owner", "Export"],
    filters: [],
    kpiCaptions: ["Open Exceptions", "High Priority", "Budget Exceptions", "Supplier Exceptions", "ERP Failures"],
    tables: [
      {heading: null, columns: ["Exception", "Order / SKU", "Business Impact", "Owner", "Age", "Priority", "Recommended Resolution", "Status"]},
    ]
  },
];

export const REFERENCE_SCREEN_BY_ID: Record<string, ReferenceScreen> = Object.fromEntries(
  REFERENCE_SCREENS.map((screen) => [screen.screenId, screen])
);
