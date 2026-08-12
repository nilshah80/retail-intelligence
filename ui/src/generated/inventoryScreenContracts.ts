// Generated from contracts/screens/inventory-replenishment.parity.yaml;
// DO NOT EDIT.

export const INVENTORY_CONTRACT_SET_ID = "inventoryReplenishment";

export const INVENTORY_VIEWPORTS = {
  desktop: "1440x1100",
  mobile: "390x844"
} as const;

export const INVENTORY_ACTION_BEHAVIOR =
  "exports are governed live downloads; workflow actions open visibly labelled non-mutating dialogs with disabled submission and no mutation endpoint, request, or history change";

export interface InventoryScreenContract {
  readonly screenId: string;
  readonly title: string;
  readonly endpoint: string;
  readonly grain: string;
  readonly actions: readonly string[];
}

export const INVENTORY_SCREEN_CONTRACTS: readonly InventoryScreenContract[] = [
  {
    screenId: "inventoryOverview",
    title: "Inventory Overview",
    endpoint: "/api/v1/inventory/overview",
    grain: "market/location",
    actions: ["Inventory Action Center", "Store Drilldown", "Warehouse Drilldown", "Run Inventory Scenario", "Export Inventory Report"]
  },
  {
    screenId: "storeInventory",
    title: "Store Inventory",
    endpoint: "/api/v1/inventory/stores",
    grain: "store x SKU",
    actions: ["Create Store Action", "Create Transfer", "Export"]
  },
  {
    screenId: "warehouseInventory",
    title: "Warehouse Inventory",
    endpoint: "/api/v1/inventory/warehouses",
    grain: "DC",
    actions: ["Release Blocked Stock", "Review Delayed Receipts", "Export"]
  },
  {
    screenId: "inventoryAgeing",
    title: "Inventory Ageing",
    endpoint: "/api/v1/inventory/ageing",
    grain: "SKU x location x age bucket",
    actions: ["Create Markdown Plan", "Create Transfer Plan", "Export"]
  },
  {
    screenId: "inventoryTransfers",
    title: "Stock Transfers",
    endpoint: "/api/v1/inventory/transfers",
    grain: "lane x SKU",
    actions: ["Create Transfer Request", "Optimize Transfers", "Export"]
  },
  {
    screenId: "inventoryValuation",
    title: "Inventory Valuation",
    endpoint: "/api/v1/inventory/valuation",
    grain: "category/location",
    actions: ["Run Valuation Scenario", "Reconcile with ERP", "Export"]
  },
  {
    screenId: "expiryWaste",
    title: "Expiry & Waste",
    endpoint: "/api/v1/inventory/expiry-waste",
    grain: "batch",
    actions: ["Create Expiry Action", "Create Waste Reduction Plan", "Export"]
  },
  {
    screenId: "replenishmentPlanner",
    title: "Replenishment Planner",
    endpoint: "/api/v1/replenishment/planner",
    grain: "SKU -> destination",
    actions: ["Approve Selected Orders", "Create Transfer Requests", "Send to ERP", "Run Scenario", "Action Center", "Export"]
  },
  {
    screenId: "suggestedOrders",
    title: "Suggested Orders",
    endpoint: "/api/v1/replenishment/orders",
    grain: "order/recommendation",
    actions: ["Approve Orders", "Modify Quantity", "Export"]
  },
  {
    screenId: "supplierPlanning",
    title: "Supplier Planning",
    endpoint: "/api/v1/replenishment/suppliers",
    grain: "supplier x scope/period",
    actions: ["Request Capacity Confirmation", "Create Expedite Request", "Export"]
  },
  {
    screenId: "safetyStock",
    title: "Safety Stock",
    endpoint: "/api/v1/replenishment/safety-stock",
    grain: "policy segment",
    actions: ["Recalculate Safety Stock", "Approve Policy", "Export"]
  },
  {
    screenId: "allocationFulfillment",
    title: "Allocation & Fulfillment",
    endpoint: "/api/v1/replenishment/allocations",
    grain: "SKU x store x channel",
    actions: ["Optimize Allocation", "Release Allocation", "Export"]
  },
  {
    screenId: "replenishmentExceptions",
    title: "Replenishment Exceptions",
    endpoint: "/api/v1/replenishment/exceptions",
    grain: "exception",
    actions: ["Resolve Selected", "Assign Owner", "Export"]
  },
  {
    screenId: "stockHealth",
    title: "Stock Health",
    endpoint: "/api/v1/inventory/stock-health",
    grain: "SKU x store",
    actions: ["Assign Owner", "Create Action"]
  },
];
