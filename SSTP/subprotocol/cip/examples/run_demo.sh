#!/usr/bin/env bash
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
#
# Run the CIP demo from the repository root using Poetry.
#
# Usage:
#   ./SSTP/subprotocol/cip/examples/run_demo.sh
#   bash SSTP/subprotocol/cip/examples/run_demo.sh
#
# Prerequisites:
#   1. Install Python dependencies:
#        poetry install
#   2. Install the L9 data-model wheel (provides ai.outshift.data_model):
#        poetry run pip install SSTP/language_bindings/python/ai_outshift_data_model-0.0.4-py3-none-any.whl
#   3. (Optional) Set LLM keys in SSTP/subprotocol/cip/llm.env to enable
#      LLM-powered features. Without keys the demo runs with a no-op LLM client.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
LLM_ENV="$SCRIPT_DIR/../llm.env"
WHEEL="$REPO_ROOT/SSTP/language_bindings/python/ai_outshift_data_model-0.0.4-py3-none-any.whl"

cd "$REPO_ROOT"

# Ensure the L9 data-model wheel is installed
if ! poetry run python -c "import ai.outshift.data_model" 2>/dev/null; then
    echo "Installing L9 data-model wheel..."
    poetry run pip install "$WHEEL" --quiet
fi

# Load LLM keys from llm.env (skip comment lines and blank lines)
if [ -f "$LLM_ENV" ]; then
    echo "Loading LLM config from $(realpath "$LLM_ENV")..."
    set -o allexport
    # shellcheck source=/dev/null
    source "$LLM_ENV"
    set +o allexport
else
    echo "Warning: llm.env not found at $LLM_ENV — running without LLM keys" >&2
fi

echo "Running CIP demo..."
poetry run python "$SCRIPT_DIR/run_demo.py"
