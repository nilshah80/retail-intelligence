"""Gate B canonical validation, reconciliation and capability evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping

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


def _apply_upstream_capability_downgrades(
    capability_mask: Mapping[str, Any],
    upstream_gate_a: Mapping[str, Any] | None,
    *,
    source_snapshot_id: str,
) -> dict[str, Any]:
    merged = dict(capability_mask)
    if upstream_gate_a is None:
        return merged
    if upstream_gate_a.get("sourceSnapshotId") != source_snapshot_id:
        raise GateBError("Gate A and canonical candidate snapshot identities differ")
    for rule in upstream_gate_a.get("rules", []):
        if rule.get("outcome") != "capability_downgrade":
            continue
        capability = rule.get("affectedCapability")
        reason_code = rule.get("reasonCode")
        if not isinstance(capability, str) or not capability:
            raise GateBError("Gate A capability downgrade has no affectedCapability")
        if not isinstance(reason_code, str) or not reason_code:
            raise GateBError("Gate A capability downgrade has no reasonCode")
        merged[capability] = {
            "available": False,
            "reasonCode": reason_code,
            "evidence": rule.get("ruleId"),
            "sourceGate": "A",
        }
    return merged


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


#: Grades that support reconstructing a fact at a past origin. Anything weaker
#: describes only the present, which is the whole reason the replay capability is
#: separate from the current-snapshot one.
_ORIGIN_SAFE_GRADES: Final[frozenset[str]] = frozenset(
    {
        "native_observed",
        "native_processed",
        "native_posted_available",
        "native_extracted",
    }
)


def _replenishment_capabilities(
    connection: duckdb.DuckDBPyConnection,
    present: set[str],
    *,
    pit_backfill: Mapping[str, int],
    incoming_split_mismatch: int,
) -> dict[str, Any]:
    """Evaluate the two inventory capabilities instead of asserting one verdict.

    `P4-2` task 16. This was hard-coded `available: False` with reason
    HISTORICAL_INBOUND_STATUS_NOT_VERSIONED. That answer happened to be correct
    for the pin it was written against, which is exactly why it was dangerous: a
    publication that DID carry the missing evidence would still have reported the
    capability unavailable, and a publication that lost evidence it used to have
    would report the same thing. A constant cannot detect either.

    Temporal-evidence policy v2 splits the claim in two, because DC
    current-position analytics are serviceable on the current pin while
    origin-safe replay is not, and one flag cannot say both.
    """

    def rows(entity: str, predicate: str = "TRUE") -> int:
        if entity not in present:
            return 0
        return _scalar(
            connection,
            f"SELECT count(*) FROM canonical_data.{entity} WHERE {predicate}",
        )

    def weakly_graded(entity: str) -> int:
        """Rows whose availability evidence cannot support a past origin."""

        if entity not in present:
            return 0
        allowed = ", ".join(_sql_string(grade) for grade in sorted(_ORIGIN_SAFE_GRADES))
        return _scalar(
            connection,
            f"SELECT count(*) FROM canonical_data.{entity} "
            f"WHERE known_as_of_evidence_grade NOT IN ({allowed})",
        )

    # Current snapshot: a position, its inbound supply, its terms and its routes,
    # all evaluated at the cutoff. Landing evidence is admissible because the claim
    # is explicitly scoped to now.
    current_missing = sorted(
        entity
        for entity in ("stock_snapshots", "inbound_shipments", "locations")
        if rows(entity) == 0
    )
    # A term and a lane are required, but either generation satisfies the current
    # claim: v1 `suppliers_leadtimes` describes the present adequately even though
    # its null origin makes it replay-ineligible.
    has_terms = rows("supply_terms") > 0 or rows("suppliers_leadtimes") > 0
    has_lanes = rows("service_lanes") > 0
    if not has_terms:
        current_missing.append("supply_terms")
    current_available = not current_missing and has_lanes

    # Replay: every fact above must be reconstructible at an arbitrary origin, and
    # store-grain state must exist. The current pin fails on all four counts.
    replay_reasons: list[str] = []
    if rows("inbound_shipment_status_events") == 0:
        replay_reasons.append("HISTORICAL_INBOUND_STATUS_NOT_VERSIONED")
    if rows("inventory_transfer_events") == 0:
        replay_reasons.append("HISTORICAL_TRANSFER_STATUS_NOT_VERSIONED")
    if not has_lanes:
        replay_reasons.append("SERVICE_LANES_NOT_DECLARED")
    store_stock_rows = rows(
        "stock_snapshots",
        "location_id IN (SELECT location_id FROM canonical_data.locations "
        "WHERE type = 'store')",
    )
    if store_stock_rows == 0:
        replay_reasons.append("STORE_GRAIN_INVENTORY_ABSENT")
    if rows("supply_terms") == 0:
        replay_reasons.append("ORIGIN_SAFE_SUPPLY_TERMS_ABSENT")
    else:
        weak_terms = weakly_graded("supply_terms")
        if weak_terms:
            replay_reasons.append("EVIDENCE_GRADE_TOO_WEAK")
    # A fulfillment knowable before it occurred admits future state into replay.
    # This is a placement violation rather than weak evidence, so it is reported
    # under its own reason code.
    if "sales_fulfillments" in present:
        premature = _scalar(
            connection,
            "SELECT count(*) FROM canonical_data.sales_fulfillments "
            "WHERE known_as_of < fulfilled_at",
        )
        if premature:
            replay_reasons.append("FULFILLMENT_AVAILABLE_BEFORE_EVENT")
    else:
        premature = 0
    if "inbound_shipment_status_events" in present:
        premature_status = _scalar(
            connection,
            "SELECT count(*) FROM canonical_data.inbound_shipment_status_events "
            "WHERE known_as_of < status_effective_at",
        )
        if premature_status:
            replay_reasons.append("STATUS_AVAILABLE_BEFORE_EVENT")
    else:
        premature_status = 0

    replay_available = not replay_reasons
    return {
        "inventory_replenishment_current_snapshot": {
            "available": current_available,
            "reasonCode": (
                None
                if current_available
                else (
                    "SERVICE_LANES_NOT_DECLARED"
                    if not has_lanes
                    else "REQUIRED_CURRENT_EVIDENCE_ABSENT"
                )
            ),
            "missingEntities": current_missing,
            "currentSnapshotStatusSplitAvailable": not incoming_split_mismatch,
            "scope": "current_cutoff_only",
        },
        "inventory_replenishment_replay": {
            "available": replay_available,
            # Every failing reason, not the first. A caller that fixes one and
            # re-runs should not discover the next one at a time.
            "reasonCodes": replay_reasons,
            "reasonCode": replay_reasons[0] if replay_reasons else None,
            "storeGrainInventoryRows": store_stock_rows,
            "prematureFulfillmentRows": premature,
            "prematureStatusRows": premature_status,
            "landingBackfillDependencies": dict(pit_backfill),
        },
        # Retained key. It meant "origin-safe replenishment", so it tracks the
        # replay verdict rather than the easier current-snapshot one: a consumer
        # reading the old name must not silently gain a weaker guarantee.
        "replenishment": {
            "available": replay_available,
            "reasonCode": replay_reasons[0] if replay_reasons else None,
            "currentSnapshotStatusSplitAvailable": not incoming_split_mismatch,
            "supersededBy": [
                "inventory_replenishment_current_snapshot",
                "inventory_replenishment_replay",
            ],
        },
    }


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
    upstream_gate_a: Mapping[str, Any] | None = None,
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
        non_positive_prices = _scalar(
            connection,
            """
            SELECT count(*) FROM canonical_data.sell_prices
            WHERE net_price <= 0 OR regular_price <= 0
               OR (promo_price IS NOT NULL AND promo_price <= 0)
            """,
        )
        if non_positive_prices:
            b03_errors.append(
                f"sell_prices: {non_positive_prices} non-positive price rows"
            )
        active_date_count, missing_active_dates = connection.execute(
            """
            WITH active_dates AS (
                SELECT DISTINCT
                    assortment.sku_id,
                    assortment.store_id,
                    assortment.channel_id,
                    calendar.date
                FROM canonical_data.assortment_calendar AS assortment
                JOIN canonical_data.stores AS stores
                  ON stores.store_id = assortment.store_id
                JOIN canonical_data.calendar AS calendar
                  ON calendar.market_id = stores.market_id
                 AND calendar.date >= assortment.active_from
                 AND (
                        assortment.active_to IS NULL
                        OR calendar.date <= assortment.active_to
                     )
            )
            SELECT
                count(*)::BIGINT,
                count(*) FILTER (WHERE sales.sku_id IS NULL)::BIGINT
            FROM active_dates
            LEFT JOIN canonical_data.sales AS sales
              ON sales.sku_id = active_dates.sku_id
             AND sales.store_id = active_dates.store_id
             AND sales.channel_id = active_dates.channel_id
             AND sales.date = active_dates.date
             AND sales.sales_version = 1
            """
        ).fetchone()
        if missing_active_dates:
            b03_errors.append(
                f"sales: {missing_active_dates} active assortment dates are absent"
            )
        sales_outside_assortment = _scalar(
            connection,
            """
            SELECT count(*)
            FROM canonical_data.sales AS sales
            WHERE sales.units > 0
              AND NOT EXISTS (
                    SELECT 1
                    FROM canonical_data.assortment_calendar AS assortment
                    WHERE assortment.sku_id = sales.sku_id
                      AND assortment.store_id = sales.store_id
                      AND assortment.channel_id = sales.channel_id
                      AND sales.date >= assortment.active_from
                      AND (
                            assortment.active_to IS NULL
                            OR sales.date <= assortment.active_to
                          )
              )
            """,
        )
        if sales_outside_assortment:
            b03_errors.append(
                f"sales: {sales_outside_assortment} positive rows outside assortment"
            )
        zero_sales_rows = _scalar(
            connection,
            "SELECT count(*) FROM canonical_data.sales WHERE units = 0",
        )
        rules.append(
            _critical(
                "B03",
                "sales density/price/assortment validation failed",
                b03_errors,
            )
            if b03_errors
            else _pass(
                "B03",
                "active assortment dates are dense and sales/prices are valid",
                dateGapPolicy="distinct_daily_row_inside_active_assortment_v1",
                activeAssortmentDates=int(active_date_count),
                missingActiveDates=int(missing_active_dates),
                zeroSalesRows=zero_sales_rows,
                positiveSalesOutsideAssortment=sales_outside_assortment,
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
        source_atp_mismatch = _scalar(
            connection,
            """
            SELECT count(*)
            FROM canonical_data.stock_snapshots AS canonical
            JOIN stage.stage_data.inventory AS source
              ON canonical.sku_id = concat(
                    source.market_id, ':', source.sku_source_key
                 )
             AND canonical.snapshot_date = source.snapshot_date
            JOIN stage.stage_data.location_crosswalk AS crosswalk
              ON crosswalk.source_system = source.source_system
             AND crosswalk.market_id = source.market_id
             AND crosswalk.source_location_key = source.location_source_key
             AND canonical.location_id = concat(
                    source.market_id, ':', crosswalk.canonical_location_key
                 )
            WHERE source.source_observed_atp_units IS NOT NULL
              AND canonical.atp_units <> source.source_observed_atp_units
            """,
        )
        if source_atp_mismatch:
            b06_errors.append(
                "stock_snapshots: "
                f"{source_atp_mismatch} ATP rows disagree with source observed ATP"
            )
        rules.append(
            _critical("B06", "inventory bucket/ATP validation failed", b06_errors)
            if b06_errors
            else _pass("B06", "inventory buckets and ATP equation pass")
        )
        inbound_status_rows = _scalar(
            connection,
            """
            SELECT count(*)
            FROM stage.stage_data.inbound_shipments
            WHERE replace(lower(status), ' ', '_') IN (
                'in_transit', 'dispatched', 'shipped'
            )
            """,
        )
        incoming_split_mismatch = _scalar(
            connection,
            """
            WITH boundary AS (
                SELECT market_id, max(snapshot_date) AS snapshot_date
                FROM stage.stage_data.inventory
                GROUP BY market_id
            ),
            transit AS (
                SELECT
                    shipment.market_id,
                    shipment.sku_source_key,
                    crosswalk.canonical_location_key,
                    sum(shipment.qty)::BIGINT AS units
                FROM stage.stage_data.inbound_shipments AS shipment
                JOIN stage.stage_data.location_crosswalk AS crosswalk
                  ON crosswalk.source_system = shipment.source_system
                 AND crosswalk.market_id = shipment.market_id
                 AND crosswalk.source_location_key =
                     shipment.to_location_source_key
                WHERE replace(lower(shipment.status), ' ', '_') IN (
                    'in_transit', 'dispatched', 'shipped'
                )
                GROUP BY
                    shipment.market_id,
                    shipment.sku_source_key,
                    crosswalk.canonical_location_key
            )
            SELECT count(*)
            FROM stage.stage_data.inventory AS source
            JOIN boundary
              ON boundary.market_id = source.market_id
             AND boundary.snapshot_date = source.snapshot_date
            JOIN stage.stage_data.location_crosswalk AS crosswalk
              ON crosswalk.source_system = source.source_system
             AND crosswalk.market_id = source.market_id
             AND crosswalk.source_location_key = source.location_source_key
            JOIN canonical_data.stock_snapshots AS canonical
              ON canonical.sku_id = concat(
                    source.market_id, ':', source.sku_source_key
                 )
             AND canonical.location_id = concat(
                    source.market_id, ':', crosswalk.canonical_location_key
                 )
             AND canonical.snapshot_date = source.snapshot_date
            LEFT JOIN transit
              ON transit.market_id = source.market_id
             AND transit.sku_source_key = source.sku_source_key
             AND transit.canonical_location_key =
                 crosswalk.canonical_location_key
            WHERE canonical.in_transit_units <> least(
                    source.incoming_units, coalesce(transit.units, 0)
                  )
               OR canonical.on_order_units <> greatest(
                    source.incoming_units
                    - least(
                        source.incoming_units, coalesce(transit.units, 0)
                      ),
                    0
                  )
               OR canonical.on_order_units + canonical.in_transit_units
                    <> source.incoming_units
            """,
        )
        rules.append(
            _critical(
                "B07",
                "on-order/in-transit source-status split failed",
                [f"{incoming_split_mismatch} current snapshot rows mismatch"],
            )
            if incoming_split_mismatch
            else _pass(
                "B07",
                "current on-order and in-transit buckets are disjoint",
                sourceSplit="current_extract_boundary_inbound_status_v1",
                inTransitSourceRows=inbound_status_rows,
                historicalStatusVersioned=False,
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
        promotion_scope_errors = _scalar(
            connection,
            """
            SELECT count(*)
            FROM (
                SELECT
                    scope.market_id,
                    scope.promo_id,
                    scope.scope_row_id,
                    count(*) AS copies,
                    bool_or(promo.promo_id IS NULL) AS missing_promotion,
                    bool_or(
                        scope.location_id IS NOT NULL
                        AND NOT starts_with(
                            scope.location_id, scope.market_id || ':'
                        )
                    ) AS cross_market_location
                FROM canonical_data.promotion_scopes AS scope
                LEFT JOIN canonical_data.promotions AS promo
                  ON promo.market_id = scope.market_id
                 AND promo.promo_id = scope.promo_id
                GROUP BY
                    scope.market_id, scope.promo_id, scope.scope_row_id
            )
            WHERE copies <> 1
               OR missing_promotion
               OR cross_market_location
            """,
        )
        rules.append(
            _critical(
                "B11",
                "promotion-scope validation failed",
                [f"{promotion_scope_errors} invalid promotion scope rows"],
            )
            if promotion_scope_errors
            else _pass(
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
                SELECT
                       prices.sku_id,
                       prices.store_id,
                       prices.channel_id,
                       prices.week_start,
                       lead(week_start) OVER (
                           PARTITION BY
                               prices.sku_id, prices.store_id, prices.channel_id
                           ORDER BY week_start
                       ) AS next_week,
                       bounds.end_date
                FROM canonical_data.sell_prices AS prices
                JOIN canonical_data.stores AS stores
                  ON stores.store_id = prices.store_id
                JOIN (
                    SELECT market_id, max(date) AS end_date
                    FROM canonical_data.calendar
                    GROUP BY market_id
                ) AS bounds
                  ON bounds.market_id = stores.market_id
            )
            SELECT count(*)
            FROM sequenced AS prices
            WHERE EXISTS (
                SELECT 1
                FROM canonical_data.assortment_calendar AS assortment
                WHERE assortment.sku_id = prices.sku_id
                  AND assortment.store_id = prices.store_id
                  AND assortment.channel_id = prices.channel_id
                  AND date_diff(
                        'day',
                        greatest(prices.week_start, assortment.active_from),
                        least(
                            coalesce(prices.next_week, prices.end_date),
                            coalesce(assortment.active_to, prices.end_date)
                        )
                      ) > 180
            )
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
                sum(gross_minor)::HUGEINT AS gross,
                sum(net_minor)::HUGEINT AS net,
                sum(tax_minor)::HUGEINT AS tax,
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
        fulfillment_mismatches = _scalar(
            connection,
            """
            WITH sales AS (
                SELECT
                    sku_id,
                    store_id,
                    channel_id,
                    date,
                    sum(units)::HUGEINT AS units
                FROM canonical_data.sales
                GROUP BY sku_id, store_id, channel_id, date
            ),
            fulfillment AS (
                SELECT
                    sku_id,
                    demand_location_id AS store_id,
                    channel_id,
                    sale_date AS date,
                    sum(units)::HUGEINT AS units
                FROM canonical_data.sales_fulfillments
                GROUP BY
                    sku_id, demand_location_id, channel_id, sale_date
            )
            SELECT count(*)
            FROM sales
            FULL OUTER JOIN fulfillment
              USING (sku_id, store_id, channel_id, date)
            WHERE coalesce(sales.units, 0) <> coalesce(fulfillment.units, 0)
            """,
        )
        if fulfillment_mismatches:
            money_errors.append(
                f"sales_fulfillments: {fulfillment_mismatches} aggregate mismatches"
            )
        overfulfilled_lines = _scalar(
            connection,
            """
            WITH fulfilled AS (
                SELECT
                    source_instance,
                    source_sale_id,
                    source_line_id,
                    sum(units)::BIGINT AS units
                FROM stage.stage_data.fulfillment
                GROUP BY source_instance, source_sale_id, source_line_id
            )
            SELECT count(*)
            FROM fulfilled
            JOIN stage.stage_data.merchandise AS merchandise
              USING (source_instance, source_sale_id, source_line_id)
            WHERE fulfilled.units > merchandise.units
            """,
        )
        if overfulfilled_lines:
            money_errors.append(
                f"fulfillment: {overfulfilled_lines} lines exceed ordered units"
            )
        rules.append(
            _critical("B16", "exact source/canonical money reconciliation failed", money_errors)
            if money_errors
            else _pass(
                "B16",
                "fulfilled units and integer-minor money reconcile exactly",
                currencies=currencies,
                fulfillmentAggregateMismatches=fulfillment_mismatches,
                overfulfilledLines=overfulfilled_lines,
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
            )
               OR (
                    event_type = 'physical_return'
                    AND (
                        units IS NULL OR units < 1
                        OR amount IS NOT NULL
                        OR currency_code IS NOT NULL
                    )
               )
               OR (
                    event_type = 'financial_refund'
                    AND (
                        units IS NOT NULL
                        OR amount IS NULL OR amount < 1
                        OR currency_code IS NULL
                    )
               )
               OR (
                    event_type = 'post_fulfilment_cancellation'
                    AND units IS NULL
               )
            """,
        )
        adjustment_reconciliation = connection.execute(
            """
            SELECT
                event_type,
                count(*)::BIGINT,
                coalesce(sum(units), 0)::HUGEINT,
                coalesce(sum(amount), 0)::HUGEINT
            FROM canonical_data.sales_adjustments
            GROUP BY event_type
            ORDER BY event_type
            """
        ).fetchall()
        rules.append(
            _critical(
                "B17",
                "sales adjustment validation failed",
                [f"{adjustment_errors} invalid adjustment rows"],
            )
            if adjustment_errors
            else _pass(
                "B17",
                "physical returns and financial refunds are distinct and valid",
                controls=[
                    {
                        "eventType": row[0],
                        "rows": int(row[1]),
                        "units": int(row[2]),
                        "amountMinor": int(row[3]),
                    }
                    for row in adjustment_reconciliation
                ],
            )
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
                "sales",
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

        capability_mask: dict[str, Any] = {
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
            **_replenishment_capabilities(
                connection,
                present,
                pit_backfill=pit_backfill,
                incoming_split_mismatch=incoming_split_mismatch,
            ),
            "competitor_intelligence": {
                "available": "competitor_prices" in present
                and "competitor_matches" in present
            },
        }
        capability_mask = _apply_upstream_capability_downgrades(
            capability_mask,
            upstream_gate_a,
            source_snapshot_id=manifest["sourceSnapshotId"],
        )
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
