"""Cross-PGS consistency: do the scores that passed the gate tell the same story about this person?

Only SUPPORTED scores are compared (a percentile exists only for them). Agreement between two scores is weak
corroboration when the scores are dependent (shared variants, shared source GWAS, correlated in the reference
population), so dependence is quantified next to every comparison instead of being ignored.

Status per pair and overall:
  NOT_COMPARABLE  fewer than two SUPPORTED scores (nothing to compare), or no common reference group;
  CONSISTENT      the gap between the person's two percentiles lies within the central 95% of the gaps seen
                  among reference individuals of the same group (scored on the same variants);
  DISCORDANT      it lies outside: the scores disagree about this person more than two scores this correlated
                  disagree about people in general.
Non-overlap of the two percentile intervals is NOT used: two different scores with correlation r < 1 are
expected to place a person differently, so narrow intervals would make almost any pair "discordant".
The comparison never changes which score is primary (the highest pre-ranked SUPPORTED score) and never
removes a result: a DISCORDANT outcome is reported, not resolved by picking the preferred score.
"""

from __future__ import annotations

import numpy as np

from prsguard.reference.distribution import panel_rows, score_panel
from prsguard.reference.projection import core_mask


def _keys(score) -> dict[tuple[str, int], float]:
    return {(str(v.chrom), int(v.pos)): v.weight for v in score.variants if v.chrom and v.pos is not None}


def _source_gwas(audit: dict) -> set[str]:
    ids = set()
    for s in (audit.get("source_gwas_ancestry") or {}).get("samples") or []:
        for k in ("gwas_catalog_id", "source_pmid"):
            if s.get(k):
                ids.add(f"{k}:{s[k]}")
    return ids


def compare(items: list[dict], panel=None, exclude_samples: set[str] = frozenset()) -> dict:
    """``items``: dicts with pgs_id, gate_status, pre_rank, score (ScoringFile), harmonisation, refdist, audit."""
    supported = [it for it in items if it["gate_status"] == "SUPPORTED"]
    base = {"compared": [it["pgs_id"] for it in supported], "rule": "SUPPORTED scores only; CONSISTENT when the "
            "person's percentile gap is within the central 95% of reference individuals' gaps", "pairs": []}
    if len(supported) < 2:
        return {**base, "status": "NOT_COMPARABLE",
                "detail": f"{len(supported)} score(s) passed the gate; at least two are needed"}
    pairs, statuses = [], []
    for i, a in enumerate(supported):
        for b in supported[i + 1:]:
            ga, gb = a["refdist"].get("reference_group"), b["refdist"].get("reference_group")
            ka, kb = _keys(a["score"]), _keys(b["score"])
            inter = set(ka) & set(kb)
            wa = sum(abs(w) for w in ka.values()) or 1.0
            wb = sum(abs(w) for w in kb.values()) or 1.0
            pair = {"a": a["pgs_id"], "b": b["pgs_id"],
                    "variant_overlap_jaccard": round(len(inter) / max(len(set(ka) | set(kb)), 1), 4),
                    "shared_variants": len(inter),
                    "weighted_overlap": {a["pgs_id"]: round(sum(abs(ka[k]) for k in inter) / wa, 4),
                                         b["pgs_id"]: round(sum(abs(kb[k]) for k in inter) / wb, 4)},
                    "shared_source_gwas": sorted(_source_gwas(a["audit"]) & _source_gwas(b["audit"]))}
            if ga != gb or ga is None:
                pair.update({"status": "NOT_COMPARABLE", "detail": "different or missing reference groups"})
                pairs.append(pair)
                statuses.append("NOT_COMPARABLE")
                continue
            pa, pb = a["refdist"]["percentile"], b["refdist"]["percentile"]
            pair.update({"reference_group": ga, "percentiles": {a["pgs_id"]: pa, b["pgs_id"]: pb},
                         "combined_intervals": {a["pgs_id"]: a["refdist"]["combined_interval"],
                                                b["pgs_id"]: b["refdist"]["combined_interval"]}})
            if panel is None:
                pair.update({"status": "NOT_COMPARABLE", "detail": "no reference panel to calibrate the gap"})
            else:
                gap = _gap_test(panel, a, b, ga, exclude_samples, pa - pb)
                pair.update(gap)
                r = gap["reference_correlation"]
                pair["dependence_note"] = (
                    f"scores correlate r = {r:.2f} in the {ga} reference; " +
                    ("agreement is largely expected from shared signal, so it is weak corroboration" if abs(r) >= 0.5
                     else "agreement is not strongly implied by shared signal"))
            pairs.append(pair)
            statuses.append(pair["status"])
    status = ("DISCORDANT" if "DISCORDANT" in statuses else
              "CONSISTENT" if "CONSISTENT" in statuses else "NOT_COMPARABLE")
    return {**base, "status": status, "pairs": pairs,
            "detail": {"DISCORDANT": "at least one pair of SUPPORTED scores disagrees about this person more than "
                                     "the same pair disagrees for 95% of reference individuals",
                       "CONSISTENT": "every pair of SUPPORTED scores agrees within the range seen for 95% of "
                                     "reference individuals",
                       "NOT_COMPARABLE": "no pair shares a reference group"}[status]}


def _gap_test(panel, a: dict, b: dict, group: str, exclude: set[str], person_gap: float) -> dict:
    """Empirical reference distribution of percentile gaps between two scores (same variant sets as the person)."""
    cmask, cgroups = core_mask(panel, set(exclude))
    gmask = cmask & (cgroups == group)
    vals = []
    for it in (a, b):
        rows, eff_alt = panel_rows(panel, it["score"])
        w = np.array([v.weight for v in it["score"].variants])
        person = np.array([r["dosage"] is not None for r in it["harmonisation"].rows])
        vals.append(score_panel(panel, rows, eff_alt, w, person & (rows >= 0), gmask))
    ranks = [100 * (np.argsort(np.argsort(v)) + 0.5) / len(v) for v in vals]
    gaps = ranks[0] - ranks[1]
    lo, hi = np.percentile(gaps, [2.5, 97.5])
    q = float((np.sum(gaps < person_gap) + 0.5 * np.sum(gaps == person_gap)) / len(gaps))
    r = float(np.corrcoef(vals[0], vals[1])[0, 1]) if np.std(vals[0]) > 0 and np.std(vals[1]) > 0 else 0.0
    return {"reference_correlation": round(r, 4), "person_percentile_gap": round(person_gap, 2),
            "reference_gap_95": [round(float(lo), 2), round(float(hi), 2)],
            "gap_quantile_in_reference": round(q, 4), "n_reference": int(gmask.sum()),
            "status": "CONSISTENT" if lo <= person_gap <= hi else "DISCORDANT"}
