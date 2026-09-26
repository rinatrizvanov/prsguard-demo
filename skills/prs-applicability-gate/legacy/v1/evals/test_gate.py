"""Correctness tests for scripts/gate.py against evals/fixtures/*.json.

Run: uv run pytest skills/prs-applicability-gate/evals
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
import gate

FIXTURES = sorted((SKILL / "evals" / "fixtures").glob("*.json"))
CFG, _ = gate.load_config(gate.DEFAULT_CONFIG)


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(path):
    case = json.loads(path.read_text())
    out = gate.evaluate(case["input"], CFG)
    expected = case["expected"]
    # Error direction: a spurious percentile is a release blocker, so flag it distinctly.
    if out["decision"] == gate.SUPPORTED:
        assert expected["decision"] == gate.SUPPORTED, f"UNSAFE: percentile released ({path.stem})"
    assert {k: out[k] for k in expected} == expected
    assert out["thresholds_version"] == CFG["version"]


def test_every_rule_covered():
    fired = {json.loads(p.read_text())["expected"]["rule_fired"] for p in FIXTURES}
    assert {f"R{i}" for i in range(12)} <= fired


def test_invalid_config_abstains():
    case = json.loads((SKILL / "evals/fixtures/r11_supported.json").read_text())
    out = gate.evaluate(case["input"], None, "missing")
    assert out["decision"] == gate.ABSTAIN and out["reason_code"] == "A_CONFIG_INVALID"


@pytest.mark.parametrize("bad", [None, [], "text", {"schema_version": "1.0"}])
def test_malformed_input_never_supports(bad):
    assert gate.evaluate(bad, CFG)["decision"] == gate.ABSTAIN


def test_abstain_carries_annotations():
    case = json.loads((SKILL / "evals/fixtures/r03_coverage_critical.json").read_text())
    out = gate.evaluate(case["input"], CFG)
    assert out["annotations"]["pgs_id"] == "PGS000001"


def test_cli():
    fixture = SKILL / "evals/fixtures/r07_pgs000001_afr_in_nr.json"
    inp = json.loads(fixture.read_text())["input"]
    proc = subprocess.run(
        [sys.executable, str(SKILL / "scripts/gate.py"), "--input", "/dev/stdin"],
        input=json.dumps(inp), capture_output=True, text=True, check=True,
    )
    assert json.loads(proc.stdout)["rule_fired"] == "R7"
