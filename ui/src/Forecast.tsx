import {useMemo, useState} from "react";
import {
  FORECAST_HEALTH_ACCURACY_TARGETS,
  FORECAST_HEALTH_DISPLAY_HORIZONS,
  FORECAST_HEALTH_FALLBACK_STATUS,
  FORECAST_HEALTH_TIERS,
  FORECAST_HEALTH_UNAVAILABLE_STATUS,
  type ForecastHealthGrain,
  type ForecastHealthStatus
} from "./generated/forecastHealthPolicy";
import {useQuery} from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable
} from "@tanstack/react-table";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  loadForecastActuals,
  loadForecastDrivers,
  loadForecastHorizons,
  loadForecastSignals,
  loadForecastStores,
  loadForecastSummary,
  loadForecastVersions,
  loadForecastWorkbench,
  type Dashboard,
  type ForecastFilters,
  type ForecastWorkbench
} from "./api";

type ForecastRow = ForecastWorkbench["items"][number];
type Tab = "Overview" | "Store View" | "SKU View" | "Demand Drivers" | "Governance";
type Modal = "actions" | "stores" | "versions" | null;

const tabs: Tab[] = [
  "Overview",
  "Store View",
  "SKU View",
  "Demand Drivers",
  "Governance"
];

const driverOrder = [
  "demand_trend",
  "promo",
  "seasonality",
  "price",
  "competitor_activity",
  "weather_local_events"
];

const driverLabels: Record<string, string> = {
  demand_trend: "Base demand trend",
  promo: "Promotion plan",
  seasonality: "Seasonality",
  price: "Price movement",
  competitor_activity: "Competitor availability",
  weather_local_events: "Weather and local events"
};

const exceptionLabels: Record<string, string> = {
  high_under_forecast_risk: "High under-forecast risk",
  high_over_forecast_risk: "High over-forecast risk",
  new_product_sparse_history: "New product / sparse history",
  promotion_uplift_conflict: "Promotion uplift conflict",
  data_quality_exception: "Data-quality exception"
};

function available(value: number | null | undefined, formatter: (value: number) => string) {
  return value === null || value === undefined || Number.isNaN(value)
    ? "Not available"
    : formatter(value);
}

function count(value: number | null | undefined) {
  return available(value, (number) => new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0
  }).format(number));
}

function percentage(value: number | null | undefined, signed = false) {
  return available(value, (number) =>
    `${signed && number > 0 ? "+" : ""}${number.toFixed(1)}%`
  );
}

function ratioPercentage(value: number | null | undefined, signed = false) {
  return percentage(value === null || value === undefined ? value : value * 100, signed);
}

/**
 * Rupees in the reference's own notation: crore, then lakh. Minor units in,
 * market-local out. The read model has already converted to the reporting
 * currency, so nothing is converted here.
 */
function money(minor: number | null | undefined): string | null {
  if (minor === null || minor === undefined) return null;
  const major = minor / 100;
  if (major >= 1e7) return `\u20B9${(major / 1e7).toFixed(2)} Cr`;
  if (major >= 1e5) return `\u20B9${(major / 1e5).toFixed(2)}L`;
  return `\u20B9${major.toLocaleString("en-IN", {maximumFractionDigits: 0})}`;
}

function storeLabel(name: string, city: string) {
  return name.toLocaleLowerCase().includes(city.toLocaleLowerCase())
    ? name
    : `${name}, ${city}`;
}

function shortDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  }).format(new Date(`${value}T00:00:00Z`));
}

function unavailable(title: string) {
  return <span className="unavailable" title={title}>Not available</span>;
}

/**
 * Decision #77 grain resolution: first matching rule wins. A channel filter
 * never changes the target grain.
 */
function resolveHealthGrain(input: {
  seriesKeySelected: boolean;
  storeSelected: boolean;
  categorySelected: boolean;
}): ForecastHealthGrain {
  if (input.seriesKeySelected) {
    return "series_key";
  }
  if (input.storeSelected || input.categorySelected) {
    return "store_category";
  }
  return "market_portfolio";
}

/**
 * Decision #80 status matrix: ordered tiers, all conditions required within a
 * tier, and any unavailable metric yields unavailable rather than a badge.
 * Accuracy and bias are percentage points; coverage is a ratio.
 */
function resolveHealthStatus(
  grain: ForecastHealthGrain,
  horizon: number,
  accuracyPct: number | null,
  biasPct: number | null,
  coverageRatio: number | null
): ForecastHealthStatus {
  if (accuracyPct === null || biasPct === null || coverageRatio === null) {
    return FORECAST_HEALTH_UNAVAILABLE_STATUS;
  }
  const target = FORECAST_HEALTH_ACCURACY_TARGETS[grain][horizon];
  if (target === undefined) {
    return FORECAST_HEALTH_UNAVAILABLE_STATUS;
  }
  const margin = accuracyPct - target;
  const absoluteBias = Math.abs(biasPct);
  for (const tier of FORECAST_HEALTH_TIERS) {
    if (margin < tier.accuracyVsTargetMinPoints) {
      continue;
    }
    if (absoluteBias > tier.absoluteBiasMaxPct) {
      continue;
    }
    if (
      coverageRatio < tier.coverageMinRatio ||
      coverageRatio > tier.coverageMaxRatio
    ) {
      continue;
    }
    return tier.status;
  }
  return FORECAST_HEALTH_FALLBACK_STATUS;
}

function statusBadge(value: string) {
  const label = value.length > 0
    ? `${value.charAt(0).toUpperCase()}${value.slice(1).toLowerCase()}`
    : value;
  const style = label === "Good" || label === "Active" || label === "Healthy"
    || label === "Strong"
    ? "b-green"
    : label === "Issue" || label === "High"
      ? "b-red"
      : "b-amber";
  return <span className={`badge ${style}`}>{label}</span>;
}

function Card({
  title,
  link,
  children,
  className = ""
}: {
  title: string;
  link?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <div className="card-head">
        <h3>{title}</h3>
        {link && <span>{link}</span>}
      </div>
      {children}
    </section>
  );
}

function SimpleRows({
  rows
}: {
  rows: Array<{label: string; value: React.ReactNode}>;
}) {
  return (
    <div className="metric-rows">
      {rows.map((row) => (
        <div className="metric-row" key={row.label}>
          <span>{row.label}</span>
          <strong>{row.value}</strong>
        </div>
      ))}
    </div>
  );
}

function ForecastModal({
  modal,
  onClose,
  summary,
  stores,
  version
}: {
  modal: Modal;
  onClose: () => void;
  summary?: ReturnType<typeof useForecastData>["summary"];
  stores?: ReturnType<typeof useForecastData>["stores"];
  version?: ReturnType<typeof useForecastData>["versions"];
}) {
  if (!modal) return null;
  const title = modal === "actions"
    ? "Forecast Action Center"
    : modal === "stores"
      ? "Open Store Drilldown"
      : "Compare Versions";
  const summaryItem = summary?.items[0];
  const versionItem = version?.items[0];
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section className="modal forecast-modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div>
            <h3>{title}</h3>
            <p>Live accepted forecast • {summary?.versionId ?? "Loading"}</p>
          </div>
          <button className="modal-close" type="button" aria-label={`Close ${title}`} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body">
          {modal === "actions" && (
            <SimpleRows rows={Object.entries(summaryItem?.exceptionCounts ?? {}).map(
              ([key, value]) => ({
                label: exceptionLabels[key] ?? key.replaceAll("_", " "),
                value: count(value)
              })
            )} />
          )}
          {modal === "stores" && (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr><th>Store</th><th>Accuracy</th><th>Bias</th><th>P90 Coverage</th></tr>
                </thead>
                <tbody>
                  {(stores?.items ?? []).map((store) => (
                    <tr key={store.storeId}>
                      <td>{storeLabel(store.name, store.city)}</td>
                      <td>{percentage(store.accuracy)}</td>
                      <td>{ratioPercentage(store.bias, true)}</td>
                      <td>{ratioPercentage(store.p90Coverage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {modal === "versions" && (
            <table className="table">
              <thead>
                <tr><th>Version</th><th>Model</th><th>Accuracy</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Baseline</td>
                  <td>MA13</td>
                  <td>{percentage(summaryItem?.baselineAccuracy)}</td>
                  <td>{statusBadge("Reference")}</td>
                </tr>
                <tr>
                  <td>{versionItem?.versionId ?? "Current"}</td>
                  <td>Active AI</td>
                  <td>{percentage(summaryItem?.accuracy)}</td>
                  <td>{statusBadge("Active")}</td>
                </tr>
                <tr>
                  <td>Prior accepted</td>
                  <td>{unavailable("A second comparable accepted version is required")}</td>
                  <td>{unavailable("A second comparable accepted version is required")}</td>
                  <td>{unavailable("A second comparable accepted version is required")}</td>
                </tr>
                <tr>
                  <td>Planner adjusted</td>
                  <td>{unavailable("Planner workflow belongs to Phase 6")}</td>
                  <td>{unavailable("Planner workflow belongs to Phase 6")}</td>
                  <td>{unavailable("Planner workflow belongs to Phase 6")}</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
        <div className="modal-foot">
          <button className="modal-action" type="button" onClick={onClose}>Close</button>
        </div>
      </section>
    </div>
  );
}

function useForecastData(filters: ForecastFilters) {
  const summary = useQuery({
    queryKey: ["forecast-summary"],
    queryFn: loadForecastSummary
  });
  const actuals = useQuery({
    queryKey: ["forecast-actuals", filters],
    queryFn: () => loadForecastActuals(filters)
  });
  const horizons = useQuery({
    queryKey: ["forecast-horizons", filters],
    queryFn: () => loadForecastHorizons(filters)
  });
  const stores = useQuery({
    queryKey: ["forecast-stores", filters],
    queryFn: () => loadForecastStores(filters)
  });
  const workbench = useQuery({
    queryKey: ["forecast-workbench", filters],
    queryFn: () => loadForecastWorkbench(filters)
  });
  const drivers = useQuery({
    queryKey: ["forecast-drivers"],
    queryFn: loadForecastDrivers
  });
  const signals = useQuery({
    queryKey: ["forecast-signals"],
    queryFn: loadForecastSignals
  });
  const versions = useQuery({
    queryKey: ["forecast-versions"],
    queryFn: loadForecastVersions
  });
  return {
    pending: [
      summary,
      actuals,
      horizons,
      stores,
      workbench,
      drivers,
      signals,
      versions
    ].some((query) => query.isPending),
    error: [
      summary,
      actuals,
      horizons,
      stores,
      workbench,
      drivers,
      signals,
      versions
    ].find((query) => query.error)?.error,
    summary: summary.data,
    actuals: actuals.data,
    horizons: horizons.data,
    stores: stores.data,
    workbench: workbench.data,
    drivers: drivers.data,
    signals: signals.data,
    versions: versions.data
  };
}

const columnHelper = createColumnHelper<ForecastRow>();

function WorkbenchTable({rows}: {rows: ForecastRow[]}) {
  const columns = useMemo(() => [
    columnHelper.display({
      id: "select",
      header: () => <input type="checkbox" aria-label="Select all forecast rows" />,
      cell: ({row}) => <input type="checkbox" aria-label={`Select ${row.original.skuId}`} />
    }),
    columnHelper.accessor("priority", {
      header: "Priority",
      cell: (info) => statusBadge(info.getValue())
    }),
    columnHelper.accessor("productName", {
      header: "SKU / Product",
      cell: ({row}) => (
        <span className="product-cell">
          <strong>{row.original.productName}</strong>
          <small>{row.original.skuId}</small>
        </span>
      )
    }),
    columnHelper.accessor("storeName", {
      header: "Store",
      // A workbench row's identity is sku x store x channel. Showing only two of
      // the three made every pair look duplicated: each SKU legitimately appears
      // once online and once in-store, and 61 product names cover more than one
      // SKU variant. The channel goes on a second line rather than in a new column
      // because it is part of this cell's identity, not a separate fact.
      cell: ({row}) => (
        <span className="product-cell">
          <strong>{storeLabel(row.original.storeName, row.original.storeCity)}</strong>
          <small>{row.original.channelType === "online" ? "E-commerce" : "Store"}</small>
        </span>
      )
    }),
    columnHelper.accessor("baseline", {
      header: "Baseline",
      cell: (info) => count(info.getValue())
    }),
    columnHelper.accessor("aiForecast", {
      header: "AI Forecast",
      cell: (info) => count(info.getValue())
    }),
    columnHelper.accessor("plannerForecast", {
      header: "Planner Forecast",
      cell: () => unavailable("Planner workflow belongs to Phase 6")
    }),
    columnHelper.accessor("lastActual", {
      header: "Last Actual",
      cell: ({row}) => (
        <span className="product-cell">
          <strong>{count(row.original.lastActual)}</strong>
          <small>{row.original.lastActualWeek ? shortDate(row.original.lastActualWeek) : ""}</small>
        </span>
      )
    }),
    columnHelper.accessor("accuracy", {
      header: "Accuracy",
      // A SeriesKey accuracy of -1049% is not a weak number, it is an
      // uninterpretable one. When absolute error exceeds total demand the
      // percentage is withheld upstream and the row says so instead, which also
      // marks exactly the rows a planner should look at.
      cell: (info) => {
        const value = info.getValue();
        const share = info.row.original.demandSharePct;
        const shareLabel = share === null || share === undefined
          ? null
          : `${share.toFixed(2)}% of demand`;
        if (value === null || value === undefined) {
          const state = info.row.original.accuracyState;
          return state === "error_exceeds_demand"
            ? unavailable("Absolute error exceeds total demand; accuracy is outside 0-100 at this grain")
            : unavailable("No positive demand in the evaluation window");
        }
        return (
          <span className="product-cell">
            <strong>{percentage(value)}</strong>
            {shareLabel ? <small>{shareLabel}</small> : null}
          </span>
        );
      }
    }),
    columnHelper.accessor("bias", {
      header: "Bias",
      cell: (info) => ratioPercentage(info.getValue(), true)
    }),
    columnHelper.accessor("confidence", {
      header: "Confidence",
      // Decision #64 Q19 / parity amendment P4-0P-A1.
      //
      // Confidence is derived from the P90 interval, and decision #92 publishes
      // the cold-start interval only through h4 while P50 continues to h26. The
      // selected window is cumulative from h1, so 8, 13 and 26 weeks mix
      // horizons that carry an interval with horizons that do not, and only the
      // 4-week default is clean.
      //
      // The server already restricts the weighted mean to the weeks that carry
      // an interval, so the number reaching here is arithmetically correct. It is
      // still not shown for a mixed window: an h1-h4 figure under a column headed
      // "Confidence", beside forecast values covering the whole selection, states
      // a scope this table never displays. That is the failure decision #78 exists
      // to prevent, so the cell takes the approved unavailable state and names the
      // window it would have covered.
      cell: (info) => {
        const row = info.row.original;
        if (row.confidenceState === "unavailable_mixed_window") {
          const covered = row.intervalCoveredThroughHorizon;
          const scope = covered === null || covered === undefined
            ? "the calibrated horizons only"
            : `weeks 1-${covered} only`;
          return unavailable(
            `Confidence covers ${scope} of the selected ${row.horizonWeeks}-week ` +
            `window; ${row.intervalWithheldWeeks} week(s) have no calibrated ` +
            "interval, so a single figure would misstate its scope"
          );
        }
        return ratioPercentage(info.getValue());
      }
    }),
    columnHelper.accessor("primaryDriver", {
      header: "Primary Driver",
      cell: (info) => driverLabels[info.getValue() ?? ""] ?? info.getValue() ?? "Not available"
    }),
    columnHelper.accessor("dataQuality", {
      header: "Data Quality",
      cell: (info) => statusBadge(info.getValue())
    }),
    columnHelper.accessor("status", {
      header: "Status",
      cell: (info) => statusBadge(info.getValue())
    })
  ], []);
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel()
  });
  return (
    <div className="table-scroll forecast-workbench-scroll">
      <table className="table forecast-workbench" id="forecastWorkbenchTable">
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Overview({
  data,
  healthGrain,
  granularity,
  setModal
}: {
  data: ReturnType<typeof useForecastData>;
  healthGrain: ForecastHealthGrain;
  granularity: string;
  setModal: (modal: Modal) => void;
}) {
  const summary = data.summary!.items[0];
  const chartData = granularity === "Monthly"
    ? Object.values(data.actuals!.items.reduce<Record<string, {
      week: string;
      forecast: number;
      actual: number;
    }>>((months, item) => {
      const month = item.targetWeekStart.slice(0, 7);
      const existing = months[month] ?? {week: month, forecast: 0, actual: 0};
      existing.forecast += item.forecast;
      existing.actual += item.actual;
      months[month] = existing;
      return months;
    }, {}))
    : data.actuals!.items.map((item) => ({
      week: shortDate(item.targetWeekStart),
      forecast: item.forecast,
      actual: item.actual
    }));
  // Decision #80: exactly four exact-horizon rows in reference order, always
  // rendered. The operational horizon selector changes future scope, not which
  // diagnostic rows exist, so it must not filter this table.
  const horizonRows = FORECAST_HEALTH_DISPLAY_HORIZONS.map((checkpoint) => {
    const exact = data.horizons!.items.find((item) => item.horizon === checkpoint);
    const actual = exact?.actualSum ?? 0;
    const accuracy = exact && actual ? 100 * (1 - exact.absErrorSum / actual) : null;
    const bias = exact && actual ? exact.signedErrorSum / actual : null;
    const coverage = exact && exact.n ? exact.coverageHits / exact.n : null;
    return {
      checkpoint,
      accuracy,
      bias,
      coverage,
      status: resolveHealthStatus(
        healthGrain,
        checkpoint,
        accuracy,
        bias === null ? null : bias * 100,
        coverage
      )
    };
  });
  const exceptionRows = [
    "high_under_forecast_risk",
    "high_over_forecast_risk",
    "new_product_sparse_history",
    "promotion_uplift_conflict",
    "data_quality_exception"
  ];
  return (
    <>
      <div className="grid-2">
        <Card title="Forecast vs Actual" link={`Last 8 ${granularity === "Monthly" ? "weeks by month" : "weeks"}`}>
          <div className="chart-box" aria-label="Forecast versus actual chart">
            <ResponsiveContainer width="100%" height={270}>
              <BarChart data={chartData} margin={{top: 12, right: 8, bottom: 4, left: 0}}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="week" fontSize={11} />
                <YAxis fontSize={11} tickFormatter={(value) =>
                  new Intl.NumberFormat("en-US", {notation: "compact"}).format(Number(value))
                } />
                <Tooltip formatter={(value) => count(Number(value))} />
                <Legend />
                <Bar dataKey="forecast" name="Forecast" fill="#2f80ed" radius={[4, 4, 0, 0]} />
                <Bar dataKey="actual" name="Actual" fill="#1fbf75" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Forecast Health by Horizon" link="Accuracy and bias">
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>Horizon</th><th>Accuracy</th><th>Bias</th><th>Coverage</th><th>Status</th></tr>
              </thead>
              <tbody>
                {horizonRows.map((row) => (
                  <tr key={row.checkpoint} data-horizon={row.checkpoint}>
                    <td>{row.checkpoint === 1 ? "1 week" : `${row.checkpoint} weeks`}</td>
                    <td>{percentage(row.accuracy)}</td>
                    <td>{ratioPercentage(row.bias, true)}</td>
                    <td>{ratioPercentage(row.coverage)}</td>
                    <td>{row.status === "unavailable"
                      ? <span className="muted">Not available</span>
                      : statusBadge(row.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <div className="grid-3">
        <Card title="Forecast Exceptions" link="Current cycle">
          <SimpleRows rows={exceptionRows.map((key) => ({
            label: exceptionLabels[key],
            value: key === "promotion_uplift_conflict"
              ? unavailable("No origin-visible promotion plan exists on the active input pin")
              : count(summary.exceptionCounts[key] ?? 0)
          }))} />
          <button className="link-button card-link" type="button" onClick={() => setModal("actions")}>
            Open Action Center
          </button>
        </Card>
        <Card title="Forecast Value Add" link="AI vs baseline">
          <SimpleRows rows={[
            // Portfolio grain, matching the KPI cards and the footer. Reading a
            // leaf-grain 72.3 beside a portfolio-grain 93.8 for what a viewer takes
            // to be the same quantity is the confusion this removes. Net FVA falls
            // to +25.3 as a result, because MA13 gains from aggregation too.
            {
              label: "Statistical baseline accuracy",
              value: percentage(summary.portfolioBaselineAccuracy ?? summary.baselineAccuracy)
            },
            {
              label: "AI forecast accuracy",
              value: percentage(summary.portfolioAccuracy ?? summary.accuracy)
            },
            {label: "Planner-adjusted accuracy", value: unavailable("Planner workflow belongs to Phase 6")},
            {
              label: "Net FVA",
              value: percentage(summary.portfolioFvaVsMa13Pct ?? summary.fvaVsMa13Pct, true)
            },
            {label: "Overrides adding value", value: unavailable("Planner workflow belongs to Phase 6")}
          ]} />
        </Card>
        <Card title="Business Impact" link="Projected">
          <SimpleRows rows={[
            "Stock-out reduction",
            "Excess inventory reduction",
            "Markdown reduction",
            "Working capital release",
            "Service-level improvement"
          ].map((label) => ({
            label,
            value: unavailable("Business-impact measures belong to Phase 4")
          }))} />
        </Card>
      </div>
    </>
  );
}

function StoreView({
  data,
  setModal
}: {
  data: ReturnType<typeof useForecastData>;
  setModal: (modal: Modal) => void;
}) {
  return (
    <Card title="Store Forecast Performance" link="Filter-scoped">
      <div className="card-toolbar">
        <span>{count(data.stores!.items.length)} current stores</span>
        <button id="storeForecastDrilldownBtn" className="btn secondary" type="button" onClick={() => setModal("stores")}>
          Open Store Drilldown
        </button>
      </div>
      <div className="table-scroll">
        <table className="table" id="storeForecastTable">
          <thead>
            <tr>
              <th>Store</th><th>Forecast Accuracy</th><th>Bias</th>
              <th>Demand at Risk</th><th>Stock-out Risk</th><th>Override Rate</th><th>Priority Action</th>
            </tr>
          </thead>
          <tbody>
            {data.stores!.items.map((store) => (
              <tr key={store.storeId}>
                <td><strong>{storeLabel(store.name, store.city)}</strong></td>
                <td>{percentage(store.accuracy)}</td>
                <td>{ratioPercentage(store.bias, true)}</td>
                <td>{money(store.demandAtRiskMinor)
                  ?? unavailable("No costed risk row for this store")}</td>
                <td>{store.stockoutRisk
                  ? <span className={`badge ${
                      store.stockoutRisk === "High" ? "b-red"
                        : store.stockoutRisk === "Medium" ? "b-amber" : "b-green"
                    }`}>{store.stockoutRisk}</span>
                  : unavailable("No health row for this store")}</td>
                <td>{unavailable("Planner workflow belongs to Phase 6")}</td>
                <td>{unavailable("No priority-action business rule is frozen")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SkuView({data}: {data: ReturnType<typeof useForecastData>}) {
  return (
    <Card title="SKU-Store Forecast Workbench" link="Current accepted version">
      <div className="record-count" id="forecastRecordCount">
        Showing {count(data.workbench!.items.length)} of {count(data.workbench!.pagination.total)} records
      </div>
      <WorkbenchTable rows={data.workbench!.items} />
    </Card>
  );
}

function DriversView({data}: {data: ReturnType<typeof useForecastData>}) {
  const liveDrivers = new Map(
    data.drivers!.items
      .filter((item) => item.driver !== "croston_routing_explanation")
      .map((item) => [item.driver, item])
  );
  return (
    <div className="grid-2 drivers-grid">
      <Card title="Demand Driver Contribution" link="Portfolio level">
        <table className="table">
          <thead>
            <tr><th>Driver</th><th>Contribution</th><th>Direction</th><th>Confidence</th></tr>
          </thead>
          <tbody>
            {driverOrder.map((driver) => {
              const item = liveDrivers.get(driver);
              return (
                <tr key={driver}>
                  <td>{driverLabels[driver]}</td>
                  <td>{item ? `${Number(item.contributionPct).toFixed(1)}%` : unavailable("No origin-visible promotion plan exists")}</td>
                  <td>{item ? item.direction : unavailable("No origin-visible promotion plan exists")}</td>
                  <td>{item ? ratioPercentage(Number(item.confidence)) : unavailable("No origin-visible promotion plan exists")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="footnote">Five live contributions renormalize to 100%. Promotion is excluded.</p>
      </Card>
      <Card title="External Signal Readiness" link="At decision time">
        <SimpleRows rows={data.signals!.items.map((signal) => ({
          label: signal.label,
          value: signal.knownAsOf
            ? signal.knownAsOf
            : unavailable(
              signal.reasonCode === "NO_ORIGIN_VISIBLE_PROMOTION_PLAN"
                ? "No origin-visible promotion plan exists"
                : "Signal freshness is not materialized"
            )
        }))} />
        <p className="footnote">
          Freshness baseline: {new Date(data.signals!.freshnessBaseline).toLocaleString("en-US", {
            timeZone: "UTC",
            dateStyle: "medium",
            timeStyle: "short"
          })} UTC
        </p>
      </Card>
    </div>
  );
}

function GovernanceView({data}: {data: ReturnType<typeof useForecastData>}) {
  const summary = data.summary!.items[0];
  return (
    <div className="grid-2">
      <Card title="Forecast Approval & SLA">
        <div className="empty-panel">
          <strong>Not available</strong>
          <span>Approval workflow and SLA ownership belong to Phase 6.</span>
        </div>
      </Card>
      <Card title="Model & Data Controls">
        <SimpleRows rows={[
          {label: "Forecast version traceability", value: statusBadge("Good")},
          {label: "Planner override comments", value: unavailable("Planner workflow belongs to Phase 6")},
          {label: "Data freshness compliance", value: unavailable("Signal freshness timestamps are not materialized")},
          {label: "Model drift within tolerance", value: unavailable("A second comparable accepted version is required")},
          {label: "Back-testing coverage", value: percentage(summary.backtestCoveragePct)}
        ]} />
        <p className="fingerprint" title={data.summary!.semanticFingerprint}>
          Semantic fingerprint: {data.summary!.semanticFingerprint.slice(0, 16)}…
        </p>
      </Card>
    </div>
  );
}

export function DemandForecast({
  dashboard,
  storeId,
  onStoreId,
  channelType
}: {
  dashboard: Dashboard;
  storeId: string;
  onStoreId: (value: string) => void;
  channelType: string;
}) {
  const [region, setRegion] = useState("");
  const [category, setCategory] = useState("");
  const [horizonWeeks, setHorizonWeeks] = useState(4);
  const [granularity, setGranularity] = useState("Weekly");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("Overview");
  const [modal, setModal] = useState<Modal>(null);
  const selectedStore = dashboard.filters.stores.find((store) => store.storeId === storeId);
  const filters = useMemo<ForecastFilters>(() => ({
    marketId: selectedStore?.marketId,
    region,
    storeId,
    channelType,
    category,
    search: search.trim(),
    horizonWeeks
  }), [selectedStore?.marketId, region, storeId, channelType, category, search, horizonWeeks]);
  const data = useForecastData(filters);
  // Decision #77 grain resolution. A channel filter never changes the grain, and
  // this screen never selects a single complete SeriesKey, so the resolved grain
  // is market/portfolio by default and store/category once one is chosen.
  // The API resolves the same decision #77 rules server-side and returns the grain
  // it actually measured at. Prefer that value: two independent implementations of
  // the same rule set is how a 95.18% portfolio number came to be displayed
  // against a 90% target as 78.27%. The local resolution stays as the pre-response
  // fallback and as a cross-check that the two agree.
  const localHealthGrain = useMemo(() => resolveHealthGrain({
    seriesKeySelected: false,
    storeSelected: storeId !== "",
    categorySelected: category !== ""
  }), [storeId, category]);
  const healthGrain = data.horizons?.metricGrain ?? localHealthGrain;
  const regions = [...new Set(dashboard.filters.stores.map((store) => store.region))].sort();
  const summary = data.summary?.items[0];
  const scopedMetrics = useMemo(() => {
    const rows = data.horizons?.items.filter((item) => item.horizon <= horizonWeeks) ?? [];
    const actual = rows.reduce((sum, row) => sum + row.actualSum, 0);
    const absError = rows.reduce((sum, row) => sum + row.absErrorSum, 0);
    const signedError = rows.reduce((sum, row) => sum + row.signedErrorSum, 0);
    return {
      accuracy: actual ? 100 * (1 - absError / actual) : null,
      bias: actual ? 100 * signedError / actual : null
    };
  }, [data.horizons?.items, horizonWeeks]);

  // Derived from the live selector and the grain the API reports, never hard-coded, so
  // the label cannot drift from the number beside it.
  const metricScopeLabel = `h1–h${horizonWeeks}, ${
    (data.horizons?.metricGrain ?? "market_portfolio").replace(/_/g, " ")
  }`;

  function exportWorkbench() {
    if (!data.workbench?.items.length) return;
    // The export carries confidence too, so it inherits decision #64 Q19: a
    // mixed-window row exports an empty confidence and states its scope in its
    // own columns. Writing the h1-h4 figure into a column headed `confidence`
    // beside a whole-window `ai_forecast` would reintroduce the defect in a file
    // that outlives the screen and carries no tooltip to qualify it.
    const headings = [
      "sku_id", "product_name", "store", "channel", "category", "horizon_weeks",
      "baseline", "ai_forecast", "last_actual", "accuracy", "bias", "confidence",
      "confidence_state", "interval_covered_through_horizon",
      "interval_withheld_weeks",
      "primary_driver", "data_quality", "status"
    ];
    const rows = data.workbench.items.map((row) => [
      row.skuId,
      row.productName,
      storeLabel(row.storeName, row.storeCity),
      row.channelId,
      row.category,
      row.horizonWeeks,
      row.baseline,
      row.aiForecast,
      row.lastActual,
      row.accuracy,
      row.bias,
      row.confidenceState === "unavailable_mixed_window" ? null : row.confidence,
      row.confidenceState,
      row.intervalCoveredThroughHorizon,
      row.intervalWithheldWeeks,
      row.primaryDriver,
      row.dataQuality,
      row.status
    ]);
    const csv = [headings, ...rows].map((row) =>
      row.map((value) => `"${String(value ?? "").replaceAll("\"", "\"\"")}"`).join(",")
    ).join("\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = `demand-forecast-${data.summary?.versionId ?? "active"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (data.error) {
    return (
      <div className="state-card error-state">
        <strong>Live forecast data is unavailable.</strong>
        <span>{String(data.error)}</span>
        <small>No sample or fallback values are displayed.</small>
      </div>
    );
  }
  if (data.pending || !data.summary || !data.actuals || !data.horizons ||
    !data.stores || !data.workbench || !data.drivers || !data.signals || !data.versions) {
    return <div className="state-card">Loading the accepted forecast…</div>;
  }

  return (
    <div id="demandForecast">
      <div className="action-toolbar" aria-label="Forecast actions">
        <button id="acceptForecastBtn" className="btn primary" type="button" disabled aria-disabled="true" title="Forecast acceptance workflow belongs to Phase 6">Accept Forecast</button>
        <button id="addForecastAdjustmentBtn" className="btn secondary" type="button" disabled aria-disabled="true" title="Planner adjustment workflow belongs to Phase 6">Add Planner Adjustment</button>
        <button id="compareForecastVersionsBtn" className="btn secondary" type="button" onClick={() => setModal("versions")}>Compare Versions</button>
        <button id="forecastScenarioBtn" className="btn secondary" type="button" disabled aria-disabled="true" title="Scenario Planning belongs to Phase 5">Scenario Planning</button>
        <button id="forecastActionCenterBtn" className="btn secondary" type="button" onClick={() => setModal("actions")}>Forecast Action Center</button>
        <button id="exportForecastBtn" className="btn secondary" type="button" onClick={exportWorkbench}>Export</button>
      </div>

      <div className="forecast-filter-toolbar">
        <select id="forecastRegionFilter" className="filter" aria-label="Forecast region" value={region} onChange={(event) => setRegion(event.target.value)}>
          <option value="">All Regions</option>
          {regions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select id="forecastStoreFilter" className="filter" aria-label="Forecast store" value={storeId} onChange={(event) => onStoreId(event.target.value)}>
          <option value="">All Stores</option>
          {dashboard.filters.stores.map((store) => (
            <option key={store.storeId} value={store.storeId}>{storeLabel(store.name, store.city)}</option>
          ))}
        </select>
        <select id="forecastCategoryFilter" className="filter" aria-label="Forecast category" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">All Categories</option>
          {summary!.categories.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select id="forecastHorizonFilter" className="filter" aria-label="Forecast horizon" value={horizonWeeks} onChange={(event) => setHorizonWeeks(Number(event.target.value))}>
          {[4, 8, 13, 26].map((value) => <option key={value} value={value}>Next {value} Weeks</option>)}
        </select>
        <select id="forecastGranularityFilter" className="filter" aria-label="Forecast granularity" value={granularity} onChange={(event) => setGranularity(event.target.value)}>
          <option>Weekly</option>
          <option disabled>Daily</option>
          <option>Monthly</option>
        </select>
        <input id="forecastSearch" className="filter search-filter" aria-label="Forecast search" placeholder="Search product, SKU or store" value={search} onChange={(event) => setSearch(event.target.value)} />
      </div>

      <div className="kpi-grid forecast-kpis">
        {/* Both tiles are scoped to the selected horizon window, while the Forecast
            Value Add card and the footer Model Accuracy report the full 26-week panel.
            Every figure is correct, but unlabelled they read as a contradiction: 93.8%
            beside 92.8% with nothing saying why. Decision #78 requires the exact grain
            and horizon to be labelled, and these were the only cells on the screen
            without it. Bias makes it more than cosmetic -- -2.1% over h1-h4 against a
            stated +/-5% target becomes -5.4% over h1-h26, so an unlabelled tile can read
            as passing a target the full panel does not. */}
        <div className="kpi">
          <small>Forecast Accuracy</small>
          <div className="value">{percentage(scopedMetrics.accuracy)}</div>
          <span className="delta unavailable">Delta: Not available</span>
          <p>Target: 90% · {metricScopeLabel}</p>
        </div>
        <div className="kpi">
          <small>Forecast Bias</small>
          <div className="value">{percentage(scopedMetrics.bias, true)}</div>
          <span className="delta unavailable">Delta: Not available</span>
          <p>Target range: ±5% · {metricScopeLabel}</p>
        </div>
        <div className="kpi">
          <small>Demand at Risk</small>
          <div className="value">
            {money(summary?.demandAtRiskMinor)
              ?? <span className="unavailable">Not available</span>}
          </div>
          <span className="delta down">
            {summary?.demandAtRiskCells?.toLocaleString("en-US") ?? "0"} SKU-store combinations
          </span>
          <p>Potential lost-sales exposure · Phase 4 inventory measure</p>
        </div>
        <div className="kpi"><small>Planner Overrides</small><div className="value unavailable">Not available</div><p>Available in Phase 6</p></div>
        <div className="kpi">
          <small>Forecast Value Add</small>
          {/* Portfolio grain, same as the Forecast Value Add card below. Two FVA
              figures on one screen must not disagree. */}
          <div className="value">
            {percentage(summary!.portfolioFvaVsMa13Pct ?? summary!.fvaVsMa13Pct, true)}
          </div>
          <p>Relative improvement vs MA13</p>
        </div>
      </div>

      <div className="forecast-tabs" id="forecastTabs" role="tablist" aria-label="Demand forecast views">
        {tabs.map((item) => (
          <button
            key={item}
            className={tab === item ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={tab === item}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <section className="forecast-panel" role="tabpanel">
        {tab === "Overview" && <Overview data={data} healthGrain={healthGrain} granularity={granularity} setModal={setModal} />}
        {tab === "Store View" && <StoreView data={data} setModal={setModal} />}
        {tab === "SKU View" && <SkuView data={data} />}
        {tab === "Demand Drivers" && <DriversView data={data} />}
        {tab === "Governance" && <GovernanceView data={data} />}
      </section>
      <ForecastModal
        modal={modal}
        onClose={() => setModal(null)}
        summary={data.summary}
        stores={data.stores}
        version={data.versions}
      />
    </div>
  );
}
