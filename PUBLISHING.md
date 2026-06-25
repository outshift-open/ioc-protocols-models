# Publishing to PyPI

This document covers how the build and publish pipeline works for the ai.outshift protocol model packages.

## Overview

This repo publishes three packages to PyPI:

| Package | Install | Contents |
|---------|---------|----------|
| `ai-outshift-all-models` | `pip install ai-outshift-all-models` | SSTP root L9 + all subprotocols (SAB, TFP, SIEP, CIP) |
| `ai-outshift-sstp-models` | `pip install ai-outshift-sstp-models` | Only SSTP root L9 models |
| `ai-outshift-subprotocols` | `pip install ai-outshift-subprotocols` | Only subprotocols (SAB, TFP, SIEP, CIP) |

### Dependencies Between Packages

```
ai-outshift-all-models          ← everything in one package (recommended)

ai-outshift-subprotocols        ← SAB + TFP + SIEP + CIP subprotocols
  └── requires: ai-outshift-sstp-models   (SAB imports L9Header, L9Payload, Actor, Context)

ai-outshift-sstp-models         ← standalone SSTP root L9 models
```

> **Note:** The SAB subprotocol imports from the root L9 models (`ai.outshift.data_model`).
> If you install `ai-outshift-subprotocols`, you must also install `ai-outshift-sstp-models`:
> ```bash
> pip install ai-outshift-sstp-models ai-outshift-subprotocols
> ```
> Or just use `ai-outshift-all-models` which bundles everything.
> TFP has no dependency on the root models and works standalone.

> **Warning:** Do NOT install `ai-outshift-all-models` alongside `ai-outshift-subprotocols` or
> `ai-outshift-sstp-models`. They ship overlapping files and uninstalling one may break the other.
>
> Pick one approach:
> - `pip install ai-outshift-all-models` — everything in one package (simplest)
> - `pip install ai-outshift-sstp-models ai-outshift-subprotocols` — separate packages

## How to Release

### 1. Bump the version

Edit `pyproject.toml` and update the version:

```toml
[tool.poetry]
name = "ai-outshift-all-models"
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

This triggers the publish workflow which builds and uploads both packages to PyPI.

### 4. Verify

Check the workflow run at: `https://github.com/outshift-open/ioc-protocols-models/actions/workflows/publish.yaml`

Once complete, verify on PyPI:
- https://pypi.org/project/ai-outshift-all-models/
- https://pypi.org/project/ai-outshift-subprotocols/

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
| `--all` | `ai-outshift-all-models` | `dist/ai_outshift_all_models-<ver>-py3-none-any.whl` |
| `--sstp` | `ai-outshift-sstp-models` | `dist/ai_outshift_sstp_models-<ver>-py3-none-any.whl` |
| `--subprotocol` | `ai-outshift-subprotocols` | `dist/ai_outshift_subprotocols-<ver>-py3-none-any.whl` |

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

Runs on `v*` tag pushes (e.g. `v0.1.0`, `v1.2.3`). Also triggers on PRs to main for CI validation, but the publish job is skipped on PRs.

### Steps

1. **Checkout** — clones the repo at the tagged commit
2. **Setup Python + Poetry** — installs Python 3.11 and Poetry 2.3.2
3. **Version validation** — ensures git tag (e.g. `v0.2.0`) matches `pyproject.toml` version (`0.2.0`). Fails fast if mismatched.
4. **Build wheels** — runs `package_models.sh --all`, `--sstp`, and `--subprotocol`, producing three wheels in `dist/`
5. **Publish** — uploads all wheels in `dist/` to PyPI using OIDC trusted publishing

### Authentication

Uses PyPI **trusted publishing** (OIDC) — no API tokens or secrets needed. GitHub mints a short-lived token that PyPI trusts based on the repository and workflow configuration.

## One-Time PyPI Setup

Before the first release, register both packages as pending publishers on PyPI:

1. Go to https://pypi.org → **Your Account** → **Publishing** → **Add a new pending publisher**
2. Fill in for **each** package:

| Field | Value |
|-------|-------|
| Package name | `ai-outshift-all-models` (then repeat for `ai-outshift-subprotocols`) |
| Owner | `outshift-open` |
| Repository | `ioc-protocols-models` |
| Workflow name | `publish.yaml` |
| Environment | *(leave blank)* |

## Usage After Install

```python
# With ai-outshift-all-models (full package):
from ai.outshift.data_model import L9, L9Header, L9Payload
from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind
from ai.outshift.tfp.data_model import TFPOperation, TFPPayload
from ai.outshift.siep.data_model import SIEPPayload
from ai.outshift.cip.data_model import CIPPayload

# With ai-outshift-subprotocols (subprotocols only):
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
pip install dist/ai_outshift_all_models-*.whl

# Run tests (builds wheel + runs pytest):
bash tests/language_bindings/python/run_tests.sh
```
