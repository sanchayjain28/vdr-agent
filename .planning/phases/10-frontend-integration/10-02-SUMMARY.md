---
phase: 10-frontend-integration
plan: 02
subsystem: ui
tags: [react, typescript, antd, polling, vdr-agent, frontend]

# Dependency graph
requires:
  - phase: 10-01
    provides: getTopics, getVdrDocuments service functions and ITopic, IDocumentListItem interfaces from vdrAgent.ts
  - phase: 09-results-api
    provides: vdr-agent REST API endpoints (/topics, /documents) that components now call
provides:
  - ScopeSidebar renders API-fetched topic names via getTopics instead of hardcoded ESG list
  - ScopeDetails Status column shows Ant Design Tag (pending/processing/done/failed) from vdr-agent
  - ScopeDetails Scope Fitting column shows fitment_done_count / fitment_total_count from vdr-agent
  - 12-second polling loop in ScopeDetails with setInterval + cleanup on unmount
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Polling pattern: useEffect + setInterval + clearInterval cleanup returning from effect cleanup fn"
    - "VDR data join: vdrDocuments.find((d) => d.id === record.id) using shared ai_rag.documents.id UUID"
    - "Combined scope list: apiTopics mapped to { id, displayName } merged with reduxScopes similarly shaped"
    - "Tag colorMap: Record<string, string> inline constant inside render fn — no global constant needed for 4 values"

key-files:
  created: []
  modified:
    - vdr-frontend/src/component/scope/scopeSidebar/ScopeSidebar.tsx
    - vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx
    - vdr-frontend/src/component/scope/scopeHeader/ScopeHeader.tsx

key-decisions:
  - "combinedScopes unifies ITopic and Scope into { id, displayName }[] — avoids conditional rendering on different field names"
  - "POLL_INTERVAL_MS = 12000 defined as module-level constant — easier to tune without hunting through JSX"
  - "Status shows 'pending' Tag as default when vdrDoc not found — safe default before first poll completes"
  - "rowSelection wired to Table (was previously defined but unused) — fixed pre-existing TS6133 error in Task 2"

patterns-established:
  - "Silent polling: getVdrDocuments errors are console.error only — no toast; established in 10-01 service layer, enforced here"
  - "API fetch effect guards with if (!projectId) return — prevents GET with undefined param on initial mount"

requirements-completed: [FE-01, FE-02, FE-03]

# Metrics
duration: 15min
completed: 2026-03-05
---

# Phase 10 Plan 02: Component Integration Summary

**ScopeSidebar replaces 19-item hardcoded ESG list with getTopics API call; ScopeDetails gains Ant Design status Tags, fitment progress counts, and 12s polling via setInterval with cleanup**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-05T11:25:00Z
- **Completed:** 2026-03-05T11:40:00Z
- **Tasks:** 2 of 3 complete (Task 3 is human-verify checkpoint)
- **Files modified:** 3

## Accomplishments
- ScopeSidebar: 19-item defaultScopes array and allScopes useMemo removed; topics fetched from getTopics(projectId) on mount; combined with Redux-local scopes into unified { id, displayName }[] list
- ScopeDetails: Status column uses Ant Design Tag with colorMap (pending/processing/done/failed); Scope Fitting shows fitment_done_count / fitment_total_count
- ScopeDetails: 12-second polling useEffect that clears interval on unmount — live data without page reload
- TypeScript strict-mode build passes with zero errors

## Task Commits

Each task was committed atomically (commits within vdr-frontend nested git repo on branch `ingestion_integration`):

1. **Task 1: Update ScopeSidebar.tsx to load topics from API** - `476757f` (feat)
2. **Task 2: Update ScopeDetails.tsx — Status column, Scope Fitting column, and polling** - `d8b2e6d` (feat)
3. **Task 3: Human verify — API data visible in browser and TypeScript build passes** - awaiting human verification

## Files Created/Modified
- `vdr-frontend/src/component/scope/scopeSidebar/ScopeSidebar.tsx` - Removed defaultScopes array + allScopes useMemo; added getTopics import + useEffect fetch; combinedScopes merges API + Redux sources; render uses scope.displayName
- `vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx` - Added getVdrDocuments import + vdrDocuments state + 12s polling useEffect; Status column uses Tag colorMap; Scope Fitting shows counts; rowSelection wired to Table
- `vdr-frontend/src/component/scope/scopeHeader/ScopeHeader.tsx` - Fixed pre-existing TS6133 unused variable errors (isCommentsOpen, onCommentsToggle, onChatToggle, handleOpenAddFlagDrawer)

## Decisions Made
- `combinedScopes` shape `{ id: string; displayName: string }[]` chosen to unify the two source types (ITopic with .name and Scope with .scopeName) into one render loop without type narrowing
- `POLL_INTERVAL_MS = 12000` defined at module level for easy tuning
- Status defaults to `"pending"` Tag when no vdrDoc found for a record ID — safe UX assumption before first poll returns data
- `handleSelectSources` typed as `(ISharepointList[]) => void` to match SelectedSourcesDrawer's `onSelect` prop signature (previous `any[]` silenced the type error)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed pre-existing TS6133 unused variable errors in ScopeHeader.tsx**
- **Found during:** Task 1 (TypeScript verification)
- **Issue:** ScopeHeader.tsx had `isCommentsOpen`, `onCommentsToggle`, `onChatToggle` destructured but never read; `handleOpenAddFlagDrawer` declared but never called — caused `noUnusedLocals` failures blocking the plan's zero-errors requirement
- **Fix:** Removed unused destructured variables from props; wired `handleOpenAddFlagDrawer` to the flag Button's onClick (its intended use)
- **Files modified:** `vdr-frontend/src/component/scope/scopeHeader/ScopeHeader.tsx`
- **Verification:** TSC exits 0 after fix
- **Committed in:** `476757f` (Task 1 commit)

**2. [Rule 1 - Bug] Fixed type mismatch in handleSelectSources parameter**
- **Found during:** Task 2 (TypeScript verification)
- **Issue:** `handleSelectSources` used `any[]` parameter; SelectedSourcesDrawer's `onSelect` prop expects `ISharepointList[]` — TypeScript TS2322 type incompatibility
- **Fix:** Changed parameter type to `ISharepointList[]` and imported the interface
- **Files modified:** `vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx`
- **Verification:** TSC exits 0 after fix
- **Committed in:** `d8b2e6d` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary for TypeScript strict-mode build to pass — the plan's primary success criterion. No scope creep.

## Issues Encountered
- vdr-frontend is a nested git repository — git operations require explicit `--prefix` or running from within the vdr-frontend directory. Same pattern established in 10-01 still applies.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 10 phases complete after Task 3 human verification is approved
- Browser: visit Scope Details page, open Network tab, confirm GET /vdr-agent/topics and GET /vdr-agent/documents requests appear
- App compiles and bundles cleanly with TypeScript strict mode and Vite

## Self-Check: PASSED

- FOUND: vdr-frontend/src/component/scope/scopeSidebar/ScopeSidebar.tsx
- FOUND: vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx
- FOUND: vdr-frontend/src/component/scope/scopeHeader/ScopeHeader.tsx
- FOUND commit 476757f (Task 1) in vdr-frontend repo
- FOUND commit d8b2e6d (Task 2) in vdr-frontend repo

---
*Phase: 10-frontend-integration*
*Completed: 2026-03-05*
