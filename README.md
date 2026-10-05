# PRSGuard

**A trait-first, evidence-aware PGS router that decides not only which polygenic score can be calculated, but
whether its interpretation is supported for the individual.**

> **RESEARCH SOFTWARE / PROTOTYPE. Not a medical device.** PRSGuard does not diagnose and never converts a
> polygenic score into absolute risk. Genetic reference placement is not ethnicity or identity.

Built for the ClawBio Hackathon (Challenge 3) on top of [ClawBio](https://github.com/ClawBio/ClawBio) (pinned at
`0ba9505`), the [PGS Catalog](https://www.pgscatalog.org/) and [1000 Genomes](https://www.internationalgenome.org/).

## The question

**Can this PGS result actually be interpreted for this person?**

Software can often produce a PRS number, but whether that score was faithfully computed and can be
interpreted are separate questions. A percentile is a different claim: that the score computed from *this*
file is the published score, that an evaluation in people like *this* person showed evidence of association, and
that there is a defensible reference population to compare them with. PRSGuard checks each of those with evidence and releases only
what the evidence supports:

| Gate status | What may be shown |
|---|---|
| **SUPPORTED** | raw score, standardized score, reference percentile with its uncertainty intervals |
| **RAW_ONLY** | raw score only (no relative or clinical interpretation) |
| **ABSTAIN** | nothing: the score cannot be faithfully computed or checked from this input |

Absolute risk is never provided. **SUPPORTED is a research-prototype reportability state, not a clinical
recommendation.** Its evaluation requirement (a 95% CI entirely above the metric's null in a single-ancestry
evaluation of the person's group) establishes evidence of association in a relevant group; it does not establish
clinically useful discrimination or calibration.

## Core principle

**Orchestration gathers evidence and calls tools. Deterministic code alone decides what claims are allowed.**

Orchestration is performed by an **LLM agent** when one drives PRSGuard (it declares itself with
`prsguard run --orchestrated-by "LLM agent: <name>"`), and otherwise by the **deterministic scripted PRSGuard CLI
orchestrator**, as in every demo result; each result records which. Orchestration resolves the trait, queries the
PGS Catalog, plans, calls tools, recovers from non-scientific failures, compares SUPPORTED scores and explains. It
may not change thresholds, re-run until SUPPORTED, choose a score by its personal result, invent or infer missing
evidence, choose a reference population for a nicer result, convert a raw score into risk, or override the gate.

```
input (genotype + trait + build + sex)
  ORCHESTRATION 1 read genotype locally          -> DETERMINISTIC 2 resolve build (never assumed)
  ORCHESTRATION 3 resolve trait -> ontology scope   4 search PGS Catalog
  DETERMINISTIC 5 eligibility E1-E8, pre-rank R1-R5, FREEZE candidates (SHA-256) before any personal scoring
  DETERMINISTIC 6 reference placement ONCE per person (1000 Genomes, fixed references, bootstrap uncertainty)
  DETERMINISTIC 7 harmonise + raw score (+ ClawBio gwas-prs cross-check)
  DETERMINISTIC 8 normalised PGS Catalog evidence + reference distribution on the matched variants
  DETERMINISTIC 9 prs-applicability-gate per candidate -> SUPPORTED / RAW_ONLY / ABSTAIN
  ORCHESTRATION 10 cross-PGS check (SUPPORTED only), primary = highest pre-ranked SUPPORTED, context, report
  CONTEXT ONLY: equity-scorer (FST, representation), equity-lit-auditor (literature equity)
```

Full diagram and boundaries: [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
scripts/setup.sh                 # .venv; with uv: exact versions from uv.lock (else pip, unlocked),
                                 # clone ClawBio at the pinned commit into vendor/, register the skills
source .venv/bin/activate

prsguard demo --out runs/demo    # the seven public demo cases, offline, ~5 s each
prsguard run --genotype my_genome.vcf.gz --trait "breast cancer" --sex female --out runs/me
prsguard route --trait "type 2 diabetes" --out t2d.frozen.json --catalog live   # candidates only, no genotype

prsguard serve                   # local-only API (127.0.0.1:8765) for uploads from the web interface
cd frontend && npm install && npm run dev    # http://localhost:3000
```

Runs use the committed PGS Catalog snapshot by default (offline, reproducible). `--catalog live` queries the PGS
Catalog and records every response into the snapshot directory. Genotypes never leave the machine
([docs/data-and-privacy.md](docs/data-and-privacy.md)).

The skills also run inside ClawBio: `python clawbio.py run prs-gate --demo` and
`python clawbio.py run equity-lit --pgs-trait "breast cancer"` (after `scripts/setup.sh`).

## Demo cases (breast cancer, female; public 1000 Genomes genotypes)

Every demo genome is the real 1000 Genomes phase 3 genotype of a named, openly consented sample (first female of
each population by ID). Only the *site content* is derived: WGS-like files contain every site of the reference
panels; the array file keeps the sites assayed by a consumer array; the thin file keeps 150 of those. The person is
detected in the reference panel and excluded from every comparison with themselves.

Frozen candidates (160 scores found -> 87 eligible -> pre-ranked top 3, before any personal scoring):
**PGS000004** (Mavaddat 2019, 313 variants), **PGS001804** (2,984), **PGS001336** (555).

| Case | Input | Placement | PGS000004 | PGS001804 | PGS001336 | Cross-PGS |
|---|---|---|---|---|---|---|
| A | HG00097 (GBR), simulated consumer array | EUR | ABSTAIN, r = 0.27 | ABSTAIN, r = 0.76 | ABSTAIN, r = 0.71 | not comparable |
| B | same person, WGS-like VCF | EUR | SUPPORTED 30th [12-59] | SUPPORTED 30th [26-34] | SUPPORTED 44th [30-59] | consistent |
| C | NA06985 (CEU) | EUR | SUPPORTED 53rd [26-78] | SUPPORTED 29th [26-34] | SUPPORTED 39th [25-55] | consistent |
| D | NA18488 (YRI) | AFR | SUPPORTED 78th [52-93] | SUPPORTED 64th [60-69] | SUPPORTED 87th [74-94] | consistent |
| E | NA19625 (ASW, admixed) | INTERMEDIATE | RAW_ONLY (TARGET_REFERENCE_UNRESOLVED) | RAW_ONLY | RAW_ONLY | not comparable |
| F | HG01566 (PEL) | AMR | SUPPORTED 45th [18-73] | RAW_ONLY (NO_RELEVANT_EVALUATION) | RAW_ONLY (NO_RELEVANT_EVALUATION) | not comparable |
| G | NA18939 (JPT), 150 sites | UNRESOLVED | ABSTAIN (LOW_SCOREABILITY) | ABSTAIN | ABSTAIN | not comparable |

Why a matched reference matters: scored against the European 1000 Genomes distribution, 44% of African-ancestry
reference individuals would appear in the "top 10%" for PGS000004 (72% for PGS000001) purely because of
allele-frequency and LD differences ([docs/benchmarks.md](docs/benchmarks.md)).

Intervals are combined 95% intervals (finite reference panel + missing variants). Percentiles are positions within
1000 Genomes reference individuals of the placed group, not probabilities of disease.

What the cases show: the same person is uninterpretable from a consumer array and interpretable from a WGS-like
file (A vs B); a score is supported for a Peruvian individual only where it was evaluated in Hispanic/Latin
American cohorts (F); an admixed individual is not forced into a reference group (E); a thin file is refused (G).

## Gate reason codes

`BUILD_UNRESOLVED`, `LOW_SCOREABILITY`, `SCOREABILITY_UNVERIFIED`, `ALLELE_HARMONIZATION_FAILED`,
`PALINDROMIC_VARIANT_UNRESOLVED`, `VARIANTS_MISSING`, `DUPLICATE_OR_CONFLICTING_VARIANTS`,
`TARGET_REFERENCE_UNRESOLVED`, `NO_RELEVANT_EVALUATION`, `EVALUATION_NOT_INFORMATIVE`,
`REFERENCE_DISTRIBUTION_UNAVAILABLE`, `REFERENCE_SENSITIVE`, `REFERENCE_SENSITIVITY_UNVERIFIED`,
`SEX_POPULATION_MISMATCH`, `SEX_NOT_PROVIDED`,
`METADATA_CONTRADICTION`, `EVALUATION_METADATA_UNAVAILABLE`, `UNSUPPORTED_SCORE_FORMAT`, `INVALID_GATE_INPUT`.

Each gate output contains `status, primary_reason, reason_codes, evidence_used, evidence_missing,
calibration_version, rule_trace, what_would_change_result, provenance` and `allowed_claims`
([skills/prs-applicability-gate/SKILL.md](skills/prs-applicability-gate/SKILL.md)).

## Calibration

No hackathon threshold survives unexamined. Coverage floors (50%/90%), ancestry confidence 0.80, the 5% evaluation
fraction, n >= 500 and the 20-point spread were removed and replaced by calibrated or explicitly argued rules:
LD-aware scoreability r >= 0.90 measured in the reference panel, held-out-calibrated reference placement,
single-ancestry evaluations showing association in the score's direction, and interval-based reference
sensitivity. See
[docs/calibration.md](docs/calibration.md) and the generated [docs/benchmarks.md](docs/benchmarks.md). Live API
checks and spot checks against the PGS Catalog web pages: [docs/live-validation.md](docs/live-validation.md).

## Tests and benchmarks

```bash
pytest                                   # all offline tests (PRSGuard, gate skill, equity-lit, legacy v1 evals)
RUN_LIVE_TESTS=1 pytest -m network       # optional live PGS Catalog / Europe PMC smoke tests
python benchmarks/ancestry_benchmark.py        # held-out placement (1000 Genomes)
python benchmarks/scoreability_benchmark.py    # masking experiments
python benchmarks/harmonisation_benchmark.py   # build agreement and allele reconciliation on real files
python benchmarks/report.py                    # regenerate docs/benchmarks.md
```

## Repository layout

```
prsguard/                     router, catalog auditor, genotypes, harmonisation, reference panels,
                              placement, distributions, evidence, cross-PGS, context, pipeline, CLI, local server
skills/prs-applicability-gate the gate (ClawBio skill) + legacy/v1 (hackathon gate and evals, kept for lineage)
skills/equity-lit-auditor     literature equity (teammate skill, integrated and live-validated)
data/                         1000G-derived reference panels, PGS Catalog snapshot, frozen candidates,
                              demo genomes, literature context
benchmarks/                   calibration experiments and their results
frontend/                     Next.js interface (static export + optional local server)
docs/                         architecture, calibration, benchmarks, live validation, data and privacy,
                              equity-lit integration notes
scripts/                      setup.sh, install_into_clawbio.py
```

## Remaining prototype assumptions

- Reference populations are 1000 Genomes phase 3 only (2,504 people; AMR core = PEL only, 85 people). Many
  ancestries are absent; people from them will be INTERMEDIATE or, worse, fall inside a broad cloud.
- The AMR reference cloud is elongated by PEL's own European admixture, so many admixed Mexican (17/25) and
  Colombian (13/25) held-out individuals are placed in AMR; the reference-sensitivity rule is the safeguard.
- PGS Catalog ancestry categories are broad (e.g. "African" includes African American cohorts) and are matched to
  placement groups at that broad level.
- Evaluations are taken as reported by the Catalog; overlap between development and evaluation samples, and
  differences in phenotype definition or covariates, are shown but not adjudicated.
- The evidence rule assumes every score is meant to be read as higher score -> higher phenotype value or risk
  (the PGS Catalog has no structured direction field). Only associations in that direction count; a score built
  the other way would be reported RAW_ONLY, never misread. Association is not proof of clinically useful
  discrimination or calibration.
- Scoring weights with weight_type "NR" are assumed log-additive, as distributed by the Catalog and as pgsc_calc
  assumes. Sex chromosomes and symbolic alleles are not scored.
- Strand-ambiguous SNPs are excluded for the person (pgsc_calc default); no imputation is performed.
- The reference panel only covers the demo scores; other scores are routed and gated but lack a reference
  distribution (RAW_ONLY). Genome-wide scores are excluded by the labelled engineering constraint E8.
- Percentiles describe the 1000 Genomes reference sample, not a disease-specific population, and are never
  converted to absolute risk.
- `r_min = 0.90` and `min_stability = 0.95` are policies; their consequences are measured, not derived.
- The person's sex is taken as declared and not checked against the genotype.
- Literature equity context is text-mined (Europe PMC abstracts and open-access methods) plus curated PGS Catalog
  records; text-mined sample sizes are heuristics. It is context only and never reaches the gate.

## Credits

PRSGuard was originally developed for ClawBio Hackathon Challenge 3 by:

- Rinat Rizvanov
- Timur Rizvanov
- Takato Honda
- Bradley Sheppard

The post-hackathon development and final integration of PRSGuard were completed by **Rinat Rizvanov**.
