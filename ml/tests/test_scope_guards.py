import pytest

from retail_ml.features.scope import ScopeJoinError, assert_market_qualified_join


def test_market_and_geo_scope_are_required_for_scoped_feeds() -> None:
    assert_market_qualified_join(
        ("market_id", "geo_scope_type", "geo_scope_id"),
        require_geo_scope=True,
    )

    with pytest.raises(ScopeJoinError, match="market_id"):
        assert_market_qualified_join(("region",), require_geo_scope=True)
    with pytest.raises(ScopeJoinError, match="geo_scope"):
        assert_market_qualified_join(("market_id", "region"), require_geo_scope=True)
