"""Build the 1000 Genomes reference panels PRSGuard ships (network; needs pysam).

    python -m prsguard.reference.build pca --out data/reference/1000g_pca.npz
    python -m prsguard.reference.build pgs --scoring-files <hmPOS_GRCh37 files...> \
        --out data/reference/1000g_pgs.npz

PCA sites: SNPs assayed on both public 23andMe genomes bundled with ClawBio
(genome-compare/data; only which sites a chip assays is used, never anyone's
genotypes), one per 400 kb bin on autosomes (distance thinning against LD),
then kept if biallelic, non-palindromic and minor allele frequency >= 5% in
the 2,504 1000 Genomes samples. PGS sites: every position of every scoring
file given (GRCh37 harmonised coordinates).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from prsguard.clawbio_env import clawbio_root
from prsguard.reference.panel import Site, fetch_sites, load_samples, save_panel, utc_now

BIN = 400_000
AUTOSOMES = {str(i) for i in range(1, 23)}
MIN_MAF = 0.05
PALINDROMIC = ({"A", "T"}, {"C", "G"})


# hg19/GRCh37 autosome lengths (1000 Genomes phase 3 contigs)
GRCH37_LENGTHS = {1: 249250621, 2: 243199373, 3: 198022430, 4: 191154276, 5: 180915260, 6: 171115067,
                  7: 159138663, 8: 146364022, 9: 141213431, 10: 135534747, 11: 135006516, 12: 133851895,
                  13: 115169878, 14: 107349540, 15: 102531392, 16: 90354753, 17: 81195210, 18: 78077248,
                  19: 59128983, 20: 63025520, 21: 48129895, 22: 51304566}
WINDOW = 20_000


def chip_rsids() -> set[str]:
    """rsIDs assayed on both ClawBio genome-compare 23andMe files (build 36 files: positions NOT used)."""
    data = clawbio_root() / "skills" / "genome-compare" / "data"
    ids = None
    for name in ("manuel_corpas_23andme.txt.gz", "george_church_23andme.txt.gz"):
        with gzip.open(data / name, "rt") as fh:
            got = {line.split("\t", 1)[0] for line in fh if line.startswith("rs")}
        ids = got if ids is None else ids & got
    return ids or set()


ENSEMBL_GRCH37 = "https://grch37.rest.ensembl.org/variation/homo_sapiens"


def chip_candidates(per_bin: int = 2) -> list[str]:
    """Chip rsIDs spread across the genome: <= per_bin per 400 kb bin of their (NCBI36) chip positions.

    The NCBI36 coordinates only spread the choice; every selected rsID is re-located on GRCh37 by Ensembl.
    """
    data = clawbio_root() / "skills" / "genome-compare" / "data"
    common = None
    for name in ("manuel_corpas_23andme.txt.gz", "george_church_23andme.txt.gz"):
        rows = {}
        with gzip.open(data / name, "rt") as fh:
            for line in fh:
                if line.startswith("rs"):
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 3 and parts[1].isdigit() and 1 <= int(parts[1]) <= 22 and parts[2].isdigit():
                        rows[parts[0]] = (int(parts[1]), int(parts[2]))
        common = rows if common is None else {k: v for k, v in common.items() if k in rows}
    bins: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for rsid, (chrom, pos) in (common or {}).items():
        bins.setdefault((chrom, pos // BIN), []).append((pos, rsid))
    return [rsid for _, items in sorted(bins.items()) for _, rsid in sorted(items)[:per_bin]]


def ensembl_grch37(rsids: list[str], batch: int = 200, log=print) -> dict[str, dict]:
    """rsID -> {chrom, pos, alleles} on GRCh37 (Ensembl GRCh37 REST); unmapped or multi-mapped rsIDs dropped."""
    import time

    import requests

    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    out: dict[str, dict] = {}
    for i in range(0, len(rsids), batch):
        ids = rsids[i:i + batch]
        for attempt in range(5):
            try:
                resp = session.post(ENSEMBL_GRCH37, json={"ids": ids}, timeout=120)
                if resp.status_code == 429:
                    time.sleep(float(resp.headers.get("Retry-After", "2")))
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 4:
                    raise
                time.sleep(3 * (attempt + 1))
        for rsid, rec in resp.json().items():
            maps = [m for m in rec.get("mappings") or [] if m.get("assembly_name") == "GRCh37"
                    and str(m.get("seq_region_name")).isdigit() and m.get("start") == m.get("end")]
            if len(maps) == 1:
                m = maps[0]
                out[rec.get("name", rsid)] = {"chrom": str(m["seq_region_name"]), "pos": int(m["start"]),
                                             "alleles": m.get("allele_string", "")}
        if (i // batch) % 10 == 0:
            log(f"  ensembl: {min(i + batch, len(rsids))}/{len(rsids)} looked up, {len(out)} mapped", flush=True)
    return out


def filter_pca(records: list[dict]) -> list[dict]:
    kept, used_bins = [], set()
    for r in records:
        d = r["dosages"]
        valid = d >= 0
        af = d[valid].sum() / (2 * valid.sum()) if valid.any() else 0
        if len(r["ref"]) != 1 or len(r["alt"]) != 1:
            continue
        if min(af, 1 - af) < MIN_MAF or {r["ref"], r["alt"]} in PALINDROMIC:
            continue
        b = (r["chrom"], r["pos"] // BIN)
        if b in used_bins:
            continue
        used_bins.add(b)
        kept.append(r)
    return kept


def scoring_positions(path: Path) -> list[Site]:
    opener = gzip.open if str(path).endswith(".gz") else open
    sites, header = [], None
    with opener(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cells = line.rstrip("\n").split("\t")
            if header is None:
                header = {c.lower(): i for i, c in enumerate(cells)}
                continue
            ci, pi = header.get("hm_chr"), header.get("hm_pos")
            if ci is None or pi is None or pi >= len(cells) or not cells[pi].strip().isdigit():
                continue
            if cells[ci].strip() not in AUTOSOMES:
                continue  # sex chromosomes: hemizygous dosage coding differs; not scored (see harmonize.py)
            sites.append(Site(cells[ci].strip(), int(cells[pi])))
    return sites


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=("pca", "pgs"))
    ap.add_argument("--scoring-files", nargs="*", default=[])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--threads", type=int, default=12)
    args = ap.parse_args(argv)
    samples = load_samples()
    if args.kind == "pca":
        candidates = chip_candidates()
        print(f"PCA: {len(candidates)} chip rsIDs selected for Ensembl GRCh37 lookup", flush=True)
        mapped = ensembl_grch37(candidates)
        sites = [Site(v["chrom"], v["pos"]) for v in mapped.values()]
        by_pos = {(v["chrom"], v["pos"]): (rsid, v["alleles"]) for rsid, v in mapped.items()}
        raw = fetch_sites(sites, threads=args.threads)
        checked = []
        for r in raw:
            rsid, alleles = by_pos.get((r["chrom"], r["pos"]), (None, ""))
            if rsid and {r["ref"], r["alt"]} <= set(alleles.split("/")):
                r["id"] = rsid  # 1000G v5b VCFs carry no IDs; the rsID is Ensembl's, alleles cross-checked
                checked.append(r)
        records = filter_pca(checked)
        meta = {"name": "1000g_pca", "purpose": "fixed projection space for reference placement",
                "selection": {"bin_bp": BIN, "per_bin": 1, "min_maf": MIN_MAF, "palindromic": "excluded",
                              "variant_type": "biallelic SNV, alleles concordant with Ensembl GRCh37",
                              "chip_content": "rsIDs assayed on both ClawBio genome-compare 23andMe files "
                                              "(NCBI36 files; positions re-mapped with Ensembl GRCh37 REST)",
                              "candidates": len(candidates), "ensembl_mapped": len(mapped),
                              "fetched": len(raw), "allele_concordant": len(checked)}}
    else:
        sites = [s for f in args.scoring_files for s in scoring_positions(Path(f))]
        print(f"PGS: {len(set(sites))} positions from {len(args.scoring_files)} scoring files", flush=True)
        records = fetch_sites(sites, threads=args.threads, allow_indels=True)
        meta = {"name": "1000g_pgs", "variant_types": "biallelic SNVs and indels (plain-sequence alleles)",
                "purpose": "empirical reference distributions and scoring calibration",
                "scoring_files": [Path(f).name for f in args.scoring_files]}
    meta.update({"retrieved_at": utc_now(), "vcf_url_template": "ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_"
                                                               "v5b.20130502.genotypes.vcf.gz"})
    saved = save_panel(args.out, records, samples, meta)
    print(f"saved {args.out} ({saved['n_variants']} variants x {saved['n_samples']} samples)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())


ENSEMBL_OVERLAP = "https://grch37.rest.ensembl.org/overlap/region/human/{chrom}:{pos}-{pos}"


def site_rsids(panel_path: Path, scoring_files: list[Path], out: Path, log=print) -> dict:
    """rsID for every PGS panel site: from the scoring files' hm_rsID, else Ensembl GRCh37 overlap lookup
    (single-base variation features whose alleles include the panel REF and ALT). Written with provenance."""
    import time

    import requests

    from prsguard.harmonize import read_scoring_file
    from prsguard.reference.panel import load_panel

    comp = str.maketrans("ACGT", "TGCA")
    pan = load_panel(panel_path)
    known: dict[tuple[str, int], list[tuple[str, set]]] = {}
    for f in scoring_files:
        for v in read_scoring_file(f, "GRCh37").variants:
            if v.rsid and v.chrom and v.pos is not None and v.other:
                known.setdefault((str(v.chrom), int(v.pos)), []).append((v.rsid, {v.effect, v.other}))
    out_map, sources = {}, {"scoring_file": 0, "ensembl_grch37_overlap": 0, "unresolved": 0}
    session = requests.Session()
    for chrom, pos, ref, alt in zip(pan.chrom.tolist(), pan.pos.tolist(), pan.ref.tolist(), pan.alt.tolist()):
        key = f"{chrom}:{pos}:{ref}:{alt}"
        hit = [rs for rs, al in known.get((chrom, pos), []) if al == {ref, alt} or
               (len(ref) == len(alt) == 1 and {a.translate(comp) for a in al} == {ref, alt})]
        if hit:
            out_map[key] = hit[0]
            sources["scoring_file"] += 1
            continue
        if len(ref) != 1 or len(alt) != 1:
            sources["unresolved"] += 1  # indel without a scoring-file rsID: Ensembl indel coordinates differ
            continue
        for attempt in range(5):
            try:
                r = session.get(ENSEMBL_OVERLAP.format(chrom=chrom, pos=pos),
                                params={"feature": "variation"}, headers={"Content-Type": "application/json"},
                                timeout=60)
                if r.status_code == 429:
                    time.sleep(float(r.headers.get("Retry-After", "2")))
                    continue
                r.raise_for_status()
                break
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
        hits = [x for x in r.json() if x.get("id", "").startswith("rs") and x.get("start") == x.get("end") == pos
                and {ref, alt} <= set(x.get("alleles") or [])]
        if len(hits) >= 1:
            out_map[key] = sorted(hits, key=lambda x: int(x["id"][2:]))[0]["id"]
            sources["ensembl_grch37_overlap"] += 1
        else:
            sources["unresolved"] += 1
        time.sleep(0.07)
    doc = {"panel_sha256": pan.meta.get("sha256"), "build": "GRCh37", "retrieved_at": utc_now(),
           "sources": sources, "method": "scoring-file hm_rsID with matching alleles, else (SNVs only) Ensembl "
                                         "GRCh37 /overlap/region variation features at the exact base whose "
                                         "alleles include REF and ALT (lowest rs number if several); keys are "
                                         "chrom:pos:ref:alt", "rsids": out_map}
    out.write_text(json.dumps(doc, indent=1) + "\n")
    log(f"rsIDs: {sources}")
    return doc
