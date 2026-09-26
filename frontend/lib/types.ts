/**
 * Types for PRSGuard pipeline output (schema `prsguard.result.v1`) and the demo index
 * (`prsguard.demo_cases.v1`). Derived from the committed demo JSONs in public/demo.
 *
 * Fields that are absent in some real outputs (e.g. an UNRESOLVED placement has no plot,
 * a withheld percentile has no intervals) are optional or nullable. Components must treat
 * every released value as present ONLY when the JSON releases it; the UI never derives
 * a percentile, standardized score or risk on its own.
 */

export type GateStatus = "SUPPORTED" | "RAW_ONLY" | "ABSTAIN";
export type PlacementStatus = "RESOLVED" | "INTERMEDIATE" | "UNSTABLE" | "UNRESOLVED";
export type CrossPgsStatus = "NOT_COMPARABLE" | "CONSISTENT" | "DISCORDANT";
export type Actor = "AGENT_ACTION" | "DETERMINISTIC_DECISION";
export type RuleOutcome = "pass" | "fail" | "not_applicable";
export type Interval = [number, number];
export type PC3 = [number, number, number];

/* ------------------------------------------------------------------ demo index */

export interface DemoCaseIndexEntry {
  id: string;
  title: string;
  description: string;
  file: string;
  sample: string;
  population: string;
  superpopulation: string;
  sex: string;
  format: string;
  n_sites: number;
  derivation: string;
  provenance: string;
  synthetic: boolean;
  same_individual_as: string | null;
  trait: string;
  label: string;
}

export interface DemoCaseIndex {
  schema: string;
  seed: number;
  note: string;
  cases: DemoCaseIndexEntry[];
}

/* ------------------------------------------------------------------ header / input */

export interface ResultLabel {
  case_id?: string | null;
  case_title?: string | null;
  data_provenance?: string | null;
  synthetic?: boolean | null;
  description?: string | null;
}

export interface Headline {
  answer: GateStatus;
  text: string;
  counts: Partial<Record<GateStatus, number>>;
  primary: string | null;
  placement: PlacementStatus | string;
}

export interface GenotypeInput {
  file: string;
  format: string;
  sha256: string;
  n_records: number;
  n_called: number;
}

export interface InputInfo {
  trait_query: string;
  sex: string | null;
  declared_build: string | null;
  genotype: GenotypeInput;
}

export interface BuildInfo {
  build: string | null;
  header_declared?: string | null;
  user_declared?: string | null;
  grch37_rsid_sites_checked?: number | null;
  grch37_position_agreement?: number | null;
  grch38_rsid_sites_checked?: number | null;
  grch38_position_agreement?: number | null;
  rule?: string;
  method?: string;
}

export interface TraceStep {
  step: number;
  actor: Actor;
  title: string;
  tool: string;
  summary: string;
  outputs?: Record<string, unknown>;
  started_at?: string;
  finished_at?: string;
}

/* ------------------------------------------------------------------ router */

export interface TraitTerm {
  id: string;
  label: string;
}

export interface ScopeTerm extends TraitTerm {
  sex: string | null;
  reason: string;
}

export interface RouterTrait {
  query: string;
  router_version?: string;
  search_hits?: TraitTerm[];
  status: string;
  detail?: string;
  term?: TraitTerm;
  scope?: ScopeTerm[];
  excluded_children?: ScopeTerm[];
  scope_rule?: string;
}

export interface RankingEvidence {
  ancestry_groups_with_metrics: string[];
  units_with_metrics: number;
  units: number;
  total_evaluation_n: number;
}

export interface Publication {
  pgp_id?: string;
  pmid?: string | null;
  doi?: string | null;
  title?: string;
  journal?: string;
  first_author?: string;
  date_publication?: string;
}

export interface EligibleScore {
  pre_rank: number;
  pgs_id: string;
  name: string;
  trait_reported: string;
  variants_number: number;
  sex_specific: string | null;
  date_release?: string;
  ranking_evidence: RankingEvidence;
  publication?: Publication;
}

export interface CatalogInfo {
  mode: string;
  release: string;
  api_version: string;
}

export interface RouterOptions {
  sex: string | null;
  build: string | null;
  max_variants: number | null;
  top_k: number;
}

export interface RouterInfo {
  trait: RouterTrait;
  options: RouterOptions;
  eligibility_rules: string[];
  ranking_rules: string[];
  n_found: number;
  n_eligible: number;
  selected: string[];
  digest: string;
  frozen_at: string;
  catalog: CatalogInfo;
  excluded_summary: ExcludedSummary;
  eligible: EligibleScore[];
  status?: string;
}

/** Excluded scores per rule: a score can fail several rules, so the counts need not sum to n_excluded. */
export interface ExcludedSummary {
  n_excluded: number;
  scores_failing_rule: Record<string, number>;
  excluded_only_by_engineering_E8: number;
}

/* ------------------------------------------------------------------ placement */

export interface PlacementPlot {
  reference: { pc: PC3; group: string; pop: string }[];
  admixed_reference: { pc: PC3; pop: string }[];
  target: PC3;
  bootstrap: PC3[];
}

export interface SelfMatch {
  checked_sites: number;
  matches: string[];
  max_concordance: number;
  rule: string;
}

export interface Placement {
  method: string;
  reference: string;
  k_pcs: number;
  cloud_quantile: number;
  n_panel_sites: number;
  n_sites_used: number;
  policy: { min_sites: number; min_stability: number; bootstrap: number; seed: number };
  excluded_reference_samples: string[];
  status: PlacementStatus;
  placement: string | null;
  nearest_reference?: string | null;
  mahalanobis_d2?: Record<string, number>;
  cloud_cut_d2?: number;
  inside_clouds?: string[];
  placement_stability?: number | null;
  bootstrap_placements?: Record<string, number>;
  supervised_admixture_context?: Record<string, number> | null;
  consistent_populations?: string[];
  population_d2?: Record<string, number>;
  variance_explained?: number[];
  detail?: string;
  self_match?: SelfMatch;
  note: string;
  plot: PlacementPlot | null;
}

/* ------------------------------------------------------------------ candidates */

export interface ScoringFile {
  name: string;
  build: string;
  sha256: string;
  url: string;
}

export interface Scoreability {
  r: number | null;
  method: string;
  r_unadjusted?: number | null;
  spearman?: number | null;
  panel_variance_share?: number | null;
  measured_in?: string | null;
  n_samples?: number | null;
  fraction_scoring_variants_in_panel?: number | null;
}

export interface Harmonisation {
  n_variants: number;
  n_matched: number;
  status_counts: Record<string, number>;
  n_located?: number;
  allele_mismatch_fraction?: number | null;
  weight_loss_by_status: Record<string, number>;
  fraction_matched?: number;
  fraction_abs_weight_matched?: number;
  top5pct_weight_variants_missing?: number;
  position_matching?: boolean;
  notes?: string[];
  scoreability?: Scoreability | null;
}

export interface RuleTraceEntry {
  rule: string;
  name: string;
  question: string;
  outcome: RuleOutcome | string;
  effect: GateStatus | string | null;
  codes: string[];
  detail: string;
  what_would_change: string | null;
}

export interface GateReason {
  code: string;
  rule: string;
  detail: string;
  meaning: string;
}

export interface WhatWouldChange {
  rule: string;
  code: string;
  change: string;
}

export interface GateProvenance {
  gate: string;
  gate_version: string;
  config_sha256: string;
  input_digest: string;
  deterministic: boolean;
}

export interface Gate {
  schema?: string;
  pgs_id: string;
  status: GateStatus;
  primary_reason: GateReason | null;
  reason_codes: string[];
  allowed_claims: Partial<Record<"raw_score" | "standardized_score" | "percentile" | "absolute_risk", boolean>>;
  evidence_used?: Record<string, unknown>;
  evidence_missing?: unknown[];
  calibration_version?: string;
  rule_trace: RuleTraceEntry[];
  what_would_change_result: WhatWouldChange[];
  provenance?: GateProvenance;
  disclaimer?: string;
}

export interface ReleasedValue {
  released: boolean;
  value: number | null;
  meaning?: string;
}

export interface SubpopulationPercentile {
  percentile: number;
  ci_panel?: Interval;
  n_reference?: number;
}

export interface PercentileValue extends ReleasedValue {
  ci_panel?: Interval;
  missing_variant_interval?: Interval;
  combined_interval?: Interval;
  reference_group?: string;
  reference_n?: number;
  subpopulation_percentiles?: Record<string, SubpopulationPercentile>;
}

export interface Interpretation {
  status: GateStatus;
  raw_score: ReleasedValue;
  standardized_score: ReleasedValue;
  percentile: PercentileValue;
  absolute_risk: ReleasedValue;
  withheld?: { items: string[]; because: string[] } | null;
}

export interface StageComposition {
  distribution_pct: Record<string, number>;
  n_individuals?: number | null;
  unit: string;
  reported?: boolean;
  sample_set_count?: number;
  n_individuals_by_code?: Record<string, number>;
  sample_sets_by_code?: Record<string, number>;
}

export interface CountryEvidence {
  country: string;
  iso3: string | null;
  name: string | null;
  stage: string;
  n: number;
  units: number;
  codes: string[];
}

export interface EvaluationMetric {
  name: string;
  estimate: number;
  ci_lower: number | null;
  ci_upper: number | null;
  null: number | null;
  informative: boolean | null;
}

export interface EvaluationUnit {
  pgp_id: string;
  pss_id: string;
  code: string;
  pooled: boolean;
  n: number;
  cases: number | null;
  percent_male: number | null;
  countries: string[];
  metrics: EvaluationMetric[];
  covariates?: string[];
}

export interface ConsistencyCheck {
  check_id: string;
  status: string;
  detail: string;
  blocking: boolean;
  kind: string;
}

export interface PopulationEvidence {
  stages: Partial<Record<"gwas" | "development" | "evaluation", StageComposition>>;
  countries: CountryEvidence[];
  countries_note?: string;
  evaluation_units: EvaluationUnit[];
  publications: Record<string, Publication>;
  consistency_checks: ConsistencyCheck[];
}

export interface EquityScorerContext {
  note: string;
  source_skill: string;
  fst_method?: string;
  person_group: string | null;
  compared_stage?: string;
  fst_to_stage_groups: Record<string, { percent_of_stage: number; fst_to_person_group: number | null }> | null;
  evaluation_representation_index?: {
    representation_index: number | null;
    unknown_fraction: number | null;
    warning: string | null;
  } | null;
}

export interface GwasPrsCrosscheck {
  note: string;
  source_skill: string;
  variants: number;
  agree: boolean | null;
  detail?: string;
  prsguard_partial_sum?: number;
  gwas_prs_partial_sum?: number;
  why_not_primary?: string;
}

export interface CatalogResponse {
  endpoint: string;
  url: string;
  file?: string;
  sha256: string;
  retrieved_at: string;
}

export interface Candidate {
  pgs_id: string;
  pre_rank: number;
  name: string;
  trait_reported: string;
  variants_number: number;
  weight_type: string;
  publication: Publication;
  method_name: string;
  ranking_evidence: RankingEvidence;
  sex_specific: string | null;
  scoring_file: ScoringFile;
  harmonisation: Harmonisation;
  gate: Gate;
  interpretation: Interpretation;
  population_evidence: PopulationEvidence;
  context: {
    equity_scorer?: EquityScorerContext | null;
    gwas_prs_crosscheck?: GwasPrsCrosscheck | null;
  };
  provenance: {
    catalog_responses: CatalogResponse[];
    gate_input_digest?: string;
  };
}

/* ------------------------------------------------------------------ cross-PGS */

export interface CrossPgsPair {
  a: string;
  b: string;
  variant_overlap_jaccard: number;
  shared_variants: number;
  weighted_overlap: Record<string, number>;
  shared_source_gwas: string[];
  reference_group: string;
  percentiles: Record<string, number>;
  combined_intervals: Record<string, Interval>;
  reference_correlation: number;
  person_percentile_gap: number;
  reference_gap_95: Interval;
  gap_quantile_in_reference: number;
  n_reference: number;
  status: CrossPgsStatus | string;
  dependence_note: string;
}

export interface CrossPgs {
  compared: string[];
  rule: string;
  pairs: CrossPgsPair[];
  status: CrossPgsStatus;
  detail: string;
}

/* ------------------------------------------------------------------ literature context */

export interface RubricComponent {
  points: number;
  max: number;
}

export interface LiteraturePaper {
  id: string;
  pmid: string | null;
  doi: string | null;
  title: string;
  year: string | null;
  journal: string | null;
  first_author: string | null;
  linked_scores: string[];
  source: string;
  equity_score: number | null;
  components: Record<string, RubricComponent>;
  flags: string[];
  ancestry_n: Record<string, number | null>;
  country_n: Record<string, number | null>;
  total_n: number | null;
}

export interface LiteratureContext {
  note: string;
  source_skill: string;
  skill_version: string;
  synthetic: boolean;
  data_provenance: string;
  role: string;
  feeds_applicability_decision: boolean;
  query: { pgs_ids: string[] };
  semantics: { role: string; feeds_applicability_decision: boolean; scale: string; note: string };
  provenance: {
    synthetic: boolean;
    data_provenance: string;
    sources: Record<string, string>;
    retrieved_at: string;
    note: string;
  };
  completed_at?: string;
  summary: {
    papers_total: number;
    papers_with_population_data: number;
    papers_european_only: number;
    median_equity_score: number | null;
    mean_equity_score: number | null;
    countries: number;
    participants_extracted: number;
    ancestry_share_basis: string;
    flags: Record<string, number>;
    extraction_check?: { papers: number; curated_groups: number; recovered: number; recall: number | null };
    retrieval_warnings: string[];
  };
  ancestry_share: Record<string, number>;
  stage_ancestry: Record<string, Record<string, number>>;
  countries: { iso3: string; name: string; participants: number; papers: number }[];
  rubric: Record<string, unknown>[];
  papers: LiteraturePaper[];
}

/* ------------------------------------------------------------------ reproducibility */

export interface Reproducibility {
  prsguard_version: string;
  git_commit: string | null;
  git_dirty?: boolean | null;
  clawbio_commit?: string | null;
  clawbio_pinned?: string | null;
  python?: string;
  platform?: string;
  packages?: Record<string, string>;
  hashes?: Record<string, string>;
  calibration_version?: string;
  seeds?: Record<string, number>;
  catalog?: CatalogInfo;
  started_at?: string;
  finished_at?: string;
  command?: string;
}

/* ------------------------------------------------------------------ top level */

export interface PrsGuardResult {
  schema: "prsguard.result.v1" | string;
  question: string;
  label: ResultLabel;
  headline: Headline;
  input: InputInfo;
  build: BuildInfo;
  trace: TraceStep[];
  router: RouterInfo;
  placement: Placement;
  candidates: Candidate[];
  cross_pgs: CrossPgs;
  primary: { pgs_id: string | null; rule: string };
  literature_context?: LiteratureContext | null;
  reproducibility: Reproducibility;
  disclaimer: string;
}

/** Where the result on screen came from. */
export type ResultSource =
  | { kind: "demo"; caseId: string; entry?: DemoCaseIndexEntry }
  | { kind: "local"; fileName: string; analysedAt: string };
