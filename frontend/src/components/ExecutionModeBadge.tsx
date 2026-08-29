export default function ExecutionModeBadge({ mode }: { mode: string | null | undefined }) {
  if (mode === "RAZORPAY_TEST_MODE") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
        Razorpay Test Mode
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-pending/30 bg-pending/10 px-2.5 py-1 text-xs font-medium text-pending">
      <span className="h-1.5 w-1.5 rounded-full bg-pending" />
      Simulation / Test Mode
    </span>
  );
}
