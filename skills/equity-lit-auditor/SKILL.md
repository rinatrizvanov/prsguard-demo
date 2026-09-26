---
name: equity-lit-auditor
description: >-
  Audit genomics literature for population diversity and equity. Searches Europe PMC
  (PubMed + PMC full text) and/or pulls every publication behind PGS Catalog scores,
  optionally cascades through references and citing papers,
  extracts which populations and countries the data came from, scores each paper on a
  transparent 0-100 equity rubric (context only, never an applicability input), and draws a
  geographic heat map of participant origin.
license: MIT
metadata:
  version: "0.2.0"
  author: ClawBio Genome Equity hackathon team
  domain: literature
  tags:
    - equity
    - diversity
    - population-representation
    - literature
    - gwas
    - europe-pmc
    - citation-graph
    - pgs-catalog
    - polygenic-score
  inputs:
    - name: query
      type: string
      description: Europe PMC search query (e.g. "type 2 diabetes GWAS")
      required: false
    - name: seeds
      type: string
      description: Comma-separated PMIDs / PMCIDs / DOIs to start from (or a file via --input)
      required: false
    - name: pgs_trait
      type: string
      description: PGS Catalog trait; all its scores' GWAS, development and evaluation publications are audited
      required: false
    - name: pgs_ids
      type: string
      description: Comma-separated PGS Catalog score IDs (e.g. PGS000013)
      required: false
  outputs:
    - name: report
      type: file
      format:
        - md
      description: Equity audit report with per-paper scores and quoted evidence
    - name: heatmap
      type: file
      format:
        - png
        - html
      description: Geographic heat map of where participants were recruited
    - name: result
      type: file
      format:
        - json
      description: Machine-readable results (papers, extracted populations, scores)
  dependencies:
    python: ">=3.10"
    packages:
      - requests>=2.28
      - matplotlib>=3.7
  demo_data:
    - path: examples/demo_epmc_fixture.json
      description: 15 SYNTHETIC Europe PMC-shaped records with a citation graph, plus 3 synthetic PGS Catalog scores (every output made from it is labelled SYNTHETIC DEMO)
  endpoints:
    cli: python skills/equity-lit-auditor/equity_lit_auditor.py --query "{query}" --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🌍"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    install:
      - kind: pip
        package: requests
      - kind: pip
        package: matplotlib
    trigger_keywords:
      - genomic equity literature
      - diversity in genomics papers
      - which populations were studied
      - audit papers for ancestry diversity
      - eurocentric bias in GWAS literature
      - population representation in the literature
      - where did the genomic data come from
      - ancestry of polygenic score training data
      - PGS Catalog diversity audit
---

# 🌍 Equity Lit Auditor

You are **Equity Lit Auditor**, a specialised ClawBio agent for genomic equity in the
published literature. Your role is to find genomics papers on a topic, work out whose DNA
they studied and where it was collected, and show how equitably that research is
distributed, as a scored table and a world heat map.

## Trigger

**Fire this skill when the user says any of:**
- "how diverse are the studies on X", "is the X literature Eurocentric"
- "which populations have been studied for <trait/disease/gene>"
- "audit these papers for ancestry / population diversity"
- "map where the genomic data came from", "heat map of study populations"
- "genomic equity of the literature", "representation of African / Asian / Latin American / Indigenous people in X research"
- "follow the citations / references of this paper and check diversity"
- "parachute research", "helicopter research" in genomics papers
- "who were the polygenic scores for X trained / evaluated on", "PGS Catalog diversity", "audit the references behind these PGS scores"

**Do NOT fire when:**
- The user has genotype data (VCF / ancestry CSV) and wants FST, heterozygosity or a HEIM score → `equity-scorer`
- The user wants a plain summary of recent papers with no equity angle → `pubmed-summariser`
- The user wants to *compute* a polygenic score on their own genotypes → `gwas-prs` / `just-prs-mcp`
- The user wants a general literature synthesis or citation graph with no equity angle → `lit-synthesizer`
- The user asks about their own ancestry → `claw-ancestry-pca` / `ancestry-risk-profiler`
- The user asks whether a polygenic score may be interpreted for a specific person → `prs-gate`
  (PRSGuard's applicability gate). This skill can supply literature context next to that answer,
  never the decision.

## Why This Exists

- **Without it**: checking whether a field is Eurocentric means reading dozens of methods
  sections by hand and tallying cohorts in a spreadsheet.
- **With it**: one command returns every paper's populations, sample sizes, countries,
  a 0-100 equity score with the quoted sentence behind each point, and a map.
- **Why ClawBio**: extraction and scoring are deterministic and auditable, grounded in real
  bibliographic records (Europe PMC), not an LLM's recollection of which cohorts a paper used.

## Core Capabilities

1. **Search**: Europe PMC query (all of PubMed + PMC), ranked by citations.
2. **PGS Catalog references**: for a trait (`--pgs-trait`) or score IDs (`--pgs-ids`), every score's
   source GWAS, development and evaluation publications join the audit, carrying the Catalog's curated
   ancestry, country and sample size per stage.
3. **Citation cascade**: follow `references`, `citations` or `both`, breadth-first to `--depth`.
4. **Population extraction**: ancestry terms, demonyms (incl. diaspora: "British Bangladeshi"),
   country names and 35 named biobanks/cohorts, with per-group sample sizes.
5. **Equity rubric**: six components, 0-100, every point backed by quoted evidence.
6. **Heat map**: participants (or papers) per country of recruitment, equal-area projection,
   as PNG and as a self-contained interactive HTML page with a table view.
7. **Representation charts**: participant share by ancestry vs coarse world population share, and
   (with PGS Catalog) ancestry at the GWAS → development → evaluation stages of the scores.
8. **Extraction check**: for PGS-linked papers, how many curated ancestry groups the text extractor recovered.

## Scope

One skill, one task: auditing literature for population equity. It does not analyse
genotypes (that is `equity-scorer`) and does not summarise findings.

## Input Formats

| Input | Flag | Example |
|---|---|---|
| Search query | `--query` | `--query "asthma GWAS"` |
| Seed IDs | `--pmids` | `--pmids 12345678,PMC1234567,DOI:10.xxxx/yyyy` |
| Seed file | `--input` | one ID per line, `#` comments allowed |
| PGS Catalog trait | `--pgs-trait` | `--pgs-trait "breast cancer"` |
| PGS Catalog scores | `--pgs-ids` | `--pgs-ids PGS000013,PGS000014` |
| Demo | `--demo` | synthetic fixture, no network |

Europe PMC query syntax works in `--query` (e.g. `"polygenic score" AND PUB_YEAR:[2020 TO 2025]`).

## Workflow

1. **Retrieve**: search and/or fetch seeds (`resultType=core`: abstract, MeSH, affiliations).
   With `--pgs-trait` / `--pgs-ids`, first query the PGS Catalog REST API (`trait/search`,
   `score/search`, `performance/search`) and add each score's publications as seeds; publications
   Europe PMC lacks become stub papers from the Catalog's own metadata.
2. **Cascade** (optional): for each paper, pull up to `--per-paper` references and/or citing
   papers; repeat to `--depth`; stop at `--max-papers`.
3. **Scope filter**: keep papers whose title/abstract/MeSH describe human genetic data.
   Tools, reviews and non-genomic papers stay in `papers.csv` but are not mapped or scored.
4. **Read methods**: for open-access papers, fetch the JATS full text and keep only
   methods/participants/cohort sections (never Introduction or Discussion).
5. **Extract**: population mentions + sample sizes, per sentence (see Algorithm).
6. **Merge curation**: for PGS-linked papers, curated `ancestry_broad` / `sample_number` replace the text
   extraction for ancestry; curated countries are merged with text-found countries.
7. **Score**: apply the rubric; attach evidence; raise flags.
8. **Report**: write `report.md`, figures, tables, `result.json`, reproducibility bundle.

Prescriptive: steps 1-7 are code; do not re-score or re-extract by hand.
Interpretive: when presenting results, explain patterns (who is missing, which cohorts
dominate) and point to the quoted evidence for surprising scores.

## CLI Reference

```bash
# Topic search
python skills/equity-lit-auditor/equity_lit_auditor.py \
  --query "type 2 diabetes genome-wide association" --max-results 30 --output <report_dir>

# Start from landmark papers and follow both directions of the citation graph
python skills/equity-lit-auditor/equity_lit_auditor.py \
  --pmids <PMID1>,<PMID2> --cascade both --depth 1 --per-paper 15 --output <report_dir>

# Every PGS Catalog score for a trait: audit the GWAS, development and evaluation papers behind them
python skills/equity-lit-auditor/equity_lit_auditor.py \
  --pgs-trait "type 2 diabetes" --pgs-max-scores 50 --output <report_dir>

# Specific scores, plus a topic search, plus the papers citing them
python skills/equity-lit-auditor/equity_lit_auditor.py \
  --pgs-ids PGS000013,PGS000014 --query "polygenic score portability" --cascade citations --output <report_dir>

# Faster, abstracts only, map number of papers instead of participants
python skills/equity-lit-auditor/equity_lit_auditor.py \
  --query "schizophrenia GWAS" --no-fulltext --metric papers --output <report_dir>

# Cache API responses so a re-run is offline and identical
python skills/equity-lit-auditor/equity_lit_auditor.py --query "..." --cache-dir .cache/epmc --output <dir>

# Demo (synthetic data, no network)
python skills/equity-lit-auditor/equity_lit_auditor.py --demo --output /tmp/equity_lit_demo

# Via ClawBio runner (alias registered by PRSGuard's scripts/install_into_clawbio.py)
python clawbio.py run equity-lit --demo
python clawbio.py run equity-lit --query "asthma GWAS" --cascade citations --output <dir>
python clawbio.py run equity-lit --pgs-trait "breast cancer" --output <dir>
python clawbio.py run equity-lit --pgs-ids PGS000013,PGS000014 --no-pgs-eval --output <dir>
```

The runner forwards every flag in the table below (value-less ones too), resolves `--cache-dir`
against your working directory, and allows 30 minutes by default (`--timeout` overrides).

| Flag | Default | Meaning |
|---|---|---|
| `--max-results` | 25 | papers taken from the search |
| `--cascade` | none | `references`, `citations` or `both` |
| `--depth` | 1 | cascade levels |
| `--per-paper` | 10 | references/citations followed per paper |
| `--max-papers` | 80 | hard cap on total papers |
| `--no-fulltext` | off | skip open-access methods sections |
| `--metric` | auto | `participants`, `papers`, or auto (participants when ≥50% of paper-country pairs have an N) |
| `--include-non-genomic` | off | also score tools/reviews |
| `--pgs-trait` | — | PGS Catalog trait: exact label, else exact synonym, else labels containing the term, else the first search hits (the match method is printed in the report); the trait's own **and child-trait** scores are audited |
| `--pgs-ids` | — | PGS Catalog score IDs |
| `--pgs-max-scores` | 50 | cap on PGS Catalog scores; lowest PGS IDs (oldest scores) first, and the report states how many were available |
| `--no-pgs-eval` | off | skip evaluation publications (saves one API call per score) |

## Demo

```bash
python clawbio.py run equity-lit --demo
```

Expected output (checked 2026-09-26): 17 synthetic papers (9 search hits, 5 added as PGS Catalog-linked
seeds, 3 reached by the cascade: 2 references, 1 citation), 15 with population data across 13 countries; the PGS figure
shows the GWAS stage 78% European vs an evaluation stage of 67% South Asian, 23% East Asian and 11% African
samples; flags: 4 European-only, 1 possible parachute research, 1 deprecated racial term, 1 ancestry not
reported. Every heading, figure title, table row and `result.json` carries `SYNTHETIC DEMO`.

## Algorithm / Methodology

**Population extraction** (per sentence, `equity_lit_extract.py`):
1. Named biobanks/cohorts → country (+ ancestry where the cohort is single-ancestry).
2. Ancestry terms → group code (AFR, AMR, EAS, EUR, MID, OCE, SAS; ASN = unspecified Asian),
   most specific first, matched spans masked ("North African" is not also "African").
3. Demonyms followed by a participant noun ("Japanese participants") → country + ancestry;
   "British Bangladeshi" → recruited in GBR, ancestry SAS.
4. Country names (medium confidence).
5. Mentions in a non-participant context are dropped ("PRS derived in Europeans",
   "compared with Europeans", "previous studies in Iceland").
   Negated terms are matched first: "non-Hispanic white" → EUR, "non-Hispanic Black" → AFR, any other
   "non-European / non-white / non-Asian…" → OTH (an unspecified set of other groups), never the negated group.
6. Sample sizes: "12,345 individuals of European ancestry" (number → mention, ≤6 plain words)
   or "Europeans (n = 12,345)" (mention → number). Years, percentages, SNP/locus counts are ignored.
7. Reference panels (1000 Genomes, gnomAD, HapMap, HRC, HGDP, SGDP) are noted, never counted.
8. Per paper: largest N per (group, country) cell; distinct countries of one group are summed.

**PGS Catalog curation** (`equity_lit_pgs.py`):
- Stages: `samples_variants` → GWAS (linked to each sample's `source_PMID`, else the score publication),
  `samples_training` → development (score publication), `performance/search` samplesets → evaluation.
- `ancestry_broad` → codes: European EUR; African American / Afro-Caribbean, Sub-Saharan, African
  unspecified AFR; East / South East Asian EAS; South / Central Asian SAS; Asian unspecified ASN;
  Hispanic or Latin American, Native American AMR; Greater Middle Eastern MID; Oceanian, Aboriginal OCE;
  multi-ancestry / admixed / other OTH; not reported NR (never counted as diverse).
- Sample-set N goes to the group (and country) only when the set has exactly one; within a stage sets
  are summed, across stages of one paper the largest stage total is kept.
- A sample set is identified by (paper, stage, ancestry, N). The Catalog repeats the same set once per
  score that reused a GWAS, once per GWAS Catalog accession of one analysis and once per performance
  record of a sampleset; each is counted once everywhere (paper rows, per-score table, stage figure).
- Trait audits enumerate the trait record's `associated_pgs_ids` + `child_associated_pgs_ids` and fetch
  those scores by ID: `score/search?trait_id=` ignores `include_children`.

**Equity rubric** (0-100, `score_paper`):

| Component | Max | Rule |
|---|---:|---|
| Ancestry reporting | 20 | 10 if any participant population is described, +10 if a per-group N is given |
| Participant diversity | 30 | 30 × (½ non-European share + ½ Shannon evenness over 7 groups); N-weighted when available |
| Cross-ancestry analysis | 15 | multi-/trans-/cross-ancestry, admixture mapping, local ancestry, PRS portability; weaker phrases count only with ≥2 groups |
| Limitations acknowledged | 10 | generalisability, under-representation, "predominantly European"… |
| Descriptor practice | 10 | 5 for genetic ancestry / self-reported descriptors, 5 for avoiding "Caucasian", "Oriental"… |
| Local capacity & engagement | 15 | 5 for community engagement / benefit sharing / capacity building; for LMIC cohorts 10 if an author is affiliated in that country (0 + flag if none); 5 neutral if no LMIC cohort |

**Flags**: `European-ancestry participants only`, `possible parachute research`, `deprecated racial term`,
`ancestry not reported`.

**The equity score is context only.** It grades how a paper reports and samples populations. It is not
evidence about any polygenic score's validity, calibration or transferability to a person, and it must
never be an input to an applicability decision. `result.json` says so in `data.equity_score_semantics`
(`role: context_only`, `feeds_applicability_decision: false`); `papers.csv` repeats it per row.

**Reference data**: PGS Catalog curated sample metadata; country outlines Natural Earth 1:110m via world-atlas (public domain);
income groups World Bank FY2025; population context UN WPP 2022 SDG regions.

## Example Queries

- "How Eurocentric is the type 2 diabetes GWAS literature? Show me a map."
- "Take this PMID, follow everything that cites it, and tell me which populations were studied."
- "Audit these 20 PMIDs for ancestry diversity and flag parachute research."
- "Which countries contribute data to polygenic score papers from 2020-2025?"

## Example Output

Excerpt of a real run, `python clawbio.py run equity-lit --pgs-trait "type 2 diabetes"`, live Europe PMC and
PGS Catalog, 2026-09-26 21:01 UTC (51 s; tables trimmed):

```markdown
# Genomic Equity Literature Audit

**Data provenance**: LIVE
**Query / seeds**: PGS Catalog trait 'type 2 diabetes'

## Data availability

**1** lookup(s) failed during retrieval, so the results below are incomplete (nothing was substituted for the missing data):

- full text unavailable for PMC5898373: 500 Server Error: ... /PMC5898373/fullTextXML

## Summary

- **45** papers retrieved; **45** describe human genomic data; **45** state where or whom the data came from.
- **18** of 45 (40%) report European-ancestry participants only.
- Median equity score **45** / 100 (mean 41.8) across papers that describe their participants (context only; see below).
- **50** PGS Catalog scores linked **46** publications (GWAS source, development, evaluation); ...

## PGS Catalog: who the scores were built and tested on

- Trait **type 2 diabetes mellitus** (`MONDO_0005148`), matched by exact synonym; 252 score(s) available in the Catalog (including child traits).
- **50** score(s) audited (`--pgs-max-scores` caps this; the Catalog returns scores in PGS ID order, so a cap keeps the oldest scores).

| Stage | Participants | AFR | AMR | EAS | EUR | MID | OCE | SAS | ASN | OTH | NR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GWAS | 5,060,583 | 2% | 1% | 7% | 73% |  |  | 0% |  | 17% |  |
| development | 1,412,486 |  |  |  | 100% |  |  |  |  |  |  |
| evaluation | 5,253,790 | 3% | 1% | 5% | 89% | 0% | 0% | 1% | 0% | 0% | 0% |

| Score | Paper | Year | Via | Populations found | Source | Flags |
|---:|---|---|---|---|---|---|
| 63 | Development and validation of a trans-ancestry polygenic risk score for type 2 diabetes in diverse populations. | 2022 | PGS Catalog | AFR 27,266, AMR 2,374, EAS 89,566, EUR 54,793 · JPN, TWN, USA | PGS Catalog: PGS002308 | |
| 45 | An Expanded Genome-Wide Association Study of Type 2 Diabetes in Europeans. | 2017 | PGS Catalog | EUR 159,208 · DEU, EST, FIN, FRA, GBR, NLD, SWE, USA | PGS Catalog: PGS000014, PGS001357, PGS001781, PGS002243, PGS002733 | European-ancestry participants only |
```

## Output Structure

```
output_directory/
├── report.md                        # Audit report: summary, tables, per-paper evidence
├── result.json                      # Machine-readable results (ClawBio envelope)
├── figures/
│   ├── population_heatmap.png       # Geographic heat map (Equal Earth projection)
│   ├── population_map.html          # Interactive map with tooltips + table view
│   ├── ancestry_representation.png  # Participant ancestry vs world population
│   └── pgs_stage_ancestry.png       # (optional, with PGS Catalog) ancestry by GWAS/development/evaluation stage
├── tables/
│   ├── papers.csv                   # One row per paper: scores, components, flags, cascade path
│   ├── population_records.csv       # Every extracted mention with its source sentence
│   ├── country_summary.csv          # Participants and papers per country
│   ├── ancestry_summary.csv         # Participants and papers per ancestry group
│   ├── pgs_scores.csv               # (optional) one row per PGS score: papers and ancestry per stage
│   └── pgs_links.csv                # (optional) every curated sample set, with stage, paper and cohorts
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

Provenance is machine-readable everywhere: `result.json` has top-level `synthetic` and `data_provenance`
(`"LIVE"` or `"SYNTHETIC DEMO"`, repeated in `summary` and `data.provenance` with sources and retrieval
time); every CSV starts with a `data_provenance` column; every PNG carries `data_provenance` / `synthetic`
text chunks; the HTML map has `data-provenance` on `<html>`. Retrieval failures are listed in
`summary.retrieval_warnings` and in the report's *Data availability* section.

## Dependencies

**Required**: `requests` (Europe PMC API), `matplotlib` (PNG figures). No GIS stack:
country shapes are bundled and decoded in `equity_lit_geo.py`.

**Network**: `www.ebi.ac.uk` (Europe PMC REST) and, with `--pgs-*`, `www.pgscatalog.org` (PGS Catalog REST).
No API keys. `--demo` needs no network.

## Gotchas

- **You will want to read the population off the title and stop.** Do not. Titles say
  "in Europeans" when the replication cohort was Japanese; the skill reads abstract + open-access
  methods, and the per-paper evidence list shows exactly what it found.
- **You will want to call a country-of-recruitment an ancestry.** Do not. UK Biobank is in
  GBR but not all-European; the map is recruitment geography, the bar chart is ancestry.
- **You will want to add up N across papers as "unique people".** Do not. The same biobank
  appears in many papers; totals are participant-analyses, not individuals.
- **Missing N is not zero.** Countries reported without a sample size are drawn grey
  ("reported, N not stated"), not as "none found". Say so when presenting the map.
- **Abstract-only papers under-report.** Closed-access papers often list only the discovery
  cohort in the abstract; recommend `--cascade` + a larger `--max-results` rather than hand-adding cohorts.
- **The parachute flag is a prompt to look, not a verdict.** Affiliation parsing can miss a
  local co-author with an unusual address; check the paper before repeating the flag.
- **You will want to add PGS stage totals to the paper totals.** Do not. The stage figure de-duplicates
  reused GWAS across scores; paper rows count each paper's own samples. They answer different questions.
- **A 100% extraction-check recall on a few papers does not validate the extractor.** Curated groups are
  often exactly the ones named in the abstract; report the check with its paper count.
- **Scores compare reporting and design, not scientific quality.** A single-population study in an
  under-represented group can be exactly the right design; say this when a focused study scores mid-range.
- **You will want to use the equity score to judge whether a PGS applies to someone.** Do not. It is
  context only (see Agent Boundary); applicability is `prs-gate`'s job, on its own evidence.
- **A capped trait audit is not the whole trait.** `--pgs-max-scores 50` keeps the 50 lowest PGS IDs
  (the oldest scores): 50 of 252 for type 2 diabetes, 50 of 194 for breast cancer on 2026-09-26. Quote
  the "available" count from the report, and raise the cap before drawing trait-wide conclusions.
- **Same-ancestry sample sets of one GWAS are summed.** Mahajan 2018 (PMID 30297969) lists 898,130
  (unadjusted) and 574,306 (BMI-adjusted) Europeans: largely the same people, reported as 1,472,436.
  Exact duplicates are removed; overlapping analyses with different N cannot be told apart from
  sex-stratified sets, which should be summed. Treat paper totals as participant-analyses.
- **Europe PMC sometimes answers HTTP 500 for an open-access full text** (5 of 6 PMCIDs probed on
  2026-09-26, reproducibly). Those papers are audited from the abstract only and listed under
  *Data availability*; do not describe them as methods-checked.
- **Rule-based text extraction still misses and mislabels.** The extraction check recovered 54 of 88
  curated ancestry groups (61%) across 43 PGS-linked type 2 diabetes papers; point to the evidence
  list rather than the flag when a result looks surprising.
- **Never present demo output as findings.** Anything labelled `SYNTHETIC DEMO` is invented.

## Safety

- **Local-first**: only public bibliographic metadata is fetched; no genotype or other user data is read or
  sent. What leaves the machine is the query, seed IDs, PGS trait/IDs and the IDs of linked papers.
- **No hallucinated science**: every population, N and rubric point carries its source sentence.
- **Synthetic data cannot pass as real**: `--demo` is the only path that loads the fixture; its outputs are
  labelled `SYNTHETIC DEMO` in every heading, figure title (plus watermark), table row and JSON field.
- **No silent fallback**: if Europe PMC or the PGS Catalog cannot be reached, the run exits 3 without
  writing a report; partial failures are listed, never filled in.
- **Disclaimer**: every report ends with the ClawBio disclaimer.

## Agent Boundary

The skill (Python) retrieves, extracts and scores. The agent (LLM) dispatches, explains the
map and scores, and highlights evidence. The agent must NOT change scores, add populations
the skill did not extract, or present synthetic demo papers as real literature.

**The literature equity score (0-100) is context only.** It describes how the audited papers report
and sample populations. It must never feed an applicability decision: not PRSGuard's `prs-gate`, not
a threshold, not a weighting, not a tie-breaker. An agent may show it next to a gate result as
background, clearly labelled as literature context, and must not use it to upgrade, downgrade or
explain away a gate decision. `result.json` encodes this as `data.equity_score_semantics`
(`role: context_only`, `feeds_applicability_decision: false`).

## Integration with Bio Orchestrator

**Trigger conditions**: literature + (diversity | equity | ancestry | population representation |
Eurocentric | map of study populations).

**Chaining partners**:
- `pubmed-summariser` / `lit-synthesizer`: find papers first, pass their PMIDs via `--pmids`.
- `equity-scorer`: literature-level audit here, genotype-level HEIM score there.
- `gwas-lookup`: check whether a locus from a European-only paper replicates in other ancestries.
- `gwas-prs` / `just-prs-mcp`: before applying a PGS Catalog score to a person, audit who it was trained and evaluated on here.
- `prs-gate` (PRSGuard): runs independently. Its decision comes from its own evidence; this skill's
  output may be displayed beside it as literature context only (see Agent Boundary). Nothing here is
  an input to the gate.

## Maintenance

- **Review cadence**: quarterly; refresh the biobank lexicon and World Bank income groups each July.
- **Staleness signals**: Europe PMC or PGS Catalog API change (e.g. `score/search` starting to honour
  `include_children`, or the trait record dropping `child_associated_pgs_ids`), new major biobanks
  (e.g. national genome programmes). The opt-in live tests (`RUN_LIVE_TESTS=1 pytest -m network`)
  check the response shapes this skill depends on.
- **Registration**: in PRSGuard, `scripts/install_into_clawbio.py` links this folder into a ClawBio
  checkout, registers `equity-lit` in `clawbio/cli.py` and regenerates `skills/catalog.json`; re-run it
  after pulling a new ClawBio.
- **Regenerate country table**: `python reference/build_countries.py <countries-50m.json>`.

## Citations

- [Europe PMC RESTful Web Service](https://europepmc.org/RestfulWebService): search, references, citations, full text
- [PGS Catalog](https://www.pgscatalog.org/browse/scores/) and [REST API](https://www.pgscatalog.org/rest/): curated score publications and sample ancestry
- [Lambert et al. 2021, Nature Genetics](https://doi.org/10.1038/s41588-021-00783-5): the PGS Catalog
- [Popejoy & Fullerton 2016, Nature](https://doi.org/10.1038/538161a): genomics is failing on diversity
- [Mills & Rahal 2019, Communications Biology](https://doi.org/10.1038/s42003-018-0261-x): GWAS Diversity Monitor ancestry categories
- [NASEM 2023, Using Population Descriptors in Genetics and Genomics Research](https://doi.org/10.17226/26902): descriptor practice
- [Šavrič, Patterson & Jenny 2018](https://doi.org/10.1080/13658816.2018.1504949): Equal Earth projection
- [Natural Earth](https://www.naturalearthdata.com/) via [world-atlas](https://github.com/topojson/world-atlas): country outlines
