"""PGS Catalog client and normalized evidence auditor for PRSGuard (shared by the gate, equity-lit and the UI).

Moved from the hackathon skill (skills/prs-applicability-gate/prsguard_pgs_audit.py): searching and auditing the
Catalog is orchestration, upstream of the gate. The deterministic gate only consumes the normalized record.

Original description:

Fetches the authoritative metadata for one PGS score and turns it into an
auditable evidence record:

    /rest/score/{PGS_ID}                  score, trait, variant count, weight type, publication,
                                          GWAS / development / evaluation ancestry
    /rest/performance/search?pgs_id=...   evaluation sample sets (PSS / PPM / PGP ids)
    /rest/ancestry_categories             the Catalog's own ancestry vocabulary
    /rest/info                            API version and Catalog release (provenance)

The evaluation view is re-derived from the performance records exactly as the
Catalog derives ``ancestry_distribution.eval`` (PGS_Catalog
release/scripts/UpdateScoreAncestry.py): one ancestry code per
(publication, sample set) unit, MAE/MAO when a unit pools several ancestries,
and the Catalog's own percentage rounding. Any disagreement with the published
distribution makes the metadata ``contradictory``; missing or mistyped
required fields make it ``unresolved``. GWAS and development distributions
are re-derived the same way but only as advisory checks. Only the PGS
identifier is ever sent over the network.

Every response is kept as raw bytes with its URL, retrieval time and SHA-256,
and can be written out as a snapshot directory that replays offline
(``SnapshotCatalogSource``).
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_BASE = "https://www.pgscatalog.org/rest"
USER_AGENT = "ClawBio-PRSGuard/0.1.0 (+https://github.com/ClawBio/ClawBio)"
RATE_LIMIT_INTERVAL = 0.55  # seconds; the Catalog asks clients to stay under ~2 req/s
MAX_ATTEMPTS = 4            # transient 429/5xx/connection errors are retried with backoff
MAX_RETRY_WAIT = 30.0       # seconds; bounds any Retry-After the server sends
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_PERFORMANCE_PAGES = 50
SNAPSHOT_MANIFEST = "SNAPSHOT.json"
SNAPSHOT_SCHEMA = "prsguard.pgs_snapshot.v1"
PGS_ID_RE = re.compile(r"^PGS\d{6,}$")
PGP_ID_RE = re.compile(r"^PGP\d{6,}$")
DIST_SUM_TOLERANCE = 1.0      # published percentages are rounded to 0.1
DIST_CROSSCHECK_TOLERANCE = 0.15
STAGES = ("gwas", "dev", "eval")
MULTI_CODES = ("MAE", "MAO")


class MetadataUnavailable(RuntimeError):
    """Raised when authoritative metadata cannot be obtained or trusted."""


@dataclass
class RawResponse:
    endpoint: str
    url: str
    content: bytes
    retrieved_at: str | None
    snapshot_path: str

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetadataUnavailable(f"{self.endpoint}: response is not valid JSON ({type(exc).__name__})") from exc

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def snapshot_relpath(endpoint: str, page: int = 1) -> str:
    if endpoint.startswith("score/"):
        return f"{endpoint.split('/', 1)[1]}/score.json"
    if endpoint in ("ancestry_categories", "info"):
        return f"{endpoint}.json"
    raise ValueError(f"unsupported endpoint {endpoint!r}")


def performance_relpath(pgs_id: str, page: int) -> str:
    return f"{pgs_id}/performance_search_p{page}.json"


TRAIT_ID_RE = re.compile(r"^[A-Za-z]+_[0-9]+$")


def trait_search_relpath(trait_id: str, page: int) -> str:
    return f"trait_search/{trait_id}_p{page}.json"


def _relpath(endpoint: str, page: int, pgs_id: str | None, trait_id: str | None) -> str:
    if endpoint == "performance/search":
        return performance_relpath(pgs_id, page)
    if endpoint == "score/search":
        return trait_search_relpath(trait_id, page)
    if endpoint == "trait/search":
        slug = re.sub(r"[^a-z0-9]+", "_", (trait_id or "").lower()).strip("_")[:80]
        return f"trait_lookup/search_{slug}_p{page}.json"
    if endpoint.startswith("trait/"):
        return f"trait_lookup/{endpoint.split('/', 1)[1]}.json"
    return snapshot_relpath(endpoint)


def contained_path(base: Path, rel: str) -> Path:
    """``base / rel`` if it stays inside ``base``; otherwise ValueError (no traversal)."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        raise ValueError(f"unsafe snapshot path {rel!r}")
    path = (Path(base) / rel).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise ValueError(f"unsafe snapshot path {rel!r}")
    return path


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _describe(exc: BaseException) -> str:
    """Exception text without local filesystem paths."""
    if isinstance(exc, OSError):
        return f"{type(exc).__name__}: {exc.strerror or 'I/O error'}"
    return f"{type(exc).__name__}"


def _retry_wait(resp: Any, attempt: int) -> float:
    header = (getattr(resp, "headers", None) or {}).get("Retry-After")
    wait = float(2 ** attempt)
    if header:
        try:
            wait = float(header)
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(header)
                wait = (when - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError):
                pass
    return max(0.0, min(MAX_RETRY_WAIT, wait))


class LiveCatalogSource:
    """Fetch from the public PGS Catalog REST API."""

    mode = "live"

    def __init__(self, api_base: str = API_BASE, timeout: float = 30.0, session: Any = None,
                 sleep: Any = time.sleep):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._session = session
        self._sleep = sleep
        self._last = 0.0
        self.catalog_release: str | None = None
        self.api_version: str | None = None
        self.attempts = 0

    def _get(self, url: str, params: dict | None) -> Any:
        import requests  # imported lazily so offline runs never need it

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp = None
        for attempt in range(MAX_ATTEMPTS):
            wait = RATE_LIMIT_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self.attempts += 1
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._last = time.monotonic()
                if attempt < MAX_ATTEMPTS - 1:
                    self._sleep(float(2 ** attempt))
                    continue
                raise MetadataUnavailable(f"GET {url} failed after {MAX_ATTEMPTS} attempts: "
                                          f"{type(exc).__name__}") from exc
            except requests.RequestException as exc:
                raise MetadataUnavailable(f"GET {url} failed: {type(exc).__name__}") from exc
            self._last = time.monotonic()
            if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
                self._sleep(_retry_wait(resp, attempt))
                continue
            break
        if resp is None or resp.status_code != 200:
            code = getattr(resp, "status_code", "no response")
            raise MetadataUnavailable(f"GET {getattr(resp, 'url', url)} returned HTTP {code}")
        return resp

    def fetch(self, endpoint: str, params: dict | None = None, *, url: str | None = None,
              page: int = 1, pgs_id: str | None = None, trait_id: str | None = None) -> RawResponse:
        target = url or f"{self.api_base}/{endpoint}"
        resp = self._get(target, None if url else params)
        raw = RawResponse(endpoint, resp.url, resp.content, _now(), _relpath(endpoint, page, pgs_id, trait_id))
        if endpoint == "info":
            doc = raw.json()
            if isinstance(doc, dict):
                self.catalog_release = (doc.get("latest_release") or {}).get("date")
                self.api_version = (doc.get("rest_api") or {}).get("version")
        return raw


class SnapshotCatalogSource:
    """Replay recorded responses from a snapshot directory with a checksum manifest."""

    mode = "snapshot"

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.manifest: dict = {}
        self.error: str | None = None
        try:
            doc = json.loads((self.directory / SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not isinstance(doc.get("files"), dict):
                raise ValueError("manifest has no 'files' object")
            self.manifest = doc
        except (OSError, ValueError) as exc:
            self.error = f"snapshot manifest {SNAPSHOT_MANIFEST} unusable in {self.directory.name}/: {_describe(exc)}"
        self.api_base = self.manifest.get("api_base", API_BASE)
        self.catalog_release = self.manifest.get("catalog_release")
        self.api_version = self.manifest.get("api_version")

    def entry(self, rel: str) -> dict | None:
        entry = (self.manifest.get("files") or {}).get(rel)
        return entry if isinstance(entry, dict) else None

    def read_file(self, rel: str) -> tuple[bytes, dict]:
        """Bytes of a manifest-listed file, verified against its recorded sha256."""
        if self.error:
            raise MetadataUnavailable(self.error)
        entry = self.entry(rel)
        if entry is None:
            raise MetadataUnavailable(f"snapshot {self.directory.name}/ has no {rel}")
        try:
            content = contained_path(self.directory, rel).read_bytes()
        except (OSError, ValueError) as exc:
            raise MetadataUnavailable(f"snapshot file {rel} unreadable: {_describe(exc)}") from exc
        if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
            raise MetadataUnavailable(f"snapshot checksum mismatch for {rel}: file differs from its manifest")
        return content, entry

    def verified_path(self, rel: str) -> tuple[Path, dict]:
        """Path of a manifest-listed file whose bytes match the manifest (for large files)."""
        self.read_file(rel)
        return contained_path(self.directory, rel), self.entry(rel) or {}

    def fetch(self, endpoint: str, params: dict | None = None, *, url: str | None = None,
              page: int = 1, pgs_id: str | None = None, trait_id: str | None = None) -> RawResponse:
        rel = _relpath(endpoint, page, pgs_id, trait_id)
        content, entry = self.read_file(rel)
        return RawResponse(endpoint, entry.get("url", ""), content, entry.get("retrieved_at"), rel)


def fetch_catalog_records(pgs_id: str, source: Any, collected: list[RawResponse]) -> dict:
    """Fetch every response the audit needs; appends each to ``collected``."""
    if not isinstance(pgs_id, str) or not PGS_ID_RE.match(pgs_id):
        raise MetadataUnavailable(f"{pgs_id!r} is not a PGS Catalog score id")
    score = source.fetch(f"score/{pgs_id}")
    collected.append(score)
    pages = []
    params = {"pgs_id": pgs_id, "limit": 100}
    resp = source.fetch("performance/search", params, page=1, pgs_id=pgs_id)
    for page in range(1, MAX_PERFORMANCE_PAGES + 1):
        collected.append(resp)
        doc = resp.json()
        if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
            raise MetadataUnavailable("performance/search response has no results list")
        pages.append(doc)
        nxt = doc.get("next")
        if not nxt:
            break
        resp = source.fetch("performance/search", params, url=nxt, page=page + 1, pgs_id=pgs_id)
    else:
        raise MetadataUnavailable(f"performance/search exceeded {MAX_PERFORMANCE_PAGES} pages")
    cats = source.fetch("ancestry_categories")
    collected.append(cats)
    try:
        info = source.fetch("info")
        collected.append(info)
    except MetadataUnavailable:
        info = None  # release metadata is provenance, not evidence
    categories = cats.json()
    if not isinstance(categories, dict):
        raise MetadataUnavailable("ancestry_categories response is not an object")
    return {"score": score.json(), "performance": [r for p in pages for r in p["results"]],
            "categories": categories, "info": info.json() if info else None}


def fetch_trait_search(trait_id: str, source: Any, collected: list[RawResponse]) -> list[dict]:
    """All scores the Catalog maps to ``trait_id`` (/rest/score/search?trait_id=...), every page kept."""
    if not isinstance(trait_id, str) or not TRAIT_ID_RE.match(trait_id):
        raise MetadataUnavailable(f"{trait_id!r} is not an ontology trait id")
    params = {"trait_id": trait_id, "limit": 250}
    resp = source.fetch("score/search", params, page=1, trait_id=trait_id)
    results: list[dict] = []
    for page in range(1, MAX_PERFORMANCE_PAGES + 1):
        collected.append(resp)
        doc = resp.json()
        if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
            raise MetadataUnavailable("score/search response has no results list")
        results += [r for r in doc["results"] if isinstance(r, dict)]
        if not doc.get("next"):
            return results
        resp = source.fetch("score/search", params, url=doc["next"], page=page + 1, trait_id=trait_id)
    raise MetadataUnavailable(f"score/search exceeded {MAX_PERFORMANCE_PAGES} pages")


# ---------------------------------------------------------------------------
# Ancestry vocabulary: the Catalog's own coding rules
# ---------------------------------------------------------------------------


def build_vocabulary(categories: dict) -> dict[str, str]:
    """Map every ancestry label the Catalog uses (lower-cased) to its code."""
    vocab: dict[str, str] = {}
    for code, entry in (categories or {}).items():
        if not isinstance(entry, dict):
            continue
        for label in entry.get("categories") or []:
            if isinstance(label, str):
                vocab[label.strip().lower()] = code
        display = entry.get("display_category")
        if isinstance(display, str):
            vocab[display.strip().lower()] = code
    return vocab


def catalog_ancestry_code(label: Any, vocab: dict[str, str]) -> tuple[str, bool]:
    """(code, recognised) exactly as UpdateScoreAncestry.get_ancestry_code assigns it.

    '' is NR; a vocabulary label maps to its code; any other comma-separated label
    is multi-ancestry (MAE if it mentions European, else MAO); anything else is
    OTH and reported as unrecognised.
    """
    lab = label.strip() if isinstance(label, str) else ""
    if not lab:
        return "NR", True
    if lab.lower() in vocab:
        return vocab[lab.lower()], True
    if "," in lab:
        return ("MAE" if "European" in lab else "MAO"), True
    return "OTH", False


def map_ancestry_broad(label: Any, vocab: dict[str, str]) -> str | None:
    """Catalog code for a non-empty, recognised ``ancestry_broad`` label, else None."""
    if not isinstance(label, str) or not label.strip():
        return None
    code, known = catalog_ancestry_code(label, vocab)
    return code if known else None


def catalog_percent(value: float, total: float, n_codes: int) -> float:
    """The Catalog's percentage formatting (UpdateScoreAncestry.update_ancestry)."""
    pct = (100.0 / n_codes) if total == 0 else (100.0 * value / total)
    text = f"{pct:.2f}".replace(".00", "") if pct < 0.1 else f"{pct:.1f}".replace(".0", "")
    return float(text)


def _multi_components(code: str, label: str, vocab: dict[str, str], multi: list[str]) -> list[str]:
    """UpdateScoreAncestry.update_multi_ancestry_details: component codes of a multi-ancestry label."""
    if code not in MULTI_CODES:
        return multi
    protected = sorted((k for k in vocab if "," in k), key=len, reverse=True)
    text = label
    for k in protected:
        text = re.sub(re.escape(k), lambda m: m.group(0).replace(",", "\x00"), text, flags=re.I)
    parts = [p.strip().replace("\x00", ",") for p in text.split(",")]
    key = "MAE" if "European" in parts else "MAO"
    for part in parts:
        sub, _ = catalog_ancestry_code(part, vocab)
        if sub not in MULTI_CODES and f"{key}_{sub}" not in multi:
            multi.append(f"{key}_{sub}")
    return multi


def stage_distribution(samples: list[dict], vocab: dict[str, str]) -> tuple[dict[str, float], int, list[str]]:
    """Re-derive a GWAS/development distribution (UpdateScoreAncestry.get_samples_ancestry_data)."""
    data: dict[str, float] = {}
    multi: list[str] = []
    total = 0
    for s in samples:
        n = s.get("sample_number") if _is_int(s.get("sample_number")) else None
        if not n:
            if len(samples) == 1:
                n = 0
            else:
                continue
        label = (s.get("ancestry_broad") or "").strip() if isinstance(s.get("ancestry_broad"), str) else ""
        code, _ = catalog_ancestry_code(label, vocab)
        if code not in data:
            data[code] = n
            multi = _multi_components(code, label, vocab, multi)
        else:
            data[code] += n
        total += n
    if len(data) == 1 and total == 0:
        data = {k: 1 for k in data}
    if len(multi) == 1:
        ma, anc = multi[0].split("_", 1)
        data[anc] = data.get(anc, 0) + data.pop(ma, 0)
        multi = []
    pct = {k: catalog_percent(v, total, len(data)) for k, v in data.items()}
    return pct, total, multi


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _str_or_none(x: Any) -> str | None:
    if x is None or x == "":
        return None
    return str(x)


def _stage(ad: dict, stage: str) -> dict | None:
    block = ad.get(stage) if isinstance(ad, dict) else None
    return block if isinstance(block, dict) else None


def _dist(block: dict | None) -> dict[str, float]:
    if not block or not isinstance(block.get("dist"), dict):
        return {}
    return {k: float(v) for k, v in block["dist"].items() if _is_num(v)}


def _records(x: Any) -> list[dict]:
    return [r for r in x if isinstance(r, dict)] if isinstance(x, list) else []


def _samples(records: Any, vocab: dict[str, str]) -> list[dict]:
    out = []
    for s in _records(records):
        code, known = catalog_ancestry_code(s.get("ancestry_broad"), vocab)
        out.append({
            "ancestry_broad": s.get("ancestry_broad"),
            "code": code,
            "code_recognised": known,
            "n": s.get("sample_number") if _is_int(s.get("sample_number")) else None,
            "cases": s.get("sample_cases") if _is_int(s.get("sample_cases")) else None,
            "controls": s.get("sample_controls") if _is_int(s.get("sample_controls")) else None,
            "percent_male": s.get("sample_percent_male") if _is_num(s.get("sample_percent_male")) else None,
            "countries": s.get("ancestry_country"),
            "gwas_catalog_id": s.get("source_GWAS_catalog"),
            "source_pmid": _str_or_none(s.get("source_PMID")),
            "cohorts": sorted({c.get("name_short") for c in s.get("cohorts") or []
                               if isinstance(c, dict) and isinstance(c.get("name_short"), str)}),
        })
    return out


def _required_field_problems(score: Any) -> list[str]:
    problems = []
    if not isinstance(score, dict):
        return ["score response is not a JSON object"]
    if not isinstance(score.get("id"), str):
        problems.append("id missing")
    if not isinstance(score.get("trait_reported"), str) or not score["trait_reported"].strip():
        problems.append("trait_reported missing or empty")
    vn = score.get("variants_number")
    if not _is_int(vn) or vn <= 0:
        problems.append(f"variants_number must be a positive integer (got {vn!r})")
    pub = score.get("publication")
    if not isinstance(pub, dict) or not isinstance(pub.get("id"), str) or not PGP_ID_RE.match(pub["id"]):
        problems.append("publication.id (PGP accession) missing or malformed")
    if "trait_efo" in score and not isinstance(score["trait_efo"], list):
        problems.append("trait_efo is not a list")
    if "weight_type" in score and score["weight_type"] is not None and not isinstance(score["weight_type"], str):
        problems.append("weight_type is not a string")
    ad = score.get("ancestry_distribution")
    if not isinstance(ad, dict):
        problems.append("ancestry_distribution missing or not an object")
    else:
        for stage in STAGES:
            if stage not in ad:
                continue
            block = ad[stage]
            if not isinstance(block, dict):
                problems.append(f"ancestry_distribution.{stage} is not an object")
                continue
            dist, count = block.get("dist"), block.get("count")
            if not isinstance(dist, dict) or not all(isinstance(k, str) and _is_num(v) for k, v in dist.items()):
                problems.append(f"ancestry_distribution.{stage}.dist is not a code->number map")
            if not _is_int(count) or count < 0:
                problems.append(f"ancestry_distribution.{stage}.count is not a non-negative integer")
    return problems


def _trait_matches(query: str, score: dict) -> bool:
    q = " ".join(query.lower().split())
    labels = [score.get("trait_reported") or ""]
    labels += [t.get("label") or "" for t in score.get("trait_efo") or [] if isinstance(t, dict)]
    for label in labels:
        lab = " ".join(str(label).lower().split())
        if lab and (q in lab or lab in q):
            return True
    return False


def _dist_diffs(declared: dict[str, float], derived: dict[str, float]) -> list[str]:
    diffs = []
    for code in sorted(set(declared) | set(derived)):
        a, b = declared.get(code, 0.0), derived.get(code, 0.0)
        if abs(a - b) > DIST_CROSSCHECK_TOLERANCE:
            diffs.append(f"{code}: declared {a:g} vs derived {b:g}")
    return diffs


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

RATIO_METRICS = {"OR", "HR", "RR", "SHR"}
EFFECT_METRICS = {"β", "BETA", "B"}
DISCRIMINATION_METRICS = {"AUROC", "AUC", "C-INDEX", "C-STATISTIC", "C"}


CORRELATION_RE = re.compile(r"partial[- ]?r\b|partial correlation|pearson|spearman|correlation coefficient", re.I)


def _metric_null(name: str, name_long: str | None = None) -> float | None:
    """Null value of a performance metric, or None when it has no usable null.

    Correlations (incl. partial-r) have null 0 and can be negative, so a CI excluding 0 is meaningful. R² and
    other variance-explained metrics deliberately get no null: they cannot be negative, and bootstrap intervals
    of a non-negative statistic exclude 0 almost by construction.
    """
    n = (name or "").strip().upper()
    if n in RATIO_METRICS:
        return 1.0
    if n in EFFECT_METRICS:
        return 0.0
    if n in DISCRIMINATION_METRICS:
        return 0.5
    text = f"{name or ''} {name_long or ''}"
    if CORRELATION_RE.search(text) and "R²" not in text and "R2" not in text.upper().replace(" ", ""):
        return 0.0
    return None


def performance_metrics(rec: dict) -> list[dict]:
    """Every reported metric with its estimate, 95% interval and whether that interval lies above the null.

    ``informative``: True if a CI exists and lies entirely ABOVE the metric's null (OR/HR/RR=1, beta=0,
    AUC/C=0.5, r=0), i.e. evidence of association in the direction the score is built for (higher score, higher
    risk); False if the CI includes the null or lies below it (an inverse association, e.g. case-only subtype
    comparisons); None if there is no CI or the metric has no defined null (e.g. R², E/O). ``direction`` says which.
    Evidence of association is not evidence of clinically useful discrimination or calibration.
    """
    pm = rec.get("performance_metrics") if isinstance(rec.get("performance_metrics"), dict) else {}
    out = []
    for group in ("effect_sizes", "class_acc", "othermetrics"):
        for m in pm.get(group) or []:
            if not isinstance(m, dict):
                continue
            name = m.get("name_short") or m.get("name_long")
            est, lo, hi = (m.get(k) if _is_num(m.get(k)) else None for k in ("estimate", "ci_lower", "ci_upper"))
            null = _metric_null(str(name), m.get("name_long"))
            informative = direction = None
            if null is not None and lo is not None and hi is not None:
                direction = "above_null" if lo > null else "below_null" if hi < null else "includes_null"
                informative = direction == "above_null"
            out.append({"group": group, "name": name, "name_long": m.get("name_long"), "estimate": est,
                        "ci_lower": lo, "ci_upper": hi, "se": m.get("se") if _is_num(m.get("se")) else None,
                        "null": null, "informative": informative, "direction": direction})
    return out


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_score_metadata(pgs_id: str, score: Any, performance: list[dict], categories: dict, *,
                         trait_query: str | None = None, scoring_file_header: dict | None = None) -> dict:
    """Parse and cross-check authoritative metadata for one score (pure; no I/O)."""
    checks: list[dict] = []

    def check(check_id: str, status: str, detail: str, *, blocking: bool = True, kind: str = "consistency"):
        checks.append({"check_id": check_id, "status": status, "detail": detail,
                       "blocking": blocking, "kind": kind})

    vocab = build_vocabulary(categories)
    known_codes = set((categories or {}).keys()) if isinstance(categories, dict) else set()
    score = score if isinstance(score, dict) else {}
    performance = _records(performance)

    if score.get("id") == pgs_id:
        check("SCORE_ID_MATCH", "pass", f"response id {pgs_id}", kind="resolution")
    else:
        check("SCORE_ID_MATCH", "fail", f"requested {pgs_id}, response id {score.get('id')!r}", kind="resolution")
    problems = _required_field_problems(score)
    if not known_codes:
        problems.append("ancestry category vocabulary is empty")
    check("REQUIRED_FIELDS", "fail" if problems else "pass",
          "; ".join(problems) or "all required fields present and typed", kind="resolution")

    ad = score.get("ancestry_distribution") if isinstance(score.get("ancestry_distribution"), dict) else {}
    pub = score.get("publication") if isinstance(score.get("publication"), dict) else {}
    publication = {
        "pgp_id": pub.get("id"), "pmid": _str_or_none(pub.get("PMID")), "doi": _str_or_none(pub.get("doi")),
        "title": pub.get("title"), "journal": pub.get("journal"), "first_author": pub.get("firstauthor"),
        "date_publication": pub.get("date_publication"),
    }
    score_block = {
        "pgs_id": score.get("id"), "name": score.get("name"), "trait_reported": score.get("trait_reported"),
        "trait_efo": [{"id": t.get("id"), "label": t.get("label")} for t in _records(score.get("trait_efo"))],
        "variants_number": score.get("variants_number") if _is_int(score.get("variants_number")) else None,
        "weight_type": score.get("weight_type") if isinstance(score.get("weight_type"), str) else None,
        "method_name": score.get("method_name"), "genome_build": score.get("variants_genomebuild"),
        "variants_interactions": score.get("variants_interactions"),
        "date_release": score.get("date_release"), "license": score.get("license"),
        "ftp_scoring_file": score.get("ftp_scoring_file"),
        "harmonized_scoring_files": {b: (v or {}).get("positions") for b, v in
                                     (score.get("ftp_harmonized_scoring_files") or {}).items()
                                     if isinstance(v, dict)},
        "method_params": score.get("method_params"),
    }

    gwas_block, dev_block, eval_block = (_stage(ad, s) for s in STAGES)
    gwas_raw, dev_raw = _records(score.get("samples_variants")), _records(score.get("samples_training"))
    source_gwas = {
        "reported": gwas_block is not None, "distribution_pct": _dist(gwas_block),
        "n_individuals": gwas_block.get("count") if gwas_block and _is_int(gwas_block.get("count")) else None,
        "unit": "individuals", "multi": (gwas_block or {}).get("multi") or [], "samples": _samples(gwas_raw, vocab),
    }
    development = {
        "reported": dev_block is not None, "distribution_pct": _dist(dev_block),
        "n_individuals": dev_block.get("count") if dev_block and _is_int(dev_block.get("count")) else None,
        "unit": "individuals", "multi": (dev_block or {}).get("multi") or [], "samples": _samples(dev_raw, vocab),
    }

    # Evaluation: sample sets (descriptive) and (publication, sample set) units (Catalog semantics).
    sets: dict[str, dict] = {}
    units: dict[tuple[str, str], dict] = {}
    eval_pubs: dict[str, dict] = {}
    foreign = []
    for rec in performance:
        if rec.get("associated_pgs_id") != pgs_id:
            foreign.append(f"{rec.get('id')}->{rec.get('associated_pgs_id')}")
        ss = rec.get("sampleset") if isinstance(rec.get("sampleset"), dict) else {}
        pss = ss.get("id")
        if not isinstance(pss, str) or not pss:
            continue
        rec_pub = rec.get("publication") if isinstance(rec.get("publication"), dict) else {}
        pgp = rec_pub.get("id") if isinstance(rec_pub.get("id"), str) else None
        samples = _samples(ss.get("samples"), vocab)
        entry = sets.setdefault(pss, {"ppm_ids": set(), "pgp_ids": set(), "samples": samples})
        if rec.get("id"):
            entry["ppm_ids"].add(str(rec["id"]))
        if pgp:
            entry["pgp_ids"].add(pgp)
            eval_pubs.setdefault(pgp, {
                "pmid": _str_or_none(rec_pub.get("PMID")), "doi": _str_or_none(rec_pub.get("doi")),
                "first_author": rec_pub.get("firstauthor"), "journal": rec_pub.get("journal"),
                "date_publication": rec_pub.get("date_publication"), "title": rec_pub.get("title")})
        key = (pgp or "", pss)
        record_metrics = {"ppm_id": rec.get("id"), "phenotype": rec.get("phenotyping_reported"),
                          "covariates": rec.get("covariates"), "metrics": performance_metrics(rec)}
        if key in units:
            units[key]["performance"].append(record_metrics)
            continue
        codes = list(dict.fromkeys(s["code"] for s in samples)) or ["NR"]
        code = ("MAE" if "EUR" in codes else "MAO") if len(codes) > 1 else codes[0]
        n_total = sum(smp["n"] for smp in samples if smp["n"] is not None) if any(
            smp["n"] is not None for smp in samples) else None
        male = [smp["percent_male"] for smp in samples if smp["percent_male"] is not None]
        units[key] = {"pgp_id": pgp, "pss_id": pss, "code": code, "component_codes": codes,
                      "pooled": len(codes) > 1, "n": n_total,
                      "cases": sum(smp["cases"] or 0 for smp in samples) or None,
                      "percent_male": (sum(male) / len(male)) if male else None,
                      "countries": sorted({c.strip() for smp in samples for c in str(smp["countries"] or "").split(",")
                                           if c.strip() and smp["countries"]}),
                      "performance": [record_metrics]}
    sample_sets = [{"pss_id": pss, "ppm_ids": sorted(e["ppm_ids"]), "pgp_ids": sorted(e["pgp_ids"]),
                    "samples": e["samples"]} for pss, e in sorted(sets.items())]
    unit_list = [units[k] for k in sorted(units)]
    by_code_units: dict[str, int] = {}
    for u in unit_list:
        by_code_units[u["code"]] = by_code_units.get(u["code"], 0) + 1
    by_code_n: dict[str, int] = {}
    unrecognised = set()
    for s in sample_sets:
        for smp in s["samples"]:
            if not smp["code_recognised"]:
                unrecognised.add(str(smp["ancestry_broad"]))
            if smp["n"] is not None:
                by_code_n[smp["code"]] = by_code_n.get(smp["code"], 0) + smp["n"]
    eval_dist = _dist(eval_block)
    evaluation = {
        "reported": eval_block is not None, "distribution_pct": eval_dist,
        "sample_set_count": eval_block.get("count") if eval_block and _is_int(eval_block.get("count")) else None,
        "unit": "(publication, sample set) pairs",
        "multi": (eval_block or {}).get("multi") or [],
        "units": unit_list,
        "sample_sets": sample_sets,
        "sample_sets_by_code": dict(sorted(by_code_units.items())),
        "n_individuals_by_code": dict(sorted(by_code_n.items())),
        "codes": sorted(by_code_units),
        "publications": dict(sorted(eval_pubs.items())),
    }

    # Consistency checks (blocking unless marked advisory).
    sum_problems = []
    for stage, block in (("gwas", gwas_block), ("dev", dev_block), ("eval", eval_block)):
        dist = _dist(block)
        if not dist or not block or not _is_int(block.get("count")):
            continue
        bad = [f"{k}={v:g}" for k, v in dist.items() if not 0.0 <= v <= 100.0]
        total = sum(dist.values())
        if bad:
            sum_problems.append(f"{stage}: out-of-range {', '.join(bad)}")
        if abs(total - 100.0) > DIST_SUM_TOLERANCE:
            sum_problems.append(f"{stage}: percentages sum to {total:.1f}")
    check("DISTRIBUTION_SUMS", "fail" if sum_problems else "pass",
          "; ".join(sum_problems) or f"every reported distribution sums to 100 +/- {DIST_SUM_TOLERANCE}")

    unknown = sorted({k for b in (gwas_block, dev_block, eval_block) for k in _dist(b) if k not in known_codes})
    check("ANCESTRY_CODES_KNOWN", "fail" if unknown else "pass",
          f"codes not in /rest/ancestry_categories: {', '.join(unknown)}" if unknown
          else "all codes are in the Catalog vocabulary")

    check("PERFORMANCE_SCORE_LINK", "fail" if foreign else "pass",
          f"performance records for other scores: {', '.join(foreign)}" if foreign
          else f"{len(performance)} performance records, all for {pgs_id}")

    n_units = len(unit_list)
    if eval_block is None:
        ok = n_units == 0
        check("EVAL_SAMPLE_SET_COUNT", "pass" if ok else "fail",
              "no evaluation reported and no performance records" if ok
              else f"no eval distribution but {n_units} evaluation units exist")
    else:
        ok = evaluation["sample_set_count"] == n_units
        check("EVAL_SAMPLE_SET_COUNT", "pass" if ok else "fail",
              f"eval.count={evaluation['sample_set_count']}; (publication, sample set) units={n_units}; "
              f"distinct sample sets={len(sample_sets)}")

    declared_codes, derived_codes = set(eval_dist), set(by_code_units)
    ok = declared_codes == derived_codes
    check("EVAL_CODES_CROSSCHECK", "pass" if ok else "fail",
          f"score endpoint eval codes {sorted(declared_codes)} vs performance-derived unit codes "
          f"{sorted(derived_codes)}")

    if n_units:
        derived = {c: catalog_percent(n, n_units, len(by_code_units)) for c, n in by_code_units.items()}
        diffs = _dist_diffs(eval_dist, derived)
        check("EVAL_DISTRIBUTION_CROSSCHECK", "fail" if diffs else "pass",
              "; ".join(diffs) or "declared eval percentages match the (publication, sample set) units")
    else:
        check("EVAL_DISTRIBUTION_CROSSCHECK", "not_evaluable", "no evaluation units", blocking=False)

    if unrecognised:
        check("ANCESTRY_LABELS_RECOGNISED", "warn",
              f"labels outside the Catalog vocabulary (coded OTH as the Catalog does): "
              f"{', '.join(sorted(unrecognised))}", blocking=False)
    else:
        check("ANCESTRY_LABELS_RECOGNISED", "pass", "every evaluation label is in the vocabulary", blocking=False)

    if trait_query:
        ok = _trait_matches(trait_query, score)
        check("TRAIT_MATCH", "pass" if ok else "fail",
              f"requested trait {trait_query!r} vs catalog {score.get('trait_reported')!r} / EFO "
              f"{[t['label'] for t in score_block['trait_efo']]}")
    else:
        check("TRAIT_MATCH", "skipped", "no trait requested", blocking=False)

    header_pgp = (scoring_file_header or {}).get("pgp_id")
    if header_pgp:
        ok = header_pgp == publication["pgp_id"]
        check("SCORING_FILE_PUBLICATION_MATCH", "pass" if ok else "fail",
              f"scoring-file header pgp_id {header_pgp} vs catalog {publication['pgp_id']}")
    else:
        check("SCORING_FILE_PUBLICATION_MATCH", "skipped", "no scoring-file header pgp_id", blocking=False)

    has_ids = bool(publication["pmid"] or publication["doi"])
    check("PUBLICATION_IDENTIFIERS", "pass" if has_ids else "warn",
          f"PMID {publication['pmid']}, DOI {publication['doi']}", blocking=False)

    for stage, block, raw_samples in (("GWAS", gwas_block, gwas_raw), ("DEV", dev_block, dev_raw)):
        if block is None and not raw_samples:
            continue
        derived_pct, derived_n, _ = stage_distribution(raw_samples, vocab)
        diffs = _dist_diffs(_dist(block), derived_pct)
        if block is not None and block.get("count") != derived_n:
            diffs.append(f"count declared {block.get('count')} vs derived {derived_n}")
        check(f"{stage}_DISTRIBUTION_CROSSCHECK", "warn" if diffs else "pass",
              "; ".join(diffs) or f"{stage.lower()} distribution matches its samples", blocking=False)

    resolution_failed = [c for c in checks if c["kind"] == "resolution" and c["status"] == "fail"]
    blocking_failed = [c for c in checks if c["kind"] == "consistency" and c["blocking"] and c["status"] == "fail"]
    if resolution_failed:
        status = "unresolved"
        detail = "; ".join(f"{c['check_id']}: {c['detail']}" for c in resolution_failed)
    elif blocking_failed:
        status = "contradictory"
        detail = "; ".join(f"{c['check_id']}: {c['detail']}" for c in blocking_failed)
    else:
        status, detail = "resolved", "metadata resolved; all blocking consistency checks passed"

    return {
        "status": status,
        "detail": detail,
        "requested_pgs_id": pgs_id,
        "score": score_block,
        "publication": publication,
        "source_gwas_ancestry": source_gwas,
        "development_ancestry": development,
        "evaluation_ancestry": evaluation,
        "consistency_checks": checks,
        "failed_checks": [c["check_id"] for c in resolution_failed + blocking_failed],
    }


def unresolved_evidence(pgs_id: str, detail: str) -> dict:
    def empty_anc() -> dict:
        return {"reported": False, "distribution_pct": {}, "n_individuals": None, "unit": "individuals",
                "multi": [], "samples": []}

    return {
        "status": "unresolved", "detail": detail, "requested_pgs_id": pgs_id,
        "score": {"pgs_id": None, "name": None, "trait_reported": None, "trait_efo": [],
                  "variants_number": None, "weight_type": None, "method_name": None, "genome_build": None,
                  "variants_interactions": None, "date_release": None, "license": None,
                  "ftp_scoring_file": None},
        "publication": {"pgp_id": None, "pmid": None, "doi": None, "title": None, "journal": None,
                        "first_author": None, "date_publication": None},
        "source_gwas_ancestry": empty_anc(), "development_ancestry": empty_anc(),
        "evaluation_ancestry": {"reported": False, "distribution_pct": {}, "sample_set_count": None,
                                "unit": "(publication, sample set) pairs", "multi": [], "units": [],
                                "sample_sets": [], "sample_sets_by_code": {}, "n_individuals_by_code": {},
                                "codes": [], "publications": {}},
        "consistency_checks": [{"check_id": "FETCH", "status": "fail", "detail": detail,
                                "blocking": True, "kind": "resolution"}],
        "failed_checks": ["FETCH"],
    }


def run_cohort_audit(pgs_id: str, source: Any, *, trait_query: str | None = None,
                     scoring_file_header: dict | None = None) -> tuple[dict, list[RawResponse]]:
    """Fetch, parse and cross-check metadata. Never raises: problems become 'unresolved'."""
    raw: list[RawResponse] = []
    if not isinstance(pgs_id, str) or not PGS_ID_RE.match(pgs_id):
        evidence = unresolved_evidence(str(pgs_id), f"{pgs_id!r} is not a PGS Catalog score id (PGS + 6 digits)")
    else:
        try:
            records = fetch_catalog_records(pgs_id, source, raw)
            evidence = audit_score_metadata(pgs_id, records["score"], records["performance"],
                                            records["categories"], trait_query=trait_query,
                                            scoring_file_header=scoring_file_header)
        except MetadataUnavailable as exc:
            evidence = unresolved_evidence(pgs_id, str(exc))
        except Exception as exc:  # malformed catalog data must fail closed, never crash the gate
            evidence = unresolved_evidence(pgs_id, f"metadata could not be parsed ({_describe(exc)})")
    evidence["provenance"] = {
        "mode": getattr(source, "mode", "unknown"),
        "api_base": getattr(source, "api_base", API_BASE),
        "api_version": getattr(source, "api_version", None),
        "catalog_release": getattr(source, "catalog_release", None),
        "responses": [{"endpoint": r.endpoint, "url": r.url, "file": r.snapshot_path, "sha256": r.sha256,
                       "retrieved_at": r.retrieved_at} for r in raw],
    }
    return evidence, raw


# ---------------------------------------------------------------------------
# Snapshot writing (so any run's metadata can be replayed offline)
# ---------------------------------------------------------------------------


def write_snapshot(directory: str | Path, raw: list[RawResponse], *, api_base: str, catalog_release: str | None,
                   api_version: str | None, created_by: str,
                   extra_files: list[dict] | None = None) -> Path:
    """Write raw responses (and extra files) plus a SNAPSHOT.json manifest.

    ``extra_files`` items: {"rel": str, "content": bytes, "url": str|None, "retrieved_at": str|None,
    "kind": str, "note": str (optional)}. Relative paths may not leave ``directory``.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    items = [{"rel": r.snapshot_path, "content": r.content, "url": r.url, "retrieved_at": r.retrieved_at,
              "kind": "pgs_rest"} for r in raw]
    items += list(extra_files or [])
    for item in items:
        dest = contained_path(directory, item["rel"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not (dest.exists() and dest.read_bytes() == item["content"]):
            dest.write_bytes(item["content"])
        entry = {"url": item.get("url"), "sha256": hashlib.sha256(item["content"]).hexdigest(),
                 "retrieved_at": item.get("retrieved_at"), "kind": item.get("kind")}
        if item.get("note"):
            entry["note"] = item["note"]
        files[item["rel"]] = entry
    manifest = {"schema": SNAPSHOT_SCHEMA, "api_base": api_base, "api_version": api_version,
                "catalog_release": catalog_release, "created_by": created_by,
                "files": dict(sorted(files.items()))}
    path = directory / SNAPSHOT_MANIFEST
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Live runs that leave a replayable snapshot behind
# ---------------------------------------------------------------------------


class RecordingSource:
    """Live PGS Catalog source that records every response so the run can be replayed offline."""

    mode = "live"

    def __init__(self, directory: str | Path, live: Any = None):
        self.directory = Path(directory)
        self.live = live or LiveCatalogSource()
        self.recorded: dict[str, RawResponse] = {}

    api_base = property(lambda self: self.live.api_base)
    catalog_release = property(lambda self: self.live.catalog_release)
    api_version = property(lambda self: self.live.api_version)

    def fetch(self, endpoint: str, params: dict | None = None, **kw) -> RawResponse:
        if endpoint != "info" and self.live.catalog_release is None:
            try:
                self.recorded.setdefault("info.json", self.live.fetch("info"))
            except MetadataUnavailable:
                pass
        raw = self.live.fetch(endpoint, params, **kw)
        self.recorded[raw.snapshot_path] = raw
        return raw

    def save(self, extra_files: list[dict] | None = None) -> Path:
        keep = []
        manifest_path = self.directory / SNAPSHOT_MANIFEST
        if manifest_path.exists():
            for rel, e in (json.loads(manifest_path.read_text()).get("files") or {}).items():
                if rel not in self.recorded and (self.directory / rel).exists():
                    keep.append({"rel": rel, "content": (self.directory / rel).read_bytes(), "url": e.get("url"),
                                 "retrieved_at": e.get("retrieved_at"), "kind": e.get("kind"), "note": e.get("note")})
        return write_snapshot(self.directory, list(self.recorded.values()), api_base=self.api_base,
                              catalog_release=self.catalog_release, api_version=self.api_version,
                              created_by="prsguard", extra_files=keep + list(extra_files or []))


def open_source(mode: str, snapshot_dir: str | Path) -> Any:
    """'snapshot' replays ``snapshot_dir``; 'live' fetches and records into it."""
    if mode == "snapshot":
        return SnapshotCatalogSource(snapshot_dir)
    if mode == "live":
        return RecordingSource(snapshot_dir)
    raise ValueError(f"unknown catalog mode {mode!r}")


# ---------------------------------------------------------------------------
# Harmonised scoring files (large; downloaded once, then verified from the snapshot)
# ---------------------------------------------------------------------------


def scoring_file_relpath(pgs_id: str, build: str) -> str:
    if not PGS_ID_RE.match(pgs_id) or build not in ("GRCh37", "GRCh38"):
        raise ValueError(f"bad scoring file request {pgs_id!r} {build!r}")
    return f"{pgs_id}/{pgs_id}_hmPOS_{build}.txt.gz"


def scoring_file(pgs_id: str, build: str, source: Any, url: str | None = None) -> tuple[Path, dict]:
    """Local path of the PGS Catalog harmonised scoring file (checksum-verified) and its manifest entry.

    Snapshot mode: must already be in the snapshot. Live/recording mode: downloaded from ``url`` (the
    ``ftp_harmonized_scoring_files`` link in the score record) and added to the snapshot manifest.
    """
    rel = scoring_file_relpath(pgs_id, build)
    if isinstance(source, SnapshotCatalogSource):
        return source.verified_path(rel)
    directory = Path(source.directory)
    manifest_path = directory / SNAPSHOT_MANIFEST
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    entry = (manifest.get("files") or {}).get(rel)
    path = contained_path(directory, rel)
    if entry and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.get("sha256"):
        return path, entry
    if not url:
        raise MetadataUnavailable(f"no download URL for {rel}")
    import requests

    resp = requests.get(url, timeout=300, headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise MetadataUnavailable(f"GET {url} returned HTTP {resp.status_code}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    entry = {"url": url, "sha256": hashlib.sha256(resp.content).hexdigest(), "retrieved_at": _now(),
             "kind": "scoring_file"}
    manifest.setdefault("files", {})[rel] = entry
    manifest["files"] = dict(sorted(manifest["files"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path, entry
