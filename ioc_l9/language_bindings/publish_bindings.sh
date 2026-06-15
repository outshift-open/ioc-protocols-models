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
    
    # Create Go module-specific tag for proper versioning
    create_go_module_tag "$version"
    
    log_success "Go module v$version published successfully"
}

# Create Go module-specific tag
create_go_module_tag() {
    local version="$1"
    
    log_info "Creating Go module tag..."
    
    # Create Go module-specific tag (with "v" prefix and subpath)
    local go_module_tag="ioc_l9/language_bindings/golang/v$version"
    
    # Ensure we're in project root
    cd "$PROJECT_ROOT"
    
    # Check if Go module tag already exists
    if git tag -l "$go_module_tag" | grep -q "^$go_module_tag$"; then
        log_error "Go module tag $go_module_tag already exists"
        log_info "Use 'git tag -d $go_module_tag' to delete locally and 'git push origin :refs/tags/$go_module_tag' to delete remotely"
        exit 1
    fi
    
    # Create Go module-specific tag
    log_info "Creating Go module tag: $go_module_tag"
    git tag "$go_module_tag" -m "IOC L9 Protocol Go module v$version"
    
    # Push the tag
    log_info "Pushing Go module tag to origin..."
    git push origin "$go_module_tag"
    
    # Verify Go module is accessible with the new tag
    log_info "Verifying Go module accessibility..."
    local module_path="github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang"
    
    # Test that the module can be fetched with the Go module tag
    if go list -m "$module_path@v$version" >/dev/null 2>&1; then
        log_success "Go module accessible at v$version"
        log_info "Usage: go get $module_path@v$version"
    else
        log_warning "Go module published but may take time to be accessible via go get"
        log_info "Try: go get $module_path@v$version"
    fi
}


# Show help information
show_help() {
    cat << EOF
Usage: $0 <language>

Publishes IOC L9 Protocol language bindings after validation.

Languages:
  python    Publish Python package to PyPI
  golang    Publish Go module with proper Git tags
  all       Publish both Python and Go bindings

Examples:
  $0 python    # Publish Python package only
  $0 golang    # Publish Go module only  
  $0 all       # Publish all language bindings

Go Module Management:
  # List all published Go module versions
  git ls-remote --tags origin | grep "ioc_l9/language_bindings/golang"
  
  # Check specific version availability
  go list -m github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0
  
  # Install specific version
  go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0

Requirements:
  - Python: PyPI API token configured (poetry config pypi-token.pypi <token>)
  - Go: Git push permissions to repository
  - All: Generated bindings must exist (run make generate_bindings first)

EOF
}

# Main function
main() {
    local language="${1:-}"
    
    # Handle help flag
    case "$language" in
        --help|-h|help)
            show_help
            exit 0
            ;;
    esac
    
    if [ -z "$language" ]; then
        echo "Usage: $0 <language>"
        echo "Languages: python, golang, all"
        echo "Use --help for more information"
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
