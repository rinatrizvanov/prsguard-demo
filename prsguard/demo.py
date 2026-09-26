"""Demo genomes A-G, derived from PUBLIC 1000 Genomes phase 3 genotypes (open-access, redistributable).

No private data and no invented genotypes: every genotype is the real 1000 Genomes call of the named sample.
What is simulated is only which sites a file contains:

  A  consumer array   sample X, sites of a simulated consumer array (rsIDs assayed on the public 23andMe
                      genomes bundled with ClawBio), 23andMe text format, GRCh37
  B  WGS-like         the same sample X, every site of the PRSGuard reference panels, VCF GRCh37
  C  EUR              a CEU sample, WGS-like VCF
  D  AFR              a YRI sample, WGS-like VCF
  E  admixed          an ASW sample (African American, admixed), WGS-like VCF
  F  AMR              a PEL sample, WGS-like VCF
  G  very thin file   150 array sites of a JPT sample, 23andMe text format

Samples are the first female sample (by 1000 Genomes ID) of each population, so the choice is reproducible and
not tuned to a result. Demo people are themselves in the reference panel; PRSGuard detects and excludes them from
every reference comparison (prsguard.reference.projection.self_matches).

    python -m prsguard.demo make      # writes data/demo/
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

from prsguard.clawbio_env import REPO_ROOT
from prsguard.reference.build import GRCH37_LENGTHS, chip_rsids
from prsguard.reference.panel import load_panel

DEMO_DIR = REPO_ROOT / "data" / "demo"
THIN_SITES = 150
SEED = 20260926
PROVENANCE = "Public 1000 Genomes phase 3 genotypes (open access)"
CASES = [
    {"id": "A", "pop": "GBR", "kind": "array", "title": "Sparse consumer array",
     "description": "Consumer-array-like file: the sites a direct-to-consumer array assays."},
    {"id": "B", "pop": "GBR", "kind": "wgs", "same_as": "A", "title": "Same person, WGS-like file",
     "description": "The same individual as case A with every site of the reference panels."},
    {"id": "C", "pop": "CEU", "kind": "wgs", "title": "European reference placement",
     "description": "An individual of the CEU population (Utah residents with Northern/Western European "
                    "ancestry)."},
    {"id": "D", "pop": "YRI", "kind": "wgs", "title": "African reference placement",
     "description": "An individual of the YRI population (Yoruba in Ibadan, Nigeria)."},
    {"id": "E", "pop": "ASW", "kind": "wgs", "title": "Admixed individual",
     "description": "An individual of the ASW population (African ancestry in the Southwest US)."},
    {"id": "F", "pop": "PEL", "kind": "wgs", "title": "Latin American reference placement",
     "description": "An individual of the PEL population (Peruvians in Lima, Peru)."},
    {"id": "G", "pop": "JPT", "kind": "thin", "title": "Very thin file",
     "description": f"Only {THIN_SITES} array sites (e.g. a truncated or filtered export)."},
]


def _samples_by_pop(panel) -> dict[str, str]:
    out = {}
    for s, p, sex in sorted(zip(panel.samples.tolist(), panel.pop.tolist(), panel.sex.tolist())):
        if sex == "female" and p not in out:
            out[p] = s
    return out


def _merged_sites(pca, pgs, rsids: dict[str, str]):
    """All panel records keyed by (chrom, pos, ref, alt): an SNV and an indel may share a position."""
    sites = {}
    for pan in (pca, pgs):
        for i in range(len(pan.pos)):
            key = (str(pan.chrom[i]), int(pan.pos[i]), str(pan.ref[i]), str(pan.alt[i]))
            rid = str(pan.ids[i]) if str(pan.ids[i]).startswith("rs") else rsids.get(":".join(map(str, key)))
            if key not in sites:
                sites[key] = {"rsid": rid, "ref": key[2], "alt": key[3], "panel": pan, "row": i}
    return dict(sorted(sites.items(), key=lambda kv: (int(kv[0][0]), kv[0][1], kv[0][2], kv[0][3])))


def _gt(site: dict, col: int) -> int:
    return int(site["panel"].dosages[site["row"], col])


def write_vcf(path: Path, sample: str, sites: dict, col_of: dict, header_note: str) -> None:
    with gzip.open(path, "wt") as fh:
        fh.write("##fileformat=VCFv4.2\n##reference=GRCh37\n")
        fh.write(f"##source=PRSGuard demo genome; {header_note}\n")
        for c in range(1, 23):
            fh.write(f"##contig=<ID={c},length={GRCH37_LENGTHS[c]}>\n")
        fh.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + sample + "\n")
        for (chrom, pos, _, _), s in sites.items():
            d = _gt(s, col_of[id(s["panel"])])
            gt = {0: "0/0", 1: "0/1", 2: "1/1"}.get(d, "./.")
            fh.write(f"{chrom}\t{pos}\t{s['rsid'] or '.'}\t{s['ref']}\t{s['alt']}\t.\tPASS\t.\tGT\t{gt}\n")


def write_23andme(path: Path, sites: dict, col_of: dict, header_note: str) -> None:
    with open(path, "w") as fh:
        fh.write(f"# PRSGuard demo genome - {header_note}\n")
        fh.write("# NOT a real 23andMe file: 23andMe-style text layout only.\n")
        fh.write("# Coordinates: reference human assembly build 37 (GRCh37).\n")
        fh.write("# rsid\tchromosome\tposition\tgenotype\n")
        for (chrom, pos, _, _), s in sites.items():
            d = _gt(s, col_of[id(s["panel"])])
            gt = {0: s["ref"] * 2, 1: "".join(sorted(s["ref"] + s["alt"])), 2: s["alt"] * 2}.get(d, "--")
            fh.write(f"{s['rsid']}\t{chrom}\t{pos}\t{gt}\n")


def make(out_dir: Path = DEMO_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pca = load_panel(REPO_ROOT / "data" / "reference" / "1000g_pca.npz")
    pgs = load_panel(REPO_ROOT / "data" / "reference" / "1000g_pgs.npz")
    assert list(pca.samples) == list(pgs.samples)
    rsids = json.loads((REPO_ROOT / "data" / "reference" / "1000g_pgs_rsids.json").read_text())["rsids"]
    sites = _merged_sites(pca, pgs, rsids)
    chip = chip_rsids()
    # Arrays: SNVs only (consumer arrays report indels as I/D codes that cannot be matched to scoring alleles),
    # one record per rsID.
    array_sites, seen = {}, set()
    for k, v in sites.items():
        if v["rsid"] in chip and len(v["ref"]) == 1 and len(v["alt"]) == 1 and v["rsid"] not in seen:
            array_sites[k] = v
            seen.add(v["rsid"])
    pick = _samples_by_pop(pca)
    rng = np.random.default_rng(SEED)
    thin_keys = sorted(rng.choice(len(array_sites), size=THIN_SITES, replace=False))
    keys = list(array_sites)
    thin_sites = {keys[i]: array_sites[keys[i]] for i in thin_keys}
    cases = []
    for case in CASES:
        sample = pick[case["pop"]]
        j = int(np.where(pca.samples == sample)[0][0])
        col_of = {id(pca): j, id(pgs): j}
        superpop = str(pca.superpop[j])
        note = (f"{PROVENANCE}, sample {sample} ({case['pop']}, {superpop}); ")
        if case["kind"] == "wgs":
            fname = f"case_{case['id']}_{sample}_wgs_like.vcf.gz"
            write_vcf(out_dir / fname, sample, sites, col_of, note + "all sites of the PRSGuard reference panels "
                      "(WGS-like subset, not a whole genome)")
            n, fmt, derivation = len(sites), "VCF (GRCh37)", "all reference-panel sites (WGS-like subset)"
        elif case["kind"] == "array":
            fname = f"case_{case['id']}_{sample}_array.txt"
            write_23andme(out_dir / fname, array_sites, col_of, note + "sites of a SIMULATED consumer array")
            n, fmt, derivation = len(array_sites), "23andMe-style text (GRCh37)", (
                "simulated array: reference-panel sites whose rsID is assayed on the public 23andMe genomes "
                "bundled with ClawBio")
        else:
            fname = f"case_{case['id']}_{sample}_thin.txt"
            write_23andme(out_dir / fname, thin_sites, col_of, note + f"{THIN_SITES} randomly chosen array sites")
            n, fmt, derivation = len(thin_sites), "23andMe-style text (GRCh37)", (
                f"{THIN_SITES} array sites chosen with seed {SEED}")
        cases.append({"id": case["id"], "title": case["title"], "description": case["description"],
                      "file": fname, "sample": sample, "population": case["pop"], "superpopulation": superpop,
                      "sex": "female", "format": fmt, "n_sites": n, "derivation": derivation,
                      "provenance": PROVENANCE + f", sample {sample}", "synthetic": False,
                      "same_individual_as": case.get("same_as"),
                      "trait": "breast cancer",
                      "label": f"PUBLIC 1000 GENOMES SAMPLE {sample} - site content "
                               + ("SIMULATED" if case["kind"] != "wgs" else "restricted to panel sites")})
    manifest = {"schema": "prsguard.demo_cases.v1", "seed": SEED, "note": __doc__.split("\n\n")[1],
                "cases": cases}
    (out_dir / "cases.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return cases


if __name__ == "__main__":
    if sys.argv[1:] != ["make"]:
        sys.exit("usage: python -m prsguard.demo make")
    for c in make():
        print(c["id"], c["file"], c["n_sites"], c["label"])
