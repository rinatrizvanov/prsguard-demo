"""Genotype input: parsing and genome-build resolution.

Consumer-array text files (23andMe, AncestryDNA, MyHeritage) are parsed with ClawBio's shared parser
(``clawbio.common.parsers``). VCFs are parsed here because the shared parser keeps only rows that carry an rsID,
and position-only VCF rows are needed for PGS files without rsIDs.

Genome build is never assumed. It is taken from the file header when declared (23andMe "build 36/37", VCF
``##reference``/contig lengths) and checked against an independent coordinate source (GRCh37 positions of
rsIDs in the 1000 Genomes projection panel). Build resolution returns GRCh37, GRCh38, NCBI36 or UNRESOLVED
with the evidence used.
"""

from __future__ import annotations

import gzip
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from prsguard.clawbio_env import clawbio_root

GRCH37_CHR1 = 249250621
GRCH38_CHR1 = 248956422
NCBI36_CHR1 = 247249719
AUTOSOMES = {str(i) for i in range(1, 23)}
# A build is confirmed when >= this fraction of informative rsIDs sit at its coordinates and the alternative
# build explains <= the complement. Correct and wrong builds are bimodal (see docs/calibration.md: ~99-100% vs
# ~0-3% agreement on real files), so the rule is insensitive to the exact cut-offs.
BUILD_AGREEMENT = 0.90
MIN_BUILD_SITES = 20


@dataclass
class Call:
    rsid: str | None
    chrom: str
    pos: int | None
    alleles: tuple[str, ...]   # called alleles, e.g. ("A", "G"); () = no call
    site_alleles: tuple[str, ...] | None = None   # VCF REF + ALTs of the record; None for array text files


@dataclass
class GenotypeSet:
    path: str
    fmt: str
    sha256: str
    calls: list[Call]
    declared_build: str | None
    build: str = "UNRESOLVED"
    build_evidence: dict = field(default_factory=dict)
    by_rsid: dict[str, list[int]] = field(default_factory=dict)
    by_pos: dict[tuple[str, int], list[int]] = field(default_factory=dict)

    def index(self) -> None:
        self.by_rsid, self.by_pos = {}, {}
        for i, c in enumerate(self.calls):
            if c.rsid:
                self.by_rsid.setdefault(c.rsid, []).append(i)
            if c.pos is not None:
                self.by_pos.setdefault((c.chrom, c.pos), []).append(i)

    @property
    def n_called(self) -> int:
        return sum(1 for c in self.calls if c.alleles)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_chrom(c: str) -> str:
    c = str(c).strip()
    return c[3:] if c.lower().startswith("chr") else c


def _open(path: Path):
    return gzip.open(path, "rt", errors="replace") if str(path).endswith(".gz") else open(path, errors="replace")


def _declared_text_build(path: Path) -> str | None:
    with _open(path) as fh:
        for _, line in zip(range(60), fh):
            if not line.startswith("#"):
                break
            low = line.lower()
            if re.search(r"build\s*36|ncbi\s*36|hg18", low):
                return "NCBI36"
            if re.search(r"build\s*37|grch37|hg19", low):
                return "GRCh37"
            if re.search(r"build\s*38|grch38|hg38", low):
                return "GRCh38"
    return None


class GenotypeInputError(ValueError):
    """The genotype file cannot be read unambiguously (e.g. a multi-sample VCF without a chosen sample)."""


def _gt_alleles(fmt: str, sample_field: str, table: list[str]) -> tuple[str, ...]:
    """Called alleles of one sample: GT is located by name in FORMAT (it need not be the first key)."""
    keys = fmt.split(":")
    if "GT" not in keys:
        return ()
    values = sample_field.split(":")
    gi = keys.index("GT")
    if gi >= len(values):          # trailing FORMAT fields may be dropped (VCF 4.x): GT absent = no call
        return ()
    idx = re.split(r"[/|]", values[gi])
    if not idx or not all(i.isdigit() for i in idx) or not all(int(i) < len(table) for i in idx):
        return ()                  # "./.", ".", malformed or out-of-range allele index: no call
    return tuple(table[int(i)] for i in idx)


def _parse_vcf(path: Path, sample: str | None = None) -> tuple[list[Call], str | None]:
    """Parse a single-sample VCF, or the explicitly named ``sample`` of a multi-sample VCF.

    A multi-sample VCF without ``sample`` is rejected: silently scoring the first sample column could analyse
    the wrong person.
    """
    calls, declared = [], None
    col: int | None = None
    with _open(path) as fh:
        for line in fh:
            if line.startswith("##"):
                low = line.lower()
                m = re.match(r"##contig=<id=(?:chr)?1,.*length=(\d+)", low)
                if m:
                    declared = {GRCH37_CHR1: "GRCh37", GRCH38_CHR1: "GRCh38", NCBI36_CHR1: "NCBI36"}.get(
                        int(m.group(1)), declared)
                elif low.startswith("##reference") and declared is None:
                    declared = ("GRCh38" if re.search(r"grch38|hg38", low) else
                                "GRCh37" if re.search(r"grch37|hg19|b37|hs37d5", low) else None)
                continue
            if line.startswith("#"):
                if line.startswith("#CHROM"):
                    col = _sample_column(line.rstrip("\n").split("\t")[9:], sample, path)
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 10:
                continue
            if col is None:        # no #CHROM header: decide from the first record
                col = _sample_column([f"column {i + 10}" for i in range(len(cols) - 9)], sample, path)
            ref, alts = cols[3].upper(), cols[4].upper().split(",")
            alleles = _gt_alleles(cols[8], cols[col] if col < len(cols) else "", [ref] + alts)
            rsid = cols[2] if cols[2].startswith("rs") else None
            calls.append(Call(rsid, _norm_chrom(cols[0]), int(cols[1]) if cols[1].isdigit() else None, alleles,
                              (ref, *alts)))
    return calls, declared


def _sample_column(samples: list[str], sample: str | None, path: Path) -> int:
    if sample is not None:
        if sample not in samples:
            raise GenotypeInputError(f"sample {sample!r} not found in {path.name} "
                                     f"(samples: {', '.join(samples[:10])})")
        return 9 + samples.index(sample)
    if len(samples) != 1:
        raise GenotypeInputError(
            f"{path.name} has {len(samples)} sample columns; PRSGuard analyses one person. Choose one with "
            f"--sample (e.g. --sample {samples[0] if samples else 'NAME'}).")
    return 9


def _parse_array(path: Path) -> tuple[list[Call], str]:
    clawbio_root()
    from clawbio.common.parsers import detect_format, parse_genetic_file

    fmt = detect_format(path)
    records = parse_genetic_file(str(path), fmt=fmt)
    calls = []
    for rsid, rec in records.items():
        gt = (rec.genotype or "").upper()
        alleles = tuple(gt) if gt and all(ch in "ACGT" for ch in gt) else ()
        pos = int(rec.pos) if str(rec.pos).isdigit() else None
        calls.append(Call(rsid if rsid.startswith("rs") else None, _norm_chrom(rec.chrom), pos, alleles))
    return calls, fmt


def load_genotypes(path: str | Path, sample: str | None = None) -> GenotypeSet:
    path = Path(path)
    is_vcf = ".vcf" in path.name.lower()
    if sample is not None and not is_vcf:
        raise GenotypeInputError("--sample applies only to VCF input")
    if is_vcf:
        calls, declared = _parse_vcf(path, sample)
        fmt = "vcf"
    else:
        calls, fmt = _parse_array(path)
        declared = _declared_text_build(path)
    gs = GenotypeSet(path=path.name, fmt=fmt, sha256=_sha256(path), calls=calls, declared_build=declared)
    gs.index()
    return gs


def _agreement(gs: GenotypeSet, anchors: dict[str, tuple[str, int]] | None) -> tuple[int, float | None]:
    informative = agree = 0
    for rsid, (chrom, pos) in (anchors or {}).items():
        for i in gs.by_rsid.get(rsid, []):
            c = gs.calls[i]
            if c.pos is None or c.chrom not in AUTOSOMES:
                continue
            informative += 1
            agree += int(c.chrom == str(chrom) and c.pos == int(pos))
    return informative, (agree / informative if informative else None)


def resolve_build(gs: GenotypeSet, grch37_positions: dict[str, tuple[str, int]],
                  user_declared: str | None = None,
                  grch38_positions: dict[str, tuple[str, int]] | None = None) -> GenotypeSet:
    """Decide the build from declarations (file header, user) and rsID anchor positions on GRCh37 (and GRCh38).

    A build is confirmed empirically when >= BUILD_AGREEMENT of >= MIN_BUILD_SITES anchor rsIDs sit at its
    coordinates. When the anchors refute every build they cover, or there are too few anchors, the declared build
    is used only if the declarations are unambiguous (and not refuted); otherwise UNRESOLVED. Never guessed.
    """
    n37, f37 = _agreement(gs, grch37_positions)
    n38, f38 = _agreement(gs, grch38_positions) if grch38_positions else (0, None)
    declared = {d for d in (gs.declared_build, user_declared) if d}
    evidence = {"header_declared": gs.declared_build, "user_declared": user_declared,
                "grch37_rsid_sites_checked": n37, "grch37_position_agreement": None if f37 is None else round(f37, 4),
                "grch38_rsid_sites_checked": n38, "grch38_position_agreement": None if f38 is None else round(f38, 4),
                "rule": f"a build is confirmed if >= {BUILD_AGREEMENT:.0%} of >= {MIN_BUILD_SITES} anchor rsIDs agree "
                        f"and refuted if <= {1 - BUILD_AGREEMENT:.0%}; otherwise the declared build if unambiguous "
                        "and not refuted"}
    if len(declared) > 1:
        evidence["declaration_conflict"] = sorted(declared)
    refuted = set()
    confirmed = None
    for build, n, f in (("GRCh37", n37, f37), ("GRCh38", n38, f38)):
        if n >= MIN_BUILD_SITES and f is not None:
            if f >= BUILD_AGREEMENT:
                confirmed = build
            elif f <= 1 - BUILD_AGREEMENT:
                refuted.add(build)
    one = next(iter(declared)) if len(declared) == 1 else None
    if confirmed:
        build = confirmed
        evidence["method"] = "empirical (rsID anchor positions)" + (" + declaration" if confirmed in declared else "")
        if declared - {confirmed}:
            evidence["conflict"] = f"declared {sorted(declared)}, positions agree with {confirmed}"
    elif one and one not in refuted:
        build = one
        evidence["method"] = (f"declared {one}; " + (f"anchors refute {sorted(refuted)}" if refuted else
                                                    "too few anchor rsIDs to check"))
    else:
        build = "UNRESOLVED"
        evidence["method"] = ("declared build refuted by anchor positions" if one in refuted else
                              "no unambiguous declaration and no build confirmed by anchor positions")
    gs.build, gs.build_evidence = build, evidence
    return gs
