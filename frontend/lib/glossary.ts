/**
 * Human-readable glossary for reason codes and statuses. Mirrors the descriptions in
 * skills/prs-applicability-gate (gate v2.1.0). Used only for labels and tooltips: every
 * decision shown in the UI is read from the result JSON, never re-derived here.
 */

export const REASON_CODES: Record<string, string> = {
  INVALID_GATE_INPUT: "The gate input is missing required fields, has wrong types, or fails its digest.",
  UNSUPPORTED_SCORE_FORMAT:
    "The scoring file is not a plain additive log-scale score (ratio weights, dosage-specific weights, haplotype/interaction terms, or unreadable rows).",
  BUILD_UNRESOLVED: "The genotype file's genome build could not be established; positions cannot be trusted.",
  ALLELE_HARMONIZATION_FAILED:
    "Too many located variants have alleles that cannot be reconciled with the scoring file (wrong strand/build/file suspected).",
  LOW_SCOREABILITY: "The score computable from this genotype correlates too weakly with the published score.",
  SCOREABILITY_UNVERIFIED:
    "No reference panel or allele frequencies to measure how well the computable score represents the published score.",
  PALINDROMIC_VARIANT_UNRESOLVED: "Excluded strand-ambiguous (A/T, C/G) variants are the largest loss.",
  VARIANTS_MISSING: "Variants absent from the genotype file are the largest loss.",
  DUPLICATE_OR_CONFLICTING_VARIANTS: "Duplicated or position-conflicting variants are the largest loss.",
  SEX_POPULATION_MISMATCH: "The score or all of its relevant evaluations are specific to the other sex.",
  SEX_NOT_PROVIDED: "The score is sex-specific but the person's sex was not provided.",
  METADATA_CONTRADICTION: "PGS Catalog metadata for this score failed a blocking consistency check.",
  EVALUATION_METADATA_UNAVAILABLE: "PGS Catalog metadata for this score could not be retrieved.",
  TARGET_REFERENCE_UNRESOLVED:
    "The person could not be placed stably inside one reference group (intermediate/admixed, unstable, or too few sites).",
  NO_RELEVANT_EVALUATION: "No single-ancestry evaluation in the person's reference group reports a metric.",
  EVALUATION_NOT_INFORMATIVE:
    "Relevant evaluations exist but none shows evidence of association in the score's direction (no metric's 95% CI lies entirely above the null).",
  REFERENCE_DISTRIBUTION_UNAVAILABLE: "No reference distribution on the person's matched variant set.",
  REFERENCE_SENSITIVE: "The percentile depends on which reference population is chosen within the group.",
};

export function reasonMeaning(code: string): string {
  return REASON_CODES[code] ?? code;
}
