# Internet of Cognition (IOC) Protocols Models

Protocol definitions, language bindings, and tooling for the IOC L9 / SSTP protocol stack.

## Prerequisites

Before anything else, make sure you have these installed:

- Python 3.9+ with [Poetry](https://python-poetry.org/)
- Go 1.21+
- `go-jsonschema`: `go install github.com/atombender/go-jsonschema@latest`

## Quick Start

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

> **⚠️ Important:** Python wheel files (`.whl`) are not tracked in git. After `git pull` or cloning the repo, run `make build_wheels` to regenerate them before running tests.

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
├── SSTP/
│   ├── spec/l9_schema.json              # THE schema (single source of truth)
│   ├── language_bindings/
│   │   ├── python/
│   │   │   ├── generate.sh              # Generates models from schema
│   │   │   ├── pyproject.toml           # Wheel package definition
│   │   │   └── ai/outshift/data_model.py  # Generated models (from ai.outshift import data_model)
│   │   ├── golang/
│   │   │   ├── data_model.go            # Generated Go structs
│   │   │   └── go.mod                   # Go module definition
│   │   └── publish_bindings.sh          # Go module publisher (--tag to push)
│   ├── documentation/
│   │   ├── protocol_reference.html      # Generated HTML reference
│   │   ├── index.html                   # Docs landing page (created by publish)
│   │   └── config.json                  # Doc generator config
│   └── skills/                          # Hand-authored (not generated)
├── scripts/
│   ├── generate_artifacts.sh            # Full pipeline (generate + test)
│   ├── publish_artifacts.sh             # Publish docs + validate bindings
│   └── release_artifacts.sh             # Create git release tag
├── src/                                 # Pydantic source models
└── tests/language_bindings/             # Binding validation tests
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
| `make build_wheels` | Build all Python wheel packages (required after git pull) |
| `make clean` | Remove all generated files |
| `make print-version` | Print current schema version |

---

## Python Wheel Files

Python wheel files (`.whl`) are **not tracked in git** per OSPO compliance requirements. These files are:
- Generated from language bindings
- Required for running tests
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

The CI pipeline automatically builds these wheels before running tests.

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

## Release Workflow (Publishing a Version)

When you're ready to cut a release, run these 4 steps in order:

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
| `{version}` | `0.0.2` | Repository release tag |
| `SSTP/language_bindings/golang/v{version}` | `SSTP/language_bindings/golang/v0.0.2` | Go module tag (enables `go get`) |

---

## Python Wheel Usage (Consumers)

### Install the wheel:

```bash
pip install SSTP/language_bindings/python/ai_outshift_data_model-0.0.2-py3-none-any.whl
```

### Use in your code:

```python
from ai.outshift import data_model

msg = data_model.L9(
    header=data_model.L9Header(
        protocol="L9",
        subprotocol="SSTP",
        version="1.0",
        kind="message",
        subkind="chat",
        actors=data_model.Actors(
            actors=[data_model.Actor(id="actor-1", role="analyst")],
            groups=["team_alpha"],
        ),
    ),
    payload=data_model.L9Payload(
        type="text",
        data={"content": "Hello from L9!"},
    ),
)
```

### Rebuild the wheel after schema changes:

```bash
make generate_bindings LANGUAGE=python   # regenerate models
make build_wheel                         # build wheel (version from schema)
```

The wheel is output to `SSTP/language_bindings/python/` with the version from `make print-version`.

---

## Go Module Usage (Consumers)

### Install the module:

```bash
go get github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang@v0.0.2
```

> **Private repo:** You'll need `GOPRIVATE=github.com/cisco-eti/*` and SSH git access configured.
>
> **Public repo:** No extra config needed — `go get` works out of the box.

### Use in your code:

```go
import l9 "github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang"

msg := l9.L9SchemaJson{
    Header: l9.L9Header{
        Protocol:    "L9",
        Subprotocol: "SSTP",
        Version:     "1.0",
        Kind:        "message",
        Subkind:     "chat",
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

```bash
# Validate only (no tag created, nothing pushed)
make publish_bindings LANGUAGE=golang

# Validate + create + push the versioned git tag
./SSTP/language_bindings/publish_bindings.sh golang --tag
```

Tag format: `SSTP/language_bindings/golang/v{version}`

Without tagging, local development uses `replace` directives in `go.mod`:

```go
replace github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang => ../path/to/local/copy
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

The version lives in one place: `SSTP/spec/l9_schema.json` → `"version"` field.

```bash
# Print current version
make print-version

# Use in scripts
VERSION=$(make -s print-version)
```

---

## Skills

Skills live in `SSTP/skills/` and are **hand-authored**. They must be updated manually whenever the schema or bindings change.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
