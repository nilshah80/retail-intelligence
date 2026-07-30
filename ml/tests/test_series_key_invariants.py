import pytest

from retail_ml.keys import SERIES_KEY_FIELDS, SeriesKey


def test_channel_is_part_of_series_identity() -> None:
    store = SeriesKey("sku-1", "store-1", "store")
    ecommerce = SeriesKey("sku-1", "store-1", "ecommerce")

    assert store != ecommerce
    assert SERIES_KEY_FIELDS == ("sku_id", "store_id", "channel_id")
    assert len(store.as_tuple()) == 3


def test_series_key_rejects_empty_components() -> None:
    with pytest.raises(ValueError, match="channel_id"):
        SeriesKey("sku-1", "store-1", "")
