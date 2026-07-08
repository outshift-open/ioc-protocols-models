# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SAB — Semantic Alignment via Bargaining: source-of-truth payload models.

These hand-authored Pydantic models are the **source of truth** for the SAB
subprotocol. The pipeline mirrors TFP/SIEP/CIP:

    src/sab_models.py               (these models — edit here)
        │  spec/generate_sab_schema.py
        ▼
    spec/sab_schema.json            (generated JSON Schema for payload.data)
        │  language_bindings/python/generate.sh
        ▼
    language_bindings/python/ai/outshift/sab/data_model.py

Do NOT hand-edit ``sab_schema.json`` or the generated ``data_model.py``. Change
these models and re-run the generators.

Scope
-----
These models describe **only** ``L9Payload.data`` (carried when
``L9Payload.type == "json-schema"``). SAB does **not** redeclare an L9 header —
the envelope is the canonical ``L9Header`` / ``L9Payload`` / ``L9`` from the L9
core. :class:`~SSTP.subprotocol.sab.src.builder.SABMessageBuilder` assembles the
full ``L9`` and writes SAB metadata (e.g. ``msg_created_at``) into the canonical
``header.attributes`` dict.

Message flow / kind mapping (applied by the builder, reflected in
``header.kind`` / ``header.subkind``):

    CE status   L9 kind        L9 subkind      payload.data variant
    ─────────   ───────────    ────────────    ─────────────────────────
    intent      contingency    negotiation     SABIntentPayloadData
    ongoing     contingency    negotiation     SABNegotiatePayloadData
    agreed      commit         converged       SABCommitPayloadData
    broken      commit         timeout         SABCommitPayloadData
    timeout     commit         disagreement    SABCommitPayloadData

The SAO sub-models mirror NegMAS 0.15.1 (``negmas.sao.common`` /
``negmas.gb.common``) — ported from
``ioc-cfn-cognitive-agents/protocol/sstp/negmas_sao.py`` so this package stays
self-contained (no cross-repo import).
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    computed_field,
    field_serializer,
    field_validator,
)

# ---------------------------------------------------------------------------
# Literals / type aliases
# ---------------------------------------------------------------------------

EncodingType = Literal["json", "structured_text", "hybrid"]

# NegMAS: negmas.outcomes.Outcome = tuple | dict | Mapping | None (dict in practice).
Outcome = Union[Dict[str, Any], Tuple, None]


# ---------------------------------------------------------------------------
# SAB kind / subkind vocabulary
#
# These are NOT baked into a bespoke header class — the builder uses them to set
# the canonical ``L9Header.kind`` / ``L9Header.subkind``.
# ---------------------------------------------------------------------------


class SABKind(str, Enum):
    """Allowed values for ``L9Header.kind`` on an SAB message."""

    contingency = "contingency"
    commit = "commit"


class SABSubkind(str, Enum):
    """Allowed values for ``L9Header.subkind`` on an SAB message."""

    negotiation = "negotiation"
    converged = "converged"
    disagreement = "disagreement"
    timeout = "timeout"


# ---------------------------------------------------------------------------
# NegMAS SAO mirror (negmas 0.15.1.post1)
#
# Inheritance chain: MechanismState → GBState → SAOState.
# All field names match the NegMAS source so snapshots round-trip.
# ---------------------------------------------------------------------------


class ResponseType(IntEnum):
    """Possible responses to offers during a NegMAS SAO negotiation round.

    Mirrors ``negmas.gb.common.ResponseType``.
    """

    ACCEPT_OFFER = 0
    REJECT_OFFER = 1
    END_NEGOTIATION = 2
    NO_RESPONSE = 3
    WAIT = 4
    LEAVE = 5


class ThreadState(BaseModel):
    """Per-thread state in a GB (Generalized Bargaining) round."""

    new_offer: Outcome = None
    new_data: Optional[Dict[str, Any]] = None
    new_responses: Dict[str, ResponseType] = Field(default_factory=dict)
    accepted_offers: List[Outcome] = Field(default_factory=list)


class MechanismState(BaseModel):
    """Base state for all NegMAS negotiation mechanisms."""

    running: bool = False
    waiting: bool = False
    started: bool = False
    step: int = 0
    time: float = 0.0
    relative_time: float = 0.0
    broken: bool = False
    timedout: bool = False
    agreement: Outcome = None
    results: Any = None
    n_negotiators: int = 0
    has_error: bool = False
    error_details: str = ""
    erred_negotiator: str = ""
    erred_agent: str = ""


class GBState(MechanismState):
    """State for Generalized Bargaining mechanisms; parent of SAOState."""

    threads: Dict[str, ThreadState] = Field(default_factory=dict)
    last_thread: str = ""
    left_negotiators: List[str] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def n_participating(self) -> int:
        """Number of negotiators still active (= n_negotiators − left)."""
        return self.n_negotiators - len(self.left_negotiators)


class SAOState(GBState):
    """Full mechanism state for the Stacked Alternating Offers (SAO) protocol."""

    current_offer: Outcome = None
    current_proposer: Optional[str] = None
    current_proposer_agent: Optional[str] = None
    n_acceptances: int = 0
    new_offers: List[Tuple[str, Outcome]] = Field(default_factory=list)
    new_offerer_agents: List[Optional[str]] = Field(default_factory=list)
    last_negotiator: Optional[str] = None
    current_data: Optional[Dict[str, Any]] = None
    new_data: List[Tuple[str, Optional[Dict[str, Any]]]] = Field(default_factory=list)


class SAOResponse(BaseModel):
    """A single negotiator response in one SAO round."""

    response: ResponseType = ResponseType.NO_RESPONSE
    outcome: Outcome = None
    data: Optional[Dict[str, Any]] = None

    @field_validator("response", mode="before")
    @classmethod
    def _coerce_response(cls, v: Any) -> ResponseType:
        """Accept the int value (0) or the enum name ('ACCEPT_OFFER')."""
        if isinstance(v, ResponseType):
            return v
        if isinstance(v, int):
            return ResponseType(v)
        if isinstance(v, str):
            try:
                return ResponseType[v]
            except KeyError:
                return ResponseType(int(v))
        return ResponseType(v)

    @field_serializer("response")
    def _serialize_response(self, v: ResponseType) -> str:
        """Serialize ResponseType as its human-readable name, not the int."""
        return v.name


class SAONMI(BaseModel):
    """NegotiatorMechanismInterface configuration snapshot for SAO.

    Omits the internal ``_mechanism`` back-reference and the ``time_limit`` /
    ``n_steps`` computed fields (derived at runtime). All base fields have
    defaults so this can be built from a plain dict / JSON snapshot.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    n_outcomes: Union[int, float] = 0
    shared_time_limit: float = float("inf")
    shared_n_steps: Optional[int] = None
    private_time_limit: float = float("inf")
    private_n_steps: Optional[int] = None
    pend: float = 0.0
    pend_per_second: float = 0.0
    step_time_limit: float = float("inf")
    negotiator_time_limit: float = float("inf")
    dynamic_entry: bool = False
    max_n_negotiators: Optional[int] = None
    annotation: Dict[str, Any] = Field(default_factory=dict)
    end_on_no_response: bool = True
    one_offer_per_step: bool = False
    offering_is_accepting: bool = True
    allow_none_with_data: bool = True
    allow_negotiators_to_leave: bool = True


# ---------------------------------------------------------------------------
# semantic_context variants
#
# ``schema_id``, ``issues`` and ``options_per_issue`` are intentionally NOT
# modelled here: at the L9 layer the envelope is identified by
# ``header.context.semantic.schema_id`` and issues/options are promoted into
# ``header.context.topic`` by the builder. Keeping them out of payload.data
# matches the wire format.
# ---------------------------------------------------------------------------


class SemanticContext(BaseModel):
    """Schema/encoding metadata for a plain (intent) payload."""

    schema_version: str = "1.0"
    encoding: EncodingType = "json"


class NegotiateSemanticContext(BaseModel):
    """SAO-specific semantic context for ``kind='negotiate'`` messages.

    Carries a full NegMAS SAO snapshot so receivers have the mechanism state,
    the latest response, and (optionally) the NMI configuration in one place.
    """

    schema_version: str = "1.0"
    encoding: EncodingType = "json"
    session_id: str
    sao_state: Optional[SAOState] = None
    sao_response: Optional[SAOResponse] = None
    nmi: Optional[SAONMI] = None
    offer_validation_failure: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Set when the previous counter_offer was rejected for unrecognised "
            "issue keys/option values (validation failure, not a strategic "
            "reject). Shape: {rejected_agent_id, round, problems, hint}."
        ),
    )


class NegotiateCommitSemanticContext(BaseModel):
    """Semantic context for ``kind='commit'`` messages that finalize a negotiation."""

    schema_version: str = "1.0"
    encoding: EncodingType = "json"
    session_id: str
    outcome: str = Field(
        ...,
        description=(
            "High-level outcome: 'agreement' — consensus reached; "
            "'disagreement' — step budget exhausted; 'broken' — a participant "
            "dropped out or returned an invalid offer; 'error' — pipeline exception."
        ),
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Populated only when outcome='error'.",
    )
    content_text: Optional[str] = Field(
        default=None,
        description="Original natural-language mission description passed to /initiate.",
    )
    agents_negotiating: Optional[List[str]] = Field(
        default=None,
        description="Agent IDs that participated in this negotiation.",
    )
    final_agreement: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Agreed option per issue: {'issue_id': str, 'chosen_option': str}. "
            "None when the negotiation ended without agreement."
        ),
    )


# ---------------------------------------------------------------------------
# payload.data — the stripped SSTP message body carried in L9Payload.data
# ---------------------------------------------------------------------------


class SABOrigin(BaseModel):
    """Who produced this message (tenant_id is not carried at the L9 layer)."""

    actor_id: str
    attestation: Optional[str] = None


class SABPayloadBase(BaseModel):
    """Fields present in every SAB ``payload.data`` variant."""

    message_id: str
    version: str = Field(default="0", description="SSTP protocol version.")
    dt_created: str = Field(description="ISO 8601 creation timestamp.")
    origin: SABOrigin
    payload_hash: str = Field(description="SHA-256 hex digest of the original payload.")


class SABIntentPayloadData(SABPayloadBase):
    """``payload.data`` when the wrapped SSTP message is kind=intent."""

    semantic_context: SemanticContext


class SABNegotiatePayloadData(SABPayloadBase):
    """``payload.data`` when the wrapped SSTP message is kind=negotiate."""

    semantic_context: NegotiateSemanticContext


class SABCommitPayloadData(SABPayloadBase):
    """``payload.data`` when the wrapped SSTP message is kind=commit."""

    semantic_context: NegotiateCommitSemanticContext


class SABPayloadData(RootModel):
    """Union of the three SAB ``payload.data`` variants.

    This is the root the schema generator dumps. Variants are discriminated by
    the shape of ``semantic_context`` (commit and negotiate carry ``session_id``;
    commit additionally carries ``outcome``). Ordered most-constrained first so
    Pydantic's smart-union matching stays unambiguous.
    """

    root: Union[
        SABCommitPayloadData,
        SABNegotiatePayloadData,
        SABIntentPayloadData,
    ]


__all__ = [
    "EncodingType",
    "Outcome",
    "SABKind",
    "SABSubkind",
    "ResponseType",
    "ThreadState",
    "MechanismState",
    "GBState",
    "SAOState",
    "SAOResponse",
    "SAONMI",
    "SemanticContext",
    "NegotiateSemanticContext",
    "NegotiateCommitSemanticContext",
    "SABOrigin",
    "SABPayloadBase",
    "SABIntentPayloadData",
    "SABNegotiatePayloadData",
    "SABCommitPayloadData",
    "SABPayloadData",
]
