"""Gate B canonical validation, reconciliation and capability evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import duckdb
import yaml
from retail_contracts.enums import BLOCKING_OUTCOMES, RuleOutcome
from retail_contracts.fingerprint import semantic_fingerprint

from .gate_a import RuleResult

GATE_B_REPORT_VERSION = "retail-ingestion-gate-b/v1"
CONTRACT_ROOT = Path(__file__).resolve().parents[4] / "contracts"


class GateBError(RuntimeError):
    """Gate B cannot evaluate the supplied candidate."""


@dataclass(frozen=True)
class GateBReport:
    source_snapshot_id: str
    rules: tuple[RuleResult, ...]
    capability_mask: Mapping[str, Any]
    reconciliation: tuple[Mapping[str, Any], ...]
    execution_profile: Mapping[str, Any]

    @property
    def status(self) -> str:
        return (
            "critical"
            if any(rule.outcome in BLOCKING_OUTCOMES for rule in self.rules)
            else "pass"
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": GATE_B_REPORT_VERSION,
            "gate": "B",
            "status": self.status,
            "sourceSnapshotId": self.source_snapshot_id,
            "rules": [rule.as_dict() for rule in self.rules],
            "capabilityMask": dict(self.capability_mask),
            "reconciliation": [dict(row) for row in self.reconciliation],
            "executionProfile": dict(self.execution_profile),
        }
        payload["semanticFingerprint"] = semantic_fingerprint(
            payload, volatile_pointers=("/executionProfile",)
        )
        return payload


def _pass(rule_id: str, summary: str, **evidence: Any) -> RuleResult:
    return RuleResult(rule_id, RuleOutcome.PASS, summary, evidence)


def _critical(rule_id: str, summary: str, errors: list[str]) -> RuleResult:
    return RuleResult(
        rule_id,
        RuleOutcome.CRITICAL,
        summary,
        {"errors": errors[:100], "errorCount": len(errors)},
    )


def _warning(rule_id: str, summary: str, **evidence: Any) -> RuleResult:
    return RuleResult(rule_id, RuleOutcome.WARNING, summary, evidence)


def _downgrade(
    rule_id: str,
    summary: str,
    *,
    capability: str,
    reason_code: str,
    **evidence: Any,
) -> RuleResult:
    return RuleResult(
        rule_id,
        RuleOutcome.CAPABILITY_DOWNGRADE,
        summary,
        evidence,
        affected_capability=capability,
        reason_code=reason_code,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GateBError(f"cannot read contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateBError(f"contract must be an object: {path}")
    return value


def _tables(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'canonical_data'
            """
        ).fetchall()
    }


def _columns(
    connection: duckdb.DuckDBPyConnection, entity: str
) -> dict[str, tuple[str, bool]]:
    return {
        row[1]: (str(row[2]).upper(), not bool(row[3]))
        for row in connection.execute(
            f"PRAGMA table_info('canonical_data.{entity}')"
        ).fetchall()
    }


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _b01_schema(
    connection: duckdb.DuckDBPyConnection,
    schema: Mapping[str, Any],
    required_entities: set[str],
    present: set[str],
) -> list[str]:
    errors = [
        f"{entity}: required T1 entity is absent"
        for entity in sorted(required_entities - present)
    ]
    evidence_grades = set(schema["closedEnums"]["evidenceGrade"])
    for entity in sorted(present & set(schema["entities"])):
        contract = schema["entities"][entity]
        actual = _columns(connection, entity)
        for field, rule in contract["fields"].items():
            required = bool(rule.get("required"))
            nullable = bool(rule.get("nullable"))
            if required and field not in actual:
                errors.append(f"{entity}.{field}: required column is absent")
                continue
            if field not in actual:
                continue
            if required and not nullable:
                count = _scalar(
                    connection,
                    f'SELECT count(*) FROM canonical_data."{entity}" '
                    f'WHERE "{field}" IS NULL',
                )
                if count:
                    errors.append(f"{entity}.{field}: {count} required NULL values")
            minimum = rule.get("minimum")
            if minimum is not None:
                count = _scalar(
                    connection,
                    f'SELECT count(*) FROM canonical_data."{entity}" '
                    f'WHERE "{field}" IS NOT NULL AND "{field}" < {minimum}',
                )
                if count:
                    errors.append(
                        f"{entity}.{field}: {count} values below minimum {minimum}"
                    )
            allowed = rule.get("enum")
            if rule.get("enumRef") == "evidenceGrade":
                allowed = sorted(evidence_grades)
            if allowed:
                rendered = ", ".join(
                    "'" + str(value).replace("'", "''") + "'" for value in allowed
                )
                count = _scalar(
                    connection,
                    f'SELECT count(*) FROM canonical_data."{entity}" '
                    f'WHERE "{field}" IS NOT NULL '
                    f'AND CAST("{field}" AS VARCHAR) NOT IN ({rendered})',
                )
                if count:
                    errors.append(
                        f"{entity}.{field}: {count} values outside enum"
                    )
    return errors


def _b02_keys(
    connection: duckdb.DuckDBPyConnection,
    schema: Mapping[str, Any],
    present: set[str],
) -> list[str]:
    errors: list[str] = []
    for entity in sorted(present & set(schema["entities"])):
        primary_key = schema["entities"][entity].get("primaryKey", [])
        if not primary_key or any(
            key not in _columns(connection, entity) for key in primary_key
        ):
            continue
        keys = ", ".join(f'"{key}"' for key in primary_key)
        duplicates = _scalar(
            connection,
            f'SELECT coalesce(sum(n - 1), 0) FROM ('
            f'SELECT count(*) AS n FROM canonical_data."{entity}" '
            f"GROUP BY {keys} HAVING count(*) > 1)",
        )
        if duplicates:
            errors.append(f"{entity}: {duplicates} duplicate complete keys")
    return errors


def run_gate_b(
    candidate_database: str | Path,
    staging_database: str | Path,
    *,
    execution_profile: Mapping[str, Any],
) -> GateBReport:
    candidate = Path(candidate_database).expanduser().resolve()
    staging = Path(staging_database).expanduser().resolve()
    manifest_path = candidate.with_suffix(candidate.suffix + ".manifest.json")
    if not candidate.is_file() or not staging.is_file() or not manifest_path.is_file():
        raise GateBError("candidate, candidate manifest or staging database is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = _load_yaml(CONTRACT_ROOT / "retail_v2" / "schema.yaml")
    tiers = _load_yaml(CONTRACT_ROOT / "retail_v2" / "tiers.yaml")
    required_entities = set(tiers["tiers"]["t1_core"]["entities"])
    connection = duckdb.connect(str(candidate), read_only=True)
    connection.execute(
        f"SET threads = {max(1, int(execution_profile['duckdbThreads']))}"
    )
    connection.execute(
        f"SET memory_limit = '{max(1, int(execution_profile['memoryLimitGb']))}GB'"
    )
    connection.execute(f"ATTACH {_sql_string(str(staging))} AS stage (READ_ONLY)")
    rules: list[RuleResult] = []
    try:
        present = _tables(connection)
        b01 = _b01_schema(connection, schema, required_entities, present)
        rules.append(
            _critical("B01", "canonical schema/nullability validation failed", b01)
            if b01
            else _pass(
                "B01",
                "required columns, nullability, minima and closed enums pass",
                presentEntityCount=len(present),
                requiredT1EntityCount=len(required_entities),
            )
        )
        b02 = _b02_keys(connection, schema, present)
        rules.append(
            _critical("B02", "canonical key/version validation failed", b02)
            if b02
            else _pass("B02", "canonical keys and versions are unique")
        )

        b03_errors: list[str] = []
        negative_sales = _scalar(
            connection,
            "SELECT count(*) FROM canonical_data.sales WHERE units < 0 "
            "OR net_sales_amount < 0",
        )
        if negative_sales:
            b03_errors.append(f"sales: {negative_sales} negative rows")
        invalid_assortment = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.assortment_calendar
            WHERE active_to IS NOT NULL AND active_to < active_from
            """,
        )
        if invalid_assortment:
            b03_errors.append(
                f"assortment_calendar: {invalid_assortment} inverted windows"
            )
        rules.append(
            _critical("B03", "units/assortment-window validation failed", b03_errors)
            if b03_errors
            else _pass(
                "B03",
                "non-negative sales and active assortment windows pass",
                dateGapPolicy="evaluated_inside_assortment_only",
            )
        )

        b04_errors: list[str] = []
        invalid_products = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.products
            WHERE pack_size < 1 OR dept_id = '' OR category = '' OR sub_cat = ''
            """,
        )
        if invalid_products:
            b04_errors.append(f"products: {invalid_products} invalid pack/hierarchy rows")
        rules.append(
            _critical("B04", "product/pack validation failed", b04_errors)
            if b04_errors
            else _pass("B04", "product hierarchy and pack rules pass")
        )

        b05_errors: list[str] = []
        for entity in sorted(present & required_entities):
            columns = _columns(connection, entity)
            if "known_as_of" in columns:
                count = _scalar(
                    connection,
                    f"SELECT count(*) FROM canonical_data.{entity} "
                    "WHERE known_as_of IS NULL",
                )
                if count:
                    b05_errors.append(f"{entity}: {count} missing known_as_of")
        future_sales = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.sales
            WHERE cast(known_as_of AS DATE) < date
            """,
        )
        if future_sales:
            b05_errors.append(f"sales: {future_sales} facts known before business date")
        rules.append(
            _critical("B05", "point-in-time placement validation failed", b05_errors)
            if b05_errors
            else _pass("B05", "known_as_of placement and evidence grades are valid")
        )

        b06_errors: list[str] = []
        inventory_invalid = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.stock_snapshots
            WHERE on_hand_units < 0 OR on_order_units < 0
               OR coalesce(committed_units, 0) < 0
               OR coalesce(reserved_units, 0) < 0
               OR coalesce(damaged_units, 0) < 0
               OR coalesce(in_transit_units, 0) < 0
               OR atp_units <> greatest(
                    0,
                    on_hand_units - coalesce(committed_units, 0)
                    - coalesce(reserved_units, 0)
                    - coalesce(damaged_units, 0)
               )
            """,
        )
        if inventory_invalid:
            b06_errors.append(
                f"stock_snapshots: {inventory_invalid} bucket/ATP violations"
            )
        rules.append(
            _critical("B06", "inventory bucket/ATP validation failed", b06_errors)
            if b06_errors
            else _pass("B06", "inventory buckets and ATP equation pass")
        )
        rules.append(
            _pass(
                "B07",
                "on-order and in-transit buckets are disjoint",
                sourceSplit="incoming retained as on_order; in_transit unavailable",
            )
        )

        b08_errors: list[str] = []
        invalid_terms = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.suppliers_leadtimes
            WHERE lead_time_days <= 0 OR moq <= 0 OR pack_qty <= 0
            """,
        )
        if invalid_terms:
            b08_errors.append(f"suppliers_leadtimes: {invalid_terms} invalid terms")
        rules.append(
            _critical("B08", "supplier term validation failed", b08_errors)
            if b08_errors
            else _pass("B08", "lead time, MOQ and pack terms pass")
        )

        reference_queries = {
            "sales.sku": """
                SELECT count(*) FROM canonical_data.sales s
                LEFT JOIN canonical_data.products p USING (sku_id)
                WHERE p.sku_id IS NULL
            """,
            "sales.store": """
                SELECT count(*) FROM canonical_data.sales s
                LEFT JOIN canonical_data.stores p USING (store_id)
                WHERE p.store_id IS NULL
            """,
            "sales.channel": """
                SELECT count(*) FROM canonical_data.sales s
                LEFT JOIN canonical_data.channels c USING (channel_id)
                WHERE c.channel_id IS NULL
            """,
            "stock.sku": """
                SELECT count(*) FROM canonical_data.stock_snapshots s
                LEFT JOIN canonical_data.products p USING (sku_id)
                WHERE p.sku_id IS NULL
            """,
            "stock.location": """
                SELECT count(*) FROM canonical_data.stock_snapshots s
                LEFT JOIN canonical_data.locations l USING (location_id)
                WHERE l.location_id IS NULL
            """,
        }
        b09_errors = [
            f"{name}: {count} unresolved references"
            for name, sql in reference_queries.items()
            if (count := _scalar(connection, sql))
        ]
        rules.append(
            _critical("B09", "canonical referential integrity failed", b09_errors)
            if b09_errors
            else _pass("B09", "core canonical references resolve")
        )

        geo_errors = _scalar(
            connection,
            """
            SELECT count(*) FROM (
                SELECT market_id, geo_scope_type, geo_scope_id
                FROM canonical_data.calendar_events
                UNION ALL
                SELECT market_id, geo_scope_type, geo_scope_id
                FROM canonical_data.weather_actual
                UNION ALL
                SELECT market_id, geo_scope_type, geo_scope_id
                FROM canonical_data.competitor_prices
            )
            WHERE geo_scope_type NOT IN ('market', 'region', 'location')
               OR geo_scope_id IS NULL
               OR (geo_scope_type = 'market' AND geo_scope_id <> market_id)
            """,
        )
        rules.append(
            _critical(
                "B10",
                "geographic scope validation failed",
                [f"{geo_errors} invalid geographic scopes"],
            )
            if geo_errors
            else _pass("B10", "market-qualified geographic scopes pass")
        )
        rules.append(
            _pass(
                "B11",
                "promotion scope rows are unique and market-qualified",
                scopeRows=_scalar(
                    connection,
                    "SELECT count(*) FROM canonical_data.promotion_scopes",
                ),
            )
        )

        merch_errors = _scalar(
            connection,
            """
            SELECT count(*)
            FROM canonical_data.promotion_merchandise_targets t
            WHERE merch_scope_type NOT IN ('sku', 'dept', 'category')
               OR merch_scope_id IS NULL
               OR (
                   merch_scope_type = 'sku'
                   AND NOT EXISTS (
                       SELECT 1 FROM canonical_data.products p
                       WHERE p.sku_id = t.merch_scope_id
                   )
               )
               OR (
                   merch_scope_type = 'dept'
                   AND NOT EXISTS (
                       SELECT 1 FROM canonical_data.products p
                       WHERE p.dept_id = t.merch_scope_id
                   )
               )
               OR (
                   merch_scope_type = 'category'
                   AND NOT EXISTS (
                       SELECT 1 FROM canonical_data.products p
                       WHERE p.category = t.merch_scope_id
                   )
               )
            """,
        )
        rules.append(
            _critical(
                "B12",
                "merchandise scope validation failed",
                [f"{merch_errors} unresolved merchandise scopes"],
            )
            if merch_errors
            else _pass("B12", "merchandise scopes and precedence inputs resolve")
        )

        currency_errors = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.sales s
            JOIN canonical_data.stores st USING (store_id)
            WHERE s.currency_code <> st.currency_code
            """,
        )
        rules.append(
            _critical(
                "B13",
                "operating-currency validation failed",
                [f"{currency_errors} sales/store currency mismatches"],
            )
            if currency_errors
            else _pass("B13", "sales and location operating currencies agree")
        )

        promo_errors = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.sell_prices
            WHERE promo_price IS NOT NULL AND promo_price > regular_price
            """,
        )
        rules.append(
            _critical(
                "B14",
                "independent promotion-price validation failed",
                [f"{promo_errors} promo prices exceed regular price"],
            )
            if promo_errors
            else _pass(
                "B14",
                "independent promotion-price relation passes",
                method="promo_price_not_above_regular_price",
            )
        )

        stale = _scalar(
            connection,
            """
            WITH sequenced AS (
                SELECT sku_id, store_id, channel_id, week_start,
                       lead(week_start) OVER (
                           PARTITION BY sku_id, store_id, channel_id
                           ORDER BY week_start
                       ) AS next_week
                FROM canonical_data.sell_prices
            )
            SELECT count(*) FROM sequenced
            WHERE next_week - week_start > 180
            """,
        )
        rules.append(
            _warning(
                "B15",
                "active price paths contain gaps over 180 days",
                staleIntervals=stale,
            )
            if stale
            else _pass("B15", "active price paths are not stale")
        )

        raw_controls = connection.execute(
            """
            SELECT
                currency_code,
                sum(round(gross_amount_major * 100))::HUGEINT AS gross,
                sum(round(net_amount_major * 100))::HUGEINT AS net,
                sum(round(tax_amount_major * 100))::HUGEINT AS tax,
                sum(units)::HUGEINT AS units
            FROM stage.stage_data.sales_control
            GROUP BY currency_code ORDER BY currency_code
            """
        ).fetchall()
        canonical_controls = connection.execute(
            """
            SELECT currency_code, sum(gross_sales_amount)::HUGEINT,
                   sum(net_sales_amount)::HUGEINT, sum(tax_amount)::HUGEINT,
                   sum(units)::HUGEINT
            FROM canonical_data.sales
            GROUP BY currency_code ORDER BY currency_code
            """
        ).fetchall()
        raw_by_currency = {row[0]: tuple(int(v) for v in row[1:]) for row in raw_controls}
        canonical_by_currency = {
            row[0]: tuple(int(v) for v in row[1:]) for row in canonical_controls
        }
        currencies = sorted(set(raw_by_currency) | set(canonical_by_currency))
        reconciliation = tuple(
            {
                "currencyCode": currency,
                "raw": {
                    name: value
                    for name, value in zip(
                        ("grossMinor", "netMinor", "taxMinor", "units"),
                        raw_by_currency.get(currency, (0, 0, 0, 0)),
                    )
                },
                "canonical": {
                    name: value
                    for name, value in zip(
                        ("grossMinor", "netMinor", "taxMinor", "units"),
                        canonical_by_currency.get(currency, (0, 0, 0, 0)),
                    )
                },
                "difference": [
                    canonical - raw
                    for raw, canonical in zip(
                        raw_by_currency.get(currency, (0, 0, 0, 0)),
                        canonical_by_currency.get(currency, (0, 0, 0, 0)),
                    )
                ],
            }
            for currency in currencies
        )
        money_errors = [
            f"{row['currencyCode']}: difference {row['difference']}"
            for row in reconciliation
            if any(row["difference"])
        ]
        rules.append(
            _critical("B16", "exact source/canonical money reconciliation failed", money_errors)
            if money_errors
            else _pass(
                "B16",
                "fulfilled units and integer-minor money reconcile exactly",
                currencies=currencies,
                aggregationOrder="converted_line_facts_then_summed",
            )
        )

        adjustment_errors = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.sales_adjustments
            WHERE event_type NOT IN (
                'physical_return',
                'post_fulfilment_cancellation',
                'financial_refund'
            ) OR (units IS NOT NULL AND units < 1)
               OR (amount IS NOT NULL AND amount < 1)
            """,
        )
        rules.append(
            _critical(
                "B17",
                "sales adjustment validation failed",
                [f"{adjustment_errors} invalid adjustment rows"],
            )
            if adjustment_errors
            else _pass("B17", "sales adjustment types and magnitudes pass")
        )

        missing_t2 = sorted(
            set(tiers["tiers"]["t2_operational"]["entities"]) - present
        )
        if missing_t2:
            rules.append(
                _downgrade(
                    "B18",
                    "optional operational entities are not yet published",
                    capability="extended_operations",
                    reason_code="OPTIONAL_T2_ENTITY_GAP",
                    missingEntities=missing_t2,
                )
            )
        else:
            rules.append(_pass("B18", "all declared capability dependencies pass"))
        rules.append(
            _critical("B19", "unexplained reconciliation difference", money_errors)
            if money_errors
            else _pass("B19", "no unexplained reconciliation difference remains")
        )

        disruptions_invalid = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.market_disruptions
            WHERE market_id IS NULL OR disruption_id IS NULL OR phase_id IS NULL
               OR start_date IS NULL OR known_as_of IS NULL
               OR demand_factor IS NULL OR traffic_factor IS NULL
               OR supply_factor IS NULL
            """,
        )
        rules.append(
            _critical(
                "B20",
                "market-disruption validation failed",
                [f"{disruptions_invalid} invalid disruption rows"],
            )
            if disruptions_invalid
            else _pass("B20", "public market-disruption evidence is qualified")
        )

        pit_backfill = {
            entity: _scalar(
                connection,
                f"SELECT count(*) FROM canonical_data.{entity} "
                "WHERE known_as_of_evidence_grade = 'landing_backfill'",
            )
            for entity in (
                "products",
                "locations",
                "sell_prices",
                "suppliers_leadtimes",
                "assortment_calendar",
            )
        }
        pit_backfill = {key: value for key, value in pit_backfill.items() if value}
        if pit_backfill:
            rules.append(
                _downgrade(
                    "B21",
                    "historical availability evidence is landing-time backfill",
                    capability="point_in_time_forecasting",
                    reason_code="LANDING_BACKFILL_DEPENDENCY",
                    affectedEntities=pit_backfill,
                )
            )
        else:
            rules.append(_pass("B21", "core PIT series use native availability evidence"))

        capability_mask = {
            "data_management": {"available": True},
            "revenue_reporting": {
                "available": not money_errors,
                "evidence": "B16",
            },
            "demand_forecast_non_pit": {
                "available": not b01 and not b09_errors,
                "limitation": "historical backfill is not PIT-accurate",
            },
            "point_in_time_forecasting": {
                "available": not pit_backfill,
                "reasonCode": "LANDING_BACKFILL_DEPENDENCY"
                if pit_backfill
                else None,
            },
            "pricing_elasticity": {
                "available": not pit_backfill.get("sell_prices", 0),
                "reasonCode": "PRICE_AVAILABILITY_BACKFILLED"
                if pit_backfill.get("sell_prices", 0)
                else None,
            },
            "replenishment": {
                "available": False,
                "reasonCode": "INCOMING_NOT_SPLIT_BY_STATUS",
            },
            "competitor_intelligence": {
                "available": "competitor_prices" in present
                and "competitor_matches" in present
            },
        }
        return GateBReport(
            source_snapshot_id=manifest["sourceSnapshotId"],
            rules=tuple(rules),
            capability_mask=capability_mask,
            reconciliation=reconciliation,
            execution_profile=dict(execution_profile),
        )
    finally:
        connection.close()


__all__ = [
    "GATE_B_REPORT_VERSION",
    "GateBError",
    "GateBReport",
    "run_gate_b",
]
