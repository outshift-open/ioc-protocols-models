#!/usr/bin/env python3
"""
Semantic Interaction Exchange Protocol demo — entry point.

Run:
    python scripts/interaction_engine.py

Delegates to siep_demo.run_demo(), which implements the full IE episode using:
  ioc_l9/siep_builder.py  — fluent L9 message builder
  ioc_l9/siep_engine.py   — SIEPEngine (grounding check + repair cycle)
  scripts/siep_demo.py    — declarative episode + verbose + summary display
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from siep_demo import run_demo

if __name__ == "__main__":
    run_demo()
