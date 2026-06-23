"""TFP — Team Formation via Polling: source-of-truth models.

These hand-authored Pydantic models are the **source of truth** for the TFP
subprotocol payload. The pipeline is:

    src/tfp_models.py            (these models — edit here)
        │  scripts/generate_spec.sh
        ▼
    spec/tfp_schema.json         (generated JSON Schema)
        │  language_bindings/python/generate.sh
        ▼
    language_bindings/python/data_model.py   (generated bindings)

Do NOT hand-edit ``tfp_schema.json`` or ``data_model.py``. Change these
models and re-run the generators.
Message flow (one episode):
    *Kind*       *Subkind*            *Operation*         *Meaning*

    intent      team-formation   poll_open         initiator broadcasts task + required skills to a group
    exchange    team-formation   bid               each candidate advertises its skills / availability / fit
    exchange    team-formation   decline           a candidate opts out (optional)
    exchange    team-formation   select            initiator picks members and assigns roles
    exchange    team-formation   accept            a selected candidate confirms membership (with a reason)
    exchange    team-formation   reject            a selected candidate declines to join (with a reason);
                                                        the recruiter may re-select a fallback candidate
    exchange    team-formation   re_poll           re-poll for uncovered mandatory skills / if candidates reject the proposal to join
    commit      converged             form_converged    team is formed successfully
    commit      abort                 form_failed       team formation failed (mandatory skills uncovered and no fallback candidate found)
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TFPOperation(str, Enum):
    """The TFP operation carried by a single turn ."""

    POLL_OPEN = "poll_open"
    BID = "bid"
    DECLINE = "decline"
    CLARIFY = "clarify"
    SELECT = "select"
    ACCEPT = "accept"
    REJECT = "reject"
    FORM_FAILED = "form_failed"
    FORM_CONVERGED = "form_converged"
    RE_POLL = "re_poll"


class SkillRequirement(BaseModel):
    """A single skill the task needs, declared by the initiator on ``poll_open``."""

    skill: str
    min_proficiency: float = Field(0.0, ge=0.0, le=1.0)
    weight: float = Field(1.0, ge=0.0)
    mandatory: bool = True


class SkillClaim(BaseModel):
    """A skill a candidate claims to possess, declared on ``bid``."""

    skill: str
    proficiency: float = Field(..., ge=0.0, le=1.0)


class TaskSpec(BaseModel):
    """What the team is being formed to accomplish."""

    task_id: str
    description: str
    objective: Optional[str] = None
    deadline: Optional[str] = None


class CandidateOffer(BaseModel):
    """A candidate's response to a poll — its advertised capability for this task."""

    skills: List[SkillClaim] = Field(default_factory=list)
    availability: Optional[float] = Field(None, ge=0.0, le=1.0)
    fit_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    cost: Optional[float] = None
    notes: Optional[str] = None


class RoleAssignment(BaseModel):
    """Role given to a selected member within the formed team."""

    agent_id: str
    role: str
    responsible_for: List[str] = Field(default_factory=list)


class TeamSelection(BaseModel):
    """The initiator's selection decision, carried on ``select`` and ``form``."""

    members: List[str] = Field(default_factory=list)
    roles: List[RoleAssignment] = Field(default_factory=list)
    coverage: float = Field(0.0, ge=0.0, le=1.0)
    unmet_skills: List[str] = Field(default_factory=list)
    aggregate_fit: Optional[float] = Field(None, ge=0.0, le=1.0)


class TFPPayload(BaseModel):
    """The TFP subprotocol payload. Goes inside ``L9Payload.data`` when
    ``L9Header.subprotocol == "TFP"`` and ``L9Payload.type == "json-schema"``.

    Fields are populated according to ``operation``:
      * ``poll_open`` sets ``task`` + ``required_skills``
      * ``bid``       sets ``offer``
      * ``select`` / ``form`` set ``selection``
    """

    operation: TFPOperation
    poll_id: str
    task: Optional[TaskSpec] = None
    required_skills: List[SkillRequirement] = Field(default_factory=list)
    offer: Optional[CandidateOffer] = None
    selection: Optional[TeamSelection] = None
    reason: Optional[str] = None
    reasoning_summary: Optional[str] = None
