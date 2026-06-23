#!/bin/bash

# Golang Language Bindings Test Runner
# Tests the Go bindings generated from JSON Schema

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "Running Golang Language Bindings Tests..."
echo "Project root: $PROJECT_ROOT"

# Change to project root
cd "$PROJECT_ROOT"

# Change to test directory
cd "$SCRIPT_DIR"

# Check if generated Go models exist
GENERATED_MODELS="$PROJECT_ROOT/SSTP/language_bindings/golang/data_model.go"
if [ ! -f "$GENERATED_MODELS" ]; then
    echo "Error: Generated Golang models not found at: $GENERATED_MODELS"
    echo "Please generate the models first (make generate_bindings LANGUAGE=golang)"
    exit 1
fi

# Ensure Go is available
if ! command -v go &> /dev/null; then
    echo "Go is not installed or not in PATH"
    echo "Please install Go to run Golang binding tests"
    exit 1
fi

echo "Running Golang binding tests..."
echo ""

# Initialize go module if go.sum doesn't exist
if [ ! -f "go.sum" ]; then
    echo "Initializing Go module..."
    go mod tidy
fi

echo "Model Validation Tests..."
if go test -v .; then
    echo "✅ Golang binding tests PASSED"
else
    echo "❌ Golang binding tests FAILED"
    exit 1
fi
