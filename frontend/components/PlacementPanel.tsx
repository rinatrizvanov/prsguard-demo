import type { Placement } from "@/lib/types";
import { ancestryMeta, sortCodes } from "@/lib/ancestry";
import { fmtFraction, fmtInt, fmtNum, isNum } from "@/lib/format";
import { StatusBadge } from "./Badges";
import { IconCheck, IconInfo } from "./Icons";
import { PcaPlot } from "./PcaPlot";

export const PLACEMENT_NOTE = "Genetic reference placement is not ethnicity or identity.";

const STATUS_EXPLAIN: Record<string, string> = {
  RESOLVED: "inside exactly one reference group's cloud, stably across bootstrap replicates",
  INTERMEDIATE: "outside every reference cloud — consistent with admixed or unrepresented genetic backgrounds",
  UNSTABLE: "placement changes across bootstrap replicates",
  UNRESOLVED: "too little data to place the person against the reference",
};

export function PlacementPanel({ placement, personLabel }: { placement: Placement; personLabel: string }) {
  const p = placement;
  const d2 = p.mahalanobis_d2 ?? {};
  const cut = p.cloud_cut_d2;
  const inside = new Set(p.inside_clouds ?? []);
  const boots = p.bootstrap_placements ?? {};
  const nBoot = Object.values(boots).reduce((a, b) => a + b, 0) || p.policy?.bootstrap || 0;
  const adm = p.supervised_admixture_context ?? null;

  return (
    <div className="panel">
      <div className="callout identity" role="note">
        <IconInfo size={16} />
        <span>{p.note || PLACEMENT_NOTE}</span>
      </div>

      <div className="grid-plot">
        <div>
          {p.plot ? (
            <PcaPlot plot={p.plot} varianceExplained={p.variance_explained} personLabel={personLabel} />
          ) : (
            <div className="empty-state">
              <strong>No projection plot.</strong>
              <br />
              Placement is {p.status}: {p.detail ?? "insufficient data"}.
            </div>
          )}
        </div>

        <div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
            <StatusBadge status={p.status} size="lg" />
            {p.placement ? (
              <span>
                placed in reference group <strong>{p.placement}</strong>
              </span>
            ) : (
              <span className="muted">no reference group assigned</span>
            )}
          </div>
          <p className="small muted">
            {STATUS_EXPLAIN[p.status] ?? ""}
            {p.detail ? (
              <>
                <br />
                <span style={{ color: "var(--ink-2)" }}>{p.detail}</span>
              </>
            ) : null}
          </p>

          <dl className="kv small">
            {p.nearest_reference ? (
              <>
                <dt>Nearest reference</dt>
                <dd>{p.nearest_reference}</dd>
              </>
            ) : null}
            {isNum(p.placement_stability) ? (
              <>
                <dt>Placement stability</dt>
                <dd>
                  <strong>{fmtFraction(p.placement_stability, 0)}</strong> of {fmtInt(nBoot)} bootstrap replicates gave
                  the same call
                  <div className="tiny muted">
                    {Object.entries(boots)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}{" "}
                    (minimum {fmtFraction(p.policy?.min_stability, 0)}). A stability fraction, not an ancestry
                    percentage.
                  </div>
                </dd>
              </>
            ) : null}
            <dt>Sites used</dt>
            <dd>
              {fmtInt(p.n_sites_used)} of {fmtInt(p.n_panel_sites)} panel sites{" "}
              <span className="muted">(minimum {fmtInt(p.policy?.min_sites)})</span>
            </dd>
            {p.consistent_populations && p.consistent_populations.length > 0 ? (
              <>
                <dt>Consistent populations</dt>
                <dd className="mono">{p.consistent_populations.join(", ")}</dd>
              </>
            ) : null}
            {p.self_match && p.self_match.matches.length > 0 ? (
              <>
                <dt>Self-match excluded</dt>
                <dd>
                  <span className="mono">{p.self_match.matches.join(", ")}</span>{" "}
                  <span className="tiny muted">
                    (concordance {fmtNum(p.self_match.max_concordance, 2)} over {fmtInt(p.self_match.checked_sites)}{" "}
                    sites; {p.self_match.rule})
                  </span>
                </dd>
              </>
            ) : null}
          </dl>

          {Object.keys(d2).length > 0 ? (
            <>
              <h4 className="subhead">Mahalanobis distance to each reference cloud</h4>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Group</th>
                      <th scope="col" className="r">
                        D²
                      </th>
                      <th scope="col">Inside cloud?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortCodes(Object.keys(d2)).map((g) => (
                      <tr key={g} className={inside.has(g) ? "is-selected" : undefined}>
                        <th scope="row">{g}</th>
                        <td className="r">{fmtNum(d2[g], 2)}</td>
                        <td>
                          {inside.has(g) ? (
                            <span>
                              <IconCheck size={12} /> yes
                            </span>
                          ) : (
                            <span className="muted">no</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="tiny muted" style={{ marginTop: 6 }}>
                Cloud boundary: D² ≤ {fmtNum(cut, 3)} ({fmtFraction(p.cloud_quantile, 1)} quantile, {p.k_pcs} PCs).
              </p>
            </>
          ) : null}

          {adm && Object.keys(adm).length > 0 ? (
            <>
              <h4 className="subhead">
                Reference-similarity proportions (model-based context; not ancestry percentages or identity)
              </h4>
              <div className="mini-bars">
                {sortCodes(Object.keys(adm)).map((g) => (
                  <FragmentRow key={g} code={g} value={adm[g]} />
                ))}
              </div>
              <p className="tiny muted" style={{ marginTop: 6 }}>
                Supervised model fitted to the five 1000 Genomes reference groups. Context only: the gate uses the
                placement status above, never these proportions.
              </p>
            </>
          ) : null}

          <details className="disclosure">
            <summary>Method</summary>
            <div className="disclosure-body small">
              <p>{p.method}.</p>
              <p>Reference: {p.reference}.</p>
              <p>
                Bootstrap: {p.policy?.bootstrap} replicates, seed {p.policy?.seed}.
              </p>
              {p.excluded_reference_samples?.length ? (
                <p>
                  Excluded reference samples: <span className="mono">{p.excluded_reference_samples.join(", ")}</span>
                </p>
              ) : null}
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}

function FragmentRow({ code, value }: { code: string; value: number }) {
  return (
    <>
      <span className="mono">{code}</span>
      <span className="bar-track" aria-hidden="true">
        <span
          className="bar-fill"
          style={{
            display: "block",
            width: `${Math.max(0, Math.min(1, value)) * 100}%`,
            background: ancestryMeta(code).color,
          }}
        />
      </span>
      <span className="num">{fmtNum(value, 3)}</span>
    </>
  );
}
