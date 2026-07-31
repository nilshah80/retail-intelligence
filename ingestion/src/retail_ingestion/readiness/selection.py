"""PP3-A7 retailer/tenant publication selection and lifecycle.

Replaces "discover the committed demo pin" with an explicit, immutable selection
per retailer x tenant x capability x environment. There is no `latest`
resolution: a runtime command names a selection, and every mismatch fails closed
rather than degrading serving quietly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

SELECTION_SCHEMA_VERSION: Final[str] = "retail-publication-selection/v1"

#: Audit metadata and derived ids are excluded from semantic identity, so
#: re-approving the same publication cannot mint a different selection.
IDENTITY_EXCLUDES: Final[frozenset[str]] = frozenset(
    {"approval", "selectionId", "semanticIdentityExcludes", "lifecycle"}
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

    if selection.get("schemaVersion") != SELECTION_SCHEMA_VERSION:
        raise SelectionError(
            f"unsupported selection schema {selection.get('schemaVersion')!r}"
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

    publication = Path(repository_root) / selection["publication"]["logicalPath"]
    if not publication.exists():
        raise SelectionError(
            f"selected publication has moved or is absent: {publication}"
        )
    return selection


def verify_against_publication(
    selection: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    """Confirm the selected publication is byte-for-byte the one approved."""

    declared = selection["publication"]
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
    "SelectionError",
    "assert_one_active_per_scope",
    "derive_record_id",
    "derive_selection_id",
    "resolve_selection",
    "rollback",
    "scope_key",
    "semantic_identity",
    "transition",
    "validate_selection",
    "verify_against_publication",
]
