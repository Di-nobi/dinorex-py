#!/usr/bin/env python3
"""
cli.py — dinorex-py command-line interface.

Usage:
  dinorex-py scan [DIRECTORY] [OPTIONS]
  dinorex-py login
  dinorex-py signup
  dinorex-py logout
  dinorex-py whoami
  dinorex-py upgrade
"""

from __future__ import annotations

import getpass
import importlib.metadata
import json
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
    click.echo(click.style("  🦕  DINOREX", fg="green", bold=True) + click.style(f" v{__version__}", fg="bright_black"))
    click.echo(click.style("  AI-powered API documentation — one command, full docs.", fg="bright_black"))
    click.echo()


def _print_user(auth: dict) -> None:
    user = auth["user"]
    plan_label = click.style("PRO ⚡", fg="yellow") if user["plan"] == "PRO" else click.style("Free", fg="bright_black")
    if user["plan"] == "PRO":
        scans_label = click.style("unlimited", fg="green")
    else:
        remaining = user.get("scansRemaining", 0) or 0
        limit = user.get("scanLimit", 10)
        scans_label = click.style(f"{remaining}/{limit} remaining this month", fg="white")

    click.echo(click.style("  Logged in as: ", fg="bright_black") + click.style(user["email"], fg="white"))
    click.echo(click.style("  Plan: ", fg="bright_black") + plan_label + click.style("  |  Scans: ", fg="bright_black") + scans_label)
    click.echo()


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


class Step:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text: str, color: str = "cyan"):
        self.text = text
        self.color = color
        click.echo(f"  {click.style(self.FRAMES[0], fg=color)} {text}", nl=False)

    def succeed(self, msg: str | None = None) -> None:
        click.echo(f"\r  {click.style('✓', fg='green')} {msg or self.text}   ")

    def fail(self, msg: str) -> None:
        click.echo(f"\r  {click.style('✗', fg='red')} {msg}   ")


# ── Auth flow ─────────────────────────────────────────────────────────────────

def _ensure_auth() -> dict:
    """Check auth.json — if missing, prompt signup or login."""
    from .auth import load_auth
    existing = load_auth()
    if existing:
        return existing

    click.echo(click.style("  You need an account to use Dinorex.\n", fg="yellow"))
    choice = click.prompt("  Do you have an account? (yes/no)", default="no")
    click.echo()

    if choice.lower().startswith("y"):
        return _run_login()
    else:
        return _run_signup()


def _run_signup() -> dict:
    from .auth import save_auth, api_request

    click.echo(click.style("  Create your free account\n", fg="green", bold=True))
    name = click.prompt("  Name    ")
    email = click.prompt("  Email   ")
    password = getpass.getpass("  Password: ")

    s = Step("Creating account…", color="green")
    try:
        res = api_request("/auth/signup", method="POST", body={"name": name, "email": email, "password": password})
        auth = {"token": res["token"], "user": res["user"]}
        save_auth(auth)
        s.succeed(click.style(res["message"], fg="green"))
        return auth
    except RuntimeError as e:
        s.fail(str(e))
        sys.exit(1)


def _run_login() -> dict:
    from .auth import save_auth, api_request

    click.echo(click.style("  Login to Dinorex\n", fg="green", bold=True))
    email = click.prompt("  Email   ")
    password = getpass.getpass("  Password: ")

    s = Step("Logging in…", color="green")
    try:
        res = api_request("/auth/login", method="POST", body={"email": email, "password": password})
        auth = {"token": res["token"], "user": res["user"]}
        save_auth(auth)
        s.succeed(click.style(res["message"], fg="green"))
        return auth
    except RuntimeError as e:
        s.fail(str(e))
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__)
def cli() -> None:
    """🦕 Dinorex — AI-powered API docs for Python projects."""


@cli.command("signup")
def signup() -> None:
    """Create a free Dinorex account."""
    _banner()
    auth = _run_signup()
    _print_user(auth)


@cli.command("login")
def login() -> None:
    """Login to your Dinorex account."""
    _banner()
    auth = _run_login()
    _print_user(auth)


@cli.command("logout")
def logout() -> None:
    """Logout of your Dinorex account."""
    from .auth import clear_auth
    _banner()
    clear_auth()
    click.echo(click.style("  ✓ Logged out successfully. 🦕\n", fg="green"))


@cli.command("whoami")
def whoami() -> None:
    """Show the current logged-in user."""
    from .auth import load_auth
    _banner()
    auth = load_auth()
    if not auth:
        click.echo(click.style("  Not logged in. Run: dinorex login\n", fg="yellow"))
        return
    _print_user(auth)


@cli.command("upgrade")
def upgrade() -> None:
    """Upgrade to Dinorex Pro for unlimited scans."""
    from .auth import load_auth
    _banner()
    auth = load_auth()
    if auth and auth["user"]["plan"] == "PRO":
        click.echo(click.style("  You're already on Pro! 🎉\n", fg="yellow"))
        return
    click.echo(click.style("  Upgrade to Dinorex Pro for unlimited scans.\n", fg="green"))
    click.echo(click.style("  → https://dinorex.dev/upgrade\n", fg="white"))


@cli.command("scan")
@click.argument("directory", default=".", required=False)
@click.option("-p", "--port", default=4321, show_default=True, help="Docs server port")
@click.option("--no-open", "no_open", is_flag=True, default=False, help="Skip opening browser")
def scan(directory: str, port: int, no_open: bool) -> None:
    """Scan a Python project and launch the interactive docs UI."""
    from .auth import load_auth, api_request
    from .scanner import scan_project
    from .store import diff_scan, load_store, save_store, hash_content

    _banner()

    # ── Auth check ──
    auth = _ensure_auth()
    _print_user(auth)

    target_dir = str(Path(directory).resolve())
    click.echo(click.style(f"  📂 {target_dir}\n", fg="bright_black"))

    # ── 1. Scan files locally ──
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
        click.style("Discovered: ", fg="green") +
        click.style(
            f"{summary.routes} routes  {summary.controllers} controllers  "
            f"{summary.services} services  {summary.models} models",
            fg="white",
        )
    )

    # ── 2. Check cache ──
    all_files = (
        result.collected.routes + result.collected.controllers +
        result.collected.services + result.collected.models
    )
    stored = load_store(target_dir)
    spec = None

    if stored and stored.get("spec") and stored.get("hashes"):
        diff = diff_scan(stored["hashes"], all_files)
        has_changes = diff.new_files or diff.changed_files or diff.removed_files

        if not has_changes:
            spec = stored["spec"]
            click.echo(click.style("  ✓ No changes since last scan — using cached spec.", fg="bright_black"))
        else:
            # ── 3a. Send changed files to server ──
            changed = diff.new_files + diff.changed_files
            route_paths = {f.path for f in result.collected.routes}
            ctrl_paths  = {f.path for f in result.collected.controllers}
            svc_paths   = {f.path for f in result.collected.services}
            model_paths = {f.path for f in result.collected.models}

            s2 = Step(
                f"Sending {len(diff.new_files)} new, {len(diff.changed_files)} changed files to Dinorex…",
                color="cyan",
            )
            try:
                res = api_request("/scan", method="POST", token=auth["token"], body={
                    "projectName": Path(target_dir).name,
                    "routes":      [f.__dict__ for f in changed if f.path in route_paths],
                    "controllers": [f.__dict__ for f in changed if f.path in ctrl_paths],
                    "services":    [f.__dict__ for f in changed if f.path in svc_paths],
                    "models":      [f.__dict__ for f in changed if f.path in model_paths],
                    "existingSpec": stored["spec"],
                    "removedFiles": diff.removed_files,
                })
                spec = res["spec"]
                hashes = {f.path: hash_content(f.content) for f in all_files}
                save_store(target_dir, spec, hashes)

                u = res.get("usage", {})
                usage_str = (
                    click.style("PRO — unlimited", fg="yellow")
                    if u.get("plan") == "PRO"
                    else click.style(f"{u.get('scansThisMonth', '?')}/{u.get('scanLimit', '?')} scans used", fg="bright_black")
                )
                s2.succeed(click.style("Incremental update complete. ", fg="cyan") + usage_str)
            except RuntimeError as exc:
                s2.fail(str(exc))
                sys.exit(1)
    else:
        # ── 3b. Full scan ──
        s2 = Step("Sending files to Dinorex server for analysis…", color="cyan")
        try:
            res = api_request("/scan", method="POST", token=auth["token"], body={
                "projectName": Path(target_dir).name,
                "routes":      [f.__dict__ for f in result.collected.routes],
                "controllers": [f.__dict__ for f in result.collected.controllers],
                "services":    [f.__dict__ for f in result.collected.services],
                "models":      [f.__dict__ for f in result.collected.models],
            })
            spec = res["spec"]
            hashes = {f.path: hash_content(f.content) for f in all_files}
            save_store(target_dir, spec, hashes)

            u = res.get("usage", {})
            total_endpoints = sum(len(c.get("endpoints", [])) for c in spec.get("collections", []))
            usage_str = (
                click.style("PRO — unlimited", fg="yellow")
                if u.get("plan") == "PRO"
                else click.style(f"{u.get('scansRemaining', '?')} scans remaining this month", fg="bright_black")
            )
            s2.succeed(
                click.style(f"{total_endpoints} endpoints across {len(spec.get('collections', []))} collections — ", fg="cyan") +
                usage_str
            )
        except RuntimeError as exc:
            s2.fail(str(exc))
            sys.exit(1)

    # ── 4. Start local UI server ──
    from .server import start_server

    s3 = Step(f"Starting docs UI on :{port}…", color="yellow")
    try:
        srv = start_server(target_dir, port=port, cached_spec=spec)
        time.sleep(0.5)
    except Exception as exc:
        s3.fail(str(exc))
        sys.exit(1)

    s3.succeed(click.style("Docs server running!", fg="yellow"))
    click.echo()
    click.echo(click.style(f"  ✓ Dinorex docs → {srv['url']}", fg="green", bold=True))
    click.echo(click.style("  Tip: run  dinorex scan  again to pick up new endpoints.", fg="bright_black"))
    click.echo(click.style("  Ctrl+C to stop.\n", fg="bright_black"))

    if not no_open:
        _open_browser(srv["url"])

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo(click.style("\n  Dinorex stopped. 🦕\n", fg="bright_black"))
        sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()