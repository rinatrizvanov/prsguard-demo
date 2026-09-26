"""ClawBio registration of the PRSGuard skills (needs the pinned vendor/ClawBio checkout from scripts/setup.sh).

`clawbio.py run` is the interface an LLM agent uses. The gate's calibration must not be replaceable through it:
`--config` is deliberately NOT forwarded (the runner drops unregistered flags), so a run through ClawBio always uses
the shipped config/calibration.yaml. Calibration research uses the gate's own CLI, whose outputs are labelled
non-canonical.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from prsguard.clawbio_env import REPO_ROOT

CLAWBIO = REPO_ROOT / "vendor" / "ClawBio"
GATE = REPO_ROOT / "skills" / "prs-applicability-gate"
pytestmark = pytest.mark.skipif(not (CLAWBIO / "clawbio.py").exists(), reason="run scripts/setup.sh first")


def _installer():
    spec = importlib.util.spec_from_file_location("_installer", REPO_ROOT / "scripts" / "install_into_clawbio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prs_gate_registration_forwards_no_extra_flags():
    alias, entry = _installer().SKILL_ENTRIES["prs-applicability-gate"]
    assert alias == "prs-gate"
    assert '"allowed_extra_flags": set()' in entry and "--config" not in entry


def test_runner_cannot_replace_the_gate_calibration(tmp_path):
    example = GATE / "examples" / "case_B_PGS001336.gate_input.json"
    out = tmp_path / "out"
    proc = subprocess.run([sys.executable, "clawbio.py", "run", "prs-gate", "--input", str(example), "--output",
                           str(out), "--config", str(tmp_path / "does_not_exist.yaml")],
                          cwd=CLAWBIO, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    summary = json.loads((out / "result.json").read_text())
    shipped = "sha256:" + __import__("hashlib").sha256((GATE / "config" / "calibration.yaml").read_bytes()).hexdigest()
    assert summary["config_sha256"] == shipped and summary["config_canonical"] is True
    assert [r["status"] for r in summary["results"]] == ["SUPPORTED"]
