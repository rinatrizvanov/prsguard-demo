import type { RouterInfo } from "@/lib/types";
import { fmtDate, fmtInt, fmtTimestamp, shortHash } from "@/lib/format";
import { Disclosure } from "./Disclosure";
import { IconSnowflake } from "./Icons";

function ruleText(rules: string[], code: string): string {
  return rules.find((r) => r.startsWith(`${code} `)) ?? code;
}

export function CandidateSelection({ router: raw }: { router: RouterInfo }) {
  // Tolerate partial router objects (e.g. from a newer or older local server) without inventing values.
  const router: RouterInfo = {
    ...raw,
    selected: raw.selected ?? [],
    eligible: raw.eligible ?? [],
    eligibility_rules: raw.eligibility_rules ?? [],
    ranking_rules: raw.ranking_rules ?? [],
    excluded_summary: raw.excluded_summary ?? {
      n_excluded: raw.n_found - raw.n_eligible,
      scores_failing_rule: {},
      excluded_only_by_engineering_E8: 0,
    },
    options: raw.options ?? { sex: null, build: null, max_variants: null, top_k: raw.selected?.length ?? 0 },
    trait: raw.trait ?? { query: "", status: "unknown" },
  };
  const excluded = Object.entries(router.excluded_summary.scores_failing_rule ?? {}).sort(([a], [b]) =>
    a.localeCompare(b, "en", { numeric: true }),
  );
  const nExcluded = router.n_found - router.n_eligible;
  const selected = new Set(router.selected);
  const trait = router.trait;

  return (
    <div className="panel">
      <div className="panel-title">
        <h3>How the candidates were chosen</h3>
        <span className="small muted">
          trait-first; the person&apos;s genotype is never an input to selection or ranking
        </span>
      </div>

      <ol className="funnel" aria-label="Candidate selection funnel">
        <li>
          <div className="big num">{fmtInt(router.n_found)}</div>
          <div className="lbl">
            scores found in the PGS Catalog for{" "}
            <strong>{trait.term ? `${trait.term.label} (${trait.term.id})` : trait.query}</strong>
            {trait.scope ? ` and ${trait.scope.length - 1} equivalent term(s)` : ""}
          </div>
        </li>
        <li>
          <div className="big num">{fmtInt(router.n_eligible)}</div>
          <div className="lbl">eligible under rules E1–E8 ({fmtInt(nExcluded)} excluded)</div>
        </li>
        <li>
          <div className="big num">{fmtInt(router.selected.length)}</div>
          <div className="lbl">
            <IconSnowflake size={12} /> <strong>frozen</strong>: top {router.options.top_k} by pre-rank (R1–R5), before
            any personal scoring
          </div>
        </li>
      </ol>

      {excluded.length > 0 ? (
        <>
          <h4 className="subhead">Excluded scores by rule</h4>
          <p className="tiny muted">
            Number of excluded scores failing each rule (a score can fail several).{" "}
            {fmtInt(router.excluded_summary.excluded_only_by_engineering_E8)} score(s) were excluded only by the
            engineering constraint E8.
          </p>
          <ul className="excl-list">
            {excluded.map(([code, n]) => {
              const engineering = code === "E8";
              return (
                <li key={code} className={engineering ? "engineering" : undefined}>
                  <strong className="mono">{code}</strong> × {fmtInt(n)} —{" "}
                  <span className="muted">{ruleText(router.eligibility_rules, code).replace(/^E\d+\s*/, "")}</span>
                  {engineering ? (
                    <div className="tiny" style={{ marginTop: 3 }}>
                      <strong>Engineering constraint, not a scientific criterion</strong>
                      {router.options.max_variants ? ` (max_variants = ${fmtInt(router.options.max_variants)})` : ""}.
                      Larger scores are skipped because of runtime and reference-panel limits of this demo.
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <p className="tiny muted" style={{ marginTop: 6 }}>
            Counts are rule hits: a score can fail more than one rule, so they need not sum to the {fmtInt(nExcluded)}{" "}
            excluded scores.
          </p>
        </>
      ) : null}

      <dl className="kv small" style={{ marginTop: 12 }}>
        <dt>Candidate-set digest</dt>
        <dd className="mono" title={router.digest}>
          {shortHash(router.digest, 16, 8)}
        </dd>
        <dt>Frozen at</dt>
        <dd>{fmtTimestamp(router.frozen_at)}</dd>
        <dt>PGS Catalog</dt>
        <dd>
          {router.catalog?.mode} · release {router.catalog?.release} · API {router.catalog?.api_version}
        </dd>
        <dt>Options</dt>
        <dd>
          sex {router.options.sex ?? "not given"} · build {router.options.build ?? "any"} · top k {router.options.top_k}
          {router.options.max_variants
            ? ` · max_variants ${fmtInt(router.options.max_variants)} (E8, engineering)`
            : ""}
        </dd>
      </dl>

      <Disclosure summary="Eligibility and ranking rules">
        <h4 className="subhead">Eligibility (all must hold)</h4>
        <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
          {router.eligibility_rules.map((r) => (
            <li key={r} style={{ marginBottom: 4 }}>
              <strong className="mono">{r.split(" ")[0]}</strong> {r.slice(r.indexOf(" ") + 1)}
              {r.startsWith("E8") ? <em className="muted"> — engineering constraint</em> : null}
            </li>
          ))}
        </ul>
        <h4 className="subhead">Pre-ranking (applied in order; ties broken by the next rule)</h4>
        <ol className="small" style={{ paddingLeft: 18, margin: 0 }}>
          {router.ranking_rules.map((r) => (
            <li key={r} style={{ marginBottom: 4 }}>
              {r}
            </li>
          ))}
        </ol>
      </Disclosure>

      {trait.scope ? (
        <Disclosure
          summary={`Trait scope: ${trait.scope.length} term(s) in, ${trait.excluded_children?.length ?? 0} excluded`}
        >
          <p className="small">
            Query <strong>&ldquo;{trait.query}&rdquo;</strong> resolved to{" "}
            <strong>
              {trait.term?.label} ({trait.term?.id})
            </strong>{" "}
            — {trait.detail}.
          </p>
          {trait.scope_rule ? <p className="small muted">Scope rule: {trait.scope_rule}</p> : null}
          <div className="grid-2">
            <div>
              <h4 className="subhead">In scope</h4>
              <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                {trait.scope.map((s) => (
                  <li key={s.id}>
                    {s.label} <span className="mono muted">{s.id}</span> — <span className="muted">{s.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="subhead">Excluded sub-phenotypes</h4>
              <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                {(trait.excluded_children ?? []).map((s) => (
                  <li key={s.id}>
                    {s.label} <span className="mono muted">{s.id}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Disclosure>
      ) : null}

      {router.eligible && router.eligible.length > 0 ? (
        <Disclosure summary={`All ${fmtInt(router.eligible.length)} eligible scores in pre-rank order`}>
          <div className="table-wrap scroll-y">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col" className="r">
                    Pre-rank
                  </th>
                  <th scope="col">PGS</th>
                  <th scope="col">Name</th>
                  <th scope="col" className="r">
                    Variants
                  </th>
                  <th scope="col">R1 groups with metrics</th>
                  <th scope="col" className="r">
                    R2 units w/ metrics
                  </th>
                  <th scope="col" className="r">
                    R3 total eval. N
                  </th>
                  <th scope="col">R4 released</th>
                </tr>
              </thead>
              <tbody>
                {router.eligible.map((e) => (
                  <tr key={e.pgs_id} className={selected.has(e.pgs_id) ? "is-selected" : undefined}>
                    <td className="r">{e.pre_rank}</td>
                    <th scope="row" className="mono nowrap">
                      {e.pgs_id}
                      {selected.has(e.pgs_id) ? <span className="visually-hidden"> (selected)</span> : null}
                    </th>
                    <td>{e.name}</td>
                    <td className="r">{fmtInt(e.variants_number)}</td>
                    <td className="mono">{e.ranking_evidence.ancestry_groups_with_metrics.join(" ") || "—"}</td>
                    <td className="r">{fmtInt(e.ranking_evidence.units_with_metrics)}</td>
                    <td className="r">{fmtInt(e.ranking_evidence.total_evaluation_n)}</td>
                    <td className="nowrap">{fmtDate(e.date_release)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tiny muted" style={{ marginTop: 6 }}>
            Highlighted rows are the frozen top-{router.options.top_k} candidates.
          </p>
        </Disclosure>
      ) : null}
    </div>
  );
}
