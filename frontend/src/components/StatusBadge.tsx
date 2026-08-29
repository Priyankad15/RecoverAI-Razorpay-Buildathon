interface StatusConfig {
  label: string;
  dotClass: string;
  textClass: string;
  bgClass: string;
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  SUCCESS: { label: "Recovered", dotClass: "bg-recovered", textClass: "text-recovered", bgClass: "bg-recovered/10 border-recovered/30" },
  FAILED: { label: "Failed", dotClass: "bg-atrisk", textClass: "text-atrisk", bgClass: "bg-atrisk/10 border-atrisk/30" },
  BLOCKED: { label: "Blocked", dotClass: "bg-blocked", textClass: "text-blocked", bgClass: "bg-blocked/10 border-blocked/30" },
  PENDING_HUMAN_APPROVAL: { label: "Needs approval", dotClass: "bg-pending", textClass: "text-pending", bgClass: "bg-pending/10 border-pending/30" },
  COMPLETED: { label: "Completed", dotClass: "bg-accent", textClass: "text-accent", bgClass: "bg-accent/10 border-accent/30" },
  NOT_EXECUTED: { label: "Not executed", dotClass: "bg-muted", textClass: "text-muted", bgClass: "bg-muted/10 border-muted/30" },
  UNPROCESSED: { label: "Unprocessed", dotClass: "bg-slate-500", textClass: "text-slate-400", bgClass: "bg-slate-500/10 border-slate-500/30" },
  ALLOW: { label: "Allow", dotClass: "bg-recovered", textClass: "text-recovered", bgClass: "bg-recovered/10 border-recovered/30" },
  BLOCK: { label: "Block", dotClass: "bg-blocked", textClass: "text-blocked", bgClass: "bg-blocked/10 border-blocked/30" },
  HUMAN_APPROVAL: { label: "Human approval", dotClass: "bg-pending", textClass: "text-pending", bgClass: "bg-pending/10 border-pending/30" },
};

const FALLBACK: StatusConfig = {
  label: "Unknown",
  dotClass: "bg-slate-500",
  textClass: "text-slate-400",
  bgClass: "bg-slate-500/10 border-slate-500/30",
};

export default function StatusBadge({ status }: { status: string | null | undefined }) {
  const config = (status && STATUS_CONFIG[status]) || FALLBACK;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${config.bgClass} ${config.textClass}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${config.dotClass}`} />
      {config.label}
    </span>
  );
}
