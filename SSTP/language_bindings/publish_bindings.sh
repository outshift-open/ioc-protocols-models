#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# IOC L9 Protocol - Language Bindings Publisher
# Publishes Go module with version tag and path-based tag
#
# Usage:
#   ./publish_bindings.sh golang              # Validate Go bindings (no tag)
#   ./publish_bindings.sh golang --tag        # Validate + create Go module git tag
#   ./publish_bindings.sh all                 # Validate all bindings
#   ./publish_bindings.sh all --tag           # Validate all + create tags
#   ./publish_bindings.sh --help              # Show help message
#
# Prerequisites:
#   - Language bindings must be pre-generated using 'make generate_bindings'
#   - For --tag: Git push permissions for tags

set -e

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

# Get version from schema using root Makefile
get_schema_version() {
    local version
    version=$(cd "$PROJECT_ROOT" && make -s print-version 2>/dev/null)

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
        golang|all)
            return 0
            ;;
        *)
            log_error "Invalid language: $lang"
            log_error "Supported: golang, all"
            exit 1
            ;;
    esac
}

# Verify Go bindings exist
verify_golang_bindings() {
    log_step "Verifying Go Bindings Exist"

    log_info "Checking for existing Go bindings..."

    if [ ! -f "$PROJECT_ROOT/SSTP/language_bindings/golang/data_model.go" ]; then
        log_error "Go bindings not found: SSTP/language_bindings/golang/data_model.go"
        log_error "Please run 'make generate_bindings LANGUAGE=golang' first to generate bindings"
        exit 1
    fi

    log_success "Go bindings exist and ready for publishing"
}

# Publish Go module
publish_golang() {
    local version="$1"
    local create_tag="$2"

    log_step "Publishing Go Module v$version"

    verify_golang_bindings

    # Run tests first
    log_info "Running Go binding tests..."
    cd "$PROJECT_ROOT"
    if ! make test_bindings LANGUAGE=golang; then
        log_error "Go tests failed - aborting publish"
        exit 1
    fi

    log_success "Go tests passed"

    # Create Go module-specific tag only if --tag is passed
    if [ "$create_tag" = "true" ]; then
        create_go_module_tag "$version"
    else
        log_info "Skipping git tag creation (pass --tag to create)"
        log_info "Go module validated and ready for tagging when needed"
    fi

    log_success "Go module v$version publish complete"
}

# Create Go module-specific tag (version tag + path tag)
create_go_module_tag() {
    local version="$1"

    log_info "Creating Go module tag..."

    local go_module_tag="SSTP/language_bindings/golang/v$version"

    cd "$PROJECT_ROOT"

    # Check if Go module tag already exists
    if git tag -l "$go_module_tag" | grep -q "^$go_module_tag$"; then
        log_error "Go module tag $go_module_tag already exists"
        log_info "Use 'git tag -d $go_module_tag' to delete locally and 'git push origin :refs/tags/$go_module_tag' to delete remotely"
        exit 1
    fi

    log_info "Creating Go module tag: $go_module_tag"
    git tag "$go_module_tag" -m "IOC L9 Protocol Go module v$version"

    log_info "Pushing Go module tag to origin..."
    git push origin "$go_module_tag"

    log_info "Verifying Go module accessibility..."
    local module_path="github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang"

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
Usage: $0 <language> [--tag]

Publishes IOC L9 Protocol Go module bindings.

Languages:
  golang    Validate and optionally tag Go module
  all       Validate all bindings (currently Go only)

Options:
  --tag     Create and push Git tag for Go module versioning
            Without --tag, only validates bindings and runs tests

Examples:
  $0 golang          # Validate Go bindings (no git tag)
  $0 golang --tag    # Validate + create git tag for release
  $0 all --tag       # Validate all + tag

Go Module Management:
  # List all published Go module versions
  git ls-remote --tags origin | grep "SSTP/language_bindings/golang"

  # Check specific version availability
  go list -m github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang@v1.0.0

  # Install specific version
  go get github.com/cisco-eti/ioc-protocols-models/SSTP/language_bindings/golang@v1.0.0

Requirements:
  - Go: Git push permissions to repository (for --tag)
  - Generated bindings must exist (run make generate_bindings first)

EOF
}

# Main function
main() {
    local language=""
    local create_tag="false"

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h|help)
                show_help
                exit 0
                ;;
            --tag)
                create_tag="true"
                shift
                ;;
            *)
                if [ -z "$language" ]; then
                    language="$1"
                else
                    log_error "Unknown option: $1"
                    echo "Use --help for usage information"
                    exit 1
                fi
                shift
                ;;
        esac
    done

    if [ -z "$language" ]; then
        echo "Usage: $0 <language> [--tag]"
        echo "Languages: golang, all"
        echo "Use --help for more information"
        exit 1
    fi

    validate_language "$language"

    log_step "IOC L9 Protocol - Publishing Language Bindings"
    log_info "Language: $language"
    log_info "Create tag: $create_tag"

    VERSION=$(get_schema_version)
    log_info "Schema version: $VERSION"

    cd "$PROJECT_ROOT"

    case "$language" in
        golang|all)
            publish_golang "$VERSION" "$create_tag"
            ;;
    esac

    log_step "Publishing Complete"
    log_success "Done!"
}

main "$@"
