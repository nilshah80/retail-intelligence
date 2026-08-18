import {useEffect, useMemo, useRef, useState, type ReactNode} from "react";
import {useQuery} from "@tanstack/react-query";
import {
  loadDashboard,
  loadForecastSummary,
  loadFx,
  type Dashboard,
  type FxRates
} from "./api";
import {DemandForecast} from "./Forecast";
import {ExecutiveOverview} from "./ExecutiveOverview";
import {InventoryPage, inventoryScreens, type InventoryPageId} from "./Inventory";
import {
  PricingPage,
  pricingScreens,
  type PricingPageId
} from "./Pricing";

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

const currencyOrder = ["INR", "USD", "EUR", "GBP", "AED"] as const;

const primaryNavigation = [
  {
    icon: "⌂",
    label: "Executive Overview"
  }
];

const pricingNavigation = [
  {icon: "🏷", label: "Price Recommendations"},
  {icon: "◫", label: "Price Simulation"},
  {icon: "◉", label: "Competitor Monitor"},
  {icon: "▣", label: "Promotion Planner"}
];

/**
 * Every addressable destination. A nav item that cannot be reached is
 * decoration, so the union is the navigation's source of truth and the label
 * maps below are derived from it rather than duplicated.
 */
export type PageId =
  | "overview"
  | "demandForecast"
  | "dataManagement"
  | InventoryPageId
  | PricingPageId;

const pricingPageIds: PricingPageId[] = [
  "priceRecommendations", "priceSimulation", "competitorMonitor", "promotionPlanner"
];

const inventoryPageIds: InventoryPageId[] = [
  "inventoryOverview", "storeInventory", "warehouseInventory",
  "inventoryAgeing", "inventoryTransfers", "inventoryValuation",
  "expiryWaste", "replenishmentPlanner", "suggestedOrders",
  "supplierPlanning", "safetyStock", "allocationFulfillment",
  "replenishmentExceptions", "stockHealth"
];

export function isPageId(value: string | null): value is PageId {
  if (value === "overview" || value === "demandForecast" || value === "dataManagement") return true;
  if (pricingPageIds.includes(value as PricingPageId)) return true;
  return inventoryPageIds.includes(value as InventoryPageId);
}

function isPricingPage(page: PageId): page is PricingPageId {
  return pricingPageIds.includes(page as PricingPageId);
}

export function pageTitle(page: PageId): string {
  if (page === "overview") return "Executive Overview";
  if (page === "demandForecast") return "Demand Forecast";
  if (page === "dataManagement") return "Data Management";
  if (isPricingPage(page)) return pricingScreens[page].title;
  return inventoryScreens[page].title;
}

export function pageSubtitle(page: PageId): string {
  if (page === "overview") {
    return "Real-time snapshot of pricing, demand and inventory performance";
  }
  if (page === "demandForecast") {
    return "Forecast demand by SKU, store, channel and time";
  }
  if (page === "dataManagement") {
    return "Monitor source systems, data freshness and data quality";
  }
  if (isPricingPage(page)) return pricingScreens[page].subtitle;
  return inventoryScreens[page].subtitle;
}

/** Nav label -> destination, keyed off the same table the parity contract uses. */
const pageByNavLabel: Record<string, PageId> = Object.fromEntries(
  [
    ...pricingPageIds.map((id) => [pricingScreens[id].title, id] as const),
    ...inventoryPageIds.map((id) => [
    // "Exceptions" is the nav label the reference HTML uses for the
    // replenishment exceptions destination; every other label matches its title.
    id === "replenishmentExceptions" ? "Exceptions" : inventoryScreens[id].title,
    id
    ] as const)
  ]
) as Record<string, PageId>;

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
  {icon: "⌁", label: "Performance Insights", disabled: true, reason: "A governed performance-insights route is not available."},
  {icon: "□", label: "Reports & Exports", disabled: true, reason: "A governed reports-and-exports route is not available."},
  {icon: "♢", label: "Alerts & Notifications", disabled: true, reason: "A governed alerts-and-notifications route is not available."}
];

const adminNavigation = [
  {icon: "▦", label: "Data Management"},
  {icon: "⚙", label: "Model Management", disabled: true, reason: "A governed model-management route is not available."},
  {icon: "♙", label: "User Management", disabled: true, reason: "Authenticated identity and user-management authority are not available."},
  {icon: "☼", label: "Settings", disabled: true, reason: "A governed settings route is not available."}
];

function NavItem({
  icon,
  label,
  active = false,
  onClick,
  disabled = false,
  reason
}: {
  icon: string;
  label: string;
  active?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  reason?: string;
}) {
  return (
    <button
      className={`nav-item${active ? " active" : ""}`}
      type="button"
      data-nav-label={label}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      disabled={disabled}
      title={disabled ? reason : undefined}
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
  items: Array<{icon: string; label: string; disabled?: boolean; reason?: string}>;
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
          onClick={item.disabled ? undefined : () => onSelect?.(item.label)}
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
  page: PageId;
  onPage: (page: PageId) => void;
}) {
  const inventoryChildren: PageId[] = [
    "storeInventory", "warehouseInventory", "inventoryAgeing",
    "inventoryTransfers", "inventoryValuation", "expiryWaste"
  ];
  const replenishmentChildren: PageId[] = [
    "suggestedOrders", "supplierPlanning", "safetyStock",
    "allocationFulfillment", "replenishmentExceptions"
  ];
  const [inventoryOpen, setInventoryOpen] = useState(
    () => page === "inventoryOverview" || inventoryChildren.includes(page)
  );
  const [replenishmentOpen, setReplenishmentOpen] = useState(
    () => page === "replenishmentPlanner" || replenishmentChildren.includes(page)
  );
  // Keep the group containing the active destination expanded. Without this a
  // deep link highlights a nav item inside a collapsed submenu.
  useEffect(() => {
    if (page === "inventoryOverview" || inventoryChildren.includes(page)) {
      setInventoryOpen(true);
    }
    if (page === "replenishmentPlanner" || replenishmentChildren.includes(page)) {
      setReplenishmentOpen(true);
    }
  }, [page]);
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">🛒</div>
        <div>
          <h1>AI Retail Intelligence</h1>
          <p>Dynamic Pricing &amp;<br />Demand Forecasting</p>
        </div>
      </div>
      {primaryNavigation.map((item) => (
        <NavItem
          key={item.label}
          {...item}
          active={page === "overview"}
          onClick={() => onPage("overview")}
        />
      ))}
      <NavigationSection
        title="PRICING"
        items={pricingNavigation}
        activeLabel={isPricingPage(page) ? pageTitle(page) : undefined}
        onSelect={(label) => {
          const target = pageByNavLabel[label];
          if (target) onPage(target);
        }}
      />

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
          onToggle={() => {
            setInventoryOpen((value) => !value);
            onPage("inventoryOverview");
          }}
        >
          {inventoryNavigation.map((item) => (
            <NavItem
              key={item.label}
              {...item}
              active={page === pageByNavLabel[item.label]}
              onClick={() => {
                const target = pageByNavLabel[item.label];
                if (target) onPage(target);
              }}
            />
          ))}
        </NavigationParent>
        <NavigationParent
          icon="⇄"
          label="Replenishment Planner"
          open={replenishmentOpen}
          onToggle={() => {
            setReplenishmentOpen((value) => !value);
            onPage("replenishmentPlanner");
          }}
        >
          {replenishmentNavigation.map((item) => (
            <NavItem
              key={item.label}
              {...item}
              active={page === pageByNavLabel[item.label]}
              onClick={() => {
                const target = pageByNavLabel[item.label];
                if (target) onPage(target);
              }}
            />
          ))}
        </NavigationParent>
        <NavItem
          icon="◇"
          label="Stock Health"
          active={page === "stockHealth"}
          onClick={() => onPage("stockHealth")}
        />
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
      <div className="sidebar-user" aria-label="User identity unavailable">
        <div className="sidebar-user-avatar" aria-hidden="true">—</div>
        <div>
          <strong>Identity unavailable</strong>
          <span>Authentication not configured</span>
        </div>
      </div>
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
  onFx: (trigger: HTMLElement) => void;
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
        <h2 id="page-heading" tabIndex={-1}>{title}</h2>
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
          ) : "Authority decision window"}
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
          disabled={!dashboard}
          title={!dashboard ? "Currency authority is loading." : undefined}
          onChange={(event) => onCurrency(event.target.value)}
        >
          {currencyOrder.map((code) => (
            <option
              key={code}
              value={code}
              disabled={!dashboard || !dashboard.filters.currencies.includes(code)}
            >
              {currencySymbols[code] ?? ""} {code}
            </option>
          ))}
        </select>
        <button
          className="filter"
          type="button"
          title="Currency settings"
          onClick={(event) => onFx(event.currentTarget)}
        >
          FX
        </button>
        <button
          className="filter icon-button"
          type="button"
          aria-label="Notifications"
          disabled
          title="A governed notification source is not available."
        >🔔</button>
      </div>
    </header>
  );
}

function FxModal({
  open,
  fx,
  pending,
  error,
  returnFocus,
  onClose
}: {
  open: boolean;
  fx?: FxRates;
  pending: boolean;
  error: Error | null;
  returnFocus: HTMLElement | null;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open) return;
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
  }, [open, returnFocus]);

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
        aria-labelledby="fx-modal-title"
        aria-modal="true"
        className="modal"
        role="dialog"
      >
        <div className="modal-head">
          <h3 ref={titleRef} id="fx-modal-title" tabIndex={-1}>Multi-Currency Configuration</h3>
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

function SourceTable({
  sources,
  onValidation
}: {
  sources: SourceRow[];
  onValidation: (source: SourceRow, trigger: HTMLElement) => void;
}) {
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
                onValidation={onValidation}
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
  onToggle,
  onValidation
}: {
  source: SourceRow;
  selected: boolean;
  onToggle: () => void;
  onValidation: (source: SourceRow, trigger: HTMLElement) => void;
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
            <button
              className="link-button"
              type="button"
              onClick={(event) => onValidation(source, event.currentTarget)}
            >Validation Results</button>
          </td>
        </tr>
      )}
    </>
  );
}

function DataManagementDialog({
  kind,
  source,
  returnFocus,
  onClose
}: {
  kind: "add" | "validation";
  source?: SourceRow;
  returnFocus: HTMLElement | null;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  const title = kind === "add" ? "Add Data Source" : "Validation Results";
  const titleId = `data-management-dialog-${kind}`;
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
  const unavailableValidation = (
    <span className="cell-unavailable" title="The retained source summary does not publish this validation measure.">Not available</span>
  );
  return (
    <div className="modal-backdrop open" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={containerRef} className="modal pricing-modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="modal-head">
          <div>
            <h3 ref={titleRef} id={titleId} tabIndex={-1}>{title}</h3>
            {kind === "validation" && <p>{source?.name ?? "Selected source"}</p>}
          </div>
          <button className="modal-close" type="button" aria-label={`Close ${title}`} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {kind === "add" ? (
            <>
              <div className="callout compact-callout"><strong>Connection unavailable</strong><p>Source connection authority is not configured. These local choices do not contact or register a source.</p></div>
              <div className="pricing-form-grid two">
                <div className="pricing-field"><label><span>Source Name</span><input className="filter" readOnly aria-readonly="true" /></label></div>
                <div className="pricing-field"><label><span>Type</span><select className="filter" defaultValue="API"><option>API</option><option>Database</option><option>SFTP</option><option>CSV</option></select></label></div>
                <div className="pricing-field"><label><span>Refresh</span><select className="filter" defaultValue="15 minutes"><option>15 minutes</option><option>Hourly</option><option>Daily</option></select></label></div>
              </div>
            </>
          ) : (
            <div className="simulation-metrics">
              <div><small>Quality</small><strong>{source ? formatPct(source.qualityPct) : unavailableValidation}</strong></div>
              <div><small>Valid</small><strong>{unavailableValidation}</strong></div>
              <div><small>Duplicates</small><strong>{unavailableValidation}</strong></div>
              <div><small>Missing</small><strong>{unavailableValidation}</strong></div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          {kind === "add" ? (
            <>
              <button className="modal-action" type="button" disabled title="Source connection authority is not configured.">Connect</button>
              <button className="filter" type="button" onClick={onClose}>Cancel</button>
            </>
          ) : (
            <button className="modal-action" type="button" onClick={onClose}>Close</button>
          )}
        </div>
      </section>
    </div>
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
  page: PageId;
  onPage: (page: PageId) => void;
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
  const fxTrigger = useRef<HTMLElement | null>(null);
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
          title={pageTitle(page)}
          subtitle={pageSubtitle(page)}
          storeId={storeId}
          onStoreId={onStoreId}
          channelType={channelType}
          onChannelType={onChannelType}
          currency={activeCurrency}
          onCurrency={setCurrency}
          onFx={(trigger) => {
            fxTrigger.current = trigger;
            setFxOpen(true);
          }}
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
              {page === "overview"
                ? "Executive monetary values use the accepted reporting currency; source coverage and calculation bases are disclosed with each measure."
                : page === "demandForecast"
                ? "Demand Forecast currently presents units and percentages; no live monetary measure is converted."
                : isPricingPage(page)
                  ? "Operating prices and aggregates remain in the governed display currency; currencies without retained FX evidence stay disabled."
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
        returnFocus={fxTrigger.current}
        onClose={() => setFxOpen(false)}
      />
    </div>
  );
}

function DataManagement({dashboard}: {dashboard: Dashboard}) {
  const [dialog, setDialog] = useState<"add" | "validation" | null>(null);
  const [validationSource, setValidationSource] = useState<SourceRow | undefined>();
  const dialogTrigger = useRef<HTMLElement | null>(null);
  return (
    <div id="dataManagement">
      <div className="action-toolbar" aria-label="Data Management actions">
        <button
          id="addDataSourceBtn"
          className="btn primary"
          type="button"
          onClick={(event) => {
            dialogTrigger.current = event.currentTarget;
            setDialog("add");
          }}
        >Add Data Source</button>
        <button className="btn secondary" type="button" disabled title="A governed sample-upload workflow and accepted file contract are not configured.">Upload Sample Data</button>
        <button className="btn secondary" type="button" disabled title="A governed validation execution workflow is not configured.">Run Validation</button>
      </div>
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
      <SourceTable
        sources={dashboard.sources}
        onValidation={(source, trigger) => {
          dialogTrigger.current = trigger;
          setValidationSource(source);
          setDialog("validation");
        }}
      />
      {dialog && (
        <DataManagementDialog
          kind={dialog}
          source={validationSource}
          returnFocus={dialogTrigger.current}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

export default function App() {
  const initialPage = new URLSearchParams(window.location.search).get("page");
  const [page, setPage] = useState<PageId>(
    isPageId(initialPage) ? initialPage : "overview"
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
    queryFn: ({signal}) => loadForecastSummary(signal),
    // The global footer's Forecast Coverage and Model Accuracy KPIs are portfolio
    // metrics shown on every page, so the summary that feeds them loads on every
    // page rather than the Demand Forecast page alone.
    enabled: true
  });
  // The tab label follows the destination. index.html hard-codes "Data
  // Management" and nothing ever updated it, so every tab claimed to be that page
  // regardless of what it showed. With sixteen destinations and several tabs open
  // that is not cosmetic: the tab strip is how someone finds the window they
  // want, and all of them read the same.
  useEffect(() => {
    document.title = `Retail Intelligence · ${pageTitle(page)}`;
    const heading = document.getElementById("page-heading");
    heading?.focus({preventScroll: true});
  }, [page]);
  useEffect(() => {
    if (!isPageId(initialPage)) {
      const normalized = new URL(window.location.href);
      normalized.searchParams.set("page", "overview");
      normalized.hash = "";
      window.history.replaceState({page: "overview"}, "", normalized);
    }
    const restorePage = () => {
      const requested = new URLSearchParams(window.location.search).get("page");
      const restored: PageId = isPageId(requested) ? requested : "overview";
      if (!isPageId(requested)) {
        const normalized = new URL(window.location.href);
        normalized.searchParams.set("page", restored);
        normalized.hash = "";
        window.history.replaceState({page: restored}, "", normalized);
      }
      setPage(restored);
      document.getElementById("page-heading")?.focus({preventScroll: true});
    };
    window.addEventListener("popstate", restorePage);
    return () => window.removeEventListener("popstate", restorePage);
  }, []);
  const changePage = (nextPage: PageId) => {
    if (nextPage === page) {
      document.getElementById("page-heading")?.focus({preventScroll: true});
      return;
    }
    setPage(nextPage);
    const url = new URL(window.location.href);
    url.searchParams.set("page", nextPage);
    url.hash = "";
    window.history.pushState({page: nextPage}, "", url);
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

  if (!isPricingPage(page) && dashboard.isPending) {
    return (
      <Shell {...shellProps}>
        <div className="state-card">Loading live retail data…</div>
      </Shell>
    );
  }
  if (!isPricingPage(page) && (dashboard.error || !dashboard.data)) {
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
      {page === "overview" ? (
        <ExecutiveOverview
          dashboard={dashboard.data!}
          storeId={storeId}
          channelType={channelType}
          forecastSummary={forecastSummary.data}
          forecastSummaryPending={forecastSummary.isPending}
          forecastSummaryError={forecastSummary.error}
          onNavigate={(target) => changePage(target)}
        />
      ) : isPricingPage(page) ? (
        <PricingPage
          pageId={page}
          dashboard={dashboard.data}
          storeId={storeId}
          onStoreId={setStoreId}
          channelType={channelType}
          onNavigate={changePage}
        />
      ) : page === "demandForecast" ? (
        <DemandForecast
          dashboard={dashboard.data!}
          storeId={storeId}
          onStoreId={setStoreId}
          channelType={channelType}
        />
      ) : page === "dataManagement" ? (
        <DataManagement dashboard={dashboard.data!} />
      ) : (
        <InventoryPage pageId={page} />
      )}
    </Shell>
  );
}
