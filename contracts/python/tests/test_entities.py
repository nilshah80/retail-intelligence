"""Machine-readable ``retail_v2`` contract invariants."""

from __future__ import annotations

from copy import deepcopy

import pytest
from retail_contracts.entities import (
    CHANNEL_GRAIN_ENTITIES,
    CHANNEL_REQUIRED_ENTITIES,
    EXPECTED_ENTITY_COUNT,
    VERSIONED_ENTITIES,
    ContractValidationError,
    load_retail_v2,
    validate_contract_tree,
    validate_retail_v2,
)


def test_entire_contract_tree_validates() -> None:
    # Contract revision 2 adds the four multi-echelon inventory entities and their
    # four staging roles. Asserted as exact totals rather than lower bounds: an
    # entity or role appearing without a deliberate contract change is the thing
    # this test exists to catch.
    assert validate_contract_tree() == {
        "entities": 57,
        "tiers": 3,
        "stagingEnvelopes": 6,
        "stagingV2Roles": 39,
        "jsonSchemas": 5,
        "openApiContracts": 1,
        "guardrailVectors": 4,
        "determinismContracts": 1,
    }


def test_entity_inventory_and_temporal_classes_are_closed() -> None:
    document = load_retail_v2()
    assert len(document["entities"]) == EXPECTED_ENTITY_COUNT
    versioned = {
        name
        for name, entity in document["entities"].items()
        if entity.get("temporalClass") == "cumulative_versioned"
    }
    assert versioned == set(VERSIONED_ENTITIES)


def test_channel_is_orthogonal_and_part_of_every_demand_grain() -> None:
    entities = load_retail_v2()["entities"]
    for name in CHANNEL_REQUIRED_ENTITIES:
        assert entities[name]["fields"]["channel_id"]["required"] is True
    for name in CHANNEL_GRAIN_ENTITIES:
        assert "channel_id" in entities[name]["grain"]
    assert "channel_id" not in entities["stores"]["fields"]


def test_contract_rejects_undefined_or_optional_primary_key_field() -> None:
    document = load_retail_v2()
    broken = deepcopy(document)
    broken["entities"]["sales"]["fields"]["sku_id"]["required"] = False
    with pytest.raises(ContractValidationError, match="must be required"):
        validate_retail_v2(broken)


def test_contract_rejects_a_fourth_versioned_entity() -> None:
    document = load_retail_v2()
    broken = deepcopy(document)
    broken["entities"]["sell_prices"]["temporalClass"] = "cumulative_versioned"
    with pytest.raises(ContractValidationError, match="must be exactly"):
        validate_retail_v2(broken)


def test_supplier_origin_is_required_but_nullable() -> None:
    """Required means the key is present; it does not override nullable."""

    supplier = load_retail_v2()["entities"]["suppliers_leadtimes"]
    origin = supplier["fields"]["from_location_id"]
    assert "from_location_id" in supplier["grain"]
    assert "from_location_id" in supplier["primaryKey"]
    assert origin["required"] is True
    assert origin["nullable"] is True


def test_contract_rejects_non_boolean_nullable() -> None:
    document = load_retail_v2()
    broken = deepcopy(document)
    broken["entities"]["suppliers_leadtimes"]["fields"]["from_location_id"][
        "nullable"
    ] = "yes"
    with pytest.raises(ContractValidationError, match="nullable must be boolean"):
        validate_retail_v2(broken)
