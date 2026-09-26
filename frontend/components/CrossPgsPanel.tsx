import type { CrossPgs, CrossPgsPair } from "@/lib/types";
import { fmtInt, fmtInterval, fmtNum, fmtSigned } from "@/lib/format";
import { StatusBadge } from "./Badges";
import { IconInfo } from "./Icons";

/** Person's percentile gap vs the reference 95% gap range, on a fixed −100…100 axis. */
function GapStrip({ pair }: { pair: CrossPgsPair }) {
  const W = 220;
  const H = 34;
  const pad = 8;
  const x = (v: number) => pad + ((Math.max(-100, Math.min(100, v)) + 100) / 200) * (W - 2 * pad);
  const [lo, hi] = pair.reference_gap_95;
  const g = pair.person_percentile_gap;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      role="img"
      aria-label={`Person's gap ${fmtSigned(g, 1)} percentile points; reference 95% range ${fmtInterval(pair.reference_gap_95)}`}
      style={{ maxWidth: "100%", height: "auto" }}
    >
      <line x1={pad} x2={W - pad} y1={14} y2={14} stroke="#e3e2dc" strokeWidth={2} />
      <line x1={x(0)} x2={x(0)} y1={6} y2={22} stroke="#c8c7bf" />
      <rect x={x(lo)} y={9} width={Math.max(1, x(hi) - x(lo))} height={10} rx={2} fill="#2a78d6" opacity={0.25} />
      <line x1={x(g)} x2={x(g)} y1={4} y2={24} stroke="#15171b" strokeWidth={2.5} />
      <text x={pad} y={H - 1} fontSize={9.5} fill="#62615c">
        −100
      </text>
      <text x={x(0)} y={H - 1} fontSize={9.5} fill="#62615c" textAnchor="middle">
        0
      </text>
      <text x={W - pad} y={H - 1} fontSize={9.5} fill="#62615c" textAnchor="end">
        +100
      </text>
    </svg>
  );
}

export function CrossPgsPanel({ cross, primary }: { cross: CrossPgs; primary: string | null }) {
  const pairs = cross?.pairs ?? [];
  return (
    <div className="panel">
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <StatusBadge status={cross?.status ?? "NOT_COMPARABLE"} size="lg" />
        <span>{cross?.detail}</span>
      </div>
      <div className="callout" role="note">
        <IconInfo size={16} />
        <div>
          <p style={{ marginBottom: 4 }}>
            Only <strong>SUPPORTED</strong> scores are compared (compared here:{" "}
            <span className="mono">{cross?.compared?.length ? cross.compared.join(", ") : "none"}</span>). The check
            reports agreement; it <strong>never changes the primary score</strong>
            {primary ? (
              <>
                {" "}
                (<span className="mono">{primary}</span>, chosen by the fixed rule &ldquo;highest pre-ranked
                SUPPORTED&rdquo;)
              </>
            ) : null}{" "}
            and never releases anything the gate withheld.
          </p>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Rule: {cross?.rule}.
          </p>
        </div>
      </div>

      {pairs.length > 0 ? (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Pair</th>
                <th scope="col">Percentiles</th>
                <th scope="col">Person gap vs reference 95% gap range</th>
                <th scope="col" className="r">
                  Reference r
                </th>
                <th scope="col">Variant overlap</th>
                <th scope="col">Shared source GWAS</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={`${p.a}-${p.b}`}>
                  <th scope="row" className="mono nowrap">
                    {p.a}
                    <br />
                    {p.b}
                  </th>
                  <td className="nowrap num">
                    {fmtNum(p.percentiles[p.a], 1)}
                    <br />
                    {fmtNum(p.percentiles[p.b], 1)}
                    <div className="tiny muted">{p.reference_group} reference</div>
                  </td>
                  <td style={{ minWidth: 230 }}>
                    <GapStrip pair={p} />
                    <div className="tiny">
                      gap <strong className="num">{fmtSigned(p.person_percentile_gap, 1)}</strong> · reference 95%{" "}
                      <span className="num">{fmtInterval(p.reference_gap_95)}</span> · n = {fmtInt(p.n_reference)}
                    </div>
                  </td>
                  <td className="r">{fmtNum(p.reference_correlation, 2)}</td>
                  <td className="small" style={{ minWidth: 150 }}>
                    Jaccard {fmtNum(p.variant_overlap_jaccard, 4)} ({fmtInt(p.shared_variants)} shared)
                    <div className="tiny muted">
                      weighted:{" "}
                      {Object.entries(p.weighted_overlap)
                        .map(([k, v]) => `${k} ${fmtNum(v, 3)}`)
                        .join(" · ")}
                    </div>
                  </td>
                  <td className="small">{p.shared_source_gwas.length ? p.shared_source_gwas.join(", ") : "none"}</td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {pairs.length > 0 ? (
        <ul className="small" style={{ paddingLeft: 18, marginTop: 10 }}>
          {pairs.map((p) => (
            <li key={`${p.a}-${p.b}-note`}>
              <span className="mono">
                {p.a} × {p.b}
              </span>
              : {p.dependence_note}
            </li>
          ))}
        </ul>
      ) : (
        <p className="small muted" style={{ marginBottom: 0 }}>
          No pairs to compare: at least two SUPPORTED scores are needed.
        </p>
      )}
    </div>
  );
}
