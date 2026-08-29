import type {
  AnalyticsResponse,
  AuditEvent,
  DashboardSummary,
  HealthResponse,
  PaymentDetail,
  PaymentListResponse,
  RecoveryWorkflowResponse,
} from "../types/api";

// Backend base URL - configurable via Vite env var. Accepts either
// VITE_API_URL (the name used in this project's deployment docs) or
// VITE_API_BASE_URL (the original Phase 1 name) so a Vercel deployment
// configured with either variable name works - a mismatch here would
// silently fall back to localhost in production, which is exactly the
// failure mode this dual-read avoids. Defaults to localhost for local
// dev only.
const API_BASE_URL =
  import.meta.env.VITE_API_URL ?? import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON - fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/dashboard/summary");
}

export function fetchAnalytics(): Promise<AnalyticsResponse> {
  return request<AnalyticsResponse>("/api/analytics");
}

export interface ListPaymentsParams {
  search?: string;
  status?: string;
  sortBy?: "created_at" | "amount" | "transaction_id";
  sortDir?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export function fetchPayments(params: ListPaymentsParams = {}): Promise<PaymentListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.sortBy) query.set("sort_by", params.sortBy);
  if (params.sortDir) query.set("sort_dir", params.sortDir);
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));
  const qs = query.toString();
  return request<PaymentListResponse>(`/api/payments${qs ? `?${qs}` : ""}`);
}

export function fetchPaymentDetail(transactionId: string): Promise<PaymentDetail> {
  return request<PaymentDetail>(`/api/payments/${encodeURIComponent(transactionId)}`);
}

export function triggerRecovery(transactionId: string): Promise<RecoveryWorkflowResponse> {
  return request<RecoveryWorkflowResponse>(`/api/recovery/${encodeURIComponent(transactionId)}`, {
    method: "POST",
  });
}

export function fetchRecoveryResult(transactionId: string): Promise<RecoveryWorkflowResponse> {
  return request<RecoveryWorkflowResponse>(`/api/recovery/${encodeURIComponent(transactionId)}`);
}

export function fetchAuditTrail(transactionId?: string): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(transactionId ? `/api/audit/${encodeURIComponent(transactionId)}` : "/api/audit");
}
