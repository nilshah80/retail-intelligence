"""Atomic source-shaped publication with deterministic content inventory."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml

from .spool import RowSpool

INTERNAL_PARTITION_FIELD = "__partitionDate"

PARTITION_DATE_FIELDS = (
    INTERNAL_PARTITION_FIELD,
    "date",
    "businessDate",
    "postingDate",
    "effectiveDate",
    "effectiveFrom",
    "startDate",
    "observedAt",
    "validDate",
    "createdAt",
    "requestedAt",
    "processedAt",
    "issuedAt",
    "orderDate",
    "receiptDate",
    "requestDate",
    "expectedDate",
    "actualDate",
    "confirmedAt",
    "shipmentDate",
    "invoiceDate",
    "introducedDate",
    "discontinuedDate",
    "snapshotDate",
    "eventDate",
    "rateDate",
)

UNPARTITIONED_DATASETS = {
    "products",
    "productVariants",
    "inventoryItems",
    "locations",
    "items",
    "itemVariants",
    "companyMarketConfig",
    "vendors",
    "vendorItemTerms",
    "customerSegments",
    "storeAssortment",
    "competitorMatches",
    "catalogTruth",
    "competitorMatchTruth",
}

EMPTY_DATASET_FIELDS: dict[str, tuple[str, ...]] = {
    "orders": (
        "id", "name", "createdAt", "processedAt", "currencyCode",
        "taxesIncluded", "subtotalPrice", "totalTax", "totalPrice",
        "displayFinancialStatus", "displayFulfillmentStatus", "locationId",
        "sourceName", "customerSegmentId", "channelId", "lineCount",
        "customerId",
    ),
    "orderLines": (
        "id", "orderId", "variantId", "sku", "productTitle", "variantTitle",
        "vendor", "productCode", "barcode", "quantity", "originalUnitPrice",
        "discountedUnitPrice", "promotionIds", "currencyCode", "taxRate",
        "lineNumber", "customerSegmentId", "channelId",
    ),
    "customers": (
        "id", "syntheticCustomerKey", "segmentId", "createdAt", "state",
        "email", "phone", "firstName", "lastName",
        "directIdentifiersPresent", "number", "displayName", "marketCode",
        "segmentCode", "phoneNumber", "blocked",
    ),
    "salesInvoices": (
        "id", "number", "externalDocumentNumber", "invoiceDate", "postingDate",
        "currencyCode", "totalAmountExcludingTax", "totalTaxAmount",
        "totalAmountIncludingTax", "status", "customerSegmentCode",
        "salesChannelCode", "customerId",
    ),
    "salesInvoiceLines": (
        "id", "documentId", "lineNumber", "itemId", "itemNumber",
        "variantCode", "sku", "description", "locationCode", "quantity",
        "unitPrice", "netAmount", "taxAmount", "amountIncludingTax",
        "currencyCode",
    ),
    "itemLedgerEntries": (
        "id", "entryNumber", "postingDate", "entryType", "itemNumber",
        "variantCode", "sku", "locationCode", "quantity", "documentNumber",
    ),
    "fulfillmentOrders": (
        "id", "orderId", "status", "requestStatus", "createdAt", "updatedAt",
        "deliveryMethod", "destinationLocationId",
    ),
    "fulfillmentOrderLines": (
        "id", "fulfillmentOrderId", "orderLineId", "sku", "totalQuantity",
        "remainingQuantity", "warehouseKey",
    ),
    "fulfillments": (
        "id", "orderId", "fulfillmentOrderId", "locationId", "status",
        "shipmentStatus", "createdAt", "deliveredAt", "trackingCompany",
        "trackingNumber",
    ),
    "fulfillmentLines": (
        "id", "fulfillmentId", "orderLineId", "sku", "quantity",
        "warehouseKey",
    ),
    "fulfillmentStatusHistory": (
        "fulfillmentId", "sequence", "status", "occurredAt", "warehouseKey",
    ),
    # Source contract v13 store echelon. Declared so a small window that produced
    # no store waste (or a feature-off run) still emits a schema-complete empty
    # file rather than failing the writer.
    "storeInventorySnapshots": (
        "locationCode", "observedAt", "sku", "inventory", "availableInventory",
        "committedInventory", "reservedInventory", "damagedInventory",
        "qualityControlInventory", "safetyStockInventory", "incomingInventory",
        "assortmentActive", "residualOnly", "oldestReceiptDate",
    ),
    "storeTransferEvents": (
        "transferId", "sku", "fromLocationCode", "toLocationCode", "quantity",
        "status", "statusEffectiveAt", "observedAt", "unitCostAmountMinor",
        "currencyCode",
    ),
    "storeWasteEvents": (
        "eventId", "sku", "locationCode", "eventDate", "quantity",
        "reasonCode", "observedAt",
    ),
    # A store sale the shelf could not cover, which the DC fulfilled instead. The
    # simulation has always computed this; it was declared in the dataset list and
    # never written, so `sales` recorded the sale while the shelf dropped only by
    # servedFromStoreUnits and nothing downstream could tell the two apart. Any
    # shelf-level reconstruction then charges the whole sale to the store: on the
    # tightened network that is 123,894 units of india-west drift over 52 weeks.
    "storeStockoutEvents": (
        "eventId", "sku", "locationCode", "channelId", "eventDate",
        "demandUnits", "servedFromStoreUnits", "shortfallUnits",
        "servedFromLocationCode", "observedAt",
    ),
    "inboundStatusEvents": (
        "shipmentId", "sku", "locationCode", "quantity", "status",
        "statusEffectiveAt", "observedAt", "expectedReceiptDate",
    ),
    "supplyTerms": (
        "vendorId", "destinationLocationCode", "originKind", "merchScopeType",
        "merchScopeId", "effectiveFrom", "leadTimeDays", "leadTimeStdDevDays",
        "minimumOrderQuantity", "orderMultiple", "capacityUnitsPerMonth",
        "paymentTermsCode", "observedAt",
    ),
    "serviceLanes": (
        "laneKey", "marketKey", "laneType", "demandLocationKey", "channelKey",
        "supplyLocationKey", "priorityRank", "transitDays", "effectiveFrom",
        "effectiveTo", "observedAt",
    ),
    "taxLines": (
        "orderLineId", "orderId", "title", "rate", "shareOfTax", "price",
        "currencyCode", "jurisdiction",
    ),
    "returns": (
        "id", "orderId", "name", "status", "requestedAt", "processedAt",
        "reason",
    ),
    "returnLines": (
        "id", "returnId", "orderLineId", "sku", "requestedQuantity",
        "processedQuantity", "restockType", "restockLocationId",
    ),
    "refunds": (
        "id", "orderId", "returnId", "createdAt", "totalRefunded",
        "currencyCode", "status",
    ),
    "refundTransactions": (
        "id", "refundId", "orderId", "kind", "gateway", "status", "amount",
        "currencyCode", "processedAt", "errorCode",
    ),
    "webhookHmacFixtures": (
        "fixtureId", "topic", "shopDomain", "webhookId", "apiVersion", "body",
        "hmacHeader", "validExpected", "idParityOrderId",
    ),
    "sourceEventCrosswalk": (
        "eventKey", "lineKey", "orderKey", "shopifyOrderId",
        "shopifyOrderLineId", "businessCentralInvoiceId",
        "businessCentralInvoiceLineIds", "marketKey", "storeKey",
    ),
    "competitorMatchTruth": (
        "matchKey", "marketKey", "competitorId", "competitorSku", "ourSku",
        "matchMethod", "matchConfidence", "effectiveFrom", "effectiveTo",
    ),
    "promotionSkus": (
        "marketKey", "promotionId", "sku", "departmentId", "categoryId",
        "discountPct", "discountBasis", "effectiveFrom", "effectiveTo",
    ),
    "competitorPrices": (
        "marketKey", "targetType", "targetId", "observedAt", "validDate",
        "competitorId", "competitorSku", "competitorProductTitle", "price",
        "currencyCode", "available", "promotionText",
    ),
    "competitorMatches": (
        "matchKey", "marketKey", "competitorId", "competitorSku", "ourSku",
        "matchMethod", "matchConfidence", "effectiveFrom", "effectiveTo",
    ),
    "allocationDemandRequests": (
        "requestKey", "marketKey", "storeKey", "channelId", "requestDate", "sku",
        "requestedQuantity", "allocatedQuantity", "unallocatedQuantity",
        "warehousePriority", "status",
    ),
    "allocationSupplyPools": (
        "poolKey", "marketKey", "warehouseKey", "snapshotDate", "sku",
        "availableQuantity", "incomingQuantity", "safetyStockQuantity",
    ),
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SourceWriter:
    """Stage one deterministic run and promote it atomically."""

    def __init__(
        self,
        output_root: str,
        scenario_id: str,
        run_id: str,
        *,
        overwrite: bool = False,
        generation_partition: str = "month",
        source_format: str = "parquet",
        compression: str = "zstd",
        workers: int = 2,
        duckdb_threads: int = 1,
        memory_limit_gb: float = 4.0,
        spool_chunk_rows: int = 10_000,
    ) -> None:
        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.target = root / scenario_id / run_id
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._overwrite = overwrite
        self._generation_partition = generation_partition
        self._source_format = source_format
        self._compression = compression
        self._workers = max(1, workers)
        self._duckdb_threads = max(1, duckdb_threads)
        self._memory_limit_gb = max(0.5, memory_limit_gb)
        self._spool_chunk_rows = max(1, spool_chunk_rows)
        self.reused = self.target.is_dir() and not overwrite
        self.objects: list[dict[str, Any]] = []
        self.schemas: dict[str, dict[str, Any]] = {}
        self.telemetry: dict[str, float | int] = {
            "datasetsPublished": 0,
            "sourcePublicationSeconds": 0.0,
            "duckdbMirrorSeconds": 0.0,
        }
        self._stage: Path | None = None
        self._spools: list[RowSpool] = []
        if not self.reused:
            self._stage = Path(
                tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=self.target.parent)
            )

    @property
    def base(self) -> Path:
        return self.target if self.reused else self._require_stage()

    def _require_stage(self) -> Path:
        if self._stage is None:
            raise RuntimeError("writer has no active staging directory")
        return self._stage

    @property
    def work_directory(self) -> Path:
        work = self._require_stage() / ".work"
        work.mkdir(parents=True, exist_ok=True)
        return work

    def new_spool(self, name: str) -> RowSpool:
        """Create an internal repeatable row stream owned by this run."""

        spool = RowSpool(
            self.work_directory / "row-spools",
            name,
            chunk_rows=self._spool_chunk_rows,
        )
        self._spools.append(spool)
        return spool

    def adopt_spools(self, spools: Iterable[RowSpool]) -> None:
        """Take cleanup ownership of spools created by market worker processes."""

        self._spools.extend(spools)

    def work_size_bytes(self) -> int:
        """Measure private spill/temp files before they are removed on promote."""

        if self._stage is None:
            return 0
        work = self._stage / ".work"
        return sum(
            path.stat().st_size
            for path in work.rglob("*")
            if path.is_file()
        )

    def _register(
        self,
        path: Path,
        *,
        source_system: str,
        dataset: str,
        rows: int | None,
        restricted: bool,
        logical_path: str | None = None,
    ) -> None:
        stage = self._require_stage()
        self.objects.append(
            {
                "path": path.relative_to(stage).as_posix(),
                "logicalPath": logical_path or path.relative_to(stage).as_posix(),
                "sourceSystem": source_system,
                "dataset": dataset,
                "format": path.suffix.lstrip("."),
                "compression": (
                    self._compression
                    if path.suffix.lower() == ".parquet"
                    else "none"
                ),
                "rows": rows,
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
                "contentDeterminism": (
                    "logical"
                    if dataset == "sourceRunDuckdb"
                    else "byte"
                ),
                "restricted": restricted,
            }
        )

    def write_dataset(
        self,
        relative_path: str,
        rows: Iterable[dict[str, Any]],
        *,
        source_system: str,
        dataset: str,
        restricted: bool = False,
        fieldnames: Iterable[str] | None = None,
    ) -> None:
        if self.reused:
            return
        started = time.perf_counter()
        logical_path = Path(relative_path).with_suffix(
            f".{self._source_format}"
        ).as_posix()
        iterator = iter(rows)
        first = next(iterator, None)
        resolved_fieldnames = sorted(
            {
                field
                for field in (fieldnames or EMPTY_DATASET_FIELDS.get(dataset, ()))
                if not field.startswith("__")
            }.union(
                key
                for key in (first or {})
                if not key.startswith("__")
            )
        )
        if not resolved_fieldnames:
            raise ValueError(f"{relative_path} needs fieldnames when it has no rows")
        schema = {
            "logicalPath": logical_path,
            "sourceSystem": source_system,
            "dataset": dataset,
            "restricted": restricted,
            "fields": [
                {
                    "name": field,
                    "physicalType": "VARCHAR",
                    "nullable": True,
                }
                for field in resolved_fieldnames
            ],
        }
        prior_schema = self.schemas.setdefault(logical_path, schema)
        if prior_schema != schema:
            raise ValueError(f"inconsistent schema across partitions for {logical_path}")

        partition_field = None
        if first is not None and dataset not in UNPARTITIONED_DATASETS:
            partition_field = next(
                (
                    field
                    for field in PARTITION_DATE_FIELDS
                    if field in resolved_fieldnames
                ),
                None,
            )
        staged: dict[str, dict[str, Any]] = {}
        open_states: OrderedDict[str, dict[str, Any]] = OrderedDict()
        max_open_partition_files = 16

        def close_state(state: dict[str, Any]) -> None:
            handle = state.get("handle")
            if handle is None:
                return
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            state["handle"] = None
            state["writer"] = None

        def ensure_open(
            partition: str,
            state: dict[str, Any],
        ) -> csv.DictWriter:
            if state.get("handle") is not None:
                open_states.move_to_end(partition)
                return state["writer"]
            while len(open_states) >= max_open_partition_files:
                _, evicted = open_states.popitem(last=False)
                close_state(evicted)
            first_open = not state["initialized"]
            handle = state["path"].open(
                "w" if first_open else "a",
                encoding="utf-8",
                newline="",
            )
            csv_writer = csv.DictWriter(
                handle,
                fieldnames=resolved_fieldnames,
                extrasaction="raise",
                lineterminator="\n",
            )
            if first_open:
                csv_writer.writeheader()
                state["initialized"] = True
            state["handle"] = handle
            state["writer"] = csv_writer
            open_states[partition] = state
            return csv_writer

        def add_row(row: dict[str, Any]) -> None:
            public_row = {
                key: value
                for key, value in row.items()
                if not key.startswith("__")
            }
            unknown = set(public_row).difference(resolved_fieldnames)
            if unknown:
                raise ValueError(
                    f"{relative_path} introduced fields after its first row: "
                    f"{sorted(unknown)}"
                )
            partition = ""
            if partition_field:
                raw_date = str(row.get(partition_field, ""))[:10]
                if raw_date:
                    try:
                        parsed = date.fromisoformat(raw_date)
                    except ValueError as exc:
                        raise ValueError(
                            f"{relative_path}.{partition_field} contains "
                            f"non-ISO date {row.get(partition_field)!r}"
                        ) from exc
                    partition = (
                        parsed.isoformat()
                        if self._generation_partition == "day"
                        else f"{parsed.year:04d}-{parsed.month:02d}"
                    )
            state = staged.get(partition)
            if state is None:
                ordinal = len(staged)
                csv_path = (
                    self.work_directory
                    / "dataset-csv"
                    / f"{self._duckdb_table_name(logical_path)}-{ordinal:05d}.csv"
                )
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                state = {
                    "path": csv_path,
                    "handle": None,
                    "writer": None,
                    "initialized": False,
                    "rows": 0,
                }
                staged[partition] = state
            ensure_open(partition, state).writerow(public_row)
            state["rows"] += 1

        if first is not None:
            add_row(first)
            for row in iterator:
                add_row(row)
        if not staged:
            csv_path = (
                self.work_directory
                / "dataset-csv"
                / f"{self._duckdb_table_name(logical_path)}-empty.csv"
            )
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            staged[""] = {
                "path": csv_path,
                "handle": None,
                "writer": None,
                "initialized": False,
                "rows": 0,
            }
            ensure_open("", staged[""])
        for state in list(open_states.values()):
            close_state(state)
        open_states.clear()

        def publish(item: tuple[str, dict[str, Any]]) -> tuple[str, int]:
            partition, state = item
            if partition:
                base = Path(logical_path).with_suffix("").as_posix()
                if self._generation_partition == "day":
                    year, month, day = partition.split("-")
                    relative = (
                        f"{base}/year={year}/month={month}/day={day}/"
                        f"part.{self._source_format}"
                    )
                else:
                    year, month = partition.split("-")
                    relative = (
                        f"{base}/year={year}/month={month}/"
                        f"part.{self._source_format}"
                    )
            else:
                relative = logical_path
            output_path = self._require_stage() / relative
            output_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path = state["path"]
            if self._source_format == "csv":
                os.replace(csv_path, output_path)
            elif self._source_format == "parquet":
                self._csv_to_parquet(csv_path, output_path)
                csv_path.unlink(missing_ok=True)
            else:
                raise ValueError(f"unsupported source format {self._source_format!r}")
            if restricted:
                output_path.chmod(0o600)
            return relative, state["rows"]

        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            published = list(executor.map(publish, sorted(staged.items())))
        for relative, row_count in sorted(published):
            self._register(
                self._require_stage() / relative,
                source_system=source_system,
                dataset=dataset,
                rows=row_count,
                restricted=restricted,
                logical_path=logical_path,
            )
        self.telemetry["datasetsPublished"] = (
            int(self.telemetry["datasetsPublished"]) + 1
        )
        self.telemetry["sourcePublicationSeconds"] = round(
            float(self.telemetry["sourcePublicationSeconds"])
            + time.perf_counter()
            - started,
            6,
        )

    def _csv_to_parquet(self, staging_csv: Path, path: Path) -> None:
        """Convert one staged partition with an isolated, memory-capped worker."""

        try:
            import duckdb
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parquet publication requires the datagen DuckDB dependency"
            ) from exc
        temp = path.with_suffix(path.suffix + ".tmp")
        connection = duckdb.connect()
        try:
            per_worker_gb = max(
                0.25,
                self._memory_limit_gb / self._workers,
            )
            connection.execute(f"SET memory_limit='{per_worker_gb:.3f}GB'")
            connection.execute("SET threads=1")
            connection.execute(
                "CREATE TABLE payload AS "
                "SELECT * FROM read_csv_auto(?, header=true, all_varchar=true, "
                "sample_size=-1, hive_partitioning=false)",
                [str(staging_csv)],
            )
            compression = (
                "uncompressed"
                if self._compression == "none"
                else self._compression
            )
            output_path = str(temp).replace("'", "''")
            connection.execute(
                f"COPY payload TO '{output_path}' "
                f"(FORMAT PARQUET, COMPRESSION {compression.upper()})"
            )
        finally:
            connection.close()
        os.replace(temp, path)

    def write_json(
        self,
        relative_path: str,
        value: Any,
        *,
        source_system: str,
        dataset: str,
        restricted: bool = False,
        register: bool = True,
    ) -> None:
        if self.reused:
            return
        path = self._require_stage() / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if restricted:
            path.chmod(0o600)
        if register:
            self._register(
                path,
                source_system=source_system,
                dataset=dataset,
                rows=None,
                restricted=restricted,
                logical_path=relative_path,
            )

    def write_yaml(
        self,
        relative_path: str,
        value: Any,
        *,
        source_system: str,
        dataset: str,
        restricted: bool = False,
        register: bool = True,
    ) -> None:
        if self.reused:
            return
        path = self._require_stage() / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        text = yaml.safe_dump(
            value,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if restricted:
            path.chmod(0o600)
        if register:
            self._register(
                path,
                source_system=source_system,
                dataset=dataset,
                rows=None,
                restricted=restricted,
                logical_path=relative_path,
            )

    @staticmethod
    def _duckdb_table_name(relative_path: str) -> str:
        stem = Path(relative_path).with_suffix("").as_posix()
        return "".join(
            character if character.isalnum() else "_"
            for character in stem
        ).strip("_").lower()

    def _write_duckdb_mirror(
        self,
        relative_path: str,
        source_objects: list[dict[str, Any]],
    ) -> None:
        try:
            import duckdb
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "DuckDB publication requires the datagen project dependency; "
                "install datagen/pyproject.toml before generation"
            ) from exc

        stage = self._require_stage()
        path = stage / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        connection = duckdb.connect(
            str(temp),
            config={
                "memory_limit": f"{self._memory_limit_gb:.3f}GB",
                "threads": str(self._duckdb_threads),
            },
        )
        try:
            connection.execute(
                """
                CREATE TABLE source_object_catalog (
                    table_name VARCHAR NOT NULL,
                    source_path VARCHAR NOT NULL,
                    logical_path VARCHAR NOT NULL,
                    source_system VARCHAR NOT NULL,
                    dataset VARCHAR NOT NULL,
                    source_rows BIGINT,
                    source_sha256 VARCHAR NOT NULL,
                    source_format VARCHAR NOT NULL,
                    source_compression VARCHAR NOT NULL,
                    restricted BOOLEAN NOT NULL
                )
                """
            )
            logical_by_table: dict[str, str] = {}
            created_tables: set[str] = set()
            for source_object in sorted(source_objects, key=lambda row: row["path"]):
                logical_path = source_object["logicalPath"]
                table_name = self._duckdb_table_name(logical_path)
                prior_logical = logical_by_table.setdefault(table_name, logical_path)
                if prior_logical != logical_path:
                    raise ValueError(
                        "DuckDB table-name collision between "
                        f"{prior_logical!r} and {logical_path!r}"
                    )
                quoted_table = '"' + table_name.replace('"', '""') + '"'
                source_path = stage / source_object["path"]
                if source_object["format"] == "csv":
                    reader = (
                        "read_csv_auto(?, header=true, all_varchar=true, "
                        "sample_size=-1, hive_partitioning=false)"
                    )
                elif source_object["format"] == "parquet":
                    reader = "read_parquet(?, hive_partitioning=false)"
                else:
                    raise ValueError(
                        f"cannot mirror source format {source_object['format']!r}"
                    )
                if table_name not in created_tables:
                    connection.execute(
                        f"CREATE TABLE {quoted_table} AS SELECT * FROM {reader}",
                        [str(source_path)],
                    )
                    created_tables.add(table_name)
                else:
                    connection.execute(
                        f"INSERT INTO {quoted_table} BY NAME SELECT * FROM {reader}",
                        [str(source_path)],
                    )
                connection.execute(
                    "INSERT INTO source_object_catalog "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        table_name,
                        source_object["path"],
                        logical_path,
                        source_object["sourceSystem"],
                        source_object["dataset"],
                        source_object["rows"],
                        source_object["sha256"],
                        source_object["format"],
                        source_object["compression"],
                        source_object["restricted"],
                    ],
                )
            connection.execute(
                """
                CREATE TABLE source_dataset_catalog AS
                SELECT
                    table_name,
                    logical_path,
                    min(source_system) AS source_system,
                    min(dataset) AS dataset,
                    sum(source_rows) AS source_rows,
                    count(*) AS partition_count,
                    bool_or(restricted) AS restricted
                FROM source_object_catalog
                GROUP BY table_name, logical_path
                ORDER BY logical_path
                """
            )
            connection.execute(
                """
                CREATE TABLE source_schema (
                    logical_path VARCHAR NOT NULL,
                    source_system VARCHAR NOT NULL,
                    dataset VARCHAR NOT NULL,
                    restricted BOOLEAN NOT NULL,
                    ordinal_position INTEGER NOT NULL,
                    field_name VARCHAR NOT NULL,
                    physical_type VARCHAR NOT NULL,
                    nullable BOOLEAN NOT NULL
                )
                """
            )
            for logical_path in sorted(self.schemas):
                schema = self.schemas[logical_path]
                for ordinal, field in enumerate(schema["fields"], start=1):
                    connection.execute(
                        "INSERT INTO source_schema VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            logical_path,
                            schema["sourceSystem"],
                            schema["dataset"],
                            schema["restricted"],
                            ordinal,
                            field["name"],
                            field["physicalType"],
                            field["nullable"],
                        ],
                    )
            connection.execute("CHECKPOINT")
        finally:
            connection.close()
        os.replace(temp, path)
        path.chmod(0o600)
        self._register(
            path,
            source_system="generator",
            dataset="sourceRunDuckdb",
            rows=len(source_objects),
            restricted=True,
        )

    def write_duckdb_mirror(self) -> None:
        """Mirror the selected source format into one browsable DuckDB."""

        if self.reused:
            return
        started = time.perf_counter()
        source_objects = [
            dict(row)
            for row in self.objects
            if row["format"] == self._source_format
        ]
        if source_objects:
            self._write_duckdb_mirror(
                "source-run.duckdb",
                source_objects,
            )
        self.telemetry["duckdbMirrorSeconds"] = round(
            time.perf_counter() - started,
            6,
        )

    def write_source_schema(self) -> None:
        """Publish the generator-owned field dictionary for this source run."""

        if self.reused:
            return
        self.write_json(
            "source-schema.json",
            {
                "schemaVersion": "retail-source-schema/v1",
                "physicalTypePolicy": (
                    "Authoritative CSV/Parquet source fields are emitted as strings; "
                    "ingestion adapters own semantic typing."
                ),
                "datasets": [
                    self.schemas[path]
                    for path in sorted(self.schemas)
                ],
            },
            source_system="generator",
            dataset="sourceSchema",
        )

    def promote(self) -> Path:
        if self.reused:
            return self.target
        self.clear_work()
        stage = self._require_stage()
        backup: Path | None = None
        if self.target.exists():
            backup = self.target.with_name(f".{self.target.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(self.target, backup)
        os.replace(stage, self.target)
        self._stage = None
        if backup is not None:
            shutil.rmtree(backup)
        return self.target

    def abort(self) -> None:
        self.clear_work()
        if self._stage is not None and self._stage.exists():
            shutil.rmtree(self._stage)
            self._stage = None

    def clear_work(self) -> None:
        for spool in self._spools:
            spool.close()
        self._spools = []
        if self._stage is not None:
            shutil.rmtree(self._stage / ".work", ignore_errors=True)
