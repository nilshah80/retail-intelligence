"""Closed enums the two gates and the capability mask depend on.

Every one of these is a *locked* decision. They are closed on purpose: an
implementation that only understands `critical` and `warning` would silently
mishandle a `capability_downgrade`, and a single collapsed "scope" enum would let
an Indian region join a US one. See `docs/OPEN_DECISIONS.md` #40, #41, #42 and
`plans/local/phase2-implementation-plan.md` §7.
"""

from enum import StrEnum


class GeoScopeType(StrEnum):
    """Single-axis geographic scope (decision #40).

    Resolved only *inside* `market_id`. Market-wide means `(market, market_id)` —
    never an unqualified `ALL`.
    """

    MARKET = "market"
    REGION = "region"
    LOCATION = "location"


class MerchScopeType(StrEnum):
    """Merchandise scope for supplier terms and promotion targets (decision #42).

    Precedence is strictly `SKU > DEPT > CATEGORY`; see `merch_precedence`.
    """

    SKU = "sku"
    DEPT = "dept"
    CATEGORY = "category"


#: Lower number wins. Conflicting equal-precedence matches are a Gate-B critical.
MERCH_PRECEDENCE: dict[MerchScopeType, int] = {
    MerchScopeType.SKU: 0,
    MerchScopeType.DEPT: 1,
    MerchScopeType.CATEGORY: 2,
}


def merch_precedence(scope_type: MerchScopeType | str) -> int:
    """Return the precedence rank of a merchandise scope (lower wins)."""
    return MERCH_PRECEDENCE[MerchScopeType(scope_type)]


class TemporalClass(StrEnum):
    """How an entity establishes identity over time (decision #41).

    Only cumulative/correctable facts carry explicit monotonic integer versions.
    Everything else uses natural key + effective/observation time + `known_as_of`.
    """

    CUMULATIVE_VERSIONED = "cumulative_versioned"
    OBSERVATIONAL = "observational"


class RuleOutcome(StrEnum):
    """Gate A / Gate B rule outcome — a closed enum, not free text.

    `CAPABILITY_DOWNGRADE` is not a severity of failure: the data is valid but
    cannot support one named capability. It routes to the capability mask with an
    `affected_capability` and a `reason_code`, never to `quality_violations` as if
    it were a lesser `CRITICAL`.
    """

    PASS = "pass"
    WARNING = "warning"
    CAPABILITY_DOWNGRADE = "capability_downgrade"
    CRITICAL = "critical"


#: Outcomes that block publication of the affected tier.
BLOCKING_OUTCOMES: frozenset[RuleOutcome] = frozenset({RuleOutcome.CRITICAL})


class EvidenceGrade(StrEnum):
    """Provenance of a derived `known_as_of` value.

    Availability evidence only. Business/effective time (`event_at`,
    `effective_from`, `sale_date`, `receipt_date`) may **never** become
    `known_as_of` by default — those say when a fact applies or happened, not when
    the retailer first knew it, and conflating them reintroduces historical
    leakage. A profile may promote a posting or event timestamp only under an
    explicit versioned rule that its source semantics justify.
    """

    NATIVE_OBSERVED = "native_observed"
    NATIVE_PROCESSED = "native_processed"
    NATIVE_POSTED_AVAILABLE = "native_posted_available"
    NATIVE_EXTRACTED = "native_extracted"
    LANDING_BACKFILL = "landing_backfill"


#: Grades that cannot support a point-in-time claim. A T1 series resting on one of
#: these downgrades the PIT capability (Gate B B21) rather than passing silently.
NON_PIT_EVIDENCE: frozenset[EvidenceGrade] = frozenset({EvidenceGrade.LANDING_BACKFILL})


class EntityTier(StrEnum):
    """Publication tier (plan W1.12).

    A T2/T3 gap downgrades a capability; it never fails the T1 publication.
    """

    T1_CORE = "t1_core"
    T2_OPERATIONAL = "t2_operational"
    T3_CONTROL = "t3_control"


class DatasetClass(StrEnum):
    """How a published source dataset is handled (plan W1.16).

    Not every dataset becomes staging data. An unclassified dataset is a Gate-A
    critical (A13) — silence is not a classification.
    """

    STAGED = "staged"
    CONTROL_ONLY = "control_only"
    FIXTURE_ONLY = "fixture_only"
    RESTRICTED_ORACLE = "restricted_oracle"
    IGNORED_BY_PROFILE = "ignored_by_profile"
    UNSUPPORTED = "unsupported"


class ColumnOutcome(StrEnum):
    """What a missing or unusable source column does (plan W1.15).

    A blanket hard error is wrong for real retailers; so is silently zero-filling.
    """

    GATE_A_FAILURE = "gate_a_failure"
    DERIVE_WITH_PROVENANCE = "derive_with_provenance"
    CAPABILITY_DOWNGRADE = "capability_downgrade"
    QUARANTINE = "quarantine"
    DECLARED_UNSUPPORTED = "declared_unsupported"


class CapabilityAvailability(StrEnum):
    """Capability availability axis — orthogonal to evidence (spec §11.10)."""

    ENABLED = "enabled"
    REQUIRES_COMPANION = "requires_companion"
    UNAVAILABLE = "unavailable"


class CapabilityEvidence(StrEnum):
    """Capability evidence axis — orthogonal to availability.

    `SYNTHETIC_SCENARIO` can power a visibly labelled demo only; it can never
    satisfy a client-actual required-field gate (spec §4.9, §10.3).
    """

    CLIENT_ACTUAL = "client_actual"
    SYNTHETIC_TEST = "synthetic_test"
    SYNTHETIC_SCENARIO = "synthetic_scenario"


class RowProvenance(StrEnum):
    """Row-level provenance label — separate from entity ownership (spec §11.0)."""

    SYNTHETIC = "SYNTHETIC"
    SHOPIFY_ACTUAL = "SHOPIFY_ACTUAL"
    SHOPIFY_DERIVED = "SHOPIFY_DERIVED"
    ERP_ACTUAL = "ERP_ACTUAL"
    EXTERNAL_ACTUAL = "EXTERNAL_ACTUAL"


class GateStatus(StrEnum):
    """Overall status of an ingest run (spec §4.1)."""

    PASS = "pass"
    VALIDATED_PARTIAL = "validated_partial"
    FAIL = "fail"


__all__ = [
    "BLOCKING_OUTCOMES",
    "MERCH_PRECEDENCE",
    "NON_PIT_EVIDENCE",
    "CapabilityAvailability",
    "CapabilityEvidence",
    "ColumnOutcome",
    "DatasetClass",
    "EntityTier",
    "EvidenceGrade",
    "GateStatus",
    "GeoScopeType",
    "MerchScopeType",
    "RowProvenance",
    "RuleOutcome",
    "TemporalClass",
    "merch_precedence",
]
