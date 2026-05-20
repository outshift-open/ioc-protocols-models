"""
Phase 4 — Communication
Conversation within the MAS: Agent-Agent and Agent-Tool (state management).
query  — retrieve an EvidenceBundle from a source/tool
ingest — absorb a retrieved bundle into shared state
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from l9.shared import EvidenceBundle


class CommunicationSubKind(str, Enum):
    AGENT_AGENT      = "agent_agent"
    AGENT_TOOL       = "agent_tool"
    STATE_MANAGEMENT = "state_management"


class CommunicationAction(str, Enum):
    SEND_MESSAGE = "send_message"
    INVOKE_TOOL  = "invoke_tool"
    UPDATE_STATE = "update_state"
    BROADCAST    = "broadcast"
    QUERY        = "query"   # retrieve an EvidenceBundle or knowledge artifact
    INGEST       = "ingest"  # absorb a retrieved bundle into shared state


class CommunicationEvent(str, Enum):
    MESSAGE_SENT     = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    TOOL_INVOKED     = "tool_invoked"
    TOOL_RESPONDED   = "tool_responded"
    STATE_UPDATED    = "state_updated"
    QUERY_ISSUED     = "query_issued"
    BUNDLE_INGESTED  = "bundle_ingested"


class QueryRequest(BaseModel):
    """Issued by an agent to retrieve an EvidenceBundle from a source."""
    query_id:   str            = ""
    query_text: str            = ""
    target:     str            = ""   # tool name or external URI
    filters:    Dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    """Result returned for a QueryRequest."""
    query_id: str                  = ""
    bundles:  List[EvidenceBundle] = Field(default_factory=list)
    error:    Optional[str]        = None


class IngestResult(BaseModel):
    """Outcome of an INGEST action on a QueryResponse."""
    bundle_id: str          = ""
    status:    str          = "pending"   # pending | success | failed
    error:     Optional[str] = None


class CommunicationState(BaseModel):
    message_log:      List[Dict[str, Any]] = Field(default_factory=list)
    tool_invocations: List[Dict[str, Any]] = Field(default_factory=list)
    shared_state:     Dict[str, Any]       = Field(default_factory=dict)
    query_log:        List[QueryRequest]   = Field(default_factory=list)
    ingest_log:       List[IngestResult]   = Field(default_factory=list)
    ingested_bundles: List[EvidenceBundle] = Field(default_factory=list)


class CommunicationKind(BaseModel):
    phase:     int                        = 4
    name:      str                        = "Communication"
    sub_kinds: List[CommunicationSubKind] = Field(default_factory=lambda: list(CommunicationSubKind))
    actions:   List[CommunicationAction]  = Field(default_factory=lambda: list(CommunicationAction))
    events:    List[CommunicationEvent]   = Field(default_factory=lambda: list(CommunicationEvent))
    state:     CommunicationState         = Field(default_factory=CommunicationState)

    def query(self, request: QueryRequest) -> None:
        """Log a QUERY action (QUERY_ISSUED event)."""
        self.state.query_log.append(request)

    def ingest(self, bundle: EvidenceBundle) -> IngestResult:
        """Absorb an EvidenceBundle into shared state (BUNDLE_INGESTED event)."""
        bundle.ingested = True
        self.state.ingested_bundles.append(bundle)
        result = IngestResult(bundle_id=bundle.bundle_id, status="success")
        self.state.ingest_log.append(result)
        return result
