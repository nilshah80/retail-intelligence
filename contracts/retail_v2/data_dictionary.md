# `retail_v2` data dictionary

The authoritative field-level contract is
[`schema.yaml`](schema.yaml). This document records cross-entity meanings that
must not be reinterpreted by adapters, ML or API code.

| Term | Meaning |
|---|---|
| `market_id` | Stable operating-market identifier; all regional/location scopes resolve inside it. |
| `location_id` / `store_id` | `locations.location_id` is authoritative; `store_id` is the demand-view alias. |
| `channel_id` | Market-qualified demand/price/promotion channel, orthogonal to location. |
| `known_as_of` | Earliest defensible availability time, not merely when the business event happened. |
| `known_as_of_evidence_grade` | Closed provenance grade explaining which native/extract/landing evidence supports `known_as_of`. |
| money with `semantic: money_minor` | Exact integer minor units paired with currency. |
| `net_price` | Display/feature unit price; never the source-money reconciliation authority. |
| `source_price_path_id` | Provenance identity of an independently observed price path; fan-out copies retain one ID. |
| `geo_scope_*` | One geographic axis inside a market: market, region or location. |
| `merch_scope_*` | Merchandise targeting with `sku > dept > category` precedence. |
| `assortment_calendar` | Active SKU×demand-location×channel window used for zero densification and lifecycle-aware gates. |

Channel-aware demand is mandatory in `retail_v2`. A profile lacking native
channel data can declare one stable default channel with provenance; downstream
transforms never aggregate observed channel distinctions away.
