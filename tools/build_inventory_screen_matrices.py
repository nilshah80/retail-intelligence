"""Generate the inventory/replenishment screen parity contract.

`P4-4` tasks 12-16. One structured definition produces ONE document with fourteen
screen sections, so the artifact -> screen -> endpoint mapping cannot disagree
between files -- and so the contract directory does not carry fourteen copies of
identical shell/behavior/approval boilerplate. The shared blocks are stated once
at document level; each screen section carries only what differs: its endpoint,
artifacts, grain, elements and actions.

What a matrix freezes, per the plan:

* the authoritative artifact(s) and the live read endpoint;
* the primary grain;
* per-element status -- live, or an APPROVED unavailable state with its owning
  decision. "Partial screen" is never a reason to remove an element, and an
  unavailable element is never replaced by a fabricated zero;
* action controls: visible, natively disabled, no mutation handler (P4-D9/D11);
* the interval rule for every interval-consuming element (P4-D17).

Approval posture is recorded the same way as the P4-0P amendment: autonomous
authorization under the user's standing instruction, with the per-screen human
visual review still owed. A test asserts the classification cannot silently
become a human sign-off.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREEN_ROOT = REPO_ROOT / "contracts" / "screens"

APPROVAL = {
    "status": "approved_for_implementation",
    "actor": "nilay.shah",
    "approvedAt": "2026-08-01",
    "authorization": (
        "Explicit user instruction to complete Phase 4 autonomously, deciding "
        "without pausing for input and documenting deviations for review."
    ),
    "classification": "autonomous_authorization_not_independent_human_review",
    "reviewOutstanding": (
        "Per-screen human visual review at 1440x1100 and 390x844 remains owed "
        "before Demo 4 sign-off; this authorization does not stand in for it."
    ),
}

UNAVAILABLE = "Not available"

#: One row per destination. `elements` lists the load-bearing KPI/table/panel
#: dispositions; the full HTML shell (filters, buttons, layout) is inherited from
#: the reference page anchor and preserved as-is.
SCREENS: list[dict[str, Any]] = [
    {
        "screenId": "inventoryOverview",
        "title": "Inventory Overview",
        "pageSelector": "#inventoryOverview",
        "endpoint": "/api/v1/inventory/overview",
        "artifacts": ["inventory_positions", "stock_health", "demand_at_risk", "replay_metrics"],
        "grain": "market/location",
        "elements": [
            {"label": "Total Inventory Value", "status": "live", "source": "inventory_valuation gross, market-local; reporting FX for the display strip only"},
            {"label": "Stock Availability", "status": "live", "source": "inventory_positions atp share of active cells"},
            {"label": "Demand at Risk", "status": "live", "source": "demand_at_risk governed available-P90 exposure", "intervalRule": "withheld interval rows are excluded and counted, never zero risk"},
            {"label": "Stock-out SKUs", "status": "live", "source": "stock_health stockout class count"},
            {"label": "Overstock Value", "status": "live", "source": "stock_health overstock exposure, market-local"},
            {"label": "Inventory Turn", "status": "live", "source": "replay_metrics trailing turn"},
            {"label": "Working capital trend chart", "status": "live", "source": "inventory_valuation weekly gross series"},
            {"label": "Inventory Action Center modal", "status": "live", "source": "replenishment_exceptions counts by class"},
        ],
        "actions": ["Inventory Action Center", "Store Drilldown", "Warehouse Drilldown", "Run Inventory Scenario", "Export Inventory Report"],
    },
    {
        "screenId": "storeInventory",
        "title": "Store Inventory",
        "pageSelector": "#storeInventory",
        "endpoint": "/api/v1/inventory/stores",
        "artifacts": ["inventory_positions", "stock_health", "demand_at_risk"],
        "grain": "store x SKU",
        "elements": [
            {"label": "Store position table", "status": "live", "source": "inventory_positions store-grain rows under the active-or-residual rule"},
            {"label": "Availability %", "status": "live", "source": "atp > 0 share of active cells"},
            {"label": "Days of Supply", "status": "live", "source": "position / trailing observed daily demand; insufficient trailing demand renders Not available"},
            {"label": "Lost Sales Exposure", "status": "live", "source": "store stockout events x accepted unit price, market-local"},
            {"label": "Transfer Opportunity", "status": "live", "source": "transfer_recommendations expected benefit for this store"},
            {"label": "Create Store Action", "status": "disabled_action", "decision": "P4-D9 workflow belongs to Phase 6"},
            {"label": "Create Transfer", "status": "disabled_action", "decision": "P4-D9"},
        ],
        "actions": ["Create Store Action", "Create Transfer", "Export"],
    },
    {
        "screenId": "warehouseInventory",
        "title": "Warehouse Inventory",
        "pageSelector": "#warehouseInventory",
        "endpoint": "/api/v1/inventory/warehouses",
        "artifacts": ["inventory_positions", "inventory_valuation", "supplier_planning"],
        "grain": "DC",
        "elements": [
            {"label": "DC position table", "status": "live", "source": "inventory_positions dc rows"},
            {"label": "Utilization %", "status": "live", "source": "on_hand vs warehouse_capacity_snapshots"},
            {"label": "Blocked stock", "status": "live", "source": "damaged + quality_control buckets"},
            {"label": "Delayed receipts", "status": "live", "source": "inbound status events past expected_receipt_date and not received"},
            {"label": "Fill rate", "status": "live", "source": "replay_metrics fill by dc"},
        ],
        "actions": ["Warehouse Export"],
    },
    {
        "screenId": "inventoryAgeing",
        "title": "Inventory Ageing",
        "pageSelector": "#inventoryAgeing",
        "endpoint": "/api/v1/inventory/ageing",
        "artifacts": ["inventory_ageing"],
        "grain": "SKU x location x age bucket",
        "elements": [
            {"label": "Age bucket table", "status": "live", "source": "inventory_ageing deterministic buckets from batch/receipt dates; store rows use oldest_receipt_date"},
            {"label": "De-assorted residual stock rows", "status": "live", "source": "residualOnly cells preserved -- dead stock is the point of this screen"},
            {"label": "Action ladder", "status": "live", "source": "deterministic ladder from inventory-policy/2.0.0 hold/markdown thresholds"},
            {"label": "Non-batch scope note", "status": "live", "source": "reason-coded scope: rows without batch lineage age by receipt evidence"},
        ],
        "actions": ["Ageing Export"],
    },
    {
        "screenId": "inventoryTransfers",
        "title": "Stock Transfers",
        "pageSelector": "#inventoryTransfers",
        "endpoint": "/api/v1/inventory/transfers",
        "artifacts": ["transfer_recommendations"],
        "grain": "lane x SKU",
        "elements": [
            {"label": "Recommendation table", "status": "live", "source": "transfer_recommendations over active typed lanes only"},
            {"label": "Expected benefit", "status": "live", "source": "single market-local currency per row; never summed across markets"},
            {"label": "Historical DC-to-DC movements", "status": "live", "source": "inventory_transfer_events status history"},
            {"label": "Approve / send controls", "status": "disabled_action", "decision": "P4-D11 ERP transmission is shadow_not_sent; no send path exists"},
        ],
        "actions": ["Create Transfer", "Transfer Export"],
    },
    {
        "screenId": "inventoryValuation",
        "title": "Inventory Valuation",
        "pageSelector": "#inventoryValuation",
        "endpoint": "/api/v1/inventory/valuation",
        "artifacts": ["inventory_valuation"],
        "grain": "category/location",
        "elements": [
            {"label": "Gross value", "status": "live", "source": "accepted unit cost x on hand, market-local minor units"},
            {"label": "Store WAC lineage", "status": "live", "source": "store receipt/transfer cost evidence; a lane-imputed DC WAC renders under the explicit derived_lane_wac label or not at all"},
            {"label": "ERP vs WMS variance (DC)", "status": "live", "source": "wms_inventory_comparisons, DC scope only"},
            {"label": "ERP vs WMS variance (store)", "status": "unavailable", "decision": "no reconciled store WMS facts exist on the pin; fabricating parity would be worse than absence"},
            {"label": "NRV", "status": "unavailable", "decision": "P4-D10: no approved markdown/pricing-floor policy"},
            {"label": "Provisions", "status": "unavailable", "decision": "P4-D10"},
        ],
        "actions": ["Valuation Export"],
    },
    {
        "screenId": "expiryWaste",
        "title": "Expiry & Waste",
        "pageSelector": "#expiryWaste",
        "endpoint": "/api/v1/inventory/expiry-waste",
        "artifacts": ["inventory_expiry_waste"],
        "grain": "batch",
        "elements": [
            {"label": "Expiry exposure", "status": "live", "source": "batches with expiry inside the policy window"},
            {"label": "Waste actuals", "status": "live", "source": "waste_events plus store waste, reason-coded"},
            {"label": "Non-expiring SKUs", "status": "not_applicable", "decision": "a SKU without shelf-life rules has no expiry; rendered as not applicable rather than zero risk"},
        ],
        "actions": ["Expiry Export"],
    },
    {
        "screenId": "replenishmentPlanner",
        "title": "Replenishment Planner",
        "pageSelector": "#replenishmentPlanner",
        "endpoint": "/api/v1/replenishment/planner",
        "artifacts": ["replenishment_recommendations", "demand_at_risk"],
        "grain": "SKU -> destination",
        "elements": [
            {"label": "Suggested order table", "status": "live", "source": "replenishment_recommendations with lane, term, MOQ/pack, cover, capacity and budget guards"},
            {"label": "Reorder point / order-up-to", "status": "live", "source": "policy v2 formulas over accepted forecast", "intervalRule": "cold-start H5+ rows skip the interval-dependent output and emit cold_start_interval_unavailable; P50 remains where authorized"},
            {"label": "Budget ceiling meter", "status": "live", "source": "market-local weeklyReplenishmentBudgetMinor"},
            {"label": "Approve orders", "status": "disabled_action", "decision": "P4-D9"},
        ],
        "actions": ["Approve Orders", "Adjust Parameters", "Planner Export"],
    },
    {
        "screenId": "suggestedOrders",
        "title": "Suggested Orders",
        "pageSelector": "#suggestedOrders",
        "endpoint": "/api/v1/replenishment/orders",
        "artifacts": ["replenishment_recommendations"],
        "grain": "order/recommendation",
        "elements": [
            {"label": "Order candidate table", "status": "live", "source": "read-only candidate orders with deterministic ordering"},
            {"label": "ERP status", "status": "live", "source": "constant shadow_not_sent per P4-D11 -- displayed truthfully, not as a fake Sent"},
            {"label": "Send to ERP", "status": "disabled_action", "decision": "P4-D11: no send path exists, including after controls render"},
        ],
        "actions": ["Send to ERP", "Orders Export"],
    },
    {
        "screenId": "supplierPlanning",
        "title": "Supplier Planning",
        "pageSelector": "#supplierPlanning",
        "endpoint": "/api/v1/replenishment/suppliers",
        "artifacts": ["supplier_planning"],
        "grain": "supplier x scope/period",
        "elements": [
            {"label": "Performance table", "status": "live", "source": "supplier_performance lead mean/std, OTD, capacity"},
            {"label": "Origin-safe terms", "status": "live", "source": "supply_terms with sku > dept > category precedence and explicit origin kind"},
            {"label": "Risk classification", "status": "live", "source": "deterministic risk from OTD and lead variability under policy v2"},
            {"label": "Capacity confirmation", "status": "live", "source": "capacity_confirmed_pct vs the frozen supplierCapacityConfirmedPctFloor"},
        ],
        "actions": ["Supplier Export"],
    },
    {
        "screenId": "safetyStock",
        "title": "Safety Stock",
        "pageSelector": "#safetyStock",
        "endpoint": "/api/v1/replenishment/safety-stock",
        "artifacts": ["safety_stock_segments"],
        "grain": "policy segment",
        "elements": [
            {"label": "Segment table", "status": "live", "source": "safety_stock_segments from hard-gated interval and service class"},
            {"label": "Service level by class", "status": "live", "source": "market-local serviceLevelsByClass from policy v2"},
            {"label": "Cold-start H5+ rows", "status": "live", "source": "rendered as manual-judgment/unavailable with the governed exception", "intervalRule": "never zero safety stock, never a collapsed row, never a fake confidence"},
        ],
        "actions": ["Safety Stock Export"],
    },
    {
        "screenId": "allocationFulfillment",
        "title": "Allocation & Fulfillment",
        "pageSelector": "#allocationFulfillment",
        "endpoint": "/api/v1/replenishment/allocations",
        "artifacts": ["allocation_recommendations"],
        "grain": "SKU x store x channel",
        "elements": [
            {"label": "Allocation table", "status": "live", "source": "allocation_recommendations; allocated + residual = node ATP asserted per pool"},
            {"label": "Channel split", "status": "live", "source": "channel rows preserved through replay per P4-D16; no silent aggregation"},
            {"label": "Historical requests/shortfall", "status": "live", "source": "canonical allocations evidence"},
            {"label": "Direct-DC fulfillment", "status": "live", "source": "only rows with an explicit customer_fulfillment lane; otherwise store ATP"},
        ],
        "actions": ["Allocation Export"],
    },
    {
        "screenId": "replenishmentExceptions",
        "title": "Replenishment Exceptions",
        "pageSelector": "#replenishmentExceptions",
        "endpoint": "/api/v1/replenishment/exceptions",
        "artifacts": ["replenishment_exceptions"],
        "grain": "exception",
        "elements": [
            {"label": "Exception table", "status": "live", "source": "deterministic engine-derived rows incl. cold_start_interval_unavailable projections"},
            {"label": "Owner / SLA age / assignment", "status": "unavailable", "decision": "P4-D9: workflow state belongs to Phase 6"},
            {"label": "Resolution history / notes", "status": "unavailable", "decision": "P4-D9"},
            {"label": "Assign / resolve controls", "status": "disabled_action", "decision": "P4-D9: visible, natively disabled, no mutation handler"},
        ],
        "actions": ["Assign", "Resolve", "Exceptions Export"],
    },
    {
        "screenId": "stockHealth",
        "title": "Stock Health",
        "pageSelector": "#stockHealth",
        "endpoint": "/api/v1/inventory/stock-health",
        "artifacts": ["stock_health", "demand_at_risk"],
        "grain": "SKU x store",
        "elements": [
            {"label": "Eight-column triage table", "status": "live", "source": "stock_health over active plus de-assorted residual cells"},
            {"label": "AI vs Control", "status": "out_of_scope", "decision": "P4-D8: belongs to Phase 8 Performance Insights, not this destination"},
            {"label": "Model Performance", "status": "out_of_scope", "decision": "P4-D8"},
        ],
        "actions": ["Stock Health Export"],
    },
]


def build_screen_section(screen: dict[str, Any]) -> dict[str, Any]:
    """Only what differs per screen; the shared blocks live at document level."""

    return {
        "screenId": screen["screenId"],
        "title": screen["title"],
        "pageSelector": screen["pageSelector"],
        "readModel": {
            "endpoint": screen["endpoint"],
            "artifacts": screen["artifacts"],
            "grain": screen["grain"],
        },
        "elements": screen["elements"],
        "actions": screen["actions"],
    }


def build_document() -> dict[str, Any]:
    return {
        "schemaVersion": "retail-screen-contract-set/v1",
        "contractSetId": "inventoryReplenishment",
        "status": "frozen_approved_for_implementation",
        "authority": {
            "html": "docs/ai_retail_intelligence_dashboard_multicurrency_v6.html",
            "specification": "docs/demand_forecast_poc_spec.md",
            "plan": "plans/local/phase4-implementation-plan.md",
            "api": "contracts/api/openapi.yaml",
        },
        "dataMode": "accepted_live_only",
        "activation": {
            "requiredLifecycleStatus": "accepted",
            "verifier": "retail-inventory-verifier/v1",
            "oneBundleForAllScreens": True,
            "note": (
                "P4-D15: one inventory/replenishment bundle owns all 14 read "
                "models. Partial page activation is forbidden; element-level "
                "unavailable is allowed only where a screen section records it."
            ),
        },
        "shell": {
            "inheritFrom": "contracts/screens/data-management.yaml",
            "preserve": (
                "navigation order, labels, filters, KPI/table/control positions "
                "and design tokens from the reference HTML; no redesign, rename, "
                "removal or addition of visible product concepts"
            ),
        },
        "actionBehavior": (
            "visible and natively disabled with aria-disabled; no mutation "
            "endpoint or handler exists (P4-D9/P4-D11)"
        ),
        "behavior": {
            "loading": "Preserve the reviewed shell; show loading in value regions.",
            "error": "Preserve the shell and state that live inventory data is unavailable.",
            "empty": "Show zero only for an exact governed zero under a frozen policy.",
            "unavailable": f"Use the literal text {UNAVAILABLE}; never substitute HTML sample values.",
            "staleness": "409 renders the governed stale state; 503 the governed unavailable state.",
            "intervalRule": (
                "P4-D17: an unavailable interval is skipped with its governed "
                "exception. Null is never coerced to zero safety stock, zero "
                "risk, or a numeric confidence."
            ),
        },
        "viewports": {"desktop": "1440x1100", "mobile": "390x844"},
        "reviewGate": {
            "reactImplementationAuthorized": True,
            "approval": APPROVAL,
        },
        "screens": [build_screen_section(screen) for screen in SCREENS],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if len(SCREENS) != 14:
        raise SystemExit("the destination count is 14; the definition drifted")

    rendered = yaml.safe_dump(
        build_document(), sort_keys=False, width=88, allow_unicode=True
    )
    path = SCREEN_ROOT / "inventory-replenishment.parity.yaml"
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            print(f"matrix set drifted or absent: {path.name}", file=sys.stderr)
            return 1
        print("the 14-screen matrix set matches its derivation")
        return 0
    path.write_text(rendered, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(SCREENS)} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
