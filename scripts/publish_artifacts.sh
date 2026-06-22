#!/bin/bash

# IOC L9 Protocol - Artifacts Publisher
# Publishes complete artifacts including documentation and language bindings
#
# Usage:
#   ./scripts/publish_artifacts.sh                # Publish all artifacts (schema version)
#   ./scripts/publish_artifacts.sh 1.2.3         # Publish all artifacts (specific version)
#   ./scripts/publish_artifacts.sh --help         # Show help message
#
# What it does:
#   1. Publishes documentation artifacts to SSTP/documentation/
#   2. Publishes Python package to PyPI and Go module preparation

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

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

get_version() {
    local provided_version="$1"

    if [ -n "$provided_version" ]; then
        log_info "Using provided version: $provided_version"
        echo "$provided_version"
        return
    fi

    local version
    version=$(cd "$PROJECT_ROOT" && make -s print-version 2>/dev/null)

    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi

    log_info "Using schema version: $version"
    echo "$version"
}

publish_docs() {
    log_step "Publishing Documentation Artifacts"

    log_info "Using Makefile target: publish_docs"

    if ! (cd "$PROJECT_ROOT" && make publish_docs); then
        log_error "Failed to publish documentation artifacts"
        exit 1
    fi

    log_success "Documentation artifacts published successfully"
}

publish_bindings() {
    log_step "Publishing Language Bindings"

    log_info "Using Makefile target: publish_bindings"

    if ! (cd "$PROJECT_ROOT" && make publish_bindings); then
        log_error "Failed to publish language bindings"
        exit 1
    fi

    log_success "Language bindings published successfully"
}

main() {
    local provided_version="$1"

    log_step "IOC L9 Protocol - Artifacts Publisher"
    log_info "Starting artifact publishing process..."

    VERSION=$(get_version "$provided_version")
    log_info "Version: $VERSION"

    cd "$PROJECT_ROOT"

    # Step 1: Publish documentation artifacts
    publish_docs

    # Step 2: Publish language bindings
    publish_bindings

    local artifact_folder
    artifact_folder=$(make -s print-artifact-folder)

    log_step "Publishing Complete"
    log_success "All artifacts published successfully!"
    log_success "  Documentation artifacts: $artifact_folder/"
    log_success "  Go module: Published with proper tags"
    log_info "Artifacts v$VERSION are ready. Use scripts/release_artifacts.sh to create repository tag."
}

# Handle script arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [version] [options]"
        echo ""
        echo "Publishes IOC L9 Protocol artifacts including documentation and language bindings."
        echo ""
        echo "Arguments:"
        echo "  version           Optional version to use (defaults to schema version)"
        echo ""
        echo "Options:"
        echo "  --help, -h        Show this help message"
        echo ""
        echo "Examples:"
        echo "  $0                    # Publish all artifacts (schema version)"
        echo "  $0 1.2.3             # Publish all artifacts (specific version)"
        exit 0
        ;;
    "")
        main ""
        ;;
    *)
        if [[ "$1" =~ ^[v]?[0-9] ]]; then
            main "$1"
        else
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
        fi
        ;;
esac
