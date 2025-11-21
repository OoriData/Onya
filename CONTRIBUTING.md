onya Contributor Guide

# Quick Reference

## Why We Use `uv pip install -U .`

This project uses a non-standard source layout where `pylib/` becomes `onya/` during package building. This remapping only happens during wheel building, not in development environments.

**Why not use hatch environments?**
- Hatch's path remapping (`tool.hatch.build.sources`) only applies during wheel building
- Hatch's dev-mode uses editable installs which can't apply the source remapping
- Setting `dev-mode=false` means no install happens at all

**Solution:** We use proper package installation (`uv pip install -U .`) instead of editable/dev-mode installs. This ensures the source remapping is applied correctly and your development environment matches the built package.

See also the note in `pyproject.toml` at `[tool.hatch.build.targets.wheel]` for more details on this limitation.

## Daily Development

```bash
# Install in current virtualenv
uv pip install -U .

# Run tests
pytest test/ -v

# Run specific test file
pytest test/test_graph.py -v

# Run linting
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Run tests with coverage
pytest test/ --cov=onya --cov-report=html
```

## Making Changes

```bash
# After editing any Python files in pylib/
uv pip install -U .

# After editing resources/
uv pip install -U .

# After editing tests only (no reinstall needed)
pytest test/ -v
```

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
├── pylib/              # Source code (becomes 'onya' package when installed)
│   ├── __init__.py
│   ├── __about__.py    # Version info
│   ├── graph.py        # Graph, node, edge, property classes
│   ├── terms.py        # Common IRI vocabulary terms
│   └── serial/         # Serialization modules
│       ├── __init__.py
│       ├── literate.py
│       ├── literate_lex.py
│       └── litparse_util.py
├── test/               # Tests
│   ├── conftest.py
│   ├── test_graph.py
│   ├── test_graphobj.py
│   ├── test_readme.py
│   ├── test_serial_literate.py
│   └── resource/       # Test resources
│       └── schemaorg/
│           ├── achebe-bio.onya
│           └── thingsfallapart.onya
├── pyproject.toml      # Project config
├── README.md
└── SPEC.md             # Format specification
```

When installed, becomes:

```
site-packages/
└── onya/
    ├── __init__.py
    ├── __about__.py
    ├── graph.py
    ├── terms.py
    └── serial/
        ├── __init__.py
        ├── literate.py
        ├── literate_lex.py
        └── litparse_util.py
```

## Key Files

- `pylib/__about__.py` - Version number (update for releases)
- `pyproject.toml` - Dependencies, metadata, build config
- `pylib/graph.py` - Core graph model implementation
- `pylib/serial/literate_lex.py` - Onya Literate format parser
- `test/resource/` - Test data files in Onya format
- `README.md` - Main documentation
- `SPEC.md` - Format specification

# Publishing a Release

Before creating a release:

- [ ] Update version in `pylib/__about__.py`
- [ ] Update CHANGELOG.md
- [ ] Run tests locally: `pytest test/ -v`
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
from onya.serial import literate_lex

onya_text = '''
# @docheader
* @document: http://example.org/test
* @base: http://example.org/

# TestNode [Thing]
* name: Hello
'''

g = graph()
doc_iri = literate_lex.parse(onya_text, g)
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
- Runs ruff linting
- Runs pytest test suite

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
