#!/usr/bin/env bash
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
#
# Run the TFP team-formation demo from the repository root using Poetry.
#
# Usage:
#   ./SSTP/subprotocol/tfp/examples/run_demo.sh            # success scenario
#   ./SSTP/subprotocol/tfp/examples/run_demo.sh --fail     # failure scenario
#   bash SSTP/subprotocol/tfp/examples/run_demo.sh --out /tmp/dump.json
#
# Any extra arguments are forwarded to team_formation_example.py.
#
# Prerequisites:
#   1. Install Python dependencies:
#        poetry install
#   2. The L9 data-model wheel (provides ai.outshift.data_model) is installed
#      automatically by this script from SSTP/language_bindings/python/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

cd "$REPO_ROOT"

# Ensure the L9 data-model wheel is installed (provides ai.outshift.data_model).
if ! poetry run python -c "import ai.outshift.data_model" 2>/dev/null; then
    WHEEL="$(ls "$REPO_ROOT"/SSTP/language_bindings/python/ai_outshift_data_model-*.whl 2>/dev/null | sort -V | tail -1 || true)"
    if [ -z "$WHEEL" ]; then
        echo "Error: L9 data-model wheel not found in SSTP/language_bindings/python/." >&2
        echo "Build it first with: make build_wheel" >&2
        exit 1
    fi
    echo "Installing L9 data-model wheel: $(basename "$WHEEL")..."
    poetry run pip install "$WHEEL" --quiet
fi

echo "Running TFP team-formation demo..."
poetry run python "$SCRIPT_DIR/team_formation_example.py" "$@"
