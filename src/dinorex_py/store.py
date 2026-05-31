"""
store.py — Saves the generated spec to .dinorex/spec.json inside the user's project.
Tracks file hashes so incremental scans only re-analyse changed files.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Types ─────────────────────────────────────────────────────────────────────

ApiSpec = Dict[str, Any]          # the full JSON spec blob
HashStore = Dict[str, str]        # { relative_path: md5_hex }


@dataclass
class DiffResult:
    new_files: List[Any] = field(default_factory=list)        # FileEntry list
    changed_files: List[Any] = field(default_factory=list)
    removed_files: List[str] = field(default_factory=list)
    unchanged: List[Any] = field(default_factory=list)
    new_hashes: HashStore = field(default_factory=dict)


# ── Paths ─────────────────────────────────────────────────────────────────────

def _store_dir(project_dir: str) -> Path:
    return Path(project_dir) / ".dinorex"


def _spec_file(project_dir: str) -> Path:
    return _store_dir(project_dir) / "spec.json"


# ── Hash ──────────────────────────────────────────────────────────────────────

def hash_content(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


# ── Load / Save ───────────────────────────────────────────────────────────────

def load_store(project_dir: str) -> Optional[dict]:
    """Returns { spec, hashes, last_scan } or None."""
    f = _spec_file(project_dir)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_store(project_dir: str, spec: ApiSpec, hashes: HashStore) -> None:
    d = _store_dir(project_dir)
    d.mkdir(parents=True, exist_ok=True)

    # keep spec out of version control
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")

    from datetime import datetime, timezone
    payload = {
        "spec": spec,
        "hashes": hashes,
        "last_scan": datetime.now(timezone.utc).isoformat(),
    }
    _spec_file(project_dir).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ── Diff ──────────────────────────────────────────────────────────────────────

def diff_scan(stored_hashes: HashStore, current_files: list) -> DiffResult:
    """
    Compare a fresh scan against stored hashes.

    Parameters
    ----------
    stored_hashes : { path: md5 }
    current_files : list[FileEntry]
    """
    current_hashes: HashStore = {
        f.path: hash_content(f.content) for f in current_files
    }

    new_files: list = []
    changed_files: list = []
    unchanged: list = []

    for f in current_files:
        prev = stored_hashes.get(f.path)
        if prev is None:
            new_files.append(f)
        elif prev != current_hashes[f.path]:
            changed_files.append(f)
        else:
            unchanged.append(f)

    current_paths = {f.path for f in current_files}
    removed_files = [p for p in stored_hashes if p not in current_paths]

    return DiffResult(
        new_files=new_files,
        changed_files=changed_files,
        removed_files=removed_files,
        unchanged=unchanged,
        new_hashes=current_hashes,
    )