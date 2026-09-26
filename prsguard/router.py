"""Trait-first PGS candidate router: resolve -> search -> eligibility -> pre-rank -> FREEZE.

Everything here uses PGS Catalog metadata only. No genotype, score or percentile of the person is read, so the
candidate set and its order are fixed before personal scoring starts. The frozen set is written with a SHA-256
digest; the pipeline refuses to score against a candidate file whose digest does not verify.

Agent vs deterministic boundary: resolving free text to an ontology term and choosing the trait scope are
recorded planning decisions (the default rule below, or an explicit override); eligibility and ranking are
fixed rules applied by code.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prsguard import catalog

ROUTER_VERSION = "1.0.0"
SEX_QUALIFIERS = {"female": "female", "females": "female", "women": "female", "woman": "female",
                  "male": "male", "males": "male", "men": "male", "man": "male"}
NON_SPECIFIC_CODES = {"NR", "MAE", "MAO", "OTH"}

ELIGIBILITY_RULES = [
    "E1 trait: mapped (PGS Catalog trait_efo) to the resolved term or an in-scope child term.",
    "E2 phenotype: trait_reported names the whole outcome (the term's label, a Catalog synonym of an in-scope term, "
    "or the query); parenthetical qualifiers are allowed only when they are a sex qualifier, a synonym or "
    "abbreviation of the term, or a phenotype code (PheCode/ICD); subtype, age-of-onset or carrier-status scores "
    "answer a different question.",
    "E3 sex: sex-specific scores are excluded when the person's sex is given and differs.",
    "E4 score model: additive with log-scale weights and no interaction terms (what the scorer computes).",
    "E5 file: a PGS Catalog harmonised scoring file exists for the requested genome build (any build if unknown).",
    "E6 evaluated: at least one evaluation (publication, sample set) unit in the Catalog.",
    "E7 metadata: the Catalog record resolves and passes the consistency audit.",
    "E8 engineering: variants_number <= max_variants when set (the prsguard CLI sets 10,000 by default, the size "
    "the shipped 1000 Genomes reference panel supports; --max-variants 0 disables it). A runtime constraint, not a "
    "scientific criterion.",
]
RANKING_RULES = [
    "R1 more distinct ancestry groups (single-ancestry evaluation units; NR/MAE/MAO/OTH not counted) with at "
    "least one reported performance metric - breadth of validation first;",
    "R2 more evaluation units with a reported performance metric;",
    "R3 larger total evaluation sample size (sum over units);",
    "R4 earlier Catalog release (longer track record); R5 PGS id. The person's genotype is never an input.",
]


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _base_and_qualifiers(label: str) -> tuple[str, list[str]]:
    """'Type 2 diabetes (T2D) (PheCode 250.2)' -> ('type 2 diabetes', ['t2d', 'phecode 250.2'])."""
    quals: list[str] = []
    while True:
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", label)
        if not m:
            return _norm(label), quals
        label = m.group(1)
        quals.insert(0, _norm(m.group(2)))


PHENOTYPE_CODE_RE = re.compile(r"^(?:phecode|icd-?10(?:-cm)?|icd-?9(?:-cm)?|icd|read|snomed(?: ct)?)\s*[:#]?\s*"
                               r"[a-z]?\d[\w.]*(?:\s*[,/;-]\s*[a-z]?\d[\w.]*)*$")


def _equivalents(label: str) -> set[str]:
    base = _norm(label)
    out = {base}
    for a, b in (("cancer", "carcinoma"), ("carcinoma", "cancer")):
        if a in base.split():
            out.add(" ".join(b if w == a else w for w in base.split()))
    return out


# ---------------------------------------------------------------------------
# Trait resolution and scope
# ---------------------------------------------------------------------------


def resolve_trait(query: str, source: Any, raw: list, scope_override: list[str] | None = None) -> dict:
    q = _norm(query)
    resp = source.fetch("trait/search", {"term": query, "limit": 50}, trait_id=query)
    raw.append(resp)
    results = [r for r in (resp.json() or {}).get("results", []) if isinstance(r, dict)]
    # Tiered: an exact label match wins; synonyms are consulted only when no label matches (many terms list a
    # broader outcome as a synonym, e.g. "breast carcinoma" lists "breast cancer").
    exact = [r for r in results if _norm(r.get("label")) == q]
    matched_on = "exact label match"
    if not exact:
        exact = [r for r in results if q in {_norm(s) for s in r.get("trait_synonyms") or []}]
        matched_on = "exact synonym match"
    base = {"query": query, "router_version": ROUTER_VERSION,
            "search_hits": [{"id": r.get("id"), "label": r.get("label")} for r in results[:15]]}
    if len(exact) != 1:
        return {**base, "status": "ambiguous" if exact else "unresolved",
                "detail": ("several terms match exactly" if exact else "no ontology term has this exact label or "
                           "synonym; choose one of search_hits (an agent may ask the user)"),
                "term": None, "scope": []}
    term = exact[0]
    detail = source.fetch(f"trait/{term['id']}", {"include_children": 1})
    raw.append(detail)
    children = [c for c in (detail.json() or {}).get("child_traits", []) if isinstance(c, dict)]
    scope = [{"id": term["id"], "label": term["label"], "sex": None, "reason": "resolved term",
              "synonyms": sorted({str(x) for x in term.get("trait_synonyms") or []})}]
    excluded = []
    accepted = _equivalents(term["label"])
    for c in children:
        label = _norm(c.get("label"))
        sex = None
        words = label.split()
        if words and words[0] in SEX_QUALIFIERS:
            sex, label = SEX_QUALIFIERS[words[0]], " ".join(words[1:])
        if scope_override is not None:
            keep = c.get("id") in scope_override
            why = "explicit scope override"
        else:
            keep = label in accepted
            why = ("same outcome (label equivalent to the resolved term)" if keep else
                   "narrower sub-phenotype (molecular subtype or other qualifier)")
        entry = {"id": c.get("id"), "label": c.get("label"), "sex": sex, "reason": why}
        if keep:
            entry["synonyms"] = sorted({str(x) for x in c.get("trait_synonyms") or []})
        (scope if keep else excluded).append(entry)
    return {**base, "status": "resolved", "detail": matched_on, "term": {"id": term["id"],
            "label": term["label"]}, "scope": scope, "excluded_children": excluded,
            "scope_rule": ("resolved term plus child terms whose label (after an optional sex prefix) equals the "
                           "resolved label or its cancer/carcinoma equivalent")}


# ---------------------------------------------------------------------------
# Eligibility and ranking
# ---------------------------------------------------------------------------


@dataclass
class RouterOptions:
    sex: str | None = None                 # "female" / "male" / None
    build: str | None = None               # "GRCh37" / "GRCh38" / None (unknown)
    max_variants: int | None = None        # engineering constraint, off by default
    top_k: int = 3
    extra: dict = field(default_factory=dict)


def eligibility(rec: dict, trait: dict, opts: RouterOptions) -> tuple[list[str], dict]:
    """Reasons a Catalog score record is NOT eligible (empty list = eligible) and derived facts."""
    reasons = []
    scope = {s["id"]: s for s in trait["scope"]}
    mapped = [t for t in rec.get("trait_efo") or [] if isinstance(t, dict) and t.get("id") in scope]
    facts: dict[str, Any] = {"mapped_terms": [t.get("id") for t in mapped], "sex_specific": None}
    if not mapped:
        reasons.append("E1: not mapped to an in-scope term")
    base, quals = _base_and_qualifiers(str(rec.get("trait_reported") or ""))
    accepted = set().union(*(_equivalents(s["label"]) for s in trait["scope"]))
    accepted |= set().union(*(_equivalents(" ".join(_norm(s["label"]).split()[1:])) for s in trait["scope"]
                              if s["sex"]))
    synonyms = {_norm(x) for s in trait["scope"] for x in s.get("synonyms") or []}
    accepted |= set().union(set(), *(_equivalents(x) for x in synonyms | {_norm(trait.get("query"))}))
    for qual in quals:
        if qual in SEX_QUALIFIERS:
            facts["sex_specific"] = SEX_QUALIFIERS[qual]
        elif qual in synonyms or qual in accepted or PHENOTYPE_CODE_RE.match(qual):
            facts.setdefault("neutral_qualifiers", []).append(qual)  # abbreviation or phenotype code
        else:
            reasons.append(f"E2: trait_reported qualifier '({qual})' marks a sub-phenotype")
    if base not in accepted:
        reasons.append(f"E2: trait_reported {rec.get('trait_reported')!r} is not the resolved outcome")
    for t in mapped:
        if scope[t["id"]]["sex"]:
            facts["sex_specific"] = scope[t["id"]]["sex"]
    if facts["sex_specific"] and opts.sex and facts["sex_specific"] != opts.sex:
        reasons.append(f"E3: {facts['sex_specific']}-specific score, person is {opts.sex}")
    from prsguard.evidence import ratio_weight_type  # shared with the gate's score-model rule
    if ratio_weight_type(rec.get("weight_type")):
        reasons.append(f"E4: weight_type {rec.get('weight_type')!r} is a ratio scale, not log-additive")
    inter = rec.get("variants_interactions")
    if isinstance(inter, int) and inter > 0:
        reasons.append(f"E4: {inter} interaction terms")
    files = {b: (v or {}).get("positions") for b, v in (rec.get("ftp_harmonized_scoring_files") or {}).items()
             if isinstance(v, dict)}
    facts["harmonized_builds"] = sorted(b for b, u in files.items() if u)
    if opts.build and not files.get(opts.build):
        reasons.append(f"E5: no harmonised scoring file for {opts.build}")
    elif not facts["harmonized_builds"]:
        reasons.append("E5: no harmonised scoring file")
    ev = ((rec.get("ancestry_distribution") or {}).get("eval") or {})
    if not (isinstance(ev.get("count"), int) and ev["count"] > 0):
        reasons.append("E6: no evaluation in the Catalog")
    vn = rec.get("variants_number")
    if opts.max_variants and isinstance(vn, int) and vn > opts.max_variants:
        reasons.append(f"E8 (engineering): {vn} variants > {opts.max_variants}")
    return reasons, facts


def ranking_evidence(evidence: dict) -> dict:
    units = evidence["evaluation_ancestry"]["units"]
    with_metrics = [u for u in units if any(p["metrics"] for p in u.get("performance") or [])]
    groups = sorted({u["code"] for u in with_metrics if u["code"] not in NON_SPECIFIC_CODES})
    n_total = sum(u["n"] for u in units if isinstance(u.get("n"), int))
    return {"ancestry_groups_with_metrics": groups, "units_with_metrics": len(with_metrics),
            "units": len(units), "total_evaluation_n": n_total}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def route(query: str, source: Any, opts: RouterOptions, scope_override: list[str] | None = None,
          log=lambda *_: None) -> tuple[dict, list]:
    """Resolve, search, filter and rank; returns (candidate_set, raw_responses). Does not touch genotypes."""
    raw: list = []
    trait = resolve_trait(query, source, raw, scope_override)
    if trait["status"] != "resolved":
        return {"trait": trait, "status": "TRAIT_UNRESOLVED", "selected": []}, raw
    records: dict[str, dict] = {}
    for term in trait["scope"]:
        for rec in catalog.fetch_trait_search(term["id"], source, raw):
            records.setdefault(rec["id"], rec)
    log(f"router: {len(records)} scores mapped to {len(trait['scope'])} in-scope terms")
    eligible, excluded = [], []
    for pid in sorted(records):
        reasons, facts = eligibility(records[pid], trait, opts)
        if reasons:
            excluded.append({"pgs_id": pid, "reasons": reasons})
            continue
        evidence, ev_raw = catalog.run_cohort_audit(pid, source)
        raw.extend(ev_raw)
        if evidence["status"] != "resolved":
            excluded.append({"pgs_id": pid, "reasons": [f"E7: metadata {evidence['status']}: {evidence['detail']}"]})
            continue
        rev = ranking_evidence(evidence)
        rec = records[pid]
        pub = rec.get("publication") or {}
        eligible.append({
            "pgs_id": pid, "name": rec.get("name"), "trait_reported": rec.get("trait_reported"),
            "variants_number": rec.get("variants_number"), "weight_type": rec.get("weight_type"),
            "date_release": rec.get("date_release"), "publication": {"pgp_id": pub.get("id"),
                                                                      "pmid": str(pub.get("PMID") or "") or None,
                                                                      "doi": pub.get("doi")},
            **facts, "ranking_evidence": rev,
            "sort_key": [-len(rev["ancestry_groups_with_metrics"]), -rev["units_with_metrics"],
                         -rev["total_evaluation_n"], str(rec.get("date_release") or "9999"), pid],
        })
    eligible.sort(key=lambda e: e["sort_key"])
    for i, e in enumerate(eligible, 1):
        e["pre_rank"] = i
    selected = [e["pgs_id"] for e in eligible[:opts.top_k]]
    body = {
        "schema": "prsguard.candidate_set.v1", "router_version": ROUTER_VERSION, "status": "FROZEN",
        "trait": trait, "options": {"sex": opts.sex, "build": opts.build, "max_variants": opts.max_variants,
                                    "top_k": opts.top_k},
        "eligibility_rules": ELIGIBILITY_RULES, "ranking_rules": RANKING_RULES,
        "n_found": len(records), "n_eligible": len(eligible), "eligible": eligible,
        "excluded": excluded, "selected": selected,
        "catalog": {"mode": getattr(source, "mode", None), "release": getattr(source, "catalog_release", None),
                    "api_version": getattr(source, "api_version", None)},
    }
    return freeze(body), raw


def freeze(body: dict) -> dict:
    body = dict(body)
    body.pop("digest", None)
    body["frozen_at"] = body.get("frozen_at") or datetime.now(UTC).replace(microsecond=0).isoformat()
    body["digest"] = "sha256:" + hashlib.sha256(_canonical({k: v for k, v in body.items()
                                                            if k not in ("digest",)}).encode()).hexdigest()
    return body


def verify_frozen(body: dict) -> bool:
    expect = "sha256:" + hashlib.sha256(_canonical({k: v for k, v in body.items() if k != "digest"}).encode()
                                        ).hexdigest()
    return body.get("digest") == expect and body.get("status") == "FROZEN"


def write_frozen(body: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path
