"""Calibration evidence for the build rule (BUILD_AGREEMENT) and the allele rule (max_mismatch_fraction).

Real public files only: the seven 1000 Genomes demo genomes (GRCh37) and the two public 23andMe genomes bundled
with ClawBio (NCBI36). For each file: anchor-position agreement with GRCh37 and GRCh38, and, for each candidate
score, the fraction of located variants whose alleles cannot be reconciled. A perturbation arm corrupts a known
fraction of genotype calls (replacing both alleles with a base outside the site's alleles) to show how the
mismatch fraction responds.

    python benchmarks/harmonisation_benchmark.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prsguard.clawbio_env import clawbio_root  # noqa: E402
from prsguard.genotypes import Call, load_genotypes, resolve_build  # noqa: E402
from prsguard.harmonize import harmonise, read_scoring_file  # noqa: E402
from prsguard.reference.panel import load_panel  # noqa: E402

SCORES = ("PGS000004", "PGS001804", "PGS001336", "PGS000001")
SEED = 20260926


def mismatch_fraction(h) -> float | None:
    c = h.counts
    located = c["matched"] + c["matched_flipped"] + c["allele_mismatch"] + c["palindromic_excluded"]
    return round(c["allele_mismatch"] / located, 4) if located else None


def main() -> int:
    pca = load_panel(ROOT / "data" / "reference" / "1000g_pca.npz")
    a37 = {str(i): (str(c), int(p)) for i, c, p in zip(pca.ids, pca.chrom, pca.pos)}
    a38 = json.loads((ROOT / "data" / "reference" / "1000g_pca_grch38_positions.json").read_text())["positions"]
    files = [(p, None) for p in sorted((ROOT / "data" / "demo").glob("case_*"))]
    cb = clawbio_root() / "skills" / "genome-compare" / "data"
    files += [(cb / "manuel_corpas_23andme.txt.gz", "NCBI36"), (cb / "george_church_23andme.txt.gz", "NCBI36")]
    scores = {pid: read_scoring_file(ROOT / "data" / "catalog_snapshot" / pid / f"{pid}_hmPOS_GRCh37.txt.gz",
                                     "GRCh37") for pid in SCORES}
    rng = np.random.default_rng(SEED)
    rows = []
    for path, declared in files:
        gs = resolve_build(load_genotypes(path), a37, declared, a38)
        ev = gs.build_evidence
        row = {"file": path.name, "build": gs.build, "grch37_agreement": ev["grch37_position_agreement"],
               "grch38_agreement": ev["grch38_position_agreement"], "anchors_checked": ev["grch37_rsid_sites_checked"],
               "mismatch": {}}
        for pid, sf in scores.items():
            row["mismatch"][pid] = mismatch_fraction(harmonise(sf, gs))
        rows.append(row)
    # Perturbation arm on the WGS-like demo genome (case B): corrupt a fraction of calls.
    base = load_genotypes(next((ROOT / "data" / "demo").glob("case_B_*")))
    base.build = "GRCh37"
    perturb = []
    for frac in (0.0, 0.02, 0.05, 0.10, 0.2, 0.5):
        calls = []
        for c in base.calls:
            if rng.random() < frac and c.site_alleles:
                bad = next(b for b in "ACGT" if b not in c.site_alleles)
                calls.append(Call(c.rsid, c.chrom, c.pos, (bad, bad), c.site_alleles))
            else:
                calls.append(c)
        gs = type(base)(path=base.path, fmt=base.fmt, sha256=base.sha256, calls=calls, declared_build="GRCh37",
                        build="GRCh37")
        gs.index()
        perturb.append({"corrupted_fraction": frac,
                        "mismatch": {pid: mismatch_fraction(harmonise(sf, gs)) for pid, sf in scores.items()}})
    out = {"benchmark": "build agreement and allele reconciliation on real public files", "seed": SEED,
           "files": rows, "perturbation": perturb}
    (ROOT / "benchmarks" / "results" / "harmonisation_benchmark.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
