# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Basic validation tests for the SSTP Python bindings.

These tests verify that the generated/synced package can be imported and that
the core L9 header builder produces structurally valid envelopes.  They are
intentionally lightweight — the goal is CI gate, not exhaustive correctness.
"""

import time
import pytest

from sstp.l9_base import L9HeaderBuilder, L9Transport, L9_VERSION
from sstp.ie.l9 import build_l9_header, kind_for_event_type
from sstp.snp.l9 import build_snp_l9_header, NegotiationOperation


# ── L9 transport enum ────────────────────────────────────────────────────────

def test_transport_values():
    assert L9Transport.SSTP == "SSTP"
    assert L9Transport.CSTP == "CSTP"
    assert L9Transport.LSTP == "LSTP"


def test_transport_is_str():
    import json
    assert json.dumps(L9Transport.SSTP) == '"SSTP"'


# ── IE header builder ─────────────────────────────────────────────────────────

IE_EVENT_KINDS = [
    ("turn_ingested",   "intent"),
    ("peer_turn",       "delegation"),
    ("repair_required", "query"),
    ("repair_applied",  "delegation"),
    ("decision_emitted","commit"),
    ("episode_persisted","memory_delta"),
    ("conversation_terminated","knowledge"),
]

@pytest.mark.parametrize("event_type,expected_kind", IE_EVENT_KINDS)
def test_ie_kind_mapping(event_type, expected_kind):
    assert kind_for_event_type(event_type) == expected_kind


def test_ie_build_l9_header_structure():
    header = build_l9_header(
        use_case="healthcare",
        event_type="turn_ingested",
        sender="agent-1",
        receiver="agent-2",
        timestamp_ms=int(time.time() * 1000),
    )
    assert header["protocol"] == "SSTP"
    assert header["version"] == L9_VERSION
    assert header["kind"] == "intent"
    assert "message_id" in header
    assert header["semantic_context"]["cognition_protocol"] == "IE"


def test_ie_alias_message_resolves():
    assert kind_for_event_type("message") == kind_for_event_type("peer_turn")


# ── SNP header builder ────────────────────────────────────────────────────────

def test_snp_build_l9_header_structure():
    header = build_snp_l9_header(
        use_case="healthcare",
        operation=NegotiationOperation.PROPOSE,
        sender="panel-agent-1",
        receiver="panel-agent-2",
        timestamp_ms=int(time.time() * 1000),
    )
    assert header["protocol"] == "SSTP"
    assert "message_id" in header
    assert header["semantic_context"]["cognition_protocol"] == "SNP"


def test_snp_operations_are_strings():
    for op in NegotiationOperation:
        assert isinstance(op, str)
