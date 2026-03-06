# Codebase Structure

**Analysis Date:** 2026-03-05

## Directory Layout

```
/Users/sanchayjain/Desktop/ERM/
├── frontend/                       # React TypeScript web UI
│   ├── src/
│   │   ├── main.tsx               # React DOM entry point
│   │   ├── App.tsx                # Route definitions
│   │   ├── pages/                 # Page components (Home, Chat, Projects, etc.)
│   │   ├── components/            # Reusable UI components
│   │   ├── layout/                # Layout wrappers (AppLayout, AuthLayout)
│   │   ├── routes/                # Route guards (ProtectedRoute, PersistLogin)
│   │   ├── store/                 # Redux slices and store configuration
│   │   ├── services/              # HTTP API clients (axios instances)
│   │   ├── shared/                # Shared utilities, types, constants, hooks
│   │   └── mocks/                 # Mock data for development
│   ├── package.json               # Dependencies (React 19, Redux, Vite, Ant Design)
│   ├── vite.config.ts             # Vite build configuration
│   ├── tsconfig.json              # TypeScript configuration
│   └── Dockerfile                 # Multi-stage Docker build
│
├── ingestion-service/             # Python FastAPI microservice (document processing)
│   ├── main.py                    # FastAPI app creation and configuration
│   ├── app/
│   │   ├── temporal/              # Workflow orchestration (Temporal SDK)
│   │   │   ├── workflows/         # Workflow definitions (ProjectSync, DocumentProcessing, ProjectUnsync)
│   │   │   ├── activities/        # Activity implementations (download, convert, chunk, embed)
│   │   │   ├── worker.py          # Worker process entrypoint
│   │   │   ├── client.py          # Temporal client singleton
│   │   │   ├── scheduler.py       # Cron-based sync scheduling
│   │   │   ├── retry_policies.py  # Named retry policies
│   │   │   └── models.py          # Workflow input/output models
│   │   ├── core/                  # Business logic
│   │   │   ├── routers/           # FastAPI endpoints (projects.py, sharepoint_ingestion.py, excel_skills.py)
│   │   │   ├── llm/               # Claude API client, rate limiting, concurrency control
│   │   │   ├── vision/            # PDF processing via Claude Vision
│   │   │   ├── sharepoint/        # SharePoint Graph API integration
│   │   │   ├── chunking/          # Semantic text chunking
│   │   │   ├── embedding/         # Vector embedding (Bedrock Cohere)
│   │   │   ├── conversion/        # File format conversion (LibreOffice)
│   │   │   ├── pipeline/          # Document processing orchestration
│   │   │   ├── builders/          # Builder patterns for complex objects
│   │   │   ├── context/           # Context managers and utilities
│   │   │   ├── validation/        # Business rule validation
│   │   │   ├── excel/             # Excel processing (skills)
│   │   │   ├── storage/           # Local file storage utilities
│   │   │   └── monitoring/        # Observability utilities
│   │   ├── db/                    # Database layer
│   │   │   ├── clients/           # PostgreSQL connection pool manager
│   │   │   └── dao/               # Data Access Objects (ProjectDAO, DocumentDAO, EmbeddingDAO, etc.)
│   │   ├── config/                # Pydantic Settings (environment configuration)
│   │   ├── models/                # API request/response Pydantic models
│   │   ├── auth/                  # Authentication and authorization utilities
│   │   ├── logging/               # Logging configuration
│   │   ├── startup.py             # Application lifecycle (startup/shutdown hooks)
│   │   └── observability/         # Monitoring and metrics
│   ├── migrations/flyway/         # Database migration scripts (V1-V6)
│   ├── tests/                     # Unit and integration tests
│   ├── requirements.txt           # Python dependencies
│   ├── pyproject.toml             # Poetry configuration
│   ├── Dockerfile                 # Container image build
│   ├── docker-compose.yml         # Ingestion-only compose
│   └── deploy/                    # Deployment configs (Kubernetes, Docker)
│
├── user-service/                  # Python FastAPI microservice (authentication)
│   ├── main.py                    # FastAPI app creation
│   ├── app/
│   │   ├── microsoft_sso/         # Microsoft OAuth/SSO implementation
│   │   │   ├── endpoints/         # FastAPI auth routes (auth.py)
│   │   │   ├── core/              # Microsoft login/token logic
│   │   │   ├── dao/               # User database access
│   │   │   └── schemas/           # Pydantic models for auth requests/responses
│   │   ├── db/                    # Database layer (same pattern as ingestion-service)
│   │   │   ├── clients/
│   │   │   └── dao/
│   │   ├── config/                # Pydantic Settings
│   │   ├── logging/               # Logging configuration
│   │   └── startup.py             # Lifecycle hooks
│   ├── pyproject.toml             # Poetry configuration
│   ├── Dockerfile                 # Container image
│   └── tests/                     # Unit tests
│
├── excel-analyser/                # Python FastAPI microservice (report generation)
│   ├── main.py                    # FastAPI app entry
│   ├── app/                       # Business logic
│   ├── report_generation/         # Report generation via Claude/Bedrock
│   ├── requirements.txt           # Dependencies
│   └── Dockerfile                 # Container image
│
├── docker-compose.yml             # Root compose: all services + Temporal + PostgreSQL
├── start.sh                       # Script to start all services selectively
├── stop.sh                        # Script to stop services
├── .planning/codebase/            # GSD analysis documents
│   ├── ARCHITECTURE.md            # Architecture patterns and layers
│   └── STRUCTURE.md               # This file
└── .gitignore                     # Git ignore rules
```

## Directory Purposes

**`frontend/src/`:**
- Purpose: React application source code
- Contains: Components, pages, routing, state management, API integration
- Key files: `main.tsx` (app bootstrap), `App.tsx` (route definitions), `store/store.ts` (Redux configuration)

**`frontend/src/pages/`:**
- Purpose: Full-page React components for each route
- Contains: Home, Chat, Projects, ProjectDetails, ReportGenerator, AITools, Dashboard, Auth
- Organization: One directory per page; internal structure varies (some have components subdirectory)

**`frontend/src/components/`:**
- Purpose: Reusable UI components
- Contains: Sidebar, Chat interface, Collaborators, Pagination, Modals, etc.
- Usage: Imported across multiple pages

**`frontend/src/store/`:**
- Purpose: Redux state management
- Contains: Feature slices (auth, project, knowledgeAIChat, reportGenerator, etc.), root store configuration, persistence
- Key file: `store.ts` (configures Redux with localStorage persistence)

**`frontend/src/services/`:**
- Purpose: HTTP client configuration and API integration
- Contains: Three Axios instances (`ragApi`, `userPermissionApi`, `ingestionApi`), interceptors, token refresh logic
- Key file: `apiClients.ts` (all HTTP client setup)

**`frontend/src/shared/`:**
- Purpose: Shared utilities across the app
- Contains: `constants.ts` (route paths, enums), `types.ts` (TypeScript interfaces), `utils/` (helper functions), `hooks/` (custom React hooks), `configs.ts` (environment-specific API URLs)

**`ingestion-service/app/temporal/`:**
- Purpose: Temporal workflow orchestration
- Contains: Workflow definitions, activity implementations, worker process, client singleton, retry policies, scheduling
- Dependency: Temporal server (separate container)

**`ingestion-service/app/core/routers/`:**
- Purpose: FastAPI HTTP endpoints
- Key files: `projects.py` (project CRUD, sync, unsync), `sharepoint_ingestion.py` (SharePoint browsing), `excel_skills.py` (skill management)
- Pattern: Each router handles one domain; includes authentication checks, pagination, error handling

**`ingestion-service/app/core/llm/`:**
- Purpose: Claude API client and rate limiting
- Key files: `claude/` (API wrapper), `in_memory_rate_limiter.py`, `distributed_rate_limiter.py` (PostgreSQL-backed), `concurrency_manager.py`
- Critical: Handles rate limiting for 200 RPM Bedrock/Claude APIs

**`ingestion-service/app/core/vision/`:**
- Purpose: PDF processing via Claude Vision
- Responsibility: Extract text, structure, and metadata from PDFs
- Output: Markdown-like format with heading hierarchy for semantic chunking

**`ingestion-service/app/db/`:**
- Purpose: Database abstraction layer
- Contains: PostgreSQL connection pooling (`DatabaseClient`), Data Access Objects for each entity
- Pattern: Sync-only (no async SQLAlchemy), connection pool size 10-40 per worker

**`ingestion-service/migrations/flyway/`:**
- Purpose: Database schema versioning
- Contains: SQL scripts (V1.sql - V6.sql) executed in order on startup
- Schema namespace: `ai_rag`

**`user-service/app/microsoft_sso/`:**
- Purpose: Microsoft OAuth 2.0 authentication
- Key files: `endpoints/auth.py` (login, callback, refresh, logout), `core/` (token validation)
- Integrates with: Microsoft Graph API, JWT token generation/validation

**`excel-analyser/`:**
- Purpose: ESG report generation and Excel analysis
- Contains: Report generation logic, integration with Claude/Bedrock APIs
- Uses: Document embeddings from ingestion-service, generates human-readable ESG reports

## Key File Locations

**Entry Points:**
- Frontend: `/Users/sanchayjain/Desktop/ERM/frontend/src/main.tsx` (React DOM mount)
- Ingestion API: `/Users/sanchayjain/Desktop/ERM/ingestion-service/main.py` (FastAPI app)
- Ingestion Worker: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/worker.py` (Temporal worker)
- User Service: `/Users/sanchayjain/Desktop/ERM/user-service/main.py` (FastAPI app)

**Configuration:**
- Frontend: `/Users/sanchayjain/Desktop/ERM/frontend/src/shared/configs.ts` (API URLs per environment)
- Ingestion: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/config/` (Pydantic Settings)
- User Service: `/Users/sanchayjain/Desktop/ERM/user-service/app/config/` (Pydantic Settings)
- Docker: `/Users/sanchayjain/Desktop/ERM/docker-compose.yml` (all services + Temporal + database)

**Core Logic:**
- Document Processing: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/workflows/project_sync_workflow.py` (orchestrates sync)
- PDF Extraction: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/vision/` (Claude Vision)
- Embeddings: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/embedding/` (Bedrock Cohere)
- SharePoint Sync: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/sharepoint/` (Graph API integration)

**Testing:**
- Ingestion Tests: `/Users/sanchayjain/Desktop/ERM/ingestion-service/tests/` (pytest suite)
- User Service Tests: `/Users/sanchayjain/Desktop/ERM/user-service/tests/` (pytest suite)
- Frontend Tests: Not present (TBD)

## Naming Conventions

**Files:**
- Python service files: `snake_case.py` (e.g., `project_sync_workflow.py`, `document_activities.py`)
- React component files: `PascalCase.tsx` (e.g., `ProjectDetails.tsx`, `ChatInterface.tsx`)
- Redux slices: `camelCase` with domain prefix (e.g., `authSlice.ts`, `projectSlice.ts`)
- Constants files: `SCREAMING_SNAKE_CASE` for constants, `camelCase` for config objects (e.g., `configs.ts`, `constants.ts`)

**Directories:**
- Feature/domain directories: `lowercase` (e.g., `projects`, `sharepoint`, `temporal`)
- Component directories: `PascalCase` (e.g., `ProjectDetails`, `ChatInterface`, `Sidebar`)
- Utility directories: `lowercase` with purpose (e.g., `utils`, `hooks`, `dao`, `activities`)

**TypeScript/React:**
- Interface/Type names: `PascalCase` with I prefix for interfaces (optional): `IConfig`, `IProject`, `ProjectResponse`
- Function names: `camelCase` (e.g., `createProject`, `handleSync`, `useProjects`)
- React hooks: `useXxx` convention (e.g., `useProjects`, `useAuth`, `useChat`)
- Redux slices: `xxxSlice` (e.g., `projectSlice`, `authSlice`)

**Python:**
- Class names: `PascalCase` (e.g., `ProjectDAO`, `DocumentProcessingWorkflow`)
- Function/method names: `snake_case` (e.g., `get_documents`, `sync_project`)
- Constants: `SCREAMING_SNAKE_CASE` (e.g., `MAX_CHUNK_SIZE`, `TEMPORAL_TASK_QUEUE`)
- Environment variables: `ERM_RAG_` prefix (e.g., `ERM_RAG_DB_HOST`, `ERM_RAG_TEMPORAL_HOST`)

## Where to Add New Code

**New Frontend Feature:**
- Primary code: `/Users/sanchayjain/Desktop/ERM/frontend/src/pages/{featureName}/` (page component) or `/Users/sanchayjain/Desktop/ERM/frontend/src/components/{FeatureName}/` (reusable component)
- Redux state: `/Users/sanchayjain/Desktop/ERM/frontend/src/store/{featureName}/{featureNameSlice}.ts`
- API integration: `/Users/sanchayjain/Desktop/ERM/frontend/src/services/` (add methods to existing axios clients or create new service file)
- Tests: `/Users/sanchayjain/Desktop/ERM/frontend/src/{page|component}/__tests__/` (co-located with component)

**New Backend Endpoint (Ingestion Service):**
- Route handler: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/routers/{domain}.py` (or create new if new domain)
- Business logic: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/{domain}/` (e.g., `/core/sharepoint/`, `/core/vision/`)
- Database access: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/db/dao/{entity}_dao.py`
- Models: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/models/{entity}.py`
- Tests: `/Users/sanchayjain/Desktop/ERM/ingestion-service/tests/{unit|integration}/{domain}/test_xxx.py`

**New Workflow (Ingestion Service):**
- Workflow definition: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/workflows/{workflow_name}_workflow.py`
- Activities: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/activities/{activity_name}_activities.py`
- Register in worker: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/worker.py` (add to `run()` function)
- Trigger from API: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/routers/` (use Temporal client to start workflow)

**New User Service Endpoint:**
- Route handler: `/Users/sanchayjain/Desktop/ERM/user-service/app/microsoft_sso/endpoints/{domain}.py` (or extend `auth.py`)
- Business logic: `/Users/sanchayjain/Desktop/ERM/user-service/app/microsoft_sso/core/`
- Database access: `/Users/sanchayjain/Desktop/ERM/user-service/app/db/dao/{entity}_dao.py`
- Models: `/Users/sanchayjain/Desktop/ERM/user-service/app/models/` or in endpoints file

**Shared Utilities:**
- React hooks: `/Users/sanchayjain/Desktop/ERM/frontend/src/shared/hooks/` (one per file, e.g., `useProjects.ts`)
- React utilities: `/Users/sanchayjain/Desktop/ERM/frontend/src/shared/utils/` (helper functions, e.g., `formatters.ts`, `validators.ts`)
- Python utilities: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/` (domain-specific) or `/app/` root (generic, e.g., in `utils.py`)

## Special Directories

**`frontend/src/mocks/`:**
- Purpose: Mock data for development and testing
- Generated: No
- Committed: Yes
- Usage: Imported in Redux slices for testing without real backend

**`ingestion-service/migrations/flyway/`:**
- Purpose: Database schema versioning
- Generated: No (manually written SQL)
- Committed: Yes
- Execution: Flyway CLI runs on service startup, applies in order

**`ingestion-service/.env.local`:**
- Purpose: Development environment configuration
- Generated: No (template provided as `.env.example`)
- Committed: No (in `.gitignore`)
- Contains: AWS credentials, PostgreSQL connection, Temporal server address, SharePoint tokens

**`ingestion-service/deploy/`:**
- Purpose: Deployment configurations
- Contains: Kubernetes manifests, Helm charts, Docker compose
- Committed: Yes
- Usage: CI/CD pipeline deploys using these configs

**`frontend/node_modules/`, `ingestion-service/.venv/`, etc.:**
- Purpose: Installed dependencies
- Generated: Yes
- Committed: No
- Managed by: npm (frontend), Poetry (Python services)

---

*Structure analysis: 2026-03-05*
