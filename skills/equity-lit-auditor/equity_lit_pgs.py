"""equity_lit_pgs.py: PGS Catalog as a curated source of papers and populations.

The PGS Catalog (https://www.pgscatalog.org) curates, for every polygenic
score, the publications behind it and the ancestry, country and size of the
samples used at each stage:

    GWAS          samples_variants   -> the GWAS the variants came from (source_PMID)
    development   samples_training   -> the score's own publication
    evaluation    performance/search -> the publications that tested the score

Each stage's publication becomes a paper in the audit ("the references for
the dataset"), and the curated sample metadata becomes high-confidence
population records attached to that paper. REST API docs:
https://www.pgscatalog.org/rest/
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from equity_lit_extract import PopulationRecord, country_mentions

PGS_API = "https://www.pgscatalog.org/rest"
USER_AGENT = "ClawBio-equity-lit-auditor/0.1 (+https://github.com/ClawBio/ClawBio)"

STAGES = ("GWAS", "development", "evaluation")

# PGS Catalog / GWAS Catalog broad ancestry categories -> skill ancestry codes.
# OTH = multi-ancestry / admixed / other; NR = not reported.
BROAD_TO_CODE: list[tuple[str, str]] = [
    (r"not reported|^nr$", "NR"),
    (r"multi|admixed|other", "OTH"),
    (r"greater middle eastern|middle eastern|north african|persian", "MID"),
    (r"african american|afro[- ]caribbean|sub[- ]saharan|african", "AFR"),
    (r"south east asian|southeast asian|east asian", "EAS"),
    (r"south asian|central asian", "SAS"),
    (r"asian", "ASN"),
    (r"hispanic|latin american|native american", "AMR"),
    (r"oceanian|aboriginal|pacific", "OCE"),
    (r"european", "EUR"),
]


def split_labels(text: str) -> list[str]:
    """Split 'European, East Asian' on commas that are not inside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in text or "":
        depth += ch == "("
        depth -= ch == ")"
        if ch in ",;" and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def broad_to_codes(label: str) -> list[str]:
    codes: list[str] = []
    for part in split_labels(label):
        low = part.lower()
        for pat, code in BROAD_TO_CODE:
            if re.search(pat, low):
                codes.append(code)
                break
        else:
            codes.append("OTH")
    return codes or ["NR"]


def pub_seed(pub: dict | None) -> str | None:
    """Publication dict -> seed ID understood by literature.parse_seed."""
    if not pub:
        return None
    pmid = str(pub.get("PMID") or pub.get("pmid") or "").strip()
    if pmid.isdigit():
        return f"MED:{pmid}"
    if ":" in pmid:          # bundled demo fixture uses 'DEMO:D001'
        return pmid
    doi = (pub.get("doi") or "").strip()
    return f"DOI:{doi}" if doi else None


@dataclass
class PGSLink:
    """One (paper, score, stage) link with the curated sample sets for it."""

    seed: str
    pgs_id: str
    stage: str
    publication: dict = field(default_factory=dict)
    samples: list[dict] = field(default_factory=list)


@dataclass
class PGSResult:
    scores: list[dict] = field(default_factory=list)
    links: list[PGSLink] = field(default_factory=list)
    traits: list[dict] = field(default_factory=list)

    @property
    def seeds(self) -> list[str]:
        return list(dict.fromkeys(link.seed for link in self.links))


class PGSCatalogClient:
    def __init__(self, timeout: int = 30, delay: float = 0.2, cache_dir: Path | None = None):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, path: str, params: dict | None = None) -> dict:
        cache_file = None
        if self.cache_dir:
            key = re.sub(r"[^A-Za-z0-9]+", "_", "pgs_" + path + json.dumps(params or {}, sort_keys=True))[:200]
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                return json.loads(cache_file.read_text(encoding="utf-8"))
        time.sleep(self.delay)
        url = path if path.startswith("http") else f"{PGS_API}/{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        if cache_file:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _paged(self, path: str, params: dict, limit: int) -> list[dict]:
        out: list[dict] = []
        data = self._get(path, {**params, "limit": min(limit, 250)})
        while True:
            out.extend(data.get("results", []) or [])
            nxt = data.get("next")
            if len(out) >= limit or not nxt:
                break
            data = self._get(nxt)
        return out[:limit]

    def search_traits(self, term: str) -> list[dict]:
        return self._paged("trait/search", {"term": term}, 50)

    def scores_for_trait(self, efo_id: str, limit: int) -> list[dict]:
        return self._paged("score/search", {"trait_id": efo_id, "include_children": 1}, limit)

    def scores_by_ids(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 50):
            out.extend(self._paged("score/search", {"pgs_ids": ",".join(ids[i:i + 50])}, 50))
        return out

    def performance(self, pgs_id: str, limit: int = 100) -> list[dict]:
        return self._paged("performance/search", {"pgs_id": pgs_id}, limit)


class PGSFixtureClient:
    """Replays the 'pgs' block of the demo fixture with the PGSCatalogClient interface."""

    def __init__(self, path: Path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8")).get("pgs", {})

    def search_traits(self, term: str) -> list[dict]:
        return self.data.get("traits", [])

    def scores_for_trait(self, efo_id: str, limit: int) -> list[dict]:
        return [s for s in self.data.get("scores", {}).values()
                if any(t.get("id") == efo_id for t in s.get("trait_efo", []))][:limit]

    def scores_by_ids(self, ids: list[str]) -> list[dict]:
        scores = self.data.get("scores", {})
        return [scores[i] for i in ids if i in scores]

    def performance(self, pgs_id: str, limit: int = 100) -> list[dict]:
        return self.data.get("performance", {}).get(pgs_id, [])[:limit]


def _match_trait(traits: list[dict], term: str) -> list[dict]:
    """Prefer exact label matches; otherwise every trait whose label contains the term."""
    t = term.lower().strip()
    exact = [x for x in traits if (x.get("label") or "").lower() == t]
    if exact:
        return exact
    return [x for x in traits if t in (x.get("label") or "").lower()] or traits[:3]


def gather(client, trait: str | None, pgs_ids: list[str], max_scores: int, include_eval: bool,
           log=print) -> PGSResult:
    """Collect scores and turn their publications + sample sets into PGSLinks."""
    res = PGSResult()
    scores: dict[str, dict] = {}
    if trait:
        res.traits = _match_trait(client.search_traits(trait), trait)
        for tr in res.traits:
            for s in client.scores_for_trait(tr["id"], max_scores):
                scores.setdefault(s["id"], s)
                if len(scores) >= max_scores:
                    break
        log(f"  PGS Catalog: {len(res.traits)} trait(s) matched '{trait}': "
            + ", ".join(f"{t.get('label')} ({t.get('id')})" for t in res.traits))
    if pgs_ids:
        for s in client.scores_by_ids(pgs_ids):
            scores.setdefault(s["id"], s)
    res.scores = list(scores.values())[:max_scores]

    for s in res.scores:
        sid = s["id"]
        # GWAS stage: samples point at their own source GWAS publication.
        by_seed: dict[str, list[dict]] = {}
        for smp in s.get("samples_variants") or []:
            seed = pub_seed({"PMID": smp.get("source_PMID"), "doi": smp.get("source_DOI")}) or pub_seed(s.get("publication"))
            if seed:
                by_seed.setdefault(seed, []).append(smp)
        for seed, smps in by_seed.items():
            res.links.append(PGSLink(seed, sid, "GWAS", s.get("publication") or {}, smps))
        seed = pub_seed(s.get("publication"))
        if seed:
            res.links.append(PGSLink(seed, sid, "development", s.get("publication") or {},
                                     list(s.get("samples_training") or [])))
        if include_eval:
            for perf in client.performance(sid):
                pseed = pub_seed(perf.get("publication"))
                samples = ((perf.get("sampleset") or {}).get("samples")) or []
                if pseed:
                    res.links.append(PGSLink(pseed, sid, "evaluation", perf.get("publication") or {}, samples))
    log(f"  PGS Catalog: {len(res.scores)} score(s) -> {len(res.seeds)} linked publication(s)")
    return res


def curated_records(link: PGSLink) -> list[PopulationRecord]:
    """Curated PGS sample sets -> PopulationRecords (confidence 'curated')."""
    recs: list[PopulationRecord] = []
    for smp in link.samples:
        broad = smp.get("ancestry_broad") or "Not reported"
        codes = broad_to_codes(broad)
        n = smp.get("sample_number")
        n = int(n) if isinstance(n, (int, float)) or (isinstance(n, str) and n.isdigit()) else None
        countries = country_mentions(smp.get("ancestry_country") or "")
        cohorts = ", ".join(c.get("name_short", "") for c in smp.get("cohorts") or [] if c.get("name_short"))
        snippet = (f"{link.pgs_id} {link.stage}: {n if n is not None else 'NR'} {broad}"
                   + (f"; {smp.get('ancestry_country')}" if smp.get("ancestry_country") else "")
                   + (f"; cohorts {cohorts}" if cohorts else ""))
        # N is attributable to a group / country only when the sample set has exactly one.
        n_group = n if len(codes) == 1 else None
        for code in codes:
            recs.append(PopulationRecord(
                ancestry=code, iso3=None, n=n_group, term=broad, kind="pgs_catalog",
                section=f"PGS Catalog ({link.stage})", confidence="curated", snippet=snippet,
            ))
        for iso in countries:
            recs.append(PopulationRecord(
                ancestry=codes[0] if len(codes) == 1 else None, iso3=iso,
                n=n if len(countries) == 1 else None, term=smp.get("ancestry_country") or "",
                kind="pgs_catalog", section=f"PGS Catalog ({link.stage})", confidence="curated", snippet=snippet,
            ))
    return recs


def stage_ancestry(res: PGSResult) -> dict[str, dict[str, int]]:
    """Participants by ancestry code for each stage, across all scores.

    Sample sets are de-duplicated per (stage, publication, ancestry, N) so a
    GWAS reused by ten scores counts once.
    """
    out = {st: {} for st in STAGES}
    seen = set()
    for link in res.links:
        for smp in link.samples:
            n = smp.get("sample_number")
            if not isinstance(n, (int, float)):
                continue
            codes = broad_to_codes(smp.get("ancestry_broad") or "Not reported")
            key = (link.stage, link.seed, smp.get("ancestry_broad"), n)
            if key in seen:
                continue
            seen.add(key)
            code = codes[0] if len(codes) == 1 else "OTH"
            out[link.stage][code] = out[link.stage].get(code, 0) + int(n)
    return out
