import type { PrsGuardResult } from "@/lib/types";
import { fmtTimestamp, humanise, shortCommit, shortHash } from "@/lib/format";
import { IconShield } from "./Icons";

export function Reproducibility({ result }: { result: PrsGuardResult }) {
  const r = result.reproducibility ?? ({} as PrsGuardResult["reproducibility"]);
  const hashes = Object.entries(r.hashes ?? {});
  const pkgs = Object.entries(r.packages ?? {});
  const seeds = Object.entries(r.seeds ?? {});
  return (
    <div className="panel">
      <div className="repro-grid">
        <div>
          <h3 className="subhead">Versions</h3>
          <dl className="kv small">
            <dt>PRSGuard</dt>
            <dd>
              {r.prsguard_version}{" "}
              <span className="mono" title={r.git_commit ?? undefined}>
                @ {shortCommit(r.git_commit)}
              </span>
              {r.git_dirty ? (
                <span className="badge neutral" style={{ marginLeft: 6 }}>
                  uncommitted changes
                </span>
              ) : null}
            </dd>
            <dt>ClawBio</dt>
            <dd className="mono">
              {shortCommit(r.clawbio_commit)}
              {r.clawbio_pinned && r.clawbio_pinned !== r.clawbio_commit ? (
                <span className="muted"> (pinned {shortCommit(r.clawbio_pinned)})</span>
              ) : r.clawbio_pinned ? (
                <span className="muted"> (= pinned)</span>
              ) : null}
            </dd>
            <dt>Calibration</dt>
            <dd className="mono">{r.calibration_version ?? "—"}</dd>
            <dt>PGS Catalog</dt>
            <dd>
              {r.catalog ? `${r.catalog.mode} · release ${r.catalog.release} · API ${r.catalog.api_version}` : "—"}
            </dd>
            <dt>Python</dt>
            <dd>
              {r.python ?? "—"} <span className="muted small">{r.platform}</span>
            </dd>
            {pkgs.length > 0 ? (
              <>
                <dt>Packages</dt>
                <dd className="mono small">{pkgs.map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
              </>
            ) : null}
          </dl>
        </div>
        <div>
          <h3 className="subhead">Hashes</h3>
          <dl className="kv small">
            {hashes.map(([k, v]) => (
              <FragmentKV key={k} k={humanise(k)} v={v} />
            ))}
          </dl>
          <h3 className="subhead">Seeds &amp; timing</h3>
          <dl className="kv small">
            {seeds.map(([k, v]) => (
              <FragmentKV key={k} k={humanise(k)} v={String(v)} plain />
            ))}
            <dt>Started</dt>
            <dd>{fmtTimestamp(r.started_at)}</dd>
            <dt>Finished</dt>
            <dd>{fmtTimestamp(r.finished_at)}</dd>
          </dl>
        </div>
      </div>
      {r.command ? (
        <>
          <h3 className="subhead">Command</h3>
          <code className="cmd">{r.command}</code>
        </>
      ) : null}
      <div className="disclaimer" role="note">
        <IconShield size={14} /> <strong>Disclaimer.</strong> {result.disclaimer}
      </div>
    </div>
  );
}

function FragmentKV({ k, v, plain = false }: { k: string; v: string; plain?: boolean }) {
  return (
    <>
      <dt>{k}</dt>
      <dd className={plain ? undefined : "mono"} title={v}>
        {plain ? v : shortHash(v, 16, 6)}
      </dd>
    </>
  );
}
