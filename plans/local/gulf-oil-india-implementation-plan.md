# Gulf Oil India Implementation Plan — Lubricants Tenant Datagen and Source Onboarding

_Companion to `plans/local/plan.md`, `plans/local/tasks.md`,
`plans/local/phase4-implementation-plan.md`, and `plans/local/phase5-implementation-plan.md`._
_Source authority: `datagen/README.md`, `datagen/src/retail_datagen/config.py`
(`retail-source-config/v13`), and `datagen/src/retail_datagen/catalog_packs.py`
(catalog pack `2026.6`)._
_Ingestion authority: `contracts/profiles/profile.schema.json`
(`retail-source-profile/v1`) and `ingestion/src/retail_ingestion/profiles/retail_datagen.yaml`._
_Data authority: `contracts/retail_v2/schema.yaml`, `contracts/staging/staging-v2.yaml`, and the
explicitly selected immutable publication._
_Validation authority: `contracts/validation-policy.yaml`; repository CI remains prohibited._

**Revision 1 — 2026-08-06. DRAFT FOR REVIEW. NO WORK PACKAGE IS AUTHORIZED UNTIL `GOI-0` PASSES.
`GOI-0` IS A CLIENT-EVIDENCE GATE, NOT AN ENGINEERING PACKAGE.**

This plan adds a second tenant scenario — Gulf Oil Lubricants India — to the existing generator and
ingestion stack. It is deliberately narrower than Phase 4 or Phase 5: no new engine, no new model,
no new screen, no new canonical entity. The whole deliverable is one catalog-vocabulary extension
inside `datagen/`, one Gulf scenario configuration, one ingestion source profile, and the evidence
that the resulting publication passes the same Gate A/Gate B contract the Northstar retail tenant
passes today.

The plan exists because the naive framing — "it is only a config change" — is false in two specific
places, and both were verified against the code rather than assumed:

1. **The option vocabulary is closed.** `SUPPORTED_OPTION_DIMENSIONS`
   (`datagen/src/retail_datagen/catalog_packs.py:24`) and `_OPTION_VALUES`
   (`catalog_packs.py:545`) admit no viscosity grade and no litre/kilogram pack size. Config
   validation rejects any `optionValues` name outside that pool
   (`datagen/src/retail_datagen/config.py:1118`). A lubricant SKU *is* grade × pack, so Gulf cannot
   be expressed at all until this is extended. This is the one hard blocker.
2. **The ingestion source profile is scenario-bound, not generic.**
   `ingestion/src/retail_ingestion/profiles/retail_datagen.yaml` hard-codes `extractWindow`
   (`2016-07-28` → `2026-07-28`), all six Northstar `sourceInstances` with their
   `logicalPathPrefix`/`sourceMarketId`/`marketId`/currency/timezone, and `locationOverrides` keyed
   to literal Shopify location GIDs. A Gulf run under this profile fails at Gate A.

Everything else verified clean. There is no hard-coded department, category, or tax class anywhere
in `ingestion/`, `ml/`, `api/`, or `db/` logic — the only occurrences are docstrings
(`ml/src/retail_ml/inventory_run/build.py:1707`,
`db/migrations/versions/0013_sku_dimension_display_names.py:4`) and test fixtures. `retail_v2`
carries generic scopes (`merch_scope_type: [sku, dept, category]`,
`locations.type: [store, online, dc, 3pl]`). Option dimensions ride the generic
`option1Name`…`option3Value` columns in the Shopify lane and `code`/`description` in Business
Central, so extending the vocabulary changes **no downstream schema**.

The consequence, stated plainly so it is not overclaimed later: **code changes land only in
`datagen/`; one new profile YAML lands in `ingestion/`; `ml/`, `api/`, `db/`, and `ui/` code is
untouched.** The routine per-publication artifacts (`contracts/ml/expected-pin.json`, Decision-#73
selection records) are regenerated exactly as they are for any new run.

---

## 0 · Recommendation, status, and approval boundary

### 0.1 Recommended order

1. Clear `GOI-0`: obtain the client-confirmed Gulf category, product-line, grade, pack, and price
   list. The taxonomy in §8 is a **proposal built from public brand knowledge and is not evidence**.
   No catalog code is written against an unconfirmed SKU list.
2. Resolve `GOI-D1` (topology framing) and `GOI-D2` (source-system framing) in writing. Both change
   the size of the work by an order of magnitude and neither is reversible cheaply after the first
   publication.
3. Extend the catalog vocabulary and the India locale tax treatment in `datagen/` only, behind a
   catalog-pack version bump, with the Northstar preset byte-stable.
4. Author the Gulf scenario configuration through the Config Builder, not by hand.
5. Author the Gulf ingestion source profile and prove it on a small fixture before any long run.
6. Generate a short showcase horizon first, take it end to end through Gate A/Gate B/publication,
   and only then commit to the long-horizon run.
7. Publish, select, and pin the Gulf publication as a **second, parallel** lineage. Do not
   supersede or repoint the Northstar retail lineage.
8. Assess forecast/ML viability against the Gulf publication as a separate, explicitly gated
   question. It is not a deliverable of this plan.

### 0.2 Why this is a tenant onboarding, not a phase

Phases 3–5 move the *capability* frontier: a new model, a new engine, new screens, new canonical
semantics. This plan moves the *tenant* frontier and deliberately holds capability constant. The
success criterion is that a Gulf publication is indistinguishable, to every downstream consumer,
from a Northstar publication in every respect except its data. If any package here finds itself
editing `ml/`, `api/`, `db/`, or `ui/` code, that is a signal the isolation boundary has been
breached and the package must stop and escalate, not work around it.

### 0.3 Inherited gates from the retail track

Gulf work does not clear, bypass, or inherit the retail track's open gates:

- Phase 3 forecast authorization is NO-GO after Review #2; no accepted forecast exists under the
  repaired authority.
- Phase 5 is a draft plan; `P5-0`, the temporal-evidence gates, and `P5-1P` are unpassed.

Therefore: a Gulf **source publication** is achievable under this plan. A Gulf **forecast** or
**pricing recommendation** is not, and must not be represented as achievable, until the retail
track's own authorization is repaired. If the Gulf requirement is pricing intelligence, that
dependency sits on the critical path and belongs to Phase 5, not here.

### 0.4 Workstream states

| Workstream | State |
|---|---|
| Client catalog evidence | **blocked** — `GOI-0` |
| Topology and source-system framing | **undecided** — `GOI-D1`, `GOI-D2` |
| Catalog vocabulary extension | ready after `GOI-0` |
| India lubricant tax treatment | ready after `GOI-0` |
| Gulf scenario configuration | ready after vocabulary extension |
| Gulf ingestion profile | ready after scenario ids are frozen |
| Publication and selection | ready after fixture proof |
| Forecast/ML on Gulf data | **out of scope** — see §0.3 |

### 0.5 Non-negotiable invariants

1. **Isolation holds.** `datagen/` imports no `contracts/`, `ingestion/`, `ml/`, or `api/` module,
   and emits no canonical `retail_v2` terminology. `tools/check_import_boundaries.py` stays green.
2. **The Northstar preset does not move.** Every checked-in retail config must produce a
   byte-identical catalog and an unchanged config hash after the vocabulary extension. If the
   extension moves the Northstar run id, the extension is wrong.
3. **Catalog-pack version is the change carrier.** Any change to `_OPTION_VALUES`,
   `_FAMILY_BEHAVIOUR`, `PACK_COUNTS`, or `FAMILY_MEASUREMENTS` bumps `CATALOG_PACK_VERSION`
   (`catalog_packs.py:21`) and is recorded in the resolved config the run embeds.
4. **Two lineages, never merged.** Gulf and Northstar publications are separate immutable lineages
   with separate selections. No Gulf artifact supersedes a retail artifact and no shared pin file
   is repointed in place.
5. **Brands are reference identities only.** Gulf product-line names are used exactly as Castrol,
   Shell, Mobil, and Valvoline already are at `catalog_packs.py:471`: recognizable catalog
   identities attached to wholly synthetic prices, costs, volumes, and demand
   (`catalog_packs.py:465`). No generated observation is ever presented as a real Gulf commercial
   fact.
6. **No repository CI.** Validation runs through `tools/dev.py` per
   `contracts/validation-policy.yaml`.
7. **Unconfirmed data is not shipped.** Any SKU, grade, pack, or price not present in the client
   evidence pack is either omitted or explicitly flagged as synthetic filler in the resolved
   config. It is never silently presented as Gulf's assortment.

---

## 1 · Verified starting point

### 1.1 What datagen publishes today

Generator `0.16.0`, source spec `retail-source-config/v13`
(`datagen/src/retail_datagen/__init__.py:18`). One run publishes four lanes plus a manifest,
a resolved config, a source schema, and a single all-source DuckDB mirror:

| Lane | Representative datasets |
|---|---|
| `shopify/<shop>/` | products, product_variants, orders, order_lines, price_history, inventory_items/levels, fulfillments, fulfillment status history, returns, refunds, tax_lines, catalog_events, webhook HMAC fixtures |
| `business-central/<company>/` | items, item_variants, item_ledger_entries, item_cost_layers, item_batches, purchase/transfer orders and shipments, warehouse receipts, inventory and store_inventory snapshots, stockout/waste/transfer events, supply_terms, inbound_status_events, vendors, vendor_item_terms, supplier_performance, supplier_capacity_confirmations |
| `companion/<market>/` | store_assortment, competitor_prices, competitor_matches, promotions, promotion_skus, fx_rates, holidays, local_events, weather actuals/forecasts, macro_index, pandemic timeline/signals, service_lanes, allocation demand/supply pools |
| `_truth/` | restricted demand factors, catalog truth, inventory constraint truth, competitor match truth, source event crosswalk |

The Gulf tenant reuses all of it unchanged. No new dataset is proposed by this plan.

### 1.2 Verified generic downstream (no change required)

Confirmed by search across `ingestion/`, `ml/`, `api/`, `db/`, `ui/`:

- **No taxonomy coupling.** Zero references to any department or category slug in executable code.
  The four hits are two docstrings and two test fixtures.
- **No `taxCategory` / `tax_category` reference downstream at all.** The GST class is consumed
  entirely inside `datagen/`.
- **Generic canonical scopes.** `contracts/retail_v2/schema.yaml:267` and `:444` use
  `merch_scope_type: [sku, dept, category]`; `:210`, `:373`, `:475` use
  `geo_scope_type: [market, region, location]`; `:142` uses
  `locations.type: [store, online, dc, 3pl]`.
- **Generic option carriage.** Shopify variants expose `option1Name`/`option1Value` …
  `option3Name`/`option3Value`; Business Central variants expose `code`, `description`,
  `measurementUnit`, `measurementValue`, `unitOfMeasureCode`. Adding a viscosity dimension adds
  **no column** anywhere.
- **Pack semantics already have a home.** Litre/kilogram content lands in
  `measurementUnit`/`measurementValue`, already covered by the profile's `quantityPolicy`
  derivation rule.
- **Migration 0013 is generic.** It adds display-name columns; the values come from canonical data.
- **UI scenario values are test-only.** `india-west`/`us-new-york` appear solely in `.test.tsx`
  fixtures.
- **CLI already parameterized.** `--source-profile` is a flag on `gate-a`, `stage`, `transform`,
  `gate-b`, `publish`, `run`, and `bench` (`ingestion/src/retail_ingestion/cli.py:98` onward) and is
  plumbed through `tools/dev.py:3541` onward. `tools/dev.py datagen --config` accepts an override
  at `tools/dev.py:3300`.

### 1.3 Scenario-bound artifacts that must be authored

- **`ingestion/src/retail_ingestion/profiles/retail_datagen.yaml`** — `profileId`
  `retail-datagen-multi-source`, `profileVersion` `1.3.0`. Scenario-bound content: `extractWindow`
  dates; six `sourceInstances` keyed to `northstar-in`/`northstar-us`/`bc-northstar-*`/
  `india-mumbai`/`us-new-york` with their `logicalPathPrefix`, `sourceMarketId` → `marketId`
  mapping, `currencyCode`, and `timezone`; and `locationOverrides` keyed to literal Shopify location
  GIDs. A Gulf run has none of these ids. **A new profile document is required.** The ~360-line
  `datasets` block carries over unchanged because the same generator emits the same dataset ids.
- **`contracts/ml/expected-pin.json`** — pins exact snapshot, Gate A, Gate B, publication, and
  retention fingerprints. Regenerated per publication via `tools/build_expected_pin.py`.
- **Decision-#73 selection records** under `contracts/evidence/publication-selections/` —
  candidate → approved → active, per capability, per lineage.
- **`tools/dev.py:3043`** — `command_config_hash` hard-codes the Northstar config path with no
  override. Minor; either parameterize it or validate the Gulf config through the datagen CLI
  directly.

### 1.4 Blocking catalog-vocabulary gaps

| Gap | Location | Effect on Gulf |
|---|---|---|
| No viscosity/grade dimension | `catalog_packs.py:24` | SKU identity cannot be expressed |
| `packSize` values are Single / Pack of 2 / Pack of 6 / Family pack | `catalog_packs.py:545` | No 500 ml, 1 L, 5 L, 20 L, 26 L, 210 L, 18 kg |
| `PACK_COUNTS` is a 4-entry unit map | `catalog_packs.py:58` | Net content per pack cannot be derived |
| `FAMILY_MEASUREMENTS` has one automotive-oils entry (ML/1000) | `catalog_packs.py:38` | Grease (kg), coolant, AdBlue lack measurement bases |
| Only 4 automotive families in a fixed 41-family set | `catalog_packs.py:113` | 16 Gulf categories collapse onto shared price bands, shelf life, and Castrol/Shell reference products |
| `catalogFamily` must exist in **every** configured market's pack | `config.py:917` | Gulf families must be added to `IN` at minimum |
| `taxCategory` is a closed 12-value list | `config.py:900` | `automotive` is present and usable; a `lubricants` class would require extending it |
| India `automotive` GST is `0.28` | `locale_packs.py`, `IN.tax.categoryRates` | Lubricants are 18%; every Gulf net/gross figure is wrong until corrected |

Two constraints that bound the design rather than block it:

- **Three option dimensions maximum.** `generator.py:921`–`:926` writes `option1`…`option3` and
  silently drops the rest. No validator catches a fourth. Grade × pack = 2, so Gulf fits, but the
  budget must be stated in the config review.
- **`variantDefinitions` must contain at least `variantsPerProduct` rows** for its market
  (`config.py:1076`), and every `optionValues` name must exist in the pack pool
  (`config.py:1118`).

### 1.5 Business-model mismatch

Gulf Oil Lubricants India is a lubricant marketer with a distributor-led B2B2C chain: plants and
depots → distributors → retailers, mechanics, workshops, fleets, and OEMs. The generator models a
multi-category retailer that owns its stores and warehouses. `SUPPORTED_CHANNEL_TYPES` is
`{store, online, marketplace}` (`config.py:31`) — there is no distributor, OEM, institutional, or
industrial channel — and the customer model is B2C-shaped (`openingRegisteredCustomers`,
`guestCheckoutRate`, `annualChurnRate`).

This is `GOI-D1`. It is the single largest scope determinant in the plan and must be decided before
any configuration is authored.

### 1.6 Segment-population risk at single-market scale

`MIN_SEGMENT_SERIES = 25` (`ml/src/retail_ml/models/reconciliation.py:33`) gates segment-level
reconciliation and cold-start blending. A single-market Gulf scenario with a small number of
distributor locations can produce segments below that floor, which yields fallbacks and refusals
rather than results. This is a **scenario-sizing constraint, not a code defect**, and it is why §7
requires the SKU × location grid to be sized against the floor before the long run, not after.

### 1.7 Reusable assets

- The complete `datasets` block of the existing ingestion profile.
- The India locale pack: GST-inclusive basis, CGST/SGST/IGST components, ₹ price endings, fiscal
  year starting April, tropical-monsoon climate with `monsoonMonths: [6,7,8,9]`, reviewed Diwali
  and Holi tables, and the `diwali-season` sale window.
- The phased-event machinery (`events`, `promotions`, `pandemics`) with `costMultiplier`,
  `leadTimeMultiplier`, and `inventoryLossPct`, which models base-oil and crude cost shocks without
  new code.
- The Phase 4 multi-echelon apparatus: service lanes, spill lanes, transit days, shortfall events,
  transfer and inbound status histories.

---

## 2 · Authority, scope, and non-goals

### 2.1 Authority hierarchy

1. Client-confirmed Gulf catalog evidence (`GOI-0`) — authoritative for every product fact.
2. `contracts/profiles/profile.schema.json` — authoritative for the ingestion profile shape.
3. `datagen/src/retail_datagen/config.py` — authoritative for scenario validity.
4. `contracts/retail_v2/schema.yaml` — authoritative for canonical meaning.
5. This plan — authoritative for sequencing and gates only.

Where the client evidence and this plan's §8 proposal disagree, the client evidence wins and §8 is
amended.

### 2.2 In scope

- Catalog-vocabulary extension in `datagen/` (option dimensions, option values, pack counts,
  measurement bases, Gulf catalog families).
- India lubricant tax-rate correction.
- One Gulf scenario configuration, authored in the Config Builder.
- One Gulf ingestion source profile.
- Fixture proof, short-horizon publication, then long-horizon publication.
- Gate A, Gate B, readiness, publication, selection, and pin for the Gulf lineage.
- Regression evidence that the Northstar lineage is unmoved.

### 2.3 Explicit non-goals

- Any forecast, price-response, elasticity, replenishment, or allocation **result** on Gulf data.
- New channel types, secondary-sales grain, distributor schemes, rebates, or claim settlement.
- A SAP-shaped source profile or adapter.
- Any new canonical entity, staging envelope, or Gate rule.
- Any change to `ml/`, `api/`, `db/`, or `ui/` code.
- Any new screen, or any change to an approved screen matrix.
- Superseding, retiring, or repointing the Northstar retail lineage.

### 2.4 Artifact retention

Retain per Gulf run: resolved config (YAML and JSON), config hash, catalog-pack version, generator
version, execution profile, source-run manifest, source schema, Gate A and Gate B evidence, the
readiness verdict, the publication manifest, selection records, peak memory, per-stage wall time,
and row counts. Retain the client evidence pack from `GOI-0` alongside the scenario config, because
it is the only justification for the catalog content.

---

## 3 · Target architecture

### 3.1 End-to-end flow

```text
client catalog evidence (GOI-0)
  → catalog-pack extension (datagen, version-bumped)
  → Gulf scenario config (Config Builder → YAML + JSON)
  → datagen generate → shopify/ + business-central/ + companion/ + _truth/ + manifest
  → land (immutable snapshot)
  → Gate A  [Gulf source profile]
  → adapters → standardized staging → source-neutral transforms
  → retail_v2 candidate → Gate B → readiness
  → curated Parquet/DuckDB publication
  → Decision-#73 candidate → approved → active selection
  → expected-pin (Gulf lineage)
  ┈┈ stop. ML/API/UI consumption is out of scope (§0.3).
```

### 3.2 Tenant topology mapping

Under `GOI-D1` option A (recommended):

| Gulf entity | Generator entity | Canonical `locations.type` |
|---|---|---|
| Blending plant | `warehouse` | `dc` |
| Regional depot / C&F | `warehouse` | `dc` |
| Distributor | `store` | `store` |
| Bazaar-trade sell-out | `channel` type `store` | `store` |
| E-commerce / D2C | `channel` type `online` | `online` |
| Marketplace | `channel` type `marketplace` | `online` |

`warehousePriority` on each distributor expresses depot preference; `servesLocations` on each depot
expresses its territory; `primaryLaneTransitDays` and `spillLaneTransitDays` express the primary
and overflow lanes. Every Phase 4 mechanic — days of cover, lane resolution, shortfall events,
transfer history — applies unchanged.

The vocabulary is imprecise: a "store" is a distributor. That imprecision must be recorded in the
scenario description and in any demo narration, because the word appears in canonical data and on
screen.

### 3.3 Catalog model

Four departments and sixteen categories replace the ten-department retail hierarchy for this
tenant. Departments and categories are fully editable in the Config Builder
(`datagen/config-builder.html:13170`), so the hierarchy itself needs no code.

Per-category economics — `targetMargin`, `elasticityMin`/`elasticityMax`, `seasonalityPeakMonth`,
`seasonalityStrength`, `costingMethod`, `baseReturnRate` — are category-level config fields, so
lubricant economics (thin CV-oil margin, near-zero returns, FIFO on shelf-life-bound fluids) are
expressible without touching a family.

What a family still supplies, and therefore what the extension must add: reference product
identities, the market price band, the `categoryCode` SKU segment, `shelfLifeDays`, the default
option dimensions, and the measurement basis.

### 3.4 SKU identity and option budget

```
product line   = brand line + viscosity grade      e.g. Gulf Superfleet XLD 15W-40
sellable SKU   = product line × pack size          e.g. …15W-40, 20 L
option budget  = 2 of 3 (viscosity, packSize)
```

`productCode` must match `^[A-Z][A-Z0-9-]{2,39}$` (`config.py:28`); `brandCode` must match
`[A-Z0-9]{2,8}` (`config.py:1013`). Net content per pack flows into
`measurementUnit`/`measurementValue` from the extended `PACK_COUNTS` and `FAMILY_MEASUREMENTS`.

### 3.5 Seasonality and demand drivers

Expressed entirely through existing config surfaces:

| Driver | Surface |
|---|---|
| Monsoon oil-change surge | category `seasonalityPeakMonth`/`Strength`, IN climate `monsoonMonths` |
| Kharif / Rabi tractor-oil peaks | `events` with dated `demandMultiplier`, category-scoped |
| Diwali two-wheeler servicing | IN reviewed holiday table + `diwali-season` sale window + `promotions` |
| Freight-cycle CV demand | `events` with channel and category scope |
| Base-oil / crude cost shocks | phased `events`/`pandemics` with `costMultiplier`, `leadTimeMultiplier` |
| Distributor scheme periods | `promotions` with `discountPct` + `demandMultiplier` |

### 3.6 Source-instance and profile mapping

Under `GOI-D2` option A (recommended): retain Shopify and Business Central as **source shapes**, not
claims about Gulf's real systems. One market means three source instances:

| `sourceSystem` | `sourceInstance` | `logicalPathPrefix` | capability |
|---|---|---|---|
| `shopify` | `gulf-in` | `shopify/gulf-in/` | `commerce` |
| `businessCentral` | `bc-gulf-in` | `business-central/bc-gulf-in/` | `operations` |
| `companion` | `india-<market>` | `companion/india-<market>/` | `external_signals` |

`publicationRequirements.requiredCapabilities` stays `[commerce, operations, external_signals]`.
The profile must carry the Gulf `extractWindow`, and its `locationOverrides` must be regenerated
against the Gulf run's actual location keys or omitted entirely.

This framing must be stated in the demo narrative. Presenting a Business Central-shaped extract as
Gulf's ERP would be a false claim about the client's estate.

### 3.7 Run identity and pack versioning

Anything that moves a run id: master seed, time window, market/topology set, catalog content,
generator version, source spec version, and the catalog-pack version. Because the vocabulary
extension bumps `CATALOG_PACK_VERSION`, the Northstar byte-stability proof in `GOI-2` must
demonstrate that the *resolved catalog and config hash* for the retail preset are unchanged, and
must explicitly record whether the pack-version field itself appears in the retail run identity. If
it does, the retail lineage's re-pin cost is a stated, approved consequence — not a discovery made
after the fact.

---

## 4 · Decisions and proposed decisions

### GOI-D0 · Catalog evidence standard

**Proposed:** no product line, grade, pack size, MRP, or category enters the Gulf config without a
client-supplied source. Gaps are filled with SKUs explicitly labelled synthetic in the resolved
config, or left empty. **Rationale:** the §8 taxonomy is assembled from public brand knowledge and
is unverified; shipping it as Gulf's assortment would misrepresent the client's own catalog back to
them. **Status:** requires approval at `GOI-0`.

### GOI-D1 · Topology framing

**Option A (recommended):** map depots to warehouses and distributors to stores; reuse Phase 4
multi-echelon mechanics unchanged; accept imprecise vocabulary. **Option B:** add first-class
distributor/OEM/institutional/industrial channel types, secondary-sales grain, and scheme
structures — a `retail-source-config/v14` change touching `SUPPORTED_CHANNEL_TYPES`, config
sections, adapters, staging, and Gate B capabilities. **Recommendation:** A for the PoC; escalate
to B only if secondary-sales or scheme modelling is the actual client requirement. **Status:**
undecided; blocks `GOI-3`.

### GOI-D2 · Source-system framing

**Option A (recommended):** keep Shopify and Business Central shapes as source stand-ins; zero
ingestion adapter work. **Option B:** author a SAP-shaped profile and bounded adapter — a separate
ingestion workstream with its own Gate A/Gate B evidence. **Recommendation:** A, with the framing
stated explicitly in every demo. **Status:** undecided; blocks `GOI-4`.

### GOI-D3 · Tax treatment

**Proposed:** correct the India lubricant rate to 18%. Two mechanisms: (a) change the `IN`
`automotive` rate from `0.28` to `0.18`, which alters the Northstar retail preset's automotive
department and therefore its data; or (b) add a `lubricants` tax class to the closed list at
`config.py:900` and to the `IN` `categoryRates`, leaving `automotive` untouched. **Recommendation:**
(b) — it preserves invariant §0.5.2. **Status:** requires approval at `GOI-1`.

### GOI-D4 · Family granularity

**Proposed:** add Gulf-specific catalog families rather than pointing all sixteen categories at
`automotive-oils`. Collapsing is *valid* — validation passes — but every category would inherit one
price band, one shelf life, and the Castrol/Shell/Mobil/Valvoline reference set. **Recommendation:**
add families for the eight behaviourally distinct groups (MCO, PCMO, DEO, tractor, gear/ATF,
grease, coolant/brake, industrial) and reuse existing families for the adjacent range where the
behaviour genuinely matches. **Status:** requires approval at `GOI-1`.

### GOI-D5 · Catalog generation mode

**Proposed:** `explicit`. Every Gulf SKU comes from `productTemplates`; no generated filler. In
`explicit` mode `skusPerDepartment` is not used and `build_catalog` emits templates only.
**Rationale:** a client-facing lubricants catalog must not contain invented product lines.
**Alternative:** `hybrid`, if a long synthetic tail is wanted behind confirmed hero SKUs — permitted
only with `GOI-D0` labelling. **Status:** requires approval at `GOI-3`.

### GOI-D6 · Market granularity

**Proposed:** decide between one `IN` market and four regional markets (West/South/North/East).
Regional markets give genuine demand divergence and a richer story, but multiply the run and raise
the risk of thin segments under `MIN_SEGMENT_SERIES`. **Recommendation:** start single-market for
the showcase horizon; revisit before the long run using the `GOI-5` sizing evidence. **Status:**
undecided; blocks `GOI-3`.

### GOI-D7 · Horizon

**Proposed:** a 90-day showcase config for iteration plus a long-horizon config for depth. The
retail track's ten-year run costs roughly 90 minutes and 15 GB; a Gulf run of similar horizon
should be budgeted equivalently. **Status:** requires approval at `GOI-5`.

### GOI-D8 · Lineage separation

**Proposed:** Gulf publications carry their own selection records and their own expected-pin
document; no shared pin file is repointed in place, and no Gulf artifact supersedes a retail
artifact. **Rationale:** Decision #90's single-active-authority rule is scoped per lineage;
conflating tenants would make "exactly one active version" ambiguous. **Status:** requires approval
at `GOI-6`.

### GOI-D9 · Trademark and presentation

**Proposed:** carry the existing generator disclaimer verbatim into every Gulf artifact and demo
surface: brand and product-line names are reference identities; prices, costs, volumes, demand, and
operations are simulated. **Status:** requires approval at `GOI-0`.

### GOI-D10 · `config-hash` parameterization

**Proposed:** either add a `--config` argument to `command_config_hash` (`tools/dev.py:3043`) or
validate the Gulf config through `retail_datagen.cli validate-config` directly. **Recommendation:**
the direct CLI path, to keep `tools/dev.py` free of tenant knowledge. **Status:** requires approval
at `GOI-3`.

---

## 5 · Deliverables

### 5.1 Datagen deliverables

1. Extended `SUPPORTED_OPTION_DIMENSIONS` with a viscosity/grade dimension.
2. Extended `_OPTION_VALUES` with grade values and litre/kilogram pack values.
3. Extended `PACK_COUNTS` and `FAMILY_MEASUREMENTS` covering litre, kilogram, and unit bases.
4. New Gulf catalog families in `_FAMILY_BEHAVIOUR`, with India reference identities.
5. `CATALOG_PACK_VERSION` bump and its record in the resolved config.
6. India lubricant tax class or rate correction per `GOI-D3`.
7. `datagen/configs/gulf-oil-india-showcase.yaml` and `gulf-oil-india-<horizon>.yaml`.
8. Config Builder support for the new dimension and values, exported losslessly to YAML and JSON.
9. Datagen tests: vocabulary, catalog build, SKU uniqueness, measurement derivation, Northstar
   byte-stability.

### 5.2 Ingestion deliverables

1. `ingestion/src/retail_ingestion/profiles/gulf_oil_india.yaml` — schema-valid under
   `retail-source-profile/v1`, carrying the required top-level fields
   (`schemaVersion`, `profileId`, `profileVersion`, `sourceSystem`, `sourceSchemaVersion`,
   `businessTimezone`, `channelPolicy`, `assortmentPolicy`, `money`, `quantityPolicy`,
   `mappingReferences`, `sourceInstances`, `authenticity`, `datasets`,
   `publicationRequirements`) and per-instance fields (`sourceSystem`, `sourceInstance`,
   `logicalPathPrefix`, `marketId`, `currencyCode`, `timezone`, `capabilities`).
2. A fixture-scale round-trip test proving the profile against a small Gulf run.
3. Gate A, Gate B, readiness, and publication evidence for the Gulf lineage.

### 5.3 Evidence deliverables

1. Client catalog evidence pack, retained beside the scenario config.
2. Northstar regression evidence: unchanged catalog digest and config hash.
3. SKU × location sizing evidence against `MIN_SEGMENT_SERIES`.
4. Gulf publication manifest, selection records, and expected-pin document.
5. Per-stage timings and peak memory for the Gulf run, added to
   `docs/pipeline-stage-timings.md`.

### 5.4 Traceability

Each work package below gets a matching entry in `plans/local/tasks.md` under a new
`Gulf Oil India tenant` section, following the existing `[ ]` / `[~]` / `[x]` convention. No package
is started without its ledger entry.

---

## 6 · Proposed file layout

Names are proposed; ids are authoritative once frozen.

```text
plans/local/
  gulf-oil-india-implementation-plan.md      # this file
  tasks.md                                   # amended: new Gulf tenant section

docs/
  decision-GOI-1-topology-framing.md
  decision-GOI-2-source-system-framing.md
  decision-GOI-3-india-lubricant-tax-class.md
  gulf-oil-india-catalog-evidence/           # retained client evidence pack

datagen/
  src/retail_datagen/
    catalog_packs.py                         # amended: dimensions, values, packs, families, version
    config.py                                # amended only if GOI-D3 adds a tax class
    locale_packs.py                          # amended: IN lubricant rate
  configs/
    gulf-oil-india-showcase.yaml
    gulf-oil-india-showcase.json
    gulf-oil-india-<horizon>.yaml
    gulf-oil-india-<horizon>.json
  config-builder.html                        # amended: new dimension and values
  tests/
    test_gulf_catalog.py
    test_catalog_pack_stability.py

ingestion/
  src/retail_ingestion/profiles/
    gulf_oil_india.yaml
  tests/
    test_gulf_profile_round_trip.py

contracts/
  ml/
    expected-pin-gulf-oil-india.json         # separate lineage, per GOI-D8
  evidence/publication-selections/
    gulf-oil-india-*-candidate.json
    gulf-oil-india-*-approved.json
    gulf-oil-india-*-active.json
```

---

## 7 · Work packages

### GOI-0 · Client catalog evidence and framing decisions

**Entry:** none. This is the plan's first gate.

**Tasks:**

1. Obtain from the client, in writing: department and category structure; product lines per
   category; viscosity grades per line; pack sizes per line; indicative MRP and cost bands;
   channel mix; depot and distributor topology; and the intended demo question.
2. Record which of §8's proposed entries the evidence confirms, contradicts, or leaves unaddressed.
   Amend §8 to match the evidence. Do not carry unconfirmed entries forward silently.
3. Decide `GOI-D0` (evidence standard) and `GOI-D9` (trademark and presentation).
4. Decide `GOI-D1` (topology) and `GOI-D2` (source-system framing) in writing, each with its
   rationale and its accepted consequence.
5. Confirm whether the client requirement is source/data demonstration, forecasting, or pricing,
   and record the §0.3 dependency explicitly if it is either of the latter two.

**Exit:** an approved evidence pack, an amended §8, and four recorded decisions.

**Stop:** if the evidence pack is unavailable, do not proceed by inventing a catalog. A synthetic
lubricants catalog presented as Gulf's assortment is a worse outcome than a delayed one.

### GOI-1 · Freeze the vocabulary and tax design

**Entry:** `GOI-0` complete.

**Tasks:**

1. Specify the grade dimension: name, code format, and the exact value list from the evidence pack.
2. Specify pack values: display names, codes, unit, and numeric content for every pack in scope.
3. Specify measurement bases per new family (millilitre, gram, unit).
4. Specify the Gulf families per `GOI-D4`: `categoryCode`, option dimensions, reference identities,
   price band, seasonality peak and strength, margin, return rate, elasticity range, costing
   method, shelf life.
5. Decide `GOI-D3` and specify the exact edit.
6. State the option budget per category and prove no category exceeds three dimensions.
7. Define the catalog-pack version increment and where it is recorded in run identity.

**Exit:** a reviewed vocabulary and family specification. No code written yet.

**Stop:** do not write catalog code against a specification containing an unconfirmed grade, pack,
or price band.

### GOI-2 · Extend the catalog pack with Northstar byte-stability

**Entry:** `GOI-1` approved.

**Tasks:**

1. Implement the dimension, value, pack-count, measurement, and family additions.
2. Implement the `GOI-D3` tax change.
3. Bump `CATALOG_PACK_VERSION`.
4. Extend the Config Builder to author the new dimension and values, and prove lossless YAML/JSON
   export and re-import.
5. Prove the Northstar preset produces a byte-identical resolved catalog and an unchanged config
   hash. Record explicitly whether the pack-version bump moves the retail run identity, and if it
   does, obtain approval for that consequence before proceeding.
6. Run the full datagen suite plus `tools/check_import_boundaries.py`.

**Exit:** vocabulary extended, retail preset provably unmoved or its movement explicitly approved.

**Stop:** if the retail catalog digest changes for any reason other than an approved pack-version
field, revert and re-specify. Silent movement of the accepted retail lineage is a no-go.

### GOI-3 · Author the Gulf scenario configuration

**Entry:** `GOI-2` complete; `GOI-D1` and `GOI-D6` decided.

**Tasks:**

1. Author the showcase config in the Config Builder: retailer, market(s), legal entity, channels,
   depots as warehouses, distributors as stores, source instances, and operations.
2. Author the four departments and sixteen categories with per-category economics.
3. Author every confirmed product template with its grade and pack variants under `GOI-D5`.
4. Author seasonality: monsoon, Kharif/Rabi, Diwali, freight cycle, and at least one base-oil cost
   shock.
5. Export YAML and JSON; validate with `retail_datagen.cli validate-config`; resolve `GOI-D10`.
6. Run `retail_datagen.cli plan` and record product count, sellable SKU count, estimated orders,
   and partition count.
7. Confirm no category exceeds the three-option budget and no `productCode`/`brandCode` violates its
   pattern.

**Exit:** a validated Gulf showcase configuration with a recorded plan estimate.

**Stop:** a validation pass is not a fidelity pass. If the plan estimate implies a SKU or order
volume the client would not recognize, return to `GOI-1`.

### GOI-4 · Author and fixture-prove the Gulf ingestion profile

**Entry:** `GOI-3` complete; Gulf source-instance ids frozen; `GOI-D2` decided.

**Tasks:**

1. Author `gulf_oil_india.yaml` against `contracts/profiles/profile.schema.json`, carrying over the
   `datasets` block unchanged and replacing `extractWindow`, `sourceInstances`, and
   `locationOverrides`.
2. Generate a small deterministic Gulf fixture.
3. Run the fixture through generate → land → Gate A → stage → transform → Gate B → readiness →
   publish using `--source-profile`.
4. Prove that no ingestion, ML, API, DB, or UI **code** file was modified to make the run pass.
5. Prove the Northstar profile still passes its own round-trip unchanged.
6. Add the profile round-trip test.

**Exit:** a Gulf fixture reaches publication with zero downstream code change.

**Stop:** if any stage requires a code edit outside `datagen/`, halt and escalate. That result
falsifies the plan's central premise and the plan must be revised before continuing.

### GOI-5 · Short-horizon publication and sizing evidence

**Entry:** `GOI-4` complete.

**Tasks:**

1. Generate the full showcase horizon.
2. Take it end to end to a curated publication.
3. Record per-stage wall time, peak memory, row counts, and control totals; append to
   `docs/pipeline-stage-timings.md`.
4. Compute the SKU × location × week grid and compare every intended analysis segment against
   `MIN_SEGMENT_SERIES = 25`. Record which segments clear the floor and which do not.
5. Decide `GOI-D6` and `GOI-D7` using this evidence, not estimates.
6. Confirm the expected source outcomes: nonzero store and depot stock; typed origin-safe service
   lanes; fulfillment and status facts passing event-placement rules; supplier terms reaching
   `native_extracted` or stronger; non-degenerate lead-time distribution; reconstructible inbound
   positions.

**Exit:** one Gulf showcase publication plus sizing evidence sufficient to approve the long run.

**Stop:** if segments fall below the floor, resize the scenario before the long run. Discovering
thin segments after a multi-hour generation is avoidable waste.

### GOI-6 · Long-horizon publication, selection, and pin

**Entry:** `GOI-5` complete; `GOI-D6`, `GOI-D7`, and `GOI-D8` approved.

**Tasks:**

1. Author the long-horizon config from the approved showcase config; validate and plan it.
2. Generate without overwriting the showcase run.
3. Run Gate A and Gate B; publish an immutable curated publication with retained evidence.
4. Create Decision-#73 candidate → approved → active selections for the Gulf lineage only.
5. Generate the Gulf expected-pin document as a separate artifact per `GOI-D8`.
6. Prove that the Northstar publication, selections, and pin are untouched and still active.
7. Prove determinism: repeated generation under the same pinned writer and profile reproduces
   source ids exactly after excluded logical objects are removed.

**Exit:** one active Gulf source selection coexisting with the unchanged Northstar selection.

**Stop:** do not write any shared or retail pin file. Do not mark a Gulf capability ready if its
readiness verdict is unproven, and do not infer readiness from a global Gate B pass.

### GOI-7 · Isolation, regression, and portability evidence

**Entry:** `GOI-6` complete.

**Tasks:**

1. Run the full repository suite via `tools/dev.py test` plus `contracts`, `boundaries`, `ui-test`,
   and `ml-test`.
2. Prove the Northstar lineage end to end from its own pin and confirm identical control totals.
3. Prove that no executable file under `ml/`, `api/`, `db/`, or `ui/` differs from `main`.
4. Collect manual Windows, macOS, and Linux evidence for the Gulf datagen and ingestion path per
   `contracts/validation-policy.yaml`.
5. Record safe versus performance profile equivalence for the Gulf run: matching canonical schemas,
   control totals, and ordered row digests. Cross-profile source-id equality is not required.

**Exit:** a green suite, an unmoved retail lineage, and retained portability evidence.

### GOI-8 · Demo framing and handover

**Entry:** `GOI-7` complete.

**Tasks:**

1. Write the demo narrative stating plainly: which data is synthetic; that Shopify and Business
   Central are source shapes rather than claims about Gulf's estate; that "store" denotes a
   distributor; and which client-confirmed catalog facts underpin the assortment.
2. Record the §0.3 dependency in the handover: no Gulf forecast or pricing result exists or is
   authorized under this plan.
3. Record the escalation path to `GOI-D1` option B and `GOI-D2` option B, with their scope.
4. Update `plans/local/tasks.md` and this plan's status header.

**Exit:** a handover a reviewer can act on without reading the code.

---

## 8 · Proposed catalog specification

**This section is a starting proposal assembled from public brand knowledge. It is not evidence and
must be replaced or confirmed entry by entry at `GOI-0`.**

### 8.1 Departments and categories

| Department | Categories |
|---|---|
| Automotive Engine Oils | Motorcycle Oils, Passenger Car Motor Oils, Diesel/CV Engine Oils, Tractor & Farm Oils |
| Driveline & Specialities | Gear Oils, Transmission Fluids, Greases, Coolants & Brake Fluids |
| Industrial Lubricants | Hydraulic Oils, Compressor & Turbine Oils, Metalworking Fluids, Industrial Gear & Circulating |
| Adjacent & New Energy | Batteries, AdBlue/DEF, EV Fluids, Car Care & Consumables |

### 8.2 Product lines and pack matrix

| Category | Product lines (proposed) | Grades | Pack sizes |
|---|---|---|---|
| Motorcycle Oils | Gulf Pride 4T Plus, 4T Ultra, 4T UltraSynth, Gulf Pride 2T | 10W-30, 20W-40, 10W-50 | 500 ml, 800 ml, 900 ml, 1 L, 2.5 L |
| Passenger Car Motor Oils | Gulf Formula G, Formula ULE, Formula GX, Ultrasynth X | 0W-20, 5W-30, 5W-40, 10W-40 | 1 L, 3 L, 3.5 L, 4 L, 5 L |
| Diesel/CV Engine Oils | Gulf Superfleet XLD, LE, Supreme, Turbo | 15W-40, 20W-40 | 5 L, 7.5 L, 10 L, 20 L, 26 L, 50 L, 210 L |
| Tractor & Farm Oils | Gulf Superior Tractor Oil, Max Star, Multi-TF | 15W-40, 20W-40 | 5 L, 7.5 L, 10 L, 20 L, 26 L, 50 L |
| Gear Oils | Gulf Gear MP, EP, HD | 80W-90, 85W-140 | 500 ml, 1 L, 5 L, 20 L, 210 L |
| Transmission Fluids | Gulf ATF range, UTTO | — | 1 L, 5 L, 20 L |
| Greases | Gulf Crown, Superlith, Wheel Bearing | NLGI 2, NLGI 3 | 500 g, 1 kg, 5 kg, 18 kg, 180 kg |
| Coolants & Brake Fluids | Gulf coolant range, Gulf Brake Fluid DOT 3/DOT 4 | — | 500 ml, 1 L, 5 L |
| Hydraulic Oils | Gulf Harmony AW | ISO VG 32, 46, 68 | 20 L, 26 L, 50 L, 210 L |
| Compressor & Turbine | Gulf compressor and turbine ranges | ISO VG 46, 68 | 20 L, 210 L |
| Batteries | Gulf automotive, two-wheeler, inverter | Ah ratings | unit |
| AdBlue/DEF | Gulf AdBlue | — | 5 L, 10 L, 20 L, 210 L |
| EV Fluids | Gulf EV fluid range | — | 1 L, 5 L |

Indicative scale: roughly 60–90 product lines × 4–6 pack variants ≈ **300–500 sellable SKUs**, which
sits comfortably inside the generator's proven range and is realistic for a lubricants assortment.

### 8.3 Vocabulary additions required

- **Grade dimension** — a new entry in `SUPPORTED_OPTION_DIMENSIONS` plus its value list, covering
  the multigrade engine-oil grades, the gear-oil grades, the ISO VG grades, and the NLGI grades in
  scope.
- **Pack values** — litre, millilitre, and kilogram packs per the matrix above, each with a display
  name, a short code, and a numeric content entry in `PACK_COUNTS`.
- **Measurement bases** — a `FAMILY_MEASUREMENTS` entry per new family: millilitre for fluids, gram
  for greases, unit for batteries.

### 8.4 Economics to confirm at `GOI-0`

Per category: target margin, elasticity range, seasonality peak month and strength, base return
rate, costing method, shelf-life days, and the market price band. Lubricants generally carry low
return rates and FIFO costing on shelf-life-bound fluids, but the actual bands are client evidence,
not defaults to be assumed.

---

## 9 · Acceptance gates

### 9.1 Entry gates

- Client catalog evidence pack approved and retained.
- `GOI-D0`, `GOI-D1`, `GOI-D2`, `GOI-D9` recorded with rationale.
- §8 amended to match the evidence, with unconfirmed entries removed or explicitly labelled.
- The §0.3 dependency recorded if the requirement is forecasting or pricing.

### 9.2 Catalog and vocabulary gates

- Every Gulf category resolves a `catalogFamily` present in every configured market's pack.
- Every category declares at most three option dimensions.
- Every `productCode` matches `^[A-Z][A-Z0-9-]{2,39}$`; every `brandCode` matches `[A-Z0-9]{2,8}`.
- Every `variantDefinitions` entry carries option values present in the pack pool, and each product
  meets its market's `variantsPerProduct` minimum.
- Every sellable SKU is unique within its market; no duplicate product code.
- Net content resolves for every pack via `PACK_COUNTS` and `FAMILY_MEASUREMENTS`.
- Lubricant categories resolve an 18% GST rate under the approved `GOI-D3` mechanism.
- The Northstar preset yields a byte-identical resolved catalog and unchanged config hash, or its
  movement is explicitly approved.

### 9.3 Generation gates

- `validate-config` and `plan` both pass, with the plan estimate reviewed against client
  expectation.
- Repeated generation under the same pinned writer and profile reproduces source ids exactly.
- Safe and performance profiles yield matching canonical schemas, control totals, and ordered row
  digests.
- Restricted `_truth/` output lands in its own permission lane.

### 9.4 Ingestion and publication gates

- The Gulf profile is schema-valid under `retail-source-profile/v1`.
- Gate A passes with machine-readable evidence over the Gulf snapshot.
- Gate B passes; capability verdicts are published independently rather than inferred from a global
  pass.
- Typed service lanes cover fulfillment rows at corrected effective visibility.
- Store and depot inventory is complete at each origin for active cells; inactive zero-state
  Cartesian cells are absent.
- Supplier terms are origin-safe, varied, and precedence-complete.
- One immutable curated publication exists with retained evidence and Decision-#73 selections.

### 9.5 Isolation and regression gates

- No executable file under `ml/`, `api/`, `db/`, or `ui/` differs from `main`.
- `tools/check_import_boundaries.py` passes.
- The Northstar publication, selections, and pin are unchanged and still active.
- The full repository suite passes via `tools/dev.py`.
- Manual Windows, macOS, and Linux evidence is retained. No repository CI is added.

### 9.6 No-go conditions

Any one of these stops the work:

1. The client evidence pack is unavailable and the catalog would have to be invented.
2. The vocabulary extension moves the Northstar catalog digest without explicit approval.
3. Any stage requires a code change outside `datagen/` — the plan's premise is falsified and must be
   revised before continuing.
4. Gate B passes globally while the required Gulf capabilities are unready or insufficient.
5. A Gulf artifact would supersede, retire, or repoint a retail artifact.
6. A Gulf forecast or pricing number is requested for demonstration while §0.3 remains open.
7. Segment counts fall below `MIN_SEGMENT_SERIES` for the intended analysis and the scenario is not
   resized.

---

## 10 · Test and evidence matrix

### 10.1 Datagen tests

- Vocabulary: every new dimension and value is accepted; an unknown value is rejected; a
  four-dimension category is detected rather than silently truncated.
- Catalog build: expected product and SKU counts per department; unique product codes and SKUs;
  correct `categoryCode` segments; correct net content per pack.
- Lifecycle: no SKU receives inventory, demand, an order, or a price before its launch date, and
  none trades after discontinuation.
- Tax: lubricant categories resolve 18%; the retail `automotive` class is unaffected under
  `GOI-D3(b)`.
- Stability: the Northstar preset's resolved catalog digest and config hash are unchanged.
- Config Builder: lossless YAML/JSON export and re-import of the new dimension.

### 10.2 Ingestion tests

- Profile schema validity for `gulf_oil_india.yaml`.
- Fixture round-trip: generate → land → Gate A → stage → transform → Gate B → publish.
- Northstar profile round-trip unchanged.
- Negative case: the Gulf run under the Northstar profile fails at Gate A with a clear reason,
  documenting why the new profile is necessary.

### 10.3 Publication evidence

- Gate A and Gate B reports, readiness verdict, publication manifest, selection records, and pin
  document for the Gulf lineage.
- Control totals and ordered row digests for the Gulf publication.
- Per-stage timings and peak memory appended to `docs/pipeline-stage-timings.md`.

### 10.4 Regression evidence

- Full `tools/dev.py` suite output.
- `git diff --stat main` proving no change under `ml/`, `api/`, `db/`, `ui/`.
- Northstar pin and selections re-verified as active.

### 10.5 Manual evidence

- Windows, macOS, and Linux runs of the Gulf datagen and ingestion path.
- Config Builder screenshots covering the new dimension authoring surface.

---

## 11 · Security, privacy, trademark, and operational constraints

1. **Trademark.** Gulf brand and product-line names remain their owners' marks, used only as
   recognizable reference identities in synthetic fixtures, exactly as the existing catalog packs
   use Castrol, Shell, Mobil, and Valvoline. Every artifact and demo surface carries the disclaimer.
2. **No client data.** Only the catalog evidence pack — structure, product lines, packs, indicative
   bands — enters the repository. No customer, distributor, pricing agreement, or commercial data
   from the client is committed. If the evidence pack contains commercially sensitive pricing,
   retain it outside the repository and reference it.
3. **Truth lane.** `_truth/` stays restricted and permissioned; it never enters an ML input path.
4. **No misrepresentation.** Business Central and Shopify shapes are never described as Gulf's real
   systems, and no simulated observation is presented as a Gulf commercial fact.
5. **No CI.** Validation runs through `tools/dev.py` per `contracts/validation-policy.yaml`.
6. **Resource budget.** A long-horizon run is roughly 90 minutes and 15 GB by the retail
   comparator; the Gulf run is budgeted and scheduled accordingly, not run opportunistically.

---

## 12 · Sequencing and review gates

### 12.1 Default sequence

`GOI-0` → `GOI-1` → `GOI-2` → `GOI-3` → `GOI-4` → `GOI-5` → `GOI-6` → `GOI-7` → `GOI-8`.

`GOI-1` and the Config Builder portion of `GOI-2` may overlap once the vocabulary specification is
frozen. Nothing else may overlap: each package's exit is the next package's entry evidence.

### 12.2 Review gates

| Gate | Reviewer question |
|---|---|
| After `GOI-0` | Is the catalog client-confirmed, and is the framing decision recorded with its consequence? |
| After `GOI-2` | Is the retail lineage provably unmoved? |
| After `GOI-4` | Did anything outside `datagen/` require a code change? |
| After `GOI-5` | Do the segment counts support the intended analysis? |
| After `GOI-6` | Do two independent lineages coexist with exactly one active selection each? |
| After `GOI-7` | Is the retail track demonstrably unaffected? |

### 12.3 Escalation

If `GOI-D1` option B or `GOI-D2` option B is selected at any point, this plan is superseded. Those
options change the source contract and the ingestion adapter surface, and they require their own
plan with their own Gate A/Gate B and capability analysis. They are not amendments to this one.

---

## 13 · Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Catalog invented rather than confirmed | Client sees a wrong assortment; credibility loss | `GOI-D0` and the `GOI-0` stop condition |
| Pack-version bump moves the retail run id | Retail lineage needs an unplanned re-pin | Measure in `GOI-2` and approve the consequence before proceeding |
| Retail catalog digest changes silently | Accepted lineage invalidated | Byte-stability proof is a hard `GOI-2` exit |
| Thin segments under `MIN_SEGMENT_SERIES` | Fallbacks and refusals instead of results | Size in `GOI-5` before the long run |
| Distributor-as-store vocabulary confuses reviewers | Wrong reading of on-screen data | State it in the scenario description and the demo narrative |
| Shopify/BC read as Gulf's real ERP | False claim about the client estate | `GOI-D2` framing stated in every demo surface |
| Forecast or pricing expected from this plan | Commitment that cannot be met | §0.3 dependency recorded at `GOI-0` and again at `GOI-8` |
| Long run consumes hours before a defect surfaces | Wasted cycle | Fixture proof in `GOI-4`, short horizon in `GOI-5` |
| Four-dimension category truncated silently | Missing variant axis, undetected | Explicit budget check in `GOI-3`; test in `GOI-2` |
| Gulf and retail lineages conflated | Ambiguous single-active-authority semantics | `GOI-D8` separation and the `GOI-6` coexistence proof |

---

## 14 · Approval block

### 14.1 Approvals required before implementation

1. The client catalog evidence pack and the amended §8.
2. `GOI-D0` evidence standard and `GOI-D9` trademark and presentation.
3. `GOI-D1` topology framing and its accepted vocabulary imprecision.
4. `GOI-D2` source-system framing and its demo statement.
5. `GOI-D3` tax mechanism.
6. `GOI-D4` family granularity.
7. `GOI-D5` catalog generation mode.
8. `GOI-D6` market granularity and `GOI-D7` horizon, on `GOI-5` evidence.
9. `GOI-D8` lineage separation.
10. `GOI-D10` config-hash handling.
11. The pack-version consequence for the retail lineage, if any.
12. Work-package ordering and the §12.2 review gates.

### 14.2 Not approved by plan creation

Creating this file does not approve:

- any Gulf catalog content, product line, grade, pack, or price;
- a catalog-pack version bump or any change to `_FAMILY_BEHAVIOUR`, `_OPTION_VALUES`, `PACK_COUNTS`,
  or `FAMILY_MEASUREMENTS`;
- a change to the India locale tax table or the closed `taxCategory` list;
- a Gulf source run, publication, selection, or pin;
- a new ingestion source profile;
- source contract `v14`, a new channel type, or any secondary-sales grain;
- any ML, API, database, or UI change;
- any forecast, elasticity, pricing, or replenishment result on Gulf data;
- any representation to the client about what the Gulf demo will show.

### 14.3 Evidence required to authorize the next package

Each package begins only when its entry evidence is linked from an updated plan, task, or evidence
record. A verbal "continue" does not substitute for a missing decision, evidence pack, contract
fingerprint, capability verdict, or approval.

---

## 15 · Final definition of done

The Gulf Oil India tenant onboarding is complete only when all are true:

1. A client-confirmed catalog evidence pack is retained, and every shipped SKU traces to it or is
   explicitly labelled synthetic.
2. `GOI-D0` through `GOI-D10` are decided and recorded with rationale and consequence.
3. The catalog vocabulary supports lubricant SKU identity — grade and pack — within the
   three-dimension budget, with net content resolving for every pack.
4. Lubricant categories resolve an 18% GST rate under the approved mechanism, and the retail
   `automotive` class is unaffected or its change is approved.
5. The Northstar preset produces a byte-identical resolved catalog and an unchanged config hash, or
   its movement was measured and approved before it happened.
6. A validated Gulf configuration exists in both YAML and JSON, authored through the Config Builder
   and re-importable losslessly.
7. A schema-valid Gulf ingestion source profile exists and is proven on a fixture before any long
   run.
8. No executable file under `ml/`, `api/`, `db/`, or `ui/` differs from `main`, and
   `check_import_boundaries.py` passes.
9. One immutable Gulf curated publication exists with Gate A, Gate B, readiness, manifest, and
   retained evidence.
10. Decision-#73 candidate → approved → active selections exist for the Gulf lineage, and a separate
    Gulf expected-pin document is generated.
11. The Northstar publication, selections, and pin are provably unchanged and still active; exactly
    one version is active per scope within each lineage.
12. Repeated generation is deterministic under the same pinned writer and profile; safe and
    performance profiles match on canonical schemas, control totals, and ordered row digests.
13. Segment counts for every intended analysis clear `MIN_SEGMENT_SERIES`, or the shortfall is
    recorded and accepted.
14. Per-stage timings and peak memory for the Gulf run are retained, and manual Windows, macOS, and
    Linux evidence exists.
15. The demo narrative states the synthetic boundary, the source-shape framing, and the
    distributor-as-store vocabulary, and records that no Gulf forecast or pricing result is
    authorized under this plan.
