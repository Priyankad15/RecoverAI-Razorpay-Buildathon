import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/payments", label: "Failed Payments" },
  { to: "/audit", label: "Audit Trail" },
  { to: "/analytics", label: "Analytics" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-ink text-slate-100">
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-panel md:flex">
          <div className="px-5 py-5">
            <p className="text-sm font-semibold tracking-tight text-white">RecoverAI</p>
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Revenue Recovery</p>
          </div>
          <nav className="flex flex-1 flex-col gap-1 px-3">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive ? "bg-accent/15 text-accent" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="border-t border-border px-5 py-4">
            <p className="text-[11px] leading-relaxed text-slate-500">
              SIMULATION / TEST MODE
              <br />
              No real money moves here.
            </p>
          </div>
        </aside>

        <div className="flex-1">
          <header className="border-b border-border bg-panel px-4 py-3 md:hidden">
            <p className="mb-2 text-sm font-semibold text-white">RecoverAI</p>
            <nav className="flex gap-1.5 overflow-x-auto">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `shrink-0 rounded-full border px-3 py-1 text-xs font-medium ${
                      isActive
                        ? "border-accent/40 bg-accent/15 text-accent"
                        : "border-border text-slate-400 hover:text-slate-200"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
