"""
server.py — Lightweight Flask server that serves the Dinorex UI and API.
Mirrors the same endpoints as the Node version so the same frontend works.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from .scanner import scan_project
from .store import diff_scan, load_store, save_store, ApiSpec

# Public folder lives at src/public relative to this file
_HERE = Path(__file__).parent
PUBLIC_DIR = _HERE / "public"


def create_app(
    target_dir: str,
    cached_spec: Optional[ApiSpec] = None,
    provider: str = "anthropic",
) -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)

    # ── State ────────────────────────────────────────────────────────────────
    state: dict[str, Any] = {
        "spec": cached_spec,
        "analyzing": False,
        "status": (
            {"state": "ready"}
            if cached_spec
            else {"state": "pending", "message": "Starting analysis..."}
        ),
    }

    def _get_agent():
        if provider == "groq":
            from .agent_groq import analyze_with_ai, analyze_incremental
        else:
            from .agent import analyze_with_ai, analyze_incremental
        return analyze_with_ai, analyze_incremental

    def run_analysis(force_rescan: bool = False) -> None:
        if state["analyzing"]:
            return
        state["analyzing"] = True
        try:
            result = scan_project(target_dir)
            all_files = (
                result.collected.routes
                + result.collected.controllers
                + result.collected.services
                + result.collected.models
            )
            analyze_with_ai, analyze_incremental = _get_agent()
            stored = load_store(target_dir)

            if not force_rescan and stored and stored.get("spec") and stored.get("hashes"):
                state["status"] = {
                    "state": "analyzing",
                    "message": "Checking for new/changed endpoints...",
                }
                diff = diff_scan(stored["hashes"], all_files)
                spec, changed = analyze_incremental(stored["spec"], diff)
                state["spec"] = spec
                if changed:
                    save_store(target_dir, spec, diff.new_hashes)
                    state["status"] = {
                        "state": "ready",
                        "message": "Spec updated with new endpoints.",
                    }
                else:
                    state["status"] = {"state": "ready", "message": "No changes detected."}
            else:
                state["status"] = {
                    "state": "analyzing",
                    "message": "Running full AI analysis...",
                }
                project_name = Path(target_dir).name
                spec = analyze_with_ai(result.collected, project_name)
                state["spec"] = spec

                from .store import hash_content
                hashes = {f.path: hash_content(f.content) for f in all_files}
                save_store(target_dir, spec, hashes)
                state["status"] = {"state": "ready", "message": "Full analysis complete."}

        except Exception as exc:
            state["status"] = {"state": "error", "message": str(exc)}
        finally:
            state["analyzing"] = False

    # ── Bootstrap ─────────────────────────────────────────────────────────────
    if not cached_spec:
        stored = load_store(target_dir)
        if stored and stored.get("spec"):
            state["spec"] = stored["spec"]
            state["status"] = {"state": "ready", "message": "Loaded from cache."}
            threading.Thread(target=run_analysis, args=(False,), daemon=True).start()
        else:
            threading.Thread(target=run_analysis, args=(True,), daemon=True).start()

    # ── API routes ─────────────────────────────────────────────────────────────

    @app.get("/api/status")
    def api_status():
        return jsonify(state["status"])

    @app.get("/api/spec")
    def api_spec():
        if not state["spec"]:
            return jsonify({"_loading": True, "status": state["status"]})
        return jsonify(state["spec"])

    @app.post("/api/rescan")
    def api_rescan():
        if state["analyzing"]:
            return jsonify({"message": "Already scanning..."})
        threading.Thread(target=run_analysis, args=(False,), daemon=True).start()
        return jsonify({"message": "Rescan started"})

    @app.post("/api/rescan/full")
    def api_rescan_full():
        if state["analyzing"]:
            return jsonify({"message": "Already scanning..."})
        threading.Thread(target=run_analysis, args=(True,), daemon=True).start()
        return jsonify({"message": "Full rescan started"})

    # ── Static (serve the same frontend) ──────────────────────────────────────

    @app.get("/")
    def index():
        return send_from_directory(str(PUBLIC_DIR), "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        # Try public dir first, fall back to index.html for SPA routing
        target = PUBLIC_DIR / filename
        if target.exists() and target.is_file():
            return send_from_directory(str(PUBLIC_DIR), filename)
        return send_from_directory(str(PUBLIC_DIR), "index.html")

    return app


def start_server(
    target_dir: str,
    port: int = 4321,
    cached_spec: Optional[ApiSpec] = None,
    provider: str = "anthropic",
) -> dict[str, Any]:
    app = create_app(target_dir, cached_spec=cached_spec, provider=provider)
    url = f"http://localhost:{port}"

    server_thread = threading.Thread(
        target=lambda: app.run(port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    return {"app": app, "port": port, "url": url, "thread": server_thread}