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


def _balanced_end(html: str, start: int) -> int:
    """Index just past the `</div>` that closes the div opening at `start`."""

    depth = 0
    cursor = start
    pattern = re.compile(r"<div\b|</div>")
    while match := pattern.search(html, cursor):
        depth += 1 if match.group(0) == "<div" else -1
        cursor = match.end()
        if depth == 0:
            return cursor
    raise ExtractionError(f"unclosed div at offset {start}")


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
    # Cards in document order, each tagged with the layout block it sits in and
    # what KIND of card it is. The kind is the distinction an earlier version of
    # this extractor missed entirely, and missing it is why two screens came out
    # wrong: the reference uses two different tables that look alike in markup.
    #
    #   rows      -- a <thead> and one row per entity. Reads the page's `items`.
    #   breakdown -- NO <thead>, and every row is a label with one or two values.
    #                This is an AGGREGATION view: "Store inventory / ₹31.6 Cr /
    #                64.9%". It reads the endpoint's SQL summary, not `items`, and
    #                rendering it from a page of rows would be a partial total.
    #   alerts    -- .alert children, a decision list.
    #   donut     -- a ring plus a legend of labelled shares.
    #
    # The row LABELS of a breakdown are extracted because they are the approved
    # vocabulary and each one has to be mapped to a summary field by hand; without
    # them a breakdown cannot be filled at all.
    # Grid wrappers are found by DEPTH, not by regex. A non-greedy `(.*?)</div>`
    # stops at the first closing tag, which is inside the wrapper's first card --
    # so the second and later cards in every grid were silently dropped, and that
    # is why Inventory Overview lost its donut and its ageing table and Store
    # Inventory lost its heatmap.
    cards: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for opener in re.finditer(r'<div class="(grid-3|grid-2)">', block):
        end = _balanced_end(block, opener.start())
        spans.append((opener.start(), end))
        _register_cards(cards, block[opener.end() : end], opener.group(1))
    # Whatever sits outside every grid wrapper is a full-width card. Cut the spans
    # out rather than string-replacing, so an identical grid appearing twice cannot
    # remove the wrong one.
    remainder = ""
    cursor = 0
    for start, end in sorted(spans):
        remainder += block[cursor:start]
        cursor = end
    remainder += block[cursor:]
    _register_cards(cards, remainder, "full")
    if not actions:
        raise ExtractionError(f"{screen_id}: no action buttons found")
    if not cards:
        raise ExtractionError(f"{screen_id}: no cards found")
    return {
        "screenId": screen_id,
        "actions": actions,
        "filters": filters,
        "kpiCaptions": kpis,
        "cards": cards,
    }


def _register_cards(cards: list[dict[str, Any]], html: str, layout: str) -> None:
    """Append every card in `html`, classified, preserving document order."""

    for card in re.findall(
        r'<div class="card">(.*?)(?=<div class="card">|\Z)', html, re.S
    ):
        heading_match = re.search(r"<h3>(.*?)</h3>", card, re.S)
        heading = _strip_tags(heading_match.group(1)) if heading_match else None
        link_match = re.search(r'<span class="link">(.*?)</span>', card, re.S)
        link = _strip_tags(link_match.group(1)) if link_match else None
        entry: dict[str, Any] = {"heading": heading, "link": link, "layout": layout}

        if 'class="donut' in card:
            entry["kind"] = "donut"
            # The reference writes its legend as "Healthy 58%". Only the label is
            # kept: the share is an illustrative VALUE and lifting it would put a
            # sample percentage one import from a screen.
            entry["labels"] = [
                re.sub(r"\s*[\d.]+%\s*$", "", _strip_tags(item)).strip()
                for item in re.findall(
                    r"<div><span class=\"dot\".*?</span>(.*?)</div>", card, re.S
                )
            ]
            cards.append(entry)
            continue
        if 'class="alert"' in card:
            entry["kind"] = "alerts"
            entry["labels"] = [
                _strip_tags(item)
                for item in re.findall(r"<strong>(.*?)</strong>", card, re.S)
            ]
            cards.append(entry)
            continue
        if "<table" not in card:
            continue
        thead = re.search(r"<thead><tr>(.*?)</tr></thead>", card, re.S)
        if thead:
            entry["kind"] = "rows"
            entry["columns"] = [
                _strip_tags(cell) or "select"
                for cell in re.findall(r"<th[^>]*>(.*?)</th>", thead.group(1), re.S)
            ]
            entry["labels"] = []
        else:
            entry["kind"] = "breakdown"
            entry["columns"] = []
            entry["labels"] = [
                _strip_tags(row.split("</td>")[0])
                for row in re.findall(r"<tr><td>(.*?)</tr>", card, re.S)
            ]
        cards.append(entry)


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
        "export type ReferenceCardKind = \"rows\" | \"breakdown\" | \"alerts\" | \"donut\";",
        "",
        "export interface ReferenceCard {",
        "  readonly kind: ReferenceCardKind;",
        "  readonly heading: string | null;",
        "  readonly link: string | null;",
        "  /** grid-3 | grid-2 | full -- the layout block the card sits in. */",
        "  readonly layout: string;",
        "  /** Column headers, for a `rows` card. */",
        "  readonly columns: readonly string[];",
        "  /** Row labels, for a `breakdown`, `alerts` or `donut` card. */",
        "  readonly labels: readonly string[];",
        "}",
        "",
        "export interface ReferenceScreen {",
        "  readonly screenId: string;",
        "  readonly actions: readonly string[];",
        "  readonly filters: readonly (readonly string[])[];",
        "  readonly kpiCaptions: readonly string[];",
        "  readonly cards: readonly ReferenceCard[];",
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
        lines.append("    cards: [")
        for card in screen["cards"]:
            lines.append(
                f"      {{kind: {_ts(card['kind'])}, "
                f"heading: {_ts(card['heading'])}, "
                f"link: {_ts(card.get('link'))}, "
                f"layout: {_ts(card['layout'])}, "
                f"columns: {_ts(card.get('columns', []))}, "
                f"labels: {_ts(card.get('labels', []))}}},"
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
