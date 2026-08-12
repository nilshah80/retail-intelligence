use std::collections::BTreeMap;
use std::sync::OnceLock;

use anyhow::{Context, Result};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ContractDocument {
    #[allow(dead_code)]
    schema_version: String,
    datasets: BTreeMap<String, Vec<String>>,
}

fn document() -> &'static ContractDocument {
    static DOCUMENT: OnceLock<ContractDocument> = OnceLock::new();
    DOCUMENT.get_or_init(|| {
        serde_json::from_str(include_str!("../contracts/source-fields-v13.json"))
            .expect("embedded source field contract is valid")
    })
}

pub fn fields(source_system: &str, dataset: &str) -> Result<Vec<String>> {
    document()
        .datasets
        .get(&format!("{source_system}/{dataset}"))
        .cloned()
        .with_context(|| format!("missing field contract for {source_system}/{dataset}"))
}

pub fn fields_with_pricing_evidence(
    source_system: &str,
    dataset: &str,
    enabled: bool,
) -> Result<Vec<String>> {
    let mut resolved = fields(source_system, dataset)?;
    if enabled {
        let optional: &[&str] = match (source_system, dataset) {
            ("shopify", "priceHistory") => &["knownAsOf", "provenanceClass", "generationMethod"],
            ("companion", "promotions") => &[
                "knownAsOf",
                "lifecycleStatus",
                "provenanceClass",
                "generationMethod",
            ],
            ("companion", "promotionSkus") => &["knownAsOf", "provenanceClass", "generationMethod"],
            ("companion", "competitorPrices") => &[
                "competitorBrand",
                "competitorModel",
                "competitorGtin",
                "competitorAttributes",
                "availabilityState",
                "evidenceClass",
                "derivationClass",
                "usePurpose",
                "generationMethod",
            ],
            ("companion", "competitorMatches") => &[
                "matchedAttributes",
                "evidenceClass",
                "derivationClass",
                "usePurpose",
                "generationMethod",
            ],
            ("hiddenTruth", "competitorMatchTruth") => &[
                "candidateKey",
                "departmentId",
                "categoryId",
                "referenceAttributes",
                "candidateAttributes",
                "truthLabel",
                "truthSplit",
                "missingAttributeCohort",
                "truthMethod",
                "generationMethod",
            ],
            _ => &[],
        };
        resolved.extend(optional.iter().map(|field| (*field).to_owned()));
        resolved.sort();
        resolved.dedup();
    }
    Ok(resolved)
}

#[must_use]
pub fn dataset_keys() -> Vec<String> {
    document().datasets.keys().cloned().collect()
}

#[must_use]
pub fn snake_case(value: &str) -> String {
    let mut result = String::with_capacity(value.len() + 8);
    for (index, character) in value.chars().enumerate() {
        if character.is_ascii_uppercase() {
            if index > 0 {
                result.push('_');
            }
            result.push(character.to_ascii_lowercase());
        } else {
            result.push(character);
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::{dataset_keys, fields, fields_with_pricing_evidence, snake_case};

    #[test]
    fn frozen_contract_covers_all_python_v13_datasets() {
        assert_eq!(dataset_keys().len(), 78);
        assert_eq!(fields("shopify", "orders").expect("orders").len(), 18);
        assert_eq!(
            fields("companion", "holidays").expect("holidays"),
            [
                "date",
                "kind",
                "marketKey",
                "name",
                "retailBehavior",
                "targetId",
                "targetType",
            ]
        );
        assert_eq!(
            snake_case("fulfillmentStatusHistory"),
            "fulfillment_status_history"
        );
    }

    #[test]
    fn pricing_evidence_fields_are_opt_in_and_sorted_like_python() {
        let legacy =
            fields_with_pricing_evidence("shopify", "priceHistory", false).expect("legacy fields");
        assert!(!legacy.iter().any(|field| field == "knownAsOf"));

        let enriched =
            fields_with_pricing_evidence("shopify", "priceHistory", true).expect("enriched fields");
        assert_eq!(
            enriched,
            [
                "currencyCode",
                "effectiveDate",
                "generationMethod",
                "knownAsOf",
                "price",
                "priceList",
                "priceReason",
                "provenanceClass",
                "sku",
                "variantId",
            ]
        );
    }
}
