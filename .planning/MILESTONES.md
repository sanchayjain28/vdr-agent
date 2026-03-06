# Milestones

## v1.0 VDR Agent Service (Shipped: 2026-03-06)

**Phases completed:** 10 phases, 21 plans, 45 feat commits
**Timeline:** 9 days (2026-02-24 → 2026-03-05)
**Codebase:** 2,299 LOC Python (vdr-agent), 83 files modified

**Key accomplishments:**
- Stood up a complete FastAPI microservice with Pydantic config, async DB pool, Docker integration
- Implemented concurrency-safe document claiming via `FOR UPDATE SKIP LOCKED` — no duplicate processing possible
- Built full AI generation pipeline: parallel section summaries → combined document summary → per-topic fitment evaluations via AWS Bedrock
- Created REST API surface: topic CRUD (5 endpoints) + results API (3 endpoints) consuming 4 DAO layers across 2 schemas
- Wired vdr-frontend to vdr-agent APIs: API-driven topic sidebar, polling document status, processing status indicators

**Git range:** `feat(01-01)` → `feat(10-01)` (45 commits)

### Known Gaps

Proceeding with known gaps as tech debt (audit status: `gaps_found`):

- **FE-01** (partial): ScopeSidebar wiring present but Phase 10 unverified; `VDR_AGENT_BASE_URL` is `"https://TBD/"` in non-localhost configs
- **FE-02** (partial): `getDocumentFitment()` exported but never called; only aggregate counts shown, not per-topic detail
- **FE-03** (partial): ScopeDetails status Tag wiring appears complete but Phase 10 unverified
- **TOPIC-01** (integration bug): AddScope sends empty `instruction: ""` → API returns 422
- **TOPIC-04** (missing UI): No delete button in frontend — DELETE endpoint unreachable from UI
- **API-01** (design gap): Dedicated `/documents/{id}/summary` endpoint never called from frontend
- **API-02** (orphaned): `getDocumentFitment()` dead code — per-topic fitment route unused

### Tech Debt

- CORS wildcard TODO in main.py
- Migration execution not human-verified against live Postgres
- `VDR_AGENT_BASE_URL` placeholder in DEV/PRE_PROD configs
- No Nyquist validation for any phase

---

