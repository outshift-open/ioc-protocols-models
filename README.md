# IOC Protocols Models

Protocol definitions, language bindings, and tooling for the IOC L9 / SSTP protocol stack.

## Prerequisites

Before anything else, make sure you have these installed:

- Python 3.9+ with [Poetry](https://python-poetry.org/)
- Go 1.21+
- `go-jsonschema`: `go install github.com/atombender/go-jsonschema@latest`

## Quick Start

```bash
# Generate all bindings + docs + run tests (one command does everything)
make all

# Or step by step:
make generate_bindings        # Python + Go bindings from schema
make generate_docs            # HTML documentation
make test_bindings            # Validate generated code
```

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
│   │   ├── python/generated_models.py   # Generated Pydantic v2 models
│   │   ├── golang/
│   │   │   ├── generated_models.go      # Generated Go structs
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
| `make clean` | Remove all generated files |
| `make print-version` | Print current schema version |

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

# Step 2: Publish artifacts (finalize docs, validate bindings)
./scripts/publish_artifacts.sh "$VERSION"

# Step 3: Create the repository git tag (e.g. 0.0.2)
./scripts/release_artifacts.sh "$VERSION"

# Step 4: Create the Go module tag and push it
./SSTP/language_bindings/publish_bindings.sh golang --tag
```

After this, two tags exist on the remote:

| Tag | Example | Purpose |
|-----|---------|---------|
| `{version}` | `0.0.2` | Repository release tag |
| `SSTP/language_bindings/golang/v{version}` | `SSTP/language_bindings/golang/v0.0.2` | Go module tag (enables `go get`) |

---

## Go Module Usage (Consumers)

### For private repo access, configure git + Go:

```bash
# In ~/.gitconfig — rewrite HTTPS to SSH for private repos
[url "git@github.com:"]
    insteadOf = https://github.com/

# In your shell profile — tell Go this is private
export GOPRIVATE=github.com/cisco-eti/*
```

### Install the module:

```bash
go get github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang@v0.0.2
```

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
