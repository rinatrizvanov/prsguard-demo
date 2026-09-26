"""Regression tests for the PRSGuard integration of equity-lit-auditor.

Every bug below was found in live runs against Europe PMC and the PGS Catalog on
2026-09-26 (see docs/equity-lit-integration.md in the PRSGuard repo). The fixtures are
small, hand-built copies of the real response shapes; no test here touches the network
except the ones marked ``network`` at the bottom (opt-in: RUN_LIVE_TESTS=1 or
PRSGUARD_LIVE_TESTS=1).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

import pytest
import requests

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import equity_lit_auditor as app  # noqa: E402
from equity_lit_extract import aggregate_records, audit_paper, extract_populations  # noqa: E402
from equity_lit_literature import EuropePMCClient, Paper, paper_from_record  # noqa: E402
from equity_lit_pgs import (  # noqa: E402
    PGSCatalogClient, _match_trait, curated_records, gather, stage_ancestry,
)
from equity_lit_render import GROUP_LABELS, fold_stage_groups  # noqa: E402

QUIET = {"log": lambda *_: None}
LIVE = os.getenv("RUN_LIVE_TESTS") == "1" or os.getenv("PRSGUARD_LIVE_TESTS") == "1"

# ---------------------------------------------------------------------------
# Recorded shapes (trimmed from live PGS Catalog responses, 2026-09-26)
# ---------------------------------------------------------------------------

SCOTT_2017 = 28566273   # DIAGRAM T2D GWAS: 159,208 Europeans, two GWAS Catalog accessions


def _gwas_sample(countries: str, gcst: str) -> dict:
    return {"sample_number": 159208, "ancestry_broad": "European", "ancestry_country": countries,
            "source_GWAS_catalog": gcst, "source_PMID": SCOTT_2017, "source_DOI": None,
            "cohorts": [{"name_short": "DIAGRAM"}, {"name_short": "GERA"}]}


def _score(pgs_id: str) -> dict:
    return {
        "id": pgs_id, "name": pgs_id, "trait_reported": "Type 2 diabetes", "variants_number": 100,
        "publication": {"id": f"PGP{pgs_id[-3:]}", "PMID": 30000000 + int(pgs_id[-3:]), "doi": f"10.1/{pgs_id}",
                        "title": f"Score {pgs_id}", "date_publication": "2020-01-01"},
        # Same people, two accessions, country list in a different order (as served for PGS000014).
        "samples_variants": [_gwas_sample("France, Germany, U.K., NR, U.S.", "GCST004774"),
                             _gwas_sample("U.S., France, Germany, U.K., NR", "GCST004773")],
        "samples_training": [],
    }


UKB_EVAL_SET = {"id": "PSS001117", "samples": [
    {"sample_number": 68229, "ancestry_broad": "European", "ancestry_country": "U.K.",
     "cohorts": [{"name_short": "UKB"}]}]}


def _perf(pgs_id: str, ppm: int) -> dict:
    # One performance record per metric / covariate model, all on the same sampleset.
    return {"id": f"PPM{ppm:06d}", "associated_pgs_id": pgs_id, "sampleset": UKB_EVAL_SET,
            "publication": {"id": "PGP000999", "PMID": 33563654, "doi": "10.1/eval", "title": "Evaluation"}}


class FakePGS:
    """PGSCatalogClient interface over constructed records."""

    def __init__(self, scores: dict, perf: dict, traits: list | None = None):
        self.scores, self.perf, self.traits = scores, perf, traits or []

    def search_traits(self, term):
        return self.traits

    def scores_for_trait(self, efo_id, limit):
        self.last_count = len(self.scores)
        return list(self.scores.values())[:limit]

    def scores_by_ids(self, ids):
        return [self.scores[i] for i in ids if i in self.scores]

    def performance(self, pgs_id, limit=500):
        found = self.perf.get(pgs_id, [])
        self.last_count = len(found)
        return found[:limit]


@pytest.fixture
def reused_gwas():
    """Three scores built on the same GWAS, all evaluated 12x on one UKB sampleset."""
    scores = {s: _score(s) for s in ("PGS000014", "PGS000020", "PGS000031")}
    perf = {s: [_perf(s, 23 + i) for i in range(12)] for s in scores}
    return gather(FakePGS(scores, perf), None, list(scores), 50, True, **QUIET)


# ---------------------------------------------------------------------------
# Bug 1: the same curated sample set was counted once per score / accession / metric
# ---------------------------------------------------------------------------

class TestCuratedSampleDedup:
    def test_paper_level_gwas_counted_once(self, reused_gwas):
        seed = f"MED:{SCOTT_2017}"
        recs = [r for l in reused_gwas.links if l.seed == seed for r in curated_records(l)]
        paper = Paper(id=str(SCOTT_2017), source="MED", title="An expanded GWAS of type 2 diabetes", abstract="")
        a = audit_paper(paper, recs)
        # Was 159,208 x 6 = 955,248 (3 scores x 2 accessions) before the fix.
        assert a.ancestry_n == {"EUR": 159208}

    def test_evaluation_sampleset_linked_once_per_score(self, reused_gwas):
        ev = [l for l in reused_gwas.links if l.stage == "evaluation"]
        assert len(ev) == 3                    # was 36: one link per performance record
        assert {l.pgs_id for l in ev} == {"PGS000014", "PGS000020", "PGS000031"}

    def test_per_score_table_counts_each_set_once(self, reused_gwas):
        summary = app.summarise_pgs(reused_gwas, stage_ancestry(reused_gwas), [], [])
        row = {r["pgs_id"]: r for r in summary["scores"]}["PGS000014"]
        assert row["gwas_ancestry"] == "EUR 159,208"          # was EUR 318,416
        assert row["evaluation_ancestry"] == "EUR 68,229"     # was EUR 818,748

    def test_stage_figure_counts_each_set_once(self, reused_gwas):
        st = stage_ancestry(reused_gwas)
        assert st["GWAS"] == {"EUR": 159208}
        assert st["evaluation"] == {"EUR": 68229}

    def test_distinct_sets_in_one_stage_are_still_summed(self):
        link_samples = [{"sample_number": 1000, "ancestry_broad": "European"},
                        {"sample_number": 300, "ancestry_broad": "European"}]
        from equity_lit_pgs import PGSLink
        a = audit_paper(Paper(id="1", source="MED", title="t", abstract=""),
                        curated_records(PGSLink("MED:1", "PGS1", "evaluation", {}, link_samples)))
        assert a.ancestry_n == {"EUR": 1300}


# ---------------------------------------------------------------------------
# Bug 2: score/search ignores include_children, so child-trait scores were missed
# ---------------------------------------------------------------------------

BREAST_CANCER_TRAIT = {   # trait/search result shape, trimmed
    "id": "MONDO_0007254", "label": "breast cancer", "trait_synonyms": ["breast cancer", "primary breast cancer"],
    "associated_pgs_ids": ["PGS018525", "PGS018526"],
    "child_associated_pgs_ids": ["PGS000004", "PGS000001", "PGS000007"],
}


class TestTraitScoresIncludeChildren:
    def _client(self):
        client = PGSCatalogClient(delay=0)
        direct = [{"id": "PGS018525"}, {"id": "PGS018526"}]
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append((url, dict(params or {})))
            r = requests.models.Response()
            r.status_code = 200
            if url.endswith("trait/search"):
                body = {"count": 1, "next": None, "results": [BREAST_CANCER_TRAIT]}
            elif "pgs_ids" in (params or {}):
                ids = params["pgs_ids"].split(",")
                body = {"count": len(ids), "next": None, "results": [{"id": i} for i in ids]}
            else:   # trait_id search: the live API returns direct associations only
                body = {"count": len(direct), "next": None, "results": direct}
            r._content = json.dumps(body).encode()
            return r

        client.session.get = fake_get
        return client, calls

    def test_child_trait_scores_are_audited_in_id_order(self):
        client, calls = self._client()
        res = gather(client, "breast cancer", [], 3, False, **QUIET)
        assert [s["id"] for s in res.scores] == ["PGS000001", "PGS000004", "PGS000007"]
        assert res.traits[0]["scores_available"] == 5
        assert res.traits[0]["match"] == "exact label"
        assert not any("trait_id" in p for _, p in calls)   # the ignored-parameter search is not used

    def test_trait_without_id_lists_falls_back_to_trait_search(self):
        trait = {"id": "EFO_1", "label": "x"}
        client = FakePGS({"PGS1": {"id": "PGS1", "samples_variants": [], "publication": {}}}, {}, [trait])
        res = gather(client, "x", [], 5, False, **QUIET)
        assert [s["id"] for s in res.scores] == ["PGS1"]


class TestTraitMatching:
    TRAITS = ({"id": "A", "label": "type 1 diabetes mellitus", "trait_synonyms": ["T1D"]},
              {"id": "B", "label": "type 2 diabetes mellitus", "trait_synonyms": ["T2D", "type 2 diabetes"]})

    def test_exact_synonym_beats_substring(self):
        m = _match_trait(list(self.TRAITS), "t2d")
        assert [t["id"] for t in m] == ["B"] and m[0]["match"] == "exact synonym"

    def test_last_resort_is_labelled(self):
        m = _match_trait(list(self.TRAITS), "insulin resistance")
        assert m and all(t["match"].startswith("first search hits") for t in m)


def test_unknown_pgs_ids_are_reported():
    msgs = []
    res = gather(FakePGS({"PGS000014": _score("PGS000014")}, {}), None, ["PGS000014", "PGS999999"], 5, False,
                 log=msgs.append)
    assert [s["id"] for s in res.scores] == ["PGS000014"]
    assert any("warning:" in m and "PGS999999" in m for m in msgs)


def test_truncated_performance_list_is_reported():
    scores = {"PGS000014": _score("PGS000014")}
    many = {"PGS000014": [_perf("PGS000014", i) for i in range(5)]}
    client = FakePGS(scores, many)
    client.performance = lambda pid, limit=500: (setattr(client, "last_count", 900), many[pid][:2])[1]
    msgs = []
    gather(client, None, ["PGS000014"], 5, True, log=msgs.append)
    assert any("read 2 of 900" in m and "warning:" in m for m in msgs)


# ---------------------------------------------------------------------------
# Bug 3: negated ancestry terms were read as the group they negate
# ---------------------------------------------------------------------------

class TestNegatedAncestryTerms:
    def _anc(self, text):
        recs, _, _ = extract_populations(text, "abstract")
        return aggregate_records(recs)[0]

    def test_non_european_is_not_european(self):
        # Graham et al. 2021 (PMID 34887591) abstract, flagged "European-ancestry participants only" before the fix.
        text = ("Here we conduct a multi-ancestry, genome-wide genetic discovery meta-analysis of lipid levels in "
                "approximately 1.65 million individuals, including 350,000 of non-European ancestries.")
        assert self._anc(text) == {"OTH": 350000}

    def test_non_hispanic_white_and_black(self):
        anc = self._anc("We enrolled 5,000 non-Hispanic white participants and 2,000 non-Hispanic Black participants.")
        assert anc == {"EUR": 5000, "AFR": 2000}      # was {"AMR": 5000, ...}

    def test_plain_terms_unchanged(self):
        assert self._anc("We studied 4,000 Hispanic participants.") == {"AMR": 4000}
        assert self._anc("A GWAS of 500,000 individuals of European ancestry.") == {"EUR": 500000}

    def test_paper_not_flagged_european_only(self):
        a = audit_paper(Paper(id="1", source="MED", title="Lipids GWAS",
                              abstract="A GWAS of 1.65 million individuals, including 350,000 of non-European "
                                       "ancestries, and 1.3 million individuals of European ancestry."))
        assert "European-ancestry participants only" not in a.flags
        assert a.components["participant_diversity"]["points"] > 0


class TestExcludedPopulationsAreNotParticipants:
    def _anc(self, text):
        recs, _, _ = extract_populations(text, "abstract")
        return aggregate_records(recs)

    def test_wtccc_exclusion_clause(self):
        # WTCCC 2007 (PMID 17554300) abstract: read as OTH participants once "non-European" stopped
        # being read as European; the population is excluded, not studied.
        anc, cty = self._anc("We have shown that, provided individuals with non-European ancestry are excluded, the "
                             "extent of population stratification in the British population is generally modest.")
        assert anc == {} and cty == {"GBR": None}

    @pytest.mark.parametrize("text", [
        "Samples of non-European ancestry (n = 1,234) were excluded.",
        "We excluded 250 participants of African ancestry.",
    ])
    def test_excluded_groups_dropped(self, text):
        assert self._anc(text) == ({}, {})

    @pytest.mark.parametrize("text,anc", [
        ("After excluding related individuals, 5,000 Nigerian adults remained.", {"AFR": 5000}),
        ("12,000 Europeans were included, and 300 duplicates were excluded.", {"EUR": 12000}),
    ])
    def test_exclusion_elsewhere_in_sentence_keeps_participants(self, text, anc):
        assert self._anc(text)[0] == anc


def test_stage_figure_keeps_unspecified_asian_separate():
    folded = fold_stage_groups({"EUR": 100, "ASN": 5, "OTH": 3, "XYZ": 1})
    assert folded == {"EUR": 100, "ASN": 5, "OTHER": 4}
    assert GROUP_LABELS["ASN"] == "Asian (unspecified)"


# ---------------------------------------------------------------------------
# Synthetic data can never pass as real
# ---------------------------------------------------------------------------

LABEL = "SYNTHETIC DEMO"


@pytest.fixture(scope="module")
def demo_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("provenance_demo")
    assert app.main(["--demo", "--output", str(out)]) == 0
    return out


def _png_text(path: Path) -> dict:
    from PIL import Image
    with Image.open(path) as im:
        return dict(im.text)


class TestSyntheticLabelling:
    def test_result_json_flags(self, demo_out):
        res = json.loads((demo_out / "result.json").read_text())
        assert res["synthetic"] is True and res["data_provenance"] == LABEL          # top of the envelope
        assert res["summary"]["synthetic"] is True and res["summary"]["data_provenance"] == LABEL
        assert res["data"]["synthetic"] is True and res["data"]["provenance"]["synthetic"] is True
        assert all("SYNTHETIC" in v for v in res["datasets"].values())

    def test_every_table_row_is_tagged(self, demo_out):
        tables = sorted((demo_out / "tables").glob("*.csv"))
        assert len(tables) == 6
        for t in tables:
            rows = list(csv.DictReader(t.open()))
            assert rows, t.name
            assert next(iter(rows[0])) == "data_provenance", t.name
            assert {r["data_provenance"] for r in rows} == {LABEL}, t.name

    def test_every_figure_is_labelled(self, demo_out):
        pngs = sorted((demo_out / "figures").glob("*.png"))
        assert {p.name for p in pngs} == {"population_heatmap.png", "ancestry_representation.png",
                                          "pgs_stage_ancestry.png"}
        for p in pngs:
            meta = _png_text(p)
            assert meta["data_provenance"] == LABEL and meta["synthetic"] == "true", p.name
            assert LABEL in meta["Title"], p.name
        assert _png_text(demo_out / "figures/pgs_stage_ancestry.png")["Title"] == \
            "PGS Catalog: ancestry of participants at each stage (SYNTHETIC DEMO)"

    def test_html_map_is_labelled(self, demo_out):
        page = (demo_out / "figures/population_map.html").read_text()
        assert f'data-provenance="{LABEL}"' in page and 'data-synthetic="true"' in page
        assert re.search(r"<title>[^<]*SYNTHETIC DEMO[^<]*</title>", page)
        assert re.search(r"<h1[^>]*>[^<]*SYNTHETIC DEMO", page)
        assert 'role="alert"' in page and f">{LABEL}</text>" in page   # banner + SVG watermark

    def test_every_report_heading_is_labelled(self, demo_out):
        lines = (demo_out / "report.md").read_text().splitlines()
        assert LABEL in lines[0]
        headings = [ln for ln in lines if ln.startswith("#")]
        assert len(headings) > 10
        assert all("SYNTHETIC" in h for h in headings), [h for h in headings if "SYNTHETIC" not in h]

    def test_stdout_is_labelled(self, tmp_path, capsys):
        app.main(["--demo", "--output", str(tmp_path)])
        assert capsys.readouterr().out.startswith(f"[{LABEL}] ")


# ---------------------------------------------------------------------------
# Live mode: never falls back to the fixture, failures are loud or reported
# ---------------------------------------------------------------------------

EPMC_RECORD = {
    "id": "123", "source": "MED", "pmid": "123", "pmcid": "PMC999", "doi": "10.1/x",
    "title": "A GWAS of asthma", "abstractText": "We studied 1,000 Ugandan adults.", "pubYear": "2021",
    "isOpenAccess": "N", "citedByCount": 7, "journalInfo": {"journal": {"title": "J Genet"}},
    "authorList": {"author": [{"authorAffiliationDetailsList": {"authorAffiliation": [
        {"affiliation": "Makerere University, Kampala, Uganda"}]}}]},
}


@pytest.fixture
def no_fixture(monkeypatch):
    """Fail the test if live mode ever touches the synthetic fixture."""
    def boom(*_a, **_k):
        raise AssertionError("live mode loaded the synthetic demo fixture")
    monkeypatch.setattr(app, "FixtureClient", boom)
    monkeypatch.setattr(app, "PGSFixtureClient", boom)
    monkeypatch.setattr("equity_lit_literature.time.sleep", lambda *_: None)
    monkeypatch.setattr("equity_lit_pgs.time.sleep", lambda *_: None)


def _fake_get(routes):
    def get(self, url, params=None, timeout=None):
        for frag, body in routes.items():
            if frag in url:
                if isinstance(body, Exception):
                    raise body
                r = requests.models.Response()
                r.status_code = 200
                r._content = json.dumps(body).encode()
                return r
        raise AssertionError(f"unexpected URL {url}")
    return get


class TestLiveModeHonesty:
    def test_network_failure_fails_loudly_without_demo_fallback(self, tmp_path, monkeypatch, capsys, no_fixture):
        monkeypatch.setattr(requests.Session, "get", _fake_get({"": requests.ConnectionError("offline")}))
        assert app.main(["--query", "asthma GWAS", "--output", str(tmp_path)]) == 3
        assert not (tmp_path / "report.md").exists() and not (tmp_path / "result.json").exists()
        assert "never replaced by demo data" in capsys.readouterr().err

    def test_live_outputs_are_marked_live_not_synthetic(self, tmp_path, monkeypatch, no_fixture):
        monkeypatch.setattr(requests.Session, "get", _fake_get(
            {"/search": {"resultList": {"result": [EPMC_RECORD]}, "nextCursorMark": "*"}}))
        assert app.main(["--query", "asthma GWAS", "--no-fulltext", "--output", str(tmp_path)]) == 0
        res = json.loads((tmp_path / "result.json").read_text())
        assert res["synthetic"] is False and res["data_provenance"] == "LIVE"
        assert res["data"]["provenance"]["retrieved_at"]
        report = (tmp_path / "report.md").read_text()
        assert "SYNTHETIC" not in report and "**Data provenance**: LIVE" in report
        for p in (tmp_path / "figures").glob("*.png"):
            assert _png_text(p)["synthetic"] == "false"
        rows = list(csv.DictReader((tmp_path / "tables/papers.csv").open()))
        assert rows[0]["data_provenance"] == "LIVE"

    def test_partial_failure_is_reported_not_hidden(self, tmp_path, monkeypatch, no_fixture):
        monkeypatch.setattr(requests.Session, "get", _fake_get({
            "/references": requests.ConnectionError("reset by peer"),
            "/search": {"resultList": {"result": [EPMC_RECORD]}, "nextCursorMark": "*"},
        }))
        assert app.main(["--query", "asthma GWAS", "--cascade", "references", "--no-fulltext",
                         "--output", str(tmp_path)]) == 0
        res = json.loads((tmp_path / "result.json").read_text())
        assert any("reference lookup failed for MED:123" in w for w in res["summary"]["retrieval_warnings"])
        assert "## Data availability" in (tmp_path / "report.md").read_text()


# ---------------------------------------------------------------------------
# The equity score is context only
# ---------------------------------------------------------------------------

class TestEquityScoreIsContextOnly:
    def test_json_labels_the_score(self, demo_out):
        res = json.loads((demo_out / "result.json").read_text())
        sem = res["data"]["equity_score_semantics"]
        assert sem["role"] == "context_only" and sem["feeds_applicability_decision"] is False
        assert res["summary"]["equity_score_role"] == "context_only"
        assert res["summary"]["median_equity_score"] is not None       # the score itself is kept
        assert all("score" in p["audit"] for p in res["data"]["papers"])

    def test_tables_and_report_label_the_score(self, demo_out):
        rows = list(csv.DictReader((demo_out / "tables/papers.csv").open()))
        assert {r["equity_score_role"] for r in rows} == {"context_only"}
        assert "must never be used as an input to a PRS applicability decision" in \
            (demo_out / "report.md").read_text()

    def test_skill_md_agent_boundary_says_so(self):
        md = (SKILL_DIR / "SKILL.md").read_text()
        boundary = md.split("## Agent Boundary", 1)[1].split("\n## ", 1)[0]
        assert "context only" in boundary.lower()
        assert "applicability" in boundary and "never" in boundary.lower()


# ---------------------------------------------------------------------------
# Relocation: the skill finds ClawBio when symlinked in or run from PRSGuard
# ---------------------------------------------------------------------------

def _fake_clawbio(root: Path) -> Path:
    (root / "clawbio" / "common").mkdir(parents=True)
    (root / "clawbio" / "common" / "reproducibility.py").write_text("")
    (root / "skills").mkdir()
    return root


def test_clawbio_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWBIO_DIR", str(_fake_clawbio(tmp_path / "cb")))
    assert app.find_clawbio_root() == (tmp_path / "cb").resolve()


def test_clawbio_root_through_symlink(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAWBIO_DIR", raising=False)
    cb = _fake_clawbio(tmp_path / "ClawBio")
    link = cb / "skills" / "equity-lit-auditor"
    link.symlink_to(SKILL_DIR, target_is_directory=True)
    monkeypatch.setattr(app, "__file__", str(link / "equity_lit_auditor.py"))
    assert app.find_clawbio_root() == cb.resolve()


# ---------------------------------------------------------------------------
# Live smoke tests (opt-in)
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(not LIVE, reason="set RUN_LIVE_TESTS=1 (or PRSGUARD_LIVE_TESTS=1) for live API calls")


@pytest.mark.network
@live
def test_live_breast_cancer_reaches_child_trait_scores():
    res = gather(PGSCatalogClient(), "breast cancer", [], 5, False, **QUIET)
    assert res.traits[0]["id"] == "MONDO_0007254" and res.traits[0]["scores_available"] >= 190
    assert "PGS000001" in [s["id"] for s in res.scores]      # a breast carcinoma (child trait) score


@pytest.mark.network
@live
def test_live_t2d_evaluation_sets_not_duplicated():
    res = gather(PGSCatalogClient(), None, ["PGS000014"], 1, True, **QUIET)
    ev = [l for l in res.links if l.stage == "evaluation"]
    assert ev and len(ev) == len({(l.seed, tuple(sorted(str(s) for s in l.samples))) for l in ev})
    st = stage_ancestry(res)
    assert st["GWAS"]["EUR"] == 159208


@pytest.mark.network
@live
def test_live_europe_pmc_search_shape():
    recs = EuropePMCClient().search("polygenic score portability", limit=3)
    assert len(recs) == 3
    papers = [paper_from_record(r) for r in recs]
    assert all(p.id and p.source and p.title for p in papers)


def test_space_grouped_thousands_are_one_number():
    """Found in the live breast-cancer run: '70 877 women' was read as 877 and '53 051' as 51."""
    import equity_lit_extract as ex

    assert ex.parse_number("53 051") == 53051
    assert ex.parse_number("1\u2009234\u2009567") == 1234567
    recs, _, total = ex.extract_populations(
        "The KARMA study is a population-based screening cohort comprising 70 877 women in Sweden.", "methods")
    assert total == 70877
    assert all(r.n in (None, 70877) for r in recs)


def test_score_names_are_not_sample_sizes():
    """Found in the live breast-cancer run: 'the PGS 313 for American women' was read as 313 women."""
    import equity_lit_extract as ex

    _, _, total = ex.extract_populations(
        "We further investigate the generalizability of the PGS 313 for American women of European ancestry.",
        "abstract")
    assert total is None
    _, _, total = ex.extract_populations("The PRS313 was evaluated in 18,342 women.", "abstract")
    assert total == 18342
