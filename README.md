# Internet of Cognition (IOC) Protocols Models

[![Contributor-Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-fbab2c.svg)](CODE_OF_CONDUCT.md)
[![Maintainer](https://img.shields.io/badge/Maintainer-Cisco-00bceb.svg)](https://opensource.cisco.com)
[![PyPI](https://img.shields.io/pypi/v/ioc-l9-all-models)](https://pypi.org/project/ioc-l9-all-models/)
[![Python](https://img.shields.io/pypi/pyversions/ioc-l9-all-models)](https://pypi.org/project/ioc-l9-all-models/)

Protocol definitions, language bindings, and tooling for the IOC L9 / SSTP protocol stack.

## About The Project

Cisco Outshift is releasing the Internet of Cognition (IoC) software stack. Since the advent of agentic AI and multi-agentic systems, standard protocols like A2A/MCP have been defined to run on top of Layer 7 protocols such as HTTP. These protocols are referred to as Layer 8.

One of the key hypotheses within the IoC initiative is that a new protocol layer is required on top of the existing Layer 8 protocols to deal with the semantic and cognition aspects of multi-agentic systems. This new protocol layer is named Layer 9 (L9).

This repository contains:
- L9 protocol JSON schema specifications
- Language bindings for Python and Go
- PyPI packages for Python consumers
- Documentation and examples
- Subprotocols: SIEP (Semantic Interoperability and Epistemic Protocol), CIP (Cognition and Interoperability Protocol), SAB (Semantic Alignment Broadcast), TFP (Team Formation via Polling)
- SKILL file representations for autonomous agentic frameworks (OpenClaw, Claude, Codex)

---

## Python Package (PyPI)

The protocol models are published to [PyPI](https://pypi.org/project/ioc-l9-all-models/) for easy consumption of L9 and subprotocol models:

### Install

```bash
pip install ioc-l9-all-models
```

### Quick Start

```python
# import L9 protocol models
from ai.outshift.data_model import L9, L9Header, L9Payload, Message, Actor, ParticipantSet, Kind

# import SAB subprotocol models
# from ai.outshift.sab.data_model import SAB, SABActors, SABHeader, SABPayload, SABIntentPayloadData

# Create an L9 message
msg = L9(
    header=L9Header(
        protocol="SSTP",
        subprotocol="TFP",
        version="1.0",
        kind=Kind.intent,
        subkind="",
        participants=ParticipantSet(
            actors=[Actor(id="actor-1", role="analyst")],
            groups={"team_alpha": ["actor-1"]},
        ),
    ),
    payload=L9Payload(
        type="text",
        data={"content": "Hello from L9!"},
    ),
)

print(msg.model_dump_json(indent=2))
```

### Requirements

- Python >= 3.10, < 3.14
- pydantic >= 2.0

---

## Getting Started (Development)

### Prerequisites

Before anything else, make sure you have these installed:

- Python 3.10+ with [Poetry](https://python-poetry.org/)
- Go 1.21+ (only if generating Go bindings)
- `go-jsonschema`: `go install github.com/atombender/go-jsonschema@latest` (only if generating Go bindings)

### Development Setup

```bash
# After cloning or pulling latest changes, build the wheel files first:
make build_wheels             # Build Python wheels (required for tests)

# Generate all bindings + docs + run tests (one command does everything)
make all

# Or step by step:
make generate_bindings        # Python + Go bindings from schema
make generate_docs            # HTML documentation
make test_bindings            # Validate generated code
```

> **Important:** Python wheel files (`.whl`) are not tracked in git. After `git pull` or cloning the repo, run `make build_wheels` to regenerate them before running tests.

---

## How It Works

Everything is driven from a single source of truth:

```
SSTP/spec/l9_schema.json  →  generates  →  Python models + Go structs + HTML docs
```

You edit the schema, then run the tooling to regenerate everything else.

---

## Project Structure

```
.
├── Makefile                              # All build targets (start here)
├── pyproject.toml                        # PyPI package definition (ioc-l9-all-models)
├── PACKAGE.md                            # PyPI package long description
├── PUBLISHING.md                         # PyPI publish guide
├── SSTP/
│   ├── spec/l9_schema.json              # THE schema (single source of truth)
│   ├── language_bindings/
│   │   ├── python/
│   │   │   ├── generate.sh              # Generates models from schema
│   │   │   ├── pyproject.toml           # Wheel package definition
│   │   │   └── ai/outshift/data_model.py  # Generated models
│   │   ├── golang/
│   │   │   ├── data_model.go            # Generated Go structs
│   │   │   └── go.mod                   # Go module definition
│   │   └── publish_bindings.sh          # Go module publisher (--tag to push)
│   ├── subprotocol/
│   │   ├── sab/                         # Semantic Alignment Broadcast
│   │   ├── tfp/                         # Team Formation via Polling
│   │   ├── siep/                        # Semantic Interoperability and Epistemic Protocol
│   │   └── cip/                         # Cognition and Interoperability Protocol
│   ├── documentation/
│   │   ├── protocol_reference.html      # Generated HTML reference
│   │   ├── index.html                   # Docs landing page
│   │   └── config.json                  # Doc generator config
│   ├── examples/                        # A2A + L9 demo scripts
│   └── skills/                          # Hand-authored (not generated)
├── scripts/
│   ├── generate_artifacts.sh            # Full pipeline (generate + test)
│   ├── publish_artifacts.sh             # Publish docs + validate bindings
│   ├── release_artifacts.sh             # Create git release tag
│   ├── package_models.sh               # Build distributable PyPI wheels
│   ├── build_wheels.sh                  # Build all development wheels
│   └── unit-test.sh                     # Run unit tests
├── src/                                 # Pydantic source models (epistemic, primitives, state_mgmt)
└── tests/                               # Binding validation tests
```

---

## Makefile Targets

| Target | What it does |
|--------|-------------|
| `make all` | Full pipeline: validate schema → generate bindings + docs → run tests |
| `make generate_bindings` | Generate all language bindings (or `LANGUAGE=python\|golang`) |
| `make generate_docs` | Generate HTML docs into `SSTP/documentation/` |
| `make test_bindings` | Run binding tests (or `LANGUAGE=python\|golang`) |
| `make publish_docs` | Finalize docs (create index.html + version metadata) |
| `make publish_bindings` | Validate bindings (use script with `--tag` for git tagging) |
| `make build_wheel` | Build Python wheel (ai-outshift-data-model) |
| `make build_sab_wheel` | Build Python wheel (ai-outshift-sab-data-model) |
| `make build_tfp_wheel` | Build Python wheel (ai-outshift-tfp-data-model) |
| `make build_siep_wheel` | Build Python wheel (ai-outshift-subprotocols-siep) |
| `make build_cip_wheel` | Build Python wheel (ai-outshift-subprotocols-cip) |
| `make build_wheels` | Build all Python wheels (required after git pull) |
| `make pkg_model` | Build distributable wheel (`package_models.sh --all`) |
| `make clean` | Remove all generated files |
| `make print-version` | Print current schema version |

---

## Python Wheel Files (Local Development Only)

> **Note:** These wheels are for local development and testing only. End users should install from PyPI with `pip install ioc-l9-all-models`.

Python wheel files (`.whl`) are **not tracked in git** per OSPO compliance requirements. These files are:
- Generated from language bindings
- Required for running local tests
- Automatically ignored by `.gitignore`

### After Git Pull or Clone

```bash
# Regenerate wheel files (required before running tests)
make build_wheels
```

This will build:
- `SSTP/language_bindings/python/ai_outshift_data_model-*.whl`
- `SSTP/subprotocol/sab/language_bindings/python/ai_outshift_sab_data_model-*.whl`
- `SSTP/subprotocol/tfp/language_bindings/python/ai_outshift_tfp_data_model-*.whl`
- `SSTP/subprotocol/siep/language_bindings/python/ai_outshift_subprotocols_siep-*.whl`
- `SSTP/subprotocol/cip/language_bindings/python/ai_outshift_subprotocols_cip-*.whl`

The CI pipeline automatically builds these wheels before running tests.

### Install a Wheel Locally

```bash
pip install SSTP/language_bindings/python/ai_outshift_data_model-0.0.2-py3-none-any.whl
```

### Rebuild After Schema Changes

```bash
make generate_bindings LANGUAGE=python   # regenerate models
make build_wheel                         # build wheel (version from schema)
```

---

## Day-to-Day Development

### 1. Edit the schema

Make your changes in `SSTP/spec/l9_schema.json`. Bump the `"version"` field if this is a new release.

### 2. Regenerate everything

```bash
make all
```

This validates the schema, regenerates Python + Go bindings, generates docs, and runs all tests. If it passes, you're good.

### 3. Run tests independently (optional)

```bash
make test_bindings                       # All languages
make test_bindings LANGUAGE=python       # Python only
make test_bindings LANGUAGE=golang       # Go only
```

### 4. Generate specific things (optional)

```bash
make generate_bindings LANGUAGE=python   # Just Python
make generate_bindings LANGUAGE=golang   # Just Go
make generate_docs                       # Just docs
```

---

## Release Workflow (Full)

When you're ready to cut a release, run these steps in order:

```bash
# Step 0: Get the version from the schema
VERSION=$(make -s print-version)

# Step 1: Generate + validate everything (bindings, docs, tests)
./scripts/generate_artifacts.sh

# Step 2: Build the Python wheel (version stamped from schema)
make build_wheel

# Step 3: Publish artifacts (finalize docs, validate bindings)
./scripts/publish_artifacts.sh "$VERSION"

# Step 4: Create the repository git tag (e.g. 0.0.2)
./scripts/release_artifacts.sh "$VERSION"

# Step 5: Create the Go module tag and push it
./SSTP/language_bindings/publish_bindings.sh golang --tag
```

After this, two tags exist on the remote:

| Tag | Example | Purpose |
|-----|---------|---------|
| `v{version}` | `v0.0.2` | PyPI publish trigger + repository release |
| `SSTP/language_bindings/golang/v{version}` | `SSTP/language_bindings/golang/v0.0.2` | Go module tag (enables `go get`) |

---

## Go Module Usage (Consumers)

### Install the module:

```bash
go get github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang@v0.0.2
```

> **Private repo:** You'll need `GOPRIVATE=github.com/outshift-open/*` and SSH git access configured.
>
> **Public repo:** No extra config needed — `go get` works out of the box.

### Use in your code:

```go
import l9 "github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang"

msg := l9.L9SchemaJson{
    Header: l9.L9Header{
        Protocol:    "SSTP",
        Subprotocol: "TFP",
        Version:     "1.0",
        Kind:        "intent",
        Subkind:     "",
        Actors: l9.Actors{
            Actors: []l9.Actor{{ID: "actor-1", Role: "analyst"}},
            Groups: []string{"team_alpha"},
        },
    },
    Payload: l9.L9Payload{
        Type: "text",
        Data: l9.L9PayloadData{"content": "Hello from L9!"},
    },
}
```

### Check published versions:

```bash
git ls-remote --tags origin | grep "SSTP/language_bindings/golang"
```

---

## Go Module Publishing (Maintainers)

Go modules are published via GitHub Actions workflow. Two methods available:

### GitHub Actions (Recommended)

1. Go to **Actions** → **"Publish Go Module Bindings"**
2. Click **"Run workflow"**
3. Optionally specify version (or use schema version)
4. Creates tag: `SSTP/language_bindings/golang/v{version}`

See [`.github/workflows/publish-go-bindings.yaml`](.github/workflows/publish-go-bindings.yaml) for details.

### Command Line (Alternative)

```bash
# Validate only (no tag created, nothing pushed)
make publish_bindings LANGUAGE=golang

# Validate + create + push the versioned git tag
./SSTP/language_bindings/publish_bindings.sh golang --tag
```

### Local Development

Without tagging, local development uses `replace` directives in `go.mod`:

```go
replace github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang => ../path/to/local/copy
```

---

## Documentation

```bash
make generate_docs    # Generate HTML reference from schema
make publish_docs     # Create index.html + finalize in SSTP/documentation/
make clean_docs       # Remove generated doc files
```

Output: `SSTP/documentation/protocol_reference.html`

---

## Cleaning Up

```bash
make clean                               # Remove all generated files
make clean_bindings                      # Just bindings (or LANGUAGE=python|golang)
make clean_docs                          # Just docs
make clean_pycache                       # Python __pycache__ dirs
```

---

## Version Management

The version lives in one place: `pyproject.toml` → `version` field.

```bash
# Print current version
make print-version

# Use in scripts
VERSION=$(make -s print-version)
```

---

## Skills

Skills live in `SSTP/skills/` and are **hand-authored**. They must be updated manually whenever the schema or bindings change.

## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**. For detailed contributing guidelines, please see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Distributed under the Apache License 2.0. See [LICENSE.md](LICENSE.md) for more information.

## Contact

Project Link: [https://github.com/outshift-open/ioc-protocols-models](https://github.com/outshift-open/ioc-protocols-models)