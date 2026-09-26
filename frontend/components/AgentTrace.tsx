import type { PrsGuardResult, TraceStep } from "@/lib/types";
import { fmtTimestamp, shortHash } from "@/lib/format";
import { ActorBadge } from "./Badges";
import { IconSnowflake } from "./Icons";

function isFreezeStep(s: TraceStep): boolean {
  return /freeze/i.test(s.title) || (s.outputs != null && "digest" in s.outputs && "frozen_at" in s.outputs);
}

function isPersonalScoringStep(s: TraceStep): boolean {
  return /harmonis|harmoniz|raw score/i.test(s.title);
}

export function AgentTrace({ result }: { result: PrsGuardResult }) {
  const steps = [...(result.trace ?? [])].sort((a, b) => a.step - b.step);
  const scoring = steps.find(isPersonalScoringStep);
  const nAgent = steps.filter((s) => s.actor === "AGENT_ACTION").length;
  const nDet = steps.length - nAgent;

  return (
    <div className="panel">
      <div className="trace-legend" aria-label="Legend">
        <span className="item">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <circle cx="9" cy="9" r="7.5" fill="#f1edfb" stroke="#5a3fb3" strokeWidth="1.5" strokeDasharray="3 2" />
          </svg>
          <ActorBadge actor="AGENT_ACTION" />
          <span className="muted">gathers evidence, calls tools, explains ({nAgent})</span>
        </span>
        <span className="item">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <rect x="1.5" y="1.5" width="15" height="15" rx="3" fill="#1f2937" />
          </svg>
          <ActorBadge actor="DETERMINISTIC_DECISION" />
          <span className="muted">fixed code decides what may be claimed ({nDet})</span>
        </span>
      </div>

      <ol className="timeline">
        {steps.map((s) => {
          const agent = s.actor === "AGENT_ACTION";
          const freeze = isFreezeStep(s);
          const outputs = s.outputs && Object.keys(s.outputs).length > 0 ? s.outputs : null;
          return (
            <li key={s.step}>
              <span className={`node ${agent ? "agent" : "det"}`} aria-hidden="true">
                {s.step}
              </span>
              <div className={`trace-card ${agent ? "agent" : "det"}`}>
                <div className="trace-top">
                  <span className="visually-hidden">Step {s.step}:</span>
                  <ActorBadge actor={s.actor} />
                  <h3>{s.title}</h3>
                </div>
                <div className="tool">tool: {s.tool}</div>
                <p className="summary">{s.summary}</p>
                {freeze ? (
                  <div className="freeze-mark">
                    <strong>
                      <IconSnowflake size={13} /> CANDIDATES FROZEN
                    </strong>{" "}
                    before any personal scoring — digest{" "}
                    <span className="mono" title={result.router?.digest}>
                      {shortHash(result.router?.digest, 12, 6)}
                    </span>
                    , frozen at {fmtTimestamp(result.router?.frozen_at)}
                    {scoring?.started_at ? (
                      <>
                        ; personal scoring started {fmtTimestamp(scoring.started_at)} (step {scoring.step})
                      </>
                    ) : null}
                    . The candidate list and its order cannot change after this point.
                  </div>
                ) : null}
                {outputs ? (
                  <details className="trace-outputs">
                    <summary>Recorded outputs</summary>
                    <pre className="json">{JSON.stringify(outputs, null, 2)}</pre>
                  </details>
                ) : null}
                {s.started_at ? (
                  <div className="tiny muted" style={{ marginTop: 4 }}>
                    {fmtTimestamp(s.started_at)}
                    {s.finished_at && s.finished_at !== s.started_at ? ` → ${fmtTimestamp(s.finished_at)}` : ""}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
