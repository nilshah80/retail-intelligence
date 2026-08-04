// Generated from contracts/screens/inventory-replenishment.parity.yaml;
// DO NOT EDIT.

export const INVENTORY_CONTRACT_SET_ID = "inventoryReplenishment";

export const INVENTORY_VIEWPORTS = {
  desktop: "1440x1100",
  mobile: "390x844"
} as const;

export const INVENTORY_ACTION_BEHAVIOR =
  "visible and natively disabled with aria-disabled; no mutation endpoint or handler exists (P4-D9/P4-D11)";

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
    actions: ["Warehouse Export"]
  },
  {
    screenId: "inventoryAgeing",
    title: "Inventory Ageing",
    endpoint: "/api/v1/inventory/ageing",
    grain: "SKU x location x age bucket",
    actions: ["Ageing Export"]
  },
  {
    screenId: "inventoryTransfers",
    title: "Stock Transfers",
    endpoint: "/api/v1/inventory/transfers",
    grain: "lane x SKU",
    actions: ["Create Transfer", "Transfer Export"]
  },
  {
    screenId: "inventoryValuation",
    title: "Inventory Valuation",
    endpoint: "/api/v1/inventory/valuation",
    grain: "category/location",
    actions: ["Valuation Export"]
  },
  {
    screenId: "expiryWaste",
    title: "Expiry & Waste",
    endpoint: "/api/v1/inventory/expiry-waste",
    grain: "batch",
    actions: ["Expiry Export"]
  },
  {
    screenId: "replenishmentPlanner",
    title: "Replenishment Planner",
    endpoint: "/api/v1/replenishment/planner",
    grain: "SKU -> destination",
    actions: ["Approve Orders", "Adjust Parameters", "Planner Export"]
  },
  {
    screenId: "suggestedOrders",
    title: "Suggested Orders",
    endpoint: "/api/v1/replenishment/orders",
    grain: "order/recommendation",
    actions: ["Send to ERP", "Orders Export"]
  },
  {
    screenId: "supplierPlanning",
    title: "Supplier Planning",
    endpoint: "/api/v1/replenishment/suppliers",
    grain: "supplier x scope/period",
    actions: ["Supplier Export"]
  },
  {
    screenId: "safetyStock",
    title: "Safety Stock",
    endpoint: "/api/v1/replenishment/safety-stock",
    grain: "policy segment",
    actions: ["Safety Stock Export"]
  },
  {
    screenId: "allocationFulfillment",
    title: "Allocation & Fulfillment",
    endpoint: "/api/v1/replenishment/allocations",
    grain: "SKU x store x channel",
    actions: ["Allocation Export"]
  },
  {
    screenId: "replenishmentExceptions",
    title: "Replenishment Exceptions",
    endpoint: "/api/v1/replenishment/exceptions",
    grain: "exception",
    actions: ["Assign", "Resolve", "Exceptions Export"]
  },
  {
    screenId: "stockHealth",
    title: "Stock Health",
    endpoint: "/api/v1/inventory/stock-health",
    grain: "SKU x store",
    actions: ["Stock Health Export"]
  },
];
