"""End-to-end runs on the public demo genomes (offline: committed snapshot, frozen candidates, 1000G panels)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from prsguard import cross_pgs
from prsguard.clawbio_env import REPO_ROOT
from prsguard.cli import DEMO_CANDIDATES, DEMO_LITERATURE
from prsguard.pipeline import RunConfig, run

DEMO = REPO_ROOT / "data" / "demo"
CASES = {c["id"]: c for c in json.loads((DEMO / "cases.json").read_text())["cases"]}
_cache: dict = {}


def result(case: str, tmp_root: Path, **kw) -> dict:
    key = (case, tuple(sorted(kw.items())))
    if key not in _cache:
        c = CASES[case]
        cfg = RunConfig(genotype=DEMO / c["file"], trait="breast cancer", out_dir=tmp_root / f"{case}_{len(_cache)}",
                        sex=kw.get("sex", "female"), declared_build=kw.get("build"), candidates=DEMO_CANDIDATES,
                        literature_context=DEMO_LITERATURE if DEMO_LITERATURE.exists() else None,
                        case={"id": case, "title": c["title"], "provenance": c["provenance"], "synthetic": False})
        _cache[key] = run(cfg)
    return _cache[key]


@pytest.fixture(scope="module")
def tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("runs")


def statuses(r):
    return {c["pgs_id"]: c["gate"]["status"] for c in r["candidates"]}


EXPECTED = {  # the committed demo outcomes; a change here is a scientific change and must be reviewed
    "A": {"PGS000004": "ABSTAIN", "PGS001804": "ABSTAIN", "PGS001336": "ABSTAIN"},
    "B": {"PGS000004": "SUPPORTED", "PGS001804": "SUPPORTED", "PGS001336": "SUPPORTED"},
    "C": {"PGS000004": "SUPPORTED", "PGS001804": "SUPPORTED", "PGS001336": "SUPPORTED"},
    "D": {"PGS000004": "SUPPORTED", "PGS001804": "SUPPORTED", "PGS001336": "SUPPORTED"},
    "E": {"PGS000004": "RAW_ONLY", "PGS001804": "RAW_ONLY", "PGS001336": "RAW_ONLY"},
    "F": {"PGS000004": "SUPPORTED", "PGS001804": "RAW_ONLY", "PGS001336": "RAW_ONLY"},
    "G": {"PGS000004": "ABSTAIN", "PGS001804": "ABSTAIN", "PGS001336": "ABSTAIN"},
}


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_demo_case_outcomes(case, tmp_root):
    r = result(case, tmp_root)
    assert statuses(r) == EXPECTED[case]
    assert [s["actor"] for s in r["trace"]].count("ORCHESTRATION") >= 4
    assert r["orchestration"]["kind"] == "scripted_cli" and "scripted" in r["orchestration"]["performed_by"]
    assert len(r["trace"]) == 10
    for c in r["candidates"]:  # the gate's rule trace is complete even when placement is unresolved
        assert [x["rule"] for x in c["gate"]["rule_trace"]] == [f"G{i}" for i in range(1, 13)]


def test_each_ancestry_is_placed(tmp_root):
    got = {case: (result(case, tmp_root)["placement"]["status"], result(case, tmp_root)["placement"]["placement"])
           for case in "BCDEF"}
    assert got == {"B": ("RESOLVED", "EUR"), "C": ("RESOLVED", "EUR"), "D": ("RESOLVED", "AFR"),
                   "E": ("INTERMEDIATE", None), "F": ("RESOLVED", "AMR")}


def test_sparse_array_vs_wgs_same_person(tmp_root):
    a, b = result("A", tmp_root), result("B", tmp_root)
    assert a["placement"]["placement"] == b["placement"]["placement"] == "EUR"
    for ca, cb in zip(a["candidates"], b["candidates"]):
        assert ca["harmonisation"]["scoreability"]["r"] < cb["harmonisation"]["scoreability"]["r"]
        assert "LOW_SCOREABILITY" in ca["gate"]["reason_codes"]


def test_percentile_released_only_when_supported(tmp_root):
    for case in EXPECTED:
        for c in result(case, tmp_root)["candidates"]:
            p = c["interpretation"]["percentile"]
            assert p["released"] == (c["gate"]["status"] == "SUPPORTED")
            if not p["released"]:
                assert p["value"] is None and c["interpretation"]["standardized_score"]["value"] is None
            assert c["interpretation"]["absolute_risk"] == {**c["interpretation"]["absolute_risk"],
                                                            "released": False, "value": None}
            if c["gate"]["status"] == "ABSTAIN":
                assert c["interpretation"]["raw_score"]["value"] is None


def test_primary_is_highest_pre_ranked_supported(tmp_root):
    for case in EXPECTED:
        r = result(case, tmp_root)
        sup = sorted((c for c in r["candidates"] if c["gate"]["status"] == "SUPPORTED"), key=lambda c: c["pre_rank"])
        assert r["primary"]["pgs_id"] == (sup[0]["pgs_id"] if sup else None)


def test_cross_pgs_only_compares_supported(tmp_root):
    assert result("F", tmp_root)["cross_pgs"]["status"] == "NOT_COMPARABLE"
    b = result("B", tmp_root)["cross_pgs"]
    assert b["status"] in ("CONSISTENT", "DISCORDANT") and len(b["pairs"]) == 3
    for p in b["pairs"]:
        assert p["reference_gap_95"][0] <= 0 <= p["reference_gap_95"][1]


def test_cross_pgs_not_comparable_with_fewer_than_two():
    out = cross_pgs.compare([{"pgs_id": "PGS1", "gate_status": "SUPPORTED"},
                             {"pgs_id": "PGS2", "gate_status": "RAW_ONLY"}])
    assert out["status"] == "NOT_COMPARABLE"


def test_male_person_breast_cancer(tmp_root):
    """A female-specific candidate set cannot be reused for a male person; sex changes eligibility upstream."""
    with pytest.raises(SystemExit):
        result("B", tmp_root, sex="male")


def test_user_build_declaration_conflict_is_recorded(tmp_root):
    r = result("A", tmp_root, build="GRCh38")
    assert r["build"]["build"] == "GRCh37" and "conflict" in r["build"]


def test_no_genotypes_or_local_paths_in_result(tmp_root):
    for case in EXPECTED:
        text = json.dumps(result(case, tmp_root))
        assert "/Users/" not in text and "/home/" not in text
        assert not re.search(r'"genotype": "[ACGT]/[ACGT]"', text)
        assert "\"dosage\":" not in text and "\"rows\":" not in text   # no per-variant data


def test_deterministic_except_timestamps(tmp_root):
    a = result("D", tmp_root)
    c = CASES["D"]
    b = run(RunConfig(genotype=DEMO / c["file"], trait="breast cancer", out_dir=tmp_root / "D_again", sex="female",
                      candidates=DEMO_CANDIDATES, literature_context=DEMO_LITERATURE if DEMO_LITERATURE.exists()
                      else None, case={"id": "D", "title": c["title"], "provenance": c["provenance"],
                                       "synthetic": False}))

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("started_at", "finished_at", "retrieved_at")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    assert strip(a) == strip(b)


def test_synthetic_literature_context_is_refused(tmp_root, tmp_path):
    lit = json.loads(DEMO_LITERATURE.read_text())
    lit["synthetic"] = True
    fake = tmp_path / "lit.json"
    fake.write_text(json.dumps(lit))
    c = CASES["B"]
    with pytest.raises(SystemExit):
        run(RunConfig(genotype=DEMO / c["file"], trait="breast cancer", out_dir=tmp_path / "o", sex="female",
                      candidates=DEMO_CANDIDATES, literature_context=fake))


@pytest.mark.parametrize("bad", ["../escaped", "/tmp/prsguard_abs_escape", "PGS000001/../x", "PGS000001\n"])
def test_candidate_set_with_path_like_pgs_id_is_refused(tmp_path, bad):
    from prsguard import router

    cset = json.loads(DEMO_CANDIDATES.read_text())
    cset["selected"] = [bad, *cset["selected"][1:]]
    tampered = tmp_path / "cands.frozen.json"
    tampered.write_text(json.dumps(router.freeze(cset)))   # digest is valid: the check must not rely on it
    c = CASES["B"]
    out = tmp_path / "out"
    before = set(tmp_path.rglob("*"))
    with pytest.raises(SystemExit, match="invalid PGS identifiers"):
        run(RunConfig(genotype=DEMO / c["file"], trait="breast cancer", out_dir=out, sex="female",
                      candidates=tampered))
    created = set(tmp_path.rglob("*")) - before
    assert all(p == out or out in p.parents for p in created)
    assert not (tmp_path / "escaped").exists() and not (tmp_path.parent / "escaped").exists()


def test_supported_results_rest_on_an_evaluated_sensitivity_check(tmp_root):
    n = 0
    for case in EXPECTED:
        for c in result(case, tmp_root)["candidates"]:
            if c["gate"]["status"] == "SUPPORTED":
                assert c["gate"]["evidence_used"]["reference_distribution.reference_sensitive"] is False
                n += 1
    assert n == 10  # B, C, D (3 each) and F (PGS000004)


def test_single_defensible_reference_end_to_end_is_unverified_not_supported(tmp_path, monkeypatch):
    """Case F with only PEL as a defensible reference: sensitivity cannot be checked, so no percentile."""
    from prsguard import pipeline as pl

    real = pl.projection.run_placement

    def only_pel(*a, **kw):
        out = real(*a, **kw)
        out["consistent_populations"] = ["PEL"]
        return out

    monkeypatch.setattr(pl.projection, "run_placement", only_pel)
    c = CASES["F"]
    r = run(RunConfig(genotype=DEMO / c["file"], trait="breast cancer", out_dir=tmp_path / "F", sex="female",
                      candidates=DEMO_CANDIDATES))
    pgs4 = next(x for x in r["candidates"] if x["pgs_id"] == "PGS000004")
    assert pgs4["gate"]["status"] == "RAW_ONLY"
    assert pgs4["gate"]["reason_codes"] == ["REFERENCE_SENSITIVITY_UNVERIFIED"]
    assert pgs4["interpretation"]["percentile"]["released"] is False
    gi = json.loads((tmp_path / "F" / "gate" / "PGS000004.input.json").read_text())["reference_distribution"]
    assert gi["reference_sensitive"] is None and gi["reference_sensitivity_assessable"] is False
