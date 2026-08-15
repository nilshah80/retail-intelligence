"""Lubricant catalog vocabulary for the Gulf Oil India tenant.

The `gulf-lubricants-IN` pack adds the grade and fill dimensions a lubricant SKU
needs. A lubricant SKU is grade x pack, and neither axis existed: `packSize` held
Single/Pack of 2/Pack of 6/Family pack, and there was no viscosity at all.

These tests pin the four properties that make the addition safe rather than
merely present:

* **Tenants are isolated by pack, not by country.** Packs are keyed by pack id,
  so `real-retail-IN` and `gulf-lubricants-IN` coexist in India without either
  seeing the other's families. This is what keeps the retail presets
  byte-identical when a tenant is added.
* **Existing catalogs do not move.** `packSize` was deliberately left untouched
  and new dimensions added instead, because option values are a pack-global list
  and `_partial_combinations` runs `itertools.product` over it -- adding a value
  to `packSize` would change which variants every existing family selects. The
  retail presets must resolve byte-identically.
* **A fill is absolute, not a multiplier.** `packSize` scales a family's nominal
  content (a 6-pack of 150 g snacks is 900 g). A 20 L drum is 20 L regardless of
  what the family base says, so the fill replaces the base instead of scaling it.
  Getting this wrong yields a 20 L drum recorded as 20,000 L.
* **Grade systems do not mix.** SAE multigrade, gear, NLGI and ISO VG are
  separate dimensions rather than one `grade` holding all of them, so a grease
  can never be offered as 15W-40 nor an engine oil as NLGI 2.

The related in-family constraint -- a diesel engine oil takes 15W-40, never
0W-20 -- is *not* enforceable through a pack-global value list, and this is the
concrete reason the Gulf scenario is authored in `explicit` catalog mode. The
generated path would happily pair a heavy-duty line with a light grade. The last
test pins that the explicit path honours exactly the grades a product declares.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from retail_datagen.catalog_packs import (  # noqa: E402
    CATALOG_PACK_METADATA,
    CATALOG_PACK_VERSION,
    PACK_FILLS,
    SUPPORTED_OPTION_DIMENSIONS,
    _explicit_combinations,
    _measurement,
    _option_price_multiplier,
    _partial_combinations,
    build_catalog,
    resolve_catalog_pack,
)
from retail_datagen.config import (  # noqa: E402
    SUPPORTED_TAX_CATEGORIES,
    load_config,
)
from retail_datagen.locale_packs import LOCALE_PACKS  # noqa: E402
from tools.sync_presets import EMBED_ONLY_PRESETS, PRESETS  # noqa: E402

GULF_FAMILIES = {
    "lubricants-adblue",
    "lubricants-coolant-brake",
    "lubricants-diesel-engine",
    "lubricants-ev-fluids",
    "lubricants-gear",
    "lubricants-grease",
    "lubricants-hydraulic",
    "lubricants-industrial",
    "lubricants-motorcycle",
    "lubricants-pcmo",
    "lubricants-tractor",
    "lubricants-transmission",
}

GRADE_DIMENSIONS = {"viscosity", "gearGrade", "nlgiGrade", "isoViscosityGrade"}
FILL_DIMENSIONS = {"packVolume", "packWeight"}
GULF_DISTRIBUTOR_GEOGRAPHY = {
    ("Ahmedabad", "GJ"),
    ("Bengaluru", "KA"),
    ("Chennai", "TN"),
    ("Coimbatore", "TN"),
    ("Faridabad", "HR"),
    ("Guwahati", "AS"),
    ("Hyderabad", "TS"),
    ("Indore", "MP"),
    ("Jaipur", "RJ"),
    ("Kolkata", "WB"),
    ("Ludhiana", "PB"),
    ("Mumbai", "MH"),
    ("Pune", "MH"),
}


class GulfVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = resolve_catalog_pack("gulf-lubricants-IN")

    def test_gulf_families_live_only_in_the_gulf_pack(self) -> None:
        # The whole point of pack scoping: a retail scenario must not be able to
        # select a lubricant family, and the retail packs' familyIds must not
        # move because a tenant was added.
        self.assertEqual(
            GULF_FAMILIES,
            GULF_FAMILIES.intersection(
                CATALOG_PACK_METADATA["gulf-lubricants-IN"]["familyIds"]
            ),
        )
        for pack_id, metadata in CATALOG_PACK_METADATA.items():
            if pack_id == "gulf-lubricants-IN":
                continue
            leaked = GULF_FAMILIES.intersection(metadata["familyIds"])
            self.assertEqual(set(), leaked, f"{pack_id} leaked {sorted(leaked)}")

    def test_retail_packs_keep_their_original_family_count(self) -> None:
        for pack_id in ("real-retail-IN", "real-retail-US", "real-retail-GB", "real-retail-DE"):
            self.assertEqual(41, len(CATALOG_PACK_METADATA[pack_id]["familyIds"]), pack_id)

    def test_gulf_families_use_one_grade_and_one_fill(self) -> None:
        # Two dimensions, leaving headroom under the option1..option3 ceiling
        # that the Shopify writer silently truncates at.
        for family_id in sorted(GULF_FAMILIES):
            dimensions = set(self.pack["families"][family_id]["optionDimensions"])
            self.assertLessEqual(len(dimensions), 3, family_id)
            self.assertEqual(
                1,
                len(dimensions & FILL_DIMENSIONS),
                f"{family_id} must declare exactly one fill dimension",
            )
            self.assertTrue(
                dimensions & GRADE_DIMENSIONS or "format" in dimensions,
                f"{family_id} must declare a grade or a format axis",
            )

    def test_grease_and_engine_oil_cannot_share_a_grade_system(self) -> None:
        grease = set(self.pack["families"]["lubricants-grease"]["optionDimensions"])
        engine = set(self.pack["families"]["lubricants-diesel-engine"]["optionDimensions"])
        self.assertIn("nlgiGrade", grease)
        self.assertIn("viscosity", engine)
        self.assertEqual(set(), grease & engine & GRADE_DIMENSIONS)

    def test_every_declared_dimension_is_supported_and_populated(self) -> None:
        for family_id in sorted(GULF_FAMILIES):
            for dimension in self.pack["families"][family_id]["optionDimensions"]:
                self.assertIn(dimension, SUPPORTED_OPTION_DIMENSIONS, dimension)
                self.assertTrue(self.pack["optionValues"].get(dimension), dimension)

    def test_every_fill_value_has_a_numeric_fill(self) -> None:
        for dimension in FILL_DIMENSIONS:
            for value in self.pack["optionValues"][dimension]:
                self.assertIn(value["code"], PACK_FILLS, value["code"])


class FillSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = resolve_catalog_pack("gulf-lubricants-IN")

    def _options(self, dimension: str, code: str) -> list[dict[str, str]]:
        value = next(
            row for row in self.pack["optionValues"][dimension] if row["code"] == code
        )
        return [{"name": dimension, "value": value["name"], "code": code}]

    def test_fill_replaces_the_family_base_rather_than_scaling_it(self) -> None:
        # The family nominal base is 1 L. A 20 L drum must measure 20,000 ml --
        # not 20,000 x 1,000.
        _, value, unit = _measurement(
            "lubricants-diesel-engine", self._options("packVolume", "20L")
        )
        self.assertEqual(Decimal("20000"), value)
        self.assertEqual("ml", unit)

    def test_grease_fill_measures_in_grams(self) -> None:
        _, value, unit = _measurement(
            "lubricants-grease", self._options("packWeight", "18KG")
        )
        self.assertEqual(Decimal("18000"), value)
        self.assertEqual("g", unit)

    def test_packsize_families_keep_the_original_multiplier_path(self) -> None:
        # The regression that matters: a family with no fill dimension must
        # behave exactly as it did before 2026.7.
        _, value, unit = _measurement(
            "grocery-snacks", [{"name": "packSize", "value": "Pack of 6", "code": "6PK"}]
        )
        self.assertEqual(Decimal("900"), value)  # 150 g base x 6
        self.assertEqual("g", unit)

    def test_price_rises_monotonically_with_fill(self) -> None:
        codes = ["500ML", "1L", "5L", "20L", "210L"]
        multipliers = [
            _option_price_multiplier(self._options("packVolume", code)) for code in codes
        ]
        self.assertEqual(multipliers, sorted(multipliers))
        self.assertEqual(len(set(multipliers)), len(multipliers))

    def test_bulk_packs_are_cheaper_per_litre_than_the_one_litre_pack(self) -> None:
        # Sub-linear, or a 210 L barrel prices as 210 bottles and no fleet buys one.
        for code in ("5L", "20L", "210L"):
            litres = PACK_FILLS[code][0] / Decimal("1000")
            multiplier = _option_price_multiplier(self._options("packVolume", code))
            self.assertLess(multiplier / litres, Decimal("1"), code)


class ExplicitModeTests(unittest.TestCase):
    """Why Gulf is authored in `explicit` mode rather than `generated`."""

    def setUp(self) -> None:
        self.pack = resolve_catalog_pack("gulf-lubricants-IN")

    def test_generated_mode_can_pair_a_diesel_line_with_an_implausible_grade(self) -> None:
        # Documents the limitation rather than pretending it away: the value
        # list is pack-global, so the generated path may hand a heavy-duty
        # family a light grade. This is the constraint that makes `explicit`
        # mandatory for a client-facing lubricant catalog.
        combinations = _partial_combinations(
            self.pack, ["viscosity", "packVolume"], 8, 20260806, "gulf-deo-001"
        )
        drawn = {
            option["value"]
            for combination in combinations
            for option in combination
            if option["name"] == "viscosity"
        }
        self.assertTrue(
            drawn - {"15W-40", "20W-40"},
            "expected the generated path to draw grades outside the diesel set",
        )

    def test_explicit_mode_honours_exactly_the_declared_grades(self) -> None:
        definitions = [
            {"optionValues": {"viscosity": "15W-40", "packVolume": "5 L"}},
            {"optionValues": {"viscosity": "15W-40", "packVolume": "20 L"}},
            {"optionValues": {"viscosity": "20W-40", "packVolume": "210 L"}},
        ]
        combinations = _explicit_combinations(
            self.pack, ["viscosity", "packVolume"], definitions, 3
        )
        self.assertEqual(3, len(combinations))
        for combination in combinations:
            grade = next(o["value"] for o in combination if o["name"] == "viscosity")
            self.assertIn(grade, {"15W-40", "20W-40"})

    def test_variant_codes_are_sku_safe(self) -> None:
        for dimension in GRADE_DIMENSIONS | FILL_DIMENSIONS:
            for value in self.pack["optionValues"][dimension]:
                self.assertRegex(value["code"], r"^[A-Z0-9]+$", value["code"])

    def test_explicit_variant_cost_override_seats_the_variant_cost(self) -> None:
        # §6.0 pricing calibration seam: an explicit VariantDefinition `cost` is
        # the authoritative weighted-average unit cost for exactly the matched
        # variant, bypassing the base_cost x option multiplier x jitter chain,
        # and must not leak to its siblings. Parity with catalog.rs.
        import yaml

        config = yaml.safe_load(
            (ROOT / "configs" / "gulf-oil-india-ten-year.yaml").read_text()
        )
        template = config["catalog"]["productTemplates"][0]
        target = dict(template["variantDefinitions"][0]["optionValues"])
        template["variantDefinitions"][0]["cost"] = "123.45"

        matched, siblings = None, []
        for products in build_catalog(config).values():
            for product in products:
                if product.get("productCode") != template["productCode"]:
                    continue
                for variant in product["variants"]:
                    options = {o["name"]: o["value"] for o in variant["options"]}
                    if options == target:
                        matched = variant
                    else:
                        siblings.append(Decimal(str(variant["baseCost"])))
        self.assertIsNotNone(matched, "override variant not generated")
        assert matched is not None
        self.assertEqual(Decimal("123.45"), Decimal(str(matched["baseCost"])))
        self.assertTrue(
            all(cost != Decimal("123.45") for cost in siblings),
            "cost override leaked to sibling variants",
        )


class RetailStabilityTests(unittest.TestCase):
    """The retail presets must not move because Gulf was added."""

    def test_packsize_vocabulary_is_unchanged(self) -> None:
        codes = [row["code"] for row in resolve_catalog_pack("real-retail-IN")["optionValues"]["packSize"]]
        self.assertEqual(["1PK", "2PK", "6PK", "FAM"], codes)

    def test_no_retail_family_gained_a_lubricant_dimension(self) -> None:
        pack = resolve_catalog_pack("real-retail-IN")
        for family_id, family in pack["families"].items():
            if family_id in GULF_FAMILIES:
                continue
            overlap = set(family["optionDimensions"]) & (GRADE_DIMENSIONS | FILL_DIMENSIONS)
            self.assertEqual(set(), overlap, family_id)

    def test_checked_in_presets_carry_the_current_pack_version(self) -> None:
        # `_validate_catalog_pack` compares the effective pack to the resolved
        # metadata exactly. Load each preset so a deliberately small `extends`
        # overlay is checked against the inherited pack instead of being forced
        # to duplicate the base preset's catalog block.
        for path in sorted((ROOT / "configs").glob("*.yaml")):
            config = load_config(path)
            versions = {
                market["catalogPack"]["version"] for market in config["markets"]
            }
            self.assertEqual({CATALOG_PACK_VERSION}, versions, path.name)

    def test_lubricants_tax_falls_back_to_the_india_default_rate(self) -> None:
        # No locale pack was edited: India's defaultRate is already 18%, which is
        # exactly the lubricant GST rate, and `simulation._tax_rate` falls back
        # to it for any category the table does not name.
        tax = LOCALE_PACKS["IN"]["tax"]
        self.assertNotIn("lubricants", tax["categoryRates"])
        self.assertEqual("0.18", tax["defaultRate"])
        self.assertEqual("0.28", tax["categoryRates"]["automotive"])

    def test_gulf_distributors_declare_national_geography(self) -> None:
        for preset in (
            ROOT / "configs" / "gulf-oil-india-showcase.yaml",
            ROOT / "configs" / "gulf-oil-india-ten-year.yaml",
        ):
            with self.subTest(preset=preset.name):
                stores = load_config(preset)["stores"]
                actual = {(store["city"], store["regionCode"]) for store in stores}
                self.assertEqual(GULF_DISTRIBUTOR_GEOGRAPHY, actual)
                self.assertEqual(13, len(stores))

    def test_gulf_batches_have_a_governed_quality_control_hold(self) -> None:
        for preset in (
            ROOT / "configs" / "gulf-oil-india-showcase.yaml",
            ROOT / "configs" / "gulf-oil-india-ten-year.yaml",
        ):
            with self.subTest(preset=preset.name):
                inventory = load_config(preset)["operations"]["inventory"]
                self.assertEqual(5, inventory["qualityControlHoldDays"])


class ConfigBuilderDriftTests(unittest.TestCase):
    """The Config Builder carries a serialized copy of the generator contract.

    `config-builder.html` does not read `catalog_packs.py`; `tools/sync_presets.py`
    stamps the contract into JSON script elements. Nothing enforced that the two
    agreed, so extending the Python pack without re-running the sync produced a
    builder that rejected the very categories the extension enabled -- while
    every Python test passed. These tests are that missing gate.
    """

    HTML = (ROOT / "config-builder.html").read_text(encoding="utf-8")

    def _embedded(self, element_id: str) -> object:
        match = re.search(
            rf'<script id="{element_id}" type="application/json">(.*?)</script>',
            self.HTML,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing embedded script {element_id}")
        assert match is not None
        return json.loads(match.group(1))

    def test_embedded_catalog_packs_match_python(self) -> None:
        self.assertEqual(CATALOG_PACK_METADATA, self._embedded("catalogPacks"))

    def test_embedded_locale_packs_match_python(self) -> None:
        self.assertEqual(LOCALE_PACKS, self._embedded("localePacks"))

    def test_tax_category_dropdown_matches_python(self) -> None:
        # A select whose option list omits a valid value does not fail loudly:
        # it renders the first option instead, so opening a Gulf category showed
        # `apparel` and exporting would have silently rewritten the tax class.
        match = re.search(
            r'"Tax category",[^)]*?"select",\[([^\]]*)\]', self.HTML, re.DOTALL
        )
        self.assertIsNotNone(match, "tax category select not found")
        assert match is not None
        embedded = tuple(re.findall(r'"([a-z]+)"', match.group(1)))
        self.assertEqual(SUPPORTED_TAX_CATEGORIES, embedded)

    def test_embedded_presets_match_their_yaml(self) -> None:
        # The vocabularies above were guarded; the embedded *presets* were not.
        # The builder shipped the Gulf showcase with startDate 2025-08-01 (a
        # Friday) while the YAML had been corrected to 2025-08-07 (a Thursday),
        # so exporting from the builder would have handed back a Friday-start
        # config -- reintroducing the replay-oracle failure that the Thursday
        # move was made to fix, at the cost of a full regeneration.
        for element_id, path in {**PRESETS, **EMBED_ONLY_PRESETS}.items():
            with self.subTest(preset=element_id):
                self.assertEqual(
                    load_config(path),
                    self._embedded(element_id),
                    f"{element_id} is stale -- re-run datagen/tools/sync_presets.py",
                )

    def test_inline_dimension_vocabulary_matches_python(self) -> None:
        # This list is inline JavaScript, not a JSON script element, so
        # `sync_presets.py` does not touch it. It is hand-maintained and is the
        # single most likely thing to drift.
        match = re.search(r'optionDimensions=new Set\(\[([^\]]*)\]\)', self.HTML)
        self.assertIsNotNone(match, "inline optionDimensions Set not found")
        assert match is not None
        embedded = set(re.findall(r'"([A-Za-z]+)"', match.group(1)))
        self.assertEqual(SUPPORTED_OPTION_DIMENSIONS, embedded)

    def test_store_editor_preserves_geography_overrides(self) -> None:
        self.assertIn('["City","city"]', self.HTML)
        self.assertIn('["State / region code","regionCode"]', self.HTML)
        self.assertIn("city and state / region must be supplied together", self.HTML)


if __name__ == "__main__":
    unittest.main()
