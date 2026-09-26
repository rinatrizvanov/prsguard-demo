"use client";

import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from "react";
import type { PrsGuardResult } from "@/lib/types";
import {
  ALLOWED_SUFFIXES,
  DEFAULT_PORT,
  analyzeFile,
  checkHealth,
  fileProblem,
  isValidPort,
  serverOrigin,
  type BuildOption,
  type HealthInfo,
  type SexOption,
} from "@/lib/localServer";
import { TraitSearch } from "./TraitSearch";
import { IconLock, IconUpload } from "./Icons";

export const PRIVACY_SENTENCE =
  "Uploads are analysed only by a PRSGuard server running on your own machine (`prsguard serve`). This website never receives genomic data.";

type ServerState = { kind: "checking" } | { kind: "absent"; reason: string } | { kind: "connected"; info: HealthInfo };

function fmtBytes(n: number): string {
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MB`;
  if (n >= 1 << 10) return `${(n / (1 << 10)).toFixed(0)} KB`;
  return `${n} B`;
}

export function LocalAnalysis({ onResult }: { onResult: (r: PrsGuardResult, fileName: string) => void }) {
  const [port, setPort] = useState(DEFAULT_PORT);
  const [portText, setPortText] = useState(String(DEFAULT_PORT));
  const [server, setServer] = useState<ServerState>({ kind: "checking" });
  const [file, setFile] = useState<File | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [trait, setTrait] = useState("");
  const [sex, setSex] = useState<SexOption>("");
  const [build, setBuild] = useState<BuildOption>("");
  const [busy, setBusy] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const ids = useId();

  const probe = useCallback(async (p: number) => {
    setServer({ kind: "checking" });
    try {
      const info = await checkHealth(p);
      setServer({ kind: "connected", info });
    } catch (e: unknown) {
      setServer({
        kind: "absent",
        reason: e instanceof Error && e.name !== "TimeoutError" ? e.message : "no response",
      });
    }
  }, []);

  useEffect(() => {
    void probe(port);
  }, [port, probe]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const connected = server.kind === "connected";
  const disabled = !connected || busy;

  const pick = (f: File | null) => {
    setRunErr(null);
    if (!f) {
      setFile(null);
      setFileErr(null);
      return;
    }
    const problem = fileProblem(f);
    setFileErr(problem);
    setFile(problem ? null : f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDrag(false);
    if (disabled) return;
    pick(e.dataTransfer.files?.[0] ?? null);
  };

  const run = async () => {
    if (!file || !trait.trim() || !connected) return;
    setBusy(true);
    setRunErr(null);
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      const r = await analyzeFile(port, file, { trait: trait.trim(), sex, build }, ctl.signal);
      onResult(r, file.name);
    } catch (e: unknown) {
      if (!ctl.signal.aborted) setRunErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  return (
    <div>
      <p className="privacy-note">
        <IconLock size={13} /> {PRIVACY_SENTENCE.split("`prsguard serve`")[0]}
        <code>prsguard serve</code>
        {PRIVACY_SENTENCE.split("`prsguard serve`")[1]}
      </p>

      <div className="server-status" aria-live="polite">
        {server.kind === "checking" ? (
          <>
            <span className="dot wait" aria-hidden="true" /> Looking for a local PRSGuard server at{" "}
            <code>{serverOrigin(port)}</code>…
          </>
        ) : server.kind === "connected" ? (
          <>
            <span className="dot on" aria-hidden="true" />
            <span>
              <strong>Connected</strong> to the local PRSGuard server {server.info.version} at{" "}
              <code>{serverOrigin(port)}</code> (loopback only).
            </span>
          </>
        ) : (
          <>
            <span className="dot off" aria-hidden="true" />
            <span>
              <strong>No local server found</strong> at <code>{serverOrigin(port)}</code>. Upload and trait search are
              disabled.
            </span>
          </>
        )}
        <button
          type="button"
          className="btn small"
          onClick={() => void probe(port)}
          disabled={server.kind === "checking"}
        >
          Check again
        </button>
      </div>

      {server.kind === "absent" ? (
        <div className="callout" style={{ display: "block" }}>
          <p style={{ marginBottom: 6 }}>
            To analyse your own file, start the server on this computer, then press “Check again”:
          </p>
          <code className="cmd">prsguard serve --port {port}</code>
          <p className="small muted" style={{ margin: "6px 0 0" }}>
            The server binds to 127.0.0.1 only, analyses the file locally and deletes it after responding. The hosted
            demo below works without it.
          </p>
        </div>
      ) : null}

      <details className="disclosure" style={{ marginBottom: 14 }}>
        <summary>Server port</summary>
        <div className="disclosure-body">
          <div className="field" style={{ maxWidth: 260 }}>
            <label htmlFor={`${ids}-port`}>Port on 127.0.0.1</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                id={`${ids}-port`}
                className="input"
                inputMode="numeric"
                value={portText}
                onChange={(e) => setPortText(e.target.value.replace(/[^0-9]/g, "").slice(0, 5))}
              />
              <button
                type="button"
                className="btn small"
                onClick={() => {
                  const p = Number(portText);
                  if (isValidPort(p)) setPort(p);
                }}
                disabled={!isValidPort(Number(portText))}
              >
                Use
              </button>
            </div>
            <span className="tiny muted">The host is fixed to 127.0.0.1 so files can only go to your own machine.</span>
          </div>
        </div>
      </details>

      <div className="form-grid">
        <div className="field">
          <span className="label" id={`${ids}-file-label`}>
            Genotype file
          </span>
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              if (!disabled) setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
          >
            <input
              id={`${ids}-file`}
              type="file"
              aria-labelledby={`${ids}-file-label`}
              accept={ALLOWED_SUFFIXES.join(",") + ",.gz"}
              disabled={disabled}
              onChange={(e) => pick(e.target.files?.[0] ?? null)}
            />
            <span className="tiny muted">
              <IconUpload size={12} /> 23andMe-style text, CSV/TSV or VCF (optionally .gz), up to 300 MB. Or drop a file
              here.
            </span>
            {file ? (
              <span className="small">
                Selected: <strong className="mono">{file.name}</strong> ({fmtBytes(file.size)})
              </span>
            ) : null}
            {fileErr ? <span className="error-box small">{fileErr}</span> : null}
          </div>
        </div>

        <TraitSearch port={port} value={trait} onChange={setTrait} disabled={disabled} />

        <div className="field">
          <label htmlFor={`${ids}-build`}>Genome build</label>
          <select
            id={`${ids}-build`}
            className="input"
            value={build}
            disabled={disabled}
            onChange={(e) => setBuild(e.target.value as BuildOption)}
          >
            <option value="">Auto-detect (recommended)</option>
            <option value="GRCh37">GRCh37 / hg19</option>
            <option value="GRCh38">GRCh38 / hg38</option>
            <option value="NCBI36">NCBI36 / hg18</option>
          </select>
          <span className="tiny muted">Declared builds are verified against rsID anchor positions; never assumed.</span>
        </div>

        <fieldset className="field">
          <legend>Sex</legend>
          <div className="segmented" role="radiogroup" aria-label="Sex">
            {(
              [
                ["female", "Female"],
                ["male", "Male"],
                ["", "Not given"],
              ] as [SexOption, string][]
            ).map(([v, l]) => (
              <label key={l}>
                <input
                  type="radio"
                  name={`${ids}-sex`}
                  value={v}
                  checked={sex === v}
                  disabled={disabled}
                  onChange={() => setSex(v)}
                />
                {l}
              </label>
            ))}
          </div>
          <span className="tiny muted">Used for sex-specific scores and evaluations (rules E3, G6, G10).</span>
        </fieldset>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 16, flexWrap: "wrap" }}>
        <button
          type="button"
          className="btn primary"
          disabled={disabled || !file || trait.trim().length < 2}
          onClick={() => void run()}
        >
          {busy ? "Analysing on your machine…" : "Analyse locally"}
        </button>
        {busy ? (
          <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
            Cancel
          </button>
        ) : null}
        <span className="small muted">
          {connected
            ? "The file is sent only to 127.0.0.1. New traits query the live PGS Catalog from your machine and can take minutes."
            : "Start the local server to enable analysis."}
        </span>
      </div>
      {runErr ? (
        <p className="error-box" role="alert" style={{ marginTop: 10 }}>
          Local analysis failed: {runErr}
        </p>
      ) : null}
    </div>
  );
}
