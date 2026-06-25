#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Python Language Bindings Test Runner
# Builds the wheel using package_models.sh --all, installs it, and runs tests.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "Running Python Language Bindings Tests..."
echo "Project root: $PROJECT_ROOT"

cd "$PROJECT_ROOT"

# Build the wheel (--all includes SSTP root + all subprotocols)
echo "Building wheel with --all mode..."
bash "$PROJECT_ROOT/scripts/package_models.sh" --all

# Find the built wheel
WHEEL=$(ls "$PROJECT_ROOT/dist"/ai_outshift_all_models-*.whl 2>/dev/null | tail -1)
if [ -z "$WHEEL" ]; then
    echo "Error: Wheel not found in dist/ after build"
    exit 1
fi

# Install dependencies (--no-root: skip project install since ai/ is transient)
echo "Installing dependencies..."
poetry install --no-root --with dev
echo "Installing wheel: $WHEEL"
poetry run pip install "$WHEEL" --force-reinstall --quiet

# Run tests
echo ""
echo "Running Python binding tests..."
FAILED=0

poetry run pytest tests/language_bindings/python/test_model_validation.py -v || FAILED=1

echo ""
if [ $FAILED -eq 1 ]; then
    echo "Python binding tests FAILED"
    exit 1
else
    echo "Python binding tests PASSED"
fi
