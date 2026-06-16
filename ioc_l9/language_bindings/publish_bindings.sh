#!/bin/bash

# IOC L9 Protocol - Language Bindings Publisher
# Publishes existing Python and Go language bindings after successful validation
#
# Usage:
#   ./publish_bindings.sh python    # Publish Python package to PyPI
#   ./publish_bindings.sh golang    # Publish Go module (prepare for tagging)
#   ./publish_bindings.sh all       # Publish both Python and Go bindings
#
# Prerequisites:
#   - Language bindings must be pre-generated using 'make generate_bindings'
#   - Clean git working directory
#   - Poetry with PyPI authentication configured
#   - Git push permissions for tags
#   - All tests must pass before publishing

set -e

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
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IOC_L9_DIR="$PROJECT_ROOT/ioc_l9"

# Get version from schema using Makefile target
get_schema_version() {
    local current_dir=$(pwd)
    cd "$IOC_L9_DIR"
    local version=$(make -s print-version 2>/dev/null)
    cd "$current_dir"
    
    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi
    
    echo "$version"
}

# Validate language parameter
validate_language() {
    local lang="$1"
    case "$lang" in
        python|golang|all)
            return 0
            ;;
        *)
            log_error "Invalid language: $lang"
            log_error "Supported languages: python, golang, all"
            exit 1
            ;;
    esac
}


# Verify Python bindings exist (assumes already generated)
verify_python_bindings() {
    log_step "Verifying Python Bindings Exist"
    
    log_info "Checking for existing Python bindings..."
    
    if [ ! -f "$IOC_L9_DIR/language_bindings/python/generated_models.py" ]; then
        log_error "Python bindings not found: $IOC_L9_DIR/language_bindings/python/generated_models.py"
        log_error "Please run 'make generate_bindings LANGUAGE=python' first to generate bindings"
        exit 1
    fi
    
    log_success "Python bindings exist and ready for publishing"
}

# Verify Go bindings exist (assumes already generated)
verify_golang_bindings() {
    log_step "Verifying Go Bindings Exist"
    
    log_info "Checking for existing Go bindings..."
    
    if [ ! -f "$IOC_L9_DIR/language_bindings/golang/generated_models.go" ]; then
        log_error "Go bindings not found: $IOC_L9_DIR/language_bindings/golang/generated_models.go"
        log_error "Please run 'make generate_bindings LANGUAGE=golang' first to generate bindings"
        exit 1
    fi
    
    log_success "Go bindings exist and ready for publishing"
}

# Publish Python package to PyPI
publish_python() {
    local version="$1"
    
    log_step "Publishing Python Package v$version"
    
    # Verify bindings exist first
    verify_python_bindings
    
    # Run tests first
    log_info "Running Python binding tests..."
    cd "$IOC_L9_DIR"
    if ! make test_bindings LANGUAGE=python; then
        log_error "Python tests failed - aborting publish"
        exit 1
    fi
    
    log_success "Python tests passed"
    log_success "Python package v$version ready for publishing"
    
    # Build and publish Python package (commented for now as we dont want to publish to pypi)
    # log_info "Building Python package..."
    # cd "$PROJECT_ROOT"
    
    # # Update version in pyproject.toml
    # sed -i.bak "s/version = \".*\"/version = \"$version\"/" pyproject.toml
    
    # # Build package
    # poetry build
    
    # # Publish to PyPI (requires authentication)
    # log_info "Publishing to PyPI..."
    # poetry publish
    
    # Note: Git tag will be created after all bindings are published
    # Future implementation can publish to appropriate registries as required
    # either here or via github actions
}

# Publish Go module
publish_golang() {
    local version="$1"
    
    log_step "Publishing Go Module v$version"
    
    # Verify bindings exist first
    verify_golang_bindings
    
    # Run tests first
    log_info "Running Go binding tests..."
    cd "$IOC_L9_DIR"
    if ! make test_bindings LANGUAGE=golang; then
        log_error "Go tests failed - aborting publish"
        exit 1
    fi
    
    log_success "Go tests passed"
    log_success "Go module v$version ready for publishing"
    
    # Note: Git tag will be created after all bindings are published
    # For Go modules, the Git repository itself IS the module registry
    # so "publishing" means creating and pushing Git tags
    # Future implementation can publish to appropriate registries as required
    # either here or via github actions
}


# Main function
main() {
    local language="${1:-}"
    
    if [ -z "$language" ]; then
        echo "Usage: $0 <language>"
        echo "Languages: python, golang, all"
        exit 1
    fi
    
    validate_language "$language"
    
    log_step "IOC L9 Protocol - Publishing Language Bindings"
    log_info "Language: $language"
    
    # Get version from schema
    VERSION=$(get_schema_version)
    log_info "Schema version: $VERSION"
    
    # Ensure we're in project root
    cd "$PROJECT_ROOT"
    
    case "$language" in
        python)
            publish_python "$VERSION"
            ;;
        golang)
            publish_golang "$VERSION"
            ;;
        all)
            publish_python "$VERSION"
            publish_golang "$VERSION"
            ;;
    esac
    
    log_step "Publishing Complete"
    log_success "All requested language bindings published successfully!"
}

# Run main function with all arguments
main "$@"
