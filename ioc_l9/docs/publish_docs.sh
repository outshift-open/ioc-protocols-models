#!/bin/bash

# IOC L9 Protocol - Documentation Publisher
# Publishes existing documentation artifacts
#
# Usage:
#   ./publish_docs.sh               # Publish existing documentation
#   ./publish_docs.sh --help        # Show help message
#
# What it does:
#   1. Verifies HTML documentation exists (must be pre-generated)
#   2. Copies documentation files to artifact folder (configured in Makefile)
#   3. Creates version metadata and artifact index
#
# Prerequisites:
#   - Poetry with dev dependencies installed
#   - json-schema-for-humans package available

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

# Verify documentation exists (assumes already generated)
verify_docs_exist() {
    log_step "Verifying Documentation Exists"
    
    log_info "Checking for existing generated documentation..."
    
    if [ ! -d "$IOC_L9_DIR/docs/generated" ]; then
        log_error "Generated documentation not found: $IOC_L9_DIR/docs/generated"
        log_error "Please run 'make generate_docs' first to generate documentation"
        exit 1
    fi
    
    if [ ! -f "$IOC_L9_DIR/docs/generated/protocol_reference.html" ]; then
        log_error "Protocol reference not found: $IOC_L9_DIR/docs/generated/protocol_reference.html"
        log_error "Please run 'make generate_docs' first to generate documentation"
        exit 1
    fi
    
    log_success "Documentation exists and ready for publishing"
}

# Publish documentation artifacts to configurable folder
publish_docs_artifacts() {
    log_step "Publishing Documentation Artifacts"
    
    # Get the artifact folder from Makefile
    local artifact_folder=$(cd "$IOC_L9_DIR" && make -s print-artifact-folder 2>/dev/null || echo "$PROJECT_ROOT/ioc_l9_artifacts")
    
    log_info "Publishing documentation artifacts to: $artifact_folder/docs/"
    
    # Create artifact directory
    mkdir -p "$artifact_folder/docs"
    
    # Copy generated documentation
    log_info "Copying generated documentation..."
    if [ -d "$IOC_L9_DIR/docs/generated" ]; then
        cp -r "$IOC_L9_DIR/docs/generated"/* "$artifact_folder/docs/"
    else
        log_error "Generated documentation not found: $IOC_L9_DIR/docs/generated"
        exit 1
    fi
    
    # Copy JSON schema files
    log_info "Copying JSON schema files..."
    if [ -d "$IOC_L9_DIR/spec/json_schema" ]; then
        cp "$IOC_L9_DIR/spec/json_schema"/* "$artifact_folder/docs/"
    else
        log_error "JSON schema files not found: $IOC_L9_DIR/spec/json_schema"
        exit 1
    fi
    
    # Copy Artifacts usage guide
    log_info "Copying Artifacts usage files..."
    if [ -f "$IOC_L9_DIR/docs/Artifacts.md" ]; then
        cp "$IOC_L9_DIR/docs/Artifacts.md" "$artifact_folder/docs/"
    else
        log_error "Artifacts.md not found: $IOC_L9_DIR/docs/Artifacts.md"
        exit 1
    fi
    
    # Verify documentation was published
    local docs_file="$artifact_folder/docs/protocol_reference.html"
    if [ ! -f "$docs_file" ]; then
        log_error "Documentation not published: $docs_file"
        exit 1
    fi
    
    log_success "Documentation artifacts published successfully!"
    log_info "✅ Output directory: $artifact_folder/docs/"
    
    echo "$artifact_folder"
}

# Add version metadata and create index
finalize_docs() {
    local version="$1"
    
    # Get the artifact folder from Makefile
    local artifact_folder=$(cd "$IOC_L9_DIR" && make -s print-artifact-folder)
    local output_dir="$artifact_folder/docs"
    
    # Create index file for artifacts
    log_info "Creating artifacts index..."
    cat > "$output_dir/index.html" << EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IOC L9 Protocol v$version - Documentation Artifacts</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
        .header { border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .artifact { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9; }
        .version { color: #666; font-size: 0.9em; }
        .bindings { margin: 20px 0; padding: 15px; border: 1px solid #007acc; border-radius: 5px; background: #f0f8ff; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
        ul { margin: 10px 0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>IOC L9 Protocol v$version</h1>
        <p class="version">Documentation generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")</p>
        <p class="version">Git Tag: $git_tag</p>
        <p class="version">Git Commit: $git_commit</p>
    </div>
    
    <h2>Documentation Artifacts</h2>
    
    <div class="artifact">
        <h3><a href="protocol_reference.html">📖 Protocol Reference Documentation</a></h3>
        <p>Interactive HTML documentation generated from the JSON schema with full type definitions and examples.</p>
    </div>
    
    <div class="artifact">
        <h3><a href="l9.json">📋 JSON Schema</a></h3>
        <p>Complete JSON schema definition for IOC L9 Protocol v$version. Use this for validation and code generation.</p>
    </div>
    
    <div class="artifact">
        <h3><a href="Artifacts.md">📚 Usage Guide</a></h3>
        <p>Comprehensive guide on how to use the published Python and Go language bindings in your projects.</p>
    </div>
    
    
    <div class="bindings">
        <h2>Language Bindings</h2>
        <p><strong>Ready-to-use packages for integrating IOC L9 Protocol:</strong></p>
        <ul>
            <li><strong>Python:</strong> <code>pip install ioc-l9==$version</code></li>
            <li><strong>Go:</strong> <code>go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v$version</code></li>
        </ul>
    </div>
    
    <hr style="margin: 40px 0;">
    <footer>
        <p><strong>Repository:</strong> <a href="https://github.com/cisco-eti/ioc-protocols-models">https://github.com/cisco-eti/ioc-protocols-models</a></p>
        <p><strong>Issues:</strong> <a href="https://github.com/cisco-eti/ioc-protocols-models/issues">Report problems or request features</a></p>
    </footer>
</body>
</html>
EOF
    
    log_success "Documentation artifacts published to: $output_dir"
    log_info "✅ Protocol reference: protocol_reference.html"
    log_info "✅ JSON schema: l9.json"
    log_info "✅ Usage guide: Artifacts.md"
    log_info "✅ Artifacts index: index.html"
}

# Main function
main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                echo "Usage: $0 [options]"
                echo ""
                echo "Publishes existing IOC L9 Protocol documentation artifacts."
                echo "Uses the artifact folder configured in the Makefile (ARTIFACT_PUBLISH_FOLDER)."
                echo ""
                echo "Prerequisites:"
                echo "  Documentation must be pre-generated using 'make generate_docs'"
                echo ""
                echo "Options:"
                echo "  --help, -h          Show this help message"
                echo ""
                echo "Published artifacts:"
                echo "  - protocol_reference.html    Interactive HTML documentation"
                echo "  - l9.json                    JSON schema file"
                echo "  - Artifacts.md               Usage guide"
                echo "  - index.html                 Artifacts index page"
                echo ""
                echo "Configuration:"
                echo "  Output location is controlled by ARTIFACT_PUBLISH_FOLDER in Makefile"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
    
    log_step "IOC L9 Protocol - Documentation Publisher"
    
    # Get version from schema
    VERSION=$(get_schema_version)
    log_info "Schema version: $VERSION"
    
    # Ensure we're in project root
    cd "$PROJECT_ROOT"
    
    # Step 1: Verify documentation exists (assumes already generated)
    verify_docs_exist
    
    # Step 2: Publish documentation artifacts
    artifact_folder=$(publish_docs_artifacts)
    
    # Step 3: Add version metadata and create index
    finalize_docs "$VERSION"
    
    # Get artifact folder for final message
    local artifact_folder=$(cd "$IOC_L9_DIR" && make -s print-artifact-folder)
    
    log_step "Documentation Publishing Complete"
    log_success "Documentation artifacts ready at: $artifact_folder/docs/"
    log_info "Open $artifact_folder/docs/index.html to view the artifacts index"
}

# Run main function with all arguments
main "$@"
