# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Re-export TheoryOfMindEngineBase from CIP for SIEP tomcore compatibility."""

from SSTP.subprotocol.cip.src.tom import TheoryOfMindEngineBase

__all__ = ["TheoryOfMindEngineBase"]
