"""Empirical reference distribution of a PGS in 1000 Genomes, computed on the person's matched variant set.

Why this construction:

* The person's raw score is a sum over the variants that could be harmonised for them. A percentile is only
  meaningful against reference individuals scored on exactly the same variants with the same effect alleles,
  so the reference scores here use the intersection (person-matched and present in the reference panel).
* The reference for the percentile is the placed group's core 1000 Genomes populations (for AMR: PEL only).
* Uncertainty is reported, never hidden, from three separate sources:
  - finite reference panel: Jeffreys 95% interval for the empirical CDF at the person's score
    (the count below the person is Binomial(n, F(x)));
  - missing variants: the published score also includes variants the person lacks. In the reference group the
    full (panel-available) score is regressed on the reduced score; the 95% prediction interval of the person's
    full score is mapped to full-score percentiles. This uses the reference LD, not an independence assumption;
  - reference choice: percentiles against every 1000G population of the placed superpopulation whose own cloud
    contains the person (admixed populations included), with their intervals. Disjoint intervals mean the
    answer depends on which defensible reference is chosen (REFERENCE_SENSITIVE).
* r(full, reduced) in the reference group is the scoreability metric used by the gate: the reduced score's
  per-SD association with the outcome is approximately r x the published per-SD association.

Nothing here is an absolute risk. The percentile is a position within a reference sample of the general
population of one continental group, not a probability of disease.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import beta, norm, pearsonr, spearmanr

from prsguard.harmonize import COMP, PALINDROMIC, Harmonisation, ScoringFile
from prsguard.reference.panel import ReferencePanel
from prsguard.reference.projection import CORE_POPS, core_mask

INTERVAL = 0.95


def panel_rows(panel: ReferencePanel, score: ScoringFile) -> tuple[np.ndarray, np.ndarray]:
    """For every scoring variant: panel row (-1 = not in panel) and whether the effect allele is the panel ALT.

    SNVs match directly or after a strand flip; indels match exactly. Palindromic SNVs are matched as reported
    (forward strand, as in the Catalog harmonisation) so that the panel's FULL score contains them and their loss
    is measured; they are never matched for the person (prsguard.harmonize excludes them).
    """
    index = panel.position_index()
    rows = np.full(len(score.variants), -1, dtype=np.int64)
    eff_alt = np.zeros(len(score.variants), dtype=bool)
    for v in score.variants:
        if v.chrom is None or v.pos is None or v.other is None or set(v.effect + v.other) - set("ACGT"):
            continue
        pair = {v.effect, v.other}
        snv = len(v.effect) == 1 and len(v.other) == 1
        for r in index.get((str(v.chrom), int(v.pos)), []):
            ref, alt = str(panel.ref[r]), str(panel.alt[r])
            if pair == {ref, alt}:
                rows[v.idx], eff_alt[v.idx] = r, v.effect == alt
            elif snv and pair not in PALINDROMIC and {a.translate(COMP) for a in pair} == {ref, alt}:
                rows[v.idx], eff_alt[v.idx] = r, v.effect.translate(COMP) == alt
            if rows[v.idx] >= 0:
                break
    return rows, eff_alt


def score_panel(panel: ReferencePanel, rows: np.ndarray, eff_alt: np.ndarray, weights: np.ndarray,
                use: np.ndarray, sample_mask: np.ndarray) -> np.ndarray:
    """Scores of reference samples over scoring variants ``use`` (boolean over scoring variants)."""
    sel = np.where(use & (rows >= 0))[0]
    if not len(sel):
        return np.zeros(int(sample_mask.sum()))
    d = panel.dosages[np.ix_(rows[sel], np.where(sample_mask)[0])].astype(float)
    missing = d < 0
    if missing.any():  # 1000G phase 3 is complete; kept for other panels: mean-impute from the same samples
        p = np.where(missing, 0, d).sum(1) / np.maximum((~missing).sum(1), 1)
        d = np.where(missing, p[:, None], d)
    eff = np.where(eff_alt[sel][:, None], d, 2 - d)
    return weights[sel] @ eff


def empirical_percentile(ref: np.ndarray, x: float) -> dict:
    n = len(ref)
    k = float((ref < x).sum() + 0.5 * (ref == x).sum())
    a = (1 - INTERVAL) / 2
    lo, hi = beta.ppf(a, k + 0.5, n - k + 0.5), beta.ppf(1 - a, k + 0.5, n - k + 0.5)
    return {"percentile": round(100 * k / n, 2), "ci_panel": [round(100 * float(lo), 2), round(100 * float(hi), 2)],
            "n_reference": n}


def reference_distribution(panel: ReferencePanel, score: ScoringFile, h: Harmonisation, group: str | None,
                           exclude_samples: set[str] = frozenset(),
                           sensitivity_pops: list[str] | None = None) -> dict:
    rows, eff_alt = panel_rows(panel, score)
    weights = np.array([v.weight for v in score.variants])
    person = np.array([r["dosage"] if r["dosage"] is not None else np.nan for r in h.rows], dtype=float)
    in_panel = rows >= 0
    matched = ~np.isnan(person)
    inter = matched & in_panel
    out = {"reference_panel": panel.meta.get("name", "1000g_pgs"), "panel_sha256": panel.meta.get("sha256"),
           "n_scoring_variants": len(score.variants), "n_scoring_variants_in_panel": int(in_panel.sum()),
           "n_person_matched": int(matched.sum()), "n_intersection": int(inter.sum()),
           "variant_set": "person-matched variants present in the reference panel (same effect alleles)",
           "group": group, "excluded_reference_samples": sorted(exclude_samples), "absolute_risk": None}
    if not inter.any():
        return {**out, "available": False, "detail": "no matched variant is present in the reference panel"}
    x = float(np.nansum(np.where(inter, weights * person, 0)))
    out["person_score_on_intersection"] = round(x, 6)
    mask_all = ~np.isin(panel.samples, list(exclude_samples))
    # Scoreability is measured in the group the person is placed in, or across all core samples if unplaced.
    cmask, cgroups = core_mask(panel, set(exclude_samples))
    sc_mask = cmask & (cgroups == group) if group else cmask
    full = score_panel(panel, rows, eff_alt, weights, in_panel, sc_mask)
    red = score_panel(panel, rows, eff_alt, weights, inter, sc_mask)
    if np.std(full) > 0 and np.std(red) > 0:
        r = float(pearsonr(full, red)[0])
        rho = float(spearmanr(full, red)[0])
    else:
        r = rho = None
    # Variants absent from the panel cannot be measured; assuming they are independent of the panel part, the
    # correlation with the complete score is r * sqrt(V_panel / (V_panel + V_absent)). V_absent uses the reported
    # effect-allele frequency when given, else p = 0.5 (maximum variance: conservative).
    v_panel = float(np.var(full, ddof=1)) if len(full) > 1 else 0.0
    absent = [v for v in score.variants if rows[v.idx] < 0]
    v_absent = sum(v.weight ** 2 * 2 * (v.af_reported if v.af_reported and 0 < v.af_reported < 1 else 0.5) *
                   (1 - (v.af_reported if v.af_reported and 0 < v.af_reported < 1 else 0.5)) for v in absent)
    share = v_panel / (v_panel + v_absent) if v_panel + v_absent > 0 else None
    r_adj = None if r is None or share is None else r * float(np.sqrt(share))
    out["scoreability"] = {"r_full_reduced": None if r is None else round(r, 4),
                           "r_full_reduced_adjusted": None if r_adj is None else round(r_adj, 4),
                           "spearman_full_reduced": None if rho is None else round(rho, 4),
                           "panel_variance_share": None if share is None else round(share, 4),
                           "measured_in": group or "all core reference samples",
                           "n_samples": int(sc_mask.sum()),
                           "full_score_definition": "all scoring variants present in the reference panel; "
                                                    "adjusted value accounts for variants absent from the panel",
                           "fraction_scoring_variants_in_panel": round(float(in_panel.mean()), 4)}
    if group is None:
        return {**out, "available": False, "detail": "no resolved reference group for this person"}
    gmask = sc_mask & mask_all
    ref_red = red
    mu, sd = float(ref_red.mean()), float(ref_red.std(ddof=1))
    pct = empirical_percentile(ref_red, x)
    out.update({"available": True, "reference_group": group, "reference_n": int(gmask.sum()),
                "reference_populations": list(CORE_POPS.get(group, ())),
                "reference_mean": round(mu, 6), "reference_sd": round(sd, 6),
                "standardized_score": round((x - mu) / sd, 3) if sd > 0 else None, **pct})
    # Missing-variant uncertainty: prediction interval of the full score given the reduced score.
    if r is not None and inter.sum() < in_panel.sum():
        b, a = np.polyfit(red, full, 1)
        resid_sd = float(np.std(full - (a + b * red), ddof=2))
        z = norm.ppf(1 - (1 - INTERVAL) / 2)
        pred = a + b * x
        lo_s, hi_s = pred - z * resid_sd, pred + z * resid_sd
        lo_p = empirical_percentile(full, lo_s)["percentile"]
        hi_p = empirical_percentile(full, hi_s)["percentile"]
        out["missing_variant_interval"] = [lo_p, hi_p]
        comb_lo = empirical_percentile(full, lo_s)["ci_panel"][0]
        comb_hi = empirical_percentile(full, hi_s)["ci_panel"][1]
        out["combined_interval"] = [comb_lo, comb_hi]
        out["missing_variant_method"] = ("95% prediction interval of the full panel score regressed on the reduced "
                                         "score in the reference group, mapped to full-score percentiles")
    else:
        out["missing_variant_interval"] = [pct["percentile"], pct["percentile"]]
        out["combined_interval"] = pct["ci_panel"]
        out["missing_variant_method"] = "no scoring variant missing among panel-available variants"
    # Reference-choice sensitivity: every 1000G population of the group whose cloud contains the person
    # (prsguard.reference.projection.population_consistency); the core populations if not given.
    subs = {}
    pops = sensitivity_pops if sensitivity_pops is not None else list(CORE_POPS.get(group, ()))
    out["sensitivity_populations"] = pops
    out["sensitivity_note"] = ("percentile reference = the group's core populations; sensitivity is checked against "
                               "every 1000 Genomes population of the superpopulation (admixed ones included) whose "
                               "cloud contains the person, as equally defensible alternatives")
    for pop in pops:
        pm = mask_all & (panel.pop == pop)
        if pm.sum() >= 20:
            subs[pop] = empirical_percentile(score_panel(panel, rows, eff_alt, weights, inter, pm), x)
    disjoint = [(a_, b_) for i, a_ in enumerate(subs) for b_ in list(subs)[i + 1:]
                if subs[a_]["ci_panel"][1] < subs[b_]["ci_panel"][0]
                or subs[b_]["ci_panel"][1] < subs[a_]["ci_panel"][0]]
    # Tri-state: true = compared and sensitive; false = compared and not sensitive; null = NOT evaluable (fewer
    # than two defensible references to compare). An unevaluated check is never reported as "not sensitive".
    evaluated = len(subs) >= 2
    out["subpopulation_percentiles"] = subs
    out["reference_sensitivity_assessable"] = evaluated
    out["reference_sensitive"] = bool(disjoint) if evaluated else None
    out["reference_sensitive_pairs"] = [list(p) for p in disjoint] if evaluated else None
    out["reference_sensitivity_detail"] = (
        f"compared {len(subs)} reference populations ({', '.join(subs)})" if evaluated else
        f"not evaluable: {len(subs)} defensible reference population(s) with >= 20 individuals "
        f"({', '.join(subs) or 'none'}); at least two are needed to compare")
    return out


def alternative_group_percentiles(panel: ReferencePanel, score: ScoringFile, h: Harmonisation,
                                  groups: list[str], exclude_samples: set[str] = frozenset()) -> dict:
    """Percentile of the same score against several groups (used for intermediate placements, context only)."""
    rows, eff_alt = panel_rows(panel, score)
    weights = np.array([v.weight for v in score.variants])
    person = np.array([r["dosage"] if r["dosage"] is not None else np.nan for r in h.rows], dtype=float)
    inter = ~np.isnan(person) & (rows >= 0)
    if not inter.any():
        return {}
    x = float(np.nansum(np.where(inter, weights * person, 0)))
    cmask, cgroups = core_mask(panel, set(exclude_samples))
    return {g: empirical_percentile(score_panel(panel, rows, eff_alt, weights, inter, cmask & (cgroups == g)), x)
            for g in groups}
