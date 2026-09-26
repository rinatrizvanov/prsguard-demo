/** Presentation-only formatting. Nothing here derives a scientific quantity. */

export const DASH = "—";

export function isNum(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  return isNum(x) ? x.toFixed(digits) : DASH;
}

export function fmtSigned(x: number | null | undefined, digits = 2): string {
  if (!isNum(x)) return DASH;
  const s = x.toFixed(digits);
  return x > 0 ? `+${s}` : s;
}

export function fmtInt(x: number | null | undefined): string {
  return isNum(x) ? Math.round(x).toLocaleString("en-US") : DASH;
}

/** Compact counts for chart labels: 1,284 / 12.9K / 4.2M. */
export function fmtCompact(x: number | null | undefined): string {
  if (!isNum(x)) return DASH;
  const a = Math.abs(x);
  if (a >= 1e6) return `${(x / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${(x / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
  return fmtInt(x);
}

/** A fraction in [0, 1] shown as a percentage. */
export function fmtFraction(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? `${(x * 100).toFixed(digits)}%` : DASH;
}

export function fmtInterval(iv: readonly number[] | null | undefined, digits = 1): string {
  if (!iv || iv.length < 2 || !isNum(iv[0]) || !isNum(iv[1])) return DASH;
  return `${iv[0].toFixed(digits)} – ${iv[1].toFixed(digits)}`;
}

export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 19)} UTC`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return iso.slice(0, 10);
}

/** "sha256:2d274ccf...8c33" → "sha256:2d274ccf…8c33". */
export function shortHash(h: string | null | undefined, head = 10, tail = 4): string {
  if (!h) return DASH;
  const [algo, hex] = h.includes(":") ? h.split(":", 2) : ["", h];
  if (hex.length <= head + tail + 1) return h;
  return `${algo ? `${algo}:` : ""}${hex.slice(0, head)}…${hex.slice(-tail)}`;
}

export function shortCommit(c: string | null | undefined): string {
  return c ? c.slice(0, 12) : DASH;
}

/** Catalog/Europe PMC titles arrive HTML-escaped (e.g. "PGS&lt;sub&gt;313&lt;/sub&gt;"). Render as plain text. */
export function plainText(s: string | null | undefined): string {
  if (!s) return "";
  const decoded = s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_, h: string) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d: string) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&amp;/g, "&");
  return decoded
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function doiUrl(doi: string | null | undefined): string | null {
  return doi ? `https://doi.org/${doi}` : null;
}

export function pmidUrl(pmid: string | null | undefined): string | null {
  return pmid ? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/` : null;
}

export function pgsUrl(pgsId: string): string {
  return `https://www.pgscatalog.org/score/${pgsId}/`;
}

export function pgpUrl(pgpId: string): string {
  return `https://www.pgscatalog.org/publication/${pgpId}/`;
}

export function humanise(s: string): string {
  return s.replace(/_/g, " ");
}
