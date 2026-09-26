import type { PrsGuardResult, ResultSource } from "@/lib/types";
import { AgentTrace } from "./AgentTrace";
import { CandidateSelection } from "./CandidateSelection";
import { CandidateTable } from "./CandidateTable";
import { CrossPgsPanel } from "./CrossPgsPanel";
import { InterpretationTiles, ReleaseMatrix } from "./Interpretation";
import { PlacementPanel } from "./PlacementPanel";
import { Reproducibility } from "./Reproducibility";
import { ResultHeader } from "./ResultHeader";
import { CodeList } from "./Badges";
import { SectionBoundary } from "./ErrorBoundary";

const SECTIONS = [
  { id: "interpretation", label: "Interpretation" },
  { id: "trace", label: "Agent trace" },
  { id: "placement", label: "Reference placement" },
  { id: "candidates", label: "Candidates & evidence" },
  { id: "cross-pgs", label: "Cross-PGS" },
  { id: "reproducibility", label: "Reproducibility" },
];

export function ResultView({ result, source }: { result: PrsGuardResult; source: ResultSource }) {
  const primaryId = result.primary?.pgs_id ?? result.headline?.primary ?? null;
  const primary = primaryId ? result.candidates.find((c) => c.pgs_id === primaryId) : undefined;
  const personLabel =
    source.kind === "demo"
      ? `This person (demo case ${result.label?.case_id ?? source.caseId})`
      : `This person (${source.fileName})`;
  const allCodes = Array.from(new Set(result.candidates.flatMap((c) => c.gate?.reason_codes ?? [])));
  const resultKey = `${source.kind}-${source.kind === "demo" ? source.caseId : source.analysedAt}`;

  return (
    <div>
      <SectionBoundary key={`h-${resultKey}`} name="result header">
        <ResultHeader result={result} source={source} />
      </SectionBoundary>

      <nav className="section-nav" aria-label="Result sections">
        <ul>
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <section className="section" id="interpretation" aria-labelledby="h-interpretation">
        <div className="section-head">
          <h2 id="h-interpretation">Reference interpretation</h2>
          <p>
            What the deterministic gate allows to be said for this person. Values the gate did not release are shown as
            withheld, with the reason codes — they are never estimated by this page.
          </p>
        </div>
        <SectionBoundary key={`i-${resultKey}`} name="interpretation">
          <div className="panel">
            {primary ? (
              <>
                <div className="panel-title">
                  <h3>
                    Primary score <span className="mono">{primary.pgs_id}</span> {primary.name}
                  </h3>
                  <span className="small muted">
                    pre-rank #{primary.pre_rank} · {result.primary?.rule}
                  </span>
                </div>
                <InterpretationTiles candidate={primary} />
              </>
            ) : (
              <div className="callout warn" style={{ marginBottom: 14 }}>
                <div>
                  <p style={{ marginBottom: 4 }}>
                    <strong>No primary score.</strong> No candidate passed the gate as SUPPORTED, so no standardized
                    score or percentile is interpreted for this person.
                  </p>
                  <p className="small" style={{ marginBottom: 0 }}>
                    Reason codes across candidates: <CodeList codes={allCodes} />
                  </p>
                </div>
              </div>
            )}
            <h3 className="subhead" style={{ marginTop: 18 }}>
              What was released, per candidate
            </h3>
            <ReleaseMatrix
              candidates={[...result.candidates].sort((a, b) => a.pre_rank - b.pre_rank)}
              primary={primaryId}
            />
            {!primary ? (
              <p className="gate-sentence">No percentile is released unless the evidence gate supports it.</p>
            ) : null}
          </div>
        </SectionBoundary>
      </section>

      <section className="section" id="trace" aria-labelledby="h-trace">
        <div className="section-head">
          <h2 id="h-trace">Agent trace</h2>
          <p>
            The agent gathers evidence and orchestrates tools. Deterministic code decides what claims are allowed. The
            candidate list is frozen (digest) before any personal genotype is scored.
          </p>
        </div>
        <SectionBoundary key={`t-${resultKey}`} name="agent trace">
          <AgentTrace result={result} />
        </SectionBoundary>
      </section>

      <section className="section" id="placement" aria-labelledby="h-placement">
        <div className="section-head">
          <h2 id="h-placement">Reference placement</h2>
          <p>
            Where this genotype falls relative to the 1000 Genomes reference panel, computed once per person. It decides
            which reference distribution — if any — a percentile may be taken from.
          </p>
        </div>
        <SectionBoundary key={`p-${resultKey}`} name="reference placement">
          <PlacementPanel placement={result.placement} personLabel={personLabel} />
        </SectionBoundary>
      </section>

      <section className="section" id="candidates" aria-labelledby="h-candidates">
        <div className="section-head">
          <h2 id="h-candidates">Candidate scores and the evidence behind them</h2>
          <p>
            Each frozen candidate is scored and passed through the applicability gate on its own. Expand a row for its
            interpretation, rule trace, population evidence and provenance.
          </p>
        </div>
        <SectionBoundary key={`s-${resultKey}`} name="candidate selection">
          <CandidateSelection router={result.router} />
        </SectionBoundary>
        <div style={{ marginTop: 16 }}>
          <SectionBoundary key={`c-${resultKey}`} name="candidate table">
            <CandidateTable result={result} />
          </SectionBoundary>
        </div>
      </section>

      <section className="section" id="cross-pgs" aria-labelledby="h-cross">
        <div className="section-head">
          <h2 id="h-cross">Cross-PGS consistency</h2>
          <p>
            Do independent SUPPORTED scores place this person similarly, relative to how much reference individuals
            vary?
          </p>
        </div>
        <SectionBoundary key={`x-${resultKey}`} name="cross-PGS">
          <CrossPgsPanel cross={result.cross_pgs} primary={primaryId} />
        </SectionBoundary>
      </section>

      <section className="section" id="reproducibility" aria-labelledby="h-repro">
        <div className="section-head">
          <h2 id="h-repro">Reproducibility</h2>
          <p>Everything needed to re-run this result and check it has not changed.</p>
        </div>
        <SectionBoundary key={`r-${resultKey}`} name="reproducibility">
          <Reproducibility result={result} />
        </SectionBoundary>
      </section>
    </div>
  );
}
