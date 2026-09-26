import type { DemoCaseIndexEntry } from "@/lib/types";
import { fmtInt } from "@/lib/format";

export function DemoPicker({
  cases,
  selected,
  onSelect,
  disabled = false,
}: {
  cases: DemoCaseIndexEntry[];
  selected: string | null;
  onSelect: (id: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <div className="compare-hint">
        <span>
          <strong>Try this:</strong> compare <strong>A</strong> and <strong>B</strong> — the same person (HG00097) as a
          sparse consumer array and as a WGS-like file. Same genome, different answer.
        </span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <button type="button" className="btn small" onClick={() => onSelect("A")} disabled={disabled}>
            Show A
          </button>
          <button type="button" className="btn small" onClick={() => onSelect("B")} disabled={disabled}>
            Show B
          </button>
        </span>
      </div>
      <fieldset className="demo-grid">
        <legend className="visually-hidden">Demo genome</legend>
        {cases.map((c) => (
          <label key={c.id} className="demo-card">
            <input
              type="radio"
              name="demo-case"
              value={c.id}
              checked={selected === c.id}
              onChange={() => onSelect(c.id)}
              disabled={disabled}
            />
            <span className="card-head">
              <span className="case-letter" aria-hidden="true">
                {c.id}
              </span>
              <span className="card-title">
                <span className="visually-hidden">Case {c.id}: </span>
                {c.title}
              </span>
            </span>
            <span className="meta">
              <span title="1000 Genomes population label of the sample (a reference label, not identity)">
                1000G {c.population} · {c.superpopulation}
              </span>
              <span>{c.format}</span>
              <span>{fmtInt(c.n_sites)} sites</span>
            </span>
            <span className="small muted">
              {c.description}
              {c.same_individual_as && !/same individual/i.test(c.description)
                ? ` Same individual as case ${c.same_individual_as}.`
                : ""}
            </span>
            <span className="prov-label">
              {c.synthetic ? <strong>SYNTHETIC · </strong> : null}
              {c.label}
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
