"""Source ingestion: immutable landing through curated `retail_v2` publication.

Owns the whole boundary from raw source data to curated output:

    immutable raw landing -> Gate A -> profile/adapter -> standardized staging
      -> source-neutral transforms -> canonical retail_v2 candidate -> Gate B
      -> curated Parquet/DuckDB

Imports `retail_contracts` for meaning and `retail_execution` for bounded
throughput. Never imports `ml`, `api` or `datagen`.
"""

INGESTION_VERSION = "0.1.0"
PROFILE_CONTRACT_VERSION = "retail-source-profile/v1"

__all__ = ["INGESTION_VERSION", "PROFILE_CONTRACT_VERSION"]
