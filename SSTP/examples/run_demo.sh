#!/usr/bin/env bash
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
#
# Multi-protocol SSTP demo runner: SIEP → CIP → SAB
# Usage: ./run_demo.sh [--no-llm]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LLM_ENV="${REPO_ROOT}/SSTP/subprotocol/cip/llm.env"

# ── LLM credentials ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--no-llm" ]]; then
    echo "[run_demo] --no-llm: skipping LLM configuration"
elif [[ -f "${LLM_ENV}" ]]; then
    echo "[run_demo] Loading LLM credentials from ${LLM_ENV}"
    source "${LLM_ENV}"
    export LLM_MODEL LLM_API_KEY LLM_API_BASE
else
    echo "[run_demo] Warning: ${LLM_ENV} not found — CIP guidance will use rule-based fallback"
fi

# ── Wheel check ───────────────────────────────────────────────────────────────
cd "${REPO_ROOT}"
if ! python3 -c "from ai.outshift.data_model import L9" 2>/dev/null; then
    echo "[run_demo] Installing ai-outshift-data-model wheel …"
    WHEEL=$(find . -name "ai_outshift_data_model*.whl" | head -1)
    if [[ -z "${WHEEL}" ]]; then
        echo "[run_demo] ERROR: wheel not found. Run: poetry install" >&2
        exit 1
    fi
    pip install --quiet "${WHEEL}"
fi

# ── Run ───────────────────────────────────────────────────────────────────────
echo "[run_demo] Starting multi-protocol demo …"
echo
poetry run python "${SCRIPT_DIR}/run_demo.py"
