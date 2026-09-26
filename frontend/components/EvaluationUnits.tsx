"use client";

import { useId, useMemo, useState } from "react";
import type { EvaluationMetric, EvaluationUnit, Publication } from "@/lib/types";
import { ancestryMeta, sortCodes } from "@/lib/ancestry";
import { fmtInt, fmtNum, isNum, pgpUrl } from "@/lib/format";
import { IconCheck, IconDash, IconX } from "./Icons";
import { segFill } from "./AncestryStageChart";

function ciText(m: EvaluationMetric): string {
  if (isNum(m.ci_lower) && isNum(m.ci_upper)) return `[${fmtNum(m.ci_lower, 2)}, ${fmtNum(m.ci_upper, 2)}]`;
  return "no CI";
}

function NullVerdict({ m }: { m: EvaluationMetric }) {
  if (m.informative === true) {
    return (
      <span title={`95% CI excludes the null value ${m.null ?? ""}`} style={{ color: "var(--ok-text)" }}>
        <IconCheck size={12} /> CI excludes null{isNum(m.null) ? ` (${m.null})` : ""}
      </span>
    );
  }
  if (m.informative === false) {
    return (
      <span title="95% CI includes the null value" style={{ color: "var(--no-text)" }}>
        <IconX size={12} /> CI includes null{isNum(m.null) ? ` (${m.null})` : ""}
      </span>
    );
  }
  return (
    <span className="muted" title="No CI or no null value defined for this metric">
      <IconDash size={12} /> not assessable
    </span>
  );
}

export function EvaluationUnitsTable({
  units,
  publications,
  personGroup,
}: {
  units: EvaluationUnit[];
  publications: Record<string, Publication>;
  personGroup?: string | null;
}) {
  const codes = useMemo(() => sortCodes(Array.from(new Set(units.map((u) => u.code)))), [units]);
  const [code, setCode] = useState<string>("ALL");
  const [withMetrics, setWithMetrics] = useState(false);
  const selectId = useId();

  const rows = units.filter((u) => (code === "ALL" || u.code === code) && (!withMetrics || u.metrics.length > 0));

  return (
    <div>
      <div className="plot-toolbar">
        <div className="field" style={{ gridAutoFlow: "column", alignItems: "center", gap: 8 }}>
          <label htmlFor={selectId}>Ancestry</label>
          <select
            id={selectId}
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            style={{ width: "auto" }}
          >
            <option value="ALL">All codes ({units.length})</option>
            {codes.map((c) => (
              <option key={c} value={c}>
                {c}
                {c === personGroup ? " (person's reference group)" : ""} ({units.filter((u) => u.code === c).length})
              </option>
            ))}
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={withMetrics} onChange={(e) => setWithMetrics(e.target.checked)} />
          Only units reporting a metric
        </label>
        <span className="small muted">{rows.length} shown</span>
      </div>

      <div className="table-wrap scroll-y">
        <table className="data">
          <caption className="visually-hidden">
            PGS Catalog evaluation units: one row per (publication, sample set) pair
          </caption>
          <thead>
            <tr>
              <th scope="col">Publication</th>
              <th scope="col">Sample set</th>
              <th scope="col">Ancestry</th>
              <th scope="col" className="r">
                N
              </th>
              <th scope="col" className="r">
                Cases
              </th>
              <th scope="col" className="r">
                % male
              </th>
              <th scope="col">Metrics (estimate, 95% CI, vs null)</th>
              <th scope="col">Countries</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u, i) => {
              const pub = publications[u.pgp_id];
              return (
                <tr key={`${u.pgp_id}-${u.pss_id}-${u.code}-${i}`}>
                  <td className="nowrap">
                    <a href={pgpUrl(u.pgp_id)} target="_blank" rel="noreferrer noopener" className="mono">
                      {u.pgp_id}
                    </a>
                    {pub ? (
                      <div className="tiny muted">
                        {pub.first_author} {pub.date_publication?.slice(0, 4)}
                      </div>
                    ) : null}
                  </td>
                  <td className="mono nowrap">
                    {u.pss_id}
                    {u.pooled ? <div className="tiny muted">pooled</div> : null}
                  </td>
                  <td className="nowrap">
                    <span
                      className="swatch"
                      style={{ background: segFill(u.code), marginRight: 5, verticalAlign: -1 }}
                      aria-hidden="true"
                    />
                    <span className="mono" title={ancestryMeta(u.code).label}>
                      {u.code}
                    </span>
                  </td>
                  <td className="r">{fmtInt(u.n)}</td>
                  <td className="r">{u.cases != null ? fmtInt(u.cases) : "—"}</td>
                  <td className="r">
                    {isNum(u.percent_male) ? fmtNum(u.percent_male, 1) : <span className="muted">NR</span>}
                  </td>
                  <td style={{ minWidth: 260 }}>
                    {u.metrics.length === 0 ? (
                      <span className="muted">no metric reported</span>
                    ) : (
                      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 3 }}>
                        {u.metrics.map((m, j) => (
                          <li key={j} className="small">
                            <strong>{m.name}</strong> {fmtNum(m.estimate, 3)} <span className="muted">{ciText(m)}</span>{" "}
                            <NullVerdict m={m} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="small" style={{ minWidth: 140 }}>
                    {u.countries.length > 4
                      ? `${u.countries.slice(0, 4).join(", ")} +${u.countries.length - 4} more`
                      : u.countries.join(", ") || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        &ldquo;CI excludes null&rdquo; is the Catalog-derived <code>informative</code> flag used by the gate (G9): the
        metric&apos;s 95% CI does not contain its null value (e.g. OR/HR = 1, AUROC = 0.5).
      </p>
    </div>
  );
}
