"""
ioc_l9 package
"""
from typing import Optional
from pydantic import BaseModel

from ioc_l9.utils import Actor, SemanticContext, PolicyLabel, Provenance, Group
from ioc_l9.epistemic import Epistemic
class L9Header(BaseModel):
    """
    Header for L9 IOC
    """
    protocol: str
    version: str
    kind: str
    sub_kind: str
    group: Group
    actors: list[Actor]
    semantic: SemanticContext
    policy: Optional[PolicyLabel] = None
    provenance: Optional[Provenance] = None
    epistemic: Optional[Epistemic] = None
class L9Payload(BaseModel):
    """
    Payload for L9 IOC
    """
    type: str
    data: dict

class L9(BaseModel):
    """
    L9 for L9 IOC
    """
    header: L9Header
    payload: L9Payload