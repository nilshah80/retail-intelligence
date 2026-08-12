"""PP3-A7 retailer/tenant publication selection and lifecycle.

Replaces "discover the committed demo pin" with an explicit, immutable selection
per retailer x tenant x capability x environment. There is no `latest`
resolution: a runtime command names a selection, and every mismatch fails closed
rather than degrading serving quietly.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

SELECTION_SCHEMA_VERSION: Final[str] = "retail-publication-selection/v1"
SELECTION_SCHEMA_VERSION_V2: Final[str] = "retail-publication-selection/v2"

#: Audit metadata and derived ids are excluded from semantic identity, so
#: re-approving the same publication cannot mint a different selection.
IDENTITY_EXCLUDES: Final[frozenset[str]] = frozenset(
    {"approval", "selectionId", "semanticIdentityExcludes", "lifecycle"}
)

# V2 makes the runtime rule an ordered, schema-enforced RFC 6901 vector. Keeping
# it beside the legacy rule makes compatibility deliberate instead of allowing a
# schema default and a Python constant to drift independently again.
IDENTITY_EXCLUDES_V2: Final[tuple[str, ...]] = (
    "/approval",
    "/lifecycle",
    "/selectionId",
    "/semanticIdentityExcludes",
)
LEGACY_EXPLICIT_IDENTITY_EXCLUDES: Final[tuple[str, ...]] = (
    "approval",
    "selectionId",
    "semanticIdentityExcludes",
    "lifecycle",
)

TERMINAL_STATES: Final[frozenset[str]] = frozenset({"superseded", "rejected"})
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"approved", "rejected"}),
    "approved": frozenset({"active", "rejected"}),
    "active": frozenset({"superseded"}),
    "superseded": frozenset(),
    "rejected": frozenset(),
}


class SelectionError(RuntimeError):
    """A publication selection is absent, ambiguous or under-capable."""


def semantic_identity(selection: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in selection.items()
        if key not in IDENTITY_EXCLUDES
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def derive_selection_id(selection: Mapping[str, Any]) -> str:
    """Identify *what* is selected. Stable across lifecycle states."""

    return f"sel_{semantic_identity(selection)[:16]}"


def derive_record_id(selection: Mapping[str, Any]) -> str:
    """Identify one lifecycle record of that selection.

    The selection id answers "which publication for which scope"; the record id
    answers "which approval event". Keeping them separate is what lets a
    supersedes chain exist without the selected publication appearing to change.
    """

    lifecycle = selection.get("lifecycle") or {}
    payload = {
        "selectionId": derive_selection_id(selection),
        "state": lifecycle.get("state"),
        "supersedes": lifecycle.get("supersedes"),
        "reasonCode": lifecycle.get("reasonCode"),
        "approval": selection.get("approval"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"rec_{digest[:16]}"


def semantic_identity_v2(selection: Mapping[str, Any]) -> str:
    """Return the JCS semantic identity declared by the V2 exclusion vector."""

    vector = tuple(selection.get("semanticIdentityExcludes") or ())
    if vector != IDENTITY_EXCLUDES_V2:
        raise SelectionError(
            "selection v2 semanticIdentityExcludes must exactly equal the "
            f"ordered vector {list(IDENTITY_EXCLUDES_V2)!r}"
        )
    from retail_contracts.fingerprint import semantic_fingerprint

    return semantic_fingerprint(
        dict(selection), volatile_pointers=IDENTITY_EXCLUDES_V2
    )


def derive_selection_id_v2(selection: Mapping[str, Any]) -> str:
    return f"sel_{semantic_identity_v2(selection)[:16]}"


def derive_record_id_v2(selection: Mapping[str, Any]) -> str:
    """Identify one immutable V2 lifecycle event using canonical JSON."""

    lifecycle = selection.get("lifecycle") or {}
    payload = {
        "approval": selection.get("approval"),
        "reasonCode": lifecycle.get("reasonCode"),
        "selectionId": derive_selection_id_v2(selection),
        "state": lifecycle.get("state"),
        "supersedes": lifecycle.get("supersedes"),
    }
    from retail_contracts.fingerprint import canonical_json_bytes

    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"rec_{digest[:16]}"


def scope_key(selection: Mapping[str, Any]) -> tuple[str, str, str, str]:
    scope = selection["scope"]
    return (
        str(scope["retailerId"]),
        str(scope["tenantId"]),
        str(scope["capability"]),
        str(scope["environment"]),
    )


def validate_selection(selection: Mapping[str, Any]) -> None:
    """Structural and identity checks before a selection may be used."""

    version = selection.get("schemaVersion")
    if version == SELECTION_SCHEMA_VERSION_V2:
        validate_selection_v2(selection)
        return
    if version != SELECTION_SCHEMA_VERSION:
        raise SelectionError(
            f"unsupported selection schema {version!r}"
        )
    explicit_vector = selection.get("semanticIdentityExcludes")
    if explicit_vector is not None and tuple(explicit_vector) != (
        LEGACY_EXPLICIT_IDENTITY_EXCLUDES
    ):
        raise SelectionError(
            "legacy v1 selection has a conflicting explicit identity-exclusion "
            "vector; omission uses the frozen compatibility rule"
        )
    expected = derive_selection_id(selection)
    if selection.get("selectionId") != expected:
        raise SelectionError(
            f"selectionId {selection.get('selectionId')!r} does not match its "
            f"semantic identity {expected!r}"
        )
    state = selection["lifecycle"]["state"]
    if state not in ALLOWED_TRANSITIONS:
        raise SelectionError(f"unknown lifecycle state {state!r}")


def validate_selection_v2(selection: Mapping[str, Any]) -> None:
    """Validate V2 identity, lifecycle-event identity, and closed fields."""

    if selection.get("schemaVersion") != SELECTION_SCHEMA_VERSION_V2:
        raise SelectionError(
            f"unsupported selection schema {selection.get('schemaVersion')!r}"
        )
    expected = derive_selection_id_v2(selection)
    if selection.get("selectionId") != expected:
        raise SelectionError(
            f"selectionId {selection.get('selectionId')!r} does not match its "
            f"semantic identity {expected!r}"
        )
    lifecycle = selection.get("lifecycle") or {}
    state = lifecycle.get("state")
    if state not in ALLOWED_TRANSITIONS:
        raise SelectionError(f"unknown lifecycle state {state!r}")
    expected_record = derive_record_id_v2(selection)
    if lifecycle.get("recordId") != expected_record:
        raise SelectionError(
            f"recordId {lifecycle.get('recordId')!r} does not match its lifecycle "
            f"identity {expected_record!r}"
        )


def assert_one_active_per_scope(selections: Iterable[Mapping[str, Any]]) -> None:
    """Two active selections for one scope is a hard failure, not a race."""

    seen: dict[tuple[str, str, str, str], str] = {}
    for selection in selections:
        if selection["lifecycle"]["state"] != "active":
            continue
        key = scope_key(selection)
        if key in seen:
            raise SelectionError(
                "two active selections for scope "
                f"{'/'.join(key)}: {seen[key]} and {selection['selectionId']}"
            )
        seen[key] = str(selection["selectionId"])


def transition(
    selection: Mapping[str, Any],
    target_state: str,
    *,
    actor: str,
    reason: str,
    reason_code: str | None = None,
) -> dict[str, Any]:
    """Return a NEW selection record. Nothing is ever mutated in place."""

    current = selection["lifecycle"]["state"]
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target_state not in allowed:
        raise SelectionError(
            f"illegal transition {current} -> {target_state}; "
            f"allowed: {sorted(allowed) or 'none'}"
        )
    updated = json.loads(json.dumps(selection))
    updated["lifecycle"] = {
        "state": target_state,
        "supersedes": selection["lifecycle"].get("recordId"),
    }
    if reason_code:
        updated["lifecycle"]["reasonCode"] = reason_code
    updated["approval"] = {
        "actor": actor,
        "approvedAt": selection["approval"]["approvedAt"],
        "reason": reason,
    }
    updated["selectionId"] = derive_selection_id(updated)
    updated["lifecycle"]["recordId"] = derive_record_id(updated)
    return updated


def transition_v2(
    selection: Mapping[str, Any],
    target_state: str,
    *,
    actor: str,
    recorded_at: str,
    reason: str,
    evidence_fingerprint: str,
    reason_code: str | None = None,
) -> dict[str, Any]:
    """Return a new V2 event; the selected subject identity stays unchanged."""

    validate_selection_v2(selection)
    current = selection["lifecycle"]["state"]
    if target_state not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise SelectionError(
            f"illegal transition {current} -> {target_state}; allowed: "
            f"{sorted(ALLOWED_TRANSITIONS.get(current, ())) or 'none'}"
        )
    updated = json.loads(json.dumps(selection))
    updated["lifecycle"] = {
        "state": target_state,
        "supersedes": selection["lifecycle"]["recordId"],
    }
    if reason_code:
        updated["lifecycle"]["reasonCode"] = reason_code
    updated["approval"] = {
        "actor": actor,
        "recordedAt": recorded_at,
        "reason": reason,
        "evidenceFingerprint": evidence_fingerprint,
    }
    updated["selectionId"] = derive_selection_id_v2(updated)
    updated["lifecycle"]["recordId"] = derive_record_id_v2(updated)
    validate_selection_v2(updated)
    return updated


def rollback(
    active: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Roll back by superseding forward, never by editing history."""

    if active["lifecycle"]["state"] != "active":
        raise SelectionError("only an active selection can be rolled back")
    if scope_key(active) != scope_key(previous):
        raise SelectionError("rollback target must share the active scope")
    retired = transition(
        active,
        "superseded",
        actor=actor,
        reason=reason,
        reason_code="ROLLBACK",
    )
    reinstated = json.loads(json.dumps(previous))
    reinstated["lifecycle"] = {
        "state": "active",
        "supersedes": retired["lifecycle"]["recordId"],
        "reasonCode": "ROLLBACK",
    }
    reinstated["approval"] = {
        "actor": actor,
        "approvedAt": previous["approval"]["approvedAt"],
        "reason": reason,
    }
    reinstated["selectionId"] = derive_selection_id(reinstated)
    reinstated["lifecycle"]["recordId"] = derive_record_id(reinstated)
    return retired, reinstated


def resolve_selection(
    path: str | Path,
    *,
    retailer_id: str,
    tenant_id: str,
    capability: str,
    environment: str,
    repository_root: str | Path = ".",
    require_sufficient: bool = True,
) -> dict[str, Any]:
    """Load an explicitly named selection and fail closed on any mismatch.

    There is deliberately no search, no glob and no newest-wins fallback: the
    caller names one file, and it must match the requested scope exactly.
    """

    selection_path = Path(path)
    if not selection_path.is_file():
        raise SelectionError(f"publication selection is absent: {selection_path}")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    validate_selection(selection)

    requested = (retailer_id, tenant_id, capability, environment)
    if scope_key(selection) != requested:
        raise SelectionError(
            f"selection scope {'/'.join(scope_key(selection))} does not match "
            f"requested {'/'.join(requested)}"
        )
    if selection["lifecycle"]["state"] != "active":
        raise SelectionError(
            f"selection is {selection['lifecycle']['state']}, not active"
        )

    readiness = selection["readiness"]
    if readiness["capabilityReadiness"] != "ready":
        raise SelectionError(
            f"capability {capability} is {readiness['capabilityReadiness']}, "
            "not ready"
        )
    if require_sufficient and readiness["capabilitySufficiency"] != "sufficient":
        raise SelectionError(
            f"capability {capability} sufficiency is "
            f"{readiness['capabilitySufficiency']}"
        )

    subject = selection.get("subject") or selection.get("publication") or {}
    publication = Path(repository_root) / subject["logicalPath"]
    if not publication.exists():
        raise SelectionError(
            f"selected publication has moved or is absent: {publication}"
        )
    return selection


def _current_heads(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    superseded = {
        str((record.get("lifecycle") or {}).get("supersedes"))
        for record in records
        if (record.get("lifecycle") or {}).get("supersedes")
    }
    return [
        record
        for record in records
        if str((record.get("lifecycle") or {}).get("recordId")) not in superseded
    ]


def resolve_selection_ledger(
    ledger_root: str | Path,
    *,
    retailer_id: str,
    tenant_id: str,
    capability: str,
    environment: str,
    repository_root: str | Path = ".",
    require_sufficient: bool = True,
) -> dict[str, Any]:
    """Resolve exactly one current active event for the complete requested scope."""

    root = Path(ledger_root)
    if not root.is_dir():
        raise SelectionError(f"selection ledger is absent: {root}")
    records: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    ledger_paths = sorted(
        Path(entry.path)
        for entry in os.scandir(root)
        if entry.is_file() and entry.name.endswith(".json")
    )
    for path in ledger_paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SelectionError(f"invalid selection record {path}: {exc}") from exc
        if record.get("schemaVersion") not in {
            SELECTION_SCHEMA_VERSION,
            SELECTION_SCHEMA_VERSION_V2,
        }:
            continue
        validate_selection(record)
        record_id = str((record.get("lifecycle") or {}).get("recordId") or "")
        if not record_id:
            raise SelectionError(f"selection record has no recordId: {path}")
        if record_id in paths:
            raise SelectionError(
                f"duplicate selection recordId {record_id}: {paths[record_id]} and {path}"
            )
        paths[record_id] = path
        records.append(record)

    requested = (retailer_id, tenant_id, capability, environment)
    scoped = [record for record in records if scope_key(record) == requested]
    if not scoped:
        raise SelectionError(
            "no selection records for exact scope " + "/".join(requested)
        )
    by_record_id = {
        str(record["lifecycle"]["recordId"]): record for record in scoped
    }
    for record in scoped:
        predecessor = record["lifecycle"].get("supersedes")
        if predecessor is not None and predecessor not in by_record_id:
            raise SelectionError(
                f"selection predecessor {predecessor} is absent from exact scope "
                + "/".join(requested)
            )
    active = [
        record
        for record in _current_heads(scoped)
        if record["lifecycle"]["state"] == "active"
    ]
    if len(active) != 1:
        raise SelectionError(
            f"exact scope {'/'.join(requested)} resolves to {len(active)} current "
            "active selections; expected exactly one"
        )
    selected = dict(active[0])
    readiness = selected["readiness"]
    if readiness["capabilityReadiness"] != "ready":
        raise SelectionError(
            f"capability {capability} is {readiness['capabilityReadiness']}, not ready"
        )
    if require_sufficient and readiness["capabilitySufficiency"] != "sufficient":
        raise SelectionError(
            f"capability {capability} sufficiency is "
            f"{readiness['capabilitySufficiency']}"
        )
    subject = selected.get("subject") or selected.get("publication") or {}
    logical_path = subject.get("logicalPath")
    if logical_path and not (Path(repository_root) / logical_path).exists():
        raise SelectionError(
            "selected publication has moved or is absent: "
            f"{Path(repository_root) / logical_path}"
        )
    selected["_recordPath"] = str(paths[selected["lifecycle"]["recordId"]])
    return selected


def verify_against_publication(
    selection: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    """Confirm the selected publication is byte-for-byte the one approved."""

    declared = selection.get("subject") or selection.get("publication") or {}
    checks = {
        "publicationSemanticFingerprint": manifest.get("semanticFingerprint"),
        "gateBSemanticFingerprint": manifest.get("gateBSemanticFingerprint"),
        "sourceSnapshotId": manifest.get("sourceSnapshotId"),
    }
    for key, actual in checks.items():
        if declared.get(key) != actual:
            raise SelectionError(
                f"{key} mismatch: selection {declared.get(key)!r} vs "
                f"publication {actual!r}"
            )
    objects = manifest.get("objects")
    if isinstance(objects, list) and declared["objectCount"] != len(objects):
        raise SelectionError(
            f"object count mismatch: selection {declared['objectCount']} vs "
            f"publication {len(objects)}"
        )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "IDENTITY_EXCLUDES",
    "SELECTION_SCHEMA_VERSION",
    "SELECTION_SCHEMA_VERSION_V2",
    "SelectionError",
    "assert_one_active_per_scope",
    "derive_record_id",
    "derive_record_id_v2",
    "derive_selection_id",
    "derive_selection_id_v2",
    "resolve_selection",
    "resolve_selection_ledger",
    "rollback",
    "scope_key",
    "semantic_identity",
    "semantic_identity_v2",
    "transition",
    "transition_v2",
    "validate_selection",
    "validate_selection_v2",
    "verify_against_publication",
]
