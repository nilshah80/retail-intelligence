#!/usr/bin/env python3
"""API smoke evidence for the fifteen inventory routes (P4-8 task 14).

The evidence has to be *bound*, not merely collected. A record saying "all
fifteen routes returned 200" proves the server is up and nothing else -- it does
not say which bundle answered, and a stale activation serving old rows would pass
that check exactly as cleanly as a correct one.

So every response's envelope is compared against the identity PostgreSQL
currently holds in `active_inventory_versions`. The database is the authority for
what is active; the API is the thing being tested. Reading the expected identity
out of the API's own response and then checking the response against it would
prove only internal consistency.

Two run modes and both are legitimate evidence:

* nothing activated -> every route must return the governed 503 with no identity
  leaked in the body. That is the accepted-but-inactive state the plan requires,
  and it is worth recording as evidence rather than as an error;
* a bundle activated -> every route must return 200 with an envelope naming the
  active run, version, fingerprint, consumed forecast and policy version.

The one thing this refuses to write is a mixed result. Some routes serving and
others 503 means the fifteen do not share one authority, and a partial pass would
hide which screens are trustworthy.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))

#: The fifteen routes, in the order api/internal/httpapi/inventory.go declares
#: them. `versions` first because it is the lineage endpoint the other fourteen
#: screens are checked against.
ROUTES = (
    "/api/v1/inventory/versions",
    "/api/v1/inventory/overview",
    "/api/v1/inventory/stores",
    "/api/v1/inventory/warehouses",
    "/api/v1/inventory/ageing",
    "/api/v1/inventory/transfers",
    "/api/v1/inventory/valuation",
    "/api/v1/inventory/expiry-waste",
    "/api/v1/inventory/stock-health",
    "/api/v1/replenishment/planner",
    "/api/v1/replenishment/orders",
    "/api/v1/replenishment/suppliers",
    "/api/v1/replenishment/safety-stock",
    "/api/v1/replenishment/allocations",
    "/api/v1/replenishment/exceptions",
)

#: Fields that must never appear in an unavailable body. A 503 that leaks the run
#: id it could not serve tells a caller a version exists and is being withheld,
#: which is a different fact from "no version is active".
IDENTITY_FIELDS = (
    "inventoryRunId",
    "inventoryVersionId",
    "semanticFingerprint",
    "items",
)


class SmokeError(RuntimeError):
    """The API's answers cannot be bound to an authority."""


def _fetch(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read() or b"{}"
        try:
            return int(error.code), json.loads(body)
        except json.JSONDecodeError:
            return int(error.code), {"_raw": body.decode("utf-8", "replace")[:400]}
    except urllib.error.URLError as error:
        raise SmokeError(
            f"cannot reach {path}: {error.reason}. Start the API first."
        ) from error


def active_identity(dsn: str) -> dict[str, Any] | None:
    """What PostgreSQL says is active, or None. The authority for this check."""

    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT inventory_version_id, inventory_run_id,
                       run_semantic_fingerprint, source_selection_id,
                       forecast_run_id, forecast_version_id, policy_version,
                       markets
                FROM retail_serving.active_inventory_versions
                """
            )
            rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise SmokeError(
            f"{len(rows)} rows in active_inventory_versions; P4-D15 allows one"
        )
    row = rows[0]
    return {
        "inventoryVersionId": str(row[0]),
        "inventoryRunId": str(row[1]),
        "semanticFingerprint": str(row[2]),
        "sourceSelectionId": str(row[3]),
        "forecastAuthority": {
            "forecastRunId": str(row[4]),
            "forecastVersionId": str(row[5]),
        },
        "policyVersion": str(row[6]),
        "markets": sorted(str(market) for market in row[7]),
    }


def smoke(base_url: str, dsn: str) -> dict[str, Any]:
    expected = active_identity(dsn)
    results: list[dict[str, Any]] = []
    findings: list[str] = []

    for path in ROUTES:
        status, body = _fetch(base_url, path)
        entry: dict[str, Any] = {"path": path, "status": status}
        if expected is None:
            if status != 503:
                findings.append(
                    f"{path}: no bundle is active, so the governed status is 503, "
                    f"not {status}"
                )
            leaked = [field for field in IDENTITY_FIELDS if body.get(field)]
            if leaked:
                findings.append(
                    f"{path}: unavailable body leaks {leaked}; 'withheld' and "
                    "'absent' are different facts and only one is true"
                )
            entry["reasonCode"] = body.get("reasonCode")
        else:
            if status != 200:
                findings.append(
                    f"{path}: a bundle is active but the route returned {status}"
                )
            else:
                for field in (
                    "inventoryRunId",
                    "inventoryVersionId",
                    "semanticFingerprint",
                    "policyVersion",
                ):
                    if body.get(field) != expected[field]:
                        findings.append(
                            f"{path}: {field} is {body.get(field)!r}, but the "
                            f"active version is {expected[field]!r}"
                        )
                if body.get("forecastAuthority") != expected["forecastAuthority"]:
                    findings.append(
                        f"{path}: forecastAuthority does not name the forecast the "
                        "active version consumed"
                    )
                if body.get("dataMode") != "live":
                    findings.append(
                        f"{path}: dataMode is {body.get('dataMode')!r}; a served "
                        "row that is not marked live is a row nobody can place"
                    )
                entry["rows"] = len(body.get("items") or [])
                entry["markets"] = body.get("markets")
        results.append(entry)

    statuses = {entry["status"] for entry in results}
    if len(statuses) > 1:
        findings.append(
            f"the fifteen routes returned mixed statuses {sorted(statuses)}; they "
            "share one authority, so they cannot disagree about whether it exists"
        )
    if findings:
        raise SmokeError(
            "inventory API smoke failed:\n  - " + "\n  - ".join(findings)
        )
    return {
        "schemaVersion": "retail-inventory-api-smoke/v1",
        "baseUrl": base_url,
        "state": "unavailable_no_active_bundle" if expected is None else "live",
        "activeIdentity": expected,
        "routes": results,
        "routeCount": len(results),
        "checked": (
            [
                "governedStatusIs503",
                "noIdentityLeakedInUnavailableBody",
                "allFifteenAgree",
            ]
            if expected is None
            else [
                "statusIs200",
                "envelopeMatchesPostgresActiveIdentity",
                "forecastAuthorityMatchesConsumedForecast",
                "dataModeIsLive",
                "allFifteenAgree",
            ]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--postgres-dsn", required=True)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="write the evidence record here as well as to stdout",
    )
    args = parser.parse_args(argv)

    try:
        record = smoke(args.base_url, args.postgres_dsn)
    except SmokeError as error:
        print(str(error), file=sys.stderr)
        return 1
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.evidence is not None:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
