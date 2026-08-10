use std::collections::BTreeMap;

use anyhow::{Context, Result};

use crate::catalog::Product;
use crate::config::LoadedConfig;
use crate::deterministic::{round_half_even_f64, stable_integer};
use crate::projection::catalog::local_iso_at;
use crate::simulation::model::FieldValues;
use crate::simulation::store_inventory::StoreVariant;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SelectedVariant {
    pub product_index: usize,
    pub variant_index: usize,
}

#[derive(Debug, Clone)]
pub struct StoreAssortment {
    pub selected_by_store: BTreeMap<String, Vec<SelectedVariant>>,
    pub rows: Vec<FieldValues>,
}

impl StoreAssortment {
    #[must_use]
    pub fn store_inventory_variants(
        &self,
        catalog: &[Product],
    ) -> BTreeMap<String, Vec<StoreVariant>> {
        self.selected_by_store
            .iter()
            .map(|(store_id, selected)| {
                let variants = selected
                    .iter()
                    .map(|position| {
                        let product = &catalog[position.product_index];
                        StoreVariant::from_catalog(
                            product,
                            &product.variants[position.variant_index],
                        )
                    })
                    .collect();
                (store_id.clone(), variants)
            })
            .collect()
    }
}

/// Select store coverage and emit the effective-dated native assortment relation.
pub fn build(config: &LoadedConfig, catalog: &[Product]) -> Result<StoreAssortment> {
    let mut selected_by_store = BTreeMap::new();
    let mut rows = Vec::new();
    let master_seed = config.scenario.identity.master_seed.to_string();
    let start = config.scenario.time.start_date;
    let end = config.scenario.time.end_date;
    for store in &config.scenario.stores {
        let market = config
            .scenario
            .markets
            .iter()
            .find(|row| row.market_id == store.market_id)
            .with_context(|| format!("unknown market {}", store.market_id))?;
        let mut by_category = BTreeMap::<String, Vec<SelectedVariant>>::new();
        for (product_index, product) in catalog.iter().enumerate() {
            if product.market_id != store.market_id {
                continue;
            }
            for variant_index in 0..product.variants.len() {
                by_category
                    .entry(product.category_id.clone())
                    .or_default()
                    .push(SelectedVariant {
                        product_index,
                        variant_index,
                    });
            }
        }
        let mut store_selected = Vec::new();
        for (category_id, mut positions) in by_category {
            positions.sort_by_key(|position| {
                stable_integer(
                    &[
                        &master_seed,
                        "store-assortment",
                        &store.store_id,
                        &catalog[position.product_index].variants[position.variant_index].sku,
                    ],
                    i64::MAX as u64,
                )
            });
            let target = round_half_even_f64(positions.len() as f64 * store.assortment_coverage)
                .max(1.0) as usize;
            for position in positions.into_iter().take(target) {
                let product = &catalog[position.product_index];
                let variant = &product.variants[position.variant_index];
                let valid_from = start.max(variant.launch_date);
                let valid_to = end.min(variant.discontinue_date.unwrap_or(end));
                store_selected.push(position);
                rows.push(values([
                    ("marketKey", store.market_id.clone()),
                    ("storeKey", store.store_id.clone()),
                    ("sku", variant.sku.clone()),
                    ("productCode", product.product_code.clone()),
                    ("departmentId", product.department_id.clone()),
                    ("categoryId", category_id.clone()),
                    ("validFrom", valid_from.to_string()),
                    ("validTo", valid_to.to_string()),
                    ("observedAt", local_iso_at(valid_from, 0, &market.timezone)?),
                    ("active", "true".to_owned()),
                    (
                        "assortmentReason",
                        "deterministic-store-coverage".to_owned(),
                    ),
                ]));
            }
        }
        selected_by_store.insert(store.store_id.clone(), store_selected);
    }
    Ok(StoreAssortment {
        selected_by_store,
        rows,
    })
}

fn values<const N: usize>(entries: [(&'static str, String); N]) -> FieldValues {
    entries.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::build;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::deterministic::sha256_hex;

    #[test]
    fn gulf_mini_assortment_matches_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let assortment = build(&config, &catalog).expect("assortment");
        let fields = contracts::fields("companion", "storeAssortment").expect("fields");
        let normalized = assortment
            .rows
            .iter()
            .map(|row| {
                fields
                    .iter()
                    .map(|field| {
                        row.get(field.as_str())
                            .filter(|value| !value.is_empty())
                            .cloned()
                    })
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        assert_eq!(assortment.rows.len(), 3_201);
        assert_eq!(
            sha256_hex(serde_json::to_string(&normalized).unwrap().as_bytes()),
            "87f73302d4c20135dbad0eb5389200fe9645b05e11b6f1447c711910bd0c8970"
        );
    }
}
