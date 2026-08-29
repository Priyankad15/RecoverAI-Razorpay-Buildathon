import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchAnalytics } from "../api/client";
import KpiCard from "../components/KpiCard";
import { ErrorState, LoadingState } from "../components/States";
import type { AnalyticsResponse } from "../types/api";
import { formatInr, formatPercent } from "../utils/format";

const STATUS_COLORS: Record<string, string> = {
  SUCCESS: "#33C48D",
  FAILED: "#F2A649",
  BLOCKED: "#E5484D",
  PENDING_HUMAN_APPROVAL: "#8B7FF2",
  COMPLETED: "#4F8AF4",
  NOT_EXECUTED: "#64748B",
  UNPROCESSED: "#475569",
};

export default function Analytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchAnalytics()
      .then(setData)
      .catch((err) => setError(err.message ?? "Failed to load analytics"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-white">Analytics</h1>
        <p className="text-sm text-slate-400">Computed live from persisted recovery attempts.</p>
      </div>

      {loading && <LoadingState label="Loading analytics..." />}
      {error && <ErrorState message={error} onRetry={load} />}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard label="Revenue at Risk" value={formatInr(data.summary.revenue_at_risk_inr)} accent="atrisk" />
            <KpiCard
              label="Potentially Recoverable"
              value={formatInr(data.summary.potentially_recoverable_revenue_inr)}
              accent="pending"
            />
            <KpiCard label="Recovered Revenue" value={formatInr(data.summary.recovered_revenue_inr)} accent="recovered" />
            <KpiCard label="Recovery Rate" value={formatPercent(data.summary.recovery_rate)} />
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-panel p-5">
              <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Outcome Breakdown
              </p>
              {Object.keys(data.status_breakdown).length === 0 ? (
                <p className="py-10 text-center text-sm text-slate-500">No processed transactions yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={Object.entries(data.status_breakdown).map(([status, count]) => ({ status, count }))}
                      dataKey="count"
                      nameKey="status"
                      innerRadius={55}
                      outerRadius={90}
                      paddingAngle={2}
                    >
                      {Object.keys(data.status_breakdown).map((status) => (
                        <Cell key={status} fill={STATUS_COLORS[status] ?? "#64748B"} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "#101B2D", border: "1px solid #1E2C45", borderRadius: 8, fontSize: 12 }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
              <div className="mt-3 flex flex-wrap gap-3">
                {Object.entries(data.status_breakdown).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLORS[status] ?? "#64748B" }} />
                    {status} ({count})
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-border bg-panel p-5">
              <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Failure Reasons
              </p>
              {Object.keys(data.failure_reason_breakdown).length === 0 ? (
                <p className="py-10 text-center text-sm text-slate-500">No data yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    data={Object.entries(data.failure_reason_breakdown).map(([reason, count]) => ({ reason, count }))}
                    layout="vertical"
                    margin={{ left: 24 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E2C45" horizontal={false} />
                    <XAxis type="number" stroke="#64748B" fontSize={11} allowDecimals={false} />
                    <YAxis type="category" dataKey="reason" stroke="#64748B" fontSize={11} width={110} />
                    <Tooltip
                      contentStyle={{ background: "#101B2D", border: "1px solid #1E2C45", borderRadius: 8, fontSize: 12 }}
                      cursor={{ fill: "rgba(255,255,255,0.03)" }}
                    />
                    <Bar dataKey="count" fill="#4F8AF4" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="mt-6 rounded-xl border border-border bg-panel p-5">
            <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Top Reason Codes
            </p>
            {Object.keys(data.top_reason_codes).length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No decisions recorded yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.top_reason_codes).map(([code, count]) => (
                  <span
                    key={code}
                    className="rounded-lg border border-border bg-panel2 px-3 py-1.5 font-mono text-xs text-slate-300"
                  >
                    {code} <span className="text-slate-500">×{count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
