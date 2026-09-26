"use client";

import { useState } from "react";
import type { Candidate, PrsGuardResult } from "@/lib/types";
import { fmtFraction, fmtInt, fmtNum, humanise, isNum } from "@/lib/format";
import { CodeList, StatusBadge } from "./Badges";
import { IconChevronDown, IconLock } from "./Icons";
import { releasedNumber } from "./Interpretation";
import { CandidateDetail } from "./CandidateDetail";
import { SectionBoundary } from "./ErrorBoundary";

function PercentileCell({ c }: { c: Candidate }) {
  const v = releasedNumber(c.interpretation.percentile);
  if (v !== null) {
    return (
      <span>
        <strong className="num">{fmtNum(v, 1)}</strong>{" "}
        <span className="tiny muted">{c.interpretation.percentile.reference_group}</span>
      </span>
    );
  }
  return (
    <span className="muted">
      <IconLock size={12} /> withheld
    </span>
  );
}

export function CandidateTable({ result }: { result: PrsGuardResult }) {
  const primary = result.primary?.pgs_id ?? result.headline?.primary ?? null;
  const cands = [...result.candidates].sort((a, b) => a.pre_rank - b.pre_rank);
  // Open the primary score by default; with no primary, open the top pre-ranked candidate so the reason is visible.
  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    const first = primary ?? cands[0]?.pgs_id;
    return first ? { [first]: true } : {};
  });

  return (
    <div>
      <div className="cand-list" role="list" aria-label="Candidate scores">
        <div className="cand-head cand-cols" aria-hidden="true">
          <span>Pre-rank</span>
          <span>Score</span>
          <span>Variants matched</span>
          <span>Scoreability r</span>
          <span>Gate</span>
          <span>Reason codes</span>
          <span>Percentile</span>
          <span />
        </div>
        {cands.map((c) => {
          const isOpen = !!open[c.pgs_id];
          const h = c.harmonisation;
          const r = h?.scoreability?.r;
          const detailId = `cand-detail-${c.pgs_id}`;
          return (
            <div role="listitem" key={c.pgs_id} className={`cand-row ${isOpen ? "open" : ""}`}>
              <button
                type="button"
                className="cand-summary cand-cols"
                aria-expanded={isOpen}
                aria-controls={detailId}
                onClick={() => setOpen((o) => ({ ...o, [c.pgs_id]: !o[c.pgs_id] }))}
              >
                <span className="c-rank">
                  <span className="cell-label">Pre-rank</span>
                  <span className="rank">#{c.pre_rank}</span>
                </span>
                <span className="c-score">
                  <span className="cell-label">Score</span>
                  <span className="pgs-id">{c.pgs_id}</span>{" "}
                  {c.pgs_id === primary ? <span className="badge primary-tag">PRIMARY</span> : null}
                  <span className="pgs-name" style={{ display: "block" }}>
                    {c.name} · {c.publication?.first_author} {c.publication?.date_publication?.slice(0, 4)}
                  </span>
                </span>
                <span>
                  <span className="cell-label">Variants matched</span>
                  <span className="num">
                    {fmtInt(h?.n_matched)} / {fmtInt(h?.n_variants ?? c.variants_number)}
                  </span>
                  {isNum(h?.fraction_matched) ? (
                    <span className="tiny muted" style={{ display: "block" }}>
                      {fmtFraction(h.fraction_matched, 1)}
                    </span>
                  ) : null}
                </span>
                <span>
                  <span className="cell-label">Scoreability r</span>
                  <span className="num">{fmtNum(r, 3)}</span>
                </span>
                <span>
                  <span className="cell-label">Gate</span>
                  <StatusBadge status={c.gate.status} />
                </span>
                <span>
                  <span className="cell-label">Reason codes</span>
                  <CodeList codes={c.gate.reason_codes} empty="none" />
                </span>
                <span>
                  <span className="cell-label">Percentile</span>
                  <PercentileCell c={c} />
                </span>
                <span className="c-toggle">
                  <span className="chev" aria-hidden="true">
                    <IconChevronDown size={14} />
                  </span>
                  <span className="visually-hidden">
                    {isOpen ? "Hide" : "Show"} evidence for {c.pgs_id}
                  </span>
                </span>
              </button>
              <div id={detailId} hidden={!isOpen}>
                {isOpen ? (
                  <div className="cand-detail">
                    <SectionBoundary name={`evidence for ${c.pgs_id}`}>
                      <CandidateDetail candidate={c} result={result} />
                    </SectionBoundary>
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <p className="tiny muted" style={{ marginTop: 8 }}>
        Primary score rule: {result.primary?.rule ?? "highest pre-ranked candidate whose gate status is SUPPORTED"}.
        Scoreability r measures how well the score computable from this file represents the published score (
        {humanise(cands[0]?.harmonisation?.scoreability?.method ?? "reference_panel_correlation")}).
      </p>
    </div>
  );
}
