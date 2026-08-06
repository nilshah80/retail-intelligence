"""Versioned real-brand reference catalogs and rich catalog generation.

The generated transactions, prices, inventory and demand remain synthetic. Product
and brand names are recognizable retail reference data so demos exercise the same
catalog identities an adapter will encounter from a real retailer.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from .identity import rng, stable_integer

CATALOG_PACK_VERSION = "2026.7"
MONEY_QUANT = Decimal("0.01")
SUPPORTED_CATALOG_MODES = {"generated", "hybrid", "explicit"}
# Option values are a pack-global list per dimension, so every value of a
# dimension must be meaningful for every family that declares it. Lubricant
# grades are not interchangeable -- an engine oil is never NLGI 2 and a grease is
# never 15W-40 -- so each grade system gets its own dimension rather than one
# `grade` dimension holding values that only some families may legally take.
# `packSize` (Single/Pack of 2/...) is deliberately left untouched: adding values
# to it would change `itertools.product` in `_partial_combinations` and move
# every existing catalog.
SUPPORTED_OPTION_DIMENSIONS = {
    "ageGroup",
    "color",
    "compatibility",
    "connectivity",
    "flavour",
    "format",
    "gearGrade",
    "isoViscosityGrade",
    "nlgiGrade",
    "packSize",
    "packVolume",
    "packWeight",
    "power",
    "size",
    "storage",
    "viscosity",
}
SUPPORTED_LAUNCH_PROFILES = {"linear-ramp", "flagship-spike-decay", "evergreen"}

FAMILY_MEASUREMENTS: dict[str, tuple[str, Decimal, str]] = {
    "grocery-staples": ("KG", Decimal("1000"), "g"),
    "grocery-snacks": ("G", Decimal("150"), "g"),
    "grocery-beverages": ("ML", Decimal("500"), "ml"),
    "grocery-dairy": ("ML", Decimal("1000"), "ml"),
    "home-cleaning": ("ML", Decimal("750"), "ml"),
    "beauty-skincare": ("ML", Decimal("200"), "ml"),
    "beauty-haircare": ("ML", Decimal("300"), "ml"),
    "beauty-cosmetics": ("G", Decimal("30"), "g"),
    "beauty-grooming": ("ML", Decimal("200"), "ml"),
    "health-vitamins": ("EA", Decimal("30"), "count"),
    "health-otc": ("EA", Decimal("20"), "count"),
    "health-first-aid": ("EA", Decimal("10"), "count"),
    "baby-care": ("EA", Decimal("24"), "count"),
    "baby-feeding": ("G", Decimal("400"), "g"),
    "stationery-writing": ("EA", Decimal("5"), "count"),
    "automotive-car-care": ("ML", Decimal("500"), "ml"),
    "automotive-oils": ("ML", Decimal("1000"), "ml"),
    # Lubricant families quote a 1 L / 1 kg nominal base. In practice an
    # absolute pack fill overrides it (see `_measurement`), so these values act
    # as the fallback for a product that declares no fill dimension.
    "lubricants-motorcycle": ("ML", Decimal("1000"), "ml"),
    "lubricants-pcmo": ("ML", Decimal("1000"), "ml"),
    "lubricants-diesel-engine": ("ML", Decimal("1000"), "ml"),
    "lubricants-tractor": ("ML", Decimal("1000"), "ml"),
    "lubricants-gear": ("ML", Decimal("1000"), "ml"),
    "lubricants-transmission": ("ML", Decimal("1000"), "ml"),
    "lubricants-grease": ("G", Decimal("1000"), "g"),
    "lubricants-coolant-brake": ("ML", Decimal("1000"), "ml"),
    "lubricants-hydraulic": ("ML", Decimal("1000"), "ml"),
    "lubricants-industrial": ("ML", Decimal("1000"), "ml"),
    "lubricants-adblue": ("ML", Decimal("1000"), "ml"),
    "lubricants-ev-fluids": ("ML", Decimal("1000"), "ml"),
}

PACK_COUNTS = {
    "1PK": Decimal("1"),
    "2PK": Decimal("2"),
    "6PK": Decimal("6"),
    "FAM": Decimal("4"),
}

# Absolute pack fills. Unlike `packSize`, which multiplies a family's base
# measurement, a fill *is* the content: a 20 L drum is 20 L regardless of what
# the family's nominal unit says. Each entry carries the fill in the family's
# base unit (ml or g) and a price multiplier relative to the 1 L / 1 kg pack.
# Multipliers are sub-linear because bulk packs sell at a lower unit rate, and
# strictly increasing so a larger pack is never cheaper in absolute terms.
PACK_FILLS: dict[str, tuple[Decimal, Decimal]] = {
    "500ML": (Decimal("500"), Decimal("0.58")),
    "900ML": (Decimal("900"), Decimal("0.95")),
    "1L": (Decimal("1000"), Decimal("1")),
    "3L5": (Decimal("3500"), Decimal("3.25")),
    "5L": (Decimal("5000"), Decimal("4.55")),
    "7L5": (Decimal("7500"), Decimal("6.75")),
    "10L": (Decimal("10000"), Decimal("8.80")),
    "20L": (Decimal("20000"), Decimal("17")),
    "26L": (Decimal("26000"), Decimal("21.80")),
    "50L": (Decimal("50000"), Decimal("41")),
    "210L": (Decimal("210000"), Decimal("168")),
    "500G": (Decimal("500"), Decimal("0.58")),
    "1KG": (Decimal("1000"), Decimal("1")),
    "5KG": (Decimal("5000"), Decimal("4.55")),
    "18KG": (Decimal("18000"), Decimal("15.60")),
    "180KG": (Decimal("180000"), Decimal("148")),
}


def _products(value: str) -> list[dict[str, str]]:
    """Parse compact curated real-product reference rows."""

    rows = []
    for item in value.split(";"):
        brand, code, name, material = (part.strip() for part in item.split("|"))
        rows.append(
            {
                "brand": brand,
                "brandCode": code,
                "name": name,
                "material": material,
            }
        )
    return rows


def _family(
    code: str,
    dimensions: list[str],
    products: str,
    *,
    price: tuple[str, str],
    peak: int,
    strength: float,
    margin: float,
    returns: float,
    elasticity: tuple[float, float],
    costing: str = "WAC",
    shelf_life_days: int | None = None,
) -> dict[str, Any]:
    return {
        "categoryCode": code,
        "optionDimensions": dimensions,
        "products": _products(products),
        "priceBandUsd": {"min": price[0], "max": price[1]},
        "seasonalityPeakMonth": peak,
        "seasonalityStrength": strength,
        "costingMethod": costing,
        "targetMargin": margin,
        "baseReturnRate": returns,
        "elasticityMin": elasticity[0],
        "elasticityMax": elasticity[1],
        "shelfLifeDays": shelf_life_days,
    }


_FAMILY_BEHAVIOUR: dict[str, dict[str, Any]] = {
    "apparel-tops": _family(
        "TOP", ["color", "size"],
        "Uniqlo|UNQ|Uniqlo AIRism Cotton T-Shirt|Cotton blend;"
        "Nike|NKE|Nike Sportswear Club T-Shirt|Cotton;"
        "Adidas|ADS|Adidas Essentials 3-Stripes T-Shirt|Cotton;"
        "Levi's|LEV|Levi's Original Housemark T-Shirt|Cotton",
        price=("15", "55"), peak=4, strength=.18, margin=.54, returns=.10,
        elasticity=(-2.2, -.85), costing="FIFO",
    ),
    "apparel-bottoms": _family(
        "BTM", ["color", "size"],
        "Levi's|LEV|Levi's 511 Slim Fit Jeans|Stretch denim;"
        "Dockers|DCK|Dockers Ultimate Chinos|Cotton twill;"
        "Nike|NKE|Nike Sportswear Club Fleece Joggers|Cotton blend;"
        "Adidas|ADS|Adidas Tiro Track Pants|Recycled polyester",
        price=("30", "110"), peak=9, strength=.15, margin=.52, returns=.11,
        elasticity=(-2.1, -.8), costing="FIFO",
    ),
    "apparel-outerwear": _family(
        "OUT", ["color", "size"],
        "The North Face|TNF|The North Face Nuptse Jacket|Recycled nylon;"
        "Columbia|COL|Columbia Watertight II Jacket|Recycled polyester;"
        "Patagonia|PAT|Patagonia Nano Puff Jacket|Recycled polyester;"
        "Uniqlo|UNQ|Uniqlo Ultra Light Down Jacket|Nylon",
        price=("70", "330"), peak=12, strength=.45, margin=.56, returns=.13,
        elasticity=(-2.0, -.7), costing="FIFO",
    ),
    "apparel-footwear": _family(
        "FTW", ["color", "size"],
        "Nike|NKE|Nike Air Max 90|Leather and textile;"
        "Adidas|ADS|Adidas Stan Smith|Synthetic leather;"
        "New Balance|NBL|New Balance 574|Suede and mesh;"
        "Puma|PMA|Puma Suede Classic|Suede",
        price=("55", "180"), peak=8, strength=.20, margin=.50, returns=.14,
        elasticity=(-2.1, -.7), costing="FIFO",
    ),
    "electronics-mobile": _family(
        "MOB", ["color", "storage"],
        "Apple|APL|Apple iPhone 16|Aluminium and glass;"
        "Samsung|SMS|Samsung Galaxy S24|Aluminium and glass;"
        "Google|GGL|Google Pixel 9|Aluminium and glass;"
        "OnePlus|ONP|OnePlus 13|Aluminium and glass",
        price=("550", "1300"), peak=9, strength=.28, margin=.22, returns=.065,
        elasticity=(-1.6, -.4),
    ),
    "electronics-tablets": _family(
        "TAB", ["storage", "connectivity"],
        "Apple|APL|Apple iPad Air 11-inch (M3)|Aluminium and glass;"
        "Samsung|SMS|Samsung Galaxy Tab S10+|Aluminium and glass;"
        "Microsoft|MSF|Microsoft Surface Pro 11|Aluminium and glass;"
        "Lenovo|LNV|Lenovo Tab P12|Aluminium and glass",
        price=("300", "1400"), peak=9, strength=.24, margin=.25, returns=.06,
        elasticity=(-1.55, -.38),
    ),
    "electronics-laptops": _family(
        "LAP", ["storage", "format"],
        "Apple|APL|Apple MacBook Air 13-inch (M4)|Aluminium;"
        "Dell|DEL|Dell XPS 13|Aluminium;"
        "Lenovo|LNV|Lenovo ThinkPad X1 Carbon|Carbon fibre;"
        "HP|HPI|HP Spectre x360 14|Aluminium",
        price=("650", "2400"), peak=8, strength=.22, margin=.23, returns=.075,
        elasticity=(-1.5, -.35),
    ),
    "electronics-audio": _family(
        "AUD", ["color", "connectivity"],
        "Apple|APL|Apple AirPods Pro (2nd generation)|Polycarbonate;"
        "Sony|SNY|Sony WH-1000XM5 Headphones|Recycled plastic;"
        "Bose|BOS|Bose QuietComfort Ultra Headphones|Aluminium and plastic;"
        "JBL|JBL|JBL Flip 6 Speaker|Recycled plastic",
        price=("90", "480"), peak=11, strength=.24, margin=.32, returns=.07,
        elasticity=(-1.8, -.55),
    ),
    "electronics-accessories": _family(
        "EAC", ["color", "compatibility"],
        "Apple|APL|Apple MagSafe Charger|Aluminium and polycarbonate;"
        "Anker|ANK|Anker 737 Power Bank|Aluminium and polycarbonate;"
        "Belkin|BEL|Belkin BoostCharge Pro 3-in-1|Polycarbonate;"
        "Logitech|LOG|Logitech MX Master 3S Mouse|Recycled plastic",
        price=("20", "180"), peak=11, strength=.16, margin=.40, returns=.045,
        elasticity=(-2.0, -.7),
    ),
    "grocery-staples": _family(
        "GST", ["packSize", "format"],
        "India Gate|ING|India Gate Basmati Rice Classic|Basmati rice;"
        "Tata|TAT|Tata Salt|Iodised salt;"
        "Quaker|QKR|Quaker Oats|Wholegrain oats;"
        "Barilla|BAR|Barilla Spaghetti No. 5|Durum wheat",
        price=("2", "24"), peak=10, strength=.12, margin=.24, returns=.01,
        elasticity=(-2.6, -1.0), costing="FIFO", shelf_life_days=365,
    ),
    "grocery-snacks": _family(
        "GSN", ["packSize", "flavour"],
        "Lay's|LAY|Lay's Classic Potato Chips|Potato;"
        "Oreo|ORE|Oreo Original Cookies|Wheat and cocoa;"
        "Pringles|PRG|Pringles Original|Potato;"
        "Cadbury|CAD|Cadbury Dairy Milk|Milk chocolate",
        price=("1", "12"), peak=12, strength=.20, margin=.31, returns=.008,
        elasticity=(-3.0, -1.2), costing="FIFO", shelf_life_days=240,
    ),
    "grocery-beverages": _family(
        "GBV", ["packSize", "flavour"],
        "Coca-Cola|COK|Coca-Cola Original Taste|Carbonated beverage;"
        "Pepsi|PEP|Pepsi Cola|Carbonated beverage;"
        "Tropicana|TRP|Tropicana Orange Juice|Orange juice;"
        "Red Bull|RDB|Red Bull Energy Drink|Carbonated energy drink",
        price=("1", "20"), peak=6, strength=.28, margin=.29, returns=.006,
        elasticity=(-3.1, -1.1), costing="FIFO", shelf_life_days=270,
    ),
    "grocery-dairy": _family(
        "GDA", ["packSize", "format"],
        "Amul|AMU|Amul Taaza Milk|Cow milk;"
        "Danone|DAN|Danone Natural Yogurt|Cultured milk;"
        "Kerrygold|KER|Kerrygold Pure Irish Butter|Cream;"
        "Philadelphia|PHI|Philadelphia Original Cream Cheese|Cultured milk",
        price=("2", "15"), peak=5, strength=.10, margin=.22, returns=.005,
        elasticity=(-2.5, -1.0), costing="FIFO", shelf_life_days=21,
    ),
    "home-cookware": _family(
        "CKW", ["size", "format"],
        "Tefal|TEF|Tefal Jamie Oliver Frying Pan|Stainless steel;"
        "Lodge|LDG|Lodge Cast Iron Skillet|Cast iron;"
        "Prestige|PRE|Prestige Pressure Cooker|Stainless steel;"
        "Le Creuset|LCR|Le Creuset Signature Casserole|Enamelled cast iron",
        price=("25", "380"), peak=10, strength=.18, margin=.38, returns=.045,
        elasticity=(-1.8, -.6),
    ),
    "home-appliances": _family(
        "HAP", ["color", "power"],
        "Dyson|DYS|Dyson V15 Detect Vacuum|Polycarbonate;"
        "Philips|PHL|Philips Airfryer 3000 Series|Plastic and steel;"
        "KitchenAid|KAD|KitchenAid Artisan Stand Mixer|Die-cast metal;"
        "Instant Pot|INP|Instant Pot Duo 7-in-1|Stainless steel",
        price=("70", "850"), peak=11, strength=.22, margin=.30, returns=.055,
        elasticity=(-1.55, -.45),
    ),
    "home-bedding": _family(
        "BED", ["color", "size"],
        "IKEA|IKE|IKEA DVALA Sheet Set|Cotton;"
        "Brooklinen|BRK|Brooklinen Luxe Core Sheet Set|Cotton sateen;"
        "Tempur-Pedic|TMP|Tempur-Pedic Adapt Pillow|Memory foam;"
        "Sleepyhead|SLH|Sleepyhead Original Mattress Protector|Cotton blend",
        price=("20", "260"), peak=1, strength=.12, margin=.44, returns=.06,
        elasticity=(-1.9, -.7), costing="FIFO",
    ),
    "home-cleaning": _family(
        "CLN", ["packSize", "flavour"],
        "Tide|TID|Tide Original Liquid Laundry Detergent|Liquid detergent;"
        "Ariel|ARL|Ariel Matic Front Load Detergent|Powder detergent;"
        "Dettol|DET|Dettol Antiseptic Liquid|Antiseptic liquid;"
        "Mr. Clean|MRC|Mr. Clean Multi-Surface Cleaner|Liquid cleaner",
        price=("4", "35"), peak=3, strength=.08, margin=.30, returns=.008,
        elasticity=(-2.5, -1.0), costing="FIFO", shelf_life_days=730,
    ),
    "beauty-skincare": _family(
        "SKN", ["packSize", "format"],
        "CeraVe|CER|CeraVe Hydrating Facial Cleanser|Ceramide formula;"
        "The Ordinary|ORD|The Ordinary Niacinamide 10% + Zinc 1%|Water-based serum;"
        "Neutrogena|NEU|Neutrogena Hydro Boost Water Gel|Hyaluronic gel;"
        "Nivea|NIV|Nivea Soft Moisturising Cream|Moisturising cream",
        price=("6", "45"), peak=1, strength=.10, margin=.48, returns=.025,
        elasticity=(-2.3, -.8), costing="FIFO", shelf_life_days=730,
    ),
    "beauty-haircare": _family(
        "HAR", ["packSize", "format"],
        "L'Oréal Paris|LOR|L'Oréal Paris Elvive Total Repair 5 Shampoo|Liquid shampoo;"
        "Dove|DOV|Dove Intensive Repair Conditioner|Liquid conditioner;"
        "Pantene|PAN|Pantene Pro-V Daily Moisture Renewal Shampoo|Liquid shampoo;"
        "Kérastase|KRS|Kérastase Elixir Ultime Hair Oil|Hair oil",
        price=("5", "65"), peak=7, strength=.08, margin=.45, returns=.02,
        elasticity=(-2.4, -.9), costing="FIFO", shelf_life_days=900,
    ),
    "beauty-cosmetics": _family(
        "COS", ["color", "format"],
        "Maybelline|MAY|Maybelline Fit Me Matte + Poreless Foundation|Liquid foundation;"
        "MAC|MAC|MAC Matte Lipstick|Wax and pigment;"
        "L'Oréal Paris|LOR|L'Oréal Paris Voluminous Mascara|Mascara;"
        "e.l.f.|ELF|e.l.f. Halo Glow Liquid Filter|Liquid complexion booster",
        price=("7", "55"), peak=12, strength=.22, margin=.55, returns=.035,
        elasticity=(-2.2, -.75), costing="FIFO", shelf_life_days=730,
    ),
    "beauty-grooming": _family(
        "GRM", ["packSize", "format"],
        "Gillette|GIL|Gillette Fusion5 Razor Blades|Stainless steel;"
        "Philips|PHL|Philips OneBlade 360|Stainless steel and plastic;"
        "Braun|BRN|Braun Series 7 Electric Shaver|Metal and plastic;"
        "Old Spice|OSP|Old Spice Deodorant Stick|Solid deodorant",
        price=("5", "220"), peak=6, strength=.08, margin=.39, returns=.035,
        elasticity=(-2.0, -.65), shelf_life_days=1095,
    ),
    "health-vitamins": _family(
        "VIT", ["packSize", "format"],
        "Centrum|CEN|Centrum Adults Multivitamin|Tablet;"
        "Nature Made|NMD|Nature Made Vitamin D3|Softgel;"
        "Himalaya|HIM|Himalaya Ashvagandha Tablets|Herbal tablet;"
        "Seven Seas|SVS|Seven Seas Cod Liver Oil|Capsule",
        price=("6", "45"), peak=1, strength=.15, margin=.38, returns=.012,
        elasticity=(-2.0, -.7), costing="FIFO", shelf_life_days=730,
    ),
    "health-otc": _family(
        "OTC", ["packSize", "format"],
        "Tylenol|TYL|Tylenol Extra Strength Caplets|Caplet;"
        "Advil|ADV|Advil Tablets|Tablet;"
        "Vicks|VCK|Vicks VapoRub|Topical ointment;"
        "Strepsils|STR|Strepsils Original Lozenges|Lozenge",
        price=("4", "30"), peak=12, strength=.30, margin=.32, returns=.006,
        elasticity=(-1.7, -.5), costing="FIFO", shelf_life_days=730,
    ),
    "health-first-aid": _family(
        "FAD", ["packSize", "format"],
        "Band-Aid|BND|Band-Aid Flexible Fabric Adhesive Bandages|Fabric adhesive;"
        "Dettol|DET|Dettol Antiseptic Cream|Antiseptic cream;"
        "3M|THM|3M Nexcare Waterproof Bandages|Polymer adhesive;"
        "Savlon|SAV|Savlon Antiseptic Cream|Antiseptic cream",
        price=("3", "28"), peak=7, strength=.06, margin=.36, returns=.008,
        elasticity=(-1.9, -.6), costing="FIFO", shelf_life_days=730,
    ),
    "health-wellness": _family(
        "WEL", ["packSize", "flavour"],
        "Optimum Nutrition|OPN|Optimum Nutrition Gold Standard Whey|Whey protein;"
        "Ensure|ENS|Ensure Original Nutrition Powder|Nutrition powder;"
        "Gatorade|GAT|Gatorade Electrolyte Powder|Electrolyte powder;"
        "Yakult|YAK|Yakult Probiotic Drink|Fermented milk",
        price=("3", "90"), peak=1, strength=.18, margin=.35, returns=.008,
        elasticity=(-2.2, -.8), costing="FIFO", shelf_life_days=180,
    ),
    "sports-fitness": _family(
        "FIT", ["color", "size"],
        "Nike|NKE|Nike Metcon 9 Training Shoes|Textile and rubber;"
        "Adidas|ADS|Adidas Training Mat|Synthetic rubber;"
        "Bowflex|BFL|Bowflex SelectTech 552 Dumbbells|Steel and moulded plastic;"
        "Decathlon|DEC|Domyos 500 Resistance Bands|Natural rubber",
        price=("10", "550"), peak=1, strength=.28, margin=.38, returns=.07,
        elasticity=(-2.0, -.65),
    ),
    "sports-outdoor": _family(
        "ODR", ["color", "size"],
        "Coleman|CLM|Coleman Sundome Camping Tent|Polyester;"
        "The North Face|TNF|The North Face Borealis Backpack|Recycled polyester;"
        "Hydro Flask|HYD|Hydro Flask Wide Mouth Bottle|Stainless steel;"
        "Quechua|QUE|Quechua MH100 Hiking Backpack|Polyester",
        price=("18", "420"), peak=6, strength=.35, margin=.42, returns=.06,
        elasticity=(-1.9, -.6),
    ),
    "sports-team": _family(
        "TMS", ["color", "size"],
        "Nike|NKE|Nike Academy Football|Synthetic leather;"
        "Spalding|SPD|Spalding TF-1000 Basketball|Composite leather;"
        "Wilson|WIL|Wilson US Open Tennis Racket|Graphite;"
        "Gray-Nicolls|GNC|Gray-Nicolls Powerbow Cricket Bat|English willow",
        price=("15", "350"), peak=7, strength=.25, margin=.36, returns=.045,
        elasticity=(-1.8, -.55),
    ),
    "sports-yoga": _family(
        "YOG", ["color", "size"],
        "Lululemon|LUL|Lululemon The Mat 5mm|Natural rubber;"
        "Manduka|MAN|Manduka PRO Yoga Mat|PVC;"
        "Gaiam|GAI|Gaiam Essentials Yoga Block|EVA foam;"
        "Decathlon|DEC|Kimjaly Cotton Yoga Strap|Cotton",
        price=("8", "160"), peak=1, strength=.20, margin=.45, returns=.04,
        elasticity=(-2.1, -.7),
    ),
    "toys-building": _family(
        "BLD", ["ageGroup", "format"],
        "LEGO|LEG|LEGO Classic Creative Brick Box|ABS plastic;"
        "MEGA|MGA|MEGA BLOKS Big Building Bag|Polypropylene;"
        "Magna-Tiles|MGT|Magna-Tiles Classic Set|ABS plastic;"
        "Playmobil|PLY|Playmobil City Life Set|ABS plastic",
        price=("15", "180"), peak=12, strength=.48, margin=.40, returns=.045,
        elasticity=(-2.2, -.75),
    ),
    "toys-games": _family(
        "GAM", ["ageGroup", "format"],
        "Hasbro|HAS|Monopoly Classic Game|Cardboard and plastic;"
        "Mattel|MAT|UNO Card Game|Coated card;"
        "Asmodee|ASM|Catan Board Game|Cardboard and wood;"
        "Ravensburger|RAV|Ravensburger Disney Villainous|Cardboard and plastic",
        price=("5", "75"), peak=12, strength=.42, margin=.39, returns=.035,
        elasticity=(-2.4, -.8),
    ),
    "baby-care": _family(
        "BBC", ["packSize", "ageGroup"],
        "Pampers|PAM|Pampers Premium Care Diapers|Cellulose and polymer;"
        "Huggies|HUG|Huggies Little Snugglers Diapers|Cellulose and polymer;"
        "Johnson's|JNJ|Johnson's Baby Lotion|Moisturising lotion;"
        "WaterWipes|WWP|WaterWipes Original Baby Wipes|Water-based wipe",
        price=("4", "55"), peak=3, strength=.05, margin=.28, returns=.012,
        elasticity=(-2.5, -1.0), costing="FIFO", shelf_life_days=730,
    ),
    "baby-feeding": _family(
        "BFD", ["packSize", "ageGroup"],
        "Philips Avent|AVT|Philips Avent Natural Response Baby Bottle|Polypropylene;"
        "Tommee Tippee|TMT|Tommee Tippee Closer to Nature Bottle|Polypropylene;"
        "Gerber|GER|Gerber Oatmeal Baby Cereal|Wholegrain oats;"
        "Aptamil|APT|Aptamil Follow On Milk|Milk-based powder",
        price=("5", "60"), peak=3, strength=.05, margin=.27, returns=.01,
        elasticity=(-2.3, -.9), costing="FIFO", shelf_life_days=365,
    ),
    "books-fiction": _family(
        "BFI", ["format", "size"],
        "Penguin|PGN|The Thursday Murder Club|Paper and ink;"
        "Bloomsbury|BLM|Harry Potter and the Philosopher's Stone|Paper and ink;"
        "HarperCollins|HPC|The Alchemist|Paper and ink;"
        "Simon & Schuster|SNS|The Seven Husbands of Evelyn Hugo|Paper and ink",
        price=("7", "32"), peak=12, strength=.22, margin=.36, returns=.035,
        elasticity=(-1.9, -.6), costing="FIFO",
    ),
    "books-nonfiction": _family(
        "BNF", ["format", "size"],
        "Penguin|PGN|Atomic Habits|Paper and ink;"
        "Portfolio|PRT|The Psychology of Money|Paper and ink;"
        "Random House|RNH|Sapiens: A Brief History of Humankind|Paper and ink;"
        "Simon & Schuster|SNS|Steve Jobs|Paper and ink",
        price=("8", "38"), peak=1, strength=.18, margin=.35, returns=.03,
        elasticity=(-1.8, -.55), costing="FIFO",
    ),
    "stationery-writing": _family(
        "SWR", ["packSize", "color"],
        "Pilot|PIL|Pilot G2 Gel Pens|Plastic and gel ink;"
        "Uni-ball|UNB|Uni-ball Eye Rollerball Pens|Plastic and liquid ink;"
        "Faber-Castell|FBC|Faber-Castell Colour Pencils|Wood and pigment;"
        "Sharpie|SHP|Sharpie Permanent Markers|Plastic and ink",
        price=("2", "28"), peak=8, strength=.35, margin=.42, returns=.012,
        elasticity=(-2.5, -.9), costing="FIFO",
    ),
    "stationery-notebooks": _family(
        "NBK", ["format", "size"],
        "Moleskine|MOL|Moleskine Classic Notebook|Acid-free paper;"
        "Camlin|CAM|Camlin Premio Notebook|Paper;"
        "Leuchtturm1917|LEU|Leuchtturm1917 Hardcover Notebook|Acid-free paper;"
        "Five Star|FVS|Five Star Spiral Notebook|Paper and wire",
        price=("3", "42"), peak=8, strength=.38, margin=.40, returns=.015,
        elasticity=(-2.4, -.85), costing="FIFO",
    ),
    "automotive-car-care": _family(
        "CCR", ["packSize", "format"],
        "Meguiar's|MGR|Meguiar's Ultimate Wash & Wax|Liquid cleaner;"
        "Turtle Wax|TRW|Turtle Wax Hybrid Solutions Ceramic Spray|Liquid coating;"
        "3M|THM|3M Car Care Glass Cleaner|Aerosol cleaner;"
        "Armor All|AAL|Armor All Original Protectant|Liquid protectant",
        price=("5", "45"), peak=6, strength=.12, margin=.35, returns=.018,
        elasticity=(-2.0, -.65), shelf_life_days=1095,
    ),
    "automotive-accessories": _family(
        "CAA", ["color", "compatibility"],
        "Bosch|BOS|Bosch Aerotwin Wiper Blades|Rubber and steel;"
        "Michelin|MCH|Michelin Digital Tyre Pressure Gauge|Plastic and electronics;"
        "Garmin|GRM|Garmin Dash Cam Mini 3|Plastic and electronics;"
        "Scosche|SCO|Scosche MagicMount Phone Holder|Plastic and magnet",
        price=("8", "180"), peak=7, strength=.10, margin=.38, returns=.045,
        elasticity=(-1.9, -.6),
    ),
    "automotive-oils": _family(
        "OIL", ["packSize", "format"],
        "Castrol|CAS|Castrol EDGE 5W-30 Engine Oil|Synthetic motor oil;"
        "Mobil 1|MBL|Mobil 1 Advanced Full Synthetic 5W-30|Synthetic motor oil;"
        "Shell|SHL|Shell Helix Ultra 5W-40|Synthetic motor oil;"
        "Valvoline|VAL|Valvoline Advanced Full Synthetic 5W-30|Synthetic motor oil",
        price=("8", "75"), peak=5, strength=.08, margin=.28, returns=.01,
        elasticity=(-1.8, -.55), costing="FIFO", shelf_life_days=1825,
    ),
    "automotive-two-wheeler": _family(
        "TWH", ["color", "compatibility"],
        "Studds|STD|Studds Thunder D3 Helmet|Thermoplastic shell;"
        "Vega|VEG|Vega Bolt Helmet|ABS shell;"
        "Motul|MOT|Motul 7100 4T Engine Oil|Synthetic motor oil;"
        "Oxford|OXF|Oxford Boss Alarm Disc Lock|Hardened steel",
        price=("10", "190"), peak=4, strength=.10, margin=.34, returns=.035,
        elasticity=(-1.9, -.6),
    ),
    # ---------------------------------------------------------------------
    # Lubricant families for the Gulf Oil India tenant.
    #
    # Price bands are quoted per 1 L / 1 kg in USD and scaled to the market by
    # `priceScale`; the absolute pack fill supplies the rest of the pack
    # economics. Product-line identities are real Gulf brand names used exactly
    # as Castrol/Shell/Mobil/Valvoline are used above -- recognizable reference
    # identities on wholly synthetic prices, costs, volumes and demand.
    #
    # PROVISIONAL: the line-up, grades and bands below are assembled from public
    # brand knowledge and have NOT been confirmed against Gulf's price list.
    # GOI-0 replaces every unconfirmed entry before this ships to a client.
    # ---------------------------------------------------------------------
    "lubricants-motorcycle": _family(
        "MCO", ["viscosity", "packVolume"],
        "Gulf|GULF|Gulf Pride 4T Plus|Mineral motor oil;"
        "Gulf|GULF|Gulf Pride 4T Ultra|Semi-synthetic motor oil;"
        "Gulf|GULF|Gulf Pride 4T UltraSynth|Synthetic motor oil;"
        "Gulf|GULF|Gulf Pride 2T|Two-stroke motor oil",
        price=("4", "9"), peak=10, strength=.22, margin=.34, returns=.006,
        elasticity=(-2.1, -.7), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-pcmo": _family(
        "PCM", ["viscosity", "packVolume"],
        "Gulf|GULF|Gulf Formula G|Synthetic motor oil;"
        "Gulf|GULF|Gulf Formula ULE|Fully synthetic motor oil;"
        "Gulf|GULF|Gulf Formula GX|Semi-synthetic motor oil;"
        "Gulf|GULF|Gulf Ultrasynth X|Fully synthetic motor oil",
        price=("6", "15"), peak=7, strength=.14, margin=.32, returns=.005,
        elasticity=(-1.9, -.6), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-diesel-engine": _family(
        "DEO", ["viscosity", "packVolume"],
        "Gulf|GULF|Gulf Superfleet XLD|Mineral diesel engine oil;"
        "Gulf|GULF|Gulf Superfleet LE|Semi-synthetic diesel engine oil;"
        "Gulf|GULF|Gulf Superfleet Supreme|Mineral diesel engine oil;"
        "Gulf|GULF|Gulf Superfleet Turbo|Mineral diesel engine oil",
        price=("3.50", "7.50"), peak=3, strength=.16, margin=.24, returns=.004,
        elasticity=(-2.3, -.85), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-tractor": _family(
        "TRC", ["viscosity", "packVolume"],
        "Gulf|GULF|Gulf Superior Tractor Oil|Mineral tractor oil;"
        "Gulf|GULF|Gulf Max Star|Mineral tractor oil;"
        "Gulf|GULF|Gulf Multi TF|Universal transmission fluid;"
        "Gulf|GULF|Gulf Tracsynth|Semi-synthetic tractor oil",
        price=("3.40", "6"), peak=6, strength=.38, margin=.26, returns=.004,
        elasticity=(-2.4, -.9), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-gear": _family(
        "GER", ["gearGrade", "packVolume"],
        "Gulf|GULF|Gulf Gear MP|Mineral gear oil;"
        "Gulf|GULF|Gulf Gear EP|Extreme-pressure gear oil;"
        "Gulf|GULF|Gulf Gear HD|Heavy-duty gear oil;"
        "Gulf|GULF|Gulf Gear Synth|Synthetic gear oil",
        price=("4.20", "8.50"), peak=7, strength=.12, margin=.30, returns=.004,
        elasticity=(-1.9, -.6), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-transmission": _family(
        "ATF", ["format", "packVolume"],
        "Gulf|GULF|Gulf ATF DX-III|Automatic transmission fluid;"
        "Gulf|GULF|Gulf ATF Multi|Automatic transmission fluid;"
        "Gulf|GULF|Gulf UTTO|Universal tractor transmission oil;"
        "Gulf|GULF|Gulf CVT Fluid|Continuously variable transmission fluid",
        price=("5", "11"), peak=7, strength=.10, margin=.30, returns=.004,
        elasticity=(-1.8, -.55), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-grease": _family(
        "GRS", ["nlgiGrade", "packWeight"],
        "Gulf|GULF|Gulf Crown Grease|Lithium grease;"
        "Gulf|GULF|Gulf Superlith|Lithium complex grease;"
        "Gulf|GULF|Gulf Wheel Bearing Grease|Lithium grease;"
        "Gulf|GULF|Gulf Multipurpose Grease|Calcium grease",
        price=("3", "7.20"), peak=6, strength=.14, margin=.32, returns=.004,
        elasticity=(-2.0, -.65), costing="FIFO", shelf_life_days=1460,
    ),
    "lubricants-coolant-brake": _family(
        "CBF", ["format", "packVolume"],
        "Gulf|GULF|Gulf Radiator Coolant|Glycol coolant;"
        "Gulf|GULF|Gulf Endurance Coolant|Long-life glycol coolant;"
        "Gulf|GULF|Gulf Brake Fluid DOT 3|Glycol-ether brake fluid;"
        "Gulf|GULF|Gulf Brake Fluid DOT 4|Glycol-ether brake fluid",
        price=("2.40", "6"), peak=4, strength=.20, margin=.30, returns=.005,
        elasticity=(-2.2, -.75), costing="FIFO", shelf_life_days=1095,
    ),
    "lubricants-hydraulic": _family(
        "HYD", ["isoViscosityGrade", "packVolume"],
        "Gulf|GULF|Gulf Harmony AW|Anti-wear hydraulic oil;"
        "Gulf|GULF|Gulf Harmony HVI|High-viscosity-index hydraulic oil;"
        "Gulf|GULF|Gulf Harmony ZF|Zinc-free hydraulic oil;"
        "Gulf|GULF|Gulf Hydrasynth|Synthetic hydraulic fluid",
        price=("2.60", "5.40"), peak=3, strength=.10, margin=.22, returns=.003,
        elasticity=(-2.0, -.7), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-industrial": _family(
        "IND", ["isoViscosityGrade", "packVolume"],
        "Gulf|GULF|Gulf Cyclo Compressor Oil|Compressor oil;"
        "Gulf|GULF|Gulf Turbine Oil|Turbine oil;"
        "Gulf|GULF|Gulf Cutting Oil|Metalworking fluid;"
        "Gulf|GULF|Gulf Industrial Gear Oil|Industrial gear oil",
        price=("3.60", "9.60"), peak=3, strength=.10, margin=.24, returns=.003,
        elasticity=(-1.8, -.55), costing="FIFO", shelf_life_days=1825,
    ),
    "lubricants-adblue": _family(
        "DEF", ["format", "packVolume"],
        "Gulf|GULF|Gulf AdBlue|Urea solution;"
        "Gulf|GULF|Gulf AdBlue Bulk|Urea solution;"
        "Gulf|GULF|Gulf DEF|Diesel exhaust fluid;"
        "Gulf|GULF|Gulf AdBlue Pro|Urea solution",
        price=("0.50", "1"), peak=3, strength=.08, margin=.16, returns=.003,
        elasticity=(-2.6, -1.0), costing="FIFO", shelf_life_days=365,
    ),
    "lubricants-ev-fluids": _family(
        "EVF", ["format", "packVolume"],
        "Gulf|GULF|Gulf eVolt Driveline Fluid|Synthetic EV driveline fluid;"
        "Gulf|GULF|Gulf eVolt Coolant|Dielectric coolant;"
        "Gulf|GULF|Gulf eVolt Grease|Synthetic EV grease;"
        "Gulf|GULF|Gulf eVolt Thermal Fluid|Dielectric thermal fluid",
        price=("9.60", "21.70"), peak=10, strength=.15, margin=.38, returns=.005,
        elasticity=(-1.5, -.45), costing="FIFO", shelf_life_days=1460,
    ),
}

_REGIONAL_PRODUCT_OVERRIDES = {
    "IN": {
        "grocery-staples": _products(
            "India Gate|ING|India Gate Basmati Rice Classic|Basmati rice;"
            "Tata|TAT|Tata Salt|Iodised salt;"
            "Aashirvaad|ASH|Aashirvaad Whole Wheat Atta|Whole wheat;"
            "Quaker|QKR|Quaker Oats|Wholegrain oats"
        ),
        "grocery-dairy": _products(
            "Heritage Foods|HRT|Heritage Full Cream Milk|Cow milk;"
            "Mother Dairy|MDR|Mother Dairy Classic Curd|Cultured milk;"
            "Amul|AMU|Amul Pasteurised Butter|Cream;"
            "Britannia|BRT|Britannia Cheese Slices|Processed cheese"
        ),
    },
    "US": {
        "grocery-staples": _products(
            "Ben's Original|BEN|Ben's Original Long Grain White Rice|Long-grain rice;"
            "Morton|MOR|Morton Iodized Salt|Iodised salt;"
            "Quaker|QKR|Quaker Old Fashioned Oats|Wholegrain oats;"
            "Barilla|BAR|Barilla Spaghetti No. 5|Durum wheat"
        ),
        "grocery-dairy": _products(
            "Horizon Organic|HOR|Horizon Organic Whole Milk|Cow milk;"
            "Chobani|CHO|Chobani Plain Greek Yogurt|Cultured milk;"
            "Land O Lakes|LOL|Land O Lakes Salted Butter|Cream;"
            "Philadelphia|PHI|Philadelphia Original Cream Cheese|Cultured milk"
        ),
    },
    "GB": {
        "grocery-staples": _products(
            "Tilda|TIL|Tilda Pure Basmati Rice|Basmati rice;"
            "Saxa|SAX|Saxa Fine Salt|Salt;"
            "Quaker|QKR|Quaker Rolled Oats|Wholegrain oats;"
            "Barilla|BAR|Barilla Spaghetti No. 5|Durum wheat"
        ),
        "grocery-dairy": _products(
            "Arla|ARL|Arla Cravendale Whole Milk|Cow milk;"
            "Müller|MUL|Müller Corner Strawberry Yogurt|Cultured milk;"
            "Lurpak|LUR|Lurpak Slightly Salted Butter|Cream;"
            "Cathedral City|CTC|Cathedral City Mature Cheddar|Cow milk"
        ),
    },
    "DE": {
        "grocery-staples": _products(
            "Oryza|ORY|Oryza Basmati Reis|Basmati rice;"
            "Bad Reichenhaller|BRH|Bad Reichenhaller AlpenJodSalz|Iodised salt;"
            "Kölln|KOL|Kölln Blütenzarte Flocken|Wholegrain oats;"
            "Barilla|BAR|Barilla Spaghetti No. 5|Durum wheat"
        ),
        "grocery-dairy": _products(
            "Weihenstephan|WEI|Weihenstephan Haltbare Vollmilch|Cow milk;"
            "Müller|MUL|Müller Joghurt mit der Ecke|Cultured milk;"
            "Kerrygold|KER|Kerrygold Original Irische Butter|Cream;"
            "Philadelphia|PHI|Philadelphia Doppelrahmstufe Natur|Cultured milk"
        ),
    },
}


_OPTION_VALUES = {
    "color": [
        {"name": "Black", "code": "BLK"}, {"name": "Blue", "code": "BLU"},
        {"name": "White", "code": "WHT"}, {"name": "Red", "code": "RED"},
        {"name": "Natural", "code": "NAT"},
    ],
    "size": [
        {"name": "Small", "code": "S"}, {"name": "Medium", "code": "M"},
        {"name": "Large", "code": "L"}, {"name": "Extra Large", "code": "XL"},
    ],
    "connectivity": [
        {"name": "Wi-Fi", "code": "WIFI"}, {"name": "Wi-Fi + Cellular", "code": "CELL"},
        {"name": "Bluetooth", "code": "BT"}, {"name": "USB-C", "code": "USBC"},
    ],
    "power": [
        {"name": "750W", "code": "750W"}, {"name": "1000W", "code": "1000W"},
        {"name": "1500W", "code": "1500W"}, {"name": "2000W", "code": "2000W"},
    ],
    "compatibility": [
        {"name": "Universal", "code": "UNI"}, {"name": "iPhone", "code": "IPH"},
        {"name": "Android", "code": "AND"}, {"name": "Vehicle specific", "code": "VEH"},
    ],
    "storage": [
        {"name": "64 GB", "code": "64G"}, {"name": "128 GB", "code": "128G"},
        {"name": "256 GB", "code": "256G"},
        {"name": "512 GB", "code": "512G"}, {"name": "1 TB", "code": "1TB"},
    ],
    "packSize": [
        {"name": "Single", "code": "1PK"}, {"name": "Pack of 2", "code": "2PK"},
        {"name": "Pack of 6", "code": "6PK"}, {"name": "Family pack", "code": "FAM"},
    ],
    "flavour": [
        {"name": "Original", "code": "ORG"}, {"name": "Classic", "code": "CLS"},
        {"name": "Assorted", "code": "AST"}, {"name": "No added sugar", "code": "NAS"},
    ],
    "format": [
        {"name": "Standard", "code": "STD"}, {"name": "Compact", "code": "CMP"},
        {"name": "Large", "code": "LRG"}, {"name": "Premium", "code": "PRM"},
    ],
    "ageGroup": [
        {"name": "0-2 years", "code": "A02"}, {"name": "3-5 years", "code": "A35"},
        {"name": "6-9 years", "code": "A69"}, {"name": "10+ years", "code": "A10"},
    ],
    "viscosity": [
        {"name": "0W-20", "code": "0W20"}, {"name": "5W-30", "code": "5W30"},
        {"name": "5W-40", "code": "5W40"}, {"name": "10W-30", "code": "10W30"},
        {"name": "10W-40", "code": "10W40"}, {"name": "15W-40", "code": "15W40"},
        {"name": "20W-40", "code": "20W40"}, {"name": "20W-50", "code": "20W50"},
    ],
    "gearGrade": [
        {"name": "75W-90", "code": "75W90"}, {"name": "80W-90", "code": "80W90"},
        {"name": "85W-140", "code": "85W140"},
    ],
    "nlgiGrade": [
        {"name": "NLGI 0", "code": "NLGI0"}, {"name": "NLGI 1", "code": "NLGI1"},
        {"name": "NLGI 2", "code": "NLGI2"}, {"name": "NLGI 3", "code": "NLGI3"},
    ],
    "isoViscosityGrade": [
        {"name": "ISO VG 32", "code": "VG32"}, {"name": "ISO VG 46", "code": "VG46"},
        {"name": "ISO VG 68", "code": "VG68"}, {"name": "ISO VG 100", "code": "VG100"},
        {"name": "ISO VG 150", "code": "VG150"}, {"name": "ISO VG 220", "code": "VG220"},
    ],
    "packVolume": [
        {"name": "500 ml", "code": "500ML"}, {"name": "900 ml", "code": "900ML"},
        {"name": "1 L", "code": "1L"}, {"name": "3.5 L", "code": "3L5"},
        {"name": "5 L", "code": "5L"}, {"name": "7.5 L", "code": "7L5"},
        {"name": "10 L", "code": "10L"}, {"name": "20 L", "code": "20L"},
        {"name": "26 L", "code": "26L"}, {"name": "50 L", "code": "50L"},
        {"name": "210 L", "code": "210L"},
    ],
    "packWeight": [
        {"name": "500 g", "code": "500G"}, {"name": "1 kg", "code": "1KG"},
        {"name": "5 kg", "code": "5KG"}, {"name": "18 kg", "code": "18KG"},
        {"name": "180 kg", "code": "180KG"},
    ],
}

_COUNTRY_SETTINGS = {
    "IN": {
        "id": "real-retail-IN", "label": "India real-brand reference catalog",
        "barcodeFormat": "EAN13", "countryOfOrigin": "IN", "priceScale": "83",
    },
    "US": {
        "id": "real-retail-US", "label": "United States real-brand reference catalog",
        "barcodeFormat": "UPCA", "countryOfOrigin": "US", "priceScale": "1",
    },
    "GB": {
        "id": "real-retail-GB", "label": "United Kingdom real-brand reference catalog",
        "barcodeFormat": "EAN13", "countryOfOrigin": "GB", "priceScale": "0.79",
    },
    "DE": {
        "id": "real-retail-DE", "label": "Germany/Europe real-brand reference catalog",
        "barcodeFormat": "EAN13", "countryOfOrigin": "DE", "priceScale": "0.92",
    },
}


def _resolved_pack(country_code: str) -> dict[str, Any]:
    source = _COUNTRY_SETTINGS[country_code]
    scale = Decimal(source["priceScale"])
    families: dict[str, dict[str, Any]] = {}
    for family_id, definition in _FAMILY_BEHAVIOUR.items():
        family = deepcopy(definition)
        if family_id in _REGIONAL_PRODUCT_OVERRIDES.get(country_code, {}):
            family["products"] = deepcopy(
                _REGIONAL_PRODUCT_OVERRIDES[country_code][family_id]
            )
        price_usd = family.pop("priceBandUsd")
        family["priceBand"] = {
            "min": str((Decimal(price_usd["min"]) * scale).quantize(MONEY_QUANT)),
            "max": str((Decimal(price_usd["max"]) * scale).quantize(MONEY_QUANT)),
        }
        family["productNames"] = [row["name"] for row in family["products"]]
        family["materials"] = sorted({row["material"] for row in family["products"]})
        families[family_id] = family
    brands = sorted(
        {
            (row["brand"], row["brandCode"])
            for family in families.values()
            for row in family["products"]
        }
    )
    return {
        "id": source["id"],
        "version": CATALOG_PACK_VERSION,
        "label": source["label"],
        "countryCode": country_code,
        "barcodeFormat": source["barcodeFormat"],
        "countryOfOrigin": source["countryOfOrigin"],
        "brands": [{"name": name, "code": code} for name, code in brands],
        "collections": [],
        "optionValues": deepcopy(_OPTION_VALUES),
        "families": families,
    }


CATALOG_PACKS = {country: _resolved_pack(country) for country in _COUNTRY_SETTINGS}
CATALOG_PACK_METADATA = {
    country: {
        "id": pack["id"],
        "version": pack["version"],
        "label": pack["label"],
        "countryCode": country,
        "barcodeFormat": pack["barcodeFormat"],
        "familyIds": sorted(pack["families"]),
    }
    for country, pack in CATALOG_PACKS.items()
}


def resolve_catalog_pack(country_code: str) -> dict[str, Any]:
    try:
        return deepcopy(CATALOG_PACKS[country_code])
    except KeyError as exc:
        raise ValueError(f"unsupported catalog country {country_code!r}") from exc


def _decimal_between(
    master_seed: int,
    purpose: str,
    key: str,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    random = rng(master_seed, purpose, key)
    return minimum + (maximum - minimum) * Decimal(str(random.random()))


def _price(
    master_seed: int,
    key: str,
    family: dict[str, Any],
    market: dict[str, Any],
) -> Decimal:
    minimum = Decimal(family["priceBand"]["min"])
    maximum = Decimal(family["priceBand"]["max"])
    random = rng(master_seed, "catalog-price", key)
    raw = minimum + (maximum - minimum) * Decimal(str(random.random() ** 1.7))
    endings = market["localePack"]["currency"]["priceEndings"]
    ending = Decimal(endings[stable_integer(key, modulo=len(endings))]) / 100
    whole = raw.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    result = whole + ending
    return min(maximum, max(minimum, result)).quantize(MONEY_QUANT)


def _snap_price(value: Decimal, market: dict[str, Any]) -> Decimal:
    endings = market["localePack"]["currency"]["priceEndings"]
    whole = int(value)
    candidates = [
        Decimal(major) + Decimal(ending) / Decimal("100")
        for major in range(max(0, whole - 1), whole + 2)
        for ending in endings
    ]
    return min(
        (candidate for candidate in candidates if candidate > 0),
        key=lambda candidate: (abs(candidate - value), candidate),
    ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _barcode_check_digit(body: str) -> str:
    total = sum(
        int(character) * (3 if (len(body) - index) % 2 else 1)
        for index, character in enumerate(body)
    )
    return str((10 - total % 10) % 10)


def _barcode(barcode_format: str, sku: str) -> str:
    if barcode_format == "UPCA":
        # UPC-A restricted-circulation numbers use number-system digit 4.
        # Prefixing the body with ``04`` would instead normalize to GTIN-13
        # prefix 004, which is ordinary GS1 company-prefix space.
        body = "4" + f"{stable_integer('barcode', sku, modulo=10_000_000_000):010d}"
    else:
        body = "020" + f"{stable_integer('barcode', sku, modulo=1_000_000_000):09d}"
    return body + _barcode_check_digit(body)


def barcode_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"\d{12}|\d{13}", value)) and value[-1] == _barcode_check_digit(
        value[:-1]
    )


def _partial_combinations(
    pack: dict[str, Any],
    dimensions: list[str],
    count: int,
    master_seed: int,
    product_key: str,
) -> list[list[dict[str, str]]]:
    option_lists = [pack["optionValues"][dimension] for dimension in dimensions]
    combinations = [
        [
            {"name": dimension, "value": value["name"], "code": value["code"]}
            for dimension, value in zip(dimensions, values, strict=True)
        ]
        for values in itertools.product(*option_lists)
    ]
    random = rng(master_seed, "variant-combinations", product_key)
    random.shuffle(combinations)
    return combinations[: min(count, len(combinations))]


def _explicit_combinations(
    pack: dict[str, Any],
    dimensions: list[str],
    definitions: list[dict[str, Any]],
    count: int,
) -> list[list[dict[str, str]]]:
    combinations: list[list[dict[str, str]]] = []
    for definition in definitions[:count]:
        option_values = definition["optionValues"]
        combination: list[dict[str, str]] = []
        for dimension in dimensions:
            selected = next(
                value
                for value in pack["optionValues"][dimension]
                if value["name"] == option_values[dimension]
            )
            combination.append(
                {
                    "name": dimension,
                    "value": selected["name"],
                    "code": selected["code"],
                }
            )
        combinations.append(combination)
    return combinations


def _normalized_popularity(
    master_seed: int,
    product_key: str,
    count: int,
) -> list[Decimal]:
    random = rng(master_seed, "variant-popularity", product_key)
    draws = [Decimal(str(-math.log(max(random.random(), 1e-12)))) for _ in range(count)]
    total = sum(draws, Decimal("0"))
    return [(draw / total).quantize(Decimal("0.000001")) for draw in draws]


def _option_price_multiplier(options: list[dict[str, str]]) -> Decimal:
    multiplier = Decimal("1")
    for option in options:
        if option["name"] == "storage":
            multiplier *= {
                "64G": Decimal("0.86"),
                "128G": Decimal("1"),
                "256G": Decimal("1.16"),
                "512G": Decimal("1.375"),
                "1TB": Decimal("1.65"),
            }[option["code"]]
        elif option["name"] == "packSize":
            count = PACK_COUNTS[option["code"]]
            # Multi-packs carry a modest unit discount while remaining
            # monotonically more expensive than smaller packs.
            multiplier *= Decimal("1") + (count - Decimal("1")) * Decimal("0.82")
        elif option["name"] == "power":
            multiplier *= {
                "750W": Decimal("1"),
                "1000W": Decimal("1.08"),
                "1500W": Decimal("1.18"),
                "2000W": Decimal("1.28"),
            }[option["code"]]
        elif option["name"] == "connectivity":
            multiplier *= {
                "WIFI": Decimal("1"),
                "CELL": Decimal("1.22"),
                "BT": Decimal("1"),
                "USBC": Decimal("1"),
            }[option["code"]]
        elif option["name"] in {"packVolume", "packWeight"}:
            # The family price band is quoted per 1 L / 1 kg, so the fill
            # multiplier carries the whole pack economics. A 210 L barrel is not
            # a variant of a 1 L bottle at the same price.
            multiplier *= PACK_FILLS[option["code"]][1]
    return multiplier


def _measurement(
    family_id: str,
    options: list[dict[str, str]],
) -> tuple[str, Decimal, str]:
    unit_of_measure, value, measurement_unit = FAMILY_MEASUREMENTS.get(
        family_id,
        ("EA", Decimal("1"), "count"),
    )
    # An absolute fill replaces the family's nominal content rather than
    # multiplying it; a 20 L drum holds 20 L whatever the family base says.
    # Families that declare no fill dimension keep the original packSize
    # multiplier path exactly, which is what keeps existing catalogs stable.
    fill = next(
        (
            PACK_FILLS[option["code"]][0]
            for option in options
            if option["name"] in {"packVolume", "packWeight"}
        ),
        None,
    )
    if fill is not None:
        return unit_of_measure, fill, measurement_unit
    pack_count = next(
        (
            PACK_COUNTS[option["code"]]
            for option in options
            if option["name"] == "packSize"
        ),
        Decimal("1"),
    )
    return unit_of_measure, value * pack_count, measurement_unit


def _weight_grams(value: Decimal, measurement_unit: str) -> Decimal:
    if measurement_unit in {"g", "ml"}:
        return value
    if measurement_unit in {"kg", "l"}:
        return value * Decimal("1000")
    return Decimal("0")


def _product_from_definition(
    *,
    config: dict[str, Any],
    market: dict[str, Any],
    department: dict[str, Any],
    category: dict[str, Any],
    sequence: int,
    variant_count: int,
    definition: dict[str, Any] | None,
    generated_lifecycle_position: tuple[int, int] | None = None,
) -> dict[str, Any]:
    master_seed = config["identity"]["masterSeed"]
    pack = resolve_catalog_pack(market["countryCode"])
    family = pack["families"][category["catalogFamily"]]
    generation = config["catalog"]["generation"]
    lifecycle = generation["lifecycle"]
    country = market["countryCode"]
    product_key = (
        definition["productId"]
        if definition
        else f"{market['marketId']}-{category['categoryId']}-{sequence:03d}"
    )
    category_position = next(
        index
        for index, row in enumerate(department["categories"])
        if row["categoryId"] == category["categoryId"]
    )
    category_sequence = max(
        0,
        (sequence - 1 - category_position) // len(department["categories"]),
    )
    reference_product = family["products"][
        category_sequence % len(family["products"])
    ]
    brand = (
        {"name": definition["brand"], "code": definition["brandCode"]}
        if definition
        else {
            "name": reference_product["brand"],
            "code": reference_product["brandCode"],
        }
    )
    title = definition["title"] if definition else reference_product["name"]
    material = (
        definition.get("material", reference_product["material"])
        if definition
        else reference_product["material"]
    )
    description = (
        definition["description"]
        if definition
        else (
            f"Synthetic retail listing for {title}; brand and product-line identity "
            f"are real reference data, while price, demand and operations are simulated."
        )
    )
    product_code = (
        definition["productCode"]
        if definition
        else f"{generation['skuPrefix']}-{country}-{family['categoryCode']}-{sequence:03d}"
    )
    base_price = (
        Decimal(definition["basePrice"])
        if definition
        else _price(master_seed, product_key, family, market)
    )
    target_margin = Decimal(str(category["targetMargin"]))
    margin_delta = _decimal_between(
        master_seed, "catalog-margin", product_key, Decimal("-0.04"), Decimal("0.04")
    )
    base_cost = (
        Decimal(definition["baseCost"])
        if definition
        else (base_price * (Decimal("1") - target_margin - margin_delta)).quantize(
            MONEY_QUANT, rounding=ROUND_HALF_EVEN
        )
    )
    start = date.fromisoformat(config["time"]["startDate"])
    end = date.fromisoformat(config["time"]["endDate"])
    horizon = max(1, (end - start).days)
    launch_spread_days = round(horizon * generation["launchSpreadPct"])
    if definition:
        launch_date = date.fromisoformat(definition["launchDate"])
    else:
        if generated_lifecycle_position is None:
            raise ValueError("generated products require a lifecycle position")
        generated_index, generated_total = generated_lifecycle_position
        incumbent_count = min(
            generated_total,
            math.ceil(generated_total * generation["incumbentProductPct"]),
        )
        if generated_index <= incumbent_count:
            launch_date = start - timedelta(
                days=stable_integer(
                    master_seed,
                    "catalog-launch-history",
                    product_key,
                    modulo=generation["launchHistoryDays"] + 1,
                )
            )
        else:
            launch_date = min(
                end,
                start
                + timedelta(
                    days=1
                    + stable_integer(
                        master_seed,
                        "catalog-launch-forward",
                        product_key,
                        modulo=max(1, launch_spread_days),
                    )
                ),
            )
    discontinue_date: date | None = None
    if definition and definition.get("discontinueDate"):
        discontinue_date = date.fromisoformat(definition["discontinueDate"])
    elif not definition and launch_date < end and (
        rng(master_seed, "catalog-discontinue", product_key).random()
        < generation["discontinueRate"]
    ):
        life_days = generation["minProductLifeDays"] + stable_integer(
            master_seed,
            "catalog-product-life",
            product_key,
            modulo=generation["maxProductLifeDays"] - generation["minProductLifeDays"] + 1,
        )
        candidate = launch_date + timedelta(days=life_days)
        if candidate <= end:
            discontinue_date = candidate
    dimensions = (
        definition["optionDimensions"]
        if definition and definition["optionDimensions"]
        else category["optionDimensions"]
    )
    combinations = (
        _explicit_combinations(
            pack,
            dimensions,
            definition["variantDefinitions"],
            variant_count,
        )
        if definition and definition.get("variantDefinitions")
        else _partial_combinations(
            pack,
            dimensions,
            variant_count,
            master_seed,
            product_key,
        )
    )
    if len(combinations) < variant_count:
        raise ValueError(
            f"{product_key} requests {variant_count} variants but its option matrix "
            f"only provides {len(combinations)}"
        )
    popularity = _normalized_popularity(master_seed, product_key, variant_count)
    product_popularity = Decimal(
        str(
            math.exp(
                rng(
                    master_seed, "product-popularity", market["marketId"], product_key
                ).gauss(0, 1.25)
            )
        )
    )
    launch_profile = (
        definition.get("launchProfile", lifecycle["defaultLaunchProfile"])
        if definition
        else lifecycle["defaultLaunchProfile"]
    )
    variant_launch_spread = (
        definition.get(
            "variantLaunchSpreadDays",
            0 if launch_profile == "flagship-spike-decay" else generation["variantLaunchSpreadDays"],
        )
        if definition
        else generation["variantLaunchSpreadDays"]
    )
    variants: list[dict[str, Any]] = []
    for position, (options, demand_weight) in enumerate(
        zip(combinations, popularity, strict=True), start=1
    ):
        option_code = "-".join(option["code"] for option in options)
        variant_code = option_code[:20]
        sku = f"{product_code}-{option_code}"
        variant_key = f"{product_key}:{option_code}"
        price = _snap_price(
            base_price
            * _option_price_multiplier(options)
            * (
                Decimal("1")
                + _decimal_between(
                    master_seed,
                    "variant-price",
                    variant_key,
                    Decimal("-0.015"),
                    Decimal("0.015"),
                )
            ),
            market,
        )
        cost = (
            base_cost
            * _option_price_multiplier(options)
            * (
                Decimal("1")
                + _decimal_between(
                    master_seed,
                    "variant-cost",
                    variant_key,
                    Decimal("-0.03"),
                    Decimal("0.06"),
                )
            )
        ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)
        elasticity = _decimal_between(
            master_seed,
            "variant-elasticity",
            variant_key,
            Decimal(str(category["elasticityMin"])),
            Decimal(str(category["elasticityMax"])),
        ).quantize(Decimal("0.0001"))
        return_probability = max(
            Decimal("0"),
            min(
                Decimal("0.50"),
                Decimal(str(category["baseReturnRate"]))
                + Decimal(
                    str(rng(master_seed, "variant-return", variant_key).gauss(0, .015))
                ),
            ),
        ).quantize(Decimal("0.0001"))
        variant_launch_date = launch_date
        if position > 1 and variant_launch_spread:
            variant_launch_date = min(
                end,
                launch_date
                + timedelta(
                    days=stable_integer(
                        master_seed,
                        "variant-launch",
                        variant_key,
                        modulo=variant_launch_spread + 1,
                    )
                ),
            )
        if discontinue_date:
            variant_launch_date = min(variant_launch_date, discontinue_date)
        unit_of_measure, measurement_value, measurement_unit = _measurement(
            category["catalogFamily"],
            options,
        )
        variants.append(
            {
                "variantKey": variant_key,
                "variantCode": variant_code,
                "sku": sku,
                "title": " / ".join(option["value"] for option in options),
                "barcode": _barcode(pack["barcodeFormat"], sku),
                "options": options,
                "position": position,
                "basePrice": price,
                "baseCost": cost,
                "demandWeight": (demand_weight * product_popularity).quantize(
                    Decimal("0.000001")
                ),
                "elasticity": elasticity,
                "returnProbability": return_probability,
                "unitOfMeasure": unit_of_measure,
                "measurementValue": measurement_value,
                "measurementUnit": measurement_unit,
                "weight": _weight_grams(
                    measurement_value,
                    measurement_unit,
                ),
                "weightUnit": "g",
                "launchDate": variant_launch_date.isoformat(),
                "discontinueDate": discontinue_date.isoformat() if discontinue_date else "",
            }
        )
    return {
        "productKey": product_key,
        "productCode": product_code,
        "title": title,
        "description": description,
        "brand": brand["name"],
        "brandCode": brand["code"],
        "departmentId": department["departmentId"],
        "categoryId": category["categoryId"],
        "catalogFamily": category["catalogFamily"],
        "taxCategory": category["taxCategory"],
        "unitOfMeasure": FAMILY_MEASUREMENTS.get(
            category["catalogFamily"],
            ("EA", Decimal("1"), "count"),
        )[0],
        "material": material,
        "launchDate": launch_date.isoformat(),
        "discontinueDate": discontinue_date.isoformat() if discontinue_date else "",
        "successorOfProductCode": (
            definition.get("successorOfProductCode", "") if definition else ""
        ),
        "successorProductCode": "",
        "successorLaunchDate": "",
        "launchProfile": launch_profile,
        "lifecycle": deepcopy(lifecycle),
        "seasonalityPeakMonth": category["seasonalityPeakMonth"],
        "seasonalityStrength": Decimal(str(category["seasonalityStrength"])),
        "costingMethod": category["costingMethod"],
        "shelfLifeDays": (
            max(
                1,
                round(
                    family["shelfLifeDays"]
                    * (
                        0.80
                        + stable_integer(
                            master_seed,
                            "shelf-life",
                            product_key,
                            modulo=41,
                        )
                        / 100
                    )
                ),
            )
            if family["shelfLifeDays"] is not None
            else None
        ),
        "countryOfOrigin": pack["countryOfOrigin"],
        "variants": variants,
    }


def _link_successors(config: dict[str, Any], market_id: str, products: list[dict[str, Any]]) -> None:
    """Create lineage and guarantee a configurable overlapping predecessor runout."""

    generation = config["catalog"]["generation"]
    lifecycle = generation["lifecycle"]
    by_code = {row["productCode"]: row for row in products}
    explicit_codes = {
        row["productCode"]
        for row in config["catalog"]["productTemplates"]
        if row["marketId"] == market_id
    }
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product in products:
        by_family[product["catalogFamily"]].append(product)
    for family_products in by_family.values():
        ordered = sorted(family_products, key=lambda row: (row["launchDate"], row["productCode"]))
        for prior, current in zip(ordered, ordered[1:]):
            if (
                prior["productCode"] in explicit_codes
                or current["productCode"] in explicit_codes
                or current["successorOfProductCode"]
                or current["launchDate"] <= prior["launchDate"]
            ):
                continue
            if (
                rng(
                    config["identity"]["masterSeed"],
                    "catalog-replacement",
                    market_id,
                    current["productCode"],
                ).random()
                < generation["replacementLinkRate"]
            ):
                current["successorOfProductCode"] = prior["productCode"]
    for successor in products:
        predecessor_code = successor["successorOfProductCode"]
        if not predecessor_code:
            continue
        predecessor = by_code.get(predecessor_code)
        if predecessor is None:
            continue
        successor_launch = date.fromisoformat(successor["launchDate"])
        runout_end = successor_launch + timedelta(days=30 * lifecycle["runoutMonths"])
        existing_end = (
            date.fromisoformat(predecessor["discontinueDate"])
            if predecessor["discontinueDate"]
            else None
        )
        if existing_end is None or existing_end < runout_end:
            predecessor["discontinueDate"] = runout_end.isoformat()
            for variant in predecessor["variants"]:
                variant["discontinueDate"] = runout_end.isoformat()
        predecessor["successorProductCode"] = successor["productCode"]
        predecessor["successorLaunchDate"] = successor["launchDate"]


def build_catalog(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build deterministic market catalogs with exact per-department SKU targets."""

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    templates = config["catalog"]["productTemplates"]
    mode = config["catalog"]["generation"]["mode"]
    for market in config["markets"]:
        market_id = market["marketId"]
        target_per_department = market["assortment"]["skusPerDepartment"]
        variants_per_product = market["assortment"]["variantsPerProduct"]
        category_weights = market["assortment"].get(
            "categoryAssortmentWeights",
            {},
        )
        used_product_codes: set[str] = set()
        used_skus: set[str] = set()
        market_templates = [row for row in templates if row["marketId"] == market_id]
        for department in config["catalog"]["departments"]:
            department_templates = [
                row
                for row in market_templates
                if row["departmentId"] == department["departmentId"]
            ]
            sku_count = 0
            sequence = 0
            if mode in {"hybrid", "explicit"}:
                for definition in department_templates:
                    sequence += 1
                    product = _product_from_definition(
                        config=config,
                        market=market,
                        department=department,
                        category=next(
                            row
                            for row in department["categories"]
                            if row["categoryId"] == definition["categoryId"]
                        ),
                        sequence=sequence,
                        variant_count=variants_per_product,
                        definition=definition,
                    )
                    if product["productCode"] in used_product_codes:
                        raise ValueError(
                            f"duplicate product code {product['productCode']} in {market_id}"
                        )
                    product_skus = {row["sku"] for row in product["variants"]}
                    if overlap := product_skus.intersection(used_skus):
                        raise ValueError(
                            f"duplicate sellable SKU(s) in {market_id}: {sorted(overlap)}"
                        )
                    result[market_id].append(product)
                    used_product_codes.add(product["productCode"])
                    used_skus.update(product_skus)
                    sku_count += len(product["variants"])
            if mode == "explicit":
                continue
            generated_total = math.ceil(
                max(0, target_per_department - sku_count) / variants_per_product
            )
            generated_index = 0
            generated_products_by_category: dict[str, int] = defaultdict(int)
            while sku_count < target_per_department:
                sequence += 1
                generated_index += 1
                if category_weights:
                    # Smooth weighted allocation gives the Config Builder an
                    # explicit, per-market category-depth control. Categories
                    # omitted from the map retain the uniform weight of 1.
                    category = min(
                        department["categories"],
                        key=lambda row: (
                            (
                                Decimal(
                                    generated_products_by_category[
                                        row["categoryId"]
                                    ]
                                )
                                + Decimal("0.5")
                            )
                            / Decimal(
                                str(
                                    category_weights.get(
                                        row["categoryId"],
                                        1,
                                    )
                                )
                            ),
                            -Decimal(
                                str(
                                    category_weights.get(
                                        row["categoryId"],
                                        1,
                                    )
                                )
                            ),
                            row["categoryId"],
                        ),
                    )
                else:
                    # Preserve the original uniform catalog byte-for-byte when
                    # no weighting control is present.
                    category = department["categories"][
                        (sequence - 1) % len(department["categories"])
                    ]
                product = _product_from_definition(
                    config=config,
                    market=market,
                    department=department,
                    category=category,
                    sequence=sequence,
                    variant_count=min(
                        variants_per_product, target_per_department - sku_count
                    ),
                    definition=None,
                    generated_lifecycle_position=(generated_index, generated_total),
                )
                if product["productCode"] in used_product_codes:
                    continue
                product_skus = {row["sku"] for row in product["variants"]}
                if product_skus.intersection(used_skus):
                    continue
                result[market_id].append(product)
                used_product_codes.add(product["productCode"])
                used_skus.update(product_skus)
                sku_count += len(product["variants"])
                generated_products_by_category[category["categoryId"]] += 1
        _link_successors(config, market_id, result[market_id])
    return dict(result)


def catalog_controls(
    catalog: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, int]]:
    return {
        market_id: {
            "products": len(products),
            "sellableSkus": sum(len(product["variants"]) for product in products),
        }
        for market_id, products in sorted(catalog.items())
    }
