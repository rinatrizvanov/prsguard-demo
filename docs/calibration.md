# Calibration: every number PRSGuard uses, and why

Calibration version **2026.09.26-2** (gate 2.1.0) (`skills/prs-applicability-gate/config/calibration.yaml`). Numbers quoted
below come from `docs/benchmarks.md`, which is generated from `benchmarks/results/*.json` by
`python benchmarks/report.py`. Re-running `benchmarks/ancestry_benchmark.py`, `benchmarks/scoreability_benchmark.py`
and `benchmarks/harmonisation_benchmark.py` regenerates every table from public data.

Each parameter is one of three kinds:

- **Calibrated**: chosen from a benchmark on public data, with the benchmark in this repository.
- **Policy**: a value judgement that cannot be derived from data. It is stated as a judgement, anchored to
  the published metric where possible, and its measured consequences are reported.
- **Engineering**: a runtime constraint of this prototype, not a scientific criterion. It is labelled as such
  wherever it has an effect.

## 1. What happened to the hackathon thresholds

| Hackathon threshold | Where | Status in v2 | Replaced by |
|---|---|---|---|
| Coverage hard floor 50% / soft floor 90% of variants | v1 `thresholds.yaml` | **Removed** | r(full, reduced) >= 0.90: weight- and LD-aware scoreability measured in the reference panel (section 3) |
| Ancestry confidence >= 0.80 | v1 `thresholds.yaml` | **Removed** | Placement inside a fixed reference cloud (chi-squared, 4 df, 0.999), >= 200 sites and bootstrap stability >= 0.95, all calibrated on held-out samples (section 4) |
| Evaluation fraction >= 5% in the target ancestry | v1 `thresholds.yaml` | **Removed** | Qualitative rule: at least one single-ancestry evaluation in the placed group whose 95% CI lies entirely above the metric's null: evidence of association, not of clinical utility (section 5) |
| Evaluation n >= 500 | hackathon gate | **Removed** | Same rule: the CI already accounts for sample size, so a separate N cut-off is redundant and arbitrary |
| 20-percentile-point spread between references | hackathon panel | **Removed** | REFERENCE_SENSITIVE: disjoint 95% percentile intervals between equally defensible 1000 Genomes populations (section 6) |
| Fraction-sum tolerance 0.05 | v1 input validation | Kept only as input validation in legacy v1 | v2 validates types and ranges and verifies the input digest |

The v1 gate and its evals are kept unchanged in `skills/prs-applicability-gate/legacy/v1` (33 evals pass) for
lineage. v1 is not called anywhere.

## 2. Genome build (`prsguard/genotypes.py`)

| Parameter | Value | Kind | Evidence |
|---|---|---|---|
| `BUILD_AGREEMENT` | 0.90 | Calibrated | Anchor agreement is bimodal on real files: 1.0 for every GRCh37 demo genome and 0.0002 (GRCh37) and 0.0 (GRCh38) for the two NCBI36 23andMe genomes; wrong-build agreement is <= 0.016 on every file. Any cut between 0.1 and 0.9 gives identical results. |
| `MIN_BUILD_SITES` | 20 anchors | Policy | Below 20 informative anchor rsIDs the declaration is used only if it is unambiguous and not refuted. The thin demo file (150 sites) still has 125 anchors. |
| Anchors | 6,557 PCA-panel rsIDs with GRCh37 (1000 Genomes) and GRCh38 (Ensembl) positions | Data | Both builds can be confirmed or refuted; NCBI36 is only ever taken from an unambiguous declaration. |

The build is never assumed: no declaration and no confirmation gives `UNRESOLVED`, and the gate returns
`BUILD_UNRESOLVED` (ABSTAIN). The public Corpas 23andMe genome (NCBI36 positions, no build header) resolves to
`UNRESOLVED`; the Church genome (header "build 36") resolves to `NCBI36`. A wrong user declaration is overruled
by confirmed anchors and the conflict is recorded.

## 3. Scoreability (`r_min = 0.90`, policy with measured consequences)

**Metric.** In the 1000 Genomes group the person is placed in (all core samples if unplaced), PRSGuard computes
the published score over every panel-available variant (FULL) and over the variants actually matched for the
person (REDUCED), then takes the Pearson correlation. Variants absent from the panel are accounted for by
r_adj = r x sqrt(V_panel / (V_panel + V_absent)), where V_absent uses the reported effect-allele frequencies
(p = 0.5, the maximum-variance and so conservative choice, when not reported). Palindromic SNVs are included in
FULL as reported, so their loss is measured with LD, but are never used for the person.

**Why not "percent of variants".** In the masking experiments the band 0.90 <= r < 0.95 contains masks that kept
anywhere from 60% to 95% of variants, and one heavily weighted variant can matter more than hundreds of small
ones. The count-based floors of v1 could not express this.

**Why 0.90.** A reduced score correlated r with the full score has a per-SD association of about r times the
published one (the part of the full score it does not capture is lost). r >= 0.90 therefore means "this is still
the published score, keeping at least 90% of its published effect per SD". That is a policy anchored in the
published metric. Its consequences for percentiles, measured in `docs/benchmarks.md`:

| r | median abs. percentile error | 95th percentile (median over masks) | top decile recovered |
|---|---|---|---|
| >= 0.99 | 2.0 | 7.5 | 0.91 |
| 0.95-0.97 | 4.8 | 18.1 | 0.80 |
| 0.90-0.95 | 6.9 | 24.3 | 0.72 |
| 0.85-0.90 | 8.8 | 31.1 | 0.64 |

Near the threshold a percentile can therefore move by roughly 25 points for 1 in 20 people. PRSGuard does not
hide this: every released percentile carries a **missing-variant interval** (95% prediction interval of the
full score given the reduced score, from the reference panel), and the combined interval shown to the user
includes it. The threshold decides whether the score is still the published score; the interval says how
precisely it places this person.

**Consumer arrays.** A simulated consumer array (chip content of the public 23andMe genomes) gives r between 0.27
and 0.82 for all four demo scores in all five groups, so every array-only result ABSTAINs with
LOW_SCOREABILITY. The same person with a WGS-like file gets r = 0.95-1.00 (demo cases A vs B).

## 4. Reference placement (calibrated, held-out)

Method (`prsguard/reference/projection.py`): PCA refit on the person's observed sites, fitted on 100 reference
samples per core group (fixed seed; 85 PEL); 4 PCs; the person is compared with each group cloud by Mahalanobis
distance; inside = d^2 <= chi-squared(4) 0.999 quantile (18.47); stability = share of 100 marker bootstraps
giving the same placement. Admixed 1000 Genomes populations (ASW, ACB, MXL, PUR, CLM) never define axes.
The person's own sample is excluded automatically when present in the panel (genotype concordance >= 0.99 over
>= 100 sites).

| Parameter | Value | Kind | Evidence (leave-one-out, `docs/benchmarks.md`) |
|---|---|---|---|
| K | 4 PCs | Design | Five reference groups span a 4-dimensional between-group space. |
| Cloud quantile | 0.999 | Calibrated | Held-out core samples' d^2: median 4.2, 95th 12.9, 99th 17.0 (cut 18.47). 163/168 held-out core samples resolve to their own group; **0 resolve to a wrong group**. |
| `min_sites` | 200 | Calibrated | With random site subsets, 0 wrong placements at any size; the share resolved rises from 4/30 (50 sites) and 9/30 (100) to 21/30 (200), 29/30 (400), 30/30 (800+). 200 is the smallest size at which most held-out people resolve, with median stability 0.98. |
| `min_stability` | 0.95 | Policy, consistent with the 95% level used throughout | Held-out core samples at full density have stability 1.0; unstable outcomes concentrate in admixed individuals near cloud boundaries. |

**Admixed individuals.** ASW: 20/25 INTERMEDIATE, 1 UNSTABLE, 4 resolved (3 into AFR with an estimated >= 0.90
AFR component). PUR: 18/25 INTERMEDIATE, 5 UNSTABLE. **Known limitation:** because PEL itself carries European
admixture, the AMR cloud is elongated and 17/25 MXL and 13/25 CLM fall inside it. PRSGuard therefore treats every
1000 Genomes population of the placed superpopulation whose own cloud contains the person (admixed ones included)
as an equally defensible reference, and reports REFERENCE_SENSITIVE when their percentile intervals are disjoint
(section 6).

Bootstrap stability is a robustness measure of the placement. It is **not** an ancestry percentage. Supervised
admixture proportions (EM against fixed core-group frequencies) are shown as model-based context only.
Genetic reference placement is not ethnicity or identity.

## 5. Evaluation evidence (qualitative rule, no numeric cut-off)

A score passes G9 only if the PGS Catalog lists at least one **single-ancestry** evaluation (publication, sample
set) in the person's placed group reporting a metric whose 95% CI lies **entirely above** the metric's null:
OR/HR/RR > 1, beta > 0, AUROC/C-index > 0.5, correlation (including partial-r) > 0. For every metric type the gate
recognises, a higher score means higher risk, so this is evidence of association in the direction the score is
built for. Pooled multi-ancestry units (MAE/MAO) and NR units never count as group-specific evidence. R-squared and
other variance-explained metrics have no usable null (they cannot be negative, and their bootstrap intervals exclude
0 almost by construction), so they never count on their own. Missing CIs make a metric uninformative. This
replaced both the 5% fraction and the n >= 500 rule, because a CI already reflects sample size.

**What this rule does and does not establish.** It establishes evidence of association in a relevant evaluation
group. It does **not** establish clinically useful discrimination (an AUROC of 0.55 with a CI above 0.5 passes) or
calibration, and the gate never claims it does. SUPPORTED is a research-prototype reportability state (a percentile
may be shown with its intervals), not a clinical recommendation. A discrimination or calibration requirement would
need a threshold (what AUROC is "useful"?) that cannot be derived from the Catalog data, so none is imposed.

**Direction (gate 2.1.0).** Gate 2.0.0 accepted any CI excluding the null, so an inverse association counted too.
The Catalog snapshot contains four such evaluations for PGS000004, all case-only subtype comparisons (e.g. OR 0.86
[0.82, 0.89] for ER-negative status among cases; OR 0.80 [0.65, 0.99] for grade 3 vs grade 1 tumours). They are not
evidence for interpreting a breast-cancer risk score, so 2.1.0 requires the CI to lie above the null. No demo
outcome changed (other evaluations already supported the same scores). Phenotype definitions of evaluations
(subtype-only or case-only analyses) are otherwise not adjudicated; see the README's prototype assumptions.

Found during this work: the auditor originally knew nulls only for OR/HR/beta/AUROC, so PGS001804 (evaluated with
partial-r, e.g. 0.110 [0.091, 0.129] in Europeans) was wrongly treated as uninformative. Fixed and tested.

## 6. Reference distribution and percentile

**Why the reference must match the person** (`docs/benchmarks.md`, "Known reference samples"): scored against the
EUR 1000 Genomes distribution, 44% of AFR individuals fall above the EUR 90th percentile for PGS000004 and 72% for
PGS000001 (mean shifts of 1.2 and 1.8 EUR standard deviations). These shifts come from allele-frequency and LD
differences, not from risk, which is why PRSGuard never uses a reference the person is not placed in.

- Reference = the placed group's core 1000 Genomes populations (AFR 504, EUR 503, EAS 504, SAS 489, AMR = PEL 85),
  minus the person if present; scored on exactly the person's matched variants with the same effect alleles.
- Finite panel: Jeffreys 95% interval for the empirical CDF at the person's score (Brown, Cai & DasGupta 2001).
- Missing variants: 95% prediction interval of the full score given the reduced score in the reference group.
- Reference sensitivity (`REFERENCE_SENSITIVE`): percentiles against every 1000 Genomes population of the placed
  superpopulation whose cloud contains the person; disjoint 95% intervals fail G12. No point-spread cut-off.
- Absolute risk is never computed.

## 7. Allele reconciliation (`max_mismatch_fraction = 0.05`)

Real, correctly built public files show 0-0.4% unreconcilable alleles among located variants (all seven demo
genomes and both 23andMe genomes, four scores; `docs/benchmarks.md`). Corrupting a known share of calls shows the
detected fraction tracks the corruption (2% -> ~2%, 10% -> ~8-9%): there is **no natural gap**, so the value is
reasoned rather than read off a gap. For biallelic SNVs, a random wrong call lands on a valid allele about as often
as not, so a detected rate e implies a similar rate of undetectable wrong calls, which attenuate the score
roughly as r ~ 1 - e. Capping e at 0.05 keeps that attenuation within the scoreability tolerance while leaving a
>10x margin over every correct file tested. (An earlier draft used 0.10 on a claimed "empty gap"; the perturbation
benchmark showed that claim was wrong.)

## 8. Cross-PGS consistency

A pair of SUPPORTED scores is DISCORDANT when the gap between the person's two percentiles falls outside the
central 95% of the gaps observed among reference individuals of the same group, scored on the same variant sets.
Interval non-overlap is not used: two different scores (the demo scores correlate r = 0.26-0.54 in 1000 Genomes)
are expected to place a person differently, and narrow intervals would label almost every pair discordant.
Dependence (variant overlap, weighted overlap, shared source GWAS, reference correlation) is reported beside each
pair. The comparison never changes the primary score.

## 9. Engineering constraints

| Constraint | Value | Effect |
|---|---|---|
| Router E8 `max_variants` | 10,000 (demo; `--max-variants 0` disables) | Genome-wide scores cannot be reference-scored from remotely fetched 1000 Genomes sites in reasonable time. For breast cancer, 62 of 149 otherwise-eligible scores are excluded by E8 alone; this is recorded in the frozen candidate set and shown in the UI. |
| Reference subset | 100 per core group for placement | Keeps placement to ~1-2 s per person with 100 bootstraps. Percentiles use all core samples. |
| Reference panels | 1000 Genomes phase 3 only; PGS panel covers the scores used in the demo | Other scores are routed and gated, but without panel sites they have no reference distribution (REFERENCE_DISTRIBUTION_UNAVAILABLE) and scoreability falls back to reported allele frequencies (labelled as an independence approximation). |
