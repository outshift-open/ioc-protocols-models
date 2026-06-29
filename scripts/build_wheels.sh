#!/usr/bin/env bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# build_wheels.sh - Build all Python wheel packages
#
# This script builds the Python wheel files that were removed from VCS
# to comply with OSPO policies. The wheels are built from the language
# bindings and are required for running tests.
#
# USAGE:
#   ./scripts/build_wheels.sh    # Build all wheels
#   make build_wheels            # Via Makefile (recommended)

set -euo pipefail

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
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

log_step "Building Python Wheels"

# Build main L9 wheel
log_info "Building main L9 wheel (ai-outshift-data-model)..."
if make build_wheel; then
    log_success "Built: SSTP/language_bindings/python/ai_outshift_data_model-*.whl"
else
    log_error "Failed to build main L9 wheel"
    exit 1
fi

# Build SAB subprotocol wheel
log_info "Building SAB subprotocol wheel (ai-outshift-sab-data-model)..."
if make build_sab_wheel; then
    log_success "Built: SSTP/subprotocol/sab/language_bindings/python/ai_outshift_sab_data_model-*.whl"
else
    log_error "Failed to build SAB wheel"
    exit 1
fi

# Build TFP subprotocol wheel (if it exists)
if [ -f "$PROJECT_ROOT/SSTP/subprotocol/tfp/spec/tfp_schema.json" ]; then
    log_info "Building TFP subprotocol wheel (ai-outshift-tfp-data-model)..."
    if make build_tfp_wheel; then
        log_success "Built: SSTP/subprotocol/tfp/language_bindings/python/ai_outshift_tfp_data_model-*.whl"
    else
        log_error "Failed to build TFP wheel"
        exit 1
    fi
fi

# Build SIEP subprotocol wheel (if it exists)
if [ -f "$PROJECT_ROOT/SSTP/subprotocol/siep/spec/siep_schema.json" ]; then
    log_info "Building SIEP subprotocol wheel (ai-outshift-subprotocols-siep)..."
    if make build_siep_wheel; then
        log_success "Built: SSTP/subprotocol/siep/language_bindings/python/ai_outshift_subprotocols_siep-*.whl"
    else
        log_error "Failed to build SIEP wheel"
        exit 1
    fi
fi

# Build CIP subprotocol wheel (if it exists)
if [ -f "$PROJECT_ROOT/SSTP/subprotocol/cip/schema/cip_payload.schema.json" ]; then
    log_info "Building CIP subprotocol wheel (ai-outshift-subprotocols-cip)..."
    if make build_cip_wheel; then
        log_success "Built: SSTP/subprotocol/cip/language_bindings/python/ai_outshift_subprotocols_cip-*.whl"
    else
        log_error "Failed to build CIP wheel"
        exit 1
    fi
fi

log_step "All Wheels Built Successfully"
log_success "Wheels are now available for local testing"
log_info "Note: These .whl files are gitignored and won't be committed to VCS"

exit 0
