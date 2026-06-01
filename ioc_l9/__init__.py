"""
ioc_l9 package
"""
from pydantic import BaseModel

from ioc_l9.utils import Actor, SemanticContext, PolicyLabel, Provenance
from ioc_l9.representation_state import RepresentationState

class L9Header(BaseModel):
    """
    Header for L9 IOC
    """
    protocol: str
    version: str
    kind: str
    message_id: str
    dt_created: int
    actors: list[Actor]
    semantic_context: SemanticContext
    policy_labels: list[str]
    provenance: dict
    episode_id: str 
    parents_ids: list[str] ## TODO maybe we can put inside Actor object 

class L9Payload(BaseModel):
    """
    Payload for L9 IOC
    """
    type: str
    representation_state: RepresentationState
    data: dict

class L9(BaseModel):
    """
    L9 for L9 IOC
    """
    header: L9Header
    payload: L9Payload