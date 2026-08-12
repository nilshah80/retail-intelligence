"""Governed price-response, recommendation, competitor, and promotion logic."""

from .competitor import build_competitor_foundation, load_competitor_policy
from .panel import build_weekly_panel, load_response_policy
from .policy import PricingPolicyError, enumerate_candidates, scaled_change_cap
from .promotion import build_promotion_foundation, load_promotion_policy
from .recommendation import build_recommendations
from .response import assess_response_series, fit_poisson
from .simulation import run_price_simulation

__all__ = [
    "PricingPolicyError",
    "assess_response_series",
    "build_weekly_panel",
    "build_competitor_foundation",
    "build_promotion_foundation",
    "build_recommendations",
    "enumerate_candidates",
    "fit_poisson",
    "load_competitor_policy",
    "load_promotion_policy",
    "load_response_policy",
    "run_price_simulation",
    "scaled_change_cap",
]
