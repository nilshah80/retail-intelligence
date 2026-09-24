#!/usr/bin/env python3
"""Read-only verification of the disposable Castrol database and running API.

Run after starting the demo API/UI. This writes evidence only beneath the chosen
output directory; requests execute read-only simulations, never workflow writes.
The existing pricing CSV defect is reported separately from conversion failures.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DSN = os.environ.get("RETAIL_VERIFY_POSTGRES_DSN",
    "postgresql://retail:castrol-demo-local-only@127.0.0.1:55432/retail_intelligence"
)
EXPECTED_CATALOG_SKUS = 268
LEGACY_IDENTITY = re.compile(r"gulf|glf[-_]|demo", re.IGNORECASE)
FORBIDDEN_COMPETITOR = re.compile(r"castrol|gulf|glf[-_]", re.IGNORECASE)
COMPETITOR_KEYS = {
    "competitorid", "competitorname", "competitorbrand", "competitormodel",
    "competitorproducttitle", "competitorproductname", "competitorproductid",
    "competitorurl", "matchedproduct", "compid", "compproductid",
}
METADATA_ROUTES = (
    "/healthz", "/api/v1/fx/rates", "/api/v1/data-management/summary",
    "/api/v1/data-management/dashboard", "/api/v1/data-management/gates",
    "/api/v1/data-management/capabilities", "/api/v1/data-management/reconciliation",
    "/api/v1/data-management/quality-findings",
)
SCENARIO_PRESETS = (
    "expected_demand", "high_demand", "low_demand", "promotion_upside",
    "supply_constrained",
)


def read_routes() -> list[str]:
    """Use the app's route arrays so a new enabled screen cannot be overlooked."""
    routes = list(METADATA_ROUTES)
    for filename, array in (
        ("forecast.go", "forecastPaths"), ("inventory.go", "inventoryPaths"),
        ("pricing.go", "pricingReadPaths"),
    ):
        source = (REPO_ROOT / "api/internal/httpapi" / filename).read_text()
        match = re.search(rf"var {array} = \[\]string\{{(.*?)\n\}}", source, re.S)
        if not match:
            raise RuntimeError(f"Cannot discover routes from {filename}:{array}")
        routes.extend(re.findall(r'"(/api/v1/[^"{}]+)"', match.group(1)))
    return list(dict.fromkeys(routes))


def query(path: str, **values: Any) -> str:
    return path + "?" + urllib.parse.urlencode(values)


def identity_findings(value: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Scan nested values, keys and JSON stored inside text fields.

    Castrol is valid in our own SKU/name fields even on competitor responses;
    only the competing company's identity fields exclude our own brand.
    """
    legacy: list[dict[str, str]] = []
    competitors: list[dict[str, str]] = []

    def walk(node: Any, path: str = "$", depth: int = 0) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}"
                if LEGACY_IDENTITY.search(key_text):
                    legacy.append({"path": child_path, "value": key_text[:240]})
                normalized = re.sub(r"[^a-z]", "", key_text.lower())
                if normalized in COMPETITOR_KEYS and isinstance(child, str):
                    if FORBIDDEN_COMPETITOR.search(child):
                        competitors.append({"path": child_path, "value": child[:240]})
                walk(child, child_path, depth)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]", depth)
        elif isinstance(node, str):
            if LEGACY_IDENTITY.search(node):
                legacy.append({"path": path, "value": node[:240]})
            stripped = node.lstrip()
            if depth < 3 and stripped.startswith(("{", "[")):
                try:
                    embedded = json.loads(node)
                except (ValueError, TypeError):
                    return
                walk(embedded, path + "(embeddedJSON)", depth + 1)

    walk(value)
    return legacy, competitors


def fetch(base: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/json", **(
            {"Content-Type": "application/json"} if body is not None else {}
        )},
        method="POST" if body is not None else "GET",
    )
    try:
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            status = int(response.status)
            headers = dict(response.headers.items())
        text = raw.decode("utf-8-sig", "replace")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
        return {
            "status": status, "headers": headers, "payload": payload,
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "seconds": round(time.monotonic() - started, 3),
        }
    except (OSError, urllib.error.URLError) as error:
        return {"status": None, "payload": None, "error": str(error),
                "seconds": round(time.monotonic() - started, 3)}


class Verification:
    def __init__(self, base: str, output: Path) -> None:
        self.base, self.output = base.rstrip("/"), output
        self.checks: list[dict[str, Any]] = []
        self.payloads: dict[str, Any] = {}
        self.database_target: dict[str, Any] | None = None
        self.output.mkdir(parents=True, exist_ok=True)

    def assertion(self, name: str, passed: bool, **evidence: Any) -> None:
        self.checks.append({"name": name, "passed": bool(passed), **evidence})

    def check_response(
        self, name: str, path: str, response: dict[str, Any], *,
        expected: int = 200, mode: str | None = None, known_pricing_export: bool = False,
    ) -> Any:
        payload = response.get("payload")
        legacy, competitors = identity_findings(payload)
        reasons = []
        known = (
            known_pricing_export and response["status"] == 503
            and isinstance(payload, dict) and payload.get("reasonCode") == "PRICING_READ_FAILED"
            and payload.get("message") == "Export rows could not be read."
        )
        if response["status"] != expected:
            reasons.append(f"Expected HTTP {expected}, received {response['status']}")
        if mode and (not isinstance(payload, dict) or payload.get("dataMode") != mode):
            reasons.append(f"Expected dataMode={mode}")
        if legacy:
            reasons.append(f"Found {len(legacy)} legacy identity value(s)")
        if competitors:
            reasons.append(f"Found {len(competitors)} excluded competitor identity value(s)")
        if response.get("error"):
            reasons.append(response["error"])
        entry = {
            "name": name, "path": path, "status": response["status"],
            "expectedStatus": expected, "passed": not reasons,
            "classification": "known_baseline_issue" if known and not legacy and not competitors
                              else "failure" if reasons else "passed",
            "seconds": response["seconds"], "bytes": response.get("bytes"),
            "sha256": response.get("sha256"), "findings": reasons,
            "legacyIdentityCount": len(legacy), "competitorIdentityCount": len(competitors),
        }
        if legacy:
            entry["legacyExamples"] = legacy[:10]
        if competitors:
            entry["competitorExamples"] = competitors[:10]
        if isinstance(payload, dict):
            for key in ("dataMode", "reasonCode", "message"):
                if key in payload:
                    entry[key] = payload[key]
            if isinstance(payload.get("items"), list):
                entry["itemCount"] = len(payload["items"])
        self.checks.append(entry)
        return payload

    def request(self, name: str, path: str, body: dict[str, Any] | None = None,
                **options: Any) -> Any:
        return self.check_response(name, path, fetch(self.base, path, body), **options)

    def save(self) -> dict[str, Any]:
        known = [c for c in self.checks if c.get("classification") == "known_baseline_issue"]
        failures = [c for c in self.checks if not c["passed"] and c not in known]
        report = {
            "schemaVersion": "castrol-disposable-demo-verification/v1",
            "checkedAt": datetime.now(timezone.utc).isoformat(), "baseUrl": self.base,
            "databaseTarget": self.database_target,
            "checks": self.checks, "totalChecks": len(self.checks),
            "passedChecks": sum(c["passed"] for c in self.checks),
            "passed": not failures, "allChecksPassed": not failures and not known,
            "failedChecks": failures, "knownBaselineIssues": known,
            "limitations": [
                "Browser rendering must be verified separately.",
                "This verifies served payloads and full competitor/pricing pagination; "
                "it is not an exhaustive scan of every historical database row.",
            ],
        }
        (self.output / "api-verification.json").write_text(json.dumps(report, indent=2) + "\n")
        (self.output / "api-baseline-payloads.json").write_text(
            json.dumps(self.payloads, indent=2) + "\n"
        )
        return report

    def all_pages(self, path: str, label: str) -> None:
        offset, total, pages, seen = 0, None, 0, 0
        while total is None or offset < total:
            request_path = query(path, offset=offset, limit=200)
            payload = self.request(f"{label} page {pages + 1}", request_path, mode="live")
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                self.assertion(f"{label} complete population scanned", False,
                               detail="Pagination response has no items")
                return
            pagination = payload.get("pagination") or {}
            current_total = pagination.get("total")
            if not isinstance(current_total, int) or current_total < 0:
                self.assertion(f"{label} complete population scanned", False,
                               detail="Pagination response has no valid total")
                return
            if total is not None and total != current_total:
                self.assertion(f"{label} stable population", False,
                               before=total, after=current_total)
            total = current_total
            received = len(payload["items"])
            pages += 1
            seen += received
            if received == 0:
                break
            offset += received
            if pages > 1000:
                break
        self.assertion(f"{label} complete population scanned", seen == total and bool(total),
                       received=seen, expected=total, pages=pages)


def check_workflows(v: Verification) -> None:
    recommendations = v.payloads.get("/api/v1/pricing/recommendations", {})
    items = recommendations.get("items", []) if isinstance(recommendations, dict) else []
    candidate = next((row for row in items if row.get("recordKind") == "recommendation"
                      and row.get("proposedPriceMinor") is not None), None)
    if candidate is None:
        selectable = v.request("Find selectable price recommendation", query(
            "/api/v1/pricing/recommendations", recordKind="recommendation", limit=200
        ), mode="live")
        if isinstance(selectable, dict):
            candidate = next((row for row in selectable.get("items", [])
                              if row.get("proposedPriceMinor") is not None), None)
            recommendations = selectable
    v.assertion("Price simulation has a recommendation", candidate is not None)
    if candidate:
        identifier = candidate["recommendationId"]
        activation = recommendations["authority"]["activationSetId"]
        v.request("Pricing recommendation detail", "/api/v1/pricing/recommendations/" +
                  urllib.parse.quote(identifier, safe=""), mode="live")
        filtered = v.request("Pricing product/store filter", query(
            "/api/v1/pricing/recommendations", search=candidate["productName"],
            storeId=candidate["storeId"], category=candidate["category"], limit=5,
        ), mode="live")
        v.assertion("Pricing filter retains mapped product", isinstance(filtered, dict)
                    and bool(filtered.get("items")) and all(
                        row.get("storeId") == candidate["storeId"]
                        and row.get("category") == candidate["category"]
                        for row in filtered.get("items", [])
                    ))
        v.request("Pricing simulation", "/api/v1/pricing/simulations:run", {
            "recommendationId": identifier, "proposedPriceMinor": candidate["proposedPriceMinor"],
            "simulationPeriod": "Next 4 Weeks", "demandAssumption": "Expected",
            "inventoryObjective": "Margin Protection", "expectedActivationSetId": activation,
        })
        export_path = query(
            "/api/v1/pricing/export", scope="selected", format="csv", includeExplanation="yes",
            filename="castrol-pricing-verification", expectedCount=1,
            expectedActivationSetId=activation, ids=identifier,
        )
        pricing_export = v.request("Pricing CSV export (known baseline SQL defect)", export_path,
                                   known_pricing_export=True)
        if isinstance(pricing_export, str):
            (v.output / "pricing-export.csv").write_text(pricing_export)

    competitor_payload = v.payloads.get("/api/v1/competitors/matches", {})
    competitor_items = competitor_payload.get("items", []) if isinstance(competitor_payload, dict) else []
    v.assertion("Competitor population is populated", bool(competitor_items))
    if competitor_items:
        match_id = competitor_items[0]["matchId"]
        v.request("Competitor match detail", "/api/v1/competitors/matches/" +
                  urllib.parse.quote(match_id, safe=""), mode="live")
    v.all_pages("/api/v1/competitors/matches", "Competitor identities")
    v.all_pages("/api/v1/pricing/recommendations", "Pricing identities")
    v.save()

    versions = v.payloads.get("/api/v1/forecast/versions", {})
    version = versions.get("versionId") if isinstance(versions, dict) else None
    if not version:
        summary = v.payloads.get("/api/v1/forecast/summary", {})
        version = summary.get("versionId") if isinstance(summary, dict) else None
    v.assertion("Forecast scenario has an active version", bool(version))
    if version:
        context = v.request("Forecast scenario context", query(
            "/api/v1/forecast/scenario/context", expectedForecastVersion=version,
        ))
        if isinstance(context, dict) and context.get("scenarioContextVersion"):
            authority = {key: context[key] for key in
                         ("forecastVersion", "scenarioContextVersion", "inventory")}
            for preset in SCENARIO_PRESETS:
                result = v.request(f"Forecast scenario {preset}", "/api/v1/forecast/scenario", {
                    "presetId": preset, "userOverrides": {},
                    "businessScope": {"marketId": "", "storeId": "", "channelId": "",
                                      "category": "", "horizonWeeks": 4},
                    "expectedAuthority": authority,
                }, mode="assumption_projection")
                if isinstance(result, dict) and "calculation" in result:
                    calculation = result["calculation"]
                    v.assertion(f"Scenario {preset} carries expected authority",
                                result.get("authority") == authority and result.get("presetId") == preset,
                                demandUnits=calculation.get("demandUnits"))
                v.save()

    workbench = v.request("Forecast workbench", query(
        "/api/v1/forecast/series", view="workbench", limit=5,
    ), mode="live")
    rows = workbench.get("items", []) if isinstance(workbench, dict) else []
    v.assertion("Forecast workbench contains mapped products", bool(rows) and all(
        "castrol" in row.get("productName", "").lower() for row in rows
    ))
    if rows:
        row = rows[0]
        filtered = v.request("Forecast mapped product/store filter", query(
            "/api/v1/forecast/series", view="workbench", search=row["productName"],
            storeId=row["storeId"], category=row["category"], limit=5,
        ), mode="live")
        v.assertion("Forecast filter retains mapped product", isinstance(filtered, dict)
                    and bool(filtered.get("items")) and all(
                        item.get("storeId") == row["storeId"]
                        and item.get("category") == row["category"]
                        for item in filtered.get("items", [])
                    ))
        export_path = "/api/v1/direct-exports/exportForecastBtn"
        params = {"scope": "selected_visible", "expectedCount": 1,
                  "currency": "INR", "ids": row["rowId"]}
        metadata = v.request("Forecast CSV metadata", query(export_path, **params, metadata="true"))
        if isinstance(metadata, dict) and metadata.get("scopeRevision"):
            csv_response = fetch(v.base, query(export_path, **params,
                                                scopeRevision=metadata["scopeRevision"]))
            exported = v.check_response("Forecast CSV export", export_path, csv_response)
            if isinstance(exported, str):
                exported_rows = list(csv.DictReader(io.StringIO(exported)))
                v.assertion("Forecast CSV contains one mapped product", len(exported_rows) == 1
                            and "castrol" in exported.lower(), csvRows=len(exported_rows))
                (v.output / "forecast-export.csv").write_text(exported)
    v.request("Promotion simulation is intentionally unavailable",
              "/api/v1/promotions/simulations:run", {}, expected=422, mode="unavailable")


def _database_python() -> Path:
    python = REPO_ROOT / "db/.venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        python = Path(sys.executable)
    return python


def expected_database_target() -> dict[str, Any]:
    """Allow explicit local snapshot restores without changing conversion guards."""
    from psycopg.conninfo import conninfo_to_dict
    info = conninfo_to_dict(DEFAULT_DSN)
    host = info.get("host", "")
    if host not in ("127.0.0.1", "localhost", "::1") or info.get("dbname") != "retail_intelligence":
        raise ValueError("Verification requires a local retail_intelligence database")
    return {"host": host, "port": int(info.get("port", 5432)), "database": info["dbname"]}


def database_snapshot() -> dict[str, Any]:
    """Read the selected local database; require its Castrol conversion marker."""
    import psycopg
    from psycopg.rows import dict_row

    expected_database_target()
    with psycopg.connect(
        DEFAULT_DSN, row_factory=dict_row, connect_timeout=10,
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
        application_name="castrol-demo-verification",
    ) as conn:
        adaptation = conn.execute(
            "SELECT report->'passed' AS passed,report->'retainedSkuCount' AS retained_sku_count,"
            "report->>'createdAt' AS created_at,report->>'sourceRunId' AS source_run_id "
            "FROM castrol_demo.adaptation WHERE singleton"
        ).fetchone()
        forecast = conn.execute(
            "SELECT forecast_run_id,version_id,activation_scope_fingerprint,markets "
            "FROM retail_serving.active_forecast_versions"
        ).fetchall()
        inventory = conn.execute(
            "SELECT inventory_run_id,inventory_version_id,markets FROM retail_serving.active_inventory_versions"
        ).fetchall()
        pricing = conn.execute(
            "SELECT activation_set_id,bundle_id,semantic_fingerprint,source_run_id "
            "FROM retail_serving.active_pricing_bundles"
        ).fetchall()
        if len(forecast) != 1 or len(inventory) != 1 or len(pricing) != 1:
            raise ValueError("The disposable database must have one active forecast, inventory and pricing authority")
        forecast, inventory, pricing = forecast[0], inventory[0], pricing[0]
        products = conn.execute(
            "SELECT DISTINCT sku_id,product_name FROM retail_serving.forecast_series_dimensions "
            "WHERE version_id=%s ORDER BY sku_id", (forecast["version_id"],),
        ).fetchall()
        counts = conn.execute(
            "SELECT count(*) AS total,count(*) FILTER(WHERE record_kind='recommendation') AS recommendations,"
            "count(*) FILTER(WHERE record_kind='withheld_assessment') AS withheld,"
            "count(*) FILTER(WHERE record_kind='recommendation' AND action='Increase') AS increase,"
            "count(*) FILTER(WHERE record_kind='recommendation' AND action='Decrease') AS decrease,"
            "count(*) FILTER(WHERE record_kind='recommendation' AND action='Hold') AS hold "
            "FROM retail_serving.price_recommendations WHERE bundle_id=%s", (pricing["bundle_id"],),
        ).fetchone()
        counts["acceptedResponses"] = conn.execute(
            "SELECT count(*) AS n FROM retail_serving.pricing_response_assessments "
            "WHERE bundle_id=%s AND disposition='accepted'", (pricing["bundle_id"],),
        ).fetchone()["n"]
        competitor = conn.execute(
            "SELECT count(*) AS matches,count(DISTINCT c.sku_id) AS products "
            "FROM retail_serving.pricing_competitor_assessments c WHERE c.bundle_id=%s "
            "AND EXISTS(SELECT 1 FROM retail_serving.price_recommendations r "
            "WHERE r.bundle_id=c.bundle_id AND r.market_id=c.market_id AND r.sku_id=c.sku_id)",
            (pricing["bundle_id"],),
        ).fetchone()
        forecast["seriesCount"] = conn.execute(
            "SELECT count(*) AS n FROM retail_serving.forecast_series WHERE version_id=%s AND horizon_week=1",
            (forecast["version_id"],),
        ).fetchone()["n"]
        return {
            "expectedTarget": expected_database_target(),
            "target": {"host": conn.info.host, "port": conn.info.port,
                       "database": conn.execute("SELECT current_database() AS name").fetchone()["name"]},
            "adaptation": adaptation, "forecast": forecast, "inventory": inventory,
            "pricingAuthority": pricing, "pricingCounts": counts,
            "competitorCounts": competitor, "products": products,
        }


def check_database_binding(v: Verification) -> None:
    result = subprocess.run(
        [str(_database_python()), str(Path(__file__).resolve()), "--database-snapshot"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False,
    )
    if result.returncode:
        v.assertion("Selected Castrol database instance can be verified", False,
                    detail=(result.stderr or result.stdout).replace(DEFAULT_DSN, "[redacted DSN]")[-4000:])
        return
    snapshot = json.loads(result.stdout)
    v.database_target = snapshot["target"]
    (v.output / "database-instance-verification.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    v.assertion("Database probe reached the selected local target",
                v.database_target == snapshot["expectedTarget"],
                observed=v.database_target)
    marker = snapshot.get("adaptation") or {}
    v.assertion("Disposable database has a completed Castrol conversion",
                marker.get("passed") is True and marker.get("retained_sku_count") == EXPECTED_CATALOG_SKUS,
                adaptation=marker)
    products = {row["sku_id"]: row["product_name"] for row in snapshot["products"]}
    v.assertion("Database contains the expected mapped Castrol catalog",
                len(products) == EXPECTED_CATALOG_SKUS and all(
                    sku.startswith("castrol-india:") and name.startswith("Castrol ")
                    for sku, name in products.items()),
                observedSkus=len(products), expectedSkus=EXPECTED_CATALOG_SKUS)

    def payload(path: str) -> dict[str, Any]:
        value = v.payloads.get(path)
        return value if isinstance(value, dict) else {}

    def equal(name: str, observed: Any, expected: Any) -> None:
        v.assertion(name, observed == expected, observed=observed, expected=expected)

    dashboard = payload("/api/v1/data-management/dashboard")
    footer = dashboard.get("footer") or {}
    equal("API catalog total matches the disposable database", footer.get("totalSkus"), len(products))
    equal("API active catalog matches the disposable database", footer.get("activeSkus"), len(products))
    api_markets = sorted(row.get("marketId", "") for row in (dashboard.get("filters") or {}).get("markets", []))
    expected_markets = sorted(snapshot["forecast"]["markets"])
    equal("API market IDs match the disposable database", api_markets, expected_markets)
    equal("Disposable database uses the Castrol market", expected_markets, ["castrol-india"])

    forecast = payload("/api/v1/forecast/summary")
    for api_key, db_key in (("forecastRunId", "forecast_run_id"), ("versionId", "version_id"),
                            ("activationScopeFingerprint", "activation_scope_fingerprint"), ("markets", "markets")):
        equal(f"Forecast API {api_key} matches the disposable database", forecast.get(api_key), snapshot["forecast"][db_key])
    forecast_items = forecast.get("items") or [{}]
    equal("Forecast API series population matches the disposable database",
          forecast_items[0].get("seriesCount"), snapshot["forecast"]["seriesCount"])
    inventory = payload("/api/v1/inventory/versions")
    for api_key, db_key in (("inventoryRunId", "inventory_run_id"), ("inventoryVersionId", "inventory_version_id"), ("markets", "markets")):
        equal(f"Inventory API {api_key} matches the disposable database", inventory.get(api_key), snapshot["inventory"][db_key])

    recommendations = payload("/api/v1/pricing/recommendations")
    authority = recommendations.get("authority") or {}
    for api_key, db_key in (("activationSetId", "activation_set_id"), ("bundleId", "bundle_id"),
                            ("bundleSemanticFingerprint", "semantic_fingerprint"), ("sourceRunId", "source_run_id")):
        equal(f"Pricing API {api_key} matches the disposable database", authority.get(api_key), snapshot["pricingAuthority"][db_key])
    counts = snapshot["pricingCounts"]
    equal("Pricing API population matches the disposable database", (recommendations.get("pagination") or {}).get("total"), counts["total"])
    own_items = recommendations.get("items") or []
    v.assertion("Pricing API product identities match the disposable catalog", bool(own_items) and all(
        row.get("productName") == products.get(row.get("skuId"))
        and row.get("marketId") == "castrol-india" for row in own_items))
    summary = payload("/api/v1/pricing/recommendations/summary")
    equal("Pricing API open recommendations match the disposable database", (summary.get("kpis") or {}).get("openRecommendations"), counts["recommendations"])
    mixes = {row["label"]: row.get("count") for row in summary.get("recommendationMix", [])}
    for label, key in (("Increase price", "increase"), ("Reduce price", "decrease"), ("Hold price", "hold"), ("Manual review", "withheld")):
        equal(f"Pricing API {label} count matches the disposable database", mixes.get(label), counts[key])
    equal("Pricing API accepted response capability matches the disposable database",
          ((summary.get("capabilities") or {}).get("priceResponse") or {}).get("acceptedRows"), counts["acceptedResponses"])
    rival_counts = snapshot["competitorCounts"]
    equal("Competitor API match population matches the disposable database",
          (payload("/api/v1/competitors/matches").get("pagination") or {}).get("total"), rival_counts["matches"])
    equal("Competitor API monitored products match the disposable database",
          (payload("/api/v1/competitors/summary").get("kpis") or {}).get("productsMonitored"), rival_counts["products"])


def check_database_authority(v: Verification) -> None:
    dsn = DEFAULT_DSN
    python = _database_python()
    evidence = v.output / "inventory-authority-verification.json"
    result = subprocess.run(
        [str(python), str(REPO_ROOT / "tools/inventory_api_smoke.py"),
         "--base-url", v.base, "--postgres-dsn", dsn, "--evidence", str(evidence)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False,
    )
    detail: dict[str, Any] = {"returnCode": result.returncode}
    if result.returncode == 0:
        record = json.loads(result.stdout)
        legacy, competitors = identity_findings(record)
        v.assertion("All fifteen inventory routes match isolated database authority",
                    record.get("state") == "live" and not legacy and not competitors,
                    routeCount=record.get("routeCount"), **detail)
    else:
        v.assertion("All fifteen inventory routes match isolated database authority", False,
                    detail=(result.stderr or result.stdout).replace(dsn, "[redacted DSN]")[-4000:],
                    **detail)


def main() -> int:
    global DEFAULT_DSN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--postgres-dsn", default=DEFAULT_DSN,
                        help="Local restored Castrol database; defaults to the isolated conversion instance")
    parser.add_argument("--database-snapshot", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / ".serve-runtime/castrol-demo/validation")
    args = parser.parse_args()
    DEFAULT_DSN = args.postgres_dsn
    os.environ["RETAIL_VERIFY_POSTGRES_DSN"] = DEFAULT_DSN
    if args.database_snapshot:
        print(json.dumps(database_snapshot()))
        return 0
    verifier = Verification(args.base_url, args.output)
    try:
        routes = read_routes()
        live_prefixes = ("/api/v1/forecast/", "/api/v1/inventory/", "/api/v1/replenishment/",
                         "/api/v1/pricing/", "/api/v1/competitors/", "/api/v1/promotions/",
                         "/api/v1/executive/")
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = pool.map(lambda path: fetch(verifier.base, path), routes)
            for path, response in zip(routes, responses):
                mode = "live" if path.startswith(live_prefixes) or path in (
                    "/api/v1/data-management/summary", "/api/v1/data-management/dashboard",
                    "/api/v1/fx/rates",
                ) else None
                verifier.payloads[path] = verifier.check_response(path, path, response, mode=mode)
        print(f"Checked {len(routes)} read routes", flush=True)
        dashboard = verifier.payloads.get("/api/v1/data-management/dashboard", {})
        markets = dashboard.get("filters", {}).get("markets", []) if isinstance(dashboard, dict) else []
        verifier.assertion("Castrol India is the demo market", bool(markets) and all(
            "castrol" in market.get("name", "").lower() for market in markets
        ), markets=markets)
        verifier.save()
        check_database_binding(verifier)
        verifier.save()
        check_workflows(verifier)
        check_database_authority(verifier)
    except Exception as error:  # Preserve findings even when a prerequisite is broken.
        verifier.assertion("Verifier completed every phase", False,
                           detail=f"{type(error).__name__}: {error}".replace(DEFAULT_DSN, "[redacted DSN]"))
    report = verifier.save()
    print(json.dumps({
        "passed": report["passed"], "passedChecks": report["passedChecks"],
        "totalChecks": report["totalChecks"], "failedChecks": len(report["failedChecks"]),
        "knownBaselineIssues": len(report["knownBaselineIssues"]),
        "report": str(args.output / "api-verification.json"),
    }, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
