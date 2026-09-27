"""Reference placement (held-out, each ancestry) and reference distributions, on the committed 1000G panels."""

from __future__ import annotations

import numpy as np
import pytest

from prsguard.clawbio_env import REPO_ROOT
from prsguard.genotypes import load_genotypes
from prsguard.harmonize import harmonise, read_scoring_file
from prsguard.reference import distribution, projection
from prsguard.reference.panel import load_panel

REF = REPO_ROOT / "data" / "reference"
SNAP = REPO_ROOT / "data" / "catalog_snapshot"
FAST = projection.PlacementPolicy(bootstrap=20)


@pytest.fixture(scope="module")
def pca():
    return load_panel(REF / "1000g_pca.npz")


@pytest.fixture(scope="module")
def pgs():
    return load_panel(REF / "1000g_pgs.npz")


def held_out(panel, pop, k=0, sites=None, seed=1):
    j = np.where(panel.pop == pop)[0][k]
    t = panel.dosages[:, j].astype(float)
    if sites:
        keep = np.random.default_rng(seed).choice(len(t), sites, replace=False)
        m = np.full(len(t), np.nan)
        m[keep] = t[keep]
        t = m
    return str(panel.samples[j]), t


@pytest.mark.parametrize("pop, group", [("GBR", "EUR"), ("YRI", "AFR"), ("CHB", "EAS"), ("GIH", "SAS"),
                                        ("PEL", "AMR")])
def test_held_out_core_samples_resolve_to_their_group(pca, pop, group):
    s, t = held_out(pca, pop)
    out = projection.place_vector(pca, t, FAST, exclude_samples={s}, with_plot=False)
    assert out["status"] == "RESOLVED" and out["placement"] == group
    assert s in out["excluded_reference_samples"]


def test_admixed_asw_is_not_forced_into_a_group(pca):
    # NA19625 (ASW) is demo case E
    j = int(np.where(pca.samples == "NA19625")[0][0])
    out = projection.place_vector(pca, pca.dosages[:, j].astype(float), FAST, exclude_samples={"NA19625"},
                                  with_plot=False)
    assert out["status"] == "INTERMEDIATE" and out["placement"] is None


def test_too_few_sites_is_unresolved(pca):
    s, t = held_out(pca, "GBR", sites=120)
    out = projection.place_vector(pca, t, FAST, exclude_samples={s}, with_plot=False)
    assert out["status"] == "UNRESOLVED"


def test_self_match_detected_and_excluded(pca):
    gs = load_genotypes(next((REPO_ROOT / "data" / "demo").glob("case_C_*")))
    gs.build = "GRCh37"
    out = projection.run_placement(pca, gs, FAST, with_plot=False)
    assert out["self_match"]["matches"] == ["NA06985"]
    assert "NA06985" in out["excluded_reference_samples"]


def test_placement_is_deterministic(pca):
    s, t = held_out(pca, "CHB")
    a = projection.place_vector(pca, t, FAST, exclude_samples={s})
    b = projection.place_vector(pca, t, FAST, exclude_samples={s})
    assert a == b


def test_stability_is_not_called_an_ancestry_percentage(pca):
    s, t = held_out(pca, "GBR")
    out = projection.place_vector(pca, t, FAST, exclude_samples={s}, with_plot=False)
    assert "placement_stability" in out and "ancestry_percent" not in str(out).lower()


def _score_and_person(pid, case):
    score = read_scoring_file(SNAP / pid / f"{pid}_hmPOS_GRCh37.txt.gz", "GRCh37")
    gs = load_genotypes(next((REPO_ROOT / "data" / "demo").glob(f"case_{case}_*")))
    gs.build = "GRCh37"
    return score, harmonise(score, gs)


def test_percentile_uses_the_matched_variant_set_and_reports_uncertainty(pgs):
    score, h = _score_and_person("PGS001336", "B")
    rd = distribution.reference_distribution(pgs, score, h, "EUR", {"HG00097"})
    assert rd["available"] and rd["n_intersection"] == h.counts["n_matched"]
    lo, hi = rd["ci_panel"]
    assert lo <= rd["percentile"] <= hi
    assert rd["combined_interval"][0] <= lo and rd["combined_interval"][1] >= hi
    assert rd["reference_n"] == 502  # 503 EUR core minus the person
    assert rd["absolute_risk"] is None


def test_sparse_file_widens_missing_variant_interval_and_lowers_r(pgs):
    score, h_wgs = _score_and_person("PGS000004", "B")
    _, h_arr = _score_and_person("PGS000004", "A")
    wgs = distribution.reference_distribution(pgs, score, h_wgs, "EUR", {"HG00097"})
    arr = distribution.reference_distribution(pgs, score, h_arr, "EUR", {"HG00097"})
    width = lambda iv: iv[1] - iv[0]  # noqa: E731
    assert arr["scoreability"]["r_full_reduced_adjusted"] < 0.5 < 0.9 < wgs["scoreability"]["r_full_reduced_adjusted"]
    assert width(arr["missing_variant_interval"]) > width(wgs["missing_variant_interval"])


def test_no_group_means_no_distribution(pgs):
    score, h = _score_and_person("PGS000004", "E")
    rd = distribution.reference_distribution(pgs, score, h, None, {"NA19625"})
    assert rd["available"] is False and "percentile" not in rd


def test_inside_several_clouds_is_not_resolved():
    """Two overlapping reference clouds: the point lies inside both, so no single reference group is assigned."""
    rng = np.random.default_rng(0)
    pts, labels = [], []
    centres = {"AFR": 0.0, "EUR": 0.5, "EAS": 60.0, "SAS": 90.0, "AMR": 120.0}
    for g, c in centres.items():
        pts.append(rng.normal(c, 1.0, size=(100, projection.K)))
        labels += [g] * 100
    ref_pcs, labels = np.vstack(pts), np.array(labels)
    out = projection.place(np.full(projection.K, 0.25), ref_pcs, labels)
    assert sorted(out["inside_clouds"]) == ["AFR", "EUR"] and out["placement"] == "INTERMEDIATE"
    single = projection.place(np.full(projection.K, 60.0), ref_pcs, labels)
    assert single["inside_clouds"] == ["EAS"] and single["placement"] == "EAS"


def test_sparse_multi_cloud_person_is_intermediate_with_reason(pca):
    """Found by benchmarks/multicloud_benchmark.py: sparse inputs can fall inside several core clouds."""
    rng = np.random.default_rng(3)
    for j in rng.choice(np.where(np.isin(pca.pop, ["GBR", "CEU", "IBS", "TSI", "PJL", "GIH"]))[0], 80,
                        replace=False):
        t = pca.dosages[:, j].astype(float)
        keep = rng.choice(len(t), 200, replace=False)
        m = np.full(len(t), np.nan)
        m[keep] = t[keep]
        out = projection.place_vector(pca, m, projection.PlacementPolicy(bootstrap=5), {str(pca.samples[j])},
                                      with_plot=False)
        if len(out["inside_clouds"]) > 1:
            assert out["status"] == "INTERMEDIATE" and out["placement"] is None
            assert "more than one reference cloud" in out["detail"]
            return
    pytest.fail("no multi-cloud sparse individual found in 80 draws (benchmark predicts ~22%)")
