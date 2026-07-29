"""Canonical `retail_v2` semantic contract.

This package owns *meaning*: entity schemas, money and FX arithmetic, canonical
identity/fingerprint rules and the closed enums the gates depend on. Operational
throughput controls live in the separate `retail-intelligence-execution` package —
changing one must never change the other's outcomes.

The package deliberately imports nothing from `ingestion`, `ml`, `api` or `datagen`.
"""

CONTRACT_VERSION = "retail_v2"
STAGING_CONTRACT_VERSION = "retail-staging/v1"

__all__ = ["CONTRACT_VERSION", "STAGING_CONTRACT_VERSION"]
