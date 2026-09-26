"use client";

import { useEffect, useId, useMemo, useRef, useState, type MouseEvent } from "react";
import { geoEqualEarth, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import type { CountryEvidence } from "@/lib/types";
import { assetUrl } from "@/lib/paths";
import { fmtCompact, fmtInt } from "@/lib/format";
import iso3Table from "@/lib/geo/iso3.json";
import { IconGlobe } from "./Icons";
import { Disclosure } from "./Disclosure";

interface IsoEntry {
  n: string;
  name: string;
  lat: number;
  lon: number;
}
const ISO3 = iso3Table as Record<string, IsoEntry>;

const W = 900;
const H = 440;
const BUBBLE = "#2a78d6";

type WorldFeatures = Feature<Geometry, { name?: string }>[];

let worldPromise: Promise<WorldFeatures> | null = null;
function loadWorld(): Promise<WorldFeatures> {
  if (!worldPromise) {
    worldPromise = fetch(assetUrl("/geo/countries-110m.json"), { cache: "force-cache" })
      .then((r) => {
        if (!r.ok) throw new Error(`world map: HTTP ${r.status}`);
        return r.json() as Promise<Topology>;
      })
      .then((topo) => {
        const obj = topo.objects.countries as GeometryCollection<{ name?: string }>;
        const fc = feature(topo, obj) as unknown as FeatureCollection<Geometry, { name?: string }>;
        return fc.features;
      })
      .catch((e: unknown) => {
        worldPromise = null;
        throw e;
      });
  }
  return worldPromise;
}

const STAGE_LABEL: Record<string, string> = {
  gwas: "GWAS",
  development: "Development",
  evaluation: "Evaluation",
};
const STAGE_ORDER = ["gwas", "development", "evaluation"];

export const GEOGRAPHY_NOTE =
  "Geography is not ancestry: countries are where participants were recruited. A multi-country sample's N is shown for each of its countries.";

interface Bubble {
  iso3: string;
  name: string;
  x: number;
  y: number;
  r: number;
  n: number;
  units: number;
  codes: string[];
  spellings: string[];
}

export function WorldMap({ countries, note }: { countries: CountryEvidence[]; note?: string }) {
  const stagesPresent = STAGE_ORDER.filter((s) => countries.some((c) => c.stage === s));
  const [stage, setStage] = useState<string>(
    stagesPresent.includes("evaluation") ? "evaluation" : (stagesPresent[0] ?? "evaluation"),
  );
  const [world, setWorld] = useState<WorldFeatures | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<{ b: Bubble; left: number; top: number } | null>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const radioName = useId();

  useEffect(() => {
    let alive = true;
    loadWorld()
      .then((f) => alive && setWorld(f))
      .catch((e: unknown) => alive && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  const projection = useMemo(
    () =>
      geoEqualEarth().fitExtent(
        [
          [8, 8],
          [W - 8, H - 8],
        ],
        { type: "Sphere" },
      ),
    [],
  );
  const path = useMemo(() => geoPath(projection), [projection]);

  const rows = useMemo(() => countries.filter((c) => c.stage === stage), [countries, stage]);
  const { bubbles, unmapped, activeIds } = useMemo(() => {
    // The Catalog records free-text country strings ("U.S.", "USA", "US"); rows that resolve to the
    // same ISO3 code are drawn as one bubble. The table below keeps the rows exactly as recorded.
    const byIso = new Map<string, Omit<Bubble, "r">>();
    const un: CountryEvidence[] = [];
    const ids = new Set<string>();
    for (const c of rows) {
      const e = c.iso3 ? ISO3[c.iso3] : undefined;
      const xy = e ? projection([e.lon, e.lat]) : null;
      if (!e || !xy || !c.iso3) {
        un.push(c);
        continue;
      }
      ids.add(e.n);
      const prev = byIso.get(c.iso3);
      if (prev) {
        prev.n += c.n;
        prev.units += c.units;
        prev.codes = Array.from(new Set([...prev.codes, ...c.codes]));
        prev.spellings.push(c.country);
      } else {
        byIso.set(c.iso3, {
          iso3: c.iso3,
          name: c.name ?? e.name,
          x: xy[0],
          y: xy[1],
          n: c.n,
          units: c.units,
          codes: [...c.codes],
          spellings: [c.country],
        });
      }
    }
    const mapped = Array.from(byIso.values());
    const maxN = Math.max(1, ...mapped.map((m) => m.n));
    const bs: Bubble[] = mapped.map((m) => ({ ...m, r: 2.5 + Math.sqrt(m.n / maxN) * 24 })).sort((a, b) => b.n - a.n);
    return { bubbles: bs, unmapped: un, activeIds: ids };
  }, [rows, projection]);

  const onEnter = (e: MouseEvent<SVGCircleElement>, b: Bubble) => {
    const host = frameRef.current?.getBoundingClientRect();
    const r = e.currentTarget.getBoundingClientRect();
    if (!host) return;
    setHover({ b, left: r.left - host.left + r.width / 2, top: r.top - host.top });
  };

  const noteText = note && note.startsWith("Geography is not ancestry") ? note : GEOGRAPHY_NOTE;
  const maxN = bubbles[0]?.n ?? 0;

  return (
    <div>
      <div className="plot-toolbar">
        <fieldset className="segmented">
          <legend className="visually-hidden">Stage</legend>
          {STAGE_ORDER.map((s) => {
            const n = countries.filter((c) => c.stage === s).length;
            return (
              <label key={s}>
                <input
                  type="radio"
                  name={radioName}
                  value={s}
                  checked={stage === s}
                  disabled={n === 0}
                  onChange={() => setStage(s)}
                />
                {STAGE_LABEL[s]} ({n})
              </label>
            );
          })}
        </fieldset>
        <span className="small muted">
          Bubble area proportional to recruited N per country (largest: {fmtCompact(maxN)})
        </span>
      </div>

      <div className="map-frame" ref={frameRef} onMouseLeave={() => setHover(null)}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Recruitment countries at the ${STAGE_LABEL[stage]} stage: ${bubbles.length} mapped countries. ${noteText}`}
        >
          <path d={path({ type: "Sphere" }) ?? undefined} fill="#f7fafc" stroke="#d9dee5" />
          {world
            ? world.map((f, i) => (
                <path
                  key={(f.id as string | undefined) ?? `f${i}`}
                  d={path(f) ?? undefined}
                  fill={f.id != null && activeIds.has(String(f.id)) ? "#d6e2f1" : "#e7e7e2"}
                  stroke="#ffffff"
                  strokeWidth={0.6}
                />
              ))
            : null}
          {bubbles.map((b) => (
            <circle
              key={b.iso3}
              cx={b.x}
              cy={b.y}
              r={b.r}
              fill={BUBBLE}
              fillOpacity={0.55}
              stroke="#ffffff"
              strokeWidth={1.5}
              onMouseEnter={(e) => onEnter(e, b)}
              onMouseLeave={() => setHover(null)}
            >
              <title>{`${b.name}: N = ${fmtInt(b.n)} (${b.units} sample-set mention(s); ${b.codes.join(", ")})`}</title>
            </circle>
          ))}
          {hover ? (
            <circle cx={hover.b.x} cy={hover.b.y} r={hover.b.r + 2} fill="none" stroke="#15171b" strokeWidth={1.5} />
          ) : null}
        </svg>
        {hover ? (
          <div className="tooltip" style={{ left: hover.left, top: hover.top }} role="status">
            <strong>{hover.b.name}</strong>
            <br />N = {fmtInt(hover.b.n)} recruited · {hover.b.units} sample-set mention(s)
            <br />
            ancestry codes: {hover.b.codes.join(", ") || "—"}
            {hover.b.spellings.length > 1 ? (
              <>
                <br />
                recorded as: {hover.b.spellings.map((x) => `“${x}”`).join(", ")}
              </>
            ) : null}
          </div>
        ) : null}
        {err ? (
          <div className="error-box" style={{ position: "absolute", left: 8, bottom: 8 }}>
            Map geometry unavailable ({err}); see the table below.
          </div>
        ) : null}
      </div>

      <p className="map-caption">
        <IconGlobe size={15} /> <span>{noteText}</span>
      </p>

      {unmapped.length > 0 ? (
        <p className="small" style={{ marginTop: 6 }}>
          <strong>Unmapped country strings</strong> (as recorded in the PGS Catalog; not placed on the map):{" "}
          {unmapped.map((u, i) => (
            <span key={`${u.country}-${i}`}>
              {i > 0 ? "; " : ""}
              <span className="mono">&ldquo;{u.country}&rdquo;</span> (N = {fmtInt(u.n)})
            </span>
          ))}
        </p>
      ) : null}

      <Disclosure summary={`Country table (${rows.length} ${STAGE_LABEL[stage].toLowerCase()} rows)`}>
        <div className="table-wrap scroll-y">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Country (as recorded)</th>
                <th scope="col">ISO3</th>
                <th scope="col" className="r">
                  N recruited
                </th>
                <th scope="col" className="r">
                  Sample sets
                </th>
                <th scope="col">Ancestry codes</th>
              </tr>
            </thead>
            <tbody>
              {[...rows]
                .sort((a, b) => b.n - a.n)
                .map((c, i) => (
                  <tr key={`${c.country}-${i}`}>
                    <th scope="row">{c.name ?? c.country}</th>
                    <td className="mono">{c.iso3 ?? <em className="muted">unmapped</em>}</td>
                    <td className="r">{fmtInt(c.n)}</td>
                    <td className="r">{fmtInt(c.units)}</td>
                    <td className="mono">{c.codes.join(", ")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </div>
  );
}
