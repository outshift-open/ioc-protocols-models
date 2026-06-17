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
    A participant in a protocol exchange — can be a human, an AI agent, or a system.
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
    ## TODO Nandu, Peter please review
    """
    sensitivity: str        # data sensitivity level e.g. "public" | "confidential" | "restricted"
    propagation: str        # how far this label propagates to downstream messages
    retention_policy: str   # how long this message/data should be retained


class Provenance(BaseModel):
    """
    Tracks the origin and lineage of a message — who created it, from what source,
    and through which transformations. Fields TBD.
    """
    # TODO: add fields — e.g. source_agent_id, created_at, derived_from




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