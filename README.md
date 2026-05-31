# dinorex-py

> AI-powered API documentation for Python projects — one command, full docs.

The Python sibling of [dinorex](https://github.com/your-org/dinorex).  
Point it at any Python backend and get a live interactive docs UI instantly.

## Supported frameworks

| Framework | Route detection | Model/schema detection |
|-----------|----------------|----------------------|
| **FastAPI** | `@router.get`, `@app.get`, `APIRouter` | Pydantic v1 & v2 `BaseModel` |
| **Flask** | `@app.route`, `@bp.route`, `MethodView` | Marshmallow schemas |
| **Django** | `urls.py` `path()` / `re_path()`, CBVs | Django ORM `models.Model` |
| **DRF** | `ViewSet`, `APIView`, `@action` | `ModelSerializer`, `Serializer` |
| **Falcon** | `on_get`, `on_post` … responders | — |
| **Sanic** | `@app.route`, `@bp.route` | — |
| **Litestar** | `@get`, `@post`, `Controller` | Pydantic / attrs |
| **Starlette** | `Route()`, `Mount()` | Pydantic |
| **Tornado** | `RequestHandler` subclasses | — |
| **aiohttp** | `RouteTableDef`, `add_route` | — |
| **SQLAlchemy** | — | `Column`, `mapped_column` |
| **Tortoise ORM** | — | `fields.CharField` … |

## Installation

```bash
pip install dinorex-py
```

## Quick start

```bash
# Anthropic (default)
export ANTHROPIC_API_KEY=sk-ant-...
dinorex scan /path/to/your/project

# Groq (free)
export GROQ_API_KEY=gsk_...
dinorex scan /path/to/your/project --provider groq

# Custom port
dinorex scan . -p 8080
```

## Project structure

```
dinorex-py/
├── src/
│   └── dinorex_py/
│       ├── __init__.py
│       ├── cli.py          # Click CLI entry point
│       ├── scanner.py      # File discovery for all Python frameworks
│       ├── agent.py        # Anthropic Claude agent
│       ├── agent_groq.py   # Groq/Llama3 agent (free tier)
│       ├── server.py       # Flask server + REST API
│       ├── store.py        # Persistent spec cache + diff logic
│       └── public/         # Frontend UI (shared with dinorex Node)
├── pyproject.toml
└── README.md
```

## How it works

1. **Scan** — discovers route files, controllers, services, and models using glob patterns tuned for every Python framework.
2. **Analyse** — sends the source code to Claude (or Llama3 via Groq) which extracts a structured JSON spec.
3. **Cache** — saves the spec and file hashes to `.dinorex/spec.json`. Re-runs are incremental — only changed files are re-analysed.
4. **Serve** — starts a local Flask server with the interactive UI.

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required for Anthropic provider |
| `GROQ_API_KEY` | Required for Groq provider |
| `DINOREX_PROVIDER` | Set default provider (`anthropic` or `groq`) |

## License

MIT