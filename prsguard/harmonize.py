"""Harmonise a PGS Catalog scoring file against one genotype set and compute the raw score.

Matching (never silent): a scoring variant is matched by rsID when both sides carry it (and, if the genotype
build is known, only if the positions agree), otherwise by chromosome:position when the genotype build equals
the scoring file's build. Called alleles must then be explained by the effect/other alleles either directly or
after complementing (a strand flip); a VCF record must also carry both scoring alleles as REF/ALT, so a
homozygous-reference call at a co-located SNV never stands in for an indel. Strand flips are resolved only for
non-palindromic SNVs; indels are matched exactly; A/T and C/G SNVs are excluded, as pgsc_calc does by default
(keep_ambiguous = false), because their strand cannot be told from the alleles. Duplicated scoring rows and
rsID/position conflicts are excluded and reported. Only autosomal variants are scored:
sex-chromosome dosages depend on hemizygosity conventions the Catalog does not standardise, so X/Y/MT rows are
excluded and counted (their loss is part of the scoreability measurement).

The raw score is the sum of weight x effect-allele dosage over matched variants: no imputation. Reference
distributions are computed on exactly the same matched variant set (prsguard.reference.distribution), so the
reported percentile is the percentile of the score actually computed.
"""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from prsguard.genotypes import GenotypeSet

COMP = str.maketrans("ACGT", "TGCA")
PALINDROMIC = ({"A", "T"}, {"C", "G"})
UNSUPPORTED_COLUMNS = ("dosage_0_weight", "dosage_1_weight", "dosage_2_weight", "is_haplotype", "is_diplotype",
                       "is_interaction", "is_dominant", "is_recessive")


@dataclass
class ScoreVariant:
    idx: int
    rsid: str | None
    chrom: str | None
    pos: int | None
    effect: str
    other: str | None
    weight: float
    af_reported: float | None


@dataclass
class ScoringFile:
    path: str
    sha256: str
    build: str | None
    header: dict
    variants: list[ScoreVariant]
    unsupported: list[str] = field(default_factory=list)
    parse_problems: list[str] = field(default_factory=list)


def _open(path: Path):
    return gzip.open(path, "rt", errors="replace") if str(path).endswith(".gz") else open(path, errors="replace")


def read_scoring_file(path: str | Path, build: str | None) -> ScoringFile:
    """Parse a PGS Catalog (harmonised) scoring file; ``build`` is the harmonised coordinate build."""
    path = Path(path)
    header: dict = {}
    variants: list[ScoreVariant] = []
    problems: list[str] = []
    cols: dict[str, int] | None = None
    unsupported: list[str] = []
    flag_cols: dict[str, int] = {}
    with _open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                body = line.lstrip("#").strip()
                if "=" in body:
                    k, _, v = body.partition("=")
                    header.setdefault(k.strip().lower(), v.strip())
                continue
            cells = line.rstrip("\n").split("\t")
            if cols is None:
                cols = {c.strip().lower(): i for i, c in enumerate(cells)}
                unsupported = [c for c in UNSUPPORTED_COLUMNS if c in cols and not c.startswith("is_")]
                flag_cols = {c: cols[c] for c in UNSUPPORTED_COLUMNS if c.startswith("is_") and c in cols}
                continue

            def get(*names, cols=cols, cells=cells):
                for n in names:
                    i = cols.get(n)
                    if i is not None and i < len(cells) and cells[i].strip() not in ("", "NA", "."):
                        return cells[i].strip()
                return None

            for flag, i in flag_cols.items():
                if i < len(cells) and cells[i].strip().lower() in ("true", "1"):
                    if flag not in unsupported:
                        unsupported.append(flag)
            weight = get("effect_weight")
            effect = (get("effect_allele") or "").upper()
            try:
                w = float(weight) if weight is not None else None
            except ValueError:
                w = None
            if w is None or not effect:
                problems.append(f"row {len(variants) + 1}: missing effect allele or weight")
                continue
            other = (get("other_allele") or "").upper() or None
            if other is None:
                inferred = (get("hm_inferotherallele") or "").upper()
                other = inferred if inferred and "/" not in inferred and inferred != effect else None
            chrom = get("hm_chr", "chr_name")
            pos = get("hm_pos", "chr_position")
            af = get("allelefrequency_effect")
            variants.append(ScoreVariant(
                idx=len(variants), rsid=get("hm_rsid", "rsid"), chrom=chrom.replace("chr", "") if chrom else None,
                pos=int(pos) if pos and pos.isdigit() else None, effect=effect, other=other, weight=w,
                af_reported=float(af) if af and af.replace(".", "", 1).isdigit() else None))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return ScoringFile(path=path.name, sha256=sha, build=build, header=header, variants=variants,
                       unsupported=unsupported, parse_problems=problems)


@dataclass
class Harmonisation:
    rows: list[dict]
    counts: dict
    raw_score: float | None
    matched_keys: list[tuple[str, int, str, str | None]]  # (chrom, pos, effect, other) of matched variants
    build_used_for_positions: str | None
    notes: list[str]


STATUSES = ("matched", "matched_flipped", "missing", "no_call", "allele_mismatch", "palindromic_excluded",
            "duplicate_excluded", "position_conflict", "non_snv_excluded", "non_autosomal_excluded",
            "build_unresolved")
AUTOSOMES = {str(i) for i in range(1, 23)}


def _dosage(alleles: tuple[str, ...], effect: str) -> int:
    return sum(1 for a in alleles if a == effect)


def _comp(a: str) -> str:
    return a.translate(COMP)


def _resolve(v: ScoreVariant, calls: list) -> tuple[str, int | None, object]:
    """Status, effect-allele dosage and the call used, for one scoring variant and its candidate calls."""
    called = [c for c in calls if len(c.alleles) == 2]
    if not called:
        return "no_call", None, calls[0]  # no call, or a haploid call on an autosomal variant
    ea, oa = v.effect, v.other
    if oa is None:
        return "allele_mismatch", None, called[0]  # alleles cannot be verified without the other allele
    snv = len(ea) == 1 and len(oa) == 1
    if snv and {ea, oa} in PALINDROMIC:
        return "palindromic_excluded", None, called[0]
    options = []
    for c in called:
        got = set(c.alleles)
        site = set(c.site_alleles) if c.site_alleles else None
        # VCF records must carry both scoring alleles; array calls are judged on the called alleles only.
        if (site is None or {ea, oa} <= site) and got <= {ea, oa}:
            options.append(("matched", _dosage(c.alleles, ea), c))
        elif snv and (site is None or {_comp(ea), _comp(oa)} <= site) and got <= {_comp(ea), _comp(oa)}:
            options.append(("matched_flipped", _dosage(c.alleles, _comp(ea)), c))
    if not options:
        return "allele_mismatch", None, called[0]
    if len({(o[0], o[1]) for o in options}) > 1:
        return "duplicate_excluded", None, called[0]  # conflicting calls for the same variant
    return options[0]


def harmonise(score: ScoringFile, gs: GenotypeSet) -> Harmonisation:
    positions_ok = gs.build in ("GRCh37", "GRCh38") and score.build == gs.build
    notes = []
    if not positions_ok:
        notes.append(f"position matching disabled: genotype build {gs.build}, scoring build {score.build}")
    keys: dict = {}
    dup = set()
    for v in score.variants:
        k = (v.rsid or f"{v.chrom}:{v.pos}", v.effect, v.other)
        if k in keys:
            dup.add(k)
        keys[k] = v.idx
    rows, total, matched_keys = [], 0.0, []
    counts = {s: 0 for s in STATUSES}
    for v in score.variants:
        row = {"idx": v.idx, "rsid": v.rsid, "chrom": v.chrom, "pos": v.pos, "effect": v.effect, "other": v.other,
               "weight": v.weight, "status": None, "dosage": None, "match_by": None, "genotype": None}
        k = (v.rsid or f"{v.chrom}:{v.pos}", v.effect, v.other)
        if k in dup:
            row["status"] = "duplicate_excluded"
        elif set(v.effect + (v.other or "")) - set("ACGT"):
            row["status"] = "non_snv_excluded"  # symbolic or non-sequence alleles (e.g. I/D, HLA, CNV)
        elif v.chrom is not None and v.chrom not in AUTOSOMES:
            row["status"] = "non_autosomal_excluded"  # X/Y/MT dosage coding differs by sex; never scored
        else:
            hits, how = [], None
            if v.rsid and v.rsid in gs.by_rsid:
                hits, how = gs.by_rsid[v.rsid], "rsid"
                if positions_ok and v.pos is not None:
                    c0 = gs.calls[hits[0]]
                    if c0.pos is not None and (c0.chrom != v.chrom or c0.pos != v.pos):
                        hits, how = [], None
                        row["status"] = "position_conflict"
            if not hits and row["status"] is None and positions_ok and v.pos is not None:
                hits = gs.by_pos.get((v.chrom, v.pos), [])
                how = "position" if hits else None
            if row["status"] is None:
                if not hits:
                    row["status"] = "build_unresolved" if not positions_ok and not v.rsid else "missing"
                else:
                    status, dosage, call = _resolve(v, [gs.calls[i] for i in hits])
                    row.update({"status": status, "dosage": dosage, "match_by": how,
                                "genotype": "/".join(call.alleles) if call is not None and call.alleles else None})
        counts[row["status"]] += 1
        if row["dosage"] is not None:
            total += v.weight * row["dosage"]
            matched_keys.append((v.chrom, v.pos, v.effect, v.other))
        rows.append(row)
    counts["n_variants"] = len(score.variants)
    counts["n_matched"] = counts["matched"] + counts["matched_flipped"]
    n_match = counts["n_matched"]
    return Harmonisation(rows=rows, counts=counts, raw_score=total if n_match else None, matched_keys=matched_keys,
                         build_used_for_positions=gs.build if positions_ok else None, notes=notes)


def scoreability(score: ScoringFile, h: Harmonisation) -> dict:
    """Unweighted and effect-weighted fractions of the score retained by the matched variants."""
    w_all = sum(abs(v.weight) for v in score.variants)
    w_matched = sum(abs(r["weight"]) for r in h.rows if r["dosage"] is not None)
    # Variance share under HWE uses reported effect-allele frequencies when the file provides them for all rows.
    have_af = all(v.af_reported is not None and 0 < v.af_reported < 1 for v in score.variants)
    var_share = None
    if have_af and score.variants:
        var = {v.idx: v.weight ** 2 * 2 * v.af_reported * (1 - v.af_reported) for v in score.variants}
        tot = sum(var.values())
        var_share = sum(var[r["idx"]] for r in h.rows if r["dosage"] is not None) / tot if tot else None
    top = sorted(score.variants, key=lambda v: -abs(v.weight))[:max(1, len(score.variants) // 20)]
    top_missing = [v.rsid or f"{v.chrom}:{v.pos}" for v in top
                   if h.rows[v.idx]["dosage"] is None]
    n = len(score.variants)
    return {"n_variants": n, "n_matched": h.counts["n_matched"],
            "fraction_matched": round(h.counts["n_matched"] / n, 4) if n else None,
            "fraction_abs_weight_matched": round(w_matched / w_all, 4) if w_all else None,
            "fraction_variance_matched_reported_af": None if var_share is None else round(var_share, 4),
            "top5pct_weight_variants_missing": top_missing}
