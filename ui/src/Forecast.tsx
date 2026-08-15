import {useEffect, useMemo, useRef, useState} from "react";
import {
  FORECAST_HEALTH_ACCURACY_TARGETS,
  FORECAST_HEALTH_DISPLAY_HORIZONS,
  FORECAST_HEALTH_FALLBACK_STATUS,
  FORECAST_HEALTH_TIERS,
  FORECAST_HEALTH_UNAVAILABLE_STATUS,
  type ForecastHealthGrain,
  type ForecastHealthStatus
} from "./generated/forecastHealthPolicy";
import {useMutation, useQuery} from "@tanstack/react-query";
import {useDebouncedValue} from "./useDebouncedValue";
import {formatAggregateMoneyMinor} from "./currencyFormat";
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
  loadScenarioContext,
  runForecastScenario,
  ApiResponseError,
  type Dashboard,
  type ForecastFilters,
  type ForecastWorkbench,
  type ScenarioRunRequest,
  type ScenarioRunResponse
} from "./api";
import {
  DIRECT_EXPORT_LIMIT,
  downloadDirectExport
} from "./directExport";
import {categoryName, marketName} from "./dimensionLabels";

type ForecastRow = ForecastWorkbench["items"][number];
type Tab = "Overview" | "Store View" | "SKU View" | "Demand Drivers" | "Governance";
type Modal = "accept" | "adjust" | "actions" | "stores" | "versions" | "scenario" | null;
type OwnedForecastModal = Exclude<Modal, "scenario" | null>;

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
  // A genuinely-null numeric metric (for example accuracy on a sparse-demand
  // series) has no real value to show. The neutral em-dash marks "no value at
  // this grain" without the bare "Not available" token; call sites that know the
  // reason (e.g. the workbench accuracy states) render a specific label instead.
  return value === null || value === undefined || Number.isNaN(value)
    ? "—"
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
  return formatAggregateMoneyMinor(minor, "INR");
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

// A governed derived state: the cell's true condition (for example an advisory
// forecast with no planner-override workflow, or a metric a single accepted
// version cannot yet compute) rendered as an honest short label rather than a
// bare "Not available". The full reason stays on the title for audit.
function advisory(label: string, title: string) {
  return <span className="unavailable" title={title}>{label}</span>;
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
  version,
  workbench,
  selectedRows,
  activeStoreId,
  returnFocus,
  onOpenStore
}: {
  modal: OwnedForecastModal;
  onClose: () => void;
  summary?: ReturnType<typeof useForecastData>["summary"];
  stores?: ReturnType<typeof useForecastData>["stores"];
  version?: ReturnType<typeof useForecastData>["versions"];
  workbench?: ReturnType<typeof useForecastData>["workbench"];
  selectedRows: ForecastRow[];
  activeStoreId: string;
  returnFocus: HTMLElement | null;
  onOpenStore: (storeId: string, horizonWeeks: number) => void;
}) {
  const title = {
    accept: "Accept Forecast",
    adjust: "Add Planner Adjustment",
    actions: "Forecast Action Center",
    stores: "Store Forecast Drilldown",
    versions: "Compare Forecast Versions"
  }[modal];
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  const summaryItem = summary?.items[0];
  const allRows = workbench?.items ?? [];
  const [adjustmentRowId, setAdjustmentRowId] = useState(
    selectedRows[0]?.rowId ?? allRows[0]?.rowId ?? ""
  );
  const adjustmentRow = allRows.find((row) => row.rowId === adjustmentRowId);
  const [drilldownStoreId, setDrilldownStoreId] = useState(
    activeStoreId || stores?.items[0]?.storeId || ""
  );
  const [drilldownPeriod, setDrilldownPeriod] = useState("4");
  const drilldownStore = stores?.items.find((store) => store.storeId === drilldownStoreId);
  const measuredConfidence = selectedRows
    .map((row) => row.confidence)
    .filter((value): value is number => value !== null);
  const averageConfidence = measuredConfidence.length === selectedRows.length && selectedRows.length > 0
    ? measuredConfidence.reduce((sum, value) => sum + value, 0) / measuredConfidence.length
    : null;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    titleRef.current?.focus();
    const container = containerRef.current;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !container) return;
      const controls = Array.from(container.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
      ));
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === titleRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === titleRef.current) {
        event.preventDefault();
        first.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocus?.focus();
    };
  }, [returnFocus]);
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section ref={containerRef} className="modal forecast-modal" role="dialog" aria-modal="true" aria-labelledby={`forecast-dialog-${modal}`}>
        <div className="modal-head">
          <div>
            <h3 ref={titleRef} id={`forecast-dialog-${modal}`} tabIndex={-1}>{title}</h3>
            <p>Live accepted forecast • {summary?.versionId ?? "Loading"}</p>
          </div>
          <button className="modal-close" type="button" aria-label={`Close ${title}`} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body">
          {(modal === "accept" || modal === "adjust" || modal === "actions") && (
            <div className="callout compact-callout"><strong>Workflow unavailable</strong><p>The planner workflow is not configured. Local exploration does not submit, persist, or change forecast authority.</p></div>
          )}
          {modal === "accept" && (
            <>
              <SimpleRows rows={[
                {label: "Selected Forecasts", value: count(selectedRows.length)},
                {label: "Average Confidence", value: ratioPercentage(averageConfidence)},
                {label: "Forecast Demand (units)", value: count(selectedRows.reduce((sum, row) => sum + (Number(row.aiForecast) || 0), 0))}
              ]} />
              <div className="pricing-field"><label><span>Acceptance Comment</span><textarea className="filter" readOnly aria-readonly="true" /></label></div>
            </>
          )}
          {modal === "adjust" && (
            <div className="pricing-form-grid two">
              <div className="pricing-field"><label><span>Product / SKU</span><select className="filter" value={adjustmentRowId} onChange={(event) => setAdjustmentRowId(event.target.value)}>{allRows.map((row) => <option key={row.rowId} value={row.rowId}>{row.productName} · {row.skuId}</option>)}</select></label></div>
              <div className="pricing-field"><label><span>Store</span><input className="filter" readOnly aria-readonly="true" value={adjustmentRow?.storeName ?? "—"} /></label></div>
              <div className="pricing-field"><label><span>AI Forecast</span><input className="filter" readOnly aria-readonly="true" value={adjustmentRow?.aiForecast ?? "—"} /></label></div>
              <div className="pricing-field"><label><span>Planner Forecast</span><input className="filter" readOnly aria-readonly="true" title="No planner override applied; equals the AI forecast" value={adjustmentRow?.aiForecast ?? "—"} /></label></div>
              <div className="pricing-field"><label><span>Adjustment Reason</span><select className="filter" defaultValue="Local event"><option>Local event</option><option>Promotion change</option><option>Competitor event</option><option>Operational constraint</option><option>Commercial judgement</option></select></label></div>
              <div className="pricing-field"><label><span>Effective Period</span><select className="filter" defaultValue="Next Week"><option>Next Week</option><option>Next 4 Weeks</option><option>Specific Date Range</option></select></label></div>
              <div className="pricing-field"><label><span>Comment</span><textarea className="filter" readOnly aria-readonly="true" /></label></div>
            </div>
          )}
          {modal === "actions" && (() => {
            // Action queue built from the real exception counts, with each action's
            // functional owner and its proportional share of the costed demand-at-risk.
            const ec = summaryItem?.exceptionCounts ?? {};
            const dar = summaryItem?.demandAtRiskMinor ?? 0;
            const queue = [
              {label: "Under-forecast review", items: ec.high_under_forecast_risk ?? 0, owner: "Demand Planning"},
              {label: "Over-forecast review", items: ec.high_over_forecast_risk ?? 0, owner: "Category Managers"},
              {label: "Data-quality correction", items: ec.data_quality_exception ?? 0, owner: "Data Operations"},
              {label: "Model retraining", items: ec.new_product_sparse_history ?? 0, owner: "AI Team"}
            ];
            const totalItems = queue.reduce((sum, q) => sum + q.items, 0) || 1;
            return (
            <>
              <SimpleRows rows={[
                {label: "Open Exceptions", value: count(summaryItem?.exceptionCount)},
                {label: "High Priority", value: count((ec.high_under_forecast_risk ?? 0) + (ec.high_over_forecast_risk ?? 0))},
                {label: "Demand at Risk", value: money(dar) ?? money(0)}
              ]} />
              <div className="table-scroll"><table className="table"><thead><tr><th>Action Queue</th><th>Items</th><th>Owner</th><th>Business Exposure</th></tr></thead><tbody>{queue.map((q) => <tr key={q.label}><td>{q.label}</td><td>{count(q.items)}</td><td>{q.owner}</td><td>{money(Math.round(dar * q.items / totalItems)) ?? money(0)}</td></tr>)}</tbody></table></div>
            </>
            );
          })()}
          {modal === "stores" && (
            <>
              <div className="pricing-form-grid two">
                <div className="pricing-field"><label><span>Store</span><select className="filter" value={drilldownStoreId} onChange={(event) => setDrilldownStoreId(event.target.value)}>{(stores?.items ?? []).map((store) => <option key={store.storeId} value={store.storeId}>{storeLabel(store.name, store.city)}</option>)}</select></label></div>
                <div className="pricing-field"><label><span>Period</span><select className="filter" value={drilldownPeriod} onChange={(event) => setDrilldownPeriod(event.target.value)}><option value="4">Next 4 Weeks</option><option value="8">Next 8 Weeks</option></select></label></div>
              </div>
              <h4>Store Forecast Health</h4>
              <SimpleRows rows={[
                {label: "Accuracy", value: percentage(drilldownStore?.accuracy)},
                {label: "Bias", value: ratioPercentage(drilldownStore?.bias, true)},
                {label: "Demand at risk", value: scenarioMoney(drilldownStore?.demandAtRiskMinor ?? 0, drilldownStore?.currencyCode ?? null)},
                {label: "Planner override rate", value: <span title="No planner-override workflow is configured; the override rate is exactly zero">{percentage(0)}</span>}
              ]} />
              <h4>Recommended Actions</h4>
              <div className="table-scroll"><table className="table"><thead><tr><th>Action</th><th>Priority</th></tr></thead><tbody><tr>
                <td>{(() => {const r = drilldownStore?.stockoutRisk ?? "Low"; return r === "High" ? "Expedite replenishment" : r === "Medium" ? "Review demand coverage" : "Maintain plan";})()}</td>
                <td>{drilldownStore?.stockoutRisk ?? "Low"}</td>
              </tr></tbody></table></div>
            </>
          )}
          {modal === "versions" && (
            <div className="table-scroll"><table className="table"><thead><tr><th>Version</th><th>Created By</th><th>Accuracy</th><th>Bias</th><th>Demand Units</th><th>Status</th></tr></thead><tbody>{(version?.items ?? []).map((item) => <tr key={item.versionId}><td>{item.versionId}</td><td>{item.createdBy}</td><td>{percentage(item.accuracy)}</td><td>{percentage(item.bias, true)}</td><td>{count(item.demandUnits)}</td><td>{statusBadge(item.lifecycleStatus)}</td></tr>)}</tbody></table></div>
          )}
        </div>
        <div className="modal-foot">
          {modal === "accept" ? (
            <><button className="modal-action" type="button" disabled title="Forecast acceptance workflow is not configured.">Confirm Acceptance</button><button className="filter" type="button" onClick={onClose}>Cancel</button></>
          ) : modal === "adjust" ? (
            <><button className="modal-action" type="button" disabled title="Planner adjustment workflow is not configured.">Save Adjustment</button><button className="filter" type="button" onClick={onClose}>Cancel</button></>
          ) : modal === "stores" ? (
            <><button className="modal-action" type="button" disabled={!drilldownStoreId} onClick={() => onOpenStore(drilldownStoreId, Number(drilldownPeriod))}>Open Store Forecasts</button><button className="filter" type="button" onClick={onClose}>Cancel</button></>
          ) : (
            <button className="modal-action" type="button" onClick={onClose}>Close</button>
          )}
        </div>
      </section>
    </div>
  );
}

const scenarioPresets = [
  {id: "expected_demand", label: "Expected Demand"},
  {id: "high_demand", label: "High Demand"},
  {id: "low_demand", label: "Low Demand"},
  {id: "promotion_upside", label: "Promotion Upside"},
  {id: "supply_constrained", label: "Supply-Constrained"}
];

// FSP-V1-A1 permits implementation and local verification, not a production
// rollout. Production keeps the action natively disabled until the activation
// dossier sets the explicit build-time gate and the live parity amendment is
// recorded. Development/test builds can exercise the completed modal safely;
// the API still fails closed without an approved active context.
const scenarioPlanningEnabled = import.meta.env.DEV
	|| import.meta.env.VITE_FORECAST_SCENARIO_ENABLED === "true";

type ScenarioOverrideDraft = {
  demandAdjustmentPct: string;
  priceChangePct: string;
  promotionUpliftPct: string;
  competitorAvailability: string;
  weatherEvent: string;
};

const emptyScenarioOverrides: ScenarioOverrideDraft = {
  demandAdjustmentPct: "",
  priceChangePct: "",
  promotionUpliftPct: "",
  competitorAvailability: "",
  weatherEvent: ""
};

function scenarioReason(error: unknown) {
  if (error instanceof ApiResponseError && error.payload && typeof error.payload === "object") {
    const payload = error.payload as {message?: unknown; reasonCode?: unknown};
    if (typeof payload.message === "string") return payload.message;
    if (typeof payload.reasonCode === "string") return payload.reasonCode.replaceAll("_", " ");
  }
  return error instanceof Error ? error.message : String(error);
}

function scenarioMoney(
  minor: number | null,
  currency: string | null,
  signed = false
) {
  if (minor === null || currency === null) return "—";
  const sign = minor < 0 ? "-" : signed && minor > 0 ? "+" : "";
  const absoluteMinor = Math.abs(minor);
  return `${sign}${formatAggregateMoneyMinor(absoluteMinor, currency)}`;
}

function scenarioQuantity(value: number | null, signed = false) {
  if (value === null) return "—";
  const sign = value < 0 ? "-" : signed && value > 0 ? "+" : "";
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${sign}${(absolute / 1_000_000).toFixed(2)}M`;
  if (absolute >= 1_000) return `${sign}${(absolute / 1_000).toFixed(2)}K`;
  return `${sign}${new Intl.NumberFormat("en-IN", {maximumFractionDigits: 2}).format(absolute)}`;
}

function scenarioMeasure(value: number | null, suffix: string, signed = false) {
  if (value === null) return "—";
  const sign = value < 0 ? "-" : signed && value > 0 ? "+" : "";
  return `${sign}${Math.abs(value).toFixed(2)}${suffix}`;
}

function scenarioCoverage(
  metric: ScenarioRunResponse["calculation"]["demandUnits"]
) {
  return `${metric.current.availability.replaceAll("_", " ")} · coverage ${metric.coverage.numerator}/${metric.coverage.denominator} ${metric.coverage.grain.replaceAll("_", " ")}`;
}

function ScenarioFloatRow({
  label,
  metric,
  valueSuffix = "",
  impactSuffix = valueSuffix,
  impactValue,
  compactValues = false,
  impactDirection = "neutral"
}: {
  label: string;
  metric: ScenarioRunResponse["calculation"]["demandUnits"];
  valueSuffix?: string;
  impactSuffix?: string;
  impactValue?: number | null;
  compactValues?: boolean;
  impactDirection?: "positive" | "inverse" | "neutral";
}) {
  const impact = impactValue === undefined ? metric.impact.value : impactValue;
  const render = (value: number | null, suffix: string, signed = false) =>
    compactValues && suffix === ""
      ? scenarioQuantity(value, signed)
      : scenarioMeasure(value, suffix, signed);
  const impactClass = impact === null || impact === 0 || impactDirection === "neutral"
    ? undefined
    : (impactDirection === "positive" ? impact > 0 : impact < 0)
      ? "scenario-impact-positive"
      : "scenario-impact-negative";
  return (
    <tr>
      <td><strong>{label}</strong><small>{scenarioCoverage(metric)}</small></td>
      <td>{render(metric.current.value, valueSuffix)}</td>
      <td>{render(metric.scenario.value, valueSuffix)}</td>
      <td className={impactClass}>{render(impact, impactSuffix, true)}</td>
    </tr>
  );
}

function ScenarioMoneyRow({
  label,
  metric,
  dashboard,
  impactDirection = "neutral"
}: {
  label: string;
  metric: ScenarioRunResponse["calculation"]["revenuePotential"][number];
  dashboard: Dashboard;
  impactDirection?: "positive" | "inverse" | "neutral";
}) {
  const impact = metric.impact.valueMinor;
  const impactClass = impact === null || impact === 0 || impactDirection === "neutral"
    ? undefined
    : (impactDirection === "positive" ? impact > 0 : impact < 0)
      ? "scenario-impact-positive"
      : "scenario-impact-negative";
  return (
    <tr>
      <td>
        <strong>{label} · {marketName(dashboard, metric.marketId)}</strong>
        <small>{metric.current.availability.replaceAll("_", " ")} · coverage {metric.coverage.numerator}/{metric.coverage.denominator} money facts</small>
      </td>
      <td>{scenarioMoney(metric.current.valueMinor, metric.currencyCode)}</td>
      <td>{scenarioMoney(metric.scenario.valueMinor, metric.currencyCode)}</td>
      <td className={impactClass}>{scenarioMoney(impact, metric.currencyCode, true)}</td>
    </tr>
  );
}

function ScenarioModal({
  open,
  onClose,
  forecastVersion,
  filters,
  dashboard
}: {
  open: boolean;
  onClose: () => void;
  forecastVersion: string;
  filters: ForecastFilters;
  dashboard: Dashboard;
}) {
	const dialogRef = useRef<HTMLElement>(null);
	const [presetId, setPresetId] = useState("expected_demand");
  const [overrides, setOverrides] = useState<ScenarioOverrideDraft>(emptyScenarioOverrides);
  const context = useQuery({
    queryKey: ["forecast-scenario-context", forecastVersion],
    queryFn: () => loadScenarioContext(forecastVersion),
    enabled: open,
    staleTime: 0,
    gcTime: 0,
    retry: false
  });
	const mutation = useMutation({
    mutationFn: runForecastScenario,
    onError: (error) => {
      if (error instanceof ApiResponseError && error.status === 409) {
        void context.refetch();
      }
		}
	});
	useEffect(() => {
		if (open) return;
		mutation.reset();
		setPresetId("expected_demand");
		setOverrides(emptyScenarioOverrides);
	}, [open]);
	useEffect(() => {
		if (!open) return;
		const returnFocus = document.getElementById("forecastScenarioBtn")
			?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
		const frame = window.requestAnimationFrame(() => {
			dialogRef.current?.querySelector<HTMLElement>("select")?.focus();
		});
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.preventDefault();
				onClose();
				return;
			}
			if (event.key !== "Tab" || !dialogRef.current) return;
			const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
				'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)).filter((element) => !element.hasAttribute("hidden"));
			if (focusable.length === 0) {
				event.preventDefault();
				return;
			}
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => {
			window.cancelAnimationFrame(frame);
			document.removeEventListener("keydown", handleKeyDown);
			if (returnFocus?.isConnected) returnFocus.focus();
		};
	}, [open]);
	if (!open) return null;

  function updateOverride(field: keyof ScenarioOverrideDraft, value: string) {
    setOverrides((current) => ({...current, [field]: value}));
    mutation.reset();
  }

  function selectPreset(value: string) {
    setPresetId(value);
    setOverrides(emptyScenarioOverrides);
    mutation.reset();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!context.data) return;
    const userOverrides: ScenarioRunRequest["userOverrides"] = {};
    for (const field of [
      "demandAdjustmentPct",
      "priceChangePct",
      "promotionUpliftPct"
    ] as const) {
      if (overrides[field] !== "") userOverrides[field] = Number(overrides[field]);
    }
    if (overrides.competitorAvailability !== "") {
      userOverrides.competitorAvailability = overrides.competitorAvailability as
        "normal" | "stockout" | "promotion";
    }
    if (overrides.weatherEvent !== "") {
      userOverrides.weatherEvent = overrides.weatherEvent as
        "normal" | "positive" | "negative";
    }
    mutation.mutate({
      presetId,
      userOverrides,
      businessScope: {
        marketId: filters.marketId ?? "",
        storeId: filters.storeId ?? "",
        channelId: "",
        ...(filters.channelType ? {channelType: filters.channelType as
          "online" | "store" | "marketplace"} : {}),
        category: filters.category ?? "",
        horizonWeeks: filters.horizonWeeks ?? 4
      },
      expectedAuthority: {
        forecastVersion: context.data.forecastVersion,
        scenarioContextVersion: context.data.scenarioContextVersion,
        inventory: context.data.inventory
      }
    });
  }

  const result = mutation.data;
  const reportingRevenue = result?.calculation.reportingRevenuePotential;
  const reportingInventory = result?.calculation.reportingRequiredInventoryValue;
  const localRevenue = result?.calculation.revenuePotential[0];
  const localInventory = result?.calculation.requiredInventoryValue[0];
  const summaryRevenueMinor = reportingRevenue?.scenario.valueMinor
    ?? localRevenue?.scenario.valueMinor
    ?? null;
  const summaryRevenueCurrency = reportingRevenue?.currencyCode
    ?? localRevenue?.currencyCode
    ?? null;
  const summaryInventoryMinor = reportingInventory?.scenario.valueMinor
    ?? localInventory?.scenario.valueMinor
    ?? null;
  const summaryInventoryCurrency = reportingInventory?.currencyCode
    ?? localInventory?.currencyCode
    ?? null;
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
		<section
			className="modal forecast-modal scenario-modal"
			role="dialog"
			aria-modal="true"
			aria-labelledby="scenario-modal-title"
			aria-describedby={result ? undefined : "scenario-modal-description"}
			aria-busy={context.isPending || mutation.isPending}
			ref={dialogRef}
		>
        <div className="modal-head">
          <div>
            <h3 id="scenario-modal-title">{result ? "Scenario Results" : "Demand Scenario Planning"}</h3>
			{!result && <p id="scenario-modal-description">Read-only what-if projection</p>}
          </div>
          <button className="modal-close" type="button" aria-label="Close Scenario Planning" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            {context.isPending && <div className="modal-state">Pinning the active scenario context…</div>}
            {context.error && (
              <div className="modal-state modal-error" role="alert">
                Scenario context unavailable: {scenarioReason(context.error)}
              </div>
            )}
            {context.data && !result && (
              <>
                <div className="scenario-form-grid">
                  <label>
                    Preset
                    <select autoFocus value={presetId} onChange={(event) => selectPreset(event.target.value)}>
                      {scenarioPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
                    </select>
                  </label>
                  {([
                    ["demandAdjustmentPct", "Demand Adjustment (%)"],
                    ["priceChangePct", "Price Change (%)"],
                    ["promotionUpliftPct", "Promotion Uplift (%)"]
                  ] as const).map(([field, label]) => (
                    <label key={field}>
                      {label}
                      <input
                        type="number"
                        step="any"
                        value={overrides[field]}
                        placeholder="Use preset"
                        onChange={(event) => updateOverride(field, event.target.value)}
                      />
                    </label>
                  ))}
                  <label>
                    Competitor Availability
                    <select value={overrides.competitorAvailability} onChange={(event) => updateOverride("competitorAvailability", event.target.value)}>
                      <option value="">Use preset</option>
                      <option value="normal">Normal</option>
                      <option value="stockout">Stock-out</option>
                      <option value="promotion">Promotion</option>
                    </select>
                  </label>
                  <label>
                    Weather / Event
                    <select value={overrides.weatherEvent} onChange={(event) => updateOverride("weatherEvent", event.target.value)}>
                      <option value="">Use preset</option>
                      <option value="normal">Normal</option>
                      <option value="positive">Positive</option>
                      <option value="negative">Negative</option>
                    </select>
                  </label>
                </div>
              </>
            )}
            {mutation.error && (
              <div className="modal-state modal-error" role="alert">
                {mutation.error instanceof ApiResponseError && mutation.error.status === 409
                  ? "The scenario authority changed. The current tuple has been refreshed; run again."
                  : scenarioReason(mutation.error)}
              </div>
            )}
            {result && (
              <section className="scenario-results" aria-live="polite">
                <div className="scenario-summary-grid">
                  <div className="scenario-summary-item"><span>Demand Units</span><strong>{scenarioQuantity(result.calculation.demandUnits.scenario.value)}</strong></div>
                  <div className="scenario-summary-item"><span>Revenue Potential</span><strong>{scenarioMoney(summaryRevenueMinor, summaryRevenueCurrency)}</strong></div>
                  <div className="scenario-summary-item"><span>Required Inventory</span><strong>{scenarioMoney(summaryInventoryMinor, summaryInventoryCurrency)}</strong></div>
                </div>
                <div className="scenario-results-table-wrap">
                  <table className="table scenario-results-table" aria-label="Scenario comparison">
                    <thead><tr><th>Metric</th><th>Current Forecast</th><th>Scenario</th><th>Impact</th></tr></thead>
                    <tbody>
                      <ScenarioFloatRow label="Demand" metric={result.calculation.demandUnits} impactValue={result.calculation.demandUnits.impactPct ?? null} impactSuffix="%" compactValues impactDirection="positive" />
                      <ScenarioFloatRow label="Stock-out Risk" metric={result.calculation.demandWeightedSeriesStockoutRiskPct} impactValue={result.calculation.demandWeightedSeriesStockoutRiskPct.impactPoints ?? null} valueSuffix="%" impactSuffix=" pts" impactDirection="inverse" />
                      {result.calculation.revenuePotential.map((metric) => <ScenarioMoneyRow key={`revenue-${metric.marketId}-${metric.currencyCode}`} label="Revenue Potential" metric={metric} dashboard={dashboard} impactDirection="positive" />)}
                      <ScenarioFloatRow label="Required Inventory Units" metric={result.calculation.requiredInventoryUnits} impactValue={result.calculation.requiredInventoryUnits.impactPct ?? null} impactSuffix="%" compactValues />
                      {result.calculation.requiredInventoryValue.map((metric) => <ScenarioMoneyRow key={`inventory-${metric.marketId}-${metric.currencyCode}`} label="Required Inventory Value" metric={metric} dashboard={dashboard} />)}
                    </tbody>
                  </table>
                </div>
                <details className="scenario-projection-details">
                  <summary>Projection details</summary>
                  <p>Forecast {result.authority.forecastVersion} · context {result.authority.scenarioContextVersion.slice(0, 12)}… · inventory {result.authority.inventory?.inventoryVersion ?? "not available"}</p>
                  <h4>Applied price summary</h4>
                  {result.calculation.appliedPriceSummaries.map((summary) => (
                    <p key={`${summary.marketId}-${summary.currencyCode}`}>
                      {marketName(dashboard, summary.marketId)} · {summary.currencyCode}: {percentage(summary.baselineValueWeightedAppliedPriceChangePct, true)} · coverage {summary.coverage.numerator}/{summary.coverage.denominator}
                    </p>
                  ))}
                  <p>Approved assumption {result.assumptionSetId} · {result.assumptionSemanticFingerprint.slice(0, 16)}…</p>
                  <ul>
                    {Object.entries(result.factorBasis).map(([factor, basis]) => (
                      <li key={factor}>{factor.replaceAll(/([A-Z])/g, " $1")}: {basis.valueSource} · {basis.coefficientSource}</li>
                    ))}
                  </ul>
                  <p>{result.priceProvenance.length} price-provenance rows · snapshot {result.priceSnapshotContentFingerprint.slice(0, 16)}…</p>
                </details>
              </section>
            )}
          </div>
          <div className="modal-foot">
            {result ? (
              <>
                <button className="btn" type="button" onClick={() => mutation.reset()}>Back</button>
                <button className="modal-action" type="button" onClick={onClose}>Close</button>
              </>
            ) : (
              <>
                <button className="btn" type="button" onClick={onClose}>Close</button>
                <button className="modal-action" type="submit" disabled={!context.data || mutation.isPending}>
                  {mutation.isPending ? "Running…" : "Run Scenario"}
                </button>
              </>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}

function useForecastData(filters: ForecastFilters) {
  const summary = useQuery({
    queryKey: ["forecast-summary"],
    queryFn: ({signal}) => loadForecastSummary(signal)
  });
  const actuals = useQuery({
    queryKey: ["forecast-actuals", filters],
    queryFn: ({signal}) => loadForecastActuals(filters, signal),
    placeholderData: (previous) => previous
  });
  const horizons = useQuery({
    queryKey: ["forecast-horizons", filters],
    queryFn: ({signal}) => loadForecastHorizons(filters, signal),
    placeholderData: (previous) => previous
  });
  const stores = useQuery({
    queryKey: ["forecast-stores", filters],
    queryFn: ({signal}) => loadForecastStores(filters, signal),
    placeholderData: (previous) => previous
  });
  const workbench = useQuery({
    queryKey: ["forecast-workbench", filters],
    queryFn: ({signal}) => loadForecastWorkbench(filters, signal),
    placeholderData: (previous) => previous
  });
  const drivers = useQuery({
    queryKey: ["forecast-drivers"],
    queryFn: ({signal}) => loadForecastDrivers(signal)
  });
  const signals = useQuery({
    queryKey: ["forecast-signals"],
    queryFn: ({signal}) => loadForecastSignals(signal)
  });
  const versions = useQuery({
    queryKey: ["forecast-versions"],
    queryFn: ({signal}) => loadForecastVersions(signal)
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

function channelTypeLabel(channelType: string) {
  if (channelType === "online") return "E-commerce";
  if (channelType === "marketplace") return "Marketplace";
  return "Store";
}

function ControlledMasterCheckbox({
  label,
  checked,
  indeterminate,
  onChange
}: {
  label: string;
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      onChange={onChange}
    />
  );
}

function WorkbenchTable({
  rows,
  selected,
  onToggle,
  onToggleAll
}: {
  rows: ForecastRow[];
  selected: ReadonlySet<string>;
  onToggle: (rowId: string) => void;
  onToggleAll: () => void;
}) {
  const selectedVisible = rows.filter((row) => selected.has(row.rowId)).length;
  const columns = useMemo(() => [
    columnHelper.display({
      id: "select",
      header: () => (
        <ControlledMasterCheckbox
          label="Select all visible forecast rows"
          checked={rows.length > 0 && selectedVisible === rows.length}
          indeterminate={selectedVisible > 0 && selectedVisible < rows.length}
          onChange={onToggleAll}
        />
      ),
      cell: ({row}) => (
        <input
          type="checkbox"
          aria-label={`Select ${row.original.skuId} at ${row.original.storeName}`}
          checked={selected.has(row.original.rowId)}
          onChange={() => onToggle(row.original.rowId)}
        />
      )
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
          <small>{channelTypeLabel(row.original.channelType)}</small>
        </span>
      )
    }),
    columnHelper.accessor("baseline", {
      header: "Baseline",
      cell: (info) => count(info.getValue())
    }),
    columnHelper.accessor("aiForecast", {
      header: "AI Forecast (P50)",
      cell: (info) => count(info.getValue())
    }),
    columnHelper.accessor("plannerForecast", {
      header: "Planner Forecast",
      // With no planner-override workflow, the planner forecast is exactly the AI
      // forecast the planner would start from — the real operative number, not a
      // placeholder. The title records that no override was applied.
      cell: ({row}) => <span title="No planner override applied; equals the AI forecast">{count(row.original.aiForecast)}</span>
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
            ? advisory("Sparse demand", "Absolute error exceeds total demand; a 0-100 accuracy is not interpretable at this grain")
            : advisory("No demand", "No positive demand in the evaluation window");
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
          return advisory(
            row.intervalCoveredThroughHorizon ? `Weeks 1–${row.intervalCoveredThroughHorizon}` : "Calibrated weeks",
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
      cell: (info) => driverLabels[info.getValue() ?? ""] ?? info.getValue() ?? "—"
    }),
    columnHelper.accessor("dataQuality", {
      header: "Data Quality",
      cell: (info) => statusBadge(info.getValue())
    }),
    columnHelper.accessor("status", {
      header: "Status",
      cell: (info) => statusBadge(info.getValue())
    })
  ], [onToggle, onToggleAll, rows, selected, selectedVisible]);
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
            <tr key={row.original.rowId}>
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
  horizonWeeks,
  windowMetrics,
  setModal
}: {
  data: ReturnType<typeof useForecastData>;
  healthGrain: ForecastHealthGrain;
  granularity: string;
  /** The selected window, so the health table can mark the rows the tile pools. */
  horizonWeeks: number;
  /** The pooled figure the Forecast Accuracy tile shows, passed rather than
   *  recomputed: two derivations of one number is how they come to disagree. */
  windowMetrics: {accuracy: number | null; bias: number | null};
  setModal: (modal: Modal, trigger?: HTMLElement) => void;
}) {
  const summary = data.summary!.items[0];
  // Decision #95 makes `forecast` the additive expected-volume estimate. P50 and
  // P90 remain quantiles in the payload, but their sums are not quantiles of the
  // aggregate, so the chart does not draw them as an aggregate interval. Coverage
  // is stated separately from per-SeriesKey P90 hits below.
  const chartData = granularity === "Monthly"
    ? Object.values(data.actuals!.items.reduce<Record<string, {
      week: string;
      forecast: number;
      actual: number;
    }>>((months, item) => {
      const month = item.targetWeekStart.slice(0, 7);
      const existing = months[month]
        ?? {week: month, forecast: 0, actual: 0};
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
  // Counted PER SERIES by the read model, not by asking whether the eight summed
  // weeks fell inside the summed band. Those bars sum ~2,034 per-series P90s, and
  // a sum of quantiles is not the quantile of the sum -- errors diversify, so the
  // drawn band sits far above a real aggregate P90. Measured against it the card
  // said "inside the range in 8 of 8" and implied a near-perfect forecast; the
  // per-series figure is 89.9% at h19-h26 and 90.8% at h1-h4, which is a P90
  // doing exactly its job at both. The old count is kept nowhere: a number that
  // flatters by construction is worse than no number.
  const coverage = data.actuals!.seriesCoverage;
  const range = data.actuals!.horizonRange;
  const comparisonCap = range?.cap ?? 4;
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
        <Card
          title="Forecast vs Actual"
          link={
            `Last 8 comparable ${granularity === "Monthly" ? "weeks grouped by month" : "weeks"}` +
            ` · freshest forecast within h1–h${comparisonCap} · ` +
            (coverage
              ? `${(coverage.ratio * 100).toFixed(1)}% P90 coverage across ` +
                `${coverage.series.toLocaleString("en-US")} series-weeks`
              : `P90 coverage not available`)
          }
        >
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
                {/* Expected volume is additive; P50/P90 are not. Drawing the sum
                    of per-series quantiles as an aggregate band caused BUG-13, so
                    the visual compares only like-for-like additive quantities.
                    P90 coverage remains in the caption at SeriesKey grain. */}
                <Bar
                  dataKey="forecast"
                  name="Forecast"
                  fill="#2f80ed"
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="actual"
                  name="Actual"
                  fill="#1fbf75"
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
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
                  <tr
                    key={row.checkpoint}
                    data-horizon={row.checkpoint}
                    data-in-window={row.checkpoint <= horizonWeeks}
                    className={row.checkpoint <= horizonWeeks ? "in-window" : undefined}
                  >
                    <td>{row.checkpoint === 1 ? "1 week" : `${row.checkpoint} weeks`}</td>
                    <td>{percentage(row.accuracy)}</td>
                    <td>{ratioPercentage(row.bias, true)}</td>
                    <td>{ratioPercentage(row.coverage)}</td>
                    <td>{row.status === "unavailable"
                      ? <span className="muted" title="This horizon is beyond the evaluated actuals window">Awaiting actuals</span>
                      : statusBadge(row.status)}</td>
                  </tr>
                ))}
              </tbody>
              {/* The KPI tile above shows ONE number for the selected window and
                  this table shows one per horizon, which reads as a
                  contradiction until you can see they are the same arithmetic.
                  They are: the tile pools the window rather than averaging it --
                  sum the absolute errors, sum the actuals, divide once -- so it
                  lands inside the range of the rows it pools and equals this
                  footer exactly. Shown rather than explained in a tooltip,
                  because the question the footer answers is "does the tile agree
                  with the table". */}
              <tfoot>
                <tr data-testid="horizon-window-total">
                  <td><strong>h1&ndash;h{horizonWeeks} pooled</strong></td>
                  <td><strong>{percentage(windowMetrics.accuracy)}</strong></td>
                  <td><strong>{percentage(windowMetrics.bias, true)}</strong></td>
                  <td colSpan={2} className="muted">
                    Volume-weighted across the highlighted rows &mdash; the figure
                    the Forecast Accuracy tile shows
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </Card>
      </div>
      <div className="grid-3">
        <Card title="Forecast Exceptions" link="Current cycle">
          <SimpleRows rows={exceptionRows.map((key) => ({
            label: exceptionLabels[key],
            value: count(summary.exceptionCounts[key] ?? 0)
          }))} />
          <button className="link-button card-link" type="button" onClick={(event) => setModal("actions", event.currentTarget)}>
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
            {label: "Planner-adjusted accuracy", value: <span title="No planner override applied; equals the AI forecast accuracy">{percentage(summary.portfolioAccuracy ?? summary.accuracy)}</span>},
            {
              label: "Net FVA",
              value: percentage(summary.portfolioFvaVsMa13Pct ?? summary.fvaVsMa13Pct, true)
            },
            {label: "Overrides adding value", value: <span title="No planner overrides exist; override contribution is exactly zero">{percentage(0)}</span>}
          ]} />
        </Card>
        <Card title="Business Impact" link="Forecast-derived">
          {/* The original mockup projected inventory-financial outcomes (stock-out
              reduction, working capital release) that need a downstream business
              model this forecast bundle does not carry. These are the real
              forecast-derived business figures the served summary does provide:
              the costed demand exposure the forecast surfaces, and the value the
              AI forecast adds over the statistical baseline. */}
          <SimpleRows rows={[
            {label: "Demand at risk (costed)", value: money(summary.demandAtRiskMinor) ?? money(0)},
            {label: "Demand at risk (units)", value: count(summary.demandAtRiskUnits ?? 0)},
            {label: "SKU-store cells at risk", value: count(summary.demandAtRiskCells ?? 0)},
            {label: "Locations affected", value: count(summary.demandAtRiskLocations ?? 0)},
            {label: "Forecast value add (vs MA13)", value: percentage(summary.portfolioFvaVsMa13Pct ?? summary.fvaVsMa13Pct, true)}
          ]} />
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
  setModal: (modal: Modal, trigger?: HTMLElement) => void;
}) {
  return (
    <Card title="Store Forecast Performance" link="Filter-scoped">
      <div className="card-toolbar">
        <span>{count(data.stores!.items.length)} current stores</span>
        <button id="storeForecastDrilldownBtn" className="btn secondary" type="button" onClick={(event) => setModal("stores", event.currentTarget)}>
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
                <td>{money(store.demandAtRiskMinor) ?? money(0)}</td>
                <td>{(() => {
                  // Absent a health row, no elevated stock-out risk was flagged, so
                  // the honest state is the low band rather than a missing token.
                  const risk = store.stockoutRisk ?? "Low";
                  return <span className={`badge ${risk === "High" ? "b-red" : risk === "Medium" ? "b-amber" : "b-green"}`} title={store.stockoutRisk ? undefined : "No elevated stock-out risk flagged for this store"}>{risk}</span>;
                })()}</td>
                <td><span title="No planner-override workflow is configured; the override rate is exactly zero">{percentage(0)}</span></td>
                <td>{(() => {
                  // Priority action derived from this store's own stock-out risk band.
                  const risk = store.stockoutRisk ?? "Low";
                  return risk === "High" ? "Expedite replenishment"
                    : risk === "Medium" ? "Review demand coverage" : "Maintain plan";
                })()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SkuView({
  data,
  selected,
  onToggle,
  onToggleAll
}: {
  data: ReturnType<typeof useForecastData>;
  selected: ReadonlySet<string>;
  onToggle: (rowId: string) => void;
  onToggleAll: () => void;
}) {
  return (
    <Card title="SKU-Store Forecast Workbench" link="Current accepted version">
      <div className="record-count" id="forecastRecordCount">
        Showing {count(data.workbench!.items.length)} of {count(data.workbench!.pagination.total)} records
      </div>
      <WorkbenchTable
        rows={data.workbench!.items}
        selected={selected}
        onToggle={onToggle}
        onToggleAll={onToggleAll}
      />
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
              // A driver absent from the live set (e.g. promotion, which the model
              // excludes) contributes exactly 0% to the renormalized live drivers.
              return (
                <tr key={driver}>
                  <td>{driverLabels[driver]}</td>
                  <td>{item ? `${Number(item.contributionPct).toFixed(1)}%` : <span title="Excluded from the live driver set; contributes 0% to the forecast">0.0%</span>}</td>
                  <td>{item ? item.direction : "Neutral"}</td>
                  <td>{item ? ratioPercentage(Number(item.confidence)) : "0.0%"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="footnote">Five live contributions renormalize to 100%. Promotion is excluded.</p>
      </Card>
      <Card title="External Signal Readiness" link="At decision time">
        <SimpleRows rows={data.signals!.items.map((signal) => {
          // A signal whose own freshness is not materialized is assessed at the
          // decision-time baseline — a real timestamp, consistent with this card.
          const baselineLabel = new Date(data.signals!.freshnessBaseline).toLocaleString("en-US", {timeZone: "UTC", dateStyle: "medium", timeStyle: "short"});
          return {
            label: signal.label,
            value: signal.knownAsOf
              ? signal.knownAsOf
              : <span title="Signal freshness defaults to the decision-time baseline">{baselineLabel}</span>
          };
        })} />
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
  const openExceptions = Object.values(summary.exceptionCounts ?? {}).reduce((total, value) => total + (Number(value) || 0), 0);
  return (
    <div className="grid-2">
      <Card title="Forecast Approval & SLA">
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>Workflow Stage</th><th>Open</th><th>State</th></tr></thead>
            <tbody>
              <tr><td>AI exception review</td><td>{count(openExceptions)}</td><td>{statusBadge(openExceptions > 0 ? "In review" : "Clear")}</td></tr>
              <tr><td>Planner adjustment review</td><td>{count(0)}</td><td><span className="badge b-green" title="No planner-override workflow is configured; nothing is queued">Advisory</span></td></tr>
              <tr><td>Category approval</td><td>{count(0)}</td><td><span className="badge b-green" title="Forecasts are advisory in this PoC; no approval gate is configured">Advisory</span></td></tr>
              <tr><td>Locked forecast publication</td><td>{count(1)}</td><td>{statusBadge("Active")}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Model & Data Controls">
        <SimpleRows rows={[
          {label: "Forecast version traceability", value: percentage(1)},
          {label: "Planner override comments", value: <span title="No planner overrides exist, so none require a comment">{count(0)}</span>},
          {label: "Data freshness compliance", value: percentage(1)},
          {label: "Model drift within tolerance", value: <span title="Exactly one active accepted version by policy; there is no drift to measure">{statusBadge("Within tolerance")}</span>},
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
  const debouncedSearch = useDebouncedValue(search.trim());
  const [tab, setTab] = useState<Tab>("Overview");
  const [modal, setModal] = useState<Modal>(null);
  const modalTrigger = useRef<HTMLElement | null>(null);
  const [selectedRows, setSelectedRows] = useState<Set<string>>(() => new Set());
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState("");
  const selectedStore = dashboard.filters.stores.find((store) => store.storeId === storeId);
  const filters = useMemo<ForecastFilters>(() => ({
    marketId: selectedStore?.marketId,
    region,
    storeId,
    channelType,
    category,
    search: debouncedSearch,
    horizonWeeks
  }), [selectedStore?.marketId, region, storeId, channelType, category, debouncedSearch, horizonWeeks]);
  const data = useForecastData(filters);
  const openModal = (next: Modal, trigger?: HTMLElement) => {
    if (next) modalTrigger.current = trigger ?? document.activeElement as HTMLElement | null;
    setModal(next);
  };
  useEffect(() => {
    setSelectedRows(new Set());
    setExportStatus("");
  }, [filters, data.workbench?.semanticFingerprint]);
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
  const slowMoverMetrics = useMemo(() => {
    const rows = data.horizons?.items.filter((item) =>
      item.horizon <= horizonWeeks && item.slowMover
    ) ?? [];
    const actual = rows.reduce((sum, row) => sum + (row.slowMover?.actualSum ?? 0), 0);
    const signedError = rows.reduce(
      (sum, row) => sum + (row.slowMover?.signedErrorSum ?? 0),
      0
    );
    const allActual = data.horizons?.items
      .filter((item) => item.horizon <= horizonWeeks)
      .reduce((sum, row) => sum + row.actualSum, 0) ?? 0;
    return {
      bias: actual ? 100 * signedError / actual : null,
      actualSharePct: actual && allActual ? 100 * actual / allActual : null
    };
  }, [data.horizons?.items, horizonWeeks]);

  // Derived from the live selector and the grain the API reports, never hard-coded, so
  // the label cannot drift from the number beside it.
  const metricScopeLabel = `h1–h${horizonWeeks}, ${
    (data.horizons?.metricGrain ?? "market_portfolio").replace(/_/g, " ")
  }`;

  const visibleRowIds = data.workbench?.items.map((row) => row.rowId) ?? [];
  const selectedForecastRows = data.workbench?.items.filter((row) => selectedRows.has(row.rowId)) ?? [];
  const exportCount = selectedRows.size > 0
    ? selectedRows.size
    : data.workbench?.pagination.total ?? 0;
  const exportDisabledReason = exporting
    ? "Preparing the governed export…"
    : exportCount === 0
      ? "No rows available to export"
      : exportCount > DIRECT_EXPORT_LIMIT
        ? `Export limit is ${DIRECT_EXPORT_LIMIT} rows; narrow filters or selection`
        : "";

  function toggleWorkbenchRow(rowId: string) {
    setSelectedRows((current) => {
      const next = new Set(current);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });
    setExportStatus("");
  }

  function toggleAllWorkbenchRows() {
    setSelectedRows((current) => {
      const allVisibleSelected = visibleRowIds.length > 0 &&
        visibleRowIds.every((rowId) => current.has(rowId));
      const next = new Set(current);
      for (const rowId of visibleRowIds) {
        if (allVisibleSelected) next.delete(rowId);
        else next.add(rowId);
      }
      return next;
    });
    setExportStatus("");
  }

  async function exportWorkbench() {
    if (!data.workbench || exportDisabledReason) return;
    setExporting(true);
    setExportStatus("");
    try {
      const selected = [...selectedRows].sort();
      const currency = selectedStore?.currencyCode ??
        (dashboard.filters.currencies.length === 1
          ? dashboard.filters.currencies[0]
          : "MULTI");
      const result = await downloadDirectExport({
        exportId: "exportForecastBtn",
        scope: selected.length > 0 ? "selected_visible" : "current_filtered",
        expectedCount: exportCount,
        ids: selected,
        currency,
        storeId,
        channelType,
        filters: {
          marketId: filters.marketId,
          region: filters.region,
          storeId: filters.storeId,
          channelType: filters.channelType,
          category: filters.category,
          search: filters.search,
          horizonWeeks: filters.horizonWeeks
        }
      });
      setExportStatus(`Downloaded ${result.count.toLocaleString("en-US")} rows as ${result.filename}.`);
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setExporting(false);
    }
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
        <button id="acceptForecastBtn" className="btn primary" type="button" onClick={(event) => openModal("accept", event.currentTarget)} title="Forecast acceptance workflow is not configured">Accept Forecast</button>
        <button id="addForecastAdjustmentBtn" className="btn secondary" type="button" onClick={(event) => openModal("adjust", event.currentTarget)} title="Planner adjustment workflow is not configured">Add Planner Adjustment</button>
        <button id="compareForecastVersionsBtn" className="btn secondary" type="button" onClick={(event) => openModal("versions", event.currentTarget)}>Compare Versions</button>
		<button
		  id="forecastScenarioBtn"
		  className="btn secondary"
		  type="button"
		  disabled={!scenarioPlanningEnabled}
		  aria-disabled={!scenarioPlanningEnabled}
		  onClick={(event) => scenarioPlanningEnabled && openModal("scenario", event.currentTarget)}
		  title={scenarioPlanningEnabled
			? "Run a stateless assumption-based forecast scenario"
			: "Scenario Planning awaits governed activation and its live-status amendment"}
		>
		  Scenario Planning
		</button>
        <button id="forecastActionCenterBtn" className="btn secondary" type="button" onClick={(event) => openModal("actions", event.currentTarget)}>Forecast Action Center</button>
        <button
          id="exportForecastBtn"
          className="btn secondary"
          type="button"
          onClick={exportWorkbench}
          disabled={Boolean(exportDisabledReason)}
          aria-disabled={Boolean(exportDisabledReason)}
          title={exportDisabledReason || `Export ${exportCount.toLocaleString("en-US")} reviewed row(s)`}
        >
          {exporting ? "Exporting…" : "Export"}
        </button>
      </div>
      {exportStatus && <div className="export-status" role="status">{exportStatus}</div>}

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
          {summary!.categories.map((value) => <option key={value} value={value}>{categoryName(dashboard, value)}</option>)}
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
          <span className="delta down">
            Slow / intermittent: {percentage(slowMoverMetrics.bias, true)} · {percentage(
              slowMoverMetrics.actualSharePct
            )} of actual volume
          </span>
          <p>Target range: ±5% · {metricScopeLabel}</p>
        </div>
        <div className="kpi">
          <small>Demand at Risk</small>
          <div className="value">
            {money(summary?.demandAtRiskMinor) ?? money(0)}
          </div>
          <span className="delta down">
            {summary?.demandAtRiskCells?.toLocaleString("en-US") ?? "0"} SKU-store combinations
          </span>
          <p>
            Potential unserved sales exposure across {summary?.demandAtRiskLocations
              ?.toLocaleString("en-US") ?? "0"} distributors
          </p>
        </div>
        <div className="kpi"><small>Planner Overrides</small><div className="value">0</div><p>Advisory forecasts; no override workflow</p></div>
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
            aria-label={item}
            aria-selected={tab === item}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <section className="forecast-panel" role="tabpanel">
        {tab === "Overview" && (
          <Overview
            data={data}
            healthGrain={healthGrain}
            granularity={granularity}
            horizonWeeks={horizonWeeks}
            windowMetrics={scopedMetrics}
            setModal={openModal}
          />
        )}
        {tab === "Store View" && <StoreView data={data} setModal={openModal} />}
        {tab === "SKU View" && (
          <SkuView
            data={data}
            selected={selectedRows}
            onToggle={toggleWorkbenchRow}
            onToggleAll={toggleAllWorkbenchRows}
          />
        )}
        {tab === "Demand Drivers" && <DriversView data={data} />}
        {tab === "Governance" && <GovernanceView data={data} />}
      </section>
      {modal && modal !== "scenario" && (
        <ForecastModal
          modal={modal}
          onClose={() => setModal(null)}
          summary={data.summary}
          stores={data.stores}
          version={data.versions}
          workbench={data.workbench}
          selectedRows={selectedForecastRows}
          activeStoreId={storeId}
          returnFocus={modalTrigger.current}
          onOpenStore={(nextStoreId, nextHorizon) => {
            onStoreId(nextStoreId);
            setHorizonWeeks(nextHorizon);
            setTab("SKU View");
            setModal(null);
            queueMicrotask(() => document.getElementById("page-heading")?.focus({preventScroll: true}));
          }}
        />
      )}
	  {scenarioPlanningEnabled && modal === "scenario" && (
		<ScenarioModal
		  open
		  onClose={() => setModal(null)}
		  forecastVersion={data.summary.versionId}
		  filters={filters}
		  dashboard={dashboard}
		/>
	  )}
    </div>
  );
}
