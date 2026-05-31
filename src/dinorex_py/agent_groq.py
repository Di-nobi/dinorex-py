"""
agent_groq.py — Free Groq/Llama3 version of the dinorex-py AI agent.

Get a free key at: https://console.groq.com
Set it: export GROQ_API_KEY=gsk_your_key_here

To use instead of the Anthropic agent, pass --provider groq to the CLI.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .scanner import CollectedFiles
from .store import ApiSpec, DiffResult

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
MAX_CHARS = 12_000


# ── Prompts (same as agent.py) ────────────────────────────────────────────────

SYSTEM_FULL = """You are an expert API analyst. Analyse Python backend source code and extract a complete API specification.

Supported frameworks — recognise ALL of these:

Routing / controllers:
- FastAPI   : @app.get / @router.get / @router.post / APIRouter
- Flask     : @app.route / @bp.route / MethodView / Flask-RESTful Resource
- Django    : urlpatterns = [path(...)] in urls.py; class-based views
- DRF       : ViewSet, APIView, @action decorator
- Falcon    : on_get / on_post / on_put / on_patch / on_delete methods
- Sanic     : @app.route / @bp.route
- Litestar  : @get / @post / @put / @patch / @delete / Controller subclasses
- Starlette : Route() / Mount()
- Tornado   : RequestHandler subclasses
- aiohttp   : app.router.add_get / RouteTableDef

Models / schemas:
- Pydantic v1 & v2, Django ORM, DRF Serializers, SQLAlchemy, Tortoise ORM, Marshmallow

Rules:
- Return ONLY valid JSON. No markdown, no explanation, no code fences.
- Infer realistic example values from field names and Python types.
- Group endpoints into logical collections (e.g. "Users", "Auth", "Products").
- Detect auth: Depends(get_current_user), @login_required, IsAuthenticated, JWTAuthentication → requiresAuth: true.
- For DRF ViewSets infer full CRUD. For Django urls.py combine include() prefix with path() patterns.
- Pydantic Optional[T] or field with default → required: false.

Return ONLY this JSON structure:
{
  "projectName": "string",
  "baseUrl": "http://localhost:8000",
  "version": "1.0.0",
  "description": "string",
  "collections": [
    {
      "name": "string",
      "description": "string",
      "endpoints": [
        {
          "id": "unique-kebab-slug",
          "method": "GET|POST|PUT|PATCH|DELETE",
          "path": "/api/resource/{id}",
          "summary": "Short title",
          "description": "Longer description",
          "requiresAuth": false,
          "pathParams": [{ "name": "id", "type": "string", "description": "...", "example": "abc123" }],
          "queryParams": [{ "name": "page", "type": "integer", "description": "...", "example": 1 }],
          "requestBody": {
            "contentType": "application/json",
            "schema": {
              "fieldName": { "type": "string", "example": "value", "required": true, "description": "..." }
            }
          },
          "responses": {
            "200": { "description": "Success", "example": {} },
            "400": { "description": "Bad Request" },
            "401": { "description": "Unauthorized" },
            "404": { "description": "Not Found" },
            "422": { "description": "Validation Error" },
            "500": { "description": "Server Error" }
          }
        }
      ]
    }
  ]
}"""

SYSTEM_INCREMENTAL = """You are an expert API analyst doing an INCREMENTAL update to an existing API spec.
You understand FastAPI, Flask, Django/DRF, Falcon, Sanic, Litestar, Starlette, Tornado, aiohttp, Pydantic, SQLAlchemy, Marshmallow.

Receive: 1) EXISTING spec JSON  2) NEW/CHANGED files.
- Update changed endpoints, add new ones, remove deleted ones.
- Return COMPLETE updated spec JSON only. No markdown."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_context(files: list) -> str:
    return "\n\n".join(
        f"### {f.path}\n```python\n{f.content}\n```" for f in files
    )


def _parse_json(raw: str) -> ApiSpec:
    cleaned = (
        raw.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in response.\n\nSnippet: {raw[:300]}")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from Groq: {exc}") from exc


def _call_groq(system: str, user: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set.\n"
            "Get a free key at https://console.groq.com\n"
            "Then: export GROQ_API_KEY=gsk_your_key_here"
        )
    resp = httpx.post(
        GROQ_API_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "model": MODEL,
            "temperature": 0.1,
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _batch_files(files: list) -> list[list]:
    batches: list[list] = []
    current: list = []
    size = 0
    for f in files:
        length = len(f.content) + len(f.path) + 20
        if size + length > MAX_CHARS and current:
            batches.append(current)
            current = []
            size = 0
        current.append(f)
        size += length
    if current:
        batches.append(current)
    return batches


def _merge_specs(specs: list[ApiSpec]) -> ApiSpec:
    base = specs[0]
    cols: dict[str, Any] = {}
    for spec in specs:
        for col in spec.get("collections", []):
            if col["name"] not in cols:
                cols[col["name"]] = {**col, "endpoints": []}
            existing_keys = {
                f"{e['method']}:{e['path']}"
                for e in cols[col["name"]]["endpoints"]
            }
            for ep in col.get("endpoints", []):
                key = f"{ep['method']}:{ep['path']}"
                if key not in existing_keys:
                    cols[col["name"]]["endpoints"].append(ep)
                    existing_keys.add(key)
    return {**base, "collections": list(cols.values())}


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_with_ai(collected: CollectedFiles, project_name: str = "API") -> ApiSpec:
    import time

    all_files = (
        collected.routes
        + collected.controllers
        + collected.services
        + collected.models
    )
    batches = _batch_files(all_files)
    print(f"\n  📦 Sending {len(batches)} batch(es) to Groq ({len(all_files)} files total)...")

    partial_specs: list[ApiSpec] = []
    for i, batch in enumerate(batches):
        context = _build_context(batch)
        user_msg = (
            f'Project name: "{project_name}" (batch {i + 1} of {len(batches)})\n\n'
            f"{context}\n\n"
            "Extract all API endpoints found in these files and return ONLY the JSON spec."
        )
        raw = _call_groq(SYSTEM_FULL, user_msg)
        partial_specs.append(_parse_json(raw))
        if i < len(batches) - 1:
            time.sleep(1)

    return partial_specs[0] if len(partial_specs) == 1 else _merge_specs(partial_specs)


def analyze_incremental(
    existing_spec: ApiSpec, diff: DiffResult
) -> tuple[ApiSpec, bool]:
    if not diff.new_files and not diff.changed_files and not diff.removed_files:
        return existing_spec, False

    files_to_analyze = diff.new_files + diff.changed_files
    changed_context = _build_context(files_to_analyze)

    removed_context = ""
    if diff.removed_files:
        removed_context = (
            "\n\nREMOVED FILES (delete their endpoints):\n"
            + "\n".join(diff.removed_files)
        )

    spec_str = json.dumps(existing_spec, indent=2)
    if len(spec_str) > 6000:
        spec_str = spec_str[:6000] + "\n... [truncated]"

    user_msg = (
        f"EXISTING SPEC:\n{spec_str}\n\n"
        f"NEW/CHANGED FILES:\n{changed_context}"
        f"{removed_context}\n\n"
        "Return the complete updated spec JSON only."
    )
    raw = _call_groq(SYSTEM_INCREMENTAL, user_msg)
    updated = _parse_json(raw)
    return updated, True