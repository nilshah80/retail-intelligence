"""Coverage for the orchestration in tools/dev.py.

Both bugs in the pipeline command were found by running it, not by tests: --label named
the feature directory as well as the artifact directories, and the host-profile helper is
the thing that decides whether a 40-minute backtest takes 40 minutes or five hours. These
are pure functions and were trivially testable; not testing them is how a command built to
absorb wiring mistakes shipped with two of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev  # noqa: E402


def test_stage_slice_is_inclusive_and_ordered() -> None:
    assert dev._stage_slice("land", "activate") == dev.PIPELINE_STAGES
    assert dev._stage_slice("publish", "activate") == (
        "publish",
        "materialize",
        "activate",
    )
    # A single-stage slice must contain exactly that stage, which is what
    # `--from materialize --to materialize` relies on.
    assert dev._stage_slice("materialize", "materialize") == ("materialize",)


def test_datagen_is_not_a_pipeline_stage() -> None:
    """Generation is ~90 minutes and 15 GB and the pinned scenario reproduces its
    business data exactly, so it must not be reachable from the fast loop by accident."""

    assert "datagen" not in dev.PIPELINE_STAGES
    assert "generate" not in dev.PIPELINE_STAGES


def test_stage_order_puts_finalize_before_the_ml_stages() -> None:
    """Skipping finalize left ingestion/data/evidence/<run>/gate-a.json absent, which the
    pinned-run tests read directly, so two of them failed on an otherwise complete run."""

    order = list(dev.PIPELINE_STAGES)
    assert order.index("finalize") < order.index("features")
    assert order.index("publish") < order.index("materialize") < order.index("activate")


def test_host_profile_never_returns_ultra_performance() -> None:
    """ultra-performance asks for 6 model workers x 4 threads regardless of core count,
    so on a 16-core host it oversubscribes and contends rather than going faster."""

    assert dev._host_execution_profile() != "ultra-performance"
    assert dev._host_execution_profile() in {"safe", "balanced", "performance"}


@pytest.mark.parametrize(
    "lead_days,expected",
    [(5, 2), (1, 2), (7, 2), (8, 3), (60, 10)],
)
def test_reorder_horizon_from_lead_time(lead_days: int, expected: int) -> None:
    """The h1-h4 interval limit is load-bearing, so the horizon a reorder decision needs
    must be derived from lead time plus review period rather than assumed."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml" / "src"))
    from retail_ml.policies.interval_availability import horizon_for_lead_time

    assert horizon_for_lead_time(lead_days) == expected
