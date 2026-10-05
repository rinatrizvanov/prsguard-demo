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
    assert len({r["output"] for r in summary["results"]}) == len(summary["results"])  # no overwrites
    for r in summary["results"]:
        written = json.loads((out / r["output"]).read_text())
        assert written["status"] == r["status"] and written["pgs_id"] == r["pgs_id"]
        assert (out / r["output"].replace(".json", ".md")).exists()


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


# ---- fail-closed validation (external review) ------------------------------------------------------------------

def _invalid(res):
    return res["status"] == "ABSTAIN" and res["reason_codes"] == ["INVALID_GATE_INPUT"]


def test_null_mismatch_fraction_with_located_variants_is_invalid_not_a_crash():
    assert _invalid(run(mutate(harmonisation__allele_mismatch_fraction=None)))


def test_null_mismatch_fraction_is_valid_only_when_nothing_located():
    gi = mutate(harmonisation__allele_mismatch_fraction=None, harmonisation__n_located=0,
                harmonisation__n_matched=0)
    res = run(gi)
    assert "INVALID_GATE_INPUT" not in res["reason_codes"]
    assert rule(res, "G4")["outcome"] == "not_applicable"
    assert _invalid(run(mutate(harmonisation__n_located=0, harmonisation__n_matched=0)))  # 0.0 given, must be null


@pytest.mark.parametrize("changes", [
    {"harmonisation__allele_mismatch_fraction": -0.1},
    {"harmonisation__allele_mismatch_fraction": 1.5},
    {"harmonisation__allele_mismatch_fraction": "0.01"},
    {"harmonisation__allele_mismatch_fraction": float("nan")},
    {"placement__placement_stability": -0.2},
    {"placement__placement_stability": 1.01},
    {"scoreability__r": -1.5},
    {"harmonisation__weight_loss_by_status": {"missing": -0.3}},
    {"score_file__n_parse_problems": -1},
    {"candidate__sex_specific": "both"},
    {"reference_distribution": ["not", "an", "object"]},
    {"evaluation__units": ["not a unit"]},
    {"evaluation__units": [{"code": "EUR", "metrics": "not a list"}]},
])
def test_out_of_domain_or_malformed_inputs_abstain(changes):
    assert _invalid(run(mutate(**changes)))


def test_negative_correlation_is_valid_input_but_low_scoreability():
    res = run(mutate(scoreability__r=-0.5))
    assert res["status"] == "ABSTAIN" and "LOW_SCOREABILITY" in res["reason_codes"]


def test_gate_never_raises_on_mutated_inputs():
    import random

    rng = random.Random(20260926)
    weird = [None, -1, 2.5, "x", [], {}, True, float("nan"), {"a": [1]}, [None]]
    base = base_input()
    paths = [(blk, k) for blk, v in base.items() if isinstance(v, dict) for k in v]
    for _ in range(400):
        gi = copy.deepcopy(base)
        for blk, k in rng.sample(paths, 3):
            gi[blk][k] = rng.choice(weird)
        res = run(gi)  # must not raise
        assert res["status"] in ("SUPPORTED", "RAW_ONLY", "ABSTAIN")
        assert res["allowed_claims"]["absolute_risk"] is False


# ---- backport from the ClawBio upstream port (gate 2.2.0) ------------------------------------------------------

RULE_IDS = [f"G{i}" for i in range(1, 13)]


def _cli(*args):
    return subprocess.run([sys.executable, str(SKILL / "prs_applicability_gate.py"), *map(str, args)],
                          capture_output=True, text=True)


def test_demo_cases_sharing_a_pgs_id_keep_separate_outputs(tmp_path):
    """case_B and case_G both concern PGS001336; the later one used to overwrite the earlier one's files."""
    out = tmp_path / "demo"
    assert _cli("--demo", "--output", out).returncode == 0
    rows = {r["input"]: r for r in json.loads((out / "result.json").read_text())["results"]}
    b, g = rows["case_B_PGS001336.gate_input.json"], rows["case_G_PGS001336.gate_input.json"]
    assert b["pgs_id"] == g["pgs_id"] == "PGS001336" and b["output"] != g["output"]
    assert json.loads((out / b["output"]).read_text())["status"] == "SUPPORTED"
    assert json.loads((out / g["output"]).read_text())["status"] == "ABSTAIN"


def test_same_input_file_name_twice_gets_unique_outputs(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for d, r in (("a", 0.98), ("b", 0.5)):
        (tmp_path / d / "x.gate_input.json").write_text(json.dumps(mutate(scoreability__r=r)))
    out = tmp_path / "out"
    assert _cli("--input", tmp_path / "a" / "x.gate_input.json", tmp_path / "b" / "x.gate_input.json",
                "--output", out).returncode == 0
    rows = json.loads((out / "result.json").read_text())["results"]
    assert [r["output"] for r in rows] == ["x_gate.json", "x_2_gate.json"]
    assert [json.loads((out / r["output"]).read_text())["status"] for r in rows] == ["SUPPORTED", "ABSTAIN"]


def test_demo_outputs_are_deterministic(tmp_path):
    for d in ("one", "two"):
        assert _cli("--demo", "--output", tmp_path / d).returncode == 0
    names = sorted(p.name for p in (tmp_path / "one").iterdir())
    assert names == sorted(p.name for p in (tmp_path / "two").iterdir())
    for n in names:
        assert (tmp_path / "one" / n).read_bytes() == (tmp_path / "two" / n).read_bytes(), n


@pytest.mark.parametrize("pgs_id", ["../escaped", "../../escaped", "/tmp/prsguard_abs_escape", "a/b/escaped",
                                    "..\\escaped", "PGS000001/../../escaped", "‥／escaped",
                                    "‮escaped", "PGS000001\n", "", "." * 300])
def test_pgs_id_is_data_never_a_path(tmp_path, pgs_id):
    inputs, out = tmp_path / "inputs", tmp_path / "out"
    inputs.mkdir()
    (inputs / "case.gate_input.json").write_text(json.dumps(mutate(candidate__pgs_id=pgs_id)))
    before = {p for p in tmp_path.rglob("*")}
    assert _cli("--input", inputs / "case.gate_input.json", "--output", out).returncode == 0
    created = {p for p in tmp_path.rglob("*")} - before
    assert created and all(p == out or out in p.parents for p in created), sorted(map(str, created))
    assert not Path("/tmp/prsguard_abs_escape_gate.json").exists()
    assert json.loads((out / "case_gate.json").read_text())["pgs_id"] == pgs_id  # kept as data


@pytest.mark.parametrize("filename, expected", [
    ("case_B.gate_input.json", "case_B"), ("..gate_input.json", "input"), ("...hidden.json", "hidden"),
    ("a b;rm -rf.json", "a_b_rm_-rf"), ("über∕x.json", "_ber_x"), (".json", "input"),
])
def test_output_names_are_sanitised(filename, expected):
    assert gate.output_stem(Path(filename), set()) == expected


@pytest.mark.parametrize("content, fragment", [
    ("", "empty"), ("   \n", "empty"), ("{not json", "not valid JSON"),
    ('{"schema": "prs-applicability-gate', "not valid JSON"),  # truncated
    ("[1, 2, 3]", "not a JSON object"), ('"just a string"', "not a JSON object"), ("42", "not a JSON object"),
    ("null", "not a JSON object"),
])
def test_malformed_input_files_fail_closed(tmp_path, content, fragment):
    f = tmp_path / "bad.gate_input.json"
    f.write_text(content)
    out = tmp_path / "out"
    proc = _cli("--input", f, "--output", out)
    assert proc.returncode == 0 and "Traceback" not in proc.stderr, proc.stderr
    res = json.loads((out / "bad_gate.json").read_text())
    assert res["status"] == "ABSTAIN" and res["reason_codes"] == ["INVALID_GATE_INPUT"]
    assert fragment in res["primary_reason"]["detail"]
    assert [r["rule"] for r in res["rule_trace"]] == RULE_IDS


def test_unreadable_input_file_fails_closed(tmp_path):
    out = tmp_path / "out"
    proc = _cli("--input", tmp_path / "missing.gate_input.json", "--output", out)
    assert proc.returncode == 0 and "Traceback" not in proc.stderr
    assert json.loads((out / "missing_gate.json").read_text())["reason_codes"] == ["INVALID_GATE_INPUT"]


@pytest.mark.parametrize("changes, status", [
    ({}, "SUPPORTED"),
    ({"placement__placement": "SAS"}, "RAW_ONLY"),
    ({"scoreability__r": 0.5}, "ABSTAIN"),
    ({"placement__status": "INTERMEDIATE", "placement__placement": None}, "RAW_ONLY"),
    ({"placement__status": "UNRESOLVED", "placement__placement": None, "person__sex": "female"}, "RAW_ONLY"),
    ({"schema": "wrong"}, "ABSTAIN"),
])
def test_rule_trace_is_complete_and_ordered(changes, status):
    gi = mutate(**changes) if "schema" not in changes else {**base_input(), "schema": "wrong"}
    if changes.get("placement__placement") == "SAS":
        gi["reference_distribution"]["reference_group"] = "SAS"
    res = run(gi)
    assert res["status"] == status
    assert [r["rule"] for r in res["rule_trace"]] == RULE_IDS
    for r in res["rule_trace"]:
        assert r["outcome"] in ("pass", "fail", "not_applicable")
        if r["outcome"] == "not_applicable":
            assert r["detail"] and r["effect"] is None and r["codes"] == []


def test_unresolved_placement_reports_g10_explicitly():
    res = run(mutate(placement__status="UNRESOLVED", placement__placement=None))
    g10 = rule(res, "G10")
    assert g10["outcome"] == "not_applicable" and "no resolved reference group" in g10["detail"]


# ---- G12 tri-state: true = compared & sensitive, false = compared & not sensitive, else not established -------------

def test_reference_sensitive_false_passes_g12():
    res = run(base_input())  # reference_sensitive: false = a comparison was made and found not sensitive
    assert res["status"] == "SUPPORTED" and rule(res, "G12")["outcome"] == "pass"


def test_reference_sensitive_true_is_raw_only():
    res = run(mutate(reference_distribution__reference_sensitive=True,
                     reference_distribution__reference_sensitive_pairs=[["FIN", "TSI"]]))
    assert res["status"] == "RAW_ONLY" and res["reason_codes"] == ["REFERENCE_SENSITIVE"]


@pytest.mark.parametrize("value", [None, "false", "False", 0, 1, [], {}, "not evaluable"])
def test_unestablished_reference_sensitivity_is_never_supported(value):
    gi = mutate(reference_distribution__reference_sensitive=value,
                reference_distribution__reference_sensitive_pairs=None)
    res = run(gi)
    assert res["status"] == "RAW_ONLY", res["rule_trace"]
    assert res["reason_codes"] == ["REFERENCE_SENSITIVITY_UNVERIFIED"]
    assert rule(res, "G12")["outcome"] == "fail"
    assert "reference_distribution.reference_sensitive" in res["evidence_missing"]
    assert res["allowed_claims"]["percentile"] is False


def test_missing_reference_sensitive_key_is_never_supported():
    gi = base_input()
    del gi["reference_distribution"]["reference_sensitive"]
    res = run(gi)
    assert res["status"] == "RAW_ONLY" and res["reason_codes"] == ["REFERENCE_SENSITIVITY_UNVERIFIED"]


def test_unverified_g12_explains_why_when_the_producer_says_so():
    gi = mutate(reference_distribution__reference_sensitive=None,
                reference_distribution__reference_sensitivity_assessable=False,
                reference_distribution__reference_sensitivity_detail="not evaluable: 1 defensible reference "
                                                                     "population(s) with >= 20 individuals (PEL)")
    detail = rule(run(gi), "G12")["detail"]
    assert "not evaluable" in detail and "PEL" in detail


def test_g12_not_applicable_without_a_resolved_group_regardless_of_sensitivity():
    res = run(mutate(placement__status="INTERMEDIATE", placement__placement=None,
                     reference_distribution__reference_sensitive=None))
    assert rule(res, "G12")["outcome"] == "not_applicable"
    assert res["reason_codes"] == ["TARGET_REFERENCE_UNRESOLVED"]
