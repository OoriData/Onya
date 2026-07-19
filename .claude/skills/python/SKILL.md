---
name: python-backend
description: Python 3.12+ backend and library development — packaging, testing, pyproject.toml, uv, hatchling, asyncio, and repo hygiene. Use when working on Python services, CLIs, or libraries.
---

# Python Backend Development

## Purpose
Follow this skill for Python 3.12+ backend and library work: packaging, project structure, testing, and repository hygiene.

## Default rules
- Single quotes throughout, including triple-quoted strings.
- Absolute imports; 120-char lines; moderate comments.
- `uv` for installs; `uv pip install .` for real package validation (not `-U`; use `--reinstall-package <pkg>` to force a rebuild after source edits). `uv pip` ignores `uv.lock` — we don't rely on locking; reserve `uv sync` (exact lock mirror, prunes extras — wrong for shared venvs) for repos that genuinely need it, and pass `--no-editable` (or `UV_NO_EDITABLE=1`) when you do — the prefix rewrite makes an editable sync hard-fail, same as `uv run`. Never paper over that failure with `[tool.uv] package = false`: it installs no package at all, so the rewrite never runs and the library isn't importable — only valid for genuine non-library app/service repos.
- Hatchling build system; no `setuptools`, no `setup.py`.
- No editable installs for libraries.
- `asyncio` for I/O-bound work; multiprocessing for CPU-bound.
- `fire` for CLI args; `structlog` for logging; `httpx` for HTTP; `pytest` for tests.
- `tenacity` for retries; `rich` for terminal output.
- No `langchain` unless explicitly requested.
- Dataclasses over Pydantic; keep abstractions proportionate to the task.

## When the project sends prompts to an LLM
Also follow [python-prompting](../python-prompting/SKILL.md): WordLoom for all prompts, shared loader module, no inline `system='...'` strings.

## When writing or organizing tests
Also follow [testing](../testing/SKILL.md): keep the default run fast and unit-only; mark anything hitting unowned code or live services `@pytest.mark.integration` and exclude it by default; own the boundary instead of mocking third-party internals.

## When adding native (C/C++/Rust) acceleration
Also follow [python-c](../python-c/SKILL.md): profile before porting; pick the interface
deliberately (cffi/Cython/nanobind/PyO3); ship an *observable* pure-Python fallback; and
remember hatchling does NOT compile extensions by default — wire an explicit build hook or
the accelerator silently ships as a dead symbol.

## Workflow
1. Read the repo's `CLAUDE.md` / `AGENTS.md` first.
2. Check `pyproject.toml` — follow its build and test commands.
3. Prefer small, deterministic changes.
4. Validate with `pytest` or a targeted run.
5. Report any assumptions or unresolved ambiguity.

## Packaging
- Library code lives under `pylib/`.
- Use `[tool.hatch.build.targets.wheel]` with `only-include = ['pylib']`.
- Map `pylib` to the package name in `[tool.hatch.build.sources]`.
- Export CLIs through `[project.scripts]` with a `main()` entry point in each module.

## Service & async hardening
Recurring, easy-to-miss correctness/security gotchas in long-running services and CLIs:

- **Retain fire-and-forget tasks.** `asyncio.create_task(coro())` returns a task the
  event loop holds only *weakly* — under GC pressure it can be collected mid-`await`,
  silently dropping the work (a webhook enqueue, a deferred Slack post). Keep a strong
  reference until it finishes:
  ```python
  _tasks: set[asyncio.Task] = set()

  def spawn_background(coro):
      t = asyncio.create_task(coro)
      _tasks.add(t)
      t.add_done_callback(_tasks.discard)
      return t
  ```
- **Secret-safe tracebacks.** `structlog.dev.ConsoleRenderer()` (Rich) renders local
  variables in tracebacks — which leaks secrets, since API keys live in headers dicts,
  settings objects, etc. Always pass `exception_formatter=structlog.dev.plain_traceback`,
  and define a single `configure_logging()` so the policy can't drift between entry
  points — one copy that forgets it leaks in that service's logs.
- **Read-only SQLite over a read-only mount.** Open with a `file:` URI in `mode=ro` so the
  connection can never write and won't auto-create a missing file:
  ```python
  dsn = Path(path).resolve().as_uri() + '?mode=ro'   # as_uri() percent-encodes the path
  await aiosqlite.connect(dsn, uri=True)
  ```
  Build the URI with `Path.as_uri()`, not an f-string: a raw `file:{path}?mode=ro`
  truncates the path at a literal `?` and opens the wrong file. And `aiosqlite.connect`
  on a bare path *auto-creates* an empty DB — so a missing mount silently looks like an
  empty store; `mode=ro` makes it fail loudly instead.

## If the task is unclear
Ask for the repo type (library vs service), runtime target, and whether strict installability or editable installs are acceptable. This axis decides `[tool.uv] package`: a library with the `pylib` prefix rewrite must stay a package (install real wheels, `--no-editable`); only a genuine non-library app/service run from source is a candidate for `package = false`.


## Full conventions

Additional context for coding tools & agents

- Python 3.12+ code, unless otherwise specified
- Python code uses single outer quotes, including triple single quotes for e.g. docstrings
- prefer absolute imports to relative imports
- Use a decent amount of comments
  - not *too* many, just enough that anybody familiar with the code can use them as a reference point. Not meant to teach somebody new every intricacy of the code, just help keep the savvy reader oriented.
- if it saves a line, put a comment after a line rather than above it
  - use the standard two spaces before the comment character, eg. `CODE  # COMMENT`
- Try to stick to 120 characters per line
  - if one of those comments would break this guideline, just put that comment above the line instead, as is standard convention
- If there is a pyproject.toml in place, use it as a reference for builds, installs, etc. The basic packaging and dev preference, including if you have to supply your own pyproject.toml, is as follows:
  - Prefer hatchling build system over setuptools, poetry, etc. Avoid setuptools as much as possible. No setup.py.
  - Reusable Python code modules are developed in the `pylib` folder, and installed using e.g. `uv pip install .`, which includes proper mapping to Python library package namespace via `tool.hatch.build.sources`. The `__init__.py` and other modules in the top-level package go directly in `pylib`, though submodules can use subdirectories, e.g. `pylib/a/b` becomes `installed_library_name.a.b`. Ultimately this will mean the installed package is importable as `from installed_library_name.etc import …`
  - Use `[tool.hatch.build.targets.wheel]` with `only-include = ["pylib"]` to ensure the pylib directory structure gets included properly in the wheel, avoiding the duplication issue that can occur with sources mapping
  - Yes this means editable and "dev mode" environments are NOT desirable, nor are shenanigans adding pylib to `sys.path`. Layer-efficient dockerization is an option if that's needed.
  - The ethos is to always develop keeping things properly installable. No dev mode shortcuts. Substantive modification to library code requires a reinstall each time — use `uv pip install --reinstall-package <pkg> .`. (A bare `uv pip install .` can skip rebuilding the local package when its version string is unchanged even though the source changed; `--reinstall-package` forces the rebuild of just your package. Do **not** reach for `-U`/`--upgrade` here — see below.)
  - Note: This avoidance of editable installs can be relaxed for non-library code, such as demos or main app launch scripts (e.g. webapp back ends)
  - If it's a CLI provided as part of a library, though, it should still use proper installation via `[project.scripts]` entry points (e.g., `myapp = 'myapp.cli.scout:main'`), which creates console scripts that work correctly after `uv pip install .`. The CLI module lives in `pylib/cli/` and exposes a `main()` function that uses fire to handle command-line arguments. 
- **Debugging package issues**: When modules aren't importing correctly after installation, check:
  - That you are in the correct virtualenv (you may have to ask the developer)
  - Package structure in site-packages (e.g., `ls -la /path/to/site-packages/package_name/`)
- Use uv, but pay attention to the above
  - Again always use `uv pip install .` (not `-U`) for full installation, never editable installs (`pip install -e`). This ensures proper testing of the actual distribution. **Avoid `-U`/`--upgrade` in the dev loop**: it force-upgrades the whole transitive dependency tree on every install (gratuitous drift, and it ignores `uv.lock` anyway — see below), yet it still does *not* force the local package to rebuild after a source edit. Reach for `--reinstall-package <pkg>` for that, not `-U`.
  - **`uv run` needs `--no-editable` — it's mandatory, not optional**: a bare `uv run` (and `uv run --reinstall`) syncs the workspace project as an *editable* install. With the `[tool.hatch.build.sources]` prefix rewrite above (e.g. `'pylib' = 'mypkg'`), hatchling rejects dev-mode builds outright — `ValueError: Dev mode installations are unsupported when any path rewrite … changes a prefix rather than removes it`. So this isn't a stale-build nuisance, it's a hard failure: always pass `--no-editable` to `uv run`, or install once with `uv pip install .` and invoke the tool directly (`pytest`, your CLI, …) in that environment.
  - **uv venv gotcha**: `uv run` uses the project's `.venv/` (auto-created), ignoring `$VIRTUAL_ENV`. `uv pip install` does the opposite — it follows `$VIRTUAL_ENV`, NOT the project `.venv/`. So `uv pip install .` run from inside an outer venv will *not* update what `uv run` sees. Either deactivate the outer venv before installing, or let `uv run` manage things.
  - **uv rebuild gotcha**: `uv run --no-editable` caches its build of the package in `.venv/` and only rebuilds when `pyproject.toml` changes — edits to source under `pylib/` alone do NOT trigger a rebuild. After such edits, pass `--reinstall-package <pkg>` to force a fresh build of just your package (e.g. `uv run --no-editable --reinstall-package mypkg pytest`); a blanket `--reinstall` works too but needlessly rebuilds every dependency.
  - **`uv.lock` is not part of this dev loop**: `uv pip install` ignores `uv.lock` entirely, so nothing above ever consults a lock — a committed `uv.lock` is inert here, not a reproducibility guarantee. Only `uv sync` reads/writes it, and `uv sync` makes the target environment an *exact mirror* of the lock: it prunes anything not in that lockfile. That's actively wrong for a venv shared by more than one project (it strips out the other project's packages) and it tailors the environment to a single lockfile. We deliberately do **not** rely on `uv.lock` for reproducibility — prefer testing the actual built distribution via `uv pip install .`. If a specific repo genuinely needs locked, reproducible installs, adopt `uv sync` wholesale for that repo and give it its own dedicated (non-shared) venv.
  - **If you do use `uv sync`, it needs `--no-editable` too — same hard failure as `uv run`**: `uv sync` installs the workspace project as an *editable* install by default, so with the `[tool.hatch.build.sources]` prefix rewrite above it hits the identical `ValueError: Dev mode installations are unsupported when any path rewrite … changes a prefix` — this isn't a stale-build nuisance, it's a hard failure. Use `uv sync --no-editable` (or set `UV_NO_EDITABLE=1` in that repo's env); this builds and installs a real wheel, so the rewrite applies and the package imports under its installed name. Note there is **no** `pyproject.toml` home for this — `[tool.uv]` has no `no-editable` key, so it must be the flag or the env var.
  - **Do NOT "fix" the sync/editable clash with `[tool.uv] package = false`**: it silences the crash by telling uv the project is not a package and never to install it — so only dependencies land in the venv, the prefix rewrite never runs, and the package is not importable under its installed name (`from installed_library_name… ` fails). That defeats the whole point of testing the actual built distribution; it's a mute button, not a fix. `package = false` is only correct for a repo that is *genuinely* a non-library application/service run from source (webapp back end, demo, launcher) with **no** prefix rewrite — i.e. exactly the case where editable installs are already relaxed. For a library with the `pylib` rewrite, use `--no-editable` (above) instead.
- Use async (e.g. asyncio) wherever it makes sense. Avoid multithreading, though multiprocessing is OK. Multiprocess for CPU-bound concurrency, and asyncIO for I/O bound, cooperative etc.
- Be pythonic. Avoid e.g. complex abstract class hierarchies for the sake of them, though classes are also fine in many usage patterns. We love dictionaries, dynamic dispatch, etc.
  - I don't consider Pydantic very Pythonic, so we can tolerate it if need be (e.g. we're using a toolkit that strictly works with Pydantic), but otherwise, simple dataclasses are better.
- Type hints are OK in moderation, but avoid absolutely littering the code with them.
  - No excess imports & symbols, e.g. Use type | None rather than Optional[type]
- use iterator patterns as much as practical. Also functional programming approaches, including partials (currying) and decorators
- Preferred tools:
  - Logging: structlog
  - Retries on failure: tenacity
  - CLI argument processing: fire—avoid argparse except for truly trivial usage
  - CLI formatting: rich
  - HTTP client: httpx (async)
    - Add hishel (RFC 9111 HTTP cache; `hishel.AsyncCacheClient(storage=FileStorage(...))`) for httpx wherever ETag/Last-Modified/Cache-Control make sense
  - HTML/XML parsing & content selection: selectolax
  - Browser-like Web crawling/scraping: Python playwright (with playwright_stealth if needed)
  - pytest, as well as pytest-mock, pytest-httpx, pytest-asyncio
  - rapidfuzz for fuzzy text matching
  - Native acceleration: profile first. Bind existing C with cffi, existing C++ with
    nanobind (not pybind11 for greenfield); write new hot kernels in Cython or Rust/PyO3.
    Raw CPython C-API only for a tiny stable kernel. Always keep a pure-Python fallback. See the `python-c` skill.
- Testing: keep the default run fast, cheap, and deterministic (unit only). Tests that hit unowned code or live services (DB, HTTP, browser) are integration tests — mark them `@pytest.mark.integration`, register the marker, and exclude them by default via `addopts = '-m "not integration"'` in `pyproject.toml`. Don't mock third-party internals; own the boundary and ship a real in-memory implementation alongside the production one. Let callers inject the `httpx.AsyncClient` so tests can use `MockTransport`. See the `testing` skill for the full pattern.
- AVOID the following unless explicitly requested or otherwise unavoidable:
  - langchain

- Prompts sent to LLMs (Claude, OpenAI, OpenRouter, etc.) are content, not code. Keep them in [WordLoom](https://github.com/OoriData/WordLoom/) `.loom.toml` files under `prompts/`, loaded through a shared `prompts.py` module. Use WordLoom's [file-inclusion](https://github.com/OoriData/WordLoom/blob/main/implementation.md#extension-file-inclusion) (`file:` / `glob:` / `dir:`) to compose prompts from external assets rather than pasting them into TOML. No inline `system = 'You are...'` strings in Python source. See the `python-prompting` skill for the full pattern.

- Once again PREFER SINGLE QUOTES

