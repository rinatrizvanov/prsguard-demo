#!/usr/bin/env python3
"""Deterministic PRS applicability gate.

Maps a canonical input object to PERCENTILE_SUPPORTED, RAW_SCORE_ONLY, or ABSTAIN using ordered
rules (first match wins). Fails closed: malformed input or config produces ABSTAIN, never an
exception or a percentile.

    python scripts/gate.py --input canonical.json [--config config/thresholds.yaml]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSIONS = {"1.0"}
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"
THRESHOLD_KEYS = ("min_ancestry_confidence", "coverage_hard_floor", "coverage_soft_floor",
                  "min_eval_fraction", "fraction_sum_tolerance")

UNKNOWN = "UNKNOWN"
POPULATIONS = {"AFR", "AMR", "EAS", "EUR", "SAS"}
TARGET_LABELS = POPULATIONS | {"ADMIXED"}
EVAL_LABELS = POPULATIONS | {"ADMIXED", "NR"}

ABSTAIN, RAW, SUPPORTED = "ABSTAIN", "RAW_SCORE_ONLY", "PERCENTILE_SUPPORTED"

# Tier A, score: missing -> ABSTAIN.
SCORE_FIELDS = ("prs.raw_score", "prs.variants_matched", "prs.variants_in_score",
                "pgs.eval_ancestry")
# Tier A, ancestry: missing -> RAW_SCORE_ONLY (the raw score does not depend on ancestry).
ANCESTRY_FIELDS = ("target.ancestry_label", "target.ancestry_confidence")
# Required for PERCENTILE_SUPPORTED; missing -> RAW_SCORE_ONLY.
REFERENCE_FIELD = "prs.percentile_reference_population"

# Human-readable text is generated from the reason code so explanation and record cannot drift.
# (why, what would need to change)
REASONS = {
    "A_CONFIG_INVALID": (
        "The gate's threshold configuration is missing or invalid.",
        "Fix config/thresholds.yaml.",
    ),
    "A_SCHEMA_UNSUPPORTED": (
        "The input is not a recognised canonical gate object.",
        "Rebuild the input with a supported schema_version.",
    ),
    "A_MISSING_INPUT": (
        "A value needed to interpret the score is missing.",
        "Supply the fields listed in inputs_missing.",
    ),
    "A_METADATA_CONTRADICTION": (
        "The score or ancestry metadata is internally inconsistent.",
        "Correct the upstream metadata; see the R2 trace entry.",
    ),
    "A_COVERAGE_CRITICAL": (
        ("Too few of the score's variants were found for the result to represent the "
        "published score."),
        "Use genotype data covering more of the score's variants.",
    ),
    "R_COVERAGE_LOW": (
        ("Some of the score's variants are missing, so its position in a reference "
        "distribution is unreliable."),
        "Improve variant coverage above the soft floor.",
    ),
    "R_ANCESTRY_UNKNOWN": (
        "The sample's genetic ancestry is unknown, so no reference distribution can be chosen.",
        "Supply a mappable ancestry label and confidence.",
    ),
    "R_ANCESTRY_LOW_CONFIDENCE": (
        "The sample's genetic ancestry could not be assigned with enough confidence.",
        "Improve the ancestry estimate above the confidence minimum.",
    ),
    "R_ANCESTRY_COHORT_UNRESOLVED": (
        ("The score was not evaluated in a labelled cohort of the sample's ancestry; the sample "
        "may belong to an unlabelled cohort fraction, but that cannot be confirmed."),
        "Use a score evaluated in a labelled cohort of the sample's ancestry.",
    ),
    "R_ANCESTRY_NOT_EVALUATED": (
        "The score was not evaluated in the sample's ancestry.",
        "Use a score evaluated in the sample's ancestry.",
    ),
    "R_PERCENTILE_REFERENCE_UNKNOWN": (
        "The population the percentile was computed against is unknown.",
        "Compute the percentile against a named reference population.",
    ),
    "R_PERCENTILE_REFERENCE_MISMATCH": (
        "The percentile was computed against a population different from the sample's ancestry.",
        "Use a reference distribution matching the sample's ancestry.",
    ),
    "P_SUPPORTED": (
        ("The score was evaluated in the sample's ancestry and the percentile is referenced "
        "against that population."),
        None,
    ),
}

_ABSENT = object()


def _get(obj: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(obj, dict) or key not in obj:
            return _ABSENT
        obj = obj[key]
    return obj


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _problem(path: str, v: Any) -> str | None:
    """None if v is usable for this field; otherwise why it counts as UNKNOWN."""
    if v is _ABSENT:
        return "absent"
    if v == UNKNOWN:
        return "UNKNOWN"
    if path == "prs.raw_score" or path == "target.ancestry_confidence":
        return None if _is_num(v) else f"not a number: {v!r}"
    if path in ("prs.variants_matched", "prs.variants_in_score"):
        return None if _is_int(v) else f"not an integer: {v!r}"
    if path == "target.ancestry_label":
        return None if v in TARGET_LABELS else f"outside vocabulary: {v!r}"
    if path == REFERENCE_FIELD:
        return None if v in POPULATIONS else f"not a population code: {v!r}"
    if path == "pgs.eval_ancestry":
        if not isinstance(v, list) or not v:
            return f"not a non-empty list: {v!r}"
        for g in v:
            if not isinstance(g, dict) or g.get("label") not in EVAL_LABELS \
                    or not _is_num(g.get("fraction")):
                return f"invalid entry: {g!r}"
    return None


def load_config(path: Path) -> tuple[dict | None, str]:
    try:
        cfg = yaml.safe_load(path.read_text())
    except Exception as e:  # noqa: BLE001
        return None, f"cannot read config: {e}"
    if not isinstance(cfg, dict) or not isinstance(cfg.get("version"), str):
        return None, "config missing string 'version'"
    for k in THRESHOLD_KEYS:
        if not _is_num(cfg.get(k)):
            return None, f"config missing numeric '{k}'"
    if cfg["coverage_soft_floor"] < cfg["coverage_hard_floor"]:
        return None, "coverage_soft_floor is below coverage_hard_floor"
    return cfg, ""


def _annotations(inp: Any) -> dict:
    """Tier C passthrough, carried even on ABSTAIN so a refusal names what it refused."""
    return {
        "pgs_id": _get(inp, "pgs.pgs_id"),
        "trait": _get(inp, "pgs.trait"),
        "publication": _get(inp, "pgs.publication"),
        "candidate_percentile": _get(inp, "prs.candidate_percentile"),
        "extraction_notes": _get(inp, "extraction_notes"),
    } if isinstance(inp, dict) else {}


def evaluate(inp: Any, cfg: dict | None, cfg_error: str = "") -> dict:
    trace: list[dict] = []
    used: dict[str, Any] = {}
    missing: list[str] = []

    def step(rule: str, fired: bool, detail: str) -> bool:
        trace.append({"rule": rule, "fired": fired, "detail": detail})
        return fired

    def done(decision: str, code: str, rule: str) -> dict:
        why, change = REASONS[code]
        ann = {k: v for k, v in _annotations(inp).items() if v is not _ABSENT}
        return {
            "decision": decision,
            "reason_code": code,
            "rule_fired": rule,
            "explanation": why,
            "what_would_change_it": change,
            "inputs_used": used,
            "inputs_missing": missing,
            "thresholds_version": cfg.get("version") if cfg else None,
            "trace": trace,
            "annotations": ann,
        }

    if step("CONFIG", cfg is None, cfg_error or "config ok"):
        return done(ABSTAIN, "A_CONFIG_INVALID", "CONFIG")
    assert cfg is not None

    version = _get(inp, "schema_version")
    version = None if version is _ABSENT else version
    if step("R0", version not in SCHEMA_VERSIONS, f"schema_version={version!r}"):
        return done(ABSTAIN, "A_SCHEMA_UNSUPPORTED", "R0")

    problems: dict[str, str] = {}
    for path in SCORE_FIELDS + ANCESTRY_FIELDS + (REFERENCE_FIELD,):
        v = _get(inp, path)
        p = _problem(path, v)
        if p is None:
            used[path] = v
        else:
            problems[path] = p
            missing.append(path)
    set_count = _get(inp, "pgs.eval_sample_set_count")  # Tier B: ignored when absent
    if _is_int(set_count):
        used["pgs.eval_sample_set_count"] = set_count

    # ---- ABSTAIN rules: the raw score itself cannot be trusted ----
    bad = {k: problems[k] for k in SCORE_FIELDS if k in problems}
    if step("R1", bool(bad), f"unusable: {bad}" if bad else "score inputs present"):
        return done(ABSTAIN, "A_MISSING_INPUT", "R1")

    matched, total = used["prs.variants_matched"], used["prs.variants_in_score"]
    groups = used["pgs.eval_ancestry"]
    conf = used.get("target.ancestry_confidence")
    issues = []
    if total <= 0:
        issues.append(f"variants_in_score={total} (must be > 0)")
    elif not 0 <= matched <= total:
        issues.append(f"variants_matched={matched} not within [0, variants_in_score={total}]")
    frac_sum = sum(g["fraction"] for g in groups)
    if abs(frac_sum - 1) > cfg["fraction_sum_tolerance"]:
        issues.append(f"eval_ancestry fractions sum to {frac_sum:.3f}")
    if set_count == 0 and any(g["fraction"] > 0 for g in groups):
        issues.append("non-zero eval fraction with eval_sample_set_count=0")
    if conf is not None and not 0 <= conf <= 1:
        issues.append(f"ancestry_confidence={conf} outside [0, 1]")
    if step("R2", bool(issues), "; ".join(issues) or "metadata consistent"):
        return done(ABSTAIN, "A_METADATA_CONTRADICTION", "R2")

    coverage = matched / total
    used["derived.coverage_fraction"] = round(coverage, 6)
    if step("R3", coverage < cfg["coverage_hard_floor"],
            f"coverage={coverage:.4f}, hard floor={cfg['coverage_hard_floor']}"):
        return done(ABSTAIN, "A_COVERAGE_CRITICAL", "R3")

    # ---- RAW_SCORE_ONLY rules: raw score stands, percentile withheld ----
    if step("R4", coverage < cfg["coverage_soft_floor"],
            f"coverage={coverage:.4f}, soft floor={cfg['coverage_soft_floor']}"):
        return done(RAW, "R_COVERAGE_LOW", "R4")

    bad = {k: problems[k] for k in ANCESTRY_FIELDS if k in problems}
    if step("R5", bool(bad), f"unusable: {bad}" if bad else "ancestry inputs present"):
        return done(RAW, "R_ANCESTRY_UNKNOWN", "R5")

    target = used["target.ancestry_label"]
    if step("R6", conf < cfg["min_ancestry_confidence"],
            f"ancestry_confidence={conf}, minimum={cfg['min_ancestry_confidence']}"):
        return done(RAW, "R_ANCESTRY_LOW_CONFIDENCE", "R6")

    min_frac = cfg["min_eval_fraction"]
    target_frac = sum(g["fraction"] for g in groups if g["label"] == target)
    nr_frac = sum(g["fraction"] for g in groups if g["label"] == "NR")
    evaluated = target_frac >= min_frac
    # R7 precedes R8 so the unlabelled-cohort case gets its own reason code.
    if step("R7", not evaluated and nr_frac >= min_frac,
            f"{target} fraction={target_frac:.3f}, NR fraction={nr_frac:.3f}, min={min_frac}"):
        return done(RAW, "R_ANCESTRY_COHORT_UNRESOLVED", "R7")
    if step("R8", not evaluated, f"{target} fraction={target_frac:.3f}, min={min_frac}"):
        return done(RAW, "R_ANCESTRY_NOT_EVALUATED", "R8")

    ref_problem = problems.get(REFERENCE_FIELD)
    if step("R9", ref_problem is not None,
            f"percentile_reference_population {ref_problem}" if ref_problem
            else f"reference={used[REFERENCE_FIELD]}"):
        return done(RAW, "R_PERCENTILE_REFERENCE_UNKNOWN", "R9")
    ref = used[REFERENCE_FIELD]
    if step("R10", ref != target, f"reference={ref}, target={target}"):
        return done(RAW, "R_PERCENTILE_REFERENCE_MISMATCH", "R10")

    step("R11", True, "no blocking rule matched")
    return done(SUPPORTED, "P_SUPPORTED", "R11")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()
    try:
        inp = json.loads(args.input.read_text())
    except Exception:  # noqa: BLE001 - unreadable input fails closed at R0
        inp = None
    cfg, cfg_error = load_config(args.config)
    print(json.dumps(evaluate(inp, cfg, cfg_error), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
