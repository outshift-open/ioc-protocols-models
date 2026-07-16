# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SAB subprotocol source-of-truth package.

Exposes the payload models (``sab_models``) and :class:`SABMessageBuilder`.
Importing this package puts the L9 core language binding
(``SSTP/language_bindings/python``) on ``sys.path`` so ``ai.outshift.data_model``
resolves in-place — a pip-installed L9 wheel also satisfies the import.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve CI/ioc-protocols-models/SSTP/language_bindings/python and add to sys.path.
#   parents[0]=src [1]=sab [2]=subprotocol [3]=SSTP
_L9_PY_BINDING = Path(__file__).resolve().parents[3] / "language_bindings" / "python"
if _L9_PY_BINDING.is_dir() and str(_L9_PY_BINDING) not in sys.path:
    sys.path.insert(0, str(_L9_PY_BINDING))

from .builder import (  # noqa: E402
    SAB_L9_SCHEMA_URN,
    SAB_ONTOLOGY_REF,
    SERVER_ACTOR_ID,
    STATUS_KIND,
    SABMessageBuilder,
    build_topic,
    now_iso,
    payload_hash,
)
from .sab_models import (  # noqa: E402
    EncodingType,
    GBState,
    MechanismState,
    NegotiateCommitSemanticContext,
    NegotiateSemanticContext,
    Outcome,
    ResponseType,
    SABCommitPayloadData,
    SABIntentPayloadData,
    SABKind,
    SABNegotiatePayloadData,
    SABOrigin,
    SABPayloadBase,
    SABPayloadData,
    SABSubkind,
    SAONMI,
    SAOResponse,
    SAOState,
    SemanticContext,
    ThreadState,
)

__all__ = [
    # builder
    "SABMessageBuilder",
    "SAB_L9_SCHEMA_URN",
    "SAB_ONTOLOGY_REF",
    "SERVER_ACTOR_ID",
    "STATUS_KIND",
    "build_topic",
    "now_iso",
    "payload_hash",
    # enums / vocab
    "SABKind",
    "SABSubkind",
    "ResponseType",
    "EncodingType",
    "Outcome",
    # payload models
    "SABOrigin",
    "SABPayloadBase",
    "SABIntentPayloadData",
    "SABNegotiatePayloadData",
    "SABCommitPayloadData",
    "SABPayloadData",
    # semantic contexts
    "SemanticContext",
    "NegotiateSemanticContext",
    "NegotiateCommitSemanticContext",
    # SAO snapshot models
    "MechanismState",
    "GBState",
    "SAOState",
    "SAOResponse",
    "SAONMI",
    "ThreadState",
]
