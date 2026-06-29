#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# IOC L9 Protocol - Documentation Publisher
# Publishes documentation artifacts to SSTP/documentation/
#
# Usage:
#   ./SSTP/documentation/publish_docs.sh
#   make publish_docs
#
# What it does:
#   1. Verifies HTML documentation exists (must be pre-generated)
#   2. Copies schema file to documentation folder
#   3. Creates version metadata and artifact index

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCS_DIR="$PROJECT_ROOT/SSTP/documentation"

get_schema_version() {
    local version
    version=$(cd "$PROJECT_ROOT" && make -s print-version 2>/dev/null)

    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi

    echo "$version"
}

verify_docs_exist() {
    log_step "Verifying Documentation Exists"

    if [ ! -f "$DOCS_DIR/protocol_reference.html" ]; then
        log_error "Protocol reference not found: $DOCS_DIR/protocol_reference.html"
        log_error "Please run 'make generate_docs' first"
        exit 1
    fi

    log_success "Documentation exists and ready for publishing"
}

finalize_docs() {
    local version="$1"

    log_step "Finalizing Documentation"

    local git_tag=""
    local git_commit=""
    if command -v git >/dev/null 2>&1 && [ -d "$PROJECT_ROOT/.git" ]; then
        git_tag=$(cd "$PROJECT_ROOT" && git describe --tags --exact-match 2>/dev/null || echo "")
        git_commit=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "")
    fi

    log_info "Creating artifacts index..."
    cat > "$DOCS_DIR/index.html" << EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IOC L9 Protocol v$version - Documentation</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
        .header { border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .artifact { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9; }
        .version { color: #666; font-size: 0.9em; }
        .bindings { margin: 20px 0; padding: 15px; border: 1px solid #007acc; border-radius: 5px; background: #f0f8ff; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
    </style>
</head>
<body>
    <div class="header">
        <h1>IOC L9 Protocol v$version</h1>
        <p class="version">Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")</p>
        <p class="version">Git Tag: $git_tag</p>
        <p class="version">Git Commit: $git_commit</p>
    </div>

    <h2>Documentation Artifacts</h2>

    <div class="artifact">
        <h3><a href="protocol_reference.html">Protocol Reference Documentation</a></h3>
        <p>Interactive HTML documentation generated from the JSON schema.</p>
    </div>

    <div class="artifact">
        <h3><a href="../spec/l9_schema.json">JSON Schema</a></h3>
        <p>Complete JSON schema definition for IOC L9 Protocol v$version.</p>
    </div>

    <div class="artifact">
        <h3><a href="Artifacts.md">Usage Guide</a></h3>
        <p>Guide on how to use the published Python and Go language bindings.</p>
    </div>

    <div class="bindings">
        <h2>Language Bindings</h2>
        <ul>
            <li><strong>Go:</strong> <code>go get github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang@v$version</code></li>
        </ul>
    </div>

    <hr style="margin: 40px 0;">
    <footer>
        <p><strong>Repository:</strong> <a href="https://github.com/outshift-open/ioc-protocols-models">https://github.com/outshift-open/ioc-protocols-models</a></p>
    </footer>
</body>
</html>
EOF

    log_success "Documentation index created: $DOCS_DIR/index.html"
}

main() {
    log_step "IOC L9 Protocol - Documentation Publisher"

    VERSION=$(get_schema_version)
    log_info "Schema version: $VERSION"

    cd "$PROJECT_ROOT"

    verify_docs_exist
    finalize_docs "$VERSION"

    log_step "Documentation Publishing Complete"
    log_success "Documentation artifacts ready at: $DOCS_DIR/"
}

main "$@"
