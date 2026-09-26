"use client";

import { useMemo, useRef, useState, type PointerEvent } from "react";
import type { PlacementPlot } from "@/lib/types";
import {
  ancestryMeta,
  POP_LABEL,
  SUPERPOP_LABEL,
  SUPERPOP_SHAPE,
  SUPERPOPS,
  type MarkerShape,
  type Superpop,
} from "@/lib/ancestry";
import { fmtInt } from "@/lib/format";

const W = 640;
const H = 470;
const M = { l: 54, r: 16, t: 14, b: 46 };
const ADMIXED_COLOR = "#8a8883";
const INK = "#15171b";

type AxisPair = "12" | "13" | "23";
const AXES: Record<AxisPair, [number, number]> = { "12": [0, 1], "13": [0, 2], "23": [1, 2] };

type Kind = "reference" | "admixed" | "bootstrap" | "target";

interface Pt {
  sx: number;
  sy: number;
  kind: Kind;
  title: string;
  sub: string;
  group?: string;
}

export function shapePath(shape: MarkerShape, cx: number, cy: number, r: number): string {
  switch (shape) {
    case "square": {
      const s = r * 0.9;
      return `M${cx - s},${cy - s}h${2 * s}v${2 * s}h${-2 * s}z`;
    }
    case "triangle": {
      const h = r * 1.25;
      return `M${cx},${cy - h}L${cx + h * 0.95},${cy + h * 0.7}L${cx - h * 0.95},${cy + h * 0.7}z`;
    }
    case "triangle-down": {
      const h = r * 1.25;
      return `M${cx},${cy + h}L${cx + h * 0.95},${cy - h * 0.7}L${cx - h * 0.95},${cy - h * 0.7}z`;
    }
    case "diamond": {
      const d = r * 1.3;
      return `M${cx},${cy - d}L${cx + d},${cy}L${cx},${cy + d}L${cx - d},${cy}z`;
    }
    default:
      return `M${cx - r},${cy}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`;
  }
}

function niceTicks(min: number, max: number, count = 5): number[] {
  const span = max - min;
  if (!(span > 0)) return [min];
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export function MarkerIcon({ shape, color, hollow = false }: { shape: MarkerShape; color: string; hollow?: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path
        d={shapePath(shape, 7, 7, 4.6)}
        fill={hollow ? "none" : color}
        stroke={hollow ? color : "#fcfcfb"}
        strokeWidth={hollow ? 1.4 : 1}
      />
    </svg>
  );
}

export function PcaPlot({
  plot,
  varianceExplained,
  personLabel,
}: {
  plot: PlacementPlot;
  varianceExplained?: number[];
  personLabel: string;
}) {
  const [axes, setAxes] = useState<AxisPair>("12");
  const [showAdmixed, setShowAdmixed] = useState(true);
  const [showBoot, setShowBoot] = useState(true);
  const [hover, setHover] = useState<{ left: number; top: number; pt: Pt } | null>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const [ix, iy] = AXES[axes];

  const scales = useMemo(() => {
    const all: number[][] = [
      ...plot.reference.map((p) => p.pc),
      ...plot.admixed_reference.map((p) => p.pc),
      ...plot.bootstrap,
      plot.target,
    ];
    const xs = all.map((p) => p[ix]);
    const ys = all.map((p) => p[iy]);
    const pad = (a: number, b: number) => {
      const d = (b - a || 1) * 0.06;
      return [a - d, b + d] as const;
    };
    const [x0, x1] = pad(Math.min(...xs), Math.max(...xs));
    const [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
    const sx = (v: number) => M.l + ((v - x0) / (x1 - x0)) * (W - M.l - M.r);
    const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b);
    return { sx, sy, xt: niceTicks(x0, x1), yt: niceTicks(y0, y1) };
  }, [plot, ix, iy]);

  const points = useMemo(() => {
    const { sx, sy } = scales;
    const ref: Pt[] = plot.reference.map((p) => ({
      sx: sx(p.pc[ix]),
      sy: sy(p.pc[iy]),
      kind: "reference",
      group: p.group,
      title: `${p.pop} — ${POP_LABEL[p.pop] ?? "1000 Genomes population"}`,
      sub: `1000 Genomes reference group ${p.group}`,
    }));
    const adm: Pt[] = plot.admixed_reference.map((p) => ({
      sx: sx(p.pc[ix]),
      sy: sy(p.pc[iy]),
      kind: "admixed",
      title: `${p.pop} — ${POP_LABEL[p.pop] ?? "1000 Genomes population"}`,
      sub: "Admixed 1000 Genomes population (shown for context; not a placement group)",
    }));
    const boot: Pt[] = plot.bootstrap.map((p, i) => ({
      sx: sx(p[ix]),
      sy: sy(p[iy]),
      kind: "bootstrap",
      title: `Bootstrap replicate ${i + 1}`,
      sub: "The person re-projected on resampled sites (placement uncertainty)",
    }));
    const tgt: Pt = {
      sx: sx(plot.target[ix]),
      sy: sy(plot.target[iy]),
      kind: "target",
      title: personLabel,
      sub: "Projected position of this genotype",
    };
    return { ref, adm, boot, tgt };
  }, [plot, scales, ix, iy, personLabel]);

  const { groupCounts, groupPops, admixedPops } = useMemo(() => {
    const m: Record<string, number> = {};
    const pops: Record<string, Set<string>> = {};
    for (const p of plot.reference) {
      m[p.group] = (m[p.group] ?? 0) + 1;
      (pops[p.group] ??= new Set()).add(p.pop);
    }
    const adm = Array.from(new Set(plot.admixed_reference.map((p) => p.pop))).sort();
    return {
      groupCounts: m,
      groupPops: Object.fromEntries(Object.entries(pops).map(([g, s]) => [g, Array.from(s).sort()])),
      admixedPops: adm,
    };
  }, [plot]);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    const frame = frameRef.current;
    if (!svg || !frame) return;
    const rect = svg.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    const vy = ((e.clientY - rect.top) / rect.height) * H;
    const found: { p: Pt | null; d: number } = { p: null, d: 14 * 14 };
    const consider = (p: Pt) => {
      const d = (p.sx - vx) ** 2 + (p.sy - vy) ** 2;
      if (d < found.d) {
        found.d = d;
        found.p = p;
      }
    };
    consider(points.tgt);
    if (!found.p) {
      points.ref.forEach(consider);
      if (showAdmixed) points.adm.forEach(consider);
      if (showBoot) points.boot.forEach(consider);
    }
    const b = found.p;
    if (!b) {
      setHover(null);
      return;
    }
    const fr = frame.getBoundingClientRect();
    setHover({
      left: rect.left - fr.left + (b.sx / W) * rect.width,
      top: rect.top - fr.top + (b.sy / H) * rect.height,
      pt: b,
    });
  };

  const ve = (i: number) =>
    varianceExplained && typeof varianceExplained[i] === "number"
      ? ` (${(varianceExplained[i] * 100).toFixed(1)}% of variance)`
      : "";

  const ariaLabel = `Principal components ${ix + 1} and ${iy + 1} of the 1000 Genomes reference (${fmtInt(
    plot.reference.length,
  )} core-group individuals${showAdmixed ? `, ${fmtInt(plot.admixed_reference.length)} admixed-population individuals` : ""}) with this person's projected position${
    showBoot ? ` and ${plot.bootstrap.length} bootstrap replicates` : ""
  }.`;

  return (
    <div>
      <div className="plot-toolbar">
        <fieldset className="segmented" aria-label="Principal component axes">
          <legend className="visually-hidden">Axes</legend>
          {(Object.keys(AXES) as AxisPair[]).map((k) => (
            <label key={k}>
              <input type="radio" name="pca-axes" value={k} checked={axes === k} onChange={() => setAxes(k)} />
              PC{AXES[k][0] + 1} / PC{AXES[k][1] + 1}
            </label>
          ))}
        </fieldset>
        <label className="check">
          <input type="checkbox" checked={showAdmixed} onChange={(e) => setShowAdmixed(e.target.checked)} />
          Admixed populations
        </label>
        <label className="check">
          <input type="checkbox" checked={showBoot} onChange={(e) => setShowBoot(e.target.checked)} />
          Bootstrap cloud
        </label>
      </div>

      <div className="plot-frame" ref={frameRef}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={ariaLabel}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {/* grid & axes */}
          {scales.xt.map((t) => (
            <g key={`x${t}`}>
              <line x1={scales.sx(t)} x2={scales.sx(t)} y1={M.t} y2={H - M.b} stroke="#ebeae4" />
              <text x={scales.sx(t)} y={H - M.b + 16} fontSize={11} textAnchor="middle" fill="#62615c">
                {t}
              </text>
            </g>
          ))}
          {scales.yt.map((t) => (
            <g key={`y${t}`}>
              <line x1={M.l} x2={W - M.r} y1={scales.sy(t)} y2={scales.sy(t)} stroke="#ebeae4" />
              <text x={M.l - 8} y={scales.sy(t) + 4} fontSize={11} textAnchor="end" fill="#62615c">
                {t}
              </text>
            </g>
          ))}
          <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="none" stroke="#c8c7bf" />
          <text x={(M.l + W - M.r) / 2} y={H - 8} fontSize={12} textAnchor="middle" fill="#3f4147">
            PC{ix + 1}
            {ve(ix)}
          </text>
          <text
            x={14}
            y={(M.t + H - M.b) / 2}
            fontSize={12}
            textAnchor="middle"
            fill="#3f4147"
            transform={`rotate(-90 14 ${(M.t + H - M.b) / 2})`}
          >
            PC{iy + 1}
            {ve(iy)}
          </text>

          {/* admixed (behind), hollow & muted */}
          {showAdmixed ? (
            <g opacity={0.8}>
              {points.adm.map((p, i) => (
                <circle key={i} cx={p.sx} cy={p.sy} r={2.9} fill="none" stroke={ADMIXED_COLOR} strokeWidth={1} />
              ))}
            </g>
          ) : null}

          {/* core reference groups: colour + shape */}
          <g>
            {points.ref.map((p, i) => {
              const g = (p.group ?? "EUR") as Superpop;
              const shape = SUPERPOP_SHAPE[g] ?? "circle";
              return (
                <path
                  key={i}
                  d={shapePath(shape, p.sx, p.sy, 3.1)}
                  fill={ancestryMeta(g).color}
                  fillOpacity={0.78}
                  stroke="#fcfcfb"
                  strokeWidth={0.6}
                />
              );
            })}
          </g>

          {/* bootstrap uncertainty cloud */}
          {showBoot ? (
            <g>
              {points.boot.map((p, i) => (
                <circle key={i} cx={p.sx} cy={p.sy} r={1.8} fill={INK} fillOpacity={0.45} />
              ))}
            </g>
          ) : null}

          {/* the person */}
          <g>
            <circle cx={points.tgt.sx} cy={points.tgt.sy} r={11} fill="none" stroke="#fcfcfb" strokeWidth={4} />
            <circle cx={points.tgt.sx} cy={points.tgt.sy} r={11} fill="none" stroke={INK} strokeWidth={2} />
            <path
              d={`M${points.tgt.sx - 16},${points.tgt.sy}h8M${points.tgt.sx + 8},${points.tgt.sy}h8M${points.tgt.sx},${
                points.tgt.sy - 16
              }v8M${points.tgt.sx},${points.tgt.sy + 8}v8`}
              stroke={INK}
              strokeWidth={2}
            />
            <circle cx={points.tgt.sx} cy={points.tgt.sy} r={3} fill={INK} />
          </g>

          {hover ? (
            <circle
              cx={hover.pt.sx}
              cy={hover.pt.sy}
              r={hover.pt.kind === "target" ? 14 : 6}
              fill="none"
              stroke={INK}
              strokeWidth={1.5}
            />
          ) : null}
        </svg>
        {hover ? (
          <div className="tooltip" style={{ left: hover.left, top: hover.top }} role="status">
            <strong>{hover.pt.title}</strong>
            <br />
            {hover.pt.sub}
          </div>
        ) : null}
      </div>

      <ul className="legend" aria-label="Plot legend">
        {SUPERPOPS.map((g) => (
          <li key={g} title={(groupPops[g] ?? []).map((p) => `${p}: ${POP_LABEL[p] ?? p}`).join("\n")}>
            <MarkerIcon shape={SUPERPOP_SHAPE[g]} color={ancestryMeta(g).color} />
            {SUPERPOP_LABEL[g]}
            <span className="muted">
              n={groupCounts[g] ?? 0} · {(groupPops[g] ?? []).join(" ")}
            </span>
          </li>
        ))}
        <li>
          <MarkerIcon shape="circle" color={ADMIXED_COLOR} hollow />
          Admixed 1000G populations, not placement groups
          <span className="muted">
            n={plot.admixed_reference.length} · {admixedPops.join(" ")}
          </span>
        </li>
        <li>
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <circle cx="4" cy="5" r="1.6" fill={INK} fillOpacity={0.5} />
            <circle cx="9" cy="8" r="1.6" fill={INK} fillOpacity={0.5} />
            <circle cx="6" cy="10.5" r="1.6" fill={INK} fillOpacity={0.5} />
          </svg>
          Bootstrap replicates (n={plot.bootstrap.length})
        </li>
        <li>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r="5.5" fill="none" stroke={INK} strokeWidth="1.6" />
            <circle cx="8" cy="8" r="1.8" fill={INK} />
          </svg>
          <strong>This person</strong>
        </li>
      </ul>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        Hover a point for its 1000 Genomes population code. PCA is refit on the sites observed in this file, so axes
        differ between cases.
      </p>
    </div>
  );
}
