"""The immutable inventory/replenishment run bundle (P4-8 tasks 1 and 3).

Thirteen Parquet artifacts plus one manifest. The manifest carries lineage, the
frozen policy identity, the replay verdict and a semantic fingerprint per
artifact; the run id is DERIVED from those, so two bundles with the same inputs,
policy and outputs are the same run and a bundle whose lineage differs cannot
borrow another run's identity.

Artifact names are the projection table names from migration 0010, and
`ARTIFACT_COLUMNS` is the only place the column contract is written down. The
materializer imports it rather than restating it: two copies of "the projection
contract" is how a bundle and a schema drift apart while both look correct.

Validation here mirrors every CHECK constraint 0010 declares. A violation should
surface as a readable Python error at publish time naming the artifact and the
rule, not as a constraint name from a COPY four steps later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Final, NamedTuple

import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ml.publish.run_artifacts import (
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
)

RUN_SCHEMA_VERSION: Final[str] = "retail-inventory-replenishment-run/v1"

#: The frozen policy this publisher implements. A bundle published against a
#: different policy version is a different contract, not a newer run.
POLICY_VERSION: Final[str] = "inventory-policy/2.0.0"

#: Decision #92's calibrated boundary. Named here because the publisher refuses a
#: manifest that claims a different one: moving the boundary is a preregistered
#: mechanism change, never a field a run gets to set.
CALIBRATED_MAX_HORIZON: Final[int] = 4

#: Every reason a Phase 4 artifact may cite for withholding an interval-derived
#: value. Extending this set means a new governed reason exists, which is a
#: contract change and not a convenience.
#:
#: The second reason is not about the interval itself. Policy v2 makes lane and
#: supply-term resolution fail closed, so a cell whose route nobody declared has
#: no lead time, hence no protection period, hence no horizon -- the interval
#: question cannot even be asked. It withholds for a DIFFERENT cause than a
#: cold-start row, and collapsing the two would tell an operator to wait for
#: calibration when what is actually missing is a declared route.
#: The four causes are separated because each has a DIFFERENT remedy, and the
#: first run against real ten-year data proved why it matters: every one of 4,741
#: rows was withheld and every one was labelled cold-start, while not a single one
#: actually exceeded the calibrated horizon. DC lead times are 4-9 days and store
#: lane transit is 1-2, so every protection period lands at horizon 2-3. The real
#: causes were that `inventory_cost` carries no store rows and the forecast is
#: store-grain so no DC has one. An operator reading "cold start" on all of it
#: would have waited for calibration that was never the problem.
GOVERNED_REASONS: Final[frozenset[str]] = frozenset(
    {
        # Protection period genuinely reaches past the calibrated horizon.
        "COLD_START_INTERVAL_UNCALIBRATED",
        # No active lane or supply term resolves, so there is no lead time and
        # hence no protection period to ask the interval question about.
        "SUPPLY_ROUTE_UNRESOLVED",
        # Nothing forecast this node's demand. DC demand is derived from the
        # stores it supplies and is not itself forecast, so a DC has no interval
        # of its own -- which is a modelling boundary, not a calibration gap.
        "FORECAST_ABSENT_FOR_NODE",
        # No accepted unit cost, so cost-weighted ABC cannot rank the cell, so no
        # service level applies. P4-D6 forbids borrowing DC cost for a store, and
        # the engine's own reason code for this is ABC_UNIT_COST_UNAVAILABLE.
        "ABC_UNIT_COST_UNAVAILABLE",
        # The node's demand is an additive P50 of the stores it supplies, which
        # policy v2 permits, but `sumOfChannelP90: forbidden` -- the sum of upper
        # quantiles is not the upper quantile of the sum, since it assumes every
        # store peaks in the same week. So the node has a central scenario and no
        # interval, and `nodeSafetyStockBasis:
        # accepted_aggregate_residual_variability` is not in the forecast artifact.
        "NODE_INTERVAL_BASIS_UNAVAILABLE",
    }
)

#: Reasons a constrained solve refused on its own terms, with the interval intact.
#: Kept apart from GOVERNED_REASONS because these do not answer "why is there no
#: interval" -- they answer "why, given one, is there no order". A screen prints
#: either, so both must be named somewhere rather than arriving as free text.
SOLVER_REASONS: Final[frozenset[str]] = frozenset(
    {
        # The supplier's minimum order is larger than the max-cover headroom, so
        # ordering at all would breach the cover cap. The engine refuses rather
        # than silently violating one of the two constraints.
        "MOQ_EXCEEDS_MAX_COVER",
    }
)

#: Decision P4-D11: recommendations are shadow-only. The column exists so the
#: absence of ERP submission is a published fact rather than an omission.
ERP_STATUS: Final[str] = "shadow_not_sent"

ARTIFACT_SCHEMAS: Final[dict[str, str]] = {
    "inventory_positions": "retail-inventory-positions/v1",
    "inventory_stock_health": "retail-inventory-stock-health/v1",
    "inventory_demand_at_risk": "retail-inventory-demand-at-risk/v1",
    "inventory_ageing": "retail-inventory-ageing/v1",
    "inventory_expiry_waste": "retail-inventory-expiry-waste/v1",
    "inventory_sku_dimension": "retail-inventory-sku-dimension/v1",
    "inventory_warehouse_capacity": "retail-inventory-warehouse-capacity/v1",
    "inventory_inbound_summary": "retail-inventory-inbound-summary/v1",
    "inventory_market_policy": "retail-inventory-market-policy/v1",
    "inventory_valuation": "retail-inventory-valuation/v1",
    "replenishment_recommendations": "retail-replenishment-recommendations/v1",
    "replenishment_safety_stock": "retail-replenishment-safety-stock/v1",
    "replenishment_transfers": "retail-replenishment-transfers/v1",
    "replenishment_allocations": "retail-replenishment-allocations/v1",
    "replenishment_suppliers": "retail-replenishment-suppliers/v1",
    "replenishment_exceptions": "retail-replenishment-exceptions/v1",
    "inventory_replay_metrics": "retail-inventory-replay-metrics/v1",
}

#: Column order per artifact, identical to migration 0010's projection tables.
ARTIFACT_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "inventory_positions": (
        "market_id",
        "location_id",
        "location_kind",
        "sku_id",
        "on_hand_units",
        "committed_units",
        "reserved_units",
        "damaged_units",
        "on_order_units",
        "in_transit_units",
        "atp_units",
        "assortment_active",
        "residual_only",
    ),
    "inventory_stock_health": (
        "market_id",
        "location_id",
        "sku_id",
        "health_class",
        "cover_days",
        "reason_code",
    ),
    "inventory_demand_at_risk": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
        "risk_units",
        "risk_value_minor",
        "currency_code",
        "interval_available",
        "reason_code",
    ),
    "inventory_ageing": (
        "market_id",
        "location_id",
        "sku_id",
        "age_bucket",
        "on_hand_units",
        "action",
        "markdown_pct",
        "residual_only",
    ),
    "inventory_expiry_waste": (
        "market_id",
        "location_id",
        "sku_id",
        "expiring_units",
        "expired_units",
        "waste_units",
        "exposure_minor",
        "currency_code",
    ),
    # The dimension the fourteen screens read category and money through. Not a
    # fact table: one row per market x location x SKU, joined by the read model
    # wherever a card groups by category or denominates a column in currency.
    "inventory_sku_dimension": (
        "market_id",
        "location_id",
        "sku_id",
        "category",
        "category_label",
        "product_name",
        "location_name",
        "location_kind",
        "unit_cost_minor",
        "cost_method",
        "currency_code",
        "trailing_daily_units",
    ),
    "inventory_valuation": (
        "market_id",
        "location_id",
        "category",
        "gross_value_minor",
        "currency_code",
        "cost_method",
        "cost_reason_code",
        "wms_variance_units",
    ),
    "replenishment_recommendations": (
        "market_id",
        "destination_location_id",
        "supply_location_id",
        "sku_id",
        "recommended_units",
        "reorder_point_units",
        "order_up_to_units",
        # The lead time the supply term resolved to. The engine computed it to
        # size the protection period and published nothing, so the reference's
        # Lead Time and Expected Receipt columns had no fact behind them.
        "lead_time_days",
        "interval_available",
        "reason_code",
        "erp_status",
    ),
    "replenishment_safety_stock": (
        "market_id",
        "location_id",
        "sku_id",
        "abc_class",
        "service_level",
        "safety_stock_units",
        "interval_available",
        "reason_code",
    ),
    "replenishment_transfers": (
        "market_id",
        "lane_id",
        "from_location_id",
        "to_location_id",
        "sku_id",
        "units",
        "expected_benefit_minor",
        "currency_code",
        "transit_days",
    ),
    "replenishment_allocations": (
        "market_id",
        "location_id",
        "channel_id",
        "sku_id",
        "requested_units",
        "allocated_units",
        "shortfall_units",
    ),
    "replenishment_suppliers": (
        "market_id",
        "supplier_id",
        # The merchandise scope this supplier serves, and how many scopes it
        # serves in total. A supplier is not single-category -- 239 of the 280 in
        # the source carry more than one term -- so the count travels with the
        # label and the screen can say "+2" rather than implying exclusivity.
        "category",
        "category_label",
        "scope_count",
        # The vendor master's own name, and what this supplier still owes the
        # network. Both screens showed a UUID and a blank because the dimension
        # landed and was never staged, and no inbound row named its vendor.
        "supplier_name",
        "open_po_units",
        "open_po_value_minor",
        "currency_code",
        "otd_rate",
        "lead_time_mean_days",
        "lead_time_std_days",
        "capacity_confirmed_pct",
        "risk_class",
        "reason_codes",
    ),
    "replenishment_exceptions": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
        "exception_class",
        "severity",
        "reason_code",
        "evidence",
    ),
    "inventory_replay_metrics": (
        "market_id",
        "metric",
        "cohort",
        "candidate_value",
        "incumbent_value",
        "passed",
    ),
    # The storage ceiling per warehouse, which utilisation has no denominator
    # without. `used_units` is deliberately not carried: the source's used figure
    # IS the on-hand the position artifact already publishes -- identical to the
    # unit at both India DCs -- and a second copy of it could disagree with the
    # holding the same screen values beside it.
    "inventory_warehouse_capacity": (
        "market_id",
        "location_id",
        "capacity_units",
        "snapshot_date",
    ),
    # Inbound reliability per node. The position projection carries an on-order
    # and an in-transit bucket and no dates, so nothing downstream could tell a
    # late receipt from a merely open one.
    "inventory_inbound_summary": (
        "market_id",
        "location_id",
        "open_shipments",
        "open_units",
        "received_shipments",
        "late_shipments",
    ),
    # The market-scoped ceilings the screens measure a plan against. The policy
    # declares them and the read model cannot read a policy document, so a
    # governance figure had no denominator.
    "inventory_market_policy": (
        "market_id",
        "weekly_replenishment_budget_minor",
        "currency_code",
    ),
}

#: The grain of each artifact. Duplicates on these columns mean two rows claim the
#: same cell, and a screen summing them double-counts.
ARTIFACT_GRAIN: Final[dict[str, tuple[str, ...]]] = {
    "inventory_sku_dimension": ("market_id", "location_id", "sku_id"),
    "inventory_positions": ("market_id", "location_id", "sku_id"),
    "inventory_stock_health": ("market_id", "location_id", "sku_id"),
    "inventory_demand_at_risk": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
    ),
    "inventory_ageing": ("market_id", "location_id", "sku_id", "age_bucket"),
    "inventory_expiry_waste": ("market_id", "location_id", "sku_id"),
    "inventory_valuation": ("market_id", "location_id", "category"),
    "replenishment_recommendations": (
        "market_id",
        "destination_location_id",
        "sku_id",
    ),
    "replenishment_safety_stock": ("market_id", "location_id", "sku_id"),
    "replenishment_transfers": ("market_id", "lane_id", "sku_id"),
    "replenishment_allocations": (
        "market_id",
        "location_id",
        "channel_id",
        "sku_id",
    ),
    "replenishment_suppliers": ("market_id", "supplier_id"),
    "replenishment_exceptions": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
        "exception_class",
    ),
    "inventory_replay_metrics": ("market_id", "metric", "cohort"),
    "inventory_warehouse_capacity": ("market_id", "location_id"),
    "inventory_inbound_summary": ("market_id", "location_id"),
    "inventory_market_policy": ("market_id",),
}

class IntervalGate(NamedTuple):
    """One table's interval truth table, mirroring its CHECK in 0010."""

    #: The column whose presence the flag governs.
    gate: str
    #: Every further column that must be absent when the interval is.
    withheld_null: tuple[str, ...]
    #: Whether an available interval also *obliges* a value. 0010 says this
    #: differs per table, and the difference is load-bearing -- see below.
    obliges_value: bool


#: The interval truth table, mirroring 0010. The withheld direction is universal:
#: no run may publish a number derived from an interval it did not earn. The
#: available direction is not, and 0010 is deliberate about which tables oblige a
#: value:
#:
#:     inventory_demand_at_risk       = (risk_units IS NOT NULL)
#:     replenishment_safety_stock     = (safety_stock_units IS NOT NULL)
#:     replenishment_recommendations  OR recommended_units IS NULL
#:
#: (each prefixed by `interval_available` in 0010)
#:
#: At-risk units and safety stock are closed-form functions of the interval: given
#: one, the other follows, so absence can only mean the interval was withheld. A
#: recommended quantity is not -- it is the output of a constrained solve that can
#: refuse on its own terms (no supply ATP, a cap below the minimum order). That
#: refusal is a third state, and the exceptions artifact carries its reason. This
#: file previously applied the bidirectional rule to all three and so rejected the
#: very rows 0010 accepts, which is how a legitimate solver refusal on two rows
#: presented as a decision #92 violation.
INTERVAL_GATED: Final[dict[str, IntervalGate]] = {
    "inventory_demand_at_risk": IntervalGate(
        "risk_units",
        ("risk_value_minor", "currency_code"),
        obliges_value=True,
    ),
    "replenishment_safety_stock": IntervalGate(
        "safety_stock_units",
        ("service_level",),
        obliges_value=True,
    ),
    "replenishment_recommendations": IntervalGate(
        "recommended_units",
        ("reorder_point_units", "order_up_to_units"),
        obliges_value=False,
    ),
}

#: Columns whose absence must be explained by a named reason, and the column that
#: names it. The same shape 0009 gave the forecast interval.
REASON_PAIRED: Final[dict[str, tuple[str, str]]] = {
    "inventory_stock_health": ("cover_days", "reason_code"),
    "inventory_valuation": ("gross_value_minor", "cost_reason_code"),
}

HEALTH_CLASSES: Final[frozenset[str]] = frozenset(
    {"stockout", "understock", "healthy", "overstock", "dead"}
)

RUN_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/createdAt",
    "/executionProfile",
    "/stageTelemetry",
    *tuple(
        f"/artifacts/{name}/{field}"
        for name in ARTIFACT_SCHEMAS
        for field in ("path", "bytes", "sha256")
    ),
)


class InventoryPublicationError(RuntimeError):
    """A candidate cannot satisfy the immutable inventory-run contract."""


@dataclass(frozen=True)
class InventoryRunPublication:
    """Identity released only after every artifact has been written and hashed."""

    inventory_run_id: str
    semantic_fingerprint: str
    root: Path
    lifecycle_status: str
    row_counts: dict[str, int]


def _replay_reason_code(
    *, acceptance_passed: bool, oracle: Mapping[str, Any] | None
) -> str | None:
    """Name which stage actually withheld the replay capability.

    P4-D13 runs the oracle first: the mechanism must reconstruct observed stock
    before any policy comparison is allowed to mean anything. So there are two
    distinct unavailable states, and a screen that conflates them misinforms --
    "the replay does not reproduce" and "the replay reproduces but no candidate
    strictly won" call for completely different reading.
    """

    if acceptance_passed:
        return None
    if oracle is not None and bool(oracle.get("passed")):
        return "REPLAY_NO_CANDIDATE_IMPROVEMENT"
    return "REPLAY_ORACLE_DID_NOT_REPRODUCE"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryPublicationError(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_artifact(name: str, frame: pd.DataFrame, *, markets: list[str]) -> None:
    """Every structural rule 0010 enforces, checked here first and by name."""

    expected = ARTIFACT_COLUMNS[name]
    _require(
        tuple(frame.columns) == expected,
        f"{name}: columns {tuple(frame.columns)} do not match the frozen "
        f"contract {expected}",
    )
    grain = list(ARTIFACT_GRAIN[name])
    duplicated = frame.duplicated(grain)
    _require(
        not bool(duplicated.any()),
        f"{name}: {int(duplicated.sum())} rows duplicate the grain {grain}; two "
        "rows for one cell double-count on every screen that sums them",
    )
    unknown_markets = sorted(set(frame["market_id"].astype(str)) - set(markets))
    _require(
        not unknown_markets,
        f"{name}: rows in markets {unknown_markets} the manifest does not declare",
    )

    if name in INTERVAL_GATED:
        gate, withheld_null, obliges_value = INTERVAL_GATED[name]
        available = frame["interval_available"].astype(bool)
        gate_present = frame[gate].notna()
        # The withheld direction, always: a value present without the interval
        # that earned it is fabricated.
        fabricated = gate_present & ~available
        _require(
            not bool(fabricated.any()),
            f"{name}: interval_available disagrees with {gate} on "
            f"{int(fabricated.sum())} rows -- a value present without the interval "
            "that earned it. Decision #92 makes the flag and the value one fact.",
        )
        unearned = available & ~gate_present
        if obliges_value:
            # And the available direction, where 0010 asks for it.
            _require(
                not bool(unearned.any()),
                f"{name}: interval_available disagrees with {gate} on "
                f"{int(unearned.sum())} rows -- {gate} is a closed-form function "
                "of the interval, so it cannot be absent when the interval is not.",
            )
        else:
            # Where 0010 does not, the absence is a solver refusal and still owes
            # a named reason -- otherwise the screen renders an empty cell with
            # nothing to explain it, which is the bare-unavailable defect.
            refusals = frame.loc[unearned, "reason_code"].dropna().astype(str)
            _require(
                len(refusals) == int(unearned.sum()),
                f"{name}: {gate} is absent without a reason on "
                f"{int(unearned.sum()) - len(refusals)} rows whose interval was "
                "available; a refusal a screen cannot explain renders bare",
            )
            ungoverned_refusals = sorted(set(refusals) - SOLVER_REASONS)
            _require(
                not ungoverned_refusals,
                f"{name}: ungoverned solver reasons {ungoverned_refusals}; only "
                f"{sorted(SOLVER_REASONS)} may explain a refused order",
            )
        withheld = ~available
        for column in withheld_null:
            _require(
                bool(frame.loc[withheld, column].isna().all()),
                f"{name}: {column} is populated on a row whose interval was "
                "withheld; a value derived from an absent interval is fabricated",
            )
        reasons = frame.loc[withheld, "reason_code"].dropna().astype(str)
        _require(
            len(reasons) == int(withheld.sum()),
            f"{name}: a withheld interval must name its reason on every row",
        )
        ungoverned = sorted(set(reasons) - GOVERNED_REASONS)
        _require(
            not ungoverned,
            f"{name}: ungoverned interval reasons {ungoverned}; only "
            f"{sorted(GOVERNED_REASONS)} are contractual",
        )
        # An available interval may not borrow a withholding reason. The one
        # exception is the solver refusal governed above, and only on the rows it
        # actually explains: a reason sitting beside a published quantity explains
        # nothing and contradicts itself.
        excused = ~available if obliges_value else unearned
        stray = frame.loc[available & ~excused, "reason_code"].notna()
        _require(
            not bool(stray.any()),
            f"{name}: an available interval carries a withholding reason on "
            f"{int(stray.sum())} rows",
        )

    if name in REASON_PAIRED:
        value_column, reason_column = REASON_PAIRED[name]
        absent = frame[value_column].isna()
        named = frame[reason_column].notna()
        _require(
            bool((absent == named).all()),
            f"{name}: {value_column} and {reason_column} disagree on "
            f"{int((absent != named).sum())} rows. An absent value with no reason "
            "is a gap; a reason with a value is noise.",
        )

    if name == "inventory_stock_health":
        unknown = sorted(set(frame["health_class"].astype(str)) - HEALTH_CLASSES)
        _require(not unknown, f"{name}: unknown health classes {unknown}")

    if name == "replenishment_recommendations":
        statuses = set(frame["erp_status"].astype(str))
        _require(
            statuses <= {ERP_STATUS},
            f"{name}: erp_status {sorted(statuses - {ERP_STATUS})} is not "
            f"{ERP_STATUS!r}; P4-D11 keeps this surface shadow-only",
        )

    if name == "inventory_positions":
        # Active-or-residual, never Cartesian: a row that is neither in the
        # assortment nor holding residual stock is a cell nothing observed.
        phantom = (~frame["assortment_active"].astype(bool)) & (
            ~frame["residual_only"].astype(bool)
        )
        _require(
            not bool(phantom.any()),
            f"{name}: {int(phantom.sum())} rows are neither assortment-active nor "
            "residual. Emitting them makes the grain a store x SKU cross join.",
        )


#: The two capabilities temporal-evidence policy v2 split the retired
#: `inventory_replenishment` into. They are scoped separately here because they
#: rest on different evidence and fail independently.
CURRENT_SNAPSHOT_CAPABILITY: Final[str] = "inventory_replenishment_current_snapshot"
REPLAY_CAPABILITY: Final[str] = "inventory_replenishment_replay"

#: Artifacts whose every value is current-state or forecast-derived. None of them
#: consumes a replay, so none of them is affected by whether the replay reproduced.
CURRENT_SNAPSHOT_ARTIFACTS: Final[frozenset[str]] = frozenset(
    set(ARTIFACT_SCHEMAS) - {"inventory_replay_metrics"}
)


def _validate_replay(
    replay: dict[str, Any], *, metrics: pd.DataFrame, claimed: bool
) -> None:
    """Structural checks on the replay record, and the oracle only if claimed.

    The oracle is a precondition for COMPARING POLICIES, not for serving current
    state. An earlier version made it a precondition for the whole bundle, which
    meant a network whose weekly stock could not be reconstructed served nothing at
    all -- not even its own observed positions, which need no replay to be true.
    That conflated a policy-acceptance gate with a data-availability gate.

    So `claimed` decides. A run that claims the replay capability must have
    reproduced; a run that declares it unavailable publishes its measured delta and
    its failing gate rows as the evidence for that unavailability, and the twelve
    current-state artifacts stand on their own.

    What does NOT relax either way: the tolerance must still be frozen before
    scoring, and the incumbent must still be named. Those are about honesty of
    method, and a run with no method has nothing to disclose.
    """

    _require(
        replay.get("oracleTolerance", {}).get("frozenBeforeScoring") is True,
        "the oracle tolerance must be recorded as frozen before scoring; a "
        "tolerance widened after seeing the delta is not a tolerance",
    )
    _require(
        bool(replay.get("incumbentPolicyId")),
        "an incumbent policy id is required; an incumbent inferred from outcomes "
        "is a second candidate, not a baseline",
    )
    if claimed:
        _require(
            replay.get("oracle", {}).get("passed") is True,
            "a run claiming the replay capability must have reproduced observed "
            "closing stock; it has no standing to compare policies otherwise. "
            "Declare the capability unavailable to publish current state without "
            "it.",
        )
        cohorts = set(metrics["cohort"].astype(str))
        _require(
            cohorts == {"calibration", "holdout"},
            f"replay metrics cover cohorts {sorted(cohorts)}; both the calibration "
            "and holdout cohorts must be published or the split proves nothing",
        )
        return

    # An unavailable capability must say WHY, and there are exactly two reasons.
    # This used to admit only the first, which made the second unpublishable:
    # once the reconstruction was corrected the oracle reproduced, the candidate
    # still failed to beat its incumbent, and the run could not be published at
    # all -- a passing oracle read as a contradiction rather than as progress.
    oracle_failed = replay.get("oracle", {}).get("passed") is False
    gates_failed = any(
        cohort.get("passed") is False
        for cohort in (replay.get("perCohort") or {}).values()
    )
    _require(
        oracle_failed or gates_failed,
        "the replay capability is declared unavailable, so either the oracle "
        "must show it did not reproduce or a cohort must show a gate it did not "
        "pass. Unavailable with both passing is a contradiction.",
    )
    if gates_failed and not oracle_failed:
        # The oracle reproduced, so the gates WERE scored and their rows are the
        # evidence. Both cohorts, for the same reason the claimed branch demands
        # them: one cohort's verdict proves nothing about the split.
        cohorts = set(metrics["cohort"].astype(str))
        _require(
            cohorts == {"calibration", "holdout"},
            f"the replay reproduced but did not pass its gates, so both cohorts' "
            f"scored metrics are the evidence for that; found {sorted(cohorts)}",
        )
        return

    # Oracle-first: a failed oracle stops the comparison BEFORE any gate is
    # scored, so there is nothing to publish and demanding rows would force
    # scoring them anyway -- precisely what oracle-first forbids. The evidence is
    # the oracle's own measured record, per market.
    per_market = (replay.get("oracle") or {}).get("perMarket") or {}
    _require(
        bool(per_market),
        "an unavailable replay capability must publish the oracle's per-market "
        "measurement; without it the unavailability is asserted, not evidenced",
    )
    for market, verdict in sorted(per_market.items()):
        _require(
            verdict.get("measuredMeanAbsUnitDeltaPerCell") is not None,
            f"{market}: the oracle record carries no measured delta, so nothing "
            "says how far the reconstruction actually was",
        )
        _require(
            verdict.get("tolerancePerCell") is not None,
            f"{market}: the oracle record carries no tolerance, so the measured "
            "delta cannot be judged against anything",
        )


def publish_inventory_run(
    destination: str | Path,
    *,
    frames: dict[str, pd.DataFrame],
    markets: list[str],
    decision_as_of: datetime,
    input_bundle: dict[str, str],
    source_selection_id: str,
    forecast_authority: dict[str, str],
    policy_fingerprints: dict[str, str],
    replay: dict[str, Any],
    lane_coverage_pct: float,
    acceptance_passed: bool,
    execution_profile: str,
    created_at: datetime,
) -> InventoryRunPublication:
    """Write the bundle, then derive its identity from what was written."""

    _require(bool(markets), "at least one market is required")
    _require(
        decision_as_of.tzinfo is not None,
        "decisionAsOf must be timezone-aware; a naive instant cannot be replayed",
    )
    missing = sorted(set(ARTIFACT_SCHEMAS) - set(frames))
    _require(
        not missing,
        f"bundle omits required artifacts {missing}. A partial bundle serving "
        "fourteen screens has no honest way to say which screen is trustworthy.",
    )
    extra = sorted(set(frames) - set(ARTIFACT_SCHEMAS))
    _require(not extra, f"bundle carries unknown artifacts {extra}")

    for name in ARTIFACT_SCHEMAS:
        _validate_artifact(name, frames[name], markets=sorted(markets))
    replay_claimed = bool(acceptance_passed)
    _validate_replay(
        replay,
        metrics=frames["inventory_replay_metrics"],
        claimed=replay_claimed,
    )

    for market in sorted(markets):
        _require(
            market in policy_fingerprints,
            f"no resolved policy fingerprint for market {market}; an unresolved "
            "market is served by no policy at all",
        )
    _require(
        float(lane_coverage_pct) >= 100.0,
        f"lane coverage is {lane_coverage_pct}%; a fulfillment row the network "
        "cannot explain cannot be replayed",
    )
    _require(
        forecast_authority.get("coverageGateMode") == "hard",
        "the consumed forecast must have been scored under decision #85's hard "
        "per-cohort coverage gate",
    )

    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, dict[str, Any]] = {}
    row_counts: dict[str, int] = {}
    for name, schema_version in ARTIFACT_SCHEMAS.items():
        frame = frames[name]
        path = root / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        # Fingerprint the READ-BACK frame, not the in-memory one. A semantic
        # fingerprint describes what a consumer will see, and Parquet does not
        # round-trip every Python value to the same type: `reason_codes` is written
        # as a list and comes back as a numpy array, which `_normalized_scalar`
        # renders through `str()` into a different string. The verifier reads from
        # disk, so fingerprinting the in-memory frame guaranteed a mismatch on
        # every artifact carrying a list column -- which is exactly what the
        # verifier caught on `replenishment_suppliers`.
        written = pd.read_parquet(path)
        artifacts[name] = {
            "schemaVersion": schema_version,
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
            "semanticFingerprint": _frame_semantic_fingerprint(
                written, schema_version=schema_version
            ),
            "rowCount": len(written),
        }
        row_counts[name] = len(frame)

    acceptance = {
        "schemaVersion": "retail-inventory-acceptance/v1",
        "passed": bool(acceptance_passed),
        "replay": replay,
    }
    acceptance_path = root / "inventory-acceptance.json"
    acceptance_path.write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # The bundle is accepted when its current-state artifacts satisfy their own
    # contract, which the per-artifact validation above has just established. The
    # replay verdict scopes ONE capability; it is not the bundle's lifecycle.
    # Making it so meant an unreproducible replay withheld the observed positions
    # too, and those need no replay to be true.
    lifecycle_status = "accepted"
    capabilities = {
        CURRENT_SNAPSHOT_CAPABILITY: {
            "available": True,
            "artifacts": sorted(CURRENT_SNAPSHOT_ARTIFACTS),
        },
        REPLAY_CAPABILITY: {
            "available": bool(acceptance_passed),
            "artifacts": ["inventory_replay_metrics"],
            # Two different things withhold this capability and they are not
            # interchangeable. Publishing one constant for both told every reader
            # of r3..r8 that the oracle had not reproduced when it had, and the
            # real cause was a candidate that did not strictly beat the incumbent
            # -- a governed outcome under P4-D13, not a broken mechanism.
            "reasonCode": _replay_reason_code(
                acceptance_passed=bool(acceptance_passed),
                oracle=replay.get("oracle"),
            ),
            # The measured delta travels with the unavailability so the claim is
            # auditable rather than asserted.
            "oracle": replay.get("oracle"),
        },
    }
    manifest: dict[str, Any] = {
        "schemaVersion": RUN_SCHEMA_VERSION,
        "lifecycleStatus": lifecycle_status,
        "capabilities": capabilities,
        "markets": sorted(markets),
        "decisionAsOf": decision_as_of.isoformat(),
        "createdAt": created_at.isoformat(),
        "executionProfile": execution_profile,
        "inputBundle": dict(input_bundle),
        "sourceSelectionId": source_selection_id,
        "forecastAuthority": dict(forecast_authority),
        "policy": {
            "policyVersion": POLICY_VERSION,
            "resolvedFingerprints": dict(policy_fingerprints),
        },
        "intervalAvailability": {
            "calibratedMaxHorizon": CALIBRATED_MAX_HORIZON,
            "governedReasons": sorted(GOVERNED_REASONS),
            "consumersEnabled": True,
        },
        "laneContract": {"fulfillmentCoveragePct": f"{float(lane_coverage_pct):.4f}"},
        "replay": replay,
        "acceptance": {
            "schemaVersion": acceptance["schemaVersion"],
            "passed": bool(acceptance_passed),
            "semanticFingerprint": _json_semantic_fingerprint(
                acceptance, schema_version=str(acceptance["schemaVersion"])
            ),
        },
        "artifacts": artifacts,
        "fingerprintContract": {
            "schemaVersion": "semantic-fingerprint/v1",
            "volatilePointers": list(RUN_VOLATILE_POINTERS),
        },
    }

    # Identity is semantic: everything that changes what is served is in the seed,
    # and nothing that does not is. `createdAt` and the execution profile are
    # deliberately absent, so republishing the same evidence returns the same run.
    run_seed = {
        "inputBundle": manifest["inputBundle"],
        "sourceSelectionId": source_selection_id,
        "forecastAuthority": manifest["forecastAuthority"],
        "policy": manifest["policy"],
        "decisionAsOf": manifest["decisionAsOf"],
        "markets": manifest["markets"],
        "artifactSemanticFingerprints": {
            name: artifacts[name]["semanticFingerprint"] for name in ARTIFACT_SCHEMAS
        },
        "acceptanceSemanticFingerprint": manifest["acceptance"]["semanticFingerprint"],
    }
    manifest["inventoryRunId"] = "ir_" + hashlib.sha256(
        json.dumps(run_seed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    manifest["semanticFingerprint"] = semantic_fingerprint(
        manifest, volatile_pointers=RUN_VOLATILE_POINTERS
    )

    (root / "inventory-run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return InventoryRunPublication(
        inventory_run_id=str(manifest["inventoryRunId"]),
        semantic_fingerprint=str(manifest["semanticFingerprint"]),
        root=root,
        lifecycle_status=lifecycle_status,
        row_counts=row_counts,
    )


__all__ = [
    "ARTIFACT_COLUMNS",
    "ARTIFACT_GRAIN",
    "ARTIFACT_SCHEMAS",
    "CALIBRATED_MAX_HORIZON",
    "ERP_STATUS",
    "GOVERNED_REASONS",
    "HEALTH_CLASSES",
    "INTERVAL_GATED",
    "POLICY_VERSION",
    "REASON_PAIRED",
    "RUN_SCHEMA_VERSION",
    "RUN_VOLATILE_POINTERS",
    "InventoryPublicationError",
    "InventoryRunPublication",
    "publish_inventory_run",
]
