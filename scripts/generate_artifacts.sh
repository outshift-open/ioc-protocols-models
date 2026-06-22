#!/usr/bin/env bash
# generate_artifacts.sh - IOC L9 Protocol Pipeline Script
#
# Orchestrates the complete pipeline from schema validation to testing:
#
# PIPELINE STAGES:
# 1. Schema Validation - Validates JSON schema syntax and structure
# 2. Language Bindings Generation - Generates Python (Pydantic) and Go bindings
# 3. Documentation Updates - Generates HTML documentation
# 4. Comprehensive Testing - Runs validation tests for all generated components
#
# USAGE:
#   ./scripts/generate_artifacts.sh    # Run complete pipeline
#   make all                          # Run via Makefile (recommended)

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

handle_error() {
    local exit_code=$?
    local line_number=$1
    log_error "Script failed at line $line_number with exit code $exit_code"
    log_error "Pipeline terminated due to failure"
    exit $exit_code
}

trap 'handle_error $LINENO' ERR

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Verify we're in the correct project structure
if [ ! -f "$PROJECT_ROOT/pyproject.toml" ] || [ ! -d "$PROJECT_ROOT/SSTP" ]; then
    echo "Error: Not in project root. Expected structure:"
    echo "  - pyproject.toml (Poetry config)"
    echo "  - SSTP/ (protocol directory)"
    echo "Current directory: $PROJECT_ROOT"
    exit 1
fi

cd "$PROJECT_ROOT"

main() {
    log_step "IOC L9 Protocol - Pipeline"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Starting pipeline..."

    # Step 1: Check if JSON schema exists
    log_step "Step 1: Validating JSON Schema"
    check_json_schema

    # Step 2: Update Poetry lock if needed
    log_step "Step 2: Updating Dependencies"
    update_poetry_lock

    # Step 3: Generate language bindings
    log_step "Step 3: Generating Language Bindings"
    generate_bindings

    # Step 4: Generate documentation
    log_step "Step 4: Generating Documentation"
    generate_docs

    # Step 5: Run comprehensive tests
    log_step "Step 5: Running Tests"
    run_tests

    # Success summary
    log_step "Pipeline Completed Successfully"
    log_success "All checks passed!"
    log_success "  JSON schema validated"
    log_success "  Dependencies updated"
    log_success "  Language bindings generated"
    log_success "  Documentation generated"
    log_success "  All tests passed"

    return 0
}

check_json_schema() {
    local schema_path="SSTP/spec/l9_schema.json"

    log_info "Checking JSON schema at: $schema_path"

    if [ ! -f "$schema_path" ]; then
        log_error "JSON schema not found at: $schema_path"
        exit 1
    else
        log_info "JSON schema found, validating..."
    fi

    local python_cmd="python3"
    if ! command -v python3 &> /dev/null; then
        if command -v python &> /dev/null; then
            python_cmd="python"
        else
            log_error "Python not found. Please install Python to validate JSON schema."
            exit 1
        fi
    fi

    if ! $python_cmd -m json.tool "$schema_path" > /dev/null 2>&1; then
        log_error "Invalid JSON syntax in schema file"
        exit 1
    fi

    if ! grep -q '"title": "L9"' "$schema_path"; then
        log_error "Schema missing required L9 title"
        exit 1
    fi

    if ! grep -q '"\$defs"' "$schema_path"; then
        log_error "Schema missing required \$defs section"
        exit 1
    fi

    log_success "JSON schema validation passed"
}

update_poetry_lock() {
    log_info "Checking Poetry dependencies..."

    if [ ! -f "poetry.lock" ] || [ "pyproject.toml" -nt "poetry.lock" ]; then
        log_info "Updating Poetry lock file..."

        if ! poetry lock; then
            log_error "Failed to update Poetry lock file"
            exit 1
        fi

        log_success "Poetry lock file updated"
    else
        log_info "Poetry lock file is up to date"
    fi

    log_info "Installing dependencies..."
    if ! poetry install --with dev; then
        log_error "Failed to install dependencies"
        exit 1
    fi

    log_success "Dependencies installed successfully"
}

generate_bindings() {
    log_info "Generating language bindings for all languages..."

    if ! make generate_bindings; then
        log_error "Failed to generate language bindings"
        exit 1
    fi

    local python_bindings="SSTP/language_bindings/python/generated_models.py"
    local golang_bindings="SSTP/language_bindings/golang/generated_models.go"

    if [ ! -f "$python_bindings" ]; then
        log_error "Python bindings not generated: $python_bindings"
        exit 1
    fi

    if [ ! -f "$golang_bindings" ]; then
        log_error "Golang bindings not generated: $golang_bindings"
        exit 1
    fi

    log_success "Language bindings generated successfully"
}

generate_docs() {
    log_info "Generating HTML documentation from JSON schema..."

    if ! make generate_docs; then
        log_error "Failed to generate documentation"
        exit 1
    fi

    local docs_file="SSTP/documentation/generated/protocol_reference.html"
    if [ ! -f "$docs_file" ]; then
        log_error "Documentation not generated: $docs_file"
        exit 1
    fi

    log_success "Documentation generated successfully"
}

run_tests() {
    log_info "Running comprehensive test suite..."

    if ! make test_bindings; then
        log_error "Language binding tests failed"
        exit 1
    fi

    log_success "All tests passed successfully"
}

main "$@"
