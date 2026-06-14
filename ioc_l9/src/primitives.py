from pydantic import BaseModel


class Group(BaseModel):
    """
    Logical grouping of actors — e.g. a team, session, or conversation thread.
    Used in L9Header to scope the message to a shared context.
    """
    id: str       # unique group identifier
    name: str     # human-readable label for the group


class Actor(BaseModel):
    """
    A participant in a protocol exchange — can be a human, an AI agent, or a system.
    Multiple actors are listed in L9Header.actors to identify sender(s) and receiver(s).
    """
    id: str    # unique identifier for this actor
    type: str  # actor category: "human" | "agent" | "system"
    name: str  # display name
    role: str  # role in this exchange: "sender" | "receiver" | "observer" etc.


class SemanticContext(BaseModel):
    """
    Describes the semantic/ontological framework needed to correctly interpret the payload.
    The CFN routing layer uses this to select appropriate cognitive engines (CEs).
    """
    schema_id: str            # identifies the payload schema/format
    ontology_ref: str         # URI or ID of the ontology governing the domain vocabulary
    cognition_protocol: str   # which cognitive protocol should process this message


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
