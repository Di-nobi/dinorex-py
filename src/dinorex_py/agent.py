"""
agent.py — Anthropic Claude agent for dinorex-py.

Analyses Python backend source code and returns a structured API spec JSON.
Supports: FastAPI, Flask, Django/DRF, Falcon, Sanic, Litestar, Starlette,
          Tornado, aiohttp, and any Pydantic/SQLAlchemy/Tortoise models.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import anthropic

from .scanner import CollectedFiles
from .store import ApiSpec, DiffResult

client = anthropic.Anthropic()

MODEL = "claude-opus-4-5"
MAX_TOKENS = 8000

# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_FULL = """You are an expert API analyst. Analyse Python backend source code and extract a complete API specification.

Supported frameworks — recognise ALL of these:

Routing / controllers:
- FastAPI   : @app.get / @router.get / @router.post / APIRouter / @app.include_router
- Flask     : @app.route / @bp.route / MethodView / Flask-RESTful Resource
- Django    : urlpatterns = [path(...), re_path(...)] in urls.py; class-based views
- DRF       : ViewSet (list/create/retrieve/update/destroy), APIView, @action decorator
- Falcon    : responder methods (on_get, on_post, on_put, on_patch, on_delete) on Resource classes
- Sanic     : @app.route / @bp.route / app.add_route
- Litestar  : @get / @post / @put / @patch / @delete / Controller subclasses
- Starlette : Route() / Mount() / @app.route / WebSocketRoute
- Tornado   : RequestHandler subclasses with get/post/put/delete methods
- aiohttp   : app.router.add_get / add_post / add_route / RouteTableDef @routes.get

Models / schemas:
- Pydantic v1 & v2 : BaseModel subclasses — field names, types, Optional, default values
- Django ORM       : models.Model subclasses — CharField, IntegerField, ForeignKey, etc.
- DRF Serializers  : ModelSerializer / Serializer — fields map directly to request/response body
- SQLAlchemy       : declarative_base() / mapped_column / Column — extract table columns
- Tortoise ORM     : Model subclasses with fields.CharField, fields.IntField, etc.
- Marshmallow      : Schema subclasses with fields.Str(), fields.Int(), etc.
- attrs / dataclasses with type annotations

Rules:
- Return ONLY valid JSON. No markdown, no explanation, no code fences.
- Infer realistic example values from field names and Python types.
- Group endpoints into logical collections (e.g. "Users", "Auth", "Products").
- Detect auth dependencies: Depends(get_current_user), @login_required, permission_classes, IsAuthenticated, JWTAuthentication, @auth.login_required → requiresAuth: true.
- For DRF ViewSets infer the full CRUD set: list→GET /resource/, create→POST /resource/, retrieve→GET /resource/{id}, update→PUT, partial_update→PATCH, destroy→DELETE.
- For Django urls.py: combine the url prefix from include() with individual path() patterns.
- Pydantic Optional[T] / field with default → required: false. Otherwise required: true.
- attrs/dataclass fields with defaults → required: false.

Return ONLY this JSON structure, nothing else:
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

You understand all major Python web frameworks: FastAPI, Flask, Django/DRF, Falcon, Sanic, Litestar, Starlette, Tornado, aiohttp — plus Pydantic, SQLAlchemy, Tortoise ORM, Marshmallow, and DRF serializers.

You will receive:
1. The EXISTING spec (full JSON)
2. NEW or CHANGED source files to analyse

Your job:
- Extract endpoints from the new/changed files
- If an endpoint already exists (same method + path): update it if code changed, keep it if unchanged
- If it is NEW: add it to the correct collection (create collection if needed)
- Remove endpoints whose source files are listed under REMOVED FILES
- Keep all existing endpoints from unchanged files

Return the COMPLETE updated spec JSON. No markdown, no explanation, ONLY JSON."""


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
        raise ValueError(
            f"No JSON object found in AI response.\n\nSnippet: {raw[:300]}"
        )
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI returned invalid JSON: {exc}\n\nSnippet: {cleaned[:300]}"
        ) from exc


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_with_ai(collected: CollectedFiles, project_name: str = "API") -> ApiSpec:
    sections = []
    if collected.routes:
        sections.append("## ROUTES\n" + _build_context(collected.routes))
    if collected.controllers:
        sections.append("## CONTROLLERS\n" + _build_context(collected.controllers))
    if collected.services:
        sections.append("## SERVICES\n" + _build_context(collected.services))
    if collected.models:
        sections.append("## MODELS\n" + _build_context(collected.models))

    context = "\n\n---\n\n".join(sections)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_FULL,
        messages=[
            {
                "role": "user",
                "content": (
                    f'Project: "{project_name}"\n\n'
                    f"{context}\n\n"
                    "Extract all API endpoints and return the JSON spec."
                ),
            }
        ],
    )

    block = response.content[0]
    if block.type != "text":
        raise RuntimeError("Unexpected response type from Anthropic API")
    return _parse_json(block.text)


def analyze_incremental(
    existing_spec: ApiSpec, diff: DiffResult
) -> tuple[ApiSpec, bool]:
    """
    Returns (updated_spec, changed).
    If nothing changed, returns (existing_spec, False) without an API call.
    """
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
    if len(spec_str) > 8000:
        spec_str = spec_str[:8000] + "\n... [truncated]"

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_INCREMENTAL,
        messages=[
            {
                "role": "user",
                "content": (
                    f"EXISTING SPEC:\n{spec_str}\n\n"
                    f"NEW/CHANGED FILES:\n{changed_context}"
                    f"{removed_context}\n\n"
                    "Return the complete updated spec."
                ),
            }
        ],
    )

    block = response.content[0]
    if block.type != "text":
        raise RuntimeError("Unexpected response type from Anthropic API")

    updated = _parse_json(block.text)
    return updated, True