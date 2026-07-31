import {useEffect, useMemo, useState, type ReactNode} from "react";
import {useQuery} from "@tanstack/react-query";
import {
  loadDashboard,
  loadForecastSummary,
  loadFx,
  type Dashboard,
  type FxRates
} from "./api";
import {DemandForecast} from "./Forecast";

type SourceRow = Dashboard["sources"][number];

const currencySymbols: Record<string, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
  AED: "د.إ"
};

const currencyNames: Record<string, string> = {
  INR: "Indian Rupee",
  USD: "US Dollar",
  EUR: "Euro",
  GBP: "Pound Sterling",
  AED: "UAE Dirham"
};

const primaryNavigation = [
  {icon: "⌂", label: "Executive Overview"}
];

const pricingNavigation = [
  {icon: "🏷", label: "Price Recommendations"},
  {icon: "◫", label: "Price Simulation"},
  {icon: "◉", label: "Competitor Monitor"},
  {icon: "▣", label: "Promotion Planner"}
];

const inventoryNavigation = [
  {icon: "▥", label: "Store Inventory"},
  {icon: "▦", label: "Warehouse Inventory"},
  {icon: "◷", label: "Inventory Ageing"},
  {icon: "⇄", label: "Stock Transfers"},
  {icon: "₹", label: "Inventory Valuation"},
  {icon: "⚠", label: "Expiry & Waste"}
];

const replenishmentNavigation = [
  {icon: "≣", label: "Suggested Orders"},
  {icon: "▦", label: "Supplier Planning"},
  {icon: "◉", label: "Safety Stock"},
  {icon: "⇢", label: "Allocation & Fulfillment"},
  {icon: "⚠", label: "Exceptions"}
];

const analyticsNavigation = [
  {icon: "⌁", label: "Performance Insights"},
  {icon: "□", label: "Reports & Exports"},
  {icon: "♢", label: "Alerts & Notifications"}
];

const adminNavigation = [
  {icon: "▦", label: "Data Management"},
  {icon: "⚙", label: "Model Management"},
  {icon: "☼", label: "Settings"}
];

function NavItem({
  icon,
  label,
  active = false,
  onClick
}: {
  icon: string;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      className={`nav-item${active ? " active" : ""}`}
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      <span className="nav-ico">{icon}</span>
      {label}
    </button>
  );
}

function NavigationSection({
  title,
  items,
  activeLabel,
  onSelect
}: {
  title: string;
  items: Array<{icon: string; label: string}>;
  activeLabel?: string;
  onSelect?: (label: string) => void;
}) {
  return (
    <div className="nav-section">
      <div className="nav-title">{title}</div>
      {items.map((item) => (
        <NavItem
          key={item.label}
          {...item}
          active={item.label === activeLabel}
          onClick={() => onSelect?.(item.label)}
        />
      ))}
    </div>
  );
}

function NavigationParent({
  icon,
  label,
  open,
  onToggle,
  children
}: {
  icon: string;
  label: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <>
      <button
        className={`nav-item nav-parent${open ? " open" : ""}`}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span>
          <span className="nav-ico">{icon}</span>
          {label}
        </span>
        <span className="nav-caret">▶</span>
      </button>
      <div className={`nav-submenu${open ? " open" : ""}`}>{children}</div>
    </>
  );
}

function Sidebar({
  page,
  onPage
}: {
  page: "demandForecast" | "dataManagement";
  onPage: (page: "demandForecast" | "dataManagement") => void;
}) {
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [replenishmentOpen, setReplenishmentOpen] = useState(false);
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">🛒</div>
        <div>
          <h1>AI Retail Intelligence</h1>
          <p>Dynamic Pricing &amp;<br />Demand Forecasting</p>
        </div>
      </div>
      <div className="mobile-navigation" aria-label="Primary mobile navigation">
        <NavItem
          icon="▥"
          label="Demand Forecast"
          active={page === "demandForecast"}
          onClick={() => onPage("demandForecast")}
        />
        <NavItem
          icon="▦"
          label="Data Management"
          active={page === "dataManagement"}
          onClick={() => onPage("dataManagement")}
        />
      </div>

      {primaryNavigation.map((item) => <NavItem key={item.label} {...item} />)}
      <NavigationSection title="PRICING" items={pricingNavigation} />

      <div className="nav-section">
        <div className="nav-title">DEMAND &amp; INVENTORY</div>
        <NavItem
          icon="▥"
          label="Demand Forecast"
          active={page === "demandForecast"}
          onClick={() => onPage("demandForecast")}
        />
        <NavigationParent
          icon="▤"
          label="Inventory Overview"
          open={inventoryOpen}
          onToggle={() => setInventoryOpen((value) => !value)}
        >
          {inventoryNavigation.map((item) => <NavItem key={item.label} {...item} />)}
        </NavigationParent>
        <NavigationParent
          icon="⇄"
          label="Replenishment Planner"
          open={replenishmentOpen}
          onToggle={() => setReplenishmentOpen((value) => !value)}
        >
          {replenishmentNavigation.map((item) => <NavItem key={item.label} {...item} />)}
        </NavigationParent>
        <NavItem icon="◇" label="Stock Health" />
      </div>

      <NavigationSection title="ANALYTICS" items={analyticsNavigation} />
      <NavigationSection
        title="ADMIN"
        items={adminNavigation}
        activeLabel={page === "dataManagement" ? "Data Management" : undefined}
        onSelect={(label) => {
          if (label === "Data Management") onPage("dataManagement");
        }}
      />
    </aside>
  );
}

function formatDateRange(start: string, end: string) {
  const format = (value: string) =>
    new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "2-digit",
      year: "numeric",
      timeZone: "UTC"
    }).format(new Date(`${value}T00:00:00Z`));
  return `${format(start)} – ${format(end)}`;
}

function relativeTime(value: string, compact = false) {
  const elapsedMinutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 60_000)
  );
  if (elapsedMinutes < 1) return compact ? "Now" : "Just now";
  if (elapsedMinutes < 60) {
    return compact ? `${elapsedMinutes}m` : `${elapsedMinutes} min ago`;
  }
  const hours = Math.floor(elapsedMinutes / 60);
  if (hours < 24) return compact ? `${hours}h` : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return compact ? `${days}d` : `${days} days ago`;
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric"
  }).format(new Date(value));
}

function formatCount(value: number, compact = false) {
  return new Intl.NumberFormat("en-US", compact ? {
    notation: "compact",
    maximumFractionDigits: 1
  } : {}).format(value);
}

function formatPct(value: number | null) {
  return value === null ? "Not available" : `${value.toFixed(1)}%`;
}

function storeLabel(store: Dashboard["filters"]["stores"][number]) {
  return store.name;
}

function currencyAmount(value: string) {
  const amount = Number(value);
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 6
  }).format(amount);
}

function rateText(rate: FxRates["rates"][number]) {
  if (rate.baseCurrency === rate.quoteCurrency) {
    return "Base currency";
  }
  const baseSymbol = currencySymbols[rate.baseCurrency] ?? `${rate.baseCurrency} `;
  const quoteSymbol = currencySymbols[rate.quoteCurrency] ?? `${rate.quoteCurrency} `;
  return `${baseSymbol}1 = ${quoteSymbol}${currencyAmount(
    rate.rate
  )}`;
}

function displayRateText(currency: string, fx?: FxRates) {
  if (!fx) return "Loading accepted FX rate…";
  if (currency === fx.reportingCurrency) {
    return `Base currency — ${
      currencyNames[fx.reportingCurrency] ?? fx.reportingCurrency
    }`;
  }
  const rate = fx.rates.find(
    (row) => row.baseCurrency === currency &&
      row.quoteCurrency === fx.reportingCurrency
  );
  if (!rate) return "No accepted FX rate is available";
  return `${rateText(rate)} • as of ${formatDateRange(
    rate.rateDate,
    rate.rateDate
  ).split(" – ")[0]}`;
}

function Topbar({
  dashboard,
  title,
  subtitle,
  storeId,
  onStoreId,
  channelType,
  onChannelType,
  currency,
  onCurrency,
  onFx
}: {
  dashboard?: Dashboard;
  title: string;
  subtitle: string;
  storeId: string;
  onStoreId: (value: string) => void;
  channelType: string;
  onChannelType: (value: string) => void;
  currency: string;
  onCurrency: (value: string) => void;
  onFx: () => void;
}) {
  const selectedStore = dashboard?.filters.stores.find(
    (store) => store.storeId === storeId
  );
  const channelTypes = useMemo(
    () => (dashboard?.filters.channelTypes ?? []).filter(
      (channel) => !selectedStore ||
        channel.marketIds.includes(selectedStore.marketId)
    ),
    [dashboard, selectedStore]
  );
  const selectStore = (nextStoreId: string) => {
    onStoreId(nextStoreId);
    const marketId = dashboard?.filters.stores.find(
      (store) => store.storeId === nextStoreId
    )?.marketId;
    if (channelType && marketId && !dashboard?.filters.channelTypes.some(
      (channel) => channel.type === channelType &&
        channel.marketIds.includes(marketId)
    )) {
      onChannelType("");
    }
  };
  return (
    <header className="topbar">
      <div className="title">
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      <div className="filters">
        <select
          className="filter"
          aria-label="Channel"
          value={channelType}
          onChange={(event) => onChannelType(event.target.value)}
        >
          <option value="">All Channels</option>
          {channelTypes.map((channel) => (
            <option key={channel.type} value={channel.type}>
              {channel.name}
            </option>
          ))}
        </select>
        <input
          className="filter date-filter"
          aria-label="Date range"
          readOnly
          value={dashboard ? formatDateRange(
            dashboard.filters.dateRange.start,
            dashboard.filters.dateRange.end
          ) : "Loading date range"}
        />
        <select
          className="filter"
          aria-label="Store"
          value={storeId}
          onChange={(event) => selectStore(event.target.value)}
        >
          <option value="">All Stores</option>
          {(dashboard?.filters.stores ?? []).map((store) => (
            <option key={store.storeId} value={store.storeId}>
              {storeLabel(store)}
            </option>
          ))}
        </select>
        <select
          className="filter"
          aria-label="Display currency"
          value={currency}
          onChange={(event) => onCurrency(event.target.value)}
        >
          {(dashboard?.filters.currencies ?? ["INR"]).map((code) => (
            <option key={code} value={code}>
              {currencySymbols[code] ?? ""} {code}
            </option>
          ))}
        </select>
        <button
          className="filter"
          type="button"
          title="Currency settings"
          onClick={onFx}
        >
          FX
        </button>
        <button className="filter icon-button" type="button" aria-label="Notifications">🔔</button>
      </div>
    </header>
  );
}

function FxModal({
  open,
  fx,
  pending,
  error,
  onClose
}: {
  open: boolean;
  fx?: FxRates;
  pending: boolean;
  error: Error | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop open"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        aria-labelledby="fx-modal-title"
        aria-modal="true"
        className="modal"
        role="dialog"
      >
        <div className="modal-head">
          <h3 id="fx-modal-title">Multi-Currency Configuration</h3>
          <button
            aria-label="Close currency settings"
            className="modal-close"
            onClick={onClose}
            type="button"
          >
            ✕
          </button>
        </div>
        <div className="modal-body">
          {pending && (
            <div className="modal-state">Loading accepted FX rates…</div>
          )}
          {error && (
            <div className="modal-state modal-error">
              Live FX rates are unavailable. No fallback rates are displayed.
            </div>
          )}
          {fx && (
            <>
              <div className="callout">
                <strong>Accepted FX rates</strong>
                <p>
                  Rates convert each local/base currency into the retailer
                  reporting currency, {fx.reportingCurrency}. Values are read
                  from the accepted curated publication.
                </p>
              </div>
              <table className="table fx-table">
                <thead>
                  <tr>
                    <th>Currency</th>
                    <th>Configured Rate</th>
                    <th>Rate Date</th>
                  </tr>
                </thead>
                <tbody>
                  {fx.rates.map((rate) => (
                    <tr key={`${rate.baseCurrency}:${rate.quoteCurrency}`}>
                      <td>
                        <strong>{rate.baseCurrency}</strong>
                      </td>
                      <td>{rateText(rate)}</td>
                      <td>{formatDateRange(
                        rate.rateDate,
                        rate.rateDate
                      ).split(" – ")[0]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="fx-coverage">
                {formatCount(fx.coverage.observations)} accepted daily
                observations from {fx.coverage.start} through {fx.coverage.end}.
              </p>
            </>
          )}
        </div>
        <div className="modal-foot">
          <button className="modal-action" onClick={onClose} type="button">
            Close
          </button>
        </div>
      </section>
    </div>
  );
}

function Kpi({
  name,
  label,
  value
}: {
  name: string;
  label: string;
  value: string;
}) {
  return (
    <div className="kpi" data-kpi={name}>
      <small>{label}</small>
      <div className="value">{value}</div>
    </div>
  );
}

function SourceTable({sources}: {sources: SourceRow[]}) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="card source-card">
      <div className="table-scroll">
        <table className="table" data-table="sources">
          <thead>
            <tr>
              <th>Source</th>
              <th>Type</th>
              <th>Last Refresh</th>
              <th>Records</th>
              <th>Quality</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <FragmentRow
                key={source.sourceSystem}
                source={source}
                selected={selected === source.sourceSystem}
                onToggle={() => setSelected(
                  selected === source.sourceSystem ? null : source.sourceSystem
                )}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FragmentRow({
  source,
  selected,
  onToggle
}: {
  source: SourceRow;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr>
        <td><strong>{source.name}</strong></td>
        <td>{source.type}</td>
        <td>{relativeTime(source.lastRefreshAt)}</td>
        <td>{formatCount(source.records, true)}</td>
        <td>{formatPct(source.qualityPct)}</td>
        <td>
          <span className={`badge ${
            source.status === "Healthy" ? "b-green" : "b-amber"
          }`}>
            {source.status}
          </span>
        </td>
        <td>
          <button className="link-button" type="button" onClick={onToggle}>
            {selected ? "Hide mapping" : source.action}
          </button>
        </td>
      </tr>
      {selected && (
        <tr className="source-detail-row">
          <td colSpan={7}>
            <strong>{formatCount(source.datasetCount)} mapped datasets</strong>
            <span>{formatCount(source.objectCount)} accepted source objects</span>
            <span>Source key: {source.sourceSystem}</span>
          </td>
        </tr>
      )}
    </>
  );
}

function FooterKpis({
  dashboard,
  forecastCoveragePct,
  modelAccuracyPct
}: {
  dashboard: Dashboard;
  forecastCoveragePct?: number | null;
  modelAccuracyPct?: number | null;
}) {
  const values = [
    ["total-skus", "Total SKUs", formatCount(dashboard.footer.totalSkus)],
    ["active-skus", "Active SKUs", formatCount(dashboard.footer.activeSkus)],
    ["stores", "Stores", formatCount(dashboard.footer.stores)],
    ["channels", "Channels", formatCount(dashboard.footer.channels)],
    [
      "forecast-coverage",
      "Forecast Coverage",
      formatPct(forecastCoveragePct ?? dashboard.footer.forecastCoveragePct)
    ],
    [
      "data-freshness",
      "Data Freshness",
      formatPct(dashboard.kpis.dataFreshnessPct)
    ],
    [
      "model-accuracy",
      // Labelled "all horizons" because the Demand Forecast tiles above are scoped to
      // the selected window. 92.8 here beside 93.8 there is not a discrepancy, it is a
      // different horizon span, and decision #78 requires that to be visible.
      "Model Accuracy (all horizons)",
      formatPct(modelAccuracyPct ?? dashboard.footer.modelAccuracyPct)
    ]
  ];
  return (
    <div className="footer-kpis">
      {values.map(([name, label, value]) => (
        <div className="footer-kpi" data-footer-kpi={name} key={name}>
          <span>{label}</span>
          <strong className={value === "Not available" ? "unavailable" : ""}>
            {value}
          </strong>
        </div>
      ))}
    </div>
  );
}

function Shell({
  dashboard,
  fx,
  fxPending = false,
  fxError = null,
  page,
  onPage,
  storeId,
  onStoreId,
  channelType,
  onChannelType,
  forecastCoveragePct,
  modelAccuracyPct,
  children
}: {
  dashboard?: Dashboard;
  fx?: FxRates;
  fxPending?: boolean;
  fxError?: Error | null;
  page: "demandForecast" | "dataManagement";
  onPage: (page: "demandForecast" | "dataManagement") => void;
  storeId: string;
  onStoreId: (value: string) => void;
  channelType: string;
  onChannelType: (value: string) => void;
  forecastCoveragePct?: number | null;
  modelAccuracyPct?: number | null;
  children: ReactNode;
}) {
  const [currency, setCurrency] = useState("INR");
  const [fxOpen, setFxOpen] = useState(false);
  const availableCurrencies = dashboard?.filters.currencies ?? [];
  const activeCurrency = availableCurrencies.includes(currency)
    ? currency
    : availableCurrencies[0] ?? "INR";
  return (
    <div className="app">
      <Sidebar page={page} onPage={onPage} />
      <main className="main">
        <Topbar
          dashboard={dashboard}
          title={page === "demandForecast" ? "Demand Forecast" : "Data Management"}
          subtitle={page === "demandForecast"
            ? "Forecast demand by SKU, store, channel and time"
            : "Monitor source systems, data freshness and data quality"}
          storeId={storeId}
          onStoreId={onStoreId}
          channelType={channelType}
          onChannelType={onChannelType}
          currency={activeCurrency}
          onCurrency={setCurrency}
          onFx={() => setFxOpen(true)}
        />
        <section className="content">
          <div className="currency-rate-strip">
            <strong>Display Currency:</strong>
            <span className="currency-chip">
              {currencySymbols[activeCurrency] ?? ""} {activeCurrency}
            </span>
            <span>
              {displayRateText(activeCurrency, fx)}
            </span>
            <span>
              {page === "demandForecast"
                ? "Demand Forecast currently presents units and percentages; no live monetary measure is converted."
                : "All monetary values update across dashboards, tables, modals and exports."}
            </span>
          </div>
          {children}
          {dashboard && (
            <FooterKpis
              dashboard={dashboard}
              forecastCoveragePct={forecastCoveragePct}
              modelAccuracyPct={modelAccuracyPct}
            />
          )}
          <div className="page-footer">
            <span>AI Retail Intelligence — Dynamic Pricing &amp; Demand Forecasting</span>
            <span>Powered by AI • Built for Retail</span>
          </div>
        </section>
      </main>
      <FxModal
        open={fxOpen}
        fx={fx}
        pending={fxPending}
        error={fxError}
        onClose={() => setFxOpen(false)}
      />
    </div>
  );
}

function DataManagement({dashboard}: {dashboard: Dashboard}) {
  return (
    <>
      <div className="kpi-grid">
        <Kpi
          name="data-freshness"
          label="Data Freshness"
          value={formatPct(dashboard.kpis.dataFreshnessPct)}
        />
        <Kpi
          name="quality-score"
          label="Quality Score"
          value={formatPct(dashboard.kpis.qualityScorePct)}
        />
        <Kpi
          name="connected-sources"
          label="Connected Sources"
          value={formatCount(dashboard.kpis.connectedSources)}
        />
        <Kpi
          name="rejected-records"
          label="Rejected Records"
          value={formatCount(dashboard.kpis.rejectedRecords)}
        />
        <Kpi
          name="last-refresh"
          label="Last Refresh"
          value={relativeTime(dashboard.kpis.lastRefreshAt, true)}
        />
      </div>
      <SourceTable sources={dashboard.sources} />
    </>
  );
}

export default function App() {
  const initialPage = new URLSearchParams(window.location.search).get("page");
  const [page, setPage] = useState<"demandForecast" | "dataManagement">(
    initialPage === "dataManagement" ? "dataManagement" : "demandForecast"
  );
  const [storeId, setStoreId] = useState("");
  const [channelType, setChannelType] = useState("");
  const dashboard = useQuery({
    queryKey: ["data-management-dashboard"],
    queryFn: loadDashboard
  });
  const fx = useQuery({
    queryKey: ["fx-rates"],
    queryFn: loadFx
  });
  const forecastSummary = useQuery({
    queryKey: ["forecast-summary"],
    queryFn: loadForecastSummary,
    enabled: page === "demandForecast"
  });
  const changePage = (nextPage: "demandForecast" | "dataManagement") => {
    setPage(nextPage);
    const url = new URL(window.location.href);
    url.searchParams.set("page", nextPage);
    window.history.replaceState({}, "", url);
  };
  const shellProps = {
    page,
    onPage: changePage,
    storeId,
    onStoreId: setStoreId,
    channelType,
    onChannelType: setChannelType,
    fx: fx.data,
    fxPending: fx.isPending,
    fxError: fx.error,
    forecastCoveragePct: forecastSummary.data?.items[0]?.forecastCoveragePct,
    // "Model Accuracy" in the footer describes the whole portfolio, so it must be
    // the portfolio-grain figure (92.8) and not the SeriesKey one (72.3).
    modelAccuracyPct: forecastSummary.data?.items[0]?.portfolioAccuracy
      ?? forecastSummary.data?.items[0]?.accuracy
  };

  if (dashboard.isPending) {
    return (
      <Shell {...shellProps}>
        <div className="state-card">Loading live retail data…</div>
      </Shell>
    );
  }
  if (dashboard.error || !dashboard.data) {
    return (
      <Shell {...shellProps}>
        <div className="state-card error-state">
          <strong>Live data is unavailable.</strong>
          <span>{String(dashboard.error)}</span>
          <small>No sample or fallback values are displayed.</small>
        </div>
      </Shell>
    );
  }
  return (
    <Shell
      {...shellProps}
      dashboard={dashboard.data}
    >
      {page === "demandForecast"
        ? (
          <DemandForecast
            dashboard={dashboard.data}
            storeId={storeId}
            onStoreId={setStoreId}
            channelType={channelType}
          />
        )
        : <DataManagement dashboard={dashboard.data} />}
    </Shell>
  );
}
