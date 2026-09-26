"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DemoCaseIndex, PrsGuardResult, ResultSource } from "@/lib/types";
import { loadDemoCase, loadDemoIndex } from "@/lib/data";
import { DemoPicker } from "./DemoPicker";
import { LocalAnalysis } from "./LocalAnalysis";
import { ResultView } from "./ResultView";
import { Tabs } from "./Tabs";

const DEFAULT_CASE = "B";

/** The selected demo case lives in ?case=X so in-page anchors (#trace, …) do not lose it. */
function caseFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const q = new URLSearchParams(window.location.search).get("case");
  if (q && /^[A-Z]$/.test(q)) return q;
  const m = /(?:^|[#&])case=([A-Z])\b/.exec(window.location.hash);
  return m ? m[1] : null;
}

function setCaseInUrl(id: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("case", id);
  else url.searchParams.delete("case");
  if (/case=/.test(url.hash)) url.hash = "";
  window.history.replaceState(null, "", url.toString());
}

interface Shown {
  result: PrsGuardResult;
  source: ResultSource;
}

export function Workbench() {
  const [index, setIndex] = useState<DemoCaseIndex | null>(null);
  const [indexErr, setIndexErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqRef = useRef(0);
  const resultRef = useRef<HTMLDivElement>(null);

  const showCase = useCallback(async (id: string, idx: DemoCaseIndex | null, scroll = false) => {
    const req = ++reqRef.current;
    setSelected(id);
    setLoading(true);
    setError(null);
    try {
      const result = await loadDemoCase(id);
      if (req !== reqRef.current) return;
      setShown({ result, source: { kind: "demo", caseId: id, entry: idx?.cases.find((c) => c.id === id) } });
      if (typeof window !== "undefined") {
        window.history.replaceState(null, "", `#case=${id}`);
      }
      if (scroll) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e: unknown) {
      if (req !== reqRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (req === reqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    loadDemoIndex()
      .then((idx) => {
        if (!alive) return;
        setIndex(idx);
        const fromUrl = caseFromUrl();
        const initial = fromUrl && idx.cases.some((c) => c.id === fromUrl) ? fromUrl : DEFAULT_CASE;
        void showCase(initial, idx);
      })
      .catch((e: unknown) => alive && setIndexErr(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [showCase]);

  const onLocalResult = (result: PrsGuardResult, fileName: string) => {
    reqRef.current++;
    setSelected(null);
    setError(null);
    setLoading(false);
    setShown({ result, source: { kind: "local", fileName, analysedAt: new Date().toISOString() } });
    setCaseInUrl(null);
    resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const demoTrait = index?.cases[0]?.trait ?? "breast cancer";
  const demoSex = index?.cases[0]?.sex ?? "female";

  return (
    <>
      <section className="section input-panel" id="input" aria-labelledby="h-input">
        <div className="section-head">
          <h2 id="h-input">1 · Choose a genotype file</h2>
          <p>
            Seven precomputed demo cases (real pipeline outputs) run entirely in this page. Your own file can be
            analysed only by a server on your own computer.
          </p>
        </div>
        <div className="panel">
          <Tabs
            label="Input source"
            tabs={[
              {
                id: "demo",
                label: "Demo genomes A–G",
                render: () => (
                  <div>
                    {index ? (
                      <DemoPicker
                        cases={index.cases}
                        selected={selected}
                        onSelect={(id) => void showCase(id, index, true)}
                      />
                    ) : indexErr ? (
                      <p className="error-box">Could not load the demo index: {indexErr}</p>
                    ) : (
                      <div className="skeleton" style={{ height: 120 }} aria-label="Loading demo cases" />
                    )}
                    <p className="small muted" style={{ marginTop: 12, marginBottom: 0 }}>
                      Demo settings (fixed, precomputed): trait <strong>{demoTrait}</strong> · sex{" "}
                      <strong>{demoSex}</strong> · build <strong>auto-detected</strong> · PGS Catalog snapshot.{" "}
                      {index?.note ? index.note.split("\n")[0] : ""}
                    </p>
                  </div>
                ),
              },
              {
                id: "local",
                label: "Your file (local)",
                render: () => <LocalAnalysis onResult={onLocalResult} />,
              },
            ]}
          />
        </div>
      </section>

      <section className="section" id="result" aria-labelledby="h-result" ref={resultRef} aria-busy={loading}>
        <div className="section-head">
          <h2 id="h-result">2 · Result</h2>
          <p>
            Can the candidate scores be interpreted for this person? The answer, the trace of how it was reached, and
            all the evidence behind it.
          </p>
        </div>
        {error ? (
          <p className="error-box" role="alert">
            Could not load this result: {error}
          </p>
        ) : null}
        {shown ? (
          <div style={{ opacity: loading ? 0.55 : 1, transition: "opacity .15s" }}>
            <ResultView result={shown.result} source={shown.source} />
          </div>
        ) : !error ? (
          <div className="skeleton" aria-label="Loading result" />
        ) : null}
      </section>
    </>
  );
}
