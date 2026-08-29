import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchPayments, triggerRecovery } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import type { PaymentListItem } from "../types/api";
import { formatDateTime, formatInr } from "../utils/format";

const STATUS_FILTERS = ["", "UNPROCESSED", "SUCCESS", "FAILED", "BLOCKED", "PENDING_HUMAN_APPROVAL"];

export default function FailedPayments() {
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status") ?? "";
  const search = searchParams.get("search") ?? "";
  const sortBy = (searchParams.get("sort_by") as "created_at" | "amount" | "transaction_id") ?? "created_at";
  const sortDir = (searchParams.get("sort_dir") as "asc" | "desc") ?? "desc";

  const [items, setItems] = useState<PaymentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(search);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchPayments({ status: status || undefined, search: search || undefined, sortBy, sortDir, limit: 100 })
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message ?? "Failed to load payments"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [status, search, sortBy, sortDir]);

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  };

  const handleTrigger = async (transactionId: string) => {
    setTriggering(transactionId);
    try {
      await triggerRecovery(transactionId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to trigger recovery");
    } finally {
      setTriggering(null);
    }
  };

  const toggleSort = (field: "created_at" | "amount" | "transaction_id") => {
    if (sortBy === field) {
      updateParam("sort_dir", sortDir === "asc" ? "desc" : "asc");
    } else {
      const next = new URLSearchParams(searchParams);
      next.set("sort_by", field);
      next.set("sort_dir", "desc");
      setSearchParams(next);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-white">Failed Payments</h1>
        <p className="text-sm text-slate-400">{total} transaction{total === 1 ? "" : "s"} on record.</p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            updateParam("search", searchInput);
          }}
          className="flex items-center gap-2"
        >
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search transaction or customer ID"
            className="w-64 rounded-lg border border-border bg-panel px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-accent focus:outline-none"
          />
        </form>

        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s || "ALL"}
              onClick={() => updateParam("status", s)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                status === s
                  ? "border-accent/40 bg-accent/15 text-accent"
                  : "border-border text-slate-400 hover:text-slate-200"
              }`}
            >
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {loading && <LoadingState label="Loading payments..." />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && items.length === 0 && (
        <EmptyState title="No payments match these filters" description="Try clearing the search or status filter." />
      )}

      {!loading && !error && items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border bg-panel">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-slate-500">
                <SortableHeader label="Transaction" field="transaction_id" sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3 font-medium">Customer</th>
                <SortableHeader label="Amount" field="amount" sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} align="right" />
                <th className="px-4 py-3 font-medium">Method</th>
                <th className="px-4 py-3 font-medium">Failure Reason</th>
                <th className="px-4 py-3 font-medium">Probability</th>
                <th className="px-4 py-3 font-medium">Requested Action</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.transaction_id} className="border-b border-border/60 last:border-0 hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <Link to={`/payments/${item.transaction_id}`} className="font-mono text-xs text-accent hover:underline">
                      {item.transaction_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">{item.customer_id}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-200">{formatInr(item.amount)}</td>
                  <td className="px-4 py-3 text-slate-400">{item.payment_method}</td>
                  <td className="px-4 py-3 text-slate-400">{item.failure_reason ?? "—"}</td>
                  <td className="px-4 py-3 font-mono text-slate-300">
                    {item.recovery_probability !== null ? `${(item.recovery_probability * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">{item.requested_action ?? "—"}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {item.status === "UNPROCESSED" ? (
                      <button
                        onClick={() => handleTrigger(item.transaction_id)}
                        disabled={triggering === item.transaction_id}
                        className="rounded-lg border border-accent/30 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent hover:bg-accent/15 disabled:opacity-50"
                      >
                        {triggering === item.transaction_id ? "Running..." : "Trigger recovery"}
                      </button>
                    ) : (
                      <Link to={`/payments/${item.transaction_id}`} className="text-xs text-slate-500 hover:text-slate-300">
                        View →
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-border px-4 py-2 text-right text-[11px] text-slate-500">
            {formatDateTime(new Date().toISOString())} · showing {items.length} of {total}
          </div>
        </div>
      )}
    </div>
  );
}

function SortableHeader({
  label,
  field,
  sortBy,
  sortDir,
  onSort,
  align = "left",
}: {
  label: string;
  field: "created_at" | "amount" | "transaction_id";
  sortBy: string;
  sortDir: string;
  onSort: (field: "created_at" | "amount" | "transaction_id") => void;
  align?: "left" | "right";
}) {
  const active = sortBy === field;
  return (
    <th className={`px-4 py-3 font-medium ${align === "right" ? "text-right" : "text-left"}`}>
      <button onClick={() => onSort(field)} className={`inline-flex items-center gap-1 hover:text-slate-300 ${active ? "text-slate-300" : ""}`}>
        {label}
        {active && <span>{sortDir === "asc" ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}
