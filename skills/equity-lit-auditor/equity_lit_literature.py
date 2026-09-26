"""equity_lit_literature.py: Europe PMC client and citation cascade for Equity Lit Auditor.

Europe PMC indexes all of PubMed plus PMC full text and exposes reference and
citation lists, which is what makes the cascade possible without an API key.
API docs: https://europepmc.org/RestfulWebService

All network I/O for the skill lives here. ``FixtureClient`` replays a local
JSON bundle through the same code path for --demo and tests.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import requests

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
USER_AGENT = "ClawBio-equity-lit-auditor/0.1 (+https://github.com/ClawBio/ClawBio)"

# Terms that make a cascaded paper worth auditing: it must describe human
# genetic/genomic data. Tool, methods and review papers usually fail this and
# are kept in the table but excluded from the population map.
GENOMIC_STUDY_RE = re.compile(
    r"\b(genome[- ]wide|GWAS|whole[- ](?:genome|exome)|exome|sequenc(?:ing|ed)|genotyp|"
    r"polygenic|SNPs?\b|single[- ]nucleotide|genetic (?:association|variant|architecture|risk)|"
    r"heritability|biobank|pharmacogen|admixture|allele frequenc|fine[- ]mapping|eQTL)",
    re.IGNORECASE,
)

METHODS_SECTION_RE = re.compile(
    r"method|material|participant|subject|population|cohort|sample|study design|data source|recruit",
    re.IGNORECASE,
)


@dataclass
class Paper:
    """One literature record, normalised from Europe PMC ``core`` results."""

    id: str
    source: str
    title: str = ""
    abstract: str = ""
    year: str = ""
    journal: str = ""
    authors: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    is_open_access: bool = False
    cited_by: int = 0
    affiliations: list[str] = field(default_factory=list)
    mesh: list[str] = field(default_factory=list)
    methods_text: str = ""
    depth: int = 0
    via: str = "search"          # search | seed | pgs | reference | citation
    parent: str = ""             # key of the paper that led here
    pgs: list[str] = field(default_factory=list)   # "PGS000013 (development)" links

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def url(self) -> str:
        if self.source in {"MED", "PMC", "PPR", "AGR", "CBA", "CTX", "ETH", "HIR", "PAT"}:
            return f"https://europepmc.org/article/{self.source}/{self.id}"
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return ""

    @property
    def is_genomic_study(self) -> bool:
        if self.pgs:  # every PGS Catalog publication describes human genomic data
            return True
        return bool(GENOMIC_STUDY_RE.search(f"{self.title} {self.abstract} {' '.join(self.mesh)}"))


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def paper_from_publication(seed_src: str, seed_id: str, pub: dict) -> Paper:
    """Minimal Paper from a PGS Catalog publication when Europe PMC has no record."""
    date = str(pub.get("date_publication") or "")
    return Paper(
        id=seed_id, source=seed_src, title=_strip_tags(pub.get("title", "")), year=date[:4],
        journal=pub.get("journal", "") or "", authors=pub.get("firstauthor", "") or "",
        doi=pub.get("doi", "") or "", pmid=str(pub.get("PMID") or "") if str(pub.get("PMID") or "").isdigit() else "",
        via="pgs",
    )


def paper_from_record(rec: dict, depth: int = 0, via: str = "search", parent: str = "") -> Paper:
    """Build a Paper from a Europe PMC search result (resultType=core)."""
    affiliations: list[str] = []
    for author in (rec.get("authorList") or {}).get("author", []) or []:
        details = (author.get("authorAffiliationDetailsList") or {}).get("authorAffiliation", []) or []
        for d in details:
            if d.get("affiliation"):
                affiliations.append(d["affiliation"])
        if author.get("affiliation"):
            affiliations.append(author["affiliation"])
    if rec.get("affiliation"):
        affiliations.append(rec["affiliation"])
    mesh = [
        m.get("descriptorName", "")
        for m in (rec.get("meshHeadingList") or {}).get("meshHeading", []) or []
    ]
    journal = (
        ((rec.get("journalInfo") or {}).get("journal") or {}).get("title")
        or rec.get("journalTitle")
        or rec.get("bookOrReportDetails", {}).get("publisher", "")
        or ""
    )
    return Paper(
        id=str(rec.get("id", "")),
        source=str(rec.get("source", "")),
        title=_strip_tags(rec.get("title", "")),
        abstract=_strip_tags(rec.get("abstractText", "")),
        year=str(rec.get("pubYear", "")),
        journal=journal,
        authors=rec.get("authorString", ""),
        doi=rec.get("doi", ""),
        pmid=str(rec.get("pmid", "")),
        pmcid=rec.get("pmcid", ""),
        is_open_access=rec.get("isOpenAccess") == "Y",
        cited_by=int(rec.get("citedByCount") or 0),
        affiliations=list(dict.fromkeys(affiliations)),
        mesh=[m for m in mesh if m],
        depth=depth,
        via=via,
        parent=parent,
    )


def methods_from_fulltext_xml(xml_text: str, max_chars: int = 20000) -> str:
    """Pull participant-describing sections out of a JATS full-text XML.

    Only methods-like sections are kept: scanning the Discussion or the
    Introduction would pick up populations the paper merely mentions.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    chunks: list[str] = []
    for sec in root.iter("sec"):
        title_el = sec.find("title")
        title = "".join(title_el.itertext()) if title_el is not None else ""
        sec_type = sec.get("sec-type", "")
        if METHODS_SECTION_RE.search(title) or METHODS_SECTION_RE.search(sec_type):
            paras = [" ".join("".join(p.itertext()).split()) for p in sec.findall("p")]
            if paras:
                chunks.append(f"[{title.strip() or sec_type}] " + " ".join(paras))
    text = " ".join(chunks)
    return text[:max_chars]


class EuropePMCClient:
    """Thin, polite client for the Europe PMC REST API."""

    def __init__(self, timeout: int = 20, delay: float = 0.15, cache_dir: Path | None = None):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    # -- low level -------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, as_json: bool = True):
        cache_file = None
        if self.cache_dir:
            key = re.sub(r"[^A-Za-z0-9]+", "_", path + json.dumps(params or {}, sort_keys=True))[:200]
            cache_file = self.cache_dir / (key + (".json" if as_json else ".xml"))
            if cache_file.exists():
                text = cache_file.read_text(encoding="utf-8")
                return json.loads(text) if as_json else text
        time.sleep(self.delay)
        self.calls += 1
        resp = self.session.get(f"{EPMC_BASE}/{path}", params=params, timeout=self.timeout)
        if resp.status_code == 404:
            return {} if as_json else ""
        resp.raise_for_status()
        if cache_file:
            cache_file.write_text(resp.text, encoding="utf-8")
        return resp.json() if as_json else resp.text

    # -- API -------------------------------------------------------------
    def search(self, query: str, limit: int = 25) -> list[dict]:
        results: list[dict] = []
        cursor = "*"
        while len(results) < limit:
            page = min(100, limit - len(results))
            data = self._get("search", {
                "query": query, "format": "json", "resultType": "core",
                "pageSize": page, "cursorMark": cursor, "sort": "CITED desc",
            })
            batch = (data.get("resultList") or {}).get("result", []) or []
            results.extend(batch)
            nxt = data.get("nextCursorMark")
            if not batch or not nxt or nxt == cursor:
                break
            cursor = nxt
        return results[:limit]

    def fetch_records(self, keys: list[tuple[str, str]]) -> list[dict]:
        """Fetch core records for (source, id) pairs, 20 per request."""
        out: list[dict] = []
        for i in range(0, len(keys), 20):
            chunk = keys[i:i + 20]
            q = " OR ".join(f"(EXT_ID:{pid} AND SRC:{src})" for src, pid in chunk)
            data = self._get("search", {"query": q, "format": "json", "resultType": "core",
                                        "pageSize": len(chunk)})
            out.extend((data.get("resultList") or {}).get("result", []) or [])
        return out

    def references(self, source: str, pid: str, limit: int) -> list[dict]:
        data = self._get(f"{source}/{pid}/references", {"format": "json", "pageSize": min(limit, 1000)})
        return ((data.get("referenceList") or {}).get("reference", []) or [])[:limit]

    def citations(self, source: str, pid: str, limit: int) -> list[dict]:
        data = self._get(f"{source}/{pid}/citations", {"format": "json", "pageSize": min(limit, 1000)})
        return ((data.get("citationList") or {}).get("citation", []) or [])[:limit]

    def fulltext_xml(self, pmcid: str) -> str:
        return self._get(f"{pmcid}/fullTextXML", as_json=False) or ""


class FixtureClient:
    """Replays a bundled JSON fixture with the same interface as EuropePMCClient.

    Fixture layout: {"search": {query: [records]}, "records": {"SRC:ID": record},
    "references": {"SRC:ID": [refs]}, "citations": {...}, "fulltext": {PMCID: xml}}.
    A search for an unknown query returns every record flagged ``"seed": true``.
    """

    def __init__(self, path: Path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.calls = 0

    def search(self, query: str, limit: int = 25) -> list[dict]:
        hits = self.data.get("search", {}).get(query)
        if hits is None:
            hits = [r for r in self.data["records"].values() if r.get("seed")]
        return hits[:limit]

    def fetch_records(self, keys: list[tuple[str, str]]) -> list[dict]:
        recs = self.data["records"]
        return [recs[f"{s}:{i}"] for s, i in keys if f"{s}:{i}" in recs]

    def references(self, source: str, pid: str, limit: int) -> list[dict]:
        return self.data.get("references", {}).get(f"{source}:{pid}", [])[:limit]

    def citations(self, source: str, pid: str, limit: int) -> list[dict]:
        return self.data.get("citations", {}).get(f"{source}:{pid}", [])[:limit]

    def fulltext_xml(self, pmcid: str) -> str:
        return self.data.get("fulltext", {}).get(pmcid, "")


def parse_seed(seed: str) -> tuple[str, str]:
    """'PMID:123' / '123' -> ('MED','123'); 'PMC123' -> ('PMC','PMC123'); 'DOI:10.x' -> ('DOI','10.x')."""
    s = seed.strip()
    if re.fullmatch(r"(?i)pmid:\s*\d+", s):
        return "MED", s.split(":", 1)[1].strip()
    if s.isdigit():
        return "MED", s
    if re.fullmatch(r"(?i)PMC\d+", s):
        return "PMC", s.upper()
    if s.lower().startswith("doi:") or s.startswith("10."):
        return "DOI", s.split(":", 1)[1].strip() if s.lower().startswith("doi:") else s
    if ":" in s:
        src, pid = s.split(":", 1)
        return src.upper(), pid
    raise ValueError(f"Unrecognised seed identifier: {seed!r}")


def collect_papers(
    client,
    query: str | None,
    seeds: list[str],
    max_results: int,
    cascade: str,
    depth: int,
    per_paper: int,
    max_papers: int,
    fulltext: bool,
    log=print,
) -> list[Paper]:
    """Search + optional reference/citation cascade. Returns de-duplicated Papers."""
    papers: dict[str, Paper] = {}

    initial: list[Paper] = []
    if query:
        for rec in client.search(query, limit=max_results):
            initial.append(paper_from_record(rec, 0, "search"))
    if seeds:
        parsed = [parse_seed(s) for s in seeds]
        doi_seeds = [pid for src, pid in parsed if src == "DOI"]
        id_seeds = [(src, pid) for src, pid in parsed if src != "DOI"]
        recs = client.fetch_records(id_seeds) if id_seeds else []
        for doi in doi_seeds:
            recs.extend(client.search(f'DOI:"{doi}"', limit=1))
        for rec in recs:
            initial.append(paper_from_record(rec, 0, "seed"))
    for p in initial:
        papers.setdefault(p.key, p)
    log(f"  {len(papers)} initial paper(s)")

    frontier = list(papers.values())
    directions = {"references": ["reference"], "citations": ["citation"],
                  "both": ["reference", "citation"]}.get(cascade, [])
    for level in range(1, depth + 1):
        if not directions or len(papers) >= max_papers:
            break
        found: list[tuple[str, str, str, str]] = []  # (src, id, via, parent)
        for parent in frontier:
            if parent.source in {"", "DOI"}:
                continue
            for via in directions:
                fn = client.references if via == "reference" else client.citations
                try:
                    items = fn(parent.source, parent.id, per_paper)
                except requests.RequestException as exc:  # keep going on partial failure
                    log(f"  warning: {via} lookup failed for {parent.key}: {exc}")
                    continue
                for it in items:
                    if it.get("id") and it.get("source"):
                        found.append((it["source"], str(it["id"]), via, parent.key))
        new = [(s, i, v, par) for s, i, v, par in found if f"{s}:{i}" not in papers]
        new = list({f"{s}:{i}": (s, i, v, par) for s, i, v, par in new}.values())
        room = max_papers - len(papers)
        new = new[:room]
        if not new:
            break
        meta = {f"{s}:{i}": (v, par) for s, i, v, par in new}
        frontier = []
        for rec in client.fetch_records([(s, i) for s, i, _, _ in new]):
            k = f"{rec.get('source')}:{rec.get('id')}"
            via, par = meta.get(k, ("reference", ""))
            p = paper_from_record(rec, level, via, par)
            if k not in papers:
                papers[k] = p
                frontier.append(p)
        log(f"  cascade depth {level}: +{len(frontier)} paper(s) via {cascade}")

    if fulltext:
        n = 0
        for p in papers.values():
            if p.is_open_access and p.pmcid and p.is_genomic_study:
                try:
                    p.methods_text = methods_from_fulltext_xml(client.fulltext_xml(p.pmcid))
                    n += bool(p.methods_text)
                except requests.RequestException as exc:
                    log(f"  warning: full text unavailable for {p.pmcid}: {exc}")
        log(f"  methods sections read from {n} open-access full text(s)")
    return list(papers.values())
