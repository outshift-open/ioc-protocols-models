"""
ioc_l9 package — L9 message envelope and IE/SNP payload models.

An L9 message is the fundamental unit of communication between agents in a MAS.
It is defined by Figure 1 of the L9 specification and carries:

  - routing + metadata header fields (protocol, kind, epistemic, …)
  - one or more typed payload parts (ie, snp, utterance, …)

Kind values (spec §kind):
  intent      — opens an episode; declares the topic
  exchange    — substantive work: proposals, peer turns, assessments
  contingency — signals a grounding problem that must be repaired before continuing
  commit      — closes a negotiation branch or repair cycle
  knowledge   — writes a converged fact to permanent memory

SubProtocol values:
  IE  — Semantic Interaction Exchange Protocol: grounding, contingency detection, repair
  SNP — Semantic Negotiation Protocol: multi-agent convergence
"""

from __future__ import annotations

<<<<<<< HEAD:ioc_l9/__init__.py
from enum import Enum
from typing import Annotated, List, Optional, Union

from pydantic import BaseModel, Field

from ioc_l9.primitives import (
    ActorRef, AttributesCtx, Group, MessageRef, PolicyCtx, SemanticCtx,
)
from ioc_l9.epistemic import AbstractEpistemic, SIEPEpistemic


# ── Discriminated union over all known epistemic subtypes ─────────────────────
# To register a new subtype, add it to this Union alongside its Literal value.

EpistemicField = Annotated[
    Union[SIEPEpistemic, AbstractEpistemic],
    Field(discriminator="epistemic_kind"),
]


# ── Protocol-level enumerations ────────────────────────────────────────────────

class Kind(str, Enum):
    intent      = "intent"
    exchange    = "exchange"
    contingency = "contingency"
    commit      = "commit"
    knowledge   = "knowledge"


class SubKind(str, Enum):
    converged = "converged"
    rejected  = "rejected"
    abort     = "abort"


class SubProtocol(str, Enum):
    SIEP = "SIEP"
    SNP = "SNP"


# ── IE payload types (spec §IE Payload Schema) ─────────────────────────────────

class RepairReason(str, Enum):
    grounding_failure    = "grounding_failure"     # response did not engage prior evidence
    scope_mismatch       = "scope_mismatch"        # concept is outside the sender's known scope
    ungroundable_novelty = "ungroundable_novelty"  # claim cannot be grounded in shared ontology


class RevisionCause(str, Enum):
    grounded_argument = "grounded_argument"  # peer's argument was contingent → genuine revision
    social_compliance = "social_compliance"  # yielded to pressure without being persuaded
    semantic_memory   = "semantic_memory"    # prior loaded from SemanticMemory at episode open
    new_evidence      = "new_evidence"       # external data injection
    repair_resolution = "repair_resolution"  # revised after a successful repair cycle


class SIEPUtterance(BaseModel):
    """
    Utterance portion of the IE payload — what the sender is arguing from
    and which prior-turn concepts it is engaging.
    """
    evidence: List[str] = Field(default_factory=list)
    addresses_evidence: List[str] = Field(default_factory=list)  # ∅ on first turn
    turn_depth: int = 0  # 0 = top-level; >0 = inside a repair branch

=======
from ioc_l9.src.primitives import Actors, PolicyLabel, Message, Context
>>>>>>> main:ioc_l9/src/__init__.py

class SIEPGrounding(BaseModel):
    """
    Grounding verification result — filled by the *receiver*, not the sender.
    Records whether the incoming turn genuinely engaged the prior turn's evidence.
    """
    contingency_verified: Optional[bool] = None    # True iff score ≥ θ_c
    contingency_score: Optional[float] = None      # |evidence ∩ prior| / |prior|
    repair_reason: Optional[RepairReason] = None   # set when contingency_verified=False
    challenges: List[str] = Field(default_factory=list)  # concept URIs the receiver disputes


<<<<<<< HEAD:ioc_l9/__init__.py
class SIEPBelief(BaseModel):
=======

class L9Header(BaseModel):
    """
    Routing and metadata envelope for every L9 message.
    The CFN layer reads the header — especially `kind` and `sub_kind` —
    to decide which Cognitive Engine (CE) should handle the message.
    """
    protocol: str                        # protocol name, e.g. "SSTP"
    subprotocol: str                      # subprotocol name, e.g. "CIP"
    version: str                         # protocol version string, e.g. "1.0"
    kind: str                            # message kind — drives CFN routing (see module docstring)
    subkind: str                        # finer-grained classification within the kind
    actors: Actors                 # all participants: sender(s), receiver(s), observers
    message: Optional[Message] = None 
    policy: Optional[PolicyLabel] = None      # optional data governance labels
    attributes: Optional[dict] = None
    context: Optional[Context] = None               # optional context 
    

class L9(BaseModel):
>>>>>>> main:ioc_l9/src/__init__.py
    """
    Belief state of the sender for a specific concept in this episode.
    prior is immutable after the initial_prior declaration (invariant T2).
    """
    prior: float = 0.5      # π(a,c,ε) — GAR anchor; immutable once declared
    posterior: float = 0.5  # ρ(a,c,ε) — current belief after all revisions
    revision_cause: Optional[RevisionCause] = None


class SIEPPayload(BaseModel):
    """Complete IE sub-protocol payload (spec §IE Payload Schema)."""
    utterance: SIEPUtterance = Field(default_factory=SIEPUtterance)
    grounding: SIEPGrounding = Field(default_factory=SIEPGrounding)
    belief: SIEPBelief = Field(default_factory=SIEPBelief)


# ── Payload wrapper ────────────────────────────────────────────────────────────

class PayloadPart(BaseModel):
    """
    One typed section of a message payload.
    type ∈ { "utterance", "ie", "snp", "process", … }
    content holds an SIEPPayload when type="siep".
    """
    type: str
    location: str = "inline"
    content: Optional[object] = None  # SIEPPayload | SNPPayload | str | dict
    ref: Optional[str] = None         # external payload reference URN


# ── Complete L9 message ────────────────────────────────────────────────────────

class L9Message(BaseModel):
    """
    Complete L9 message — the full envelope described in Figure 1 of the spec.

    All L9 header fields are inlined at the top level (matching the abstract
    schema M := { kind, subkind, subprotocol, epistemic, message, payload }).
    """
    # ── header identity ──
    protocol: str = "SSTP"
    version: str = "0"
    subprotocol: Optional[SubProtocol] = None
    kind: Kind
    subkind: Optional[SubKind] = None

    # ── header routing ──
    actor: Optional[ActorRef] = None
    message: MessageRef = Field(default_factory=MessageRef)
    semantic: SemanticCtx = Field(default_factory=SemanticCtx)
    policy: Optional[PolicyCtx] = None
    attributes: AttributesCtx = Field(default_factory=AttributesCtx)

    # ── header epistemic ──
    epistemic: EpistemicField = Field(default_factory=AbstractEpistemic)

    # ── payload ──
    payload: List[PayloadPart] = Field(default_factory=list)

    def siep_payload(self) -> Optional[SIEPPayload]:
        """Return the typed SIEPPayload from the payload list, or None."""
        for part in self.payload:
            if part.type == "siep" and isinstance(part.content, SIEPPayload):
                return part.content
        return None


# Legacy aliases — kept so any existing code that imported the old names
# still resolves without an immediate error.
L9Header = L9Message   # old name pointed at a header-only model; L9Message is now the full envelope
L9Payload = PayloadPart