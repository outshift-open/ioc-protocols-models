"""Shared primitives used across all L9 protocol phases."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class Knowledge(BaseModel):
    """A unit of knowledge held by an agent or the shared knowledge store."""
    domain:            str       = ""
    facts:             List[str] = Field(default_factory=list)
    confidence:        float     = 1.0
    source_bundle_ids: List[str] = Field(default_factory=list)  # traceability


class EvidenceBundle(BaseModel):
    """A packaged collection of evidence (docs, observations, data) with provenance."""
    bundle_id: str            = ""
    source:    str            = ""   # tool, agent, or external URI
    content:   List[str]      = Field(default_factory=list)
    metadata:  Dict[str, Any] = Field(default_factory=dict)
    ingested:  bool           = False
