import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchPaymentDetail, triggerRecovery } from "../api/client";
import AgentVsRules from "../components/AgentVsRules";
import AuditTimeline from "../components/AuditTimeline";
import ExecutionModeBadge from "../components/ExecutionModeBadge";
import SimulationBanner from "../components/SimulationBanner";
import StatusBadge from "../components/StatusBadge";
import { ErrorState, LoadingState } from "../components/States";
import type { PaymentDetail } from "../types/api";
import { formatDateTime, formatInr } from "../utils/format";

export default function TransactionDetail() {
  const { transactionId } = useParams<{ transactionId: string }>();
  const [detail, setDetail] = useState<PaymentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  const load = () => {
    if (!transactionId) return;
    setLoading(true);
    setError(null);
    fetchPaymentDetail(transactionId)
      .then(setDetail)
      .catch((err) => setError(err.message ?? "Failed to load transaction"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [transactionId]);

  const handleTrigger = async () => {
    if (!transactionId) return;
    setTriggering(true);
    try {
      await triggerRecovery(transactionId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to trigger recovery");
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div>
      <Link to="/payments" className="text-xs text-slate-500 hover:text-slate-300">
        ← Back to Failed Payments
      </Link>

      {loading && <LoadingState label="Loading transaction..." />}
      {error && <ErrorState message={error} onRetry={load} />}

      {detail && (
        <>
          <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="font-mono text-xl font-semibold text-white">{detail.transaction_id}</h1>
              <p className="text-sm text-slate-400">Customer: {detail.customer_id}</p>
            </div>
            <StatusBadge status={detail.status} />
          </div>

          <SimulationBanner />

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCard label="Amount" value={formatInr(detail.amount)} />
            <InfoCard label="Payment Method" value={detail.payment_method} />
            <InfoCard label="Failure Reason" value={detail.failure_reason ?? "—"} />
            <InfoCard label="Filed" value={formatDateTime(detail.created_at)} />
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCard label="Previous Transactions" value={String(detail.previous_transactions)} />
            <InfoCard label="Previous Success Rate" value={`${(detail.previous_success_rate * 100).toFixed(0)}%`} />
            <InfoCard label="Customer Type" value={detail.customer_type ?? "—"} />
            <InfoCard label="Subscription Status" value={detail.subscription_status ?? "—"} />
          </div>

          <div className="mt-8">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Recovery Decision
            </p>

            {detail.latest_attempt ? (
              <>
                <AgentVsRules
                  recoveryProbability={detail.latest_attempt.recovery_probability}
                  agentAction={detail.latest_attempt.requested_action ?? "—"}
                  agentConfidence={detail.latest_attempt.agent_confidence ?? 0}
                  agentExplanation={detail.latest_attempt.agent_explanation ?? ""}
                  agentReasonCodes={[]}
                  rulesDecision={detail.latest_attempt.rules_decision ?? "—"}
                  rulesReasonCodes={[]}
                  rulesExplanation=""
                  executionStatus={detail.latest_attempt.execution_status ?? "—"}
                />

                <div className="mt-4 rounded-xl border border-border bg-panel p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Execution Result
                    </p>
                    <ExecutionModeBadge mode={detail.latest_attempt.execution_mode} />
                  </div>
                  <div className="flex flex-wrap items-center gap-4 text-sm">
                    <span>
                      Recovered amount:{" "}
                      <span className="font-mono font-semibold text-recovered">
                        {formatInr(detail.latest_attempt.recovered_amount ?? 0)}
                      </span>
                    </span>
                    {detail.latest_attempt.failure_reason && (
                      <span className="text-slate-400">Failure: {detail.latest_attempt.failure_reason}</span>
                    )}
                    <span className="text-slate-500">
                      Completed:{" "}
                      {detail.latest_attempt.completed_at ? formatDateTime(detail.latest_attempt.completed_at) : "—"}
                    </span>
                  </div>

                  {detail.latest_attempt.execution_mode === "RAZORPAY_TEST_MODE" && (
                    <div className="mt-3 rounded-lg border border-accent/20 bg-accent/5 p-3">
                      <p className="text-xs font-medium text-accent">
                        Razorpay Test Mode Payment Link {detail.latest_attempt.recovered_amount ? "confirmed" : "created"}
                      </p>
                      <div className="mt-2 space-y-1 text-xs text-slate-400">
                        {detail.latest_attempt.razorpay_reference_id && (
                          <p>
                            Reference ID:{" "}
                            <span className="font-mono text-slate-300">{detail.latest_attempt.razorpay_reference_id}</span>
                          </p>
                        )}
                        {detail.latest_attempt.razorpay_payment_link_url && (
                          <p>
                            Link:{" "}
                            <a
                              href={detail.latest_attempt.razorpay_payment_link_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-accent hover:underline"
                            >
                              {detail.latest_attempt.razorpay_payment_link_url}
                            </a>
                          </p>
                        )}
                      </div>
                      {!detail.latest_attempt.recovered_amount && (
                        <p className="mt-2 text-xs font-medium text-atrisk">
                          Creating a Payment Link does not mean payment recovered — awaiting confirmed payment.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-border p-6 text-center">
                <p className="text-sm text-slate-400">No recovery workflow has been run for this transaction yet.</p>
                <button
                  onClick={handleTrigger}
                  disabled={triggering}
                  className="mt-3 rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/15 disabled:opacity-50"
                >
                  {triggering ? "Running recovery workflow..." : "Trigger recovery"}
                </button>
              </div>
            )}
          </div>

          <div className="mt-8">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Audit Timeline</p>
            <AuditTimeline events={detail.audit_trail} />
          </div>
        </>
      )}
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-panel p-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-medium text-slate-200">{value}</p>
    </div>
  );
}
