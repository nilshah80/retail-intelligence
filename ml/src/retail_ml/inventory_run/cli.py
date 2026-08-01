"""Inventory-run subcommands: build, verify, materialize, activate.

Kept in this package rather than in `retail_ml.cli` because the four steps only
make sense together and they all import the same three modules. `retail_ml.cli`
registers them, so the entry point is unchanged.

The steps stay separate commands on purpose. A single `do-everything` would mean
an operator could not stop between "the evidence exists" and "the evidence is
what we serve", and that gap is the whole point of the accepted-but-inactive
state the API answers with a governed 503.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint
from retail_contracts.guardrails import resolve_guardrails

from retail_ml.inventory_publish.postgres import (
    activate_inventory_version,
    materialize_inventory_run,
)
from retail_ml.inventory_publish.run_artifacts import publish_inventory_run
from retail_ml.inventory_publish.verify import verify_inventory_run
from retail_ml.inventory_run.build import build_artifacts, coverage_summary
from retail_ml.inventory_run.load import (
    connect,
    lane_coverage_pct,
    load_inventory_inputs,
)
from retail_ml.inventory_run.replay_driver import load_market_history, run_replay

#: Weeks of history the replay covers. Fifty-two so every market sees a full
#: annual cycle: a shorter window scores a policy on one season.
REPLAY_WEEKS = 52


def _selection_ids(repository_root: Path) -> dict[str, str]:
    """The ACTIVE decision-#73 selection per capability, by derived currency."""

    directory = (
        repository_root / "contracts" / "evidence" / "publication-selections"
    )
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    selections = [
        record
        for record in records
        if record.get("schemaVersion") == "retail-publication-selection/v1"
    ]
    superseded = {
        record["lifecycle"]["supersedes"]
        for record in selections
        if record["lifecycle"].get("supersedes")
    }
    return {
        record["scope"]["capability"]: record["selectionId"]
        for record in selections
        if record["lifecycle"]["recordId"] not in superseded
        and record["lifecycle"]["state"] == "active"
    }


def _active_forecast(dsn: str) -> dict[str, str]:
    """The live decision-#90 forecast authority, or refuse.

    Read from PostgreSQL rather than from a bundle on disk: the question is which
    forecast is CURRENTLY authoritative, and only the database knows that.
    """

    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT forecast_run_id, version_id
                FROM retail_serving.active_forecast_versions
                """
            )
            rows = cursor.fetchall()
    if len(rows) != 1:
        raise SystemExit(
            f"decision #90 requires exactly one active forecast; found {len(rows)}"
        )
    return {
        "forecastRunId": str(rows[0][0]),
        "forecastVersionId": str(rows[0][1]),
        "coverageGateMode": "hard",
    }


def _forecast_series(dsn: str) -> pd.DataFrame:
    """The served forecast series, read from the projection the API serves.

    Not from the Parquet bundle: the bundle is the immutable authority for what
    was published, but the inventory run must consume what is actually being
    SERVED, and those differ the moment a newer bundle is materialized but not
    activated.
    """

    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT series.market_id, series.store_id, series.sku_id,
                       series.horizon_week, series.yhat_p50, series.yhat_p90
                FROM retail_serving.forecast_series AS series
                JOIN retail_serving.active_forecast_versions AS active
                  ON active.forecast_run_id = series.forecast_run_id
                 AND active.version_id = series.version_id
                """
            )
            rows = cursor.fetchall()
    frame = pd.DataFrame(
        rows,
        columns=[
            "market_id",
            "store_id",
            "sku_id",
            "horizon_week",
            "yhat_p50",
            "yhat_p90",
        ],
    )
    if frame.empty:
        raise SystemExit(
            "the active forecast projection is empty; materialize and activate a "
            "forecast before running inventory against it"
        )
    for column in ("yhat_p50", "yhat_p90"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["horizon_week"] = frame["horizon_week"].astype(int)
    return frame


def _policy_by_market(
    currency_by_market: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve inventory policy v2 per market, with its own fingerprint.

    The fingerprint covers the resolved INVENTORY policy alone, not the whole
    guardrail bundle. The manifest field is "the resolved policy fingerprint for
    this market" and the bundle declares `policyVersion: inventory-policy/2.0.0`,
    so binding pricing and price-response into it would make the recorded
    fingerprint change when a price rule moves and nothing about inventory did.
    """

    resolved: dict[str, Any] = {}
    fingerprints: dict[str, str] = {}
    for market, currency in sorted(currency_by_market.items()):
        policy = resolve_guardrails(
            market, currency, inventory_policy_generation="v2"
        )["inventoryPolicy"]
        resolved[market] = policy
        fingerprints[market] = semantic_fingerprint(policy, volatile_pointers=())
    return resolved, fingerprints


def _levels(
    recommendations: pd.DataFrame,
) -> tuple[dict[str, dict[tuple[str, str], Decimal]], dict[str, dict[tuple[str, str], Decimal]]]:
    """Published reorder points and order-up-to levels, keyed for the replay."""

    points: dict[str, dict[tuple[str, str], Decimal]] = {}
    levels: dict[str, dict[tuple[str, str], Decimal]] = {}
    for row in recommendations.itertuples(index=False):
        if pd.isna(row.reorder_point_units) or pd.isna(row.order_up_to_units):
            continue
        market = str(row.market_id)
        key = (str(row.sku_id), str(row.destination_location_id))
        points.setdefault(market, {})[key] = Decimal(str(row.reorder_point_units))
        levels.setdefault(market, {})[key] = Decimal(str(row.order_up_to_units))
    return points, levels


def command_build(args: argparse.Namespace) -> int:
    """Load, build, replay, then publish -- in that order and no other.

    The replay runs AFTER the artifacts exist because it scores the levels the
    bundle publishes. Scoring levels computed separately for the replay would
    accept a policy nobody is serving.
    """

    as_of = date.fromisoformat(args.as_of)
    curated = Path(args.curated_root)
    dsn = args.postgres_dsn
    forecast = _active_forecast(dsn)
    series = _forecast_series(dsn)
    attributes = _market_attributes(curated)
    # The markets the bundle covers are those the SERVED forecast covers. A market
    # with locations but no active forecast has no interval to consume, so
    # including it would publish thirteen artifacts of withheld rows.
    markets = sorted(set(series["market_id"].astype(str)) & set(attributes))
    if not markets:
        raise SystemExit(
            "no market appears in both the active forecast and the curated "
            f"locations; forecast has {sorted(set(series['market_id']))}, "
            f"publication has {sorted(attributes)}"
        )
    policy, fingerprints = _policy_by_market(
        {market: attributes[market][1] for market in markets}
    )

    inputs = load_inventory_inputs(
        curated, as_of=as_of, forecast_series=series, policy=policy
    )
    # A first pass produces the levels; the replay scores them; the metrics then
    # go into the same bundle. The artifacts themselves do not change between the
    # two calls -- only `inventory_replay_metrics` is filled in.
    provisional = build_artifacts(
        inputs, replay_metrics=_empty_metrics()
    )
    points, levels = _levels(provisional["replenishment_recommendations"])

    histories = [
        load_market_history(
            curated,
            market_id=market,
            timezone=attributes[market][0],
            as_of=as_of,
            weeks=REPLAY_WEEKS,
        )
        for market in markets
    ]
    trailing_by_market = {
        market: {
            (str(row.sku_id), str(row.location_id)): Decimal(
                str(row.trailing_avg_daily_units)
            )
            for row in inputs.trailing_demand.itertuples(index=False)
            if str(row.market_id) == market
        }
        for market in markets
    }
    scored = run_replay(
        histories,
        trailing_by_market=trailing_by_market,
        reorder_points=points,
        order_up_to=levels,
    )
    artifacts = build_artifacts(inputs, replay_metrics=scored["metrics"])

    coverage, covered, total = lane_coverage_pct(curated, as_of=as_of)
    summary = coverage_summary(artifacts)
    print(
        json.dumps(
            {
                "markets": markets,
                "laneCoverage": {
                    "pct": str(coverage),
                    "covered": covered,
                    "total": total,
                },
                "replayPassed": scored["passed"],
                "coverage": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )

    published = publish_inventory_run(
        args.bundle,
        frames=artifacts,
        markets=markets,
        decision_as_of=datetime.combine(
            as_of, datetime.min.time(), tzinfo=timezone.utc
        ),
        input_bundle=_input_bundle(Path(args.repository_root)),
        source_selection_id=_selection_ids(Path(args.repository_root))[
            "inventory_replenishment_replay"
        ],
        forecast_authority=forecast,
        policy_fingerprints=fingerprints,
        replay=scored["replay"],
        lane_coverage_pct=float(coverage),
        acceptance_passed=bool(scored["passed"]),
        execution_profile=args.execution_profile,
        created_at=datetime.now(tz=timezone.utc),
    )
    print(json.dumps(asdict(published) | {"root": str(published.root)}, indent=2,
                     sort_keys=True, default=str))
    return 0


def _empty_metrics() -> pd.DataFrame:
    from retail_ml.inventory_publish.run_artifacts import ARTIFACT_COLUMNS

    return pd.DataFrame(columns=list(ARTIFACT_COLUMNS["inventory_replay_metrics"]))


def _market_attributes(curated_root: Path) -> dict[str, tuple[str, str]]:
    """market_id -> (timezone, currency_code), or refuse if either is ambiguous.

    Both must be single-valued per market for a different reason, and both refuse
    rather than pick. Two timezones means the replay clock buckets one market's
    week two ways; two currencies means one money column holds two units.
    """

    connection = connect(curated_root)
    try:
        rows = connection.execute(
            """
            SELECT market_id,
                   min(timezone) AS timezone,
                   count(DISTINCT timezone) AS zones,
                   min(currency_code) AS currency_code,
                   count(DISTINCT currency_code) AS currencies
            FROM locations
            WHERE active
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        if int(row[2]) > 1:
            raise SystemExit(
                f"market {row[0]} spans {row[2]} timezones; the replay clock "
                "would bucket its week two ways"
            )
        if int(row[4]) > 1:
            raise SystemExit(
                f"market {row[0]} spans {row[4]} currencies; a money column "
                "would then mean different things in the same column"
            )
    return {str(row[0]): (str(row[1]), str(row[3])) for row in rows}


def _input_bundle(repository_root: Path) -> dict[str, str]:
    pin = json.loads(
        (repository_root / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "sourceSnapshotId": pin["sourceSnapshotId"],
        "gateASemanticFingerprint": pin["gateA"]["semanticFingerprint"],
        "gateBSemanticFingerprint": pin["gateB"]["semanticFingerprint"],
        "publicationSemanticFingerprint": pin["publication"]["semanticFingerprint"],
    }


def command_verify(args: argparse.Namespace) -> int:
    repository_root = Path(args.repository_root)
    pin = json.loads(
        (repository_root / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    verified = verify_inventory_run(
        args.bundle,
        expected_pin=pin,
        active_selection_id=_selection_ids(repository_root)[
            "inventory_replenishment_replay"
        ],
        active_forecast=_active_forecast(args.postgres_dsn),
    )
    print(
        json.dumps(
            {
                "verdict": "verified",
                "inventoryRunId": verified.inventory_run_id,
                "semanticFingerprint": verified.semantic_fingerprint,
                "markets": verified.markets,
                "artifacts": sorted(verified.artifact_paths),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_materialize(args: argparse.Namespace) -> int:
    repository_root = Path(args.repository_root)
    pin = json.loads(
        (repository_root / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    verified = verify_inventory_run(
        args.bundle,
        expected_pin=pin,
        active_selection_id=_selection_ids(repository_root)[
            "inventory_replenishment_replay"
        ],
        active_forecast=_active_forecast(args.postgres_dsn),
    )
    result = materialize_inventory_run(verified, postgres_dsn=args.postgres_dsn)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def command_activate(args: argparse.Namespace) -> int:
    result = activate_inventory_version(
        postgres_dsn=args.postgres_dsn,
        inventory_run_id=args.inventory_run_id,
        expected_run_semantic_fingerprint=args.run_semantic_fingerprint,
        actor=args.actor,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def register(subparsers: Any) -> None:
    """Attach the four subcommands to `retail_ml.cli`'s parser."""

    build = subparsers.add_parser("inventory-build")
    build.add_argument("--repository-root", type=Path, default=Path.cwd())
    build.add_argument("--curated-root", type=Path, required=True)
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--as-of", required=True)
    build.add_argument("--postgres-dsn", required=True)
    build.add_argument("--execution-profile", default="performance")
    build.set_defaults(handler=command_build)

    verify = subparsers.add_parser("inventory-verify")
    verify.add_argument("--repository-root", type=Path, default=Path.cwd())
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--postgres-dsn", required=True)
    verify.set_defaults(handler=command_verify)

    materialize = subparsers.add_parser("inventory-materialize")
    materialize.add_argument("--repository-root", type=Path, default=Path.cwd())
    materialize.add_argument("--bundle", type=Path, required=True)
    materialize.add_argument("--postgres-dsn", required=True)
    materialize.set_defaults(handler=command_materialize)

    activate = subparsers.add_parser("inventory-activate")
    activate.add_argument("--inventory-run-id", required=True)
    activate.add_argument("--run-semantic-fingerprint", required=True)
    activate.add_argument("--actor", required=True)
    activate.add_argument("--postgres-dsn", required=True)
    activate.set_defaults(handler=command_activate)


__all__ = [
    "REPLAY_WEEKS",
    "command_activate",
    "command_build",
    "command_materialize",
    "command_verify",
    "register",
]
