import r from "../demo_result.json";

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
const fmt = (x, d = 3) => (x === null || x === undefined ? null : Number(x).toFixed(d));
const evalSummary = (o) =>
  Object.entries(o || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ") || "none reported";

function Card({ c }) {
  const cov = c.coverage || {};
  const pub = (c.provenance && c.provenance.publication) || {};
  const api = (c.provenance && c.provenance.pgs_catalog_api) || {};
  const sf = (c.provenance && c.provenance.scoring_file) || {};
  const reason = c.unscoreable_reason || (c.gate && c.gate.output && c.gate.output.explanation) || "";
  const raw = fmt(c.released && c.released.raw_score);
  const pctValue = c.released && c.released.percentile;
  return (
    <div className={`card ${c.decision}`}>
      <div className="muted small">Pre-rank #{c.pre_rank}</div>
      <h3>
        {c.pgs_id} <span className="muted">{c.name}</span>
      </h3>
      <span className={`badge ${c.decision}`}>{c.decision}</span>
      <p className="reason">{reason}</p>
      <dl className="kv">
        <dt>Coverage</dt>
        <dd>
          {cov.usable_variants !== null && cov.usable_variants !== undefined
            ? `${cov.usable_variants} / ${cov.catalog_variants} variants (${(cov.fraction * 100).toFixed(1)}%)`
            : `not scoreable (0 / ${cov.catalog_variants})`}
        </dd>
        <dt>Evaluated in</dt>
        <dd>{evalSummary(c.evidence && c.evidence.evaluation_ancestry_units)}</dd>
        <dt>Raw score</dt>
        <dd>{raw !== null ? raw : "not released"}</dd>
        <dt>Percentile</dt>
        <dd>{pctValue !== null && pctValue !== undefined ? Number(pctValue).toFixed(1) : <b>WITHHELD</b>}</dd>
      </dl>
      <details>
        <summary>View evidence &amp; provenance</summary>
        <dl className="kv small">
          <dt>Publication</dt>
          <dd>
            {pub.pgp_id} · {pub.first_author} · {pub.journal}
          </dd>
          <dt>PMID / DOI</dt>
          <dd>
            {pub.pmid || "—"} / {pub.doi || "—"}
          </dd>
          <dt>Source GWAS</dt>
          <dd>{evalSummary(c.evidence && c.evidence.source_gwas_ancestry)}</dd>
          <dt>Gate</dt>
          <dd className="mono">
            {c.reason_code} ({c.gate && c.gate.rule_fired}) · thresholds{" "}
            {c.provenance && c.provenance.gate && c.provenance.gate.thresholds_version}
          </dd>
          <dt>Audit codes</dt>
          <dd className="mono">{(c.upstream_audit && c.upstream_audit.reason_codes.join(", ")) || "none"}</dd>
          <dt>PGS Catalog</dt>
          <dd className="mono">
            {api.mode} · release {api.catalog_release} · API {api.api_version}
          </dd>
          <dt>Scoring file</dt>
          <dd className="mono">
            {sf.filename} · sha256 {sf.sha256}
          </dd>
          <dt>Decision digest</dt>
          <dd className="mono">
            {c.decision_digest} {c.verified ? "(verified)" : "(not verified)"}
          </dd>
        </dl>
      </details>
    </div>
  );
}

export default function Page() {
  const search = r.candidate_search || {};
  const cmp = r.comparison || {};
  const status = r.cross_pgs_status || cmp.status;
  const primary = r.primary && r.primary.pgs_id;
  const cmpText =
    status === "NOT_COMPARABLE" && (cmp.eligible || []).length < 2
      ? "fewer than 2 candidates passed the gate."
      : cmp.status_rule;
  return (
    <main>
      <section className="hero">
        <h1>PRSGuard</h1>
        <div className="trait">{cap(r.request.trait)}</div>
        <div className="primaryline">
          Primary result: <b>{primary || "NONE"}</b>
        </div>
        <p>
          {primary
            ? "Highest pre-ranked candidate that passed the evidence gate."
            : "No candidate passed the evidence gate, so no percentile is released."}
        </p>
        <p className="muted small">No percentile is released unless the evidence gate supports it.</p>
      </section>

      <div className="grid">
        {r.candidates.map((c) => (
          <Card key={c.pgs_id} c={c} />
        ))}
      </div>

      <div className={`banner ${status}`}>
        <b>{status.replace("_", " ")}</b> — {cmpText}
      </div>

      <section className="selection">
        <div>
          {search.n_found} scores found → {search.n_eligible} eligible → top {(search.selected || []).length} selected
        </div>
        <div className="muted">Selection was fixed before personal scoring.</div>
        <details>
          <summary>Selection rules</summary>
          <ul className="small">
            {(search.rules || []).map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </details>
      </section>

      <p className="disclaimer">{r.disclaimer}</p>
    </main>
  );
}
