#!/usr/bin/env bash
# =============================================================================
# package_models.sh — Build distributable wheel for ai.outshift namespace packages
# =============================================================================
#
# This script assembles the ai.outshift Python namespace package tree from the
# source protocol definitions (SSTP root and subprotocols), builds a wheel using
# Poetry, and cleans up the temporary package directory on exit.
#
# The wheel is output to ./dist/ and can be installed with pip directly or
# published to a PyPI registry.
#
# -----------------------------------------------------------------------------
# MODES
# -----------------------------------------------------------------------------
#
# --all (default)
#     Builds the complete package including both the SSTP root L9 protocol
#     models and all subprotocol models (SAB, TFP). Use this for the standard
#     published wheel that gives consumers access to the full model set.
#
# --sstp
#     Builds only the SSTP root L9 protocol models under ai.outshift.
#     Use this when you only need the core L9 header/payload definitions
#     without any subprotocol dependencies.
#
# --subprotocol
#     Builds only the subprotocol models (SAB, TFP) under ai.outshift.sab
#     and ai.outshift.tfp. Use this when you only need the subprotocol-specific
#     data models without the root L9 definitions.
#
# -----------------------------------------------------------------------------
# USAGE
# -----------------------------------------------------------------------------
#
#   # Build everything (SSTP root + all subprotocols):
#   ./scripts/package_models.sh
#   ./scripts/package_models.sh --all
#
#   # Build only the SSTP root L9 models:
#   ./scripts/package_models.sh --sstp
#
#   # Build only subprotocol models (SAB, TFP):
#   ./scripts/package_models.sh --subprotocol
#
#   # Install the built wheel:
#   pip install dist/ai_outshift_all_models-*.whl
#
# -----------------------------------------------------------------------------
# PACKAGE STRUCTURE & IMPORTS PER MODE
# -----------------------------------------------------------------------------
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ --all (default)                                                             │
# ├─────────────────────────────────────────────────────────────────────────────┤
# │                                                                             │
# │  Package tree:                                                              │
# │                                                                             │
# │    ai/                                                                      │
# │    ├── __init__.py                                                          │
# │    └── outshift/                                                            │
# │        ├── __init__.py                                                      │
# │        ├── data_model.py        ← SSTP root L9                             │
# │        ├── sab/                                                             │
# │        │   ├── __init__.py                                                  │
# │        │   └── data_model.py    ← SAB subprotocol                          │
# │        └── tfp/                                                             │
# │            ├── __init__.py                                                  │
# │            └── data_model.py    ← TFP subprotocol                          │
# │                                                                             │
# │  Python usage:                                                              │
# │                                                                             │
# │    from ai.outshift.data_model import L9, L9Header, L9Payload              │
# │    from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind      │
# │    from ai.outshift.tfp.data_model import TFPOperation, TFPPayload         │
# │                                                                             │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ --sstp                                                                      │
# ├─────────────────────────────────────────────────────────────────────────────┤
# │                                                                             │
# │  Package tree:                                                              │
# │                                                                             │
# │    ai/                                                                      │
# │    ├── __init__.py                                                          │
# │    └── outshift/                                                            │
# │        ├── __init__.py                                                      │
# │        └── data_model.py        ← SSTP root L9 only                        │
# │                                                                             │
# │  Python usage:                                                              │
# │                                                                             │
# │    from ai.outshift.data_model import L9, L9Header, L9Payload              │
# │                                                                             │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ --subprotocol                                                               │
# ├─────────────────────────────────────────────────────────────────────────────┤
# │                                                                             │
# │  Package tree:                                                              │
# │                                                                             │
# │    ai/                                                                      │
# │    ├── __init__.py                                                          │
# │    └── outshift/                                                            │
# │        ├── __init__.py                                                      │
# │        ├── sab/                                                             │
# │        │   ├── __init__.py                                                  │
# │        │   └── data_model.py    ← SAB subprotocol                          │
# │        └── tfp/                                                             │
# │            ├── __init__.py                                                  │
# │            └── data_model.py    ← TFP subprotocol                          │
# │                                                                             │
# │  Python usage:                                                              │
# │                                                                             │
# │    from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind      │
# │    from ai.outshift.tfp.data_model import TFPOperation, TFPPayload         │
# │                                                                             │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# -----------------------------------------------------------------------------
# ADDING A NEW SUBPROTOCOL
# -----------------------------------------------------------------------------
#
#   1. Create the language binding at:
#      SSTP/subprotocol/<name>/language_bindings/python/ai/outshift/<name>/data_model.py
#
#   2. Add a new block in the --subprotocol section below:
#      mkdir -p "$PKG_DIR/outshift/<name>"
#      touch "$PKG_DIR/outshift/<name>/__init__.py"
#      cp "$REPO_ROOT/SSTP/subprotocol/<name>/language_bindings/python/ai/outshift/<name>/data_model.py" \
#         "$PKG_DIR/outshift/<name>/data_model.py"
#
#   3. Bump the version in pyproject.toml and tag the release.
#
# -----------------------------------------------------------------------------
# PREREQUISITES
# -----------------------------------------------------------------------------
#
#   - Python >=3.10,<3.14
#   - Poetry (with poetry-core>=2.0.0)
#   - Source protocol files must exist under SSTP/ directory
#
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG_DIR="$REPO_ROOT/ai"

MODE="${1:---all}"

usage() {
    echo "Usage: $0 [--all | --sstp | --subprotocol]"
    echo ""
    echo "Build modes:"
    echo "  --all           Build SSTP root L9 + all subprotocols (default)"
    echo "  --sstp          Build only SSTP root L9 models (ai.outshift.data_model)"
    echo "  --subprotocol   Build only subprotocols (ai.outshift.sab, ai.outshift.tfp)"
    echo ""
    echo "Examples:"
    echo "  $0              # Builds everything (same as --all)"
    echo "  $0 --all        # SSTP root L9 + SAB + TFP subprotocols"
    echo "  $0 --sstp       # Only ai.outshift.data_model (L9, L9Header, L9Payload)"
    echo "  $0 --subprotocol # Only ai.outshift.sab + ai.outshift.tfp"
    echo ""
    echo "Install:"
    echo "  pip install dist/ai_outshift_all_models-*.whl"
    echo ""
    echo "Imports after install:"
    echo "  # --sstp or --all:"
    echo "  from ai.outshift.data_model import L9, L9Header, L9Payload"
    echo ""
    echo "  # --subprotocol or --all:"
    echo "  from ai.outshift.sab.data_model import Protocol, Subprotocol, Kind"
    echo "  from ai.outshift.tfp.data_model import TFPOperation, TFPPayload"
    echo ""
    echo "Output: dist/ai_outshift_all_models-<version>-py3-none-any.whl"
    exit 1
}

case "$MODE" in
    --all|--sstp|--subprotocol) ;;
    *) usage ;;
esac

# --- Set package name based on mode ---
#
# Each mode produces a differently-named wheel so they can be published as
# separate packages on PyPI. The script temporarily patches the "name" field
# in pyproject.toml before building, then restores the original on exit.
#
# Mode → Package name mapping:
#   --all          → ai-outshift-all-models      (default, no patch needed)
#   --subprotocol  → ai-outshift-subprotocols
#   --sstp         → ai-outshift-sstp-models
#
# This allows the publish workflow to run the script three times
# (--all, --sstp, --subprotocol) and end up with three distinct wheels in dist/
# ready for PyPI upload.
ORIGINAL_NAME=$(grep '^name = ' "$REPO_ROOT/pyproject.toml" | head -1)
if [[ "$MODE" == "--subprotocol" ]]; then
    sed -i.bak 's/^name = .*/name = "ai-outshift-subprotocols"/' "$REPO_ROOT/pyproject.toml"
elif [[ "$MODE" == "--sstp" ]]; then
    sed -i.bak 's/^name = .*/name = "ai-outshift-sstp-models"/' "$REPO_ROOT/pyproject.toml"
fi

# Cleanup runs on exit (success or failure):
# - Removes the temporary ai/ package tree created for the build
# - Restores pyproject.toml from .bak if it was patched (--subprotocol/--sstp)
# This ensures pyproject.toml is never left in a modified state.
cleanup() {
    rm -rf "$PKG_DIR"
    if [[ -f "$REPO_ROOT/pyproject.toml.bak" ]]; then
        mv "$REPO_ROOT/pyproject.toml.bak" "$REPO_ROOT/pyproject.toml"
    fi
}
trap cleanup EXIT

# --- Assemble namespace package tree ---

mkdir -p "$PKG_DIR/outshift"
touch "$PKG_DIR/__init__.py"
touch "$PKG_DIR/outshift/__init__.py"

# SSTP root L9 models (--sstp, --all)
if [[ "$MODE" == "--all" || "$MODE" == "--sstp" ]]; then
    cp "$REPO_ROOT/SSTP/language_bindings/python/ai/outshift/data_model.py" \
       "$PKG_DIR/outshift/data_model.py"
fi

# Subprotocol models (--subprotocol, --all)
if [[ "$MODE" == "--all" || "$MODE" == "--subprotocol" ]]; then
    # SAB subprotocol
    mkdir -p "$PKG_DIR/outshift/sab"
    touch "$PKG_DIR/outshift/sab/__init__.py"
    cp "$REPO_ROOT/SSTP/subprotocol/sab/language_bindings/python/ai/outshift/sab/data_model.py" \
       "$PKG_DIR/outshift/sab/data_model.py"

    # TFP subprotocol
    mkdir -p "$PKG_DIR/outshift/tfp"
    touch "$PKG_DIR/outshift/tfp/__init__.py"
    cp "$REPO_ROOT/SSTP/subprotocol/tfp/language_bindings/python/ai/outshift/tfp/data_model.py" \
       "$PKG_DIR/outshift/tfp/data_model.py"
fi

# --- Build wheel ---

cd "$REPO_ROOT"
poetry build -f wheel

echo ""
echo "Wheel built successfully (mode: $MODE):"
ls -1 "$REPO_ROOT/dist/"*.whl 2>/dev/null | tail -1
