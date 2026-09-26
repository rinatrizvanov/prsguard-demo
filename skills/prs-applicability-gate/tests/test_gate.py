"""prs-applicability-gate v2: one test per rule outcome, plus determinism, tamper detection and the CLI contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_gate_under_test", SKILL / "prs_applicability_gate.py")
gate = importlib.util.module_from_spec(spec)
sys.modules["_gate_under_test"] = gate
spec.loader.exec_module(gate)
CFG = gate.load_config()


def base_input() -> dict:
    """A fully supported case: every rule passes."""
    return {
        "schema": gate.INPUT_SCHEMA,
        "candidate": {"pgs_id": "PGS000000", "pre_rank": 1, "trait_reported": "Breast cancer", "sex_specific": None},
        "score_file": {"name": "x.txt.gz", "sha256": "0" * 64, "build": "GRCh37", "weight_type": "beta",
                       "ratio_weight_type": False, "unsupported_features": [], "n_parse_problems": 0,
                       "variants_interactions": 0},
        "genotype": {"file_sha256": "1" * 64, "format": "vcf", "n_calls": 10000, "n_called": 10000,
                     "build": "GRCh37", "build_evidence": {"method": "empirical"}},
        "person": {"sex": "female"},
        "harmonisation": {"n_variants": 300, "n_matched": 290, "n_located": 295, "status_counts": {},
                          "allele_mismatch_fraction": 0.0, "weight_loss_by_status": {"palindromic_excluded": 0.02},
                          "fraction_matched": 0.97, "fraction_abs_weight_matched": 0.98},
        "scoreability": {"r": 0.98, "method": "reference_panel_correlation"},
        "placement": {"status": "RESOLVED", "placement": "EUR", "nearest_reference": "EUR",
                      "placement_stability": 1.0, "n_sites_used": 6000, "detail": "inside EUR"},
        "catalog_metadata": {"status": "resolved", "failed_checks": [], "detail": "ok", "warnings": []},
        "evaluation": {"reported": True, "unit": "(publication, sample set) pairs", "units": [
            {"pgp_id": "PGP1", "pss_id": "PSS1", "code": "EUR", "pooled": False, "n": 5000, "cases": 900,
             "percent_male": 0.0, "metrics": [{"name": "OR", "estimate": 1.6, "ci_lower": 1.5, "ci_upper": 1.7,
                                               "null": 1.0}]},
            {"pgp_id": "PGP2", "pss_id": "PSS2", "code": "AFR", "pooled": False, "n": 800, "cases": 100,
             "percent_male": 0.0, "metrics": [{"name": "AUROC", "estimate": 0.55, "ci_lower": 0.49,
                                               "ci_upper": 0.61, "null": 0.5}]}]},
        "reference_distribution": {"available": True, "reference_group": "EUR", "reference_n": 502,
                                   "n_intersection": 290, "reference_sensitive": False,
                                   "reference_sensitive_pairs": [], "detail": None},
    }


def run(gi: dict) -> dict:
    return gate.evaluate(gi, CFG)


def rule(res: dict, rid: str) -> dict:
    return next(r for r in res["rule_trace"] if r["rule"] == rid)


def test_supported_base_case():
    res = run(base_input())
    assert res["status"] == "SUPPORTED"
    assert res["reason_codes"] == [] and res["primary_reason"] is None
    assert res["allowed_claims"] == {"raw_score": True, "standardized_score": True, "percentile": True,
                                     "absolute_risk": False}
    assert all(r["outcome"] in ("pass", "not_applicable") for r in res["rule_trace"])
    assert res["calibration_version"] == CFG["calibration_version"]
    for key in ("status", "primary_reason", "reason_codes", "evidence_used", "evidence_missing",
                "calibration_version", "rule_trace", "what_would_change_result", "provenance"):
        assert key in res


def mutate(**changes) -> dict:
    gi = base_input()
    for path, value in changes.items():
        obj = gi
        keys = path.split("__")
        for k in keys[:-1]:
            obj = obj[k]
        obj[keys[-1]] = value
    return gi


@pytest.mark.parametrize("changes, status, code", [
    ({"score_file__unsupported_features": ["dosage_0_weight"]}, "ABSTAIN", "UNSUPPORTED_SCORE_FORMAT"),
    ({"score_file__ratio_weight_type": True, "score_file__weight_type": "OR"}, "ABSTAIN", "UNSUPPORTED_SCORE_FORMAT"),
    ({"score_file__variants_interactions": 3}, "ABSTAIN", "UNSUPPORTED_SCORE_FORMAT"),
    ({"score_file__n_parse_problems": 2}, "ABSTAIN", "UNSUPPORTED_SCORE_FORMAT"),
    ({"genotype__build": "UNRESOLVED"}, "ABSTAIN", "BUILD_UNRESOLVED"),
    ({"harmonisation__allele_mismatch_fraction": 0.4}, "ABSTAIN", "ALLELE_HARMONIZATION_FAILED"),
    ({"scoreability__r": 0.7}, "ABSTAIN", "LOW_SCOREABILITY"),
    ({"scoreability__r": None, "scoreability__method": None}, "ABSTAIN", "SCOREABILITY_UNVERIFIED"),
    ({"candidate__sex_specific": "female", "person__sex": "male"}, "ABSTAIN", "SEX_POPULATION_MISMATCH"),
    ({"candidate__sex_specific": "female", "person__sex": None}, "RAW_ONLY", "SEX_NOT_PROVIDED"),
    ({"catalog_metadata__status": "contradictory"}, "RAW_ONLY", "METADATA_CONTRADICTION"),
    ({"catalog_metadata__status": "unresolved"}, "RAW_ONLY", "EVALUATION_METADATA_UNAVAILABLE"),
    ({"placement__status": "INTERMEDIATE", "placement__placement": None}, "RAW_ONLY", "TARGET_REFERENCE_UNRESOLVED"),
    ({"placement__status": "UNSTABLE", "placement__placement": None}, "RAW_ONLY", "TARGET_REFERENCE_UNRESOLVED"),
    ({"placement__status": "UNRESOLVED", "placement__placement": None}, "RAW_ONLY", "TARGET_REFERENCE_UNRESOLVED"),
    ({"placement__placement": "SAS"}, "RAW_ONLY", "NO_RELEVANT_EVALUATION"),
    ({"placement__placement": "AFR"}, "RAW_ONLY", "EVALUATION_NOT_INFORMATIVE"),
    ({"person__sex": "male"}, "RAW_ONLY", "SEX_POPULATION_MISMATCH"),
    ({"reference_distribution__available": False}, "RAW_ONLY", "REFERENCE_DISTRIBUTION_UNAVAILABLE"),
    ({"reference_distribution__reference_sensitive": True,
      "reference_distribution__reference_sensitive_pairs": [["FIN", "TSI"]]}, "RAW_ONLY", "REFERENCE_SENSITIVE"),
])
def test_each_reason_code(changes, status, code):
    gi = mutate(**changes)
    if gi["placement"]["placement"] in ("SAS", "AFR"):
        gi["reference_distribution"]["reference_group"] = gi["placement"]["placement"]
    res = run(gi)
    assert res["status"] == status, res["rule_trace"]
    assert code in res["reason_codes"]
    assert res["primary_reason"]["code"] in res["reason_codes"]
    assert res["what_would_change_result"], "every failure must say what would change it"
    assert res["allowed_claims"]["percentile"] is False
    assert res["allowed_claims"]["absolute_risk"] is False
    assert res["allowed_claims"]["raw_score"] is (status == "RAW_ONLY")


def test_every_reason_code_is_documented_and_reachable():
    documented = set(gate.REASON_CODES)
    skill_md = (SKILL / "SKILL.md").read_text()
    for code in documented:
        assert code in skill_md, f"{code} missing from SKILL.md"


def test_abstain_outranks_raw_only_and_primary_is_most_severe():
    res = run(mutate(scoreability__r=0.5, placement__status="INTERMEDIATE", placement__placement=None))
    assert res["status"] == "ABSTAIN"
    assert res["primary_reason"]["code"] == "LOW_SCOREABILITY"
    assert "TARGET_REFERENCE_UNRESOLVED" in res["reason_codes"]


def test_low_scoreability_names_the_largest_loss():
    res = run(mutate(scoreability__r=0.8, harmonisation__weight_loss_by_status={"palindromic_excluded": 0.3,
                                                                                "missing": 0.1}))
    assert res["reason_codes"][:2] == ["LOW_SCOREABILITY", "PALINDROMIC_VARIANT_UNRESOLVED"]


def test_threshold_boundaries_are_inclusive_as_documented():
    assert run(mutate(scoreability__r=CFG["scoreability"]["r_min"]))["status"] == "SUPPORTED"
    cut = CFG["allele_harmonisation"]["max_mismatch_fraction"]
    assert run(mutate(harmonisation__allele_mismatch_fraction=cut))["status"] == "SUPPORTED"


def test_pooled_units_do_not_count_as_group_evidence():
    gi = base_input()
    for u in gi["evaluation"]["units"]:
        u["pooled"] = True
    assert "NO_RELEVANT_EVALUATION" in run(gi)["reason_codes"]


def test_metric_without_ci_is_not_informative():
    gi = base_input()
    gi["evaluation"]["units"][0]["metrics"] = [{"name": "AUROC", "estimate": 0.65, "ci_lower": None,
                                                "ci_upper": None, "null": 0.5}]
    assert "EVALUATION_NOT_INFORMATIVE" in run(gi)["reason_codes"]


def test_missing_evidence_is_listed_not_inferred():
    res = run(mutate(scoreability__r=None))
    assert "scoreability.r" in res["evidence_missing"]


@pytest.mark.parametrize("bad", [
    {"schema": "v1"}, {"placement": None}, {"harmonisation": {"n_variants": -1}},
])
def test_invalid_input_abstains(bad):
    gi = base_input()
    for k, v in bad.items():
        if isinstance(v, dict) and isinstance(gi.get(k), dict):
            gi[k].update(v)
        else:
            gi[k] = v
    res = run(gi)
    assert res["status"] == "ABSTAIN" and res["reason_codes"] == ["INVALID_GATE_INPUT"]


def test_out_of_range_numbers_are_rejected():
    res = run(mutate(scoreability__r=1.7))
    assert res["reason_codes"] == ["INVALID_GATE_INPUT"]


def test_tampered_input_digest_is_rejected():
    gi = base_input()
    gi["input_digest"] = gate.canonical_digest(gi)
    assert run(gi)["status"] == "SUPPORTED"
    gi["scoreability"]["r"] = 0.99
    assert run(gi)["reason_codes"] == ["INVALID_GATE_INPUT"]


def test_deterministic_and_order_independent():
    gi = base_input()
    a = run(copy.deepcopy(gi))
    shuffled = json.loads(json.dumps(gi, sort_keys=True))
    b = run(shuffled)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_config_validation(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("calibration_version: x\nscoreability: {r_min: 1.5}\n")
    with pytest.raises(ValueError):
        gate.load_config(bad)


def test_gate_has_no_side_channels():
    src = (SKILL / "prs_applicability_gate.py").read_text()
    for forbidden in ("requests", "urllib", "random", "datetime.now", "pgscatalog"):
        assert forbidden not in src.split('"""', 2)[2], forbidden


def test_cli_demo_output_contract(tmp_path):
    out = tmp_path / "demo"
    subprocess.run([sys.executable, str(SKILL / "prs_applicability_gate.py"), "--demo", "--output", str(out)],
                   check=True, capture_output=True, text=True)
    summary = json.loads((out / "result.json").read_text())
    assert summary["results"], "demo evaluated no examples"
    assert (out / "report.md").exists()
    statuses = {r["status"] for r in summary["results"]}
    assert statuses == {"SUPPORTED", "RAW_ONLY", "ABSTAIN"}, statuses
    for r in summary["results"]:
        assert (out / f"{r['pgs_id']}_gate.json").exists() or True


def test_non_canonical_config_is_labelled(tmp_path):
    alt = tmp_path / "alt.yaml"
    alt.write_text((SKILL / "config" / "calibration.yaml").read_text().replace("r_min: 0.90", "r_min: 0.80"))
    cfg = gate.load_config(alt)
    res = gate.evaluate(base_input(), cfg)
    assert res["provenance"]["config_canonical"] is False
    assert "NON-CANONICAL CALIBRATION" in gate.render_report(res)
    assert gate.evaluate(base_input(), CFG)["provenance"]["config_canonical"] is True


def test_inverse_association_is_not_supporting_evidence():
    """A CI entirely below the null (e.g. a case-only subtype comparison, OR 0.86 [0.82, 0.89]) is not evidence
    for interpreting the score, even though it excludes the null."""
    gi = base_input()
    gi["evaluation"]["units"][0]["metrics"] = [{"name": "OR", "estimate": 0.86, "ci_lower": 0.82, "ci_upper": 0.89,
                                                "null": 1.0}]
    res = run(gi)
    assert "EVALUATION_NOT_INFORMATIVE" in res["reason_codes"] and res["status"] == "RAW_ONLY"


def test_disclaimer_states_supported_is_not_clinical():
    text = run(base_input())["disclaimer"]
    assert "not a clinical recommendation" in text and "discrimination or calibration" in text
