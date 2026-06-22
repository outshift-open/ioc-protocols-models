# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from pydantic import BaseModel
from typing import Optional, Dict
from ioc_l9.src.epistemic import Epistemic
class Message(BaseModel):
    """
    Represents a message in the protocol.
    """
    id: str       # unique message identifier
    parents: str  # message content
    episode: str

class Actor(BaseModel):
    """
    A participant in a protocol exchange — can be a human, a system, or any
    other entity. Multiple actors are listed in ParticipantSet to identify
    sender(s), receiver(s), and observers.
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
    Tracks the origin and lineage of a message — who created it, from what source,
    and through which transformations. Fields TBD.
    """




class Semantic(BaseModel):
    """
    Describes the semantic/ontological framework needed to correctly interpret the payload.
    Implementations use this to select the appropriate handler for the message.
    """
    schema_id: str            # identifies the payload schema/format
    ontology_ref: str         # URI or ID of the ontology governing the domain vocabulary
    provenance: Optional[Provenance] = None   # optional origin/lineage tracking

class Context(BaseModel):
    topic: str
    epistemic: Optional[Epistemic] = None
    semantic: Optional[Semantic] = None