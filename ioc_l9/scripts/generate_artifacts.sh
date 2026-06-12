#!/usr/bin/env bash
# generate_artifacts.sh - IOC L9 Protocol Pipeline Script
#
# This script provides comprehensive automation for the IOC L9 Protocol project.
# It orchestrates the complete pipeline from schema validation to testing:
#
# PIPELINE STAGES:
# 1. Schema Validation - Validates JSON schema syntax and structure
# 2. Language Bindings Generation - Generates Python (Pydantic) and Go bindings
# 3. Skills Generation - Creates Claude AI assistant skills from protocol definitions
# 4. Comprehensive Testing - Runs validation tests for all generated components
# 5. Documentation Updates - Ensures all generated files are properly documented
#
# FEATURES:
# - Fail-fast execution with proper exit codes
# - Colored output with clear status indicators
# - Comprehensive error reporting and logging
# - Path-independent execution (works from any directory)
# - Makefile integration for consistent builds
#
# USAGE:
#   ./scripts/generate_artifacts.sh    # Run complete pipeline
#   make all                          # Run via Makefile (recommended)
#
# EXIT CODES:
#   0 - Success (all pipeline stages passed)
#   1 - Failure (pipeline stage failed with details)
#   1 - Failure (terminates pipeline)

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

# Error handler
handle_error() {
    local exit_code=$?
    local line_number=$1
    log_error "Script failed at line $line_number with exit code $exit_code"
    log_error "pipeline terminated due to failure"
    exit $exit_code
}

# Set up error handling
trap 'handle_error $LINENO' ERR

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Verify we're in the correct project structure
if [ ! -f "$PROJECT_ROOT/pyproject.toml" ] || [ ! -d "$PROJECT_ROOT/ioc_l9" ]; then
    echo "Error: Not in IOC L9 project root. Expected structure:"
    echo "  - pyproject.toml (Poetry config)"
    echo "  - ioc_l9/ (main package directory)"
    echo "Current directory: $PROJECT_ROOT"
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Main CI pipeline
main() {
    log_step "IOC L9 Protocol - Pipeline"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Starting continuous integration checks..."
    
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
    
    # Step 5: Generate skills
    log_step "Step 5: Generating Skills"
    generate_skills
    
    # Step 6: Run comprehensive tests
    log_step "Step 6: Running Tests"
    run_tests
    
    # Success summary
    log_step "Pipeline Completed Successfully"
    log_success "All checks passed!"
    log_success "✅ JSON schema validated"
    log_success "✅ Dependencies updated"
    log_success "✅ Language bindings generated"
    log_success "✅ Documentation generated"
    log_success "✅ Skills generated"
    log_success "✅ All tests passed"
    
    return 0
}

# Step 1: Check if JSON schema exists and is valid
check_json_schema() {
    local schema_path="ioc_l9/spec/json_schema/l9.json"
    
    log_info "Checking JSON schema at: $schema_path"
    
    if [ ! -f "$schema_path" ]; then
        log_error "JSON schema not found at: $schema_path"
        log_error "Please generate the JSON schema first using: make generate_spec"
        exit 1
    else
        log_info "JSON schema found, validating..."
    fi
    
    # Validate JSON syntax
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
    
    # Check schema has required structure
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

# Step 2: Update Poetry lock if needed
update_poetry_lock() {
    log_info "Checking Poetry dependencies..."
    
    # Check if pyproject.toml is newer than poetry.lock
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
    
    # Install dependencies
    log_info "Installing dependencies..."
    if ! poetry install --with dev; then
        log_error "Failed to install dependencies"
        exit 1
    fi
    
    log_success "Dependencies installed successfully"
}

# Step 3: Generate language bindings
generate_bindings() {
    log_info "Generating language bindings for all languages..."
    
    cd ioc_l9
    if ! make generate_bindings; then
        log_error "Failed to generate language bindings"
        exit 1
    fi
    cd ..
    
    # Verify generated files exist
    local python_bindings="ioc_l9/language_bindings/python/generated_models.py"
    local golang_bindings="ioc_l9/language_bindings/golang/generated_models.go"
    
    if [ ! -f "$python_bindings" ]; then
        log_error "Python bindings not generated: $python_bindings"
        exit 1
    fi
    
    if [ ! -f "$golang_bindings" ]; then
        log_error "Golang bindings not generated: $golang_bindings"
        exit 1
    fi
    
    log_success "Language bindings generated successfully"
    log_info "✅ Python bindings: $python_bindings"
    log_info "✅ Golang bindings: $golang_bindings"
}

# Step 4: Generate documentation
generate_docs() {
    log_info "Generating HTML documentation from JSON schema..."
    
    cd ioc_l9
    if ! make generate_docs; then
        log_error "Failed to generate documentation"
        exit 1
    fi
    cd ..
    
    # Verify documentation was generated
    local docs_file="ioc_l9/docs/generated/protocol_reference.html"
    if [ ! -f "$docs_file" ]; then
        log_error "Documentation not generated: $docs_file"
        exit 1
    fi
    
    log_success "Documentation generated successfully"
    log_info "✅ HTML documentation: $docs_file"
}

# Step 5: Generate skills
generate_skills() {
    log_info "Generating skills from language bindings..."
    
    cd ioc_l9
    if ! make generate_skills; then
        log_error "Failed to generate skills"
        exit 1
    fi
    cd ..
    
    # Verify skills were generated
    local skills_dir="ioc_l9/skills/claude"
    if [ ! -d "$skills_dir" ]; then
        log_error "Skills directory not found: $skills_dir"
        exit 1
    fi
    
    # Check if any SKILL_generated.md files were created
    local generated_skills=$(find "$skills_dir" -name "SKILL_generated.md" | wc -l)
    if [ "$generated_skills" -eq 0 ]; then
        log_warning "No SKILL_generated.md files found, but skills directory exists"
    else
        log_info "✅ Generated $generated_skills skill files"
    fi
    
    log_success "Skills generation completed"
    log_info "✅ Skills directory: $skills_dir"
}

# Step 6: Run comprehensive tests
run_tests() {
    log_info "Running comprehensive test suite..."
    
    cd ioc_l9
    if ! make test_bindings; then
        log_error "Language binding tests failed"
        exit 1
    fi
    
    if ! make test_skills; then
        log_error "Skills tests failed"
        exit 1
    fi
    cd ..
    
    log_success "All tests passed successfully"
}

# Run main function
main "$@"
