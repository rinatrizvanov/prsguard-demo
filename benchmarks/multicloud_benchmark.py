"""How often is a person inside MORE THAN ONE core reference cloud, and would it change the percentile?

Leave-one-out over every 1000 Genomes phase 3 individual (2,504; all projection sites), plus sparse arms (400 random
individuals each at 200, 400 and 800 random sites): each person is removed from the reference, placed with the
production placement code, and the set of core-group clouds containing them
(Mahalanobis d^2 <= chi-squared(4) 0.999 quantile) is recorded. For anyone inside two or more clouds, the percentile
of each demo score is computed against every containing group (their own genotypes at the PGS panel sites, person
excluded) and compared: disjoint Jeffreys 95% intervals mean the choice of group would change the interpretation.

    python benchmarks/multicloud_benchmark.py   # writes benchmarks/results/multicloud_benchmark.json
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prsguard.harmonize import read_scoring_file  # noqa: E402
from prsguard.reference import projection as P  # noqa: E402
from prsguard.reference.distribution import empirical_percentile, panel_rows, score_panel  # noqa: E402
from prsguard.reference.panel import load_panel  # noqa: E402

SCORES = ("PGS000004", "PGS001804", "PGS001336")
SPARSE_SITES = (200, 400, 800)
SPARSE_N = 400
SEED = 20260926
_pca = None


def _panel():
    global _pca
    if _pca is None:
        _pca = load_panel(ROOT / "data" / "reference" / "1000g_pca.npz")
    return _pca


def _one(job) -> dict:
    j, n_sites, seed = job
    pca = _panel()
    s = str(pca.samples[j])
    t = pca.dosages[:, j].astype(float)
    if n_sites:
        keep = np.random.default_rng(seed).choice(len(t), n_sites, replace=False)
        m = np.full(len(t), np.nan)
        m[keep] = t[keep]
        t = m
    out = P.place_vector(pca, t, P.PlacementPolicy(bootstrap=1, min_sites=1), exclude_samples={s}, with_plot=False)
    return {"sample": s, "pop": str(pca.pop[j]), "superpop": str(pca.superpop[j]), "n_sites": n_sites or "all",
            "status": out["status"], "nearest": out.get("nearest_reference"), "inside": out.get("inside_clouds") or []}


def main() -> int:
    pca = _panel()
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    jobs = [(j, None, 0) for j in range(len(pca.samples))]
    for n in SPARSE_SITES:
        jobs += [(int(j), n, int(rng.integers(1 << 30))) for j in rng.choice(len(pca.samples), SPARSE_N, replace=False)]
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, jobs, chunksize=16))
    core_pops = {p for pops in P.CORE_POPS.values() for p in pops}
    for r in rows:
        r["kind"] = "core" if r["pop"] in core_pops else "admixed" if r["pop"] in P.ADMIXED_POPS else "other"

    # Percentile consequence for multi-cloud individuals.
    pgs = load_panel(ROOT / "data" / "reference" / "1000g_pgs.npz")
    assert list(pgs.samples) == list(pca.samples)
    scores = {}
    for pid in SCORES:
        sf = read_scoring_file(ROOT / "data" / "catalog_snapshot" / pid / f"{pid}_hmPOS_GRCh37.txt.gz", "GRCh37")
        rows_, eff = panel_rows(pgs, sf)
        scores[pid] = (rows_, eff, np.array([v.weight for v in sf.variants]), rows_ >= 0)
    multi = [r for r in rows if len(r["inside"]) > 1]
    consequences = []
    for r in multi:
        j = int(np.where(pgs.samples == r["sample"])[0][0])
        person_mask = np.zeros(len(pgs.samples), dtype=bool)
        person_mask[j] = True
        cmask, cgroups = P.core_mask(pgs, {r["sample"]})
        entry = {"sample": r["sample"], "pop": r["pop"], "n_sites": r["n_sites"], "inside": r["inside"],
                 "scores": {}}
        for pid, (rows_, eff, w, use) in scores.items():
            x = float(score_panel(pgs, rows_, eff, w, use, person_mask)[0])
            per = {g: empirical_percentile(score_panel(pgs, rows_, eff, w, use, cmask & (cgroups == g)), x)
                   for g in r["inside"]}
            cis = [v["ci_panel"] for v in per.values()]
            disjoint = any(a[1] < b[0] or b[1] < a[0] for i, a in enumerate(cis) for b in cis[i + 1:])
            entry["scores"][pid] = {"percentiles": {g: v["percentile"] for g, v in per.items()},
                                    "ci_panel": {g: v["ci_panel"] for g, v in per.items()},
                                    "max_gap": round(max(v["percentile"] for v in per.values())
                                                     - min(v["percentile"] for v in per.values()), 2),
                                    "disjoint_intervals": disjoint}
        consequences.append(entry)

    def summary(kind, n_sites="all"):
        rs = [r for r in rows if r["kind"] == kind and r["n_sites"] == n_sites]
        combos: dict[str, int] = {}
        for r in rs:
            if len(r["inside"]) > 1:
                k = "+".join(sorted(r["inside"]))
                combos[k] = combos.get(k, 0) + 1
        return {"n": len(rs), "inside_0": sum(len(r["inside"]) == 0 for r in rs),
                "inside_1": sum(len(r["inside"]) == 1 for r in rs),
                "inside_2plus": sum(len(r["inside"]) > 1 for r in rs), "combinations": combos,
                "resolved_under_exactly_one_rule": sum(r["status"] == "RESOLVED" for r in rs)}

    by_pop = {}
    for r in multi:
        key = f"{r['pop']}@{r['n_sites']}"
        by_pop[key] = by_pop.get(key, 0) + 1
    disjoint = [c for c in consequences if any(s["disjoint_intervals"] for s in c["scores"].values())]
    out = {"benchmark": "multi-cloud membership, leave-one-out, all 1000 Genomes phase 3 individuals",
           "cloud_quantile": P.CLOUD_QUANTILE, "k_pcs": P.K, "ref_per_group": P.REF_PER_GROUP,
           "panel_sha256": pca.meta.get("sha256"), "runtime_s": round(time.time() - t0, 1),
           "summary": {str(n): {"core": summary("core", n), "admixed": summary("admixed", n)}
                       for n in ("all", *SPARSE_SITES)},
           "multi_cloud_by_population": dict(sorted(by_pop.items())),
           "multi_cloud_percentile_consequences": consequences,
           "n_multi_cloud": len(consequences),
           "n_multi_cloud_with_disjoint_percentiles": len(disjoint),
           "max_percentile_gap_between_containing_groups": max((s["max_gap"] for c in consequences
                                                                for s in c["scores"].values()), default=None),
           "rows": rows}
    (ROOT / "benchmarks" / "results" / "multicloud_benchmark.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("summary", "n_multi_cloud", "n_multi_cloud_with_disjoint_percentiles",
                                          "max_percentile_gap_between_containing_groups", "runtime_s")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
