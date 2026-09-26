#!/usr/bin/env python3
"""Equity Lit Auditor: audit genomics literature for population diversity and equity.

Search Europe PMC (PubMed + PMC), optionally cascade through references and/or
citations, extract which populations the data came from, score each paper on
a transparent equity rubric, and draw a geographic heat map of where the
participants were recruited.

Usage:
    python skills/equity-lit-auditor/equity_lit_auditor.py --query "type 2 diabetes GWAS" --output out/
    python skills/equity-lit-auditor/equity_lit_auditor.py --pmids <PMID1>,<PMCID> --cascade both --output out/
    python skills/equity-lit-auditor/equity_lit_auditor.py --pgs-trait "breast cancer" --output out/
    python skills/equity-lit-auditor/equity_lit_auditor.py --demo --output /tmp/equity_lit_demo
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import requests

SKILL_DIR = Path(__file__).resolve().parent


def find_clawbio_root() -> Path | None:
    """Locate the ClawBio checkout that provides ``clawbio.common``.

    The skill lives in several layouts: physically inside ``ClawBio/skills/``,
    symlinked there from PRSGuard (``Path.resolve()`` then points back into
    PRSGuard), or run straight from the PRSGuard repo, whose pinned checkout is
    ``vendor/ClawBio``. ``CLAWBIO_DIR`` overrides all of them.
    """
    unresolved = Path(os.path.abspath(__file__)).parent   # keeps a symlinked location
    candidates = [os.environ.get("CLAWBIO_DIR"), unresolved.parent.parent, SKILL_DIR.parent.parent,
                  SKILL_DIR.parent.parent / "vendor" / "ClawBio"]
    for c in candidates:
        if c and (Path(c) / "clawbio" / "common" / "reproducibility.py").is_file():
            return Path(c).resolve()
    return None


CLAWBIO_ROOT = find_clawbio_root()
for p in (str(SKILL_DIR), str(CLAWBIO_ROOT) if CLAWBIO_ROOT else None):
    if p and p not in sys.path:
        sys.path.insert(0, p)

from equity_lit_extract import audit_paper  # noqa: E402
from equity_lit_geo import ANCESTRY_GROUPS, REGION_POPULATION_2022, load_countries  # noqa: E402
from equity_lit_literature import (  # noqa: E402
    EPMC_BASE, EuropePMCClient, FixtureClient, collect_papers, paper_from_publication, parse_seed,
)
from equity_lit_pgs import (  # noqa: E402
    PGS_API, STAGES, PGSCatalogClient, PGSFixtureClient, PGSResult, curated_records, gather, stage_ancestry,
)
from equity_lit_render import (  # noqa: E402
    SYNTHETIC_LABEL, heatmap_html, heatmap_png, pgs_stage_png, representation_png,
)

try:
    from clawbio.common.report import DISCLAIMER, write_result_json
    from clawbio.common.reproducibility import write_checksums, write_commands_sh, write_environment_yml
except ImportError:  # standalone use outside the ClawBio checkout
    DISCLAIMER = ("ClawBio is a research and educational tool. It is not a medical device and does not "
                  "provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.")
    write_result_json = write_checksums = write_commands_sh = write_environment_yml = None
    print("warning: ClawBio checkout not found (set CLAWBIO_DIR or run scripts/setup.sh); "
          "result.json is written without the ClawBio envelope and no reproducibility/ bundle is produced.",
          file=sys.stderr)

SKILL_NAME = "equity-lit-auditor"
SKILL_VERSION = "0.2.0"
DEMO_FIXTURE = SKILL_DIR / "examples" / "demo_epmc_fixture.json"
DEMO_QUERY = "type 2 diabetes genome-wide association (synthetic demo)"
DEMO_PGS_TRAIT = "type 2 diabetes"

# The per-paper 0-100 equity score describes how the literature reports and samples
# populations. It is context for a human reader. It says nothing about whether a
# polygenic score is valid or transferable for a given person, so it must never be an
# input to an applicability decision (PRSGuard keeps it out of its gate by contract).
EQUITY_SCORE_SEMANTICS = {
    "role": "context_only",
    "feeds_applicability_decision": False,
    "scale": "0-100 per-paper rubric of population reporting and sampling in the literature",
    "note": ("Context only. The literature equity score describes how the audited papers report and sample "
             "populations; it is not a measure of any polygenic score's validity, accuracy or transferability "
             "to a person and must never be used as an input to a PRS applicability decision."),
}


def provenance_block(demo: bool, pgs_used: bool, cache: Path | None) -> dict:
    """Machine-readable provenance, repeated in result.json, every table and every figure."""
    if demo:
        return {"synthetic": True, "data_provenance": SYNTHETIC_LABEL,
                "sources": {"literature": f"SYNTHETIC DEMO fixture ({DEMO_FIXTURE.relative_to(SKILL_DIR)})",
                            "pgs_catalog": f"SYNTHETIC DEMO fixture ({DEMO_FIXTURE.relative_to(SKILL_DIR)})"},
                "retrieved_at": None, "cache_dir": None,
                "note": "Every paper, cohort and number is synthetic. Not real literature; do not cite or reuse."}
    sources = {"literature": f"Europe PMC REST API ({EPMC_BASE})"}
    if pgs_used:
        sources["pgs_catalog"] = f"PGS Catalog REST API ({PGS_API})"
    return {"synthetic": False, "data_provenance": "LIVE", "sources": sources,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cache_dir": str(cache) if cache else None,
            "note": ("Live public APIs." + (" Responses already in --cache-dir were replayed, not re-fetched."
                                            if cache else ""))}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_argument_group("what to audit")
    src.add_argument("--query", help="Europe PMC query, e.g. 'type 2 diabetes GWAS'")
    src.add_argument("--pmids", help="Comma-separated seed IDs (PMID, PMCID, DOI:...)")
    src.add_argument("--input", help="Text file with one seed ID per line (alternative to --pmids)")
    src.add_argument("--demo", action="store_true", help="Run on bundled synthetic data (no network)")
    src.add_argument("--max-results", type=int, default=25, help="Papers taken from the search (default 25)")
    pgs = ap.add_argument_group("PGS Catalog (curated score publications and sample ancestry)")
    pgs.add_argument("--pgs-trait", help="Add every PGS Catalog score for this trait, e.g. 'type 2 diabetes'")
    pgs.add_argument("--pgs-ids", help="Comma-separated PGS Catalog score IDs, e.g. PGS000013,PGS000014")
    pgs.add_argument("--pgs-max-scores", type=int, default=50, help="Max PGS Catalog scores (default 50)")
    pgs.add_argument("--no-pgs-eval", action="store_true",
                     help="Skip evaluation publications (one extra API call per score)")
    cas = ap.add_argument_group("citation cascade")
    cas.add_argument("--cascade", choices=["none", "references", "citations", "both"], default="none",
                     help="Follow reference lists, citing papers, or both (default none)")
    cas.add_argument("--depth", type=int, default=1, help="Cascade levels (default 1)")
    cas.add_argument("--per-paper", type=int, default=10, help="Max references/citations followed per paper")
    cas.add_argument("--max-papers", type=int, default=80, help="Hard cap on total papers")
    ext = ap.add_argument_group("extraction and output")
    ext.add_argument("--no-fulltext", action="store_true", help="Abstracts only; skip open-access methods sections")
    ext.add_argument("--include-non-genomic", action="store_true",
                     help="Keep papers without human genomic data (tools, reviews) in the map and stats")
    ext.add_argument("--metric", choices=["auto", "participants", "papers"], default="auto",
                     help="Heat-map value: extracted participants, number of papers, or auto")
    ext.add_argument("--cache-dir", help="Cache API responses here (re-runs are then offline)")
    ext.add_argument("--output", required=False, help="Output directory")
    args = ap.parse_args(argv)
    if args.demo:
        args.cascade = "both" if args.cascade == "none" else args.cascade
        args.pgs_trait = args.pgs_trait or DEMO_PGS_TRAIT
    elif not (args.query or args.pmids or args.input or args.pgs_trait or args.pgs_ids):
        ap.error("give --query, --pmids, --input, --pgs-trait, --pgs-ids or --demo")
    if not args.output:
        args.output = f"equity_lit_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return args


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(papers, audits, include_non_genomic: bool, metric: str):
    countries = load_countries()
    in_scope = [(p, a) for p, a in zip(papers, audits) if include_non_genomic or p.is_genomic_study]
    with_pop = [(p, a) for p, a in in_scope if a.ancestry_n or a.country_n]

    per_country = defaultdict(lambda: {"participants": 0, "papers": 0, "titles": []})
    pairs = with_n = 0
    for p, a in with_pop:
        for iso3, n in a.country_n.items():
            if iso3 not in countries:
                continue
            c = per_country[iso3]
            c["participants"] += n or 0
            c["papers"] += 1
            c["titles"].append(p.title)
            pairs += 1
            with_n += bool(n)
    if metric == "auto":
        metric = "participants" if pairs and with_n / pairs >= 0.5 else "papers"
    country_rows = []
    for iso3, c in per_country.items():
        row = countries[iso3]
        country_rows.append({
            "iso3": iso3, "name": row["name"], "un_region": row["un_region"],
            "high_income": row["high_income"], "participants": c["participants"], "papers": c["papers"],
            "titles": c["titles"], "value": c["participants"] if metric == "participants" else c["papers"],
        })
    country_rows.sort(key=lambda r: (-r["value"], r["name"]))

    anc_n = Counter()
    anc_papers = Counter()
    for _, a in with_pop:
        for g, n in a.ancestry_n.items():
            anc_n[g] += n or 0
            anc_papers[g] += 1
    total_n = sum(anc_n.values())
    if total_n:
        share = {g: anc_n[g] / total_n for g in anc_n}
        basis = "extracted sample sizes"
    else:
        tot = sum(anc_papers.values()) or 1
        share = {g: anc_papers[g] / tot for g in anc_papers}
        basis = "paper mentions (no sample sizes found)"

    region_participants = Counter()
    for r in country_rows:
        region_participants[r["un_region"]] += r["participants"]

    # Papers with no participant description at all (tools, reviews, or simply
    # unreported) are listed but kept out of the score summary.
    scores = [a.score for _, a in with_pop]
    eur_only = sum(1 for _, a in with_pop if set(a.ancestry_n) == {"EUR"})
    stats = {
        "papers_total": len(papers),
        "papers_in_scope": len(in_scope),
        "papers_with_population_data": len(with_pop),
        "papers_european_only": eur_only,
        "median_equity_score": statistics.median(scores) if scores else None,
        "mean_equity_score": round(statistics.mean(scores), 1) if scores else None,
        "countries": len(country_rows),
        "participants_extracted": total_n,
        "heatmap_metric": metric,
        "ancestry_share_basis": basis,
        "flags": Counter(f.split(":")[0] for _, a in in_scope for f in a.flags),
    }
    return in_scope, with_pop, country_rows, share, anc_n, anc_papers, region_participants, stats


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _pct(x: float) -> str:
    return f"{x:.1%}" if 0 < x < 0.01 else f"{x:.0%}"


def _heading(text: str, demo: bool) -> str:
    """Section heading; in demo mode every heading carries the synthetic label, so an
    excerpt copied out of the report still says where it came from."""
    return f"{text} ({SYNTHETIC_LABEL})" if demo else text


def pgs_section(ps: dict, demo: bool = False, traits: list | None = None) -> list[str]:
    from equity_lit_geo import ANCESTRY_GROUPS as AG
    L = [_heading("## PGS Catalog: who the scores were built and tested on", demo), "",
         "Curated sample metadata from the [PGS Catalog](https://www.pgscatalog.org/browse/scores/) for every linked "
         "score, by stage. A GWAS reused by several scores is counted once.", ""]
    for t in traits or []:
        avail = t.get("scores_available")
        L.append(f"- Trait **{t.get('label')}** (`{t.get('id')}`), matched by {t.get('match', 'n/a')}; "
                 f"{avail if avail is not None else 'unknown number of'} score(s) available in the Catalog "
                 "(including child traits).")
    L += [f"- **{len(ps['scores'])}** score(s) audited (`--pgs-max-scores` caps this; the Catalog returns scores in "
          "PGS ID order, so a cap keeps the oldest scores).", "",
          "![PGS stage ancestry](figures/pgs_stage_ancestry.png)", "",
         "| Stage | Participants | " + " | ".join(AG) + " |", "|---|---:|" + "---:|" * len(AG)]
    for st, counts in ps["stages"].items():
        tot = sum(counts.values())
        if not tot:
            continue
        cells = [f"{counts.get(g, 0) / tot:.0%}" if counts.get(g) else "" for g in AG]
        L.append(f"| {st} | {tot:,} | " + " | ".join(cells) + " |")
    L += ["", "| PGS ID | Name | Trait | Variants | GWAS ancestry | Evaluation ancestry |", "|---|---|---|---:|---|---|"]
    for r in ps["scores"]:
        pid = r["pgs_id"]
        link = pid if "DEMO" in pid else f"[{pid}](https://www.pgscatalog.org/score/{pid}/)"
        L.append(f"| {link} | {r['name']} | {r['trait']} | {r['variants']} | {r['gwas_ancestry'] or 'NR'} | "
                 f"{r['evaluation_ancestry'] or '—'} |")
    chk = ps["check"]["summary"]
    L += ["", _heading("### Extraction check against PGS Catalog curation", demo), ""]
    if chk["papers"]:
        L.append(f"The text extractor recovered **{chk['recovered']} of {chk['curated_groups']}** curated ancestry groups "
                 f"(recall {chk['recall']:.0%}) across {chk['papers']} papers with curated samples. Misses usually mean the "
                 "population is only in tables or supplements; for these papers the curated values are used.")
        L += ["", "| Paper | Curated | Text extraction | Missed | Extra |", "|---|---|---|---|---|"]
        for r in ps["check"]["rows"]:
            L.append(f"| {r['title'][:70]} | {', '.join(r['curated'])} | {', '.join(r['text']) or '—'} | "
                     f"{', '.join(r['missed']) or ''} | {', '.join(r['extra']) or ''} |")
    else:
        L.append("No linked paper had curated ancestry groups to compare against.")
    L.append("")
    return L


def build_report(label, args, papers, audits, agg, demo: bool, pgs_summary: dict | None = None,
                 provenance: dict | None = None, retrieval_warnings: list[str] | None = None,
                 pgs_traits: list | None = None) -> str:
    in_scope, with_pop, country_rows, share, anc_n, anc_papers, region_participants, stats = agg
    audit_by_key = {a.key: a for a in audits}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    provenance = provenance or {}
    if demo:
        source = "bundled SYNTHETIC fixture (demo mode, no real papers)"
    else:
        source = "; ".join(provenance.get("sources", {}).values()) or "Europe PMC (PubMed + PMC open-access full text)"
    L = [_heading("# Genomic Equity Literature Audit", demo), "",
         f"**Data provenance**: {provenance.get('data_provenance', SYNTHETIC_LABEL if demo else 'LIVE')}  ",
         f"**Query / seeds**: {label}  ",
         f"**Date**: {now}  ",
         f"**Source**: {source}  ",
         f"**Cascade**: {args.cascade}" + (f", depth {args.depth}, ≤{args.per_paper} per paper" if args.cascade != 'none' else ""), ""]
    if demo:
        L += [f"> **Demo mode ({SYNTHETIC_LABEL}).** Every paper below is synthetic and exists only to exercise the "
              "pipeline. It is not real literature: do not cite it, map it or reuse its numbers.", ""]
    if provenance.get("cache_dir"):
        L += [f"> Responses already cached in `{provenance['cache_dir']}` were replayed rather than re-fetched.", ""]
    if retrieval_warnings:
        L += [_heading("## Data availability", demo), "",
              f"**{len(retrieval_warnings)}** lookup(s) failed during retrieval, so the results below are incomplete "
              "(nothing was substituted for the missing data):", ""]
        L += [f"- {w}" for w in retrieval_warnings[:20]]
        if len(retrieval_warnings) > 20:
            L.append(f"- … {len(retrieval_warnings) - 20} more in `result.json` (`summary.retrieval_warnings`)")
        L.append("")

    L += [_heading("## Summary", demo), "",
          f"- **{stats['papers_total']}** papers retrieved; **{stats['papers_in_scope']}** describe human genomic data; "
          f"**{stats['papers_with_population_data']}** state where or whom the data came from.",
          f"- **{stats['papers_european_only']}** of {stats['papers_with_population_data']} "
          f"({_pct(stats['papers_european_only'] / max(1, stats['papers_with_population_data']))}) "
          f"report European-ancestry participants only.",
          f"- Median equity score **{stats['median_equity_score']}** / 100 (mean {stats['mean_equity_score']}) "
          f"across papers that describe their participants (context only; see below).",
          f"- **{stats['participants_extracted']:,}** participants with an extractable sample size, "
          f"from **{stats['countries']}** countries."]
    eur = share.get("EUR")
    if eur is not None:
        L.append(f"- European ancestry accounts for **{_pct(eur)}** of participants ({stats['ancestry_share_basis']}).")
    if stats.get("pgs_scores"):
        L.append(f"- **{stats['pgs_scores']}** PGS Catalog scores linked **{stats['pgs_publications']}** publications "
                 "(GWAS source, development, evaluation); their curated sample ancestry replaces text extraction for those papers.")
    flags = stats["flags"]
    if flags:
        L.append("- Flags: " + "; ".join(f"{k} ×{v}" for k, v in flags.most_common()))
    L += ["", "![Population heat map](figures/population_heatmap.png)", "",
          f"*Heat-map value: {stats['heatmap_metric']}. Interactive version: `figures/population_map.html`.*", ""]

    L += [_heading("## Where the data came from (by country)", demo), "",
          "| Country | UN region | Income | Participants (extracted) | Papers |", "|---|---|---|---:|---:|"]
    for r in country_rows[:25]:
        L.append(f"| {r['name']} | {r['un_region']} | {'HIC' if r['high_income'] else 'LMIC'} | "
                 f"{format(r['participants'], ',') if r['participants'] else 'not stated'} | {r['papers']} |")
    if len(country_rows) > 25:
        L.append(f"| … {len(country_rows) - 25} more in `tables/country_summary.csv` | | | | |")
    L.append("")

    world_total = sum(p for _, p in REGION_POPULATION_2022.values())
    L += [_heading("## Who the participants were (by ancestry)", demo), "",
          "![Ancestry representation](figures/ancestry_representation.png)", "",
          "| Ancestry group | Participants | Share | Papers | World pop. share of matching UN region (2022) |",
          "|---|---:|---:|---:|---:|"]
    for g, name in ANCESTRY_GROUPS.items():
        if g not in anc_papers:
            continue
        ref = REGION_POPULATION_2022.get(g)
        ref_s = f"{ref[1] / world_total:.0%} ({ref[0]})" if ref else "n/a"
        L.append(f"| {name} ({g}) | {anc_n[g]:,} | {_pct(share.get(g, 0))} | {anc_papers[g]} | {ref_s} |")
    L += ["", "*Geography is not ancestry: the world-population column is coarse context only.*", ""]

    if pgs_summary and pgs_summary["scores"]:
        L += pgs_section(pgs_summary, demo, pgs_traits)

    L += [_heading("## Paper-level equity scores", demo), "",
          "Rubric (0-100): ancestry reporting 20, participant diversity 30, cross-ancestry analysis 15, "
          "limitations acknowledged 10, descriptor practice 10, local capacity & engagement 15.", "",
          f"> **{EQUITY_SCORE_SEMANTICS['note']}**", "",
          "| Score | Paper | Year | Via | Populations found | Source | Flags |", "|---:|---|---|---|---|---|---|"]
    ranked = sorted(with_pop, key=lambda pa: -pa[1].score)
    for p, a in ranked:
        pops = ", ".join(
            f"{g}{' ' + format(n, ',') if n else ''}" for g, n in sorted(a.ancestry_n.items())
        ) or "—"
        cs = ", ".join(sorted(a.country_n)) or ""
        if cs:
            pops += f" · {cs}"
        via = {"search": "search", "seed": "seed", "pgs": "PGS Catalog"}.get(p.via) \
            or f"{p.via} of {p.parent.split(':')[-1]}"
        title = p.title.replace("|", "/")
        link = f"[{title}]({p.url})" if p.url else title
        src = "PGS Catalog: " + ", ".join(sorted({t.split()[0] for t in p.pgs})) if p.pgs else "text"
        L.append(f"| {a.score} | {link} | {p.year} | {via} | {pops} | {src} | {'; '.join(a.flags) or ''} |")
    no_pop = [p for p, a in in_scope if not (a.ancestry_n or a.country_n)]
    if no_pop:
        L += ["", f"{len(no_pop)} genomic paper(s) did not describe their participants in the text available "
              "(abstract / open-access methods) and are not scored: " + "; ".join(p.title for p in no_pop[:8])
              + ("…" if len(no_pop) > 8 else "")]
    skipped = [p for p in papers if not any(p is q for q, _ in in_scope)]
    if skipped:
        L += ["", f"{len(skipped)} paper(s) had no human genomic study signal (tools, reviews) and were excluded "
              "from the map: " + "; ".join(p.title for p in skipped[:8]) + ("…" if len(skipped) > 8 else "")]
    L.append("")

    L += [_heading("## Score breakdown and evidence", demo), ""]
    for p, a in ranked:
        L += [f"### {a.score}/100 · {p.title}", ""]
        for name, c in a.components.items():
            ev = f" — {c['evidence']}" if c["evidence"] else ""
            L.append(f"- {name.replace('_', ' ')}: **{c['points']}/{c['max']}**{ev}")
        if a.records:
            L.append("- Population evidence:")
            seen = set()
            for r in sorted(a.records, key=lambda r: r.n is None):
                k = (r.term, r.section)
                if k in seen:
                    continue
                seen.add(k)
                L.append(f"  - `{r.term}` → {r.ancestry or '—'} / {r.iso3 or '—'}"
                         f"{' n=' + format(r.n, ',') if r.n else ''} ({r.kind}, {r.section}, {r.confidence})")
        if a.reference_panels:
            L.append(f"- Reference panels noted (not counted): {', '.join(a.reference_panels)}")
        L.append("")

    L += [_heading("## Methods", demo), "",
          "1. **Retrieval**: Europe PMC REST API (`resultType=core`), sorted by citation count. "
          "Cascade follows `/references` and/or `/citations` for each paper, breadth-first.",
          "1b. **PGS Catalog** (optional): scores for a trait or by ID; for each, the source GWAS, development and "
          "evaluation publications join the audit, and their curated `ancestry_broad`, `ancestry_country` and "
          "`sample_number` replace text extraction for those papers.",
          "2. **Scope filter**: a paper is audited only if its title/abstract/MeSH describes human genetic or "
          "genomic data (GWAS, sequencing, genotyping, PRS, biobank…).",
          "3. **Extraction**: deterministic lexicons for ancestry terms, demonyms, country names and 35 named "
          "biobanks/cohorts, applied to the abstract and, for open-access papers, to methods/participants sections "
          "only. Sample sizes are linked to the nearest population term in the same sentence. Reference panels "
          "(1000 Genomes, gnomAD, HRC…) are excluded.",
          "4. **Scoring**: transparent rubric; each point is backed by the quoted evidence above.",
          "5. **Map**: participants (or papers) per country on an Equal Earth (equal-area) projection.", "",
          _heading("## Limitations", demo), "",
          "- Rule-based extraction misses populations described only in tables or supplements, and abstracts often "
          "omit per-group sample sizes; treat counts as a lower bound.",
          "- Per paper, the largest N per group is kept to avoid double counting discovery + replication totals; "
          "the same cohort appearing in several papers is counted once per paper.",
          "- Country of recruitment ≠ ancestry (e.g. UK Biobank is in the UK but multi-ancestry).",
          "- PGS Catalog sample sets with the same stage, ancestry and N within one paper are counted once (the "
          "Catalog repeats a set per score that reused it, per GWAS Catalog accession and per performance record); "
          "two genuinely different sets that coincide on all three would be merged.",
          "- Participant totals are participant-analyses summed over papers, not unique people.",
          "- Income groups follow the World Bank FY2025 classification (editable in `reference/build_countries.py`).", ""]
    if demo:
        L += [f"**{SYNTHETIC_LABEL}: generated from the bundled synthetic fixture. Not real literature.**", ""]
    L += ["---", "", f"*{DISCLAIMER}*", ""]
    return "\n".join(L)


def _fmt_groups(counts: dict[str, int]) -> str:
    return "; ".join(f"{g} {n:,}" for g, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def summarise_pgs(pgs_res: PGSResult, stages: dict, papers: list, audits: list) -> dict:
    """Tables for the PGS section plus the text-extraction check against curation."""
    from equity_lit_pgs import broad_to_codes, sample_identity
    scores, links = [], []
    for s in pgs_res.scores:
        mine = [l for l in pgs_res.links if l.pgs_id == s["id"]]
        per_stage = {st: {} for st in STAGES}
        seen = set()
        for l in mine:
            for smp in l.samples:
                n = smp.get("sample_number")
                ident = (l.seed, *sample_identity(l.stage, smp))
                if ident in seen:   # same sample set listed twice for this score (see sample_identity)
                    continue
                seen.add(ident)
                codes = broad_to_codes(smp.get("ancestry_broad") or "")
                code = codes[0] if len(codes) == 1 else "OTH"
                if isinstance(n, (int, float)):
                    per_stage[l.stage][code] = per_stage[l.stage].get(code, 0) + int(n)
        gw = per_stage["GWAS"]
        scores.append({
            "pgs_id": s["id"], "name": s.get("name", ""), "trait": s.get("trait_reported", ""),
            "variants": s.get("variants_number", ""),
            "development_paper": "; ".join(l.seed for l in mine if l.stage == "development"),
            "gwas_papers": "; ".join(dict.fromkeys(l.seed for l in mine if l.stage == "GWAS")),
            "evaluation_papers": "; ".join(dict.fromkeys(l.seed for l in mine if l.stage == "evaluation")),
            "gwas_ancestry": _fmt_groups(gw), "development_ancestry": _fmt_groups(per_stage["development"]),
            "evaluation_ancestry": _fmt_groups(per_stage["evaluation"]),
            "gwas_european_share": round(gw.get("EUR", 0) / sum(gw.values()), 3) if gw else "",
        })
        for l in mine:
            for smp in l.samples:
                links.append({
                    "pgs_id": l.pgs_id, "stage": l.stage, "paper": l.seed, "participants": smp.get("sample_number", ""),
                    "ancestry_broad": smp.get("ancestry_broad", ""), "countries": smp.get("ancestry_country", ""),
                    "cohorts": ", ".join(c.get("name_short", "") for c in smp.get("cohorts") or []),
                })

    # How well does the rule-based text extraction recover curated ancestry groups?
    rows, hit, total = [], 0, 0
    title_of = {p.key: p.title for p in papers}
    for a in audits:
        if not a.source.startswith("PGS Catalog"):
            continue
        cur = {g for g in a.ancestry_n if g not in {"NR", "OTH"}}
        txt = {g for g in a.text_ancestry_n if g not in {"NR", "OTH"}}
        if not cur:
            continue
        found = cur & txt
        hit += len(found)
        total += len(cur)
        rows.append({"paper": a.key, "title": title_of.get(a.key, ""), "curated": sorted(cur), "text": sorted(txt),
                     "missed": sorted(cur - txt), "extra": sorted(txt - cur)})
    check = {"rows": rows, "summary": {"papers": len(rows), "curated_groups": total, "recovered": hit,
                                       "recall": round(hit / total, 3) if total else None}}
    return {"scores": scores, "links": links, "check": check, "stages": stages}


def attach_pgs(papers: list, pgs_res: PGSResult) -> dict[str, list]:
    """Link PGS Catalog publications to papers; add stub papers Europe PMC lacks.

    Returns {paper key: curated PopulationRecords}.
    """
    by_key = {p.key: p for p in papers}
    by_doi = {p.doi.lower(): p for p in papers if p.doi}
    by_pmid = {p.pmid: p for p in papers if p.pmid}
    curated: dict[str, list] = {}
    for link in pgs_res.links:
        src, pid = parse_seed(link.seed)
        paper = by_key.get(f"{src}:{pid}") or (by_pmid.get(pid) if src == "MED" else None) \
            or (by_doi.get(pid.lower()) if src == "DOI" else None)
        if paper is None:
            paper = paper_from_publication(src, pid, link.publication)
            papers.append(paper)
            by_key[paper.key] = paper
        tag = f"{link.pgs_id} ({link.stage})"
        if tag not in paper.pgs:
            paper.pgs.append(tag)
        if paper.via == "seed":
            paper.via = "pgs"
        curated.setdefault(paper.key, []).extend(curated_records(link))
    return curated


def main(argv=None) -> int:
    args = parse_args(argv)
    out = Path(args.output).expanduser().resolve()
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(parents=True, exist_ok=True)

    seeds: list[str] = []
    if args.pmids:
        seeds += [s for s in args.pmids.split(",") if s.strip()]
    if args.input:
        seeds += [ln.strip() for ln in Path(args.input).read_text().splitlines()
                  if ln.strip() and not ln.startswith("#")]

    cache = Path(args.cache_dir) if args.cache_dir else None
    if args.demo:
        # The ONLY place the synthetic fixture is loaded. Live mode never falls back to it.
        client = FixtureClient(DEMO_FIXTURE)
        pgs_client = PGSFixtureClient(DEMO_FIXTURE)
        query = DEMO_QUERY
    else:
        client = EuropePMCClient(cache_dir=cache)
        pgs_client = PGSCatalogClient(cache_dir=cache)
        query = args.query
    pgs_ids = [x.strip() for x in (args.pgs_ids or "").split(",") if x.strip()]
    label = " | ".join(x for x in [
        query, ", ".join(seeds),
        f"PGS Catalog trait '{args.pgs_trait}'" if args.pgs_trait else "",
        f"PGS {', '.join(pgs_ids)}" if pgs_ids else "",
    ] if x)
    provenance = provenance_block(args.demo, bool(args.pgs_trait or pgs_ids), cache)
    tag = f"[{SYNTHETIC_LABEL}] " if args.demo else ""

    # Partial retrieval failures (one reference list, one full text) do not stop the run,
    # but they are recorded and reported: nothing is ever substituted for missing data.
    retrieval_warnings: list[str] = []

    def log(msg: str = "") -> None:
        print(msg)
        if "warning:" in msg:
            retrieval_warnings.append(msg.split("warning:", 1)[1].strip())

    print(f"{tag}Equity Lit Auditor: {label}")
    pgs_res = PGSResult()
    try:
        if args.pgs_trait or pgs_ids:
            pgs_res = gather(pgs_client, args.pgs_trait, pgs_ids, args.pgs_max_scores, not args.no_pgs_eval, log=log)
            if args.pgs_trait and not pgs_res.traits:
                print(f"PGS Catalog has no trait matching '{args.pgs_trait}'.", file=sys.stderr)
        papers = collect_papers(client, query, seeds + pgs_res.seeds, args.max_results, args.cascade, args.depth,
                                args.per_paper, args.max_papers, not args.no_fulltext, log=log)
    except requests.RequestException as exc:
        print(f"Could not reach Europe PMC / PGS Catalog ({exc.__class__.__name__}): {exc}\n"
              "No report was written: live results are never replaced by demo data. Check your internet "
              "connection and retry (add --cache-dir to keep what was fetched), or run --demo to see the "
              "pipeline on synthetic data.", file=sys.stderr)
        return 3
    curated = attach_pgs(papers, pgs_res)
    if not papers:
        print("No papers found. Try a broader query.", file=sys.stderr)
        return 2
    audits = [audit_paper(p, curated.get(p.key)) for p in papers]
    for p, a in zip(papers, audits):
        a.pgs = list(p.pgs)
    agg = aggregate(papers, audits, args.include_non_genomic, args.metric)
    in_scope, with_pop, country_rows, share, anc_n, anc_papers, region_participants, stats = agg
    print(f"  {tag}audited {stats['papers_in_scope']} genomic papers; {stats['countries']} countries on the map")

    metric_label = "Participants" if stats["heatmap_metric"] == "participants" else "Papers"
    title = "Where the genomic data came from"
    subtitle = (f"{stats['papers_with_population_data']} papers · {label[:90]} · "
                f"{metric_label.lower()} per country of recruitment" + (f" · {SYNTHETIC_LABEL}" if args.demo else ""))
    heatmap_png({r["iso3"]: r["value"] for r in country_rows}, metric_label, title, subtitle,
                out / "figures" / "population_heatmap.png",
                unknown={r["iso3"] for r in country_rows if r["value"] <= 0}, synthetic=args.demo)
    heatmap_html(country_rows, metric_label, title, subtitle, out / "figures" / "population_map.html",
                 synthetic=args.demo)
    representation_png(share, "extracted N" if stats["participants_extracted"] else "paper mentions",
                       out / "figures" / "ancestry_representation.png", synthetic=args.demo)
    pgs_stages = stage_ancestry(pgs_res) if pgs_res.scores else {}
    if pgs_res.scores:
        pgs_stage_png(pgs_stages, out / "figures" / "pgs_stage_ancestry.png", demo=args.demo)

    # Every table carries the provenance in its first column, so a CSV lifted out of the
    # output folder still says whether its rows are real.
    prov = provenance["data_provenance"]

    def tagged(rows: list[dict]) -> list[dict]:
        return [{"data_provenance": prov, **r} for r in rows]

    audit_by_key = {a.key: a for a in audits}
    paper_rows = []
    for p in papers:
        a = audit_by_key[p.key]
        row = {"key": p.key, "title": p.title, "year": p.year, "journal": p.journal, "doi": p.doi,
               "pmid": p.pmid, "pmcid": p.pmcid, "url": p.url, "via": p.via, "parent": p.parent,
               "depth": p.depth, "genomic_study": p.is_genomic_study, "fulltext_methods_read": bool(p.methods_text),
               "equity_score": a.score, "equity_score_role": EQUITY_SCORE_SEMANTICS["role"],
               "ancestry_groups": ";".join(f"{g}:{n or ''}" for g, n in sorted(a.ancestry_n.items())),
               "countries": ";".join(f"{c}:{n or ''}" for c, n in sorted(a.country_n.items())),
               "author_countries": ";".join(a.affiliation_countries), "flags": " | ".join(a.flags),
               "population_source": a.source, "pgs": "; ".join(p.pgs)}
        for name, c in a.components.items():
            row[name] = c["points"]
        paper_rows.append(row)
    comp_names = list(audits[0].components)
    write_csv(out / "tables" / "papers.csv", tagged(paper_rows),
              ["data_provenance", *paper_rows[0]] if paper_rows else ["data_provenance"])
    rec_rows = [{"paper": a.key, **r.__dict__} for a in audits for r in a.records]
    write_csv(out / "tables" / "population_records.csv", tagged(rec_rows),
              ["data_provenance", "paper", "ancestry", "iso3", "n", "term", "kind", "section", "confidence", "snippet"])
    write_csv(out / "tables" / "country_summary.csv",
              tagged([{**r, "titles": " | ".join(r["titles"])} for r in country_rows]),
              ["data_provenance", "iso3", "name", "un_region", "high_income", "participants", "papers", "titles"])
    write_csv(out / "tables" / "ancestry_summary.csv",
              tagged([{"ancestry": g, "label": ANCESTRY_GROUPS[g], "participants": anc_n[g],
                       "share": round(share.get(g, 0), 4), "papers": anc_papers[g]}
                      for g in ANCESTRY_GROUPS if g in anc_papers]),
              ["data_provenance", "ancestry", "label", "participants", "share", "papers"])

    pgs_summary = summarise_pgs(pgs_res, pgs_stages, papers, audits)
    if pgs_res.scores:
        write_csv(out / "tables" / "pgs_scores.csv", tagged(pgs_summary["scores"]),
                  ["data_provenance", "pgs_id", "name", "trait", "variants", "development_paper", "gwas_papers",
                   "evaluation_papers", "gwas_ancestry", "development_ancestry", "evaluation_ancestry",
                   "gwas_european_share"])
        write_csv(out / "tables" / "pgs_links.csv", tagged(pgs_summary["links"]),
                  ["data_provenance", "pgs_id", "stage", "paper", "participants", "ancestry_broad", "countries",
                   "cohorts"])
    stats["pgs_scores"] = len(pgs_res.scores)
    stats["pgs_publications"] = len(pgs_res.seeds)
    stats["extraction_check"] = pgs_summary["check"]["summary"]
    stats["retrieval_warnings"] = retrieval_warnings

    report = build_report(label, args, papers, audits, agg, args.demo, pgs_summary, provenance=provenance,
                          retrieval_warnings=retrieval_warnings, pgs_traits=pgs_res.traits)
    (out / "report.md").write_text(report, encoding="utf-8")

    stats_json = {"synthetic": provenance["synthetic"], "data_provenance": prov,
                  "equity_score_role": EQUITY_SCORE_SEMANTICS["role"],
                  **stats, "flags": dict(stats["flags"])}
    data = {"synthetic": provenance["synthetic"], "data_provenance": prov, "provenance": provenance,
            "equity_score_semantics": EQUITY_SCORE_SEMANTICS,
            "query": query, "seeds": seeds, "demo": args.demo,
            "settings": {k: getattr(args, k) for k in ("max_results", "cascade", "depth", "per_paper",
                                                        "max_papers", "no_fulltext", "include_non_genomic", "metric",
                                                        "pgs_trait", "pgs_ids", "pgs_max_scores", "no_pgs_eval")},
            "papers": [{**{k: v for k, v in p.__dict__.items() if k != "methods_text"},
                        "audit": audit_by_key[p.key].to_dict()} for p in papers],
            "countries": [{k: v for k, v in r.items() if k != "value"} for r in country_rows],
            "ancestry_share": share, "rubric_components": comp_names,
            "pgs": {"traits": pgs_res.traits, "stage_ancestry": pgs_stages,
                    "scores": pgs_summary["scores"], "links": pgs_summary["links"],
                    "extraction_check": pgs_summary["check"]}}
    written = [out / "report.md"]
    if write_result_json:
        result_path = write_result_json(out, SKILL_NAME, SKILL_VERSION, summary=stats_json, data=data,
                                        datasets=provenance["sources"])
        # Lift the provenance flags to the top of the ClawBio envelope as well.
        envelope = json.loads(result_path.read_text())
        envelope = {"synthetic": provenance["synthetic"], "data_provenance": prov, **envelope}
        result_path.write_text(json.dumps(envelope, indent=2, default=str))
        written.append(result_path)
        cmd = ["python", "skills/equity-lit-auditor/equity_lit_auditor.py"] + (list(argv) if argv else sys.argv[1:])
        written.append(write_commands_sh(out, shlex.join(cmd)))
        deps = []
        for pkg in ("requests", "matplotlib"):
            try:
                deps.append(f"{pkg}=={version(pkg)}")
            except PackageNotFoundError:
                deps.append(pkg)
        written.append(write_environment_yml(out, "clawbio-equity-lit", deps,
                                             python_version=f"{sys.version_info.major}.{sys.version_info.minor}"))
        written += sorted((out / "figures").iterdir()) + sorted((out / "tables").iterdir())
        write_checksums(written, out, anchor=out)
    else:
        (out / "result.json").write_text(json.dumps({"synthetic": provenance["synthetic"], "data_provenance": prov,
                                                     "skill": SKILL_NAME, "summary": stats_json, "data": data},
                                                    indent=2, default=str))
    print(f"Report: {out / 'report.md'}")
    print(f"Heat map: {out / 'figures' / 'population_heatmap.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
