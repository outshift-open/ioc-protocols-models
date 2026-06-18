# IOC L9 Protocol - Tooling

## Script Responsible
- **`scripts/generate_artifacts.sh`** - Generates internalartifacts
- **`scripts/publish_artifacts.sh`** - Publishes versioned artifacts for external consumption in ioc_l9_artifacts folder

## Creating a Release 
This includes invoking the generation pipeline to create artifacts (docs, bindings and skills) and publishing them, followed by creating a tagged release.
CI must ensure the order of the steps these are invoked in to ensure version consistency (Version is defined in `spec/json_schema/l9.json`)

### Consistent Version Workflow (Recommended for CI)
```bash
# Step 1: Get version once for consistency
VERSION=$(cd ioc_l9 && make -s print-version)
echo "Release version: $VERSION"

# Step 2: Generate artifacts
./scripts/generate_artifacts.sh

# Step 3: Publish artifacts with explicit version
./scripts/publish_artifacts.sh "$VERSION"

# Step 4: Create tagged release manually using same version
./scripts/release_artifacts.sh "$VERSION"
```

#### Consistency Benefits
Using explicit version parameters ensures:
- **Same version across all scripts** - No schema changes between executions
- **CI/CD reliability** - Version locked at pipeline start
- **Debugging capability** - Test with specific versions
- **Parallel execution safety** - Multiple jobs use same version


### Version Management Details

#### Version Sources
Scripts can get version information from two sources:
1. **Schema Version** (default): Extracted from `spec/json_schema/l9.json`
2. **Provided Version** (optional): Passed as script parameter

#### Version Parameter Support
Both publishing scripts support optional version parameters:

```bash
# Use schema version (automatic)
./scripts/publish_artifacts.sh
./scripts/release_artifacts.sh

# Use specific version (explicit)
./scripts/publish_artifacts.sh 1.2.3
./scripts/release_artifacts.sh 1.2.3

# Mixed usage (not recommended)
./scripts/publish_artifacts.sh 1.2.3  # specific
./scripts/release_artifacts.sh        # schema
```

#### Makefile Target to get Current Version
The unified version extraction is handled by a Makefile target:
```bash
# Get version from schema (with output)
cd ioc_l9 && make print-version

# Get version silently (for scripts)
VERSION=$(cd ioc_l9 && make -s print-version)
```

## IOC L9 Generation Pipeline Explained

### Complete Pipeline
Run the full generation and validation pipeline:
```bash
make all
```

### Cleanup
Clean generated files:
```bash
make clean          # Clean generated artifacts
```

### Language Bindings Generation Tools

The project uses different tools for generating type-safe language bindings:

- **Python**: [`datamodel-codegen`](https://github.com/koxudaxi/datamodel-code-generator) - Generates Pydantic v2 models from JSON Schema with validation
- **Golang**: [`go-jsonschema`](https://github.com/atombender/go-jsonschema) - Generates Go structs with JSON tags and validation

#### Usage

##### Generate Language Bindings

**Python bindings:**
```bash
make generate_bindings LANGUAGE=python
```

**Golang bindings:**
```bash
make generate_bindings LANGUAGE=golang
```

**All languages:**
```bash
make generate_bindings
```

#### Output

The script generates:
- `generated_models.py` - Pydantic v2 models with built-in validations

#### Validation

**Test Python bindings:**
```bash
make test_bindings LANGUAGE=python
```

**Test Golang bindings:**
```bash
make test_bindings LANGUAGE=golang
```

**Test all bindings:**
```bash
make test_bindings
```

The generated models include:
- Type validation based on the JSON Schema
- Field constraints and requirements

#### Cleanup

**Clean Python bindings:**
```bash
make clean_bindings LANGUAGE=python
```

**Clean Golang bindings:**
```bash
make clean_bindings LANGUAGE=golang
```

**Clean all bindings:**
```bash
make clean_bindings
```

### Skill Generation Tools

The project generates AI assistant skills from the protocol definitions:

- **Claude Skills**: Custom Python scripts that generate structured skill definitions for Claude AI assistants based on the IOC L9 protocol models

#### Environment Configuration

For enhanced skill generation with LLM support, configure the environment:

**Setup:**
```bash
# Copy the example configuration
cp skills/claude/.env.example skills/claude/.env

# Edit with your actual values
vi skills/claude/.env
```

**Required Configuration:**
```bash
# Required: API key for LLM service
LLM_API_KEY=your-api-key-here

# Model to use (supports OpenAI, Azure OpenAI, Bedrock)
LLM_MODEL=bedrock/global.anthropic.claude-sonnet-4-6

# Optional: Custom base URL for Azure OpenAI or other endpoints
LLM_BASE_URL=https://your-azure-endpoint.openai.azure.com/

# Optional: Temperature for generation (default: 0.3)
LLM_TEMPERATURE=0.3

# Optional: Max tokens for response (default: 5000)
LLM_MAX_TOKENS=5000
```

**Note:** Without LLM configuration, skills will be generated from `SKILL_root.md` templates only. With LLM configuration, skills are enhanced with schema-specific content and examples.

#### Usage

##### Generate Skills

**Claude skills:**
```bash
make generate_skills PLATFORM=claude
```

**All platforms:**
```bash
make generate_skills
```

#### Output

The script generates:
- `SKILL_generated.md` - Structured skill definitions for Claude AI assistants

#### Validation

**Test Claude skills:**
```bash
make test_skills PLATFORM=claude
```

**Test all skills:**
```bash
make test_skills
```

#### Cleanup

**Clean Claude skills:**
```bash
make clean_skills PLATFORM=claude
```

**Clean all skills:**
```bash
make clean_skills
```

### Documentation Generation Tools

The project generates interactive HTML documentation from the JSON Schema:

- **json-schema-for-humans**: Generates beautiful, interactive HTML documentation with navigation and examples

#### Usage

##### Generate Documentation

**Generate HTML docs:**
```bash
make generate_docs
```

#### Output

The script generates:
- `docs/generated/protocol_reference.html` - Interactive HTML documentation with schema navigation

#### Cleanup

**Clean generated docs:**
```bash
make clean_docs
```

## IOC L9 publishing Pipeline Explained

### Publishing Docs

Documentation publishing is handled by `docs/publish_docs.sh` which:
1. Generates HTML documentation from JSON schema using `json-schema-for-humans`
2. Copies required documentation files to artifact folder (configured in Makefile). The documents in Artifacts folder are meant to be consumed by external users.
3. Creates version metadata and artifact index

#### Usage
```bash
# Via Makefile
make publish_docs
```

### Publishing Skills

Skills publishing is handled by `skills/publish_skills.sh` which:
1. which can selectively publish skills generated to the artifacts folder fpr external consumption

#### Usage
```bash
# Via Makefile

# Publish specific language
make publish_skills PLATFORM=claude

# Publish skills for all platforms (default)
make publish_skills
```

### Publishing Bindings
1. which can selectively publish bindings generated to the artifacts folder for external consumption

#### Usage
```bash
# Publish specific language
make publish_bindings LANGUAGE=python
make publish_bindings LANGUAGE=golang

# Publish all languages (default)
make publish_bindings
```

#### Publishing Requirements

##### For Python (PyPI)
- **Authentication**: PyPI API token configured
  ```bash
  poetry config pypi-token.pypi your-api-token
  ```
- **Package Name**: `ioc-l9` (configured in `pyproject.toml`)
- **PyPI Publishing**: Publishes to PyPI registry

##### For Go Module
- **Git Access**: Push permissions to the repository
- **Module Path**: `github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang`
- **Go Module Publishing**: Uses Git tags for versioning

#### Listing Published Go Modules
To see all published Go module versions:
```bash
# List all Go module tags
git ls-remote --tags origin | grep "ioc_l9/language_bindings/golang"

# Check specific version availability
go list -m github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0
```

#### Pre-Publishing Validation
The system runs comprehensive tests before publishing:
- **Python**: `make test_bindings LANGUAGE=python`
- **Go**: `make test_bindings LANGUAGE=golang`
- **Validation**: Model validation, serialization, and deserialization tests

## IOC L9 artifact Versioning Explained

### Version Management
- **Uses dual Git tags** for proper Go module support:
  - Repository tag: `{version}` (e.g., `1.0.0`) for the complete release
  - Go module tag: `ioc_l9/language_bindings/golang/v{version}` (e.g., `ioc_l9/language_bindings/golang/v1.0.0`) for Go module versioning
- **Single Source of Truth**: Version is defined in `spec/json_schema/l9.json`
- **Version Metadata**: created as part of publishing artifacts
- **Python Package**: References repository tag for source code linking
- **Go Module**: Uses module-specific tag for proper versioning
  ```bash
  go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0
  ```

## CI Integration

This section provides complete GitHub Actions workflows for integrating IOC L9 Protocol tooling into your CI/CD pipeline.

### Automated Artifact Publishing Workflow

This workflow triggers on spec file PRs, generates artifacts, publishes them, and creates a PR for approval:

```yaml
name: Automated IOC L9 Artifact Publishing

on:
  pull_request:
    branches: [ main ]
    paths:
      - 'ioc_l9/spec/json_schema/l9.json'
    types: [ opened, synchronize ]

jobs:
  generate-and-publish-artifacts:
    runs-on: ubuntu-latest
    if: github.event.pull_request.draft == false
    
    steps:
    - name: Checkout PR branch
      uses: actions/checkout@v4
      with:
        ref: ${{ github.event.pull_request.head.ref }}
        fetch-depth: 0
        
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
        
    - name: Set up Go
      uses: actions/setup-go@v4
      with:
        go-version: '1.21'
        
    - name: Install Poetry
      uses: snok/install-poetry@v1
      with:
        version: latest
        virtualenvs-create: true
        virtualenvs-in-project: true
        
    - name: Install dependencies
      run: |
        cd ioc_l9
        poetry install
        
    - name: Get version from spec
      id: version
      run: |
        cd ioc_l9
        VERSION=$(make -s print-version)
        echo "version=$VERSION" >> $GITHUB_OUTPUT
        echo "Detected version: $VERSION"
        
    - name: Generate artifacts
      run: |
        cd ioc_l9
        ./scripts/generate_artifacts.sh
        
    - name: Configure PyPI authentication (optional if we want to publish to PyPI)
      env:
        PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}
      run: |
        cd ioc_l9
        poetry config pypi-token.pypi $PYPI_TOKEN
        
    - name: Publish artifacts
      run: |
        cd ioc_l9
        ./scripts/publish_artifacts.sh "${{ steps.version.outputs.version }}"
        
    - name: Commit all generated artifacts to PR branch
      run: |
        cd ioc_l9
        # Configure git
        git config --local user.email "action@github.com"
        git config --local user.name "IOC L9 Artifact Bot"
        
        # Add all generated files from generate_artifacts.sh and publish_artifacts.sh
        git add ioc_l9_artifacts/                                    # Published artifacts (docs, skills)
        git add language_bindings/python/generated_models.py        # Generated Python bindings
        git add language_bindings/golang/generated_models.go        # Generated Go bindings
        git add skills/*/SKILL_generated.md                         # Generated skills
        git add docs/generated/                                      # Generated documentation
        
        # Check if there are any changes to commit
        if git diff --staged --quiet; then
          echo "No changes to commit - artifacts are up to date"
          exit 0
        fi
        
        git commit -m "🤖 Auto-generate and publish artifacts for IOC L9 Protocol v${{ steps.version.outputs.version }}

        Generated Files:
        - Language bindings: Python (generated_models.py) and Go (generated_models.go)
        - Skills: Claude AI skills (SKILL_generated.md)
        - Documentation: HTML docs in docs/generated/
        
        Published Artifacts:
        - Documentation artifacts: ioc_l9_artifacts/docs/
        - Skills artifacts: ioc_l9_artifacts/skills/
        - Python package published to PyPI: ioc-l9==${{ steps.version.outputs.version }}
        - Go module ready for tagging at v${{ steps.version.outputs.version }}
        
        Generated from spec: ${{ github.event.pull_request.head.sha }}"
        
        # Push to the existing PR branch
        git push origin ${{ github.event.pull_request.head.ref }}
        
    - name: Comment on PR with artifact status
      uses: actions/github-script@v7
      with:
        github-token: ${{ secrets.GITHUB_TOKEN }}
        script: |
          await github.rest.issues.createComment({
            owner: context.repo.owner,
            repo: context.repo.repo,
            issue_number: ${{ github.event.pull_request.number }},
            body: `## 🤖 Artifacts Generated & Published!

          Your spec changes have triggered automatic artifact generation and publishing.

          ### Generated Files Added to PR ⚡
          - **Language Bindings**: \`generated_models.py\` (Python) and \`generated_models.go\` (Go)
          - **Skills**: Claude AI skills (\`SKILL_generated.md\` files)
          - **Documentation**: HTML docs in \`docs/generated/\`

          ### Published Artifacts ✅
          - **Python Package**: \`ioc-l9==${{ steps.version.outputs.version }}\` published to PyPI
          - **Go Module**: Ready for tagging at \`v${{ steps.version.outputs.version }}\`

          ### Repository Artifacts 📁
          - **Documentation**: Available in \`ioc_l9_artifacts/docs/\`
          - **Skills**: Available in \`ioc_l9_artifacts/skills/\`

          ### What's Included in This PR
          ✅ **Spec Changes**: Your original modifications to \`l9.json\`  
          ✅ **Generated Code**: Language bindings automatically generated from spec  
          ✅ **Generated Skills**: AI assistant skills for the updated protocol  
          ✅ **Published Artifacts**: Ready-to-use documentation and skill packages  
          ✅ **External Publishing**: Python package live on PyPI, Go module ready for tagging

          ### Next Steps
          1. **Review** all generated files and artifacts in this PR
          2. **Merge** this PR to accept spec changes + generated artifacts  
          3. **Tag release** using: \`v${{ steps.version.outputs.version }}\`

          *All artifacts automatically generated and committed by IOC L9 Publishing workflow.*`
          });
```

### Required Secrets

Configure these secrets in your GitHub repository settings:

- **`PYPI_TOKEN`**: PyPI API token for publishing Python packages
- **`GITHUB_TOKEN`**: Automatically provided by GitHub Actions