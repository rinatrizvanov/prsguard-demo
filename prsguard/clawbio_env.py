"""Locate the ClawBio checkout PRSGuard builds on and load its skills by path.

Resolution order: $CLAWBIO_ROOT, the repository PRSGuard sits in (when its
skills are installed inside a ClawBio checkout), then ``vendor/ClawBio``
(created by ``scripts/setup.sh`` at the pinned commit).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PINNED_CLAWBIO_COMMIT = "0ba950565ee6a0fe9da3bde2164f6c814bd57dc9"


@lru_cache(maxsize=1)
def clawbio_root() -> Path:
    candidates = []
    if os.environ.get("CLAWBIO_ROOT"):
        candidates.append(Path(os.environ["CLAWBIO_ROOT"]))
    candidates += [REPO_ROOT, REPO_ROOT / "vendor" / "ClawBio"]
    for c in candidates:
        if (c / "clawbio" / "common").is_dir() and (c / "skills" / "gwas-prs").is_dir():
            root = c.resolve()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            return root
    raise RuntimeError("ClawBio not found: run scripts/setup.sh or set CLAWBIO_ROOT to a ClawBio checkout")


def load_skill_module(skill: str, filename: str, module_name: str):
    """Import a ClawBio skill script by path under a unique module name (skills are not packages)."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = clawbio_root() / "skills" / skill / filename  # also puts ClawBio on sys.path
    before = list(sys.path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.path[:] = before
    return module
