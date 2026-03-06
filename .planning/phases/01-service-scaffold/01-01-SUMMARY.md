---
phase: 01-service-scaffold
plan: 01
subsystem: api
tags: [fastapi, pydantic-settings, boto3, aws-secrets-manager, uvicorn, python]

# Dependency graph
requires: []
provides:
  - "vdr-agent FastAPI skeleton at vdr-agent/main.py with GET /health returning {service: vdr-agent, status: ok, version: 0.1.0}"
  - "Pydantic Settings (VDR_AGENT_* prefix) with AWS Secrets Manager bootstrap and required-field validation"
  - "configure_logging() with structured format and noisy-logger suppression"
  - "asynccontextmanager lifespan in app/startup.py (Phase 1 minimal; Phases 3/5 add DB pool and poller)"
  - "Directory scaffold: app/config/, app/core/routers/, app/db/, app/logging/, app/models/, migrations/"
affects: [02-flyway-schema, 03-db-pool, 05-document-poller, 06-bedrock-llm, 07-topic-management, 08-api-routes]

# Tech tracking
tech-stack:
  added:
    - "fastapi>=0.115 — web framework"
    - "pydantic-settings>=2.0 — env-var config with BaseSettings"
    - "boto3>=1.28 — AWS SDK for Secrets Manager bootstrap"
    - "uvicorn>=0.30 with standard extras — ASGI server"
    - "psycopg[binary]==3.3.3 — PostgreSQL driver (pinned for psycopg-pool compatibility)"
    - "psycopg-pool>=3.2 — async connection pool (added in Phase 3)"
    - "python-dotenv>=1.0 — .env.local support in local dev"
  patterns:
    - "VDR_AGENT_* env prefix for all config — consistent with ERM_RAG_* pattern in ingestion-service"
    - "AWS Secrets Manager bootstrap at module import time — secrets loaded before Pydantic Settings instantiation"
    - "lru_cache singleton for settings — get_settings() returns same instance across app lifecycle"
    - "asynccontextmanager lifespan pattern — startup/shutdown hooks injected at app creation"
    - "Required fields have no defaults — missing VDR_AGENT_DB_HOST causes immediate Pydantic ValidationError"

key-files:
  created:
    - "vdr-agent/pyproject.toml — Poetry project config with all pinned dependencies"
    - "vdr-agent/main.py — create_app() and module-level app instance"
    - "vdr-agent/app/config/__init__.py — Settings, get_settings(), AwsSecretsSettingsSource"
    - "vdr-agent/app/logging/__init__.py — configure_logging() with dictConfig"
    - "vdr-agent/app/startup.py — lifespan asynccontextmanager"
    - "vdr-agent/app/core/routers/health.py — GET /health router"
    - "vdr-agent/app/core/routers/__init__.py — exports health_router"
    - "vdr-agent/app/__init__.py — package marker"
    - "vdr-agent/app/core/__init__.py — package marker"
    - "vdr-agent/app/db/__init__.py — package marker (DB pool added Phase 3)"
    - "vdr-agent/app/models/__init__.py — package marker"
    - "vdr-agent/migrations/.gitkeep — Flyway migration dir (populated Phase 2)"
  modified: []

key-decisions:
  - "db_host, db_name, db_user have no defaults — missing env vars cause immediate Pydantic ValidationError at startup rather than cryptic runtime errors"
  - "from __future__ import annotations added to config and main — required for str | None union syntax compatibility with Python 3.9 venv while targeting Python 3.12 in pyproject.toml"
  - "Logging module is standalone (no app.config import) — avoids circular import when configure_logging() is called from create_app() before lifespan"

patterns-established:
  - "All vdr-agent modules use from __future__ import annotations for forward reference compatibility"
  - "Settings validation in @model_validator(mode='after') produces descriptive error listing all missing VDR_AGENT_* variables"
  - "lifespan is minimal in Phase 1 — DB pool and poller are added incrementally in Phases 3 and 5"

requirements-completed: []

# Metrics
duration: 4min
completed: 2026-03-05
---

# Phase 1 Plan 1: Service Scaffold — vdr-agent skeleton Summary

**FastAPI service skeleton with VDR_AGENT_* Pydantic Settings (AWS Secrets Manager bootstrap), structured logging, asynccontextmanager lifespan, and GET /health returning {service: vdr-agent, status: ok, version: 0.1.0}**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-05T05:21:25Z
- **Completed:** 2026-03-05T05:25:05Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- vdr-agent/ directory scaffold at repo root mirrors ingestion-service layout (app/config/, app/core/routers/, app/db/, app/logging/, app/models/, migrations/)
- Pydantic Settings with VDR_AGENT_* prefix, AWS Secrets Manager bootstrap, and required-field validation — missing db_host/db_name/db_user causes immediate descriptive ValidationError
- FastAPI app (root_path=/vdr-agent, version=0.1.0) with CORSMiddleware, HTTP logging middleware, RequestValidationError handler, and GET /health endpoint

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pyproject.toml and directory scaffold** - `42f09a5` (feat)
2. **Task 2: Create main.py and health router** - `766dfed` (feat)

## Files Created/Modified

- `vdr-agent/pyproject.toml` — Poetry config with fastapi>=0.115, psycopg[binary]==3.3.3, psycopg-pool, boto3, pydantic-settings>=2.0, uvicorn
- `vdr-agent/main.py` — create_app() returning FastAPI instance on port 8001, root_path=/vdr-agent; module-level app instance; HTTP logging middleware
- `vdr-agent/app/config/__init__.py` — VDR_AGENT_* Pydantic BaseSettings, AWS Secrets Manager bootstrap (_bootstrap_config_sources()), AwsSecretsSettingsSource, get_settings() with lru_cache
- `vdr-agent/app/logging/__init__.py` — configure_logging(level) using dictConfig with console handler, noisy-logger suppression
- `vdr-agent/app/startup.py` — minimal lifespan asynccontextmanager (Phase 1 only)
- `vdr-agent/app/core/routers/health.py` — GET /health → {service, status, version}
- `vdr-agent/app/core/routers/__init__.py` — exports health_router
- Empty package markers: app/__init__.py, app/core/__init__.py, app/db/__init__.py, app/models/__init__.py
- `vdr-agent/migrations/.gitkeep` — Flyway migration placeholder

## Decisions Made

- **No defaults for required fields:** `db_host`, `db_name`, and `db_user` have no default values so a missing `VDR_AGENT_DB_HOST` env var causes Pydantic to raise a `ValidationError` at import time — matches must_have truth.
- **from __future__ import annotations:** Added to `app/config/__init__.py` and `main.py` to support `str | None` union syntax in Python 3.9 venv (pyproject.toml targets Python 3.12).
- **Standalone logging module:** `app/logging/__init__.py` does not import from `app.config` to avoid circular imports when `configure_logging()` is called from `create_app()` before settings are fully resolved.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added `from __future__ import annotations` to config and main**
- **Found during:** Task 1 (config module verification)
- **Issue:** `str | None` union syntax (PEP 604) is not supported at class definition time in Python 3.9; the project venv is Python 3.9 even though pyproject.toml targets 3.12
- **Fix:** Added `from __future__ import annotations` to `app/config/__init__.py` and `main.py` to defer type annotation evaluation
- **Files modified:** vdr-agent/app/config/__init__.py, vdr-agent/main.py
- **Verification:** `python -c "from app.config import get_settings"` succeeds without TypeError
- **Committed in:** 42f09a5 (Task 1 commit), 766dfed (Task 2 commit)

**2. [Rule 1 - Bug] Settings required fields have no defaults**
- **Found during:** Task 1 verification
- **Issue:** Plan specified `default="127.0.0.1"` for `db_host` but must_have truth requires missing `VDR_AGENT_DB_HOST` to cause startup failure; a truthy default prevents the validator from ever triggering
- **Fix:** Removed defaults from `db_host`, `db_name`, `db_user` so Pydantic raises `ValidationError` when these env vars are absent
- **Files modified:** vdr-agent/app/config/__init__.py
- **Verification:** `python -c "from app.config import Settings; Settings()"` raises `ValidationError` mentioning `db_host`, `db_name`, `db_user`
- **Committed in:** 42f09a5 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 - Bug)
**Impact on plan:** Both fixes required for correctness and spec compliance. No scope creep.

## Issues Encountered

- `eval_type_backport` package was not installed — installed automatically to support `str | None` syntax in pydantic model with Python 3.9 venv
- `fastapi` package was not installed in the venv — installed automatically during Task 2 verification

## User Setup Required

None — no external service configuration required. Set VDR_AGENT_DB_HOST, VDR_AGENT_DB_NAME, VDR_AGENT_DB_USER environment variables before running the service.

## Next Phase Readiness

- vdr-agent service skeleton is complete and fully importable
- Phase 2 (Flyway schema) can populate `vdr-agent/migrations/` with SQL migration files
- Phase 3 (DB pool) can extend `app/startup.py` lifespan with `AsyncConnectionPool` initialization
- Phase 5 (document poller) builds on the startup/shutdown lifespan pattern

---
*Phase: 01-service-scaffold*
*Completed: 2026-03-05*
