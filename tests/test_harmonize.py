"""Harmonisation failure modes with small synthetic files (labelled synthetic; no real person's data)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from prsguard.genotypes import load_genotypes, resolve_build
from prsguard.harmonize import harmonise, read_scoring_file, scoreability

HEADER = "rsID\tchr_name\tchr_position\teffect_allele\tother_allele\teffect_weight\thm_rsID\thm_chr\thm_pos\n"


def scoring(tmp_path: Path, rows: list[tuple], name="score.txt.gz", header=HEADER, meta="") -> Path:
    p = tmp_path / name
    with gzip.open(p, "wt") as fh:
        fh.write("###PGS CATALOG SCORING FILE - SYNTHETIC TEST\n#pgs_id=PGS999999\n" + meta + header)
        for r in rows:
            fh.write("\t".join("" if x is None else str(x) for x in r) + "\n")
    return p


def vcf(tmp_path: Path, rows: list[tuple], name="g.vcf", contig_len=249250621) -> Path:
    p = tmp_path / name
    lines = ["##fileformat=VCFv4.2", f"##contig=<ID=1,length={contig_len}>",
             "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTH"]
    lines += ["\t".join(map(str, (c, pos, rid or ".", ref, alt, ".", "PASS", ".", "GT", gt)))
              for c, pos, rid, ref, alt, gt in rows]
    p.write_text("\n".join(lines) + "\n")
    return p


def run(tmp_path, score_rows, geno_rows, build="GRCh37", **kw):
    sf = read_scoring_file(scoring(tmp_path, score_rows), build)
    gs = load_genotypes(vcf(tmp_path, geno_rows, **kw))
    gs.build = "GRCh37"
    return sf, gs, harmonise(sf, gs)


def status(h, i):
    return h.rows[i]["status"]


def test_direct_match_and_dosage(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 100, "rs1", "G", "A", "0/1")])
    assert status(h, 0) == "matched" and h.rows[0]["dosage"] == 1 and h.raw_score == 0.5


def test_strand_flip_resolved_for_non_palindromic(tmp_path):
    # scoring A/G on the opposite strand of genotype T/C
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 100, "rs1", "C", "T", "1/1")])
    assert status(h, 0) == "matched_flipped" and h.rows[0]["dosage"] == 2


def test_allele_flip_effect_is_ref(tmp_path):
    # effect allele is the VCF REF: dosage counts REF copies
    _, _, h = run(tmp_path, [("rs1", 1, 100, "G", "A", 1.0, "rs1", 1, 100)],
                  [(1, 100, "rs1", "G", "A", "0/0")])
    assert status(h, 0) == "matched" and h.rows[0]["dosage"] == 2


@pytest.mark.parametrize("pair", [("A", "T"), ("C", "G")])
def test_palindromic_excluded(tmp_path, pair):
    _, _, h = run(tmp_path, [("rs1", 1, 100, pair[0], pair[1], 0.5, "rs1", 1, 100)],
                  [(1, 100, "rs1", pair[0], pair[1], "0/1")])
    assert status(h, 0) == "palindromic_excluded" and h.raw_score is None


def test_allele_mismatch(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 100, "rs1", "A", "C", "0/1")])
    assert status(h, 0) == "allele_mismatch"


def test_duplicate_scoring_rows_excluded(tmp_path):
    rows = [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100), ("rs1", 1, 100, "A", "G", 0.7, "rs1", 1, 100)]
    _, _, h = run(tmp_path, rows, [(1, 100, "rs1", "G", "A", "0/1")])
    assert [status(h, 0), status(h, 1)] == ["duplicate_excluded", "duplicate_excluded"]


def test_conflicting_duplicate_calls_excluded(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 100, "rs1", "G", "A", "0/1"), (1, 100, "rs1", "G", "A", "1/1")])
    assert status(h, 0) == "duplicate_excluded"


def test_rsid_missing_matches_by_position_when_build_known(tmp_path):
    _, _, h = run(tmp_path, [(None, 1, 100, "A", "G", 0.5, None, 1, 100)],
                  [(1, 100, None, "G", "A", "0/1")])
    assert status(h, 0) == "matched" and h.rows[0]["match_by"] == "position"


def test_rsid_missing_and_build_unresolved(tmp_path):
    sf = read_scoring_file(scoring(tmp_path, [(None, 1, 100, "A", "G", 0.5, None, 1, 100)]), "GRCh37")
    gs = load_genotypes(vcf(tmp_path, [(1, 100, None, "G", "A", "0/1")], contig_len=12345))
    gs.build = "UNRESOLVED"
    assert status(harmonise(sf, gs), 0) == "build_unresolved"


def test_build_mismatch_disables_position_matching(tmp_path):
    sf = read_scoring_file(scoring(tmp_path, [(None, 1, 100, "A", "G", 0.5, None, 1, 100)]), "GRCh38")
    gs = load_genotypes(vcf(tmp_path, [(1, 100, None, "G", "A", "0/1")]))
    gs.build = "GRCh37"
    h = harmonise(sf, gs)
    assert status(h, 0) == "build_unresolved" and "position matching disabled" in h.notes[0]


def test_rsid_position_conflict(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 999, "rs1", "G", "A", "0/1")])
    assert status(h, 0) == "position_conflict"


def test_missing_variant(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100)],
                  [(1, 200, "rs2", "G", "A", "0/1")])
    assert status(h, 0) == "missing"


def test_no_call_and_haploid_are_not_scored(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, "rs1", 1, 100), ("rs2", 1, 200, "A", "G", 0.5,
                                                                               "rs2", 1, 200)],
                  [(1, 100, "rs1", "G", "A", "./."), (1, 200, "rs2", "G", "A", "1")])
    assert [status(h, 0), status(h, 1)] == ["no_call", "no_call"]


def test_non_autosomal_excluded(tmp_path):
    _, _, h = run(tmp_path, [("rsX", "X", 100, "A", "G", 0.5, "rsX", "X", 100)], [(1, 5, "rs9", "G", "A", "0/1")])
    assert status(h, 0) == "non_autosomal_excluded"


def test_indel_exact_match_and_colocated_snv_ignored(tmp_path):
    rows = [(None, 1, 100, "C", "CAAA", 0.3, None, 1, 100)]
    geno = [(1, 100, "rsSNV", "C", "T", "0/0"), (1, 100, "rsIND", "C", "CAAA", "0/1")]
    _, _, h = run(tmp_path, rows, geno)
    assert status(h, 0) == "matched" and h.rows[0]["dosage"] == 1


def test_indel_absent_record_is_mismatch_not_hom_ref(tmp_path):
    _, _, h = run(tmp_path, [(None, 1, 100, "C", "CAAA", 0.3, None, 1, 100)], [(1, 100, None, "C", "T", "0/0")])
    assert status(h, 0) == "allele_mismatch"


def test_symbolic_alleles_excluded(tmp_path):
    _, _, h = run(tmp_path, [("rs1", 1, 100, "I", "D", 0.5, "rs1", 1, 100)], [(1, 100, "rs1", "G", "A", "0/1")])
    assert status(h, 0) == "non_snv_excluded"


def test_unsupported_format_detected(tmp_path):
    header = "rsID\tchr_name\tchr_position\teffect_allele\tother_allele\teffect_weight\tdosage_0_weight\n"
    sf = read_scoring_file(scoring(tmp_path, [("rs1", 1, 100, "A", "G", 0.5, 0.1)], header=header), "GRCh37")
    assert "dosage_0_weight" in sf.unsupported


def test_scoreability_is_weight_aware(tmp_path):
    rows = [("rs1", 1, 100, "A", "G", 5.0, "rs1", 1, 100)] + [
        (f"rs{i}", 1, 100 + i, "A", "G", 0.01, f"rs{i}", 1, 100 + i) for i in range(2, 21)]
    sf, gs, h = run(tmp_path, rows, [(1, 100 + i, f"rs{i}", "G", "A", "0/1") for i in range(2, 21)])
    s = scoreability(sf, h)
    assert s["fraction_matched"] == 0.95
    assert s["fraction_abs_weight_matched"] < 0.05
    assert s["top5pct_weight_variants_missing"] == ["rs1"]


def test_array_text_file_build_and_matching():
    """A real public 23andMe genome bundled with ClawBio (NCBI36 coordinates, no build header)."""
    from prsguard.clawbio_env import clawbio_root

    path = clawbio_root() / "skills" / "genome-compare" / "data" / "manuel_corpas_23andme.txt.gz"
    gs = load_genotypes(path)
    anchors = {"rs3094315": ("1", 752566), "rs3934834": ("1", 1005806)}
    # too few anchors: declaration only; this file declares nothing, so the build is not assumed
    assert resolve_build(gs, anchors).build == "UNRESOLVED"
    assert resolve_build(gs, anchors, user_declared="NCBI36").build == "NCBI36"
