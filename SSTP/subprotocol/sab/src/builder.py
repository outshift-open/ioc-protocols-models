# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SABMessageBuilder — assemble a canonical L9 message for the SAB subprotocol.

SAB does not define its own header. This builder constructs the standard
``L9`` / ``L9Header`` / ``L9Payload`` from the L9 core and writes SAB metadata
(notably ``msg_created_at``) into the canonical ``header.attributes`` dict —
the same shape the Semantic Alignment CE emits at runtime
(``ioc-cfn-cognitive-agents/protocol/sab/l9_adapter.py``).

Example
-------
    from SSTP.subprotocol.sab.src.builder import SABMessageBuilder
    from SSTP.subprotocol.sab.src.sab_models import (
        SABNegotiatePayloadData, NegotiateSemanticContext, SAOState, SAOResponse,
    )

    data = SABNegotiatePayloadData(
        message_id="n1", dt_created="2026-06-22T10:00:02Z",
        origin=SABOrigin(actor_id="agent-buyer"), payload_hash="…",
        semantic_context=NegotiateSemanticContext(
            session_id="sess-1",
            sao_state=SAOState(step=0, n_negotiators=2),
            sao_response=SAOResponse(response=0),
        ),
    )
    l9 = (
        SABMessageBuilder("sess-1")
        .participants(["agent-buyer", "agent-seller"])
        .message("n1", parents=[])
        .topic("Agree price and delivery speed", issues=["price", "delivery_speed"])
        .created_at("2026-06-22T10:00:02Z")
        .negotiate(data)
        .build()
    )
    assert l9.header.attributes["msg_created_at"] == "2026-06-22T10:00:02Z"
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

# L9 core (generated binding). src/__init__.py puts SSTP/language_bindings/python
# on sys.path so this resolves in-place; a pip-installed L9 wheel works too.
from ai.outshift.data_model import (  # noqa: E402
    L9,
    Actor,
    Context,
    L9Header,
    L9Payload,
    Message,
    ParticipantSet,
    Semantic,
)

from .sab_models import (
    SABCommitPayloadData,
    SABIntentPayloadData,
    SABKind,
    SABNegotiatePayloadData,
    SABSubkind,
)

_PayloadData = Union[SABIntentPayloadData, SABNegotiatePayloadData, SABCommitPayloadData]

SAB_L9_SCHEMA_URN = "urn:ioc:schema:sab-l9:v1"
SAB_ONTOLOGY_REF = "urn:ioc:ontology:sab:v1"
SERVER_ACTOR_ID = "negotiation_server"

# CE status → (L9 kind, L9 subkind). Mirrors l9_adapter._STATUS_KIND.
STATUS_KIND: Dict[str, tuple[SABKind, SABSubkind]] = {
    "ongoing": (SABKind.contingency, SABSubkind.negotiation),
    "agreed": (SABKind.commit, SABSubkind.resolved),
    "broken": (SABKind.commit, SABSubkind.timeout),
    "timeout": (SABKind.commit, SABSubkind.unresolved),
}


def now_iso() -> str:
    """UTC timestamp in the ISO-8601 form used across SAB messages."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def payload_hash(data: Any) -> str:
    """SHA-256 hex digest of a JSON-serialisable payload body."""
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_topic(
    content_text: str,
    issues: Optional[List[str]] = None,
    options_per_issue: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Encode mission + negotiation space into ``header.context.topic``.

    Inverse of ``l9_adapter._parse_topic``. Issues/options live in the topic
    (not in payload.data) so the negotiation space rides on the envelope.
    """
    if not issues:
        return content_text
    return (
        f"{content_text}"
        f" | issues: {json.dumps(issues)}"
        f" | options_per_issue: {json.dumps(options_per_issue or {})}"
    )


class SABMessageBuilder:
    """Fluent builder that assembles a canonical :class:`L9` for SAB.

    Set participants / message identity / topic, choose a payload variant via
    :meth:`intent`, :meth:`negotiate`, :meth:`resolved`, :meth:`unresolved`
    or :meth:`timeout`, then call :meth:`build`.
    """

    def __init__(self, session_id: str, *, version: str = "0") -> None:
        self._session_id = session_id
        self._version = version
        self._actors: List[Actor] = []
        self._message_id: Optional[str] = None
        self._parents: List[str] = []
        self._episode: Optional[str] = None
        self._content_text: str = ""
        self._issues: Optional[List[str]] = None
        self._options: Optional[Dict[str, List[str]]] = None
        self._extra_attributes: Dict[str, Any] = {}
        self._msg_created_at: Optional[str] = None
        self._kind: Optional[SABKind] = None
        self._subkind: Optional[SABSubkind] = None
        self._data: Optional[_PayloadData] = None

    # ── participants ──────────────────────────────────────────────────────
    def participants(
        self,
        agents: List[str],
        *,
        agent_role: str = "participant",
        with_server: bool = True,
    ) -> "SABMessageBuilder":
        """One actor per agent id, plus (by default) the negotiation server."""
        self._actors = [Actor(id=a, role=agent_role) for a in agents]
        if with_server:
            self._actors.append(Actor(id=SERVER_ACTOR_ID, role="facilitator"))
        return self

    def actors(self, *actors: Actor) -> "SABMessageBuilder":
        """Set explicit :class:`Actor` objects (overrides :meth:`participants`)."""
        self._actors = list(actors)
        return self

    # ── message identity ──────────────────────────────────────────────────
    def message(
        self,
        message_id: str,
        *,
        parents: Optional[List[str]] = None,
        episode: Optional[str] = None,
    ) -> "SABMessageBuilder":
        self._message_id = message_id
        self._parents = list(parents or [])
        self._episode = episode
        return self

    def created_at(self, iso_timestamp: str) -> "SABMessageBuilder":
        """Override ``msg_created_at`` (defaults to now at build time)."""
        self._msg_created_at = iso_timestamp
        return self

    def topic(
        self,
        content_text: str,
        issues: Optional[List[str]] = None,
        options_per_issue: Optional[Dict[str, List[str]]] = None,
    ) -> "SABMessageBuilder":
        self._content_text = content_text
        self._issues = issues
        self._options = options_per_issue
        return self

    def attributes(self, **kwargs: Any) -> "SABMessageBuilder":
        """Extra ``header.attributes`` keys (e.g. workspace_id, mas_id).

        Merged alongside ``msg_created_at`` — never replaces it.
        """
        self._extra_attributes.update(kwargs)
        return self

    # ── payload variant + kind/subkind ────────────────────────────────────
    def intent(self, data: SABIntentPayloadData) -> "SABMessageBuilder":
        self._kind, self._subkind = SABKind.contingency, SABSubkind.negotiation
        self._data = data
        return self

    def negotiate(self, data: SABNegotiatePayloadData) -> "SABMessageBuilder":
        self._kind, self._subkind = SABKind.contingency, SABSubkind.negotiation
        self._data = data
        return self

    def commit(
        self, data: SABCommitPayloadData, *, subkind: SABSubkind
    ) -> "SABMessageBuilder":
        self._kind, self._subkind = SABKind.commit, subkind
        self._data = data
        return self

    def resolved(self, data: SABCommitPayloadData) -> "SABMessageBuilder":
        return self.commit(data, subkind=SABSubkind.resolved)

    def unresolved(self, data: SABCommitPayloadData) -> "SABMessageBuilder":
        return self.commit(data, subkind=SABSubkind.unresolved)

    def timeout(self, data: SABCommitPayloadData) -> "SABMessageBuilder":
        return self.commit(data, subkind=SABSubkind.timeout)

    def status(self, status: str, data: SABCommitPayloadData | SABNegotiatePayloadData) -> "SABMessageBuilder":
        """Set kind/subkind from a CE status via :data:`STATUS_KIND`."""
        if status not in STATUS_KIND:
            raise ValueError(f"Unknown SAB status: {status!r} (expected one of {list(STATUS_KIND)})")
        self._kind, self._subkind = STATUS_KIND[status]
        self._data = data
        return self

    # ── build ─────────────────────────────────────────────────────────────
    def build(self) -> L9:
        if self._data is None or self._kind is None or self._subkind is None:
            raise ValueError(
                "Choose a payload variant (intent/negotiate/resolved/…) before build()."
            )
        message_id = self._message_id or str(uuid.uuid4())
        episode = self._episode or f"urn:ioc:episode:sab:{self._session_id}"
        created_at = self._msg_created_at or now_iso()

        # msg_created_at is populated into the CANONICAL header.attributes here —
        # this is the single point that answers "where does SAB metadata live?".
        attributes: Dict[str, Any] = {"msg_created_at": created_at, **self._extra_attributes}

        return L9(
            header=L9Header(
                protocol="SSTP",
                subprotocol="SAB",
                version=self._version,
                kind=self._kind.value,
                subkind=self._subkind.value,
                participants=ParticipantSet(actors=self._actors, groups=None),
                message=Message(id=message_id, parents=list(self._parents), episode=episode),
                attributes=attributes,
                context=Context(
                    topic=build_topic(self._content_text, self._issues, self._options),
                    semantic=Semantic(
                        schema_id=SAB_L9_SCHEMA_URN,
                        ontology_ref=SAB_ONTOLOGY_REF,
                    ),
                ),
            ),
            payload=L9Payload(type="json-schema", data=self._data.model_dump()),
        )


__all__ = [
    "SABMessageBuilder",
    "SAB_L9_SCHEMA_URN",
    "SAB_ONTOLOGY_REF",
    "SERVER_ACTOR_ID",
    "STATUS_KIND",
    "now_iso",
    "payload_hash",
    "build_topic",
]
