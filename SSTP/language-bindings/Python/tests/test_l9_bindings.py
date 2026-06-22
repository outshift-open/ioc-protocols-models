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
    # 5-value session-flow vocabulary
    ("turn_ingested",          "exchange"),
    ("peer_turn",              "exchange"),
    ("repair_required",        "contingency"),
    ("repair_applied",         "commit"),
    ("decision_emitted",       "convergence"),
    ("episode_persisted",      "convergence"),
    ("conversation_terminated","convergence"),
    ("rule_update",            "convergence"),
    ("agent_request",          "exchange"),
    ("prior_query",            "exchange"),
    ("prior_injection",        "exchange"),
    ("outcome_reported",       "exchange"),
]

@pytest.mark.parametrize("event_type,expected_kind", IE_EVENT_KINDS)
def test_ie_kind_mapping(event_type, expected_kind):
    assert kind_for_event_type(event_type) == expected_kind


def test_ie_build_l9_header_structure():
    header = build_l9_header(
        use_case="healthcare",
        event_type="peer_turn",
        sender="agent-1",
        receiver="agent-2",
        timestamp_ms=int(time.time() * 1000),
    )
    assert header["protocol"] == "SSTP"
    assert header["version"] == L9_VERSION
    assert header["kind"] == "exchange"
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
        proposal_id="prop-001",
    )
    assert header["protocol"] == "SSTP"
    assert "message_id" in header
    assert header["semantic_context"]["cognition_protocol"] == "SNP"
    assert header["kind"] == "exchange"


def test_snp_operations_are_strings():
    for op in NegotiationOperation.ALL:
        assert isinstance(op, str)
