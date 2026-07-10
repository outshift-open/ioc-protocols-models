# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SAB subprotocol smoke tests.

Verifies that SAB reuses the canonical L9 envelope (no bespoke SABHeader):
  * SABMessageBuilder produces a canonical L9 with msg_created_at in
    header.attributes and the correct kind/subkind mapping;
  * the example dumps validate against l9_schema.json (envelope) and
    sab_schema.json (payload.data);
  * the removed envelope classes (SABHeader/SABActors/SABAttributes/…) are gone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_L9_PY = _REPO_ROOT / "SSTP" / "language_bindings" / "python"
for _p in (str(_L9_PY), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from SSTP.subprotocol.sab.src import (
        NegotiateCommitSemanticContext,
        NegotiateSemanticContext,
        SABCommitPayloadData,
        SABIntentPayloadData,
        SABMessageBuilder,
        SABNegotiatePayloadData,
        SABOrigin,
        SAOResponse,
        SAOState,
        SemanticContext,
    )
except ImportError as exc:  # pragma: no cover
    pytest.skip(f"SAB source models not importable: {exc}", allow_module_level=True)

_SAB_ROOT = _REPO_ROOT / "SSTP" / "subprotocol" / "sab"
_SAB_SCHEMA = json.loads((_SAB_ROOT / "spec" / "sab_schema.json").read_text())
_L9_SCHEMA = json.loads((_REPO_ROOT / "SSTP" / "spec" / "l9_schema.json").read_text())


def _negotiate_data() -> SABNegotiatePayloadData:
    return SABNegotiatePayloadData(
        message_id="n1",
        dt_created="2026-06-22T10:00:02Z",
        origin=SABOrigin(actor_id="agent-buyer"),
        payload_hash="deadbeef",
        semantic_context=NegotiateSemanticContext(
            session_id="sess-1",
            sao_state=SAOState(step=0, n_negotiators=2, current_offer={"price": "high"}),
            sao_response=SAOResponse(response=3, outcome={"price": "high"}),
        ),
    )


class TestSABBuilder:
    def test_builder_produces_canonical_l9_header(self):
        l9 = (
            SABMessageBuilder("sess-1")
            .participants(["agent-buyer", "agent-seller"])
            .message("n1", parents=[])
            .topic("Agree price", issues=["price"], options_per_issue={"price": ["low", "high"]})
            .created_at("2026-06-22T10:00:02Z")
            .negotiate(_negotiate_data())
            .build()
        )
        h = l9.header
        assert h.protocol == "SSTP"
        assert h.subprotocol == "SAB"
        assert h.kind.value == "contingency"
        assert h.subkind == "negotiation"
        # msg_created_at lives in the canonical header.attributes — not a SABHeader.
        assert h.attributes["msg_created_at"] == "2026-06-22T10:00:02Z"
        assert l9.payload.type == "json-schema"
        assert l9.payload.data["semantic_context"]["session_id"] == "sess-1"

    def test_created_at_defaults_to_now(self):
        l9 = (
            SABMessageBuilder("s").participants(["a"]).message("m1")
            .negotiate(_negotiate_data()).build()
        )
        assert l9.header.attributes["msg_created_at"]  # non-empty ISO string

    def test_commit_subkind_mapping(self):
        commit = SABCommitPayloadData(
            message_id="c1", dt_created="t", origin=SABOrigin(actor_id="s"),
            payload_hash="h",
            semantic_context=NegotiateCommitSemanticContext(session_id="s", outcome="agreement"),
        )
        for helper, expected in [("resolved", "resolved"), ("unresolved", "unresolved"), ("timeout", "timeout")]:
            l9 = getattr(SABMessageBuilder("s").participants(["a"]).message("c1"), helper)(commit).build()
            assert l9.header.kind.value == "commit"
            assert l9.header.subkind == expected

    def test_status_helper_maps_ce_status(self):
        l9 = (
            SABMessageBuilder("s").participants(["a"]).message("n1")
            .status("ongoing", _negotiate_data()).build()
        )
        assert (l9.header.kind.value, l9.header.subkind) == ("contingency", "negotiation")


class TestSABSchema:
    def test_schema_has_no_envelope_defs(self):
        defs = set(_SAB_SCHEMA.get("$defs", {}))
        assert not (defs & {"SABHeader", "SABActors", "SABAttributes", "SABL9Payload", "SAB_L9"})
        # payload-shaped: three data variants present
        assert {"SABIntentPayloadData", "SABNegotiatePayloadData", "SABCommitPayloadData"} <= defs

    def test_example_dumps_validate(self):
        jsonschema = pytest.importorskip("jsonschema")
        env_v = jsonschema.Draft202012Validator(_L9_SCHEMA)
        pay_v = jsonschema.Draft202012Validator(_SAB_SCHEMA)
        examples = _SAB_ROOT / "examples"
        files = list(examples.glob("demo_*.json"))
        assert files, "no example dumps found"
        for f in files:
            for msg in json.loads(f.read_text()):
                assert not list(env_v.iter_errors(msg)), f"{f.name}: envelope invalid"
                assert not list(pay_v.iter_errors(msg["payload"]["data"])), f"{f.name}: payload invalid"
                assert msg["header"]["attributes"]["msg_created_at"]
