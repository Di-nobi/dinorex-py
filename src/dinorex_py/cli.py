#!/usr/bin/env python3
"""
cli.py — dinorex-py command-line interface.

Usage:
  dinorex-py scan [DIRECTORY] [OPTIONS]

Options:
  -p, --port       Port for the docs server (default 4321)
  --no-open        Skip auto-opening browser
  --api-key        Anthropic or Groq API key
  --provider       anthropic (default) | groq
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import time
from pathlib import Path

import click

try:
    __version__ = importlib.metadata.version("dinorex-py")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner() -> None:
    click.echo()
    click.echo(click.style("  🦕  DINOREX-PY", fg="green", bold=True) + click.style(f" v{__version__}", fg="bright_black"))
    click.echo(click.style("  AI-powered API documentation for Python — one command, full docs.", fg="bright_black"))
    click.echo()


def _check_api_key(provider: str, api_key: str | None) -> None:
    if provider == "anthropic":
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        if not os.environ.get("ANTHROPIC_API_KEY"):
            click.echo(click.style("  ✗ ANTHROPIC_API_KEY is not set.\n", fg="red"))
            click.echo(click.style("  Option 1 — env var:  export ANTHROPIC_API_KEY=sk-ant-...", fg="bright_black"))
            click.echo(click.style("  Option 2 — flag:     dinorex-py scan --provider anthropic --api-key sk-ant-...", fg="bright_black"))
            click.echo()
            sys.exit(1)
    else:
        if api_key:
            os.environ["GROQ_API_KEY"] = api_key
        if not os.environ.get("GROQ_API_KEY"):
            click.echo(click.style("  ✗ GROQ_API_KEY is not set.\n", fg="red"))
            click.echo(click.style("  Get a free key at: https://console.groq.com", fg="bright_black"))
            click.echo(click.style("  Then: export GROQ_API_KEY=gsk_your_key_here", fg="bright_black"))
            click.echo(click.style("  Or:   dinorex-py scan --api-key gsk_...", fg="bright_black"))
            click.echo(click.style("  To use Anthropic: dinorex-py scan --provider anthropic --api-key sk-ant-...", fg="bright_black"))
            click.echo()
            sys.exit(1)


def _open_browser(url: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        elif sys.platform == "win32":
            subprocess.run(["start", url], shell=True, check=False)
        else:
            subprocess.run(["xdg-open", url], check=False)
    except Exception:
        pass


def _spinner(text: str) -> "click.progressbar":
    """Minimal spinner using click.echo + carriage return."""
    return text  # used with the _step context manager below


class Step:
    """Simple console step indicator (no external spinner dep)."""
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text: str, color: str = "cyan"):
        self.text = text
        self.color = color
        self._i = 0
        click.echo(f"  {click.style(self.FRAMES[0], fg=color)} {text}", nl=False)

    def succeed(self, msg: str | None = None) -> None:
        click.echo(f"\r  {click.style('✓', fg='green')} {msg or self.text}   ")

    def fail(self, msg: str) -> None:
        click.echo(f"\r  {click.style('✗', fg='red')} {msg}   ")


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__)
def cli() -> None:
    """🦕 Dinorex-py — AI-powered API docs for Python projects."""


@cli.command("scan")
@click.argument("directory", default=".", required=False)
@click.option("-p", "--port", default=4321, show_default=True, help="Docs server port")
@click.option("--no-open", "no_open", is_flag=True, default=False, help="Skip opening browser")
@click.option("--api-key", "api_key", default=None, help="Anthropic or Groq API key")
@click.option(
    "--provider",
    default=lambda: os.environ.get("DINOREX_PROVIDER", "anthropic"),
    show_default=True,
    help="AI provider: anthropic (default) | groq",
)
def scan(directory: str, port: int, no_open: bool, api_key: str | None, provider: str) -> None:
    """Scan a Python project and launch the interactive docs UI."""
    _banner()
    _check_api_key(provider, api_key)

    target_dir = str(Path(directory).resolve())
    click.echo(click.style(f"  📂 {target_dir}", fg="bright_black"))
    click.echo(click.style(f"  🤖 Provider: {provider}\n", fg="bright_black"))

    # ── 1. Scan ──────────────────────────────────────────────────────────────
    from .scanner import scan_project

    s1 = Step("Scanning project files…", color="green")
    try:
        result = scan_project(target_dir)
    except Exception as exc:
        s1.fail(str(exc))
        sys.exit(1)

    summary = result.summary
    total = summary.routes + summary.controllers + summary.services + summary.models
    if not total:
        s1.fail("No API files found. Make sure you're in a Flask/FastAPI/Django project.")
        sys.exit(1)

    s1.succeed(
        click.style("Discovered: ", fg="green")
        + click.style(
            f"{summary.routes} routes  {summary.controllers} controllers  "
            f"{summary.services} services  {summary.models} models",
            fg="white",
        )
    )

    # ── 2. AI analysis ────────────────────────────────────────────────────────
    if provider == "groq":
        from .agent_groq import analyze_with_ai, analyze_incremental
    else:
        from .agent import analyze_with_ai, analyze_incremental

    from .store import diff_scan, load_store, save_store, hash_content

    all_files = (
        result.collected.routes
        + result.collected.controllers
        + result.collected.services
        + result.collected.models
    )
    stored = load_store(target_dir)
    spec = None

    if stored and stored.get("spec") and stored.get("hashes"):
        diff = diff_scan(stored["hashes"], all_files)
        has_changes = diff.new_files or diff.changed_files or diff.removed_files

        if has_changes:
            s2 = Step(
                f"Incremental update — {len(diff.new_files)} new, "
                f"{len(diff.changed_files)} changed files…",
                color="cyan",
            )
            try:
                spec, _ = analyze_incremental(stored["spec"], diff)
                hashes = {f.path: hash_content(f.content) for f in all_files}
                save_store(target_dir, spec, hashes)
                s2.succeed(click.style("Incremental update complete.", fg="cyan"))
            except Exception as exc:
                s2.fail(str(exc))
                sys.exit(1)
        else:
            spec = stored["spec"]
            click.echo(click.style("  ✓ No changes since last scan — using cached spec.", fg="bright_black"))
    else:
        s2 = Step("Running full AI analysis (~15s)…", color="cyan")
        try:
            spec = analyze_with_ai(result.collected, Path(target_dir).name)
            hashes = {f.path: hash_content(f.content) for f in all_files}
            save_store(target_dir, spec, hashes)
            total_endpoints = sum(len(c.get("endpoints", [])) for c in spec.get("collections", []))
            s2.succeed(
                click.style("Analysis complete — ", fg="cyan")
                + click.style(
                    f"{total_endpoints} endpoints across {len(spec.get('collections', []))} collections",
                    fg="white",
                )
            )
        except Exception as exc:
            s2.fail(str(exc))
            sys.exit(1)

    # ── 3. Start server ───────────────────────────────────────────────────────
    from .server import start_server

    s3 = Step(f"Starting docs server on :{port}…", color="yellow")
    try:
        srv = start_server(target_dir, port=port, cached_spec=spec, provider=provider)
        time.sleep(0.5)  # let Flask bind
    except Exception as exc:
        s3.fail(str(exc))
        sys.exit(1)

    s3.succeed(click.style("Docs server running!", fg="yellow"))

    click.echo()
    click.echo(click.style(f"  ✓ Dinorex docs → {srv['url']}", fg="green", bold=True))
    click.echo()
    click.echo(click.style("  Tip: run  dinorex-py scan  again anytime to pick up new endpoints.", fg="bright_black"))
    click.echo(click.style("  Ctrl+C to stop.\n", fg="bright_black"))

    if not no_open:
        _open_browser(srv["url"])

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo(click.style("\n  Dinorex stopped. 🦕\n", fg="bright_black"))
        sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()