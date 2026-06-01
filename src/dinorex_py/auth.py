"""
auth.py — manages ~/.dinorex/auth.json
Shared between dinorex (npm) and dinorex-py (pip) — same file, same token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

AUTH_DIR = Path.home() / ".dinorex"
AUTH_FILE = AUTH_DIR / "auth.json"


def get_api_url() -> str:
    return os.environ.get("DINOREX_API_URL", "https://dinorex-server.onrender.com")


def load_auth() -> dict[str, Any] | None:
    try:
        if not AUTH_FILE.exists():
            return None
        return json.loads(AUTH_FILE.read_text())
    except Exception:
        return None


def save_auth(data: dict[str, Any]) -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data, indent=2))


def clear_auth() -> None:
    try:
        if AUTH_FILE.exists():
            AUTH_FILE.unlink()
    except Exception:
        pass


def api_request(
    endpoint: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    url = f"{get_api_url()}{endpoint}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = json.loads(e.read())
        msg = error_body.get("error", f"Request failed ({e.code})")
        hint = error_body.get("hint")
        raise RuntimeError(f"{msg}\n  {hint}" if hint else msg) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach Dinorex server: {e.reason}\n  Check your internet connection.") from None