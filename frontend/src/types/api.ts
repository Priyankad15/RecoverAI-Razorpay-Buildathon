export interface HealthResponse {
  status: string;
  service: string;
}

export type ExecutionStatus =
  | "SUCCESS"
  | "FAILED"
  | "BLOCKED"
  | "PENDING_HUMAN_APPROVAL"
  | "COMPLETED"
  | "NOT_EXECUTED"
  | "UNPROCESSED";

export interface PaymentListItem {
  transaction_id: string;
  customer_id: string;
  amount: number;
  payment_method: string;
  failure_reason: string | null;
  retry_count: number | null;
  recovery_probability: number | null;
  status: ExecutionStatus;
  requested_action: string | null;
  rules_decision: string | null;
  created_at: string;
}

export interface PaymentListResponse {
  items: PaymentListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEvent {
  timestamp: string;
  event_type: string;
  transaction_id: string | null;
  requested_action: string | null;
  rules_decision: string | null;
  execution_status: string | null;
  reason_codes: string[];
  explanation: string | null;
}

export interface RecoveryAttempt {
  id: string;
  retry_count: number | null;
  recovery_probability: number | null;
  requested_action: string | null;
  agent_explanation: string | null;
  agent_confidence: number | null;
  rules_decision: string | null;
  execution_status: string | null;
  recovered_amount: number | null;
  failure_reason: string | null;
  simulation_mode: boolean | null;
  created_at: string | null;
  completed_at: string | null;
  execution_mode: string | null;
  razorpay_payment_link_id: string | null;
  razorpay_payment_link_url: string | null;
  razorpay_reference_id: string | null;
}

export interface PaymentDetail {
  transaction_id: string;
  customer_id: string;
  amount: number;
  payment_method: string;
  failure_reason: string | null;
  status: ExecutionStatus;
  created_at: string;
  previous_transactions: number;
  previous_success_rate: number;
  subscription_status: string | null;
  customer_type: string | null;
  historical_failure_count: number;
  latest_attempt: RecoveryAttempt | null;
  audit_trail: AuditEvent[];
}

export interface RecoveryWorkflowResponse {
  transaction_id: string;
  idempotent_replay: boolean;
  recovery_probability: number | null;
  agent_requested_action: string;
  agent_confidence: number;
  agent_explanation: string;
  agent_reason_codes: string[];
  agent_provider: string;
  agent_is_mock: boolean;
  rules_decision: string;
  rules_reason_codes: string[];
  rules_explanation: string;
  requires_human_approval: boolean;
  execution_status: string;
  recovered_amount: number;
  failure_reason: string | null;
  simulation_mode: boolean;
  execution_mode: string;
  razorpay_payment_link_id: string | null;
  razorpay_payment_link_url: string | null;
  razorpay_reference_id: string | null;
  audit_events: AuditEvent[];
}

export interface DashboardSummary {
  total_payments: number;
  failed_payments: number;
  revenue_at_risk_inr: number;
  potentially_recoverable_revenue_inr: number;
  recovered_revenue_inr: number;
  recovery_rate: number;
  automated_recoveries: number;
  failed_recoveries: number;
  blocked_recoveries: number;
  pending_human_approval: number;
  unprocessed_payments: number;
}

export interface AnalyticsResponse {
  summary: DashboardSummary;
  status_breakdown: Record<string, number>;
  failure_reason_breakdown: Record<string, number>;
  top_reason_codes: Record<string, number>;
}
