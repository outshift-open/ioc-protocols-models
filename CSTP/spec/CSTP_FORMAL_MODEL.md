# CSTP v0 Formal Model

Status: Reserved — not yet implemented.

## Overview

CSTP (Continuous Semantic Transport Protocol) is the L9 transport modality for propagating embedding or vector payloads between cognitive agents.

Intended use: similarity search, semantic clustering, and dense-retrieval coordination between agents and Cognition Engines.

**Wire field value:** `"CSTP"` (see `L9Transport.CSTP` in `sstp.l9_base`)

## Relationship to SSTP

CSTP uses the same L9 envelope header structure as SSTP.  The `protocol` field is set to `"CSTP"` and the payload carries an embedding vector rather than a JSON dict.

Sub-protocols for CSTP are defined by subclassing `L9HeaderBuilder` with `PROTOCOL = L9Transport.CSTP`.

## Status

No sub-protocols or payload schemas are defined for CSTP at this time.  This directory is reserved for future specification work.

## See also

- [SSTP Formal Model](../../SSTP/spec/SSTP_FORMAL_MODEL.md) — base envelope structure shared by all transports
- `l9_base.py` — `L9Transport.CSTP` constant
