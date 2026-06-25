#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Python Language Bindings Test Runner
# Tests the Python bindings generated from JSON Schema

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "Running Python Language Bindings Tests..."
echo "Project root: $PROJECT_ROOT"

# Change to project root
cd "$PROJECT_ROOT"

# Check if wheel exists
WHEEL=$(ls "$PROJECT_ROOT/SSTP/language_bindings/python"/ai_outshift_data_model-*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
    echo "Error: Wheel not found in SSTP/language_bindings/python/"
    echo "Please build the wheel first (make build_wheel)"
    exit 1
fi

# Install dependencies and wheel
echo "Ensuring dependencies are installed..."
poetry install --with dev
echo "Installing wheel: $WHEEL"
poetry run pip install "$WHEEL" --force-reinstall --quiet

# Run the Python binding tests
echo "Running Python binding tests..."
echo ""

# Track test results
FAILED=0

echo "Model Validation Tests..."
poetry run pytest tests/language_bindings/python/test_model_validation.py -v || FAILED=1

echo ""
if [ $FAILED -eq 1 ]; then
    echo "❌ Python binding tests FAILED"
    exit 1
else
    echo "✅ Python binding tests PASSED"
fi
