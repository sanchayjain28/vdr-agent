# External Integrations

**Analysis Date:** 2026-03-05

## APIs & External Services

**Document Processing:**
- **Claude via AWS Bedrock** - Vision AI for PDF processing and text extraction
  - SDK/Client: `boto3` (AWS SDK)
  - Auth: `AWS_BEARER_TOKEN_BEDROCK` (environment variable)
  - Implementation: `ingestion-service/app/core/llm/claude/client.py` (custom async wrapper)
  - Model: Claude Sonnet 4.5 via `bedrock-runtime` service
  - Features: PDF page rendering to images, chunk processing, streaming support

**Vector Embeddings:**
- **AWS Bedrock Cohere** - Text embedding generation (1024 dimensions)
  - SDK/Client: `boto3`
  - Auth: `AWS_BEARER_TOKEN_BEDROCK`
  - Implementation: `ingestion-service/app/core/embedding/service.py`
  - Rate limiting: 200 RPM global limit with distributed coordination

**Document Conversion:**
- **LibreOffice** - Office document (Word, Excel, PPT) to PDF conversion
  - Client: Subprocess-based (system binary)
  - Implementation: `ingestion-service/app/core/conversion/` modules
  - Formats supported: .docx, .xlsx, .pptx → PDF

**Cloud Storage & Secrets:**
- **AWS Secrets Manager** - Secret injection at startup
  - SDK/Client: `boto3` (secretsmanager service)
  - Config: `ERM_RAG_AWS_SECRET_NAME`, `AWS_REGION` env vars
  - Secrets: `ERM_RAG_DB_PASSWORD`, `AWS_BEARER_TOKEN_BEDROCK` (fetched on startup)

## Data Storage

**Databases:**
- **PostgreSQL 16+**
  - Connection: `ERM_RAG_DB_HOST`, `ERM_RAG_DB_PORT`, `ERM_RAG_DB_NAME`, `ERM_RAG_DB_USER`, `ERM_RAG_DB_PASSWORD`
  - Client: `psycopg` 3.1+ (binary mode with connection pooling)
  - ORM: None (raw SQL via DAOs in `ingestion-service/app/db/dao/`)
  - Schema: `ai_rag` (auto-created)
  - Tables: `projects`, `documents`, `document_pages`, `embeddings` (VECTOR(1024)), `sharepoint_documents`, `document_runs`, `api_rate_limits`
  - Extensions: pgvector for vector similarity search

**File Storage:**
- **Local filesystem only** - Document uploads and temporary processing files
  - Location: `ERM_RAG_DATA_DIR` environment variable
  - Pattern: Per-project directories with document subdirectories

**Caching:**
- **In-Memory** - Python object caching (local worker context)
- **Distributed Rate Limiting** - PostgreSQL-backed via `api_rate_limits` table (optional, enable with `ERM_RAG_DISTRIBUTED_RATE_LIMITING_ENABLED=true`)

## Authentication & Identity

**Auth Provider:**
- **Microsoft 365 / Azure AD**
  - Implementation: MSAL (Microsoft Authentication Library)
  - Frontend: `@azure/msal-browser` 4.27.0
  - Backend: `msal` 1.26.0+ (Python)
  - Flow: OAuth 2.0 authorization code flow
  - Tenant ID: `MSAL_TENANT_ID` or `ERM_*_TENANT_ID`
  - Client ID: `MSAL_CLIENT_ID` or `ERM_*_CLIENT_ID`
  - Client Secret: `MSAL_CLIENT_SECRET` or `ERM_*_CLIENT_SECRET`
  - Scopes: `["https://graph.microsoft.com/.default"]`

**Token Management:**
- **JWT (JSON Web Tokens)** - Session tokens between frontend and backend
  - Generation: `python-jose` with cryptography extras
  - Validation: Signature verification in protected routes
  - Implementation: `user-service/app/microsoft_sso/core/security.py`
  - Expiration: Configurable TTL via settings

**User Database:**
- PostgreSQL users table (user-service)
  - Stores: email, Microsoft ID, roles, token cache (JSONB)
  - Token cache: Serialized MSAL cache for refresh token management

## SharePoint Integration

**SharePoint Graph API:**
- **Microsoft Graph API v1.0**
  - Endpoint: `https://graph.microsoft.com/v1.0`
  - Auth: OAuth 2.0 client credentials flow
  - Implementation: `ingestion-service/app/core/sharepoint/client.py`
  - Features: File browsing, download, delta sync for incremental updates
  - Credentials: `ERM_RAG_SHAREPOINT_TENANT_ID`, `ERM_RAG_SHAREPOINT_CLIENT_ID`, `ERM_RAG_SHAREPOINT_CLIENT_SECRET`, `ERM_RAG_SHAREPOINT_SITE_URL`

**SharePoint Document Sync:**
- Automated delta sync via Temporal workflows
  - Activity: `ProjectSyncWorkflow` - Periodic sync of entire SharePoint folder
  - Change detection: Delta tokens for incremental syncing
  - Scheduling: Cron-based scheduling in `ingestion-service/app/temporal/scheduler.py`

## Monitoring & Observability

**Error Tracking:**
- Not detected (no Sentry, DataDog, or similar service configured)

**Logs:**
- **Local file logging** - Python logging to console/files via `app/logging.py`
- **Structured logging** - JSON format with context (user, document IDs)
- **Level control:** `ERM_RAG_LOG_LEVEL` environment variable

**Metrics:**
- **Prometheus client** 0.19.0 - Metrics export (optional)
- Implementation: `ingestion-service/app/monitoring/` (if present)
- Not actively integrated into Prometheus/Grafana stack (local dev only)

**LLM Observability:**
- **Langfuse** 3.0.0+ - Claude API call tracing and cost tracking
  - Configuration: Langfuse API key and project ID (if enabled)
  - Implementation: Optional integration in `ingestion-service/app/core/llm/`

## Workflow Orchestration

**Temporal Server & SDK:**
- **Temporal Server** 1.23.0 (container: `temporalio/auto-setup:1.23.0`)
  - Address: `ERM_RAG_TEMPORAL_HOST` (default `localhost:7233` for dev, `temporal:7233` in Docker)
  - Storage: PostgreSQL backend (runs in dev with embedded DB)
  - UI: Temporal UI 2.22.3 on port 8080

- **Temporal SDK** (temporalio) 1.5.1+
  - Language: Python
  - Worker: `ingestion-service/app/temporal/worker.py`
  - Task queue: `rag-pipeline-queue`
  - Workflows: `ProjectSyncWorkflow`, `DocumentProcessingWorkflow`, `ProjectUnsyncWorkflow`
  - Activities: Document download, validation, conversion, extraction, chunking, embedding
  - Retry policies: Named per activity (`DB_RETRY`, `EXTERNAL_API_RETRY`, `CPU_INTENSIVE_RETRY`, etc.)

## CI/CD & Deployment

**Hosting:**
- **Docker containers** - All services containerized
- **Docker Compose** - Local development orchestration
- **AWS ECR** - Container registry (implied by `build_and_push_ecr.sh` script)

**CI Pipeline:**
- Not detected - No GitHub Actions, GitLab CI, or other CI configuration found

**Environment Management:**
- **Docker Compose** with `.env.local` and `.env` file injection
- Services: excel-analyser (8003), ingestion-service (8001), user-service (8002), frontend (5173), temporal (7233), temporal-ui (8080)
- Network: `erm-network` bridge for inter-service communication

## Environment Configuration

**Required env vars (Critical):**
- `AWS_BEARER_TOKEN_BEDROCK` - AWS Bedrock API authentication
- `ERM_RAG_DB_HOST`, `ERM_RAG_DB_PORT`, `ERM_RAG_DB_NAME`, `ERM_RAG_DB_USER`, `ERM_RAG_DB_PASSWORD` - PostgreSQL connection
- `ERM_RAG_SHAREPOINT_TENANT_ID`, `ERM_RAG_SHAREPOINT_CLIENT_ID`, `ERM_RAG_SHAREPOINT_CLIENT_SECRET` - SharePoint authentication
- `ERM_RAG_SHAREPOINT_SITE_URL` - SharePoint site URL
- `MSAL_TENANT_ID`, `MSAL_CLIENT_ID`, `MSAL_CLIENT_SECRET` - Azure AD / Microsoft SSO
- `AWS_REGION` - AWS region for Bedrock and Secrets Manager

**Optional env vars:**
- `ERM_RAG_ENV` - Set to "local" for .env file loading
- `ERM_RAG_TEMPORAL_HOST` - Temporal server address (default localhost:7233)
- `ERM_RAG_DISTRIBUTED_RATE_LIMITING_ENABLED` - Enable PostgreSQL-backed rate limiting
- `ERM_RAG_LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `ERM_RAG_AWS_SECRET_NAME` - AWS Secrets Manager secret name
- `LANGFUSE_*` - Langfuse API key and host (if LLM observability enabled)

**Secrets location:**
- `.env.local` file (local development, `.gitignore`d)
- AWS Secrets Manager (production)
- Environment variables (CI/CD pipelines)

## Webhooks & Callbacks

**Incoming:**
- `user-service/app/microsoft_sso/endpoints/auth.py` - OAuth callback endpoints:
  - `POST /auth/login` - Initiate Microsoft login
  - `GET /auth/callback` - OAuth2 authorization code callback
  - `POST /auth/logout` - User logout
  - `GET /auth/me` - Get current user info

**Outgoing:**
- SharePoint event notifications: Not implemented (polling-based via Temporal workflows)
- Temporal workflow status: Not exposed via webhooks (Temporal UI only)
- LLM insights: Optional Langfuse webhook for tracing

## Rate Limiting

**Service-Level Rate Limiting:**
- **Claude API** - Global 200 RPM limit (configurable via `ERM_RAG_PDF_GLOBAL_RPM_LIMIT`)
- **Implementation:** Two modes:
  1. In-Memory (single worker) - Semaphore-based with 60-second rolling window
  2. Distributed (multi-worker) - PostgreSQL-backed with advisory locks
- **Safety margin:** 90% of limit used (`ERM_RAG_PDF_RATE_LIMITER_SAFETY_MARGIN`)

---

*Integration audit: 2026-03-05*
