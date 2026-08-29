interface KpiCardProps {
  label: string;
  value: string;
  accent?: "default" | "recovered" | "atrisk" | "blocked" | "pending";
  sublabel?: string;
}

const ACCENT_CLASS: Record<NonNullable<KpiCardProps["accent"]>, string> = {
  default: "text-white",
  recovered: "text-recovered",
  atrisk: "text-atrisk",
  blocked: "text-blocked",
  pending: "text-pending",
};

export default function KpiCard({ label, value, accent = "default", sublabel }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-border bg-panel p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${ACCENT_CLASS[accent]}`}>{value}</p>
      {sublabel && <p className="mt-1 text-xs text-slate-500">{sublabel}</p>}
    </div>
  );
}
