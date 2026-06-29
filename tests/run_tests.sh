#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Master Test Runner for IOC L9 Language Bindings
# This script runs all language binding test suites

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=========================================="
echo "IOC L9 Language Bindings Test Suite"
echo "=========================================="
echo "Project root: $PROJECT_ROOT"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Track test results
FAILED_TESTS=()
PASSED_TESTS=()

# Function to run a language-specific test suite
run_language_tests() {
    local language=$1
    local test_script="$SCRIPT_DIR/language_bindings/$language/run_tests.sh"
    
    echo "----------------------------------------"
    echo "Running $language Language Binding Tests"
    echo "----------------------------------------"
    
    if [ -f "$test_script" ]; then
        if chmod +x "$test_script" && "$test_script"; then
            echo "✅ $language tests PASSED"
            PASSED_TESTS+=("$language")
        else
            echo "❌ $language tests FAILED"
            FAILED_TESTS+=("$language")
        fi
    else
        echo "⚠️  No test script found for $language at $test_script"
        echo "Skipping $language tests..."
    fi
    echo ""
}

# Run tests for each language
run_language_tests "python"
run_language_tests "golang"

# Summary
echo "=========================================="
echo "Test Results Summary"
echo "=========================================="

if [ ${#PASSED_TESTS[@]} -gt 0 ]; then
    echo "✅ PASSED: ${PASSED_TESTS[*]}"
fi

if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
    echo "❌ FAILED: ${FAILED_TESTS[*]}"
    echo ""
    echo "Some tests failed. Please check the output above for details."
    exit 1
else
    echo ""
    echo "🎉 All language binding tests passed!"
    exit 0
fi
