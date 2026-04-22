# LSTP v0 Formal Model

Status: Reserved — not yet implemented.

## Overview

LSTP (Latent Semantic Transport Protocol) is the L9 transport modality for propagating latent / tensor representations between cognitive agents.

Intended use: high-fidelity cognitive coordination where full distributional representations must be propagated — for example, cross-model knowledge distillation or shared embedding-space alignment.

**Wire field value:** `"LSTP"` (see `L9Transport.LSTP` in `sstp.l9_base`)

## Relationship to SSTP

LSTP uses the same L9 envelope header structure as SSTP.  The `protocol` field is set to `"LSTP"` and the payload carries a tensor or embedding rather than a JSON dict.

Sub-protocols for LSTP are defined by subclassing `L9HeaderBuilder` with `PROTOCOL = L9Transport.LSTP`.

## Status

No sub-protocols or payload schemas are defined for LSTP at this time.  This directory is reserved for future specification work.

## See also

- [SSTP Formal Model](../../SSTP/spec/SSTP_FORMAL_MODEL.md) — base envelope structure shared by all transports
- `l9_base.py` — `L9Transport.LSTP` constant
