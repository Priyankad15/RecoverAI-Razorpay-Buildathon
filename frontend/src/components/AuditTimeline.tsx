import type { AuditEvent } from "../types/api";
import { formatDateTime } from "../utils/format";
import StatusBadge from "./StatusBadge";

const EVENT_LABELS: Record<string, string> = {
  RECOVERY_RECOMMENDED: "Recovery recommended",
  RECOVERY_BLOCKED: "Recovery blocked",
  RECOVERY_APPROVAL_REQUIRED: "Human approval required",
  RECOVERY_EXECUTED: "Recovery executed",
  RECOVERY_FAILED: "Recovery failed",
  RECOVERY_COMPLETED: "Recovery completed",
  RAZORPAY_PAYMENT_LINK_CREATED: "Razorpay Payment Link created",
  RAZORPAY_PAYMENT_CONFIRMED: "Razorpay payment confirmed",
  RAZORPAY_PAYMENT_FAILED: "Razorpay payment not completed",
};

export default function AuditTimeline({ events, showTransactionId = false }: { events: AuditEvent[]; showTransactionId?: boolean }) {
  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-slate-500">
        No audit events yet. Trigger recovery on a transaction to generate a trail.
      </div>
    );
  }

  return (
    <ol className="relative space-y-4 border-l border-border pl-5">
      {events.map((event, index) => (
        <li key={`${event.timestamp}-${index}`} className="relative">
          <span className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full border-2 border-ink bg-accent" />
          <div className="rounded-lg border border-border bg-panel p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-white">{EVENT_LABELS[event.event_type] ?? event.event_type}</p>
                {showTransactionId && event.transaction_id && (
                  <span className="font-mono text-xs text-slate-500">{event.transaction_id}</span>
                )}
              </div>
              <span className="font-mono text-xs text-slate-500">{formatDateTime(event.timestamp)}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {event.requested_action && (
                <span className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                  {event.requested_action}
                </span>
              )}
              {event.rules_decision && <StatusBadge status={event.rules_decision} />}
              {event.execution_status && <StatusBadge status={event.execution_status} />}
            </div>
            {event.explanation && <p className="mt-2 text-sm text-slate-300">{event.explanation}</p>}
            {event.reason_codes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {event.reason_codes.map((code) => (
                  <span key={code} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[10px] text-slate-500">
                    {code}
                  </span>
                ))}
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
