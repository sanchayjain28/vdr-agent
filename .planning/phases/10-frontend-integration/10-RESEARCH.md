# Phase 10: Frontend Integration - Research

**Researched:** 2026-03-05
**Domain:** React / Redux / TypeScript — wiring vdr-frontend to vdr-agent REST APIs with polling
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**API URL configuration**
- Add `VDR_AGENT_BASE_URL` to `config.ts` `IConfig` interface
- Localhost: `http://localhost:8004/vdr-agent/`
- Dev / Pre-prod: placeholder strings (`"https://TBD/"`) — to be filled when hostnames are confirmed
- Create a new `vdrAgentApi` Axios instance in `apiClients.ts` using `VDR_AGENT_BASE_URL` (same interceptor pattern as `ingestionApi`)

**No new backend work. No new pages. No auth changes. Scope = wiring existing frontend to existing API.**

### Claude's Discretion
- Grid design for fitment column (summary badge vs expanded columns vs drawer)
- Whether to create a new Redux slice for vdr-agent data or fetch directly in components
- "ADD SCOPE" button wiring to POST /topics API vs keeping local-only
- Polling implementation (useEffect interval in ScopeDetails, cleared on unmount)
- TypeScript interface shapes for topics, document results, fitment items
- Exact loading / error states for each data fetch
- Order/grouping of topics in the sidebar

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FE-01 | vdr-frontend loads topic names from vdr-agent API (replaces hardcoded ESG scope list) | `GET /topics?project_id=<id>` returns `TopicResponse[]`; replace `defaultScopes` array in `ScopeSidebar.tsx` lines 22–47 |
| FE-02 | vdr-frontend shows fitment result per topic in the scope/document grid | `GET /documents/{id}/fitment` returns `FitmentItem[]` per active topic; replace `render: () => <div>-</div>` in "Scope Fitting" column |
| FE-03 | vdr-frontend shows processing status indicator (pending / processing / done) per document | `GET /documents?project_id=<id>` returns `DocumentListItem[]` with `summary_status`; replace `record.status || "-"` in "Status" column |
</phase_requirements>

---

## Summary

Phase 10 wires the existing `vdr-frontend` React/Redux/TypeScript app to the `vdr-agent` FastAPI service without building new pages or backend endpoints. All three requirements reduce to: (1) create one new Axios client, (2) create one new service file with three or four fetch functions, (3) modify two components (`ScopeSidebar.tsx` and `ScopeDetails.tsx`) to call those functions instead of showing hardcoded/empty data, and (4) add a polling interval in `ScopeDetails.tsx` to auto-refresh every 10–15 seconds.

The vdr-agent exposes three relevant endpoints: `GET /topics?project_id=`, `GET /documents?project_id=`, and `GET /documents/{id}/fitment`. The `root_path="/vdr-agent"` in FastAPI means paths served at `http://localhost:8004/vdr-agent/topics`, so the `VDR_AGENT_BASE_URL` for localhost is `http://localhost:8004/vdr-agent/` and service calls use relative paths like `topics` and `documents`.

The existing codebase already has a clear pattern: `ingestionApi` Axios instance → `get()` helper → service function → Redux dispatch. The new `vdrAgentApi` instance must follow this exact pattern. TypeScript strict mode is enabled (`"strict": true` in `tsconfig.app.json`), so all new interfaces must be complete and all optional fields must be typed as `T | null` or `T | undefined`.

**Primary recommendation:** Create `src/services/vdrAgent.ts` with `getTopics`, `getDocuments`, and `getDocumentFitment` functions; add `vdrAgentApi` to `apiClients.ts`; add `VDR_AGENT_BASE_URL` to `config.ts`; update `ScopeSidebar.tsx` to fetch topics; update `ScopeDetails.tsx` to show status + fitment + poll.

---

## Standard Stack

### Core (already in project — no new installs)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 19.2.0 | UI components | Already in project |
| TypeScript | ~5.9.3 | Type safety | Already in project |
| Redux Toolkit | ^2.11.2 | State management | Already in project; `useAppSelector` pattern used in both target components |
| Axios | ^1.13.2 | HTTP client | Already in project; `ingestionApi` pattern to copy |
| Ant Design | ^6.1.3 | UI components (Table, Tag, Badge, Spin) | Already in project; Table already used in `ScopeDetails.tsx` |
| react-toastify | ^11.0.5 | Error notifications | Already in project; used in all existing services |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| redux-persist | ^6.0.0 | State persistence | Already in store — topics slice (if added) must follow existing whitelist pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| useEffect interval (polling) | react-query `refetchInterval` | react-query not in project — don't add a library for this; useEffect is sufficient |
| Redux slice for vdr-agent data | Component-local useState | Either works; Claude's discretion — local state is simpler for this phase, Redux is more testable |

**Installation:** No new packages needed. Everything required is already a dependency.

---

## Architecture Patterns

### Relevant Existing Project Structure

```
vdr-frontend/src/
├── shared/
│   └── config.ts               # IConfig interface + environment objects — ADD VDR_AGENT_BASE_URL here
├── services/
│   ├── apiClients.ts            # Axios instances + get/post helpers — ADD vdrAgentApi here
│   ├── sharepoint.ts            # Pattern to copy for vdrAgent.ts
│   └── vdrAgent.ts              # NEW FILE — getTopics, getDocuments, getDocumentFitment
├── store/
│   ├── scope/
│   │   ├── scopeInterface.ts    # Existing Scope interface — replace or extend for API-driven data
│   │   └── scopeSlice.ts        # Existing local-only scope state — may be replaced
│   └── sharepoint/              # Pattern to copy for vdrAgent slice (if Redux approach chosen)
└── component/scope/
    └── scopeSidebar/
        └── ScopeSidebar.tsx     # TARGET: replace defaultScopes[] with API fetch
pages/scopeDetails/
    └── ScopeDetails.tsx         # TARGET: replace "-" renders + add polling
```

### Pattern 1: New Axios Instance (copy ingestionApi pattern)

**What:** Add `vdrAgentApi` instance to `apiClients.ts` with the same interceptor setup as `ingestionApi`.
**When to use:** Mandatory — locked decision.

```typescript
// In src/services/apiClients.ts — after existing ingestionApi declaration
export const vdrAgentApi = axios.create({
  baseURL: configs.VDR_AGENT_BASE_URL,
  headers: {
    "Content-Type": "application/json",
    Subdomain: getSubdomain(),
  },
});

// Must be added to the interceptor application array:
[axiosClient, ingestionApi, vdrAgentApi].forEach((client) => {
  applyRequestInterceptor(client);
  setupResponseInterceptor(client);
});
```

### Pattern 2: Config Extension

**What:** Add `VDR_AGENT_BASE_URL` to all three environment configs in `config.ts`.
**When to use:** Mandatory — locked decision.

```typescript
// In src/shared/config.ts
interface IConfig {
  BASE_URL: string;
  USER_BASE_URL: string;
  INGESTION_BASE_URL: string;
  VDR_AGENT_BASE_URL: string;  // ADD THIS
  HOST: string;
}

const LOCALHOST_CONFIG: IConfig = {
  // ...existing fields...
  VDR_AGENT_BASE_URL: "http://localhost:8004/vdr-agent/",
};

const DEV_CONFIG: IConfig = {
  // ...existing fields...
  VDR_AGENT_BASE_URL: "https://TBD/",
};

const PRE_PROD_CONFIG: IConfig = {
  // ...existing fields...
  VDR_AGENT_BASE_URL: "https://TBD/",
};
```

**CRITICAL:** The vdr-agent FastAPI app sets `root_path="/vdr-agent"` in `main.py`. When accessed directly at `http://localhost:8004`, requests go to `http://localhost:8004/vdr-agent/topics`. Therefore `VDR_AGENT_BASE_URL = "http://localhost:8004/vdr-agent/"` and service calls use `topics`, `documents` as relative paths.

### Pattern 3: Service File (copy sharepoint.ts pattern)

**What:** New `src/services/vdrAgent.ts` with typed fetch functions dispatching to store.
**When to use:** All vdr-agent API calls go through this file.

```typescript
// src/services/vdrAgent.ts
import { toast } from "react-toastify";
import { get, vdrAgentApi } from "./apiClients";

export interface ITopic {
  id: string;
  project_id: string;
  name: string;
  instruction: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface IDocumentListItem {
  id: string;
  file_name: string;
  file_path: string;
  file_type: string;
  page_count: number | null;
  summary_status: "pending" | "processing" | "done" | "failed";
  fitment_done_count: number;
  fitment_total_count: number;
}

export interface IFitmentItem {
  topic_id: string;
  topic_name: string;
  status: "pending" | "done" | "failed";
  reasoning: string | null;
}

export const getTopics = async (projectId: string): Promise<ITopic[] | undefined> => {
  try {
    return await get(vdrAgentApi, `topics`, { params: { project_id: projectId } });
  } catch (error: any) {
    console.error("getTopics error", error);
    toast.error("Failed to load topics.");
    return undefined;
  }
};

export const getVdrDocuments = async (projectId: string): Promise<IDocumentListItem[] | undefined> => {
  try {
    return await get(vdrAgentApi, `documents`, { params: { project_id: projectId } });
  } catch (error: any) {
    // Silent fail for polling — do not toast on every poll cycle
    console.error("getVdrDocuments error", error);
    return undefined;
  }
};

export const getDocumentFitment = async (documentId: string): Promise<IFitmentItem[] | undefined> => {
  try {
    return await get(vdrAgentApi, `documents/${documentId}/fitment`);
  } catch (error: any) {
    console.error("getDocumentFitment error", error);
    return undefined;
  }
};
```

### Pattern 4: Polling with useEffect (in ScopeDetails.tsx)

**What:** `setInterval` inside `useEffect`, cleared on unmount. Interval: 10–15 seconds.
**When to use:** Mandatory — success criterion 4 requires auto-refresh without page reload.

```typescript
// In ScopeDetails.tsx — add alongside existing projectId useEffect
const POLL_INTERVAL_MS = 12000; // 12 seconds — within 10-15s window

useEffect(() => {
  if (!projectId) return;

  // Initial fetch
  fetchVdrData(projectId);

  // Start polling
  const intervalId = setInterval(() => {
    fetchVdrData(projectId);
  }, POLL_INTERVAL_MS);

  // Cleanup — critical to prevent memory leaks and state updates on unmounted components
  return () => clearInterval(intervalId);
}, [projectId]);
```

### Pattern 5: ScopeSidebar — Replace defaultScopes with API data

**What:** Remove the 19-item `defaultScopes` array; fetch from API on mount.
**When to use:** Mandatory — FE-01 requirement.

```typescript
// Replace hardcoded defaultScopes with:
const [topics, setTopics] = useState<ITopic[]>([]);
const [isTopicsLoading, setIsTopicsLoading] = useState(false);

useEffect(() => {
  if (!projectId) return;
  setIsTopicsLoading(true);
  getTopics(projectId)
    .then((data) => setTopics(data ?? []))
    .finally(() => setIsTopicsLoading(false));
}, [projectId]);
```

NOTE: `ScopeSidebar.tsx` currently does NOT use `projectId`. It must be retrieved via `useAppSelector((state) => state.app.selectedProjectId)` — same selector already used in `ScopeDetails.tsx`.

### Pattern 6: ScopeDetails Table Column Updates

**What:** Replace the `"-"` renders in "Status", "File Summary", and "Scope Fitting" columns.
**When to use:** FE-02, FE-03 requirements.

The "Scope Fitting" column design is Claude's discretion. Recommended approach: show `fitment_done_count / fitment_total_count` as a progress indicator from the list endpoint (no per-row fitment API call needed for initial implementation — the list endpoint already provides aggregate counts).

```typescript
// Status column — replace record.status with summary_status from vdr-agent
{
  title: "Status",
  key: "status",
  render: (_, record) => {
    const vdrDoc = vdrDocuments.find((d) => d.id === record.id);
    const status = vdrDoc?.summary_status ?? "pending";
    // Use Ant Design Tag for visual status indicator
    const colorMap: Record<string, string> = {
      pending: "default",
      processing: "processing",
      done: "success",
      failed: "error",
    };
    return <Tag color={colorMap[status] ?? "default"}>{status}</Tag>;
  },
},

// Scope Fitting column — show aggregate progress from list endpoint
{
  title: "Scope Fitting",
  key: "scopeFitting",
  render: (_, record) => {
    const vdrDoc = vdrDocuments.find((d) => d.id === record.id);
    if (!vdrDoc) return <div>-</div>;
    return <div>{vdrDoc.fitment_done_count} / {vdrDoc.fitment_total_count}</div>;
  },
},
```

### Anti-Patterns to Avoid

- **Calling `getDocumentFitment` for every document row on every poll cycle:** This would generate `N × poll_frequency` API calls. The `GET /documents?project_id=` list endpoint already returns `fitment_done_count` and `fitment_total_count` per document — use this for the grid. Only call `getDocumentFitment` if you add a per-document detail view in a future phase.
- **Toasting on every failed poll cycle:** If the backend is temporarily unavailable, `setInterval` will show a toast every 12 seconds. Use `console.error` only for polling, reserving `toast.error` for user-initiated actions.
- **Not clearing the interval on unmount:** React 19 strict mode in development double-invokes effects; without cleanup, multiple intervals will accumulate.
- **Holding TypeScript `any` types:** `strict: true` and `noUnusedLocals: true` are enabled. All service return types must be fully typed — use `ITopic[]`, `IDocumentListItem[]`, not `any[]`.
- **Leaving `import { IProjectDocument }` unused after table refactor:** `noUnusedLocals: true` will fail the build. Clean up imports after each column change.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Status badge UI | Custom CSS class + `<span>` | Ant Design `<Tag color="...">` | Already in project, consistent look |
| Loading state spinner | Custom loader | Ant Design `<Spin>` or Table's built-in `loading` prop | Already used on the Table in ScopeDetails.tsx |
| HTTP client with interceptors | Raw fetch | Axios via `vdrAgentApi` (locked decision) | Token injection, error handling, consistent with existing |
| Polling mechanism | 3rd party library | `setInterval` + `useEffect` cleanup | react-query not in project; overkill to add for one use case |

**Key insight:** Every mechanism needed — HTTP, state, UI components, error notifications — is already present in the project. The task is purely composition.

---

## Common Pitfalls

### Pitfall 1: Document ID Mismatch Between APIs

**What goes wrong:** `IProjectDocument.id` from the ingestion-service (`GET /projects/{id}/documents`) may not match `IDocumentListItem.id` from vdr-agent (`GET /documents?project_id=`).
**Why it happens:** STATE.md explicitly states "`IProjectDocument.id` === `ai_rag.documents.id` UUID" — they are the same UUID, but this must be verified at runtime. If the ingestion-service returns `source_file_id` as `id` instead, the `vdrDocuments.find((d) => d.id === record.id)` lookup will silently return `undefined` for every row.
**How to avoid:** Confirm the UUIDs match by logging both arrays in development before wiring the render functions. The `IProjectDocument` interface has both `id` and `source_file_id` fields — `id` is the `ai_rag.documents.id` per STATE.md.
**Warning signs:** All rows show `"-"` or `"pending"` even after the vdr-agent returns data.

### Pitfall 2: Root Path vs Base URL Confusion

**What goes wrong:** `VDR_AGENT_BASE_URL = "http://localhost:8004/"` (without `/vdr-agent/`) causes 404s on all vdr-agent requests.
**Why it happens:** The FastAPI app uses `root_path="/vdr-agent"` — this is the path prefix used when running behind a reverse proxy. When accessed directly on port 8004, the routes ARE at `/vdr-agent/topics`, not `/topics`.
**How to avoid:** Set `VDR_AGENT_BASE_URL = "http://localhost:8004/vdr-agent/"` and verify with `curl http://localhost:8004/vdr-agent/health` before wiring up components.
**Warning signs:** 404 responses from the vdrAgentApi with valid request payloads.

### Pitfall 3: TypeScript Strict Mode Compilation Failures

**What goes wrong:** The build fails on `tsc -b` with "unused variable", "implicit any", or "object possibly undefined" errors after component changes.
**Why it happens:** `tsconfig.app.json` sets `strict: true`, `noUnusedLocals: true`, `noUnusedParameters: true`. When hardcoded arrays are removed, their associated type imports may become unused. When API data is optional, properties accessed without null guards fail.
**How to avoid:** After each change, run `yarn build` or `tsc --noEmit` to surface errors. Guard all `vdrDocuments.find(...)` results before property access.
**Warning signs:** CI lint or build step fails; local dev still works because Vite skips type-checking.

### Pitfall 4: Polling Creates Stale Closure Over `projectId`

**What goes wrong:** If `projectId` changes (user navigates to a different project), the interval still fetches data for the old project.
**Why it happens:** `setInterval` callback captures the value of `projectId` at the time the effect ran, not the current value.
**How to avoid:** Include `projectId` in the `useEffect` dependency array. When `projectId` changes, the cleanup function runs (clearing the old interval) and the effect re-runs (starting a new interval with the new `projectId`). This is already the standard React pattern.
**Warning signs:** Wrong data appears after navigating between projects without a page reload.

### Pitfall 5: 404 from vdr-agent When No Documents Exist

**What goes wrong:** `GET /documents?project_id=` returns HTTP 404 when no documents have been ingested for the project yet — this is by design in the vdr-agent router (`raise HTTPException(404, "No documents found")`).
**Why it happens:** The vdr-agent treats "no documents" as 404 (proxy for project existence check). The Axios `setupResponseInterceptor` propagates non-2xx responses as rejected promises.
**How to avoid:** In `getVdrDocuments`, catch the error and return `[]` (empty array) instead of `undefined` when the status is 404. This prevents the toast error from firing for empty projects.
**Warning signs:** Toast error appears immediately when opening a new project with no synced documents.

---

## Code Examples

Verified patterns from existing code:

### Existing Service Pattern (copy exactly for vdrAgent.ts)

```typescript
// Source: vdr-frontend/src/services/sharepoint.ts (existing)
export const getProjectDocuments = async (
  projectId: string,
  limit: number = 100,
): Promise<IProjectDocumentsResponse | undefined> => {
  try {
    store.dispatch(setIsProjectDocumentsLoading(true));
    const res = await get(ingestionApi, `projects/${projectId}/documents`, {
      params: { view: "list", limit },
    });
    store.dispatch(setProjectDocuments(res?.documents || []));
    store.dispatch(setProjectDocumentsTotal(res?.total || 0));
    return res;
  } catch (error: any) {
    console.error("getProjectDocuments error", error);
    toast.error("Failed to load project documents.");
    return undefined;
  } finally {
    store.dispatch(setIsProjectDocumentsLoading(false));
  }
};
```

### Existing Selector Pattern (already in ScopeDetails.tsx)

```typescript
// Source: vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx (existing)
const projectId = useAppSelector((state) => state.app.selectedProjectId);
const { projectDocuments, isProjectDocumentsLoading } = useAppSelector((state) => state.sharepoint);
```

### Existing Table Render Pattern (target for modification)

```typescript
// Source: vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx (existing — to be replaced)
{
  title: "File Summary",
  dataIndex: "fileSummary",
  key: "fileSummary",
  width: "20%",
  render: () => <div className="table-two-line">-</div>,  // REPLACE THIS
},
{
  title: "Scope Fitting",
  dataIndex: "scopeFitting",
  key: "scopeFitting",
  width: "20%",
  render: () => <div className="table-two-line">-</div>,  // REPLACE THIS
},
```

### Exact API Response Shapes (from vdr-agent source)

```typescript
// TopicResponse (GET /topics?project_id=)
// Source: vdr-agent/app/models/topic.py
{
  id: UUID,
  project_id: UUID,
  name: string,
  instruction: string,
  is_active: boolean,
  created_at: datetime,
  updated_at: datetime
}

// DocumentListItem (GET /documents?project_id=)
// Source: vdr-agent/app/models/document.py
{
  id: UUID,
  file_name: string,
  file_path: string,
  file_type: string,
  page_count: number | null,
  summary_status: "pending" | "processing" | "done" | "failed",
  fitment_done_count: number,
  fitment_total_count: number
}

// FitmentItem (GET /documents/{id}/fitment)
// Source: vdr-agent/app/models/document.py
{
  topic_id: UUID,
  topic_name: string,
  status: "pending" | "done" | "failed",
  reasoning: string | null
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded `defaultScopes` array (19 items) in `ScopeSidebar.tsx` | API-fetched topics from `GET /vdr-agent/topics?project_id=` | This phase | Source of truth moves to backend |
| `render: () => <div>-</div>` in Status/Summary/Fitting columns | Live data from vdr-agent + polling | This phase | Users see AI results without page reload |
| `scopeSlice.ts` adds scopes to local Redux state only | Topics come from API; Redux scope slice may be deprecated | This phase | Redux slice becomes optional/unused |

**Deprecated/outdated after this phase:**
- `defaultScopes` array in `ScopeSidebar.tsx` lines 22–47: remove entirely
- `allScopes` useMemo merge logic (lines 50–62): remove — no longer needed when API is the source
- The Redux `scope` whitelist entry in `store.ts` persist config: if scopeSlice is retired, remove from whitelist to avoid stale data persisting

---

## Open Questions

1. **`[Pre-Phase 10]` vdr-frontend URL prefix (from STATE.md blockers)**
   - What we know: vdr-agent serves at `root_path="/vdr-agent"` on port 8004; localhost confirmed in CONTEXT.md as `http://localhost:8004/vdr-agent/`
   - What's unclear: Dev/prod hostnames are TBD — CONTEXT.md says use placeholder strings; no gateway confirmed
   - Recommendation: Use `"https://TBD/"` for DEV_CONFIG and PRE_PROD_CONFIG as CONTEXT.md instructs; flag for environment team to fill before deployment

2. **Whether to keep or retire `scopeSlice.ts`**
   - What we know: `scopeSlice` is in redux-persist whitelist; `addScope` action is called from `AddScope` component; the "ADD SCOPE" button is local-only in scope
   - What's unclear: CONTEXT.md marks "ADD SCOPE wiring to POST /topics" as Claude's discretion — keeping local-only is acceptable for this phase
   - Recommendation: Keep `scopeSlice` for locally-added scopes (ADD SCOPE button stays local); API-fetched topics go into component state (useState) in `ScopeSidebar.tsx`. This avoids a redux-persist migration.

3. **File Summary column content**
   - What we know: `GET /documents/{id}/summary` returns `summary_text` (long AI text) which is too long for a table cell; CONTEXT.md defers FE-04 (AI summary detail view) to v2
   - What's unclear: What should the "File Summary" column show if full text is out of scope?
   - Recommendation: Keep "File Summary" as a truncated status badge (show `summary_status` from the list endpoint); OR show "-" for now since REQUIREMENTS.md lists FE-04 as v2. The column doesn't need to be removed, just left as-is or showing status.

---

## Validation Architecture

> `workflow.nyquist_validation` is not set to `true` in `.planning/config.json` — section skipped.

---

## Sources

### Primary (HIGH confidence)
- Direct code read: `vdr-frontend/src/shared/config.ts` — confirmed IConfig interface shape, three environment configs, hostname switch pattern
- Direct code read: `vdr-frontend/src/services/apiClients.ts` — confirmed `ingestionApi` pattern, interceptor array, `get()` helper signature
- Direct code read: `vdr-frontend/src/services/sharepoint.ts` — confirmed store-dispatch pattern in service functions
- Direct code read: `vdr-frontend/src/component/scope/scopeSidebar/ScopeSidebar.tsx` — confirmed `defaultScopes` array (lines 22–47), Redux selector, structure
- Direct code read: `vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx` — confirmed column render targets, polling point, `projectId` selector
- Direct code read: `vdr-agent/app/core/routers/topics.py` — confirmed `GET /topics` query param is `project_id`, returns `List[TopicResponse]`
- Direct code read: `vdr-agent/app/core/routers/documents.py` — confirmed `GET /documents` param is `project_id`, 404 on empty; `GET /{id}/fitment` returns `List[FitmentItem]`
- Direct code read: `vdr-agent/app/models/document.py` — confirmed field names: `summary_status`, `fitment_done_count`, `fitment_total_count`, `reasoning`
- Direct code read: `vdr-agent/main.py` — confirmed `root_path="/vdr-agent"`, port not set here (set in docker-compose/env); confirmed from CONTEXT.md port 8004
- Direct code read: `vdr-frontend/package.json` — confirmed React 19.2.0, TypeScript 5.9.3, Ant Design 6.1.3, Axios 1.13.2
- Direct code read: `vdr-frontend/tsconfig.app.json` — confirmed `strict: true`, `noUnusedLocals: true`, `noUnusedParameters: true`
- Direct code read: `vdr-frontend/src/store/store.ts` — confirmed redux-persist whitelist, scope slice registration

### Secondary (MEDIUM confidence)
- STATE.md decision log: `IProjectDocument.id === ai_rag.documents.id UUID` — this is the cross-API join key for document matching

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified from package.json; no new libraries needed
- Architecture: HIGH — all patterns verified from direct source code reads; exact line numbers identified
- API response shapes: HIGH — read directly from vdr-agent Pydantic model source (`document.py`, `topic.py`)
- Pitfalls: HIGH — derived from actual code structure (strict TS config, 404 on empty from router source, polling memory leak from React docs pattern)

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable stack — React, RTK, Axios, Ant Design versions unlikely to change in 30 days)
