"use client";

import type { Candidate, PrsGuardResult } from "@/lib/types";
import {
  doiUrl,
  fmtFraction,
  fmtInt,
  fmtNum,
  humanise,
  isNum,
  pgsUrl,
  plainText,
  pmidUrl,
  shortHash,
} from "@/lib/format";
import { reasonMeaning } from "@/lib/glossary";
import { CodeChip, CodeList, ContextOnlyLabel, StatusBadge } from "./Badges";
import { Disclosure } from "./Disclosure";
import { IconCheck, IconExternal, IconX } from "./Icons";
import { InterpretationTiles } from "./Interpretation";
import { Tabs } from "./Tabs";
import { AncestryStageChart } from "./AncestryStageChart";
import { WorldMap } from "./WorldMap";
import { EvaluationUnitsTable } from "./EvaluationUnits";
import { CatalogProvenance, EquityScorerPanel, LiteraturePanel } from "./LiteratureContext";

export function CandidateDetail({ candidate, result }: { candidate: Candidate; result: PrsGuardResult }) {
  const c = candidate;
  return (
    <div>
      <h4 className="subhead" style={{ marginTop: 12 }}>
        Reference interpretation for {c.pgs_id}
      </h4>
      <InterpretationTiles candidate={c} />
      <Tabs
        label={`Evidence behind ${c.pgs_id}`}
        tabs={[
          { id: "overview", label: "Overview", render: () => <OverviewTab c={c} /> },
          { id: "applicability", label: "Applicability", render: () => <ApplicabilityTab c={c} /> },
          {
            id: "population",
            label: "Population evidence",
            render: () => <PopulationTab c={c} personGroup={result.placement?.placement ?? null} />,
          },
          {
            id: "literature",
            label: "Literature & provenance",
            render: () => <LiteratureTab c={c} result={result} />,
          },
        ]}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ overview */

function OverviewTab({ c }: { c: Candidate }) {
  const pub = c.publication ?? {};
  const h = c.harmonisation;
  const sc = h?.scoreability;
  const counts = Object.entries(h?.status_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const nonzero = counts.filter(([, n]) => n > 0);
  const zero = counts.filter(([, n]) => n === 0).map(([k]) => k);
  const loss = Object.entries(h?.weight_loss_by_status ?? {}).sort((a, b) => b[1] - a[1]);
  const gp = c.context?.gwas_prs_crosscheck;

  return (
    <div>
      <div className="grid-2">
        <div>
          <h4 className="subhead">Score and publication</h4>
          <dl className="kv small">
            <dt>PGS Catalog</dt>
            <dd>
              <a href={pgsUrl(c.pgs_id)} target="_blank" rel="noreferrer noopener" className="mono">
                {c.pgs_id} <IconExternal size={11} />
              </a>{" "}
              {c.name}
            </dd>
            <dt>Reported trait</dt>
            <dd>{c.trait_reported}</dd>
            <dt>Publication</dt>
            <dd>
              {plainText(pub.title)}
              <div className="tiny muted">
                {pub.first_author} · <em>{pub.journal}</em> · {pub.date_publication} · {pub.pgp_id}
                {pub.doi ? (
                  <>
                    {" "}
                    ·{" "}
                    <a href={doiUrl(pub.doi) ?? undefined} target="_blank" rel="noreferrer noopener">
                      DOI {pub.doi}
                    </a>
                  </>
                ) : null}
                {pub.pmid ? (
                  <>
                    {" "}
                    ·{" "}
                    <a href={pmidUrl(pub.pmid) ?? undefined} target="_blank" rel="noreferrer noopener">
                      PMID {pub.pmid}
                    </a>
                  </>
                ) : null}
              </div>
            </dd>
            <dt>Method</dt>
            <dd>{c.method_name || "—"}</dd>
            <dt>Weight type</dt>
            <dd>
              <span className="mono">{c.weight_type}</span>
              {c.weight_type === "NR" ? <span className="muted"> (not reported)</span> : null}
            </dd>
            <dt>Variants</dt>
            <dd>{fmtInt(c.variants_number)}</dd>
            <dt>Sex-specific</dt>
            <dd>{c.sex_specific ?? "no"}</dd>
          </dl>
        </div>
        <div>
          <h4 className="subhead">Scoring file</h4>
          <dl className="kv small">
            <dt>File</dt>
            <dd className="mono">{c.scoring_file?.name}</dd>
            <dt>Build</dt>
            <dd>{c.scoring_file?.build}</dd>
            <dt>sha256</dt>
            <dd className="mono" title={c.scoring_file?.sha256}>
              {shortHash(c.scoring_file?.sha256, 16, 8)}
            </dd>
            <dt>URL</dt>
            <dd className="mono small">
              {c.scoring_file?.url ? (
                <a href={c.scoring_file.url} target="_blank" rel="noreferrer noopener">
                  {c.scoring_file.url.replace(/^https?:\/\//, "")}
                </a>
              ) : (
                "—"
              )}
            </dd>
          </dl>

          <h4 className="subhead">Scoreability</h4>
          {sc ? (
            <dl className="kv small">
              <dt>r</dt>
              <dd>
                <strong className="num">{fmtNum(sc.r, 4)}</strong>{" "}
                <span className="muted">({humanise(sc.method)})</span>
              </dd>
              <dt>r unadjusted / Spearman</dt>
              <dd className="num">
                {fmtNum(sc.r_unadjusted, 4)} / {fmtNum(sc.spearman, 4)}
              </dd>
              <dt>Measured in</dt>
              <dd>
                {sc.measured_in ?? "—"} reference, n = {fmtInt(sc.n_samples)}
              </dd>
              <dt>Panel variance share</dt>
              <dd className="num">{fmtFraction(sc.panel_variance_share, 1)}</dd>
              <dt>Scoring variants in panel</dt>
              <dd className="num">{fmtFraction(sc.fraction_scoring_variants_in_panel, 1)}</dd>
            </dl>
          ) : (
            <p className="small muted">Not measured.</p>
          )}
        </div>
      </div>

      <h4 className="subhead">Harmonisation</h4>
      <div className="grid-2">
        <div>
          <dl className="kv small">
            <dt>Matched</dt>
            <dd>
              <strong className="num">
                {fmtInt(h?.n_matched)} / {fmtInt(h?.n_variants)}
              </strong>{" "}
              variants ({fmtFraction(h?.fraction_matched, 1)}); {fmtFraction(h?.fraction_abs_weight_matched, 1)} of
              absolute weight
            </dd>
            <dt>Located</dt>
            <dd className="num">{fmtInt(h?.n_located)}</dd>
            <dt>Top-5% weight variants missing</dt>
            <dd className="num">{fmtInt(h?.top5pct_weight_variants_missing)}</dd>
            <dt>Allele mismatch</dt>
            <dd className="num">{fmtFraction(h?.allele_mismatch_fraction, 1)}</dd>
            <dt>Position matching</dt>
            <dd>{h?.position_matching ? "yes" : "no"}</dd>
          </dl>
          {h?.notes && h.notes.length > 0 ? (
            <ul className="small" style={{ paddingLeft: 18 }}>
              {h.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Variant status</th>
                  <th scope="col" className="r">
                    Count
                  </th>
                  <th scope="col" className="r">
                    Weight lost
                  </th>
                </tr>
              </thead>
              <tbody>
                {nonzero.map(([k, n]) => {
                  const lost = h?.weight_loss_by_status?.[k];
                  return (
                    <tr key={k}>
                      <th scope="row">{humanise(k)}</th>
                      <td className="r">{fmtInt(n)}</td>
                      <td className="r">{isNum(lost) ? fmtFraction(lost, 1) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {zero.length > 0 ? (
            <p className="tiny muted" style={{ marginTop: 6 }}>
              Zero: {zero.map(humanise).join(", ")}.
            </p>
          ) : null}
          {loss.length > 0 ? (
            <div
              className="mini-bars"
              style={{ marginTop: 8 }}
              aria-label="Share of absolute score weight lost, by status"
            >
              {loss.map(([k, v]) => (
                <LossRow key={k} label={humanise(k)} value={v} />
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <h4 className="subhead">
        ClawBio gwas-prs cross-check <ContextOnlyLabel>CONTEXT ONLY</ContextOnlyLabel>
      </h4>
      {gp ? (
        <dl className="kv small">
          <dt>Variants compared</dt>
          <dd className="num">{fmtInt(gp.variants)}</dd>
          <dt>Agreement</dt>
          <dd>
            {gp.agree === true ? (
              <span>
                <IconCheck size={12} /> partial sums agree
              </span>
            ) : gp.agree === false ? (
              <span>
                <IconX size={12} /> partial sums differ
              </span>
            ) : (
              <span className="muted">not assessable</span>
            )}
          </dd>
          {isNum(gp.prsguard_partial_sum) ? (
            <>
              <dt>Partial sums</dt>
              <dd className="num">
                PRSGuard {fmtNum(gp.prsguard_partial_sum, 6)} · gwas-prs {fmtNum(gp.gwas_prs_partial_sum, 6)}
              </dd>
            </>
          ) : null}
          {gp.detail ? (
            <>
              <dt>Detail</dt>
              <dd>{gp.detail}</dd>
            </>
          ) : null}
          {gp.why_not_primary ? (
            <>
              <dt>Why not the primary scorer</dt>
              <dd>{gp.why_not_primary}</dd>
            </>
          ) : null}
        </dl>
      ) : (
        <p className="small muted">Not run.</p>
      )}
    </div>
  );
}

function LossRow({ label, value }: { label: string; value: number }) {
  return (
    <>
      <span className="small">{label}</span>
      <span className="bar-track" aria-hidden="true">
        <span
          className="bar-fill"
          style={{ display: "block", width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: "#a8201a" }}
        />
      </span>
      <span className="num small">{fmtFraction(value, 1)}</span>
    </>
  );
}

/* ------------------------------------------------------------------ applicability */

const CLAIMS: { key: "raw_score" | "standardized_score" | "percentile" | "absolute_risk"; label: string }[] = [
  { key: "raw_score", label: "Raw score" },
  { key: "standardized_score", label: "Standardized score" },
  { key: "percentile", label: "Percentile" },
  { key: "absolute_risk", label: "Absolute risk" },
];

function ApplicabilityTab({ c }: { c: Candidate }) {
  const g = c.gate;
  const used = Object.entries(g.evidence_used ?? {});
  const missing = g.evidence_missing ?? [];
  return (
    <div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <StatusBadge status={g.status} size="lg" />
        {g.primary_reason ? (
          <span>
            primary reason <CodeChip code={g.primary_reason.code} /> from rule{" "}
            <strong className="mono">{g.primary_reason.rule}</strong>
          </span>
        ) : (
          <span>every applicable rule passed</span>
        )}
      </div>
      {g.primary_reason ? (
        <div className="callout warn">
          <div>
            <p style={{ marginBottom: 4 }}>
              <strong>{g.primary_reason.meaning || reasonMeaning(g.primary_reason.code)}</strong>
            </p>
            <p className="small">{g.primary_reason.detail}</p>
          </div>
        </div>
      ) : null}

      <h4 className="subhead">Allowed claims</h4>
      <ul className="code-list" style={{ listStyle: "none", padding: 0, margin: 0, gap: 8 }}>
        {CLAIMS.map((cl) => {
          const ok = g.allowed_claims?.[cl.key] === true;
          return (
            <li key={cl.key}>
              <span className={`badge ${ok ? "pass" : "neutral"}`}>
                {ok ? <IconCheck size={12} /> : <IconX size={12} />}
                {cl.label}: {ok ? "allowed" : "not allowed"}
              </span>
            </li>
          );
        })}
      </ul>

      <h4 className="subhead">Rule trace (evaluated in order)</h4>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Question</th>
              <th scope="col">Outcome</th>
              <th scope="col">Effect</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {(g.rule_trace ?? []).map((r) => (
              <tr
                key={r.rule}
                className={r.outcome === "fail" ? "row-fail" : r.outcome === "not_applicable" ? "row-na" : undefined}
              >
                <th scope="row" className="nowrap">
                  <span className="mono">{r.rule}</span>
                  <div className="tiny muted">{r.name}</div>
                </th>
                <td style={{ minWidth: 200 }}>{r.question}</td>
                <td>
                  <StatusBadge status={r.outcome} />
                </td>
                <td>
                  {r.effect ? <StatusBadge status={r.effect} /> : <span className="muted">—</span>}
                  {r.outcome === "fail" && (r.codes ?? []).length > 0 ? (
                    <div style={{ marginTop: 4 }}>
                      <CodeList codes={r.codes} />
                    </div>
                  ) : null}
                </td>
                <td className="small" style={{ minWidth: 220 }}>
                  {r.detail}
                  {r.outcome !== "fail" && (r.codes ?? []).length > 0 ? (
                    <div className="tiny muted">guards: {(r.codes ?? []).join(", ")}</div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid-2" style={{ marginTop: 12 }}>
        <div>
          <h4 className="subhead">What would change the result</h4>
          {(g.what_would_change_result ?? []).length === 0 ? (
            <p className="small muted">Nothing to change: the score is already SUPPORTED.</p>
          ) : (
            <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
              {(g.what_would_change_result ?? []).map((w, i) => (
                <li key={i} style={{ marginBottom: 6 }}>
                  <span className="mono">{w.rule}</span> <CodeChip code={w.code} />: {w.change}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="subhead">Evidence missing</h4>
          {missing.length === 0 ? (
            <p className="small muted">None recorded.</p>
          ) : (
            <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
              {missing.map((m, i) => (
                <li key={i}>{typeof m === "string" ? m : JSON.stringify(m)}</li>
              ))}
            </ul>
          )}
          <dl className="kv small" style={{ marginTop: 10 }}>
            <dt>Calibration version</dt>
            <dd className="mono">{g.calibration_version ?? "—"}</dd>
            {g.provenance ? (
              <>
                <dt>Gate</dt>
                <dd>
                  {g.provenance.gate} v{g.provenance.gate_version} ({g.schema})
                </dd>
              </>
            ) : null}
          </dl>
        </div>
      </div>

      {used.length > 0 ? (
        <Disclosure summary={`Evidence the gate used (${used.length} fields)`}>
          <div className="table-wrap">
            <table className="data">
              <tbody>
                {used.map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row" className="mono small">
                      {k}
                    </th>
                    <td className="mono small">
                      {typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ population evidence */

function PopulationTab({ c, personGroup }: { c: Candidate; personGroup: string | null }) {
  const pe = c.population_evidence;
  const checks = pe?.consistency_checks ?? [];
  return (
    <div>
      <h4 className="subhead">Ancestry of participants at each stage (PGS Catalog)</h4>
      <AncestryStageChart stages={pe?.stages ?? {}} />

      <h4 className="subhead" style={{ marginTop: 22 }}>
        Recruitment countries
      </h4>
      <WorldMap countries={pe?.countries ?? []} note={pe?.countries_note} />

      <h4 className="subhead" style={{ marginTop: 22 }}>
        Evaluation units ({fmtInt(pe?.evaluation_units?.length ?? 0)} (publication, sample set) pairs)
      </h4>
      <EvaluationUnitsTable
        units={pe?.evaluation_units ?? []}
        publications={pe?.publications ?? {}}
        personGroup={personGroup}
      />

      {checks.length > 0 ? (
        <Disclosure
          summary={`Catalog consistency audit (${checks.filter((x) => x.status === "pass").length} pass, ${checks.filter((x) => x.status !== "pass").length} other)`}
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Status</th>
                  <th scope="col">Blocking</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((k) => (
                  <tr key={k.check_id}>
                    <th scope="row" className="mono small">
                      {k.check_id}
                    </th>
                    <td className="small">{k.kind}</td>
                    <td>
                      <StatusBadge
                        status={k.status === "pass" ? "pass" : k.status === "fail" ? "fail" : "not_applicable"}
                      >
                        {k.status}
                      </StatusBadge>
                    </td>
                    <td className="small">{k.blocking ? "yes" : "no"}</td>
                    <td className="small">{k.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ literature & provenance */

function LiteratureTab({ c, result }: { c: Candidate; result: PrsGuardResult }) {
  return (
    <div>
      <LiteraturePanel lit={result.literature_context} pgsId={c.pgs_id} />
      <h4 className="subhead" style={{ marginTop: 22 }}>
        equity-scorer: genetic distance between the person&apos;s reference group and the score&apos;s development
        cohort
      </h4>
      <EquityScorerPanel ctx={c.context?.equity_scorer} />
      <h4 className="subhead" style={{ marginTop: 22 }}>
        PGS Catalog provenance (recorded responses)
      </h4>
      <CatalogProvenance candidate={c} />
    </div>
  );
}
