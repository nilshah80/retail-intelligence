# `datagen/` — Synthetic data generator (extract-ready)

**Purpose:** generate every input file the PoC ingests — CSV/Parquet per the `retail_v2` schema
in `contracts/`: demand, prices+promos, cost ledger, inventory + batches, competitor prices,
weather (actual + forecast), local events, macro index, FX rates.

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
determinism + immutable-publication + `known_as_of` discipline, and add the new feeds
(competitor, weather, local events, macro, FX, promotions/segments).

**Output:** files that `ml/`'s `mapped_files` ingest profile maps onto the canonical contract.

**Spec:** §9 (approach), §11 (output schema).

_No code yet — information only._
