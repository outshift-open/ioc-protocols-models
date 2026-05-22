"""
L9 Message — envelope combining L9Header and L9Payload.

Structure:
    L9
    ├── header:  L9Header   (identity, routing, kind, sub-kind, actors)
    └── payload: L9Payload  (sub-protocol name, schema reference, semantic context)

Kinds and SubKinds:
    Kind = Intent
        SubKind = intent_ambiguity_detector   — detects ambiguity in stated intent
        SubKind = intent_contingency_detector — detects contingencies in stated intent
        SubKind = repair_negotiation          — repairs intent via semantic negotiation

    Kind = Knowledge
        SubKind = query          — requests missing information
        SubKind = evidence_bundle — provides validation artifacts
        SubKind = commit          — represents stabilized shared state
        SubKind = memory_delta    — incremental update to shared knowledge

    Kind = Repair
        SubKind = repair_template — applies a structured repair template

Actors:
    Each message carries a list of Actor objects.
    Each Actor has an actor_type (SOURCE, DESTINATION, USER, …) and an Identity.
    An Identity holds the agent type, optional attestation (JWT, cert), and
    one or more typed identifiers (URL, Email, SSN, agent_id, …).

Usage:
    from l9.message import L9, L9Header, L9Payload, L9Kind, L9SubKind
    from l9.message import Identity, Actor

    msg = L9(
        header=L9Header(
            kind=L9Kind.INTENT,
            sub_kind=L9SubKind.intent_ambiguity_detector,
            actors=[
                Actor(actor_type="SOURCE",      identity=Identity(type="OpenClaw", identifiers=[{"URL": "http://agent1:8080"}])),
                Actor(actor_type="DESTINATION", identity=Identity(type="OpenClaw", identifiers=[{"URL": "http://agent2:9090"}])),
            ],
        ),
        payload=L9Payload(
            sub_protocol="NegMas",
            sub_protocol_schema="https://schemas.l9/negmas-v1.json",
            semantic_context={"goal": "Build a summarizer", "ambiguity_score": 0.72},
        ),
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums shared by header / payload
# ─────────────────────────────────────────────────────────────────────────────


##
# L9Kind — the top-level semantic category of a message.
#
#   Intent    — messages that carry, refine, or repair a stated goal or mission.
#   Knowledge — messages that assert, query, bundle, commit, or delta shared knowledge.
#   Repair    — messages that apply a structured fix to a broken or ambiguous state.
##

class L9Phase(int, Enum):
    TEAMWORK      = 1
    GOAL_INTENT   = 2
    PLANNING      = 3
    CONVERSATION  = 4
    VALIDATION    = 5


class L9Kind(str, Enum):
    UTTER          = "utter"  #Question: is this BASE COMM 
    INTENT         = "Intent"
    KNOWLEDGE      = "Knowledge"
    REPAIR         = "Repair"


##
# L9SubKind — scoped within a Kind; narrows the semantic purpose of the message.
#
# Valid under Kind.INTENT:
#   intent_ambiguity_detector   — signals that ambiguity was found in the stated intent;
#                                  triggers a clarification request to the originating actor.
#   intent_contingency_detector — signals a contingency (edge case / dependency) embedded
#                                  in the intent that must be resolved before planning.
#   repair_negotiation          — initiates semantic negotiation to repair an intent that
#                                  could not be resolved through automated detection alone.
#
# Valid under Kind.REPAIR:
#   repair_template             — applies a pre-defined repair template to a broken or
#                                  incomplete protocol state.
#
# Note: sub-kind validity per kind is documented above; runtime validation is a TODO.
##

class L9SubKind(str, Enum):
    intent_ambiguity_detector   = "intent_ambiguity_detector"
    intent_contingency_detector = "intent_contingency_detector"
    repair_template             = "repair_template"
    repair_negotiation          = "repair_negotiation"
    knowledge_query              = "knowledge_query"
    knowledge_evidence_bundle    = "knowledge_evidence_bundle"
    knowledge_commit             = "knowledge_commit"
    knowledge_memory_delta       = "knowledge_memory_delta"
    utter_delegate              = "utter_delegate"

class L9MessageType(str, Enum):
    REQUEST  = "request"
    RESPONSE = "response"
    EVENT    = "event"
    ERROR    = "error"


# ─────────────────────────────────────────────────────────────────────────────
# L9Header — routing, identity, protocol metadata
# ─────────────────────────────────────────────────────────────────────────────


##
# Actors block — describes all participants involved in a message exchange.
#
# Every L9Header carries a list of Actor objects.  Each actor has:
#   actor_type  — the role this participant plays in the exchange:
#                   SOURCE      : the agent/service that originated the message
#                   DESTINATION : the agent/service(s) the message is addressed to
#                   USER        : a human principal on whose behalf the message is sent
#                   <custom>    : any additional role defined by the application
#
#   identity    — the verifiable identity of the actor, composed of:
#                   type         : agent framework / platform (e.g. "OpenClaw")
#                   attestation  : optional proof-of-identity token (JWT, certificate
#                                  fingerprint, etc.)
#                   identifiers  : one or more typed address entries, e.g.
#                                    [{"URL": "https://myagent1:8080"}]
#                                    [{"URL": "...", "agent_id": "OC1::Agent1"}]
#                                    [{"Email": "john@cisco.com"}]
#                  (TODO: add validator — minimum one identifier per identity)
#
# Constraint (TODO): a valid L9Header must contain at least one SOURCE actor;
# zero or more DESTINATION actors are allowed.
##




    """
    1. intent KIND
Defines goals, constraints, and success criteria

2. delegate  KIND
Defines structured task assignment

3. knowledge KIND
Represents assertions, hypotheses, or proposals

4. query SUBKIND = KIND Knowledge
Requests missing information

5. evidence_bundle SUBKIND = KIND Knowledge
Provides validation artifacts

6. commit
Represents stabilized shared state

7. memory_delta SUBKIND = KIND Knowledge
Represents curated updates to shared memory
    """

class Identity(BaseModel):
    """
    The verifiable identity of an actor participating in an L9 message exchange.

    Fields:
        type         — agent framework or platform label (e.g. "OpenClaw").
        attestation  — optional proof-of-identity token: JWT, certificate fingerprint,
                       or any string that can be verified out-of-band.
        identifiers  — one or more typed address entries that allow the actor to be
                       located or contacted, e.g.:
                           [{"URL": "https://myagent1:8080"}]
                           [{"URL": "https://host:port", "agent_id": "OC1::Agent1"}]
                           [{"Email": "john@cisco.com"}]
                       TODO: add validator — minimum one identifier per identity.
    """
    type:         str                              ## e.g. "OpenClaw", "LangGraph", etc.
    attestation:  Optional[str]                = None ## TODO review if we need
    identifiers:  Optional[List[Dict[str, str]]] = None


class Actor(BaseModel):
    """
    A participant in an L9 message exchange.

    Fields:
        actor_type — the role this actor plays: SOURCE, DESTINATION, USER, or a
                     custom application-defined type.
        identity   — the verifiable identity of the actor (see Identity).
    """
    actor_type: str
    identity:   Identity

class L9Header(BaseModel):
    """
    Routing and identity envelope for an L9 message.

    Fields:
        message_id         — unique UUID for this message; auto-generated on creation.
        version            — L9 protocol version string (default "0.0.1").
        kind               — top-level semantic category: Intent | Knowledge | Repair.
        sub_kind           — narrows the purpose within the Kind (see L9SubKind).
        creation_timestamp — ISO-8601 UTC timestamp; auto-generated on creation.
        actors             — ordered list of Actor objects describing all participants.
                             Must contain at least one SOURCE actor (validation TODO).
    """

    message_id:         str          = Field(default_factory=lambda: str(uuid.uuid4()))
    version:            str          = "0.0.1"
    kind:               L9Kind       = L9Kind.INTENT
    sub_kind:           L9SubKind    = L9SubKind.intent_ambiguity_detector
    creation_timestamp: str          = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actors:             List[Actor]  = None  ## TODO: add validator — minimum one SOURCE actor required and DESTINATION actors.


# ─────────────────────────────────────────────────────────────────────────────
# L9Payload — phase-specific content
# ─────────────────────────────────────────────────────────────────────────────

class L9Payload(BaseModel):
    """
    Content envelope for an L9 message.

    Fields:
        sub_protocol        — friendly name identifying the implementation approach
                              that processes this payload (e.g. "NegMas", "Stigmetry").
                              Consumers use this to route the payload to the correct
                              sub-protocol handler.

        sub_protocol_schema — URI or inline reference to the JSON schema that defines
                              the expected structure of semantic_context for this
                              sub_protocol (e.g. "https://schemas.l9/negmas-v1.json").
                              Allows receivers to validate the payload before processing.

        semantic_context    — free-form dict carrying the sub-protocol-specific data.
                              Its structure is governed by sub_protocol_schema.
                              Examples:
                                {"goal": "...", "ambiguity_score": 0.72}
                                {"pheromone_map": {...}, "convergence": 0.95}
    """

    sub_protocol:        Optional[str]            = None
    sub_protocol_schema: Optional[str]            = None
    semantic_context:    Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# L9 — combined message
# ─────────────────────────────────────────────────────────────────────────────

class L9(BaseModel):
    """
    A complete L9 protocol message — the top-level unit of exchange between actors.

    Serialized form:
        {
            "header":  { ...L9Header fields... },
            "payload": { ...L9Payload fields... }
        }

    The header identifies who is communicating and what semantic category the
    message belongs to (Kind + SubKind).  The payload carries the sub-protocol
    name, its schema reference, and the semantic context data.

    Typical construction:
        msg = L9(
            header=L9Header(
                kind=L9Kind.INTENT,
                sub_kind=L9SubKind.intent_ambiguity_detector,
                actors=[Actor(actor_type="SOURCE", identity=Identity(...))],
            ),
            payload=L9Payload(
                sub_protocol="NegMas",
                sub_protocol_schema="https://schemas.l9/negmas-v1.json",
                semantic_context={"goal": "...", "ambiguity_score": 0.72},
            ),
        )
    """

    header:  L9Header  = Field(default_factory=L9Header)
    payload: L9Payload = Field(default_factory=L9Payload)
