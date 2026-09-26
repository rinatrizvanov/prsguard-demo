"""Held-out benchmark and calibration of reference placement (prsguard.reference.projection).

Every tested individual is removed from the reference before fitting (leave-one-out), so no sample is placed
against a cloud that contains itself.

Experiments
  core      : N_CORE random individuals from every core 1000G population, all projection sites.
  admixed   : N_ADMIXED random individuals from ASW, ACB, MXL, PUR, CLM (never used to define axes).
  sparsity  : N_SPARSE core individuals per group with random subsets of 50..3200 sites (min_sites calibration).

    python benchmarks/ancestry_benchmark.py            # writes benchmarks/results/ancestry_benchmark.json
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

from prsguard.reference import projection as P  # noqa: E402
from prsguard.reference.panel import load_panel  # noqa: E402

SEED = 20260926
N_CORE = 8          # per core population (21 populations)
N_ADMIXED = 25      # per admixed population
N_SPARSE = 6        # per core group, per site count
SITE_COUNTS = (50, 100, 200, 400, 800, 1600, 3200)
BOOTSTRAP = 50
PANEL = ROOT / "data" / "reference" / "1000g_pca.npz"
_panel = None


def _get_panel():
    global _panel
    if _panel is None:
        _panel = load_panel(PANEL)
    return _panel


def _one(job):
    kind, j, n_sites, seed = job
    panel = _get_panel()
    t = panel.dosages[:, j].astype(float)
    if n_sites:
        rng = np.random.default_rng(seed)
        keep = rng.choice(len(t), size=n_sites, replace=False)
        m = np.full(len(t), np.nan)
        m[keep] = t[keep]
        t = m
    policy = P.PlacementPolicy(min_sites=1, bootstrap=BOOTSTRAP)   # min_sites is what is being calibrated
    out = P.place_vector(panel, t, policy, exclude_samples={str(panel.samples[j])}, with_plot=False)
    return {"kind": kind, "sample": str(panel.samples[j]), "pop": str(panel.pop[j]),
            "superpop": str(panel.superpop[j]), "n_sites": int(np.sum(~np.isnan(t))), "status": out["status"],
            "nearest": out.get("nearest_reference"), "stability": out.get("placement_stability"),
            "d2_nearest": (out.get("mahalanobis_d2") or {}).get(out.get("nearest_reference")),
            "admixture": out.get("supervised_admixture_context")}


def main() -> int:
    panel = _get_panel()
    rng = np.random.default_rng(SEED)
    group_of = {p: g for g, pops in P.CORE_POPS.items() for p in pops}
    jobs = []
    for pop in sorted(set(panel.pop)):
        idx = np.where(panel.pop == pop)[0]
        if pop in group_of:
            jobs += [("core", int(j), None, 0) for j in rng.choice(idx, size=min(N_CORE, len(idx)), replace=False)]
        elif pop in P.ADMIXED_POPS:
            jobs += [("admixed", int(j), None, 0) for j in rng.choice(idx, size=min(N_ADMIXED, len(idx)),
                                                                      replace=False)]
    for pops in P.CORE_POPS.values():
        idx = np.where(np.isin(panel.pop, pops))[0]
        for n in SITE_COUNTS:
            for j in rng.choice(idx, size=N_SPARSE, replace=False):
                jobs.append(("sparsity", int(j), n, int(rng.integers(1 << 31))))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, jobs, chunksize=4))
    for r in rows:
        r["expected_group"] = group_of.get(r["pop"])
    summary = summarise(rows)
    out = {"benchmark": "reference placement, leave-one-out", "panel_sha256": panel.meta.get("sha256"),
           "seed": SEED, "bootstrap": BOOTSTRAP, "k_pcs": P.K, "cloud_quantile": P.CLOUD_QUANTILE,
           "ref_per_group": P.REF_PER_GROUP, "n_jobs": len(jobs), "runtime_s": round(time.time() - t0, 1),
           "summary": summary, "rows": rows}
    dest = ROOT / "benchmarks" / "results" / "ancestry_benchmark.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


def summarise(rows: list[dict]) -> dict:
    s: dict = {}
    core = [r for r in rows if r["kind"] == "core"]
    s["core"] = {}
    for g in P.GROUPS:
        rs = [r for r in core if r["expected_group"] == g]
        s["core"][g] = {"n": len(rs), "resolved_correct": sum(r["status"] == "RESOLVED" and r["nearest"] == g
                                                               for r in rs),
                        "resolved_wrong": sum(r["status"] == "RESOLVED" and r["nearest"] != g for r in rs),
                        "intermediate": sum(r["status"] == "INTERMEDIATE" for r in rs),
                        "unstable": sum(r["status"] == "UNSTABLE" for r in rs)}
    s["admixed"] = {}
    for pop in P.ADMIXED_POPS:
        rs = [r for r in rows if r["kind"] == "admixed" and r["pop"] == pop]
        by = {}
        for r in rs:
            key = r["status"] + ("" if r["status"] != "RESOLVED" else f":{r['nearest']}")
            by[key] = by.get(key, 0) + 1
        maxq = [max(r["admixture"].values()) for r in rs]
        s["admixed"][pop] = {"n": len(rs), "outcomes": by,
                             "median_max_admixture_component": round(float(np.median(maxq)), 3) if maxq else None,
                             "resolved_max_component": sorted(round(max(r["admixture"].values()), 3)
                                                              for r in rs if r["status"] == "RESOLVED")}
    s["sparsity"] = {}
    for n in SITE_COUNTS:
        rs = [r for r in rows if r["kind"] == "sparsity" and r["n_sites"] == n]
        res = [r for r in rs if r["status"] == "RESOLVED"]
        s["sparsity"][str(n)] = {"n": len(rs), "resolved": len(res),
                                 "resolved_correct": sum(r["nearest"] == r["expected_group"] for r in res),
                                 "resolved_wrong": sum(r["nearest"] != r["expected_group"] for r in res),
                                 "median_stability": round(float(np.median([r["stability"] for r in rs])), 3)}
    return s


if __name__ == "__main__":
    sys.exit(main())
