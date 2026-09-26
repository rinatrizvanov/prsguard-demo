#!/usr/bin/env python3
"""Install PRSGuard's ClawBio skills into a ClawBio checkout, reproducibly.

What it does (every step is idempotent; re-running converges to the same tree):

1. Links (default) or copies (``--copy``) ``skills/equity-lit-auditor`` and
   ``skills/prs-applicability-gate`` from this repository into ``<clawbio>/skills/``.
2. Registers the CLI aliases ``equity-lit`` and ``prs-gate`` in the static ``SKILLS``
   dict of ``<clawbio>/clawbio/cli.py``, inside a clearly marked managed block. In
   ClawBio at the pinned commit that dict is the only registration that lets
   ``python clawbio.py run <alias>`` forward skill-specific flags: descriptor
   (``INTENTS.json``) skills get an empty flag allowlist by design.
3. Regenerates ``skills/catalog.json`` with ClawBio's own ``scripts/generate_catalog.py``
   (the single source of truth for routing since ClawBio 0ba9505; AGENTS.md is no
   longer edited by hand).
4. Re-derives the public counts that ClawBio's ``tests/test_public_claims.py`` checks
   (README.md, llms.txt, CITATION.cff, .zenodo.json, .claude-plugin/*.json) from the
   regenerated catalogue, using the same patterns as that test. No count is typed by hand.
5. Adds the ``equity-lit-auditor`` row to ``docs/data-handling.md`` (the skill calls
   Europe PMC and the PGS Catalog; ClawBio's ``tests/test_data_handling_doc.py``
   requires every networked skill to be listed).

Nothing here touches the contents of either skill. ``--check`` verifies an existing
installation without writing anything (exit status 1 if it is incomplete).

Usage:
    python scripts/install_into_clawbio.py                     # vendor/ClawBio, symlinks
    python scripts/install_into_clawbio.py --clawbio ~/ClawBio --copy
    python scripts/install_into_clawbio.py --check
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLAWBIO = REPO_ROOT / "vendor" / "ClawBio"
COPY_MARKER = ".prsguard-installed"

BLOCK_BEGIN = "    # >>> prsguard-managed skills (scripts/install_into_clawbio.py in the PRSGuard repo) >>>"
BLOCK_END = "    # <<< prsguard-managed skills <<<"
BLOCK_RE = re.compile(r"\n?[ \t]*# >>> prsguard-managed skills.*?# <<< prsguard-managed skills <<<[^\n]*", re.DOTALL)

# folder name -> (CLI alias, registry entry source). The entry text is Python source
# inserted verbatim into clawbio/cli.py, so it can use SKILLS_DIR like upstream entries.
SKILL_ENTRIES: dict[str, tuple[str, str]] = {
    "equity-lit-auditor": ("equity-lit", '''\
    "equity-lit": {
        "script": SKILLS_DIR / "equity-lit-auditor" / "equity_lit_auditor.py",
        "demo_args": ["--demo"],
        "description": "Genomic equity literature audit (Europe PMC + PGS Catalog; context-only equity score, heat map)",
        "allowed_extra_flags": {
            "--query", "--pmids", "--max-results", "--cascade", "--depth", "--per-paper",
            "--max-papers", "--metric", "--cache-dir", "--pgs-trait", "--pgs-ids", "--pgs-max-scores",
            "--no-fulltext", "--include-non-genomic", "--no-pgs-eval",
        },
        "allowed_extra_flags_without_values": {"--no-fulltext", "--include-non-genomic", "--no-pgs-eval"},
        # The runner starts skills with cwd = the skill folder; resolve the cache path
        # against the caller's cwd so a relative --cache-dir never lands inside the skill.
        "extra_path_flags": {"--cache-dir"},
        "no_input_required": True,
        "accepts_genotypes": False,
        # Live PGS Catalog trait audits make one API call per score plus Europe PMC lookups.
        "default_timeout_seconds": 1800,
    },
'''),
    "prs-applicability-gate": ("prs-gate", '''\
    "prs-gate": {
        "script": SKILLS_DIR / "prs-applicability-gate" / "prs_applicability_gate.py",
        "demo_args": ["--demo"],
        "description": "PRSGuard polygenic score applicability gate (skill maintained in the PRSGuard repo)",
        "allowed_extra_flags": set(),
        "accepts_genotypes": False,
    },
'''),
}

DATA_HANDLING_ROW = (
    "| `equity-lit-auditor` | www.ebi.ac.uk (Europe PMC), www.pgscatalog.org (PGS Catalog, with `--pgs-trait` / "
    "`--pgs-ids`) | Your free-text query, any seed PMIDs/PMCIDs/DOIs, the PGS trait term or score IDs; then the "
    "identifiers of papers reached through PGS Catalog links and the citation cascade. Only public bibliographic "
    "data comes back; no genotype or other personal data is read or sent. `--cache-dir` makes re-runs offline; "
    "`--demo` makes no requests. | none |"
)
DATA_HANDLING_ANCHOR = "| `lit-synthesizer` |"

# Files whose counts ClawBio's tests/test_public_claims.py compares with the catalogue.
COUNT_FILES = ["README.md", "llms.txt", "CITATION.cff", ".zenodo.json",
               ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"]
# Same shapes as test_public_claims.py (plus the "N bioinformatics Agent Skills" wording in
# marketplace.json, which the test does not match but which states the same total).
SKILL_COUNT_RE = re.compile(r"(?<![\d.,])(\d[\d,]*)(\s+(?:bioinformatics\s+)?(?:Agent\s+)?skills\b)", re.IGNORECASE)
DEMO_COUNT_RE = re.compile(r"(\d+)( with runnable demo data)")
CLI_COUNT_RE = re.compile(r"(\d+)( (?:with a deterministic CLI entry point|run deterministically from the CLI))")
STATUS_SPLIT_RE = re.compile(r"(Catalog status split: `)(\d+)(` MVP skills and `)(\d+)(` planned / legacy skills)")


def log(msg: str) -> None:
    print(f"[install_into_clawbio] {msg}")


# ---------------------------------------------------------------------------
# 1. skill folders
# ---------------------------------------------------------------------------

def _ignore(_dir, names):
    return [n for n in names if n in {"__pycache__", ".pytest_cache", ".DS_Store"} or n.endswith(".pyc")]


def link_skill(name: str, clawbio: Path, copy: bool, force: bool) -> str:
    src = REPO_ROOT / "skills" / name
    dst = clawbio / "skills" / name
    if not src.is_dir():
        raise SystemExit(f"missing source skill folder: {src}")
    if dst.is_symlink():
        if not copy and dst.resolve() == src.resolve():
            return "symlink ok"
        dst.unlink()
    elif dst.exists():
        if not (dst / COPY_MARKER).exists() and not force:
            raise SystemExit(
                f"{dst} exists and was not installed by this script (no {COPY_MARKER}). ClawBio may now ship its "
                f"own '{name}'; compare them, then re-run with --force to replace it.")
        shutil.rmtree(dst)
    if copy:
        shutil.copytree(src, dst, ignore=_ignore)
        (dst / COPY_MARKER).write_text(f"copied from {src} by scripts/install_into_clawbio.py\n", encoding="utf-8")
        return "copied"
    # Relative inside this repo (vendor/ClawBio survives moving the repo); absolute elsewhere.
    inside = clawbio.resolve().is_relative_to(REPO_ROOT.resolve())
    os.symlink(os.path.relpath(src, dst.parent) if inside else src.resolve(), dst, target_is_directory=True)
    return "symlinked"


# ---------------------------------------------------------------------------
# 2. CLI registry
# ---------------------------------------------------------------------------

def _skills_dict_node(source: str) -> ast.Dict:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                isinstance(t, ast.Name) and t.id == "SKILLS" for t in node.targets):
            return node.value
    raise SystemExit("could not find the static SKILLS dict in clawbio/cli.py; ClawBio's registry changed shape")


def _registered_aliases(source: str) -> set[str]:
    node = _skills_dict_node(source)
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def register_aliases(clawbio: Path, folders: list[str]) -> list[str]:
    cli = clawbio / "clawbio" / "cli.py"
    original = cli.read_text(encoding="utf-8")
    source = BLOCK_RE.sub("", original)
    upstream = _registered_aliases(source)
    entries, notes = [], []
    for folder in folders:
        alias, entry = SKILL_ENTRIES[folder]
        if alias in upstream:
            notes.append(f"alias '{alias}' is already registered upstream; left as is")
            continue
        entries.append(entry)
    if entries:
        node = _skills_dict_node(source)
        lines = source.splitlines(keepends=True)
        close = node.end_lineno - 1                 # 0-based line holding the closing brace
        if lines[close].strip() != "}":
            raise SystemExit("SKILLS dict does not end with a lone '}' line; refusing to edit clawbio/cli.py")
        block = BLOCK_BEGIN + "\n" + "".join(entries) + BLOCK_END + "\n"
        source = "".join(lines[:close]) + block + "".join(lines[close:])
    missing = {SKILL_ENTRIES[f][0] for f in folders} - _registered_aliases(source)
    if missing:
        raise SystemExit(f"registration check failed; aliases not in SKILLS after edit: {sorted(missing)}")
    if source != original:
        cli.write_text(source, encoding="utf-8")
        notes.append("clawbio/cli.py SKILLS updated")
    else:
        notes.append("clawbio/cli.py SKILLS already current")
    return notes


# ---------------------------------------------------------------------------
# 3-5. generated catalogue, derived counts, data-handling page
# ---------------------------------------------------------------------------

def regenerate_catalog(clawbio: Path, python: str) -> dict:
    subprocess.run([python, "scripts/generate_catalog.py"], cwd=clawbio, check=True)
    return json.loads((clawbio / "skills" / "catalog.json").read_text(encoding="utf-8"))


def sync_public_counts(clawbio: Path, catalog: dict) -> list[str]:
    skills = catalog["skills"]
    total = catalog["skill_count"]
    demo = sum(1 for s in skills if s.get("has_demo"))
    cli = sum(1 for s in skills if s.get("cli_alias"))
    mvp = sum(1 for s in skills if s.get("status") == "mvp")
    planned = sum(1 for s in skills if s.get("status") == "planned")
    changed = []
    for rel in COUNT_FILES:
        path = clawbio / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = SKILL_COUNT_RE.sub(lambda m: f"{total}{m.group(2)}", text)
        new = DEMO_COUNT_RE.sub(lambda m: f"{demo}{m.group(2)}", new)
        new = CLI_COUNT_RE.sub(lambda m: f"{cli}{m.group(2)}", new)
        new = STATUS_SPLIT_RE.sub(lambda m: f"{m.group(1)}{mvp}{m.group(3)}{planned}{m.group(5)}", new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(rel)
    return changed


def add_data_handling_row(clawbio: Path) -> str:
    doc = clawbio / "docs" / "data-handling.md"
    if not doc.exists():
        return "docs/data-handling.md not present; skipped"
    lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if not ln.startswith("| `equity-lit-auditor` |")]
    anchor = next((i for i, ln in enumerate(kept) if ln.startswith(DATA_HANDLING_ANCHOR)), None)
    if anchor is None:  # fall back to the end of the first skill table
        rows = [i for i, ln in enumerate(kept) if ln.startswith("| `")]
        if not rows:
            raise SystemExit("docs/data-handling.md has no skill table to add the equity-lit-auditor row to")
        anchor = rows[-1]
    kept.insert(anchor + 1, DATA_HANDLING_ROW + "\n")
    if kept != lines:
        doc.write_text("".join(kept), encoding="utf-8")
        return "docs/data-handling.md row written"
    return "docs/data-handling.md row already current"


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def verify(clawbio: Path, python: str, folders: list[str]) -> tuple[list[str], list[str]]:
    """Return (problems, pending). Pending = the source skill in this repo is itself
    incomplete (no SKILL.md or entry script yet); registration is in place and will
    route as soon as the files exist, after one more run of this script."""
    problems, pending = [], []
    for folder in folders:
        dst = clawbio / "skills" / folder
        if not dst.is_dir():
            problems.append(f"skills/{folder} is missing in {clawbio}")
    probe = (
        "import json, sys; sys.path.insert(0, '.'); from clawbio import cli; "
        "print(json.dumps({k: str(v['script']) for k, v in cli.SKILLS.items()}))"
    )
    out = subprocess.run([python, "-c", probe], cwd=clawbio, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return problems + [f"could not import clawbio.cli: {out.stderr.strip()[-400:]}"], pending
    registry = json.loads(out.stdout.strip().splitlines()[-1])
    catalog = {s["name"]: s for s in json.loads((clawbio / "skills" / "catalog.json").read_text())["skills"]}
    for folder in folders:
        alias = SKILL_ENTRIES[folder][0]
        script = registry.get(alias)
        src = REPO_ROOT / "skills" / folder
        if not script:
            problems.append(f"alias '{alias}' is not registered in clawbio.cli.SKILLS")
            continue
        incomplete = [p for p in (Path(script).name, "SKILL.md") if not (src / p).exists()]
        if incomplete:
            pending.append(f"skills/{folder} in this repo has no {' / '.join(incomplete)} yet: '{alias}' is registered "
                           "but cannot run or be catalogued until it does; re-run this script afterwards")
            continue
        if not Path(script).exists():
            problems.append(f"alias '{alias}' points at {script}, which does not exist")
        if catalog.get(folder, {}).get("cli_alias") != alias:
            problems.append(f"skills/catalog.json has no '{alias}' entry for {folder}; regenerate the catalogue")
    return problems, pending


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clawbio", type=Path, default=DEFAULT_CLAWBIO, help=f"ClawBio checkout (default {DEFAULT_CLAWBIO})")
    ap.add_argument("--copy", action="store_true", help="Copy the skill folders instead of symlinking them")
    ap.add_argument("--force", action="store_true", help="Replace a same-named skill folder this script did not install")
    ap.add_argument("--python", default=sys.executable, help="Interpreter used to run ClawBio's generator")
    ap.add_argument("--skills", default=",".join(SKILL_ENTRIES), help="Comma-separated subset of skill folders")
    ap.add_argument("--check", action="store_true", help="Only verify an existing installation")
    ap.add_argument("--strict", action="store_true",
                    help="Also fail (exit 1) when a source skill in this repo is still incomplete")
    args = ap.parse_args(argv)

    clawbio = args.clawbio.expanduser().resolve()
    folders = [s.strip() for s in args.skills.split(",") if s.strip()]
    unknown = set(folders) - set(SKILL_ENTRIES)
    if unknown:
        ap.error(f"unknown skill folder(s): {sorted(unknown)}")
    for required in ("clawbio/cli.py", "scripts/generate_catalog.py", "skills"):
        if not (clawbio / required).exists():
            ap.error(f"{clawbio} does not look like a ClawBio checkout (missing {required}); run scripts/setup.sh")

    if not args.check:
        for folder in folders:
            log(f"skills/{folder}: {link_skill(folder, clawbio, args.copy, args.force)}")
        for note in register_aliases(clawbio, folders):
            log(note)
        catalog = regenerate_catalog(clawbio, args.python)
        log(f"skills/catalog.json regenerated: {catalog['skill_count']} skills")
        changed = sync_public_counts(clawbio, catalog)
        log("public counts re-derived in: " + (", ".join(changed) if changed else "nothing (already current)"))
        if "equity-lit-auditor" in folders:
            log(add_data_handling_row(clawbio))

    problems, pending = verify(clawbio, args.python, folders)
    for p in pending:
        log(f"PENDING: {p}")
    for p in problems:
        log(f"ERROR: {p}")
    if not problems:
        log("OK: registered " + ", ".join(f"'python clawbio.py run {SKILL_ENTRIES[f][0]}'" for f in folders)
            + f" in {clawbio}")
    return 1 if problems or (pending and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
