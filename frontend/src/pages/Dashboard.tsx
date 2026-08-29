import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchDashboardSummary } from "../api/client";
import KpiCard from "../components/KpiCard";
import SimulationBanner from "../components/SimulationBanner";
import { ErrorState, LoadingState } from "../components/States";
import type { DashboardSummary } from "../types/api";
import { formatInr, formatPercent } from "../utils/format";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchDashboardSummary()
      .then(setSummary)
      .catch((err) => setError(err.message ?? "Failed to load dashboard summary"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Dashboard</h1>
          <p className="text-sm text-slate-400">Revenue recovery overview — live from persisted attempts.</p>
        </div>
        <Link
          to="/payments"
          className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm font-medium text-accent hover:bg-accent/15"
        >
          View failed payments →
        </Link>
      </div>

      <SimulationBanner />

      {loading && <LoadingState label="Loading dashboard summary..." />}
      {error && <ErrorState message={error} onRetry={load} />}

      {summary && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard label="Revenue at Risk" value={formatInr(summary.revenue_at_risk_inr)} accent="atrisk" />
            <KpiCard
              label="Potentially Recoverable"
              value={formatInr(summary.potentially_recoverable_revenue_inr)}
              accent="pending"
            />
            <KpiCard label="Recovered Revenue" value={formatInr(summary.recovered_revenue_inr)} accent="recovered" />
            <KpiCard label="Recovery Rate" value={formatPercent(summary.recovery_rate)} />
          </div>

          <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-5">
            <KpiCard label="Failed Payments" value={String(summary.failed_payments)} />
            <KpiCard label="Automated Recoveries" value={String(summary.automated_recoveries)} accent="recovered" />
            <KpiCard label="Failed Recoveries" value={String(summary.failed_recoveries)} accent="atrisk" />
            <KpiCard label="Blocked" value={String(summary.blocked_recoveries)} accent="blocked" />
            <KpiCard label="Needs Approval" value={String(summary.pending_human_approval)} accent="pending" />
          </div>

          {summary.unprocessed_payments > 0 && (
            <div className="mt-6 rounded-xl border border-border bg-panel p-4">
              <p className="text-sm text-slate-300">
                <span className="font-mono font-semibold text-white">{summary.unprocessed_payments}</span> payment
                {summary.unprocessed_payments === 1 ? " has" : "s have"} not been run through the recovery workflow
                yet.{" "}
                <Link to="/payments?status=UNPROCESSED" className="text-accent hover:underline">
                  Review and trigger recovery →
                </Link>
              </p>
            </div>
          )}

          <div className="mt-8 rounded-xl border border-border bg-panel p-5">
            <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Recovery Workflow</p>
            <div className="flex flex-col gap-2 text-sm text-slate-400 md:flex-row md:items-center md:gap-0">
              {["Payment Failed", "Revenue Risk Detected", "ML Prediction", "AI Recommendation", "Safety Decision", "Execution / Approval / Block", "Result"].map(
                (step, i, arr) => (
                  <div key={step} className="flex items-center">
                    <span className="rounded-lg border border-border bg-panel2 px-3 py-1.5 text-xs font-medium text-slate-300">
                      {step}
                    </span>
                    {i < arr.length - 1 && <span className="mx-2 hidden text-slate-600 md:inline">→</span>}
                  </div>
                )
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
