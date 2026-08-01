"""External/companion source adapter."""

from __future__ import annotations

from retail_ingestion.readers.catalog import sql_identifier, sql_string

from .base import AdapterContext, SourceAdapter, snake_case
from .registry import register_adapter


@register_adapter
class CompanionAdapter(SourceAdapter):
    source_system = "companion"
    adapter_version = "companion-adapter/1.2.0"
    raw_schema = "raw_companion"

    _natural_key_fields = {
        "allocationDemandRequests": ("requestKey",),
        "allocationSupplyPools": ("poolKey",),
        "competitorMatches": ("matchKey",),
        "competitorPrices": (
            "competitorId",
            "competitorSku",
            "targetType",
            "targetId",
            "validDate",
        ),
        "customerSegments": ("segmentId",),
        "fxRates": ("baseCurrency", "quoteCurrency", "rateDate", "rateType"),
        "holidays": ("date", "name", "targetType", "targetId"),
        "localEvents": ("eventId",),
        "macroIndex": ("indexName", "targetType", "targetId", "validDate"),
        "pandemicSignals": ("validDate", "pandemicIds", "phaseIds"),
        "pandemicTimeline": ("pandemicId", "phaseId"),
        "promotionSkus": (
            "promotionId",
            "sku",
            "departmentId",
            "categoryId",
            "effectiveFrom",
        ),
        "promotions": ("promotionId",),
        "storeAssortment": ("sku", "storeKey", "validFrom", "observedAt"),
        "weatherActuals": ("targetType", "targetId", "validDate"),
        "weatherForecasts": (
            "provider",
            "targetType",
            "targetId",
            "issuedAt",
            "validDate",
        ),
    }
    _effective_fields = {
        "allocationDemandRequests": "requestDate",
        "allocationSupplyPools": "snapshotDate",
        "competitorMatches": "effectiveFrom",
        "competitorPrices": "validDate",
        "fxRates": "rateDate",
        "holidays": "date",
        "localEvents": "startDate",
        "macroIndex": "validDate",
        "pandemicSignals": "validDate",
        "pandemicTimeline": "startDate",
        "promotionSkus": "effectiveFrom",
        "promotions": "startDate",
        "storeAssortment": "validFrom",
        "weatherActuals": "validDate",
        "weatherForecasts": "validDate",
    }

    def materialize_staging(self, context: AdapterContext) -> tuple[str, ...]:
        """Materialize source-typed companion tables with a common envelope.

        Domain interpretation remains in source-neutral transforms. This layer
        only adds source identity, market resolution, observation evidence and
        stable provenance to the source fields.
        """

        con = context.connection
        landing = context.landing
        source_schema_version = context.profile["sourceSchemaVersion"]
        profile_version = context.profile["profileVersion"]
        snapshot_id = landing["sourceSnapshotId"]
        native_snapshot_id = landing.get("nativeSnapshotId")
        con.execute("CREATE SCHEMA IF NOT EXISTS stage_data")
        created: list[str] = []
        observed_fields = {
            "competitorPrices": "observedAt",
            "macroIndex": "observedAt",
            "pandemicSignals": "observedAt",
            "storeAssortment": "observedAt",
            "weatherActuals": "observedAt",
            "weatherForecasts": "issuedAt",
            # Source contract v13. Lanes are effective-dated planning facts; their
            # observation time is when the declaration was recorded, and without
            # this entry they would fall back to landing_backfill and be
            # replay-ineligible by construction.
            "serviceLanes": "observedAt",
        }
        staged_datasets: dict[str, str] = {}
        for ref in context.catalog.for_source(self.source_system):
            if ref.artifact_format not in {"parquet", "csv"}:
                continue
            dataset = ref.dataset
            raw_name = snake_case(dataset)
            stage_name = f"companion_{raw_name}"
            observed = observed_fields.get(dataset)
            if observed is not None:
                raw_columns = {
                    str(row[0])
                    for row in con.execute(
                        f"DESCRIBE raw_companion.{sql_identifier(raw_name)}"
                    ).fetchall()
                }
                if observed not in raw_columns:
                    # Backward-compatible downgrade for older source-schema
                    # versions: the current landing time remains explicit,
                    # and Gate B keeps the non-PIT capability downgrade.
                    observed = None
            if observed:
                known_expression = f"try_cast({observed} AS TIMESTAMPTZ)"
                evidence_grade = (
                    "native_observed"
                    if observed == "observedAt"
                    else "native_extracted"
                )
            else:
                known_expression = (
                    f"try_cast('{landing['landingTime']}' AS TIMESTAMPTZ)"
                )
                evidence_grade = "landing_backfill"
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.{stage_name} AS
                SELECT
                    'companion'::VARCHAR AS source_system,
                    _source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    _market_id AS market_id,
                    {known_expression} AS known_as_of,
                    '{evidence_grade}'::VARCHAR AS evidence_grade,
                    'EXTERNAL_ACTUAL'::VARCHAR AS row_provenance,
                    _raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    * EXCLUDE (
                        _source_instance,
                        _market_id,
                        _market_currency_code,
                        _business_timezone,
                        _raw_object_hash,
                        _raw_object_path
                    ),
                    _raw_object_path AS raw_object_path
                FROM raw_companion.{raw_name}
                """
            )
            created.append(f"stage_data.{stage_name}")
            staged_datasets[dataset] = stage_name

        signal_selects: list[str] = []
        common_columns = {
            "source_system",
            "source_instance",
            "source_schema_version",
            "source_snapshot_id",
            "native_snapshot_id",
            "market_id",
            "known_as_of",
            "evidence_grade",
            "row_provenance",
            "raw_object_hash",
            "profile_version",
            "adapter_version",
            "raw_object_path",
        }
        for dataset, stage_name in sorted(staged_datasets.items()):
            columns = tuple(
                str(row[0])
                for row in con.execute(
                    f"DESCRIBE stage_data.{sql_identifier(stage_name)}"
                ).fetchall()
            )
            business_columns = tuple(
                column for column in columns if column not in common_columns
            )
            if not business_columns:
                continue
            payload_fields = ", ".join(
                f"{sql_identifier(column)} := {sql_identifier(column)}"
                for column in business_columns
            )
            payload = f"to_json(struct_pack({payload_fields}))"
            key_fields = self._natural_key_fields.get(dataset, business_columns)
            if dataset == "storeAssortment" and "observedAt" not in columns:
                key_fields = ("sku", "storeKey", "validFrom")
            missing_keys = sorted(set(key_fields) - set(columns))
            if missing_keys:
                raise RuntimeError(
                    f"dimension signal key fields are absent for {dataset}: "
                    + ", ".join(missing_keys)
                )
            natural_key = "concat_ws('|', source_instance, " + ", ".join(
                [sql_string(dataset)]
                + [
                    f"coalesce(cast({sql_identifier(field)} AS VARCHAR), '')"
                    for field in key_fields
                ]
            ) + ")"
            effective_field = self._effective_fields.get(dataset)
            effective_at = (
                f"coalesce(try_cast({sql_identifier(effective_field)} "
                "AS TIMESTAMPTZ), known_as_of)"
                if effective_field
                else "known_as_of"
            )
            geo_scope_type = (
                "cast(targetType AS VARCHAR)"
                if {"targetType", "targetId"} <= set(columns)
                else "NULL::VARCHAR"
            )
            geo_scope_id = (
                "cast(targetId AS VARCHAR)"
                if {"targetType", "targetId"} <= set(columns)
                else "NULL::VARCHAR"
            )
            if dataset == "promotionSkus":
                merch_scope_type = (
                    "CASE WHEN nullif(sku, '') IS NOT NULL THEN 'sku' "
                    "WHEN nullif(departmentId, '') IS NOT NULL THEN 'dept' "
                    "ELSE 'category' END::VARCHAR"
                )
                merch_scope_id = (
                    "coalesce(nullif(sku, ''), nullif(departmentId, ''), "
                    "categoryId)::VARCHAR"
                )
            elif "sku" in columns:
                merch_scope_type = "'sku'::VARCHAR"
                merch_scope_id = "cast(sku AS VARCHAR)"
            else:
                merch_scope_type = "NULL::VARCHAR"
                merch_scope_id = "NULL::VARCHAR"
            channel_source_key = (
                "cast(channelId AS VARCHAR)"
                if "channelId" in columns
                else "NULL::VARCHAR"
            )
            signal_selects.append(
                f"""
                SELECT
                    source_system, source_instance, source_schema_version,
                    source_snapshot_id, native_snapshot_id,
                    sha256({natural_key})::VARCHAR AS native_record_id,
                    market_id, known_as_of, evidence_grade, row_provenance,
                    raw_object_hash, profile_version, adapter_version,
                    {sql_string(dataset)}::VARCHAR AS entity_kind,
                    {natural_key}::VARCHAR AS natural_key,
                    {effective_at} AS effective_at,
                    {payload}::JSON AS payload,
                    {geo_scope_type} AS geo_scope_type,
                    {geo_scope_id} AS geo_scope_id,
                    {merch_scope_type} AS merch_scope_type,
                    {merch_scope_id} AS merch_scope_id,
                    {channel_source_key} AS channel_source_key,
                    raw_object_path
                FROM stage_data.{sql_identifier(stage_name)}
                """
            )
        if signal_selects:
            con.execute(
                "CREATE OR REPLACE TABLE stage_data.companion_dimension_signal AS "
                + " UNION ALL ".join(signal_selects)
            )
            created.append("stage_data.companion_dimension_signal")
        return tuple(created)


__all__ = ["CompanionAdapter"]
