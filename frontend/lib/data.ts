import { assetUrl } from "./paths";
import type { DemoCaseIndex, PrsGuardResult } from "./types";

/** Static demo data shipped in public/demo. No other network source is used for demos. */

const caseCache = new Map<string, Promise<PrsGuardResult>>();
let indexPromise: Promise<DemoCaseIndex> | null = null;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(assetUrl(path), { cache: "force-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function loadDemoIndex(): Promise<DemoCaseIndex> {
  if (!indexPromise) {
    indexPromise = getJson<DemoCaseIndex>("/demo/cases.json").catch((e: unknown) => {
      indexPromise = null;
      throw e;
    });
  }
  return indexPromise;
}

export function loadDemoCase(id: string): Promise<PrsGuardResult> {
  if (!/^[A-Z]$/.test(id)) return Promise.reject(new Error(`unknown demo case ${id}`));
  let p = caseCache.get(id);
  if (!p) {
    p = getJson<unknown>(`/demo/case_${id}.json`).then((raw) => assertResult(raw));
    p.catch(() => caseCache.delete(id));
    caseCache.set(id, p);
  }
  return p;
}

/** Minimal structural check so a malformed file fails loudly instead of rendering half a result. */
export function assertResult(raw: unknown): PrsGuardResult {
  const r = raw as Partial<PrsGuardResult> | null;
  if (
    !r ||
    typeof r !== "object" ||
    typeof r.schema !== "string" ||
    !r.schema.startsWith("prsguard.result.") ||
    !r.headline ||
    !Array.isArray(r.candidates) ||
    !r.placement ||
    !r.router
  ) {
    throw new Error("Not a PRSGuard result (expected schema prsguard.result.v1).");
  }
  return r as PrsGuardResult;
}
