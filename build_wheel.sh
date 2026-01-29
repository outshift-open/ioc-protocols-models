#!/bin/bash

# Build script for ioc-cfn-protocols-models wheel package using Poetry

set -e  # Exit on error

echo "==================================="
echo "Building ioc-cfn-protocols-models"
echo "==================================="

# Clean previous builds
echo "Cleaning previous build artifacts..."
rm -rf build/ dist/ *.egg-info app/*.egg-info

# Ensure Poetry is installed
echo "Checking Poetry installation..."
if ! command -v poetry &> /dev/null; then
    echo "Poetry not found. Installing Poetry..."
    curl -sSL https://install.python-poetry.org | python3 -
fi

# Install dependencies
echo "Installing dependencies..."
poetry install

# Build the wheel
echo "Building wheel package..."
poetry build

# List the built artifacts
echo ""
echo "Build complete! Generated files:"
ls -lh dist/

echo ""
echo "==================================="
echo "Build successful!"
echo "==================================="
echo "To install the wheel, run:"
echo "  pip install dist/ioc_cfn_protocols_models-*.whl"
echo ""
echo "Or with Poetry:"
echo "  poetry install"
