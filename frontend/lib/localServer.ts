/**
 * Client for the optional local analysis server (`prsguard serve`).
 *
 * Privacy model: genotype files are sent ONLY to a PRSGuard server on this computer's
 * loopback interface. The host is hard-coded to 127.0.0.1 (only the port is configurable),
 * so this code cannot send a genotype anywhere else. The hosted website itself never
 * receives genomic data.
 */

import { assertResult } from "./data";
import type { PrsGuardResult, TraitTerm } from "./types";

export const DEFAULT_PORT = 8765;
const LOOPBACK_HOST = "127.0.0.1";

export const ALLOWED_SUFFIXES = [".txt", ".txt.gz", ".csv", ".tsv", ".vcf", ".vcf.gz"] as const;
export const MAX_UPLOAD_BYTES = 300 * 1024 * 1024;

export type SexOption = "female" | "male" | "";
export type BuildOption = "" | "GRCh37" | "GRCh38" | "NCBI36";

export interface HealthInfo {
  ok: boolean;
  version: string;
  mode: string;
}

export function isValidPort(port: number): boolean {
  return Number.isInteger(port) && port >= 1024 && port <= 65535;
}

export function serverOrigin(port: number): string {
  if (!isValidPort(port)) throw new Error("port must be an integer between 1024 and 65535");
  return `http://${LOOPBACK_HOST}:${port}`;
}

function withTimeout(ms: number, outer?: AbortSignal): { signal: AbortSignal; done: () => void } {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(new DOMException("timeout", "TimeoutError")), ms);
  const onAbort = () => ctl.abort(outer?.reason);
  outer?.addEventListener("abort", onAbort);
  return {
    signal: ctl.signal,
    done: () => {
      clearTimeout(timer);
      outer?.removeEventListener("abort", onAbort);
    },
  };
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: unknown };
    if (typeof body.error === "string") return body.error;
  } catch {
    /* fall through */
  }
  return `HTTP ${res.status}`;
}

export async function checkHealth(port: number, signal?: AbortSignal): Promise<HealthInfo> {
  const t = withTimeout(2500, signal);
  try {
    const res = await fetch(`${serverOrigin(port)}/api/health`, {
      signal: t.signal,
      cache: "no-store",
      credentials: "omit",
    });
    if (!res.ok) throw new Error(await readError(res));
    const body = (await res.json()) as Partial<HealthInfo>;
    if (!body.ok) throw new Error("server reported not ok");
    return { ok: true, version: String(body.version ?? "?"), mode: String(body.mode ?? "local") };
  } finally {
    t.done();
  }
}

export async function searchTraits(port: number, q: string, signal?: AbortSignal): Promise<TraitTerm[]> {
  const params = new URLSearchParams({ q });
  const t = withTimeout(20000, signal);
  try {
    const res = await fetch(`${serverOrigin(port)}/api/traits?${params.toString()}`, {
      signal: t.signal,
      cache: "no-store",
      credentials: "omit",
    });
    if (!res.ok) throw new Error(await readError(res));
    const body = (await res.json()) as { results?: TraitTerm[] };
    return (body.results ?? []).filter((r) => r && typeof r.label === "string");
  } finally {
    t.done();
  }
}

export function fileProblem(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED_SUFFIXES.some((s) => name.endsWith(s))) {
    return `File name must end with ${ALLOWED_SUFFIXES.join(", ")}.`;
  }
  if (!/^[\w.\- ]{1,200}$/.test(file.name)) {
    return "File name may contain only letters, digits, spaces, '.', '-' and '_'.";
  }
  if (file.size <= 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than 300 MB.";
  return null;
}

export async function analyzeFile(
  port: number,
  file: File,
  opts: { trait: string; sex: SexOption; build: BuildOption },
  signal?: AbortSignal,
): Promise<PrsGuardResult> {
  const params = new URLSearchParams({ trait: opts.trait });
  if (opts.sex) params.set("sex", opts.sex);
  if (opts.build) params.set("build", opts.build);
  const res = await fetch(`${serverOrigin(port)}/api/analyze?${params.toString()}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream", "X-Filename": file.name },
    signal,
    cache: "no-store",
    credentials: "omit",
  });
  if (!res.ok) throw new Error(await readError(res));
  return assertResult(await res.json());
}
