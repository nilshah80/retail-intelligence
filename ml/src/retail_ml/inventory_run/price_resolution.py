"""Origin-visible realised-price resolution shared by inventory and scenarios.

Inventory historically consumed only two integer maps. Scenario Planning needs
the same exact/fallback choice plus honest lineage. This module owns both so a
future provenance change cannot silently alter the existing demand-at-risk price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Final

import pandas as pd
from retail_contracts.fingerprint import canonical_json_bytes, semantic_fingerprint

PRICE_OBSERVATION_SCHEMA: Final[str] = "retail-realized-price-observation/v1"
PRICE_FALLBACK_SCHEMA: Final[str] = "retail-market-sku-price-fallback/v1"
PRICE_SNAPSHOT_SCHEMA: Final[str] = "retail-realized-price-snapshot/v1"

SeriesPriceKey = tuple[str, str, str, str]
MarketSKUKey = tuple[str, str]


class PriceResolutionError(ValueError):
    """Price evidence is duplicate, invalid, or lacks required lineage."""


def _timestamp_text(value: Any, *, context: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PriceResolutionError(f"{context} is not a timestamp") from exc
    if pd.isna(timestamp):
        raise PriceResolutionError(f"{context} is missing")
    if timestamp.tzinfo is None:
        # DuckDB may return a naive value for a canonical UTC TIMESTAMP. The
        # source contract defines known_as_of as an instant, so the loader and
        # tests interpret that representation as UTC rather than local time.
        timestamp = timestamp.tz_localize(timezone.utc)
    else:
        timestamp = timestamp.tz_convert(timezone.utc)
    return timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date_text(value: Any, *, context: str) -> str:
    if isinstance(value, datetime):
        result = value.date()
    elif isinstance(value, date):
        result = value
    else:
        try:
            result = pd.Timestamp(value).date()
        except (TypeError, ValueError) as exc:
            raise PriceResolutionError(f"{context} is not a date") from exc
    return result.isoformat()


@dataclass(frozen=True)
class PriceEvidence:
    """One chosen price and its exact or population-derived provenance."""

    unit_price_minor: int
    currency_code: str | None
    price_basis: str
    source_row_identity: str | None = None
    source_row_version: str | None = None
    observation_date: str | None = None
    known_as_of: str | None = None
    source_row_content_fingerprint: str | None = None
    fallback_population_count: int | None = None
    fallback_observation_start: str | None = None
    fallback_observation_end: str | None = None
    fallback_max_known_as_of: str | None = None
    fallback_member_set_content_fingerprint: str | None = None

    @property
    def provenance_complete(self) -> bool:
        if self.price_basis == "latest_realized_exact":
            return all(
                value is not None
                for value in (
                    self.currency_code,
                    self.source_row_identity,
                    self.source_row_version,
                    self.observation_date,
                    self.known_as_of,
                    self.source_row_content_fingerprint,
                )
            )
        return all(
            value is not None
            for value in (
                self.currency_code,
                self.fallback_population_count,
                self.fallback_observation_start,
                self.fallback_observation_end,
                self.fallback_max_known_as_of,
                self.fallback_member_set_content_fingerprint,
            )
        )


@dataclass(frozen=True)
class PriceIndex:
    exact: dict[SeriesPriceKey, PriceEvidence]
    fallback: dict[MarketSKUKey, PriceEvidence]
    snapshot_content_fingerprint: str | None

    def resolve(self, key: SeriesPriceKey) -> PriceEvidence | None:
        """Prefer exact SeriesKey evidence, then same-market/SKU median."""

        return self.exact.get(key) or self.fallback.get((key[0], key[2]))

    def numeric_views(
        self,
    ) -> tuple[dict[SeriesPriceKey, int], dict[MarketSKUKey, int]]:
        return (
            {key: evidence.unit_price_minor for key, evidence in self.exact.items()},
            {key: evidence.unit_price_minor for key, evidence in self.fallback.items()},
        )


def _observation_payload(row: dict[str, Any]) -> dict[str, Any]:
    required = {
        "market_id",
        "location_id",
        "channel_id",
        "sku_id",
        "unit_price_minor",
        "currency_code",
        "observation_date",
        "known_as_of",
        "sales_version",
    }
    missing = required - set(row)
    if missing:
        raise PriceResolutionError(
            f"price observation lacks provenance columns {sorted(missing)}"
        )
    currency = str(row["currency_code"])
    if len(currency) != 3:
        raise PriceResolutionError(f"invalid operating currency {currency!r}")
    version = row["sales_version"]
    if isinstance(version, bool) or int(version) < 1:
        raise PriceResolutionError("sales_version must be a positive integer")
    return {
        "schemaVersion": PRICE_OBSERVATION_SCHEMA,
        "marketId": str(row["market_id"]),
        "locationId": str(row["location_id"]),
        "channelId": str(row["channel_id"]),
        "skuId": str(row["sku_id"]),
        "currencyCode": currency,
        "observationDate": _date_text(
            row["observation_date"], context="observation_date"
        ),
        "knownAsOf": _timestamp_text(row["known_as_of"], context="known_as_of"),
        "salesVersion": int(version),
        "unitPriceMinor": int(row["unit_price_minor"]),
    }


def _source_identity(payload: dict[str, Any]) -> str:
    identity = {
        "entity": "sales",
        "skuId": payload["skuId"],
        "storeId": payload["locationId"],
        "channelId": payload["channelId"],
        "date": payload["observationDate"],
        "salesVersion": payload["salesVersion"],
    }
    return canonical_json_bytes(identity).decode("utf-8")


def build_price_index(
    frame: pd.DataFrame,
    *,
    source_cutoff: date | datetime | None = None,
    require_provenance: bool = False,
) -> PriceIndex:
    """Build exact and deterministic same-market/SKU fallback evidence.

    The fallback is the sorted median of the latest positive SeriesKey prices;
    for an even population its midpoint uses integer floor. This is byte-for-byte
    the old inventory algorithm, with provenance added around it.
    """

    exact: dict[SeriesPriceKey, PriceEvidence] = {}
    member_payloads: dict[MarketSKUKey, list[dict[str, Any]]] = {}
    complete_payloads: list[dict[str, Any]] = []
    provenance_columns = {
        "currency_code",
        "observation_date",
        "known_as_of",
        "sales_version",
    }
    provenance_present = provenance_columns <= set(frame.columns)
    if require_provenance and not provenance_present:
        raise PriceResolutionError(
            f"price frame lacks provenance columns {sorted(provenance_columns - set(frame.columns))}"
        )

    for record in frame.itertuples(index=False):
        row = record._asdict()
        key: SeriesPriceKey = (
            str(row["market_id"]),
            str(row["location_id"]),
            str(row["sku_id"]),
            str(row["channel_id"]),
        )
        price = int(row["unit_price_minor"])
        if price <= 0:
            raise PriceResolutionError(f"non-positive realised selling price for {key}")
        if key in exact:
            raise PriceResolutionError(f"duplicate realised selling price for {key}")

        if provenance_present:
            payload = _observation_payload(row)
            if source_cutoff is not None:
                if isinstance(source_cutoff, datetime):
                    cutoff = pd.Timestamp(source_cutoff)
                    if cutoff.tzinfo is None:
                        cutoff = cutoff.tz_localize(timezone.utc)
                    else:
                        cutoff = cutoff.tz_convert(timezone.utc)
                    cutoff_date = cutoff.date()
                else:
                    cutoff = None
                    cutoff_date = source_cutoff
                if date.fromisoformat(payload["observationDate"]) > cutoff_date:
                    raise PriceResolutionError(
                        f"price observation for {key} is after its source cutoff"
                    )
                known = pd.Timestamp(payload["knownAsOf"])
                if isinstance(source_cutoff, datetime):
                    assert cutoff is not None
                    visible = known <= cutoff
                else:
                    visible = known < (
                        pd.Timestamp(source_cutoff).tz_localize(timezone.utc)
                        + pd.Timedelta(days=1)
                    )
                if not visible:
                    raise PriceResolutionError(
                        f"price observation for {key} is not origin-visible"
                    )
            fingerprint = semantic_fingerprint(payload, volatile_pointers=())
            evidence = PriceEvidence(
                unit_price_minor=price,
                currency_code=payload["currencyCode"],
                price_basis="latest_realized_exact",
                source_row_identity=_source_identity(payload),
                source_row_version=str(payload["salesVersion"]),
                observation_date=payload["observationDate"],
                known_as_of=payload["knownAsOf"],
                source_row_content_fingerprint=fingerprint,
            )
            member = {
                "seriesKey": [key[0], key[1], key[2], key[3]],
                "observationContentFingerprint": fingerprint,
                "unitPriceMinor": price,
                "currencyCode": payload["currencyCode"],
                "observationDate": payload["observationDate"],
                "knownAsOf": payload["knownAsOf"],
            }
            member_payloads.setdefault((key[0], key[2]), []).append(member)
            complete_payloads.append(member)
        else:
            evidence = PriceEvidence(
                unit_price_minor=price,
                currency_code=None,
                price_basis="latest_realized_exact",
            )
            member_payloads.setdefault((key[0], key[2]), []).append(
                {"seriesKey": list(key), "unitPriceMinor": price}
            )
        exact[key] = evidence

    fallback: dict[MarketSKUKey, PriceEvidence] = {}
    for key, members in member_payloads.items():
        ordered_prices = sorted(int(member["unitPriceMinor"]) for member in members)
        middle = len(ordered_prices) // 2
        price = (
            ordered_prices[middle]
            if len(ordered_prices) % 2
            else (ordered_prices[middle - 1] + ordered_prices[middle]) // 2
        )
        if provenance_present:
            ordered_members = sorted(
                members,
                key=lambda member: (
                    member["seriesKey"],
                    member["observationDate"],
                    member["knownAsOf"],
                    member["observationContentFingerprint"],
                ),
            )
            currencies = {str(member["currencyCode"]) for member in ordered_members}
            if len(currencies) != 1:
                raise PriceResolutionError(
                    f"market/SKU fallback {key} crosses currencies {sorted(currencies)}"
                )
            fallback_payload = {
                "schemaVersion": PRICE_FALLBACK_SCHEMA,
                "marketId": key[0],
                "skuId": key[1],
                "members": ordered_members,
            }
            fallback[key] = PriceEvidence(
                unit_price_minor=price,
                currency_code=next(iter(currencies)),
                price_basis="market_sku_latest_median",
                fallback_population_count=len(ordered_members),
                fallback_observation_start=min(
                    str(member["observationDate"]) for member in ordered_members
                ),
                fallback_observation_end=max(
                    str(member["observationDate"]) for member in ordered_members
                ),
                fallback_max_known_as_of=max(
                    str(member["knownAsOf"]) for member in ordered_members
                ),
                fallback_member_set_content_fingerprint=semantic_fingerprint(
                    fallback_payload, volatile_pointers=()
                ),
            )
        else:
            fallback[key] = PriceEvidence(
                unit_price_minor=price,
                currency_code=None,
                price_basis="market_sku_latest_median",
                fallback_population_count=len(members),
            )

    snapshot_fingerprint: str | None = None
    if provenance_present:
        cutoff = (
            _timestamp_text(source_cutoff, context="source_cutoff")
            if isinstance(source_cutoff, datetime)
            else source_cutoff.isoformat()
            if isinstance(source_cutoff, date)
            else None
        )
        snapshot_payload = {
            "schemaVersion": PRICE_SNAPSHOT_SCHEMA,
            "sourceCutoff": cutoff,
            "observations": sorted(
                complete_payloads,
                key=lambda member: (
                    member["seriesKey"],
                    member["observationDate"],
                    member["knownAsOf"],
                    member["observationContentFingerprint"],
                ),
            ),
        }
        snapshot_fingerprint = semantic_fingerprint(
            snapshot_payload, volatile_pointers=()
        )

    return PriceIndex(
        exact=exact,
        fallback=fallback,
        snapshot_content_fingerprint=snapshot_fingerprint,
    )
