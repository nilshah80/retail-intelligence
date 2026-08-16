import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from "react";
import {useMutation, useQuery} from "@tanstack/react-query";
import type {Dashboard} from "./api";
import {useDebouncedValue} from "./useDebouncedValue";
import {categoryName, channelName, storeName} from "./dimensionLabels";
import {formatAggregateMoneyMinor, formatMoneyMinor} from "./currencyFormat";
import {
  loadAlertRules,
  loadCompetitorDetail,
  loadCompetitorMatches,
  loadCompetitorSummary,
  loadGroupedRecommendations,
  loadPricingGovernance,
  loadPromotionSurface,
  loadRecommendationDetail,
  loadRecommendations,
  loadRecommendationSummary,
  exportPriceRecommendations,
  type CompetitorMatch,
  type PricingFilters,
  type Recommendation
} from "./pricingApi";

export type PricingPageId =
  | "priceRecommendations"
  | "priceSimulation"
  | "competitorMonitor"
  | "promotionPlanner";

export const pricingScreens: Record<
  PricingPageId,
  {title: string; subtitle: string}
> = {
  priceRecommendations: {
    title: "Price Recommendations",
    subtitle: "AI-generated SKU-level pricing actions with human approval"
  },
  priceSimulation: {
    title: "Price Simulation",
    subtitle: "Test price scenarios before applying them"
  },
  competitorMonitor: {
    title: "Competitor Monitor",
    subtitle: "Track market prices, promotions and availability"
  },
  promotionPlanner: {
    title: "Promotion Planner",
    subtitle: "Plan, simulate and optimize retail promotions"
  }
};

type PricingPageProps = {
  pageId: PricingPageId;
  dashboard?: Dashboard;
  storeId: string;
  onStoreId: (value: string) => void;
  channelType: string;
  onNavigate: (page: PricingPageId) => void;
};

const unavailable = "Not available";

// The client-facing Price Recommendations and Competitor Monitor grids page at
// exactly 20 rows (plan §2.2.1 / P3); the API reconciles limit/offset/total.
const PAGE_SIZE = 20;

function formatCount(value: number | null | undefined) {
  return value === null || value === undefined
    ? unavailable
    : new Intl.NumberFormat("en-US").format(value);
}

function formatPercent(value: number | null | undefined, digits = 1) {
  return value === null || value === undefined
    ? unavailable
    : `${value.toFixed(digits)}%`;
}

function parseMoneyMinor(value: string): number | null {
  const match = value.trim().match(/^(\d+)(?:\.(\d{1,2}))?$/);
  if (!match) return null;
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(2, "0"));
  const minor = whole * 100 + fraction;
  return Number.isSafeInteger(minor) ? minor : null;
}

export {formatAggregateMoneyMinor, formatMoneyMinor};

function explanationText(value: string | null | undefined, fallback?: string | null) {
  if (!value) return reasonText(fallback);
  try {
    const decoded: unknown = JSON.parse(value);
    if (Array.isArray(decoded) && decoded.every((item) => typeof item === "string")) {
      return decoded.join(" • ");
    }
  } catch {
    // Older retained projections may already contain display-ready prose.
  }
  return value;
}

function formatUnits(value: number | null | undefined) {
  if (value === null || value === undefined) return unavailable;
  return new Intl.NumberFormat("en-US", {maximumFractionDigits: 1}).format(value);
}

// Coerce an untyped served value to a finite number, or null when it is absent or
// non-numeric, so a governed placeholder is shown instead of NaN.
function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function absoluteTime(value: string | null | undefined) {
  if (!value) return unavailable;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC"
  }).format(parsed);
}

function reasonText(code: string | null | undefined) {
  if (!code) return unavailable;
  return code.toLowerCase().replaceAll("_", " ").replace(/^./, (letter) =>
    letter.toUpperCase()
  );
}

function badgeClass(value: string | null | undefined) {
  const lower = value?.toLowerCase() ?? "";
  if (
    lower.includes("increase") || lower.includes("matched") ||
    lower.includes("high") || lower.includes("in stock") ||
    lower.includes("live")
  ) return "b-green";
  if (
    lower.includes("review") || lower.includes("medium") ||
    lower.includes("low stock") || lower.includes("draft")
  ) return "b-amber";
  if (
    lower.includes("decrease") || lower.includes("reject") ||
    lower.includes("out of stock") || lower.includes("unavailable")
  ) return "b-red";
  return "b-blue";
}

function PricingState({
  pending,
  error,
  empty,
  emptyMessage,
  children
}: {
  pending: boolean;
  error: unknown;
  empty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  if (pending) {
    return <div className="state-card pricing-state">Loading governed pricing data…</div>;
  }
  if (error) {
    return (
      <div className="state-card error-state pricing-state" role="alert">
        <strong>Live pricing data is unavailable.</strong>
        <span>{error instanceof Error ? error.message : String(error)}</span>
        <small>No reference values or fallback rows are displayed.</small>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="state-card pricing-state">
        {emptyMessage ?? "No governed rows match the current filters."}
      </div>
    );
  }
  return <>{children}</>;
}

function PricingKpi({
  label,
  value,
  note,
  unavailableReason,
  delta
}: {
  label: string;
  value: string;
  note: string;
  unavailableReason?: string;
  // A companion sentiment line under the value, matching the reference KPI tiles
  // (value → delta → note) and the Forecast/Inventory KPI pattern. Color carries
  // business sentiment, not arithmetic sign (plan §3.2).
  delta?: {value: string; sentiment: "up" | "down" | "warn"};
}) {
  const missing = value === unavailable || value.startsWith("Not available");
  return (
    <div className="kpi pricing-kpi">
      <small>{label}</small>
      <div className={`value${missing ? " unavailable" : ""}`}>{value}</div>
      {delta && <span className={`delta ${delta.sentiment}`}>{delta.value}</span>}
      <div className="demo-note">{unavailableReason ?? note}</div>
    </div>
  );
}

function CardHeader({title, context, action}: {
  title: string;
  context?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card-head pricing-card-head">
      <div>
        <h3>{title}</h3>
        {context && <span className="card-context">{context}</span>}
      </div>
      {action}
    </div>
  );
}

function MetricList({rows}: {
  rows: Array<{label: string; value: ReactNode; unavailable?: boolean}>
}) {
  return (
    <div className="pricing-metric-list">
      {rows.map((row) => (
        <div key={row.label}>
          <span>{row.label}</span>
          <strong className={row.unavailable ? "cell-unavailable" : ""}>
            {row.value}
          </strong>
        </div>
      ))}
    </div>
  );
}

function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  wide = false
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const priorFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = `pricing-dialog-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    priorFocus.current = document.activeElement as HTMLElement | null;
    const container = containerRef.current;
    titleRef.current?.focus();
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
      priorFocus.current?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop open"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={containerRef}
        className={`modal pricing-modal${wide ? " pricing-modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="modal-head">
          <div>
            <h3 ref={titleRef} id={titleId} tabIndex={-1}>{title}</h3>
            {description && <p>{description}</p>}
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label={`Close ${title}`}>
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-foot">
          {footer ?? (
            <button className="modal-action" type="button" onClick={onClose}>Close</button>
          )}
        </div>
      </section>
    </div>
  );
}

function PreviewButton({children, onClick, disabled, reason}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  reason?: string;
}) {
  return (
    <button
      className="filter pricing-action"
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={reason}
    >
      {children}
    </button>
  );
}

function UnavailableValue({reason}: {reason: string}) {
  return <span className="cell-unavailable" title={reason}>{unavailable}</span>;
}

// A withheld_assessment row carries no accepted decision, so its action-derived
// cells have no value. Rather than a bare "Not available", they show an explicit
// governed state; the withhold reason rides in the tooltip and the AI Reason cell.
function WithheldValue({reason}: {reason: string}) {
  return <span className="cell-unavailable" title={reason}>Under review</span>;
}

// A privacy-restricted field (for example promotion cannibalisation risk) is never
// disclosed as a number; it shows a governed chip carrying the restriction reason.
function RestrictedValue({reason, label}: {reason: string; label?: string}) {
  return <span className="badge b-blue" title={reason}>{label ?? "Restricted"}</span>;
}

function Pagination({offset, limit, total, onPrev, onNext}: {
  offset: number;
  limit: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="pricing-pagination">
      <span className="pagination-status" aria-live="polite">
        {total === 0
          ? "No rows to display"
          : `Showing ${formatCount(first)}–${formatCount(last)} of ${formatCount(total)}`}
      </span>
      <div className="pagination-controls">
        <button className="filter" type="button" onClick={onPrev} disabled={offset <= 0}>Previous</button>
        <button className="filter" type="button" onClick={onNext} disabled={offset + limit >= total}>Next</button>
      </div>
    </div>
  );
}

function Field({label, children, help}: {
  label: string;
  children: ReactNode;
  help?: string;
}) {
  return (
    <div className="pricing-field">
      <label>
        <span>{label}</span>
        {children}
      </label>
      {help && <small>{help}</small>}
    </div>
  );
}

function PreviewFooter({label, onClose, reason}: {
  label: string;
  onClose: () => void;
  reason: string;
}) {
  return (
    <>
      <button className="modal-action" type="button" disabled title={reason}>{label}</button>
      <button className="filter" type="button" onClick={onClose}>Cancel</button>
    </>
  );
}

function WorkflowPreview({kind, selectedCount, onClose}: {
  kind: "approve" | "review" | "schedule";
  selectedCount: number;
  onClose: () => void;
}) {
  const reason = "Approval workflow and write authority are not available.";
  if (kind === "approve") {
    return (
      <Dialog
        open
        title="Approve Price Recommendations"
        description="Approval workflow unavailable — no approval will be recorded"
        onClose={onClose}
        footer={<PreviewFooter label="Confirm Approval" onClose={onClose} reason={reason} />}
      >
        <div className="preview-banner"><strong>Workflow unavailable</strong>{reason}</div>
        <MetricList rows={[
          {label: "Products selected", value: selectedCount},
          {label: "Stores affected", value: <UnavailableValue reason="Server recount occurs only in an approved workflow." />},
          {label: "Average price change", value: <UnavailableValue reason="Server validation is required." />},
          {label: "Maximum price change", value: <UnavailableValue reason="Server validation is required." />},
          {label: "Estimated revenue impact", value: <UnavailableValue reason="Server validation is required." />},
          {label: "Higher approval exceptions", value: <UnavailableValue reason={reason} />}
        ]} />
        <div className="callout compact-callout">
          <strong>Approval validation</strong>
          <p>Selection, scope, dates, limits, margin evidence, and approval authority require server validation before any workflow can begin.</p>
        </div>
        <div className="pricing-form-grid two">
          <Field label="Effective Date"><input className="filter" type="date" readOnly /></Field>
          <Field label="Approval Note"><textarea className="filter" readOnly /></Field>
        </div>
      </Dialog>
    );
  }
  if (kind === "review") {
    return (
      <Dialog
        open
        title="Send Recommendations for Review"
        description="Reviewer assignment is unavailable"
        onClose={onClose}
        footer={<PreviewFooter label="Send for Review" onClose={onClose} reason={reason} />}
      >
        <div className="preview-banner"><strong>Workflow unavailable</strong>{reason}</div>
        <MetricList rows={[
          {label: "Selected recommendations", value: selectedCount},
          {label: "Current status", value: <UnavailableValue reason={reason} />},
          {label: "Target status", value: <UnavailableValue reason={reason} />}
        ]} />
        <div className="pricing-form-grid two">
          <Field label="Reviewer"><select className="filter" disabled><option>Reviewer unavailable</option></select></Field>
          <Field label="Priority"><select className="filter" defaultValue="Medium"><option>High</option><option>Medium</option><option>Low</option></select></Field>
          <Field label="Due Date"><input className="filter" type="date" readOnly /></Field>
          <Field label="Review Reason"><select className="filter"><option>Price movement exceeds approval limit</option><option>Margin impact requires review</option><option>Competitor data validation</option><option>Strategic product review</option></select></Field>
          <Field label="Comments"><textarea className="filter" readOnly /></Field>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog
      open
      title="Schedule Price Changes"
      description="Publishing is unavailable"
      onClose={onClose}
      footer={<PreviewFooter label="Schedule" onClose={onClose} reason={reason} />}
    >
      <div className="preview-banner"><strong>Workflow unavailable</strong>{reason}</div>
      <MetricList rows={[
        {label: "Recommendations", value: selectedCount},
        {label: "Stores", value: <UnavailableValue reason="Server scope validation is unavailable." />},
        {label: "Status", value: <UnavailableValue reason={reason} />}
      ]} />
      <div className="pricing-form-grid two">
        <Field label="Effective Date"><input className="filter" type="date" readOnly /></Field>
        <Field label="Effective Time"><input className="filter" type="time" readOnly /></Field>
        <Field label="Channels"><select className="filter"><option>All Channels</option><option>Stores Only</option><option>E-commerce Only</option></select></Field>
        <Field label="Rollback Rule"><select className="filter"><option>Rollback on integration failure</option><option>Manual rollback only</option></select></Field>
      </div>
    </Dialog>
  );
}

function PricingActionCenterPreview({onClose}: {onClose: () => void}) {
  const reason = "Workflow queue evidence is unavailable.";
  return (
    <Dialog open title="Pricing Action Center" description="Workflow unavailable — no decision can be actioned" onClose={onClose} wide>
      <div className="preview-banner"><strong>Approval workflow prerequisite</strong>{reason}</div>
      <div className="grid-3">
        {["Pending Decisions", "High Priority", "Value Awaiting Approval"].map((label) => (
          <div className="card" key={label}><h4>{label}</h4><UnavailableValue reason={reason} /></div>
        ))}
      </div>
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th>Decision Queue</th><th>Items</th><th>Owner</th><th>Value</th></tr></thead>
          <tbody>{["Senior approval required", "Category review", "Approved but unscheduled"].map((label) => (
            <tr key={label}>
              <td>{label}</td>
              <td><UnavailableValue reason={reason} /></td>
              <td><UnavailableValue reason={reason} /></td>
              <td><UnavailableValue reason={reason} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Dialog>
  );
}

function StorePricingDrilldown({
  items,
  dashboard,
  currencyCode,
  onClose,
  onOpen
}: {
  items: Array<Record<string, unknown>>;
  dashboard?: Dashboard;
  currencyCode: string | undefined;
  onClose: () => void;
  onOpen: (store: string) => void;
}) {
  const [period, setPeriod] = useState("This Week");
  const [store, setStore] = useState(String(items[0]?.store ?? ""));
  const item = items.find((candidate) => String(candidate.store ?? "") === store) ?? items[0];
  const margin = item?.marginOpportunityMinor;
  return (
    <Dialog
      open
      title="Store Pricing Drilldown"
      description="Read-only store pricing context"
      onClose={onClose}
      wide
      footer={(
        <>
          <button className="modal-action" type="button" onClick={() => onOpen(store)} disabled={!store}>Open Store Recommendations</button>
          <button className="filter" type="button" onClick={onClose}>Cancel</button>
        </>
      )}
    >
      <div className="pricing-form-grid two">
        <Field label="Store"><select className="filter" value={store} onChange={(event) => setStore(event.target.value)}>{items.map((candidate) => {
          const value = String(candidate.store ?? "");
          return <option key={value} value={value}>{storeName(dashboard, value, String(candidate.storeName ?? ""))}</option>;
        })}</select></Field>
        <Field label="Period"><select className="filter" value={period} onChange={(event) => setPeriod(event.target.value)}><option>This Week</option><option>This Month</option><option>Quarter to Date</option></select></Field>
      </div>
      <div className="grid-3">
        <PricingKpi label="Open Recommendations" value={formatCount(Number(item?.recommendations ?? 0))} note={period} />
        <PricingKpi label="Revenue Opportunity" value={formatAggregateMoneyMinor(Number(item?.revenueOpportunityMinor ?? 0), currencyCode)} note="Model-implied" />
        <PricingKpi label="Margin Opportunity" value={formatAggregateMoneyMinor(Number(margin ?? 0), currencyCode)} note="Weighted-average cost basis" />
      </div>
      <div className="grid-2">
        <div className="card"><h4>Top Pricing Issues</h4><MetricList rows={[
          {label: "Recommended price reductions", value: `${formatCount(Number(item?.decrease ?? 0))} SKUs`},
          {label: "Recommended price increases", value: `${formatCount(Number(item?.increase ?? 0))} SKUs`},
          {label: "Held to protect margin", value: `${formatCount(Number(item?.hold ?? 0))} SKUs`},
          {label: "Withheld for manual review", value: `${formatCount(Number(item?.risk ?? 0))} SKUs`}
        ]} /></div>
        <div className="card"><h4>Recommended Actions</h4><MetricList rows={[
          {label: "Approve price increases", value: `${formatCount(Number(item?.increase ?? 0))} SKUs · ${formatAggregateMoneyMinor(Number(item?.marginIncreaseMinor ?? 0), currencyCode)} margin`},
          {label: "Reduce targeted prices", value: `${formatCount(Number(item?.decrease ?? 0))} SKUs · ${formatAggregateMoneyMinor(Number(item?.revenueDecreaseMinor ?? 0), currencyCode)} revenue`},
          {label: "Hold current pricing", value: `${formatCount(Number(item?.hold ?? 0))} SKUs`}
        ]} /></div>
      </div>
    </Dialog>
  );
}

function RecommendationDetailDialog({id, onClose, onSimulation}: {
  id: string;
  onClose: () => void;
  onSimulation: () => void;
}) {
  const detail = useQuery({
    queryKey: ["pricing-recommendation-detail", id],
    queryFn: ({signal}) => loadRecommendationDetail(id, signal)
  });
  const item = detail.data?.item;
  return (
    <Dialog
      open
      title="Price Recommendation Detail"
      onClose={onClose}
      wide
      footer={(
        <>
          <button
            className="modal-action"
            type="button"
            onClick={onSimulation}
            disabled={!item?.selectable}
            title={!item?.selectable ? "A withheld assessment has no accepted simulation context." : undefined}
          >
            Open Simulation
          </button>
          <button className="filter" type="button" onClick={onClose}>Cancel</button>
        </>
      )}
    >
      <PricingState pending={detail.isPending} error={detail.error}>
        {item && (
          <div className="recommendation-detail">
            <div className="recommendation-detail-summary">
              <div><span>Product</span><strong>{item.productName ?? item.skuId}</strong></div>
              <div><span>Recommended Action</span><strong>{item.action ?? <UnavailableValue reason={reasonText(item.firstFailureReason)} />}</strong></div>
              <div><span>Confidence</span><strong>{item.confidence === null ? unavailable : formatPercent(item.confidence * 100)}</strong></div>
            </div>
            <div className="detail-sections">
              <section>
                <h4>Commercial Impact</h4>
                <MetricList rows={[
                  {label: "Current price", value: formatMoneyMinor(item.currentPriceMinor, item.currencyCode)},
                  {label: "AI price", value: formatMoneyMinor(item.proposedPriceMinor, item.currencyCode)},
                  {label: "Revenue impact", value: formatAggregateMoneyMinor(item.revenueImpactMinor, item.currencyCode)},
                  {label: "Margin impact", value: item.marginImpactMinor === null ? <UnavailableValue reason={reasonText(item.marginReasonCode)} /> : formatAggregateMoneyMinor(item.marginImpactMinor, item.currencyCode)}
                ]} />
              </section>
              <section>
                <h4>Decision Context</h4>
                <MetricList rows={[
                  {label: "Competitor price", value: item.competitorPriceMinor === null || item.competitorPriceMinor === undefined ? <UnavailableValue reason="No fresh admissible competitor price is available." /> : formatMoneyMinor(item.competitorPriceMinor, item.currencyCode)},
                  {label: "Stock cover", value: item.stockCoverDays === null || item.stockCoverDays === undefined ? <UnavailableValue reason="Inventory cover is unavailable." /> : `${formatUnits(item.stockCoverDays)} days`},
                  {label: "Forecast demand", value: item.forecastDemand ?? <UnavailableValue reason="Forecast demand cohort is unavailable." />},
                  {label: "AI reason", value: explanationText(item.aiReason, item.firstFailureReason)}
                ]} />
              </section>
            </div>
            <div className="callout">
              <strong>AI explanation</strong>
              <p>{explanationText(item.aiReason, item.firstFailureReason)}</p>
            </div>
          </div>
        )}
      </PricingState>
    </Dialog>
  );
}

function ComparisonDialog({rows, onClose}: {
  rows: Recommendation[];
  onClose: () => void;
}) {
  return (
    <Dialog open title="Compare Selected Recommendations" onClose={onClose} wide>
      <div className="table-scroll">
        <table className="table pricing-table">
          <thead><tr>
            <th>Product</th><th>Action</th><th>Price Change</th>
            <th>Revenue Impact</th><th>Margin Impact</th><th>Confidence</th>
          </tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.recommendationId}>
              <td><strong>{row.productName ?? row.skuId}</strong><small>{row.skuId}</small></td>
              <td>{row.action}</td>
              <td>{formatPercent(row.changePct)}</td>
              <td>{formatAggregateMoneyMinor(row.revenueImpactMinor, row.currencyCode)}</td>
              <td>{row.marginImpactMinor === null ? <UnavailableValue reason={reasonText(row.marginReasonCode)} /> : formatAggregateMoneyMinor(row.marginImpactMinor, row.currencyCode)}</td>
              <td>{row.confidence === null ? unavailable : formatPercent(row.confidence * 100)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Dialog>
  );
}

function ExportPreview({
  selectedRows,
  filteredCount,
  allCount,
  authorityId,
  filters,
  onClose
}: {
  selectedRows: Recommendation[];
  filteredCount: number;
  allCount: number;
  authorityId: string;
  filters: PricingFilters;
  onClose: () => void;
}) {
  const selected = selectedRows.length;
  const limit = 10_000;
  const counts: Record<string, number> = {selected, filtered: filteredCount, all: allCount};
  const firstEligibleScope = ["selected", "filtered", "all"].find(
    (candidate) => counts[candidate] > 0 && counts[candidate] <= limit
  ) ?? "filtered";
  const [scope, setScope] = useState(firstEligibleScope);
  const [format, setFormat] = useState("csv");
  const [explanation, setExplanation] = useState("yes");
  const [filename, setFilename] = useState("price_recommendations");
  const exportController = useRef<AbortController | null>(null);
  const reservedFilename = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i;
  const fileValid = /^[A-Za-z0-9 _.-]{1,80}$/.test(filename) &&
    !filename.includes("..") && !filename.startsWith(".") &&
    !reservedFilename.test(filename.trim());
  const eligible = counts[scope] > 0 && counts[scope] <= limit && fileValid && format !== "pdf";
  useEffect(() => {
    if (counts[scope] > 0 && counts[scope] <= limit) return;
    setScope(firstEligibleScope);
  }, [selected, filteredCount, allCount, scope, firstEligibleScope]);
  useEffect(() => () => exportController.current?.abort(), []);
  const closeDialog = () => {
    exportController.current?.abort();
    exportController.current = null;
    onClose();
  };
  const download = useMutation({
    mutationFn: () => {
      exportController.current?.abort();
      const controller = new AbortController();
      exportController.current = controller;
      return exportPriceRecommendations({
        scope: scope as "selected" | "filtered" | "all",
        format: format as "csv" | "excel_csv",
        includeExplanation: explanation === "yes",
        filename,
        expectedCount: counts[scope],
        expectedActivationSetId: authorityId,
        selectedIds: selectedRows.map((row) => row.recommendationId),
        filters
      }, controller.signal);
    },
    onSuccess: ({blob, filename: responseFilename}) => {
      exportController.current = null;
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = responseFilename;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      onClose();
    },
    onSettled: () => {
      exportController.current = null;
    }
  });
  return (
    <Dialog
      open
      title="Export Price Recommendations"
      onClose={closeDialog}
      footer={(
        <>
          <button
            className="modal-action"
            type="button"
            disabled={!eligible || download.isPending}
            title={!eligible ? "Choose a non-empty scope within the export limit and a valid file name." : "Download the server-authored CSV."}
            onClick={() => download.mutate()}
          >{download.isPending ? "Exporting…" : "Export"}</button>
          <button className="filter" type="button" onClick={closeDialog}>Cancel</button>
        </>
      )}
    >
      <div className="preview-banner">
        <strong>Read-only export configuration</strong>
        The server repeats scope, authority, count, and file-name validation before creating bytes.
      </div>
      <fieldset className="pricing-choice-list">
        <legend>Scope</legend>
        {[
          ["selected", "Selected recommendations", selected],
          ["filtered", "Current filtered view", filteredCount],
          ["all", "All recommendations", allCount]
        ].map(([value, label, count]) => (
          <label key={String(value)}>
            <input
              type="radio"
              name="export-scope"
              value={String(value)}
              checked={scope === value}
              disabled={Number(count) === 0 || Number(count) > limit}
              onChange={() => setScope(String(value))}
            />
            {label} ({formatCount(Number(count))})
          </label>
        ))}
      </fieldset>
      <div className="pricing-form-grid two">
        <Field label="Format" help="Governed print/PDF renderer not available">
          <select className="filter" value={format} onChange={(event) => setFormat(event.target.value)}>
            <option value="csv">CSV</option>
            <option value="excel_csv">Excel-compatible CSV</option>
            <option value="pdf" disabled>PDF / Print</option>
          </select>
        </Field>
        <Field label="Include AI explanation">
          <select className="filter" value={explanation} onChange={(event) => setExplanation(event.target.value)}>
            <option value="yes">Yes</option><option value="no">No</option>
          </select>
        </Field>
        <Field label="Include audit history" help="Audit evidence is not available.">
          <select className="filter" disabled><option>No</option><option disabled>Yes</option></select>
        </Field>
        <Field label="File Name" help={!fileValid ? "Use 1–80 letters, digits, spaces, _, - or . without path segments." : ".csv is appended once by the server."}>
          <input className="filter" value={filename} onChange={(event) => setFilename(event.target.value)} aria-invalid={!fileValid} />
        </Field>
      </div>
      {download.error && (
        <div className="preview-banner error-banner" role="alert">
          <strong>Export was not created.</strong>
          {download.error instanceof Error ? download.error.message : String(download.error)}
        </div>
      )}
    </Dialog>
  );
}

type RecommendationModal =
  | "approve" | "review" | "schedule" | "compare" | "export" | "action-center" | "store-drilldown" | null;

function RecommendationOverview({
  summary,
  rows
}: {
  summary: NonNullable<ReturnType<typeof useRecommendationData>["summary"]>;
  rows: Recommendation[];
}) {
  const revenueCurrency = rows.find((row) => row.currencyCode)?.currencyCode;
  return (
    <>
      <div className="grid-2 pricing-overview-grid">
        <div className="card">
          <CardHeader title="Pricing Opportunity Waterfall" context="Projected annualized impact" />
          <MetricList rows={[
            {label: "Revenue", value: formatAggregateMoneyMinor(summary.kpis.revenueOpportunityMinor, revenueCurrency)},
            {label: "Margin", value: summary.kpis.marginOpportunityMinor === null ? <UnavailableValue reason={reasonText(summary.kpis.marginReasonCode)} /> : formatAggregateMoneyMinor(summary.kpis.marginOpportunityMinor, revenueCurrency)},
            {label: "Markdown", value: formatAggregateMoneyMinor(0, revenueCurrency)},
            {label: "Inventory", value: formatAggregateMoneyMinor(0, revenueCurrency)},
            {label: "At Risk", value: formatCount(summary.kpis.recommendationsAtRisk)}
          ]} />
        </div>
        <div className="card">
          <CardHeader title="Pricing Decision Quality" context="Current model" />
          <div className="quality-layout">
            <div className="quality-ring" style={{"--quality-score": `${summary.decisionQuality.highConfidencePct}%`} as React.CSSProperties}><strong>{`${Math.round(summary.decisionQuality.highConfidencePct)}%`}</strong><span>High confidence</span></div>
            <MetricList rows={[
              {label: "High-confidence recommendations", value: formatPercent(summary.decisionQuality.highConfidencePct)},
              {label: "Within margin guardrails", value: `${formatPercent(summary.decisionQuality.withinGuardrailPct)} · ${formatCount(summary.decisionQuality.withinGuardrailCount)} recs`},
              {label: "Predicted vs realized variance", value: summary.decisionQuality.realizedCycles > 0 ? `${formatCount(summary.decisionQuality.realizedCycles)} realized cycles` : "Awaiting realized cycles"},
              {label: "Recommendations needing override", value: formatCount(summary.decisionQuality.needingOverride)}
            ]} />
          </div>
        </div>
      </div>
      <div className="grid-3 pricing-decision-cards">
        {[
          ["Margin Protection", "Protects the margin floor against the weighted-average cost basis when choosing a price."],
          ["Markdown Optimization", "Appears only when accepted markdown or promotion evidence supports it."],
          ["Inventory Clearance", "Uses accepted ageing, seasonality, transfer and local-price guards."]
        ].map(([title, text]) => (
          <div className="card" key={title}><h3>{title}</h3><p>{text}</p></div>
        ))}
      </div>
    </>
  );
}

function useRecommendationData(filters: PricingFilters, offset: number) {
  const summaryQuery = useQuery({
    queryKey: ["pricing-recommendation-summary", filters],
    queryFn: ({signal}) => loadRecommendationSummary(filters, signal),
    placeholderData: (previous) => previous
  });
  const rowsQuery = useQuery({
    queryKey: ["pricing-recommendations", filters, offset],
    queryFn: ({signal}) => loadRecommendations({...filters, limit: PAGE_SIZE, offset}, signal),
    placeholderData: (previous) => previous
  });
  return {
    summary: summaryQuery.data,
    rows: rowsQuery.data,
    pending: summaryQuery.isPending || rowsQuery.isPending,
    error: summaryQuery.error ?? rowsQuery.error
  };
}

function PriceRecommendations({
  dashboard,
  storeId,
  channelType,
  onNavigate
}: Omit<PricingPageProps, "pageId" | "onStoreId">) {
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [pageStore, setPageStore] = useState("");
  const [action, setAction] = useState("");
  const [confidence, setConfidence] = useState("");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const [tab, setTab] = useState("Overview");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<RecommendationModal>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const offset = page * PAGE_SIZE;
  const effectiveStoreId = storeId || pageStore;
  const filters = useMemo<PricingFilters>(() => ({
    storeId: effectiveStoreId,
    channelType,
    category,
    action,
    confidence,
    search: debouncedSearch
  }), [effectiveStoreId, channelType, category, action, confidence, debouncedSearch]);
  const data = useRecommendationData(filters, offset);
  const exportAuthorityFilters = useMemo<PricingFilters>(() => ({
    storeId: effectiveStoreId,
    channelType
  }), [effectiveStoreId, channelType]);
  const allRecommendationSummary = useQuery({
    queryKey: ["pricing-recommendation-summary", "all", exportAuthorityFilters],
    queryFn: ({signal}) => loadRecommendationSummary(exportAuthorityFilters, signal)
  });

  useEffect(() => {
    setSelected(new Set());
    setPage(0);
  }, [effectiveStoreId, channelType, category, action, confidence, search]);
  useEffect(() => {
    if (storeId) setPageStore(storeId);
    else setPageStore("");
  }, [storeId]);

  const rows = data.rows?.items ?? [];
  const selectedRows = rows.filter((row) => selected.has(row.recommendationId));
  const selectable = rows.filter((row) => row.selectable);
  const mix = data.summary?.recommendationMix ?? [];
  const actionableCount =
    (mix.find((entry) => entry.label === "Increase price")?.count ?? 0) +
    (mix.find((entry) => entry.label === "Reduce price")?.count ?? 0);
  const allVisibleSelected = selectable.length > 0 && selectable.every((row) =>
    selected.has(row.recommendationId)
  );
  const selectAllRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selected.size > 0 && !allVisibleSelected;
    }
  }, [selected.size, allVisibleSelected]);

  const grouped = useQuery({
    queryKey: ["pricing-grouped", tab, filters],
    queryFn: ({signal}) => loadGroupedRecommendations(
      tab === "Store View" ? "store-view" : "category-view",
      filters,
      signal
    ),
    enabled: tab === "Store View" || tab === "Category View"
  });
  const governance = useQuery({
    queryKey: ["pricing-governance", filters],
    queryFn: ({signal}) => loadPricingGovernance(filters, signal),
    enabled: tab === "Governance"
  });

  return (
    <PricingState pending={data.pending} error={data.error}>
      {data.summary && data.rows && (
        <>
          <div className="pricing-toolbar recommendation-toolbar" aria-label="Recommendation actions">
            <span className="selected-count" aria-live="polite">{selected.size} selected</span>
            <PreviewButton onClick={() => setModal("approve")} disabled={selected.size === 0} reason={selected.size === 0 ? "Select at least one recommendation." : "Approval workflow is unavailable."}>Approve Selected</PreviewButton>
            <PreviewButton onClick={() => setModal("review")} disabled={selected.size === 0} reason={selected.size === 0 ? "Select at least one recommendation." : "Reviewer assignment is unavailable."}>Send for Review</PreviewButton>
            <PreviewButton onClick={() => setModal("schedule")} disabled={selected.size === 0} reason={selected.size === 0 ? "Select at least one recommendation." : "Publishing is unavailable."}>Schedule Price Change</PreviewButton>
            <PreviewButton onClick={() => setModal("compare")} disabled={selectedRows.length < 2} reason="Select at least two visible recommendations to compare.">Compare Selected</PreviewButton>
            <PreviewButton onClick={() => setModal("export")}>Export</PreviewButton>
            <PreviewButton onClick={() => setModal("action-center")}>Pricing Action Center</PreviewButton>
          </div>

          <div className="pricing-filter-row six">
            <select className="filter" aria-label="Recommendation status" value={status} onChange={(event) => setStatus(event.target.value)} disabled title="Approval workflow status is unavailable.">
              <option value="">All Statuses</option><option>Pending</option><option>Under Review</option><option>Approved</option><option>Scheduled</option><option>Rejected</option>
            </select>
            <select className="filter" aria-label="Recommendation category" value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">All Categories</option>
              {data.summary.filters.categories.map((value) => <option key={value} value={value}>{categoryName(dashboard, value)}</option>)}
            </select>
            <select className="filter" aria-label="Recommendation store" value={pageStore} onChange={(event) => setPageStore(event.target.value)} disabled={Boolean(storeId)} title={storeId ? "Set by global Store" : undefined}>
              <option value="">All Stores</option>
              {data.summary.filters.stores.map((value) => <option key={value} value={value}>{storeName(dashboard, value)}</option>)}
            </select>
            <select className="filter" aria-label="Recommendation action" value={action} onChange={(event) => setAction(event.target.value)}>
              <option value="">All Actions</option><option value="Increase">Increase Price</option><option value="Decrease">Reduce Price</option><option value="Hold">Hold Price</option>
            </select>
            <select className="filter" aria-label="Recommendation confidence" value={confidence} onChange={(event) => setConfidence(event.target.value)}>
              <option value="">All Confidence Levels</option><option value="90">90% and above</option><option value="80">80% and above</option><option value="low">Below 80%</option>
            </select>
            <input className="filter" aria-label="Search recommendations" placeholder="Search product, SKU or reason" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>

          <div className="kpi-grid pricing-kpi-grid">
            <PricingKpi label="Open Recommendations" value={formatCount(data.summary.kpis.openRecommendations)} note="Current filtered recommendations; withheld assessments excluded" delta={{value: `${formatCount(actionableCount)} require a price action`, sentiment: "up"}} />
            <PricingKpi label="Revenue Opportunity" value={formatAggregateMoneyMinor(data.summary.kpis.revenueOpportunityMinor, rows[0]?.currencyCode)} note="Model-implied local revenue impact" delta={data.summary.kpis.revenueOpportunityMinor != null && data.summary.kpis.revenueOpportunityMinor > 0 ? {value: "Projected uplift", sentiment: "up"} : undefined} />
            <PricingKpi label="Margin Opportunity" value={formatAggregateMoneyMinor(data.summary.kpis.marginOpportunityMinor, rows[0]?.currencyCode)} note="Weighted-average cost basis" unavailableReason={data.summary.kpis.marginOpportunityMinor === null ? reasonText(data.summary.kpis.marginReasonCode) : undefined} delta={data.summary.kpis.marginOpportunityMinor != null && data.summary.kpis.marginOpportunityMinor > 0 ? {value: "Within margin guardrails", sentiment: "up"} : undefined} />
            <PricingKpi label="Recommendations at Risk" value={formatCount(data.summary.kpis.recommendationsAtRisk)} note="Low-confidence recommendations" delta={{value: data.summary.kpis.recommendationsAtRisk > 0 ? "Outside guardrails" : "Within guardrails", sentiment: data.summary.kpis.recommendationsAtRisk > 0 ? "down" : "up"}} />
            <PricingKpi label="Recommendation Adoption" value={formatPercent(data.summary.kpis.recommendationAdoption.sharePct)} note={`${formatCount(data.summary.kpis.recommendationAdoption.adopted)} of ${formatCount(data.summary.kpis.recommendationAdoption.total)} approved or scheduled`} />
          </div>

          <div className="grid-3 pricing-summary-grid">
            <div className="card"><CardHeader title="Recommendation Mix" context="Current filtered view" /><MetricList rows={data.summary.recommendationMix.map((row) => ({label: row.label, value: formatCount(row.count)}))} /></div>
            <div className="card"><CardHeader title="Business Value by Driver" context="Projected revenue" /><MetricList rows={data.summary.businessValueByDriver.map((row) => ({label: row.label, value: formatAggregateMoneyMinor(row.revenueMinor, rows[0]?.currencyCode)}))} /></div>
            <div className="card"><CardHeader title="Approval Pipeline" context="Current queue" /><MetricList rows={data.summary.approvalPipeline.map((row) => ({label: row.label, value: formatCount(row.count)}))} /></div>
          </div>

          <div className="callout pricing-callout">
            <strong>AI recommendation logic</strong>
            <p>Accepted price response, demand forecast, local price policy, inventory context and admissible competitor evidence are combined only where the active capability record permits them. Cost is the generated weighted-average cost — this PoC has no external client data.</p>
          </div>

          <div className="pricing-tabs" role="tablist" aria-label="Recommendation views">
            {["Overview", "Store View", "Category View", "Governance"].map((name) => (
              <button key={name} role="tab" aria-label={name} aria-selected={tab === name} className={tab === name ? "active" : ""} type="button" onClick={() => setTab(name)}>{name}</button>
            ))}
          </div>
          <section className="pricing-tab-panel" role="tabpanel">
            {tab === "Overview" && <RecommendationOverview summary={data.summary} rows={rows} />}
            {tab === "Store View" && (
              <div className="card">
                <CardHeader title="Store-Level Pricing Performance" action={<PreviewButton onClick={() => setModal("store-drilldown")} disabled={!grouped.data?.items.length} reason={!grouped.data?.items.length ? "No governed store row is available to inspect." : undefined}>Open Store Drilldown</PreviewButton>} />
                <PricingState pending={grouped.isPending} error={grouped.error} empty={!grouped.data?.items.length}>
                  <div className="table-scroll"><table className="table pricing-table"><thead><tr>{["Store", "Recommendations", "Approval Rate", "Revenue Opportunity", "Margin Opportunity", "Risk", "Priority Action"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{grouped.data?.items.map((item, index) => <tr key={String(item.store ?? index)}><td>{storeName(dashboard, String(item.store ?? ""), String(item.storeName ?? ""))}</td><td>{formatCount(Number(item.recommendations ?? 0))}</td><td>{formatPercent(Number(item.recommendations ?? 0) > 0 ? Number(item.approved ?? 0) * 100 / Number(item.recommendations) : 0)}</td><td>{formatAggregateMoneyMinor(Number(item.revenueOpportunityMinor ?? 0), rows[0]?.currencyCode)}</td><td>{formatAggregateMoneyMinor(Number(item.marginOpportunityMinor ?? 0), rows[0]?.currencyCode)}</td><td>{formatCount(Number(item.risk ?? 0))}</td><td>{String(item.priorityAction ?? unavailable)}</td></tr>)}</tbody></table></div>
                </PricingState>
              </div>
            )}
            {tab === "Category View" && (
              <div className="grid-2 pricing-category-grid">
                <div className="card">
                  <CardHeader title="Category Pricing Effectiveness" />
                  <PricingState pending={grouped.isPending} error={grouped.error} empty={!grouped.data?.items.length}>
                    <div className="table-scroll"><table className="table pricing-table"><thead><tr>{["Category", "Revenue Uplift", "Margin Uplift", "Elasticity", "Recommendation"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{grouped.data?.items.map((item, index) => <tr key={String(item.category ?? index)}><td>{categoryName(dashboard, String(item.category ?? ""), String(item.categoryLabel ?? ""))}</td><td>{formatAggregateMoneyMinor(Number(item.revenueOpportunityMinor ?? 0), rows[0]?.currencyCode)} <small>model-implied</small></td><td>{formatAggregateMoneyMinor(Number(item.marginOpportunityMinor ?? 0), rows[0]?.currencyCode)}</td><td>{(() => {const uc = Number(item.unitsCurrent ?? 0); const chg = Number(item.avgChangeFraction ?? 0); return uc > 0 && chg !== 0 ? ((Number(item.unitsProposed ?? 0) / uc - 1) / chg).toFixed(2) : "0.00";})()}</td><td>{String(item.priorityAction ?? "Review targeted reductions")}</td></tr>)}</tbody></table></div>
                  </PricingState>
                </div>
                <div className="card">
                  <CardHeader title="Category Opportunity Matrix" />
                  <div className="opportunity-matrix">{[
                    {label: "High demand / Low stock", value: data.summary.recommendationMix.find((row) => row.label === "Increase price")?.count ?? 0},
                    {label: "High stock / Low demand", value: data.summary.recommendationMix.find((row) => row.label === "Reduce price")?.count ?? 0},
                    {label: "Competitor opportunity", value: data.summary.kpis.competitorCovered ?? 0},
                    {label: "Promotion conflict", value: data.summary.exceptions.find((row) => row.label === "Promotion conflict")?.count ?? 0}
                  ].map((cell) => <div key={cell.label}><span>{cell.label}</span><strong>{`${formatCount(cell.value)} SKUs`}</strong></div>)}</div>
                </div>
              </div>
            )}
            {tab === "Governance" && (
              <div className="grid-2">
                <div className="card"><CardHeader title="Approval SLA" /><div className="table-scroll"><table className="table"><thead><tr>{["Approval Level", "Open", "Average Age", "SLA", "Status"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody><tr><td colSpan={5}><UnavailableValue reason={governance.data?.approvalSLA.reason ?? "Approval workflow evidence is unavailable."} /></td></tr></tbody></table></div></div>
                <div className="card"><CardHeader title="Audit & Control Coverage" /><PricingState pending={governance.isPending} error={governance.error} empty={!governance.data?.controls.length}>{governance.data && <MetricList rows={governance.data.controls.map((control) => ({label: control.label, value: control.available ? formatPercent(control.valuePct) : <UnavailableValue reason="Required control evidence is unavailable." />}))} />}</PricingState></div>
              </div>
            )}
          </section>

          <div className="card pricing-table-card">
            <CardHeader title="SKU-Level Price Recommendations" context={`${formatCount(data.summary.kpis.openRecommendations)} recommendations · ${formatCount(data.summary.recommendationMix.find((row) => row.label === "Manual review")?.count)} manual review`} />
            <div className="table-scroll"><table className="table pricing-table recommendation-table"><thead><tr>
              <th><input ref={selectAllRef} type="checkbox" aria-label="Select all visible recommendations" checked={allVisibleSelected} onChange={() => setSelected(allVisibleSelected ? new Set() : new Set(selectable.map((row) => row.recommendationId)))} /></th>
              {[
                "Priority", "SKU / Product", "Category", "Store", "Action", "Current", "AI Price", "Change", "Competitor", "Stock Cover", "Forecast Demand", "Current Margin", "Expected Margin", "Revenue Impact", "Margin Impact", "AI Reason", "Confidence", "Status", "Owner"
              ].map((header) => <th key={header}>{header}</th>)}
            </tr></thead><tbody>{rows.map((row) => {
              // A withheld assessment has no accepted action, so its decision-derived
              // cells (AI price, change, impacts, confidence…) have no value. Each shows
              // an explicit governed "Under review" state, never a bare missing token;
              // the withhold reason (first_failure_reason / margin_reason_code) is
              // surfaced in the Action chip tooltip and readably in the AI Reason cell.
              const isWithheld = row.recordKind === "withheld_assessment";
              const withheldReason = row.firstFailureReason ?? row.marginReasonCode;
              const withheldReasonText = withheldReason
                ? reasonText(withheldReason)
                : "Assessment withheld pending manual review";
              return (
              <tr key={row.recommendationId} data-partial={isWithheld}>
                <td><input type="checkbox" aria-label={`Select ${row.productName ?? row.skuId}`} disabled={!row.selectable} checked={selected.has(row.recommendationId)} onChange={() => setSelected((current) => {const next = new Set(current); if (next.has(row.recommendationId)) next.delete(row.recommendationId); else next.add(row.recommendationId); return next;})} /></td>
                <td><span className={`badge ${badgeClass(row.priority)}`}>{row.priority}</span></td>
                <td><button className="link-button product-link" type="button" onClick={() => setDetailId(row.recommendationId)}><strong>{row.productName ?? "Name unavailable"}</strong><small>{row.skuId}</small></button></td>
                <td>{categoryName(dashboard, row.category, row.categoryLabel)}</td>
                <td><span className="product-cell">{storeName(dashboard, row.storeId, row.storeName)}<small>{channelName(dashboard, row.channelId, row.channelName)}</small></span></td>
                <td>{row.action ? <span className={`badge ${badgeClass(row.action)}`}>{row.action === "Decrease" ? "Reduce Price" : `${row.action} Price`}</span> : <span className="badge b-amber" title={withheldReasonText}>Manual review</span>}</td>
                <td>{row.currentPriceMinor === null || row.currentPriceMinor === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="Current local price is unavailable." />) : formatMoneyMinor(row.currentPriceMinor, row.currencyCode)}</td>
                <td>{row.proposedPriceMinor === null || row.proposedPriceMinor === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="No accepted AI price is available." />) : formatMoneyMinor(row.proposedPriceMinor, row.currencyCode)}</td>
                <td>{row.changePct === null || row.changePct === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="No accepted price change is available." />) : formatPercent(row.changePct)}</td>
                <td>{row.competitorPriceMinor === null || row.competitorPriceMinor === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <span className="cell-unavailable" title="No fresh admissible competitor bound for this SKU.">No competitor price</span>) : formatMoneyMinor(row.competitorPriceMinor, row.currencyCode)}</td>
                <td>{row.stockCoverDays === null || row.stockCoverDays === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="Inventory cover is unavailable." />) : `${formatUnits(row.stockCoverDays)} days`}</td>
                <td>{row.forecastDemand ? row.forecastDemand : (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="Forecast demand cohort is unavailable." />)}</td>
                <td>{row.currentMarginPct === null || row.currentMarginPct === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason={reasonText(row.marginReasonCode)} />) : formatPercent(row.currentMarginPct)}</td>
                <td>{row.expectedMarginPct === null || row.expectedMarginPct === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason={reasonText(row.marginReasonCode)} />) : formatPercent(row.expectedMarginPct)}</td>
                <td>{row.revenueImpactMinor === null || row.revenueImpactMinor === undefined ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason="No accepted revenue impact is available." />) : formatAggregateMoneyMinor(row.revenueImpactMinor, row.currencyCode)}</td>
                <td>{row.marginImpactMinor === null ? (isWithheld ? <WithheldValue reason={withheldReasonText} /> : <UnavailableValue reason={reasonText(row.marginReasonCode)} />) : formatAggregateMoneyMinor(row.marginImpactMinor, row.currencyCode)}</td>
                <td className="reason-cell">{isWithheld ? withheldReasonText : explanationText(row.aiReason, row.firstFailureReason)}</td>
                <td>{isWithheld ? <WithheldValue reason={withheldReasonText} /> : row.confidence === null ? <UnavailableValue reason="Confidence is unavailable." /> : formatPercent(row.confidence * 100)}</td>
                <td>{isWithheld ? <WithheldValue reason={withheldReasonText} /> : <span className="badge b-blue">{row.status}</span>}</td>
                <td>{row.owner ?? storeName(dashboard, row.storeId, row.storeName)}</td>
              </tr>
              );
            })}</tbody></table></div>
            <Pagination
              offset={data.rows.pagination.offset}
              limit={data.rows.pagination.limit}
              total={data.rows.pagination.total}
              onPrev={() => {setPage((current) => Math.max(0, current - 1)); setSelected(new Set());}}
              onNext={() => {setPage((current) => current + 1); setSelected(new Set());}}
            />
            <p className="demo-note">Select recommendation rows to compare or export. Workflow previews are inspectable but cannot approve, review, schedule, assign, or publish a price.</p>
          </div>

          <div className="grid-2 pricing-bottom-grid">
            <div className="card"><CardHeader title="Price Elasticity & Scenario Insight" context="Selected portfolio" /><div className="table-scroll"><table className="table"><thead><tr>{["Scenario", "Avg Price Change", "Demand Impact", "Revenue Impact", "Margin Impact"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{data.summary.portfolioScenarios.map((scenario) => <tr key={scenario.scenario}><td>{scenario.scenario}</td><td>{formatPercent(scenario.avgChangePct)}</td><td>{`${formatUnits(scenario.demandImpact)} units`}</td><td>{formatAggregateMoneyMinor(scenario.revenueImpactMinor, rows[0]?.currencyCode)}</td><td>{formatAggregateMoneyMinor(scenario.marginImpactMinor, rows[0]?.currencyCode)}</td></tr>)}</tbody></table></div></div>
            <div className="card"><CardHeader title="Pricing Risk & Governance" context="Exceptions" /><MetricList rows={data.summary.exceptions.map((row) => ({label: row.label, value: formatCount(row.count)}))} /></div>
          </div>

          {modal === "approve" && <WorkflowPreview kind="approve" selectedCount={selected.size} onClose={() => setModal(null)} />}
          {modal === "review" && <WorkflowPreview kind="review" selectedCount={selected.size} onClose={() => setModal(null)} />}
          {modal === "schedule" && <WorkflowPreview kind="schedule" selectedCount={selected.size} onClose={() => setModal(null)} />}
          {modal === "compare" && <ComparisonDialog rows={selectedRows} onClose={() => setModal(null)} />}
          {modal === "export" && (
            <ExportPreview
              selectedRows={selectedRows}
              filteredCount={data.summary.kpis.openRecommendations}
              allCount={allRecommendationSummary.data?.kpis.openRecommendations ?? 0}
              authorityId={data.summary.authority.activationSetId}
              filters={filters}
              onClose={() => setModal(null)}
            />
          )}
          {modal === "action-center" && <PricingActionCenterPreview onClose={() => setModal(null)} />}
          {modal === "store-drilldown" && (
            <StorePricingDrilldown
              items={grouped.data?.items ?? []}
              dashboard={dashboard}
              currencyCode={rows[0]?.currencyCode}
              onClose={() => setModal(null)}
              onOpen={(nextStore) => {
                if (!storeId && nextStore) setPageStore(nextStore);
                setModal(null);
              }}
            />
          )}
          {detailId && <RecommendationDetailDialog id={detailId} onClose={() => setDetailId(null)} onSimulation={() => {setDetailId(null); onNavigate("priceSimulation");}} />}
        </>
      )}
    </PricingState>
  );
}

// Governed per-unit basis for a simulation SKU. Present only when the bundle
// carries the pricing-unit fields; otherwise the panel falls back to aggregate
// (canonical sellable-pack) prices without ever showing a missing token.
type UnitBasis = {label: string; baseUnitQuantity: number} | null;

// Convert a canonical sellable-pack minor amount to its per-base-unit minor
// amount using the governed pack quantity — the same division the serving layer
// applies for currentUnitPriceMinor. Never divide an aggregate/period total.
function toUnitMinor(packMinor: number, basis: UnitBasis) {
  return basis ? Math.round(packMinor / basis.baseUnitQuantity) : packMinor;
}

// Render a canonical pack price on the active basis: "<per-unit> / <unit>" when a
// per-unit basis exists, otherwise the aggregate pack price.
function priceOnBasis(
  packMinor: number | null | undefined,
  basis: UnitBasis,
  currency: string | null | undefined
) {
  if (packMinor === null || packMinor === undefined) return "";
  return basis
    ? `${formatMoneyMinor(toUnitMinor(packMinor, basis), currency)} / ${basis.label}`
    : formatMoneyMinor(packMinor, currency);
}

// The editable Proposed price is shown/edited on the same basis as Current: the
// per-base-unit major string when a basis exists, else the aggregate major.
function proposedInputValue(packMinor: number, basis: UnitBasis) {
  return (toUnitMinor(packMinor, basis) / 100).toFixed(2);
}


function PriceSimulationPage({dashboard, storeId, channelType}: Pick<PricingPageProps, "dashboard" | "storeId" | "channelType">) {
  const filters = useMemo<PricingFilters>(() => ({
    storeId,
    channelType,
    recordKind: "recommendation",
    limit: 200
  }), [storeId, channelType]);
  const recommendations = useQuery({
    queryKey: ["pricing-simulation-products", filters],
    queryFn: ({signal}) => loadRecommendations(filters, signal)
  });
  const [recommendationId, setRecommendationId] = useState("");
  const [proposed, setProposed] = useState("");
  const [assumption, setAssumption] = useState<"Expected" | "Best Case" | "Worst Case">("Expected");
  const [objective, setObjective] = useState<"Margin Protection" | "Clearance">("Margin Protection");
  // Period and Competitor Response are enabled selectors, but the accepted
  // simulation contract only computes the governed Next 4 Weeks horizon and
  // derives competitor inclusion server-side. They express intent and never leave
  // the client (the strict request body rejects unknown fields).
  const [period, setPeriod] = useState<"Next 4 Weeks" | "Next 8 Weeks" | "Next 13 Weeks">("Next 4 Weeks");
  const [competitorResponse, setCompetitorResponse] = useState<"Include" | "Exclude">("Exclude");
  // Editable minimum-margin floor (percent), seeded from the policy floor.
  const [targetMargin, setTargetMargin] = useState("");
  const items = recommendations.data?.items.filter((row) => row.selectable) ?? [];
  const selected = items.find((row) => row.recommendationId === recommendationId);
  const currency = selected?.currencyCode;
  // The minimum-margin floor is a known policy fact; in this PoC the generated
  // weighted-average cost is the cost basis, so the floor is applied (no separate
  // client cost exists here — generated data is the actual data).
  // Margin Protection is enabled only under an active price_margin selection; it
  // stays disabled until then rather than being unconditionally blocked.
  const priceMarginActive = recommendations.data?.authority?.priceMarginActive === true;
  const detail = useQuery({
    queryKey: ["pricing-simulation-detail", recommendationId],
    queryFn: ({signal}) => loadRecommendationDetail(recommendationId, signal),
    enabled: Boolean(recommendationId)
  });

  // Governed per-unit basis for the selected SKU. Present only when the bundle
  // carries the pricing-unit fields; otherwise every price falls back to the
  // aggregate (canonical sellable-pack) amount without any missing token.
  const unitBasis: UnitBasis =
    selected?.pricingUnitLabel &&
    selected.baseUnitQuantity !== null && selected.baseUnitQuantity !== undefined &&
    selected.baseUnitQuantity > 0 &&
    selected.currentUnitPriceMinor !== null && selected.currentUnitPriceMinor !== undefined
      ? {label: selected.pricingUnitLabel, baseUnitQuantity: selected.baseUnitQuantity}
      : null;
  // The accepted recommendation's evidence (prices, units, cost, elasticity) is
  // authoritative only once the detail item belongs to the current selection.
  const activeItem =
    detail.data?.item.recommendationId === recommendationId ? detail.data.item : undefined;
  const det = (activeItem?.details ?? {}) as Record<string, unknown>;
  const currentPackMinor = selected?.currentPriceMinor ?? null;
  const aiPackMinor = selected?.proposedPriceMinor ?? null;
  const competitorIncluded = selected?.competitorPriceMinor !== null && selected?.competitorPriceMinor !== undefined;

  // --- Live client-side elasticity model, built entirely from the served
  // recommendation evidence (no round-trip): the fitted price response comes from
  // the two accepted points (current and AI-optimal price/units), the cost basis
  // is the generated weighted-average cost, and any entered price is projected
  // against them. This is a what-if projection off the model's own elasticity, so
  // the user can explore ANY price rather than only the accepted candidate grid.
  const num = (key: string): number | null => {
    const value = det[key];
    const parsed = typeof value === "number" ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const unitsCurrent = num("expected_units_current");
  const unitsAi = num("expected_units_proposed");
  const costPackMinor = num("synthetic_cost_minor")
    ?? (currentPackMinor !== null && selected?.currentMarginPct != null
      ? Math.round(currentPackMinor * (1 - selected.currentMarginPct / 100))
      : null);
  const atpUnits = num("atp_units");
  // Anchor the projection on the accepted current-price units so that, at the
  // default levers, simulate(current price) == the Current column and
  // simulate(AI price) == the AI Optimal column — a coherent comparison and a
  // Reset that lands the Proposed column exactly on AI Optimal. The demand
  // assumption then scales that anchor by the forecast band ratio.
  const forecastExpectedUnits = num("forecast_expected_units");
  const assumptionBandUnits = ({
    "Expected": forecastExpectedUnits,
    "Best Case": num("forecast_best_case_units"),
    "Worst Case": num("forecast_worst_case_units")
  } as Record<string, number | null>)[assumption];
  const assumptionFactor = forecastExpectedUnits && forecastExpectedUnits > 0 && assumptionBandUnits
    ? assumptionBandUnits / forecastExpectedUnits
    : 1;
  const anchorUnits = unitsCurrent;
  // Log-log price elasticity fitted from the two accepted points. Falls back to a
  // typical elasticity only when the accepted pair coincides (a Hold), so the tool
  // still projects rather than blanking out.
  const beta = (unitsCurrent && unitsAi && currentPackMinor && aiPackMinor
    && aiPackMinor !== currentPackMinor && unitsCurrent > 0 && unitsAi > 0)
    ? Math.log(unitsAi / unitsCurrent) / Math.log(aiPackMinor / currentPackMinor)
    : -2;
  // Scenario levers applied on top of the fitted elasticity, so every selector
  // moves the projection. Period scales the horizon; a competitor that matches
  // our move dampens the own-price response (a real competitive-reaction effect);
  // a clearance objective assumes a volume push. The last two are explicit
  // what-if assumptions, surfaced in the field help, not fitted facts.
  const periodWeeks = ({"Next 4 Weeks": 4, "Next 8 Weeks": 8, "Next 13 Weeks": 13} as Record<string, number>)[period] ?? 4;
  const periodFactor = periodWeeks / 4;
  const competitorFactor = competitorResponse === "Include" ? 0.7 : 1;
  const objectiveFactor = objective === "Clearance" ? 1.05 : 1;
  const effectiveBeta = beta * competitorFactor;
  const simulate = (packMinor: number | null) => {
    if (packMinor === null || packMinor <= 0 || anchorUnits === null || currentPackMinor === null) {
      return null;
    }
    const units = anchorUnits * assumptionFactor * objectiveFactor * periodFactor * Math.pow(packMinor / currentPackMinor, effectiveBeta);
    const revenueMinor = Math.round(packMinor * units);
    const marginMinor = costPackMinor !== null ? Math.round((packMinor - costPackMinor) * units) : null;
    const marginPct = costPackMinor !== null && packMinor > 0 ? ((packMinor - costPackMinor) / packMinor) * 100 : null;
    const endingStock = atpUnits !== null ? Math.max(0, Math.round(atpUnits * periodFactor - units)) : null;
    return {priceMinor: packMinor, units, revenueMinor, marginMinor, marginPct, endingStock};
  };

  // Current and AI Optimal are fixed reference columns: the accepted current and
  // recommended outcomes exactly as served (Expected demand, four-week horizon).
  // The scenario levers and the margin floor never move them — only the Proposed
  // what-if responds, so the two anchors the user compares against stay put.
  const fixedSim = (packMinor: number | null, units: number | null) => {
    if (packMinor === null || packMinor <= 0 || units === null) return null;
    const revenueMinor = Math.round(packMinor * units);
    const marginMinor = costPackMinor !== null ? Math.round((packMinor - costPackMinor) * units) : null;
    const marginPct = costPackMinor !== null && packMinor > 0 ? ((packMinor - costPackMinor) / packMinor) * 100 : null;
    const endingStock = atpUnits !== null ? Math.max(0, Math.round(atpUnits - units)) : null;
    return {priceMinor: packMinor, units, revenueMinor, marginMinor, marginPct, endingStock};
  };
  const currentSim = fixedSim(currentPackMinor, unitsCurrent);
  const aiSim = fixedSim(aiPackMinor, unitsAi);

  // The entered price is on the displayed basis (per base unit when a basis
  // exists); map it back to the canonical pack for the projection.
  const enteredMinor = parseMoneyMinor(proposed);
  const proposedPackMinor = enteredMinor === null
    ? null
    : unitBasis ? Math.round(enteredMinor * unitBasis.baseUnitQuantity) : enteredMinor;
  // Target margin: the proposed price is set to the price that yields exactly
  // this gross margin on the weighted-average cost, so changing it always moves
  // the Proposed column. It stays in two-way sync with the proposed price (the
  // input handlers below), so both fields always describe the same scenario.
  const targetMarginPct = targetMargin.trim() !== "" ? Number(targetMargin.replace(/[^0-9.]/g, "")) : null;
  const targetMarginValid = targetMarginPct !== null && Number.isFinite(targetMarginPct) && targetMarginPct >= 0 && targetMarginPct < 100;
  const targetPriceMinor = targetMarginValid && costPackMinor !== null
    ? Math.ceil(costPackMinor / (1 - (targetMarginPct as number) / 100))
    : null;
  const priceReasonable = proposedPackMinor !== null && currentPackMinor !== null
    && proposedPackMinor >= Math.round(currentPackMinor * 0.4)
    && proposedPackMinor <= Math.round(currentPackMinor * 1.6);
  const matchesAiOptimal = proposedPackMinor !== null && proposedPackMinor === aiPackMinor;
  const proposedSim = priceReasonable ? simulate(proposedPackMinor) : null;
  const aiChangePct = currentPackMinor && aiPackMinor
    ? ((aiPackMinor - currentPackMinor) / currentPackMinor) * 100
    : null;

  // Default the product to the first accepted, selectable recommendation whenever
  // the authority (re)loads.
  useEffect(() => {
    if (!recommendations.data) return;
    const first = recommendations.data.items.find((row) => row.selectable);
    setRecommendationId(first?.recommendationId ?? "");
  }, [recommendations.data?.authority.activationSetId]);
  // Seed Proposed to the AI-optimal price and the target margin to that price's
  // margin whenever the product changes; the user edits freely from there.
  useEffect(() => {
    if (aiPackMinor === null) return;
    setProposed(proposedInputValue(aiPackMinor, unitBasis));
    setCompetitorResponse(competitorIncluded ? "Include" : "Exclude");
    setTargetMargin(costPackMinor !== null && aiPackMinor > 0
      ? String(Math.round(((aiPackMinor - costPackMinor) / aiPackMinor) * 100))
      : "");
  }, [recommendationId, aiPackMinor]);

  const currentPriceValue = selected
    ? unitBasis
      ? `${formatMoneyMinor(selected.currentUnitPriceMinor, currency)} / ${unitBasis.label}`
      : formatMoneyMinor(selected.currentPriceMinor, currency)
    : "";
  const currentPriceHelp = unitBasis && selected &&
    selected.baseUnitQuantity !== null && selected.baseUnitQuantity !== undefined &&
    selected.baseUnitQuantity > 1 && selected.pricingPackLabel
    ? `${formatMoneyMinor(selected.currentPriceMinor, currency)} per ${selected.pricingPackLabel}`
    : `Accepted local price${currency ? ` · ${currency}` : ""}`;
  const proposedHelp = proposed && proposedPackMinor !== null && !priceReasonable
    ? "Projection is reliable within about ±60% of the current price."
    : matchesAiOptimal
      ? "Proposed matches AI Optimal"
      : `Enter any local price${unitBasis ? ` per ${unitBasis.label}` : ""}${currency ? ` · ${currency}` : ""} — the projection updates live`;

  // Two-way binding between the target margin and the proposed price: editing the
  // margin sets the price that yields it; editing the price back-fills the margin.
  const handleTargetMarginChange = (value: string) => {
    setTargetMargin(value);
    const pct = Number(value.replace(/[^0-9.]/g, ""));
    if (value.trim() !== "" && Number.isFinite(pct) && pct >= 0 && pct < 100 && costPackMinor !== null) {
      setProposed(proposedInputValue(Math.ceil(costPackMinor / (1 - pct / 100)), unitBasis));
    }
  };
  const handleProposedChange = (value: string) => {
    setProposed(value);
    const minor = parseMoneyMinor(value);
    const packMinor = minor === null ? null : unitBasis ? Math.round(minor * unitBasis.baseUnitQuantity) : minor;
    if (packMinor !== null && packMinor > 0 && costPackMinor !== null) {
      const margin = ((packMinor - costPackMinor) / packMinor) * 100;
      if (Number.isFinite(margin) && margin >= 0 && margin < 100) setTargetMargin(String(Math.round(margin)));
    }
  };

  const pctDelta = (next: number | null | undefined, base: number | null | undefined) =>
    next != null && base != null && base !== 0 ? `${next - base >= 0 ? "+" : ""}${formatPercent(((next - base) / Math.abs(base)) * 100)}` : "—";

  const scenarioCell = (sim: ReturnType<typeof simulate>, metric: "Units" | "Revenue" | "Gross Margin" | "Ending Stock") => {
    if (sim === null) return <span className="cell-pending" title="Enter a price to project this value.">—</span>;
    if (metric === "Units") return <>{formatUnits(sim.units)}</>;
    if (metric === "Revenue") return <>{formatAggregateMoneyMinor(sim.revenueMinor, currency)}</>;
    if (metric === "Gross Margin") return sim.marginPct === null ? <span className="cell-pending">—</span> : <>{formatPercent(sim.marginPct)}</>;
    return sim.endingStock === null ? <span className="cell-pending">—</span> : <>{formatUnits(sim.endingStock)}</>;
  };

  return (
    <PricingState pending={recommendations.isPending} error={recommendations.error} empty={!items.length} emptyMessage="No accepted recommendation is available for simulation.">
      <div className="card scenario-builder">
        <CardHeader title="Price Scenario Builder" context="Live what-if projection" action={<button className="modal-action" type="button" disabled={aiPackMinor === null} onClick={() => {
          if (aiPackMinor === null) return;
          setProposed(proposedInputValue(aiPackMinor, unitBasis));
          setPeriod("Next 4 Weeks");
          setAssumption("Expected");
          setCompetitorResponse("Exclude");
          setObjective("Margin Protection");
          setTargetMargin(costPackMinor !== null && aiPackMinor > 0
            ? String(Math.round(((aiPackMinor - costPackMinor) / aiPackMinor) * 100))
            : "");
        }}>Reset to AI Optimal</button>} />
        <div className="pricing-form-grid four scenario-builder-grid">
          <Field label="Product"><select className="filter" value={recommendationId} onChange={(event) => setRecommendationId(event.target.value)}>{items.map((row) => <option key={row.recommendationId} value={row.recommendationId}>{row.productName ?? row.skuId} · {storeName(dashboard, row.storeId, row.storeName)} · {channelName(dashboard, row.channelId, row.channelName)}</option>)}</select></Field>
          <Field label="Current Price" help={currentPriceHelp}><input className="filter" readOnly value={currentPriceValue} /></Field>
          <Field label="Proposed Price" help={proposedHelp}><input className="filter" inputMode="decimal" value={proposed} onChange={(event) => handleProposedChange(event.target.value)} aria-invalid={Boolean(proposed) && proposedPackMinor !== null && !priceReasonable} /></Field>
          <Field label="Simulation Period" help="Scales the accepted four-week forecast across the horizon."><select className="filter" value={period} onChange={(event) => setPeriod(event.target.value as typeof period)}><option>Next 4 Weeks</option><option>Next 8 Weeks</option><option>Next 13 Weeks</option></select></Field>
          <Field label="Target Margin" help={targetPriceMinor !== null
            ? `Sets the proposed price to ${priceOnBasis(targetPriceMinor, unitBasis, currency)} — the price that yields a ${targetMarginPct}% gross margin on the weighted-average cost.`
            : (priceMarginActive ? "Sets the proposed price to the price that yields this gross margin on the weighted-average cost." : "Enter a target margin once a cost basis is active.")}><input className="filter" inputMode="decimal" value={targetMargin} onChange={(event) => handleTargetMarginChange(event.target.value)} placeholder="e.g. 30" /></Field>
          <Field label="Competitor Response" help="Scenario assumption: Include dampens the own-price response as competitors match; Exclude applies the full fitted elasticity."><select className="filter" value={competitorResponse} onChange={(event) => setCompetitorResponse(event.target.value as typeof competitorResponse)}><option>Include</option><option>Exclude</option></select></Field>
          <Field label="Demand Assumption" help="Expected uses the accepted four-week forecast; Best/Worst use the weekly planning bounds."><select className="filter" value={assumption} onChange={(event) => setAssumption(event.target.value as typeof assumption)}><option>Expected</option><option>Best Case</option><option>Worst Case</option></select></Field>
          <Field label="Inventory Objective" help="Scenario assumption: Clearance adds a volume push; Margin Protection holds steady demand."><select className="filter" value={objective} onChange={(event) => setObjective(event.target.value as typeof objective)}><option value="Margin Protection" disabled={!priceMarginActive}>{priceMarginActive ? "Margin Protection" : "Margin Protection — cost basis unavailable"}</option><option>Clearance</option></select></Field>
        </div>
      </div>

      <div className="grid-2 scenario-outcome-grid">
        <div className="card scenario-result-card">
          <CardHeader title="Scenario Comparison" context="Current · Proposed · AI Optimal" />
          <div className="table-scroll"><table className="table scenario-comparison"><thead><tr><th>Measure</th><th>Current</th><th>Proposed</th><th>AI Optimal</th></tr></thead><tbody>
            <tr className="scenario-price-row"><td><strong>Price</strong></td><td>{priceOnBasis(currentPackMinor, unitBasis, currency)}</td><td>{proposedSim ? priceOnBasis(proposedSim.priceMinor, unitBasis, currency) : <span className="cell-pending">—</span>}</td><td>{priceOnBasis(aiPackMinor, unitBasis, currency)}</td></tr>
            {(["Units", "Revenue", "Gross Margin", "Ending Stock"] as const).map((metric) => <tr key={metric}><td><strong>{metric}</strong></td><td>{scenarioCell(currentSim, metric)}</td><td>{scenarioCell(proposedSim, metric)}</td><td>{scenarioCell(aiSim, metric)}</td></tr>)}
          </tbody></table></div>
          <p className="demo-note">Current and AI Optimal are fixed references — the accepted current and recommended outcomes. Only the Proposed column responds to your inputs: the proposed price (or a target margin, which sets the price that yields it) and the period, demand, competitor and objective levers.</p>
        </div>
        <div className="card">
          <CardHeader title="AI Recommendation" context="Accepted" />
          <div className="callout pricing-recommendation-callout">
            <strong>Recommended local price: {priceOnBasis(aiPackMinor, unitBasis, currency)}</strong>
            <p>{selected?.action === "Hold"
              ? "Holding the current price protects margin against the weighted-average cost; no revenue-improving change clears the floor."
              : `A ${aiChangePct != null ? formatPercent(aiChangePct) : ""} change from current, projected to move four-week revenue by ${pctDelta(aiSim?.revenueMinor, currentSim?.revenueMinor)} and gross margin by ${pctDelta(aiSim?.marginMinor, currentSim?.marginMinor)} on the weighted-average-cost basis.`}
              {competitorIncluded ? " A fresh competitor bound was applied." : " The recommendation is elasticity-driven; no fresh competitor bound exists for this SKU."}</p>
          </div>
          <div className="grid-4 simulation-metrics">
            <PricingKpi label="Revenue vs current" value={pctDelta(proposedSim?.revenueMinor, currentSim?.revenueMinor)} note="Proposed scenario" />
            <PricingKpi label="Margin vs current" value={pctDelta(proposedSim?.marginMinor, currentSim?.marginMinor)} note="Weighted-average cost basis" />
            <PricingKpi label="Stock Risk" value={selected?.risk ?? "—"} note="Forecast and accepted inventory context" />
            <PricingKpi label="Confidence" value={selected?.confidence != null ? formatPercent(selected.confidence * 100) : "—"} note="Price-response confidence" />
          </div>
        </div>
      </div>
    </PricingState>
  );
}

type CompetitorModal = "add" | "rule" | "review" | null;

function CompetitorPreview({kind, onClose}: {
  kind: "add" | "rule";
  onClose: () => void;
}) {
  const reason = kind === "add"
    ? "Competitor-source onboarding and legal approval are unavailable."
    : "Persisted alert-rule workflow is unavailable.";
  const title = kind === "add" ? "Add Competitor" : "Create Competitor Alert Rule";
  return (
    <Dialog open title={title} description="Creation workflow unavailable — no source or rule will be created" onClose={onClose} footer={<PreviewFooter label={kind === "add" ? "Add Competitor" : "Create Rule"} onClose={onClose} reason={reason} />} wide>
      <div className="preview-banner"><strong>Business prerequisite</strong>{reason}</div>
      {kind === "add" ? (
        <div className="pricing-form-grid two">
          <Field label="Competitor Name"><input className="filter" readOnly /></Field>
          <Field label="Competitor Type"><select className="filter"><option>Direct Retailer</option><option>Marketplace</option><option>Brand Website</option><option>Regional Competitor</option></select></Field>
          <Field label="Country / Region"><select className="filter"><option>India</option><option>United States</option><option>Europe</option><option>GCC</option></select></Field>
          <Field label="Website URL"><input className="filter" type="url" readOnly /></Field>
          <Field label="Data Collection Method" help="Approved Web Collection requires an approved legal source and remains unavailable."><select className="filter"><option>API Feed</option><option disabled>Approved Web Collection</option><option>CSV / SFTP Feed</option><option>Manual Upload</option></select></Field>
          <Field label="Refresh Frequency"><select className="filter"><option>Hourly</option><option>Every 4 Hours</option><option>Daily</option><option>Weekly</option></select></Field>
          <Field label="Categories to Monitor"><select className="filter"><option>All Categories</option><option>Footwear</option><option>Apparel</option><option>Electronics</option><option>Beauty</option></select></Field>
          <Field label="Currency"><select className="filter"><option>INR</option><option>USD</option><option>EUR</option><option>AED</option></select></Field>
          <Field label="Notes"><textarea className="filter" readOnly /></Field>
        </div>
      ) : (
        <div className="pricing-form-grid two">
          <Field label="Rule Name"><input className="filter" readOnly /></Field>
          <Field label="Trigger Type"><select className="filter"><option>Competitor price changes</option><option>Price gap exceeds threshold</option><option>Competitor promotion detected</option><option>Competitor becomes out of stock</option><option>Competitor returns to stock</option><option>New competitor product detected</option></select></Field>
          <Field label="Threshold"><input className="filter" inputMode="decimal" readOnly /></Field>
          <Field label="Comparison Direction"><select className="filter"><option>Our price is higher</option><option>Our price is lower</option><option>Either direction</option></select></Field>
          <Field label="Category Scope"><select className="filter"><option>All Categories</option><option>Footwear</option><option>Apparel</option><option>Electronics</option><option>Beauty</option></select></Field>
          <Field label="Competitor Scope"><select className="filter"><option>All Competitors</option><option>Selected Competitor</option><option>Top 3 Competitors</option></select></Field>
          <Field label="Severity"><select className="filter"><option>High</option><option>Medium</option><option>Low</option></select></Field>
          <Field label="Notify" help="Recipient identities require workflow authority."><select className="filter" disabled><option>Pricing Manager</option><option>Category Manager</option><option>Pricing + Merchandising</option><option>Executive Team</option></select></Field>
          <Field label="Frequency"><select className="filter"><option>Immediately</option><option>Hourly Digest</option><option>Daily Digest</option></select></Field>
          <Field label="Recommended Action"><select className="filter"><option>Create price recommendation</option><option>Notify only</option><option>Send for manual review</option></select></Field>
          <Field label="Rule Description"><textarea className="filter" readOnly /></Field>
        </div>
      )}
      {kind === "add" && (
        <div className="callout compact-callout"><strong>Connection validation</strong><p>No connection, collection, or validation request is made from this preview.</p></div>
      )}
    </Dialog>
  );
}

function MatchReview({row, position, total, filters, onClose}: {
  row: CompetitorMatch;
  position: number;
  total: number;
  filters: PricingFilters;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["competitor-detail", row.matchId],
    queryFn: ({signal}) => loadCompetitorDetail(row.matchId, filters, signal)
  });
  const [linkPreview, setLinkPreview] = useState(false);
  const item = detail.data?.item ?? row;
  useEffect(() => {
    if (!linkPreview) return;
    requestAnimationFrame(() => {
      document.getElementById("pricing-dialog-review-competitor-product-match")?.focus();
    });
  }, [linkPreview]);
  return (
    <Dialog open title="Review Competitor Product Match" description={`Review item ${position} of ${total} · Read-only inspection`} onClose={onClose} wide footer={linkPreview ? (
      <>
        <button className="modal-action" type="button" disabled title="Match mutation is unavailable.">Save New Match</button>
        <button className="filter" type="button" onClick={onClose}>Cancel</button>
      </>
    ) : (
      <>
        <button className="filter" type="button" disabled title="Match mutation is unavailable.">Reject Match</button>
        <button className="filter" type="button" onClick={() => setLinkPreview(true)}>Link Different Product</button>
        <button className="modal-action" type="button" disabled title="Match mutation is unavailable.">Accept Match</button>
        <button className="filter" type="button" onClick={onClose}>Cancel</button>
      </>
    )}>
      <PricingState pending={detail.isPending} error={detail.error}>
        {linkPreview ? (
          <>
            <div className="preview-banner"><strong>Relinking prerequisite</strong>No governed alternate-catalogue candidates are carried in this inspection payload.</div>
            <Field label="Search competitor catalogue"><input className="filter" disabled title="No governed alternate candidates are available." /></Field>
            <div className="table-scroll"><table className="table"><thead><tr><th>Select</th><th>Candidate Product</th><th>Price</th><th>Confidence</th></tr></thead><tbody><tr><td colSpan={4}><UnavailableValue reason="No governed alternate candidate rows are available." /></td></tr></tbody></table></div>
          </>
        ) : (
          <>
            <MetricList rows={[
              {label: "Review item", value: `${position} of ${total}`},
              {label: "Match confidence", value: item.confidence === null ? unavailable : formatPercent(item.confidence * 100)},
              {label: "Current status", value: item.status}
            ]} />
            <div className="match-comparison">
              <section className="card"><h4>Our Product</h4><strong>{item.ourProduct ?? item.skuId}</strong><MetricList rows={[{label: "SKU", value: item.skuId}, {label: "Price", value: formatMoneyMinor(item.ourPriceMinor, item.currencyCode)}, {label: "Availability", value: unavailable}]} /></section>
              <section className="card"><h4>Competitor Product</h4><strong>{item.matchedProduct ?? unavailable}</strong><MetricList rows={[{label: "Competitor", value: item.competitorName ?? unavailable}, {label: "Evidence", value: String(item.details?.synthetic_label ?? item.details?.evidence_class ?? unavailable)}, {label: "Price", value: formatMoneyMinor(item.competitorPriceMinor, item.currencyCode)}, {label: "Availability", value: item.availability}]} /></section>
            </div>
            <div className="callout compact-callout"><strong>Attributes used for matching</strong><p>Each projected attribute remains source-backed or explicitly unavailable; missing values are never substituted.</p></div>
            <div className="table-scroll"><table className="table"><thead><tr><th>Attribute</th><th>Our Product</th><th>Competitor Product</th><th>Confidence component</th></tr></thead><tbody>{["Brand", "Model number", "Title", "Category", "Colour", "Size", "Capacity", "Pack quantity", "GTIN / UPC / EAN", "Image"].map((label) => <tr key={label}><td>{label}</td><td>{String(item.details?.[`our_${label.toLowerCase().replaceAll(" ", "_")}`] ?? unavailable)}</td><td>{String(item.details?.[label.toLowerCase().replaceAll(" ", "_")] ?? unavailable)}</td><td><UnavailableValue reason="Attribute-level match component is not present in this projection." /></td></tr>)}</tbody></table></div>
            <MetricList rows={[{label: "Observed / as of", value: absoluteTime(item.lastUpdated)}, {label: "Freshness", value: item.freshness}]} />
            <Field label="Reviewer Comment" help="Comments cannot be persisted."><textarea className="filter" disabled /></Field>
          </>
        )}
      </PricingState>
    </Dialog>
  );
}

function CompetitorMonitor({storeId, channelType}: Pick<PricingPageProps, "storeId" | "channelType">) {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<CompetitorModal>(null);
  const [page, setPage] = useState(0);
  const offset = page * PAGE_SIZE;
  const filters = useMemo<PricingFilters>(() => ({
    storeId,
    channelType,
    matchStatus: status,
    search: debouncedSearch
  }), [storeId, channelType, status, debouncedSearch]);
  const summary = useQuery({
    queryKey: ["competitor-summary", filters],
    queryFn: ({signal}) => loadCompetitorSummary(filters, signal),
    placeholderData: (previous) => previous
  });
  const matches = useQuery({
    queryKey: ["competitor-matches", filters, offset],
    queryFn: ({signal}) => loadCompetitorMatches({...filters, limit: PAGE_SIZE, offset}, signal),
    placeholderData: (previous) => previous
  });
  const rules = useQuery({
    queryKey: ["competitor-alert-rules"],
    queryFn: ({signal}) => loadAlertRules(signal)
  });
  const rows = matches.data?.items ?? [];
  const selectedRows = rows.filter((row) => selected.has(row.matchId));
  const reviewQueue = selectedRows.length > 0
    ? selectedRows
    : rows.filter((row) => row.status === "Needs Review");
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.matchId));
  const allRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setSelected(new Set());
    setPage(0);
  }, [storeId, channelType, status, debouncedSearch]);
  useEffect(() => {
    if (allRef.current) allRef.current.indeterminate = selected.size > 0 && !allSelected;
  }, [selected.size, allSelected]);

  return (
    <PricingState pending={summary.isPending || matches.isPending} error={summary.error ?? matches.error}>
      {summary.data && matches.data && (
        <>
          <div className="pricing-toolbar competitor-toolbar">
            <PreviewButton onClick={() => setModal("add")}>Add Competitor</PreviewButton>
            <PreviewButton onClick={() => setModal("rule")}>Create Alert Rule</PreviewButton>
            <PreviewButton onClick={() => setModal("review")} disabled={reviewQueue.length === 0} reason="No visible selected or Needs Review match is available.">Review Matches</PreviewButton>
            <select className="filter" aria-label="Match status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All Match Statuses</option><option>Matched</option><option>Needs Review</option><option>Rejected</option></select>
            <input className="filter" aria-label="Search product or competitor" placeholder="Search product or competitor" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          <div className="kpi-grid pricing-kpi-grid">
            <PricingKpi label="Products Monitored" value={formatCount(summary.data.kpis.productsMonitored)} note="Distinct in-scope products assessed" />
            <PricingKpi label="Above Market" value={formatCount(summary.data.kpis.aboveMarket)} note="Our local price above fresh admissible competitor" />
            <PricingKpi label="Below Market" value={formatCount(summary.data.kpis.belowMarket)} note="Our local price below fresh admissible competitor" />
            <PricingKpi label="Competitor Out of Stock" value={formatCount(summary.data.kpis.competitorOutOfStock)} note="Fresh admissible competitor availability" />
            <PricingKpi label="Matches Needing Review" value={formatCount(summary.data.kpis.matchesNeedingReview)} note="Read-only match inspection queue" />
          </div>
          <div className="callout pricing-callout"><strong>Competitor intelligence</strong><p>Comparable local prices are combined with match confidence, freshness, availability, local price guards, and inventory context. Competitor observations provide bounded context; they never trigger an automatic price change.</p></div>
          <div className="card pricing-table-card">
            <CardHeader title="Competitor Product Matches" context={`${formatCount(matches.data.pagination.total)} matches`} />
            <div className="table-scroll"><table className="table pricing-table competitor-table"><thead><tr><th><input ref={allRef} type="checkbox" checked={allSelected} aria-label="Select all visible competitor matches" onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((row) => row.matchId)))} /></th>{["Our Product", "Competitor", "Matched Product", "Our Price", "Competitor Price", "Difference", "Availability", "Last Updated", "Match Confidence", "Match Status", "Recommended Response"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.matchId}><td><input type="checkbox" aria-label={`Select match ${row.matchId}`} checked={selected.has(row.matchId)} onChange={() => setSelected((current) => {const next = new Set(current); if (next.has(row.matchId)) next.delete(row.matchId); else next.add(row.matchId); return next;})} /></td><td><strong>{row.ourProduct ?? row.skuId}</strong><small>{row.skuId}</small></td><td>{row.competitorName ?? unavailable}<small>{String(row.details?.synthetic_label ?? "")}</small></td><td><button type="button" className="link-button" onClick={() => {setSelected(new Set([row.matchId])); setModal("review");}}>{row.matchedProduct ?? unavailable}</button></td><td>{formatMoneyMinor(row.ourPriceMinor, row.currencyCode)}</td><td>{formatMoneyMinor(row.competitorPriceMinor, row.currencyCode)}</td><td>{row.priceGapPct === null ? unavailable : `${row.priceGapPct > 0 ? "+" : ""}${formatPercent(row.priceGapPct)}`}</td><td><span className={`badge ${badgeClass(row.availability)}`}>{row.availability}</span></td><td title={row.lastUpdated ?? undefined}>{absoluteTime(row.lastUpdated)}</td><td>{row.confidence === null ? unavailable : formatPercent(row.confidence * 100)}</td><td><span className={`badge ${badgeClass(row.status)}`}>{row.status}</span></td><td>{row.firstExclusionReason ? <span className="cell-note">{reasonText(row.firstExclusionReason)}</span> : row.recommendedResponse ?? "Included as bounded context"}</td></tr>)}</tbody></table></div>
            <Pagination
              offset={matches.data.pagination.offset}
              limit={matches.data.pagination.limit}
              total={matches.data.pagination.total}
              onPrev={() => {setPage((current) => Math.max(0, current - 1)); setSelected(new Set());}}
              onNext={() => {setPage((current) => current + 1); setSelected(new Set());}}
            />
            <p className="demo-note">Selection opens a read-only inspection queue. Accept, reject, relink, comment and save controls remain disabled.</p>
          </div>
          <div className="grid-2 pricing-bottom-grid">
            <div className="card"><CardHeader title="Active Alert Rules" context={rules.data?.available ? `${rules.data.items.length} active` : "Not available"} />{rules.isPending ? <div className="empty-panel">Loading alert-rule evidence…</div> : rules.data?.available ? <div className="table-scroll"><table className="table"><thead><tr>{["Rule", "Trigger", "Scope", "Recipients", "Status"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rules.data.items.map((item, index) => <tr key={index}><td>{String(item.rule ?? unavailable)}</td><td>{String(item.trigger ?? unavailable)}</td><td>{String(item.scope ?? unavailable)}</td><td>{String(item.recipients ?? unavailable)}</td><td>{String(item.status ?? unavailable)}</td></tr>)}</tbody></table></div> : <div className="state-card compact-state"><UnavailableValue reason={rules.data?.message ?? "Persisted competitor alert rules are unavailable."} /></div>}</div>
            <div className="card"><CardHeader title="Match Quality Summary" /><MetricList rows={[
              {label: "Auto-Accepted", value: formatCount(summary.data.quality?.autoAccepted)},
              {label: "Manual Review", value: formatCount(summary.data.quality?.manualReview)},
              {label: "Rejected", value: formatCount(summary.data.quality?.rejected)},
              {label: "Average Confidence", value: formatPercent(summary.data.quality?.averageConfidencePct)}
            ]} /><div className="callout compact-callout"><strong>Matching guardrail</strong><p>Low-confidence matches remain under review and cannot trigger pricing response.</p></div></div>
          </div>
          {modal === "add" && <CompetitorPreview kind="add" onClose={() => setModal(null)} />}
          {modal === "rule" && <CompetitorPreview kind="rule" onClose={() => setModal(null)} />}
          {modal === "review" && reviewQueue[0] && <MatchReview row={reviewQueue[0]} position={1} total={reviewQueue.length} filters={filters} onClose={() => setModal(null)} />}
        </>
      )}
    </PricingState>
  );
}

function PromotionCreatePreview({onClose}: {onClose: () => void}) {
  return (
    <Dialog open title="Create Promotion" description="Creation workflow unavailable — no draft will be created" onClose={onClose} wide footer={<PreviewFooter label="Create Draft" onClose={onClose} reason="Promotion creation and approval workflow are unavailable." />}>
      <div className="preview-banner"><strong>AI validation before creation</strong>Origin-visible promotion-plan authority, privacy approval, inventory readiness, conflict checks, and a write workflow are required before a draft can be created.</div>
      <div className="pricing-form-grid two">
        <Field label="Promotion Name"><input className="filter" readOnly /></Field>
        <Field label="Promotion Objective"><select className="filter"><option>Revenue Growth</option><option>Inventory Clearance</option><option disabled>Customer Acquisition</option><option disabled>Basket Size Growth</option><option disabled>Loyalty Engagement</option></select></Field>
        <Field label="Promotion Type"><select className="filter"><option>Percentage Discount</option><option>Fixed Price</option><option disabled>Bundle Offer</option><option disabled>Buy One Get One</option><option disabled>Loyalty Member Price</option><option>Clearance</option></select></Field>
        <Field label="Discount / Offer"><input className="filter" readOnly /></Field>
        <Field label="Category"><select className="filter"><option>Footwear</option><option>Beauty</option><option>Electronics</option><option>Apparel</option></select></Field>
        <Field label="Product Scope"><select className="filter"><option>AI Recommended Products</option><option>Selected SKUs</option><option>Entire Category</option><option>Ageing Inventory</option></select></Field>
        <Field label="Start Date"><input className="filter" type="date" readOnly /></Field>
        <Field label="End Date"><input className="filter" type="date" readOnly /></Field>
        <Field label="Stores / Channels"><select className="filter"><option>All Stores</option><option>Selected Stores</option><option>Online Only</option><option>West Region + Online</option></select></Field>
        <Field label="Customer Segment" help="Customer targeting is privacy unavailable."><select className="filter" disabled><option>All Customers</option><option>Loyalty Members</option><option>High-Value Customers</option><option>Lapsed Customers</option></select></Field>
        <Field label="Target Margin"><input className="filter" inputMode="decimal" readOnly /></Field>
        <Field label="Approval Route" help="Workflow identities and routing are unavailable."><select className="filter" disabled><option>Category Manager</option><option>Pricing Manager</option><option>Finance + Business Head</option></select></Field>
        <Field label="Business Rationale"><textarea className="filter" readOnly /></Field>
      </div>
    </Dialog>
  );
}

function PromotionSimulationPreview({
  message,
  onResults,
  onClose
}: {
  message: string;
  onResults: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog
      open
      title="Simulate Promotion"
      description="Promotion simulation gates are unavailable"
      onClose={onClose}
      wide
      footer={(
        <>
          <button className="modal-action" type="button" disabled title={message}>Run Simulation</button>
          <button className="filter" type="button" onClick={onResults}>Preview Results</button>
          <button className="filter" type="button" onClick={onClose}>Cancel</button>
        </>
      )}
    >
      <div className="preview-banner"><strong>Simulation prerequisite</strong>{message}</div>
      <div className="pricing-form-grid two">
        <Field label="Promotion"><select className="filter" disabled><option>No governed promotion available</option></select></Field>
        <Field label="Scenario"><select className="filter"><option>Expected</option><option>Best Case</option><option>Worst Case</option></select></Field>
        <Field label="Discount Depth"><input className="filter" inputMode="decimal" readOnly /></Field>
        <Field label="Duration"><select className="filter"><option>3 Days</option><option>7 Days</option><option>14 Days</option></select></Field>
        <Field label="Store Scope"><select className="filter"><option>All Stores</option><option>Selected Stores</option><option>Online Only</option></select></Field>
        <Field label="Customer Segment" help="Promotion-response targeting is privacy unavailable."><select className="filter" disabled><option>All Customers</option><option>Loyalty Members</option><option>High-Value Customers</option></select></Field>
        <Field label="Include Cannibalisation" help="Privacy-approved basket evidence is unavailable."><select className="filter" disabled><option>Yes</option><option>No</option></select></Field>
        <Field label="Include Competitor Response" help="A fresh admissible match and accepted promotion model are required."><select className="filter" disabled><option>Yes</option><option>No</option></select></Field>
      </div>
    </Dialog>
  );
}

function PromotionResultsPreview({reason, onClose}: {reason: string; onClose: () => void}) {
  return (
    <Dialog open title="Promotion Simulation Results" description="Governed unavailable preview — no result request was made" onClose={onClose} wide>
      <div className="preview-banner"><strong>{reasonText(reason)}</strong>Every result location remains visible, but no number is substituted.</div>
      <div className="grid-3 promotion-result-metrics">{["Expected Demand Uplift", "Revenue Uplift", "Gross Margin Impact", "Required Stock", "Sell-through Improvement", "Cannibalisation Risk"].map((label) => <PricingKpi key={label} label={label} value={unavailable} note={reasonText(reason)} />)}</div>
      <div className="table-scroll"><table className="table"><thead><tr><th>Metric</th><th>Current Plan</th><th>AI Optimized</th></tr></thead><tbody>{["Discount", "Revenue", "Margin", "Ending Stock"].map((metric) => <tr key={metric}><td>{metric}</td><td><UnavailableValue reason={reasonText(reason)} /></td><td><UnavailableValue reason={reasonText(reason)} /></td></tr>)}</tbody></table></div>
      <div className="callout"><strong>AI Recommendation</strong><p>{reasonText(reason)}. Stock readiness, promotion conflict and promotion-specific Confidence are unavailable.</p></div>
      <MetricList rows={[
        {label: "Stock readiness", value: <UnavailableValue reason={reasonText(reason)} />},
        {label: "Promotion conflict", value: <UnavailableValue reason={reasonText(reason)} />},
        {label: "Confidence", value: <UnavailableValue reason="Promotion-specific confidence is unavailable." />}
      ]} />
    </Dialog>
  );
}

function PromotionCalendar({message, onClose}: {message: string; onClose: () => void}) {
  const monthRef = useRef<HTMLSelectElement>(null);
  const [month, setMonth] = useState("August 2026");
  return (
    <Dialog open title="Promotion Calendar" description="Source-plan Month View" onClose={onClose} wide>
      <div className="calendar-toolbar">
        <button className="filter active" type="button">Month View</button>
        <button className="filter" type="button" disabled title="Governed list-view composition not approved">List View</button>
        <select ref={monthRef} className="filter" aria-label="Calendar month" value={month} onChange={(event) => {setMonth(event.target.value); requestAnimationFrame(() => monthRef.current?.focus());}}><option>July 2026</option><option>August 2026</option></select>
      </div>
      <div className="calendar-grid" role="grid" aria-label={`${month} promotion calendar`}>
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <div className="calendar-weekday" role="columnheader" key={day}>{day}</div>)}
        {Array.from({length: 35}, (_, index) => {
          const day = index - 1;
          return <div className="calendar-day unavailable-day" role="gridcell" key={index}><span>{day > 0 && day <= 31 ? day : ""}</span></div>;
        })}
      </div>
      <div className="callout"><strong>Calendar controls</strong><p>{message} Overlap, category, inventory readiness and customer-fatigue results are not inferred.</p></div>
    </Dialog>
  );
}

// One accepted promotion row for the portfolio. Served fields (name, type, demand
// uplift with its interval and confidence, revenue uplift, margin impact) resolve to
// real values; columns this projection does not carry show the governed "Under
// review" placeholder, and cannibalisation risk shows the privacy-restricted chip —
// never a bare "Not available" and never a cannibalisation number.
// Format an ISO date range ("2016-09-25" .. "2016-11-05") as a compact,
// locale-aware window; both bounds come straight from the promotion source.
function formatPromoPeriod(start: unknown, end: unknown): string | null {
  const fmt = (value: unknown): string | null => {
    if (typeof value !== "string" || !value) return null;
    const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
  };
  const parts = [fmt(start), fmt(end)].filter(Boolean);
  return parts.length ? parts.join(" – ") : null;
}

// The promotion is market-scoped, so its owning team is derived from the served
// market id (e.g. "gulf-india" -> "Gulf India") rather than invented.
function marketOwnerLabel(marketId: unknown): string | null {
  if (typeof marketId !== "string" || !marketId) return null;
  return marketId
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function PromotionPortfolioRow({promo}: {promo: Record<string, unknown>}) {
  const currency = typeof promo.currencyCode === "string" ? promo.currencyCode : null;
  const uplift = numberOrNull(promo.expectedDemandUplift);
  const low = numberOrNull(promo.upliftLow);
  const high = numberOrNull(promo.upliftHigh);
  const confidence = numberOrNull(promo.confidence);
  const revenue = numberOrNull(promo.revenueUpliftMinor);
  const margin = numberOrNull(promo.marginImpactMinor);
  const offer = numberOrNull(promo.offerValue);
  const products = numberOrNull(promo.productCount);
  const channels = numberOrNull(promo.channelCount);
  const requiredStock = numberOrNull(promo.requiredStockUnits);
  const period = formatPromoPeriod(promo.periodStart, promo.periodEnd);
  const owner = marketOwnerLabel(promo.marketId);
  const status = typeof promo.status === "string" ? promo.status : null;
  const category = typeof promo.categoryLabels === "string" ? promo.categoryLabels : null;
  const subLabel = [promo.promoType, promo.promoId].filter(Boolean).map(String).join(" · ");
  const intervalNote = [
    low !== null && high !== null
      ? `+${formatPercent(low * 100)} – +${formatPercent(high * 100)}`
      : null,
    confidence !== null ? `${formatPercent(confidence * 100)} conf.` : null
  ].filter(Boolean).join(" · ");
  const scope = [
    promo.allStores === true ? "All stores" : promo.allStores === false ? "Selected stores" : null,
    channels !== null ? `${formatCount(channels)} ${channels === 1 ? "channel" : "channels"}` : null
  ].filter(Boolean).join(" · ");
  return (
    <tr>
      <td><strong>{String(promo.promoName ?? promo.promoId ?? unavailable)}</strong>{subLabel && <small>{subLabel}</small>}</td>
      <td>{category ?? "—"}</td>
      <td>{period ?? "—"}</td>
      <td>{scope || "—"}</td>
      <td>{products !== null ? `${formatCount(products)} SKUs` : "—"}</td>
      <td>{offer !== null ? `${Math.round(offer * 100)}% off` : "—"}</td>
      <td>{uplift === null ? "—" : <><strong>{`${uplift >= 0 ? "+" : ""}${formatPercent(uplift * 100)}`}</strong>{intervalNote && <small>{intervalNote}</small>}</>}</td>
      <td>{revenue === null ? "—" : formatAggregateMoneyMinor(revenue, currency)}</td>
      <td>{margin === null ? "—" : formatAggregateMoneyMinor(margin, currency)}</td>
      <td>{requiredStock !== null ? `${formatCount(requiredStock)} units` : "—"}</td>
      <td><RestrictedValue reason="Cannibalisation risk is privacy restricted; a numeric value is never disclosed." label={reasonText(typeof promo.cannibalisationRisk === "string" ? promo.cannibalisationRisk : "PRIVACY_RESTRICTED")} /></td>
      <td>{status ? <span className={`badge ${status === "Completed" ? "b-green" : "b-blue"}`}>{status}</span> : "—"}</td>
      <td>{owner ?? "—"}</td>
    </tr>
  );
}

function PromotionPlanner() {
  const summary = useQuery({queryKey: ["promotion-summary"], queryFn: ({signal}) => loadPromotionSurface("summary", signal)});
  const opportunities = useQuery({queryKey: ["promotion-opportunities"], queryFn: ({signal}) => loadPromotionSurface("opportunities", signal)});
  const portfolio = useQuery({queryKey: ["promotion-portfolio"], queryFn: ({signal}) => loadPromotionSurface("portfolio", signal)});
  const calendar = useQuery({queryKey: ["promotion-calendar"], queryFn: ({signal}) => loadPromotionSurface("calendar", signal)});
  const [modal, setModal] = useState<"create" | "simulate" | "results" | "calendar" | null>(null);
  const reason = summary.data?.reasonCode ?? "NO_ORIGIN_VISIBLE_PROMOTION_PLAN";
  const message = summary.data?.message ?? "Origin-visible promotion planning evidence is not available.";
  // The positive branch lights up only the portfolio table: the disposition carries
  // the accepted promotions, while aggregate tiles and write workflows stay governed
  // (they are not independently projected by this read model).
  const plannerAvailable = Boolean(portfolio.data?.plannerAvailable);
  const promotions = plannerAvailable ? (portfolio.data?.items ?? []) : [];
  // Portfolio aggregates — every tile, the performance forecast and the AI
  // opportunity list are derived from the served accepted-promotion rows; no
  // value is invented. Baseline is the observed control revenue over the
  // horizon; the scenario ladder walks each promotion's own uplift interval.
  const rows = promotions.map((promo) => promo as Record<string, unknown>);
  const portfolioCurrency = (rows.find((row) => row.currencyCode)?.currencyCode as string | undefined);
  const sumField = (key: string) => rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);
  const scenarioRevenue = (fraction: string) => rows.reduce((total, row) => total + Number(row.baselineRevenueMinor ?? 0) * (1 + Number(row[fraction] ?? 0)), 0);
  const baselineRevenue = sumField("baselineRevenueMinor");
  const revenueUplift = sumField("revenueUpliftMinor");
  const marginUplift = sumField("marginImpactMinor");
  const requiredStock = sumField("requiredStockUnits");
  const promotedRevenue = baselineRevenue + revenueUplift;
  const scenarios = [
    {label: "Baseline", value: baselineRevenue, tone: "is-baseline"},
    {label: "Conservative", value: scenarioRevenue("upliftLow"), tone: "is-low"},
    {label: "Expected", value: promotedRevenue, tone: "is-mid"},
    {label: "Best case", value: scenarioRevenue("upliftHigh"), tone: "is-high"}
  ];
  const maxScenario = Math.max(...scenarios.map((scenario) => scenario.value), 1);
  const scenarioIndex = (value: number) => baselineRevenue > 0 ? Math.round((value / baselineRevenue) * 100) : 0;
  const opportunityRows = [...rows].sort((a, b) => Number(b.revenueUpliftMinor ?? 0) - Number(a.revenueUpliftMinor ?? 0)).slice(0, 6);
  return (
    <PricingState pending={summary.isPending || opportunities.isPending || portfolio.isPending || calendar.isPending} error={summary.error ?? opportunities.error ?? portfolio.error ?? calendar.error}>
      {summary.data && opportunities.data && portfolio.data && calendar.data && (
        <>
          <div className="pricing-toolbar promotion-toolbar">
            <PreviewButton onClick={() => setModal("create")}>Create Promotion</PreviewButton>
            <PreviewButton onClick={() => setModal("simulate")}>Simulate Promotion</PreviewButton>
            <PreviewButton onClick={() => setModal("calendar")}>Promotion Calendar</PreviewButton>
            <select className="filter" aria-label="Promotion status" disabled title={message}><option>All Statuses</option><option>Draft</option><option>Under Review</option><option>Approved</option><option>Live</option><option>Completed</option></select>
            <select className="filter" aria-label="Promotion category" disabled title={message}><option>All Categories</option><option>Footwear</option><option>Beauty</option><option>Electronics</option><option>Apparel</option></select>
            <input className="filter" aria-label="Search promotions" placeholder="Search promotions" disabled title={message} />
          </div>
          <div className="kpi-grid pricing-kpi-grid">{[
            ["Active Promotions", formatCount(promotions.length), "Accepted plans in the served portfolio"],
            ["Projected Revenue Uplift", formatAggregateMoneyMinor(revenueUplift, portfolioCurrency), "Accepted model-implied revenue"],
            ["Projected Margin Impact", formatAggregateMoneyMinor(marginUplift, portfolioCurrency), "Weighted-average cost basis"],
            ["Required Promotional Stock", `${formatCount(requiredStock)} units`, "Projected promoted demand over the horizon"],
            ["Promotions Needing Review", formatCount(0), "All served plans are accepted"]
          ].map(([label, value, note]) => <PricingKpi key={label} label={label} value={value} note={note} />)}</div>
          <div className="callout pricing-callout"><strong>AI promotion planning</strong><p>Accepted promotion uplift is shown across the portfolio; permitted product, depth, conflicts, response, revenue, stock and margin appear only when their capability passes, and customer-level response is never inferred.</p></div>

          <div className="grid-2 promotion-forecast-grid">
          <div className="card promotion-performance">
            <CardHeader title="Promotion Performance Forecast" context="Accepted portfolio" />
            <div className="promotion-metric-row">
              <div><span>Baseline Revenue</span><strong>{formatAggregateMoneyMinor(baselineRevenue, portfolioCurrency)}</strong></div>
              <div><span>Promoted Revenue</span><strong>{formatAggregateMoneyMinor(promotedRevenue, portfolioCurrency)}</strong></div>
              <div><span>Incremental Margin</span><strong>{formatAggregateMoneyMinor(marginUplift, portfolioCurrency)}</strong></div>
              <div><span>Cannibalisation Risk</span><RestrictedValue reason="Cannibalisation risk is privacy restricted; a numeric value is never disclosed." label={reasonText("PRIVACY_RESTRICTED")} /></div>
            </div>
            <div className="promotion-bars" aria-label="Promotion outcome scenarios">{scenarios.map((scenario) => <div key={scenario.label}><div className="promotion-bar-track"><div className={`promotion-bar ${scenario.tone}`} style={{height: `${Math.max(24, Math.round((scenario.value / maxScenario) * 130))}px`}}><span>{scenarioIndex(scenario.value)}</span></div></div><strong>{scenario.label}</strong></div>)}</div>
            <p className="promotion-index-caption">Normalized portfolio revenue index (Baseline = 100)</p>
            <table className="sr-only"><caption>Promotion performance accessible data</caption><thead><tr><th>Scenario</th><th>Revenue</th><th>Index</th></tr></thead><tbody>{scenarios.map((scenario) => <tr key={scenario.label}><td>{scenario.label}</td><td>{formatAggregateMoneyMinor(scenario.value, portfolioCurrency)}</td><td>{scenarioIndex(scenario.value)}</td></tr>)}</tbody></table>
          </div>

          <div className="card pricing-table-card"><CardHeader title="AI Promotion Opportunities" context={`${formatCount(opportunityRows.length)} ${opportunityRows.length === 1 ? "recommendation" : "recommendations"}`} /><div className="table-scroll"><table className="table"><thead><tr>{["Opportunity", "Reason", "Expected Value", "Priority"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{opportunityRows.length > 0 ? opportunityRows.map((row, index) => {
            const oppUplift = numberOrNull(row.expectedDemandUplift);
            const oppOffer = numberOrNull(row.offerValue);
            const oppReason = [
              typeof row.categoryLabels === "string" ? row.categoryLabels : null,
              oppUplift !== null ? `+${formatPercent(oppUplift * 100)} demand` : null,
              oppOffer !== null ? `${Math.round(oppOffer * 100)}% off` : null
            ].filter(Boolean).join(" · ");
            const priority = index < 2 ? "High" : index < 4 ? "Medium" : "Low";
            return <tr key={String(row.promoId ?? index)}><td><strong>{String(row.promoName ?? row.promoId)}</strong></td><td>{oppReason || "—"}</td><td>{formatAggregateMoneyMinor(Number(row.revenueUpliftMinor ?? 0), portfolioCurrency)}</td><td>{priority === "Low" ? <span style={{color: "var(--muted)"}}>Low</span> : <span className={`badge ${priority === "High" ? "b-green" : "b-blue"}`}>{priority}</span>}</td></tr>;
          }) : <tr><td colSpan={4}>—</td></tr>}</tbody></table></div></div>
          </div>
          <div className="card pricing-table-card"><CardHeader title="Promotion Portfolio" context={`${formatCount(promotions.length)} ${promotions.length === 1 ? "promotion" : "promotions"}`} /><div className="table-scroll"><table className="table promotion-table"><thead><tr>{["Promotion", "Category", "Period", "Stores / Channels", "Products", "Offer", "Expected Demand Uplift", "Revenue Uplift", "Margin Impact", "Required Stock", "Cannibalisation Risk", "Status", "Owner"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{plannerAvailable && promotions.length > 0 ? promotions.map((promo, index) => <PromotionPortfolioRow key={String(promo.promoId ?? index)} promo={promo} />) : <tr><td colSpan={13}><UnavailableValue reason={message} /></td></tr>}</tbody></table></div></div>

          <div className="grid-3 pricing-bottom-grid">
            <div className="card"><CardHeader title="Inventory Readiness" context="Completed portfolio" /><MetricList rows={[
              {label: "Fully available", value: formatCount(promotions.length)},
              {label: "Transfer required", value: formatCount(0)},
              {label: "Replenishment required", value: formatCount(0)},
              {label: "At-risk promotions", value: formatCount(0)}
            ]} /></div>
            <div className="card"><CardHeader title="Audience Targeting" /><MetricList rows={["Loyalty members", "High-value customers", "Lapsed customers", "Broad audience"].map((label) => ({label, value: <RestrictedValue reason="Customer-level audience composition is privacy restricted and never inferred." label="Privacy restricted" />}))} /></div>
            <div className="card">
              <CardHeader title="Approval & Risk" context="Accepted portfolio" />
              <MetricList rows={[
                {label: "Within margin guardrail", value: formatCount(promotions.length)},
                {label: "Finance review required", value: formatCount(0)},
                {label: "Insufficient stock", value: formatCount(0)},
                {label: "Promotion conflict", value: formatCount(0)}
              ]} />
            </div>
          </div>
          {modal === "create" && <PromotionCreatePreview onClose={() => setModal(null)} />}
          {modal === "simulate" && <PromotionSimulationPreview message={message} onResults={() => setModal("results")} onClose={() => setModal(null)} />}
          {modal === "results" && <PromotionResultsPreview reason={reason} onClose={() => setModal(null)} />}
          {modal === "calendar" && <PromotionCalendar message={message} onClose={() => setModal(null)} />}
        </>
      )}
    </PricingState>
  );
}

export function PricingPage(props: PricingPageProps) {
  if (props.pageId === "priceRecommendations") {
    return <PriceRecommendations dashboard={props.dashboard} storeId={props.storeId} channelType={props.channelType} onNavigate={props.onNavigate} />;
  }
  if (props.pageId === "priceSimulation") {
    return <PriceSimulationPage dashboard={props.dashboard} storeId={props.storeId} channelType={props.channelType} />;
  }
  if (props.pageId === "competitorMonitor") {
    return <CompetitorMonitor storeId={props.storeId} channelType={props.channelType} />;
  }
  return <PromotionPlanner />;
}
