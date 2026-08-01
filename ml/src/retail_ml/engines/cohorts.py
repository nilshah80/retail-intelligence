"""5%/95% calibration/holdout cohort identity (P4-D14).

Ported in spirit from M5 `engines/policy_calibration.py`
(sha256 0b6cfa958f063805580355f907b2b5d595008bf3d519094663265605e28f5f91) with the
cohort key re-contracted: the WHOLE key
(retailer, tenant, market, location, sku) goes to one cohort, all weeks and all
channel rows with it, for both incumbent and candidate. Splitting a key across
cohorts leaks calibration into holdout through shared state -- the store's
opening inventory on Monday is downstream of last week's calibration order.
"""

from __future__ import annotations

import hashlib

HASH_VERSION = "cohort-assignment/v1"
#: Frozen in inventory-policy/2.0.0 `cohortIdentity.seed`.
DEFAULT_SEED = 20260801
CALIBRATION_PCT = 5


def assign_cohort(
    *,
    retailer_id: str,
    tenant_id: str,
    market_id: str,
    location_id: str,
    sku_id: str,
    seed: int = DEFAULT_SEED,
    calibration_pct: int = CALIBRATION_PCT,
) -> str:
    """Deterministically assign one key to `calibration` or `holdout`.

    sha256 over the versioned, seed-prefixed key, reduced mod 100. Python's
    `hash()` is process-randomized and would assign differently per run; a
    cohort that moves between runs is not a cohort.
    """

    if not 0 < calibration_pct < 100:
        raise ValueError("calibration_pct must be in (0, 100)")
    for name, value in (
        ("retailer_id", retailer_id),
        ("tenant_id", tenant_id),
        ("market_id", market_id),
        ("location_id", location_id),
        ("sku_id", sku_id),
    ):
        if not value:
            raise ValueError(f"{name} must be non-empty; a blank key field "
                             "collapses distinct keys into one cohort")
    payload = "|".join(
        (HASH_VERSION, str(seed), retailer_id, tenant_id, market_id,
         location_id, sku_id)
    ).encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100
    return "calibration" if bucket < calibration_pct else "holdout"


__all__ = ["CALIBRATION_PCT", "DEFAULT_SEED", "HASH_VERSION", "assign_cohort"]
