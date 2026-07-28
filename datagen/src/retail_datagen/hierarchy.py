"""Default normalized retail hierarchy used by config-builder presets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .catalog_packs import CATALOG_PACKS


HIERARCHY = {
    "apparel": (
        "Apparel",
        (
            ("apparel-tops", "Tops", "apparel"),
            ("apparel-bottoms", "Bottoms", "apparel"),
            ("apparel-outerwear", "Outerwear", "apparel"),
            ("apparel-footwear", "Footwear", "apparel"),
        ),
    ),
    "electronics": (
        "Electronics",
        (
            ("electronics-mobile", "Mobile Phones", "electronics"),
            ("electronics-tablets", "Tablets", "electronics"),
            ("electronics-laptops", "Laptops", "electronics"),
            ("electronics-audio", "Audio", "electronics"),
            ("electronics-accessories", "Accessories", "electronics"),
        ),
    ),
    "groceries": (
        "Groceries",
        (
            ("grocery-staples", "Pantry Staples", "grocery"),
            ("grocery-snacks", "Snacks & Confectionery", "grocery"),
            ("grocery-beverages", "Beverages", "grocery"),
            ("grocery-dairy", "Dairy & Chilled", "grocery"),
        ),
    ),
    "home": (
        "Home & Kitchen",
        (
            ("home-cookware", "Cookware", "home"),
            ("home-appliances", "Small Appliances", "home"),
            ("home-bedding", "Bedding", "home"),
            ("home-cleaning", "Cleaning & Laundry", "home"),
        ),
    ),
    "beauty": (
        "Beauty & Personal Care",
        (
            ("beauty-skincare", "Skin Care", "beauty"),
            ("beauty-haircare", "Hair Care", "beauty"),
            ("beauty-cosmetics", "Cosmetics", "beauty"),
            ("beauty-grooming", "Grooming", "beauty"),
        ),
    ),
    "health": (
        "Health & Wellness",
        (
            ("health-vitamins", "Vitamins & Supplements", "health"),
            ("health-otc", "Over-the-Counter", "health"),
            ("health-first-aid", "First Aid", "health"),
            ("health-wellness", "Nutrition & Wellness", "health"),
        ),
    ),
    "sports": (
        "Sports & Outdoors",
        (
            ("sports-fitness", "Fitness", "sports"),
            ("sports-outdoor", "Outdoor Recreation", "sports"),
            ("sports-team", "Team Sports", "sports"),
            ("sports-yoga", "Yoga", "sports"),
        ),
    ),
    "toys-baby": (
        "Toys & Baby",
        (
            ("toys-building", "Building Toys", "toys"),
            ("toys-games", "Games", "toys"),
            ("baby-care", "Baby Care", "baby"),
            ("baby-feeding", "Baby Feeding", "baby"),
        ),
    ),
    "books-stationery": (
        "Books & Stationery",
        (
            ("books-fiction", "Fiction Books", "books"),
            ("books-nonfiction", "Non-fiction Books", "books"),
            ("stationery-writing", "Writing Instruments", "stationery"),
            ("stationery-notebooks", "Notebooks", "stationery"),
        ),
    ),
    "automotive": (
        "Automotive",
        (
            ("automotive-car-care", "Car Care", "automotive"),
            ("automotive-accessories", "Car Accessories", "automotive"),
            ("automotive-oils", "Oils & Fluids", "automotive"),
            ("automotive-two-wheeler", "Two-wheeler Accessories", "automotive"),
        ),
    ),
}


def default_departments() -> list[dict[str, Any]]:
    """Materialize hierarchy rows with behavioral defaults from the catalog pack."""

    reference = CATALOG_PACKS["US"]["families"]
    departments: list[dict[str, Any]] = []
    for department_id, (department_name, categories) in HIERARCHY.items():
        category_rows = []
        for category_id, category_name, tax_category in categories:
            family = reference[category_id]
            category_rows.append(
                {
                    "categoryId": category_id,
                    "name": category_name,
                    "taxCategory": tax_category,
                    "catalogFamily": category_id,
                    "optionDimensions": deepcopy(family["optionDimensions"]),
                    "seasonalityPeakMonth": family["seasonalityPeakMonth"],
                    "seasonalityStrength": family["seasonalityStrength"],
                    "costingMethod": family["costingMethod"],
                    "targetMargin": family["targetMargin"],
                    "baseReturnRate": family["baseReturnRate"],
                    "elasticityMin": family["elasticityMin"],
                    "elasticityMax": family["elasticityMax"],
                }
            )
        departments.append(
            {
                "departmentId": department_id,
                "name": department_name,
                "categories": category_rows,
            }
        )
    return departments
