#!/bin/bash -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Running language binding tests..."
cd "$PROJECT_ROOT"
./tests/run_tests.sh