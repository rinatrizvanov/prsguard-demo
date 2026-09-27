#!/usr/bin/env bash
# PRSGuard development setup. Safe to re-run: every step checks state first.
#
#   1. .venv; with uv: `uv sync --frozen` (exact versions from uv.lock); without uv: python3 -m venv +
#      `pip install -e ".[reference,dev]"` (pyproject lower bounds only, NOT the locked versions)
#   2. vendor/ClawBio: clone https://github.com/ClawBio/ClawBio and pin it to CLAWBIO_COMMIT
#   3. make sure the interpreter can run `clawbio.py run` (installs the runner's own deps only if missing)
#   4. scripts/install_into_clawbio.py: link equity-lit-auditor + prs-applicability-gate into
#      vendor/ClawBio and register `clawbio.py run equity-lit` / `clawbio.py run prs-gate`
#   5. offline smoke test: `clawbio.py run equity-lit --demo` (synthetic fixture, no network)
#
# Usage: scripts/setup.sh [installer options, e.g. --copy]
# Env:   CLAWBIO_COMMIT (default: the pinned commit below), PYTHON (interpreter for a new venv),
#        SKIP_SMOKE=1 to skip step 5.
set -euo pipefail

CLAWBIO_URL="https://github.com/ClawBio/ClawBio"
CLAWBIO_COMMIT="${CLAWBIO_COMMIT:-0ba950565ee6a0fe9da3bde2164f6c814bd57dc9}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
VPY="$VENV/bin/python"
CLAWBIO_DIR="$REPO_ROOT/vendor/ClawBio"

say() { printf '\033[1m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[setup] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is required"
HAVE_UV=0
command -v uv >/dev/null 2>&1 && HAVE_UV=1

pip_install() {
  if [ "$HAVE_UV" = 1 ]; then
    uv pip install --python "$VPY" "$@"
  else
    "$VPY" -m pip install "$@"
  fi
}

# --- 1. virtualenv + PRSGuard ------------------------------------------------
if [ -x "$VPY" ]; then
  say "using existing $VENV ($("$VPY" --version 2>&1))"
elif [ "$HAVE_UV" = 1 ]; then
  say "creating $VENV with uv"
  uv venv --python "${PYTHON:-3.12}" "$VENV"
else
  PY="${PYTHON:-python3}"
  command -v "$PY" >/dev/null 2>&1 || die "no uv and no $PY on PATH"
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "$PY is $("$PY" --version 2>&1); PRSGuard needs Python >= 3.11"
  say "creating $VENV with $PY -m venv"
  "$PY" -m venv "$VENV"
  "$VPY" -m pip install --upgrade pip >/dev/null
fi
"$VPY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "$VENV runs $("$VPY" --version 2>&1); PRSGuard needs Python >= 3.11 (delete .venv and re-run)"

if [ "$HAVE_UV" = 1 ] && [ -f "$REPO_ROOT/uv.lock" ]; then
  say "installing PRSGuard (editable) + extras [reference,dev] at the versions pinned in uv.lock"
  (cd "$REPO_ROOT" && UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --extra reference --extra dev)
else
  say "installing PRSGuard (editable) + extras [reference,dev] with pip (uv not found: versions are NOT locked)"
  (cd "$REPO_ROOT" && pip_install -e ".[reference,dev]")
fi

# --- 2. pinned ClawBio checkout ------------------------------------------------
if [ ! -e "$CLAWBIO_DIR" ]; then
  say "cloning $CLAWBIO_URL into vendor/ClawBio"
  mkdir -p "$REPO_ROOT/vendor"
  git clone --quiet "$CLAWBIO_URL" "$CLAWBIO_DIR"
fi
git -C "$CLAWBIO_DIR" rev-parse --git-dir >/dev/null 2>&1 \
  || die "vendor/ClawBio exists but is not a git checkout; move it aside and re-run"

HEAD_NOW="$(git -C "$CLAWBIO_DIR" rev-parse HEAD)"
if [ "$HEAD_NOW" != "$CLAWBIO_COMMIT" ]; then
  # Our own installer edits tracked files (clawbio/cli.py, skills/catalog.json, counts).
  # Never discard changes silently: only move a clean tree.
  if [ -n "$(git -C "$CLAWBIO_DIR" status --porcelain --untracked-files=no)" ]; then
    die "vendor/ClawBio is at ${HEAD_NOW:0:12}, not ${CLAWBIO_COMMIT:0:12}, and has local changes.
       Inspect them (git -C vendor/ClawBio status), then either 'git -C vendor/ClawBio stash' or delete
       vendor/ClawBio, and re-run scripts/setup.sh."
  fi
  if ! git -C "$CLAWBIO_DIR" cat-file -e "${CLAWBIO_COMMIT}^{commit}" 2>/dev/null; then
    say "fetching ClawBio to find ${CLAWBIO_COMMIT:0:12}"
    git -C "$CLAWBIO_DIR" fetch --quiet origin
  fi
  say "checking out ClawBio ${CLAWBIO_COMMIT:0:12}"
  git -C "$CLAWBIO_DIR" -c advice.detachedHead=false checkout --quiet "$CLAWBIO_COMMIT"
else
  say "vendor/ClawBio already at ${CLAWBIO_COMMIT:0:12}"
fi

# --- 3. what `clawbio.py run` itself needs --------------------------------------
# The runner core is almost stdlib-only; clawbio.common.report needs opentelemetry-sdk and the
# catalog generator prefers PyYAML. PRSGuard already depends on both, so this normally installs
# nothing. We deliberately do not install ClawBio's full dependency set (BigQuery, OpenAI, ...).
PROBE='import sys; sys.path.insert(0, "."); import clawbio.cli, clawbio.common.report, clawbio.common.reproducibility, yaml'
if ! (cd "$CLAWBIO_DIR" && "$VPY" -c "$PROBE") 2>/dev/null; then
  say "installing the ClawBio runner's dependencies (opentelemetry-sdk, pyyaml)"
  pip_install "opentelemetry-sdk>=1.44.0,<2" "pyyaml>=6.0"
  (cd "$CLAWBIO_DIR" && "$VPY" -c "$PROBE") \
    || die "clawbio.py still cannot import; try: uv pip install --python .venv/bin/python -e vendor/ClawBio"
fi
say "ClawBio runner imports OK"

# --- 4. register the PRSGuard skills --------------------------------------------
"$VPY" "$REPO_ROOT/scripts/install_into_clawbio.py" --clawbio "$CLAWBIO_DIR" "$@"

# --- 5. offline smoke test ---------------------------------------------------------
if [ "${SKIP_SMOKE:-0}" != 1 ]; then
  SMOKE_DIR="$(mktemp -d)"
  trap 'rm -rf "$SMOKE_DIR"' EXIT
  say "smoke test: clawbio.py run equity-lit --demo (synthetic fixture, no network)"
  (cd "$CLAWBIO_DIR" && "$VPY" clawbio.py run equity-lit --demo --output "$SMOKE_DIR/equity_lit_demo" >/dev/null) \
    || die "clawbio.py run equity-lit --demo failed"
  "$VPY" - "$SMOKE_DIR/equity_lit_demo/result.json" <<'PY' || die "demo output is missing its SYNTHETIC DEMO flags"
import json, sys
res = json.load(open(sys.argv[1]))
assert res["synthetic"] is True and res["data_provenance"] == "SYNTHETIC DEMO", res.get("data_provenance")
print(f"[setup] demo OK: {res['summary']['papers_total']} synthetic papers, flagged {res['data_provenance']!r}")
PY
fi

say "done. Try: (cd vendor/ClawBio && ../../.venv/bin/python clawbio.py run equity-lit --pgs-trait \"type 2 diabetes\" --output /tmp/t2d)"
