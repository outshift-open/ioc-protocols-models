# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from pydantic import BaseModel
from typing import Optional, Dict
from src.epistemic import Epistemic
class Message(BaseModel):
    """
    Represents a single message in the protocol.
    In the stateful design, messages are embedded within episodes,
    so we only need the message ID here.
    """
    id: str  # unique message identifier

class Actor(BaseModel):
    """
    A participant in a protocol exchange - can be a human, an AI agent, or a system.
    Multiple actors are listed in L9Header.actors to identify sender(s) and receiver(s).
    """
    id: str    # unique identifier for this actor
    role: str  # role in this exchange: "sender" | "receiver" | "observer" etc.
    attestation: Optional[str] = None  # optional attestation or credential information

class ParticipantSet(BaseModel):
    actors: list[Actor] # The list of actors in this message
    groups: Optional[Dict] # a place to add mas_id, workspace_id or any other grouping of the actors
class PolicyLabel(BaseModel):
    """
    Data governance and access-control labels applied to the message.
    """
    sensitivity: str        # data sensitivity level e.g. "public" | "confidential" | "restricted"
    propagation: str        # how far this label propagates to downstream messages
    retention_policy: str   # how long this message/data should be retained


class Provenance(BaseModel):
    """
    Tracks the origin and lineage of a message - who created it, from what source,
    and through which transformations. Fields TBD.
    """
    # TODO: add fields - e.g. source_agent_id, created_at, derived_from




class Semantic(BaseModel):
    """
    Describes the semantic/ontological framework needed to correctly interpret the payload.
    The CFN routing layer uses this to select appropriate cognitive engines (CEs).
    """
    schema_id: str            # identifies the payload schema/format
    ontology_ref: str         # URI or ID of the ontology governing the domain vocabulary
    provenance: Optional[Provenance] = None   # optional origin/lineage tracking

class Context(BaseModel):
    topic: str
    epistemic: Optional[Epistemic] = None
    semantic: Optional[Semantic] = None


class Episode(BaseModel):
    """
    A discrete conversation or interaction sequence.
    An episode groups the messages exchanged during one focused interaction
    (e.g. one round of clarification, one tool invocation cycle).
    """
    id: str                  # unique episode identifier
    messages: list[Message]  # ordered sequence of messages in this episode


class Session(BaseModel):
    """
    A complete session containing all episodes and messages.
    Each L9 message carries the full session state, providing complete history.
    """
    id: str                   # unique session identifier
    episodes: list[Episode]   # all episodes in this session