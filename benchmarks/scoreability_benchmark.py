"""Scoreability calibration: what does losing variants do to a PGS, measured in the 1000 Genomes panel?

For each candidate score and each core reference group, the FULL score (every panel-available variant) is compared
with REDUCED scores computed after masking variants:

  array      : keep SNVs whose rsID is assayed on the public 23andMe genomes bundled with ClawBio, excluding
               palindromic SNVs (what PRSGuard can match from a consumer array)
  random_f   : keep a random fraction f of variants (10 replicates per f)
  drop_top_k : drop the k% largest-|weight| variants (adversarial)

Metrics per mask: Pearson r(full, reduced) (= the retained share of the per-SD association), Spearman rho,
|percentile(full) - percentile(reduced)| within the group (median, 95th), same-decile agreement, and recovery of
the full score's top decile. Fractions of variants and of |weight| retained are reported to show that they do not
determine r.

    python benchmarks/scoreability_benchmark.py   # writes benchmarks/results/scoreability_benchmark.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prsguard.harmonize import PALINDROMIC, read_scoring_file  # noqa: E402
from prsguard.reference.build import chip_rsids  # noqa: E402
from prsguard.reference.distribution import panel_rows, score_panel  # noqa: E402
from prsguard.reference.panel import load_panel  # noqa: E402
from prsguard.reference.projection import GROUPS, core_mask  # noqa: E402

SEED = 20260926
SCORES = ("PGS000004", "PGS001804", "PGS001336", "PGS000001")
FRACTIONS = (0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.3)
DROP_TOP = (0.05, 0.1, 0.2)
REPLICATES = 10


def pct(x: np.ndarray) -> np.ndarray:
    return 100 * (rankdata(x) - 0.5) / len(x)


def icc_a1(x: np.ndarray, y: np.ndarray) -> float:
    """Two-way random, absolute agreement, single measure ICC(A,1) (McGraw & Wong 1996)."""
    data = np.column_stack([x, y])
    n, k = data.shape
    grand = data.mean()
    msr = k * np.sum((data.mean(1) - grand) ** 2) / (n - 1)
    msc = n * np.sum((data.mean(0) - grand) ** 2) / (k - 1)
    sse = np.sum((data - data.mean(1, keepdims=True) - data.mean(0, keepdims=True) + grand) ** 2)
    mse = sse / ((n - 1) * (k - 1))
    return float((msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n))


def metrics(full: np.ndarray, red: np.ndarray) -> dict:
    if np.std(red) == 0:
        return {"r": None}
    zf, zr = (full - full.mean()) / full.std(ddof=1), (red - red.mean()) / red.std(ddof=1)
    diff = zr - zf
    pf, pr = pct(full), pct(red)
    err = np.abs(pf - pr)
    top_f, top_r = pf >= 90, pr >= 90
    return {"r": round(float(np.corrcoef(full, red)[0, 1]), 4), "spearman": round(float(spearmanr(full, red)[0]), 4),
            "icc_a1_standardized": round(icc_a1(zf, zr), 4),
            "bland_altman_z": {"bias": round(float(diff.mean()), 4),
                               "loa95": [round(float(diff.mean() - 1.96 * diff.std(ddof=1)), 3),
                                         round(float(diff.mean() + 1.96 * diff.std(ddof=1)), 3)]},
            "pct_err_median": round(float(np.median(err)), 2), "pct_err_p95": round(float(np.percentile(err, 95)), 2),
            "same_decile": round(float(np.mean(np.floor(pf / 10) == np.floor(pr / 10))), 3),
            "top_decile_recovered": round(float((top_f & top_r).sum() / max(top_f.sum(), 1)), 3)}


def main() -> int:
    panel = load_panel(ROOT / "data" / "reference" / "1000g_pgs.npz")
    rsids = json.loads((ROOT / "data" / "reference" / "1000g_pgs_rsids.json").read_text())["rsids"]
    chip = chip_rsids()
    cmask, cgroups = core_mask(panel)
    rng = np.random.default_rng(SEED)
    rows, group_rows = [], []
    for pid in SCORES:
        score = read_scoring_file(ROOT / "data" / "catalog_snapshot" / pid / f"{pid}_hmPOS_GRCh37.txt.gz", "GRCh37")
        prow, eff_alt = panel_rows(panel, score)
        w = np.array([v.weight for v in score.variants])
        avail = prow >= 0
        absw = np.abs(w)
        site_rsid = []
        for v in score.variants:
            r = prow[v.idx]
            key = f"{panel.chrom[r]}:{panel.pos[r]}:{panel.ref[r]}:{panel.alt[r]}" if r >= 0 else None
            site_rsid.append(v.rsid or rsids.get(key))
        is_snv = np.array([len(v.effect) == 1 and len(v.other or "") == 1 for v in score.variants])
        palin = np.array([{v.effect, v.other} in PALINDROMIC for v in score.variants])
        array_keep = avail & is_snv & ~palin & np.array([bool(r) and r in chip for r in site_rsid])
        masks = [("array", 0, array_keep)]
        for f in FRACTIONS:
            idx = np.where(avail)[0]
            for rep in range(REPLICATES):
                keep = np.zeros_like(avail)
                keep[rng.choice(idx, size=max(1, int(round(f * len(idx)))), replace=False)] = True
                masks.append((f"random_{f}", rep, keep))
        order = np.argsort(-absw * avail)
        for k in DROP_TOP:
            keep = avail.copy()
            keep[order[:int(round(k * avail.sum()))]] = False
            masks.append((f"drop_top_{k}", 0, keep))
        eur = score_panel(panel, prow, eff_alt, w, avail, cmask & (cgroups == "EUR"))
        for g in GROUPS:
            vals = score_panel(panel, prow, eff_alt, w, avail, cmask & (cgroups == g))
            group_rows.append({"pgs_id": pid, "group": g, "n": int(len(vals)),
                               "mean_in_eur_sd": round(float((vals.mean() - eur.mean()) / eur.std(ddof=1)), 3),
                               "sd_ratio_to_eur": round(float(vals.std(ddof=1) / eur.std(ddof=1)), 3),
                               "share_above_eur_p90": round(float(np.mean(vals > np.percentile(eur, 90))), 3)})
        for g in GROUPS:
            gm = cmask & (cgroups == g)
            full = score_panel(panel, prow, eff_alt, w, avail, gm)
            for name, rep, keep in masks:
                red = score_panel(panel, prow, eff_alt, w, keep, gm)
                rows.append({"pgs_id": pid, "group": g, "mask": name, "replicate": rep,
                             "fraction_variants": round(float(keep.sum() / avail.sum()), 4),
                             "fraction_abs_weight": round(float(absw[keep].sum() / absw[avail].sum()), 4),
                             **metrics(full, red)})
        print(pid, "done", flush=True)
    # Calibration table: consequences as a function of r (pooled over scores, groups, masks).
    rs = np.array([r["r"] for r in rows if r.get("r") is not None])
    bands = [(0.99, 1.01), (0.97, 0.99), (0.95, 0.97), (0.90, 0.95), (0.85, 0.90), (0.80, 0.85), (0.7, 0.8),
             (0.0, 0.7)]
    table = []
    for lo, hi in bands:
        sel = [r for r in rows if r.get("r") is not None and lo <= r["r"] < hi]
        if not sel:
            continue
        table.append({"r_band": [lo, min(hi, 1.0)], "n": len(sel),
                      "pct_err_median": round(float(np.median([r["pct_err_median"] for r in sel])), 2),
                      "pct_err_p95_median": round(float(np.median([r["pct_err_p95"] for r in sel])), 2),
                      "same_decile_median": round(float(np.median([r["same_decile"] for r in sel])), 3),
                      "top_decile_recovered_median": round(float(np.median([r["top_decile_recovered"]
                                                                            for r in sel])), 3),
                      "fraction_variants_range": [min(r["fraction_variants"] for r in sel),
                                                  max(r["fraction_variants"] for r in sel)]})
    array_rows = [r for r in rows if r["mask"] == "array"]
    out = {"benchmark": "scoreability masking in 1000 Genomes core groups", "seed": SEED,
           "panel_sha256": panel.meta.get("sha256"), "scores": SCORES, "n_rows": len(rows),
           "r_consequence_table": table, "array_mask": array_rows, "group_distributions": group_rows, "rows": rows,
           "note": "r is measured against the panel-available score; see docs/calibration.md"}
    (ROOT / "benchmarks" / "results" / "scoreability_benchmark.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(table, indent=1))
    for r in array_rows:
        print(r["pgs_id"], r["group"], r["fraction_variants"], r["fraction_abs_weight"], r["r"], r["pct_err_p95"])
    _ = rs
    return 0


if __name__ == "__main__":
    sys.exit(main())
