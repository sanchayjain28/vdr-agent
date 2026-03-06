# Phase 10: Frontend Integration - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire `vdr-frontend` to `vdr-agent` APIs to surface real AI data:
1. Replace 19 hardcoded scope names in `ScopeSidebar.tsx` with topics loaded from `GET /vdr-agent/topics?project_id=<id>`
2. Populate the empty "File Summary" and "Scope Fitting" columns in `ScopeDetails.tsx` with AI summary and fitment data
3. Show processing status per document row (pending / processing / done / failed)
4. Poll every 10–15s to auto-refresh without a page reload

No new backend work. No new pages. No auth changes. Scope = wiring existing frontend to existing API.

</domain>

<decisions>
## Implementation Decisions

### API URL configuration
- Add `VDR_AGENT_BASE_URL` to `config.ts` `IConfig` interface
- Localhost: `http://localhost:8004/vdr-agent/`
- Dev / Pre-prod: placeholder strings (`"https://TBD/"`) — to be filled when hostnames are confirmed
- Create a new `vdrAgentApi` Axios instance in `apiClients.ts` using `VDR_AGENT_BASE_URL` (same interceptor pattern as `ingestionApi`)

### Claude's Discretion
- Grid design for fitment column (summary badge vs expanded columns vs drawer)
- Whether to create a new Redux slice for vdr-agent data or fetch directly in components
- "ADD SCOPE" button wiring to POST /topics API vs keeping local-only
- Polling implementation (useEffect interval in ScopeDetails, cleared on unmount)
- TypeScript interface shapes for topics, document results, fitment items
- Exact loading / error states for each data fetch
- Order/grouping of topics in the sidebar

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingestionApi` (`services/apiClients.ts`): Axios instance with subdomain header + interceptors — exact pattern to copy for `vdrAgentApi`
- `get()` helper (`services/apiClients.ts`): Used by all existing service functions; `vdrAgent.ts` service file should use the same helper
- `getProjectDocuments` (`services/sharepoint.ts`): Fetch + Redux dispatch pattern; new vdr-agent fetches should follow the same structure
- `useAppSelector` / `store/hooks.ts`: Already wired in `ScopeDetails.tsx` and `ScopeSidebar.tsx` — consistent with existing store access
- `scopeSlice.ts` + `scopeInterface.ts`: Existing Redux slice for scopes; can be extended or replaced with API-driven data

### Established Patterns
- `config.ts` exports a single `configs` object with per-environment values — add `VDR_AGENT_BASE_URL` here
- Services live in `src/services/` and dispatch to Redux store directly (not via thunks)
- `IProjectDocument.id` === `ai_rag.documents.id` UUID — this is the document ID used in all vdr-agent endpoints
- `projectId` available via `useAppSelector((state) => state.app.selectedProjectId)` — already used in `ScopeDetails.tsx`
- Table columns in `ScopeDetails.tsx` use `render: () => ...` pattern — swap the `"-"` renders

### Integration Points
- `ScopeSidebar.tsx` lines 22–47: `defaultScopes` array — replace with API call
- `ScopeDetails.tsx` line 239: `"File Summary"` column `render: () => <div>-</div>` — replace with summary data
- `ScopeDetails.tsx` line 244: `"Scope Fitting"` column `render: () => <div>-</div>` — replace with fitment data
- `ScopeDetails.tsx` line 232: `"Status"` column `render: (_, record) => record.status || "-"` — augment with `summary_status` from vdr-agent
- `config.ts`: `IConfig` interface and all three environment objects need `VDR_AGENT_BASE_URL`
- `apiClients.ts`: New `vdrAgentApi` Axios instance exported alongside `ingestionApi`
- `src/services/vdrAgent.ts`: New file — `getTopics(projectId)`, `getDocuments(projectId)`, `getDocumentFitment(documentId)`, `getDocumentSummary(documentId)`

</code_context>

<specifics>
## Specific Ideas

- API calls vdr-agent directly (not through a gateway) — `VDR_AGENT_BASE_URL` is a standalone base URL per environment
- localhost port 8004 confirmed (from Phase 1: `01-02-PLAN.md` used port 8004 for vdr-agent)
- Dev/prod VDR_AGENT_BASE_URL values are TBD — use placeholder strings so the code compiles and the shape is established

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 10-frontend-integration*
*Context gathered: 2026-03-05*
