from pydantic import BaseModel

class Actor(BaseModel):
    """
    Actor model
    """
    id: str
    type: str
    name: str
    role: str

class SemanticContext(BaseModel):
    """
    SemanticContext model
    """
    schema_id: str
    ontology_ref: str
    cognition_protocol: str

class PolicyLabel(BaseModel):
    """
    PolicyLabel model
    """
    ## TODO Nandu , Peter please review
    sensitivity: str       
    propagation: str
    retention_policy: str


class Provenance(BaseModel):
    """
    Provenance model
    """
