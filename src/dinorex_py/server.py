"""
server.py — Lightweight Flask server that serves the Dinorex UI and API.
No longer calls AI directly — spec comes from the Dinorex backend via the CLI.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from .store import diff_scan, load_store, save_store, ApiSpec, hash_content
from .scanner import scan_project
from .auth import load_auth, api_request

_HERE = Path(__file__).parent
PUBLIC_DIR = _HERE / "public"


def create_app(
    target_dir: str,
    cached_spec: Optional[ApiSpec] = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)

    state: dict[str, Any] = {
        "spec": cached_spec,
        "analyzing": False,
        "status": (
            {"state": "ready"}
            if cached_spec
            else {"state": "pending", "message": "Starting analysis..."}
        ),
    }

    def run_analysis(force_rescan: bool = False) -> None:
        if state["analyzing"]:
            return
        state["analyzing"] = True

        try:
            auth = load_auth()
            if not auth:
                state["status"] = {"state": "error", "message": "Not authenticated. Run: dinorex login"}
                return

            result = scan_project(target_dir)
            all_files = (
                result.collected.routes + result.collected.controllers +
                result.collected.services + result.collected.models
            )
            stored = load_store(target_dir)

            if not force_rescan and stored and stored.get("spec") and stored.get("hashes"):
                state["status"] = {"state": "analyzing", "message": "Checking for new/changed endpoints..."}
                diff = diff_scan(stored["hashes"], all_files)

                if not diff.new_files and not diff.changed_files and not diff.removed_files:
                    state["spec"] = stored["spec"]
                    state["status"] = {"state": "ready", "message": "No changes detected."}
                    return

                # Send only changed files to server
                changed = diff.new_files + diff.changed_files
                route_paths  = {f.path for f in result.collected.routes}
                ctrl_paths   = {f.path for f in result.collected.controllers}
                svc_paths    = {f.path for f in result.collected.services}
                model_paths  = {f.path for f in result.collected.models}

                res = api_request("/scan", method="POST", token=auth["token"], body={
                    "projectName": Path(target_dir).name,
                    "routes":      [f.__dict__ for f in changed if f.path in route_paths],
                    "controllers": [f.__dict__ for f in changed if f.path in ctrl_paths],
                    "services":    [f.__dict__ for f in changed if f.path in svc_paths],
                    "models":      [f.__dict__ for f in changed if f.path in model_paths],
                    "existingSpec": stored["spec"],
                    "removedFiles": diff.removed_files,
                })
                state["spec"] = res["spec"]
                hashes = {f.path: hash_content(f.content) for f in all_files}
                save_store(target_dir, res["spec"], hashes)
                state["status"] = {"state": "ready", "message": "Spec updated with new endpoints."}

            else:
                state["status"] = {"state": "analyzing", "message": "Sending files to Dinorex server..."}

                res = api_request("/scan", method="POST", token=auth["token"], body={
                    "projectName": Path(target_dir).name,
                    "routes":      [f.__dict__ for f in result.collected.routes],
                    "controllers": [f.__dict__ for f in result.collected.controllers],
                    "services":    [f.__dict__ for f in result.collected.services],
                    "models":      [f.__dict__ for f in result.collected.models],
                })
                state["spec"] = res["spec"]
                hashes = {f.path: hash_content(f.content) for f in all_files}
                save_store(target_dir, res["spec"], hashes)
                state["status"] = {"state": "ready", "message": "Full analysis complete."}

        except Exception as exc:
            state["status"] = {"state": "error", "message": str(exc)}
        finally:
            state["analyzing"] = False

    # Bootstrap
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

    # ── Static ─────────────────────────────────────────────────────────────────

    @app.get("/")
    def index():
        return send_from_directory(str(PUBLIC_DIR), "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        target = PUBLIC_DIR / filename
        if target.exists() and target.is_file():
            return send_from_directory(str(PUBLIC_DIR), filename)
        return send_from_directory(str(PUBLIC_DIR), "index.html")

    return app


def start_server(
    target_dir: str,
    port: int = 4321,
    cached_spec: Optional[ApiSpec] = None,
) -> dict[str, Any]:
    app = create_app(target_dir, cached_spec=cached_spec)
    url = f"http://localhost:{port}"
    thread = threading.Thread(
        target=lambda: app.run(port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return {"app": app, "port": port, "url": url, "thread": thread}