# Publishing Python and Go Bindings

This document covers how the automated build and publish pipeline works for the ai.outshift protocol model packages (Python to PyPI, Go module tags to GitHub).

## Overview

This repo publishes three packages to PyPI:

| Package | Install | Contents |
|---------|---------|----------|
| `ioc-l9-all-models` | `pip install ioc-l9-all-models` | SSTP root L9 + all subprotocols (SAB, TFP, SIEP, CIP) |
| `ioc-l9-sstp-models` | `pip install ioc-l9-sstp-models` | Only SSTP root L9 models |
| `ioc-l9-subprotocols` | `pip install ioc-l9-subprotocols` | Only subprotocols (SAB, TFP, SIEP, CIP) |

### Dependencies Between Packages

```
ioc-l9-all-models          ← everything in one package (recommended)

ioc-l9-subprotocols        ← SAB + TFP + SIEP + CIP subprotocols
  └── requires: ioc-l9-sstp-models   (SAB imports L9Header, L9Payload, Actor, Context)

ioc-l9-sstp-models         ← standalone SSTP root L9 models
```

> **Note:** The SAB subprotocol imports from the root L9 models (`ai.outshift.data_model`).
> If you install `ioc-l9-subprotocols`, you must also install `ioc-l9-sstp-models`:
> ```bash
> pip install ioc-l9-sstp-models ioc-l9-subprotocols
> ```
> Or just use `ioc-l9-all-models` which bundles everything.
> TFP has no dependency on the root models and works standalone.

> **Warning:** Do NOT install `ioc-l9-all-models` alongside `ioc-l9-subprotocols` or
> `ioc-l9-sstp-models`. They ship overlapping files and uninstalling one may break the other.
>
> Pick one approach:
> - `pip install ioc-l9-all-models` — everything in one package (simplest)
> - `pip install ioc-l9-sstp-models ioc-l9-subprotocols` — separate packages

## How to Release

### 1. Bump the version

Edit `pyproject.toml` and update the version:

```toml
[tool.poetry]
name = "ioc-l9-all-models"
version = "0.2.0"  # ← bump this
```

### 2. Commit and push

```bash
git add pyproject.toml
git commit -m "release: v0.2.0"
git push origin main
```

### 3. Tag and push the tag

```bash
git tag v0.2.0
git push origin v0.2.0
```

This triggers the automated publish workflow ([.github/workflows/publish.yaml](.github/workflows/publish.yaml)) which:
1. Builds and uploads Python packages to PyPI
2. Creates and pushes a Go module tag (`SSTP/language_bindings/golang/v0.2.0`)

### 4. Verify

Check the workflow run at: `https://github.com/outshift-open/ioc-protocols-models/actions/workflows/publish.yaml`

Once complete, verify:

**Python (PyPI):**
- https://pypi.org/project/ioc-l9-all-models/
- https://pypi.org/project/ioc-l9-subprotocols/

**Go (Module Tags):**
```bash
# Check published Go tags
git ls-remote --tags origin | grep "SSTP/language_bindings/golang"

# Verify Go module is accessible
go get github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang@v0.2.0
```

## Build Script (`scripts/package_models.sh`)

The build script assembles a temporary `ai/` namespace package tree from source protocol definitions, builds a wheel using Poetry, then cleans up.

### Modes

```bash
./scripts/package_models.sh --all          # Default: L9 root + SAB + TFP + SIEP + CIP
./scripts/package_models.sh --sstp         # Only SSTP root L9 models
./scripts/package_models.sh --subprotocol  # Only subprotocols (SAB, TFP, SIEP, CIP)
```

### Package Name Per Mode

Each mode produces a differently-named wheel by temporarily patching `pyproject.toml`:

| Mode | Package Name | Wheel File |
|------|-------------|------------|
| `--all` | `ioc-l9-all-models` | `dist/ioc_l9_all_models-<ver>-py3-none-any.whl` |
| `--sstp` | `ioc-l9-sstp-models` | `dist/ioc_l9_sstp_models-<ver>-py3-none-any.whl` |
| `--subprotocol` | `ioc-l9-subprotocols` | `dist/ioc_l9_subprotocols-<ver>-py3-none-any.whl` |

### How It Works

1. Patches `pyproject.toml` name field based on mode (creates `.bak` backup)
2. Creates temporary `ai/` directory with namespace package structure
3. Copies relevant `data_model.py` files from `SSTP/` source tree
4. Runs `poetry build -f wheel`
5. On exit (success or failure): removes `ai/` and restores `pyproject.toml` from backup

### Package Structure Per Mode

**--all (default)**
```
ai/
├── __init__.py
└── outshift/
    ├── __init__.py
    ├── data_model.py          ← SSTP root L9
    ├── sab/
    │   ├── __init__.py
    │   └── data_model.py      ← SAB subprotocol
    ├── tfp/
    │   ├── __init__.py
    │   └── data_model.py      ← TFP subprotocol
    ├── siep/
    │   ├── __init__.py
    │   └── data_model.py      ← SIEP subprotocol
    └── cip/
        ├── __init__.py
        └── data_model.py      ← CIP subprotocol
```

**--sstp**
```
ai/
├── __init__.py
└── outshift/
    ├── __init__.py
    └── data_model.py          ← SSTP root L9 only
```

**--subprotocol**
```
ai/
├── __init__.py
└── outshift/
    ├── __init__.py
    ├── sab/
    │   ├── __init__.py
    │   └── data_model.py      ← SAB subprotocol
    ├── tfp/
    │   ├── __init__.py
    │   └── data_model.py      ← TFP subprotocol
    ├── siep/
    │   ├── __init__.py
    │   └── data_model.py      ← SIEP subprotocol
    └── cip/
        ├── __init__.py
        └── data_model.py      ← CIP subprotocol
```

## Publish Workflow (`.github/workflows/publish.yaml`)

### Trigger

Runs on `v*` tag pushes (e.g. `v0.1.0`, `v1.2.3`). Also triggers on PRs to main for CI validation, but the publish jobs are skipped on PRs.

### Jobs

The workflow runs two jobs in parallel:

#### Job 1: `publish-python` (PyPI)

1. **Checkout** — clones the repo at the tagged commit
2. **Setup Python + Poetry** — installs Python 3.11 and Poetry 2.3.2
3. **Version validation** — ensures git tag (e.g. `v0.2.0`) matches `pyproject.toml` version (`0.2.0`). Fails fast if mismatched.
4. **Build wheels** — runs `package_models.sh --all`, producing the full package wheel in `dist/`
5. **Publish** — uploads wheel to PyPI using OIDC trusted publishing

#### Job 2: `publish-go` (Git Tags)

1. **Checkout** — clones the repo with full history
2. **Setup Go** — installs Go 1.21 and go-jsonschema
3. **Extract version** — derives version from the git tag (e.g., `v0.2.0` → `0.2.0`)
4. **Validate** — checks Go module path, bindings exist, and runs tests
5. **Create tag** — creates `SSTP/language_bindings/golang/v{version}` and pushes it (skips if already exists)

Both jobs run independently and in parallel for faster releases.

### Authentication

Uses PyPI **trusted publishing** (OIDC) — no API tokens or secrets needed. GitHub mints a short-lived token that PyPI trusts based on the repository and workflow configuration.

## One-Time PyPI Setup

Before the first release, register both packages as pending publishers on PyPI:

1. Go to https://pypi.org → **Your Account** → **Publishing** → **Add a new pending publisher**
2. Fill in for **each** package:

| Field | Value |
|-------|-------|
| Package name | `ioc-l9-all-models` (then repeat for `ioc-l9-subprotocols`) |
| Owner | `outshift-open` |
| Repository | `ioc-protocols-models` |
| Workflow name | `publish.yaml` |
| Environment | *(leave blank)* |

## Usage After Install

```python
# With ioc-l9-all-models (full package):
from ai.outshift.data_model import L9, L9Header, L9Payload
from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind
from ai.outshift.tfp.data_model import TFPOperation, TFPPayload
from ai.outshift.siep.data_model import SIEPPayload
from ai.outshift.cip.data_model import CIPPayload

# With ioc-l9-subprotocols (subprotocols only):
from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind
from ai.outshift.tfp.data_model import TFPOperation, TFPPayload
from ai.outshift.siep.data_model import SIEPPayload
from ai.outshift.cip.data_model import CIPPayload
```

## Adding a New Subprotocol

1. Create the language binding at:
   ```
   SSTP/subprotocol/<name>/language_bindings/python/ai/outshift/<name>/data_model.py
   ```

2. Add a new block in `scripts/package_models.sh` inside the `--subprotocol` section:
   ```bash
   mkdir -p "$PKG_DIR/outshift/<name>"
   touch "$PKG_DIR/outshift/<name>/__init__.py"
   cp "$REPO_ROOT/SSTP/subprotocol/<name>/language_bindings/python/ai/outshift/<name>/data_model.py" \
      "$PKG_DIR/outshift/<name>/data_model.py"
   ```

3. Bump the version in `pyproject.toml` and tag the release.

## Local Development

```bash
# Build and install locally for testing:
bash scripts/package_models.sh --all
pip install dist/ioc_l9_all_models-*.whl

# Run tests (builds wheel + runs pytest):
bash tests/language_bindings/python/run_tests.sh
```
