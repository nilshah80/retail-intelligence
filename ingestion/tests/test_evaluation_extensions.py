"""Adversarial/evaluation-admin Phase-2 extension fixtures."""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

import duckdb
import pytest
from retail_ingestion.profiles import load_source_profile

from .oracles.generator_truth import (
    ORACLE_PROFILE_VERSION,
    actual_units_by_market,
    expected_units_by_market,
)
from .oracles.source_controls import (
    SOURCE_CONTROL_PROFILE_VERSION,
    fulfilled_units_by_market,
    ordered_units_by_market,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = (
    REPO_ROOT
    / "datagen"
    / "output"
    / "multi-market-10-year-demo"
    / "run-c5eb1506ecd4c550"
)
CURATED_DATABASE = (
    REPO_ROOT
    / "ingestion"
    / "data"
    / "curated"
    / "run-c5eb1506ecd4c550"
    / "retail_v2.duckdb"
)
SOURCE_PROFILE = (
    REPO_ROOT
    / "ingestion"
    / "src"
    / "retail_ingestion"
    / "profiles"
    / "retail_datagen.yaml"
)


def _canonical_market_controls(values: dict[str, int]) -> dict[str, int]:
    profile = load_source_profile(SOURCE_PROFILE)
    aliases = {
        str(instance.get("sourceMarketId", instance["marketId"])): str(
            instance["marketId"]
        )
        for instance in profile["sourceInstances"]
    }
    return {
        aliases.get(market_id, market_id): units
        for market_id, units in values.items()
    }


def test_geographic_scope_collisions_require_market_qualification() -> None:
    """Literal West/city collisions cannot cross markets in any scoped join."""

    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE scopes (
                market_id VARCHAR,
                geo_scope_type VARCHAR,
                geo_scope_id VARCHAR,
                label VARCHAR
            );
            INSERT INTO scopes VALUES
                ('india-mumbai', 'region', 'west', 'West'),
                ('us-new-york', 'region', 'west', 'West'),
                ('india-mumbai', 'location', 'springfield', 'Springfield'),
                ('us-new-york', 'location', 'springfield', 'Springfield');
            CREATE TABLE observations AS
                SELECT * FROM scopes;
            """
        )
        qualified = connection.execute(
            """
            SELECT COUNT(*)
            FROM observations AS observation
            JOIN scopes AS scope
              USING (market_id, geo_scope_type, geo_scope_id)
            """
        ).fetchone()[0]
        unqualified = connection.execute(
            """
            SELECT COUNT(*)
            FROM observations AS observation
            JOIN scopes AS scope
              USING (geo_scope_type, geo_scope_id)
            """
        ).fetchone()[0]
    assert qualified == 4
    assert unqualified == 8


@pytest.mark.pinned_run
def test_evaluation_admin_hidden_truth_matches_ordered_demand_control() -> None:
    assert ORACLE_PROFILE_VERSION == (
        "retail-datagen-hidden-control-oracle/1.0.0"
    )
    assert expected_units_by_market(SOURCE_RUN) == ordered_units_by_market(SOURCE_RUN)


@pytest.mark.pinned_run
def test_public_fulfillment_control_matches_canonical_realized_sales() -> None:
    assert SOURCE_CONTROL_PROFILE_VERSION == (
        "retail-datagen-public-controls/1.0.0"
    )
    assert _canonical_market_controls(
        fulfilled_units_by_market(SOURCE_RUN)
    ) == actual_units_by_market(CURATED_DATABASE)


@pytest.mark.pinned_run
def test_webhook_hmac_and_identifier_parity_fixtures() -> None:
    secret = b"northstar-synthetic-fixture-secret"
    paths = str(SOURCE_RUN / "shopify" / "*" / "webhook_hmac_fixtures.parquet")
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            SELECT body, hmacHeader, validExpected, idParityOrderId
            FROM read_parquet(?)
            ORDER BY shopDomain, fixtureId
            """,
            [paths],
        ).fetchall()
    assert len(rows) == 24
    outcomes: set[bool] = set()
    for body, supplied, expected, parity_order_id in rows:
        calculated = base64.b64encode(
            hmac.new(secret, body.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        valid = hmac.compare_digest(calculated, supplied)
        expected_valid = expected == "true"
        outcomes.add(expected_valid)
        assert valid is expected_valid
        assert f'"id":"{parity_order_id}"' in body
    assert outcomes == {False, True}


@pytest.mark.pinned_run
def test_fulfillment_return_and_refund_histories_are_consistent() -> None:
    fulfillment_paths = str(
        SOURCE_RUN / "shopify" / "*" / "fulfillment_status_history.parquet"
    )
    return_paths = str(
        SOURCE_RUN / "shopify" / "*" / "returns" / "**" / "*.parquet"
    )
    refund_paths = str(
        SOURCE_RUN / "shopify" / "*" / "refunds" / "**" / "*.parquet"
    )
    transaction_paths = str(
        SOURCE_RUN
        / "shopify"
        / "*"
        / "refund_transactions"
        / "**"
        / "*.parquet"
    )
    with duckdb.connect() as connection:
        invalid_fulfillment_paths = connection.execute(
            """
            WITH paths AS (
                SELECT
                    fulfillmentId,
                    string_agg(
                        status,
                        '>' ORDER BY CAST(sequence AS INTEGER)
                    ) AS status_path,
                    COUNT(*) AS states,
                    COUNT(DISTINCT CAST(sequence AS INTEGER)) AS sequences
                FROM read_parquet(?)
                GROUP BY fulfillmentId
            )
            SELECT COUNT(*)
            FROM paths
            WHERE status_path NOT IN (
                'SUBMITTED>IN_PROGRESS',
                'SUBMITTED>IN_PROGRESS>DELIVERED',
                'SUBMITTED>IN_PROGRESS>DELIVERED>CLOSED'
            )
               OR states <> sequences
            """,
            [fulfillment_paths],
        ).fetchone()[0]
        invalid_returns = connection.execute(
            """
            SELECT COUNT(*)
            FROM read_parquet(?)
            WHERE status NOT IN ('OPEN', 'CLOSED', 'DECLINED')
               OR CAST(processedAt AS TIMESTAMPTZ)
                  < CAST(requestedAt AS TIMESTAMPTZ)
            """,
            [return_paths],
        ).fetchone()[0]
        invalid_refunds = connection.execute(
            """
            SELECT COUNT(*)
            FROM read_parquet(?) AS refund
            JOIN read_parquet(?) AS transaction
              ON transaction.refundId = refund.id
            WHERE
                (refund.status = 'SUCCESS' AND transaction.status <> 'SUCCESS')
                OR
                (refund.status = 'FAILED' AND transaction.status <> 'FAILURE')
                OR
                (refund.status = 'SUCCESS'
                 AND CAST(refund.totalRefunded AS DECIMAL(18, 2))
                     <> CAST(transaction.amount AS DECIMAL(18, 2)))
                OR
                (refund.status = 'FAILED'
                 AND CAST(refund.totalRefunded AS DECIMAL(18, 2)) <> 0)
            """,
            [refund_paths, transaction_paths],
        ).fetchone()[0]
    assert invalid_fulfillment_paths == 0
    assert invalid_returns == 0
    assert invalid_refunds == 0
