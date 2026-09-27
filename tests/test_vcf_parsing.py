"""VCF genotype parsing: GT located by FORMAT key, phased/missing GT, single- vs multi-sample files (synthetic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prsguard.genotypes import GenotypeInputError, load_genotypes

HEAD = ["##fileformat=VCFv4.2", "##contig=<ID=1,length=249250621>"]


def vcf(tmp_path: Path, rows: list[str], samples=("S1",), header=True, name="g.vcf") -> Path:
    lines = list(HEAD)
    if header:
        lines.append("\t".join(["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", *samples]))
    p = tmp_path / name
    p.write_text("\n".join(lines + rows) + "\n")
    return p


def row(fmt: str, *fields: str, pos=100, rid="rs1", ref="A", alt="G") -> str:
    return "\t".join(["1", str(pos), rid, ref, alt, ".", "PASS", ".", fmt, *fields])


def alleles(path: Path, **kw) -> tuple:
    return load_genotypes(path, **kw).calls[0].alleles


def test_gt_first(tmp_path):
    assert alleles(vcf(tmp_path, [row("GT:DP", "0/1:30")])) == ("A", "G")


def test_gt_not_first(tmp_path):
    # previously the first FORMAT field (DP = "12") was read as the genotype
    assert alleles(vcf(tmp_path, [row("DP:GT:GQ", "12:1/1:99")])) == ("G", "G")


def test_phased_gt(tmp_path):
    assert alleles(vcf(tmp_path, [row("GT", "1|0")])) == ("G", "A")


@pytest.mark.parametrize("fmt, field", [("GT", "./."), ("GT", "."), ("DP:GQ", "12:99"), ("DP:GT", "12"),
                                        ("GT", "0/5"), ("GT", "a/b")])
def test_missing_or_unusable_gt_is_no_call(tmp_path, fmt, field):
    assert alleles(vcf(tmp_path, [row(fmt, field)])) == ()


def test_multi_allelic_index(tmp_path):
    assert alleles(vcf(tmp_path, [row("GT", "0/2", alt="G,T")])) == ("A", "T")


def test_multi_sample_vcf_is_rejected_without_a_sample(tmp_path):
    p = vcf(tmp_path, [row("GT", "0/0", "1/1")], samples=("MOTHER", "CHILD"))
    with pytest.raises(GenotypeInputError, match="2 sample columns"):
        load_genotypes(p)


def test_multi_sample_vcf_with_explicit_sample(tmp_path):
    p = vcf(tmp_path, [row("DP:GT", "8:0/0", "9:1/1")], samples=("MOTHER", "CHILD"))
    assert alleles(p, sample="CHILD") == ("G", "G")
    assert alleles(p, sample="MOTHER") == ("A", "A")
    with pytest.raises(GenotypeInputError, match="not found"):
        load_genotypes(p, sample="FATHER")


def test_headerless_multi_sample_records_are_rejected(tmp_path):
    p = vcf(tmp_path, [row("GT", "0/0", "1/1")], header=False)
    with pytest.raises(GenotypeInputError):
        load_genotypes(p)


def test_sample_option_only_for_vcf(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("# rsid\tchromosome\tposition\tgenotype\nrs1\t1\t100\tAG\n")
    with pytest.raises(GenotypeInputError):
        load_genotypes(p, sample="S1")


def test_cli_reports_multi_sample_error(tmp_path, capsys):
    from prsguard.cli import main

    p = vcf(tmp_path, [row("GT", "0/0", "1/1")], samples=("A", "B"))
    rc = main(["run", "--genotype", str(p), "--trait", "breast cancer", "--sex", "female", "--out",
               str(tmp_path / "out")])
    assert rc == 2 and "--sample" in capsys.readouterr().err
