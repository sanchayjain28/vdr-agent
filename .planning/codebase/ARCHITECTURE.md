# Architecture

**Analysis Date:** 2026-03-05

## Pattern Overview

**Overall:** Microservices with event-driven orchestration and client-side state management.

**Key Characteristics:**
- **Decoupled Services:** Four independent microservices communicate via HTTP APIs and asynchronous workflows
- **Temporal Orchestration:** Durable workflows manage multi-step document processing pipelines with automatic retry and state management
- **Client-State Redux:** Frontend uses Redux with persistence for local application state and UI coordination
- **Distributed Rate Limiting:** PostgreSQL-backed API rate limiting for cross-service consistency
- **Two-Process Model:** Ingestion service splits API (HTTP requests) and Worker (workflow execution) into separate processes

## Layers

**Presentation Layer:**
- Purpose: User interface and state management for ESG VDR platform
- Location: `/Users/sanchayjain/Desktop/ERM/frontend/src`
- Contains: React components, pages, layouts, Redux slices, API clients, routes
- Depends on: User Service (auth), Ingestion Service (documents/projects), Excel Analyser (report generation)
- Used by: End users via web browsers

**API Gateway / Router Layer:**
- Purpose: HTTP endpoint definitions and request/response handling
- Location: `frontend: /src/routes`, `ingestion: /app/core/routers`, `user-service: /app/microsoft_sso/endpoints`
- Contains: FastAPI routers, request validation, error handling, CORS middleware
- Depends on: Database layer, business logic, external services
- Used by: Frontend and external consumers

**Business Logic / Service Layer:**
- Purpose: Core application functionality and data processing
- Location: `ingestion: /app/core/` (vision, chunking, embedding, sharepoint, llm), `user-service: /app/microsoft_sso/core`, `excel-analyser: /report_generation`
- Contains: Document processing pipeline, vector embeddings, SharePoint integration, Microsoft SSO
- Depends on: Database layer, external APIs (Claude, Bedrock, Microsoft Graph)
- Used by: Router layer, Temporal workflows

**Workflow Orchestration Layer:**
- Purpose: Durable, fault-tolerant multi-step process coordination
- Location: `ingestion: /app/temporal/`
- Contains: Three workflow types (ProjectSync, DocumentProcessing, ProjectUnsync), activity implementations, retry policies, scheduling
- Depends on: Database layer, service layer, Temporal server
- Used by: API routers (for triggering), distributed workers (for execution)

**Data Persistence Layer:**
- Purpose: State storage and query interface
- Location: `ingestion: /app/db/`, `user-service: /app/db/`
- Contains: PostgreSQL clients with connection pooling, Data Access Objects (DAOs), schema migrations (Flyway)
- Depends on: PostgreSQL database
- Used by: All layers (service, router, workflow activities)

**Configuration & Infrastructure:**
- Purpose: Environment-specific settings, startup/shutdown, logging
- Location: `app/config/` (all services), `app/logging/` (all services), `app/startup.py` (all services)
- Contains: Pydantic Settings, environment variable management, initialization hooks
- Depends on: Environment variables, PostgreSQL, Temporal, external APIs
- Used by: Application bootstrap

## Data Flow

**Authentication Flow:**
1. Frontend initiates Microsoft login → User Service `/auth/login` endpoint
2. User Service validates token via Microsoft Graph API → Returns JWT access token + refresh token
3. Frontend stores tokens in Redux + localStorage (persisted)
4. Subsequent requests include `Authorization: Bearer <token>` header
5. Token refresh: When 401 response, frontend calls User Service `/auth/refresh` with refresh token

**Document Ingestion Flow:**
1. Frontend sends project sync request → Ingestion Service `/projects/{projectId}/sync`
2. API router triggers `ProjectSyncWorkflow` via Temporal client
3. Temporal server enqueues workflow in `rag-pipeline-queue` task queue
4. Temporal Worker polls task queue, executes workflow steps:
   - Download file from SharePoint via Graph API
   - Validate file type/size
   - Convert Office docs to PDF (LibreOffice)
   - Extract text + structure via Claude Vision API
   - Chunk text semantically based on detected headings
   - Embed chunks via AWS Bedrock Cohere embeddings
   - Store embeddings in PostgreSQL pgvector column
5. Update document status in database (PENDING → PROCESSING → COMPLETED)
6. Frontend polls `/projects/{projectId}/documents` for status updates (shows live progress in UI)

**Report Generation Flow:**
1. Frontend provides documents + instructions → Ingestion Service `/generate-report`
2. Excel Analyser service processes via Claude API (or Bedrock)
3. Report stored in database with status
4. Frontend retrieves report, renders in React MDX Editor component

**State Management:**
- **Frontend Redux:** Manages auth tokens, project list, document statuses, chat history, report state (persisted to localStorage via redux-persist)
- **Temporal Server:** Manages workflow execution state, retries, schedules
- **PostgreSQL:** Source of truth for documents, projects, embeddings, users

## Key Abstractions

**Workflow:**
- Purpose: Encapsulates multi-step, long-running processes with built-in failure handling
- Examples: `ProjectSyncWorkflow` (`/app/temporal/workflows/project_sync_workflow.py`), `DocumentProcessingWorkflow` (`/app/temporal/workflows/document_processing_workflow.py`)
- Pattern: Each workflow defines `@workflow.run` method with ordered activity calls; Temporal SDK handles state persistence, retries, timeouts

**Activity:**
- Purpose: Individual task executed by distributed workers; can retry independently
- Examples: `download_file_activity`, `convert_to_pdf_activity`, `chunk_and_embed_activity` (in `/app/temporal/activities/`)
- Pattern: Each activity decorated with `@activity.run` and assigned retry policy; implements single responsibility principle

**DAO (Data Access Object):**
- Purpose: Encapsulates database queries and mutations for a single entity
- Examples: `ProjectDAO`, `DocumentDAO`, `EmbeddingDAO` (in `/app/db/dao/`)
- Pattern: Sync-only (no async SQLAlchemy), returns Pydantic models, connection pooling via `DatabaseClient`

**Service:**
- Purpose: Stateless business logic combining DAOs and external APIs
- Examples: `SharePointService`, `Claude Vision Processor`, `Embedding Service` (in `/app/core/`)
- Pattern: Injected dependencies, single concern, chainable for pipeline processing

**Redux Slice:**
- Purpose: Frontend state namespace with reducers and async thunks
- Examples: `authSlice`, `projectSlice`, `reportGeneratorSlice` (in `/frontend/src/store/*/`)
- Pattern: Each slice manages one feature domain; async thunks call API clients; persisted selectively to localStorage

## Entry Points

**Frontend Web App:**
- Location: `/Users/sanchayjain/Desktop/ERM/frontend/src/main.tsx`
- Triggers: User navigates to `http://localhost:5173` (Vite dev server)
- Responsibilities: Bootstrap React app, initialize Redux store + persistor, mount routing

**Ingestion Service API:**
- Location: `/Users/sanchayjain/Desktop/ERM/ingestion-service/main.py` (`create_app()` function)
- Triggers: FastAPI server starts on port 8000; requests to `/ingestion/*` endpoints
- Responsibilities: Create FastAPI app, include routers, attach middleware (CORS), define exception handlers, trigger startup/shutdown hooks

**Ingestion Service Worker:**
- Location: `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/temporal/worker.py`
- Triggers: `python -m app.temporal.worker` (separate process)
- Responsibilities: Connect to Temporal server, register workflow + activity implementations, poll task queue, execute activities with resource-based tuning

**User Service API:**
- Location: `/Users/sanchayjain/Desktop/ERM/user-service/main.py` (`create_app()` function)
- Triggers: FastAPI server starts on port 8000; requests to `/` endpoints (no root path)
- Responsibilities: Create FastAPI app, include auth router, handle Microsoft SSO, JWT token operations

**Excel Analyser API:**
- Location: `/Users/sanchayjain/Desktop/ERM/excel-analyser/main.py`
- Triggers: FastAPI server starts on port 8000; requests to `/analyser/*` endpoints
- Responsibilities: Process Excel files, generate ESG reports, integration with Claude/Bedrock

## Error Handling

**Strategy:** Layered error handling with context propagation and user-friendly responses.

**Patterns:**
- **API Layer:** FastAPI exception handlers catch `RequestValidationError` (422), `DatabaseError` (503/500), return JSON with error detail
- **Workflow Layer:** Activity retry policies (DB_RETRY, EXTERNAL_API_RETRY, CPU_INTENSIVE_RETRY) with exponential backoff; dead-letter queue for exhausted retries
- **Service Layer:** Try-catch blocks log errors with context (file_id, project_id); re-raise with enriched exceptions
- **Database Layer:** `DatabaseConnectionError` (connection pool exhausted) vs `DatabaseError` (query failures); both caught by API exception handler
- **Frontend Layer:** Axios response interceptor catches 401 (token refresh), logs other errors, displays toast notifications via react-toastify

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module (all backend services)
- Approach: Structured logging with context (request_id, user_id, project_id); configured per service in `app/logging/`
- Frontend: Console logs and toast notifications for user-facing events

**Validation:**
- Backend: Pydantic models for request/response validation; `RequestValidationError` caught and returned as 422
- Frontend: Form validation in React components (e.g., Project creation modal), client-side validation before API calls
- Business Logic: SharePoint source deduplication (`filter_duplicate_sources`), file type/size validation in document activities

**Authentication:**
- Strategy: Microsoft OAuth 2.0 via User Service
- Token Management: Frontend stores access + refresh tokens in localStorage; includes `Authorization` header on all API requests; User Service validates tokens against Microsoft Graph
- RBAC: `check_project_access`, `require_project_creator` middleware in Ingestion Service routes; frontend ProtectedRoute wrapper

**Rate Limiting:**
- Mode 1: In-memory (single worker) - Semaphore + rolling 60-second window in `app/core/llm/in_memory_rate_limiter.py`
- Mode 2: Distributed (multi-worker) - PostgreSQL advisory locks + `ai_rag.api_rate_limits` table; coordinated across all workers
- Configuration: `pdf_global_rpm_limit` (200 default), `pdf_global_max_concurrent` (20 default), disabled by default (set `ERM_RAG_DISTRIBUTED_RATE_LIMITING_ENABLED=true`)

**Observability:**
- Health Checks: `/health` endpoints in all services (status, timestamp, version)
- Temporal UI: Dashboard at `http://localhost:8080` shows workflow executions, retries, task queue depth
- Database Monitoring: Query `ai_rag.documents` status distribution and `ai_rag.api_rate_limits` rolling window
- Resource Monitoring: Temporal worker ResourceBasedTuner auto-scales activity slots (target 75% CPU/memory)

---

*Architecture analysis: 2026-03-05*
