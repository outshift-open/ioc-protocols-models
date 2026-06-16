#!/bin/bash

# IOC L9 Protocol - Release Manager
# Creates Git tags for published artifacts
#
# Usage:
#   ./release_artifacts.sh                    # Create Git tag (schema version)
#   ./release_artifacts.sh 1.2.3             # Create Git tag (specific version)
#   ./release_artifacts.sh --help             # Show help message
#
# What it does:
#   1. Gets version from parameter or JSON schema
#   2. Creates single Git tag (v{version}) for complete release
#   3. Verifies Go module accessibility
#
# Version Parameter:
#   - If provided: Uses the specified version
#   - If omitted: Uses version from spec/json_schema/l9.json
#
# Examples:
#   ./release_artifacts.sh                    # Use schema version
#   ./release_artifacts.sh $(make -s print-version)  # Explicit schema version
#   ./release_artifacts.sh 2.1.0             # Use specific version
#   ./release_artifacts.sh v1.5.3            # Version with 'v' prefix
#
# Prerequisites:
#   - Artifacts already published (use publish_artifacts.sh first)
#   - Git push permissions for creating tags

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
        log_info "Using provided version: $provided_version" >&2
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
    
    log_info "Using schema version: $version" >&2
    echo "$version"
}

# Create single git tag for complete release
create_version_tag() {
    local version="$1"
    
    log_step "Creating Version Tag"
    
    # Create single tag for the protocol version (without "v" prefix)
    local tag="$version"
    
    # Check if tag already exists
    if git tag -l "$tag" | grep -q "^$tag$"; then
        log_error "Tag $tag already exists"
        log_info "Use 'git tag -d $tag' to delete locally and 'git push origin :refs/tags/$tag' to delete remotely"
        exit 1
    fi
    
    log_info "Creating Git tag: $tag"
    git tag "$tag" -m "IOC L9 Protocol v$version - Complete release"
    git push origin "$tag"
    
    # Verify Go module is accessible with the new tag
    log_info "Verifying Go module accessibility..."
    local module_path="github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang"
    
    # Test that the module can be fetched
    if go list -m "$module_path@$tag" >/dev/null 2>&1; then
        log_success "Go module accessible at $tag"
    else
        log_warning "Go module published but may take time to be accessible via go get"
    fi
    
    # Create version.json in artifacts folder
    create_version_json "$version"
    
    log_success "Version tag $version created successfully"
}

# Create version.json file in artifacts folder
create_version_json() {
    local version="$1"
    local artifacts_dir="$PROJECT_ROOT/ioc_l9_artifacts"
    local version_file="$artifacts_dir/version.json"
    
    log_info "Creating version.json in artifacts folder..."
    
    # Ensure artifacts directory exists
    if [ ! -d "$artifacts_dir" ]; then
        log_error "Artifacts directory not found: $artifacts_dir"
        log_error "Please run publish_artifacts.sh first to create artifacts"
        exit 1
    fi
    
    # Create version.json with release information
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

# Main function
main() {
    local provided_version="$1"
    
    log_step "IOC L9 Protocol - Release Manager"
    log_info "Starting release tag creation process..."
    
    # Get version from parameter or schema
    VERSION=$(get_version "$provided_version")
    log_info "Version: $VERSION"
    
    # Ensure we're in project root
    cd "$PROJECT_ROOT"
    
    # Create version tag for complete release
    create_version_tag "$VERSION"
    
    log_step "Release Complete"
    log_success "Release tag created successfully!"
    log_success "✅ Git tag: $VERSION"
    log_success "✅ Version metadata: ioc_l9_artifacts/version.json"
    log_info "Release $VERSION is ready for distribution and consumption."
    log_info "Go module can be accessed with: go get ...@$VERSION"
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
        echo "  - Artifacts already published (use publish_artifacts.sh first)"
        echo "  - Git push permissions for creating tags"
        echo ""
        echo "Examples:"
        echo "  $0                    # Create Git tag for schema version"
        echo "  $0 1.2.3             # Create Git tag for specific version"
        echo ""
        echo "Complete workflow:"
        echo "  1. ./generate_artifacts.sh    # Generate artifacts"
        echo "  2. ./publish_artifacts.sh     # Publish artifacts"
        echo "  3. ./release_artifacts.sh     # Create release tag"
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
