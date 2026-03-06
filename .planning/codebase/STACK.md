# Technology Stack

**Analysis Date:** 2026-03-05

## Languages

**Primary:**
- **TypeScript** 5.9.3 - Frontend application, type-safe development
- **Python** 3.11+ (user-service), 3.12+ (ingestion-service) - Backend microservices, data processing

**Secondary:**
- **JavaScript** - Frontend tooling and build configuration
- **SCSS/SASS** 1.94.0 - Frontend styling (`frontend/src/index.scss`, `frontend/src/App.scss`)
- **Shell/Bash** - Deployment scripts (`start.sh`, `start_services.sh`, `start_temporal_worker.sh`)

## Runtime

**Environment:**
- **Node.js** - Frontend development and build (implied by npm/package.json)
- **Python 3.11+** - User Service runtime via uvicorn
- **Python 3.12+** - Ingestion Service runtime via uvicorn

**Package Manager:**
- **npm** - Frontend dependency management (`frontend/package.json`)
- **Poetry** 1.8.0+ - Python dependency management (user-service, ingestion-service, excel-analyser)
- **Lockfiles present:**
  - `frontend/yarn.lock` (also uses yarn)
  - `frontend/package-lock.json` (npm lockfile)

## Frameworks

**Core:**
- **FastAPI** 0.100.0+ - HTTP API framework for user-service, ingestion-service, excel-analyser
- **React** 19.2.0 - Frontend UI library
- **React Router DOM** 7.9.5 - Client-side routing
- **Redux Toolkit** 2.11.0 - State management
- **Ant Design (antd)** 5.28.1 - UI component library
- **Vite** 7.2.2 - Frontend build tool and dev server

**Async/Workflow:**
- **Temporal SDK** (temporalio) 1.5.1+ - Durable workflow orchestration for document processing pipeline
- **asyncio** - Python async runtime (built-in)

**Testing:**
- **pytest** 7.4.0+ - Python unit testing framework
- **pytest-asyncio** 0.21.0+ - Async test support for pytest

**Build/Dev:**
- **TypeScript Compiler (tsc)** 5.9.3 - TypeScript compilation
- **ESLint** 9.39.1+ - JavaScript/TypeScript linting
- **Black** 23.0.0+ - Python code formatting
- **mypy** 1.5.0+ - Python static type checking
- **ruff** 0.1.0+ - Python linting

## Key Dependencies

**Critical:**

### Backend (user-service, ingestion-service)
- **pydantic** 2.0-2.9 - Data validation and settings management
- **pydantic-settings** 2.0+ - Configuration from environment variables
- **psycopg** 3.1+ (binary) - PostgreSQL adapter with connection pooling
- **psycopg-pool** 3.2.0+ - Connection pooling for database access
- **python-jose** 3.3.0+ (cryptography) - JWT token generation and validation
- **boto3** 1.28.0+ - AWS SDK for Bedrock and Secrets Manager access
- **httpx** 0.27.0+ - Async HTTP client for external APIs

### Authentication & Identity
- **msal** 1.26.0+ - Microsoft Authentication Library for SSO
- **aiohttp** 3.9.0+ - Async HTTP library for SharePoint API calls
- **email-validator** 2.0.0+ - Email validation for user models

### Embeddings & LLM
- **PyMuPDF (fitz)** 1.24.0-1.24.* - PDF page rendering to images for Claude Vision
- **Pillow** 10.0.0+ - Image processing and conversion
- **pgvector** 0.2.5+ - PostgreSQL vector similarity search
- **numpy** 2.0.2+ - Numerical computing for embeddings
- **langfuse** 3.0.0+ - LLM observability and tracing

### Document Processing
- **polars** 1.0.0+ - High-performance DataFrame operations for Excel
- **fastexcel** 0.12.0+ - Polars Excel reading engine
- **openpyxl** 3.1.0+ - Excel file format support
- **xlrd** 2.0.1+ - Legacy .xls file reading
- **python-calamine** 0.3.0+ - Calamine engine for Polars .xls support
- **pyarrow** 14.0.0+ - Parquet format support
- **rapidfuzz** 3.5.0+ - Fuzzy string matching for column verification

### Frontend
- **axios** 1.13.2 - HTTP client for API requests
- **react-toastify** 11.0.5 - Toast notifications
- **react-markdown** 10.1.0 - Markdown rendering
- **react-slick** 0.31.0, **slick-carousel** 1.8.1 - Carousel component
- **html2canvas** 1.4.1 - HTML to canvas screenshot generation
- **jspdf** 4.0.0 - PDF generation
- **localforage** 1.0.3 - Local storage with fallback support
- **@toast-ui/editor** 3.2.2 - Rich text editor
- **@mdxeditor/editor** 3.52.3 - MDX content editing
- **remark-gfm** 4.0.1 - GitHub Flavored Markdown support
- **rehype-raw**, **rehype-katex** - HTML and math formula processing

### Azure Integration
- **@azure/msal-browser** 4.27.0 - Microsoft Authentication Library for browser
- **@ant-design/v5-patch-for-react-19** 1.0.3 - Compatibility patch for React 19

### Monitoring
- **prometheus-client** 0.19.0 - Prometheus metrics export

**Infrastructure:**
- **uvicorn** 0.30.0+ - ASGI server for FastAPI applications
- **python-dotenv** 1.0.0+ - Environment variable loading from .env files
- **requests** 2.32.0+ - HTTP library for synchronous API calls
- **streamlit** 1.30.0+ (ingestion-service), 1.40.0+ (excel-analyser) - Interactive web UI for testing

## Configuration

**Environment:**
- Environment variables loaded from `.env.local` (preferred) or `.env` files
- **Prefix naming:** All app settings use vendor prefixes:
  - `ERM_RAG_*` - Ingestion service configuration
  - `AWS_*` - AWS service credentials
  - `MSAL_*`, `ERM_*` - User service configuration
- **AWS Secrets Manager integration** - Optional integration via boto3 for production secret injection
- Settings implemented via Pydantic `BaseSettings` with validation

**Build:**
- `frontend/tsconfig.json` - TypeScript configuration with React 19 targets
- `frontend/eslint.config.js` - ESLint configuration (React Hooks, React Refresh plugins)
- `frontend/.prettierrc` - Prettier formatting config (100 character line width)
- `frontend/vite.config.ts` - Vite build configuration with React plugin
- `ingestion-service/docker-compose.yml`, `user-service/docker-compose.yml` - Local dev orchestration
- Root `docker-compose.yml` - Full stack orchestration (see INTEGRATIONS.md)

## Platform Requirements

**Development:**
- Node.js (version not explicitly specified, npm 6+)
- Python 3.11+ (user-service), 3.12+ (ingestion-service)
- PostgreSQL 16+ (pgvector extension required, `CREATE EXTENSION IF NOT EXISTS vector`)
- Temporal server 1.23.0+ (for workflow orchestration)
- Docker & Docker Compose (for containerized development)
- AWS Bedrock access with bearer token authentication
- LibreOffice (for Office document → PDF conversion)

**Production:**
- Container runtime (Docker)
- PostgreSQL 16+ with pgvector extension
- Temporal cluster (managed or self-hosted)
- AWS Bedrock API access (Claude Sonnet for vision, Cohere for embeddings)
- Microsoft 365 tenant (for SharePoint integration)

## Database

**PostgreSQL 16+**
- pgvector extension for vector similarity search
- Connection pooling via psycopg-pool (min 10, max 40 connections per worker)
- Synchronous connections only (no async SQLAlchemy)
- Schema: `ai_rag` (created via migration if not exists)
- Migrations: Flyway SQL migrations in `ingestion-service/migrations/flyway/`

---

*Stack analysis: 2026-03-05*
