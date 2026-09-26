"use client";

import { useRef, useState, type MouseEvent } from "react";
import type { StageComposition } from "@/lib/types";
import { ancestryMeta, sortCodes } from "@/lib/ancestry";
import { fmtInt } from "@/lib/format";
import { Disclosure } from "./Disclosure";

type StageKey = "gwas" | "development" | "evaluation";

const STAGES: { key: StageKey; name: string; sub: string }[] = [
  { key: "gwas", name: "GWAS", sub: "source association study" },
  { key: "development", name: "Development", sub: "score construction / tuning" },
  { key: "evaluation", name: "Evaluation", sub: "performance testing" },
];

function textOn(hex: string): string {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.33 ? "#15171b" : "#ffffff";
}

export function segFill(code: string): string {
  const m = ancestryMeta(code);
  if (code === "NR") {
    return `repeating-linear-gradient(135deg, ${m.color}, ${m.color} 4px, #c4c2ba 4px, #c4c2ba 6px)`;
  }
  if (m.code === "MAE" || m.code === "MAO") {
    return `repeating-linear-gradient(45deg, ${m.color}, ${m.color} 5px, rgba(255,255,255,0.35) 5px, rgba(255,255,255,0.35) 7px)`;
  }
  return m.color;
}

function stageUnit(key: StageKey, s: StageComposition): string {
  if (key === "evaluation") {
    return `${fmtInt(s.sample_set_count)} (publication, sample set) pairs`;
  }
  return s.n_individuals != null ? `N = ${fmtInt(s.n_individuals)} individuals` : "N not reported";
}

interface Tip {
  left: number;
  top: number;
  lines: string[];
}

export function AncestryStageChart({ stages }: { stages: Partial<Record<StageKey, StageComposition>> }) {
  const [tip, setTip] = useState<Tip | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const present = sortCodes(
    Array.from(new Set(STAGES.flatMap((s) => Object.keys(stages[s.key]?.distribution_pct ?? {})))),
  );

  const showTip = (e: MouseEvent<HTMLElement>, lines: string[]) => {
    const host = ref.current?.getBoundingClientRect();
    const r = e.currentTarget.getBoundingClientRect();
    if (!host) return;
    setTip({ left: r.left - host.left + r.width / 2, top: r.top - host.top, lines });
  };

  return (
    <div>
      <div className="stage-chart" ref={ref} style={{ position: "relative" }} onMouseLeave={() => setTip(null)}>
        {STAGES.map(({ key, name, sub }) => {
          const s = stages[key];
          const dist = s?.distribution_pct ?? {};
          const codes = sortCodes(Object.keys(dist)).filter((c) => (dist[c] ?? 0) > 0);
          const reported = s && s.reported !== false && codes.length > 0;
          const label = reported
            ? `${name}: ${codes.map((c) => `${c} ${dist[c].toFixed(1)}%`).join(", ")}; ${stageUnit(key, s)}`
            : `${name}: ancestry not reported in the PGS Catalog`;
          return (
            <div className="stage-row" key={key}>
              <div>
                <div className="stage-name">{name}</div>
                <div className="stage-n">{sub}</div>
                <div className="stage-n">
                  {s ? stageUnit(key, s) : "not available"}
                  {key === "evaluation" && reported ? (
                    <>
                      <br />% of pairs, not of individuals
                    </>
                  ) : reported ? (
                    <>
                      <br />% of individuals
                    </>
                  ) : null}
                </div>
              </div>
              {reported ? (
                <div className="stage-bar" role="img" aria-label={label}>
                  {codes.map((c) => {
                    const pct = dist[c];
                    const meta = ancestryMeta(c);
                    const nInd = key === "evaluation" ? s?.n_individuals_by_code?.[c] : undefined;
                    const pairs = key === "evaluation" ? s?.sample_sets_by_code?.[c] : undefined;
                    const lines = [
                      `${c} — ${meta.label}`,
                      `${pct.toFixed(1)}% of ${key === "evaluation" ? "(publication, sample set) pairs" : "individuals"}`,
                      ...(pairs != null ? [`${fmtInt(pairs)} pair(s)`] : []),
                      ...(nInd != null ? [`N = ${fmtInt(nInd)} individuals`] : []),
                    ];
                    const inside = pct >= 11;
                    return (
                      <div
                        key={c}
                        className="seg"
                        style={{
                          width: `${pct}%`,
                          background: segFill(c),
                          color: textOn(meta.color),
                        }}
                        onMouseEnter={(e) => showTip(e, lines)}
                        title={lines.join("\n")}
                      >
                        {inside ? `${c} ${Math.round(pct)}%` : ""}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="stage-bar empty">Not reported in the PGS Catalog</div>
              )}
            </div>
          );
        })}
        {tip ? (
          <div className="tooltip" style={{ left: tip.left, top: tip.top }} role="status">
            {tip.lines.map((l, i) => (
              <div key={i}>{i === 0 ? <strong>{l}</strong> : l}</div>
            ))}
          </div>
        ) : null}
      </div>

      <ul className="legend" aria-label="Ancestry legend">
        {present.map((c) => (
          <li key={c}>
            <span className="swatch" style={{ background: segFill(c) }} aria-hidden="true" />
            <span className="mono">{c}</span> {ancestryMeta(c).label}
          </li>
        ))}
      </ul>

      <Disclosure summary="Show as table">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Stage</th>
                <th scope="col">Code</th>
                <th scope="col" className="r">
                  %
                </th>
                <th scope="col" className="r">
                  Individuals
                </th>
                <th scope="col" className="r">
                  Pairs
                </th>
              </tr>
            </thead>
            <tbody>
              {STAGES.flatMap(({ key, name }) => {
                const s = stages[key];
                const dist = s?.distribution_pct ?? {};
                const codes = sortCodes(Object.keys(dist));
                if (!s || codes.length === 0) {
                  return [
                    <tr key={key}>
                      <th scope="row">{name}</th>
                      <td colSpan={4} className="muted">
                        not reported
                      </td>
                    </tr>,
                  ];
                }
                return codes.map((c) => (
                  <tr key={`${key}-${c}`}>
                    <th scope="row">{name}</th>
                    <td className="mono">{c}</td>
                    <td className="r">{dist[c].toFixed(1)}</td>
                    <td className="r">
                      {key === "evaluation"
                        ? fmtInt(s.n_individuals_by_code?.[c])
                        : codes.length === 1
                          ? fmtInt(s.n_individuals)
                          : "—"}
                    </td>
                    <td className="r">{key === "evaluation" ? fmtInt(s.sample_sets_by_code?.[c]) : "—"}</td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
        <p className="tiny muted" style={{ marginTop: 6 }}>
          GWAS and development are reported by the PGS Catalog as % of individuals. Evaluation is reported per
          (publication, sample set) pair, so its percentages count pairs, not people; the individuals column sums sample
          sizes per code and can include overlapping cohorts.
        </p>
      </Disclosure>
    </div>
  );
}
