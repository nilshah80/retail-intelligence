# `datagen/` — Synthetic data generator (extract-ready)

**Purpose:** generate one deterministic, internally canonical retail truth and publish it in two
ways:

- `canonical_test` — exact `retail_v2` Parquet for contract/unit/model tests;
- `client_shaped_test/<dialect>` — retailer/platform-style CSV/Parquet/JSONL plus
  coverage/capability manifests and source profiles for the real raw→transform→canonical path.

The truth covers versioned fulfilled demand, exact sales money, demand-to-supply fulfillment
lines and post-sale adjustments; prices/promos; cost receipts; inventory/ATP + batches;
competitors; weather actual/forecast; local events; macro and FX.

**Language:** Python.

**Isolation rule (important):** `datagen/` may depend on **`contracts/` only** — never import
from `ml/` or `api/`, and keep its own dependency file. It is built to be **lifted into its own
repo later**; when that happens it takes a copy of (or a shared package built from) `contracts/`.

**Reference (`[REUSE]`, from the M5 PoC):**
- `scripts/generate_synthetic_extension.py` — demand model (Poisson + template seasonality +
  trend + intermittency/launch gate + pandemic & weather multipliers), price + promo streams.
- `data/ingest_m5.py` — operational-field synthesis formulas (cost from assumed margin, pack/MOQ/
  lead-time hashes, 28-day burn-in stock seed, 28-day rolling-median `promo_flag`).

**For the new PoC:** localize the demand base for Indian categories/festivals, keep the
determinism + immutable-publication + `known_as_of` discipline, add an inventory-consistent event
loop, filtered pre-fulfilment cancellation controls and versioned post-fulfilment
return/refund events, and add the new feeds (competitor, weather, local events, macro, FX,
promotions/segments).

**Dialects required for local acceptance:**

- a generic retailer-shaped extract covering every canonical `[in]` domain;
- a fully synthetic, direct-identifier-free and protected-field-minimized Shopify-shaped extract
  modelling GraphQL/webhook ID parity, signed webhook envelopes, products/variants, locations,
  orders/lines, requested and processed returns, successful/failed refunds, fulfillment status
  transitions, split-money allocations and all named Shopify inventory-state observations;
- synthetic PIM/ERP/WMS/external companion feeds for the domains Shopify does not provide, allowing a
  complete Shopify-led composite test without pretending those records came from Shopify.

Real Shopify/client data never belongs in the local generator or developer laptop.

**Output:** canonical fixtures may enter canonical validation directly. Client-shaped files always
enter immutable raw landing and are normalized/semantically transformed by `ml/data`. Golden
tests compare the generic dialect with the full internal truth, the pure Shopify dialect with its
manifest-declared coverage (`validated_partial`, never a model input), and Shopify plus companion
feeds with the full truth and a full Gate-B pass.

**Spec:** §9 (approach), §11 (output schema).

_No code yet — information only._
