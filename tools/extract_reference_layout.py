#!/usr/bin/env python3
"""Derive the fourteen inventory screen layouts FROM the reference document.

This exists because I got it wrong by hand. The Phase 4 screens were built from
the parity contract's element list, which says what values a screen shows, while
the reference document says how the screen is built -- and the two are not
interchangeable. The result was one generic auto-derived table per destination
against a reference carrying KPI grids, cards, colour-coded badges, per-screen
filters and specific column orders. Worse, the action labels I had written into
the parity contract were invented: the reference gives Stock Health
"Assign Owner" and "Create Action", and the contract claimed
"Stock Health Export".

So the reference stops being something a person reads and becomes something a
generator extracts. `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`
is the source of truth for structure; this emits it as TypeScript the screens
render from, and `--check` fails when the two diverge. A label can no longer drift
by being retyped, because nothing retypes it.

What is extracted is structure only -- button labels, filter options, KPI captions
and table column headers, in document order. The reference's hard-coded VALUES are
deliberately not extracted: every number on the built screens comes from the live
API, and lifting the reference's illustrative figures into generated code would
put sample data one import away from a screen.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = (
    REPO_ROOT / "docs" / "ai_retail_intelligence_dashboard_multicurrency_v6.html"
)
OUTPUT = REPO_ROOT / "ui" / "src" / "generated" / "inventoryScreenLayout.ts"

#: Document order, which is also navigation order. Asserted rather than derived so
#: a section silently disappearing from the reference fails instead of shrinking
#: the generated file.
SCREEN_IDS = (
    "inventoryOverview",
    "storeInventory",
    "warehouseInventory",
    "inventoryAgeing",
    "inventoryTransfers",
    "inventoryValuation",
    "expiryWaste",
    "stockHealth",
    "replenishmentPlanner",
    "suggestedOrders",
    "supplierPlanning",
    "safetyStock",
    "allocationFulfillment",
    "replenishmentExceptions",
)


class ExtractionError(RuntimeError):
    """The reference document does not have the shape this extractor requires."""


def _page_block(document: str, screen_id: str) -> str:
    """The balanced <div class="page" id="..."> ... </div> for one screen.

    Balanced rather than "up to the next page div": the last section would
    otherwise swallow every modal and script that follows it, which is exactly
    what happened when this was first extracted by slicing -- Stock Health came
    out at 107KB instead of 1.1KB.
    """

    marker = f'id="{screen_id}"'
    if marker not in document:
        raise ExtractionError(f"the reference has no section {screen_id!r}")
    start = document.rindex('<div class="page"', 0, document.index(marker))
    depth = 0
    cursor = start
    pattern = re.compile(r"<div\b|</div>")
    while match := pattern.search(document, cursor):
        depth += 1 if match.group(0) == "<div" else -1
        cursor = match.end()
        if depth == 0:
            return document[start:cursor]
    raise ExtractionError(f"{screen_id}: page div is never closed")


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _extract(block: str, screen_id: str) -> dict[str, Any]:
    # Buttons carry the approved action labels. An <input> inside a header cell is
    # a select-all checkbox in the reference; it is not an action.
    actions = [
        _strip_tags(label)
        for label in re.findall(r"<button[^>]*>(.*?)</button>", block, re.S)
        if _strip_tags(label)
    ]
    filters = [
        [option.strip() for option in re.findall(r"<option>(.*?)</option>", select)]
        for select in re.findall(r'<select class="filter">(.*?)</select>', block, re.S)
    ]
    kpis = [
        _strip_tags(caption)
        for caption in re.findall(r"<small>(.*?)</small>", block, re.S)
    ]
    tables: list[dict[str, Any]] = []
    # Card headings and tables are paired by position: a table inside a card that
    # has a card-head belongs to that heading, and a bare card table has none.
    for card in re.findall(r'<div class="card">(.*?)(?=<div class="card">|\Z)', block, re.S):
        heading_match = re.search(r"<h3>(.*?)</h3>", card, re.S)
        for thead in re.findall(r"<thead><tr>(.*?)</tr></thead>", card, re.S):
            columns = [
                _strip_tags(cell) or "select"
                for cell in re.findall(r"<th[^>]*>(.*?)</th>", thead, re.S)
            ]
            tables.append(
                {
                    "heading": _strip_tags(heading_match.group(1))
                    if heading_match
                    else None,
                    "columns": columns,
                }
            )
        if not re.search(r"<thead>", card) and re.search(r"<table", card):
            tables.append({"heading": None, "columns": []})
    if not actions:
        raise ExtractionError(f"{screen_id}: no action buttons found")
    return {
        "screenId": screen_id,
        "actions": actions,
        "filters": filters,
        "kpiCaptions": kpis,
        "tables": tables,
    }


def _ts(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def render() -> str:
    document = REFERENCE.read_text(encoding="utf-8")
    screens = [
        _extract(_page_block(document, screen_id), screen_id)
        for screen_id in SCREEN_IDS
    ]
    lines = [
        "// Generated from docs/ai_retail_intelligence_dashboard_multicurrency_v6.html",
        "// by tools/extract_reference_layout.py; DO NOT EDIT.",
        "//",
        "// Structure only. Every VALUE on these screens comes from the live API --",
        "// the reference's illustrative figures are deliberately not extracted, so",
        "// sample data is never one import away from a screen.",
        "",
        "export interface ReferenceTable {",
        "  readonly heading: string | null;",
        "  readonly columns: readonly string[];",
        "}",
        "",
        "export interface ReferenceScreen {",
        "  readonly screenId: string;",
        "  readonly actions: readonly string[];",
        "  readonly filters: readonly (readonly string[])[];",
        "  readonly kpiCaptions: readonly string[];",
        "  readonly tables: readonly ReferenceTable[];",
        "}",
        "",
        "export const REFERENCE_SCREENS: readonly ReferenceScreen[] = [",
    ]
    for screen in screens:
        lines.append("  {")
        lines.append(f"    screenId: {_ts(screen['screenId'])},")
        lines.append(f"    actions: {_ts(screen['actions'])},")
        lines.append(f"    filters: {_ts(screen['filters'])},")
        lines.append(f"    kpiCaptions: {_ts(screen['kpiCaptions'])},")
        lines.append("    tables: [")
        for table in screen["tables"]:
            lines.append(
                f"      {{heading: {_ts(table['heading'])}, "
                f"columns: {_ts(table['columns'])}}},"
            )
        lines.append("    ]")
        lines.append("  },")
    lines.extend(("];", ""))
    lines.append(
        "export const REFERENCE_SCREEN_BY_ID: "
        "Record<string, ReferenceScreen> = Object.fromEntries("
    )
    lines.append("  REFERENCE_SCREENS.map((screen) => [screen.screenId, screen])")
    lines.append(");")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        if not OUTPUT.is_file():
            print(f"missing generated layout: {OUTPUT}", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != rendered:
            print(
                "ui/src/generated/inventoryScreenLayout.ts is stale against the "
                "reference document",
                file=sys.stderr,
            )
            return 1
        print("reference screen layout is current")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} for {len(SCREEN_IDS)} screens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
