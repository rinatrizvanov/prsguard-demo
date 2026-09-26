"""Tests for equity-lit-auditor. No network: Europe PMC is faked or replayed from the fixture."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import equity_lit_auditor as app  # noqa: E402
from equity_lit_extract import (  # noqa: E402
    PaperAudit, aggregate_records, audit_paper, extract_populations, parse_number, score_paper,
)
from equity_lit_geo import load_countries, shapes_by_iso3  # noqa: E402
from equity_lit_literature import (  # noqa: E402
    EuropePMCClient, FixtureClient, Paper, collect_papers, methods_from_fulltext_xml,
    paper_from_record, parse_seed,
)
from equity_lit_render import split_antimeridian  # noqa: E402


def pops(text):
    recs, panels, total = extract_populations(text, "abstract")
    return recs, aggregate_records(recs), panels, total


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_ancestry_with_sample_size_and_biobank(self):
        _, (anc, cty), _, _ = pops("We studied 452,264 individuals of European ancestry from the UK Biobank.")
        assert anc == {"EUR": 452264}
        assert cty == {"GBR": 452264}

    def test_n_equals_pattern(self):
        _, (anc, _), _, _ = pops("African Americans (n = 12,000) and Hispanic/Latino participants (n = 8,500) were included.")
        assert anc["AFR"] == 12000
        assert anc["AMR"] == 8500

    def test_demonym_implies_country_and_ancestry(self):
        _, (anc, cty), _, _ = pops("A GWAS in 191,787 Japanese participants from BioBank Japan.")
        assert anc == {"EAS": 191787}
        assert cty == {"JPN": 191787}

    def test_distinct_countries_are_summed(self):
        _, (anc, cty), _, _ = pops("We studied 4,210 Ghanaian adults and 2,975 Kenyan adults.")
        assert anc == {"AFR": 7185}
        assert cty == {"GHA": 4210, "KEN": 2975}

    def test_diaspora_recruited_in_host_country(self):
        _, (anc, cty), _, _ = pops("We recruited 44,190 British Bangladeshi and Pakistani participants in east London.")
        assert anc == {"SAS": 44190}
        assert cty == {"GBR": 44190}

    def test_non_participant_context_ignored(self):
        _, (anc, _), _, _ = pops("Polygenic scores derived in Europeans performed worse in 5,000 Nigerian adults.")
        assert "EUR" not in anc
        assert anc == {"AFR": 5000}

    def test_north_african_not_double_counted(self):
        _, (anc, _), _, _ = pops("We enrolled 900 North African participants.")
        assert anc == {"MID": 900}

    def test_reference_panels_not_counted(self):
        recs, (anc, _), panels, _ = pops("Imputation used the 1000 Genomes and gnomAD reference panels.")
        assert recs == [] and anc == {}
        assert panels == ["1000 Genomes", "gnomAD"]

    def test_years_percentages_and_loci_are_not_sample_sizes(self):
        _, (anc, _), _, _ = pops("In 2019 European participants showed 25% heritability across 112 loci.")
        assert anc == {"EUR": None}

    def test_ambiguous_country_names_skipped(self):
        recs, _, _, _ = pops("Samples were shipped to Georgia and analysed by Jordan et al.")
        assert recs == []

    @pytest.mark.parametrize("tok,val", [("12,345", 12345), ("1.2 million", 1200000), ("100k", 100000),
                                         ("857", 857), ("x", None)])
    def test_parse_number(self, tok, val):
        assert parse_number(tok) == val


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _paper(title, abstract, affs=()):
    return Paper(id="X", source="DEMO", title=title, abstract=abstract, affiliations=list(affs))


class TestScoring:
    def test_components_sum_to_score_and_respect_maxima(self):
        a = audit_paper(_paper("GWAS", "A multi-ancestry GWAS of 10,000 Europeans and 9,000 African Americans."))
        assert a.score == sum(c["points"] for c in a.components.values())
        assert all(0 <= c["points"] <= c["max"] for c in a.components.values())
        assert sum(c["max"] for c in a.components.values()) == 100

    def test_european_only_flag_and_caucasian_penalty(self):
        a = audit_paper(_paper("APOE", "We genotyped 3,120 Caucasian subjects."))
        assert "European-ancestry participants only" in a.flags
        assert any("deprecated racial term" in f for f in a.flags)
        assert a.components["descriptor_practice"]["points"] == 0

    def test_parachute_flag_when_no_local_author(self):
        a = audit_paper(_paper("BP", "Exome sequencing in 1,850 Nigerian adults.", ["Chicago, IL, USA"]))
        assert any("parachute" in f for f in a.flags)
        assert a.components["local_capacity_engagement"]["points"] == 0

    def test_local_author_earns_capacity_points(self):
        a = audit_paper(_paper("BP", "Exome sequencing in 1,850 Nigerian adults.",
                               ["College of Medicine, Ibadan, Nigeria"]))
        assert a.components["local_capacity_engagement"]["points"] == 10
        assert not any("parachute" in f for f in a.flags)

    def test_diverse_study_outscores_single_ancestry(self):
        diverse = audit_paper(_paper("T2D", "A trans-ancestry meta-analysis of 50,000 Europeans, 40,000 East Asian "
                                            "participants and 30,000 African Americans; genetic ancestry was inferred. "
                                            "Findings may not generalize to under-represented groups."))
        single = audit_paper(_paper("T2D", "A GWAS of 500,000 individuals of European ancestry."))
        assert diverse.score > single.score + 30

    def test_weak_cross_ancestry_phrase_needs_two_groups(self):
        a = audit_paper(_paper("Height", "GWAS in 1,000 Japanese participants found ancestry-specific variants."))
        assert a.components["cross_ancestry_analysis"]["points"] == 0

    def test_no_population_scores_zero_diversity(self):
        a = PaperAudit(key="k")
        score_paper(a, "We present a software tool.")
        assert a.components["participant_diversity"]["points"] == 0


# ---------------------------------------------------------------------------
# Literature client and cascade
# ---------------------------------------------------------------------------

EPMC_CORE = {
    "id": "123", "source": "MED", "pmid": "123", "pmcid": "PMC999", "doi": "10.1/x",
    "title": "A <i>GWAS</i> of asthma", "abstractText": "<h4>Methods</h4>We studied 1,000 Ugandan adults.",
    "pubYear": "2021", "isOpenAccess": "Y", "citedByCount": 7, "authorString": "A B, C D.",
    "journalInfo": {"journal": {"title": "J Genet"}},
    "authorList": {"author": [{"authorAffiliationDetailsList": {"authorAffiliation": [
        {"affiliation": "Makerere University, Kampala, Uganda"}]}}]},
    "meshHeadingList": {"meshHeading": [{"descriptorName": "Genome-Wide Association Study"}]},
}


class TestLiterature:
    def test_paper_from_record_normalises_core_result(self):
        p = paper_from_record(EPMC_CORE)
        assert p.key == "MED:123" and p.title == "A GWAS of asthma"
        assert "Methods" in p.abstract and "<h4>" not in p.abstract
        assert p.is_open_access and p.pmcid == "PMC999" and p.cited_by == 7
        assert p.affiliations == ["Makerere University, Kampala, Uganda"]
        assert p.is_genomic_study
        assert p.url == "https://europepmc.org/article/MED/123"

    def test_client_parses_search_references_citations(self):
        client = EuropePMCClient(delay=0)
        responses = {
            "search": {"resultList": {"result": [EPMC_CORE]}, "nextCursorMark": "*"},
            "MED/123/references": {"referenceList": {"reference": [{"id": "456", "source": "MED"}]}},
            "MED/123/citations": {"citationList": {"citation": [{"id": "789", "source": "MED"}]}},
        }

        def fake_get(url, params=None, timeout=None):
            path = url.split("/rest/")[1]
            r = Mock(status_code=200)
            r.json.return_value = responses[path]
            r.text = json.dumps(responses[path])
            r.raise_for_status = lambda: None
            return r

        client.session.get = fake_get
        assert client.search("asthma", limit=5)[0]["id"] == "123"
        assert client.references("MED", "123", 10) == [{"id": "456", "source": "MED"}]
        assert client.citations("MED", "123", 10) == [{"id": "789", "source": "MED"}]

    def test_methods_only_from_fulltext(self):
        xml = ("<article><body><sec><title>Introduction</title><p>Studies in Iceland.</p></sec>"
               "<sec sec-type='methods'><title>Methods</title><p>We recruited 500 Kenyan adults.</p></sec>"
               "<sec><title>Discussion</title><p>Future work in Brazil.</p></sec></body></article>")
        text = methods_from_fulltext_xml(xml)
        assert "Kenyan" in text and "Iceland" not in text and "Brazil" not in text
        assert methods_from_fulltext_xml("<not xml") == ""

    @pytest.mark.parametrize("seed,expected", [
        ("123", ("MED", "123")), ("PMID:123", ("MED", "123")), ("pmc555", ("PMC", "PMC555")),
        ("DOI:10.1/abc", ("DOI", "10.1/abc")), ("10.1/abc", ("DOI", "10.1/abc")), ("PPR:PPR1", ("PPR", "PPR1")),
    ])
    def test_parse_seed(self, seed, expected):
        assert parse_seed(seed) == expected

    def test_parse_seed_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_seed("not an id")

    def test_cascade_follows_both_directions_and_dedupes(self):
        client = FixtureClient(app.DEMO_FIXTURE)
        papers = collect_papers(client, "q", [], 25, "both", 1, 10, 80, False, log=lambda *_: None)
        keys = [p.key for p in papers]
        assert len(keys) == len(set(keys)) == 14
        via = {p.key: (p.via, p.parent) for p in papers}
        assert via["DEMO:D104"] == ("citation", "DEMO:D002")
        assert via["DEMO:D102"] == ("reference", "DEMO:D001")

    def test_cascade_respects_max_papers(self):
        client = FixtureClient(app.DEMO_FIXTURE)
        papers = collect_papers(client, "q", [], 25, "both", 2, 10, 11, False, log=lambda *_: None)
        assert len(papers) == 11

    def test_no_cascade(self):
        client = FixtureClient(app.DEMO_FIXTURE)
        papers = collect_papers(client, "q", [], 25, "none", 1, 10, 80, False, log=lambda *_: None)
        assert all(p.via == "search" for p in papers) and len(papers) == 9


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------

class TestGeo:
    def test_country_table(self):
        c = load_countries()
        assert len(c) > 240
        assert c["GBR"]["high_income"] and not c["NGA"]["high_income"]
        assert c["UGA"]["un_region"] == "Sub-Saharan Africa"
        assert "UK" in c["GBR"]["aliases"]

    def test_shapes_cover_major_countries(self):
        s = shapes_by_iso3()
        for iso in ("USA", "CHN", "IND", "NGA", "BRA", "GBR", "JPN", "UGA", "RUS"):
            assert iso in s

    def test_antimeridian_split(self):
        ring = [(170, 60), (180, 60), (180, 65), (-180, 65), (-170, 65), (-170, 60), (-180, 60), (180, 60), (170, 60)]
        parts = split_antimeridian(ring)
        assert len(parts) == 2
        for part in parts:
            lons = [p[0] for p in part]
            assert max(lons) - min(lons) <= 180


# ---------------------------------------------------------------------------
# End-to-end demo and output contract
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("equity_lit_demo")
    assert app.main(["--demo", "--output", str(out)]) == 0
    return out


class TestOutputContract:
    EXPECTED = [
        "report.md", "result.json",
        "figures/population_heatmap.png", "figures/population_map.html", "figures/ancestry_representation.png",
        "tables/papers.csv", "tables/population_records.csv", "tables/country_summary.csv",
        "tables/ancestry_summary.csv",
        "reproducibility/commands.sh", "reproducibility/environment.yml", "reproducibility/checksums.sha256",
    ]

    def test_every_documented_file_exists(self, demo_out):
        for rel in self.EXPECTED:
            assert (demo_out / rel).is_file(), rel
            assert (demo_out / rel).stat().st_size > 0, rel

    def test_skill_md_tree_matches_contract(self):
        tree = (SKILL_DIR / "SKILL.md").read_text().split("## Output Structure")[1].split("```")[1]
        for rel in self.EXPECTED:
            assert Path(rel).name in tree, rel

    def test_result_json_envelope(self, demo_out):
        res = json.loads((demo_out / "result.json").read_text())
        assert res["skill"] == "equity-lit-auditor"
        s = res["summary"]
        # 14 Europe PMC papers + 3 reached only through the synthetic PGS Catalog block
        assert s["papers_total"] == 17
        assert s["papers_with_population_data"] == 15
        assert s["papers_european_only"] == 4
        assert s["heatmap_metric"] == "participants"
        assert res["data"]["demo"] is True

    def test_country_summary(self, demo_out):
        rows = {r["iso3"]: r for r in csv.DictReader((demo_out / "tables/country_summary.csv").open())}
        assert int(rows["GBR"]["participants"]) == 452264 + 44190 + 20000   # + PGS development cohort
        assert int(rows["GHA"]["papers"]) == 2
        assert rows["PRI"]["participants"] == "0"   # reported without N

    def test_report_marks_demo_and_has_disclaimer(self, demo_out):
        report = (demo_out / "report.md").read_text()
        assert "SYNTHETIC" in report and "Demo mode" in report
        assert "not a medical device" in report
        assert "possible parachute research" in report

    def test_html_map_is_self_contained(self, demo_out):
        page = (demo_out / "figures/population_map.html").read_text()
        assert "<svg" in page and 'data-iso="GHA"' in page
        assert not re.search(r"<script[^>]+src=|<link[^>]+href=\"http", page)
        assert "prefers-color-scheme: dark" in page

    def test_rerun_is_deterministic(self, demo_out, tmp_path):
        app.main(["--demo", "--output", str(tmp_path)])
        a = (demo_out / "tables/papers.csv").read_text()
        b = (tmp_path / "tables/papers.csv").read_text()
        assert a == b


def test_cli_requires_a_source():
    with pytest.raises(SystemExit):
        app.parse_args([])
