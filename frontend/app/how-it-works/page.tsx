import type { Metadata } from "next";
import { readFileSync } from "node:fs";
import path from "node:path";
import Link from "next/link";
import type { PrsGuardResult } from "@/lib/types";
import { ActorBadge, ContextOnlyLabel, StatusBadge } from "@/components/Badges";
import { IconCheck, IconX } from "@/components/Icons";

export const metadata: Metadata = {
  title: "How PRSGuard works",
  description:
    "Architecture of PRSGuard: orchestration (LLM agent or scripted CLI), deterministic science, and context-only evidence, and what orchestration may and may not do.",
};

/** Rule texts are read from a committed demo result at build time so the page always matches the pipeline. */
function loadRules() {
  try {
    const file = path.join(process.cwd(), "public", "demo", "case_B.json");
    const r = JSON.parse(readFileSync(file, "utf8")) as PrsGuardResult;
    const gate = (r.candidates[0]?.gate.rule_trace ?? []).map((t) => ({
      rule: t.rule,
      name: t.name,
      question: t.question,
    }));
    return {
      gate,
      eligibility: r.router?.eligibility_rules ?? [],
      ranking: r.router?.ranking_rules ?? [],
      gateVersion: r.candidates[0]?.gate.provenance?.gate_version ?? "",
      calibration: r.reproducibility?.calibration_version ?? "",
    };
  } catch {
    return { gate: [], eligibility: [], ranking: [], gateVersion: "", calibration: "" };
  }
}

type Lane = "agent" | "det" | "ctx";
interface Box {
  n: string;
  title: string;
  detail: string;
  tool?: string;
}
type Row = { kind: "cells"; cells: Partial<Record<Lane, Box[]>> } | { kind: "divider"; text: string; wall?: boolean };

const LANE_NAME: Record<Lane, string> = {
  agent: "Orchestration (LLM agent or scripted CLI)",
  det: "Deterministic science",
  ctx: "Context only",
};

const ROWS: Row[] = [
  {
    kind: "cells",
    cells: {
      agent: [
        {
          n: "1",
          title: "Receive the request, read the file locally",
          detail: "Trait, sex, optional declared build. The genotype never leaves the machine.",
        },
      ],
      det: [
        {
          n: "2",
          title: "Resolve the genome build",
          detail: "rsID anchor positions + declaration; never assumed.",
          tool: "genotypes.resolve_build",
        },
      ],
    },
  },
  {
    kind: "cells",
    cells: {
      agent: [
        {
          n: "3",
          title: "Resolve the trait",
          detail: "Free text → ontology term and an explicit scope; narrower sub-phenotypes excluded.",
          tool: "PGS Catalog /trait/search",
        },
        {
          n: "4",
          title: "Search the PGS Catalog",
          detail: "Collect score, publication and evaluation metadata (snapshot or live).",
          tool: "PGS Catalog /score/search",
        },
      ],
      det: [
        {
          n: "5",
          title: "Router: eligibility, pre-rank, FREEZE",
          detail: "Rules E1–E8 and R1–R5 pick the top k; the candidate set gets a digest.",
          tool: "prsguard.router",
        },
      ],
    },
  },
  { kind: "divider", text: "CANDIDATES FROZEN — no personal genotype has been scored yet" },
  {
    kind: "cells",
    cells: {
      det: [
        {
          n: "6",
          title: "Reference placement (once per person)",
          detail:
            "PCA projection vs 1000 Genomes with bootstrap stability → RESOLVED / INTERMEDIATE / UNSTABLE / UNRESOLVED.",
          tool: "reference.projection",
        },
        {
          n: "7",
          title: "Harmonise and compute raw scores",
          detail: "Allele, strand and build checks; scoreability r against the published score.",
          tool: "prsguard.harmonize",
        },
        {
          n: "8",
          title: "Evidence audit + reference distribution",
          detail: "Catalog consistency checks; the score distribution in the placed reference group.",
          tool: "catalog + reference.distribution",
        },
        {
          n: "9",
          title: "prs-applicability-gate",
          detail: "Rules G1–G12 per candidate → SUPPORTED / RAW_ONLY / ABSTAIN and the allowed claims.",
          tool: "skills/prs-applicability-gate",
        },
        {
          n: "10 · tool",
          title: "Cross-PGS check, primary score",
          detail: "SUPPORTED scores only; primary = highest pre-ranked SUPPORTED (fixed rule).",
          tool: "prsguard.cross_pgs",
        },
      ],
      ctx: [
        {
          n: "·",
          title: "equity-scorer",
          detail: "FST between the person's reference group and the score's cohorts; representation index.",
          tool: "ClawBio equity-scorer",
        },
        {
          n: "·",
          title: "equity-lit-auditor",
          detail: "How the papers behind each score report and sample populations (live Europe PMC + PGS Catalog).",
          tool: "equity-lit-auditor",
        },
      ],
    },
  },
  {
    kind: "divider",
    text: "CONTEXT ONLY — attached to the report, never an input to the applicability gate",
    wall: true,
  },
  {
    kind: "cells",
    cells: {
      agent: [
        {
          n: "10 · report",
          title: "Explain the result",
          detail:
            "Report what the gate released, why, and what would change it — in plain language, without adding claims.",
        },
      ],
    },
  },
];

const MAY = [
  "Resolve the trait text to an ontology term and state the scope it used",
  "Search the PGS Catalog and collect score, publication and evaluation metadata",
  "Plan the run and call the deterministic tools in order",
  "Attach clearly labelled context (equity-scorer, equity-lit-auditor) to the report",
  "Explain in plain language what was released, the reason codes, and what would change the result",
];

const MAY_NOT = [
  "Add, drop or reorder candidates after the freeze, or pick a different primary score",
  "Override, relax or re-interpret any gate rule or threshold",
  "Compute or show a percentile, standardized score or risk that the gate withheld",
  "Convert a polygenic score into absolute risk or a diagnosis",
  "Use literature equity or FST context as an input to any gate decision",
  "Describe genetic reference placement as ethnicity, race or identity",
  "Send genotype data anywhere other than the machine it was read on",
];

const LANES: Lane[] = ["agent", "det", "ctx"];

function Diagram() {
  const nRows = ROWS.length;
  return (
    <div
      className="arch"
      role="img"
      aria-label="Architecture: three lanes. Orchestration (an LLM agent, or the deterministic scripted PRSGuard CLI orchestrator) receives the request, resolves the trait, searches the PGS Catalog and explains the result. Deterministic science resolves the build, applies the router rules and freezes candidates, then performs placement, harmonisation, evidence audit, reference distribution, the applicability gate and the cross-PGS check. Context only: equity-scorer and equity-lit-auditor, attached to the report and never used by the gate."
    >
      {LANES.map((l, i) => (
        <div key={l} className={`lane-head ${l}`} style={{ gridColumn: i + 1, gridRow: 1 }}>
          {l === "ctx" ? "CONTEXT ONLY" : LANE_NAME[l]}
          <small>
            {l === "agent"
              ? "gathers evidence, calls tools, explains; never decides applicability"
              : l === "det"
                ? "fixed code decides what may be claimed"
                : "never used by the applicability gate"}
          </small>
        </div>
      ))}
      {LANES.map((l, i) => (
        <div
          key={`bg-${l}`}
          className={`lane-bg ${l}`}
          style={{ gridColumn: i + 1, gridRow: `2 / span ${nRows}` }}
          aria-hidden="true"
        />
      ))}
      {ROWS.map((r, i) =>
        r.kind === "divider" ? (
          <div key={`d${i}`} className={`arch-divider ${r.wall ? "ctx-wall" : ""}`} style={{ gridRow: i + 2 }}>
            {r.text}
          </div>
        ) : (
          LANES.filter((l) => r.cells[l]?.length).map((l) => (
            <div key={`c${i}-${l}`} className="arch-cell" style={{ gridRow: i + 2, gridColumn: LANES.indexOf(l) + 1 }}>
              {(r.cells[l] ?? []).map((b, j) => (
                <div key={j} className={`arch-box ${l}`}>
                  <span className={`badge lane-chip ${l}`}>{LANE_NAME[l]}</span>
                  <span className="n">{b.n === "·" ? "context" : `step ${b.n}`}</span>
                  <strong>{b.title}</strong>
                  <span className="muted">{b.detail}</span>
                  {b.tool ? <span className="mono tiny muted">{b.tool}</span> : null}
                </div>
              ))}
            </div>
          ))
        ),
      )}
    </div>
  );
}

export default function HowItWorksPage() {
  const rules = loadRules();
  return (
    <>
      <section className="hero" aria-labelledby="hiw-title">
        <p className="eyebrow">Methodology</p>
        <h1 id="hiw-title">How PRSGuard works</h1>
        <p className="thesis">
          <strong>
            Orchestration gathers evidence and calls tools. Deterministic code alone decides what claims are allowed.
          </strong>{" "}
          Orchestration is performed by an LLM agent when one drives PRSGuard, and otherwise by the deterministic
          scripted PRSGuard CLI orchestrator (as in every demo result here); both are bound by the same rules.
          PRSGuard starts from the trait, not from the genome: candidate scores are selected and frozen before any
          personal genotype is scored, and each one must then pass an evidence gate before anything is interpreted.
        </p>
      </section>

      <section className="section" aria-labelledby="arch-h">
        <div className="section-head">
          <h2 id="arch-h">Architecture</h2>
          <p>Three lanes, read top to bottom. Every result page shows the same steps in its orchestration trace.</p>
        </div>
        <div className="panel">
          <div className="trace-legend">
            <ActorBadge actor="ORCHESTRATION" />
            <ActorBadge actor="DETERMINISTIC_DECISION" />
            <ContextOnlyLabel />
          </div>
          <Diagram />
        </div>
      </section>

      <section className="section" aria-labelledby="may-h">
        <div className="section-head">
          <h2 id="may-h">What orchestration (LLM agent or scripted CLI) may and may not do</h2>
        </div>
        <div className="may-grid">
          <div className="panel">
            <h3 className="subhead">Orchestration may</h3>
            <ul className="may-list">
              {MAY.map((m) => (
                <li key={m}>
                  <span style={{ color: "var(--ok-text)" }}>
                    <IconCheck size={14} />
                  </span>
                  {m}
                </li>
              ))}
            </ul>
          </div>
          <div className="panel">
            <h3 className="subhead">Orchestration may not</h3>
            <ul className="may-list">
              {MAY_NOT.map((m) => (
                <li key={m}>
                  <span style={{ color: "var(--no-text)" }}>
                    <IconX size={14} />
                  </span>
                  {m}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="out-h">
        <div className="section-head">
          <h2 id="out-h">Three outcomes per score</h2>
          <p>No percentile is released unless the evidence gate supports it. Absolute risk is never provided.</p>
        </div>
        <div className="table-wrap panel" style={{ padding: 0 }}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Gate status</th>
                <th scope="col">Raw score</th>
                <th scope="col">Standardized score</th>
                <th scope="col">Percentile</th>
                <th scope="col">Absolute risk</th>
                <th scope="col">Typical cause</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">
                  <StatusBadge status="SUPPORTED" />
                </th>
                <td>released</td>
                <td>released</td>
                <td>released, with intervals</td>
                <td>never</td>
                <td style={{ minWidth: 260 }}>
                  Scoreable, stably placed, and with evidence of association (95% CI above the null) in an evaluation
                  of the person&apos;s reference group. A research reportability state: not evidence of clinically
                  useful discrimination or calibration, and not a clinical recommendation.
                </td>
              </tr>
              <tr>
                <th scope="row">
                  <StatusBadge status="RAW_ONLY" />
                </th>
                <td>released</td>
                <td>withheld</td>
                <td>withheld</td>
                <td>never</td>
                <td style={{ minWidth: 260 }}>
                  No stable placement, or no relevant evaluation for the person&apos;s reference group.
                </td>
              </tr>
              <tr>
                <th scope="row">
                  <StatusBadge status="ABSTAIN" />
                </th>
                <td>withheld</td>
                <td>withheld</td>
                <td>withheld</td>
                <td>never</td>
                <td style={{ minWidth: 260 }}>
                  The computable score does not represent the published one, or inputs are invalid.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {rules.gate.length > 0 ? (
        <section className="section" aria-labelledby="gate-h">
          <div className="section-head">
            <h2 id="gate-h">The applicability gate</h2>
            <p>
              prs-applicability-gate {rules.gateVersion ? `v${rules.gateVersion}` : ""}
              {rules.calibration ? `, calibration ${rules.calibration}` : ""}. Every rule is evaluated for each
              candidate: ABSTAIN if any ABSTAIN rule failed, else RAW_ONLY if any RAW_ONLY rule failed, else SUPPORTED.
            </p>
          </div>
          <div className="table-wrap panel" style={{ padding: 0 }}>
            <table className="data rules-table">
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Name</th>
                  <th scope="col">Question</th>
                </tr>
              </thead>
              <tbody>
                {rules.gate.map((g) => (
                  <tr key={g.rule}>
                    <td>{g.rule}</td>
                    <td className="mono small">{g.name}</td>
                    <td>{g.question}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {rules.eligibility.length > 0 ? (
        <section className="section" aria-labelledby="router-h">
          <div className="section-head">
            <h2 id="router-h">The router: eligibility and pre-ranking</h2>
            <p>Applied to PGS Catalog metadata only. The person&apos;s genotype is never an input.</p>
          </div>
          <div className="grid-2">
            <div className="panel">
              <h3 className="subhead">Eligibility</h3>
              <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                {rules.eligibility.map((r) => (
                  <li key={r} style={{ marginBottom: 6 }}>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <h3 className="subhead">Pre-ranking</h3>
              <ol className="small" style={{ paddingLeft: 18, margin: 0 }}>
                {rules.ranking.map((r) => (
                  <li key={r} style={{ marginBottom: 6 }}>
                    {r}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>
      ) : null}

      <section className="section" aria-labelledby="priv-h">
        <div className="section-head">
          <h2 id="priv-h">Privacy model</h2>
        </div>
        <div className="panel">
          <ul className="may-list">
            <li>
              <IconCheck size={14} /> This website is a static export. It loads only its own files (demo results, map
              geometry).
            </li>
            <li>
              <IconCheck size={14} /> Uploads are analysed only by a PRSGuard server running on your own machine (
              <code>prsguard serve</code>, bound to 127.0.0.1). This website never receives genomic data.
            </li>
            <li>
              <IconCheck size={14} /> The local server deletes the uploaded file after responding; it sends only trait
              text and PGS IDs to the PGS Catalog.
            </li>
            <li>
              <IconCheck size={14} /> No analytics, cookies or third-party scripts.
            </li>
          </ul>
          <p className="small" style={{ marginTop: 12, marginBottom: 0 }}>
            <Link href="/">Back to the analysis</Link>
          </p>
        </div>
      </section>
    </>
  );
}
