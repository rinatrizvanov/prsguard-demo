import type { Candidate, Interval, PercentileValue, ReleasedValue } from "@/lib/types";
import { fmtInterval, fmtNum, fmtInt, isNum } from "@/lib/format";
import { CodeList } from "./Badges";
import { IconBlock, IconLock, IconShield } from "./Icons";

/**
 * A value is shown ONLY when the result JSON releases it (released === true and a finite value).
 * Nothing here computes, estimates or back-fills a withheld quantity.
 */
export function releasedNumber(v: ReleasedValue | null | undefined): number | null {
  return v && v.released === true && isNum(v.value) ? v.value : null;
}

export const GATE_SENTENCE = "No percentile is released unless the evidence gate supports it.";

function withheldCodes(c: Candidate, item: string): string[] {
  const w = c.interpretation.withheld;
  if (w && Array.isArray(w.because) && (w.items ?? []).includes(item)) return w.because;
  return c.gate.reason_codes ?? [];
}

function Withheld({ codes }: { codes: string[] }) {
  return (
    <>
      <span className="tile-state">
        <IconLock size={16} /> Withheld
      </span>
      <div className="small">
        <span className="muted">because </span>
        <CodeList codes={codes} empty="gate status does not allow this claim" />
      </div>
    </>
  );
}

export function InterpretationTiles({ candidate }: { candidate: Candidate }) {
  const it = candidate.interpretation;
  const raw = releasedNumber(it.raw_score);
  const z = releasedNumber(it.standardized_score);
  const pct = releasedNumber(it.percentile);

  return (
    <div>
      <div className="tiles" role="list" aria-label={`Reference interpretation for ${candidate.pgs_id}`}>
        <div role="listitem" className={`tile ${raw !== null ? "released" : "withheld"}`}>
          <div className="tile-label">Raw score</div>
          {raw !== null ? (
            <>
              <div className="tile-value num">{fmtNum(raw, 4)}</div>
              <p className="meaning">{it.raw_score.meaning ?? "sum of effect weight × dosage over matched variants"}</p>
            </>
          ) : (
            <Withheld codes={withheldCodes(candidate, "raw_score")} />
          )}
        </div>

        <div role="listitem" className={`tile ${z !== null ? "released" : "withheld"}`}>
          <div className="tile-label">Standardized score</div>
          {z !== null ? (
            <>
              <div className="tile-value num">
                {z > 0 ? "+" : ""}
                {fmtNum(z, 3)} <span className="small muted">SD</span>
              </div>
              <p className="meaning">{it.standardized_score.meaning}</p>
            </>
          ) : (
            <Withheld codes={withheldCodes(candidate, "standardized_score")} />
          )}
        </div>

        <div role="listitem" className={`tile percentile-tile ${pct !== null ? "released" : "withheld"}`}>
          <div className="tile-label">Percentile</div>
          {pct !== null ? (
            <>
              <div className="tile-value num">
                {fmtNum(pct, 1)}
                <span className="small muted"> / 100</span>
              </div>
              <p className="meaning">
                of the <strong>{it.percentile.reference_group ?? "?"}</strong> 1000 Genomes reference (n ={" "}
                {fmtInt(it.percentile.reference_n)}); {it.percentile.meaning ?? "not a probability of disease"}
              </p>
            </>
          ) : (
            <Withheld codes={withheldCodes(candidate, "percentile")} />
          )}
        </div>

        <div role="listitem" className="tile never">
          <div className="tile-label">Absolute risk</div>
          <span className="tile-state">
            <IconBlock size={16} /> Not provided
          </span>
          <p className="meaning">
            {it.absolute_risk?.meaning ??
              "never provided: requires calibrated incidence data, age, and a validated absolute-risk model"}
          </p>
        </div>
      </div>

      {pct !== null ? <PercentileDetail p={it.percentile} value={pct} /> : null}

      <p className="gate-sentence">
        <IconShield size={15} /> {GATE_SENTENCE}
      </p>
    </div>
  );
}

function PercentileDetail({ p, value }: { p: PercentileValue; value: number }) {
  const subs = Object.entries(p.subpopulation_percentiles ?? {});
  return (
    <div className="grid-2" style={{ marginTop: 12 }}>
      <div>
        <h4 className="subhead">Percentile uncertainty</h4>
        <PercentileStrip value={value} p={p} />
        <dl className="kv small" style={{ marginTop: 8 }}>
          <dt>Finite reference panel CI</dt>
          <dd className="num">{fmtInterval(p.ci_panel)}</dd>
          <dt>Missing-variant interval</dt>
          <dd className="num">{fmtInterval(p.missing_variant_interval)}</dd>
          <dt>Combined interval</dt>
          <dd className="num">
            <strong>{fmtInterval(p.combined_interval)}</strong>
          </dd>
          <dt>Reference</dt>
          <dd>
            {p.reference_group ?? "?"} · n = {fmtInt(p.reference_n)} reference individuals
          </dd>
        </dl>
      </div>
      {subs.length > 0 ? (
        <div>
          <h4 className="subhead">Within-group reference populations</h4>
          <p className="small muted" style={{ marginBottom: 6 }}>
            The same score placed against each 1000 Genomes population of the group (sensitivity check G12).
          </p>
          <div className="table-wrap">
            <table className="data subpop-table">
              <thead>
                <tr>
                  <th scope="col">Population</th>
                  <th scope="col" className="r">
                    Percentile
                  </th>
                  <th scope="col" className="r">
                    Panel CI
                  </th>
                  <th scope="col" className="r">
                    n
                  </th>
                </tr>
              </thead>
              <tbody>
                {subs.map(([pop, s]) => (
                  <tr key={pop}>
                    <th scope="row" className="mono">
                      {pop}
                    </th>
                    <td className="r">{fmtNum(s.percentile, 1)}</td>
                    <td className="r">{fmtInterval(s.ci_panel)}</td>
                    <td className="r">{fmtInt(s.n_reference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 0–100 strip with the three released intervals and the released point estimate. */
export function PercentileStrip({ value, p }: { value: number; p: PercentileValue }) {
  const W = 380;
  const L = 112;
  const R = 12;
  const rowH = 22;
  const rows: { label: string; iv?: Interval; tone: string }[] = [
    { label: "Panel CI", iv: p.ci_panel, tone: "#2a78d6" },
    { label: "Missing variants", iv: p.missing_variant_interval, tone: "#7a8599" },
    { label: "Combined", iv: p.combined_interval, tone: "#15171b" },
  ];
  const H = rows.length * rowH + 30;
  const x = (v: number) => L + (Math.max(0, Math.min(100, v)) / 100) * (W - L - R);
  const ticks = [0, 25, 50, 75, 100];
  const label = `Percentile ${value.toFixed(1)}; panel CI ${fmtInterval(p.ci_panel)}; missing-variant interval ${fmtInterval(
    p.missing_variant_interval,
  )}; combined interval ${fmtInterval(p.combined_interval)}.`;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      style={{ width: "100%", maxWidth: 480, height: "auto" }}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={4} y2={H - 22} stroke="#ebeae4" strokeWidth={1} />
          <text x={x(t)} y={H - 8} fontSize={12} textAnchor="middle" fill="#62615c">
            {t}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const y = 8 + i * rowH + rowH / 2;
        return (
          <g key={r.label}>
            <text x={L - 8} y={y + 4} fontSize={12.5} textAnchor="end" fill="#3f4147">
              {r.label}
            </text>
            {r.iv && isNum(r.iv[0]) && isNum(r.iv[1]) ? (
              <>
                <line
                  x1={x(r.iv[0])}
                  x2={x(r.iv[1])}
                  y1={y}
                  y2={y}
                  stroke={r.tone}
                  strokeWidth={6}
                  strokeLinecap="round"
                  opacity={0.85}
                />
                {r.iv[0] === r.iv[1] ? <circle cx={x(r.iv[0])} cy={y} r={4} fill={r.tone} /> : null}
              </>
            ) : (
              <text x={L} y={y + 4} fontSize={11} fill="#62615c">
                not reported
              </text>
            )}
          </g>
        );
      })}
      <line x1={x(value)} x2={x(value)} y1={2} y2={H - 22} stroke="#15171b" strokeWidth={2} />
      <circle cx={x(value)} cy={2 + 2} r={3.5} fill="#15171b" />
    </svg>
  );
}

/** Candidate × claim matrix: what the gate released. Reads allowed/released flags only. */
export function ReleaseMatrix({ candidates, primary }: { candidates: Candidate[]; primary: string | null }) {
  const items: { key: "raw_score" | "standardized_score" | "percentile"; label: string }[] = [
    { key: "raw_score", label: "Raw score" },
    { key: "standardized_score", label: "Standardized" },
    { key: "percentile", label: "Percentile" },
  ];
  return (
    <div className="table-wrap">
      <table className="data">
        <caption className="visually-hidden">What the gate released for each candidate score</caption>
        <thead>
          <tr>
            <th scope="col">Candidate</th>
            {items.map((i) => (
              <th scope="col" key={i.key}>
                {i.label}
              </th>
            ))}
            <th scope="col">Absolute risk</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.pgs_id}>
              <th scope="row">
                <span className="mono">{c.pgs_id}</span>
                {c.pgs_id === primary ? (
                  <span className="badge primary-tag" style={{ marginLeft: 6 }}>
                    PRIMARY
                  </span>
                ) : null}
              </th>
              {items.map((i) => {
                const v = releasedNumber(c.interpretation[i.key]);
                return (
                  <td key={i.key} className="num">
                    {v !== null ? (
                      i.key === "percentile" ? (
                        <strong>{fmtNum(v, 1)}</strong>
                      ) : (
                        fmtNum(v, i.key === "raw_score" ? 4 : 3)
                      )
                    ) : (
                      <span className="muted">
                        <IconLock size={12} /> withheld
                      </span>
                    )}
                  </td>
                );
              })}
              <td className="muted">not provided</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
