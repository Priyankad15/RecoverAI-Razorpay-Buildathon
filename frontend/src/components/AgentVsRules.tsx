import StatusBadge from "./StatusBadge";

interface AgentVsRulesProps {
  recoveryProbability: number | null;
  agentAction: string;
  agentConfidence: number;
  agentExplanation: string;
  agentReasonCodes: string[];
  rulesDecision: string;
  rulesReasonCodes: string[];
  rulesExplanation: string;
  executionStatus: string;
}

export default function AgentVsRules({
  recoveryProbability,
  agentAction,
  agentConfidence,
  agentExplanation,
  agentReasonCodes,
  rulesDecision,
  rulesReasonCodes,
  rulesExplanation,
  executionStatus,
}: AgentVsRulesProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded-xl border border-accent/30 bg-accent/5 p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-accent">AI Recommendation</p>
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-medium text-accent">
            Advisory only
          </span>
        </div>
        <p className="font-mono text-lg font-semibold text-white">{agentAction}</p>
        {recoveryProbability !== null && (
          <p className="mt-1 text-xs text-slate-400">
            Recovery probability:{" "}
            <span className="font-mono text-slate-200">{(recoveryProbability * 100).toFixed(1)}%</span> ·
            Confidence: <span className="font-mono text-slate-200">{(agentConfidence * 100).toFixed(0)}%</span>
          </p>
        )}
        <p className="mt-3 text-sm leading-relaxed text-slate-300">{agentExplanation}</p>
        {agentReasonCodes.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {agentReasonCodes.map((code) => (
              <span key={code} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                {code}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Final Safety Decision</p>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-medium text-slate-300">
            Authoritative
          </span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={rulesDecision} />
          <StatusBadge status={executionStatus} />
        </div>
        <p className="mt-3 text-sm leading-relaxed text-slate-300">{rulesExplanation}</p>
        {rulesReasonCodes.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {rulesReasonCodes.map((code) => (
              <span key={code} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                {code}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
