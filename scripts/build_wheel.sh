#!/usr/bin/env bash
# Assembles the ai.outshift namespace package layout, builds the wheel, then cleans up.
#
# Usage:
#   ./scripts/build_wheel.sh
#   pip install dist/ai_outshift_all_models-*.whl
#
# After install, import models like:
#   from ai.outshift.data_model import L9, L9Header, L9Payload
#   from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind
#   from ai.outshift.tfp.data_model import TFPOperation, TFPPayload
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG_DIR="$REPO_ROOT/ai"

cleanup() {
    rm -rf "$PKG_DIR"
}
trap cleanup EXIT

# Assemble package tree
mkdir -p "$PKG_DIR/outshift/sab"

touch "$PKG_DIR/__init__.py"
touch "$PKG_DIR/outshift/__init__.py"
touch "$PKG_DIR/outshift/sab/__init__.py"

cp "$REPO_ROOT/SSTP/language_bindings/python/ai/outshift/data_model.py" \
   "$PKG_DIR/outshift/data_model.py"

# To add a new subprotocol: copy its data_model.py into the package tree below,
# then bump the version in pyproject.toml and tag the release.
cp "$REPO_ROOT/SSTP/subprotocol/sab/language_bindings/python/ai/outshift/sab/data_model.py" \
   "$PKG_DIR/outshift/sab/data_model.py"

mkdir -p "$PKG_DIR/outshift/tfp"
touch "$PKG_DIR/outshift/tfp/__init__.py"
cp "$REPO_ROOT/SSTP/subprotocol/tfp/language_bindings/python/ai/outshift/tfp/data_model.py" \
   "$PKG_DIR/outshift/tfp/data_model.py"

# Build wheel
cd "$REPO_ROOT"
poetry build -f wheel

echo "Wheel built successfully:"
ls -1 "$REPO_ROOT/dist/"*.whl 2>/dev/null | tail -1
