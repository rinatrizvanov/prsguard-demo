"""PRSGuard end-to-end run: one person, one trait.

Steps marked ORCHESTRATION gather evidence, call tools and report; steps marked DETERMINISTIC_DECISION are made
by fixed code (router rules, placement, harmonisation, the prs-applicability-gate skill). Orchestration is
performed either by an LLM agent driving these tools or, by default, by this deterministic scripted PRSGuard CLI
orchestrator; the result records which. Whoever orchestrates can never change a threshold, re-run until SUPPORTED,
pick a score by its personal result, choose a reference population, or override the gate: orchestration never
decides applicability.

The person's genotypes never leave this machine: only trait text and PGS identifiers are sent to the PGS Catalog
(and, for optional literature context, to Europe PMC).
"""

from __future__ import annotations

import hashlib
import json
import platform
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

import prsguard
from prsguard import catalog, context, cross_pgs, evidence, router
from prsguard.clawbio_env import PINNED_CLAWBIO_COMMIT, REPO_ROOT, clawbio_root
from prsguard.genotypes import load_genotypes, resolve_build
from prsguard.harmonize import harmonise, read_scoring_file, scoreability
from prsguard.reference import distribution, projection
from prsguard.reference.panel import load_panel

RESULT_SCHEMA = "prsguard.result.v1"
QUESTION = "Can this PGS result actually be interpreted for this person?"
PCA_PANEL = REPO_ROOT / "data" / "reference" / "1000g_pca.npz"
PGS_PANEL = REPO_ROOT / "data" / "reference" / "1000g_pgs.npz"
GRCH38_ANCHORS = REPO_ROOT / "data" / "reference" / "1000g_pca_grch38_positions.json"
SNAPSHOT = REPO_ROOT / "data" / "catalog_snapshot"
GATE_PATH = REPO_ROOT / "skills" / "prs-applicability-gate" / "prs_applicability_gate.py"
PLACEMENT_NOTE = "Genetic reference placement is not ethnicity or identity."
GEOGRAPHY_NOTE = "Geography is not ancestry: countries are where participants were recruited."
DISCLAIMER = ("PRSGuard is RESEARCH SOFTWARE / a PROTOTYPE, not a medical device. It does not diagnose, and it never "
              "converts a polygenic score into absolute risk. SUPPORTED is a research-prototype reportability state, "
              "not a clinical recommendation: it requires evidence of association in a relevant evaluation group, "
              "not clinically useful discrimination or calibration. " + PLACEMENT_NOTE)
ORCH, DET = "ORCHESTRATION", "DETERMINISTIC_DECISION"
SCRIPTED_ORCHESTRATOR = "PRSGuard CLI (deterministic scripted orchestrator)"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_gate():
    import importlib.util

    name = "_prs_applicability_gate"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class RunConfig:
    genotype: Path
    trait: str
    out_dir: Path
    sex: str | None = None
    declared_build: str | None = None
    catalog_mode: str = "snapshot"
    snapshot_dir: Path = SNAPSHOT
    candidates: Path | None = None          # a frozen candidate set to reuse (digest verified)
    top_k: int = 3
    max_variants: int | None = 10_000        # router E8: engineering constraint of the shipped reference panel
    case: dict = field(default_factory=dict)  # demo labels {id, title, provenance, synthetic}
    literature_context: Path | None = None
    command: list[str] = field(default_factory=list)
    orchestrated_by: str | None = None       # who orchestrated; default: the scripted CLI
    orchestrator_kind: str = "scripted_cli"   # "scripted_cli" or "llm_agent"
    sample: str | None = None                 # VCF sample to analyse (required for multi-sample VCFs)


class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    def step(self, actor: str, title: str, tool: str, summary: str, outputs: dict | None = None,
             started: str | None = None) -> None:
        self.steps.append({"step": len(self.steps) + 1, "actor": actor, "title": title, "tool": tool,
                           "summary": summary, "outputs": outputs or {}, "started_at": started or _now(),
                           "finished_at": _now()})


# ---------------------------------------------------------------------------
# Evidence views for the report / frontend (descriptive; not gate inputs)
# ---------------------------------------------------------------------------


COUNTRIES_CSV = REPO_ROOT / "skills" / "equity-lit-auditor" / "reference" / "countries.csv"
_ALIASES: dict[str, tuple[str, str]] | None = None


def country_iso3(raw: str) -> tuple[str | None, str | None]:
    """(ISO3, canonical name) using the equity-lit-auditor country table; unknown spellings stay unmapped."""
    import csv

    global _ALIASES
    if _ALIASES is None:
        _ALIASES = {}
        with COUNTRIES_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for a in [row["name"], row["iso3"], *[x for x in row["aliases"].split("|") if x]]:
                    _ALIASES.setdefault(a.strip().lower(), (row["iso3"], row["name"]))
        _ALIASES.update({"uk": ("GBR", "United Kingdom"), "u.k.": ("GBR", "United Kingdom"),
                         "u.s": ("USA", "United States"),
                         # official names missing from the table (not typo corrections, which stay unmapped)
                         "republic of ireland": ("IRL", "Ireland"),
                         "republic of north macedonia": ("MKD", "North Macedonia"),
                         "former yugoslav republic of macedonia": ("MKD", "North Macedonia")})
    key = raw.replace("\ufeff", "").strip().lower()
    key = key[4:] if key.startswith("the ") else key
    return _ALIASES.get(key, (None, None))


def _split_countries(value) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [c.replace("\ufeff", "").strip() for c in items if c and c.strip() and c.strip() not in ("NR", "and more.")]


def _merge_countries(rows) -> list[dict]:
    """One row per (stage, country): Catalog spellings of the same country (U.S., USA, US) are merged by ISO3;
    unmapped spellings stay separate and keep iso3 = None."""
    merged: dict[tuple, dict] = {}
    for v in rows:
        iso3, name = country_iso3(v["country"])
        key = (v["stage"], iso3 or f"raw:{v['country']}")
        e = merged.setdefault(key, {"stage": v["stage"], "iso3": iso3, "name": name or v["country"],
                                    "country": name or v["country"], "raw_spellings": [], "n": 0, "units": 0,
                                    "codes": set()})
        e["raw_spellings"].append(v["country"])
        e["n"] += v["n"]
        e["units"] += v["units"]
        e["codes"] |= {c for c in v["codes"] if c}
    return sorted(({**e, "codes": sorted(e["codes"]), "raw_spellings": sorted(set(e["raw_spellings"]))}
                   for e in merged.values()), key=lambda e: (e["stage"], -e["n"], e["name"]))


def population_evidence(audit: dict) -> dict:
    def stage(block: dict | None, unit: str) -> dict:
        block = block or {}
        return {"distribution_pct": block.get("distribution_pct") or {}, "n_individuals": block.get("n_individuals"),
                "unit": block.get("unit", unit), "reported": block.get("reported")}

    ev = audit.get("evaluation_ancestry") or {}
    countries: dict[str, dict] = {}
    for u in ev.get("units") or []:
        for c in _split_countries(u.get("countries")):
            e = countries.setdefault(f"evaluation:{c}", {"country": c, "stage": "evaluation", "n": 0, "units": 0,
                                                         "codes": set()})
            e["n"] += u.get("n") or 0
            e["units"] += 1
            e["codes"].add(u.get("code"))
    for st, block in (("development", audit.get("development_ancestry")), ("gwas", audit.get("source_gwas_ancestry"))):
        for s in (block or {}).get("samples") or []:
            for c in _split_countries(s.get("countries")):
                e = countries.setdefault(f"{st}:{c}", {"country": c, "stage": st, "n": 0, "units": 0,
                                                       "codes": set()})
                e["n"] += s.get("n") or 0
                e["units"] += 1
                e["codes"].add(s.get("code"))
    evaluation_units = []
    for u in ev.get("units") or []:
        evaluation_units.append({
            "pgp_id": u.get("pgp_id"), "pss_id": u.get("pss_id"), "code": u.get("code"), "pooled": u.get("pooled"),
            "n": u.get("n"), "cases": u.get("cases"), "percent_male": u.get("percent_male"),
            "countries": u.get("countries") or [],
            "metrics": [{k: m.get(k) for k in ("name", "estimate", "ci_lower", "ci_upper", "null", "informative",
                                               "direction")}
                        for p in u.get("performance") or [] for m in p.get("metrics") or []],
            "covariates": sorted({p.get("covariates") for p in u.get("performance") or [] if p.get("covariates")})})
    return {
        "stages": {"gwas": stage(audit.get("source_gwas_ancestry"), "individuals"),
                   "development": stage(audit.get("development_ancestry"), "individuals"),
                   "evaluation": {"distribution_pct": ev.get("distribution_pct") or {},
                                  "unit": ev.get("unit"), "sample_set_count": ev.get("sample_set_count"),
                                  "n_individuals_by_code": ev.get("n_individuals_by_code") or {},
                                  "sample_sets_by_code": ev.get("sample_sets_by_code") or {}}},
        "countries": _merge_countries(countries.values()),
        "countries_note": GEOGRAPHY_NOTE + " A multi-country sample's N is shown for each of its countries.",
        "evaluation_units": evaluation_units,
        "publications": ev.get("publications") or {},
        "consistency_checks": audit.get("consistency_checks") or [],
    }


def reference_interpretation(gate_result: dict, raw_score: float | None, refdist: dict | None) -> dict:
    claims = gate_result["allowed_claims"]
    out = {"status": gate_result["status"],
           "raw_score": {"released": claims["raw_score"], "value": raw_score if claims["raw_score"] else None,
                         "meaning": "sum of effect weight x effect-allele dosage over the matched variants; has "
                                    "no meaning on its own scale"},
           "standardized_score": {"released": claims["standardized_score"], "value": None},
           "percentile": {"released": claims["percentile"], "value": None},
           "absolute_risk": {"released": False, "value": None,
                             "meaning": "never provided: requires calibrated incidence data, age, and a validated "
                                        "absolute-risk model"}}
    if claims["percentile"] and refdist and refdist.get("available"):
        out["standardized_score"].update({
            "value": refdist.get("standardized_score"),
            "meaning": f"(score - mean) / SD in {refdist['reference_n']} {refdist['reference_group']} 1000 Genomes "
                       "reference individuals scored on the same variants"})
        out["percentile"].update({
            "value": refdist["percentile"], "ci_panel": refdist["ci_panel"],
            "missing_variant_interval": refdist["missing_variant_interval"],
            "combined_interval": refdist["combined_interval"], "reference_group": refdist["reference_group"],
            "reference_n": refdist["reference_n"], "reference_populations": refdist.get("reference_populations"),
            "subpopulation_percentiles": refdist["subpopulation_percentiles"],
            "sensitivity_note": refdist.get("sensitivity_note"),
            "meaning": "position among reference individuals of the placed group; not a probability of disease"})
    withheld = [k for k in ("raw_score", "standardized_score", "percentile") if not out[k]["released"]]
    if withheld:
        out["withheld"] = {"items": withheld, "because": gate_result["reason_codes"]}
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _scoring(pid: str, build: str, source) -> Any:
    """Harmonised scoring file of ``pid``, located through the ACTIVE catalog source only.

    The score record (and so the scoring-file URL) comes from the run's own source: the verified snapshot
    directory in snapshot mode, or the live PGS Catalog (recorded into the run's snapshot directory) in live
    mode. The bundled default snapshot is never consulted implicitly.
    """
    rec = source.fetch(f"score/{pid}").json()
    files = (rec.get("ftp_harmonized_scoring_files") or {}) if isinstance(rec, dict) else {}
    url = (files.get(build) or {}).get("positions") if isinstance(files.get(build), dict) else None
    path, entry = catalog.scoring_file(pid, build, source, url)
    return read_scoring_file(path, build), entry


def _aligned(a, b) -> bool:
    return len(a.variants) == len(b.variants) and all(
        (x.effect, x.other, x.weight) == (y.effect, y.other, y.weight) for x, y in zip(a.variants, b.variants))


def run(cfg: RunConfig) -> dict:
    started = _now()
    trace = Trace()
    gate = load_gate()
    gate_cfg = gate.load_config()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    pca = load_panel(PCA_PANEL)
    pgs_panel = load_panel(PGS_PANEL)

    # 1 ORCHESTRATION: validate inputs locally
    t0 = _now()
    gs = load_genotypes(cfg.genotype, cfg.sample)
    trace.step(ORCH, "Receive the request and read the genotype file locally", "prsguard.genotypes.load_genotypes",
               f"{gs.fmt} file with {len(gs.calls):,} records ({gs.n_called:,} called); trait '{cfg.trait}', "
               f"sex {cfg.sex or 'not given'}, declared build {cfg.declared_build or 'not given'}. The genotype "
               "never leaves this machine.", {"sha256": gs.sha256, "format": gs.fmt}, t0)

    # 2 DET: build
    t0 = _now()
    anchors = {str(i): (str(c), int(p)) for i, c, p in zip(pca.ids, pca.chrom, pca.pos) if str(i).startswith("rs")}
    a38 = json.loads(GRCH38_ANCHORS.read_text())["positions"] if GRCH38_ANCHORS.exists() else None
    resolve_build(gs, anchors, cfg.declared_build, a38)
    trace.step(DET, "Resolve the genome build (never assumed)", "prsguard.genotypes.resolve_build",
               f"build {gs.build}: {gs.build_evidence.get('method')}", gs.build_evidence, t0)

    # 3-5 ORCHESTRATION + DET: trait, catalog search, eligibility/pre-rank/freeze
    source = catalog.open_source(cfg.catalog_mode, cfg.snapshot_dir)
    t0 = _now()
    router_build = gs.build if gs.build in ("GRCh37", "GRCh38") else None
    if cfg.candidates:
        cset = json.loads(Path(cfg.candidates).read_text())
        if not router.verify_frozen(cset):
            raise SystemExit(f"candidate set {cfg.candidates} failed digest verification; refusing to score")
        if router._norm(cset["trait"]["query"]) != router._norm(cfg.trait):
            raise SystemExit("candidate set was frozen for a different trait")
        opts = cset["options"]
        if opts.get("sex") not in (None, cfg.sex) or opts.get("build") not in (None, router_build):
            raise SystemExit(f"candidate set options {opts} do not match this person's sex/build")
        how = f"reused frozen candidate set {Path(cfg.candidates).name}"
    else:
        cset, raw = router.route(cfg.trait, source, router.RouterOptions(sex=cfg.sex, build=router_build,
                                                                         max_variants=cfg.max_variants,
                                                                         top_k=cfg.top_k))
        if cfg.catalog_mode == "live":
            source.save()
        how = f"routed from the PGS Catalog ({source.mode})"
    # PGS IDs name the per-candidate gate files below: accept only PGS Catalog identifiers (never paths).
    bad = [pid for pid in cset.get("selected") or []
           if not isinstance(pid, str) or not catalog.PGS_ID_RE.fullmatch(pid)]
    if bad:
        raise SystemExit(f"candidate set contains invalid PGS identifiers {bad!r}; refusing to run")
    router.write_frozen(cset, cfg.out_dir / "candidates.frozen.json")
    trait = cset["trait"]
    trace.step(ORCH, "Resolve the trait to an ontology term and scope", "PGS Catalog /trait/search",
               (f"'{cfg.trait}' -> {trait['term']['id']} {trait['term']['label']} ({trait['detail']}); scope "
                f"{len(trait['scope'])} terms, {len(trait.get('excluded_children') or [])} sub-phenotypes excluded")
               if trait.get("term") else f"trait unresolved: {trait.get('detail')}",
               {"term": trait.get("term"), "scope": [s["id"] for s in trait.get("scope") or []]}, t0)
    if cset.get("status") != "FROZEN":
        raise SystemExit(f"trait '{cfg.trait}' could not be resolved: {trait.get('detail')}")
    trace.step(ORCH, "Search the PGS Catalog and collect score metadata", "PGS Catalog /score/search",
               f"{cset['n_found']} scores mapped to the in-scope terms ({how})",
               {"n_found": cset["n_found"], "catalog": cset.get("catalog")}, t0)
    trace.step(DET, "Apply eligibility rules, pre-rank, and FREEZE before any personal scoring",
               "prsguard.router", f"{cset['n_eligible']} eligible; top {len(cset['selected'])} selected: "
               f"{', '.join(cset['selected'])}; digest {cset['digest'][:19]}...",
               {"selected": cset["selected"], "digest": cset["digest"], "frozen_at": cset["frozen_at"]}, t0)

    # 6 DET: placement, once per person
    t0 = _now()
    pc = gate_cfg["placement"]
    if abs(pc["cloud_quantile"] - projection.CLOUD_QUANTILE) > 1e-12:
        raise SystemExit("placement cloud quantile differs from the calibration config; refusing to run")
    policy = projection.PlacementPolicy(min_sites=pc["min_sites"], min_stability=pc["min_stability"])
    placement = projection.run_placement(pca, gs, policy)
    excluded = set(placement["self_match"]["matches"])
    group = placement.get("placement")
    trace.step(DET, "Place the person against the fixed 1000 Genomes reference (once)",
               "prsguard.reference.projection", f"{placement['status']}"
               + (f" in {group}" if group else f" (nearest {placement.get('nearest_reference')})")
               + (f"; stability {placement.get('placement_stability')}" if placement.get('placement_stability')
                  is not None else "") + f"; {placement['n_sites_used']} sites"
               + (f"; excluded self-match {sorted(excluded)}" if excluded else ""),
               {k: placement.get(k) for k in ("status", "placement", "nearest_reference", "placement_stability",
                                               "n_sites_used")}, t0)

    # 7-9 DET: per candidate harmonise, evidence, gate
    fst = context.fst_table(pca)
    by_id = {e["pgs_id"]: e for e in cset["eligible"]}
    items, cands = [], []
    t7 = _now()
    for pid in cset["selected"]:
        cand = by_id[pid]
        score_build = "GRCh38" if gs.build == "GRCh38" else "GRCh37"
        score, sf_entry = _scoring(pid, score_build, source)
        h = harmonise(score, gs)
        basic = scoreability(score, h)
        score37 = score if score_build == "GRCh37" else _scoring(pid, "GRCh37", source)[0]
        audit, _ = catalog.run_cohort_audit(pid, source, trait_query=None, scoring_file_header=score.header)
        if score_build == "GRCh37" or _aligned(score, score37):
            refdist = distribution.reference_distribution(pgs_panel, score37, h, group, excluded,
                                                          placement.get("consistent_populations"))
        else:
            refdist = {"available": False, "detail": "GRCh38 and GRCh37 scoring files are not row-aligned"}
        gi = evidence.build_gate_input(candidate=cand, score=score, genotypes=gs, harmonisation=h,
                                       basic_scoreability=basic, person_sex=cfg.sex, placement=placement,
                                       refdist=refdist, audit=audit)
        result = gate.evaluate(gi, gate_cfg)
        (cfg.out_dir / "gate").mkdir(exist_ok=True)
        (cfg.out_dir / "gate" / f"{pid}.input.json").write_text(json.dumps(gi, indent=2) + "\n")
        (cfg.out_dir / "gate" / f"{pid}.result.json").write_text(json.dumps(result, indent=2) + "\n")
        items.append({"pgs_id": pid, "gate_status": result["status"], "pre_rank": cand["pre_rank"], "score": score,
                      "harmonisation": h, "refdist": refdist, "audit": audit})
        cands.append({
            "pgs_id": pid, "pre_rank": cand["pre_rank"], "name": cand.get("name"),
            "trait_reported": cand.get("trait_reported"), "variants_number": cand.get("variants_number"),
            "weight_type": cand.get("weight_type"), "publication": {**(audit.get("publication") or {}),
                                                                   **cand.get("publication", {})},
            "method_name": (audit.get("score") or {}).get("method_name"),
            "ranking_evidence": cand["ranking_evidence"], "sex_specific": cand.get("sex_specific"),
            "scoring_file": {"name": score.path, "build": score.build, "sha256": "sha256:" + score.sha256,
                             "url": sf_entry.get("url")},
            "harmonisation": {**gi["harmonisation"], "scoreability": gi["scoreability"]},
            "gate": result,
            "interpretation": reference_interpretation(result, None if h.raw_score is None
                                                       else round(h.raw_score, 6), refdist),
            "population_evidence": population_evidence(audit),
            "context": {"equity_scorer": context.score_context(audit, group, fst),
                        "gwas_prs_crosscheck": context.gwas_prs_crosscheck(score, h, gs)},
            "provenance": {"catalog_responses": (audit.get("provenance") or {}).get("responses"),
                           "gate_input_digest": gi["input_digest"]},
        })
    trace.steps.append({"step": 7, "actor": DET, "title": "Harmonise variants and compute raw scores",
                        "tool": "prsguard.harmonize (+ ClawBio gwas-prs cross-check)",
                        "summary": "; ".join(f"{c['pgs_id']} {c['harmonisation']['n_matched']}/"
                                             f"{c['harmonisation']['n_variants']} matched, r = "
                                             f"{c['harmonisation']['scoreability'].get('r')}" for c in cands),
                        "outputs": {}, "started_at": t7, "finished_at": _now()})
    trace.steps.append({"step": 8, "actor": DET, "title": "Audit PGS Catalog evidence and build reference "
                        "distributions", "tool": "prsguard.catalog + prsguard.reference.distribution",
                        "summary": "; ".join(f"{c['pgs_id']} metadata "
                                             f"{c['gate']['evidence_used'].get('catalog_metadata.status')}"
                                             for c in cands), "outputs": {}, "started_at": t7, "finished_at": _now()})
    trace.steps.append({"step": 9, "actor": DET, "title": "Applicability gate, one candidate at a time",
                        "tool": "skills/prs-applicability-gate",
                        "summary": "; ".join(f"{c['pgs_id']} {c['gate']['status']}"
                                             + (f" ({c['gate']['primary_reason']['code']})"
                                                if c['gate']['primary_reason'] else "") for c in cands),
                        "outputs": {c["pgs_id"]: c["gate"]["status"] for c in cands},
                        "started_at": t7, "finished_at": _now()})

    if cfg.catalog_mode == "live":
        source.save()  # record the score, performance and category responses fetched while scoring

    # 10 ORCHESTRATION: cross-PGS, primary, context, report
    t0 = _now()
    cross = cross_pgs.compare(items, pgs_panel, excluded)
    supported = sorted((c for c in cands if c["gate"]["status"] == "SUPPORTED"), key=lambda c: c["pre_rank"])
    primary = supported[0]["pgs_id"] if supported else None
    lit = None
    if cfg.literature_context and Path(cfg.literature_context).exists():
        lit = json.loads(Path(cfg.literature_context).read_text())
        if lit.get("synthetic") or lit.get("data_provenance") != "LIVE":
            raise SystemExit("refusing to attach synthetic or non-live literature context to a result")
    trace.step(ORCH, "Cross-PGS check, choose the primary score, attach context, report",
               "prsguard.cross_pgs + report", f"cross-PGS {cross['status']}; primary "
               f"{primary or 'none (no candidate SUPPORTED)'} by the fixed rule 'highest pre-ranked SUPPORTED'",
               {"cross_pgs": cross["status"], "primary": primary}, t0)

    headline = _headline(cands, primary, placement)
    result = {
        "schema": RESULT_SCHEMA, "question": QUESTION,
        "label": {"case_id": cfg.case.get("id"), "case_title": cfg.case.get("title"),
                  "data_provenance": cfg.case.get("provenance", "user-supplied genotype file (local)"),
                  "synthetic": bool(cfg.case.get("synthetic", False)), "description": cfg.case.get("description")},
        "headline": headline,
        "input": {"trait_query": cfg.trait, "sex": cfg.sex, "declared_build": cfg.declared_build,
                  "genotype": {"file": gs.path, "format": gs.fmt, "sha256": "sha256:" + gs.sha256,
                               "n_records": len(gs.calls), "n_called": gs.n_called}},
        "build": {"build": gs.build, **gs.build_evidence},
        "orchestration": {
            "kind": cfg.orchestrator_kind,
            "performed_by": cfg.orchestrated_by or SCRIPTED_ORCHESTRATOR,
            "note": "ORCHESTRATION steps gather evidence, call tools and report; DETERMINISTIC_DECISION steps are "
                    "made by fixed code. Orchestration (LLM agent or scripted CLI) never decides applicability."},
        "trace": trace.steps,
        "router": {k: cset.get(k) for k in ("trait", "options", "eligibility_rules", "ranking_rules", "n_found",
                                            "n_eligible", "selected", "digest", "frozen_at", "catalog")}
        | {"excluded_summary": _excluded_summary(cset),
           "eligible": [{k: e.get(k) for k in ("pre_rank", "pgs_id", "name", "trait_reported", "variants_number",
                                              "sex_specific", "date_release", "ranking_evidence", "publication")}
                        for e in cset["eligible"]]},
        "placement": {**{k: v for k, v in placement.items() if k != "plot"}, "note": PLACEMENT_NOTE,
                      "plot": placement.get("plot")},
        "candidates": cands,
        "cross_pgs": cross,
        "primary": {"pgs_id": primary, "rule": "highest pre-ranked candidate whose gate status is SUPPORTED"},
        "literature_context": None if lit is None else {"note": "context only: literature equity is never an "
                                                                "input to the gate", **lit},
        "reproducibility": _repro(cfg, gs, gate_cfg, cset, started),
        "disclaimer": DISCLAIMER,
    }
    (cfg.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=_json_default) + "\n")
    (cfg.out_dir / "report.md").write_text(render_report(result))
    _write_repro_bundle(cfg, result)
    return result


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


def _excluded_summary(cset: dict) -> dict:
    """Number of excluded SCORES failing each rule (a score can fail several), plus scores failing only E8."""
    by_rule: dict[str, int] = {}
    only_e8 = 0
    for x in cset.get("excluded") or []:
        rules = sorted({r.split(":")[0].split(" ")[0] for r in x["reasons"]})
        for k in rules:
            by_rule[k] = by_rule.get(k, 0) + 1
        only_e8 += rules == ["E8"]
    return {"n_excluded": len(cset.get("excluded") or []), "scores_failing_rule": by_rule,
            "excluded_only_by_engineering_E8": only_e8}


def ordinal(x: float) -> str:
    n = int(round(x))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _headline(cands: list[dict], primary: str | None, placement: dict) -> dict:
    counts = {s: sum(c["gate"]["status"] == s for c in cands) for s in ("SUPPORTED", "RAW_ONLY", "ABSTAIN")}
    if primary:
        c = next(c for c in cands if c["pgs_id"] == primary)
        p = c["interpretation"]["percentile"]
        text = (f"Yes, for {primary}: its percentile is supported for this person - {ordinal(p['value'])} percentile "
                f"of the {p['reference_group']} reference (95% interval {p['combined_interval'][0]:.0f}-"
                f"{p['combined_interval'][1]:.0f}). Not an absolute risk and not a clinical recommendation.")
        answer = "SUPPORTED"
    elif counts["RAW_ONLY"]:
        codes = sorted({code for c in cands for code in c["gate"]["reason_codes"]})
        text = ("Only partly: a raw score can be computed, but no percentile is supported for this person "
                f"({', '.join(codes)}).")
        answer = "RAW_ONLY"
    else:
        text = "No: none of the candidate scores can be interpreted from this genotype file."
        answer = "ABSTAIN"
    return {"answer": answer, "text": text, "counts": counts, "primary": primary,
            "placement": placement.get("status")}


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _repro(cfg: RunConfig, gs, gate_cfg: dict, cset: dict, started: str) -> dict:
    import importlib.metadata as md

    pkgs = {}
    for p in ("numpy", "scipy", "pandas", "pyyaml", "requests", "pysam"):
        try:
            pkgs[p] = md.version(p)
        except md.PackageNotFoundError:
            pkgs[p] = None
    manifest = cfg.snapshot_dir / catalog.SNAPSHOT_MANIFEST
    return {
        "prsguard_version": prsguard.__version__,
        "git_commit": _git(["rev-parse", "HEAD"], REPO_ROOT),
        "git_dirty": bool(_git(["status", "--porcelain", "--untracked-files=no"], REPO_ROOT)),
        "clawbio_commit": _git(["rev-parse", "HEAD"], clawbio_root()), "clawbio_pinned": PINNED_CLAWBIO_COMMIT,
        "python": sys.version.split()[0], "platform": platform.platform(), "packages": pkgs,
        "hashes": {"genotype": "sha256:" + gs.sha256,
                   "pca_panel": "sha256:" + str(load_panel_meta(PCA_PANEL).get("sha256")),
                   "pgs_panel": "sha256:" + str(load_panel_meta(PGS_PANEL).get("sha256")),
                   "catalog_snapshot_manifest": _sha256_file(manifest) if manifest.exists() else None,
                   "gate_config": gate_cfg["_sha256"], "candidate_set": cset["digest"]},
        "calibration_version": gate_cfg["calibration_version"],
        "seeds": {"placement_bootstrap": projection.PlacementPolicy().seed, "reference_subset": projection.REF_SEED},
        "catalog": {"mode": cfg.catalog_mode, **(cset.get("catalog") or {})},
        "started_at": started, "finished_at": _now(),
        "command": " ".join(shlex.quote(c) for c in cfg.command) if cfg.command else None,
    }


def load_panel_meta(path: Path) -> dict:
    meta = Path(path).with_suffix(".json")
    return json.loads(meta.read_text()) if meta.exists() else {}


def _write_repro_bundle(cfg: RunConfig, result: dict) -> None:
    d = cfg.out_dir / "reproducibility"
    d.mkdir(exist_ok=True)
    rep = result["reproducibility"]
    (d / "provenance.json").write_text(json.dumps(rep, indent=2) + "\n")
    (d / "commands.sh").write_text("#!/usr/bin/env bash\n# Re-run this analysis (offline, from the committed "
                                   "PGS Catalog snapshot)\nset -euo pipefail\n" + (rep["command"] or "") + "\n")
    traces = {c["pgs_id"]: c["gate"]["rule_trace"] for c in result["candidates"]}
    (d / "gate_traces.json").write_text(json.dumps(traces, indent=2) + "\n")


def render_report(r: dict) -> str:
    L = [f"# PRSGuard: {r['input']['trait_query']}", ""]
    if r["label"].get("case_id"):
        L += [f"**Case {r['label']['case_id']}: {r['label']['case_title']}** - data: {r['label']['data_provenance']}"
              + (" - **SYNTHETIC**" if r["label"]["synthetic"] else ""), ""]
    L += [f"> {r['question']}", "", f"**{r['headline']['answer']}** - {r['headline']['text']}", "",
          "## Orchestration and decision trace", "",
          f"Orchestration performed by: {r['orchestration']['performed_by']}", "",
          "| # | Actor | Step | Result |", "|---|---|---|---|"]
    L += [f"| {s['step']} | {s['actor']} | {s['title']} | {s['summary']} |" for s in r["trace"]]
    pl = r["placement"]
    L += ["", "## Reference placement", "", f"{pl['status']}: {pl.get('detail')}. *{PLACEMENT_NOTE}*", "",
          "## Candidates (pre-ranked before any personal scoring)", "",
          "| Pre-rank | PGS | Variants matched | r(full, reduced) | Gate | Reason codes | Percentile |",
          "|---|---|---|---|---|---|---|"]
    for c in r["candidates"]:
        p = c["interpretation"]["percentile"]
        L.append(f"| {c['pre_rank']} | {c['pgs_id']} | {c['harmonisation']['n_matched']}/"
                 f"{c['harmonisation']['n_variants']} | {c['harmonisation']['scoreability'].get('r')} | "
                 f"**{c['gate']['status']}** | {', '.join(c['gate']['reason_codes']) or '-'} | "
                 + (f"{p['value']:.1f} ({p['combined_interval'][0]:.1f}-{p['combined_interval'][1]:.1f})"
                    if p["released"] else "withheld") + " |")
    L += ["", f"Cross-PGS: **{r['cross_pgs']['status']}** - {r['cross_pgs']['detail']}", "",
          f"Primary: {r['primary']['pgs_id'] or 'none'} ({r['primary']['rule']})", "",
          f"Reproducibility: PRSGuard {r['reproducibility']['prsguard_version']}, calibration "
          f"{r['reproducibility']['calibration_version']}, candidate set {r['router']['digest']}", "",
          f"*{r['disclaimer']}*", ""]
    return "\n".join(L)
