"""External/companion source adapter."""

from __future__ import annotations

from .base import AdapterContext, SourceAdapter, snake_case
from .registry import register_adapter


@register_adapter
class CompanionAdapter(SourceAdapter):
    source_system = "companion"
    adapter_version = "companion-adapter/1.0.0"
    raw_schema = "raw_companion"

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
            "weatherActuals": "observedAt",
            "weatherForecasts": "issuedAt",
        }
        for ref in context.catalog.for_source(self.source_system):
            if ref.artifact_format not in {"parquet", "csv"}:
                continue
            dataset = ref.dataset
            raw_name = snake_case(dataset)
            stage_name = f"companion_{raw_name}"
            observed = observed_fields.get(dataset)
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
        return tuple(created)


__all__ = ["CompanionAdapter"]
