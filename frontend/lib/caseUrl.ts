/**
 * The selected demo case lives in the query string (?case=X), never in the hash, so in-page anchors such as
 * #trace do not erase it and a refresh or bookmark reopens the same case. Pure functions (tested in
 * scripts/case-url.test.mjs).
 */

export function caseFromLocation(search: string, hash: string): string | null {
  const q = new URLSearchParams(search).get("case");
  if (q && /^[A-Z]$/.test(q)) return q;
  const legacy = /(?:^|[#&])case=([A-Z])\b/.exec(hash); // links written before ?case=X was used
  return legacy ? legacy[1] : null;
}

export function urlWithCase(href: string, id: string | null): string {
  const url = new URL(href);
  if (id) url.searchParams.set("case", id);
  else url.searchParams.delete("case");
  if (/case=/.test(url.hash)) url.hash = ""; // drop a legacy #case=X, keep real anchors (#trace)
  return url.toString();
}
