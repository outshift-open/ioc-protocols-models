# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
Golden-output regression tests for the CIP/SIEP L9 header builders.

This is a **safety net**, not a spec: it pins down the exact header dict
``build_l9_header()`` (CIP) and ``build_snp_l9_header()`` (SIEP) produce
today for every event type / SNP operation, so any future refactor —
in particular the planned migration of hcpanel's ``panel_bus.py`` /
``agent_bus.py`` off ``l9.py``/``l9_base.py`` onto the pydantic-based
``builder.py`` (``CIPMessageBuilder``/``SIEPMessageBuilder``) — has something
concrete to diff against instead of relying on manual inspection.

The fixtures in ``fixtures/l9_cip_golden.json`` and
``fixtures/l9_siep_golden.json`` were captured from the current
``l9_base.L9HeaderBuilder``-backed implementation with fixed
``message_id``/``timestamp_ms`` inputs (so output is fully deterministic).
If ``l9.py``'s vocabulary tables change intentionally, regenerate the
fixtures with the same inputs used below and review the diff.

Run from the repo root:
    poetry run pytest SSTP/tests/test_l9_header_regression.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # …/ioc-protocols-models
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from SSTP.subprotocol.cip.src.l9 import build_l9_header, _KIND_BY_EVENT_TYPE  # noqa: E402
from SSTP.subprotocol.siep.src.l9 import build_snp_l9_header, NegotiationOperation  # noqa: E402

FIXED_TS = 1750000000000
FIXTURES_DIR = _HERE.parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


CIP_GOLDEN = _load("l9_cip_golden.json")
SIEP_GOLDEN = _load("l9_siep_golden.json")


class TestCIPHeaderGolden:
    """Every CIP event type in ``_KIND_BY_EVENT_TYPE`` must match its golden header."""

    @pytest.mark.parametrize("event_type", sorted(_KIND_BY_EVENT_TYPE.keys()))
    def test_matches_golden(self, event_type: str) -> None:
        header = build_l9_header(
            use_case="hcpanel_regression",
            event_type=event_type,
            sender="dr_a",
            receiver="dr_b",
            timestamp_ms=FIXED_TS,
            message_id="fixed-msg-id",
            parent_ids=["parent-1"],
            provenance_sources=["source-1"],
            topic="concept:x",
            payload_parts=[{"type": "text", "data": {"k": "v"}}],
        )
        assert header == CIP_GOLDEN[event_type]

    def test_golden_fixture_covers_every_known_event_type(self) -> None:
        """Catches event types added to l9.py without regenerating the fixture."""
        assert set(CIP_GOLDEN.keys()) == set(_KIND_BY_EVENT_TYPE.keys())


class TestSIEPHeaderGolden:
    """Every SNP operation in ``NegotiationOperation.ALL`` must match its golden header."""

    @pytest.mark.parametrize("operation", sorted(NegotiationOperation.ALL))
    def test_matches_golden(self, operation: str) -> None:
        header = build_snp_l9_header(
            operation=operation,
            use_case="hcpanel_regression",
            sender="dr_a",
            receiver="dr_b",
            timestamp_ms=FIXED_TS,
            proposal_id="prop-1",
            message_id="fixed-msg-id",
            parent_ids=["parent-1"],
            provenance_sources=["source-1"],
            topic="concept:x",
        )
        assert header == SIEP_GOLDEN[operation]

    def test_golden_fixture_covers_every_known_operation(self) -> None:
        """Catches operations added to l9.py without regenerating the fixture."""
        assert set(SIEP_GOLDEN.keys()) == set(NegotiationOperation.ALL)
