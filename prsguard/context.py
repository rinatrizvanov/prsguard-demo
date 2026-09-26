"""Context from ClawBio skills that PRSGuard shows but never feeds into the applicability gate.

* equity-scorer: pairwise FST between the 1000 Genomes core groups (its Nei G_ST implementation) on the PCA
  panel, reported as the genetic distance between the person's reference group and the groups the score was
  developed in; and its representation index for the score's evaluation participants.
* ClawBio gwas-prs: its ``calculate_prs`` recomputes the raw score over the variants PRSGuard matched by rsID in
  the forward orientation, as an independent implementation cross-check.

Nothing here changes a gate status. The gate's inputs are built by prsguard.evidence only.
"""

from __future__ import annotations

import numpy as np

from prsguard.clawbio_env import load_skill_module
from prsguard.reference.projection import GROUPS, core_mask

CONTEXT_NOTE = "context only: not an input to the applicability gate"


def _equity():
    return load_skill_module("equity-scorer", "equity_scorer.py", "_clawbio_equity_scorer")


def _gwas_prs():
    return load_skill_module("gwas-prs", "gwas_prs.py", "_clawbio_gwas_prs")


_FST_CACHE: dict[str, dict] = {}


def fst_table(panel) -> dict:
    key = str(panel.meta.get("sha256"))
    if key not in _FST_CACHE:
        _FST_CACHE[key] = _fst(panel)
    return _FST_CACHE[key]


def _fst(panel) -> dict:
    mask, groups = core_mask(panel)
    geno = panel.dosages[:, mask].T.astype(np.int16)
    labels = groups[mask]
    pop_indices = {g: list(np.where(labels == g)[0]) for g in GROUPS}
    _, fst = _equity().compute_pairwise_fst(geno, pop_indices)
    return {f"{a}-{b}": round(float(v), 4) for (a, b), v in fst.items()}


def _fst_pair(table: dict, a: str, b: str) -> float | None:
    if a == b:
        return 0.0
    return table.get(f"{a}-{b}", table.get(f"{b}-{a}"))


def score_context(audit: dict, person_group: str | None, table: dict) -> dict:
    dev = (audit.get("development_ancestry") or {}).get("distribution_pct") or {}
    gwas = (audit.get("source_gwas_ancestry") or {}).get("distribution_pct") or {}
    stage, dist = ("development", dev) if dev else ("source GWAS", gwas)
    fst = None
    if person_group:
        fst = {g: {"percent_of_stage": pct, "fst_to_person_group": _fst_pair(table, person_group, g)}
               for g, pct in dist.items() if g in GROUPS}
    eval_counts = (audit.get("evaluation_ancestry") or {}).get("n_individuals_by_code") or {}
    rep = _equity().compute_representation_index({k: int(v) for k, v in eval_counts.items()
                                                   if isinstance(v, (int, float))}) if eval_counts else None
    return {"note": CONTEXT_NOTE, "source_skill": "equity-scorer",
            "fst_method": "Nei G_ST, ratio of averages, 1000 Genomes core groups on the PCA panel",
            "person_group": person_group, "compared_stage": stage, "fst_to_stage_groups": fst,
            "evaluation_representation_index": rep}


def gwas_prs_crosscheck(score, harmonisation, genotypes) -> dict:
    """Recompute our raw score with ClawBio gwas-prs over rows we matched by rsID without a strand flip."""
    rows = [r for r in harmonisation.rows if r["status"] == "matched" and r["match_by"] == "rsid"]
    if not rows:
        return {"note": CONTEXT_NOTE, "source_skill": "gwas-prs", "variants": 0, "agree": None,
                "detail": "no rsID-matched forward-strand variants to cross-check"}
    gp = _gwas_prs()
    geno = {r["rsid"]: r["genotype"] for r in rows}
    variants = [{"rsid": r["rsid"], "effect_allele": r["effect"], "effect_weight": r["weight"]} for r in rows]
    theirs = gp.calculate_prs(geno, variants)["raw_score"]
    ours = sum(r["weight"] * r["dosage"] for r in rows)
    return {"note": CONTEXT_NOTE, "source_skill": "gwas-prs", "variants": len(rows),
            "prsguard_partial_sum": round(ours, 8), "gwas_prs_partial_sum": round(float(theirs), 8),
            "agree": bool(abs(ours - theirs) < 1e-9),
            "why_not_primary": "gwas-prs matches by rsID only and does not resolve strand flips, palindromic "
                               "SNPs, duplicates or position-only scoring files"}
