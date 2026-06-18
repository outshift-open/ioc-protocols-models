"""
TFP — Team Formation via Polling.

A subprotocol of SSTP/L9. TFP lets an *initiator* agent that holds a task find
peer agents with the relevant skills and assemble a team to accomplish it.

These models describe the **TFP payload** only — the subprotocol-specific content
that travels inside an L9 message's payload (``L9Payload(type="json-schema", data=...)``)
whenever ``L9Header.subprotocol == "TFP"``. The L9 header (envelope) is unchanged
and is defined in ``ioc_l9.src``.

Message flow (one episode):
    *Kind*       *Subkind*            *Operation*         *Meaning*

    intent      team_form_poll        poll_open         initiator broadcasts task + required skills to a group
    exchange    team_form_response    bid               each candidate advertises its skills / availability / fit
    exchange    team_form_response    decline           a candidate opts out (optional)
    exchange    team_form_response    select            initiator picks members and assigns roles
    exchange    team_form_response    accept            a selected candidate confirms membership (with a reason)
    exchange    team_form_response    reject            a selected candidate declines to join (with a reason);
                                                        the recruiter may re-select a fallback candidate
    exchange    team_form_repoll      re_poll           re-poll for uncovered mandatory skills / if candidates reject the proposal to join
    commit      team_form_converged   form_converged    team is formed successfully
    commit      team_form_failed      form_failed       team formation failed (mandatory skills uncovered and no fallback candidate found)

"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TFPOperation(str, Enum):
    """The TFP operation carried by a single turn (analogous to SNP ``operation``)."""

    POLL_OPEN = "poll_open"   # initiator broadcasts the task + required skills
    BID = "bid"               # candidate advertises its skills/availability/fit
    DECLINE = "decline"       # candidate opts out of this poll (before selection)
    CLARIFY = "clarify"       # request for / answer to additional detail
    SELECT = "select"         # initiator selects a candidate into the team
    ACCEPT = "accept"         # selected candidate confirms membership
    REJECT = "reject"         # selected candidate declines the proposal to join
    FORM_FAILED = "form_failed" # team formation failed (mandatory skills uncovered)
    FORM_CONVERGED = "form_converged" # team finalized / committed
    RE_POLL = "re_poll" # re-poll for uncovered mandatory skills


class TFPSubkind(str, Enum):
    """
    Canonical L9 ``header.subkind`` values for TFP turns. The ``subkind`` tags the
    phase of a turn within the episode (the ``operation`` in the payload still
    carries the fine-grained semantics).

    Phase mapping:
      * ``intent``/``contingency`` poll turns  -> ``team_form_poll``
      * ``exchange`` turns (bid/decline/select/accept/reject) -> ``team_form_response``
      * terminal ``commit`` turn               -> ``team_form_converged`` | ``team_form_failed``
    """

    POLL = "team_form_poll"            # a call-for-bids was opened (initial or re-poll)
    RESPONSE = "team_form_response"    # any reply/turn during discovery & selection
    CONVERGED = "team_form_converged"  # commit: a team was formed
    FAILED = "team_form_failed"        # commit: formation failed (mandatory skills uncovered)
    RE_POLL = "team_form_re_poll"      # re-poll for uncovered mandatory skills / if candidates reject the proposal to join


class SkillRequirement(BaseModel):
    """A single skill the task needs, declared by the initiator on ``poll_open``."""

    skill: str                                              # e.g. "skill:python", "skill:threat_triage"
    min_proficiency: float = Field(0.0, ge=0.0, le=1.0)     # minimum acceptable proficiency
    weight: float = Field(1.0, ge=0.0)                      # relative importance when scoring fit
    mandatory: bool = True                                  # must be covered for the team to be valid


class SkillClaim(BaseModel):
    """A skill a candidate claims to possess, declared on ``bid``."""

    skill: str
    proficiency: float = Field(..., ge=0.0, le=1.0)         # self-assessed proficiency [0..1]


class TaskSpec(BaseModel):
    """What the team is being formed to accomplish."""

    task_id: str
    description: str
    objective: Optional[str] = None
    deadline: Optional[str] = None


class CandidateOffer(BaseModel):
    """A candidate's response to a poll — its advertised capability for this task."""

    skills: List[SkillClaim] = Field(default_factory=list)
    availability: Optional[float] = Field(None, ge=0.0, le=1.0)  # optional: 0.0 = busy .. 1.0 = free
    fit_score: Optional[float] = Field(None, ge=0.0, le=1.0)  # candidate's self-assessed fit
    cost: Optional[float] = None                            # optional cost/effort estimate
    notes: Optional[str] = None


class RoleAssignment(BaseModel):
    """Role given to a selected member within the formed team."""

    agent_id: str
    role: str
    responsible_for: List[str] = Field(default_factory=list)  # skills / sub-tasks owned


class TeamSelection(BaseModel):
    """The initiator's selection decision, carried on ``select`` and ``form``."""

    members: List[str] = Field(default_factory=list)
    roles: List[RoleAssignment] = Field(default_factory=list)
    coverage: float = Field(0.0, ge=0.0, le=1.0)            # fraction of mandatory skills covered
    unmet_skills: List[str] = Field(default_factory=list)   # mandatory skills still missing
    aggregate_fit: Optional[float] = Field(None, ge=0.0, le=1.0)


class TFPPayload(BaseModel):
    """
    The TFP subprotocol payload. Goes inside ``L9Payload.data`` when
    ``L9Header.subprotocol == "TFP"`` and ``L9Payload.type == "json-schema"``.

    Fields are populated according to ``operation``:
      * ``poll_open`` sets ``task`` + ``required_skills``
      * ``bid``       sets ``offer``
      * ``select`` / ``form`` set ``selection``
    """

    operation: TFPOperation
    poll_id: str                                            # per-poll-round ID (payload layer); distinct from header message.episode — a re-poll within one episode gets a new poll_id

    task: Optional[TaskSpec] = None
    required_skills: List[SkillRequirement] = Field(default_factory=list)
    offer: Optional[CandidateOffer] = None
    selection: Optional[TeamSelection] = None

    # Why the candidate accepted/rejected the proposal to join (or declined the
    # poll). Free text the recruiter can log and feed into reputation.
    reason: Optional[str] = None
    reasoning_summary: Optional[str] = None
