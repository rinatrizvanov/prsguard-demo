"use client";

import { useState } from "react";
import type { Candidate, EquityScorerContext, LiteratureContext as Lit } from "@/lib/types";
import { ancestryMeta, sortCodes } from "@/lib/ancestry";
import { doiUrl, fmtFraction, fmtInt, fmtNum, fmtTimestamp, plainText, pmidUrl, shortHash } from "@/lib/format";
import { ContextOnlyLabel } from "./Badges";
import { Disclosure } from "./Disclosure";
import { IconBook } from "./Icons";
import { segFill } from "./AncestryStageChart";

function StageCounts({ stageAncestry }: { stageAncestry: Record<string, Record<string, number>> }) {
  const stages = Object.keys(stageAncestry);
  const present = sortCodes(
    Array.from(
      new Set(stages.flatMap((st) => Object.keys(stageAncestry[st] ?? {}).filter((c) => stageAncestry[st][c] > 0))),
    ),
  );
  return (
    <div>
      <div className="stage-chart">
        {stages.map((st) => {
          const counts = stageAncestry[st] ?? {};
          const total = Object.values(counts).reduce((a, b) => a + (b || 0), 0);
          const codes = sortCodes(Object.keys(counts)).filter((c) => counts[c] > 0);
          return (
            <div className="stage-row" key={st}>
              <div>
                <div className="stage-name">{st}</div>
                <div className="stage-n">N = {fmtInt(total)} extracted</div>
              </div>
              {total > 0 ? (
                <div
                  className="stage-bar"
                  role="img"
                  aria-label={`${st}: ${codes.map((c) => `${c} ${fmtInt(counts[c])}`).join(", ")}`}
                >
                  {codes.map((c) => (
                    <div
                      key={c}
                      className="seg"
                      style={{ width: `${(counts[c] / total) * 100}%`, background: segFill(c) }}
                      title={`${c} — ${ancestryMeta(c).label}: N = ${fmtInt(counts[c])}`}
                    />
                  ))}
                </div>
              ) : (
                <div className="stage-bar empty">none extracted</div>
              )}
            </div>
          );
        })}
      </div>
      <ul className="legend" aria-label="Ancestry legend">
        {present.map((c) => (
          <li key={c}>
            <span className="swatch" style={{ background: segFill(c) }} aria-hidden="true" />
            <span className="mono">{c}</span> {ancestryMeta(c).label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LiteraturePanel({ lit, pgsId }: { lit: Lit | null | undefined; pgsId: string }) {
  const [onlyThis, setOnlyThis] = useState(true);
  if (!lit) {
    return (
      <div className="callout context">
        <IconBook size={16} />
        <span>
          <ContextOnlyLabel /> No literature-equity context was attached to this result.
        </span>
      </div>
    );
  }
  const linked = lit.papers.filter((p) => p.linked_scores.some((s) => s.startsWith(`${pgsId} `) || s === pgsId));
  const papers = onlyThis ? linked : lit.papers;
  const s = lit.summary;
  const rubricRows = (lit.rubric ?? []).filter((r) => r && Object.keys(r).length > 0);

  return (
    <div>
      <div className="callout context" role="note">
        <IconBook size={16} />
        <div>
          <p style={{ marginBottom: 4 }}>
            <ContextOnlyLabel />
          </p>
          <p style={{ marginBottom: 4 }}>
            <strong>Literature equity (equity-lit-auditor {lit.skill_version})</strong> describes how the papers behind
            these scores report and sample populations. It is not a measure of a score&apos;s validity or
            transferability, and feeds_applicability_decision = <code>{String(lit.feeds_applicability_decision)}</code>.
          </p>
          <p className="small" style={{ marginBottom: 0 }}>
            Data provenance:{" "}
            <span className={`badge ${lit.synthetic ? "synthetic" : "real"}`}>
              {lit.synthetic ? "SYNTHETIC" : lit.data_provenance}
            </span>{" "}
            · retrieved {fmtTimestamp(lit.provenance?.retrieved_at)} ·{" "}
            {Object.values(lit.provenance?.sources ?? {}).join("; ")}
            {lit.provenance?.note ? <span className="muted"> — {lit.provenance.note}</span> : null}
          </p>
        </div>
      </div>

      <p className="small muted">
        Audited scores: <span className="mono">{lit.query?.pgs_ids?.join(", ")}</span> (summary covers all of them).
        Scale: {lit.semantics?.scale}.
      </p>

      <div className="stat-row">
        <div className="stat">
          <div className="v num">{fmtInt(s.papers_total)}</div>
          <div className="l">papers audited</div>
        </div>
        <div className="stat">
          <div className="v num">{fmtInt(s.papers_european_only)}</div>
          <div className="l">European-ancestry participants only</div>
        </div>
        <div className="stat">
          <div className="v num">{s.median_equity_score ?? "—"}</div>
          <div className="l">median equity score (0–100)</div>
        </div>
        <div className="stat">
          <div className="v num">{fmtNum(s.mean_equity_score, 1)}</div>
          <div className="l">mean equity score</div>
        </div>
        <div className="stat">
          <div className="v num">{fmtInt(s.countries)}</div>
          <div className="l">recruitment countries</div>
        </div>
        <div className="stat">
          <div className="v num">{fmtInt(s.participants_extracted)}</div>
          <div className="l">participants extracted ({s.ancestry_share_basis})</div>
        </div>
      </div>
      {s.extraction_check ? (
        <p className="tiny muted">
          Extraction check: {fmtInt(s.extraction_check.recovered)} of {fmtInt(s.extraction_check.curated_groups)}{" "}
          curated ancestry groups recovered from {fmtInt(s.extraction_check.papers)} papers (recall{" "}
          {fmtFraction(s.extraction_check.recall, 0)}). Flags:{" "}
          {Object.entries(s.flags ?? {})
            .map(([k, v]) => `${k} (${v})`)
            .join("; ") || "none"}
          .
        </p>
      ) : null}

      <h4 className="subhead">Participants by stage in the audited literature</h4>
      <StageCounts stageAncestry={lit.stage_ancestry ?? {}} />

      <h4 className="subhead" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        Papers
        <label className="check" style={{ fontWeight: 400 }}>
          <input type="checkbox" checked={onlyThis} onChange={(e) => setOnlyThis(e.target.checked)} />
          only papers linked to {pgsId} ({linked.length} of {lit.papers.length})
        </label>
      </h4>
      <div className="table-wrap scroll-y">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Year</th>
              <th scope="col">Paper</th>
              <th scope="col">Linked as</th>
              <th scope="col">Equity score</th>
              <th scope="col">Flags</th>
              <th scope="col" className="r">
                N
              </th>
            </tr>
          </thead>
          <tbody>
            {papers.map((p) => {
              const link = doiUrl(p.doi) ?? pmidUrl(p.pmid);
              const comp = Object.entries(p.components ?? {})
                .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v.points}/${v.max}`)
                .join("\n");
              return (
                <tr key={p.id}>
                  <td className="nowrap">{p.year ?? "—"}</td>
                  <td style={{ minWidth: 260 }}>
                    {link ? (
                      <a href={link} target="_blank" rel="noreferrer noopener">
                        {plainText(p.title)}
                      </a>
                    ) : (
                      plainText(p.title)
                    )}
                    <div className="tiny muted">
                      {p.first_author} · <em>{p.journal}</em>
                      {p.pmid ? (
                        <>
                          {" "}
                          · PMID{" "}
                          <a href={pmidUrl(p.pmid) ?? undefined} target="_blank" rel="noreferrer noopener">
                            {p.pmid}
                          </a>
                        </>
                      ) : null}
                      {p.doi ? <> · DOI {p.doi}</> : null}
                    </div>
                  </td>
                  <td className="small">{p.linked_scores.join(", ")}</td>
                  <td title={comp}>
                    <span className="score-bar">
                      <span className="bar-track" aria-hidden="true">
                        <span
                          className="bar-fill"
                          style={{ display: "block", width: `${Math.max(0, Math.min(100, p.equity_score ?? 0))}%` }}
                        />
                      </span>
                      <span className="num">{p.equity_score ?? "—"}</span>
                    </span>
                  </td>
                  <td className="small">{p.flags.length ? p.flags.join("; ") : <span className="muted">none</span>}</td>
                  <td className="r">{fmtInt(p.total_n)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        Hover an equity score for its rubric components. N is the paper-level total extracted by the auditor.
      </p>

      {rubricRows.length > 0 ? (
        <Disclosure summary="Scoring rubric">
          <pre className="json">{JSON.stringify(rubricRows, null, 2)}</pre>
        </Disclosure>
      ) : null}
    </div>
  );
}

export function EquityScorerPanel({ ctx }: { ctx: EquityScorerContext | null | undefined }) {
  if (!ctx) return <p className="muted small">No equity-scorer context attached.</p>;
  const fst = Object.entries(ctx.fst_to_stage_groups ?? {});
  const eri = ctx.evaluation_representation_index;
  return (
    <div>
      <p className="small">
        <ContextOnlyLabel /> <span className="muted">{ctx.note}</span>
      </p>
      <dl className="kv small">
        <dt>Source skill</dt>
        <dd>{ctx.source_skill}</dd>
        <dt>Person&apos;s reference group</dt>
        <dd>{ctx.person_group ?? "none (placement not resolved)"}</dd>
        <dt>Compared stage</dt>
        <dd>{ctx.compared_stage ?? "—"}</dd>
        <dt>
          F<sub>ST</sub> method
        </dt>
        <dd>{ctx.fst_method ?? "—"}</dd>
        {eri ? (
          <>
            <dt>Evaluation representation index</dt>
            <dd>
              {fmtNum(eri.representation_index, 3)}{" "}
              <span className="muted">
                (unknown fraction {fmtFraction(eri.unknown_fraction, 0)}){eri.warning ? ` — ${eri.warning}` : ""}
              </span>
            </dd>
          </>
        ) : null}
      </dl>
      {fst.length > 0 ? (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Stage group</th>
                <th scope="col" className="r">
                  % of stage
                </th>
                <th scope="col" className="r">
                  F<sub>ST</sub> to person&apos;s group
                </th>
              </tr>
            </thead>
            <tbody>
              {fst.map(([g, v]) => (
                <tr key={g}>
                  <th scope="row">{g}</th>
                  <td className="r">{fmtNum(v.percent_of_stage, 1)}</td>
                  <td className="r">{fmtNum(v.fst_to_person_group, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="small muted">
          No F<sub>ST</sub> comparison available.
        </p>
      )}
    </div>
  );
}

export function CatalogProvenance({ candidate }: { candidate: Candidate }) {
  const responses = candidate.provenance?.catalog_responses ?? [];
  const gp = candidate.gate.provenance;
  return (
    <div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Endpoint</th>
              <th scope="col">URL</th>
              <th scope="col">sha256</th>
              <th scope="col">Retrieved</th>
            </tr>
          </thead>
          <tbody>
            {responses.map((r, i) => (
              <tr key={`${r.endpoint}-${i}`}>
                <th scope="row" className="mono nowrap">
                  {r.endpoint}
                </th>
                <td className="mono small">
                  <a href={r.url} target="_blank" rel="noreferrer noopener">
                    {r.url.replace(/^https?:\/\//, "")}
                  </a>
                </td>
                <td className="mono small" title={r.sha256}>
                  {shortHash(r.sha256, 12, 6)}
                </td>
                <td className="small nowrap">{fmtTimestamp(r.retrieved_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {gp ? (
        <dl className="kv small" style={{ marginTop: 10 }}>
          <dt>Gate</dt>
          <dd>
            {gp.gate} v{gp.gate_version} · deterministic: {String(gp.deterministic)}
          </dd>
          <dt>Gate config</dt>
          <dd className="mono" title={gp.config_sha256}>
            {shortHash(gp.config_sha256, 16, 6)}
          </dd>
          <dt>Gate input digest</dt>
          <dd className="mono" title={gp.input_digest}>
            {shortHash(gp.input_digest, 16, 6)}
          </dd>
        </dl>
      ) : null}
    </div>
  );
}
