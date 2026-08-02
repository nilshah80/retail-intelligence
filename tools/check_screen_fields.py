"""Every field the fourteen screens name must exist in what their endpoint serves.

A screen spec in `ui/src/Inventory.tsx` binds each KPI tile, breakdown row and
table column to a named field. Nothing checks that the name is real: the read
model returns what it selects, so a field the UI asks for and the API never
produces reads as absent and renders the governed unavailable treatment. The
screen looks deliberate. It is a typo, or a column the route forgot to select.

That is not hypothetical -- it is how the warehouse route shipped with a blank
Action cell on every row for want of `residual_only` in its projection.

The vitest suite cannot catch this: it asserts the spec is internally consistent
and matches the reference, both of which stay true while the field name is
wrong. Only the live API knows. So this runs against a serving instance and is a
developer gate rather than a unit test.

    python tools/check_screen_fields.py --base-url http://127.0.0.1:8080

Exits non-zero listing every unresolved field.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENS = REPO_ROOT / "ui" / "src" / "Inventory.tsx"

#: A screen block runs from its key line to the next one. Parsed rather than
#: imported because the source is TypeScript and this is Python; the alternative
#: is a second generated artifact to keep in step, which is the thing this file
#: exists to avoid.
SCREEN_KEY = re.compile(r"^  (\w+): \{$", re.M)
ENDPOINT = re.compile(r'endpoint: "([^"]+)"')
#: `field:` on a KPI or breakdown row, `of:` on its denominator, and `field:` on
#: a table column. Same attribute name, three contexts, one meaning.
FIELD = re.compile(r'\b(?:field|of): "(\w+)"')


def screen_blocks(source: str) -> list[tuple[str, str]]:
    keys = [(m.group(1), m.start()) for m in SCREEN_KEY.finditer(source)]
    blocks = []
    for index, (name, start) in enumerate(keys):
        end = keys[index + 1][1] if index + 1 < len(keys) else len(source)
        blocks.append((name, source[start:end]))
    return blocks


def fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args(argv)

    source = SCREENS.read_text(encoding="utf-8")
    unresolved: list[tuple[str, str, str]] = []
    checked = 0

    for name, block in screen_blocks(source):
        match = ENDPOINT.search(block)
        if match is None:
            continue
        endpoint = match.group(1)
        try:
            payload = fetch(args.base_url + endpoint)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"{name}: cannot reach {endpoint}: {error}", file=sys.stderr)
            return 2
        if payload.get("dataMode") != "live":
            print(
                f"{name}: {endpoint} is {payload.get('dataMode')} "
                f"({payload.get('reasonCode')}); activate a bundle first",
                file=sys.stderr,
            )
            return 2
        # A field resolves against the SQL summary (tiles and breakdown rows) or
        # against a served row (table columns). Both are the endpoint's output.
        available = set(payload.get("summary") or {})
        for item in payload.get("items", [])[:1]:
            available |= set(item)
        # Grouped cards are a third place a field can legitimately live -- one
        # row per category, per location, per bucket. Omitting them here reported
        # every grouped column as unresolved.
        for rows in (payload.get("cards") or {}).values():
            for row in rows[:1]:
                available |= set(row)
        for field in sorted(set(FIELD.findall(block))):
            checked += 1
            if field not in available:
                unresolved.append((name, endpoint, field))

    if unresolved:
        print(f"{len(unresolved)} of {checked} named fields do not resolve:")
        for name, endpoint, field in unresolved:
            print(f"  {name:24s} {endpoint:38s} {field}")
        return 1
    print(f"all {checked} named fields resolve against the live API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
