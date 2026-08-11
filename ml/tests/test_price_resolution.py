from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from retail_ml.inventory_run.price_resolution import (
    PriceResolutionError,
    build_price_index,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market_id": "m1",
                "location_id": "s1",
                "channel_id": "store",
                "sku_id": "sku1",
                "currency_code": "USD",
                "observation_date": date(2026, 8, 1),
                "known_as_of": datetime(2026, 8, 2, tzinfo=timezone.utc),
                "sales_version": 1,
                "unit_price_minor": 100,
            },
            {
                "market_id": "m1",
                "location_id": "s2",
                "channel_id": "online",
                "sku_id": "sku1",
                "currency_code": "USD",
                "observation_date": date(2026, 8, 3),
                "known_as_of": datetime(2026, 8, 4, tzinfo=timezone.utc),
                "sales_version": 2,
                "unit_price_minor": 103,
            },
        ]
    )


def test_exact_and_even_population_fallback_preserve_the_inventory_algorithm() -> None:
    index = build_price_index(
        _frame(), source_cutoff=date(2026, 8, 5), require_provenance=True
    )
    exact, fallback = index.numeric_views()
    assert exact[("m1", "s1", "sku1", "store")] == 100
    assert fallback[("m1", "sku1")] == 101  # integer-floor midpoint, not 102
    assert index.resolve(("m1", "missing", "sku1", "store")).price_basis == (
        "market_sku_latest_median"
    )
    assert index.resolve(("m2", "missing", "sku1", "store")) is None


def test_exact_and_fallback_publish_distinct_honest_provenance() -> None:
    index = build_price_index(
        _frame(), source_cutoff=date(2026, 8, 5), require_provenance=True
    )
    exact = index.exact[("m1", "s1", "sku1", "store")]
    fallback = index.fallback[("m1", "sku1")]
    assert exact.provenance_complete
    assert exact.source_row_identity is not None
    assert exact.source_row_content_fingerprint is not None
    assert fallback.provenance_complete
    assert fallback.source_row_identity is None
    assert fallback.fallback_population_count == 2
    assert fallback.fallback_member_set_content_fingerprint is not None
    assert index.snapshot_content_fingerprint is not None


def test_fingerprint_is_stable_under_input_row_order() -> None:
    forward = build_price_index(
        _frame(), source_cutoff=date(2026, 8, 5), require_provenance=True
    )
    reversed_frame = _frame().iloc[::-1].reset_index(drop=True)
    reverse = build_price_index(
        reversed_frame, source_cutoff=date(2026, 8, 5), require_provenance=True
    )
    assert forward.snapshot_content_fingerprint == reverse.snapshot_content_fingerprint
    assert (
        forward.fallback[("m1", "sku1")].fallback_member_set_content_fingerprint
        == reverse.fallback[("m1", "sku1")].fallback_member_set_content_fingerprint
    )


def test_duplicate_serieskey_refuses_ambiguous_latest_price() -> None:
    frame = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)
    with pytest.raises(PriceResolutionError, match="duplicate"):
        build_price_index(frame, require_provenance=True)


def test_exact_datetime_cutoff_refuses_future_known_price() -> None:
    with pytest.raises(PriceResolutionError, match="not origin-visible"):
        build_price_index(
            _frame(),
            source_cutoff=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
            require_provenance=True,
        )


def test_datetime_cutoff_compares_observation_dates_in_utc() -> None:
    frame = _frame().iloc[[0]].copy()
    frame.loc[:, "observation_date"] = date(2026, 8, 10)
    frame.loc[:, "known_as_of"] = datetime(2026, 8, 9, 18, tzinfo=timezone.utc)
    cutoff = datetime(
        2026, 8, 10, 0, 30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    with pytest.raises(PriceResolutionError, match="after its source cutoff"):
        build_price_index(frame, source_cutoff=cutoff, require_provenance=True)
