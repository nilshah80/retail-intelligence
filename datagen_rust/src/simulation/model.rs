use std::collections::{BTreeMap, HashMap};
use std::hash::{BuildHasherDefault, Hasher};

use chrono::NaiveDate;

#[derive(Debug, Clone)]
pub struct DayBatch {
    pub date: NaiveDate,
    pub orders: Vec<CausalOrder>,
    pub demand_cells: Vec<DemandCell>,
    pub inventory_snapshots: Vec<InventorySnapshot>,
    pub store_inventory_snapshots: Vec<StoreInventorySnapshot>,
    pub supply_events: Vec<SupplyEvent>,
    pub signals: Vec<SignalRow>,
}

#[derive(Debug, Clone)]
pub struct CausalOrder {
    pub order_key: String,
    pub source_sequence: u64,
    pub date: NaiveDate,
    pub created_at: String,
    pub processed_at: String,
    pub market_id: String,
    pub store_id: String,
    pub store_location_code: String,
    pub channel_id: String,
    pub channel_type: String,
    pub customer_key: Option<String>,
    pub customer_segment_id: String,
    pub currency_code: String,
    pub taxes_included: bool,
    pub lines: Vec<CausalLine>,
    pub subtotal_minor: i64,
    pub tax_minor: i64,
    pub total_minor: i64,
}

#[derive(Debug, Clone)]
pub struct CausalLine {
    pub line_key: String,
    pub line_number: usize,
    pub product_index: usize,
    pub variant_index: usize,
    pub sku: String,
    pub product_code: String,
    pub product_title: String,
    pub variant_title: String,
    pub brand: String,
    pub department_id: String,
    pub category_id: String,
    pub barcode: String,
    pub latent_quantity: i64,
    pub quantity: i64,
    pub lost_quantity: i64,
    pub served_from_store_quantity: i64,
    pub original_unit_price_minor: i64,
    pub discounted_unit_price_minor: i64,
    pub unit_cost_minor: i64,
    pub tax_rate: f64,
    pub tax_minor: i64,
    pub promotion_ids: Vec<String>,
    pub promotion_discount_pct: f64,
    pub warehouse_id: String,
    pub warehouse_location_code: String,
    pub fulfillment_group: usize,
    pub return_requested: bool,
    pub return_processed: bool,
    pub refund_success: bool,
}

#[derive(Debug, Clone)]
pub struct DemandCell {
    pub date: NaiveDate,
    pub market_id: String,
    pub store_id: String,
    pub channel_id: String,
    pub channel_type: String,
    pub sku: String,
    pub department_id: String,
    pub category_id: String,
    pub baseline_demand: f64,
    pub expected_demand: f64,
    pub latent_units: i64,
    pub realized_units: i64,
    pub lost_units: i64,
    pub day_of_week_factor: f64,
    pub trend_factor: f64,
    pub seasonality_factor: f64,
    pub holiday_factor: f64,
    pub event_factor: f64,
    pub promotion_factor: f64,
    pub price_factor: f64,
    pub weather_factor: f64,
    pub macro_factor: f64,
    pub noise_factor: f64,
    pub total_factor: f64,
    pub promotion_ids: Vec<String>,
    pub event_ids: Vec<String>,
    pub holiday_names: Vec<String>,
    pub promotion_discount_pct: f64,
}

#[derive(Debug, Clone)]
pub struct InventorySnapshot {
    pub date: NaiveDate,
    pub observed_at: String,
    pub market_id: String,
    pub warehouse_id: String,
    pub location_code: String,
    pub sku: String,
    pub inventory: i64,
    pub available: i64,
    pub committed: i64,
    pub reserved: i64,
    pub damaged: i64,
    pub quality_control: i64,
    pub safety_stock: i64,
    pub incoming: i64,
}

#[derive(Debug, Clone)]
pub struct StoreInventorySnapshot {
    pub date: NaiveDate,
    pub observed_at: String,
    pub market_id: String,
    pub store_id: String,
    pub location_code: String,
    pub sku: String,
    pub inventory: i64,
    pub available: i64,
    pub committed: i64,
    pub reserved: i64,
    pub damaged: i64,
    pub quality_control: i64,
    pub safety_stock: i64,
    pub incoming: i64,
    pub assortment_active: bool,
    pub residual_only: bool,
    pub oldest_receipt_date: String,
}

#[derive(Debug, Clone)]
pub enum SupplyEvent {
    PurchaseOrder(PurchaseOrderEvent),
    Transfer(TransferEvent),
    Waste(WasteEvent),
}

#[derive(Debug, Clone)]
pub struct PurchaseOrderEvent {
    pub order_id: String,
    pub order_number: String,
    pub market_id: String,
    pub warehouse_id: String,
    pub location_code: String,
    pub vendor_id: String,
    pub order_date: NaiveDate,
    pub expected_date: NaiveDate,
    pub actual_date: NaiveDate,
    pub delayed: bool,
    pub lines: Vec<SupplyLine>,
}

#[derive(Debug, Clone)]
pub struct SupplyLine {
    pub line_id: String,
    pub sku: String,
    pub quantity: i64,
    pub received_quantity: i64,
    pub unit_cost_minor: i64,
    pub currency_code: String,
}

#[derive(Debug, Clone)]
pub struct TransferEvent {
    pub transfer_id: String,
    pub market_id: String,
    pub from_warehouse_id: String,
    pub from_location_code: String,
    pub to_store_id: String,
    pub to_location_code: String,
    pub order_date: NaiveDate,
    pub shipment_date: NaiveDate,
    pub receipt_date: NaiveDate,
    pub lines: Vec<SupplyLine>,
}

#[derive(Debug, Clone)]
pub struct WasteEvent {
    pub event_id: String,
    pub market_id: String,
    pub location_id: String,
    pub location_code: String,
    pub date: NaiveDate,
    pub sku: String,
    pub quantity: i64,
    pub reason_code: String,
    pub store_level: bool,
}

#[derive(Debug, Clone)]
pub struct SignalRow {
    pub dataset: &'static str,
    pub values: BTreeMap<String, String>,
}

/// Dynamic causal/projection rows use a fast table of contract field names.
///
/// Every field name is part of the compiled source contract, so borrowing the
/// static literal avoids allocating and cloning dozens of identical keys for
/// every generated row. Final logical fixtures are converted to ordered maps
/// at their test/publication boundary.
pub type FieldValues = HashMap<&'static str, String, BuildHasherDefault<ContractFieldHasher>>;

/// FNV-1a is sufficient for the small, trusted compile-time field-name set and
/// avoids SipHash dominating hundreds of millions of contract lookups.
#[derive(Debug, Clone)]
pub struct ContractFieldHasher(u64);

impl Default for ContractFieldHasher {
    fn default() -> Self {
        Self(0xcbf2_9ce4_8422_2325)
    }
}

impl Hasher for ContractFieldHasher {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, bytes: &[u8]) {
        for byte in bytes {
            self.0 ^= u64::from(*byte);
            self.0 = self.0.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
}
