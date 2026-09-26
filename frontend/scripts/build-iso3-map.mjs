#!/usr/bin/env node
// Generates lib/geo/iso3.json from the equity-lit-auditor country reference table.
//
//   node scripts/build-iso3-map.mjs <countries.csv> <out.json>
//
// Output: { "<ISO3>": { "n": "<ISO numeric, 3 digits>", "name": "...", "lat": 0, "lon": 0 } }
// The ISO numeric code is the `id` used by world-atlas countries-110m.json; lat/lon (country
// centroid from the same table) positions bubbles, including for countries too small for the
// 1:110m geometry (e.g. Singapore, Hong Kong). The generated file is committed; this script
// only needs re-running when the reference table changes.

import { readFileSync, writeFileSync } from "node:fs";

const [, , src, out] = process.argv;
if (!src || !out) {
  console.error("usage: build-iso3-map.mjs <countries.csv> <out.json>");
  process.exit(2);
}

const lines = readFileSync(src, "utf8").split(/\r?\n/).filter(Boolean);
const header = lines[0].split(",");
const col = (name) => {
  const i = header.indexOf(name);
  if (i < 0) throw new Error(`column ${name} missing`);
  return i;
};
const [iIso3, iNum, iName, iLat, iLon] = ["iso3", "iso_numeric", "name", "lat", "lon"].map(col);

const map = {};
for (const line of lines.slice(1)) {
  if (line.includes('"')) throw new Error(`quoted CSV fields are not supported: ${line}`);
  const f = line.split(",");
  const iso3 = f[iIso3].trim();
  if (!/^[A-Z]{3}$/.test(iso3)) continue;
  map[iso3] = {
    n: f[iNum].trim().padStart(3, "0"),
    name: f[iName].trim(),
    lat: Number(f[iLat]),
    lon: Number(f[iLon]),
  };
}

const sorted = Object.fromEntries(
  Object.keys(map)
    .sort()
    .map((k) => [k, map[k]]),
);
writeFileSync(out, JSON.stringify(sorted) + "\n");
console.log(`wrote ${Object.keys(sorted).length} countries to ${out}`);
