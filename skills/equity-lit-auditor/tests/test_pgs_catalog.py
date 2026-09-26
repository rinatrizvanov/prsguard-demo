"""PGS Catalog integration tests (no network: fixture replay and a faked session)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import equity_lit_auditor as app  # noqa: E402
from equity_lit_extract import audit_paper  # noqa: E402
from equity_lit_literature import Paper  # noqa: E402
from equity_lit_pgs import (  # noqa: E402
    PGSCatalogClient, PGSFixtureClient, PGSLink, broad_to_codes, curated_records, gather, pub_seed,
    stage_ancestry,
)

QUIET = dict(log=lambda *_: None)


@pytest.fixture
def fixture_client():
    return PGSFixtureClient(app.DEMO_FIXTURE)


class TestMapping:
    @pytest.mark.parametrize("label,codes", [
        ("European", ["EUR"]),
        ("African American or Afro-Caribbean", ["AFR"]),
        ("Sub-Saharan African", ["AFR"]),
        ("Greater Middle Eastern (Middle Eastern, North African or Persian)", ["MID"]),
        ("East Asian", ["EAS"]),
        ("South East Asian", ["EAS"]),
        ("South Asian", ["SAS"]),
        ("Asian unspecified", ["ASN"]),
        ("Hispanic or Latin American", ["AMR"]),
        ("Oceanian", ["OCE"]),
        ("Multi-ancestry (including European)", ["OTH"]),
        ("Other admixed ancestry", ["OTH"]),
        ("Not reported", ["NR"]),
        ("NR", ["NR"]),
        ("European, East Asian", ["EUR", "EAS"]),
        ("", ["NR"]),
    ])
    def test_broad_to_codes(self, label, codes):
        assert broad_to_codes(label) == codes

    @pytest.mark.parametrize("pub,seed", [
        ({"PMID": 25855707}, "MED:25855707"),
        ({"PMID": "25855707"}, "MED:25855707"),
        ({"PMID": None, "doi": "10.1/x"}, "DOI:10.1/x"),
        ({"PMID": "DEMO:D001"}, "DEMO:D001"),
        ({}, None),
        (None, None),
    ])
    def test_pub_seed(self, pub, seed):
        assert pub_seed(pub) == seed


class TestGather:
    def test_trait_links_every_stage(self, fixture_client):
        res = gather(fixture_client, "type 2 diabetes", [], 50, True, **QUIET)
        assert [s["id"] for s in res.scores] == ["PGSDEMO01", "PGSDEMO02", "PGSDEMO03"]
        stages = {(l.pgs_id, l.stage, l.seed) for l in res.links}
        assert ("PGSDEMO01", "GWAS", "DEMO:D001") in stages          # variants from source GWAS
        assert ("PGSDEMO01", "development", "DEMO:D201") in stages   # score publication
        assert ("PGSDEMO01", "evaluation", "DEMO:D104") in stages    # performance publication
        assert ("PGSDEMO03", "GWAS", "DEMO:D102") in stages
        assert "DEMO:D202" in res.seeds and "DEMO:D203" in res.seeds

    def test_without_evaluation(self, fixture_client):
        res = gather(fixture_client, "type 2 diabetes", [], 50, False, **QUIET)
        assert not any(l.stage == "evaluation" for l in res.links)

    def test_score_ids_and_cap(self, fixture_client):
        res = gather(fixture_client, None, ["PGSDEMO03", "PGSDEMO01"], 1, False, **QUIET)
        assert len(res.scores) == 1

    def test_stage_ancestry_counts_reused_gwas_once(self, fixture_client):
        res = gather(fixture_client, "type 2 diabetes", [], 50, True, **QUIET)
        res.links.append(PGSLink("DEMO:D001", "PGSDEMO99", "GWAS", {},
                                 [{"sample_number": 452264, "ancestry_broad": "European"}]))
        st = stage_ancestry(res)
        assert st["GWAS"]["EUR"] == 452264 + 180834 + 29193
        assert st["GWAS"]["AFR"] == 56092
        assert st["development"] == {"EUR": 20000, "OTH": 12000, "NR": 5000}
        assert st["evaluation"]["AFR"] == 4210 + 2975


class TestCuratedRecords:
    def test_countries_and_sizes(self):
        link = PGSLink("MED:1", "PGS1", "GWAS", {}, [
            {"sample_number": 1000, "ancestry_broad": "European", "ancestry_country": "U.K., Finland"},
            {"sample_number": 300, "ancestry_broad": "Sub-Saharan African", "ancestry_country": "Uganda"},
        ])
        recs = curated_records(link)
        by = {(r.ancestry, r.iso3): r.n for r in recs}
        assert by[("EUR", None)] == 1000
        assert by[("AFR", None)] == 300
        assert by[("AFR", "UGA")] == 300
        assert by[("EUR", "GBR")] is None and by[("EUR", "FIN")] is None   # N not split across countries
        assert all(r.confidence == "curated" and r.kind == "pgs_catalog" for r in recs)

    def test_curated_supersedes_text(self):
        paper = Paper(id="1", source="MED", title="PRS", abstract="A score trained in 5,000 Europeans.")
        link = PGSLink("MED:1", "PGS1", "development", {}, [
            {"sample_number": 5000, "ancestry_broad": "East Asian", "ancestry_country": "Japan"}])
        a = audit_paper(paper, curated_records(link))
        assert a.ancestry_n == {"EAS": 5000}
        assert a.country_n == {"JPN": 5000}
        assert a.text_ancestry_n == {"EUR": 5000}
        assert a.source.startswith("PGS Catalog")

    def test_not_reported_does_not_count_as_diverse(self):
        paper = Paper(id="1", source="MED", title="PRS", abstract="")
        link = PGSLink("MED:1", "PGS1", "development", {}, [{"sample_number": 5000, "ancestry_broad": "NR"}])
        a = audit_paper(paper, curated_records(link))
        assert a.components["participant_diversity"]["points"] == 0
        assert "ancestry not reported" in a.flags

    def test_text_countries_kept_alongside_curated(self):
        paper = Paper(id="1", source="MED", title="PRS", abstract="We also recruited 800 participants in Ghana.")
        link = PGSLink("MED:1", "PGS1", "GWAS", {}, [
            {"sample_number": 5000, "ancestry_broad": "European", "ancestry_country": "U.K."}])
        a = audit_paper(paper, curated_records(link))
        assert a.country_n == {"GBR": 5000, "GHA": 800}
        assert a.ancestry_n == {"EUR": 5000}


class TestClient:
    def test_pagination_follows_next(self):
        client = PGSCatalogClient(delay=0)
        pages = {
            "https://www.pgscatalog.org/rest/score/search": {"results": [{"id": "PGS1"}], "next": "https://next/page2"},
            "https://next/page2": {"results": [{"id": "PGS2"}], "next": None},
        }

        def fake_get(url, params=None, timeout=None):
            r = Mock(status_code=200)
            r.json.return_value = pages[url]
            r.raise_for_status = lambda: None
            return r

        client.session.get = fake_get
        assert [s["id"] for s in client.scores_for_trait("EFO_1", 10)] == ["PGS1", "PGS2"]


@pytest.fixture(scope="module")
def pgs_demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("pgs_demo")
    assert app.main(["--demo", "--output", str(out)]) == 0
    return out


class TestEndToEnd:
    def test_pgs_outputs_exist(self, pgs_demo):
        for rel in ("tables/pgs_scores.csv", "tables/pgs_links.csv", "figures/pgs_stage_ancestry.png"):
            assert (pgs_demo / rel).is_file(), rel

    def test_pgs_papers_join_the_audit(self, pgs_demo):
        rows = {r["key"]: r for r in csv.DictReader((pgs_demo / "tables/papers.csv").open())}
        assert "DEMO:D201" in rows                       # reached only through PGS Catalog
        assert "DEMO:D203" in rows                       # not in Europe PMC: stub from PGS publication
        assert rows["DEMO:D203"]["title"].startswith("[SYNTHETIC]")
        assert "PGSDEMO02" in rows["DEMO:D002"]["pgs"]
        assert rows["DEMO:D002"]["population_source"].startswith("PGS Catalog")

    def test_summary_and_report(self, pgs_demo):
        res = json.loads((pgs_demo / "result.json").read_text())
        assert res["summary"]["pgs_scores"] == 3
        assert res["data"]["pgs"]["stage_ancestry"]["GWAS"]["EUR"] > 0
        report = (pgs_demo / "report.md").read_text()
        assert "## PGS Catalog" in report
        assert "Extraction check" in report
        assert "PGSDEMO01" in report

    def test_curated_countries_reach_the_map(self, pgs_demo):
        rows = {r["iso3"]: r for r in csv.DictReader((pgs_demo / "tables/country_summary.csv").open())}
        assert "FIN" in rows and "JPN" in rows


def test_pgs_trait_alone_is_a_valid_source():
    args = app.parse_args(["--pgs-trait", "breast cancer", "--output", "x"])
    assert args.pgs_trait == "breast cancer"


def test_runner_forwards_value_less_flags(tmp_path):
    """clawbio.py run equity-lit must pass --no-pgs-eval / --no-fulltext through its allowlist."""
    from clawbio.cli import run_skill
    res = run_skill("equity-lit", output_dir=str(tmp_path), demo=True,
                    extra_args=["--no-pgs-eval", "--no-fulltext", "--metric", "papers"])
    assert res["success"], res["stderr"]
    settings = json.loads((tmp_path / "result.json").read_text())["data"]["settings"]
    assert settings["no_pgs_eval"] is True
    assert settings["no_fulltext"] is True
    assert settings["metric"] == "papers"
