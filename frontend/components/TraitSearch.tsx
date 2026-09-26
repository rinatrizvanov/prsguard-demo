"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { TraitTerm } from "@/lib/types";
import { searchTraits } from "@/lib/localServer";

/**
 * WAI-ARIA combobox (list autocomplete). Queries only the local server's /api/traits,
 * which forwards the trait text — never genotype data — to the PGS Catalog.
 */
export function TraitSearch({
  port,
  value,
  onChange,
  disabled,
}: {
  port: number;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  const [results, setResults] = useState<TraitTerm[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<string>("");
  const [query, setQuery] = useState(value);
  // The label last chosen from the list: typing it again (or re-enabling the field) does not re-query.
  const chosen = useRef<string | null>(null);
  const id = useId();
  const listId = `${id}-list`;

  useEffect(() => {
    if (disabled) return;
    const q = query.trim();
    if (chosen.current !== null && q === chosen.current) return;
    if (q.length < 2) {
      setResults([]);
      setOpen(false);
      setStatus("");
      return;
    }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      setStatus("Searching the PGS Catalog…");
      searchTraits(port, q, ctl.signal)
        .then((r) => {
          setResults(r);
          setOpen(true);
          setActive(-1);
          setStatus(r.length ? `${r.length} trait(s) found` : "No matching traits");
        })
        .catch((e: unknown) => {
          if (ctl.signal.aborted) return;
          setResults([]);
          setStatus(`Trait search failed: ${e instanceof Error ? e.message : String(e)}`);
        });
    }, 300);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [query, port, disabled]);

  const choose = (t: TraitTerm) => {
    chosen.current = t.label;
    setQuery(t.label);
    onChange(t.label);
    setOpen(false);
    setStatus(`Selected ${t.label} (${t.id})`);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) {
      if (e.key === "ArrowDown" && results.length > 0) {
        setOpen(true);
        setActive(0);
        e.preventDefault();
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? results.length - 1 : a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="field">
      <label htmlFor={`${id}-input`}>Trait</label>
      <div className="combo">
        <input
          id={`${id}-input`}
          className="input"
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open && results.length > 0}
          aria-controls={listId}
          aria-activedescendant={open && active >= 0 ? `${id}-opt-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder="e.g. breast cancer, type 2 diabetes"
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value);
            onChange(e.target.value);
          }}
          onKeyDown={onKey}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onFocus={() => results.length > 0 && setOpen(true)}
        />
        {open && results.length > 0 ? (
          <ul className="combo-list" role="listbox" id={listId} aria-label="Matching traits">
            {results.map((r, i) => (
              <li
                key={r.id}
                id={`${id}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(r);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span>{r.label}</span>
                <span className="mono">{r.id}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <span className="tiny muted" aria-live="polite">
        {status || "Searched via your local server (trait text only)."}
      </span>
    </div>
  );
}
