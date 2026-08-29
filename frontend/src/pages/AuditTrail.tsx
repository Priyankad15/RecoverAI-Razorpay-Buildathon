import { useEffect, useState } from "react";

import { fetchAuditTrail } from "../api/client";
import AuditTimeline from "../components/AuditTimeline";
import { ErrorState, LoadingState } from "../components/States";
import type { AuditEvent } from "../types/api";

export default function AuditTrail() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchAuditTrail()
      .then((data) => setEvents([...data].reverse())) // API returns newest-first; show chronological, newest last within page
      .catch((err) => setError(err.message ?? "Failed to load audit trail"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Audit Trail</h1>
          <p className="text-sm text-slate-400">Every recovery decision event, across all transactions.</p>
        </div>
        <button
          onClick={load}
          className="rounded-lg border border-border px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
        >
          Refresh
        </button>
      </div>

      {loading && <LoadingState label="Loading audit events..." />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && <AuditTimeline events={events} showTransactionId />}
    </div>
  );
}
