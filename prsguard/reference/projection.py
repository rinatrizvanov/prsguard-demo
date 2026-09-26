"""Reference placement of ONE person relative to fixed, labelled 1000 Genomes reference populations.

Method (no unsupervised clustering, no arbitrary k):

1. Fixed reference: 1000 Genomes phase 3 "core" populations with little recent admixture define the axes
   (AFR: YRI LWK GWD MSL ESN; EUR: CEU TSI FIN GBR IBS; EAS: CHB JPT CHS CDX KHV; SAS: GIH PJL BEB STU ITU;
   AMR: PEL). Admixed populations (ASW ACB MXL PUR CLM) are never used to define axes; they are held-out test
   cases for intermediate placement.
2. PCA is refit on the reference restricted to the SNPs the person actually has (no projection shrinkage from
   missing sites), genotypes standardised with core-reference allele frequencies. K = 4 PCs: five continental
   reference groups span a 4-dimensional between-group space (benchmark over K in docs/calibration.md).
3. The person is projected and compared with each group's reference cloud by Mahalanobis distance. Inside a
   cloud = D^2 <= chi^2_{K}(0.999). Outside every cloud = INTERMEDIATE (admixed or not represented).
4. Robustness: the whole fit/projection/placement is repeated on bootstrap resamples of the SNPs. Placement
   stability = share of replicates giving the same placement. It is NOT an ancestry percentage.
5. Context only: supervised admixture proportions against fixed core-group allele frequencies (EM).

Genetic reference placement is not ethnicity, nationality or identity.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2

from prsguard.genotypes import GenotypeSet
from prsguard.reference.panel import ReferencePanel

CORE_POPS = {"AFR": ("YRI", "LWK", "GWD", "MSL", "ESN"), "EUR": ("CEU", "TSI", "FIN", "GBR", "IBS"),
             "EAS": ("CHB", "JPT", "CHS", "CDX", "KHV"), "SAS": ("GIH", "PJL", "BEB", "STU", "ITU"),
             "AMR": ("PEL",)}
ADMIXED_POPS = ("ASW", "ACB", "MXL", "PUR", "CLM")
GROUPS = tuple(CORE_POPS)
K = 4
CLOUD_QUANTILE = 0.999
REF_PER_GROUP = 100      # fixed-seed subset per core group used to fit axes and clouds (all 85 PEL)
REF_SEED = 1000
COMP = str.maketrans("ACGT", "TGCA")


@dataclass
class PlacementPolicy:
    """Calibrated in benchmarks/ancestry_benchmark.py; see docs/calibration.md."""
    min_sites: int = 200          # below this, held-out placement accuracy falls below the target
    min_stability: float = 0.95   # bootstrap agreement needed to report a RESOLVED placement
    bootstrap: int = 100
    seed: int = 20260926


def core_mask(panel: ReferencePanel, exclude: set[str] = frozenset()) -> tuple[np.ndarray, np.ndarray]:
    pop_to_group = {p: g for g, pops in CORE_POPS.items() for p in pops}
    groups = np.array([pop_to_group.get(p, "") for p in panel.pop])
    mask = (groups != "") & ~np.isin(panel.samples, list(exclude))
    return mask, groups


def fit_subset(panel: ReferencePanel, exclude: set[str] = frozenset()) -> tuple[np.ndarray, np.ndarray]:
    """Placement reference: REF_PER_GROUP core samples per group, chosen with a fixed seed (target excluded)."""
    mask, groups = core_mask(panel, exclude)
    rng = np.random.default_rng(REF_SEED)
    keep = np.zeros(len(mask), dtype=bool)
    for g in GROUPS:
        idx = np.where(mask & (groups == g))[0]
        keep[np.sort(rng.permutation(idx)[:REF_PER_GROUP])] = True
    return keep, groups


def target_dosages(panel: ReferencePanel, gs: GenotypeSet) -> np.ndarray:
    """Alt-allele dosage of the person at every panel site (NaN = not available/unverifiable)."""
    out = np.full(len(panel.pos), np.nan)
    use_pos = gs.build == "GRCh37"
    for i, (rsid, chrom, pos, ref, alt) in enumerate(zip(panel.ids, panel.chrom, panel.pos, panel.ref, panel.alt)):
        hits = gs.by_rsid.get(str(rsid), []) if str(rsid).startswith("rs") else []
        if hits and use_pos:
            c0 = gs.calls[hits[0]]
            if c0.pos is not None and (c0.chrom != str(chrom) or c0.pos != int(pos)):
                hits = []  # rsID/position conflict: do not align
        if not hits and use_pos:
            hits = gs.by_pos.get((str(chrom), int(pos)), [])
        if len(hits) != 1:
            continue
        alleles = gs.calls[hits[0]].alleles
        if len(alleles) != 2:
            continue
        s = set(alleles)
        if s <= {ref, alt}:
            out[i] = sum(a == alt for a in alleles)
        elif s <= {ref.translate(COMP), alt.translate(COMP)}:
            out[i] = sum(a == alt.translate(COMP) for a in alleles)
    return out


def _standardise(ref: np.ndarray, target: np.ndarray, p: np.ndarray):
    sd = np.sqrt(2 * p * (1 - p))
    sd[sd == 0] = 1.0
    x = (np.where(ref >= 0, ref, 2 * p) - 2 * p) / sd  # missing reference genotypes mean-imputed
    t = (target - 2 * p) / sd
    return x, t


def fit_project(ref: np.ndarray, target: np.ndarray, extra: np.ndarray | None = None, k: int = K):
    """PCA of reference rows (n x m) and projection of target (m,) and optional extra rows."""
    valid = ref >= 0
    p = np.where(valid, ref, 0).sum(0) / (2 * np.maximum(valid.sum(0), 1))
    keep = (p > 0.01) & (p < 0.99)
    x, t = _standardise(ref[:, keep], target[keep], p[keep])
    gram = x @ x.T
    vals, vecs = np.linalg.eigh(gram)
    order = np.argsort(vals)[::-1][:k]
    s = np.sqrt(np.maximum(vals[order], 1e-12))
    u = vecs[:, order]
    ref_pcs = u * s
    loadings = x.T @ u / s  # m x k
    tgt = t @ loadings
    ext = None
    if extra is not None:
        ex, _ = _standardise(extra[:, keep], target[keep], p[keep])
        ext = ex @ loadings
    return ref_pcs, tgt, ext, vals[order] / vals.sum()


def place(point: np.ndarray, ref_pcs: np.ndarray, labels: np.ndarray, k: int = K) -> dict:
    cut = float(chi2.ppf(CLOUD_QUANTILE, k))
    d2 = {}
    for g in GROUPS:
        pts = ref_pcs[labels == g]
        mu = pts.mean(0)
        cov = np.cov(pts.T) + np.eye(k) * 1e-9
        diff = point - mu
        d2[g] = float(diff @ np.linalg.solve(cov, diff))
    nearest = min(d2, key=d2.get)
    inside = [g for g in GROUPS if d2[g] <= cut]
    placement = nearest if d2[nearest] <= cut else "INTERMEDIATE"
    return {"placement": placement, "nearest": nearest, "mahalanobis_d2": {g: round(v, 3) for g, v in d2.items()},
            "inside_clouds": inside, "cloud_cut_d2": round(cut, 3)}


def population_consistency(panel: ReferencePanel, tgt: np.ndarray, ext_all: np.ndarray, all_idx: np.ndarray,
                           superpop: str, k: int = K) -> dict:
    """1000 Genomes populations of the nearest superpopulation (consortium labels, admixed ones included) whose
    own projected cloud contains the person. Each is an equally defensible reference for a percentile; the
    reference distribution checks whether the answer depends on which one is used (REFERENCE_SENSITIVE)."""
    cut = float(chi2.ppf(CLOUD_QUANTILE, k))
    pops = sorted({str(p) for p, sp in zip(panel.pop, panel.superpop) if sp == superpop})
    d2 = {}
    for pop in pops:
        rows = [n for n, j in enumerate(all_idx) if panel.pop[j] == pop]
        if len(rows) < 20:
            continue
        pts = ext_all[rows]
        diff = tgt - pts.mean(0)
        d2[pop] = round(float(diff @ np.linalg.solve(np.cov(pts.T) + np.eye(k) * 1e-9, diff)), 3)
    return {"consistent": sorted(p for p, v in d2.items() if v <= cut), "d2": d2}


def supervised_admixture(target: np.ndarray, freqs: np.ndarray, iters: int = 500, tol: float = 1e-8) -> np.ndarray:
    """EM for ancestry proportions q given fixed group alt-allele frequencies (m x G); context only."""
    obs = ~np.isnan(target)
    g = target[obs]
    p = np.clip(freqs[obs], 1e-4, 1 - 1e-4)
    q = np.full(p.shape[1], 1 / p.shape[1])
    for _ in range(iters):
        alt = p * q
        ref = (1 - p) * q
        a = alt / alt.sum(1, keepdims=True)
        b = ref / ref.sum(1, keepdims=True)
        new = (g[:, None] * a + (2 - g)[:, None] * b).sum(0) / (2 * len(g))
        if np.abs(new - q).max() < tol:
            q = new
            break
        q = new
    return q


SELF_MATCH_CONCORDANCE = 0.99   # identical genotypes (same person / monozygotic twin); first-degree ~0.6-0.7
SELF_MATCH_MIN_SITES = 100


def self_matches(panel: ReferencePanel, target: np.ndarray) -> dict:
    """Reference samples whose genotypes are identical to the person's at the observed projection sites.

    A person who is in the reference panel (e.g. a public 1000 Genomes demo genome) must not be compared with
    themselves; such samples are excluded from placement and from every reference distribution.
    """
    obs = ~np.isnan(target)
    if obs.sum() < SELF_MATCH_MIN_SITES:
        return {"checked_sites": int(obs.sum()), "matches": [], "rule": "not checked: too few sites"}
    d = panel.dosages[obs]
    conc = ((d == target[obs][:, None]) & (d >= 0)).sum(0) / np.maximum((d >= 0).sum(0), 1)
    hits = np.where(conc >= SELF_MATCH_CONCORDANCE)[0]
    return {"checked_sites": int(obs.sum()), "matches": [str(panel.samples[i]) for i in hits],
            "max_concordance": round(float(conc.max()), 4),
            "rule": f"exclude reference samples with genotype concordance >= {SELF_MATCH_CONCORDANCE} "
                    f"over >= {SELF_MATCH_MIN_SITES} sites"}


def run_placement(panel: ReferencePanel, gs: GenotypeSet, policy: PlacementPolicy | None = None,
                  exclude_samples: set[str] = frozenset(), with_plot: bool = True) -> dict:
    target = target_dosages(panel, gs)
    sm = self_matches(panel, target)
    out = place_vector(panel, target, policy, set(exclude_samples) | set(sm["matches"]), with_plot)
    out["self_match"] = sm
    return out


def place_vector(panel: ReferencePanel, target: np.ndarray, policy: PlacementPolicy | None = None,
                 exclude_samples: set[str] = frozenset(), with_plot: bool = True) -> dict:
    policy = policy or PlacementPolicy()
    mask, groups = fit_subset(panel, set(exclude_samples))
    obs = np.where(~np.isnan(target))[0]
    base = {"method": "PCA refit on the person's observed sites; Mahalanobis placement vs 1000G core groups",
            "reference": f"1000 Genomes phase 3 core populations ({REF_PER_GROUP} per group, fixed seed)",
            "k_pcs": K, "cloud_quantile": CLOUD_QUANTILE,
            "n_panel_sites": int(len(target)), "n_sites_used": int(len(obs)), "policy": policy.__dict__,
            "excluded_reference_samples": sorted(exclude_samples)}
    if len(obs) < policy.min_sites:
        return {**base, "status": "UNRESOLVED", "placement": None,
                "detail": f"{len(obs)} usable projection sites < {policy.min_sites} (calibrated minimum)"}
    ref = panel.dosages[np.ix_(obs, np.where(mask)[0])].T.astype(float)
    labels = groups[mask]
    admixed_mask = np.isin(panel.pop, ADMIXED_POPS) & ~np.isin(panel.samples, list(exclude_samples))
    # Every non-excluded panel sample is projected: for the plot and for population-level consistency below.
    all_idx = np.where(~np.isin(panel.samples, list(exclude_samples)))[0]
    extra = panel.dosages[np.ix_(obs, all_idx)].T.astype(float)
    ref_pcs, tgt, ext_all, var_expl = fit_project(ref, target[obs], extra)
    pos_of = {int(j): n for n, j in enumerate(all_idx)}
    ext = ext_all[[pos_of[int(j)] for j in np.where(admixed_mask)[0]]]
    main = place(tgt, ref_pcs, labels)
    consistency = population_consistency(panel, tgt, ext_all, all_idx, main["nearest"])
    rng = np.random.default_rng(policy.seed)
    boot_points, boot_place = [], []
    for _ in range(policy.bootstrap):
        idx = rng.integers(0, len(obs), len(obs))
        r_pcs, t_pt, _, _ = fit_project(ref[:, idx], target[obs][idx])
        # Align bootstrap PCs to the main fit (sign/rotation) by Procrustes on the reference points.
        m = r_pcs.T @ ref_pcs
        uu, _, vt = np.linalg.svd(m)
        rot = uu @ vt
        boot_points.append((t_pt @ rot).tolist())
        boot_place.append(place(t_pt, r_pcs, labels)["placement"])
    stability = boot_place.count(main["placement"]) / len(boot_place)
    fmask, _ = core_mask(panel, set(exclude_samples))
    freqs = np.vstack([np.where(panel.dosages[:, fmask & (groups == g)] >= 0,
                                panel.dosages[:, fmask & (groups == g)], 0).sum(1) /
                       (2 * np.maximum((panel.dosages[:, fmask & (groups == g)] >= 0).sum(1), 1))
                       for g in GROUPS]).T
    q = supervised_admixture(target, freqs)
    if main["placement"] == "INTERMEDIATE":
        status = "INTERMEDIATE"
    elif stability >= policy.min_stability:
        status = "RESOLVED"
    else:
        status = "UNSTABLE"
    out = {**base, "status": status, "placement": main["placement"] if status == "RESOLVED" else None,
           "nearest_reference": main["nearest"], "mahalanobis_d2": main["mahalanobis_d2"],
           "cloud_cut_d2": main["cloud_cut_d2"], "inside_clouds": main["inside_clouds"],
           "placement_stability": round(stability, 3),
           "bootstrap_placements": {p: boot_place.count(p) for p in sorted(set(boot_place), key=str)},
           "supervised_admixture_context": {g: round(float(v), 3) for g, v in zip(GROUPS, q)},
           "consistent_populations": consistency["consistent"], "population_d2": consistency["d2"],
           "variance_explained": [round(float(v), 4) for v in var_expl],
           "detail": {"RESOLVED": f"inside the {main['nearest']} reference cloud in {stability:.0%} of bootstrap "
                                  "replicates",
                      "INTERMEDIATE": f"outside every reference cloud (nearest {main['nearest']}); consistent with "
                                      "admixed or unrepresented ancestry",
                      "UNSTABLE": f"placement changes across marker bootstraps ({stability:.0%} agreement)"}[status]}
    if with_plot:
        pick = np.arange(len(labels))
        pops = panel.pop[mask]
        out["plot"] = {
            "reference": [{"pc": [round(float(v), 3) for v in ref_pcs[i, :3]], "group": str(labels[i]),
                           "pop": str(pops[i])} for i in pick],
            "admixed_reference": [{"pc": [round(float(v), 3) for v in ext[i, :3]], "pop": str(p)}
                                  for i, p in enumerate(panel.pop[admixed_mask])][::2] if ext is not None else [],
            "target": [round(float(v), 3) for v in tgt[:3]],
            "bootstrap": [[round(float(v), 3) for v in b[:3]] for b in boot_points],
        }
    return out


def reference_group_mask(panel: ReferencePanel, group: str, exclude: set[str] = frozenset()) -> np.ndarray:
    mask, groups = core_mask(panel, set(exclude))
    return mask & (groups == group)
