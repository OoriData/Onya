onya Contributor Guide

# Quick Reference

## Why We Use `uv pip install -U .`

This project uses a source layout where `pylib/` becomes `onya/` during package building. This remapping only happens during wheel building, not in development environments.

**Why not use hatch environments?**
- Hatch's path remapping (`tool.hatch.build.sources`) only applies during wheel building
- Hatch's dev-mode uses editable installs which can't apply the source remapping
- Setting `dev-mode=false` means no install happens at all

**Solution:** We use proper package installation (`uv pip install -U .`) instead of editable/dev-mode installs. This ensures the source remapping is applied correctly and your development environment matches the built package.

See also the note in `pyproject.toml` at `[tool.hatch.build.targets.wheel]` for more details on this limitation.

## Daily Development

```bash
# First-time setup: install Onya plus the test/dev dependencies (pytest, pytest-asyncio,
# hypothesis, ruff, …). Extras are declared in [project.optional-dependencies].
uv pip install -U '.[dev]'

# For PostgreSQL store work, also install the postgres extra (asyncpg):
uv pip install -U '.[dev,postgres]'

# After editing code under pylib/, reinstall (deps already present):
uv pip install -U .

# Run the fast test suite (excludes live-service integration tests)
pytest test/ -v -m "not integration"

# Run specific test file
pytest test/test_graph.py -v

# Run linting
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Run tests with coverage
pytest test/ --cov=onya --cov-report=html
```

The async store suite needs `pytest-asyncio`; the interp property tests need `hypothesis`
(they self-skip if it is absent). Both come with the `[dev]` extra.

## Making Changes

```bash
# After editing any Python files in pylib/
uv pip install -U .

# After editing resources/
uv pip install -U .

# After editing tests only (no reinstall needed)
pytest test/ -v
```

## Persistence backends & integration tests

`onya.store` ships three backends behind one async protocol: the filesystem (`file:`,
default), SQLite (`sqlite:`, stdlib), and PostgreSQL (`postgresql://`, extras-gated). The
behavioral conformance suite in `test/store/` is written once and parameterized over every
available backend.

- **Filesystem and SQLite run everywhere** — no configuration, no services, part of the
  default `pytest` run.
- **PostgreSQL is opt-in.** Live-DB tests are marked `@pytest.mark.integration` and/or gated
  on environment variables, so they are excluded from the fast run and skipped when unset
  (this is why CI passes without a database). When `ONYA_TEST_PG_DSN` is set, the conformance
  suite additionally parameterizes over the `postgres` backend.

### Running the PostgreSQL integration tests via Docker

Spin up a throwaway PostgreSQL 17 and point the tests at it:

```bash
# Start a disposable PostgreSQL 17
docker run -d --name pg17-test -e POSTGRES_PASSWORD=secret -p 5432:5432 postgres:17

# Point the tests at it (the conformance suite auto-adds the `postgres` backend)
export ONYA_TEST_PG_DSN='postgresql://postgres:secret@localhost:5432/postgres'

# Make sure asyncpg is installed
uv pip install -U '.[dev,postgres]'

# Run the whole store suite, integration tests included
pytest test/store/ -v

# ...or just the PostgreSQL-specific tests (reachable(), etc.)
pytest test/store/test_store_postgres.py -v

# Tear down when done
docker rm -f pg17-test
```

The test fixture empties the schema (`DELETE FROM onya_graph`, which cascades) between tests,
so a single database instance is reused safely. Each test graph is isolated by name.

**PostgreSQL ≥ 19 / SQL-PGQ** is a separate, currently-notional path. Its property-graph
tests gate additionally on `ONYA_TEST_PG19_DSN` and are otherwise skipped; PG 19 is still
beta, so this is intentionally left unverified for now.

## Useful Commands

```bash
# See package structure after install
python -c "import onya, os; print(os.path.dirname(onya.__file__))"
ls -la $(python -c "import onya, os; print(os.path.dirname(onya.__file__))")

# Check what files are in the installed package
pip show -f onya

# Check installed version
python -c "import onya; print(onya.__version__)"

# Compare source version
cat pylib/__about__.py

# Uninstall completely
pip uninstall onya -y

# Clean build artifacts
rm -rf build/ dist/ *.egg-info
rm -rf .pytest_cache .ruff_cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

## Testing Package Build Locally

```bash
# Build locally
python -m build
python -m build -w  # For some reason needs to need both, in this order. Probably an issue in how we're using hatch

# Test the built wheel (replace X.Y.Z with actual version)
pip install dist/Onya-0.X.Y-py3-none-any.whl --force-reinstall

# Check package contents (replace X.Y.Z with actual version)
unzip -l dist/Onya-0.X.Y-py3-none-any.whl
```

# Project Structure

```
Onya/
├── pylib/                    # Source code (becomes 'onya' package when installed)
│   ├── __init__.py
│   ├── __about__.py          # Version info
│   ├── graph.py              # Graph, node, edge, property classes; merge & union
│   ├── interp.py             # Interpretation (data-contract) plugin layer
│   ├── terms.py              # Common IRI vocabulary terms
│   ├── util.py               # IRI/CURIE helpers
│   ├── cli/                  # `onya` console script (fire-based)
│   │   ├── __init__.py
│   │   └── onya.py
│   ├── serial/               # Serialization
│   │   ├── __init__.py
│   │   ├── literate.py        # Onya Literate read()/write() (public API)
│   │   ├── _literate_parse.py # Onya Literate parser internals
│   │   ├── graphviz.py
│   │   └── mermaid.py
│   └── store/                # Pluggable persistence (onya.store)
│       ├── __init__.py       # connect() factory, entry-point dispatch
│       ├── base.py           # GraphStore/AssertionStore/GraphQueryStore protocols
│       ├── exceptions.py
│       ├── filesystem.py     # file: backend (default; the testing fake)
│       ├── _relational.py    # shared DDL, skeleton hash, write-path merge
│       ├── sqlite.py         # sqlite: backend
│       ├── postgres.py       # postgresql:// backend (asyncpg, extras-gated)
│       └── sync.py           # blocking facade
├── test/                     # Tests (test/store/ holds the store conformance suite)
│   ├── conftest.py
│   ├── test_graph.py
│   ├── test_graph_union.py
│   ├── test_serial_literate.py
│   ├── store/                # store conformance, capabilities, relational, guards
│   └── resource/schemaorg/   # fixture .onya documents
├── doc/                      # Design docs and the Python tutorial
├── pyproject.toml            # Project config
├── README.md
└── SPEC.md                   # Format specification
```

When installed, `pylib/` becomes the `onya/` package under `site-packages/` with the same
internal layout (the `pylib` → `onya` remap; see the note in `pyproject.toml`).

## Key Files

- `pylib/__about__.py` - Version number (update for releases)
- `pyproject.toml` - Dependencies, metadata, build config, store backend entry points
- `pylib/graph.py` - Core graph model, `merge()`, and model-level `union()`
- `pylib/serial/_literate_parse.py` - Onya Literate parser internals (public API in `literate.py`)
- `pylib/interp.py` - Interpretation (data-contract) plugin layer
- `pylib/store/` - Persistence backends and shared relational core
- `test/resource/` - Test data files in Onya format
- `doc/design-persistence-architecture.md` - Store architecture, schema, skeleton hash, PGQ
- `README.md` - Main documentation
- `SPEC.md` - Format specification

# Publishing a Release

Before creating a release:

- [ ] Update version in `pylib/__about__.py`
- [ ] Update CHANGELOG.md
- [ ] Run tests locally: `pytest test/ -v -m "not integration"` (and, ideally, the PostgreSQL integration tests against a Docker instance — see above)
- [ ] Run linting: `ruff check .`
- [ ] Commit and push all changes
<!-- 
- [ ] Create git tag: `git tag v0.X.Y`
- [ ] Push tag: `git push origin v0.X.Y`
 -->
- [ ] [Create GitHub release](https://github.com/OoriData/onya/releases/new) (triggers publish workflow)
- [ ] Verify package update on PyPI: https://pypi.org/project/Onya/

## Testing the Package

After publishing, test the installation:

```bash
# Create a fresh virtual environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate

# Install from PyPI
pip install Onya

# Test import
python -c "import onya; print(onya.__version__)"

# Test basic functionality
python -c "
from onya.graph import graph
from onya.serial.literate import LiterateParser

onya_text = '''
# @docheader
* @document: http://example.org/test
* @nodebase: http://example.org/

# TestNode [Thing]
* name: Hello
'''

g = graph()
op = LiterateParser()
result = op.parse(onya_text, g)
doc_iri = result.doc_iri
print(f'Parsed document: {doc_iri}')
print(f'Graph has {len(g)} nodes')
"
```

# Initial Project Setup

Historical, and to inform maintenance. GitHub Actions & PyPI publishing.

## GitHub Actions Setup

The repository includes two workflows:

### 1. CI Workflow (`.github/workflows/main.yml`)

Runs automatically on every push and pull request. It:
- Tests on Python 3.12 and 3.13
- Installs test dependencies (`pytest-asyncio`, `hypothesis`) alongside `ruff`/`pytest`
- Runs ruff linting
- Runs the pytest suite with `-m "not integration"` (no live database required)

Live PostgreSQL integration tests do not run in CI (no `ONYA_TEST_PG_DSN`); run them
locally against a Docker instance as described under *Persistence backends & integration
tests*.

### 2. Publish Workflow (`.github/workflows/publish.yml`)

Runs when you create a new GitHub release. It builds and publishes to PyPI.

## PyPI Trusted Publishing Setup

###  PyPI Setup

- Login your [PyPI](https://pypi.org) account
- For new package:
    - Go to: https://pypi.org/manage/account/publishing/
    - Click "Add a new pending publisher"
    - Fill in:
    - **PyPI Project Name**: `Onya` (must match `name` in `pyproject.toml`, with case)
    - **Owner**: `OoriData`
    - **Repository name**: `onya`
    - **Workflow name**: `publish.yml`
    - **Environment name**: `pypi` (PyPI's recommended name)
- If the package already exists on PyPI:
    - Go to the project page: https://pypi.org/manage/project/Onya/settings/publishing/
    - Add the publisher configuration as above

### GitHub Setup
- Go to: https://github.com/OoriData/onya/settings/environments
- Click "New environment"
- Name: `pypi`
- Click "Configure environment"
- (Optional) Add protection rules:
    - Required reviewers: Add yourself to require manual approval before publishing
    - Wait timer: Add a delay (e.g., 5 minutes) before publishing
- Click "Save protection rules"

### Note on using the environment name

Using an environment name (`pypi`) adds an extra layer of protection, with rules such as required reviewers (manual approval before publishing), wait timers (delay before publishing) and branch restrictions. Without an environment stipulation the workflow runs automatically when a release is created.

## First Time Publishing

Option on the very first release to PyPI: may want to do a manual publish to ensure everything is set up correctly:

```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# For some reason, the wheel only seems to work if you build first without then with `-w`
python -m build -w

# Basic build check
twine check dist/*

# Extra checking (replace VERSION with actual version)
VERSION=0.1.2 pip install --force-reinstall -U dist/Onya-$VERSION-py3-none-any.whl
python -c "from onya.graph import graph; print('Import successful')"

# Upload to Test PyPI first (optional but recommended)
twine upload --repository testpypi dist/*
# Username: __token__
# Password: your-test-pypi-token

# If test looks good, upload to real PyPI
twine upload dist/*
# Username: __token__
# Password: your-pypi-token
```

After the first manual upload, you can use trusted publishing for all future releases.

## Troubleshooting

### "Project name 'Onya' is not valid"
- Check that the name in `pyproject.toml` matches exactly (currently `Onya`)
- Names are case-insensitive but must match what you registered on PyPI

### "Invalid or non-existent authentication information"
- For trusted publishing: Double-check the repository name, owner, and workflow name
- For token auth: Make sure the token is saved as `PYPI_API_TOKEN` in GitHub secrets

### Workflow fails with "Resource not accessible by integration"
- Make sure the workflow has `id-token: write` permission
- Check that the repository settings allow GitHub Actions

### Package version already exists
- You can't overwrite versions on PyPI
- Increment the version in `pylib/__about__.py` and create a new release

## Additional Resources

- [PyPI Trusted Publishing Guide](https://docs.pypi.org/trusted-publishers/)
- [GitHub Actions for Python](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python)
- [Python Packaging Guide](https://packaging.python.org/en/latest/)
