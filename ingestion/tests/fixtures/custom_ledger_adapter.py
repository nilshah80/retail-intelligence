"""A deliberately different bounded custom adapter, used only as a fixture.

Its source publishes an append-only ledger of header/line/version events plus a
status machine. Producing one merchandise row per sale line needs a
version-resolving join and status interpretation, which the mapped-files
allowlist cannot express: there is no join, no window function and no ordering
operation in it, by design.

The adapter therefore exists to prove the extension path works — not to widen
the declarative language. It reuses shared helpers, emits standardized roles
only, and cannot bypass shared role validation.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from retail_contracts.money_sql import exact_minor_sql
from retail_ingestion.adapters.base import AdapterContext, SourceAdapter
from retail_ingestion.readers.catalog import sql_string

MANIFEST: Final[dict[str, Any]] = {
    "schemaVersion": "retail-adapter-manifest/v1",
    "sourceSystem": "ledgerErp",
    "adapterVersion": "ledger-erp-adapter/1.0.0",
    "adapterKind": "bounded_custom",
    "primaryIdentity": "source_dialect",
    "supportedSourceSchemaVersions": ["ledger-erp/2"],
    "supportedProfileVersions": ["ledger-erp-profile/1"],
    "suppliedRoles": [
        {
            "role": "merchandise",
            "providerId": "ledger_sale_events",
            "providerResolution": "exclusive",
        }
    ],
    "requiredSourceCapabilities": ["append_only_ledger", "version_sequence"],
    "providerResolutionCompatibility": ["exclusive"],
    "loading": "static_in_repository_registry",
    "justification": (
        "The source emits header, line and revision events in one append-only "
        "ledger; a sale line's final state is the highest revision whose status "
        "machine reached a posted terminal state."
    ),
    "customSemantics": {
        "reason": "header_line_version_join",
        "mappedFilesGap": (
            "Resolving the latest revision per line requires ordering and a "
            "join across event kinds. The decision-#68 allowlist has neither, "
            "and widening it would make mappings Turing-complete."
        ),
        "sharedHelpersUsed": [
            "retail_contracts.money_sql.exact_minor_sql",
            "retail_ingestion.adapters.base.SourceAdapter.register_raw_views",
        ],
    },
}

#: Only these source statuses represent posted, realized demand.
POSTED_STATUSES: Final[tuple[str, ...]] = ("POSTED", "SETTLED")


class LedgerErpAdapter(SourceAdapter):
    """Resolve a versioned event ledger into the `merchandise` role."""

    source_system = MANIFEST["sourceSystem"]
    adapter_version = MANIFEST["adapterVersion"]
    raw_schema = "raw_ledger_erp"

    def materialize_staging(self, context: AdapterContext) -> tuple[str, ...]:
        con = context.connection
        profile: Mapping[str, Any] = context.profile
        landing = context.landing
        con.execute("CREATE SCHEMA IF NOT EXISTS stage_data")
        statuses = ", ".join(sql_string(value) for value in POSTED_STATUSES)
        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.merchandise AS
            WITH resolved AS (
                -- The semantics mapped files cannot express: pick the highest
                -- revision per line, then interpret the status machine.
                SELECT
                    line.*,
                    header.posted_at,
                    header.currency_code AS header_currency,
                    row_number() OVER (
                        PARTITION BY line.sale_id, line.line_id
                        ORDER BY line.revision DESC
                    ) AS revision_rank
                FROM {self.raw_schema}.ledger_lines AS line
                JOIN {self.raw_schema}.ledger_headers AS header
                  ON header.sale_id = line.sale_id
                 AND header._source_instance = line._source_instance
            )
            SELECT
                {sql_string(self.source_system)}::VARCHAR AS source_system,
                _source_instance AS source_instance,
                {sql_string(str(profile['sourceSchemaVersion']))}::VARCHAR
                    AS source_schema_version,
                {sql_string(str(landing['sourceSnapshotId']))}::VARCHAR
                    AS source_snapshot_id,
                NULL::VARCHAR AS native_snapshot_id,
                concat_ws('|', sale_id, line_id, revision)::VARCHAR
                    AS native_record_id,
                _market_id AS market_id,
                try_cast(posted_at AS TIMESTAMPTZ) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade,
                'client'::VARCHAR AS evidence_class,
                'derived'::VARCHAR AS derivation_class,
                _raw_object_hash AS raw_object_hash,
                {sql_string(str(profile['profileVersion']))}::VARCHAR
                    AS profile_version,
                {sql_string(self.adapter_version)}::VARCHAR AS adapter_version,
                'merchandise'::VARCHAR AS role_id,
                'ledger_sale_events'::VARCHAR AS provider_id,
                'sale'::VARCHAR AS event_kind,
                sale_id::VARCHAR AS source_sale_id,
                line_id::VARCHAR AS source_line_id,
                sku::VARCHAR AS sku_source_key,
                shop::VARCHAR AS demand_location_source_key,
                'store'::VARCHAR AS channel_source_key,
                try_cast(business_day AS DATE) AS business_date,
                try_cast(qty AS BIGINT) AS units,
                -- staging-v2 declares this field in MAJOR units and the canonical
                -- transform applies exact_minor_sql to it, so converting here too made
                -- EUR 24.00 arrive as 240000 minor units instead of 2400. Same 100x
                -- defect that was fixed in the mapped_files adapter; this fixture still
                -- encoded it, which invalidated the custom-adapter round-trip evidence.
                -- Normalise the type and leave the scale alone.
                try_cast(net_major AS DECIMAL(38, 12)) AS net_amount_major,
                header_currency::VARCHAR AS currency_code
            FROM resolved
            WHERE revision_rank = 1
              AND upper(status) IN ({statuses})
            """
        )
        return ("stage_data.merchandise",)


__all__ = ["MANIFEST", "POSTED_STATUSES", "LedgerErpAdapter"]
