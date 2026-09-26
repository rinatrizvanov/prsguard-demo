---
name: equity-lit-auditor
description: >-
  Audit genomics literature for population diversity and equity. Searches Europe PMC
  (PubMed + PMC full text) and/or pulls every publication behind PGS Catalog scores,
  optionally cascades through references and citing papers,
  extracts which populations and countries the data came from, scores each paper on a
  transparent 0-100 equity rubric, and draws a geographic heat map of participant origin.
license: MIT
metadata:
  version: "0.1.0"
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
      description: 15 SYNTHETIC Europe PMC-shaped records with a citation graph, plus 3 synthetic PGS Catalog scores
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

# Via ClawBio runner
python clawbio.py run equity-lit --demo
python clawbio.py run equity-lit --query "asthma GWAS" --cascade citations --output <dir>
python clawbio.py run equity-lit --pgs-trait "breast cancer" --output <dir>
```

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
| `--pgs-trait` | — | PGS Catalog trait (exact label match preferred, else labels containing the term) |
| `--pgs-ids` | — | PGS Catalog score IDs |
| `--pgs-max-scores` | 50 | cap on PGS Catalog scores |
| `--no-pgs-eval` | off | skip evaluation publications (saves one API call per score) |

## Demo

```bash
python clawbio.py run equity-lit --demo
```

Expected output: 17 synthetic papers (9 search hits, 5 reached by the cascade, 3 reached only
through 3 synthetic PGS Catalog scores), 15 with population data across 13 countries; the PGS
figure shows GWAS stage ≈78% European vs an evaluation stage led by South Asian and East Asian
samples; flags: 4 European-only, 1 possible parachute research, 1 deprecated racial term,
1 ancestry not reported.

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
  are summed, across stages of one paper the largest stage total is kept; for the stage figure a GWAS
  reused by several scores is counted once.

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

**Reference data**: PGS Catalog curated sample metadata; country outlines Natural Earth 1:110m via world-atlas (public domain);
income groups World Bank FY2025; population context UN WPP 2022 SDG regions.

## Example Queries

- "How Eurocentric is the type 2 diabetes GWAS literature? Show me a map."
- "Take this PMID, follow everything that cites it, and tell me which populations were studied."
- "Audit these 20 PMIDs for ancestry diversity and flag parachute research."
- "Which countries contribute data to polygenic score papers from 2020-2025?"

## Example Output

```markdown
## Summary

- **14** papers retrieved; **13** describe human genomic data; **12** state where or whom the data came from.
- **3** of 12 (25%) report European-ancestry participants only.
- Median equity score **55.0** / 100 (mean 53.2) across papers that describe their participants.
- European ancestry accounts for **54%** of participants (extracted sample sizes).

| Score | Paper | Year | Via | Populations found | Flags |
|---:|---|---|---|---|---|
| 83 | Multi-ancestry meta-analysis of type 2 diabetes… | 2022 | search | AFR 59,492, AMR 33,217, EAS 77,418, EUR 180,834, SAS 24,500 · GHA, IND, JPN, USA | |
| 40 | Sequencing study of hypertension genes in Nigerian adults | 2020 | search | AFR 1,850 · NGA | possible parachute research… |
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

## Safety

- **Local-first**: only public bibliographic metadata is fetched; no user data leaves the machine.
- **No hallucinated science**: every population, N and rubric point carries its source sentence.
- **Disclaimer**: every report ends with the ClawBio disclaimer.

## Agent Boundary

The skill (Python) retrieves, extracts and scores. The agent (LLM) dispatches, explains the
map and scores, and highlights evidence. The agent must NOT change scores, add populations
the skill did not extract, or present synthetic demo papers as real literature.

## Integration with Bio Orchestrator

**Trigger conditions**: literature + (diversity | equity | ancestry | population representation |
Eurocentric | map of study populations).

**Chaining partners**:
- `pubmed-summariser` / `lit-synthesizer`: find papers first, pass their PMIDs via `--pmids`.
- `equity-scorer`: literature-level audit here, genotype-level HEIM score there.
- `gwas-lookup`: check whether a locus from a European-only paper replicates in other ancestries.
- `gwas-prs` / `just-prs-mcp`: before applying a PGS Catalog score to a person, audit who it was trained and evaluated on here.

## Maintenance

- **Review cadence**: quarterly; refresh the biobank lexicon and World Bank income groups each July.
- **Staleness signals**: Europe PMC API change, new major biobanks (e.g. national genome programmes).
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
