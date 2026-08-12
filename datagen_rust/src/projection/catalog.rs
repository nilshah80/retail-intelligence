use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

use anyhow::{Context, Result};
use chrono::{Duration, NaiveDate, NaiveDateTime, NaiveTime, TimeZone};
use chrono_tz::Tz;
use rust_decimal::{Decimal, RoundingStrategy};
use unicode_normalization::UnicodeNormalization;

use crate::catalog::{Product, Variant};
use crate::config::{LoadedConfig, Market};
use crate::deterministic::{bc_uuid, shopify_gid, stable_integer};
use crate::projection::LogicalDataset;
use crate::simulation::customers::CustomerPopulation;
use crate::simulation::effects::{event_effect, pandemic_cost_effect};
use crate::simulation::pricing::PriceEngine;

pub fn build_catalog_datasets(
    config: &LoadedConfig,
    catalog: &[Product],
) -> Result<Vec<LogicalDataset>> {
    let mut datasets = Vec::new();
    let mut price_engine = PriceEngine::new();
    let end = config.scenario.time.end_date;
    let start = config.scenario.time.start_date;
    let mut population = CustomerPopulation::new(config);
    let customer_records = population.records(
        config
            .scenario
            .markets
            .iter()
            .map(|market| market.market_id.clone()),
    )?;

    for shop in &config.scenario.source_instances.shopify {
        let market = market(config, &shop.market_id)?;
        let products = catalog
            .iter()
            .filter(|row| row.market_id == shop.market_id)
            .collect::<Vec<_>>();
        let prefix = format!("shopify/{}", shop.shop_id);
        datasets.push(dataset(
            &prefix,
            "shopify",
            "products",
            products
                .iter()
                .map(|product| product_row(market, product, start, end))
                .collect::<Result<_>>()?,
        ));
        datasets.push(dataset(
            &prefix,
            "shopify",
            "productVariants",
            products
                .iter()
                .flat_map(|product| {
                    product
                        .variants
                        .iter()
                        .map(move |variant| (*product, variant))
                })
                .map(|(product, variant)| {
                    variant_row(market, product, variant, start, end, &mut price_engine)
                })
                .collect::<Result<_>>()?,
        ));
        datasets.push(dataset(
            &prefix,
            "shopify",
            "catalogEvents",
            products
                .iter()
                .flat_map(|product| catalog_events(market, product))
                .collect::<Result<_>>()?,
        ));
        datasets.push(dataset(
            &prefix,
            "shopify",
            "priceHistory",
            price_history(config, market, &products, &mut price_engine)?,
        ));
        datasets.push(dataset(
            &prefix,
            "shopify",
            "inventoryItems",
            products
                .iter()
                .flat_map(|product| product.variants.iter())
                .map(|variant| {
                    row([
                        ("id", shopify_inventory_item_id(&shop.market_id, variant)),
                        ("sku", variant.sku.clone()),
                        ("tracked", "true".to_owned()),
                        ("requiresShipping", "true".to_owned()),
                        (
                            "countryCodeOfOrigin",
                            product_country(catalog, variant).to_owned(),
                        ),
                        ("unitCostAmount", money(variant.base_cost)),
                        ("unitCostCurrencyCode", market.currency_code.clone()),
                    ])
                })
                .collect(),
        ));
        let shop_store_ids = shop.store_ids.iter().cloned().collect::<BTreeSet<_>>();
        let mut locations = config
            .scenario
            .stores
            .iter()
            .filter(|store| shop_store_ids.contains(&store.store_id))
            .map(|store| {
                row([
                    ("id", shopify_gid("Location", &store.store_id)),
                    ("name", store.name.clone()),
                    ("active", "true".to_owned()),
                    ("address1", store.address_line1.clone()),
                    (
                        "city",
                        if store.city.is_empty() {
                            market.city.clone()
                        } else {
                            store.city.clone()
                        },
                    ),
                    (
                        "provinceCode",
                        if store.region_code.is_empty() {
                            market.region_code.clone()
                        } else {
                            store.region_code.clone()
                        },
                    ),
                    ("countryCode", market.country_code.clone()),
                    ("zip", store.postcode.clone()),
                    ("timezone", market.timezone.clone()),
                    ("locationType", "STORE".to_owned()),
                ])
            })
            .collect::<Vec<_>>();
        locations.extend(
            config
                .scenario
                .warehouses
                .iter()
                .filter(|warehouse| {
                    warehouse
                        .serves_locations
                        .iter()
                        .any(|store_id| shop_store_ids.contains(store_id))
                })
                .map(|warehouse| {
                    row([
                        ("id", shopify_gid("Location", &warehouse.warehouse_id)),
                        ("name", warehouse.name.clone()),
                        ("active", "true".to_owned()),
                        ("address1", String::new()),
                        ("city", market.city.clone()),
                        ("provinceCode", market.region_code.clone()),
                        ("countryCode", market.country_code.clone()),
                        ("zip", String::new()),
                        ("timezone", market.timezone.clone()),
                        ("locationType", "WAREHOUSE".to_owned()),
                    ])
                }),
        );
        datasets.push(dataset(&prefix, "shopify", "locations", locations));
        datasets.push(dataset(
            &prefix,
            "shopify",
            "customers",
            customer_records
                .iter()
                .filter(|record| {
                    record.market_id == shop.market_id && record.segment_id != "walk-in"
                })
                .map(|record| {
                    row([
                        ("id", shopify_gid("Customer", &record.customer_key)),
                        ("syntheticCustomerKey", record.customer_key.clone()),
                        ("segmentId", record.segment_id.clone()),
                        ("createdAt", record.created_at.clone()),
                        ("state", record.state.clone()),
                        ("email", String::new()),
                        ("phone", String::new()),
                        ("firstName", String::new()),
                        ("lastName", String::new()),
                        ("directIdentifiersPresent", "false".to_owned()),
                    ])
                })
                .collect(),
        ));
    }

    let vendors = vendor_rows(config, catalog)?;
    for company in &config.scenario.source_instances.business_central {
        let legal = config
            .scenario
            .legal_entities
            .iter()
            .find(|row| row.legal_entity_id == company.legal_entity_id)
            .context("BC legal entity")?;
        let market_ids = legal.market_ids.iter().cloned().collect::<BTreeSet<_>>();
        let company_products = market_ids
            .iter()
            .flat_map(|market_id| {
                catalog
                    .iter()
                    .filter(move |product| product.market_id == *market_id)
                    .map(move |product| (market_id.as_str(), product))
            })
            .collect::<Vec<_>>();
        let prefix = format!("business-central/{}", company.company_id);
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "items",
            company_products
                .iter()
                .map(|(market_id, product)| {
                    let vendor = vendors
                        .iter()
                        .find(|row| {
                            row.get("marketCode")
                                .is_some_and(|value| value == *market_id)
                                && row
                                    .get("brandCode")
                                    .is_some_and(|value| value == &product.brand_code)
                        })
                        .context("vendor projection")?;
                    Ok(row([
                        ("vendorId", vendor["id"].clone()),
                        ("vendorNumber", vendor["number"].clone()),
                        ("vendorName", vendor["displayName"].clone()),
                        (
                            "id",
                            bc_uuid("Item", &format!("{market_id}:{}", product.product_code)),
                        ),
                        ("number", product.product_code.clone()),
                        ("displayName", product.title.clone()),
                        ("description", product.description.clone()),
                        ("brandName", product.brand.clone()),
                        ("type", "Inventory".to_owned()),
                        ("itemCategoryCode", product.category_id.clone()),
                        ("baseUnitOfMeasureCode", product.unit_of_measure.clone()),
                        ("costingMethod", product.costing_method.clone()),
                        (
                            "countryRegionOfOriginCode",
                            product.country_of_origin.clone(),
                        ),
                        (
                            "blocked",
                            (product.discontinue_date.is_some_and(|value| value <= end))
                                .to_string(),
                        ),
                        ("introducedDate", product.launch_date.to_string()),
                        (
                            "discontinuedDate",
                            product
                                .discontinue_date
                                .map_or_else(String::new, |value| value.to_string()),
                        ),
                        (
                            "predecessorItemNumber",
                            product.successor_of_product_code.clone(),
                        ),
                    ]))
                })
                .collect::<Result<_>>()?,
        ));
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "itemVariants",
            company_products
                .iter()
                .flat_map(|(market_id, product)| {
                    product
                        .variants
                        .iter()
                        .map(move |variant| (*market_id, *product, variant))
                })
                .map(|(market_id, product, variant)| {
                    let market = market(config, market_id)?;
                    let price = price_engine.extract_price(product, variant, market, start, end)?;
                    Ok(row([
                        (
                            "id",
                            bc_uuid(
                                "ItemVariant",
                                &format!(
                                    "{market_id}:{}:{}",
                                    product.product_code, variant.variant_code
                                ),
                            ),
                        ),
                        (
                            "itemId",
                            bc_uuid("Item", &format!("{market_id}:{}", product.product_code)),
                        ),
                        ("itemNumber", product.product_code.clone()),
                        ("code", variant.variant_code.clone()),
                        ("description", variant.title.clone()),
                        ("sku", variant.sku.clone()),
                        ("barcode", variant.barcode.clone()),
                        ("unitCost", money(variant.base_cost)),
                        ("unitOfMeasureCode", variant.unit_of_measure.clone()),
                        ("measurementValue", variant.measurement_value.to_string()),
                        ("measurementUnit", variant.measurement_unit.clone()),
                        ("unitPrice", money(price)),
                        ("currencyCode", market.currency_code.clone()),
                        (
                            "blocked",
                            (variant.discontinue_date.is_some_and(|value| value <= end))
                                .to_string(),
                        ),
                        ("introducedDate", variant.launch_date.to_string()),
                        (
                            "discontinuedDate",
                            variant
                                .discontinue_date
                                .map_or_else(String::new, |value| value.to_string()),
                        ),
                        (
                            "predecessorItemNumber",
                            product.successor_of_product_code.clone(),
                        ),
                    ]))
                })
                .collect::<Result<_>>()?,
        ));
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "itemLifecycleEvents",
            company_products
                .iter()
                .flat_map(|(market_id, product)| {
                    let selected_market = market(config, market_id).expect("validated market");
                    catalog_events(selected_market, product).map(move |result| {
                        result.map(|mut values| {
                            values.insert("marketCode".to_owned(), (*market_id).to_owned());
                            values
                        })
                    })
                })
                .collect::<Result<_>>()?,
        ));
        let warehouse_ids = company
            .warehouse_ids
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut locations = config
            .scenario
            .warehouses
            .iter()
            .filter(|row| warehouse_ids.contains(&row.warehouse_id))
            .map(|warehouse| {
                let market = market(config, &warehouse.market_id).expect("validated market");
                row([
                    ("id", bc_uuid("Location", &warehouse.warehouse_id)),
                    ("code", warehouse.business_central_location_code.clone()),
                    ("displayName", warehouse.name.clone()),
                    ("marketCode", warehouse.market_id.clone()),
                    ("countryRegionCode", market.country_code.clone()),
                    (
                        "taxAreaCode",
                        market.locale_pack["tax"]["jurisdiction"]
                            .as_str()
                            .unwrap_or_default()
                            .to_owned(),
                    ),
                ])
            })
            .collect::<Vec<_>>();
        if config
            .scenario
            .operations
            .features
            .get("storeInventory")
            .copied()
            .unwrap_or(false)
        {
            let mut stores = config
                .scenario
                .stores
                .iter()
                .filter(|row| {
                    row.legal_entity_id == company.legal_entity_id
                        && !row.business_central_location_code.is_empty()
                })
                .collect::<Vec<_>>();
            stores.sort_by_key(|row| &row.store_id);
            locations.extend(stores.into_iter().map(|store| {
                let market = market(config, &store.market_id).expect("validated market");
                row([
                    ("id", bc_uuid("Location", &store.store_id)),
                    ("code", store.business_central_location_code.clone()),
                    ("displayName", store.name.clone()),
                    ("marketCode", store.market_id.clone()),
                    ("countryRegionCode", market.country_code.clone()),
                    (
                        "taxAreaCode",
                        market.locale_pack["tax"]["jurisdiction"]
                            .as_str()
                            .unwrap_or_default()
                            .to_owned(),
                    ),
                ])
            }));
        }
        datasets.push(dataset(&prefix, "businessCentral", "locations", locations));
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "companyMarketConfiguration",
            market_ids
                .iter()
                .map(|market_id| {
                    let market = market(config, market_id).expect("validated market");
                    row([
                        ("companyId", company.company_id.clone()),
                        ("companyName", company.company_name.clone()),
                        ("legalEntityId", company.legal_entity_id.clone()),
                        ("marketCode", market_id.clone()),
                        ("countryRegionCode", market.country_code.clone()),
                        ("localCurrencyCode", market.currency_code.clone()),
                        (
                            "fiscalYearStartMonth",
                            scalar(&market.locale_pack["fiscalYearStartMonth"]),
                        ),
                        (
                            "taxBasis",
                            market.locale_pack["tax"]["basis"]
                                .as_str()
                                .unwrap_or_default()
                                .to_owned(),
                        ),
                        (
                            "taxJurisdiction",
                            market.locale_pack["tax"]["jurisdiction"]
                                .as_str()
                                .unwrap_or_default()
                                .to_owned(),
                        ),
                    ])
                })
                .collect(),
        ));
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "vendors",
            vendors
                .iter()
                .filter(|row| market_ids.contains(&row["marketCode"]))
                .cloned()
                .collect(),
        ));
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "vendorItemTerms",
            vendor_term_rows(config, catalog)?
                .into_iter()
                .filter(|row| market_ids.contains(&row["marketCode"]))
                .collect(),
        ));
        let mut customer_sequence = 0_usize;
        let customer_rows = customer_records
            .iter()
            .filter(|record| market_ids.contains(&record.market_id))
            .map(|record| {
                customer_sequence += 1;
                row([
                    ("id", bc_uuid("Customer", &record.customer_key)),
                    ("number", format!("C{customer_sequence:014}")),
                    (
                        "displayName",
                        if record.segment_id == "walk-in" {
                            "Walk-in synthetic customer"
                        } else {
                            "Registered synthetic customer"
                        }
                        .to_owned(),
                    ),
                    ("marketCode", record.market_id.clone()),
                    ("segmentCode", record.segment_id.clone()),
                    ("createdAt", record.created_at.clone()),
                    ("email", String::new()),
                    ("phoneNumber", String::new()),
                    ("blocked", (record.state != "ENABLED").to_string()),
                    ("directIdentifiersPresent", "false".to_owned()),
                ])
            })
            .collect();
        datasets.push(dataset(
            &prefix,
            "businessCentral",
            "customers",
            customer_rows,
        ));
    }

    if config.scenario.output.write_hidden_truth {
        datasets.push(LogicalDataset {
            prefix: "_truth".to_owned(),
            source_system: "hiddenTruth".to_owned(),
            dataset: "catalogTruth".to_owned(),
            restricted: true,
            rows: catalog
                .iter()
                .flat_map(|product| {
                    product
                        .variants
                        .iter()
                        .map(move |variant| (product, variant))
                })
                .map(|(product, variant)| {
                    row([
                        ("marketKey", product.market_id.clone()),
                        ("productKey", product.product_key.clone()),
                        ("productCode", product.product_code.clone()),
                        ("productTitle", product.title.clone()),
                        ("brand", product.brand.clone()),
                        ("variantKey", variant.variant_key.clone()),
                        ("variantCode", variant.variant_code.clone()),
                        ("sku", variant.sku.clone()),
                        ("basePrice", money(variant.base_price)),
                        ("baseCost", money(variant.base_cost)),
                        ("currencyCode", variant.currency_code.clone()),
                        ("demandWeight", variant.demand_weight.to_string()),
                        ("elasticity", variant.elasticity.to_string()),
                        ("returnProbability", variant.return_probability.to_string()),
                        ("launchDate", variant.launch_date.to_string()),
                        (
                            "discontinueDate",
                            variant
                                .discontinue_date
                                .map_or_else(String::new, |value| value.to_string()),
                        ),
                        (
                            "predecessorProductCode",
                            product.successor_of_product_code.clone(),
                        ),
                        (
                            "successorProductCode",
                            product.successor_product_code.clone(),
                        ),
                        (
                            "successorLaunchDate",
                            product
                                .successor_launch_date
                                .map_or_else(String::new, |value| value.to_string()),
                        ),
                        ("launchProfile", product.launch_profile.clone()),
                        (
                            "shelfLifeDays",
                            product
                                .shelf_life_days
                                .map_or_else(String::new, |value| value.to_string()),
                        ),
                        (
                            "seasonalityPeakMonth",
                            product.seasonality_peak_month.to_string(),
                        ),
                        (
                            "seasonalityStrength",
                            product.seasonality_strength.to_string(),
                        ),
                    ])
                })
                .collect(),
        });
    }
    Ok(datasets)
}

fn product_row(
    market: &Market,
    product: &Product,
    start: NaiveDate,
    end: NaiveDate,
) -> Result<BTreeMap<String, String>> {
    let product_key = format!("{}:{}", market.market_id, product.product_key);
    let mut tags = Vec::<String>::new();
    for value in [
        &product.department_id,
        &product.category_id,
        &product.catalog_family,
        &product.material,
    ] {
        if !tags.contains(value) {
            tags.push(value.clone());
        }
    }
    Ok(row([
        ("id", shopify_gid("Product", &product_key)),
        ("title", product.title.clone()),
        (
            "handle",
            format!(
                "{}-{}",
                slug(&product.title),
                product.product_code.to_lowercase()
            ),
        ),
        ("descriptionHtml", format!("<p>{}</p>", product.description)),
        (
            "status",
            if product.discontinue_date.is_some_and(|value| value <= end) {
                "ARCHIVED"
            } else {
                "ACTIVE"
            }
            .to_owned(),
        ),
        ("vendor", product.brand.clone()),
        ("productType", product.category_id.clone()),
        ("tags", tags.join("|")),
        (
            "createdAt",
            local_iso_at(product.launch_date, 9, &market.timezone)?,
        ),
        (
            "publishedAt",
            local_iso_at(product.launch_date.max(start), 9, &market.timezone)?,
        ),
        (
            "predecessorProductCode",
            product.successor_of_product_code.clone(),
        ),
        (
            "successorProductCode",
            product.successor_product_code.clone(),
        ),
        ("launchProfile", product.launch_profile.clone()),
        ("launchDate", product.launch_date.to_string()),
        (
            "discontinueDate",
            product
                .discontinue_date
                .map_or_else(String::new, |value| value.to_string()),
        ),
    ]))
}

fn variant_row(
    market: &Market,
    product: &Product,
    variant: &Variant,
    start: NaiveDate,
    end: NaiveDate,
    price_engine: &mut PriceEngine,
) -> Result<BTreeMap<String, String>> {
    let key = format!("{}:{}", market.market_id, variant.variant_key);
    let price = price_engine.extract_price(product, variant, market, start, end)?;
    Ok(row([
        ("id", shopify_gid("ProductVariant", &key)),
        (
            "productId",
            shopify_gid(
                "Product",
                &format!("{}:{}", market.market_id, product.product_key),
            ),
        ),
        ("inventoryItemId", shopify_gid("InventoryItem", &key)),
        ("sku", variant.sku.clone()),
        ("barcode", variant.barcode.clone()),
        ("title", variant.title.clone()),
        ("position", variant.position.to_string()),
        ("weight", variant.weight.to_string()),
        ("weightUnit", variant.weight_unit.clone()),
        ("measurementValue", variant.measurement_value.to_string()),
        ("measurementUnit", variant.measurement_unit.clone()),
        ("price", money(price)),
        ("currencyCode", market.currency_code.clone()),
        ("taxable", "true".to_owned()),
        ("inventoryManagement", "SHOPIFY".to_owned()),
        ("inventoryPolicy", "DENY".to_owned()),
        (
            "option1Name",
            variant
                .options
                .first()
                .map_or("", |value| value.name.as_str())
                .to_owned(),
        ),
        (
            "option1Value",
            variant
                .options
                .first()
                .map_or("", |value| value.value.as_str())
                .to_owned(),
        ),
        (
            "option2Name",
            variant
                .options
                .get(1)
                .map_or("", |value| value.name.as_str())
                .to_owned(),
        ),
        (
            "option2Value",
            variant
                .options
                .get(1)
                .map_or("", |value| value.value.as_str())
                .to_owned(),
        ),
        (
            "option3Name",
            variant
                .options
                .get(2)
                .map_or("", |value| value.name.as_str())
                .to_owned(),
        ),
        (
            "option3Value",
            variant
                .options
                .get(2)
                .map_or("", |value| value.value.as_str())
                .to_owned(),
        ),
        (
            "createdAt",
            local_iso_at(variant.launch_date, 9, &market.timezone)?,
        ),
        (
            "publishedAt",
            local_iso_at(variant.launch_date, 9, &market.timezone)?,
        ),
        (
            "status",
            if variant.discontinue_date.is_some_and(|value| value <= end) {
                "ARCHIVED"
            } else {
                "ACTIVE"
            }
            .to_owned(),
        ),
        ("launchDate", variant.launch_date.to_string()),
        (
            "discontinueDate",
            variant
                .discontinue_date
                .map_or_else(String::new, |value| value.to_string()),
        ),
        (
            "predecessorProductCode",
            product.successor_of_product_code.clone(),
        ),
    ]))
}

fn catalog_events<'a>(
    market: &'a Market,
    product: &'a Product,
) -> impl Iterator<Item = Result<BTreeMap<String, String>>> + 'a {
    let product_key = format!("{}:{}", market.market_id, product.product_key);
    let mut values = vec![Ok(row([
        ("eventKey", format!("{product_key}:introduced")),
        ("eventType", "PRODUCT_INTRODUCED".to_owned()),
        (
            "occurredAt",
            local_iso_at(product.launch_date, 9, &market.timezone).unwrap_or_default(),
        ),
        ("productCode", product.product_code.clone()),
        ("sku", String::new()),
        (
            "predecessorProductCode",
            product.successor_of_product_code.clone(),
        ),
        ("status", "ACTIVE".to_owned()),
    ]))];
    if let Some(day) = product.discontinue_date {
        values.push(local_iso_at(day, 18, &market.timezone).map(|occurred| {
            row([
                ("eventKey", format!("{product_key}:discontinued")),
                ("eventType", "PRODUCT_DISCONTINUED".to_owned()),
                ("occurredAt", occurred),
                ("productCode", product.product_code.clone()),
                ("sku", String::new()),
                (
                    "predecessorProductCode",
                    product.successor_of_product_code.clone(),
                ),
                ("status", "ARCHIVED".to_owned()),
            ])
        }));
    }
    for variant in &product.variants {
        let variant_key = format!("{}:{}", market.market_id, variant.variant_key);
        values.push(
            local_iso_at(variant.launch_date, 10, &market.timezone).map(|occurred| {
                row([
                    ("eventKey", format!("{variant_key}:introduced")),
                    ("eventType", "SKU_INTRODUCED".to_owned()),
                    ("occurredAt", occurred),
                    ("productCode", product.product_code.clone()),
                    ("sku", variant.sku.clone()),
                    (
                        "predecessorProductCode",
                        product.successor_of_product_code.clone(),
                    ),
                    ("status", "ACTIVE".to_owned()),
                ])
            }),
        );
        if let Some(day) = variant.discontinue_date {
            values.push(local_iso_at(day, 18, &market.timezone).map(|occurred| {
                row([
                    ("eventKey", format!("{variant_key}:discontinued")),
                    ("eventType", "SKU_DISCONTINUED".to_owned()),
                    ("occurredAt", occurred),
                    ("productCode", product.product_code.clone()),
                    ("sku", variant.sku.clone()),
                    (
                        "predecessorProductCode",
                        product.successor_of_product_code.clone(),
                    ),
                    ("status", "ARCHIVED".to_owned()),
                ])
            }));
        }
    }
    values.into_iter()
}

fn price_history(
    config: &LoadedConfig,
    market: &Market,
    products: &[&Product],
    engine: &mut PriceEngine,
) -> Result<Vec<BTreeMap<String, String>>> {
    let mut rows = Vec::new();
    for product in products {
        for variant in &product.variants {
            let launch = variant.launch_date.max(config.scenario.time.start_date);
            let stop = variant
                .discontinue_date
                .map_or(config.scenario.time.end_date, |value| {
                    value.min(config.scenario.time.end_date)
                });
            let mut prior = None;
            let mut day = launch;
            while day <= stop {
                let event_cost = event_effect(
                    config,
                    day,
                    &market.market_id,
                    "",
                    &product.department_id,
                    &product.category_id,
                    "",
                )
                .cost;
                let pandemic_cost = pandemic_cost_effect(
                    config,
                    day,
                    &market.market_id,
                    &product.department_id,
                    &product.category_id,
                    &product.catalog_family,
                );
                let (price, phase) = engine.effective_list_price(
                    product,
                    variant,
                    market,
                    day,
                    config.scenario.time.start_date,
                    config.scenario.time.end_date,
                    event_cost * pandemic_cost,
                )?;
                if prior != Some(price) {
                    let mut values = row([
                        (
                            "variantId",
                            shopify_gid(
                                "ProductVariant",
                                &format!("{}:{}", market.market_id, variant.variant_key),
                            ),
                        ),
                        ("sku", variant.sku.clone()),
                        ("effectiveDate", day.to_string()),
                        ("price", money(price)),
                        ("currencyCode", market.currency_code.clone()),
                        ("priceList", "market-retail".to_owned()),
                        (
                            "priceReason",
                            if phase.is_empty() {
                                "regular".to_owned()
                            } else {
                                phase
                            },
                        ),
                    ]);
                    if let Some(evidence) = config.pricing_evidence() {
                        let known_day = day
                            .checked_add_signed(Duration::days(i64::from(
                                evidence.price_known_as_of_lag_days,
                            )))
                            .context("price known-as-of date overflow")?;
                        values.insert(
                            "knownAsOf".to_owned(),
                            local_iso_at(known_day, 0, &market.timezone)?,
                        );
                        values.insert(
                            "provenanceClass".to_owned(),
                            "generated_source_native".to_owned(),
                        );
                        values.insert(
                            "generationMethod".to_owned(),
                            evidence.generation_method.clone(),
                        );
                    }
                    rows.push(values);
                    prior = Some(price);
                }
                day = day.succ_opt().context("date overflow")?;
            }
        }
    }
    Ok(rows)
}

pub fn vendor_rows(
    config: &LoadedConfig,
    catalog: &[Product],
) -> Result<Vec<BTreeMap<String, String>>> {
    let mut rows = Vec::new();
    let mut seen = BTreeSet::new();
    for market in &config.scenario.markets {
        for product in catalog
            .iter()
            .filter(|row| row.market_id == market.market_id)
        {
            if !seen.insert((market.market_id.clone(), product.brand_code.clone())) {
                continue;
            }
            let key = format!("supplier:{}:{}", market.market_id, product.brand_code);
            let number = format!("V{:07}", stable_integer(&[&key], 10_000_000));
            rows.push(row([
                ("id", bc_uuid("Vendor", &key)),
                ("number", number.clone()),
                (
                    "displayName",
                    format!(
                        "Synthetic Approved Distributor {} {number}",
                        market.market_id.to_uppercase()
                    ),
                ),
                ("brandName", product.brand.clone()),
                ("brandCode", product.brand_code.clone()),
                ("marketCode", market.market_id.clone()),
                ("currencyCode", market.currency_code.clone()),
                ("blocked", "false".to_owned()),
                (
                    "observedAt",
                    local_iso_at(config.scenario.time.start_date, 8, &market.timezone)?,
                ),
            ]));
        }
    }
    Ok(rows)
}

pub fn vendor_term_rows(
    config: &LoadedConfig,
    catalog: &[Product],
) -> Result<Vec<BTreeMap<String, String>>> {
    let mut rows = Vec::new();
    let mut seen = BTreeSet::new();
    for market in &config.scenario.markets {
        for product in catalog
            .iter()
            .filter(|row| row.market_id == market.market_id)
        {
            let identity = (
                market.market_id.clone(),
                product.brand_code.clone(),
                product.category_id.clone(),
            );
            if !seen.insert(identity) {
                continue;
            }
            let key = format!("supplier:{}:{}", market.market_id, product.brand_code);
            rows.push(row([
                ("vendorId", bc_uuid("Vendor", &key)),
                ("marketCode", market.market_id.clone()),
                ("categoryId", product.category_id.clone()),
                ("minimumOrderQuantity", "12".to_owned()),
                ("orderMultiple", "6".to_owned()),
                (
                    "leadTimeDays",
                    scalar(&config.scenario.operations.inventory["supplierLeadTimeDays"]),
                ),
                (
                    "leadTimeStdDevDays",
                    scalar(&config.scenario.operations.inventory["supplierLeadTimeJitterDays"]),
                ),
                (
                    "capacityUnitsPerMonth",
                    (2000 + stable_integer(&[&key], 3000)).to_string(),
                ),
                ("paymentTermsCode", "NET30".to_owned()),
            ]));
        }
    }
    Ok(rows)
}

fn dataset(
    prefix: &str,
    source_system: &str,
    dataset: &str,
    rows: Vec<BTreeMap<String, String>>,
) -> LogicalDataset {
    LogicalDataset {
        prefix: prefix.to_owned(),
        source_system: source_system.to_owned(),
        dataset: dataset.to_owned(),
        restricted: source_system == "hiddenTruth",
        rows,
    }
}

fn row<const N: usize>(values: [(&str, String); N]) -> BTreeMap<String, String> {
    values
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value))
        .collect()
}

fn market<'a>(config: &'a LoadedConfig, market_id: &str) -> Result<&'a Market> {
    config
        .scenario
        .markets
        .iter()
        .find(|row| row.market_id == market_id)
        .with_context(|| format!("unknown market {market_id}"))
}

fn product_country<'a>(catalog: &'a [Product], variant: &Variant) -> &'a str {
    catalog
        .iter()
        .find(|row| {
            row.variants
                .iter()
                .any(|candidate| candidate.variant_key == variant.variant_key)
        })
        .map_or("", |row| row.country_of_origin.as_str())
}

fn shopify_inventory_item_id(market_id: &str, variant: &Variant) -> String {
    shopify_gid(
        "InventoryItem",
        &format!("{market_id}:{}", variant.variant_key),
    )
}

pub(crate) fn local_iso_at(day: NaiveDate, hour: u32, timezone: &str) -> Result<String> {
    let tz = Tz::from_str(timezone).with_context(|| format!("timezone {timezone}"))?;
    let local = NaiveDateTime::new(
        day,
        NaiveTime::from_hms_opt(hour.min(23), 0, 0).context("valid hour")?,
    );
    let value = tz
        .from_local_datetime(&local)
        .single()
        .or_else(|| tz.from_local_datetime(&local).earliest())
        .context("local timestamp")?;
    Ok(value.to_rfc3339())
}

fn slug(value: &str) -> String {
    let ascii = value
        .replace('&', " and ")
        .nfkd()
        .filter(|character| character.is_ascii())
        .collect::<String>()
        .to_lowercase();
    let mut result = String::new();
    let mut separator = false;
    for character in ascii.chars() {
        if character.is_ascii_lowercase() || character.is_ascii_digit() {
            result.push(character);
            separator = false;
        } else if !separator && !result.is_empty() {
            result.push('-');
            separator = true;
        }
    }
    result.trim_matches('-').to_owned()
}

fn money(value: Decimal) -> String {
    let mut result = value.round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
    result.rescale(2);
    result.to_string()
}

fn scalar(value: &serde_json::Value) -> String {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::build_catalog_datasets;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::deterministic::sha256_hex;
    use crate::projection::LogicalDataset;

    fn digest(dataset: &LogicalDataset) -> String {
        let fields = contracts::fields(&dataset.source_system, &dataset.dataset).expect("fields");
        let rows = dataset
            .rows
            .iter()
            .map(|row| {
                fields
                    .iter()
                    .map(|field| row.get(field).filter(|value| !value.is_empty()).cloned())
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        sha256_hex(serde_json::to_string(&rows).expect("rows").as_bytes())
    }

    fn sorted_digest(dataset: &LogicalDataset) -> String {
        let fields = contracts::fields(&dataset.source_system, &dataset.dataset).expect("fields");
        let mut rows = dataset
            .rows
            .iter()
            .map(|row| {
                fields
                    .iter()
                    .map(|field| row.get(field).filter(|value| !value.is_empty()).cloned())
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        rows.sort_by(|left, right| {
            for (left_value, right_value) in left.iter().zip(right) {
                let ordering = match (left_value, right_value) {
                    (Some(left), Some(right)) => left.cmp(right),
                    (Some(_), None) => std::cmp::Ordering::Less,
                    (None, Some(_)) => std::cmp::Ordering::Greater,
                    (None, None) => std::cmp::Ordering::Equal,
                };
                if !ordering.is_eq() {
                    return ordering;
                }
            }
            std::cmp::Ordering::Equal
        });
        sha256_hex(serde_json::to_string(&rows).expect("rows").as_bytes())
    }

    #[test]
    fn gulf_catalog_source_rows_match_retained_python_run() {
        let config =
            LoadedConfig::load("../datagen/configs/gulf-oil-india-ten-year.yaml").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let datasets = build_catalog_datasets(&config, &catalog).expect("projections");
        let expected = BTreeMap::from([
            (
                ("shopify/gulf-in", "products"),
                (
                    73,
                    "3047695611e3e5d2b8fafb7a4174944ee4b522f6038ce9c83007bfcca79e7e94",
                ),
            ),
            (
                ("shopify/gulf-in", "productVariants"),
                (
                    292,
                    "a810c3a3483e889838226cb3a3155577ec2297f0a24f050e732bdd0fb83908b9",
                ),
            ),
            (
                ("shopify/gulf-in", "inventoryItems"),
                (
                    292,
                    "d0de051f7b25e1ec669d827204a293bc2ee20cb69f5ca813c9cc880e908e2617",
                ),
            ),
            (
                ("shopify/gulf-in", "locations"),
                (
                    19,
                    "4a7ff971416acf47cea3026f80c451c2ac1a1cef1e7f4ef3ca23ddcf565c0de8",
                ),
            ),
            (
                ("business-central/bc-gulf-in", "items"),
                (
                    73,
                    "ab0dc59ac1cb84927eb15824751a99eb752b8310e58ea74c850befd10c8b48fb",
                ),
            ),
            (
                ("business-central/bc-gulf-in", "itemVariants"),
                (
                    292,
                    "2c5b7316a062dec92bbef1cf1dd511068dbb21666316537e96be62318358c581",
                ),
            ),
            (
                ("business-central/bc-gulf-in", "locations"),
                (
                    19,
                    "64430e5a05eae439d71a3c46ab416af192e928b440c800d9ce4f20384be42ea8",
                ),
            ),
            (
                ("business-central/bc-gulf-in", "vendors"),
                (
                    1,
                    "d729f4e1896a3398b2b5bf696d499df5868a3c62161cb0f48cde028514362736",
                ),
            ),
            (
                ("business-central/bc-gulf-in", "vendorItemTerms"),
                (
                    16,
                    "ef94f8799a4cc5af20f0a711d5f8db1bee304776da044ffc9bdde3ab571ed048",
                ),
            ),
            (
                ("_truth", "catalogTruth"),
                (
                    292,
                    "c42ebd520d1cd84d5fcf0611dac1f82615e671d61a2e4fa121cae04055490680",
                ),
            ),
        ]);
        for ((prefix, name), (rows, expected_digest)) in expected {
            let dataset = datasets
                .iter()
                .find(|row| row.prefix == prefix && row.dataset == name)
                .unwrap_or_else(|| panic!("missing {prefix}/{name}"));
            assert_eq!(dataset.rows.len(), rows, "{prefix}/{name} row count");
            assert_eq!(digest(dataset), expected_digest, "{prefix}/{name} digest");
        }
        for (prefix, name, rows, expected_digest) in [
            (
                "shopify/gulf-in",
                "catalogEvents",
                365,
                "db15ad9bf672d88de1222f0df1aadceeb2787ae0dd878bba50e50795cd0e6330",
            ),
            (
                "shopify/gulf-in",
                "priceHistory",
                9_999,
                "81d4be5ee2880dda768e2ea80cf64bb9b02569ebde2120cb66d1734436c5c79e",
            ),
            (
                "business-central/bc-gulf-in",
                "itemLifecycleEvents",
                365,
                "7edba13616040a307c852b4ef6c262d2c5016abbd4b22cf844b5a4bc564c255e",
            ),
            (
                "shopify/gulf-in",
                "customers",
                45_969,
                "30cf7326ad0829cbc4dfdc92a5d01186a03396695c2a877a7e529e11a2d1b28e",
            ),
            (
                "business-central/bc-gulf-in",
                "customers",
                45_970,
                "2bdbec0fd9e96a775aed217ce745be897760ce235cc4ec1da4817181daa2e793",
            ),
        ] {
            let dataset = datasets
                .iter()
                .find(|row| row.prefix == prefix && row.dataset == name)
                .unwrap_or_else(|| panic!("missing {prefix}/{name}"));
            assert_eq!(dataset.rows.len(), rows, "{prefix}/{name} row count");
            assert_eq!(
                sorted_digest(dataset),
                expected_digest,
                "{prefix}/{name} sorted digest"
            );
        }
    }
}
