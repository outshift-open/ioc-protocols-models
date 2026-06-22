#!/bin/bash

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

# Check if generated models exist
GENERATED_MODELS="$PROJECT_ROOT/SSTP/language_bindings/python/generated_models.py"
if [ ! -f "$GENERATED_MODELS" ]; then
    echo "Error: Generated Python models not found at: $GENERATED_MODELS"
    echo "Please generate the models first (make generate_bindings LANGUAGE=python)"
    exit 1
fi

# Install dependencies if needed
echo "Ensuring dependencies are installed..."
poetry install --with dev

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
