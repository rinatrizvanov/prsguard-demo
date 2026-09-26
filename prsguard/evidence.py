"""Normalised evidence for ONE candidate score and ONE person: the only input of the applicability gate.

The builder collects facts produced upstream (genotype build resolution, harmonisation, reference placement,
reference distribution, PGS Catalog metadata audit) into the gate-input schema ``prs-applicability-gate.input.v2``.
It does not decide anything. Missing facts stay ``None`` (UNKNOWN); nothing is inferred to fill a gap.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GATE_INPUT_SCHEMA = "prs-applicability-gate.input.v2"
PLACEMENT_GROUPS = ("AFR", "AMR", "EAS", "EUR", "SAS")


def ratio_weight_type(weight_type) -> bool:
    """True when the Catalog weight type is a ratio scale (OR/HR/RR), which cannot be summed additively."""
    if not isinstance(weight_type, str) or not weight_type.strip():
        return False
    w = weight_type.strip().lower()
    if w.startswith("log") or w in ("beta", "nr", "not reported"):
        return False
    return w in ("or", "hr", "rr") or any(k in w for k in ("odds ratio", "hazard ratio", "relative risk",
                                                            "risk ratio"))


def canonical_sha256(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=True, default=str).encode()).hexdigest()


def _weight_loss_by_status(h) -> dict[str, float]:
    total = sum(abs(r["weight"]) for r in h.rows) or 1.0
    loss: dict[str, float] = {}
    for r in h.rows:
        if r["dosage"] is None:
            loss[r["status"]] = loss.get(r["status"], 0.0) + abs(r["weight"]) / total
    return {k: round(v, 4) for k, v in sorted(loss.items(), key=lambda kv: -kv[1])}


def harmonisation_block(score, h, basic_scoreability: dict) -> dict:
    c = h.counts
    # "Located" = the genotype has a call at this variant (by rsID or position), whatever the alleles say.
    located = c["matched"] + c["matched_flipped"] + c["allele_mismatch"] + c["palindromic_excluded"]
    return {
        "n_variants": c["n_variants"], "n_matched": c["n_matched"], "status_counts": {k: v for k, v in c.items()
                                                                                    if k not in ("n_variants",
                                                                                                 "n_matched")},
        "n_located": located,
        "allele_mismatch_fraction": round(c["allele_mismatch"] / located, 4) if located else None,
        "weight_loss_by_status": _weight_loss_by_status(h),
        "fraction_matched": basic_scoreability["fraction_matched"],
        "fraction_abs_weight_matched": basic_scoreability["fraction_abs_weight_matched"],
        "top5pct_weight_variants_missing": len(basic_scoreability["top5pct_weight_variants_missing"]),
        "position_matching": h.build_used_for_positions is not None, "notes": h.notes,
    }


def scoreability_block(refdist: dict | None, basic: dict) -> dict:
    """Scoreability metric for the gate: r(full, reduced) from the reference panel when available.

    Fallback when no panel scores exist: sqrt(share of expected variance retained) from the Catalog-reported
    effect-allele frequencies (independence assumed: ignores LD, so it is labelled as an approximation).
    """
    s = (refdist or {}).get("scoreability") or {}
    if s.get("r_full_reduced_adjusted") is not None:
        return {"r": s["r_full_reduced_adjusted"], "method": "reference_panel_correlation",
                "r_unadjusted": s.get("r_full_reduced"), "spearman": s.get("spearman_full_reduced"),
                "panel_variance_share": s.get("panel_variance_share"), "measured_in": s.get("measured_in"),
                "n_samples": s.get("n_samples"),
                "fraction_scoring_variants_in_panel": s.get("fraction_scoring_variants_in_panel")}
    vs = basic.get("fraction_variance_matched_reported_af")
    if vs is not None:
        return {"r": round(vs ** 0.5, 4), "method": "reported_af_variance_share_independence_approximation"}
    return {"r": None, "method": None}


def evaluation_block(audit: dict) -> dict:
    ev = audit.get("evaluation_ancestry") or {}
    units = []
    for u in ev.get("units") or []:
        metrics = [m for p in u.get("performance") or [] for m in p.get("metrics") or []]
        units.append({"pgp_id": u.get("pgp_id"), "pss_id": u.get("pss_id"), "code": u.get("code"),
                      "pooled": bool(u.get("pooled")), "component_codes": u.get("component_codes") or [],
                      "n": u.get("n"), "cases": u.get("cases"), "percent_male": u.get("percent_male"),
                      "countries": u.get("countries") or [],
                      "covariates": sorted({p.get("covariates") for p in u.get("performance") or []
                                            if p.get("covariates")}),
                      "metrics": [{k: m.get(k) for k in ("name", "group", "estimate", "ci_lower", "ci_upper",
                                                         "null", "informative")} for m in metrics]})
    return {"reported": ev.get("reported"), "unit": ev.get("unit"), "units": units}


def build_gate_input(*, candidate: dict, score, genotypes, harmonisation, basic_scoreability: dict,
                     person_sex: str | None, placement: dict, refdist: dict | None, audit: dict) -> dict:
    header = score.header or {}
    weight_type = (audit.get("score") or {}).get("weight_type") or header.get("weight_type")
    body = {
        "schema": GATE_INPUT_SCHEMA,
        "candidate": {"pgs_id": candidate["pgs_id"], "pre_rank": candidate.get("pre_rank"),
                      "trait_reported": candidate.get("trait_reported"),
                      "sex_specific": candidate.get("sex_specific")},
        "score_file": {"name": score.path, "sha256": score.sha256, "build": score.build,
                       "weight_type": weight_type, "ratio_weight_type": ratio_weight_type(weight_type),
                       "unsupported_features": list(score.unsupported),
                       "n_parse_problems": len(score.parse_problems),
                       "variants_interactions": (audit.get("score") or {}).get("variants_interactions")},
        "genotype": {"file_sha256": genotypes.sha256, "format": genotypes.fmt, "n_calls": len(genotypes.calls),
                     "n_called": genotypes.n_called, "build": genotypes.build,
                     "build_evidence": genotypes.build_evidence},
        "person": {"sex": person_sex},
        "harmonisation": harmonisation_block(score, harmonisation, basic_scoreability),
        "scoreability": scoreability_block(refdist, basic_scoreability),
        "placement": {k: placement.get(k) for k in ("status", "placement", "nearest_reference", "placement_stability",
                                                    "n_sites_used", "detail")},
        "catalog_metadata": {"status": audit.get("status"), "failed_checks": audit.get("failed_checks") or [],
                             "detail": audit.get("detail"),
                             "warnings": [c["check_id"] for c in audit.get("consistency_checks") or []
                                          if c.get("status") == "warn"]},
        "evaluation": evaluation_block(audit),
        "reference_distribution": None if refdist is None else {
            k: refdist.get(k) for k in ("available", "reference_group", "reference_n", "n_intersection",
                                        "reference_sensitive", "reference_sensitive_pairs", "detail")},
    }
    body["input_digest"] = canonical_sha256(body)
    return body
