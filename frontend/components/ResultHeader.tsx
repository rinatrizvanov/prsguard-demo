import type { GateStatus, PrsGuardResult, ResultSource } from "@/lib/types";
import { fmtFraction, fmtInt } from "@/lib/format";
import { StatusBadge, SyntheticBadge } from "./Badges";

const ANSWER_LABEL: Record<GateStatus, string> = {
  SUPPORTED: "SUPPORTED",
  RAW_ONLY: "RAW ONLY",
  ABSTAIN: "ABSTAIN",
};

export function ResultHeader({ result, source }: { result: PrsGuardResult; source: ResultSource }) {
  const h = result.headline;
  const label = result.label ?? {};
  const b = result.build ?? { build: null };
  const trait = result.router?.trait;
  const primaryId = result.primary?.pgs_id ?? h.primary;
  const primary = primaryId ? result.candidates.find((c) => c.pgs_id === primaryId) : undefined;
  const counts = h.counts ?? {};
  const g = result.input?.genotype;

  return (
    <div className={`panel result-header ${h.answer}`}>
      <div className="case-line">
        {source.kind === "demo" ? (
          <span>
            <strong>Demo case {label.case_id ?? source.caseId}</strong>
            {label.case_title ? ` · ${label.case_title}` : ""}
          </span>
        ) : (
          <span>
            <strong>Local analysis</strong> · {source.fileName} · analysed on this computer
          </span>
        )}
        <SyntheticBadge synthetic={label.synthetic} />
        {source.kind === "demo" && label.synthetic === false ? (
          <span className="badge real">REAL PUBLIC GENOTYPES</span>
        ) : null}
      </div>
      {source.kind === "demo" && source.entry ? (
        <p className="prov-label" style={{ margin: "0 0 6px", display: "inline-block" }}>
          {source.entry.label}
        </p>
      ) : null}
      {label.data_provenance ? (
        <p className="small muted" style={{ marginBottom: 14 }}>
          Data provenance: {label.data_provenance}
        </p>
      ) : null}

      <h2 className="visually-hidden">Answer</h2>
      <div className="answer-row">
        <StatusBadge status={h.answer} size="lg">
          {ANSWER_LABEL[h.answer] ?? h.answer}
        </StatusBadge>
        <p className="headline">{h.text}</p>
      </div>

      <div className="fact-grid">
        <div className="fact">
          <div className="fact-label">Trait</div>
          <div className="fact-value">{trait?.term?.label ?? result.input?.trait_query}</div>
          <div className="fact-sub">
            {trait?.term?.id ? <span className="mono">{trait.term.id}</span> : null} · query &ldquo;
            {result.input?.trait_query}
            &rdquo;
          </div>
        </div>
        <div className="fact">
          <div className="fact-label">Genome build</div>
          <div className="fact-value">{b.build ?? "unresolved"}</div>
          <div className="fact-sub">
            {b.method ?? "—"}
            {typeof b.grch37_position_agreement === "number" ? (
              <>
                <br />
                anchors: GRCh37 {fmtFraction(b.grch37_position_agreement, 1)} · GRCh38{" "}
                {fmtFraction(b.grch38_position_agreement, 1)} of {fmtInt(b.grch37_rsid_sites_checked)}
              </>
            ) : null}
            <br />
            declared: header {b.header_declared ?? "none"}, user {b.user_declared ?? "none"}
          </div>
        </div>
        <div className="fact">
          <div className="fact-label">Reference placement</div>
          <div className="fact-value">
            <StatusBadge status={result.placement?.status ?? String(h.placement)} />{" "}
            {result.placement?.placement ? <span>{result.placement.placement}</span> : null}
          </div>
          <div className="fact-sub">not ethnicity or identity</div>
        </div>
        <div className="fact">
          <div className="fact-label">Candidates by gate status</div>
          <div className="count-row" style={{ marginTop: 2 }}>
            {(["SUPPORTED", "RAW_ONLY", "ABSTAIN"] as GateStatus[]).map((s) => (
              <StatusBadge key={s} status={s}>
                {counts[s] ?? 0} {ANSWER_LABEL[s]}
              </StatusBadge>
            ))}
          </div>
        </div>
        <div className="fact">
          <div className="fact-label">Primary score</div>
          <div className="fact-value">
            {primary ? (
              <>
                <span className="mono">{primary.pgs_id}</span> {primary.name}
              </>
            ) : (
              "none"
            )}
          </div>
          <div className="fact-sub">
            {primary ? `pre-rank #${primary.pre_rank}; ` : "no candidate is SUPPORTED; "}
            rule: highest pre-ranked SUPPORTED
          </div>
        </div>
        <div className="fact">
          <div className="fact-label">Input file</div>
          <div className="fact-value mono" style={{ fontSize: 13 }}>
            {g?.file ?? "—"}
          </div>
          <div className="fact-sub">
            {g?.format} · {fmtInt(g?.n_records)} records ({fmtInt(g?.n_called)} called) · sex{" "}
            {result.input?.sex ?? "not given"}
          </div>
        </div>
      </div>
    </div>
  );
}
