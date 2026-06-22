#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
compile_spec.py — compile a .ioc DSL spec to a Python base class.

Usage:
  python scripts/compile_spec.py SSTP/spec/siep.ioc
  python scripts/compile_spec.py SSTP/spec/siep.ioc --out SSTP/subprotocol/siep/language_bindings/python/siep_base.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from SSTP.compiler import parse_ioc_file, generate_python

_DEFAULT_OUT = {
    "siep": "SSTP/subprotocol/siep/language_bindings/python/siep_base.py",
    "cip":  "SSTP/subprotocol/cip/language_bindings/python/cip_base.py",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a .ioc spec to Python.")
    parser.add_argument("spec", help="Path to .ioc spec file")
    parser.add_argument("--out", help="Output file path (default: derived from spec name)")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"Error: {spec_path} not found", file=sys.stderr)
        sys.exit(1)

    proto = parse_ioc_file(spec_path)
    code  = generate_python(proto)

    out_path = Path(
        args.out or _DEFAULT_OUT.get(proto.name.lower(), f"{proto.name.lower()}_base.py")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(code, encoding="utf-8")
    print(f"✓ {proto.name} v{proto.version}  →  {out_path}")


if __name__ == "__main__":
    main()
