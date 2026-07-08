#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""generate_sab_schema.py — generate sab_schema.json from the SAB source models.

The source of truth is ``../src/sab_models.py`` (hand-authored Pydantic). This
script dumps the JSON Schema of ``SABPayloadData`` — the union of the three
``L9Payload.data`` variants — and applies two small normalisation passes. It is
self-contained (no cross-repo import) and needs only this repo checked out.

Pipeline (mirrors TFP/SIEP/CIP):
    ../src/sab_models.py
        │  this script
        ▼
    sab_schema.json                     (payload.data schema)
        │  ../language_bindings/python/generate.sh
        ▼
    ../language_bindings/python/ai/outshift/sab/data_model.py

Scope note
----------
sab_schema.json describes only ``payload.data``. The L9 envelope
(``header`` / ``payload.type``) is the canonical L9 schema
(``SSTP/spec/l9_schema.json``); SAB does not redeclare it. The kind/subkind
vocabulary (contingency|commit / negotiation|converged|disagreement|timeout) is
applied by ``SABMessageBuilder`` and documented in ``sab_models.py`` and
``documentation/SAB.md``.

Run from any directory:
    python3 SSTP/subprotocol/sab/spec/generate_sab_schema.py

Output:
    SSTP/subprotocol/sab/spec/sab_schema.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SPEC_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SPEC_DIR.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import sab_models as m  # noqa: E402

# ResponseType is an IntEnum; JSON Schema captures only the integer values.
# x-enum-varnames (widely supported) preserves the member names so
# datamodel-codegen emits ACCEPT_OFFER … LEAVE instead of integer_0 … integer_5.
_RESPONSE_TYPE_NAMES = [
    "ACCEPT_OFFER",
    "REJECT_OFFER",
    "END_NEGOTIATION",
    "NO_RESPONSE",
    "WAIT",
    "LEAVE",
]


def main() -> None:
    output_path = _SPEC_DIR / "sab_schema.json"

    schema = m.SABPayloadData.model_json_schema()

    # Top-level metadata (mirrors the other subprotocol schemas).
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["version"] = "0.1.0"
    schema["protocol"] = "SSTP"
    schema["subprotocol"] = "SAB"
    schema.setdefault("title", "SABPayloadData")

    # Restore ResponseType member names lost during IntEnum serialisation.
    if "ResponseType" in schema.get("$defs", {}):
        schema["$defs"]["ResponseType"]["x-enum-varnames"] = _RESPONSE_TYPE_NAMES
        schema["$defs"]["ResponseType"]["description"] = (
            "Possible responses to offers during a NegMAS SAO negotiation round. "
            "Mirrors negmas.gb.common.ResponseType."
        )

    # Python float('inf') is not valid JSON — replace with max float64.
    output_text = json.dumps(schema, indent=2).replace(
        "Infinity", "1.7976931348623157e+308"
    )

    output_path.write_text(output_text + "\n")
    print(f"Generated: {output_path}")
    print(f"Root title: {schema.get('title')}")
    print(f"Top-level $defs: {sorted(schema.get('$defs', {}).keys())}")


if __name__ == "__main__":
    main()
