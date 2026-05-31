"""
scanner.py — Finds and reads Python API source files across all major frameworks.

Supports:
  - FastAPI       : @router.get / @app.get / APIRouter
  - Flask         : @app.route / @bp.route / MethodView
  - Django        : urls.py / views.py / serializers.py / models.py
  - DRF           : ViewSet, APIView, ModelSerializer
  - Falcon        : responder methods (on_get, on_post …)
  - Sanic         : @app.route / @bp.route
  - Litestar      : @get / @post / Controller
  - Starlette     : Route(), Mount(), @app.route
  - Tornado       : RequestHandler subclasses
  - aiohttp       : app.router.add_get / add_route
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# ── Glob patterns ────────────────────────────────────────────────────────────

ROUTE_PATTERNS: list[str] = [
    "**/routes/**/*.py",
    "**/route/**/*.py",
    "**/routers/**/*.py",
    "**/router/**/*.py",
    "**/views/**/*.py",
    "**/view/**/*.py",
    "**/urls.py",
    "**/url/**/*.py",
    "**/*route*.py",
    "**/*router*.py",
    "**/*view*.py",
    "**/*views*.py",
    "**/*endpoint*.py",
    "**/*endpoints*.py",
    "**/*handler*.py",
    "**/*handlers*.py",
    "**/*resource*.py",
    "**/*resources*.py",
    "**/api/**/*.py",
    "**/app/**/*.py",
]

CONTROLLER_PATTERNS: list[str] = [
    "**/controllers/**/*.py",
    "**/controller/**/*.py",
    "**/*controller*.py",
    "**/*viewset*.py",
    "**/*ViewSet*.py",
]

SERVICE_PATTERNS: list[str] = [
    "**/services/**/*.py",
    "**/service/**/*.py",
    "**/*service*.py",
    "**/*services*.py",
]

MODEL_PATTERNS: list[str] = [
    "**/models/**/*.py",
    "**/model/**/*.py",
    "**/schemas/**/*.py",
    "**/schema/**/*.py",
    "**/serializers/**/*.py",
    "**/serializer/**/*.py",
    "**/dtos/**/*.py",
    "**/dto/**/*.py",
    "**/*model*.py",
    "**/*schema*.py",
    "**/*serializer*.py",
    "**/*entity*.py",
    "**/*pydantic*.py",
]

IGNORE_DIRS: set[str] = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "dist",
    "build",
    "migrations",
    ".mypy_cache",
    ".pytest_cache",
    "*.egg-info",
    "tests",
    "test",
}

IGNORE_FILE_SUFFIXES: tuple[str, ...] = (
    "_test.py",
    "test_.py",
    "_spec.py",
    "conftest.py",
)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class FileEntry:
    path: str       # relative to project root
    content: str


@dataclass
class ScanSummary:
    routes: int = 0
    controllers: int = 0
    services: int = 0
    models: int = 0


@dataclass
class CollectedFiles:
    routes: List[FileEntry] = field(default_factory=list)
    controllers: List[FileEntry] = field(default_factory=list)
    services: List[FileEntry] = field(default_factory=list)
    models: List[FileEntry] = field(default_factory=list)


@dataclass
class ScanResult:
    cwd: str
    summary: ScanSummary
    collected: CollectedFiles


# ── Helpers ───────────────────────────────────────────────────────────────────

def _should_ignore(path: Path) -> bool:
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    name = path.name
    for suffix in IGNORE_FILE_SUFFIXES:
        if name.endswith(suffix):
            return True
    return False


def _find_files(patterns: list[str], cwd: Path) -> list[Path]:
    seen: set[Path] = set()
    results: list[Path] = []
    for pattern in patterns:
        for match in cwd.glob(pattern):
            if match.is_file() and match not in seen:
                if not _should_ignore(match.relative_to(cwd)):
                    seen.add(match)
                    results.append(match)
    return results


def _read_file(path: Path, max_chars: int = 10_000) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + "\n\n... [truncated for length]"
        return content
    except Exception:
        return ""


def _dedup(files: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(f)
    return out


# ── Main entry ────────────────────────────────────────────────────────────────

def scan_project(target_dir: str) -> ScanResult:
    cwd = Path(target_dir).resolve()
    print(f"\n🦕 Dinorex scanning: {cwd}\n")

    route_files      = _dedup(_find_files(ROUTE_PATTERNS,      cwd))
    controller_files = _dedup(_find_files(CONTROLLER_PATTERNS, cwd))
    service_files    = _dedup(_find_files(SERVICE_PATTERNS,    cwd))
    model_files      = _dedup(_find_files(MODEL_PATTERNS,      cwd))

    def to_entries(files: list[Path]) -> list[FileEntry]:
        return [
            FileEntry(
                path=str(f.relative_to(cwd)),
                content=_read_file(f),
            )
            for f in files
        ]

    collected = CollectedFiles(
        routes=to_entries(route_files),
        controllers=to_entries(controller_files),
        services=to_entries(service_files),
        models=to_entries(model_files),
    )

    summary = ScanSummary(
        routes=len(route_files),
        controllers=len(controller_files),
        services=len(service_files),
        models=len(model_files),
    )

    return ScanResult(cwd=str(cwd), summary=summary, collected=collected)