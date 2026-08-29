export default function SimulationBanner() {
  return (
    <div className="mb-6 flex items-center gap-2 rounded-lg border border-pending/30 bg-pending/5 px-3 py-2">
      <span className="h-1.5 w-1.5 rounded-full bg-pending" />
      <p className="text-xs font-medium text-pending">
        TEST MODE — no real money moves. Recoveries run as either an in-process Simulation or a real Razorpay
        Test Mode Payment Link (test money only) — see the badge on each transaction.
      </p>
    </div>
  );
}
