#!/bin/bash

# IOC L9 Protocol - Release Manager
# Creates Git tags for published artifacts
#
# Usage:
#   ./scripts/release_artifacts.sh                # Create Git tag (schema version)
#   ./scripts/release_artifacts.sh 1.2.3         # Create Git tag (specific version)
#   ./scripts/release_artifacts.sh --help         # Show help message
#
# What it does:
#   1. Gets version from parameter or JSON schema
#   2. Creates single Git tag (v{version}) for complete release
#   3. Creates version.json in SSTP/documentation/
#
# Prerequisites:
#   - Artifacts already published (use scripts/publish_artifacts.sh first)
#   - Git push permissions for creating tags

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
        log_info "Using provided version: $provided_version" >&2
        echo "$provided_version"
        return
    fi

    local version
    version=$(cd "$PROJECT_ROOT" && make -s print-version 2>/dev/null)

    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi

    log_info "Using schema version: $version" >&2
    echo "$version"
}

create_version_tag() {
    local version="$1"

    log_step "Creating Repository Tag"

    local repo_tag="$version"

    if git tag -l "$repo_tag" | grep -q "^$repo_tag$"; then
        log_error "Repository tag $repo_tag already exists"
        log_info "Use 'git tag -d $repo_tag' to delete locally and 'git push origin :refs/tags/$repo_tag' to delete remotely"
        exit 1
    fi

    log_info "Creating repository tag: $repo_tag"
    git tag "$repo_tag" -m "IOC L9 Protocol v$version - Complete release"

    log_info "Pushing repository tag to origin..."
    git push origin "$repo_tag"

    create_version_json "$version"

    log_success "Repository tag $repo_tag created successfully"
}

create_version_json() {
    local version="$1"
    local artifact_folder
    artifact_folder=$(cd "$PROJECT_ROOT" && make -s print-artifact-folder)
    local version_file="$artifact_folder/version.json"

    log_info "Creating version.json in artifact folder..."

    if [ ! -d "$artifact_folder" ]; then
        log_error "Artifact folder not found: $artifact_folder"
        log_error "Please run scripts/publish_artifacts.sh first"
        exit 1
    fi

    cat > "$version_file" << EOF
{
  "version": "$version",
  "release_date": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

    if [ -f "$version_file" ]; then
        log_success "Created version.json: $version_file"
    else
        log_error "Failed to create version.json"
        exit 1
    fi
}

main() {
    local provided_version="$1"

    log_step "IOC L9 Protocol - Release Manager"
    log_info "Starting release tag creation process..."

    VERSION=$(get_version "$provided_version")
    log_info "Version: $VERSION"

    cd "$PROJECT_ROOT"

    create_version_tag "$VERSION"

    log_step "Release Complete"
    log_success "Repository release created successfully!"
    log_success "  Repository tag: $VERSION"
    log_success "  Version metadata: SSTP/documentation/version.json"
    log_info "Release $VERSION is ready for distribution and consumption."
}

# Handle script arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [version] [options]"
        echo ""
        echo "Creates Git tag for IOC L9 Protocol release."
        echo ""
        echo "Arguments:"
        echo "  version           Optional version to use (defaults to schema version)"
        echo ""
        echo "Options:"
        echo "  --help, -h        Show this help message"
        echo ""
        echo "Prerequisites:"
        echo "  - Artifacts already published (use scripts/publish_artifacts.sh first)"
        echo "  - Git push permissions for creating tags"
        echo ""
        echo "Complete workflow:"
        echo "  1. ./scripts/generate_artifacts.sh    # Generate artifacts"
        echo "  2. ./scripts/publish_artifacts.sh     # Publish artifacts"
        echo "  3. ./scripts/release_artifacts.sh     # Create release tag"
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
