---
name: testing
description: Fast, cheap, deterministic test suites — the unit/integration split, marking and excluding tests that hit unowned code or services, and the "don't mock what you don't own" alternative-implementations pattern. Use when writing, organizing, or speeding up tests for Python libraries or webapp back ends.
applies-to: [python, webapp]
---

# Testing

## Purpose
Keep the default test run fast, cheap, and deterministic. Tests that reach into code or services you don't own belong to an integration phase that does not run by default. Avoid brittle mocking of third-party interfaces by owning the boundary instead.

## The two phases

- **Unit tests — the default run.** Fast, offline, deterministic. No network, no real database, no filesystem beyond `tmp_path`, no clock/UUID/randomness you can't control. These run on every change and in CI by default. Aim for milliseconds per test.
- **Integration tests — opt-in only.** Anything that exercises *unowned* code or a real service (a live database, an external HTTP API, a message broker, a browser). These are marked and **excluded from the default run**; they run only when explicitly requested (a dedicated integration phase, a nightly job, or a manual `-m integration`).

The dividing question is ownership, not speed: *does this test depend on code or a service I don't control?* If yes, it's integration.

## Marking & excluding integration tests (pytest)

Register the marker and exclude it by default in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = '-m "not integration"'
markers = [
    'integration: touches unowned code or live services (DB, HTTP, browser); excluded from the default run',
]
```

Then:

```python
import pytest

@pytest.mark.integration
async def test_against_real_postgres(pg_dsn):
    ...
```

- Default `pytest` → unit only.
- `pytest -m integration` → integration only.
- `pytest -m 'integration or not integration'` (or `--override-ini addopts=`) → everything.

Never let an unmarked test silently depend on a live service — that's how a "unit" suite becomes slow and flaky.

## Don't mock what you don't own

When you find yourself heavily mocking a third-party interface (a DB driver like `asyncpg`, an SDK, an HTTP client's internals), stop and introduce **your own object at the right level of abstraction** — a clear, maintainable bridge to that third party — then provide more than one real implementation of *that*:

- A production implementation that wraps the third-party library.
- A simple, dependency-free implementation for tests, prototyping, and lightweight production use.

This is **not** mocking in the brittle sense — both are real, usable implementations. Example: rather than mocking `asyncpg`, define your own `DataDB` interface with a PostgreSQL-backed implementation *and* an in-memory one built from plain lists/dicts/`numpy`. The in-memory version gives fast, reliable unit tests with no fragile patching — and ships as a genuine feature (no-dependency mode). The Postgres-backed path is then what your *integration* tests cover.

Reference: Hynek Schlawack, ["Don't Mock What You Don't Own" in 5 Minutes](https://hynek.me/articles/what-to-mock-in-5-mins/).

## HTTP boundaries

Let callers inject the client — accept an `httpx.AsyncClient` parameter instead of constructing one inside your function. Tests then pass a client with a mock transport, no patching required:

```python
from http import HTTPStatus
import httpx

test_client = httpx.AsyncClient(
    transport=httpx.MockTransport(
        lambda request: httpx.Response(HTTPStatus.NOT_FOUND, content='Not Found')
    )
)
```

For richer request/response scripting, use [`pytest-httpx`](https://github.com/Colin-b/pytest_httpx). Real HTTP calls to a live endpoint stay behind `@pytest.mark.integration`.

## Native extensions (optional accelerators)

When a module has both a compiled accelerator and a pure-Python fallback:

- **Behaviour tests are unit tests** — parametrise over the import so the pure *and*
  compiled paths face the identical assertions. A divergence between them is a bug, and the
  pure path must run even where no toolchain exists.
- **Test the fallback itself** — force the C import to fail and assert the pure version
  answers identically and logs the degradation (no silent `except ImportError: pass`).
- **Building/importing the wheel across the platform × Python matrix is integration** —
  it needs real toolchains (`cibuildwheel`). Mark/segregate it; keep it out of the fast run.

See the `python-c` skill for the packaging and C-API side of this.

## Regression tests must have teeth
A test added with a bug fix must **fail without the fix**. A test that passes against
*both* the buggy and the fixed code proves nothing — it's false coverage. Confirm it
actually catches the regression: run it against the unpatched code (`git stash` the fix),
or construct the input so the old behaviour provably diverges. Real example: a "handles
odd paths" test using a path with *spaces* passed against both old and new code because
the underlying library tolerated spaces — only a path with the genuinely-mishandled
character (`?`) exercised the fix. Pick the input that breaks the old code, not merely a
plausible-looking one.

## Checklist
- Default run is unit-only, offline, and deterministic.
- Every test that hits unowned code or a live service is `@pytest.mark.integration` and excluded by default.
- No mocking of third-party internals — own the boundary, ship a real in-memory alternative.
- HTTP code accepts an injected `AsyncClient`; tests use `MockTransport` / `pytest-httpx`.
- No hidden dependence on wall-clock, randomness, or external state; control these via fixtures/injection.
- Optional native accelerators are tested against their pure-Python fallback (same assertions), and the matrix build is integration-only.
- Regression tests fail without the fix — verified, not assumed.

## References
- `snippets/python.md` / `snippets/webapp.md` — preferred test tooling (`pytest`, `pytest-asyncio`, `pytest-httpx`, `pytest-mock`).
- `code-review` skill — reviews flag unmarked integration tests and unowned-interface mocking.
