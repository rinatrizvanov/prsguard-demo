---
name: prs-applicability-gate
description: Decides whether a polygenic risk score may be reported as a percentile, as a raw score only, or not at all. Use this whenever PRS output is about to be shown to a user, whenever ancestry and PGS Catalog metadata need to be reconciled against a target sample, and whenever someone asks whether a percentile is valid, applicable, or trustworthy for a given individual. Trigger this even when the upstream steps appear to have succeeded cleanly and even when the user only asks to "report the score" or "format the results" — an unreviewed percentile is the failure mode this skill exists to prevent.
---

# PRS Applicability Gate

Step 5 of the PRS pipeline. Upstream steps produce a score, an ancestry estimate, PGS Catalog metadata, and population context. This skill decides what may be said about them.

## Why this exists

A raw PRS is a weighted sum of allele dosages. It is always computable and always means what it says.

A percentile is a different kind of claim: it asserts where this person falls within a reference distribution. That distribution was built from a specific population. Allele frequencies and linkage disequilibrium patterns differ across populations, so a score computed in one population and read against another population's distribution does not become noisier — it becomes *shifted*. The result is confidently wrong rather than visibly uncertain, which is worse, because nothing downstream looks broken.

So the default posture is refusal. A percentile is emitted only when the evidence affirmatively supports it. Silence is a correct output.

## Division of labour

**You do extraction.** Upstream formats vary, ancestry labels are inconsistent, and API responses are sometimes incomplete or self-contradictory. Resolving that needs judgment, and that is your job.

**`scripts/gate.py` does the verdict.** Once the facts are normalized, mapping them to one of three outcomes is a lookup, not a deliberation. Running it as code means the same facts always produce the same decision and every decision is traceable to a numbered rule.

Never reason your way to a decision in prose. Build the canonical object, call the script, report what it returns.

---

## Step 1: Build the canonical object

Populate `CanonicalGateInput` from the upstream artifacts. Fields fall into three tiers, which determine what their absence means.

### Tier A — decision-critical

Never infer, never default, never carry a plausible value forward from elsewhere in the pipeline. What a missing value costs depends on what it is needed for.

| Field | Source | If missing | Notes |
|---|---|---|---|
| `prs.raw_score` | Step 1 | ABSTAIN | |
| `prs.variants_matched` | Step 1 | ABSTAIN | |
| `prs.variants_in_score` | Step 1 or step 3 | ABSTAIN | |
| `pgs.eval_ancestry` | Step 3 | ABSTAIN | List of `{label, fraction}` |
| `target.ancestry_label` | Step 2 | RAW_SCORE_ONLY | Must map to the vocabulary below |
| `target.ancestry_confidence` | Step 2 | RAW_SCORE_ONLY | Float 0–1 |
| `prs.percentile_reference_population` | Step 1 | RAW_SCORE_ONLY | Population code the percentile was computed against |

Ancestry fields withhold only the percentile: the raw score is a weighted sum of dosages and does not depend on who the sample is. A percentile additionally requires a named reference population; a percentile computed against an unknown or estimated distribution (e.g. gwas-prs's `"estimated (allele freq)"` method) is never released.

### Tier B — modifies the decision when present, ignored when absent

`pgs.eval_sample_set_count` (used by the R2 contradiction check). `pgs.gwas_ancestry` and `context.fst_target_vs_dev` are carried but not yet used by any rule.

### Tier C — annotation only, never affects the decision

`pgs.pgs_id`, `pgs.trait`, `pgs.publication`, `prs.candidate_percentile`, QC metrics, provenance URLs.

Carry all Tier C fields through to the output even on ABSTAIN. A refusal still needs to say which score it refused to interpret.

### Ancestry vocabulary

Map every ancestry string onto exactly one of: `AFR`, `AMR`, `EAS`, `EUR`, `SAS`, `ADMIXED`, `NR`, `UNKNOWN`.

`NR` means the source explicitly reported an unlabelled cohort fraction. `UNKNOWN` means you could not map the string at all. These are different and must not be collapsed — `NR` is information about the cohort, `UNKNOWN` is a failure of extraction.

Map only on clear correspondence. "European", "EUR", "White British", "CEU" → `EUR`. A cohort described as "multi-ethnic" with no breakdown is `NR`, not a guess at its composition. A label you cannot place is `UNKNOWN`, and `UNKNOWN` in a Tier A field withholds the percentile or abstains, per the table above — which is the intended behaviour, not a bug to work around.

### Tri-state fields

Every Tier A field resolves to a value, or to `UNKNOWN`. Do not use `null`, empty string, or zero to mean "not found". Zero coverage and unmeasured coverage are different facts and the gate treats them differently.

### If you cannot map a Tier A field

Set it to `UNKNOWN` and record the raw source value in `extraction_notes`. Do not drop it, do not approximate it, and do not ask the gate to proceed without it. An unmapped critical input must fail loudly, with the gate's reason code naming it.

---

## Step 2: Run the gate

```bash
python scripts/gate.py --input canonical.json --config config/thresholds.yaml
```

Rules are evaluated in order; the first match wins and evaluation stops. All ABSTAIN rules come before all RAW_SCORE_ONLY rules, so when several problems coexist the most severe outcome wins.

| # | Condition | Decision | Reason code |
|---|---|---|---|
| R0 | Schema version unrecognized | ABSTAIN | `A_SCHEMA_UNSUPPORTED` |
| R1 | A score field (`raw_score`, `variants_matched`, `variants_in_score`, `eval_ancestry`) is `UNKNOWN` | ABSTAIN | `A_MISSING_INPUT` |
| R2 | Metadata internally contradictory | ABSTAIN | `A_METADATA_CONTRADICTION` |
| R3 | `coverage_fraction` < `coverage_hard_floor` | ABSTAIN | `A_COVERAGE_CRITICAL` |
| R4 | `coverage_fraction` < `coverage_soft_floor` | RAW_SCORE_ONLY | `R_COVERAGE_LOW` |
| R5 | `ancestry_label` or `ancestry_confidence` is `UNKNOWN` | RAW_SCORE_ONLY | `R_ANCESTRY_UNKNOWN` |
| R6 | `ancestry_confidence` < `min_ancestry_confidence` | RAW_SCORE_ONLY | `R_ANCESTRY_LOW_CONFIDENCE` |
| R7 | Target ancestry below `min_eval_fraction` in `eval_ancestry`, and `NR` fraction ≥ `min_eval_fraction` | RAW_SCORE_ONLY | `R_ANCESTRY_COHORT_UNRESOLVED` |
| R8 | Target ancestry below `min_eval_fraction` in `eval_ancestry` | RAW_SCORE_ONLY | `R_ANCESTRY_NOT_EVALUATED` |
| R9 | `percentile_reference_population` is `UNKNOWN` or not a population code | RAW_SCORE_ONLY | `R_PERCENTILE_REFERENCE_UNKNOWN` |
| R10 | `percentile_reference_population` ≠ target ancestry | RAW_SCORE_ONLY | `R_PERCENTILE_REFERENCE_MISMATCH` |
| R11 | No rule above matched | PERCENTILE_SUPPORTED | `P_SUPPORTED` |

Invalid threshold configuration also abstains, with `A_CONFIG_INVALID`, before any rule runs.

Coverage takes two thresholds because coverage is continuous while the other conditions are categorical. A score matching 60 of 77 variants is a different object from one matching 5, and a single threshold would force those into the same verdict. Coverage exactly on a threshold passes it.

R7 deserves its own rule rather than folding into R8, and must come before it (R8's condition is a superset of R7's). Consider PGS000001: evaluation cohort 72.7% EUR, 9.1% EAS, 18.2% NR. For an AFR target, the metadata is not contradictory — it is merely incomplete. The target might be inside that 18.2%, or might not. That is unsupported, not unresolvable, so the raw score still stands.

### Contradiction checks for R2

`eval_ancestry` fractions summing to more than `fraction_sum_tolerance` away from 1; `variants_in_score` of zero or less; `variants_matched` outside `[0, variants_in_score]`; a non-zero ancestry fraction alongside `eval_sample_set_count` of zero; `ancestry_confidence` outside `[0, 1]`.

### Thresholds

All thresholds live in `config/thresholds.yaml` and are stamped into every output as `thresholds_version`. Never inline a number in this file or in prose. You will retune these, and reports issued under old values must remain interpretable.

---

## Step 3: Report

The gate returns:

```json
{
  "decision": "PERCENTILE_SUPPORTED | RAW_SCORE_ONLY | ABSTAIN",
  "reason_code": "...",
  "rule_fired": "R7",
  "explanation": "...",
  "what_would_change_it": "...",
  "inputs_used": {},
  "inputs_missing": [],
  "thresholds_version": "2026.09.1",
  "trace": [],
  "annotations": {}
}
```

`explanation` and `what_would_change_it` are generated from `reason_code` inside the script; use them rather than writing your own. `annotations` carries the Tier C fields.

Pass `decision` and `reason_code` through unchanged. Generate human-readable text *from* the reason code so the frontend explanation and the machine record cannot drift apart.

`inputs_missing` is the field that makes upstream instability survivable. When step 3's API parsing degrades, it shows up there rather than as a silently wrong percentile — so surface it in the report even when the decision was favourable.

### Reporting rules by decision

**PERCENTILE_SUPPORTED** — report raw score and percentile, and state which population the percentile is referenced against.

**RAW_SCORE_ONLY** — report the raw score. Do not report the percentile, do not report a range, do not describe it as "roughly average" or "on the higher end", and do not restate it in any form the reader could reconstruct a percentile from. Say plainly why it is withheld.

**ABSTAIN** — report no risk interpretation at all. Explain the reason and name what would need to change to produce one.

### Do not

Do not re-derive the decision in prose, override the gate because its output seems overcautious, or soften an ABSTAIN with a hedged estimate. Do not report `candidate_percentile` under any decision other than PERCENTILE_SUPPORTED — it is present in the input as provenance, not as a fallback.

If the gate's output looks wrong to you, that is a finding about the rules or the thresholds. Report it as such and leave the decision intact.

---

## Testing

Fixtures live in `evals/fixtures/`, each a canonical object plus its expected decision. Cover every rule, plus: the PGS000001 NR case, an ancestry label outside the vocabulary, coverage sitting exactly on each threshold, and an API response missing `eval_ancestry` entirely.

Each fixture is `{"description", "expected": {"decision", "reason_code", "rule_fired"}, "input"}`. Run the correctness suite with `uv run pytest skills/prs-applicability-gate/evals` from the project root.

Measure three things, separately:

**Correctness** — does each fixture produce its expected decision?

**Agreement** — run the same fixture five times. Identical decisions every time? This is the real determinism metric, and extraction drift shows up here as an occasional 4/5 long before it shows up as a wrong answer.

**Error direction** — never aggregate this into the pass rate. Drifting toward ABSTAIN costs a user some utility. Drifting toward PERCENTILE_SUPPORTED hands someone a clinical-adjacent risk percentile computed against a population they are not in. Treat any instance of the second kind as a release blocker regardless of the overall score.
