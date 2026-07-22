# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
ioc_l9 package — L9 message format for the IoC protocol stack.

An L9 message is the fundamental unit of communication between participants.
It consists of a Header (routing + metadata) and a Payload (the actual data).

The `kind` field in the header drives routing decisions, directing the
message to the appropriate handler for processing.

Kind values and their meaning:
  exchange     — direct message transfer between participants
  intent       — participants negotiate shared understanding of intent/ambiguity
  contingency  — fallback handling: negotiation, repair, or escalation
  commit       — participants commit to a shared understanding before acting
  knowledge    — knowledge-base update or retrieval
"""

# Re-export all public classes for convenience
from src.l9 import Kind, L9Payload, L9Header, L9
from src.primitives import (
    Message,
    Actor,
    ParticipantSet,
    PolicyLabel,
    Provenance,
    Semantic,
    Context,
    Episode,
    Session,
    TaskWork,
    Team,
)
from src.epistemic import Epistemic

__all__ = [
    # L9 core
    "Kind",
    "L9Payload",
    "L9Header",
    "L9",
    # Primitives
    "Message",
    "Actor",
    "ParticipantSet",
    "PolicyLabel",
    "Provenance",
    "Semantic",
    "Context",
    "Episode",
    "Session",
    "TaskWork",
    "Team",
    # Epistemic
    "Epistemic",
]
