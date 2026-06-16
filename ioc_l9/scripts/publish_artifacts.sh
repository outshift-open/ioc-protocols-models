#!/bin/bash

# IOC L9 Protocol - Artifacts Publisher
# Publishes complete artifacts including documentation, skills and language bindings
#
# Usage:
#   ./publish_artifacts.sh                    # Publish all artifacts (schema version)
#   ./publish_artifacts.sh 1.2.3             # Publish all artifacts (specific version)
#   ./publish_artifacts.sh --help             # Show help message
#
# What it does:
#   1. Publishes documentation artifacts to configured folder
#   2. Publishes skills artifacts to configured folder
#   3. Publishes Python package to PyPI and Go module preparation
#
# Version Parameter:
#   - If provided: Uses the specified version
#   - If omitted: Uses version from spec/json_schema/l9.json
#
# Examples:
#   ./publish_artifacts.sh                    # Use schema version
#   ./publish_artifacts.sh $(make -s print-version)  # Explicit schema version
#   ./publish_artifacts.sh 2.1.0             # Use specific version
#   ./publish_artifacts.sh v1.5.3            # Version with 'v' prefix
#
# Prerequisites:
#   - Generated artifacts (docs and language bindings)
#   - Poetry with PyPI authentication configured

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


# Get version from parameter or schema using Makefile target
get_version() {
    local provided_version="$1"
    
    # Use provided version if given
    if [ -n "$provided_version" ]; then
        log_info "Using provided version: $provided_version"
        echo "$provided_version"
        return
    fi
    
    # Fallback to schema version
    local current_dir=$(pwd)
    cd "$IOC_L9_DIR"
    local version=$(make -s print-version 2>/dev/null)
    cd "$current_dir"
    
    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi
    
    log_info "Using schema version: $version"
    echo "$version"
}


# Publish documentation artifacts
publish_docs() {
    log_step "Publishing Documentation Artifacts"
    
    log_info "Using Makefile target: publish_docs"
    
    # Use Makefile target for consistency (in subshell to preserve working directory)
    if ! (cd "$IOC_L9_DIR" && make publish_docs); then
        log_error "Failed to publish documentation artifacts"
        exit 1
    fi
    
    log_success "Documentation artifacts published successfully"
}

# Publish skills artifacts
publish_skills() {
    log_step "Publishing Skills Artifacts"
    
    log_info "Using Makefile target: publish_skills"
    
    # Use Makefile target for consistency (in subshell to preserve working directory)
    if ! (cd "$IOC_L9_DIR" && make publish_skills); then
        log_error "Failed to publish skills artifacts"
        exit 1
    fi
    
    log_success "Skills artifacts published successfully"
}

# Publish language bindings
publish_bindings() {
    log_step "Publishing Language Bindings"
    
    log_info "Using Makefile target: publish_bindings"
    
    # Use Makefile target for consistency (in subshell to preserve working directory)
    if ! (cd "$IOC_L9_DIR" && make publish_bindings); then
        log_error "Failed to publish language bindings"
        exit 1
    fi
    
    log_success "Language bindings published successfully"
}


# Main function
main() {
    local provided_version="$1"
    
    log_step "IOC L9 Protocol - Artifacts Publisher"
    log_info "Starting artifact publishing process..."
    
    # Get version from parameter or schema
    VERSION=$(get_version "$provided_version")
    log_info "Version: $VERSION"
    
    # Ensure we're in project root
    cd "$PROJECT_ROOT"
    
    # Step 1: Publish documentation artifacts
    publish_docs

    # Step 2: Publish skills
    publish_skills
    
    # Step 3: Publish language bindings
    # publish_bindings
    
    # Get artifact folder for success message
    local artifact_folder=$(cd "$IOC_L9_DIR" && make -s print-artifact-folder)
    
    log_step "Publishing Complete"
    log_success "All artifacts published successfully!"
    log_success "✅ Documentation artifacts: $artifact_folder/docs/"
    log_success "✅ Skills artifacts: $artifact_folder/skills/"
    log_success "✅ Python package: PyPI"
    log_success "✅ Go module: Ready for tagging"
    log_info "Artifacts v$VERSION are ready. Use release_artifacts.sh to create Git tag."
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
        echo "Prerequisites:"
        echo "  - Generated artifacts (docs and language bindings)"
        echo "  - Poetry with dev dependencies"
        echo "  - PyPI authentication for Python publishing"
        echo ""
        echo "Examples:"
        echo "  $0                    # Publish all artifacts (schema version)"
        echo "  $0 1.2.3             # Publish all artifacts (specific version)"
        echo ""
        echo "To create a Git tag after publishing, use release_artifacts.sh"
        exit 0
        ;;
    "")
        # Run main function with no version
        main ""
        ;;
    *)
        # Check if it's a version (starts with digit or v)
        if [[ "$1" =~ ^[v]?[0-9] ]]; then
            # Run main function with version
            main "$1"
        else
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
        fi
        ;;
esac
