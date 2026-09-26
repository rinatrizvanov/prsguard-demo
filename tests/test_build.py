"""Genome build resolution on real public files (1000 Genomes demo genomes, ClawBio's public 23andMe genomes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prsguard.clawbio_env import REPO_ROOT, clawbio_root
from prsguard.genotypes import load_genotypes, resolve_build
from prsguard.reference.panel import load_panel

DEMO = REPO_ROOT / "data" / "demo"


@pytest.fixture(scope="module")
def anchors():
    pca = load_panel(REPO_ROOT / "data" / "reference" / "1000g_pca.npz")
    return {str(i): (str(c), int(p)) for i, c, p in zip(pca.ids, pca.chrom, pca.pos)}


@pytest.fixture(scope="module")
def anchors38():
    return json.loads((REPO_ROOT / "data" / "reference" / "1000g_pca_grch38_positions.json").read_text())["positions"]


def demo(pattern: str) -> Path:
    return next(DEMO.glob(pattern))


def test_grch37_array_confirmed(anchors):
    gs = resolve_build(load_genotypes(demo("case_A_*")), anchors)
    assert gs.build == "GRCh37"
    assert gs.build_evidence["grch37_position_agreement"] == 1.0


def test_vcf_without_rsids_uses_header_contigs(anchors):
    gs = resolve_build(load_genotypes(demo("case_B_*")), anchors)
    assert gs.declared_build == "GRCh37" and gs.build == "GRCh37"


def test_wrong_user_declaration_is_overruled_by_evidence_and_recorded(anchors):
    gs = resolve_build(load_genotypes(demo("case_A_*")), anchors, user_declared="GRCh38")
    assert gs.build == "GRCh37"
    assert "GRCh38" in gs.build_evidence["conflict"]


@pytest.mark.parametrize("name, expected", [("manuel_corpas_23andme.txt.gz", "UNRESOLVED"),   # no build header
                                            ("george_church_23andme.txt.gz", "NCBI36")])     # "build 36" header
def test_ncbi36_files_refuted_as_grch37_and_never_assumed(anchors, name, expected):
    gs = load_genotypes(clawbio_root() / "skills" / "genome-compare" / "data" / name)
    resolve_build(gs, anchors)
    ev = gs.build_evidence
    assert ev["grch37_rsid_sites_checked"] > 1000
    assert ev["grch37_position_agreement"] < 0.05     # bimodal: correct files ~1.0, wrong build ~0
    assert gs.build == expected                        # GRCh37 refuted; other builds only if declared
    assert resolve_build(gs, anchors, user_declared="NCBI36").build == "NCBI36"


def test_wrong_grch38_declaration_refuted_with_grch38_anchors(anchors, anchors38):
    gs = load_genotypes(clawbio_root() / "skills" / "genome-compare" / "data" / "manuel_corpas_23andme.txt.gz")
    resolve_build(gs, anchors, user_declared="GRCh38", grch38_positions=anchors38)
    assert gs.build_evidence["grch38_position_agreement"] < 0.05
    assert gs.build == "UNRESOLVED"
    assert "refuted" in gs.build_evidence["method"]


def test_grch38_confirmed_by_anchors(tmp_path, anchors, anchors38):
    lines = ["# rsid\tchromosome\tposition\tgenotype"] + [f"{r}\t{c}\t{p}\tAG" for r, (c, p) in
                                                        list(anchors38.items())[:300]]
    f = tmp_path / "synthetic_grch38_23andme.txt"
    f.write_text("\n".join(lines) + "\n")
    gs = resolve_build(load_genotypes(f), anchors, grch38_positions=anchors38)
    assert gs.build == "GRCh38"


def test_thin_file_relies_on_declaration(anchors):
    gs = resolve_build(load_genotypes(demo("case_G_*")), anchors)
    assert gs.build == "GRCh37"   # 150 sites include enough anchors, and the header declares build 37
