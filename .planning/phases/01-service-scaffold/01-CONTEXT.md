# Phase 1: Service Scaffold - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

A deployable FastAPI service skeleton: project structure, Pydantic settings, Docker, health check, and ingestion-service conventions. No business logic — this is the foundation everything else builds on.

</domain>

<decisions>
## Implementation Decisions

### Port & URL prefix
- Port: **8001** (ingestion-service uses 8000; avoids conflict in local dev)
- `root_path="/vdr-agent"` — matches the naming convention of the service
- Health check at `GET /health` returning `{"service": "vdr-agent", "status": "ok", "version": "0.1.0"}`

### Docker integration
- Own `Dockerfile` at `vdr-agent/Dockerfile`
- Added as a service entry in the **root `docker-compose.yml`** (alongside ingestion, user-service, etc.)
- Shares the existing PostgreSQL service — no new DB container
- `env_file: .env.local` pattern matching ingestion-service
- Volumes mount `./vdr-agent:/app` for local dev hot-reload

### Environment variable naming
- Prefix: **`VDR_AGENT_`** (e.g., `VDR_AGENT_DB_HOST`, `VDR_AGENT_ENV`, `VDR_AGENT_POLL_INTERVAL_SECONDS`)
- AWS vars shared with ingestion-service: `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` (no separate prefix)
- DB vars: `VDR_AGENT_DB_HOST`, `VDR_AGENT_DB_PORT`, `VDR_AGENT_DB_NAME`, `VDR_AGENT_DB_USER`, `VDR_AGENT_DB_PASSWORD`

### Migration tooling
- **Flyway** — matches ingestion-service exactly; `migrations/` directory at service root
- Migration files named `V{N}__{description}.sql` (e.g., `V1__create_vdr_agent_schema.sql`)
- Flyway runs as a separate step before the service starts (same pattern as ingestion-service)

### Project structure
Mirror ingestion-service layout exactly:
```
vdr-agent/
├── app/
│   ├── config/        # Pydantic Settings + AWS Secrets Manager
│   ├── core/
│   │   ├── routers/   # FastAPI routers
│   │   └── llm/       # Claude client (ported from ingestion-service)
│   ├── db/            # DatabasePool + DAOs
│   ├── logging/       # configure_logging()
│   ├── models/        # Pydantic request/response models
│   └── startup.py     # startup_event / shutdown_event
├── migrations/        # Flyway SQL files
├── main.py            # create_app()
├── pyproject.toml     # Poetry
└── Dockerfile
```

### Config validation
- Pydantic `BaseSettings` with `model_validator` — fail fast on missing required vars
- `ERM_RAG_ENV=local` triggers `.env.local` loading (same logic as ingestion-service)
- AWS Secrets Manager injection at startup (same pattern as ingestion-service `app/config/__init__.py`)

### Claude's Discretion
- Exact logging format (follow ingestion-service `app/logging/` pattern)
- CORS configuration (start with `allow_origins=["*"]` matching ingestion-service TODO)
- uvicorn worker count and reload settings
- `.dockerignore` and `.gitignore` contents

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingestion-service/app/config/__init__.py`: Pydantic Settings pattern with AWS Secrets Manager injection — copy verbatim, rename env var prefix to `VDR_AGENT_`
- `ingestion-service/app/logging/`: `configure_logging()` function — copy directly, no changes needed
- `ingestion-service/app/startup.py`: lifespan startup/shutdown pattern with `asynccontextmanager` — port structure, strip Temporal references
- `ingestion-service/main.py`: `create_app()` with CORS, lifespan, router registration — port and rename
- `ingestion-service/Dockerfile`: Base image, Poetry install, uvicorn entrypoint — adapt for vdr-agent

### Established Patterns
- **Poetry** for dependency management (`pyproject.toml`)
- **FastAPI lifespan** (`@asynccontextmanager`) for startup/shutdown — not `@app.on_event`
- **`get_settings()` with `@lru_cache`** for singleton settings access
- **`root_path`** on FastAPI app for reverse proxy prefix
- **`env_file: .env.local`** in docker-compose for local dev secrets

### Integration Points
- Root `docker-compose.yml` — add `vdr-agent` service entry alongside `ingestion`
- Shared PostgreSQL container — vdr-agent connects to same DB host/port
- `vdr-agent/` directory at repo root (alongside `ingestion-service/`, `user-service/`)

</code_context>

<specifics>
## Specific Ideas

- Service name in health check: `"vdr-agent"` (matches directory name and URL prefix)
- Follow ingestion-service naming exactly where possible — reduces cognitive load for developers switching between services
- Startup should log which env it's running in (`local` vs production) at INFO level

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-service-scaffold*
*Context gathered: 2026-03-05*
