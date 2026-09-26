#!/usr/bin/env node
// Smoke check for the static export in out/ (run after `npm run build`).
//  - key statements are present in the prerendered HTML
//  - demo data and map geometry are exported
//  - every demo result respects the release invariant the UI relies on:
//    a percentile / standardized score is present only when the gate released it.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

const out = path.resolve(process.argv[2] ?? "out");
const failures = [];
const check = (ok, msg) => {
  if (!ok) failures.push(msg);
};

const read = (p) => readFileSync(path.join(out, p), "utf8");
const html = existsSync(path.join(out, "index.html")) ? read("index.html") : "";
const how = existsSync(path.join(out, "how-it-works", "index.html")) ? read("how-it-works/index.html") : "";
check(html, "out/index.html missing");
check(how, "out/how-it-works/index.html missing");

const REQUIRED = [
  "Can this PGS result actually be interpreted for this person?",
  "RESEARCH SOFTWARE / PROTOTYPE",
  "Genetic reference placement is not ethnicity or identity",
  "Geography is not ancestry",
  "No percentile is released unless the evidence gate supports it",
  "CONTEXT ONLY",
];
for (const s of REQUIRED) check(html.includes(s), `index.html lacks: ${s}`);
for (const s of ["Agent orchestration", "Deterministic science", "CONTEXT ONLY", "The agent may not"]) {
  check(how.includes(s), `how-it-works lacks: ${s}`);
}

check(existsSync(path.join(out, "geo", "countries-110m.json")), "geo/countries-110m.json missing");
check(existsSync(path.join(out, "geo", "WORLD-ATLAS-LICENSE")), "geo/WORLD-ATLAS-LICENSE missing");

const demoDir = path.join(out, "demo");
const index = JSON.parse(readFileSync(path.join(demoDir, "cases.json"), "utf8"));
for (const c of index.cases) {
  const f = path.join(demoDir, `case_${c.id}.json`);
  if (!existsSync(f)) {
    failures.push(`demo case ${c.id} missing`);
    continue;
  }
  const r = JSON.parse(readFileSync(f, "utf8"));
  check(r.schema === "prsguard.result.v1", `case ${c.id}: schema ${r.schema}`);
  for (const cand of r.candidates ?? []) {
    const it = cand.interpretation ?? {};
    for (const k of ["percentile", "standardized_score", "raw_score"]) {
      const v = it[k] ?? {};
      if (!v.released) check(v.value == null, `case ${c.id} ${cand.pgs_id}: ${k} has a value but is not released`);
      if (v.released)
        check(cand.gate?.allowed_claims?.[k] === true, `case ${c.id} ${cand.pgs_id}: ${k} released but not allowed`);
    }
    check(!it.absolute_risk?.released, `case ${c.id} ${cand.pgs_id}: absolute risk released`);
    if (cand.gate?.status !== "SUPPORTED") {
      check(!it.percentile?.released, `case ${c.id} ${cand.pgs_id}: percentile released for ${cand.gate?.status}`);
    }
  }
}

const extra = readdirSync(demoDir).filter((f) => !/^case_[A-Z]\.json$|^cases\.json$/.test(f));
check(extra.length === 0, `unexpected files in demo/: ${extra.join(", ")}`);

if (failures.length) {
  console.error(`smoke check FAILED (${failures.length}):\n - ${failures.join("\n - ")}`);
  process.exit(1);
}
console.log(
  `smoke check passed: ${REQUIRED.length} key statements, ${index.cases.length} demo cases, map geometry present.`,
);
