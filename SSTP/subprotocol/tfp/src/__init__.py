# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Source-of-truth Pydantic models for the TFP subprotocol.

``spec/tfp_schema.json`` is generated from these models via
``scripts/generate_spec.sh``; the language bindings are generated from that
schema. Edit the models here, never the generated artifacts.
"""

from .tfp_models import (
    CandidateOffer,
    RoleAssignment,
    SkillClaim,
    SkillRequirement,
    TaskSpec,
    TeamSelection,
    TFPOperation,
    TFPPayload,
)

__all__ = [
    "CandidateOffer",
    "RoleAssignment",
    "SkillClaim",
    "SkillRequirement",
    "TaskSpec",
    "TeamSelection",
    "TFPOperation",
    "TFPPayload",
]
