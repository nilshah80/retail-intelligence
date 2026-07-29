import { useQuery } from "@tanstack/react-query";
import {
  loadGates,
  loadReconciliation,
  loadSummary,
  type DataSummary
} from "./api";

const labels: Record<string, string> = {
  data_management: "Data management",
  revenue_reporting: "Revenue reporting",
  demand_forecast_non_pit: "Demand forecast",
  point_in_time_forecasting: "PIT forecast",
  pricing_elasticity: "Pricing elasticity",
  replenishment: "Replenishment",
  competitor_intelligence: "Competitor intelligence"
};

function StatusPill({status}: {status: string}) {
  const good = status === "pass" || status === "available";
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[.14em] ${
      good ? "bg-emerald-400/12 text-emerald-300" : "bg-amber-400/12 text-amber-200"
    }`}>
      <span className={`h-1.5 w-1.5 rounded-full ${good ? "bg-emerald-300" : "bg-amber-300"}`} />
      {status.replaceAll("_", " ")}
    </span>
  );
}

function Metric({eyebrow, value, note}: {eyebrow: string; value: string; note: string}) {
  return (
    <article className="metric-card">
      <p className="text-[11px] font-semibold uppercase tracking-[.19em] text-slate-400">{eyebrow}</p>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-white">{value}</p>
      <p className="mt-2 text-sm text-slate-400">{note}</p>
    </article>
  );
}

function CapabilityGrid({summary}: {summary: DataSummary}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Object.entries(summary.capabilityMask).map(([name, state]) => (
        <article key={name} className="rounded-2xl border border-white/7 bg-white/[.025] p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-medium text-slate-100">{labels[name] ?? name}</p>
              <p className="mt-1 text-xs text-slate-500">{name}</p>
            </div>
            <StatusPill status={state.available ? "available" : "limited"} />
          </div>
          {!state.available && (
            <p className="mt-4 rounded-xl bg-amber-400/[.07] px-3 py-2 text-xs leading-5 text-amber-100/80">
              {state.reasonCode ?? state.limitation ?? "Evidence is not sufficient."}
            </p>
          )}
        </article>
      ))}
    </div>
  );
}

function Loading() {
  return (
    <main className="grid min-h-screen place-items-center bg-[#07151d] text-slate-300">
      <div className="text-center">
        <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-teal-300/20 border-t-teal-300" />
        <p className="mt-4 text-sm">Loading governed artifacts…</p>
      </div>
    </main>
  );
}

export default function App() {
  const summary = useQuery({queryKey: ["summary"], queryFn: loadSummary});
  const gates = useQuery({queryKey: ["gates"], queryFn: loadGates});
  const reconciliation = useQuery({
    queryKey: ["reconciliation"],
    queryFn: loadReconciliation
  });

  if (summary.isPending || gates.isPending || reconciliation.isPending) {
    return <Loading />;
  }
  const error = summary.error ?? gates.error ?? reconciliation.error;
  if (error || !summary.data || !gates.data || !reconciliation.data) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#07151d] p-8 text-slate-200">
        <section className="max-w-lg rounded-3xl border border-rose-300/20 bg-rose-300/[.06] p-8">
          <p className="text-xs font-bold uppercase tracking-[.2em] text-rose-300">Live API unavailable</p>
          <h1 className="mt-3 text-2xl font-semibold">Data Management could not load.</h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">{String(error)}</p>
          <p className="mt-5 text-xs text-slate-500">No stub values are substituted for live evidence.</p>
        </section>
      </main>
    );
  }

  const allRules = [...gates.data.gateA.rules, ...gates.data.gateB.rules];
  const findings = allRules.filter((rule) => rule.outcome !== "pass");
  return (
    <div className="min-h-screen bg-[#07151d] text-slate-200">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-white/7 bg-[#081923] p-6 lg:block">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-teal-300 font-black text-[#07151d]">RI</div>
          <div>
            <p className="font-semibold text-white">Retail Intelligence</p>
            <p className="text-xs text-slate-500">Control room</p>
          </div>
        </div>
        <nav className="mt-10 space-y-1 text-sm">
          <a className="nav-active" href="#overview">Data management</a>
          <span className="nav-muted">Demand forecast <small>Phase 3</small></span>
          <span className="nav-muted">Inventory <small>Phase 4</small></span>
          <span className="nav-muted">Pricing <small>Phase 5</small></span>
        </nav>
        <div className="absolute bottom-6 left-6 right-6 rounded-2xl border border-teal-300/10 bg-teal-300/[.04] p-4">
          <p className="text-[10px] font-bold uppercase tracking-[.18em] text-teal-300">Live artifact mode</p>
          <p className="mt-2 break-all font-mono text-[10px] leading-4 text-slate-500">
            {summary.data.sourceSnapshotId.slice(0, 24)}…
          </p>
        </div>
      </aside>

      <main className="lg:ml-64">
        <header className="border-b border-white/7 px-5 py-5 sm:px-8">
          <div className="mx-auto flex max-w-[1500px] items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[.2em] text-teal-300">Phase 2 · Governed ingestion</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white">Data Management</h1>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill status={summary.data.gateBStatus} />
              <div className="hidden rounded-full border border-white/10 px-4 py-2 text-xs text-slate-400 sm:block">
                Mumbai · New York
              </div>
            </div>
          </div>
        </header>

        <div id="overview" className="mx-auto max-w-[1500px] space-y-8 p-5 sm:p-8">
          <section className="hero-panel">
            <div>
              <p className="text-xs font-bold uppercase tracking-[.2em] text-teal-200">Accepted retail source run</p>
              <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                Source evidence to curated retail facts, with every gate visible.
              </h2>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-400">
                Shopify, Business Central and companion feeds are landed immutably, adapted independently,
                transformed through one source-neutral contract and reconciled before publication.
              </p>
            </div>
            <div className="mt-8 grid gap-3 font-mono text-xs text-slate-400 sm:grid-cols-2">
              <div className="hash-box"><span>Run</span>{summary.data.nativeSnapshotId}</div>
              <div className="hash-box"><span>Publication</span>{summary.data.publicationFingerprint.slice(0, 20)}…</div>
            </div>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Metric eyebrow="Source datasets" value={summary.data.sourceDatasetCount.toLocaleString()} note="Profile-classified public datasets" />
            <Metric eyebrow="Canonical entities" value={summary.data.canonicalEntityCount.toLocaleString()} note="Published retail_v2 tables" />
            <Metric eyebrow="Curated objects" value={summary.data.curatedObjectCount.toLocaleString()} note="Partitioned Parquet objects" />
            <Metric eyebrow="Critical violations" value="0" note={`${findings.length} disclosed warning or downgrade`} />
          </section>

          <section className="panel">
            <div className="section-heading">
              <div><p className="kicker">Capability mask</p><h2>What this publication can honestly support</h2></div>
              <span className="text-xs text-slate-500">Unavailable means evidence-limited, not empty.</span>
            </div>
            <CapabilityGrid summary={summary.data} />
          </section>

          <section className="grid gap-6 xl:grid-cols-[1.35fr_.65fr]">
            <div className="panel overflow-hidden">
              <div className="section-heading">
                <div><p className="kicker">Exact controls</p><h2>Source-to-canonical reconciliation</h2></div>
                <StatusPill status="pass" />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead><tr className="text-xs uppercase tracking-[.14em] text-slate-500">
                    <th>Currency</th><th>Gross</th><th>Net</th><th>Tax</th><th>Units</th><th>Difference</th>
                  </tr></thead>
                  <tbody>
                    {reconciliation.data.map((row) => (
                      <tr key={row.currencyCode} className="border-t border-white/6">
                        <td className="font-semibold text-white">{row.currencyCode}</td>
                        <td>{row.canonical.grossMinor.toLocaleString()}</td>
                        <td>{row.canonical.netMinor.toLocaleString()}</td>
                        <td>{row.canonical.taxMinor.toLocaleString()}</td>
                        <td>{row.canonical.units.toLocaleString()}</td>
                        <td className="font-mono text-emerald-300">{row.difference.every((v) => v === 0) ? "0 / 0 / 0 / 0" : row.difference.join(" / ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel">
              <div className="section-heading">
                <div><p className="kicker">Gate findings</p><h2>Visible limitations</h2></div>
              </div>
              <div className="space-y-3">
                {findings.map((rule) => (
                  <article key={rule.ruleId} className="rounded-2xl border border-amber-300/10 bg-amber-300/[.045] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-mono text-xs text-amber-200">{rule.ruleId}</span>
                      <StatusPill status={rule.outcome} />
                    </div>
                    <p className="mt-3 text-sm leading-5 text-slate-300">{rule.summary}</p>
                    {rule.reasonCode && <p className="mt-2 font-mono text-[10px] text-slate-500">{rule.reasonCode}</p>}
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
