# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/transport — A2A transport adapter for L9 messages.

L9 rides inside A2A as a DataPart. A2A is the transport; L9 is the semantic
payload. This layer is transparent to all protocol layers above it.
"""

from sstp.transport.a2a_adapter import A2ATransportAdapter

__all__ = ["A2ATransportAdapter"]
