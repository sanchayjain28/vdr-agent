---
status: testing
phase: 09-results-api
source: [09-01-SUMMARY.md, 09-02-SUMMARY.md]
started: 2026-03-05T10:55:00Z
updated: 2026-03-05T10:55:00Z
---

## Current Test

number: 1
name: Document Summary Endpoint
expected: |
  GET /vdr-agent/documents/{document_id}/summary returns JSON with
  {"document_id": "...", "status": "pending|processing|done", "summary_text": "...or null"}.
  For a document that has been processed, status is "done" and summary_text contains text.
  For a document not yet processed, status is "pending" and summary_text is null.
awaiting: user response

## Tests

### 1. Document Summary Endpoint
expected: GET /vdr-agent/documents/{document_id}/summary returns JSON with {"document_id": "...", "status": "pending|processing|done", "summary_text": "...or null"}. For a processed doc, status="done" with text. For unprocessed, status="pending" with null summary_text.
result: [pending]

### 2. Summary Endpoint 404
expected: GET /vdr-agent/documents/nonexistent-id/summary returns HTTP 404 (not a 500 or empty response).
result: [pending]

### 3. Fitment Endpoint
expected: GET /vdr-agent/documents/{document_id}/fitment returns a JSON array — one object per active topic — each with {"topic_id": "...", "topic_name": "...", "status": "pending|done|failed", "reasoning": "...or null"}. Topics not yet evaluated show status="pending".
result: [pending]

### 4. Fitment Endpoint — Active Topics Only
expected: The fitment response only includes currently active topics (soft-deleted/inactive topics are excluded). Count of items should match the number of active topics for the project.
result: [pending]

### 5. Document List Endpoint
expected: GET /vdr-agent/documents?project_id={project_id} returns a JSON array of documents. Each item includes file_name, file_type, page_count, summary_status, fitment_done_count, fitment_total_count.
result: [pending]

### 6. Document List Endpoint 404
expected: GET /vdr-agent/documents?project_id=nonexistent-project returns HTTP 404 (proxy for project not found, since vdr-agent has no projects table).
result: [pending]

### 7. Router Registration
expected: All three routes appear in the FastAPI OpenAPI spec at /vdr-agent/openapi.json (or /vdr-agent/docs). Routes visible: /documents/{document_id}/summary, /documents/{document_id}/fitment, /documents.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0

## Gaps

[none yet]
