# Coding Conventions

**Analysis Date:** 2026-03-05

## Naming Patterns

**Files:**
- **React Components:** PascalCase with `.tsx` extension (`ProjectCard.tsx`, `DeleteModal.tsx`, `ChatHistory.tsx`)
- **Non-component TypeScript:** camelCase with `.ts` extension (`projects.ts`, `knowledgeAIChat.ts`, `useChat.ts`)
- **Python modules:** snake_case with `.py` extension (`document_dao.py`, `rate_limiter.py`, `vision_processor.py`)
- **Test files:** `test_*.py` (unit tests) in `tests/unit/` directory. Example: `test_excel_duplicate_columns.py`, `test_unsync_activities.py`

**Functions:**
- **TypeScript/JavaScript:** camelCase (`getProjectList`, `formatMathToLatexNew`, `handleSelectProject`, `createProject`)
- **Python:** snake_case (`_normalize_path_for_matching`, `_deduplicate_headers`, `_ensure_async_primitives`)
- **Private functions:** Prefix with underscore in both languages (`_safe_params`, `_shorten_sql`, `_sanitize_name`)

**Variables:**
- **TypeScript:** camelCase for all locals and module-level constants that are reassignable (`isDeleteModalVisible`, `knowledgeFileProjectId`, `currentStatus`)
- **Python:** snake_case for all locals (`conn`, `cursor`, `result`, `param_list`)
- **Constants:** UPPER_SNAKE_CASE in both languages (`MAX_TITLE_CHARS`, `MAX_DESCRIPTION_CHARS`, `PAGE_SIZE`)

**Types & Interfaces:**
- **TypeScript interfaces:** Prefix with `I` (`IProject`, `IProjectCreateRequest`, `IAuthSlice`, `IUserInfo`, `IProjectCardProps`)
- **Python enums:** PascalCase (`DocumentStatus`, `PayloadAction`)
- **Python Pydantic models:** PascalCase (`DocumentCreate`, `DocumentResponse`, `SharePointDocumentCreate`, `ClaudeClientError`)

## Code Style

**Formatting:**
- **Tool:** Prettier (TypeScript) and Black (Python)
- **TypeScript print width:** 100 characters (`.prettierrc`)
- **JSX bracket same line:** true (`jsxBracketSameLine: true` in `.prettierrc`)
- **Python:** Black default (88-character line length)

**Linting:**
- **TypeScript:** ESLint with config at `frontend/eslint.config.js` and `vdr-frontend/eslint.config.js`
- **ESLint extends:** `@eslint/js`, `typescript-eslint`, `react-hooks`, `react-refresh`
- **Python:** Ruff linter, MyPy for type checking
- **Run commands:**
  ```bash
  npm run lint              # Frontend linting
  ruff check app/           # Python linting
  mypy app/                 # Python type checking
  ```

## Import Organization

**Order (TypeScript):**
1. External third-party libraries (`react`, `antd`, `axios`)
2. Redux/store imports (`@reduxjs/toolkit`, `react-redux`)
3. Custom service imports (`../services`)
4. Type imports (`import type { ... }`)
5. Local component/shared imports (`./ProjectCard.scss`)

**Example from `ProjectCard.tsx`:**
```typescript
import { LoadingOutlined } from "@ant-design/icons";
import { Button, Card, Dropdown, Space, Tooltip, Typography, type MenuProps } from "antd";
import type React from "react";
import { useState } from "react";
import { useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import { PATHS, isAdminUser } from "../../../shared";
import type { RootState } from "../../../store";
import type { IProject } from "../../../store/project/project.interface";
import Collaborators from "../../Collaborators/Collaborators";
import DeleteModal from "../../deleteModal/DeleteModal";
import "./ProjectCard.scss";
```

**Order (Python):**
1. Standard library imports
2. Third-party imports
3. Relative imports from the same package
4. Logging setup

**Example from `base.py`:**
```python
from __future__ import annotations
import logging
from typing import Any, Iterable, Optional
import psycopg
from app.db.exceptions import DatabaseConnectionError
from app.db.clients import PostgresClient

LOGGER = logging.getLogger(__name__)
```

**Path Aliases:**
- TypeScript: None explicitly configured; uses relative paths (`../shared`, `../../../store`)
- Python: Absolute imports from package root (`from app.db.exceptions import`, `from app.core.llm`)

## Error Handling

**Patterns:**

**TypeScript:**
- Toast notifications for user-facing errors via `react-toastify`
- Try-catch with generic error handler that dispatches to Redux state
- Example from `projects.ts`:
  ```typescript
  try {
    store.dispatch(setIsLoadingProjectList(true));
    const res = await get(ingestionApi, `projects`, { params: {...} });
    if (res && res?.projects) {
      store.dispatch(setProjectList(res?.projects));
    }
    return res;
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || "Failed to load Project List. Please try again");
    store.dispatch(setProjectList([]));
    return error;
  } finally {
    store.dispatch(setIsLoadingProjectList(false));
  }
  ```

**Python:**
- Custom exception hierarchy with base class `ClaudeClientError` in `app/core/llm/claude/exceptions.py`
- Specific exceptions: `APIConnectionError`, `RateLimitError`, `TimeoutError`, `InvalidRequestError`, `AuthenticationError`, `BatchProcessingError`
- Database operations wrap errors in `DatabaseConnectionError` or `QueryExecutionError` from `app/db/exceptions.py`
- Example from `base.py`:
  ```python
  try:
    cursor.execute(sql, params or ())
    result = None
    if fetchone:
      result = cursor.fetchone()
    elif fetchall:
      result = cursor.fetchall()
    conn.commit()
    return result
  except QueryExecutionError:
    conn.rollback()
    raise
  except psycopg.OperationalError as exc:
    conn.rollback()
    self.client.close()
    LOGGER.error("Database connection lost during query: %s", exc)
    raise DatabaseConnectionError("Database connection was lost.") from exc
  finally:
    cursor.close()
  ```

## Logging

**Framework:**
- **TypeScript:** `console` (no structured logging library detected)
- **Python:** Standard `logging` module with module-level logger
  ```python
  import logging
  LOGGER = logging.getLogger(__name__)
  LOGGER.error("message", exc_info=True)
  LOGGER.debug("message")
  ```

**Patterns:**
- **Python:** Always use `LOGGER` instance (not `logging.info()` directly)
- SQL logging: Truncate long queries to 200 chars for readability (`_shorten_sql()` in `base.py`)
- Parameter logging: Redact sensitive values, fallback to `"<unloggable_params>"` if unparseable (`_safe_params()` in `base.py`)
- Error context: Include relevant metadata (SQL statement, parameters, connection state)

## Comments

**When to Comment:**
- Python: Docstrings for all public functions and classes (Google-style or Sphinx format detected)
- TypeScript: Comments for complex logic, not obvious code
- React: Use `// ` for inline, JSDoc for exported functions
- Avoid commenting obvious code (e.g., `const name = "John"; // Set name`)

**Example from `client.py`:**
```python
"""
Main Claude API client implementation using AWS Bedrock.

This module provides a high-level, production-ready interface to Claude models via AWS Bedrock
with support for single completions, batch processing, streaming, and comprehensive
error handling.
"""
```

**JSDoc/TSDoc:**
- Used sparingly; most TypeScript functions lack formal documentation
- Interface definitions have inline comments
- Example from `ProjectCard.tsx`:
  ```typescript
  interface IProjectCardProps {
    index: number;
    project: IProject;
    handleLeaveProject: () => void;
  }
  ```

## Function Design

**Size:** Prefer functions under 50 lines; complex operations broken into smaller units
- Example: `getProjectList` is 39 lines; `updateProjectDetails` is 30 lines
- Long pipelines use activity-based decomposition in Python workflows

**Parameters:**
- **TypeScript:** Destructure objects where possible; avoid more than 3 positional parameters
  ```typescript
  export const getProjectList = async (
    page: number,
    limit: number = PAGE_SIZE.projects,
    searchText?: string,
  )
  ```
- **Python:** Similar; use keyword-only arguments with defaults where appropriate
  ```python
  def _execute(
    self,
    sql: str,
    params: Optional[Iterable[Any]] = None,
    *,
    fetchone: bool = False,
    fetchall: bool = False,
  )
  ```

**Return Values:**
- **TypeScript:** Return response object or error; caller handles with try-catch
- **Python:** Return result directly; raise exceptions for errors
- Avoid `null`/`None` for success states; use exceptions or explicit error types

## Module Design

**Exports:**
- **TypeScript barrel files:** Central `index.ts` files aggregate exports
  - Example: `frontend/src/components/index.ts` exports all components
  - Example: `frontend/src/shared/index.ts` exports helpers, hooks, types
- **Python:** No barrel file pattern; imports are explicit
  - Example: `from app.db.dao import BaseDAO` (imports from `__init__.py`)

**Barrel Files:**
- TypeScript: Present in `components/`, `pages/`, `shared/`, `layout/`, `routes/`, `store/`
- Pattern: `export * from './ComponentName'`
- Facilitates cleaner imports: `import { ProjectCard } from '../components'` instead of `import ProjectCard from '../components/ProjectCard/ProjectCard'`

## Redux Store Conventions

**Slice naming:** `{feature}Slice.ts` (e.g., `authSlice.ts`, `projectSlice.ts`)

**Action naming:** `set{PropertyName}` pattern (e.g., `setUserRole`, `setUserInfo`, `setIsLoadingProjectList`)

**Type naming:** `I{Feature}Slice`, `I{Feature}Interface` (e.g., `IAuthSlice`, `IProject`)

**Example from `authSlice.ts`:**
```typescript
export const authSlice = createSlice({
  name: "authSlice",
  initialState,
  extraReducers: (builder) => {
    builder.addCase(PURGE, (state) => {
      Object.assign(state, initialState);
    });
  },
  reducers: {
    setUserRole: (state, action: PayloadAction<string[]>) => {
      state.userRole = action.payload;
    },
    setUserInfo: (state, action: PayloadAction<IUserInfo | null>) => {
      state.userInfo = action.payload;
    },
  },
});

export const { setUserRole, setUserInfo } = authSlice.actions;
export default authSlice.reducer;
```

---

*Convention analysis: 2026-03-05*
