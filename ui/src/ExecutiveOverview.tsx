import {useEffect, useMemo, useRef, useState, type ReactNode} from "react";
import {useQuery} from "@tanstack/react-query";
import {
  loadExecutiveOverview,
  loadForecastActuals,
  loadForecastStores,
  loadInventorySlice,
  type Dashboard,
  type ForecastFilters,
  type ForecastSummary,
  type InventoryFilters,
  type InventorySlice
} from "./api";
import {formatAggregateMoneyMinor} from "./currencyFormat";
import {
  loadGroupedRecommendations,
  loadPricingGovernance,
  loadRecommendationSummary,
  type PricingFilters
} from "./pricingApi";

type Row = Record<string, unknown>;

export type ExecutiveDestination =
  | "demandForecast"
  | "priceRecommendations"
  | "inventoryOverview"
  | "storeInventory"
  | "inventoryAgeing"
  | "inventoryTransfers"
  | "replenishmentExceptions";

type ExecutiveDialog = "actions" | "store" | "business";

type Props = {
  dashboard: Dashboard;
  storeId: string;
  channelType: string;
  forecastSummary?: ForecastSummary;
  forecastSummaryPending: boolean;
  forecastSummaryError: Error | null;
  onNavigate: (page: ExecutiveDestination) => void;
};

const unavailable = "Not available";
const realizedValueReason =
  "A governed realized-value attribution and comparison baseline are not published.";

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function summaryNumber(slice: InventorySlice | undefined, key: string) {
  return asNumber(slice?.summary?.[key]);
}

function rowNumber(row: Row | undefined, key: string) {
  return asNumber(row?.[key]);
}

function rowText(row: Row | undefined, ...keys: string[]) {
  for (const key of keys) {
    const value = textOf(row?.[key]);
    if (value) return value;
  }
  return null;
}

function normalize(value: unknown) {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase("en-US")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function formatCount(value: number | null | undefined) {
  return value === null || value === undefined
    ? unavailable
    : new Intl.NumberFormat("en-US", {maximumFractionDigits: 0}).format(value);
}

function formatPercent(value: number | null | undefined, digits = 1) {
  return value === null || value === undefined
    ? unavailable
    : `${value.toFixed(digits)}%`;
}

function formatDays(value: number | null | undefined) {
  return value === null || value === undefined
    ? unavailable
    : `${value.toFixed(1)} days`;
}

function money(value: number | null | undefined, currency: string) {
  return formatAggregateMoneyMinor(value, currency);
}

function sum(values: Array<number | null | undefined>) {
  const available = values.filter((value): value is number =>
    value !== null && value !== undefined && Number.isFinite(value)
  );
  if (!available.length) return null;
  return available.reduce((total, value) => total + value, 0);
}

function badgeClass(value: string) {
  const key = value.toLocaleLowerCase("en-US");
  if (/strong|healthy|low|ready|ahead|improving|approved/.test(key)) return "b-green";
  if (/high|action|urgent|critical|escalated|outside|overstock/.test(key)) return "b-red";
  if (/watch|medium|risk|pending|review|warning/.test(key)) return "b-amber";
  if (/unavailable|not assigned|no signal/.test(key)) return "b-gray";
  return "b-blue";
}

function Badge({children}: {children: ReactNode}) {
  const label = String(children);
  return <span className={`badge ${badgeClass(label)}`}>{children}</span>;
}

function UnavailableValue({reason}: {reason: string}) {
  return (
    <span
      className="cell-unavailable"
      data-unavailable="true"
      title={reason}
    >
      {unavailable}
    </span>
  );
}

function ExecutiveKpi({
  name,
  label,
  value,
  pending = false,
  reason,
  delta,
  deltaTone = "up",
  note
}: {
  name: string;
  label: string;
  value: string | null;
  pending?: boolean;
  reason: string;
  delta?: string | null;
  deltaTone?: "up" | "down" | "warn";
  note: string;
}) {
  const displayed = pending ? "Loading…" : value;
  return (
    <div
      className="kpi executive-kpi"
      data-kpi={name}
      data-unavailable={!pending && displayed === null ? "true" : undefined}
      title={!pending && displayed === null ? reason : undefined}
    >
      <small>{label}</small>
      <div className={`value${displayed === null ? " unavailable" : ""}`}>
        {displayed ?? unavailable}
      </div>
      {delta && <span className={`delta ${deltaTone}`}>{delta}</span>}
      <div className="demo-note">{displayed === null ? reason : note}</div>
    </div>
  );
}

function TableEmpty({colSpan, pending = false}: {colSpan: number; pending?: boolean}) {
  return (
    <tr>
      <td className="executive-empty-cell" colSpan={colSpan}>
        {pending ? "Loading live data…" : "No governed rows are available for this scope."}
      </td>
    </tr>
  );
}

function ExecutiveModal({
  open,
  title,
  returnFocus,
  children,
  confirmLabel,
  onConfirm,
  onClose
}: {
  open: boolean;
  title: string;
  returnFocus: HTMLElement | null;
  children: ReactNode;
  confirmLabel?: string;
  onConfirm?: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open) return;
    titleRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])"
      ));
      if (!controls.length) return;
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
  }, [open, returnFocus]);

  if (!open) return null;
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section
        ref={dialogRef}
        className="modal executive-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="executive-modal-title"
      >
        <div className="modal-head">
          <h3 ref={titleRef} id="executive-modal-title" tabIndex={-1}>{title}</h3>
          <button className="modal-close" type="button" aria-label={`Close ${title}`} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-foot">
          {confirmLabel && onConfirm && (
            <button className="modal-action" type="button" onClick={onConfirm}>
              {confirmLabel}
            </button>
          )}
          <button className="filter" type="button" onClick={onClose}>Close</button>
        </div>
      </section>
    </div>
  );
}

function queryFailure(...errors: Array<Error | null | undefined>) {
  return errors.find(Boolean)?.message ?? null;
}

function categoryLabel(dashboard: Dashboard, row: Row | undefined) {
  const key = rowText(row, "category", "categoryId");
  const served = rowText(row, "categoryLabel");
  return dashboard.filters.categories?.find((category) =>
    category.categoryId === key || normalize(category.name) === normalize(served)
  )?.name ?? served ?? key ?? unavailable;
}

function storeRecord(
  rows: Row[],
  store: Dashboard["filters"]["stores"][number]
) {
  return rows.find((row) =>
    rowText(row, "locationId", "storeId", "store") === store.storeId ||
    normalize(rowText(row, "locationName", "storeName")) === normalize(store.name)
  );
}

export function ExecutiveOverview({
  dashboard,
  storeId,
  channelType,
  forecastSummary,
  forecastSummaryPending,
  forecastSummaryError,
  onNavigate
}: Props) {
  const [region, setRegion] = useState("");
  const [category, setCategory] = useState("");
  const [dialog, setDialog] = useState<ExecutiveDialog | null>(null);
  const [dialogStoreId, setDialogStoreId] = useState(storeId);
  const [reviewMessage, setReviewMessage] = useState("");
  const [reportMessage, setReportMessage] = useState("");
  const dialogTrigger = useRef<HTMLElement | null>(null);

  const regions = useMemo(
    () => Array.from(new Set(dashboard.filters.stores.map((store) => store.region)))
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right)),
    [dashboard]
  );
  const topbarStore = dashboard.filters.stores.find((store) => store.storeId === storeId);
  useEffect(() => {
    if (topbarStore && region && topbarStore.region !== region) setRegion("");
  }, [region, topbarStore]);

  const scopedStores = useMemo(() => dashboard.filters.stores.filter((store) => {
    if (storeId && store.storeId !== storeId) return false;
    if (region && store.region !== region) return false;
    return true;
  }), [dashboard, region, storeId]);
  const scopeStoreId = storeId || (scopedStores.length === 1 ? scopedStores[0].storeId : "");
  const scopeMarketIds = Array.from(new Set(scopedStores.map((store) => store.marketId)));
  const scopeMarketId = scopeMarketIds.length === 1 ? scopeMarketIds[0] : "";

  const forecastFilters = useMemo<ForecastFilters>(() => ({
    region: region || undefined,
    storeId: storeId || undefined,
    channelType: channelType || undefined,
    category: category || undefined,
    horizonWeeks: 4
  }), [category, channelType, region, storeId]);
  const inventoryFilters = useMemo<InventoryFilters>(() => ({
    marketId: scopeMarketId || undefined,
    storeId: scopeStoreId || undefined,
    category: category || undefined,
    limit: 100
  }), [category, scopeMarketId, scopeStoreId]);
  const pricingFilters = useMemo<PricingFilters>(() => ({
    storeId: scopeStoreId || undefined,
    channelType: channelType || undefined,
    category: category || undefined
  }), [category, channelType, scopeStoreId]);

  const forecastActuals = useQuery({
    queryKey: ["executive-overview", "forecast-actuals", forecastFilters],
    queryFn: ({signal}) => loadForecastActuals(forecastFilters, signal),
    retry: false
  });
  const executive = useQuery({
    queryKey: ["executive-overview", "read-model", forecastFilters],
    queryFn: ({signal}) => loadExecutiveOverview(forecastFilters, signal),
    retry: false
  });
  const forecastStores = useQuery({
    queryKey: ["executive-overview", "forecast-stores", forecastFilters],
    queryFn: ({signal}) => loadForecastStores(forecastFilters, signal),
    retry: false
  });
  const inventoryOverview = useQuery({
    queryKey: ["executive-overview", "inventory-overview", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/inventory/overview", inventoryFilters, signal),
    retry: false
  });
  const inventoryStores = useQuery({
    queryKey: ["executive-overview", "inventory-stores", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/inventory/stores", inventoryFilters, signal),
    retry: false
  });
  const inventoryValuation = useQuery({
    queryKey: ["executive-overview", "inventory-valuation", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/inventory/valuation", inventoryFilters, signal),
    retry: false
  });
  const inventoryExpiry = useQuery({
    queryKey: ["executive-overview", "inventory-expiry", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/inventory/expiry-waste", inventoryFilters, signal),
    retry: false
  });
  const inventoryTransfers = useQuery({
    queryKey: ["executive-overview", "inventory-transfers", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/inventory/transfers", inventoryFilters, signal),
    retry: false
  });
  const replenishmentExceptions = useQuery({
    queryKey: ["executive-overview", "replenishment-exceptions", inventoryFilters],
    queryFn: ({signal}) => loadInventorySlice("/api/v1/replenishment/exceptions", inventoryFilters, signal),
    retry: false
  });
  const pricingSummary = useQuery({
    queryKey: ["executive-overview", "pricing-summary", pricingFilters],
    queryFn: ({signal}) => loadRecommendationSummary(pricingFilters, signal),
    retry: false
  });
  const pricingStores = useQuery({
    queryKey: ["executive-overview", "pricing-stores", pricingFilters],
    queryFn: ({signal}) => loadGroupedRecommendations("store-view", pricingFilters, signal),
    retry: false
  });
  const pricingCategories = useQuery({
    queryKey: ["executive-overview", "pricing-categories", pricingFilters],
    queryFn: ({signal}) => loadGroupedRecommendations("category-view", pricingFilters, signal),
    retry: false
  });
  const pricingGovernance = useQuery({
    queryKey: ["executive-overview", "pricing-governance", pricingFilters],
    queryFn: ({signal}) => loadPricingGovernance(pricingFilters, signal),
    retry: false
  });

  const inventoryCurrency = executive.data?.reportingCurrency
    ?? inventoryOverview.data?.reportingCurrency
    ?? inventoryStores.data?.reportingCurrency
    ?? dashboard.filters.stores.find((store) => store.storeId === scopeStoreId)?.currencyCode
    ?? dashboard.filters.currencies[0]
    ?? "INR";
  const forecastPortfolio = forecastSummary?.items[0];
  const filteredForecastRows = forecastStores.data?.items ?? [];
  const scopeHasFilter = Boolean(region || storeId || channelType || category);
  const exactStoreForecast = scopeStoreId
    ? filteredForecastRows.find((row) => row.storeId === scopeStoreId)
    : undefined;
  const executiveSummary = executive.data?.summary;
  const forecastAccuracy = executiveSummary?.forecastAccuracyPct
    ?? (scopeHasFilter
      ? exactStoreForecast?.accuracy
        ?? (filteredForecastRows.length === 1 ? filteredForecastRows[0].accuracy : null)
        ?? null
      : forecastPortfolio?.portfolioAccuracy
        ?? forecastPortfolio?.accuracy
        ?? null);
  const forecastFva = scopeHasFilter
    ? null
    : forecastPortfolio?.portfolioFvaVsMa13Pct
      ?? forecastPortfolio?.fvaVsMa13Pct
      ?? null;
  const demandAtRiskMinor = scopeHasFilter && filteredForecastRows.length
    ? sum(filteredForecastRows.map((row) => row.demandAtRiskMinor))
    : forecastPortfolio?.demandAtRiskMinor ?? null;
  const demandAtRiskCells = scopeHasFilter && filteredForecastRows.length
    ? sum(filteredForecastRows.map((row) => row.demandAtRiskCells))
    : forecastPortfolio?.demandAtRiskCells ?? null;

  const onHandValue = region
    ? executiveSummary?.inventoryValueMinor ?? null
    : summaryNumber(inventoryOverview.data, "onHandValueMinor");
  const atRiskValue = summaryNumber(inventoryOverview.data, "atRiskValueMinor");
  const overstockValue = executiveSummary?.overstockValueMinor ?? null;
  const stockoutRate = executiveSummary?.stockoutRatePct ?? null;
  const stockTurn = summaryNumber(inventoryOverview.data, "stockTurn");
  const inventoryDays = region
    ? executiveSummary?.inventoryDays ?? null
    : stockTurn && stockTurn > 0 ? 365 / stockTurn : null;
  const nearExpiryValue = summaryNumber(inventoryExpiry.data, "nearExpiryValueMinor");
  const transferValue = summaryNumber(inventoryTransfers.data, "transferValueMinor");
  const transferBenefit = summaryNumber(inventoryTransfers.data, "expectedBenefitMinor");
  const transferRows = summaryNumber(inventoryTransfers.data, "rows");
  const markdownProvision = summaryNumber(inventoryValuation.data, "provisionMarkdownMinor");
  const exceptionRows = summaryNumber(replenishmentExceptions.data, "rows");
  const exceptionWarnings = summaryNumber(replenishmentExceptions.data, "warnings");

  const pricing = pricingSummary.data;
  const revenueOpportunity = pricing?.kpis.revenueOpportunityMinor ?? null;
  const marginOpportunity = pricing?.kpis.marginOpportunityMinor ?? null;
  const openRecommendations = pricing?.kpis.openRecommendations ?? null;
  const adoption = pricing?.kpis.recommendationAdoption as unknown;
  const adoptionPct = adoption && typeof adoption === "object"
    ? asNumber((adoption as Row).sharePct)
    : null;
  const adoptedCount = adoption && typeof adoption === "object"
    ? asNumber((adoption as Row).adopted)
    : null;
  const recommendationTotal = adoption && typeof adoption === "object"
    ? asNumber((adoption as Row).total)
    : openRecommendations;

  const locationRows = (inventoryStores.data?.cards?.locations
    ?? inventoryOverview.data?.cards?.locations
    ?? []) as Row[];
  const pricingStoreRows = (pricingStores.data?.items ?? []) as Row[];
  const executiveStoreRows = executive.data?.stores ?? [];
  const rankedStoreRows = scopedStores.map((store) => {
    const forecast = filteredForecastRows.find((row) => row.storeId === store.storeId);
    const inventory = storeRecord(locationRows, store);
    const price = storeRecord(pricingStoreRows, store);
    const executiveStore = executiveStoreRows.find((row) => row.storeId === store.storeId);
    const stockoutRisk = forecast?.stockoutRisk
      ?? rowText(inventory, "stockoutRisk")
      ?? "No signal";
    const priorityAction = rowText(inventory, "priorityAction")
      ?? rowText(price, "priorityAction")
      ?? "Review store detail";
    // Reuse the inventory engine's governed action classification rather than
    // inventing a second set of percentage thresholds on the executive page.
    const health = /maintain/i.test(priorityAction)
      ? "Healthy"
      : /rebalance/i.test(priorityAction)
        ? "Overstock"
        : /replenish|transfer|markdown/i.test(priorityAction)
          ? "At Risk"
          : /low/i.test(stockoutRisk)
            ? "Healthy"
            : /high|critical/i.test(stockoutRisk)
              ? "At Risk"
              : /medium|watch/i.test(stockoutRisk)
                ? "Watch"
                : "No signal";
    return {
      store,
      forecast,
      inventory,
      price,
      executive: executiveStore,
      stockoutRisk,
      health,
      priorityAction
    };
  }).sort((left, right) => {
    const risk = (value: string) => /high|critical/i.test(value) ? 0 : /medium|watch/i.test(value) ? 1 : 2;
    return risk(left.stockoutRisk) - risk(right.stockoutRisk)
      || (left.forecast?.accuracy ?? 101) - (right.forecast?.accuracy ?? 101);
  });
  // The approved heatmap is deliberately an executive top-five. Regional
  // rollups and drilldowns still use the complete store population below.
  const storeRows = rankedStoreRows.slice(0, 5);

  const regionRows = useMemo(() => {
    const grouped = new Map<string, typeof rankedStoreRows>();
    for (const row of rankedStoreRows) {
      const existing = grouped.get(row.store.region) ?? [];
      existing.push(row);
      grouped.set(row.store.region, existing);
    }
    return Array.from(grouped, ([name, rows]) => {
      const executiveRegion = executive.data?.regions.find((row) => row.region === name);
      const accuracy = executiveRegion?.forecastAccuracyPct
        ?? (rows.length === 1 ? rows[0].forecast?.accuracy ?? null : null);
      const days = executiveRegion?.inventoryDays
        ?? (rows.length === 1 ? rowNumber(rows[0].inventory, "daysOfSupply") : null);
      const hasHighRisk = rows.some((row) => /high|critical/i.test(row.stockoutRisk));
      const status = hasHighRisk || (accuracy !== null && accuracy < 80)
        ? "Action"
        : accuracy !== null && accuracy >= 90
          ? "Strong"
          : accuracy !== null && accuracy >= 85
            ? "Healthy"
            : "Watch";
      return {name, rows, accuracy, days, status, executive: executiveRegion};
    }).sort((left, right) => (right.accuracy ?? -1) - (left.accuracy ?? -1));
  }, [executive.data?.regions, rankedStoreRows]);

  const inventoryCategoryRows = (inventoryOverview.data?.cards?.categories ?? []) as Row[];
  const pricingCategoryRows = (pricingCategories.data?.items ?? []) as Row[];
  const executiveCategoryRows = executive.data?.categories ?? [];
  const selectedCategory = dashboard.filters.categories?.find((option) =>
    option.categoryId === category
  );
  const categoryKeys = Array.from(new Set([
    ...inventoryCategoryRows.map((row) => normalize(rowText(row, "category", "categoryId", "categoryLabel"))),
    ...pricingCategoryRows.map((row) => normalize(rowText(row, "category", "categoryId", "categoryLabel"))),
    ...executiveCategoryRows.map((row) => normalize(row.category))
  ].filter(Boolean)));
  const categoryRows = categoryKeys.map((key) => {
    const inventory = inventoryCategoryRows.find((row) =>
      normalize(rowText(row, "category", "categoryId", "categoryLabel")) === key
    );
    const price = pricingCategoryRows.find((row) =>
      normalize(rowText(row, "category", "categoryId", "categoryLabel")) === key
    );
    const executiveCategory = executiveCategoryRows.find((row) =>
      normalize(row.category) === key
    );
    return {
      key,
      label: categoryLabel(
        dashboard,
        inventory ?? price ?? (executiveCategory ? {category: executiveCategory.category} : undefined)
      ),
      inventory,
      price,
      executive: executiveCategory,
      action: rowText(price, "priorityAction")
        ?? rowText(inventory, "riskAction")
        ?? "Review category detail"
    };
  }).filter((row) => !category
    || row.key === normalize(category)
    || normalize(row.label) === normalize(selectedCategory?.name)
  ).sort((left, right) =>
    (rowNumber(right.price, "revenueOpportunityMinor") ?? rowNumber(right.inventory, "valueMinor") ?? 0)
    - (rowNumber(left.price, "revenueOpportunityMinor") ?? rowNumber(left.inventory, "valueMinor") ?? 0)
  ).slice(0, 4);

  const approvalPipeline = Array.isArray(pricing?.approvalPipeline)
    ? pricing.approvalPipeline
    : [];
  const pendingReview = sum(approvalPipeline
    .filter((row) => /pending|review/i.test(row.label))
    .map((row) => row.count));
  const pendingReviewPct = pendingReview !== null && recommendationTotal && recommendationTotal > 0
    ? pendingReview * 100 / recommendationTotal
    : null;
  const needingOverride = pricing?.decisionQuality.needingOverride ?? null;
  const needingOverridePct = needingOverride !== null && recommendationTotal && recommendationTotal > 0
    ? needingOverride * 100 / recommendationTotal
    : null;
  const explicitOutsideGuardrails = pricing?.exceptions
    ? sum(pricing.exceptions.map((row) => row.count))
    : null;
  const withinGuardrails = pricing?.decisionQuality.withinGuardrailCount ?? null;
  const outsideGuardrails = explicitOutsideGuardrails
    ?? (openRecommendations !== null && withinGuardrails !== null
      && withinGuardrails >= 0 && withinGuardrails <= openRecommendations
      ? openRecommendations - withinGuardrails
      : null);

  const worstStore = [...filteredForecastRows]
    .filter((row) => row.accuracy !== null && row.accuracy !== undefined)
    .sort((left, right) => (left.accuracy ?? 101) - (right.accuracy ?? 101))[0];
  useEffect(() => {
    if (!dialogStoreId || !scopedStores.some((store) => store.storeId === dialogStoreId)) {
      setDialogStoreId(worstStore?.storeId ?? scopedStores[0]?.storeId ?? "");
    }
  }, [dialogStoreId, scopedStores, worstStore?.storeId]);
  const dialogStore = dashboard.filters.stores.find((store) => store.storeId === dialogStoreId);
  const dialogStoreRow = rankedStoreRows.find((row) => row.store.storeId === dialogStoreId)
    ?? (dialogStore ? {
      store: dialogStore,
      forecast: filteredForecastRows.find((row) => row.storeId === dialogStoreId),
      inventory: storeRecord(locationRows, dialogStore),
      price: storeRecord(pricingStoreRows, dialogStore),
      executive: executiveStoreRows.find((row) => row.storeId === dialogStoreId),
      stockoutRisk: filteredForecastRows.find((row) => row.storeId === dialogStoreId)?.stockoutRisk ?? "No signal",
      health: "No signal",
      priorityAction: "Review store detail"
    } : undefined);

  const actionRows = [
    {
      action: "Review pricing recommendations",
      level: "Business",
      owner: "Pricing",
      due: "Current approval cycle",
      expected: marginOpportunity === null ? unavailable : `${money(marginOpportunity, inventoryCurrency)} margin opportunity`,
      status: adoptedCount && adoptedCount > 0 ? "In Progress" : "Pending",
      page: "priceRecommendations" as ExecutiveDestination
    },
    {
      action: "Authorize inventory transfer recommendations",
      level: "Store",
      owner: "Supply Chain",
      due: "Current transfer plan",
      expected: transferBenefit === null ? unavailable : `${money(transferBenefit, inventoryCurrency)} expected recovery`,
      status: transferRows && transferRows > 0 ? "Review" : "No signal",
      page: "inventoryTransfers" as ExecutiveDestination
    },
    {
      action: "Resolve forecast underperformance",
      level: "Regional",
      owner: "Demand Planning",
      due: "Next forecast review",
      expected: demandAtRiskMinor === null ? unavailable : `${money(demandAtRiskMinor, inventoryCurrency)} demand at risk`,
      status: worstStore?.accuracy !== null && worstStore?.accuracy !== undefined && worstStore.accuracy < 80
        ? "Escalated"
        : "Review",
      page: "demandForecast" as ExecutiveDestination
    },
    {
      action: "Review replenishment exceptions",
      level: "Store",
      owner: rowText(replenishmentExceptions.data?.items[0], "owner") ?? "Supply Planning",
      due: "Current exception queue",
      expected: exceptionRows === null ? unavailable : `${formatCount(exceptionRows)} open exceptions`,
      status: exceptionWarnings && exceptionWarnings > 0 ? "Pending" : "Review",
      page: "replenishmentExceptions" as ExecutiveDestination
    }
  ];

  const chartRows = forecastActuals.data?.items ?? [];
  const chartMax = Math.max(1, ...chartRows.flatMap((row) => [row.forecast, row.actual]));
  const globalError = queryFailure(
    forecastSummaryError,
    executive.error,
    forecastActuals.error,
    forecastStores.error,
    inventoryOverview.error,
    inventoryStores.error,
    inventoryValuation.error,
    inventoryExpiry.error,
    inventoryTransfers.error,
    replenishmentExceptions.error,
    pricingSummary.error,
    pricingStores.error,
    pricingCategories.error,
    pricingGovernance.error
  );
  const scopedAggregationNotes = [
    region && scopedStores.length > 1
      ? "Region scope is exact for revenue, margin, forecast and store inventory. Pricing opportunity remains enterprise-wide because the pricing summary does not publish a region filter."
      : null,
    category
      ? "Category scope is exact for revenue, margin, forecast and current inventory. Transfer, expiry and replenishment projections retain their published market/store scope where those sources do not carry a category key."
      : null
  ].filter((note): note is string => Boolean(note));
  const scopedAggregationNote = scopedAggregationNotes.length
    ? scopedAggregationNotes.join(" ")
    : null;
  const pagePending = forecastSummaryPending || [
    executive,
    forecastActuals,
    forecastStores,
    inventoryOverview,
    inventoryStores,
    inventoryValuation,
    inventoryExpiry,
    inventoryTransfers,
    replenishmentExceptions,
    pricingSummary,
    pricingStores,
    pricingCategories,
    pricingGovernance
  ].some((source) => source.isPending);

  const openDialog = (next: ExecutiveDialog, trigger: HTMLElement) => {
    dialogTrigger.current = trigger;
    setReviewMessage("");
    setDialog(next);
  };
  const navigate = (page: ExecutiveDestination) => {
    setDialog(null);
    onNavigate(page);
  };

  if (pagePending) {
    return (
      <div id="overview" className="executive-overview">
        <div className="state-card" role="status" aria-live="polite" aria-busy="true">
          <strong>Loading Executive Overview…</strong>
          <span>Assembling accepted sales, forecast, pricing and inventory measures.</span>
        </div>
      </div>
    );
  }

  return (
    <div id="overview" className="executive-overview">
      <div className="executive-toolbar" aria-label="Executive Overview actions and filters">
        <button id="executiveActionCenterBtn" className="btn primary" type="button" onClick={(event) => openDialog("actions", event.currentTarget)}>Open Action Center</button>
        <button id="storeDrilldownBtn" className="btn secondary" type="button" onClick={(event) => openDialog("store", event.currentTarget)}>Store-Level Drilldown</button>
        <button id="businessDrilldownBtn" className="btn secondary" type="button" onClick={(event) => openDialog("business", event.currentTarget)}>Business-Level Drilldown</button>
        <button id="executiveReportBtn" className="btn secondary" type="button" onClick={() => {
          setReportMessage("Print dialog opened. Choose Save as PDF to complete the executive report.");
          window.print();
        }}>Export Executive Report</button>
        <select id="executiveRegionFilter" className="filter" aria-label="Executive region" value={region} disabled={Boolean(storeId)} title={storeId ? "The global store filter already fixes the regional scope." : undefined} onChange={(event) => setRegion(event.target.value)}>
          <option value="">All Regions</option>
          {regions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select id="executiveCategoryFilter" className="filter" aria-label="Executive category" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">All Categories</option>
          {(dashboard.filters.categories ?? []).map((option) => (
            <option key={option.categoryId} value={option.categoryId}>{option.name}</option>
          ))}
        </select>
      </div>
      {(reportMessage || scopedAggregationNote || globalError) && (
        <div className={`executive-notice${globalError ? " executive-notice-warning" : ""}`} role="status">
          {reportMessage || scopedAggregationNote || `Some live executive inputs are unavailable: ${globalError}`}
        </div>
      )}

      <div className="kpi-grid executive-kpi-grid">
        <ExecutiveKpi
          name="total-revenue-ltm"
          label="Total Revenue (LTM)"
          value={executiveSummary ? money(executiveSummary.ltmRevenueMinor, inventoryCurrency) : null}
          pending={executive.isPending}
          reason={executive.error?.message ?? "Accepted LTM net sales are unavailable for this scope."}
          delta={executiveSummary?.ltmGrowthPct === null || executiveSummary?.ltmGrowthPct === undefined
            ? "New scope vs LY"
            : `${executiveSummary.ltmGrowthPct >= 0 ? "↑" : "↓"} ${Math.abs(executiveSummary.ltmGrowthPct).toFixed(1)}% vs LY`}
          deltaTone={executiveSummary?.ltmGrowthPct !== null && executiveSummary?.ltmGrowthPct !== undefined && executiveSummary.ltmGrowthPct < 0 ? "down" : "up"}
          note="Canonical net sales after financial refunds"
        />
        <ExecutiveKpi
          name="gross-margin"
          label="Gross Margin %"
          value={executiveSummary?.ltmGrossMarginPct === null || executiveSummary?.ltmGrossMarginPct === undefined
            ? null
            : formatPercent(executiveSummary.ltmGrossMarginPct)}
          pending={executive.isPending}
          reason={executive.error?.message ?? "Current accepted store-receipt WAC does not cover this sales scope."}
          delta={executiveSummary?.grossMarginDeltaPts === undefined
            ? null
            : `${executiveSummary.grossMarginDeltaPts >= 0 ? "↑" : "↓"} ${Math.abs(executiveSummary.grossMarginDeltaPts).toFixed(1)} pts vs LY mix`}
          deltaTone={executiveSummary?.grossMarginDeltaPts !== undefined && executiveSummary.grossMarginDeltaPts < 0 ? "down" : "up"}
          note={`LTM cost-covered net sales · current WAC · ${formatPercent(executiveSummary?.ltmCostCoveragePct)} row coverage`}
        />
        <ExecutiveKpi
          name="inventory-value"
          label="Inventory Value"
          value={onHandValue === null ? null : money(onHandValue, inventoryCurrency)}
          pending={inventoryOverview.isPending || (Boolean(region) && executive.isPending)}
          reason={inventoryOverview.error?.message ?? executive.error?.message ?? "Accepted inventory valuation is unavailable for this scope."}
          note="Accepted unit cost × current on-hand units"
        />
        <ExecutiveKpi
          name="stockout-loss"
          label="Stock-out Loss (Est.)"
          value={demandAtRiskMinor === null ? null : money(demandAtRiskMinor, inventoryCurrency)}
          pending={forecastSummaryPending || forecastStores.isPending}
          reason={forecastSummaryError?.message ?? forecastStores.error?.message ?? "Forecast-to-inventory exposure is unavailable."}
          delta={demandAtRiskCells === null ? null : `${formatCount(demandAtRiskCells)} cells at near-term risk`}
          deltaTone="warn"
          note="Potential unserved-sales exposure; not realized loss"
        />
        <ExecutiveKpi
          name="ai-forecast-accuracy"
          label="AI Forecast Accuracy"
          value={forecastAccuracy === null ? null : formatPercent(forecastAccuracy)}
          pending={forecastSummaryPending || forecastStores.isPending}
          reason={forecastSummaryError?.message
            ?? forecastStores.error?.message
            ?? (scopeHasFilter && filteredForecastRows.length > 1
              ? "A pooled forecast-accuracy aggregate is not published for this filtered multi-store scope; exact values remain available in the store table."
              : "Comparable forecast accuracy is unavailable.")}
          delta={forecastFva === null ? null : `${forecastFva >= 0 ? "↑" : "↓"} ${Math.abs(forecastFva).toFixed(1)}% FVA vs MA13`}
          deltaTone={forecastFva !== null && forecastFva < 0 ? "down" : "up"}
          note={exactStoreForecast ? `Store scope · target 90%` : "Portfolio accuracy · target 90%"}
        />
      </div>

      <div className="grid-3">
        <div className="card">
          <div className="card-head"><h3>Executive Business Health</h3><span>Current month</span></div>
          <div className="table-scroll"><table className="table"><tbody>
            <tr><td>Revenue vs LY</td><td>{executiveSummary ? `${money(executiveSummary.monthRevenueMinor, inventoryCurrency)} / ${money(executiveSummary.monthPriorRevenueMinor, inventoryCurrency)}` : <UnavailableValue reason="Comparable month revenue is unavailable." />}</td><td><Badge>{executiveSummary?.monthGrowthPct === null || executiveSummary?.monthGrowthPct === undefined ? "New" : executiveSummary.monthGrowthPct >= 0 ? "Ahead" : "Watch"}</Badge></td></tr>
            <tr><td>Gross margin vs LY mix</td><td>{executiveSummary?.monthGrossMarginPct === null || executiveSummary?.monthGrossMarginPct === undefined || executiveSummary?.monthPriorGrossMarginPct === null || executiveSummary?.monthPriorGrossMarginPct === undefined ? <UnavailableValue reason="Comparable cost-covered current-WAC margin is unavailable." /> : `${formatPercent(executiveSummary.monthGrossMarginPct)} / ${formatPercent(executiveSummary.monthPriorGrossMarginPct)}`}</td><td><Badge>{executiveSummary?.monthGrossMarginPct !== null && executiveSummary?.monthGrossMarginPct !== undefined && executiveSummary?.monthPriorGrossMarginPct !== null && executiveSummary?.monthPriorGrossMarginPct !== undefined && executiveSummary.monthGrossMarginPct >= executiveSummary.monthPriorGrossMarginPct ? "Ahead" : "Watch"}</Badge></td></tr>
            <tr><td>Inventory days</td><td>{inventoryDays === null ? <UnavailableValue reason="Stock turn is unavailable for this scope." /> : formatDays(inventoryDays)}</td><td><Badge>{inventoryDays === null ? "Unavailable" : "Observed"}</Badge></td></tr>
            <tr><td>Stock-out cell rate</td><td>{stockoutRate === null ? <UnavailableValue reason="Stock-health cell coverage is unavailable." /> : formatPercent(stockoutRate)}</td><td><Badge>{stockoutRate !== null && stockoutRate > 5 ? "Watch" : "Observed"}</Badge></td></tr>
            <tr><td>AI recommendation adoption</td><td>{adoptionPct === null ? <UnavailableValue reason="Approval workflow evidence is not available." /> : formatPercent(adoptionPct)}</td><td><Badge>{adoptionPct === null ? "Unavailable" : adoptionPct >= 70 ? "Improving" : "Watch"}</Badge></td></tr>
          </tbody></table></div>
        </div>

        <div className="card">
          <div className="card-head"><h3>AI Value Realization</h3><span>Current opportunities</span></div>
          <div className="executive-metric-grid">
            <div className="executive-metric"><span>Revenue Opportunity</span><strong>{revenueOpportunity === null ? <UnavailableValue reason={realizedValueReason} /> : money(revenueOpportunity, inventoryCurrency)}</strong><small>Model-implied pricing opportunity</small></div>
            <div className="executive-metric"><span>Margin Opportunity</span><strong>{marginOpportunity === null ? <UnavailableValue reason={pricing?.kpis.marginReasonCode ?? realizedValueReason} /> : money(marginOpportunity, inventoryCurrency)}</strong><small>Current accepted cost basis</small></div>
            <div className="executive-metric"><span>Markdown Provision</span><strong>{markdownProvision === null ? <UnavailableValue reason="Accepted markdown provision is unavailable." /> : money(markdownProvision, inventoryCurrency)}</strong><small>Current ageing-stock exposure</small></div>
            <div className="executive-metric"><span>Transfer Recovery</span><strong>{transferBenefit === null ? <UnavailableValue reason="Accepted transfer benefit is unavailable." /> : money(transferBenefit, inventoryCurrency)}</strong><small>Expected benefit of recommended transfers</small></div>
          </div>
          <div className="callout executive-callout"><strong>Executive insight</strong><p>These values are actionable opportunity and exposure measures. They are not presented as realized attribution without a governed post-action baseline.</p></div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Critical Decisions Required</h3><span>4 live signals</span></div>
          <div className="alert"><div className="alert-icon">₹</div><div><strong>Review high-value markdown exposure</strong><span>{markdownProvision === null ? unavailable : `${money(markdownProvision, inventoryCurrency)} current markdown provision.`}</span></div></div>
          <div className="alert"><div className="alert-icon">!</div><div><strong>Resolve stock-out exposure</strong><span>{demandAtRiskMinor === null ? unavailable : `${formatCount(demandAtRiskCells)} cells may expose ${money(demandAtRiskMinor, inventoryCurrency)} of forecast demand.`}</span></div></div>
          <div className="alert"><div className="alert-icon">↗</div><div><strong>Review price recommendations</strong><span>{openRecommendations === null ? unavailable : `${formatCount(openRecommendations)} recommendations expose ${money(marginOpportunity, inventoryCurrency)} margin opportunity.`}</span></div></div>
          <div className="alert"><div className="alert-icon">⚙</div><div><strong>Investigate forecast underperformance</strong><span>{worstStore ? `${worstStore.name} is the lowest measured store at ${formatPercent(worstStore.accuracy)}.` : unavailable}</span></div></div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card executive-wide-table-card">
          <div className="card-head"><h3>Store Performance Heatmap</h3><button className="link-button" type="button" onClick={() => navigate("storeInventory")}>{formatCount(scopedStores.length)} stores</button></div>
          <div className="table-scroll"><table className="table executive-store-table" id="executiveStoreTable">
            <thead><tr><th>Store</th><th>Revenue vs LY</th><th>Margin (cost-covered WAC)</th><th>Forecast Accuracy</th><th>Stock-out Risk</th><th>Inventory Health</th><th>Priority Action</th></tr></thead>
            <tbody>
              {storeRows.map((row) => <tr key={row.store.storeId}>
                <td><strong>{row.store.name}</strong><small className="executive-cell-note">{row.store.city}</small></td>
                <td>{row.executive?.monthGrowthPct === null ? <span title="No comparable prior-year sales">New</span> : row.executive?.monthGrowthPct === undefined ? <UnavailableValue reason="Comparable store revenue is unavailable." /> : `${row.executive.monthGrowthPct >= 0 ? "+" : ""}${row.executive.monthGrowthPct.toFixed(1)}%`}</td>
                <td>{row.executive?.monthGrossMarginPct === null || row.executive?.monthGrossMarginPct === undefined ? <UnavailableValue reason="Store current-WAC margin coverage is incomplete." /> : formatPercent(row.executive.monthGrossMarginPct)}</td>
                <td>{row.forecast?.accuracy === null || row.forecast?.accuracy === undefined ? <UnavailableValue reason="Comparable store accuracy is unavailable." /> : formatPercent(row.forecast.accuracy)}</td>
                <td><Badge>{row.stockoutRisk}</Badge></td>
                <td><Badge>{row.health}</Badge></td>
                <td><button className="link-button" type="button" onClick={() => navigate("storeInventory")}>{row.priorityAction}</button></td>
              </tr>)}
              {!storeRows.length && <TableEmpty colSpan={7} pending={forecastStores.isPending || inventoryStores.isPending} />}
            </tbody>
          </table></div>
        </div>

        <div className="card executive-wide-table-card">
          <div className="card-head"><h3>Regional Performance</h3><span>Quarter to date</span></div>
          <div className="table-scroll"><table className="table executive-region-table">
            <thead><tr><th>Region</th><th>Revenue</th><th>Growth</th><th>Margin</th><th>Inventory Days</th><th>Forecast Accuracy</th><th>Status</th></tr></thead>
            <tbody>
              {regionRows.map((row) => <tr key={row.name}>
                <td><strong>{row.name}</strong></td>
                <td>{row.executive ? money(row.executive.quarterRevenueMinor, inventoryCurrency) : <UnavailableValue reason="Quarter-to-date regional revenue is unavailable." />}</td>
                <td>{row.executive?.quarterGrowthPct === null ? "New" : row.executive?.quarterGrowthPct === undefined ? <UnavailableValue reason="Comparable prior-year regional revenue is unavailable." /> : `${row.executive.quarterGrowthPct >= 0 ? "+" : ""}${row.executive.quarterGrowthPct.toFixed(1)}%`}</td>
                <td>{row.executive?.quarterGrossMarginPct === null || row.executive?.quarterGrossMarginPct === undefined ? <UnavailableValue reason="Regional current-WAC margin coverage is incomplete." /> : formatPercent(row.executive.quarterGrossMarginPct)}</td>
                <td>{row.days === null ? <UnavailableValue reason="Location days of supply are unavailable." /> : row.days.toFixed(1)}</td>
                <td>{row.accuracy === null ? <UnavailableValue reason="Comparable regional accuracy is unavailable." /> : formatPercent(row.accuracy)}</td>
                <td><Badge>{row.status}</Badge></td>
              </tr>)}
              {!regionRows.length && <TableEmpty colSpan={7} pending={forecastStores.isPending || inventoryStores.isPending} />}
            </tbody>
          </table></div>
        </div>
      </div>

      <div className="grid-3">
        <div className="card">
          <div className="card-head"><h3>Category Performance</h3><button className="link-button" type="button" onClick={() => navigate("priceRecommendations")}>View details</button></div>
          <div className="table-scroll"><table className="table"><thead><tr><th>Category</th><th>Revenue</th><th>Margin</th><th>Sell-through</th><th>Action</th></tr></thead><tbody>
            {categoryRows.map((row) => <tr key={row.key}>
              <td><strong>{row.label}</strong></td>
              <td>{row.executive ? money(row.executive.quarterRevenueMinor, inventoryCurrency) : <UnavailableValue reason="Quarter-to-date category revenue is unavailable." />}</td>
              <td>{row.executive?.quarterGrossMarginPct === null || row.executive?.quarterGrossMarginPct === undefined ? <UnavailableValue reason="Category current-WAC margin coverage is incomplete." /> : formatPercent(row.executive.quarterGrossMarginPct)}</td>
              <td>{row.executive?.sellThroughPct === null || row.executive?.sellThroughPct === undefined ? <UnavailableValue reason="Trailing 91-day category sell-through is unavailable." /> : formatPercent(row.executive.sellThroughPct)}</td>
              <td><button className="link-button" type="button" onClick={() => navigate("priceRecommendations")}>{row.action}</button></td>
            </tr>)}
            {!categoryRows.length && <TableEmpty colSpan={5} pending={inventoryOverview.isPending || pricingCategories.isPending} />}
          </tbody></table></div>
          <p className="executive-card-note">Quarter-to-date net revenue; margin uses cost-covered sales at the current accepted store-receipt WAC; sell-through uses trailing 91-day demand.</p>
        </div>

        <div className="card">
          <div className="card-head"><h3>Inventory Risk Exposure</h3><button className="link-button" type="button" onClick={() => navigate("inventoryOverview")}>₹ value</button></div>
          <table className="table"><tbody>
            <tr><td>Overstock</td><td>{overstockValue === null ? <UnavailableValue reason="Costed overstock exposure is unavailable." /> : money(overstockValue, inventoryCurrency)}</td><td><Badge>{overstockValue && overstockValue > 0 ? "High" : "No signal"}</Badge></td></tr>
            <tr><td>At-risk inventory</td><td>{atRiskValue === null ? <UnavailableValue reason="At-risk inventory value is unavailable." /> : money(atRiskValue, inventoryCurrency)}</td><td><Badge>{atRiskValue && atRiskValue > 0 ? "Watch" : "No signal"}</Badge></td></tr>
            <tr><td>Near stock-out</td><td>{demandAtRiskMinor === null ? <UnavailableValue reason="Forecast demand at risk is unavailable." /> : `${money(demandAtRiskMinor, inventoryCurrency)} sales risk`}</td><td><Badge>{demandAtRiskMinor && demandAtRiskMinor > 0 ? "High" : "No signal"}</Badge></td></tr>
            <tr><td>Near expiry</td><td>{nearExpiryValue === null ? <UnavailableValue reason="Near-expiry cost exposure is unavailable." /> : money(nearExpiryValue, inventoryCurrency)}</td><td><Badge>{nearExpiryValue && nearExpiryValue > 0 ? "Watch" : "No signal"}</Badge></td></tr>
            <tr><td>Transfer opportunity</td><td>{transferValue === null ? <UnavailableValue reason="Transfer recommendation value is unavailable." /> : money(transferValue, inventoryCurrency)}</td><td><Badge>{transferRows && transferRows > 0 ? "Action" : "No signal"}</Badge></td></tr>
          </tbody></table>
        </div>

        <div className="card">
          <div className="card-head"><h3>Pricing Governance</h3><button className="link-button" type="button" onClick={() => navigate("priceRecommendations")}>This week</button></div>
          <table className="table"><tbody>
            <tr><td>Recommendations generated</td><td>{openRecommendations === null ? <UnavailableValue reason="Pricing recommendation summary is unavailable." /> : formatCount(openRecommendations)}</td></tr>
            <tr><td>Approved</td><td>{adoptionPct === null ? <UnavailableValue reason="Approval workflow evidence is not available." /> : formatPercent(adoptionPct)}</td></tr>
            <tr><td>Under review</td><td>{pendingReviewPct === null ? <UnavailableValue reason="Approval pipeline evidence is not available." /> : formatPercent(pendingReviewPct)}</td></tr>
            <tr><td>Needs override</td><td>{needingOverridePct === null ? <UnavailableValue reason="Override evidence is unavailable." /> : formatPercent(needingOverridePct)}</td></tr>
            <tr><td>Outside guardrails</td><td>{outsideGuardrails === null ? <UnavailableValue reason="A distinct outside-guardrail count is not published." /> : <Badge>{formatCount(outsideGuardrails)}</Badge>}</td></tr>
          </tbody></table>
          {!pricingGovernance.data?.approvalSLA.available && <p className="executive-card-note">Counts reflect current recommendation dispositions; no time-based approval SLA is configured.</p>}
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h3>Demand Forecast vs Actual</h3><button className="link-button" type="button" onClick={() => navigate("demandForecast")}>By week</button></div>
          <div className="chart-box executive-chart">
            {chartRows.length ? (
              <>
                <div className="executive-bars" role="img" aria-label="Weekly demand forecast compared with actual units">
                  {chartRows.map((row, index) => <div className="executive-bar-group" key={`${row.targetWeekStart}-${index}`} title={`${row.targetWeekStart}: forecast ${formatCount(row.forecast)}, actual ${formatCount(row.actual)}`}>
                    <div className="executive-bar-pair">
                      <div className="executive-bar forecast" style={{height: `${Math.max(3, row.forecast / chartMax * 100)}%`}}><span>{formatCount(row.forecast)}</span></div>
                      <div className="executive-bar actual" style={{height: `${Math.max(3, row.actual / chartMax * 100)}%`}}><span>{formatCount(row.actual)}</span></div>
                    </div>
                    <small>W{index + 1}</small>
                  </div>)}
                </div>
                <div className="executive-chart-legend"><span><i className="forecast" />Forecast</span><span><i className="actual" />Actual</span></div>
              </>
            ) : <div className="executive-chart-state">{forecastActuals.isPending ? "Loading comparable weeks…" : "Comparable forecast and actual weeks are unavailable."}</div>}
          </div>
        </div>

        <div className="card executive-wide-table-card">
          <div className="card-head"><h3>Executive Action Tracker</h3><button className="link-button" type="button" onClick={(event) => openDialog("actions", event.currentTarget)}>{actionRows.length} open actions</button></div>
          <div className="table-scroll"><table className="table" id="executiveActionTable"><thead><tr><th>Action</th><th>Level</th><th>Accountable Function</th><th>Review Window</th><th>Expected Value</th><th>Status</th></tr></thead><tbody>
            {actionRows.map((row) => <tr key={row.action}>
              <td><button className="link-button" type="button" onClick={() => navigate(row.page)}>{row.action}</button></td>
              <td>{row.level}</td>
              <td>{row.owner}</td>
              <td>{row.due}</td>
              <td>{row.expected}</td>
              <td><Badge>{row.status}</Badge></td>
            </tr>)}
          </tbody></table></div>
          <p className="executive-card-note">Accountable functions and review windows describe the source queue; no individual assignment or due date is implied.</p>
        </div>
      </div>

      <ExecutiveModal
        open={dialog === "actions"}
        title="Executive Action Center"
        returnFocus={dialogTrigger.current}
        confirmLabel="Mark Reviewed"
        onConfirm={() => setReviewMessage("Reviewed for this browser session only; no persistent workflow record was created.")}
        onClose={() => setDialog(null)}
      >
        <div className="executive-summary-grid">
          <div><span>Open Actions</span><strong>{actionRows.length}</strong></div>
          <div><span>High Priority</span><strong>{formatCount([markdownProvision, demandAtRiskMinor, marginOpportunity, exceptionWarnings].filter((value) => value !== null && value !== 0).length)}</strong></div>
          <div><span>Value at Risk</span><strong>{demandAtRiskMinor === null ? unavailable : money(demandAtRiskMinor, inventoryCurrency)}</strong></div>
        </div>
        {reviewMessage && <div className="executive-notice" role="status">{reviewMessage}</div>}
        <div className="table-scroll"><table className="table executive-modal-table"><thead><tr><th>Action</th><th>Accountable Function</th><th>Decision Needed</th><th>Value</th></tr></thead><tbody>
          <tr><td>Ageing stock clearance</td><td>Merchandising</td><td>Review markdown exposure</td><td>{markdownProvision === null ? unavailable : money(markdownProvision, inventoryCurrency)}</td></tr>
          <tr><td>Forecast correction</td><td>Demand Planning</td><td>Review lowest-accuracy scope</td><td>{demandAtRiskMinor === null ? unavailable : `${money(demandAtRiskMinor, inventoryCurrency)} risk`}</td></tr>
          <tr><td>Inventory transfer batch</td><td>Supply Chain</td><td>Authorize operational review</td><td>{transferBenefit === null ? unavailable : money(transferBenefit, inventoryCurrency)}</td></tr>
        </tbody></table></div>
      </ExecutiveModal>

      <ExecutiveModal
        open={dialog === "store"}
        title="Store-Level Drilldown"
        returnFocus={dialogTrigger.current}
        confirmLabel="Open Store Action Plan"
        onConfirm={() => navigate("storeInventory")}
        onClose={() => setDialog(null)}
      >
        <div className="executive-form-grid">
          <label><span>Store</span><select className="filter" value={dialogStoreId} onChange={(event) => setDialogStoreId(event.target.value)}>{scopedStores.map((store) => <option key={store.storeId} value={store.storeId}>{store.name}</option>)}</select></label>
          <label><span>Period</span><select className="filter" defaultValue="This Week"><option>This Week</option><option>This Month</option></select></label>
        </div>
        <div className="grid-2 executive-modal-grid">
          <div className="card"><h3>Store KPIs</h3><table className="table"><tbody>
            <tr><td>Revenue vs LY</td><td>{dialogStoreRow?.executive?.monthGrowthPct === null ? "New" : dialogStoreRow?.executive?.monthGrowthPct === undefined ? unavailable : `${dialogStoreRow.executive.monthGrowthPct >= 0 ? "+" : ""}${dialogStoreRow.executive.monthGrowthPct.toFixed(1)}%`}</td></tr>
            <tr><td>Margin (cost-covered WAC)</td><td>{dialogStoreRow?.executive?.monthGrossMarginPct === null || dialogStoreRow?.executive?.monthGrossMarginPct === undefined ? unavailable : formatPercent(dialogStoreRow.executive.monthGrossMarginPct)}</td></tr>
            <tr><td>Forecast accuracy</td><td>{dialogStoreRow?.forecast?.accuracy === null || dialogStoreRow?.forecast?.accuracy === undefined ? unavailable : formatPercent(dialogStoreRow.forecast.accuracy)}</td></tr>
            <tr><td>Stock-out risk</td><td><Badge>{dialogStoreRow?.stockoutRisk ?? "No signal"}</Badge></td></tr>
          </tbody></table></div>
          <div className="card"><h3>Recommended Actions</h3><table className="table"><tbody>
            <tr><td>{rowText(dialogStoreRow?.inventory, "priorityAction") ?? "Review store inventory"}</td><td>{rowNumber(dialogStoreRow?.inventory, "valueMinor") === null ? unavailable : money(rowNumber(dialogStoreRow?.inventory, "valueMinor"), inventoryCurrency)}</td></tr>
            <tr><td>{rowText(dialogStoreRow?.price, "priorityAction") ?? "Review local pricing"}</td><td>{rowNumber(dialogStoreRow?.price, "recommendations") === null ? unavailable : `${formatCount(rowNumber(dialogStoreRow?.price, "recommendations"))} recommendations`}</td></tr>
            <tr><td>Review forecast exceptions</td><td>{dialogStoreRow?.forecast?.demandAtRiskCells === null || dialogStoreRow?.forecast?.demandAtRiskCells === undefined ? unavailable : `${formatCount(dialogStoreRow.forecast.demandAtRiskCells)} cells`}</td></tr>
          </tbody></table></div>
        </div>
      </ExecutiveModal>

      <ExecutiveModal
        open={dialog === "business"}
        title="Business-Level Drilldown"
        returnFocus={dialogTrigger.current}
        onClose={() => setDialog(null)}
      >
        <div className="grid-2 executive-modal-grid">
          <div className="card"><h3>Business Levers</h3><table className="table"><tbody>
            <tr><td>Pricing optimization</td><td>{marginOpportunity === null ? unavailable : `${money(marginOpportunity, inventoryCurrency)} margin opportunity`}</td></tr>
            <tr><td>Markdown optimization</td><td>{markdownProvision === null ? unavailable : `${money(markdownProvision, inventoryCurrency)} exposure`}</td></tr>
            <tr><td>Inventory transfers</td><td>{transferValue === null ? unavailable : `${money(transferValue, inventoryCurrency)} opportunity`}</td></tr>
            <tr><td>Forecast improvement</td><td>{demandAtRiskMinor === null ? unavailable : `${money(demandAtRiskMinor, inventoryCurrency)} sales risk`}</td></tr>
          </tbody></table></div>
          <div className="card"><h3>Executive Decisions</h3><table className="table"><tbody>
            <tr><td>Pricing guardrails</td><td><Badge>{withinGuardrails !== null && withinGuardrails > 0 ? "Ready" : "Review"}</Badge></td></tr>
            <tr><td>Clearance exposure</td><td><Badge>{markdownProvision !== null && markdownProvision > 0 ? "Review" : "No signal"}</Badge></td></tr>
            <tr><td>Model retraining</td><td><Badge>{worstStore?.accuracy !== null && worstStore?.accuracy !== undefined && worstStore.accuracy < 80 ? "Review" : "No signal"}</Badge></td></tr>
            <tr><td>Transfer plan</td><td><Badge>{transferRows && transferRows > 0 ? "Ready" : "No signal"}</Badge></td></tr>
          </tbody></table></div>
        </div>
      </ExecutiveModal>
    </div>
  );
}
