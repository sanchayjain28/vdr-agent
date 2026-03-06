# Codebase Concerns

**Analysis Date:** 2026-03-05

## Critical Security Issues

### Hardcoded Admin User Bypasses All Authentication in ingestion-service

**Issue:** The JWT authentication dependency in `ingestion-service` returns a hardcoded admin user unconditionally. All JWT token validation is commented out. The `get_current_user()` function bypasses all auth checks for every protected endpoint.

**Files:** `ingestion-service/app/auth/jwt_auth.py` lines 18-30

**Impact:** Any caller to any protected route in the ingestion service (project CRUD, SharePoint browsing, sync triggering) is treated as a specific admin user regardless of what token they send — including no token at all. The service has no authentication at all.

**Fix approach:** Uncomment JWT validation block, restore `credentials: HTTPAuthorizationCredentials = Depends(security)` parameter, and pass `settings.user_service_jwt_secret` to jwt.decode().

---

### Real SharePoint Credentials Committed to Git

**Issue:** `ingestion-service/.env.local` is tracked by git and contains production SharePoint OAuth2 credentials including tenant ID, client ID, and client secret (line 61-70). The file was committed in commit `7863e5c` and is still accessible in git history.

**Files:** `ingestion-service/.env.local` (tracked in git)

**Current state:**
```

```

**Impact:** These credentials grant OAuth2 access to the ERM SharePoint tenant. Anyone with access to the git history has valid credentials.

**Fix approach:**
1. Immediately rotate the SharePoint client secret in Azure AD
2. Run `git rm --cached ingestion-service/.env.local` to stop tracking
3. Add `ingestion-service/.env.local` to `.gitignore`
4. Use `git filter-repo` to remove from all history if repo is shared externally

---

### vdr-frontend Token Injection Completely Disabled

**Issue:** The entire authentication token interceptor for `vdr-frontend` is commented out. No JWT token is attached to any outgoing API request.

**Files:** `vdr-frontend/src/services/apiClients.ts` lines 92-110

**Current state:**
```typescript
client.interceptors.request.use((config) => {
    config.headers = config.headers || {};
    /*
    const token = localStorage.getItem(LocalStorageName.Token);
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    */
    return config;
```

**Impact:** All API calls from `vdr-frontend` are unauthenticated. Combined with the commented-out ingestion-service auth, both layers of authentication are simultaneously non-functional. Currently "works" because ingestion-service auth is bypassed.

**Fix approach:** Uncomment token attachment logic and implement token refresh flow (lines 111-159 also commented out).

---

### CORS Wildcard with Credentials Enabled Across All Backend Services

**Issue:** All three Python services have `allow_origins=["*"]` with `allow_credentials=True`. All three have TODO comments acknowledging this is incomplete security work.

**Files:**
- `ingestion-service/main.py` lines 47-56
- `user-service/main.py` lines 55-59
- `excel-analyser/main.py` lines 52-57

**Current pattern:**
```python
# TODO: Restrict these wildcard CORS settings once the frontend origin is finalized.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Impact:** Any origin can make credentialed cross-origin requests. Note: modern browsers reject the combination of wildcard origin + `allow_credentials=True` per CORS spec, so the credentials flag is effectively broken.

**Fix approach:** Replace `["*"]` with specific frontend origins from `frontend/src/shared/configs.ts` and `vdr-frontend/src/shared/config.ts`. Use environment-specific configuration for each deployment.

---

### OAuth State Parameter CSRF Validation Skipped

**Issue:** The OAuth2 callback endpoint in `excel-analyser` receives the `state` parameter but skips CSRF validation with an explicit TODO comment.

**Files:** `excel-analyser/app/microsoft_sso/endpoints/auth.py` lines 144-147

**Current state:**
```python
# TODO: Validate state parameter against session (implement session management)
# For now, we'll skip state validation but it should be implemented for production
if state:
    LOGGER.debug(f"Callback received for env={env}, state={state}")
```

**Impact:** The OAuth2 flow is vulnerable to CSRF attacks. An attacker could craft a malicious callback URL and trick a victim into completing authentication under the attacker's context.

**Fix approach:** Store generated state in short-lived server-side session or signed cookie at login, verify it matches during callback.

---

## High-Severity Scaling & Operational Issues

### In-Memory Instruction Cache Blocks Horizontal Scaling

**Issue:** `excel-analyser` uses an in-memory LRU cache for report section instructions. When horizontally scaled (Helm chart exists at `excel-analyser/helm/`), each pod has its own isolated cache.

**Files:** `excel-analyser/report_generation/services/instruction_cache.py` lines 1-13

**Current pattern:**
```python
"""...This is a temporary solution until Redis is implemented.

TODO: Replace with Redis for production deployment
```

**Impact:** Multi-instance deployments result in cache inconsistency. Cache invalidation on one pod does not propagate to others. This causes stale instruction data to be served depending on which pod handles the request.

**Fix approach:** Replace with Redis or database-backed cache before multi-instance deployment.

---

### Distributed Rate Limiting Disabled by Default

**Issue:** The in-memory rate limiter for Claude API calls doesn't coordinate across multiple Temporal workers. The distributed PostgreSQL-backed rate limiter exists but is disabled by default.

**Files:** `ingestion-service/app/core/llm/rate_limiter.py` and `ingestion-service/.env.local` line 102

**Current state:**
```
ERM_RAG_DISTRIBUTED_RATE_LIMITING_ENABLED=false
```

**Impact:** Running multiple Temporal workers (supported via `ingestion-service/start_multiple_workers.sh`) multiplies the effective rate limit by the number of workers. With 3 workers and 200 RPM limit, actual rate becomes 600 RPM, causing 429 throttling errors.

**Fix approach:** Enable `ERM_RAG_DISTRIBUTED_RATE_LIMITING_ENABLED=true` for multi-worker deployments. Document this requirement in `ingestion-service/start_multiple_workers.sh`.

---

### Unbounded Queries Block Scheduler Performance

**Issue:** Two critical scheduler queries load all records without pagination:

1. `get_documents_by_project_id` in `ingestion-service/app/db/dao/sharepoint_document_dao.py` (lines 314-325) — fetches all documents for a project with no LIMIT
2. `get_projects_with_sync_enabled` in `ingestion-service/app/db/dao/project_dao.py` (lines 196-208) — loads all sync-enabled projects with no limit

**Impact:** As project count and document count grow, the scheduler loads entire result sets into memory. At scale this causes memory exhaustion and slow scheduler iterations.

**Fix approach:** Add LIMIT/OFFSET pagination with safe defaults. Use cursor-based pagination for the scheduler query.

---

## Medium-Severity Data & Integrity Issues

### Six Production Routes Labeled "[TESTING ONLY]" Still Live

**Issue:** Multiple routes in `ingestion-service/app/core/routers/projects.py` are explicitly documented as testing-only in their docstrings yet are active:

- Line 195: `[TESTING ONLY] Update project details`
- Line 502: `[TESTING ONLY] Create a new project`
- Line 728: `[TESTING ONLY] List and search projects with optional filters and pagination`
- Line 922: `[TESTING ONLY] Get project details`
- Line 1674: `[TESTING ONLY] Add new SharePoint sources to an existing project`
- Line 1798: `[TESTING ONLY] Delete a project and stop its schedule`

**Impact:** These endpoints expose direct database mutation (create/update/delete projects) that are labeled as not intended for production.

**Fix approach:** Gate behind `Depends(require_admin)` for genuinely admin-only endpoints, or move behind a debug router disabled in non-local environments.

---

### Azure AD Tenant ID Malformed in frontend Config

**Issue:** The Azure `TENANT_ID` in localhost and dev configs is missing the leading `f`.

**Files:** `frontend/src/shared/configs.ts` lines 24, 37

**Current state:**
```typescript
AZURE: {
    TENANT_ID: "2fe6bd3-9c4a-485b-ae69-e18820a88130",  // Wrong - missing leading 'f'
```

**Correct value:** `f2fe6bd3-9c4a-485b-ae69-e18820a88130` (visible in .env.local and UAT_CONFIG)

**Impact:** Azure AD authentication will fail for localhost and dev environments. Any call constructing MSAL authority URL will generate a malformed tenant reference.

**Fix approach:** Update both LOCALHOST_CONFIG and DEV_CONFIG to use correct tenant ID.

---

### Bare `except:` Clauses Silently Swallow Fatal Exceptions

**Issue:** Two bare `except:` clauses catch even `SystemExit` and `KeyboardInterrupt` with no logging.

**Files:**
- `ingestion-service/app/core/routers/projects.py` line 2314
- `ingestion-service/app/core/vision/pdf_processor.py` line 1145

**Current pattern:**
```python
try:
    progress = await handle.query("get_progress")
    response["progress"] = progress
except:
    pass
```

**Impact:** Fatal exceptions and errors in workflow progress querying/PDF processing are silently lost. Makes debugging stuck workflows impossible.

**Fix approach:** Replace with `except Exception as e:` and add `LOGGER.warning("...", e)`.

---

## Medium-Severity Functional Issues

### Web Search Agent Falls Back to Fabricated Mock Results Silently

**Issue:** The `WebSearchAgent` in `excel-analyser` returns mock search results when no real provider is configured. This is a production-exposed agent.

**Files:** `excel-analyser/app/agents/web_search/agent.py` lines 134-168

**Current pattern:**
```python
# TODO: Integrate with actual search API (Brave, Google, Bing, etc.)
if not api_key:
    LOGGER.warning("Brave Search API key not configured, using mock search")
    return await self._mock_search(query)
```

**Impact:** Users receive fictional search results with no visible indication that results are not real.

**Fix approach:** Either configure a real search provider (Brave/Google/Bing) or disable the web search agent entirely until a real provider is wired up.

---

### Temporary Frontend Endpoint Not Removed

**Issue:** A function is marked as temporary with a TODO to remove after project details API changes.

**Files:** `frontend/src/services/reportGenerator.ts` lines 103-118

**Current state:**
```typescript
// TEMPORARY ENDPOINT
// TODO: Remove this endpoint after getting details in project details
export const getReportListByProjectId = async (projectId: string) => {
```

**Impact:** Temporary code remains in production. Increases surface area for bugs and confusion about what is authoritative.

**Fix approach:** Audit whether project details API now returns report list data. Migrate call sites and remove function.

---

### Report PDF Export Uses Hardcoded Internal Document Number Placeholder

**Issue:** PDF export falls back to an internal project reference string when metadata is missing.

**Files:** `frontend/src/shared/utils/pdfExport.ts` lines 776, 931

**Current pattern:**
```typescript
documentNumber: metadata?.documentNumber || "KM60-EN-RP-XXXXX",
```

**Impact:** Generated PDFs with missing document numbers display an internal reference string visible to clients.

**Fix approach:** Derive from project metadata or display empty string with visible prompt.

---

## Data & Token Security Issues

### JWT Tokens Stored in localStorage (XSS Vulnerable)

**Issue:** Both frontends store access and refresh tokens in `localStorage`, which is accessible via JavaScript and vulnerable to XSS attacks.

**Files:**
- `frontend/src/pages/auth/callback/Callback.tsx` lines 50-52
- `vdr-frontend/src/services/apiClients.ts` lines 61-62

**Current pattern:**
```typescript
localStorage.setItem(LocalStorageName.Token, response.access_token);
localStorage.setItem(LocalStorageName.RefreshToken, response.refresh_token);
```

**Impact:** Any successful XSS attack (including via compromised third-party library) can exfiltrate tokens. Refresh tokens (7-day lifespan) are especially sensitive.

**Fix approach:** Store tokens in `HttpOnly` cookies managed server-side. Enforce strict Content Security Policy to reduce XSS surface area.

---

### Placeholder URLs in Frontend Config

**Issue:** Multiple config entries use `https://dev.test.com/` as placeholders for `USER_BASE_URL`.

**Files:**
- `frontend/src/shared/configs.ts` lines 19, 32
- `vdr-frontend/src/shared/config.ts` lines 11, 18

**Impact:** Any feature calling `USER_BASE_URL` in localhost or dev mode will fail silently or hit a non-existent domain.

**Fix approach:** Replace with actual dev user-service URL (`http://localhost:8002` locally, `https://dev-user-service.ermtools.app` for dev).

---

## Code Quality & Testing Issues

### Zero Test Coverage in Frontend

**Issue:** No test files exist in either frontend codebase (`frontend/src/` and `vdr-frontend/src/`).

**Files:** Both `frontend/` and `vdr-frontend/` — no `*.test.*` or `*.spec.*` files found

**Impact:** UI logic changes are not validated. Auth flow changes, state management bugs, and broken components go undetected until production.

**Fix approach:** Add basic smoke tests for auth flow. Use Vitest for unit testing components. Aim for 50%+ coverage on critical paths (auth, API integration, state).

---

### Limited Integration Test Coverage

**Issue:** Test coverage is unit-only. No integration tests for API endpoints and no E2E tests for user flows.

**Files:**
- `ingestion-service/tests/unit/` — 20 unit test files, zero integration tests
- `user-service/tests/unit/` — minimal coverage
- Backend has no API contract tests

**Impact:** Database migration errors, API contract changes, and cross-service failures are not caught before deployment.

**Fix approach:** Add API-level integration tests for critical ingestion-service routes (project CRUD, sync trigger, document status). Use pytest + HTTPX.

---

### Excessive TypeScript `any` Usage

**Issue:** Approximately 96 uses of `: any` or `as any` across frontend code, concentrated in store interfaces and API service layers.

**Notable files:**
- `vdr-frontend/src/store/knowledgeAIChat/knowledgeAIChat.interface.ts` — `metadata: any`, `last_error: any`
- `vdr-frontend/src/services/apiClients.ts` — `payload?: any` in helpers

**Impact:** Loses type safety at API boundaries. TypeScript compile-time checks become useless for those paths.

**Fix approach:** Progressively type API response shapes using explicit interfaces. Start with highest-traffic service functions.

---

### Large Monolithic Router File

**Issue:** The projects router in ingestion-service is 2,557 lines, combining CRUD, workflow triggering, SharePoint integration, and document management in one file.

**Files:** `ingestion-service/app/core/routers/projects.py` — 2,557 lines

**Impact:** Hard to test individual endpoints. Endpoint logic mixed with routing. Navigation is difficult. Testing requires mocking entire database layer.

**Fix approach:** Extract endpoint logic to service classes (pattern already used in `excel-analyser/app/routers/chat_sessions.py`). Keep router files thin — only routing, parameter extraction, response formatting.

---

## Low-Severity Issues

### PDF Export Uses Hardcoded setTimeout for Font Loading

**Issue:** PDF generation uses fixed `setTimeout` delays instead of waiting for actual font loading events.

**Files:** `frontend/src/shared/utils/pdfExport.ts` lines 754, 757, 829, 877, 880

**Current pattern:**
```typescript
await new Promise((resolve) => setTimeout(resolve, PDF_CONFIG.fontLoadDelay));
```

**Impact:** On slow devices, delays may be insufficient, causing missing fonts. On fast devices, delays add unnecessary latency.

**Fix approach:** Use `document.fonts.ready` promise for event-driven font loading.

---

### Mock Reviewer Data Hardcoded in vdr-frontend

**Issue:** The reviewer selection modal uses a hardcoded list of fictional reviewers with placeholder avatars.

**Files:** `vdr-frontend/src/component/scope/SelectReviewerModal/SelectReviewerModal.tsx` lines 19-50

**Impact:** The reviewer assignment feature is non-functional. Consistent with Phase 6 gap (vdr-frontend not yet connected to live APIs) but should be tracked.

**Fix approach:** Fetch reviewers from user-service or project collaborators list (blocked by Phase 6 API integration).

---

### Missing HTTP Rate Limiting on user-service and excel-analyser

**Issue:** Neither `user-service` nor `excel-analyser` apply HTTP-level rate limiting. `ingestion-service` rate-limits Claude API but not incoming HTTP requests.

**Files:** `user-service/main.py`, `excel-analyser/main.py` — no throttling middleware present

**Impact:** Login endpoint in user-service is susceptible to brute-force attacks. Analysis endpoints in excel-analyser could be abused to generate high LLM costs.

**Fix approach:** Add `slowapi` rate limiting to auth endpoints in user-service and analysis trigger endpoints in excel-analyser.

---

### Commented-Out Code Blocks in vdr-frontend

**Issue:** Approximately 130 lines of token refresh logic are commented out in `vdr-frontend/src/services/apiClients.ts` (lines 22-66, 111-159) rather than removed or tracked in a branch.

**Impact:** Creates confusion about whether this is planned functionality, dead code, or work in progress.

**Fix approach:** If planned work, uncomment and implement. If dead code, remove it.

---

### docker-compose.yml References Missing Env Files

**Issue:** The root `docker-compose.yml` references `./excel-analyser/.env` (line 18) and `./user-service/.env` (line 69) but no template or example files exist in the repository.

**Files:** Root `/docker-compose.yml` lines 18, 69

**Impact:** New developers cloning the repo cannot start the full stack without undocumented env files. The `start.sh` script depends on these files existing.

**Fix approach:** Create `excel-analyser/.env.example` and `user-service/.env.example` with placeholder values. Commit them. Update README.

---

### Unimplemented Chunk Boundary Optimization

**Issue:** A TODO marks an unimplemented optimization in the markdown chunker.

**Files:** `ingestion-service/app/core/chunking/markdown_chunker.py` line 434

```python
# TODO: Implement intelligent boundary optimization:
```

**Impact:** Chunk quality for documents with irregular heading hierarchies may be suboptimal, affecting RAG retrieval accuracy.

**Fix approach:** Implement the boundary optimization or document why the current heuristic is production-ready.

---

### Report Section Export Not Implemented

**Issue:** A TODO marks selected-sections export feature as unimplemented.

**Files:** `frontend/src/pages/reportGenerator/ReportGenerator.tsx` line 308

```typescript
// TODO: Implement selected sections export
```

**Impact:** Users cannot selectively export report sections — only full report export works.

**Fix approach:** Implement section-level export using the same PDF utility in `frontend/src/shared/utils/pdfExport.ts`.

---

### File Cleanup from PVC Not Implemented

**Issue:** Sandbox API file cleanup requires PVC mounting that is not configured in Kubernetes deployment.

**Files:** `excel-analyser/sandbox_api/main.py` line 337

```python
# TODO: Add file cleanup from PVC (requires mounting PVC to API pod or cleanup job)
```

**Impact:** Temporary files accumulate without bound in Kubernetes deployments, leading to disk exhaustion.

**Fix approach:** Mount PVC in Kubernetes deployment spec. Add background cleanup job deleting files older than 24 hours.

---

*Concerns audit: 2026-03-05*
