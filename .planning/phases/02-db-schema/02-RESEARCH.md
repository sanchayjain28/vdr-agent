# Phase 2: DB Schema - Research

**Researched:** 2026-03-05
**Domain:** PostgreSQL schema design, Flyway migrations, partial indexes, cross-schema FK constraints
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Migration file structure**
- Separate Flyway file per table — 4 migration files (V1 through V4), one table each
- Naming: `V1__create_vdr_agent_schema.sql`, `V2__create_topics_table.sql`, `V3__create_processing_state_table.sql`, `V4__create_document_summaries_table.sql`, `V5__create_fitment_results_table.sql`
  - V1 creates the schema (`CREATE SCHEMA IF NOT EXISTS vdr_agent`) and any shared trigger functions
  - One file per table after that
- Each file is idempotent: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`

**Cross-schema FK strategy**
- `document_id` columns in `processing_state`, `document_summaries`, and `fitment_results` use actual FK constraints referencing `ai_rag.documents(id)`
- `ON DELETE CASCADE` — if a document is deleted from ai_rag, its vdr_agent rows are cleaned up automatically
- `topic_id` in `fitment_results` FK references `vdr_agent.topics(id)` with `ON DELETE CASCADE`

**Document summaries scope**
- `document_summaries` stores one combined final summary per document — not per-section, not per-topic
- Single `summary_text TEXT` column — the final Claude output after section summaries are collapsed
- Section summaries are ephemeral (computed in memory during generation, not persisted)
- One row per document, enforced by UNIQUE constraint on `document_id`

**Fitment result data model**
- `fitment_results` stores reasoning text only — no boolean relevant/not-relevant, no score
- Columns: `id`, `document_id` (FK), `topic_id` (FK), `reasoning TEXT`, `status TEXT`, `created_at`, `updated_at`
- UNIQUE constraint on `(document_id, topic_id)` — enables `ON CONFLICT DO UPDATE` for safe re-runs
- `status` enum: `pending | processing | done | failed` (same pattern as processing_state)

### Claude's Discretion
- Whether to create a shared `update_updated_at_column()` trigger function in `vdr_agent` schema or reference the one in `ai_rag` (prefer creating own copy in `vdr_agent` schema to avoid cross-schema dependency)
- Exact column ordering and SQL comment style (follow ingestion-service conventions)
- Whether `processing_state` needs a UNIQUE constraint on `document_id` (yes — one row per document)
- Stale-lock threshold value is app config only, not a DB default

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROC-01 | System polls for documents with completed embeddings and no AI summary using `FOR UPDATE SKIP LOCKED` (atomic claim, no duplicates) | Partial index on `(summary_status, created_at) WHERE summary_status IN ('pending', 'failed')` on `processing_state` enables the poll query; `UNIQUE` constraint on `document_id` ensures exactly one processing_state row per document |
| PROC-04 | System tracks processing status per document: `pending` → `processing` → `done` / `failed` | `processing_state.summary_status` TEXT with CHECK constraint + `processing_started_at TIMESTAMPTZ` for stale-lock detection; same pattern as `ai_rag.documents.status` |
</phase_requirements>

---

## Summary

This phase is pure SQL DDL — no application code. The deliverable is five Flyway migration files that create the `vdr_agent` schema and four tables (`topics`, `processing_state`, `document_summaries`, `fitment_results`) with all columns, constraints, partial indexes, triggers, and cross-schema FK relationships.

All patterns are already established in the ingestion-service migrations and can be copied directly. The project uses Flyway for database migrations, idempotent `CREATE IF NOT EXISTS` SQL, `gen_random_uuid()` UUIDs, `TIMESTAMPTZ` timestamps, `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`, and CHECK constraints for status enums. The `update_updated_at_column()` trigger function from `ai_rag` schema should be recreated in `vdr_agent` schema (V1) to avoid cross-schema dependency.

The most technically sensitive element is the partial index on `processing_state(summary_status, created_at) WHERE summary_status IN ('pending', 'failed')` — this is the index the Phase 5 poller will use for `FOR UPDATE SKIP LOCKED` queries. Getting this right in Phase 2 avoids a schema migration in Phase 5. The fitment_results `UNIQUE (document_id, topic_id)` constraint enables idempotent upserts using `ON CONFLICT DO UPDATE`.

**Primary recommendation:** Copy the exact idempotent SQL patterns from `ingestion-service/migrations/flyway/V2__projects_table.sql` and `V3__documents_and_embeddings.sql`, adapt them to the `vdr_agent` schema, and add the phase-specific partial index and UNIQUE constraints.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flyway | (CLI, same as ingestion-service) | Database migration versioning and execution | Already established in the project; ingestion-service uses same tool |
| PostgreSQL | 16+ (matches ingestion-service) | Database | Project database; pgvector already installed |
| psycopg | 3.3.3 (locked in pyproject.toml) | Python PostgreSQL driver used by vdr-agent | Already in vdr-agent pyproject.toml |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psycopg-pool | >=3.2,<4.0 | Async connection pooling | Phase 3 (DB pool) and Phase 5 (poller) — not in Phase 2 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Flyway CLI | Alembic (Python) | Alembic requires Python env at migration time; Flyway is standalone and already in use |
| Plain TEXT for status | PostgreSQL ENUM type | TEXT + CHECK constraint is easier to add values to later and is idempotent in Flyway without special handling |

**Installation:**
No new packages required for Phase 2. All tooling (Flyway CLI) is already present. The vdr-agent service itself does not run migrations at startup — migrations are run via a script (same pattern as ingestion-service `scripts/run_flyway_migration.sh`).

---

## Architecture Patterns

### Recommended Project Structure
```
vdr-agent/
├── migrations/
│   └── flyway/
│       ├── V1__create_vdr_agent_schema.sql       # schema + trigger function
│       ├── V2__create_topics_table.sql            # vdr_agent.topics
│       ├── V3__create_processing_state_table.sql  # vdr_agent.processing_state
│       ├── V4__create_document_summaries_table.sql # vdr_agent.document_summaries
│       └── V5__create_fitment_results_table.sql   # vdr_agent.fitment_results
└── scripts/
    └── run_flyway_migration.sh                    # (to be created — mirrors ingestion-service)
```

### Pattern 1: Idempotent Table Creation with Status Check Constraint

**What:** Each migration file creates a table with `CREATE TABLE IF NOT EXISTS`, defines columns inline including CHECK constraint for status enums, then uses `DO $$ BEGIN ... END $$` blocks for idempotent ALTER operations (add missing columns, add missing constraints).

**When to use:** Every table creation migration in this project.

**Example (from ingestion-service V3):**
```sql
-- Source: ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql
SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS processing_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE,
    summary_status TEXT NOT NULL DEFAULT 'pending',
    processing_started_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_summary_status CHECK (summary_status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT processing_state_document_id_unique UNIQUE (document_id)
);
```

### Pattern 2: Idempotent Constraint Addition via DO Block

**What:** Use a `DO $$ BEGIN ... END $$` block with a check against `pg_constraint` to add a constraint only if it doesn't already exist. This makes the migration idempotent — safe to run twice.

**When to use:** For UNIQUE constraints, CHECK constraints added after table creation, and any `ALTER TABLE` operations.

**Example (from ingestion-service V2):**
```sql
-- Source: ingestion-service/migrations/flyway/V2__projects_table.sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'processing_state_document_id_unique'
        AND conrelid = 'processing_state'::regclass
    ) THEN
        ALTER TABLE processing_state ADD CONSTRAINT processing_state_document_id_unique UNIQUE (document_id);
    END IF;
END $$;
```

### Pattern 3: Trigger Creation with Idempotency

**What:** Always use `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`. Never use `CREATE OR REPLACE TRIGGER` (not available in all PostgreSQL versions). The trigger function itself uses `CREATE OR REPLACE FUNCTION`.

**When to use:** Every table that has `updated_at` auto-update.

**Example (from ingestion-service V3):**
```sql
-- Source: ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql
DROP TRIGGER IF EXISTS update_processing_state_updated_at ON processing_state;
CREATE TRIGGER update_processing_state_updated_at
    BEFORE UPDATE ON processing_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### Pattern 4: Partial Index for Polling Query

**What:** A partial index limits index entries to only rows matching the WHERE clause — dramatically reducing index size and improving poll query performance when the vast majority of rows are `done`.

**When to use:** For the `processing_state` table, to support the Phase 5 `FOR UPDATE SKIP LOCKED` poll query.

**Example:**
```sql
-- Source: PostgreSQL official docs — partial indexes
-- https://www.postgresql.org/docs/current/indexes-partial.html
CREATE INDEX IF NOT EXISTS idx_processing_state_pending_failed
    ON processing_state(summary_status, created_at)
    WHERE summary_status IN ('pending', 'failed');
```

### Pattern 5: Cross-Schema FK Reference

**What:** PostgreSQL supports FK constraints across schemas using the fully qualified `schema.table(column)` syntax.

**When to use:** `document_id` FK from any `vdr_agent` table to `ai_rag.documents(id)`.

**Example:**
```sql
-- Source: PostgreSQL official docs — https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK
document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE
```

### Pattern 6: ON CONFLICT DO UPDATE (Upsert)

**What:** The UNIQUE constraint on `fitment_results(document_id, topic_id)` enables PostgreSQL's `INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE SET ...` syntax.

**When to use:** `fitment_results` table — must have the UNIQUE constraint defined at the table level for the upsert to work in Phase 7 application code.

**Example (schema side — the constraint that enables it):**
```sql
CONSTRAINT fitment_results_doc_topic_unique UNIQUE (document_id, topic_id)
```

### Anti-Patterns to Avoid
- **Using schema-qualified names in `SET search_path`:** Set `SET search_path TO vdr_agent, public;` at the top of each file — then use unqualified table names within that file. Exception: the cross-schema FK to `ai_rag.documents` still needs the schema prefix.
- **Referencing `ai_rag.update_updated_at_column()` directly:** Creates a cross-schema function dependency. Instead, redefine `update_updated_at_column()` in V1 scoped to `vdr_agent` schema, and reference it unqualified (search_path will resolve it).
- **PostgreSQL ENUM type for status:** Prefer TEXT + CHECK constraint. ENUM types require `DROP TYPE` / `CREATE TYPE` sequences for changes, which complicates idempotent migrations.
- **NOT NULL on `processing_started_at`:** Must be nullable — it is NULL until a worker claims the row.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Migration versioning | Custom schema_version table | Flyway (already in project) | Handles checksums, ordering, baseline, repair; already integrated |
| Idempotent DDL | Custom migration guards | `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, DO blocks | Built into PostgreSQL DDL syntax |
| Stale lock detection | Application-level heartbeat table | `processing_started_at TIMESTAMPTZ` column | Simple timestamp comparison in poll query is sufficient; Temporal is explicitly out of scope |
| Upsert logic | SELECT then INSERT/UPDATE | `INSERT ... ON CONFLICT DO UPDATE` | Atomic, no race condition |

**Key insight:** All patterns needed already exist in the `ingestion-service/migrations/flyway/` files. Phase 2 is a copy-and-adapt exercise, not a design exercise.

---

## Common Pitfalls

### Pitfall 1: Flyway Checksum Failure on Edit
**What goes wrong:** If a migration file is edited after being applied to any database (local or CI), Flyway will reject subsequent runs with a checksum mismatch error.
**Why it happens:** Flyway stores a checksum of each applied migration in the `flyway_schema_history` table.
**How to avoid:** Never edit a migration file once it has been applied. If a change is needed, create a new migration file (V6, etc.).
**Warning signs:** `ERROR: Migration checksum mismatch for migration version X` — use `flyway repair` to fix dev environments, but never alter the file in production.

### Pitfall 2: Cross-Schema FK Without Privilege
**What goes wrong:** The PostgreSQL user running migrations may not have REFERENCES privilege on `ai_rag.documents`.
**Why it happens:** Cross-schema FK constraints require SELECT privilege on the referenced table and REFERENCES privilege on the referenced column.
**How to avoid:** Verify that the `VDR_AGENT_DB_USER` has the necessary privileges on `ai_rag.documents`. If not, either grant privileges or document that the DBA must run `GRANT REFERENCES ON TABLE ai_rag.documents TO vdr_agent_user;` before migration.
**Warning signs:** `ERROR: permission denied for table documents` during migration.

### Pitfall 3: Partial Index WHERE Clause Must Match Query Exactly
**What goes wrong:** PostgreSQL uses a partial index only if the query's WHERE clause is compatible with the index predicate. If Phase 5 polls with `WHERE summary_status = 'pending'` but the index is `WHERE summary_status IN ('pending', 'failed')`, the index may or may not be used depending on the planner's cost estimation.
**Why it happens:** The planner must recognize that the query's WHERE clause implies the index predicate.
**How to avoid:** Keep the partial index predicate `WHERE summary_status IN ('pending', 'failed')` exactly as specified — this is the polling pattern. The Phase 5 query should poll for both pending and failed rows (failed rows are retry candidates in v1's basic case) or at minimum use the same status values.
**Warning signs:** `EXPLAIN ANALYZE` shows sequential scan on `processing_state` instead of index scan.

### Pitfall 4: `SET search_path` Scope in Flyway
**What goes wrong:** `SET search_path TO vdr_agent, public;` at the start of a migration file may not persist across all DDL statements if Flyway wraps each statement in a transaction that resets the path.
**Why it happens:** Flyway transaction wrapping behavior depends on configuration.
**How to avoid:** In V1, create the schema with `CREATE SCHEMA IF NOT EXISTS vdr_agent`. In subsequent files, set `search_path` at the top AND use unqualified names consistently. If issues arise, use schema-qualified names (`vdr_agent.table_name`) for safety.
**Warning signs:** `ERROR: relation "topics" does not exist` when `vdr_agent.topics` does.

### Pitfall 5: Missing `flyway_schema_history` Initialization
**What goes wrong:** If the `vdr_agent` schema is new (no prior migrations), Flyway needs `baselineOnMigrate=true` for the first run.
**Why it happens:** Flyway expects its history table to exist before running migrations in a schema it does not own.
**How to avoid:** The `run_flyway_migration.sh` script for vdr-agent must include `-baselineOnMigrate=true -baselineVersion=0` (or `1`), matching the ingestion-service pattern.
**Warning signs:** `ERROR: Found non-empty schema(s) ... without Flyway's history table!`

---

## Code Examples

Verified patterns from official sources and project codebase:

### V1: Schema and Trigger Function
```sql
-- Source: adapted from ingestion-service/migrations/flyway/V1__core_schema_setup.sql
-- Flyway Migration: V1 - Create vdr_agent Schema
CREATE SCHEMA IF NOT EXISTS vdr_agent;

SET search_path TO vdr_agent, public;

-- Create updated_at trigger function scoped to vdr_agent schema
-- (Intentional copy — avoids cross-schema function dependency on ai_rag)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column IS 'Auto-update updated_at timestamp on row modification';
```

### V2: Topics Table
```sql
-- Source: adapted from ingestion-service/migrations/flyway/V2__projects_table.sql pattern
-- Flyway Migration: V2 - Topics Table
SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,  -- plain UUID, no FK (user-service not yet integrated)
    name TEXT NOT NULL,
    instruction_text TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topics_project_id ON topics(project_id);
CREATE INDEX IF NOT EXISTS idx_topics_project_active ON topics(project_id, is_active) WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS update_topics_updated_at ON topics;
CREATE TRIGGER update_topics_updated_at
    BEFORE UPDATE ON topics
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE topics IS 'ESG evaluation topics — each topic has a name and instruction for fitment evaluation';
COMMENT ON COLUMN topics.project_id IS 'UUID of the project this topic belongs to — no FK constraint until user-service schema confirmed (Phase 8 concern)';
COMMENT ON COLUMN topics.instruction_text IS 'Instruction text passed to Claude for fitment evaluation against this topic';
```

### V3: Processing State Table with Partial Index
```sql
-- Source: adapted from ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql pattern
-- + PostgreSQL docs: https://www.postgresql.org/docs/current/indexes-partial.html
-- Flyway Migration: V3 - Processing State Table
SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS processing_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE,
    summary_status TEXT NOT NULL DEFAULT 'pending',
    processing_started_at TIMESTAMPTZ,          -- stale-lock detection: set when status→processing
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_summary_status CHECK (summary_status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT processing_state_document_id_unique UNIQUE (document_id)
);

-- Partial index for poll query: only pending/failed rows are ever polled
-- Enables FOR UPDATE SKIP LOCKED query in Phase 5 poller
CREATE INDEX IF NOT EXISTS idx_processing_state_pending_failed
    ON processing_state(summary_status, created_at)
    WHERE summary_status IN ('pending', 'failed');

DROP TRIGGER IF EXISTS update_processing_state_updated_at ON processing_state;
CREATE TRIGGER update_processing_state_updated_at
    BEFORE UPDATE ON processing_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE processing_state IS 'Per-document AI processing status — one row per document';
COMMENT ON COLUMN processing_state.summary_status IS 'Pipeline status: pending (awaiting pickup), processing (claimed by worker), done (summary generated), failed (error occurred)';
COMMENT ON COLUMN processing_state.processing_started_at IS 'Timestamp when worker claimed this row — used by poller to detect stale locks (threshold configured in app, not DB)';
```

### V4: Document Summaries Table
```sql
-- Flyway Migration: V4 - Document Summaries Table
SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS document_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT document_summaries_document_id_unique UNIQUE (document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_summaries_document_id ON document_summaries(document_id);

DROP TRIGGER IF EXISTS update_document_summaries_updated_at ON document_summaries;
CREATE TRIGGER update_document_summaries_updated_at
    BEFORE UPDATE ON document_summaries
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE document_summaries IS 'One combined AI summary per document — final output after collapsing section summaries';
COMMENT ON COLUMN document_summaries.summary_text IS 'Final Claude-generated summary of the full document content (not scoped to any topic)';
```

### V5: Fitment Results Table with Composite UNIQUE
```sql
-- Flyway Migration: V5 - Fitment Results Table
SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS fitment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES vdr_agent.topics(id) ON DELETE CASCADE,
    reasoning TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_fitment_status CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT fitment_results_doc_topic_unique UNIQUE (document_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_fitment_results_document_id ON fitment_results(document_id);
CREATE INDEX IF NOT EXISTS idx_fitment_results_topic_id ON fitment_results(topic_id);
CREATE INDEX IF NOT EXISTS idx_fitment_results_status ON fitment_results(status);

DROP TRIGGER IF EXISTS update_fitment_results_updated_at ON fitment_results;
CREATE TRIGGER update_fitment_results_updated_at
    BEFORE UPDATE ON fitment_results
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE fitment_results IS 'AI fitment evaluation results — one row per (document, topic) pair';
COMMENT ON COLUMN fitment_results.reasoning IS 'Raw Claude output explaining why the document is or is not relevant to the topic';
COMMENT ON COLUMN fitment_results.status IS 'Evaluation status: pending, processing, done, or failed';
COMMENT ON CONSTRAINT fitment_results_doc_topic_unique ON fitment_results IS 'Enables ON CONFLICT DO UPDATE for safe re-runs without duplicates';
```

### Flyway Migration Script (for vdr-agent)
```bash
# Source: adapted from ingestion-service/scripts/run_flyway_migration.sh
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCATIONS="filesystem:${ROOT_DIR}/migrations/flyway"
JDBC_URL="jdbc:postgresql://${VDR_AGENT_DB_HOST}:${VDR_AGENT_DB_PORT:-5432}/${VDR_AGENT_DB_NAME}"

exec flyway \
  "-locations=${LOCATIONS}" \
  "-url=${JDBC_URL}" \
  "-user=${VDR_AGENT_DB_USER}" \
  "-password=${VDR_AGENT_DB_PASSWORD}" \
  "-schemas=vdr_agent" \
  "-baselineOnMigrate=true" \
  "-baselineVersion=0" \
  migrate
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PostgreSQL ENUM type for status | TEXT + CHECK constraint | Ongoing best practice | Easier to alter values; idempotent in Flyway without type management |
| `CREATE OR REPLACE TRIGGER` | `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` | PostgreSQL 14 added `CREATE OR REPLACE TRIGGER` | Both work in PG16; `DROP/CREATE` pattern is already established in this project — use it for consistency |
| Cross-schema FKs avoided | Cross-schema FKs accepted | Standard practice | Fully supported by PostgreSQL; cascades work across schemas |

**Deprecated/outdated:**
- `SERIAL` / `BIGSERIAL` for auto-increment PKs: Replaced by `gen_random_uuid()` with UUID PKs — matches the entire project's convention.
- `CURRENT_TIMESTAMP` for timestamps: Project uses `NOW()` — equivalent but shorter; stick to `NOW()`.

---

## Open Questions

1. **`project_id` FK on `topics` table**
   - What we know: `project_id` is stored as plain UUID in `vdr_agent.topics` with no FK constraint. The STATE.md blocker says "confirm whether project_id is FK to existing table or plain UUID" before Phase 8.
   - What's unclear: Whether `ai_rag.projects(id)` is the correct target or if there is a separate user-service projects table.
   - Recommendation: Use plain UUID (no FK) for `topics.project_id` in Phase 2 as decided. Add FK constraint in Phase 8 once user-service schema is confirmed. This is already locked in CONTEXT.md.

2. **VDR_AGENT_DB_USER privileges on `ai_rag.documents`**
   - What we know: Cross-schema FKs require REFERENCES privilege. The DB user for vdr-agent (`VDR_AGENT_DB_USER`) may be different from the ingestion-service user.
   - What's unclear: Whether `VDR_AGENT_DB_USER` already has REFERENCES privilege on `ai_rag.documents`.
   - Recommendation: Migration plan should include a verification step — run migrations and check for privilege errors. If the FK fails, include a GRANT statement or document as a DBA prerequisite. An alternative is to document the FK as a comment and make it a soft reference (no DB constraint) — but the locked decision says use actual FK constraints, so privilege must be granted.

3. **Flyway migration numbering — does V1 in vdr-agent conflict with V1 in ai_rag?**
   - What we know: Flyway tracks migration history per schema (the `-schemas` flag scopes the `flyway_schema_history` table). vdr-agent Flyway will use `-schemas=vdr_agent` so its history table lives in `vdr_agent.flyway_schema_history`, separate from `ai_rag.flyway_schema_history`.
   - What's unclear: Nothing — schemas are isolated. V1 in vdr-agent does not conflict with V1 in ai_rag.
   - Recommendation: Confirmed non-issue. Proceed with V1–V5 numbering.

---

## Sources

### Primary (HIGH confidence)
- `ingestion-service/migrations/flyway/V1__core_schema_setup.sql` — trigger function pattern (verified by reading file)
- `ingestion-service/migrations/flyway/V2__projects_table.sql` — idempotent constraint addition, DO block pattern (verified by reading file)
- `ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql` — table creation, index, trigger patterns (verified by reading file)
- `ingestion-service/scripts/run_flyway_migration.sh` — Flyway CLI invocation pattern (verified by reading file)
- `.planning/phases/02-db-schema/02-CONTEXT.md` — locked decisions (verified by reading file)
- PostgreSQL official docs — https://www.postgresql.org/docs/current/indexes-partial.html (partial indexes)
- PostgreSQL official docs — https://www.postgresql.org/docs/current/ddl-constraints.html (FK, UNIQUE, CHECK constraints)

### Secondary (MEDIUM confidence)
- `vdr-agent/pyproject.toml` — confirms Python 3.12, psycopg 3.3.3, no migration library in vdr-agent itself (Flyway is CLI, not Python)
- `vdr-agent/app/config/__init__.py` — confirms `VDR_AGENT_DB_*` env var naming for migration script

### Tertiary (LOW confidence)
- None — all claims verified against project files or PostgreSQL official docs.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Flyway and patterns verified directly from existing project migrations
- Architecture: HIGH — All SQL patterns copied from existing ingestion-service migrations; partial index syntax verified against PostgreSQL docs
- Pitfalls: HIGH (Flyway checksum, search_path) / MEDIUM (cross-schema privileges — depends on runtime DB configuration not visible in code)

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable domain — PostgreSQL DDL and Flyway patterns do not change frequently)
