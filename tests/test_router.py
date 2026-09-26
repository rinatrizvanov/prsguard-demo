"""Router: trait resolution, eligibility, ranking and freezing (offline, from the committed PGS Catalog snapshot)."""

from __future__ import annotations

import copy
import json

import pytest

from prsguard import catalog, router
from prsguard.clawbio_env import REPO_ROOT

SNAP = REPO_ROOT / "data" / "catalog_snapshot"
FROZEN = REPO_ROOT / "data" / "candidate_sets" / "breast_cancer_female_GRCh37.frozen.json"


@pytest.fixture(scope="module")
def routed():
    src = catalog.open_source("snapshot", SNAP)
    cs, _ = router.route("breast cancer", src, router.RouterOptions(sex="female", build="GRCh37",
                                                                    max_variants=10_000, top_k=3))
    return cs


def test_label_match_beats_synonym_match():
    src = catalog.open_source("snapshot", SNAP)
    t = router.resolve_trait("breast cancer", src, [])
    assert t["status"] == "resolved" and t["term"]["id"] == "MONDO_0007254"
    assert t["detail"] == "exact label match"


def test_scope_keeps_same_outcome_and_excludes_subtypes(routed):
    scope = {s["id"] for s in routed["trait"]["scope"]}
    assert {"MONDO_0007254", "MONDO_0004989", "MONDO_0004379"} <= scope
    excluded = [c["label"] for c in routed["trait"]["excluded_children"]]
    assert excluded and all(c not in scope for c in (x["id"] for x in routed["trait"]["excluded_children"]))


def test_committed_candidate_set_is_reproduced(routed):
    frozen = json.loads(FROZEN.read_text())
    assert router.verify_frozen(frozen)
    for key in ("selected", "n_found", "n_eligible", "eligible", "excluded", "trait", "options"):
        assert routed[key] == frozen[key], key
    assert routed["selected"] == ["PGS000004", "PGS001804", "PGS001336"]


def test_ranking_is_metadata_only_and_ordered(routed):
    keys = [e["sort_key"] for e in routed["eligible"]]
    assert keys == sorted(keys)
    assert [e["pre_rank"] for e in routed["eligible"]] == list(range(1, len(keys) + 1))
    assert "genotype" not in json.dumps(routed["eligible"]).lower()


def test_freeze_detects_tampering():
    frozen = json.loads(FROZEN.read_text())
    bad = copy.deepcopy(frozen)
    bad["selected"] = ["PGS001336", "PGS000004", "PGS001804"]
    assert not router.verify_frozen(bad)


def test_engineering_cap_is_labelled(routed):
    assert any("E8 (engineering)" in r for x in routed["excluded"] for r in x["reasons"])
    assert any(r.startswith("E8 engineering") for r in routed["eligibility_rules"])


def _rec(**kw):
    base = {"id": "PGS999999", "trait_reported": "Breast cancer", "trait_efo": [{"id": "MONDO_0007254"}],
            "weight_type": "beta", "variants_interactions": 0,
            "ftp_harmonized_scoring_files": {"GRCh37": {"positions": "x"}, "GRCh38": {"positions": "y"}},
            "ancestry_distribution": {"eval": {"count": 3}}, "variants_number": 100}
    base.update(kw)
    return base


TRAIT = {"scope": [{"id": "MONDO_0007254", "label": "breast cancer", "sex": None},
                   {"id": "MONDO_0004379", "label": "female breast carcinoma", "sex": "female"}]}


@pytest.mark.parametrize("rec, opts, rule", [
    (_rec(trait_efo=[{"id": "EFO_0000000"}]), {}, "E1"),
    (_rec(trait_reported="Breast cancer (ER-negative)"), {}, "E2"),
    (_rec(trait_reported="Breast cancer (female)"), {"sex": "male"}, "E3"),
    (_rec(trait_efo=[{"id": "MONDO_0004379"}]), {"sex": "male"}, "E3"),
    (_rec(weight_type="OR"), {}, "E4"),
    (_rec(variants_interactions=2), {}, "E4"),
    (_rec(ftp_harmonized_scoring_files={}), {"build": "GRCh37"}, "E5"),
    (_rec(ancestry_distribution={"eval": {"count": 0}}), {}, "E6"),
    (_rec(variants_number=50_000), {"max_variants": 10_000}, "E8"),
])
def test_each_eligibility_rule(rec, opts, rule):
    reasons, _ = router.eligibility(rec, TRAIT, router.RouterOptions(**opts))
    assert any(r.startswith(rule) for r in reasons), reasons


def test_eligible_record_passes():
    reasons, facts = router.eligibility(_rec(), TRAIT, router.RouterOptions(sex="female", build="GRCh37"))
    assert reasons == [] and facts["harmonized_builds"] == ["GRCh37", "GRCh38"]


T2D = {"query": "type 2 diabetes",
       "scope": [{"id": "MONDO_0005148", "label": "type 2 diabetes mellitus", "sex": None,
                  "synonyms": ["T2D", "T2DM", "NIDDM", "type 2 diabetes"]}]}


@pytest.mark.parametrize("reported, ok", [
    ("Type 2 diabetes", True),
    ("Type 2 diabetes (T2D)", True),
    ("Type 2 diabetes (T2D) (PheCode 250.2)", True),
    ("Type 2 diabetes mellitus (ICD-10 E11)", True),
    ("Type 2 diabetes with ketoacidosis", False),
    ("Type 2 diabetes (based on SNPs associated with insulin secretion)", False),
])
def test_synonym_abbreviation_and_code_qualifiers(reported, ok):
    rec = _rec(trait_reported=reported, trait_efo=[{"id": "MONDO_0005148"}])
    reasons, facts = router.eligibility(rec, T2D, router.RouterOptions())
    assert (not any(r.startswith("E2") for r in reasons)) is ok, reasons
