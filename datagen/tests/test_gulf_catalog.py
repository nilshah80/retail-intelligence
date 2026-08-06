"""Lubricant catalog vocabulary for the Gulf Oil India tenant.

Catalog pack 2026.7 adds the grade and fill dimensions a lubricant SKU needs.
A lubricant SKU is grade x pack, and neither axis existed: `packSize` held
Single/Pack of 2/Pack of 6/Family pack, and there was no viscosity at all.

These tests pin the three properties that make the addition safe rather than
merely present:

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

from retail_datagen.catalog_packs import (  # noqa: E402
    CATALOG_PACK_METADATA,
    CATALOG_PACK_VERSION,
    PACK_FILLS,
    SUPPORTED_OPTION_DIMENSIONS,
    _explicit_combinations,
    _measurement,
    _option_price_multiplier,
    _partial_combinations,
    resolve_catalog_pack,
)
from retail_datagen.locale_packs import LOCALE_PACKS  # noqa: E402

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


class GulfVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = resolve_catalog_pack("IN")

    def test_every_gulf_family_resolves_in_every_market(self) -> None:
        # config.py requires a category's catalogFamily to exist in *every*
        # configured market's pack, so a family present only in IN would make a
        # multi-market scenario unconfigurable.
        for country, metadata in CATALOG_PACK_METADATA.items():
            missing = GULF_FAMILIES.difference(metadata["familyIds"])
            self.assertEqual(set(), missing, f"{country} is missing {sorted(missing)}")

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
        self.pack = resolve_catalog_pack("IN")

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
        self.pack = resolve_catalog_pack("IN")

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


class LubricantTaxTests(unittest.TestCase):
    def test_india_rates_lubricants_at_eighteen_percent(self) -> None:
        rates = LOCALE_PACKS["IN"]["tax"]["categoryRates"]
        self.assertEqual("0.18", rates["lubricants"])

    def test_retail_automotive_rate_is_untouched(self) -> None:
        # The whole reason `lubricants` is its own class: moving `automotive`
        # from 0.28 would silently change the retail tenant's data.
        self.assertEqual("0.28", LOCALE_PACKS["IN"]["tax"]["categoryRates"]["automotive"])

    def test_every_locale_pack_prices_the_new_class(self) -> None:
        for country, pack in LOCALE_PACKS.items():
            self.assertIn("lubricants", pack["tax"]["categoryRates"], country)


class RetailStabilityTests(unittest.TestCase):
    """The retail presets must not move because Gulf was added."""

    def test_packsize_vocabulary_is_unchanged(self) -> None:
        codes = [row["code"] for row in resolve_catalog_pack("IN")["optionValues"]["packSize"]]
        self.assertEqual(["1PK", "2PK", "6PK", "FAM"], codes)

    def test_no_retail_family_gained_a_lubricant_dimension(self) -> None:
        pack = resolve_catalog_pack("IN")
        for family_id, family in pack["families"].items():
            if family_id in GULF_FAMILIES:
                continue
            overlap = set(family["optionDimensions"]) & (GRADE_DIMENSIONS | FILL_DIMENSIONS)
            self.assertEqual(set(), overlap, family_id)

    def test_checked_in_presets_carry_the_current_pack_version(self) -> None:
        # `_validate_catalog_pack` compares the embedded pack to the resolved
        # metadata exactly, so a preset left un-synced fails config validation.
        for path in sorted((ROOT / "configs").glob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            versions = set(re.findall(r"version: '(\d{4}\.\d+)'", text))
            self.assertIn(CATALOG_PACK_VERSION, versions, path.name)


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

    def test_inline_dimension_vocabulary_matches_python(self) -> None:
        # This list is inline JavaScript, not a JSON script element, so
        # `sync_presets.py` does not touch it. It is hand-maintained and is the
        # single most likely thing to drift.
        match = re.search(r'optionDimensions=new Set\(\[([^\]]*)\]\)', self.HTML)
        self.assertIsNotNone(match, "inline optionDimensions Set not found")
        assert match is not None
        embedded = set(re.findall(r'"([A-Za-z]+)"', match.group(1)))
        self.assertEqual(SUPPORTED_OPTION_DIMENSIONS, embedded)


if __name__ == "__main__":
    unittest.main()
