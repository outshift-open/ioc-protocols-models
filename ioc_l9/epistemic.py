"""
Epistemic representations for L9 messages.

AbstractEpistemic is the minimal contract every epistemic block must satisfy:
  - message_act   communicative intent (assertion/compliance/challenge)
  - state         protocol phase (taskwork/grounding/team_process)
  - uncertainty   confidence level [0..1]
  - epistemic_kind discriminator field — self-describes the subtype on the wire

Subclass AbstractEpistemic to add method-specific epistemic state.  The
discriminator field lets any receiver deserialize back to the right type
without out-of-band knowledge.

Currently defined subtypes:
  IEEpistemic ("ie")  — ToM/Interaction-Engine flavoured belief tracking;
                        carries belief_status and concept_id.

Add further subtypes (e.g. "fuzzy", "bayesian", "frame") by:
  1. Subclassing AbstractEpistemic with the new Literal value.
  2. Adding the subclass to EpistemicField in ioc_l9/__init__.py.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


# ── Shared enumerations (protocol-level, not method-specific) ─────────────────

class MessageAct(str, Enum):
    """Communicative intent of this turn (L9 spec §epistemic.speech_act)."""
    assertion  = "assertion"   # sender holds this belief with conviction; GAR counts this
    challenge  = "challenge"   # sender disagrees and is pushing back
    compliance = "compliance"  # sender yields without genuine conviction; SCR counts this


class EpistemicState(str, Enum):
    """Which epistemic protocol phase is active (L9 spec §epistemic.state)."""
    taskwork     = "taskwork"      # independent reasoning, no peer influence yet
    grounding    = "grounding"     # pairwise exchange — checking shared understanding
    team_process = "team_process"  # team-level coordination, negotiation, convergence


# ── IE/ToM-specific enumerations ──────────────────────────────────────────────

class BeliefStatus(str, Enum):
    """
    Sender's self-declared epistemic position at send time.
    Used by the Interaction Engine (ToM) for belief tracking.
    (L9 spec §epistemic.belief_status)
    """
    asserted   = "asserted"    # sender holds this belief and states it directly
    deferred   = "deferred"    # holding judgment, not committing yet
    challenged = "challenged"  # actively disputing a prior belief
    revised    = "revised"     # updated a prior belief based on new evidence
    retracted  = "retracted"   # withdrawing a previously asserted belief entirely
    unresolved = "unresolved"  # exchange ended without convergence


# ── Abstract base ─────────────────────────────────────────────────────────────

class AbstractEpistemic(BaseModel):
    """
    Minimal abstract epistemic block — the fields every L9 epistemic
    representation must carry, regardless of the method used.

    message_act and state are protocol-level: they describe the communicative
    role of this message within the L9 episode structure, independent of how
    the sender internally represents belief.

    uncertainty is likewise method-agnostic: every epistemic method can express
    some scalar confidence, even if internal representation differs.

    epistemic_kind is the wire discriminator — receivers use it to deserialize
    to the correct concrete subclass without out-of-band knowledge.
    """
    epistemic_kind: Literal["abstract"] = "abstract"
    message_act:    Optional[MessageAct]    = None
    state:          Optional[EpistemicState] = None
    uncertainty:    float = 0.0   # [0..1]; 0 = perfect confidence


# ── IE / ToM subtype ──────────────────────────────────────────────────────────

class IEEpistemic(AbstractEpistemic):
    """
    Interaction-Engine (ToM) flavoured epistemic block.

    Extends the abstract base with the two IE-specific tracking fields:
      belief_status — sender's self-declared position in the ToM belief cycle
      concept_id    — URI of the concept under discussion ("concept:{name}"
                      or a sub-concept URN)

    These fields are specific to IE/ToM and must NOT be assumed present when
    processing a message whose epistemic_kind is not "ie".
    """
    epistemic_kind: Literal["ie"] = "ie"
    belief_status:  Optional[BeliefStatus] = None
    concept_id:     Optional[str] = None
