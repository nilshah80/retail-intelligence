"""Harden Forecast Scenario request and assumption authority boundaries.

Tier-band continuity cannot be expressed by a row-local CHECK constraint. This
migration makes the bundle's existing seal transition validate every
market/department partition inside PostgreSQL, so a bypass of the Python
publisher cannot seal or approve ambiguous coefficient bands.

Revision ID: 0027_scenario_hardening
Revises: 0026_scenario_context
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_scenario_hardening"
down_revision: str | Sequence[str] | None = "0026_scenario_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.seal_scenario_assumption_set()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            tier_count BIGINT;
        BEGIN
            IF TG_OP = 'UPDATE'
               AND NOT OLD.children_sealed
               AND NEW.children_sealed
               AND (to_jsonb(NEW) - 'children_sealed')
                   = (to_jsonb(OLD) - 'children_sealed') THEN
                SELECT COUNT(*) INTO tier_count
                  FROM {SCHEMA}.forecast_scenario_tier_coefficients
                 WHERE assumption_semantic_fingerprint = NEW.semantic_fingerprint;
                IF tier_count = 0 THEN
                    RAISE EXCEPTION 'assumption bundle % has no tier coefficients',
                        NEW.semantic_fingerprint;
                END IF;

                IF EXISTS (
                    WITH ordered AS (
                        SELECT
                            tiers.market_id,
                            tiers.dept_id,
                            tiers.lower_price_minor,
                            tiers.upper_price_minor,
                            rules.minimum_price_minor,
                            ROW_NUMBER() OVER partition_window AS ordinal,
                            COUNT(*) OVER partition_window AS band_count,
                            LAG(tiers.upper_price_minor) OVER partition_window
                                AS previous_upper
                        FROM {SCHEMA}.forecast_scenario_tier_coefficients AS tiers
                        LEFT JOIN {SCHEMA}.forecast_scenario_market_rules AS rules
                          ON rules.assumption_semantic_fingerprint =
                             tiers.assumption_semantic_fingerprint
                         AND rules.market_id = tiers.market_id
                        WHERE tiers.assumption_semantic_fingerprint =
                              NEW.semantic_fingerprint
                        WINDOW partition_window AS (
                            PARTITION BY tiers.market_id, tiers.dept_id
                            ORDER BY tiers.lower_price_minor
                            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                        )
                    )
                    SELECT 1
                    FROM ordered
                    WHERE minimum_price_minor IS NULL
                       OR (ordinal = 1
                           AND lower_price_minor <> minimum_price_minor)
                       OR (ordinal > 1
                           AND (previous_upper IS NULL
                                OR lower_price_minor <> previous_upper))
                       OR (ordinal < band_count AND upper_price_minor IS NULL)
                       OR (ordinal = band_count AND upper_price_minor IS NOT NULL)
                ) THEN
                    RAISE EXCEPTION
                        'assumption bundle % has incomplete or ambiguous tier coverage',
                        NEW.semantic_fingerprint;
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '% is append-only after its one seal transition',
                TG_TABLE_NAME;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.seal_scenario_assumption_set()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND NOT OLD.children_sealed
               AND NEW.children_sealed
               AND (to_jsonb(NEW) - 'children_sealed')
                   = (to_jsonb(OLD) - 'children_sealed') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '% is append-only after its one seal transition',
                TG_TABLE_NAME;
        END;
        $$
        """
    )
