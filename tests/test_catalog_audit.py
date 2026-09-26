"""Tests for the PGS Catalog cohort auditor (prsguard.catalog; ported from the hackathon prsguard_pgs_audit).

Offline tests run against the recorded PGS000001 snapshot in
``data/catalog_snapshot`` (captured from https://www.pgscatalog.org/rest on
2026-09-25). Corruption tests mutate copies of those real responses so every
contradiction is checked against otherwise-authentic metadata.

The live test only runs with RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "catalog_snapshot"
CORRUPTED_DIR = Path(__file__).resolve().parent / "fixtures" / "pgs_catalog_corrupted"


from prsguard import catalog as audit  # noqa: E402


def _json(rel: str) -> dict:
    return json.loads((SNAPSHOT_DIR / rel).read_text())


@pytest.fixture
def score() -> dict:
    return _json("PGS000001/score.json")


@pytest.fixture
def performance() -> list[dict]:
    return _json("PGS000001/performance_search_p1.json")["results"]


@pytest.fixture
def categories() -> dict:
    return _json("ancestry_categories.json")


def failed(evidence: dict) -> set[str]:
    return {c["check_id"] for c in evidence["consistency_checks"] if c["status"] == "fail"}


# ---------------------------------------------------------------------------
# PGS000001 from the recorded snapshot — the values observed in the challenge
# ---------------------------------------------------------------------------


def test_pgs000001_snapshot_resolves_with_observed_values():
    ev, raw = audit.run_cohort_audit("PGS000001", audit.SnapshotCatalogSource(SNAPSHOT_DIR))
    assert ev["status"] == "resolved", ev["consistency_checks"]
    assert ev["score"]["pgs_id"] == "PGS000001"
    assert ev["score"]["name"] == "PRS77_BC"
    assert ev["score"]["trait_reported"] == "Breast cancer"
    assert ev["score"]["variants_number"] == 77
    assert {"id": "MONDO_0004989", "label": "breast carcinoma"} in ev["score"]["trait_efo"]

    pub = ev["publication"]
    assert pub["pgp_id"] == "PGP000001"
    assert pub["pmid"] == "25855707"
    assert pub["doi"] == "10.1093/jnci/djv036"
    assert pub["first_author"] == "Mavaddat N"

    gwas = ev["source_gwas_ancestry"]
    assert gwas["distribution_pct"] == {"EUR": 100.0}
    assert gwas["n_individuals"] == 22627
    assert gwas["samples"][0]["gwas_catalog_id"] == "GCST001937"

    assert ev["development_ancestry"]["reported"] is False

    ev_anc = ev["evaluation_ancestry"]
    assert ev_anc["distribution_pct"] == {"EUR": 72.7, "EAS": 9.1, "NR": 18.2}
    assert ev_anc["sample_set_count"] == 11
    assert ev_anc["unit"] == "(publication, sample set) pairs"
    assert len(ev_anc["sample_sets"]) == 11
    assert ev_anc["sample_sets_by_code"] == {"EAS": 1, "EUR": 8, "NR": 2}
    assert ev_anc["codes"] == ["EAS", "EUR", "NR"]
    assert ev_anc["n_individuals_by_code"]["EAS"] == 6335
    pss = {s["pss_id"] for s in ev_anc["sample_sets"]}
    assert "PSS012310" in pss  # TPMI, the only East Asian evaluation


def test_snapshot_provenance_records_urls_and_checksums():
    ev, raw = audit.run_cohort_audit("PGS000001", audit.SnapshotCatalogSource(SNAPSHOT_DIR))
    prov = ev["provenance"]
    assert prov["mode"] == "snapshot"
    assert prov["api_base"] == "https://www.pgscatalog.org/rest"
    assert prov["catalog_release"]
    endpoints = {r["endpoint"] for r in prov["responses"]}
    assert {"score/PGS000001", "performance/search", "ancestry_categories"} <= endpoints
    for r in prov["responses"]:
        assert len(r["sha256"]) == 64
        assert r["url"].startswith("https://www.pgscatalog.org/rest/")
    assert len(raw) == len(prov["responses"])


def test_all_blocking_checks_pass_on_authentic_metadata(score, performance, categories):
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert failed(ev) == set()
    statuses = {c["check_id"]: c["status"] for c in ev["consistency_checks"]}
    for check in ("SCORE_ID_MATCH", "REQUIRED_FIELDS", "DISTRIBUTION_SUMS",
                  "ANCESTRY_CODES_KNOWN", "PERFORMANCE_SCORE_LINK",
                  "EVAL_SAMPLE_SET_COUNT", "EVAL_CODES_CROSSCHECK",
                  "EVAL_DISTRIBUTION_CROSSCHECK"):
        assert statuses[check] == "pass", check


# ---------------------------------------------------------------------------
# Deliberately corrupted / conflicting cohort metadata
# ---------------------------------------------------------------------------


def test_eval_distribution_that_does_not_sum_to_100_is_contradictory(score, performance, categories):
    score["ancestry_distribution"]["eval"]["dist"]["EUR"] = 122.7
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "DISTRIBUTION_SUMS" in failed(ev)


def test_eval_count_disagreeing_with_performance_sample_sets_is_contradictory(score, performance, categories):
    score["ancestry_distribution"]["eval"]["count"] = 12
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "EVAL_SAMPLE_SET_COUNT" in failed(ev)


def test_eval_ancestry_relabelled_in_score_endpoint_is_contradictory(score, performance, categories):
    # The score endpoint claims South Asian evaluation; the performance
    # sample sets say East Asian (TPMI). A SAS target must not be supported.
    dist = score["ancestry_distribution"]["eval"]["dist"]
    dist["SAS"] = dist.pop("EAS")
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "EVAL_CODES_CROSSCHECK" in failed(ev)


def test_shifted_eval_percentages_are_contradictory(score, performance, categories):
    dist = score["ancestry_distribution"]["eval"]["dist"]
    dist["EUR"], dist["NR"] = 70.0, 20.9
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "EVAL_DISTRIBUTION_CROSSCHECK" in failed(ev)


def test_unknown_ancestry_code_is_contradictory(score, performance, categories):
    score["ancestry_distribution"]["gwas"]["dist"] = {"XYZ": 100}
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "ANCESTRY_CODES_KNOWN" in failed(ev)


def test_performance_record_for_another_score_is_contradictory(score, performance, categories):
    performance[0]["associated_pgs_id"] = "PGS000002"
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "PERFORMANCE_SCORE_LINK" in failed(ev)


def test_unmappable_evaluation_ancestry_is_contradictory(score, performance, categories):
    for p in performance:
        if p["sampleset"]["id"] == "PSS012310":
            p["sampleset"]["samples"][0]["ancestry_broad"] = "Martian"
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "contradictory"
    assert "EVAL_CODES_CROSSCHECK" in failed(ev)


@pytest.mark.parametrize("mutate", [
    lambda s: s.pop("ancestry_distribution"),
    lambda s: s.__setitem__("variants_number", "77"),
    lambda s: s.__setitem__("variants_number", -1),
    lambda s: s.__setitem__("publication", None),
    lambda s: s.__setitem__("trait_reported", ""),
    lambda s: s["ancestry_distribution"].__setitem__("eval", {"dist": "EUR"}),
])
def test_missing_or_mistyped_required_fields_are_unresolved(score, performance, categories, mutate):
    mutate(score)
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "unresolved"
    assert "REQUIRED_FIELDS" in failed(ev)


def test_response_for_a_different_score_is_unresolved(score, performance, categories):
    score["id"] = "PGS000002"
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["status"] == "unresolved"
    assert "SCORE_ID_MATCH" in failed(ev)


def test_score_never_evaluated_resolves_with_no_evaluation_codes(score, categories):
    score["ancestry_distribution"]["eval"] = {"dist": {}, "count": 0}
    ev = audit.audit_score_metadata("PGS000001", score, [], categories)
    assert ev["status"] == "resolved", failed(ev)
    assert ev["evaluation_ancestry"]["codes"] == []


@pytest.mark.parametrize("query,ok", [
    ("Breast cancer", True), ("breast CANCER", True), ("breast carcinoma", True),
    ("breast", True), ("type 2 diabetes", False),
])
def test_requested_trait_must_match_catalog_trait(score, performance, categories, query, ok):
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories, trait_query=query)
    assert ("TRAIT_MATCH" in failed(ev)) is (not ok)


def test_scoring_file_header_publication_mismatch_is_contradictory(score, performance, categories):
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories,
                                    scoring_file_header={"pgs_id": "PGS000001", "pgp_id": "PGP000999"})
    assert ev["status"] == "contradictory"
    assert "SCORING_FILE_PUBLICATION_MATCH" in failed(ev)


def test_pmid_is_normalised_to_string(score, performance, categories):
    ev = audit.audit_score_metadata("PGS000001", score, performance, categories)
    assert ev["publication"]["pmid"] == "25855707"


# ---------------------------------------------------------------------------
# Snapshot integrity and fetch failures fail closed
# ---------------------------------------------------------------------------


def test_tampered_snapshot_file_is_unresolved(tmp_path):
    snap = tmp_path / "snap"
    shutil.copytree(SNAPSHOT_DIR, snap)
    path = snap / "PGS000001" / "score.json"
    doc = json.loads(path.read_text())
    doc["variants_number"] = 78
    path.write_text(json.dumps(doc))
    ev, _ = audit.run_cohort_audit("PGS000001", audit.SnapshotCatalogSource(snap))
    assert ev["status"] == "unresolved"
    assert "checksum" in ev["detail"].lower()


def test_missing_score_in_snapshot_is_unresolved(tmp_path):
    ev, _ = audit.run_cohort_audit("PGS999999", audit.SnapshotCatalogSource(SNAPSHOT_DIR))
    assert ev["status"] == "unresolved"
    assert "PGS999999" in ev["detail"]


def test_missing_performance_records_are_unresolved(tmp_path):
    snap = tmp_path / "snap"
    shutil.copytree(SNAPSHOT_DIR, snap)
    (snap / "PGS000001" / "performance_search_p1.json").unlink()
    manifest = json.loads((snap / "SNAPSHOT.json").read_text())
    manifest["files"].pop("PGS000001/performance_search_p1.json")
    (snap / "SNAPSHOT.json").write_text(json.dumps(manifest))
    ev, _ = audit.run_cohort_audit("PGS000001", audit.SnapshotCatalogSource(snap))
    assert ev["status"] == "unresolved"


def test_network_failure_is_unresolved_not_an_exception():
    class Broken:
        mode = "live"
        api_base = audit.API_BASE

        def fetch(self, endpoint, params=None):
            raise audit.MetadataUnavailable("connection refused")

    ev, raw = audit.run_cohort_audit("PGS000001", Broken())
    assert ev["status"] == "unresolved"
    assert "connection refused" in ev["detail"]
    assert raw == []


def test_invalid_pgs_id_is_rejected_before_any_request():
    class Exploding:
        mode = "live"
        api_base = audit.API_BASE

        def fetch(self, endpoint, params=None):  # pragma: no cover - must not run
            raise AssertionError("no request expected")

    ev, _ = audit.run_cohort_audit("../../etc/passwd", Exploding())
    assert ev["status"] == "unresolved"


# ---------------------------------------------------------------------------
# Ancestry vocabulary mapping (PGS Catalog /rest/ancestry_categories)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,code", [
    ("European", "EUR"), ("east asian", "EAS"), ("Not reported", "NR"), ("NR", "NR"),
    ("Sub-Saharan African, African American or Afro-Caribbean", "AFR"),
    ("Greater Middle Eastern (Middle Eastern, North African or Persian)", "GME"),
    ("European, East Asian", "MAE"),
    ("East Asian, South Asian", "MAO"),
    ("Multi-ancestry (including European)", "MAE"),
    ("Martian", None), ("", None), (None, None),
])
def test_ancestry_broad_mapping(categories, label, code):
    vocab = audit.build_vocabulary(categories)
    assert audit.map_ancestry_broad(label, vocab) == code


# ---------------------------------------------------------------------------
# Live PGS Catalog (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1" and os.getenv("PRSGUARD_LIVE_TESTS") != "1",
                    reason="set RUN_LIVE_TESTS=1 for live PGS Catalog calls")
def test_live_pgs000001_matches_observed_catalog_values(tmp_path):
    ev, raw = audit.run_cohort_audit("PGS000001", audit.LiveCatalogSource())
    assert ev["status"] == "resolved", ev["detail"]
    assert ev["score"]["trait_reported"] == "Breast cancer"
    assert ev["score"]["variants_number"] == 77
    assert ev["source_gwas_ancestry"]["distribution_pct"] == {"EUR": 100.0}
    assert ev["source_gwas_ancestry"]["n_individuals"] == 22627
    assert ev["evaluation_ancestry"]["distribution_pct"] == {"EUR": 72.7, "EAS": 9.1, "NR": 18.2}
    assert ev["evaluation_ancestry"]["sample_set_count"] == 11
    assert ev["publication"]["pmid"] == "25855707"
    assert ev["publication"]["doi"] == "10.1093/jnci/djv036"
    assert ev["provenance"]["mode"] == "live"
    assert all(r["retrieved_at"] for r in ev["provenance"]["responses"])
