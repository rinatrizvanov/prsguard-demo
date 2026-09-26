"""Literature-equity context from the equity-lit-auditor skill, trimmed for PRSGuard results.

CONTEXT ONLY: the literature equity score (0-100 per paper) describes how the papers behind a score report and
sample populations. It is never an input to the applicability gate.

    python -m prsguard.literature <equity-lit result.json> <out.json> --pgs-ids PGS000004,PGS001804,PGS001336
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _clean(text):
    import html
    import re

    return re.sub(r"<[^>]+>", "", html.unescape(text)).strip() if isinstance(text, str) else text


def trim(result: dict, pgs_ids: list[str]) -> dict:
    data = result.get("data") or {}
    prov = dict(data.get("provenance") or {})
    prov.pop("cache_dir", None)  # local path, not provenance
    papers = []
    for p in data.get("papers") or []:
        a = p.get("audit") or {}
        papers.append({
            "id": p.get("id"), "pmid": p.get("pmid"), "doi": p.get("doi"), "title": _clean(p.get("title")),
            "year": p.get("year"), "journal": _clean(p.get("journal")),
            "first_author": (p.get("authors") or "").split(",")[0].strip() or None,
            "linked_scores": a.get("pgs") or p.get("pgs") or [], "source": a.get("source"),
            "equity_score": a.get("score"), "components": {k: {"points": v.get("points"), "max": v.get("max")}
                                                           for k, v in (a.get("components") or {}).items()},
            "flags": a.get("flags") or [], "ancestry_n": a.get("ancestry_n") or {},
            "country_n": a.get("country_n") or {}, "total_n": a.get("total_n")})
    papers.sort(key=lambda x: (str(x.get("year") or ""), str(x.get("id"))), reverse=True)
    summary = dict(result.get("summary") or {})
    return {
        "source_skill": "equity-lit-auditor", "skill_version": result.get("version"),
        "synthetic": bool(result.get("synthetic")), "data_provenance": result.get("data_provenance"),
        "role": "context_only", "feeds_applicability_decision": False,
        "query": {"pgs_ids": pgs_ids},
        "semantics": data.get("equity_score_semantics"),
        "provenance": prov, "completed_at": result.get("completed_at"),
        "summary": {k: summary.get(k) for k in ("papers_total", "papers_with_population_data",
                                                "papers_european_only", "median_equity_score",
                                                "mean_equity_score", "countries", "participants_extracted",
                                                "ancestry_share_basis", "flags", "extraction_check",
                                                "retrieval_warnings")},
        "ancestry_share": data.get("ancestry_share"),
        "stage_ancestry": (data.get("pgs") or {}).get("stage_ancestry"),
        "countries": [{k: c.get(k) for k in ("iso3", "name", "participants", "papers")}
                      for c in data.get("countries") or []],
        "rubric": _rubric(data),
        "papers": papers,
    }


def _rubric(data: dict) -> list[dict]:
    """Component names with their maximum points (taken from the per-paper audits)."""
    maxima: dict[str, int] = {}
    for p in data.get("papers") or []:
        for k, v in ((p.get("audit") or {}).get("components") or {}).items():
            maxima.setdefault(k, v.get("max"))
    names = [r if isinstance(r, str) else r.get("key") for r in data.get("rubric_components") or []]
    return [{"key": k, "max": maxima.get(k)} for k in names or list(maxima)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("out")
    ap.add_argument("--pgs-ids", required=True)
    a = ap.parse_args(argv)
    doc = trim(json.loads(Path(a.result).read_text()), a.pgs_ids.split(","))
    if doc["synthetic"]:
        sys.exit("refusing to attach SYNTHETIC equity-lit output as literature context for a real result")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {a.out}: {len(doc['papers'])} papers, provenance {doc['data_provenance']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
