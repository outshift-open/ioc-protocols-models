"""
Fluent builder for IE-subprotocol L9 messages.

The builder covers two distinct concerns, kept visually separate:

  1. Header fields  — kind, epistemic state, belief status, concept, parents
                      set via chainable single-responsibility methods

  2. L9 payload     — a typed SIEPPayload object passed as one argument to .payload()
                      constructed explicitly by the caller with SIEPPayload(…)

Usage:

    from ioc_l9 import SIEPPayload, IEUtterance, IEBelief

    msg = (
        SIEPMessageBuilder(episode, sender="agent-alpha")
            .exchange().grounding().asserted()
            .concept("concept:task_objective")
            .parents(prior_msg.message.id)
            .payload(SIEPPayload(
                utterance=IEUtterance(
                    evidence=[CONCEPT, SUB],
                    addresses_evidence=[CONCEPT],
                ),
                belief=IEBelief(prior=0.72, posterior=0.72),
            ))
            .build()
    )

Also exposes contingency_score() — the grounding-check formula used by SIEPEngine.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from ioc_l9 import (
    ActorRef, SIEPPayload, Kind, L9Message, MessageRef, PayloadPart,
    SubKind, SubProtocol,
)
from ioc_l9.epistemic import (
    AbstractEpistemic, BeliefStatus, EpistemicState, SIEPEpistemic, MessageAct,
)


def contingency_score(evidence: List[str], prior_evidence: List[str]) -> float:
    """
    Fraction of the prior turn's evidence that the current turn engages.

        score = |evidence ∩ prior_evidence| / |prior_evidence|

    Returns 1.0 when prior_evidence is empty (first turn — nothing to address).
    A score below θ_c = 0.40 triggers a grounding failure and repair cycle.
    """
    if not prior_evidence:
        return 1.0
    return len(set(evidence) & set(prior_evidence)) / len(prior_evidence)


class SIEPMessageBuilder:
    """
    Fluent builder for L9 / IE messages.

    Header setters and .payload() are the two halves of every message.
    Chain setter calls, then call .build() last.
    """

    def __init__(self, episode_urn: str, sender: str) -> None:
        self._ep     = episode_urn
        self._sender = sender
        # ── header ──
        self._kind:     Optional[Kind]    = None
        self._subkind:  Optional[SubKind] = None
        self._parents:  List[str]         = []
        # ── epistemic (header) ──
        self._msg_act:       Optional[MessageAct]    = None
        self._ep_state:      Optional[EpistemicState] = None
        self._belief_status: Optional[BeliefStatus]  = None
        self._concept:       Optional[str]            = None
        self._uncertainty:   float                    = 0.0
        # ── payload ──
        self._siep_payload: Optional[SIEPPayload] = None
        self._text:       Optional[str]       = None

    # ── kind ──────────────────────────────────────────────────────────────────

    def intent(self)          -> SIEPMessageBuilder: self._kind = Kind.intent;       return self
    def exchange(self)        -> SIEPMessageBuilder: self._kind = Kind.exchange;      return self
    def contingency(self)     -> SIEPMessageBuilder: self._kind = Kind.contingency;   return self
    def commit_converged(self)-> SIEPMessageBuilder:
        self._kind = Kind.commit; self._subkind = SubKind.converged; return self
    def commit_rejected(self) -> SIEPMessageBuilder:
        self._kind = Kind.commit; self._subkind = SubKind.rejected;  return self

    # ── epistemic state ────────────────────────────────────────────────────────

    def taskwork(self)     -> SIEPMessageBuilder: self._ep_state = EpistemicState.taskwork;     return self
    def grounding(self)    -> SIEPMessageBuilder: self._ep_state = EpistemicState.grounding;    return self
    def team_process(self) -> SIEPMessageBuilder: self._ep_state = EpistemicState.team_process; return self

    # ── belief status (also sets the matching message_act) ────────────────────

    def asserted(self)   -> SIEPMessageBuilder:
        self._belief_status = BeliefStatus.asserted;   self._msg_act = MessageAct.assertion; return self
    def challenged(self) -> SIEPMessageBuilder:
        self._belief_status = BeliefStatus.challenged; self._msg_act = MessageAct.challenge; return self
    def revised(self)    -> SIEPMessageBuilder:
        self._belief_status = BeliefStatus.revised;    self._msg_act = MessageAct.assertion; return self
    def unresolved(self) -> SIEPMessageBuilder:
        self._belief_status = BeliefStatus.unresolved; return self

    # ── concept / uncertainty ─────────────────────────────────────────────────

    def concept(self, c: str)       -> SIEPMessageBuilder: self._concept    = c; return self
    def uncertainty(self, u: float) -> SIEPMessageBuilder: self._uncertainty = u; return self

    # ── causal chain ──────────────────────────────────────────────────────────

    def parents(self, *ids: str) -> SIEPMessageBuilder:
        self._parents = list(ids); return self

    # ── payload ───────────────────────────────────────────────────────────────

    def payload(self, ie: SIEPPayload) -> SIEPMessageBuilder:
        """Attach the IE-specific L9 payload. Constructed explicitly by the caller."""
        self._siep_payload = ie
        return self

    def text(self, t: str) -> SIEPMessageBuilder:
        """Attach a natural-language utterance string as a separate payload part."""
        self._text = t
        return self

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> L9Message:
        if self._kind is None:
            raise ValueError("Set a kind (.intent()/.exchange()/…) before calling .build()")

        parts: List[PayloadPart] = []
        if self._siep_payload is not None:
            parts.append(PayloadPart(type="siep", location="inline", content=self._siep_payload))
        if self._text:
            parts.append(PayloadPart(type="utterance", location="inline", content=self._text))

        epistemic = (
            SIEPEpistemic(
                message_act=self._msg_act,
                state=self._ep_state,
                belief_status=self._belief_status,
                concept_id=self._concept,
                uncertainty=self._uncertainty,
            )
            if (self._belief_status is not None or self._concept is not None)
            else AbstractEpistemic(
                message_act=self._msg_act,
                state=self._ep_state,
                uncertainty=self._uncertainty,
            )
        )

        return L9Message(
            subprotocol=SubProtocol.SIEP,
            kind=self._kind,
            subkind=self._subkind,
            actor=ActorRef(id=self._sender),
            message=MessageRef(
                id=str(uuid.uuid4()),
                parents=self._parents,
                episode=self._ep,
            ),
            epistemic=epistemic,
            payload=parts,
        )

