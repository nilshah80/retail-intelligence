#!/usr/bin/env python3
"""Validate every machine-readable Phase-2 contract."""

from __future__ import annotations

import json

from retail_contracts.entities import validate_contract_tree


def main() -> int:
    summary = validate_contract_tree()
    print(json.dumps({"status": "valid", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
