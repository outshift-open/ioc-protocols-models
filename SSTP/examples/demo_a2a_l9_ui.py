# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
demo_a2a_l9_ui.py — Browser UI for demo_a2a_l9.py

Usage:
    python3 SSTP/examples/demo_a2a_l9_ui.py
    # Then open http://localhost:8765

Features:
  - Run the demo from the browser
  - Live console output streamed via SSE
  - Messages displayed as color-coded cards by L9 kind & subprotocol
  - Agent roster with skills
  - Expandable L9 payload details
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

_HERE    = Path(__file__).resolve().parent
_REPO    = _HERE.parents[1]
_MSG_JSON = _HERE / "demo_a2a_l9_messages.json"

PORT = 8765

# ─────────────────────────────────────────────────────────────────────────────
# Demo runner (subprocess, non-blocking)
# ─────────────────────────────────────────────────────────────────────────────

_run_lock   = threading.Lock()
_demo_queue: queue.Queue[str | None] = queue.Queue()   # None = sentinel (done)
_demo_running = False


def _stream_demo() -> None:
    global _demo_running
    script = _HERE / "demo_a2a_l9.py"
    env    = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(_REPO)}
    try:
        proc = subprocess.Popen(
            ["poetry", "run", "python", str(script)],
            cwd=str(_REPO),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        for line in iter(proc.stdout.readline, ""):
            _demo_queue.put(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            _demo_queue.put(f"[exit code {proc.returncode}]")
    except Exception as exc:
        _demo_queue.put(f"[ERROR] {exc}")
    finally:
        _demo_queue.put(None)
        _demo_running = False


# ─────────────────────────────────────────────────────────────────────────────
# HTML template
# ─────────────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>demo_a2a_l9 · L9 Sequence Diagram</title>
<style>
  :root {
    --bg: #f0f2fa; --panel: #ffffff; --border: #dde1f0;
    --text: #1e2240; --muted: #6b73a0; --accent: #4f46e5;
    /* kinds */
    --intent:      #1d4ed8; --intent-bg:      #dbeafe;
    --exchange:    #6d28d9; --exchange-bg:    #ede9fe;
    --commit:      #065f46; --commit-bg:      #d1fae5;
    --contingency: #92400e; --contingency-bg: #fef3c7;
    /* subprotocols */
    --tfp:  #0f766e; --tfp-bg:  #ccfbf1;
    --siep: #3730a3; --siep-bg: #e0e7ff;
    --cip:  #c2410c; --cip-bg:  #ffedd5;
    --sab:  #5b21b6; --sab-bg:  #f3e8ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { font-size: 18px; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; height: 100vh; overflow: hidden; font-size: 1rem; }

  /* ── Top header ── */
  header { background: var(--panel); border-bottom: 2px solid var(--border);
    padding: .7rem 1.5rem; display: flex; align-items: center; gap: 1rem; height: 62px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06); }
  header h1 { font-size: 1.6rem; font-weight: 700; color: var(--accent); }
  header .subtitle { color: var(--muted); font-size: 1.05rem; }

  /* ── Scenario banner ── */
  .scenario-banner {
    background: #f8f9ff; border-bottom: 2px solid var(--border);
    padding: .65rem 1.5rem; font-size: .92rem; display: flex; gap: 1.2rem;
    align-items: stretch; }
  .scenario-banner-col { display: flex; flex-direction: column; gap: .3rem; }
  .scenario-banner-col .sb-label {
    font-size: .72rem; text-transform: uppercase; letter-spacing: .1em;
    color: var(--muted); font-weight: 700; }
  .scenario-banner-col .sb-value { color: var(--text); font-size: .88rem; line-height: 1.45; }
  .sb-divider { width: 1px; background: var(--border); flex-shrink: 0; align-self: stretch; margin: .1rem 0; }
  .sb-contract { flex: 2; min-width: 260px; }
  .sb-contract .sb-title { font-size: 1rem; font-weight: 700; color: var(--accent); margin-bottom: .2rem; }
  .sb-contract .sb-desc  { font-size: .86rem; color: var(--text); line-height: 1.5; }
  .sb-contract .sb-objective { font-size: .83rem; color: var(--muted); margin-top: .25rem;
    border-left: 3px solid var(--accent); padding-left: .5rem; line-height: 1.4; }
  .sb-agent { flex: 1; min-width: 180px; }
  .sb-agent-name { font-weight: 700; font-size: .92rem; margin-bottom: .15rem; }
  .sb-agent-skills { font-size: .83rem; color: var(--muted); line-height: 1.45; }
  .sb-agent-role  { font-size: .8rem; display: inline-block; margin-top: .2rem;
    background: var(--bg); border: 1px solid var(--border); border-radius: .3rem;
    padding: .1rem .4rem; color: var(--text); }

  /* ── Root layout ── */
  .root { display: flex; height: calc(100vh - 62px - 72px); }

  /* ── Sidebar ── */
  aside { width: 280px; flex-shrink: 0; background: var(--panel); border-right: 1px solid var(--border);
    overflow-y: auto; display: flex; flex-direction: column; }
  .sidebar-section { padding: .75rem 1rem; border-bottom: 1px solid var(--border); }
  .sidebar-section h2 { font-size: .95rem; text-transform: uppercase; letter-spacing: .1em;
    color: var(--muted); margin-bottom: .6rem; }

  #run-btn { width: 100%; padding: .55rem 1rem; border-radius: .5rem; border: none;
    background: var(--accent); color: #fff; font-weight: 600; cursor: pointer;
    font-size: 1rem; transition: opacity .2s; }
  #run-btn:disabled { opacity: .4; cursor: not-allowed; }
  #run-btn:not(:disabled):hover { opacity: .85; }

  #status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--muted); margin-right: .4rem; }
  #status-dot.running { background: #16a34a; box-shadow: 0 0 6px #16a34a; animation: pulse 1s infinite; }
  #status-dot.done    { background: #16a34a; }
  #status-dot.error   { background: #dc2626; }
  #status-label { font-size: 1rem; color: var(--muted); }

  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  .badge { display: inline-flex; align-items: center; padding: .22rem .5rem; border-radius: .3rem;
    font-size: .9rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
  .legend-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .35rem; }

  #console { background: #1e2235; border-radius: .375rem; padding: .4rem;
    font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: .88rem; color: #a8b4d0;
    max-height: 180px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; border: 1px solid #c8cde0; }
  #console .ln { line-height: 1.5; }
  #console .ln.llm  { color: #67e8f9; }
  #console .ln.err  { color: #fca5a5; }
  #console .ln.step { color: #fde68a; font-weight: 600; }
  #console .ln.hr   { color: #364060; }

  /* ── Sequence diagram main area ── */
  .seq-main { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

  /* Stats bar */
  #stats-bar { display: flex; gap: .6rem; padding: .6rem 1rem; background: var(--panel);
    border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap;
    box-shadow: 0 1px 3px rgba(0,0,0,.04); }
  .stat { background: var(--bg); border: 1px solid var(--border); border-radius: .4rem;
    padding: .3rem .7rem; text-align: center; }
  .stat .n { font-size: 1.6rem; font-weight: 700; color: var(--accent); }
  .stat .l { font-size: .9rem; color: var(--muted); text-transform: uppercase; }

  /* Sequence diagram container */
  .seq-wrap { flex: 1; overflow-y: auto; overflow-x: auto; position: relative; background: var(--bg); }

  /* Agent header row */
  .seq-head { display: flex; position: sticky; top: 0; z-index: 20; background: var(--panel);
    border-bottom: 2px solid var(--border); box-shadow: 0 2px 6px rgba(0,0,0,.06); }
  .seq-head-gutter { width: 240px; flex-shrink: 0; padding: .85rem .85rem;
    font-size: 1rem; color: var(--muted); border-right: 1px solid var(--border);
    font-weight: 600; }
  .agent-hdr { flex: 1; min-width: 200px; text-align: center; padding: .85rem .25rem;
    border-right: 1px solid var(--border); }
  .agent-hdr-name { font-weight: 700; font-size: 1.2rem; color: var(--accent); }
  .agent-hdr-icon { font-size: 2.2rem; display: block; margin-bottom: .3rem; }

  /* Phase separator */
  .phase-sep { display: flex; align-items: center;
    background: var(--panel); border-top: 2px solid var(--border);
    border-bottom: 1px solid var(--border); }
  .phase-sep-gutter { width: 240px; flex-shrink: 0; padding: .6rem .85rem;
    border-right: 1px solid var(--border); }
  .phase-sep-line { flex: 1; height: 2px; opacity: .25; }

  /* ── Message row ── */
  .seq-row { display: flex; align-items: stretch; min-height: 80px;
    border-bottom: 1px solid var(--border);
    cursor: pointer; transition: background .1s; position: relative; background: #fff; }
  .seq-row:nth-child(even) { background: #fafbff; }
  .seq-row:hover  { background: #eef0fd !important; }

  /* left gutter */
  .seq-gutter { width: 240px; flex-shrink: 0; padding: .6rem .85rem;
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column; gap: .3rem; justify-content: center; }
  .seq-num { font-size: 1rem; color: var(--muted); font-family: monospace; font-weight: 600; }
  .seq-step-label { font-size: 1.05rem; color: var(--text); line-height: 1.4; font-weight: 500; }
  .seq-badges { display: flex; flex-wrap: wrap; gap: .25rem; margin-top: .3rem; }

  /* agent columns (lifelines) */
  .seq-cols { flex: 1; display: flex; position: relative; min-width: 0; }
  .seq-col { flex: 1; min-width: 200px; border-right: 1px solid #e8eaf5; position: relative;
    display: flex; align-items: center; justify-content: center; }
  .seq-col::before { content: ''; position: absolute; top: 0; bottom: 0; left: 50%;
    width: 2px; background: #c8cde8; transform: translateX(-50%); z-index: 0; }
  .seq-col.is-sender::before   { background: var(--accent); width: 3px; opacity: .5; }
  .seq-col.is-receiver::before { background: var(--accent); width: 3px; opacity: .5; }

  /* ── Arrow ── */
  .seq-arrow-wrap { position: absolute; top: 0; bottom: 0; display: flex; align-items: center;
    pointer-events: none; z-index: 5; }
  .seq-arrow-inner { position: relative; display: flex; flex-direction: column;
    align-items: center; justify-content: center; width: 100%; }
  .arrow-label-row { display: flex; align-items: center; gap: .3rem; margin-bottom: .25rem; }
  .arrow-kind { font-size: 1.1rem; font-weight: 700; letter-spacing: .02em; }
  .arrow-sub  { font-size: .95rem; color: var(--muted); }
  .arrow-line-row { display: flex; align-items: center; width: 100%; }
  .arrow-line { height: 2px; flex: 1; }
  .arrow-head { width: 0; height: 0; border-top: 6px solid transparent;
    border-bottom: 6px solid transparent; flex-shrink: 0; }
  .arrow-head.right { border-left: 10px solid currentColor; }
  .arrow-head.left  { border-right: 10px solid currentColor; }

  /* ── Resize handle ── */
  .resize-handle { width: 5px; flex-shrink: 0; cursor: col-resize; background: var(--border);
    transition: background .15s; position: relative; }
  .resize-handle:hover, .resize-handle.dragging { background: var(--accent); }
  .resize-handle::after { content: '⋮'; position: absolute; top: 50%; left: 50%;
    transform: translate(-50%,-50%); color: var(--muted); font-size: 1rem;
    pointer-events: none; }

  /* ── Right detail panel ── */
  .detail-panel { width: 560px; flex-shrink: 0; background: var(--panel);
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: -2px 0 8px rgba(0,0,0,.06); }
  .detail-panel-header { padding: .85rem 1rem; border-bottom: 1px solid var(--border);
    flex-shrink: 0; background: #fafbff; }
  .detail-panel-header .dp-step { font-size: .92rem; color: var(--muted); margin-bottom: .35rem;
    font-family: monospace; }
  .detail-panel-header .dp-kind { font-size: 1.3rem; font-weight: 700; display: flex; align-items: center; gap: .5rem; }
  .detail-panel-header .dp-agents { margin-top: .5rem; display: flex; align-items: center;
    gap: .4rem; flex-wrap: wrap; font-size: 1rem; }
  .detail-panel-body { flex: 1; overflow-y: auto; padding: .75rem; display: flex; flex-direction: column; gap: .6rem; }
  .dp-empty { color: var(--muted); font-size: 1.05rem; text-align: center; padding: 3rem 1rem; }
  .dp-section { background: #fff; border: 1px solid var(--border); border-radius: .5rem;
    overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
  .dp-section-title { font-size: .9rem; text-transform: uppercase; letter-spacing: .1em;
    color: var(--muted); padding: .4rem .7rem; border-bottom: 1px solid var(--border);
    background: #f5f6ff; font-weight: 700; }
  .dp-field { display: flex; border-bottom: 1px solid #eef0f8; }
  .dp-field:last-child { border-bottom: none; }
  .dp-field .dk { color: var(--muted); padding: .35rem .6rem; min-width: 130px; flex-shrink: 0;
    border-right: 1px solid #eef0f8; background: #fafbff; font-size: .95rem; font-weight: 500; }
  .dp-field .dv { color: var(--text); padding: .35rem .6rem; font-family: 'Cascadia Code', monospace;
    word-break: break-all; font-size: .95rem; flex: 1; line-height: 1.5; }
  .dp-raw-pre { background: #1e2235; padding: .6rem; font-family: 'Cascadia Code', monospace;
    font-size: .88rem; color: #a8b4d0; overflow: auto; max-height: 280px; }
  details summary { cursor: pointer; color: var(--muted); font-size: .95rem;
    padding: .4rem .7rem; user-select: none; }
  details[open] summary { border-bottom: 1px solid var(--border); }
  .agent-chip { display: inline-flex; align-items: center; gap: .3rem; background: var(--bg);
    border: 1px solid var(--border); border-radius: 9999px; padding: .2rem .6rem; font-size: .95rem; }

  .empty { text-align: center; color: var(--muted); padding: 5rem 2rem; }
  .empty .icon { font-size: 3rem; margin-bottom: .5rem; }

  /* ── Routing hints (broadcast / self-send) ── */
  .routing-hint { margin-top: .3rem; font-size: .82rem; font-weight: 600;
    padding: .15rem .4rem; border-radius: .3rem; display: inline-flex; align-items: center; gap: .3rem; }
  .broadcast-hint { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
  .self-hint      { background: #e0e7ff; color: #3730a3; border: 1px solid #c7d2fe; }
  .self-arrow-box { border: 2.5px dashed; border-radius: 8px; padding: .3rem .7rem;
    font-size: .95rem; white-space: nowrap; background: rgba(255,255,255,.7);
    display: inline-flex; align-items: center; gap: .4rem; margin-top: .2rem; }

  /* ── Playback ── */
  .seq-row   { transition: opacity .35s ease, transform .35s ease; }
  .phase-sep { transition: opacity .35s ease; }
  .seq-row.pb-hidden, .phase-sep.pb-hidden { opacity: 0; pointer-events: none; transform: translateY(6px); }
  .seq-row.active { box-shadow: inset 3px 0 0 var(--accent); background: #e8eaff !important; outline: 2px solid var(--accent); outline-offset: -2px; }

  .pb-btn { padding: .4rem .75rem; border-radius: .4rem; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: .9rem; cursor: pointer; font-weight: 600;
    transition: background .15s; }
  .pb-btn:hover:not(:disabled) { background: var(--accent); color: #fff; border-color: var(--accent); }
  .pb-btn:disabled { opacity: .35; cursor: not-allowed; }
  .pb-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  #pb-speed { padding: .35rem .5rem; border-radius: .4rem; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: .9rem; cursor: pointer; width: 100%; margin-top: .4rem; }
  #pb-progress { height: 4px; background: var(--border); border-radius: 2px; margin-top: .5rem; overflow: hidden; }
  #pb-progress-bar { height: 100%; background: var(--accent); border-radius: 2px; transition: width .3s; }

  /* ── Right panel: A2A → L9 nesting ── */
  .a2a-outer { border: 2px solid #334 !important; }
  .a2a-outer > .dp-section-title {
    background: #1e2235; color: #a8b4d0; display: flex; align-items: center; gap: .5rem; }
  .a2a-outer > .dp-section-title .a2a-subtitle {
    font-weight: 400; opacity: .65; text-transform: none; letter-spacing: 0; font-size: .82rem; }

  .l9-envelope {
    margin: .5rem; border: 2px solid var(--accent);
    border-radius: .45rem; background: #f0f1ff; overflow: hidden; }
  .l9-envelope-label {
    background: var(--accent); color: #fff; padding: .28rem .7rem;
    font-size: .83rem; font-weight: 700; display: flex; align-items: center; gap: .4rem; }
  .l9-envelope-label code {
    background: rgba(255,255,255,.22); border-radius: .25rem;
    padding: .05rem .3rem; font-size: .8rem; font-weight: 400; }
  .l9-envelope-body { padding: .4rem; display: flex; flex-direction: column; gap: .4rem; }

  .l9-inner { border: 1px solid #c7d2fe !important; background: #fff !important;
    box-shadow: none !important; border-radius: .4rem !important; }
  .l9-inner > .dp-section-title { background: #e8ecff; color: var(--accent);
    border-bottom-color: #c7d2fe; }

  .participants-nested { margin: .3rem .4rem .4rem; border: 1px solid #dde1f0;
    border-radius: .35rem; overflow: hidden; background: #fafbff; }
  .participants-nested > .dp-section-title { background: #f2f4ff; color: var(--muted);
    font-size: .82rem; padding: .3rem .6rem; border-bottom: 1px solid #dde1f0; }

  /* ── Drift row highlight ── */
  .seq-row--drift { background: #fff7ed !important; }
  .seq-row--drift:hover { background: #fed7aa !important; }
  .seq-row--drift .seq-gutter { border-left: 4px solid #f97316; }
  .drift-badge { background: #fff7ed; border: 1.5px solid #f97316; color: #c2410c;
    border-radius: .3rem; padding: .15rem .45rem; font-size: .82rem; font-weight: 700;
    display: inline-flex; align-items: center; gap: .25rem; margin-top: .3rem; }
  .drift-detail-box { background: #fff7ed; border: 1.5px solid #f97316; border-radius: .4rem;
    padding: .45rem .7rem; font-size: .88rem; color: #7c2d12; line-height: 1.55;
    margin-bottom: .1rem; }
  .drift-detail-box strong { color: #c2410c; }

  /* ── CIP Journey timeline ── */
  .cip-journey { background: #fff; border: 2px solid var(--cip); border-radius: .5rem;
    overflow: hidden; }
  .cip-journey-title { background: var(--cip-bg); color: var(--cip); padding: .4rem .7rem;
    font-size: .88rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em;
    border-bottom: 1px solid #fed7aa; }
  .cip-journey-steps { display: flex; flex-direction: column; }
  .cip-step { display: flex; align-items: flex-start; gap: .5rem; padding: .4rem .7rem;
    border-bottom: 1px solid #fef3c7; font-size: .87rem; }
  .cip-step:last-child { border-bottom: none; }
  .cip-step-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
    margin-top: .25rem; background: #d1d5db; border: 2px solid #9ca3af; }
  .cip-step.current .cip-step-dot { background: var(--cip); border-color: var(--cip);
    box-shadow: 0 0 6px var(--cip); }
  .cip-step.done .cip-step-dot { background: #16a34a; border-color: #16a34a; }
  .cip-step-body { flex: 1; }
  .cip-step-label { font-weight: 600; color: var(--text); }
  .cip-step.current .cip-step-label { color: var(--cip); }
  .cip-step.done   .cip-step-label { color: #15803d; }
  .cip-step-detail { color: var(--muted); font-size: .82rem; margin-top: .15rem; line-height: 1.4; }
  .cip-step-connector { width: 2px; height: 10px; background: #e5e7eb; margin-left: .75rem; }

  /* ── SAB bargaining boxes ── */
  .sab-open-box { background: #fdf4ff; border: 2px solid var(--sab); border-radius: .5rem;
    overflow: hidden; margin-bottom: .1rem; }
  .sab-open-box-title { background: var(--sab-bg); color: var(--sab); padding: .4rem .7rem;
    font-size: .88rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em;
    border-bottom: 1px solid #e9d5ff; }
  .sab-issue-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  .sab-issue-table th { background: #f3e8ff; color: var(--sab); padding: .3rem .6rem;
    text-align: left; font-weight: 700; border-bottom: 1px solid #e9d5ff; }
  .sab-issue-table td { padding: .3rem .6rem; border-bottom: 1px solid #f3e8ff; vertical-align: top; }
  .sab-issue-table tr:last-child td { border-bottom: none; }
  .sab-option { display: inline-block; margin: .1rem .15rem; padding: .1rem .4rem;
    border-radius: .25rem; border: 1px solid #d8b4fe; background: #fff; font-size: .82rem; }
  .sab-option.pos-commercial { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; font-weight: 700; }
  .sab-option.pos-liability  { background: #fce7f3; border-color: #f9a8d4; color: #9d174d; font-weight: 700; }
  .sab-option.pos-agreed     { background: #d1fae5; border-color: #6ee7b7; color: #065f46; font-weight: 700; }
  .sab-positions { display: flex; gap: .5rem; padding: .5rem .7rem; flex-wrap: wrap; }
  .sab-position-card { flex: 1; min-width: 130px; border-radius: .4rem; padding: .4rem .6rem;
    font-size: .85rem; line-height: 1.5; }
  .sab-position-card.commercial { background: #eff6ff; border: 1px solid #93c5fd; }
  .sab-position-card.liability  { background: #fdf2f8; border: 1px solid #f9a8d4; }
  .sab-position-card .sp-agent  { font-weight: 700; font-size: .8rem; text-transform: uppercase;
    letter-spacing: .06em; margin-bottom: .2rem; }
  .sab-distance { padding: .35rem .7rem; background: #fff7ed; border-top: 1px solid #fed7aa;
    font-size: .83rem; color: #92400e; }

  .sab-resolved-box { background: #f0fdf4; border: 2px solid #16a34a; border-radius: .5rem;
    overflow: hidden; margin-bottom: .1rem; }
  .sab-resolved-title { background: #d1fae5; color: #065f46; padding: .4rem .7rem;
    font-size: .88rem; font-weight: 700; border-bottom: 1px solid #a7f3d0; }
  .sab-agreed-terms { display: flex; gap: .6rem; padding: .5rem .7rem; flex-wrap: wrap; }
  .sab-term { background: #fff; border: 2px solid #6ee7b7; border-radius: .4rem;
    padding: .4rem .7rem; flex: 1; min-width: 120px; }
  .sab-term .st-label { font-size: .75rem; text-transform: uppercase; letter-spacing: .08em;
    color: #16a34a; font-weight: 700; margin-bottom: .2rem; }
  .sab-term .st-value { font-size: 1rem; font-weight: 700; color: #065f46; }
  .sab-rounds { padding: .4rem .7rem; border-top: 1px solid #a7f3d0; font-size: .85rem; }
  .sab-rounds-title { font-weight: 700; color: #065f46; margin-bottom: .3rem; font-size: .82rem;
    text-transform: uppercase; letter-spacing: .06em; }
  .sab-round-row { display: flex; align-items: center; gap: .4rem; margin-bottom: .2rem; }
  .sab-round-agent { font-size: .78rem; color: var(--muted); min-width: 130px; }
  .sab-round-offer { display: flex; gap: .25rem; }
</style>
</head>
<body>

<header>
  <div>
    <h1>⚡ demo_a2a_l9 · Sequence Diagram</h1>
    <div class="subtitle">TFP → SIEP → CIP → SAB · A2A transport · L9 messages between agents
      <span style="font-size:.85rem;color:var(--muted);margin-left:.5rem">TFP = Team Formation Protocol · SIEP = Semantic Interaction Exchange Protocol · CIP = Contingency Interaction Protocols · SAB = Semantic Alignment via Bargaining</span>
    </div>
  </div>
</header>

<!-- ── Scenario context banner ── -->
<div class="scenario-banner">

  <!-- Contract problem statement -->
  <div class="scenario-banner-col sb-contract">
    <span class="sb-label">📄 Problem statement</span>
    <div class="sb-title">Cross-jurisdiction SaaS Enterprise Agreement</div>
    <div class="sb-desc">
      Two AI agents must jointly interpret and resolve an unresolved consequential damages clause
      in a SaaS contract that spans multiple legal jurisdictions. Neither agent alone holds the
      full picture — commercial law expertise must be combined with indemnity &amp; damages analysis.
    </div>
    <div class="sb-objective">
      Objective: align on a shared legal standard for material breach, then negotiate and agree on
      <strong>governing interpretation</strong> (US / UK / Hybrid) and <strong>damages cap</strong>
      (6 / 12 / 24 months of fees).
    </div>
  </div>

  <div class="sb-divider"></div>

  <!-- Commercial-agent -->
  <div class="scenario-banner-col sb-agent">
    <span class="sb-label">⚖️ Agent 1</span>
    <div class="sb-agent-name" style="color:var(--intent)">commercial-agent</div>
    <div class="sb-agent-skills">
      Contract law &amp; material breach standards<br>
      GDPR / CCPA data-processing compliance<br>
      Cross-jurisdiction SaaS agreements
    </div>
    <span class="sb-agent-role">Lead · team coordinator</span>
  </div>

  <div class="sb-divider"></div>

  <!-- Liability-agent -->
  <div class="scenario-banner-col sb-agent">
    <span class="sb-label">🛡️ Agent 2</span>
    <div class="sb-agent-name" style="color:var(--exchange)">liability-agent</div>
    <div class="sb-agent-skills">
      Indemnity &amp; consequential damages scope<br>
      SLA breach threshold analysis<br>
      Cross-jurisdiction indemnity frameworks
    </div>
    <span class="sb-agent-role">Participant · damages specialist</span>
  </div>

  <div class="sb-divider"></div>

  <!-- Repair Cognition Engine -->
  <div class="scenario-banner-col sb-agent">
    <span class="sb-label">🔧 Agent 3</span>
    <div class="sb-agent-name" style="color:var(--cip)">repair-cognition-engine</div>
    <div class="sb-agent-skills">
      Detects semantic drift between agents<br>
      Issues hard-stop repair directives<br>
      Verifies re-alignment before proceeding
    </div>
    <span class="sb-agent-role">CIP · contingency repair</span>
  </div>

</div>

<div class="root">

<!-- ── Sidebar ── -->
<aside>
  <div class="sidebar-section">
    <h2>Demo control</h2>
    <button id="run-btn" onclick="runDemo()">▶ Run Demo</button>
    <div style="margin-top:.5rem">
      <span id="status-dot"></span>
      <span id="status-label">Idle — click Run to start</span>
    </div>
  </div>

  <div class="sidebar-section">
    <h2>Live console</h2>
    <div id="console"><span class="ln" style="color:var(--muted)">Output will appear here…</span></div>
  </div>

  <div class="sidebar-section" id="playback-section" style="display:none">
    <h2>▶ Playback</h2>
    <div style="display:flex;gap:.35rem;flex-wrap:wrap">
      <button class="pb-btn" id="pb-prev"  onclick="pbPrev()"   title="Previous" disabled>◀</button>
      <button class="pb-btn" id="pb-play"  onclick="pbToggle()" title="Play / Pause">▶ Play</button>
      <button class="pb-btn" id="pb-next"  onclick="pbNext()"   title="Next" disabled>▶</button>
      <button class="pb-btn" id="pb-reset" onclick="pbReset()"  title="Reset to start">↺</button>
    </div>
    <select id="pb-speed" onchange="pbSpeed=+this.value">
      <option value="2000">🐢 Slow (2 s)</option>
      <option value="900" selected>🚶 Medium (0.9 s)</option>
      <option value="350">🏃 Fast (0.35 s)</option>
      <option value="100">⚡ Turbo (0.1 s)</option>
    </select>
    <div id="pb-status" style="margin-top:.4rem;font-size:.88rem;color:var(--muted)">0 / 0</div>
    <div id="pb-progress"><div id="pb-progress-bar" style="width:0%"></div></div>
  </div>

   <div class="sidebar-section">
    <h2>Kind colours</h2>
    <div class="legend-grid">
      <span class="badge" style="background:var(--intent-bg);color:var(--intent)">intent</span>
      <span class="badge" style="background:var(--exchange-bg);color:var(--exchange)">exchange</span>
      <span class="badge" style="background:var(--commit-bg);color:var(--commit)">commit</span>
      <span class="badge" style="background:var(--contingency-bg);color:var(--contingency)">contingency</span>
    </div>
  </div>

  <div class="sidebar-section">
    <h2>Subprotocol colours</h2>
    <div class="legend-grid">
      <span class="badge" style="background:var(--tfp-bg);color:var(--tfp)" title="Team Formation Protocol">TFP</span>
      <span class="badge" style="background:var(--siep-bg);color:var(--siep)" title="Semantic Interaction Exchange Protocol">SIEP</span>
      <span class="badge" style="background:var(--cip-bg);color:var(--cip)" title="Contingency Interaction Protocols">CIP</span>
      <span class="badge" style="background:var(--sab-bg);color:var(--sab)" title="Semantic Alignment via Bargaining">SAB</span>
    </div>
  </div>
</aside>

<!-- ── Sequence diagram ── -->
<div class="seq-main">
  <div id="stats-bar"></div>

  <div class="seq-wrap" id="seq-wrap">
    <!-- agent header row -->
    <div class="seq-head" id="seq-head">
      <div class="seq-head-gutter">Step / Label</div>
    </div>
    <!-- message rows -->
    <div id="seq-body">
      <div class="empty"><div class="icon">🔭</div><div>Run the demo to see the sequence diagram</div></div>
    </div>
  </div>
</div>

<!-- ── Detail side panel ── -->
<div class="resize-handle" id="resize-handle"></div>
<div class="detail-panel" id="detail-panel">
  <div class="detail-panel-header" id="dp-header">
    <div class="dp-empty">Hover over a message to inspect its L9 envelope</div>
  </div>
  <div class="detail-panel-body" id="dp-body"></div>
</div>

</div><!-- .root -->

<script>
// ── colour helpers ────────────────────────────────────────────────────────────
const KIND_COLOR = {
  intent:      'var(--intent)',
  exchange:    'var(--exchange)',
  commit:      'var(--commit)',
  contingency: 'var(--contingency)',
};
const KIND_BG = {
  intent:      'var(--intent-bg)',
  exchange:    'var(--exchange-bg)',
  commit:      'var(--commit-bg)',
  contingency: 'var(--contingency-bg)',
};
const SUB_COLOR = { TFP:'var(--tfp)', SIEP:'var(--siep)', CIP:'var(--cip)', SAB:'var(--sab)' };
const SUB_BG    = { TFP:'var(--tfp-bg)', SIEP:'var(--siep-bg)', CIP:'var(--cip-bg)', SAB:'var(--sab-bg)' };
const PHASE_COLOR = { TFP:'var(--tfp)', SIEP:'var(--siep)', CIP:'var(--cip)', SAB:'var(--sab)' };

const AGENT_ICON = {
  'commercial-agent': '⚖️',
  'liability-agent':  '🛡️',
  'repair-cognition-engine': '🔧',
};
function agentIcon(id) { return AGENT_ICON[id] || '🤖'; }

function badge(text, bg, fg) {
  return `<span class="badge" style="background:${bg};color:${fg}">${text}</span>`;
}
function kindBadge(k) { return badge(k, KIND_BG[k]||'var(--border)', KIND_COLOR[k]||'var(--muted)'); }
function subBadge(s)  { return badge(s, SUB_BG[s]||'var(--border)',  SUB_COLOR[s]||'var(--muted)'); }

// ── Console ───────────────────────────────────────────────────────────────────
const consoleEl = document.getElementById('console');
const statusDot = document.getElementById('status-dot');
const statusLbl = document.getElementById('status-label');
const runBtn    = document.getElementById('run-btn');

function appendConsole(line) {
  let cls = 'ln';
  if (line.includes('[LLM]'))      cls += ' llm';
  else if (line.includes('ERROR') || line.includes('exit code')) cls += ' err';
  else if (line.includes('STEP ')) cls += ' step';
  else if (/^[═─]+$/.test(line.trim())) cls += ' hr';
  const d = document.createElement('div');
  d.className = cls; d.textContent = line;
  consoleEl.appendChild(d);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ── Run demo (SSE) ────────────────────────────────────────────────────────────
function runDemo() {
  runBtn.disabled = true;
  statusDot.className = 'running';
  statusLbl.textContent = 'Running demo…';
  consoleEl.innerHTML = '';
  const es = new EventSource('/run');
  es.addEventListener('line', e => appendConsole(e.data));
  es.addEventListener('done', () => {
    es.close();
    statusDot.className = 'done';
    statusLbl.textContent = 'Completed ✓';
    runBtn.disabled = false;
    loadMessages(true);   // auto-play after demo run
  });
  es.addEventListener('error', e => {
    if (e.data) appendConsole('[ERROR] ' + e.data);
    statusDot.className = 'error';
    statusLbl.textContent = 'Error — check console';
    runBtn.disabled = false;
    es.close();
  });
}

// ── Extract L9/SAB (Semantic Alignment via Bargaining) info from a message entry ───
function extractL9Info(entry) {
  const parts = entry.a2a_message?.parts || [];
  for (const p of parts) {
    if (p.type !== 'data' || !p.decoded_l9_or_sab) continue;
    const d = p.decoded_l9_or_sab;
    const h = d.header;
    if (!h) continue;
    const actors  = h.participants?.actors || [];
    const sender  = actors.find(a => a.role === 'sender')?.id || '—';
    const recvrs  = actors.filter(a => a.role !== 'sender').map(a => a.id);
    return {
      subprotocol: h.subprotocol || entry.phase,
      kind:    h.kind    || '—',
      subkind: h.subkind || null,
      sender,
      receivers: recvrs,
      messageId: h.message?.id  || '',
      episode:   h.message?.episode || '',
      parents:   h.message?.parents || [],
      topic:     h.context?.topic  || '',
      payload:   d.payload || null,
      raw: d,
    };
  }
  return null;
}

// ── Sequence diagram rendering ────────────────────────────────────────────────
const SKIP_AGENTS = /^topic:/;
const AGENT_ORDER = ['commercial-agent', 'liability-agent', 'repair-cognition-engine'];

function collectAgents(msgs) {
  const set = new Set();
  for (const m of msgs) {
    const info = extractL9Info(m);
    if (!info) continue;
    if (!SKIP_AGENTS.test(info.sender)) set.add(info.sender);
    for (const r of info.receivers) if (!SKIP_AGENTS.test(r)) set.add(r);
  }
  const agents = [...set];
  agents.sort((a, b) => {
    const ai = AGENT_ORDER.indexOf(a), bi = AGENT_ORDER.indexOf(b);
    if (ai < 0 && bi < 0) return a.localeCompare(b);
    if (ai < 0) return 1; if (bi < 0) return -1;
    return ai - bi;
  });
  return agents;
}

// ── Side panel ────────────────────────────────────────────────────────────────
let _activeRow = -1;

function dpField(k, v) {
  return `<div class="dp-field"><span class="dk">${k}</span><span class="dv">${String(v).slice(0,300)}</span></div>`;
}
function dpSection(title, fields) {
  if (!fields.length) return '';
  return `<div class="dp-section">
    <div class="dp-section-title">${title}</div>
    ${fields.map(([k,v]) => dpField(k,v)).join('')}
  </div>`;
}

function showDetail(idx, entry, info) {
  // Clear ALL highlighted rows in one sweep — no stale state
  document.querySelectorAll('#seq-body .seq-row.active')
    .forEach(el => el.classList.remove('active'));
  _activeRow = idx;
  document.getElementById('row-'+idx)?.classList.add('active');

  const dpHeader = document.getElementById('dp-header');
  const dpBody   = document.getElementById('dp-body');
  const kind    = info?.kind || '—';
  const sub     = info?.subprotocol || entry.phase;
  const subkind = info?.subkind ? `:${info.subkind}` : '';
  const kColor  = KIND_COLOR[kind]  || 'var(--muted)';
  const kBg     = KIND_BG[kind]     || 'var(--border)';
  const sColor  = SUB_COLOR[sub]    || 'var(--muted)';
  const sBg     = SUB_BG[sub]       || 'var(--border)';

  // ── Header ──
  const sender   = info?.sender    || '—';
  const recvrs   = info?.receivers || [];
  const agentChip = (id, role) =>
    `<span class="agent-chip">${agentIcon(id)} ${id} <span style="color:var(--muted)">${role}</span></span>`;

  dpHeader.innerHTML = `
    <div class="dp-step">#${String(idx+1).padStart(2,'0')} · ${entry.phase}</div>
    <div class="dp-kind">
      <span class="badge" style="background:${kBg};color:${kColor}">${kind}${subkind}</span>
      <span class="badge" style="background:${sBg};color:${sColor}">${sub}</span>
    </div>
    <div class="dp-agents">
      ${agentChip(sender, 'sender')}
      ${recvrs.length ? '<span style="color:var(--muted)">→</span>' : ''}
      ${recvrs.map(r => agentChip(r, 'receiver')).join('')}
    </div>`;

  // ── Body sections ──
  // Structure: A2A (outer) → L9 Envelope (nested) → { L9 Header + Participants, L9 Payload }

  const h = info?.raw?.header || {};
  const a2a = entry.a2a_message || {};

  // ── Drift detection box (msg 10: SIEP exchange with wrong doctrine) ──
  const isDrift = entry.phase === 'SIEP' && entry.label.includes('⚠');
  const driftBox = isDrift ? `
    <div class="drift-detail-box">
      <strong>⚠ Semantic Drift Detected</strong><br>
      liability-agent applied <code>concept:substantial_performance</code> (tort doctrine)
      instead of the agreed <code>concept:material_breach</code> (contract-law standard).<br>
      <span style="margin-top:.3rem;display:block">
        belief.prior = ${info?.raw?.payload?.data?.belief?.prior ?? '?'} ·
        evidence: ${JSON.stringify(info?.raw?.payload?.data?.utterance?.evidence ?? [])}
      </span>
      This mismatch triggers escalation → <strong>CIP repair</strong> (messages #11–#14).
    </div>` : '';

  // ── CIP Journey (messages 11–14: contingency lifecycle) ──
  let cipJourneyHtml = '';
  if (entry.phase === 'CIP') {
    const allMsgs  = window._msgs  || [];
    const allInfos = window._infos || [];
    const cipMsgs  = allMsgs.map((m, i) => ({ m, info: allInfos[i], i }))
                            .filter(x => x.m.phase === 'CIP');

    const stepDefs = [
      { match: x => x.info?.kind === 'contingency' && x.m.label.includes('raises'),
        label: '🚨 Contingency raised',
        detail: m => {
          const d = m.info?.raw?.payload?.data || {};
          return `scope_mismatch detected · challenges: ${JSON.stringify(d.grounding?.challenges || [])}`;
        }},
      { match: x => x.m.label.includes('repair_guidance') || x.m.label.includes('hard-stop'),
        label: '🔧 CIP engine: repair guidance issued',
        detail: m => {
          const t = m.info?.raw?.payload?.data?.utterance?.text || '';
          return t.slice(0, 120) || 'hard-stop instruction sent to liability-agent';
        }},
      { match: x => x.m.label.includes('re-anchor'),
        label: '🔄 liability-agent re-anchors',
        detail: m => {
          const d = m.info?.raw?.payload?.data || {};
          return `belief ${d.belief?.prior} → ${d.belief?.posterior} · ${d.belief?.revision_cause || ''}`;
        }},
      { match: x => x.info?.kind === 'commit' && (x.info?.subkind === 'resolved' || x.m.label.includes('resolved')),
        label: '✅ Alignment restored · commit:resolved',
        detail: m => {
          const d = m.info?.raw?.payload?.data || {};
          return `contingency_score=${d.grounding?.contingency_score} · contingency_verified=${d.grounding?.contingency_verified}`;
        }},
    ];

    const steps = stepDefs.map(def => {
      const found = cipMsgs.find(def.match);
      return { ...def, found };
    });

    const stepsHtml = steps.map(s => {
      const isCurrent = s.found && s.found.i === idx;
      const isDone    = s.found && s.found.i < idx;
      const cls       = isCurrent ? 'current' : isDone ? 'done' : '';
      const detail    = s.found ? s.detail(s.found) : '—';
      return `
        <div class="cip-step ${cls}">
          <div class="cip-step-dot"></div>
          <div class="cip-step-body">
            <div class="cip-step-label">${s.label}${s.found ? ` <span style="color:var(--muted);font-weight:400">#${s.found.i+1}</span>` : ''}</div>
            <div class="cip-step-detail">${detail}</div>
          </div>
        </div>`;
    }).join('<div class="cip-step-connector"></div>');

    cipJourneyHtml = `
      <div class="cip-journey">
        <div class="cip-journey-title">🔁 CIP Repair Journey — triggered by drift in msg #10</div>
        <div class="cip-journey-steps">${stepsHtml}</div>
      </div>`;
  }

  // ── SAB boxes (msg 15: open / misalignment · msg 20: resolved agreement) ──
  let sabHtml = '';
  if (entry.phase === 'SAB') {
    const allMsgs  = window._msgs  || [];
    const allInfos = window._infos || [];

    // Helper: extract current_offer from a SAB message
    const getOffer = m => {
      const parts = m?.a2a_message?.parts || [];
      const l9 = parts.find(p => p.type === 'data')?.decoded_l9_or_sab;
      return l9?.payload?.data?.semantic_context?.sao_state?.current_offer || null;
    };
    const getSender = m => {
      const parts = m?.a2a_message?.parts || [];
      const l9 = parts.find(p => p.type === 'data')?.decoded_l9_or_sab;
      const actors = l9?.header?.participants?.actors || [];
      return actors.find(a => a.role === 'sender')?.id || '?';
    };
    const getFinalAgreement = m => {
      const parts = m?.a2a_message?.parts || [];
      const l9 = parts.find(p => p.type === 'data')?.decoded_l9_or_sab;
      return l9?.payload?.data?.semantic_context?.final_agreement || null;
    };

    // Collect all SAB negotiate rounds (msgs with offers)
    const sabRounds = allMsgs
      .map((m, i) => ({ m, i, offer: getOffer(m), sender: getSender(m) }))
      .filter(x => x.offer && x.m.phase === 'SAB');

    const OPTIONS_MAP = {
      governing_interpretation: { us_standard: 'US Standard', uk_standard: 'UK Standard', hybrid: 'Hybrid' },
      damages_cap: { '6_months_fees': '6 months', '12_months_fees': '12 months', '24_months_fees': '24 months' },
    };

    // ── msg 15: SAB open — show misalignment ──
    if (entry.label.includes('negotiate_open') || (entry.phase === 'SAB' && idx === allMsgs.findIndex(m => m.phase === 'SAB'))) {
      const firstOffer  = sabRounds[0]; // commercial-agent: us_standard / 6_months
      const secondOffer = sabRounds[1]; // liability-agent: uk_standard / 24_months
      const issues = ['governing_interpretation', 'damages_cap'];

      const rowsHtml = issues.map(issue => {
        const opts = ['us_standard','uk_standard','hybrid','6_months_fees','12_months_fees','24_months_fees']
          .filter(o => OPTIONS_MAP[issue]?.[o]);
        const coVal = firstOffer?.offer?.[issue];
        const laVal = secondOffer?.offer?.[issue];
        const optsHtml = opts.map(o => {
          let cls = 'sab-option';
          if (o === coVal) cls += ' pos-commercial';
          else if (o === laVal) cls += ' pos-liability';
          return `<span class="${cls}" title="${o === coVal ? '⚖️ commercial-agent' : o === laVal ? '🛡️ liability-agent' : ''}">${OPTIONS_MAP[issue][o]}</span>`;
        }).join('');
        return `<tr><td style="font-weight:600;color:var(--text)">${issue.replace('_',' ')}</td><td>${optsHtml}</td></tr>`;
      }).join('');

      const posHtml = firstOffer && secondOffer ? `
        <div class="sab-positions">
          <div class="sab-position-card commercial">
            <div class="sp-agent" style="color:#1d4ed8">⚖️ commercial-agent opens</div>
            <div>🗳 ${OPTIONS_MAP.governing_interpretation[firstOffer.offer.governing_interpretation] || firstOffer.offer.governing_interpretation}</div>
            <div>💰 ${OPTIONS_MAP.damages_cap[firstOffer.offer.damages_cap] || firstOffer.offer.damages_cap}</div>
          </div>
          <div style="align-self:center;font-size:1.2rem;color:var(--muted)">⟺</div>
          <div class="sab-position-card liability">
            <div class="sp-agent" style="color:#9d174d">🛡️ liability-agent counters</div>
            <div>🗳 ${OPTIONS_MAP.governing_interpretation[secondOffer.offer.governing_interpretation] || secondOffer.offer.governing_interpretation}</div>
            <div>💰 ${OPTIONS_MAP.damages_cap[secondOffer.offer.damages_cap] || secondOffer.offer.damages_cap}</div>
          </div>
        </div>
        <div class="sab-distance">⚠ Maximum divergence on both issues — bargaining starts from opposite ends of the option space</div>` : '';

      sabHtml = `
        <div class="sab-open-box">
          <div class="sab-open-box-title">🤝 SAB opens — 2 open issues · agents at opposite positions</div>
          <table class="sab-issue-table">
            <tr><th>Issue</th><th>Options <span style="font-weight:400;font-size:.78rem">(🔵 commercial · 🔴 liability)</span></th></tr>
            ${rowsHtml}
          </table>
          ${posHtml}
        </div>`;
    }

    // ── msg 20: commit:converged — show final agreement ──
    const isResolved = info?.kind === 'commit' && (info?.subkind === 'converged' || entry.label.includes('agreed'));
    if (isResolved) {
      const finalAgreement = getFinalAgreement(entry);
      const agreedMap = {};
      (finalAgreement || []).forEach(a => { agreedMap[a.issue_id] = a.chosen_option; });

      const termsHtml = Object.entries(agreedMap).map(([issue, val]) => `
        <div class="sab-term">
          <div class="st-label">${issue.replace('_',' ')}</div>
          <div class="st-value">✅ ${OPTIONS_MAP[issue]?.[val] || val}</div>
        </div>`).join('');

      const roundsHtml = sabRounds.map((r, ri) => {
        const isAgreed = ri === sabRounds.length - 1;
        return `<div class="sab-round-row">
          <span class="sab-round-agent">${r.sender === 'commercial-agent' ? '⚖️' : '🛡️'} ${r.sender} #${r.i+1}</span>
          <div class="sab-round-offer">
            <span class="sab-option${isAgreed ? ' pos-agreed' : r.sender === 'commercial-agent' ? ' pos-commercial' : ' pos-liability'}">${OPTIONS_MAP.governing_interpretation[r.offer.governing_interpretation] || r.offer.governing_interpretation}</span>
            <span class="sab-option${isAgreed ? ' pos-agreed' : r.sender === 'commercial-agent' ? ' pos-commercial' : ' pos-liability'}">${OPTIONS_MAP.damages_cap[r.offer.damages_cap] || r.offer.damages_cap}</span>
          </div>
          ${isAgreed ? '<span style="color:#16a34a;font-weight:700">✅ accepted</span>' : ''}
        </div>`;
      }).join('');

      sabHtml = `
        <div class="sab-resolved-box">
          <div class="sab-resolved-title">✅ SAB commit:converged — damages clause agreed</div>
          <div class="sab-agreed-terms">${termsHtml}</div>
          <div class="sab-rounds">
            <div class="sab-rounds-title">📋 Negotiation history (${sabRounds.length} rounds)</div>
            ${roundsHtml}
          </div>
        </div>`;
    }
  }

  // ── L9 Header fields ──
  const hFields = [
    ['protocol',    h.protocol],
    ['subprotocol', h.subprotocol],
    ['version',     h.version],
    ['kind',        h.kind + (h.subkind ? ':'+h.subkind : '')],
    ['message.id',  (h.message?.id||'').slice(0,12) + '…'],
    ['episode',     (h.message?.episode||'').slice(-40)],
    ['parents',     (h.message?.parents||[]).length
                     ? h.message.parents.map(p=>p.slice(0,8)+'…').join(', ')
                     : '[ ]'],
    ['sensitivity', h.policy?.sensitivity],
    ['propagation', h.policy?.propagation],
    ['topic',       (h.context?.topic||'').slice(0,120)],
  ].filter(([,v]) => v != null && v !== '' && v !== undefined);

  // ── Participants (nested inside L9 Header) ──
  const actors = h.participants?.actors || [];
  const participantsHtml = actors.length ? `
    <div class="participants-nested">
      <div class="dp-section-title">👥 Participants</div>
      ${actors.map(a => dpField(a.role, `${agentIcon(a.id)} ${a.id}`)).join('')}
    </div>` : '';

  const l9HeaderHtml = hFields.length ? `
    <div class="dp-section l9-inner">
      <div class="dp-section-title">🗂 L9 Header</div>
      ${hFields.map(([k,v]) => dpField(k,v)).join('')}
      ${participantsHtml}
    </div>` : '';

  // ── L9 Payload ──
  const d = info?.payload?.data;
  let l9PayloadHtml = '';
  if (d) {
    const pFields = [];
    const pick = (k, lbl) => { const v = d[k]; if (v != null && v !== '') pFields.push([lbl||k, typeof v==='object' ? JSON.stringify(v,null,2) : String(v)]); };
    pick('operation'); pick('poll_id'); pick('reason');
    if (d.task?.description) pFields.push(['task.description', d.task.description]);
    if (d.task?.objective)   pFields.push(['task.objective',   d.task.objective]);
    if (d.selection?.members)           pFields.push(['selected_agents', JSON.stringify(d.selection.members)]);
    if (d.selection?.coverage    !=null) pFields.push(['coverage',       d.selection.coverage]);
    if (d.selection?.aggregate_fit!=null) pFields.push(['aggregate_fit', d.selection.aggregate_fit]);
    if (d.required_skills?.length) pFields.push(['required_skills', d.required_skills.map(s=>s.skill).join(', ')]);
    if (d.utterance?.text)    pFields.push(['utterance.text',     d.utterance.text.slice(0,300)]);
    if (d.utterance?.evidence) pFields.push(['utterance.evidence', JSON.stringify(d.utterance.evidence)]);
    if (d.utterance?.addresses_evidence) pFields.push(['addresses_evidence', JSON.stringify(d.utterance.addresses_evidence)]);
    if (d.belief?.prior    !=null) pFields.push(['belief.prior',    d.belief.prior]);
    if (d.belief?.posterior!=null) pFields.push(['belief.posterior', d.belief.posterior]);
    if (d.belief?.revision_cause) pFields.push(['revision_cause', d.belief.revision_cause]);
    if (d.grounding?.repair_reason) pFields.push(['repair_reason', d.grounding.repair_reason]);
    if (d.grounding?.contingency_score!=null) pFields.push(['contingency_score', d.grounding.contingency_score]);
    if (d.grounding?.challenges?.length) pFields.push(['challenges', JSON.stringify(d.grounding.challenges)]);
    const st = d.semantic_context?.sao_state;
    if (st) {
      pFields.push(['step',     st.step]);
      pFields.push(['proposer', st.current_proposer]);
      if (st.current_offer) pFields.push(['current_offer', JSON.stringify(st.current_offer)]);
      if (st.n_outcomes)    pFields.push(['n_outcomes',    st.n_outcomes]);
    }
    if (d.semantic_context?.outcome) pFields.push(['outcome', d.semantic_context.outcome]);
    if (d.final_agreement)  pFields.push(['final_agreement', JSON.stringify(d.final_agreement)]);
    if (pFields.length) l9PayloadHtml = `
      <div class="dp-section l9-inner">
        <div class="dp-section-title">📋 L9 Payload</div>
        ${pFields.map(([k,v]) => dpField(k,v)).join('')}
      </div>`;
  }

  // ── L9 Envelope (wraps Header + Payload, sits inside A2A) ──
  const mediaType = (a2a.parts||[]).find(p => p.type==='data')?.media_type || 'application/l9+json';
  const l9EnvelopeHtml = (l9HeaderHtml || l9PayloadHtml) ? `
    <div class="l9-envelope">
      <div class="l9-envelope-label">📦 data part · <code>${mediaType}</code> — L9 Envelope</div>
      <div class="l9-envelope-body">
        ${l9HeaderHtml}
        ${l9PayloadHtml}
      </div>
    </div>` : '';

  // ── A2A Message (outermost card) ──
  const a2aMetaFields = [
    ['message_id', a2a.message_id],
    ['context_id', a2a.context_id],
    ['task_id',    a2a.task_id],
    ['role',       a2a.role],
  ].filter(([,v]) => v);
  (a2a.parts||[]).forEach((p, i) => {
    if (p.type === 'text') a2aMetaFields.push([`part[${i}].text`, p.text?.slice(0, 200)]);
  });

  let sections = `
    ${driftBox}
    ${cipJourneyHtml}
    ${sabHtml}
    <div class="dp-section a2a-outer">
      <div class="dp-section-title">🚌 A2A Message <span class="a2a-subtitle">transport envelope</span></div>
      ${a2aMetaFields.map(([k,v]) => dpField(k,v)).join('')}
      ${l9EnvelopeHtml}
    </div>`;

  // ── Raw JSON ──
  sections += `<div class="dp-section">
    <details>
      <summary>Raw JSON</summary>
      <pre class="dp-raw-pre">${JSON.stringify({a2a_message: entry.a2a_message, decoded_l9: info?.raw || {}}, null, 2)}</pre>
    </details>
  </div>`;

  dpBody.innerHTML = sections || `<div class="dp-empty">No payload data</div>`;
}

// ── Playback engine ───────────────────────────────────────────────────────────
let pbSpeed  = 900;   // ms per step
let _pbIdx   = -1;    // index of last revealed row (-1 = none shown)
let _pbTotal = 0;
let _pbTimer = null;
let _pbPlaying = false;

function _pbUpdateUI() {
  const shown = _pbIdx + 1;
  document.getElementById('pb-status').textContent = `${shown} / ${_pbTotal}`;
  const pct = _pbTotal ? (shown / _pbTotal * 100) : 0;
  document.getElementById('pb-progress-bar').style.width = pct + '%';
  document.getElementById('pb-prev').disabled  = _pbIdx <= 0;
  document.getElementById('pb-next').disabled  = _pbIdx >= _pbTotal - 1;
  const playBtn = document.getElementById('pb-play');
  playBtn.textContent = _pbPlaying ? '⏸ Pause' : '▶ Play';
  playBtn.classList.toggle('active', _pbPlaying);
}

function _pbReveal(i) {
  if (i < 0 || i >= _pbTotal) return;
  const msgs  = window._msgs  || [];
  const infos = window._infos || [];

  // Reveal phase-sep if this is the first message of a new phase
  const allRows    = document.querySelectorAll('#seq-body .seq-row');
  const allSeps    = document.querySelectorAll('#seq-body .phase-sep');
  const row = document.getElementById('row-' + i);
  if (!row) return;

  // Reveal preceding phase-sep if hidden
  let prev = row.previousElementSibling;
  while (prev) {
    if (prev.classList.contains('phase-sep') && prev.classList.contains('pb-hidden')) {
      prev.classList.remove('pb-hidden'); break;
    }
    if (prev.classList.contains('seq-row')) break;
    prev = prev.previousElementSibling;
  }

  row.classList.remove('pb-hidden');
  _pbIdx = i;

  // Scroll into view
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });

  // Auto-open detail panel
  if (msgs[i] && infos[i] !== undefined) {
    _activeRow = -1;   // force refresh
    showDetail(i, msgs[i], infos[i]);
  }
  _pbUpdateUI();
}

function pbNext() {
  if (_pbIdx < _pbTotal - 1) _pbReveal(_pbIdx + 1);
  else pbPause();
}
function pbPrev() {
  if (_pbIdx > 0) _pbReveal(_pbIdx - 1);
}
function pbPlay() {
  if (_pbPlaying) return;
  _pbPlaying = true;
  _pbUpdateUI();
  const tick = () => {
    if (!_pbPlaying) return;
    if (_pbIdx >= _pbTotal - 1) { pbPause(); return; }
    pbNext();
    _pbTimer = setTimeout(tick, pbSpeed);
  };
  _pbTimer = setTimeout(tick, _pbIdx < 0 ? 0 : pbSpeed);
}
function pbPause() {
  _pbPlaying = false;
  clearTimeout(_pbTimer);
  _pbUpdateUI();
}
function pbToggle() { _pbPlaying ? pbPause() : pbPlay(); }
function pbReset() {
  pbPause();
  // Re-hide all rows and phase-seps
  document.querySelectorAll('#seq-body .seq-row, #seq-body .phase-sep')
    .forEach(el => el.classList.add('pb-hidden'));
  // Clear any active highlight
  document.querySelectorAll('#seq-body .seq-row.active')
    .forEach(el => el.classList.remove('active'));
  _pbIdx = -1;
  _activeRow = -1;
  document.getElementById('dp-header').innerHTML = '<div class="dp-empty">Hover or use playback to inspect messages</div>';
  document.getElementById('dp-body').innerHTML = '';
}
function pbInit(total, autoPlay) {
  _pbTotal   = total;
  _pbIdx     = -1;
  _pbPlaying = false;
  clearTimeout(_pbTimer);
  document.getElementById('playback-section').style.display = '';
  _pbUpdateUI();
  if (autoPlay) setTimeout(pbPlay, 600);
}

function renderSeqRow(entry, idx, info, agents, colMap) {
  const N = agents.length;
  const phase = entry.phase;
  const kind  = info?.kind || '—';
  const sub   = info?.subprotocol || phase;
  const kColor = KIND_COLOR[kind]  || 'var(--muted)';
  const kBg    = KIND_BG[kind]     || 'var(--border)';
  const sColor = SUB_COLOR[sub]    || 'var(--muted)';
  const subkindText = info?.subkind ? `:${info.subkind}` : '';

  // Determine sender/receiver columns
  const senderAgent = !SKIP_AGENTS.test(info?.sender||'') ? info?.sender : null;
  const recvAgents  = (info?.receivers||[]).filter(r => !SKIP_AGENTS.test(r));
  const sCol = senderAgent != null ? (colMap[senderAgent] ?? -1) : -1;
  const rCols = recvAgents.map(r => colMap[r] ?? -1).filter(c => c >= 0);
  const rCol  = rCols.length > 0 ? rCols[0] : -1;

  // Build column cells
  let colsHtml = '';
  for (let i = 0; i < N; i++) {
    const isSender   = i === sCol;
    const isReceiver = rCols.includes(i);
    colsHtml += `<div class="seq-col${isSender?' is-sender':''}${isReceiver?' is-receiver':''}"></div>`;
  }

  // Build arrow overlay
  let arrowHtml = '';
  let gutterHint = '';   // extra annotation shown in the step gutter

  if (sCol >= 0) {
    const colW = 100 / N;
    const isSelfSend = rCol === sCol;
    const isBroadcast = rCol < 0;

    if (isBroadcast || isSelfSend) {
      // ── Broadcast or self-send ──
      const centerPct = (sCol + 0.5) * colW;
      const label  = isBroadcast ? 'broadcast' : 'self';
      const icon   = isBroadcast ? '📡' : '↩';
      gutterHint = isBroadcast
        ? `<div class="routing-hint broadcast-hint">${icon} broadcast · topic:tfp/polls</div>`
        : `<div class="routing-hint self-hint">${icon} self-send</div>`;
      arrowHtml = `
        <div class="seq-arrow-wrap" style="left:calc(${centerPct}% - 90px);width:180px;">
          <div class="seq-arrow-inner">
            <div class="arrow-label-row">
              <span class="arrow-kind" style="color:${kColor}">${kind}${subkindText}</span>
              ${subBadge(sub)}
            </div>
            <div class="self-arrow-box" style="border-color:${kColor};color:${kColor}">
              ${icon} <strong>${senderAgent||'?'}</strong>
              <span style="opacity:.7;font-size:.85em">${label}</span>
            </div>
          </div>
        </div>`;
    } else {
      const leftToRight = rCol > sCol;
      const fromPct = (Math.min(sCol, rCol) + 0.5) * colW;
      const toPct   = (Math.max(sCol, rCol) + 0.5) * colW;
      const leftPct = fromPct;
      const widthPct = toPct - fromPct;

      arrowHtml = `
        <div class="seq-arrow-wrap" style="left:${leftPct}%;width:${widthPct}%;">
          <div class="seq-arrow-inner">
            <div class="arrow-label-row" style="${leftToRight ? '' : 'flex-direction:row-reverse'}">
              <span class="arrow-kind" style="color:${kColor}">${kind}${subkindText}</span>
              ${subBadge(sub)}
            </div>
            <div class="arrow-line-row" style="${leftToRight ? '' : 'flex-direction:row-reverse'}">
              ${leftToRight ? '' : `<div class="arrow-head left" style="color:${kColor}"></div>`}
              <div class="arrow-line" style="background:${kColor}"></div>
              ${leftToRight ? `<div class="arrow-head right" style="color:${kColor}"></div>` : ''}
            </div>
          </div>
        </div>`;
    }
  }

  const id = idx;
  const isDrift = entry.phase === 'SIEP' && entry.label.includes('⚠');
  const driftBadge = isDrift
    ? `<div class="drift-badge">⚠ DRIFT DETECTED — tort doctrine applied</div>` : '';
  return `
<div class="seq-row${isDrift ? ' seq-row--drift' : ''} pb-hidden" id="row-${id}" onmouseenter="showDetail(${id}, _msgs[${id}], _infos[${id}])">
  <div class="seq-gutter">
    <span class="seq-num">#${String(idx+1).padStart(2,'0')}</span>
    <span class="seq-step-label">${entry.label}</span>
    <div class="seq-badges">
      ${kindBadge(kind)}
    </div>
    ${gutterHint}
    ${driftBadge}
  </div>
  <div class="seq-cols">
    ${colsHtml}
    ${arrowHtml}
  </div>
</div>`;
}

function renderSequence(msgs, autoPlay) {
  const agents = collectAgents(msgs);
  const colMap = {};
  agents.forEach((a, i) => colMap[a] = i);

  // Store globally for hover access
  window._msgs  = msgs;
  window._infos = msgs.map(m => extractL9Info(m));

  // Render agent headers
  const headEl = document.getElementById('seq-head');
  headEl.innerHTML = `<div class="seq-head-gutter">Step / Label</div>` +
    agents.map(a => `
      <div class="agent-hdr">
        <span class="agent-hdr-icon">${agentIcon(a)}</span>
        <div class="agent-hdr-name">${a}</div>
      </div>`).join('');

  // Stats bar
  const counts = {};
  msgs.forEach(m => counts[m.phase] = (counts[m.phase]||0)+1);
  document.getElementById('stats-bar').innerHTML = [['Total', msgs.length], ...Object.entries(counts)]
    .map(([l,n]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

  // Message rows
  let html = '';
  let lastPhase = '';
  const PHASE_NAMES = { TFP:'Team Formation Protocol', SIEP:'Semantic Interaction Exchange Protocol', CIP:'Contingency Interaction Protocols', SAB:'Semantic Alignment via Bargaining' };

  msgs.forEach((m, i) => {
    const info = extractL9Info(m);
    if (m.phase !== lastPhase) {
      lastPhase = m.phase;
      const pc = PHASE_COLOR[m.phase] || 'var(--muted)';
      html += `<div class="phase-sep pb-hidden">
        <div class="phase-sep-gutter" style="color:${pc};font-size:1rem;font-weight:700">
          ${m.phase} — ${PHASE_NAMES[m.phase]||''}
        </div>
        <div class="phase-sep-line" style="background:${pc};opacity:.3"></div>
      </div>`;
    }
    html += renderSeqRow(m, i, info, agents, colMap);
  });

  document.getElementById('seq-body').innerHTML = html;
  pbInit(msgs.length, autoPlay);
}

function loadMessages(autoPlay) {
  fetch('/messages')
    .then(r => r.json())
    .then(data => {
      const msgs = data.episode_messages || [];
      if (msgs.length) renderSequence(msgs, autoPlay);
    })
    .catch(err => appendConsole('[UI ERROR] ' + err));
}

// Load existing messages on page load
window.addEventListener('DOMContentLoaded', () => {
  fetch('/messages').then(r => r.ok ? r.json() : null)
    .then(d => { if (d?.episode_messages?.length) loadMessages(false); })
    .catch(() => {});

  // ── Resize handle drag logic ──
  const handle = document.getElementById('resize-handle');
  const panel  = document.getElementById('detail-panel');
  let dragging = false, startX = 0, startW = 0;
  handle.addEventListener('mousedown', e => {
    dragging = true; startX = e.clientX; startW = panel.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const delta = startX - e.clientX;
    const newW = Math.max(320, Math.min(900, startW + delta));
    panel.style.width = newW + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  });
});
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # silence default logging
        pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self._send_html()
        elif path == "/run":
            self._sse_run()
        elif path == "/messages":
            self._send_json()
        else:
            self.send_error(404)

    # ── /  ────────────────────────────────────────────────────────────────────
    def _send_html(self):
        body = _HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── /messages  ────────────────────────────────────────────────────────────
    def _send_json(self):
        if not _MSG_JSON.exists():
            body = b'{"episode_messages":[]}'
        else:
            body = _MSG_JSON.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    # ── /run  (SSE)  ──────────────────────────────────────────────────────────
    def _sse_run(self):
        global _demo_running
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        with _run_lock:
            if not _demo_running:
                _demo_running = True
                while not _demo_queue.empty():
                    try: _demo_queue.get_nowait()
                    except queue.Empty: break
                threading.Thread(target=_stream_demo, daemon=True).start()

        def _sse(event: str, data: str) -> bytes:
            escaped = data.replace("\n", "\\n")
            return f"event: {event}\ndata: {escaped}\n\n".encode()

        try:
            while True:
                try:
                    item = _demo_queue.get(timeout=30)
                except queue.Empty:
                    # keep-alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue

                if item is None:
                    self.wfile.write(_sse("done", ""))
                    self.wfile.flush()
                    break

                self.wfile.write(_sse("line", item))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"  L9 Inspector  →  {url}")
    print(f"  Press Ctrl-C to stop")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")


if __name__ == "__main__":
    main()
