# Testing Patterns

**Analysis Date:** 2026-03-05

## Test Framework

**Runner:**
- **Python:** pytest 7.4.0+
- **Config:** `pyproject.toml` with pytest configuration
- **TypeScript:** No test framework configured (only linting/type checking)

**Assertion Library:**
- **Python:** pytest built-in assertions (`assert`)

**Run Commands:**
```bash
pytest tests/                            # Run all tests
pytest tests/unit/                       # Run unit tests only
pytest tests/test_token_redaction.py    # Run single test file
pytest tests/unit/temporal/              # Run specific module tests
pytest -v                                # Verbose output
pytest --cov=app                         # Coverage report
```

## Test File Organization

**Location:**
- **Python:** Co-located in `tests/` directory (separate from source)
- **Structure:** Mirrors application structure
  - `tests/unit/` — Unit tests
  - `tests/unit/temporal/` — Temporal workflow tests
  - Test files at project root for cross-cutting concerns (`tests/test_token_redaction.py`)

**Naming:**
- **Pattern:** `test_*.py` for test files
- **Examples:** `test_unsync_activities.py`, `test_excel_duplicate_columns.py`, `test_platform_config.py`

**Directory Structure:**
```
tests/
├── unit/
│   ├── temporal/
│   │   ├── activities/
│   │   │   └── test_unsync_activities.py
│   │   ├── __init__.py
│   │   └── test_workflow_platform_threading.py
│   ├── test_excel_duplicate_columns.py
│   ├── test_excel_sheet_reconciliation.py
│   ├── test_platform_config.py
│   ├── test_file_activities_platform_routing.py
│   └── ... (19 test files total)
└── test_token_redaction.py
```

## Test Structure

**Suite Organization:**
```python
class TestDeduplicateHeaders:
    """Tests for _deduplicate_headers()."""

    def test_no_duplicates_unchanged(self):
        headers = ["name", "age", "city"]
        result = _deduplicate_headers(headers)
        assert result == ["name", "age", "city"]

    def test_simple_duplicate(self):
        headers = ["yes", "no", "yes"]
        result = _deduplicate_headers(headers)
        assert result == ["yes", "no", "yes_1"]

    @pytest.mark.parametrize("input_path,is_folder,expected", [
        ("Documents/file.pdf", False, "/Documents/file.pdf"),
        ("/Documents/file.pdf", False, "/Documents/file.pdf"),
        ...
    ])
    def test_normalize_path_for_matching(self, input_path, is_folder, expected):
        result = _normalize_path_for_matching(input_path, is_folder)
        assert result == expected, f"Expected '{expected}', got '{result}'"
```

**Patterns:**

**1. Class-based test organization:**
- Group related tests into `Test{Component}` classes
- One logical feature per test class
- Example from `test_excel_duplicate_columns.py`:
  ```python
  class TestDeduplicateHeaders:
      """Tests for _deduplicate_headers()."""

  class TestDeduplicateRenameMap:
      """Tests for _deduplicate_rename_map()."""

  class TestSanitizeName:
      """Tests for _sanitize_name()."""
  ```

**2. Descriptive test names:**
- Start with `test_`
- Use underscores to separate concerns: `test_no_duplicates_unchanged`, `test_multiple_duplicates_of_same_name`
- Name describes expected behavior, not implementation

**3. Parametrized tests:**
- Use `@pytest.mark.parametrize()` for multiple input combinations
- Example from `test_unsync_activities.py`:
  ```python
  @pytest.mark.parametrize("input_path,is_folder,expected", [
      # Files - with and without leading slash
      ("Documents/file.pdf", False, "/Documents/file.pdf"),
      ("/Documents/file.pdf", False, "/Documents/file.pdf"),
      ...
      # Edge cases
      ("", False, "/"),
      ("", True, "/%"),
  ])
  def test_normalize_path_for_matching(self, input_path, is_folder, expected):
      result = _normalize_path_for_matching(input_path, is_folder)
      assert result == expected, f"Expected '{expected}', got '{result}'"
  ```

**Setup/Teardown:**
- Uses pytest fixtures (not shown in examples, but standard pattern)
- No explicit `setUp`/`tearDown` methods; rely on pytest's fixture mechanism

## Mocking

**Framework:**
- **Python:** unittest.mock (standard library)
- **Approach:** Not extensively used in analyzed files; tests focus on isolated pure functions

**Patterns:**

**What to Mock:**
- External API calls (Bedrock, SharePoint Graph API)
- Database connections
- File system operations

**What NOT to Mock:**
- Pure functions (test directly)
- Business logic in data transformation
- Path normalization logic

**Example of unmocked unit test (from `test_unsync_activities.py`):**
```python
def test_normalize_path_for_matching(self, input_path, is_folder, expected):
    # No mocking - test function directly
    result = _normalize_path_for_matching(input_path, is_folder)
    assert result == expected
```

## Fixtures and Factories

**Test Data:**
- **Parametrize approach:** Use `@pytest.mark.parametrize()` for test cases
- **Inline data:** Test data defined inline in test methods (not in separate fixture files)
- Example from `test_excel_duplicate_columns.py`:
  ```python
  def test_no_duplicates_unchanged(self):
      headers = ["name", "age", "city"]
      result = _deduplicate_headers(headers)
      assert result == ["name", "age", "city"]
  ```

**Location:**
- Fixtures would go in `conftest.py` (not present in current codebase)
- Test data currently defined inline per test method

## Coverage

**Requirements:** Not enforced (no coverage targets found in config)

**View Coverage:**
```bash
pytest --cov=app tests/         # Generate coverage report
pytest --cov=app --cov-report=html tests/  # HTML coverage report
```

## Test Types

**Unit Tests:**
- **Scope:** Individual functions and classes
- **Approach:** Pure function testing, no dependencies
- **Example:** `test_unsync_activities.py` tests `_normalize_path_for_matching()` with 10+ parameter combinations
- **Characteristics:**
  - Single responsibility per test
  - Clear input → output
  - No side effects
  - Fast execution (< 1s per test)

**Integration Tests:**
- **Scope:** Not detected in analyzed files
- **Approach:** Would test component interactions (activities with database, API calls, etc.)
- **Currently:** Not observed

**E2E Tests:**
- **Framework:** Not used
- **Status:** Not configured in codebase

## Common Patterns

**Async Testing:**
- **Framework:** `pytest-asyncio` for async test support
- Pattern:
  ```python
  @pytest.mark.asyncio
  async def test_async_function():
      result = await some_async_function()
      assert result == expected
  ```

**Error Testing:**
- Verify exceptions are raised correctly:
  ```python
  def test_error_case(self):
      with pytest.raises(ValueError):
          function_that_raises()
  ```

**Edge Case Testing:**
- Extensive use of parametrized tests to cover boundary conditions
- Example from `test_unsync_activities.py`:
  ```python
  @pytest.mark.parametrize("input_path,is_folder,expected", [
      ...
      # Edge cases
      ("", False, "/"),
      ("/", False, "/"),
      # Paths with trailing slashes (should be stripped for files)
      ("Documents/file.pdf/", False, "/Documents/file.pdf"),
  ])
  ```

**Documentation Testing:**
- Test docstrings explain intent and expected behavior
- Example from `test_unsync_activities.py`:
  ```python
  def test_normalization_matches_storage_format(self):
      """Test that normalized paths match how SharePoint sync stores them.

      SharePoint sync (browsing_service.py) stores paths with:
      - Leading slash: YES (always)
      - Example: parent_path="/Documents", name="file.pdf" → "/Documents/file.pdf"
      """
  ```

## Test Dependencies

**Required packages (from `pyproject.toml`):**
```toml
[tool.poetry.group.dev.dependencies]
pytest = ">=7.4.0"
pytest-asyncio = ">=0.21.0"
black = ">=23.0.0"
mypy = ">=1.5.0"
ruff = ">=0.1.0"
```

**Install for testing:**
```bash
poetry install           # Installs all dependencies including dev
pip install -r requirements.txt  # Or with pip
```

## TypeScript Testing Strategy

**Status:** No test framework configured
- No Jest, Vitest, or similar in `package.json` or `vdr-frontend/package.json`
- **Recommendation if adding tests:**
  - Use Vitest (modern, ESM-first alternative to Jest)
  - Config would go in `vitest.config.ts`
  - Tests would use React Testing Library for component testing
  - Naming: `*.test.tsx` or `*.spec.tsx`

---

*Testing analysis: 2026-03-05*
