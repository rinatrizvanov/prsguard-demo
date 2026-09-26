---
name: prs-applicability-gate
description: >-
  Deterministic gate that decides whether ONE polygenic score result may be interpreted for ONE person:
  SUPPORTED (raw score, standardised score and reference percentile may be shown), RAW_ONLY (raw score only)
  or ABSTAIN (nothing), with reason codes, a full rule trace, the evidence used and missing, and what would
  change the result. Never produces absolute risk.
license: MIT
metadata:
  version: "2.1.0"
  author: PRSGuard team (ClawBio Hackathon Challenge 3)
  domain: genomics
  tags:
    - polygenic-score
    - applicability
    - ancestry
    - pgs-catalog
    - safety-gate
  inputs:
    - name: gate_input
      type: file
      format:
        - json
      description: Normalised evidence for one candidate score and one person (schema prs-applicability-gate.input.v2)
      required: true
  outputs:
    - name: result
      type: file
      format:
        - json
      description: Gate decision (schema prs-applicability-gate.output.v2) per input, plus a summary result.json
    - name: report
      type: file
      format:
        - md
      description: Human-readable rule trace
  dependencies:
    python: ">=3.10"
    packages:
      - pyyaml>=6.0
  demo_data:
    - path: examples/
      description: Gate inputs produced by PRSGuard from public 1000 Genomes demo genomes (one SUPPORTED, one RAW_ONLY, one ABSTAIN)
  endpoints:
    cli: python skills/prs-applicability-gate/prs_applicability_gate.py --input {gate_input} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🚦"
    homepage: https://github.com/rinatrizvanov/prsguard-demo
    os:
      - darwin
      - linux
    install:
      - kind: pip
        package: pyyaml
    trigger_keywords:
      - can this polygenic score be interpreted
      - is this PRS percentile valid for me
      - PRS applicability
      - prs gate
      - should this PGS percentile be shown
---

# 🚦 PRS Applicability Gate

You are **PRS Applicability Gate**, a specialised ClawBio agent for polygenic-score interpretation safety. Your role
is to decide, deterministically, what may be said about one polygenic score result for one person.

## Trigger

**Fire this skill when the user says any of:**
- "can this polygenic score / PRS / PGS be interpreted for me (for this person)?"
- "is this PRS percentile valid / applicable / trustworthy for this sample?"
- "should the percentile be shown?", "gate this PRS result", "prs gate"
- "does this score apply to my ancestry?" (after a score and reference placement exist)
- any time a PGS percentile is about to be reported to a person, even if the upstream steps looked clean

**Do NOT fire when:**
- the user wants a score *computed* (use `gwas-prs`, or the full PRSGuard pipeline which calls this gate)
- the user wants candidate scores *found or ranked* for a trait (PRSGuard router / PGS Catalog search)
- the user wants ancestry *inferred* (`claw-ancestry-pca`, or PRSGuard reference placement)
- the user wants a literature equity review (`equity-lit-auditor`)

## Why This Exists

- **Without it**: a raw PGS is silently turned into a percentile against a reference population the person may
  not belong to, from a genotype file that may not even contain the score's important variants, for a score never
  evaluated in anyone like them. Nothing looks broken; the number is confidently wrong.
- **With it**: every claim beyond the raw sum must be earned by evidence, rule by rule, and every refusal says
  exactly what evidence is missing.
- **Why ClawBio**: the decision is code with calibrated, cited parameters, not a model's judgement; the same input
  always gives the same answer.

## Core Capabilities

1. **Three-way decision**: SUPPORTED / RAW_ONLY / ABSTAIN with an explicit `allowed_claims` block.
2. **Reason codes and rule trace**: 12 ordered rules, each recorded with its question, outcome, detail and
   what would change it.
3. **Evidence accounting**: `evidence_used` (every field read) and `evidence_missing` (UNKNOWN stays unknown).
4. **Tamper evidence**: the input digest is re-verified; a modified input is rejected.

## Scope

**One skill, one task.** Input: one candidate score plus normalised evidence. The gate does NOT search the PGS
Catalog, rank scores, infer ancestry, compute scores or percentiles, compare scores, or choose a primary score.
Those are upstream/downstream steps of the PRSGuard pipeline.

## Input Formats

| Format | Extension | Required Fields | Example |
|--------|-----------|-----------------|---------|
| Gate input v2 | `.json` | candidate, score_file, genotype, person, harmonisation, scoreability, placement, catalog_metadata, evaluation, reference_distribution | `examples/case_B_PGS001336.gate_input.json` |

Gate inputs are produced by `prsguard.evidence.build_gate_input` in the PRSGuard repository.

## Workflow

1. **Validate** the input schema, types, ranges and digest (G1). Invalid input is ABSTAIN.
2. **Evaluate** rules G2-G12 in order (all of them, so the trace is complete).
3. **Decide**: ABSTAIN if any ABSTAIN rule failed, else RAW_ONLY if any RAW_ONLY rule failed, else SUPPORTED.
   The primary reason is the first failing rule at the decisive severity.
4. **Report**: write `<pgs_id>_gate.json` and `<pgs_id>_gate.md`, and a summary `result.json` / `report.md`.

Freedom level: none. The agent may explain the output; it may not reinterpret it.

## CLI Reference

```bash
python skills/prs-applicability-gate/prs_applicability_gate.py --input gate_input.json --output out/
python skills/prs-applicability-gate/prs_applicability_gate.py --demo --output /tmp/prs_gate_demo
python clawbio.py run prs-gate --demo          # after scripts/install_into_clawbio.py
```

`--config` (an alternative calibration file) exists only on the direct CLI, for calibration research; results
then carry `config_canonical: false` and a NON-CANONICAL CALIBRATION banner. It is deliberately **not** forwarded
by `clawbio.py run prs-gate`, the interface an LLM agent uses, so orchestration cannot swap thresholds (the
ClawBio runner drops unregistered flags; a regression test proves the shipped calibration is used).

## Demo

```bash
python skills/prs-applicability-gate/prs_applicability_gate.py --demo --output /tmp/prs_gate_demo
```

Evaluates three gate inputs produced by PRSGuard from public 1000 Genomes demo genomes: a EUR WGS-like genome with
PGS001336 (SUPPORTED), an admixed ASW genome (RAW_ONLY, TARGET_REFERENCE_UNRESOLVED) and a 150-site file (ABSTAIN).

## Algorithm / Methodology

| Rule | Question | Fails with | Effect |
|---|---|---|---|
| G1 INPUT_VALID | Well-formed, in range, digest intact? | INVALID_GATE_INPUT | ABSTAIN |
| G2 SCORE_FORMAT | Plain additive score on a log scale? | UNSUPPORTED_SCORE_FORMAT | ABSTAIN |
| G3 BUILD | Genotype build established, never assumed? | BUILD_UNRESOLVED | ABSTAIN |
| G4 ALLELES | Located variants' alleles reconcilable? (<= max_mismatch_fraction) | ALLELE_HARMONIZATION_FAILED | ABSTAIN |
| G5 SCOREABILITY | r(computable score, published score) >= r_min? | LOW_SCOREABILITY (+ PALINDROMIC_VARIANT_UNRESOLVED / VARIANTS_MISSING / DUPLICATE_OR_CONFLICTING_VARIANTS naming the largest loss), SCOREABILITY_UNVERIFIED | ABSTAIN |
| G6 SEX_SCORE | Sex-specific score used for that sex? | SEX_POPULATION_MISMATCH (ABSTAIN), SEX_NOT_PROVIDED (RAW_ONLY) | |
| G7 METADATA | PGS Catalog record resolved and consistent? | METADATA_CONTRADICTION, EVALUATION_METADATA_UNAVAILABLE | RAW_ONLY |
| G8 PLACEMENT | Person stably inside one reference group? | TARGET_REFERENCE_UNRESOLVED | RAW_ONLY |
| G9 EVALUATION | Single-ancestry evaluation in that group with a metric whose 95% CI lies entirely above the null (evidence of association in the score's direction)? | NO_RELEVANT_EVALUATION, EVALUATION_NOT_INFORMATIVE | RAW_ONLY |
| G10 SEX_EVALUATION | Do those evaluations include the person's sex? | SEX_POPULATION_MISMATCH | RAW_ONLY |
| G11 REFERENCE_DISTRIBUTION | Reference distribution on the person's matched variants? | REFERENCE_DISTRIBUTION_UNAVAILABLE | RAW_ONLY |
| G12 REFERENCE_SENSITIVITY | Percentile robust across equally defensible reference populations? | REFERENCE_SENSITIVE | RAW_ONLY |

**Key parameters** (`config/calibration.yaml`, derivations in the PRSGuard repository's `docs/calibration.md`):
- `r_min = 0.90`: policy anchored in the published metric (a reduced score keeps ~r of the published per-SD
  association), with its consequences for percentile error measured by masking experiments in 1000 Genomes.
- `max_mismatch_fraction = 0.05`: detected allele mismatches estimate a similar rate of undetectable wrong calls,
  which attenuate the score roughly as r ~ 1 - e; all real, correctly built public files tested show <= 0.4%.
- Evaluation rule: qualitative (at least one single-ancestry evaluation in the placed group whose metric CI lies
  entirely above its null); no arbitrary sample-size or fraction cut-off. Inverse associations do not count.
- Placement parameters (`min_sites = 200`, `min_stability = 0.95`, cloud quantile 0.999) are calibrated by the
  held-out 1000 Genomes benchmark and recorded in the config so a change bumps `calibration_version`.

### What SUPPORTED means (and does not)

- G9 establishes **evidence of association** in a relevant evaluation group. It does **not** establish clinically
  useful discrimination (an AUROC of 0.55 with a CI above 0.5 passes) or calibration.
- SUPPORTED is a **research-prototype reportability state**: the percentile may be shown with its intervals. It is
  not a clinical recommendation and never an absolute risk.

## Example Queries

- "Can my breast cancer polygenic score percentile be trusted?"
- "Gate PGS000004 for this sample"
- "Is it valid to show a percentile for this admixed genome?"

## Example Output

```markdown
# PRS applicability gate: PGS001336

**Status: SUPPORTED**

## What may be reported

- Raw score: yes
- Standardised score and percentile: yes
- Absolute risk: never

| Rule | Question | Outcome | Detail |
|---|---|---|---|
| G5 SCOREABILITY | Does the computable score represent the published score (r >= r_min)? | pass | r = 0.97 ... |
| G8 PLACEMENT | Is the person placed stably inside one reference group? | pass | RESOLVED: inside the EUR reference cloud in 100% of bootstrap replicates |
| G9 EVALUATION | Is there evidence of association (95% CI above the null) in an evaluation of the person's group? | pass | 2 EUR evaluation units with a 95% CI above the null ... |
```

(Full outputs for all three statuses are produced by `--demo`; see `examples/`.)

## Output Structure

```
output_directory/
├── result.json            # summary: calibration version, gate version, config hash, one row per input
├── report.md              # summary report
├── <pgs_id>_gate.json     # full decision per input (schema prs-applicability-gate.output.v2)
└── <pgs_id>_gate.md       # rule trace per input
```

Output fields: `status`, `primary_reason`, `reason_codes`, `allowed_claims`, `evidence_used`,
`evidence_missing`, `calibration_version`, `rule_trace`, `what_would_change_result`, `provenance`
(gate version, config sha256, input digest), `disclaimer`.

## Dependencies

**Required**: `pyyaml` >= 6.0 (config). Nothing else: the gate has no network access and no randomness.

## Gotchas

- **You will want to re-run with a different reference population to get a percentile.** Do not. Reference
  choice is decided by placement upstream; G12 exists precisely to catch answers that depend on that choice.
- **You will want to call a RAW_ONLY score "roughly average".** Do not. RAW_ONLY means no relative statement is
  supported; the raw sum has no meaning on its own scale.
- **You will want to treat a pooled multi-ancestry evaluation as evidence for every group in it.** Do not; pooled
  units never count as group-specific evidence (G9).
- **You will want to read "percent of variants matched" as scoreability.** Do not; a few heavily weighted
  variants can matter more than hundreds of small ones. The gate uses r(full, reduced) measured with LD.
- **You will want to treat MAE/NR evaluations, an AUROC without a CI, or an inverse association (CI below the
  null, e.g. a case-only subtype comparison) as supporting evidence.** Do not; they are not.
- **You will want to describe a passed G9 as "the score performs well" or "is clinically useful".** Do not; it
  shows association only.
- **You will want to fill a missing field with a plausible default.** Do not; missing stays in
  `evidence_missing` and the affected rule fails.
- **You will want to present a percentile as a risk.** Never. `absolute_risk` is always false.

## Safety

- **Local-first**: the gate reads one JSON file and writes files; no network, no genotype data in its input.
- **Disclaimer**: every output carries the research-software disclaimer.
- **Audit trail**: input digest, config sha256, calibration and gate versions in every decision.
- **No hallucinated science**: every parameter traces to `config/calibration.yaml` and its documented derivation.

## Agent Boundary

The agent (LLM) may gather evidence, call this skill, and explain its output. The agent must NOT change thresholds,
edit the config, re-run until SUPPORTED, choose a score or a reference population by the personal result, fill in
missing evidence, convert a raw score into clinical or absolute risk, or override the status. The same limits
bind the deterministic scripted PRSGuard CLI orchestrator, which runs the same plan without an LLM.

## Integration with Bio Orchestrator

**Trigger conditions**: route here when a PGS result for a person exists and is about to be interpreted, or the
user asks whether a PRS percentile applies to them.

**Chaining partners**:
- PRSGuard router and `gwas-prs`: upstream (candidates, harmonised raw score).
- `claw-ancestry-pca` / PRSGuard reference placement: upstream (placement status).
- `equity-scorer`, `equity-lit-auditor`: context shown next to the decision, never an input to it.

## Maintenance

- **Review cadence**: re-run the calibration benchmarks when the reference panel, the placement method or the PGS
  Catalog schema changes; any change to `config/calibration.yaml` requires a new `calibration_version`.
- **Staleness signals**: PGS Catalog REST schema change; new evaluation deposits for the scores in use.
- **Deprecation**: the v1 gate (percentile thresholds from the hackathon) is kept in `legacy/v1` with its evals.

## Citations

- [PGS Catalog](https://www.pgscatalog.org/) (Lambert et al., Nat Genet 2021); score metadata, evaluations,
  harmonised scoring files
- [1000 Genomes Project phase 3](https://www.internationalgenome.org/) (Nature 2015); reference genotypes
- [pgsc_calc](https://github.com/PGScatalog/pgsc_calc) (Lambert et al., Nat Genet 2024); default exclusion of
  strand-ambiguous variants that this gate's inputs follow
- Martin et al., Nat Genet 2019; Privé et al., AJHG 2022; reduced PGS accuracy across ancestries, the reason
  evaluations in the person's group are required
- Brown, Cai & DasGupta, Stat Sci 2001; Jeffreys interval used for the finite-panel percentile uncertainty
