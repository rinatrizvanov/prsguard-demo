"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export interface TabDef {
  id: string;
  label: ReactNode;
  render: () => ReactNode;
}

/**
 * WAI-ARIA tabs with automatic activation: Left/Right (and Home/End) move between tabs,
 * Tab moves into the panel. Only the active panel is rendered (panels can be heavy).
 */
export function Tabs({ tabs, label, initial }: { tabs: TabDef[]; label: string; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.id);
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const focusTab = (i: number) => {
    const t = tabs[(i + tabs.length) % tabs.length];
    setActive(t.id);
    refs.current[t.id]?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusTab(i + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusTab(i - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusTab(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusTab(tabs.length - 1);
    }
  };

  const current = tabs.find((t) => t.id === active) ?? tabs[0];

  return (
    <div>
      <div className="tablist" role="tablist" aria-label={label}>
        {tabs.map((t, i) => {
          const selected = t.id === current.id;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[t.id] = el;
              }}
              role="tab"
              type="button"
              id={`${base}-tab-${t.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(t.id)}
              onKeyDown={(e) => onKey(e, i)}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${base}-panel-${current.id}`}
        aria-labelledby={`${base}-tab-${current.id}`}
        tabIndex={0}
      >
        {current.render()}
      </div>
    </div>
  );
}
