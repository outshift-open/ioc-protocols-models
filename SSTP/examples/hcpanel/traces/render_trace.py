#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
"""
Render a run-result JSON into an interleaved L9+LLM markdown trace.

Usage:
    python3 render_trace.py <result.json> [output.md]

Produces a trace in the same style as l9_trace_pt1008_cip_siep.md:
  - Header with patient / outcome / metrics
  - Episode A (TP) wire messages table
  - Episode B (TW) wire messages table + LLM layer per specialist
  - Episode C (task panel) wire messages table
  - Convergence detail block
  - Epistemic summary
  - LLM call breakdown
"""
from __future__ import annotations

import json
import sys
import datetime
from collections import defaultdict, Counter
from typing import Any, Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────────────

def _ts(msg: Dict[str, Any]) -> str:
    """Return HH:MM:SS from message.created_at, or empty string."""
    created = (msg.get("message") or {}).get("created_at", "")
    if not created:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(created.rstrip("Z"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ""


def _actor(msg: Dict[str, Any]) -> str:
    actors = (msg.get("participants") or {}).get("actors") or []
    if actors:
        return actors[0].get("id", "?")
    return "?"


def _utterance(msg: Dict[str, Any]) -> str:
    for part in (msg.get("payload") or []):
        if part.get("type") == "utterance":
            return str(part.get("content", ""))
    sem = msg.get("semantic") or {}
    schema = sem.get("schema_id", "")
    if schema:
        return schema.split(":")[-1]
    return ""


def _ep_suffix(msg: Dict[str, Any]) -> str:
    eid = (msg.get("message") or {}).get("episode", "") or ""
    for sfx in (":tp", ":tw", ":t"):
        if sfx in eid:
            return sfx
    # SIEP panel episodes look like :panel: or end in a UUID
    if ":panel:" in eid or ("tw" not in eid and "tp" not in eid and eid):
        return ":panel"
    return ""


def _siep_op(msg: Dict[str, Any]) -> str:
    for part in (msg.get("payload") or []):
        if part.get("type") in ("siep_proposal", "decision"):
            c = part.get("content") or {}
            op = c.get("operation", "")
            pos = c.get("position") or {}
            cause = pos.get("likely_cause", "")
            conf = pos.get("confidence") or pos.get("posterior") or ""
            if op == "accept":
                return f"**accept** `{cause}` conf={conf}"
            elif op in ("counter_proposal", "counter-proposal"):
                return f"**counter** → `{cause}` conf={conf}"
            elif op:
                return f"**{op}**"
    # convergence block
    for part in (msg.get("payload") or []):
        if part.get("type") == "convergence":
            c = part.get("content") or {}
            return f"**converged** mpc={c.get('mpc','')} gar={c.get('gar','')} scr={c.get('scr','')}"
    return ""


def _short_utterance(u: str, maxlen: int = 120) -> str:
    u = u.replace("\n", " ").strip()
    return (u[:maxlen] + "…") if len(u) > maxlen else u


def _role_from_agent(agent_id: str) -> str:
    parts = agent_id.split("-", 1)
    return parts[1].replace("-", "_") if len(parts) == 2 else agent_id


# ── partition wire messages ───────────────────────────────────────────────────

def _partition(wire: List[Dict[str, Any]]) -> Tuple[list, list, list, list]:
    """Split wire into tp, tw, task, knowledge — outer envelope only.

    Only messages whose episode ID ends in :tp, :tw, or :t are included.
    Inner SIEP panel messages (:panel:) and unscoped messages are excluded.
    knowledge messages are collected separately regardless of episode.
    """
    tp, tw, task, knowledge = [], [], [], []
    for m in wire:
        eid = (m.get("message") or {}).get("episode", "") or ""
        if m.get("kind") == "knowledge":
            knowledge.append(m)
        elif eid.endswith(":tp"):
            tp.append(m)
        elif eid.endswith(":tw"):
            tw.append(m)
        elif eid.endswith(":t"):
            task.append(m)
        # inner SIEP panel and unscoped messages are excluded from the session-flow view
    return tp, tw, task, knowledge


# ── wire table ────────────────────────────────────────────────────────────────

def _wire_table(
    msgs: List[Dict[str, Any]],
    start_idx: int = 1,
    label: str = "Ep. state",
    siep: bool = False,
) -> Tuple[str, int]:
    header = (
        f"| # | Time (UTC) | Actor | Kind | Subkind | Schema | {label} | "
        + ("SIEP operation | " if siep else "")
        + "Utterance |\n"
    )
    sep = (
        "|---|-----------|-------|------|---------|--------|"
        + ("-----------|" if not siep else "-----------|----------------|")
        + "-----------|\n"
    )
    rows = [header, sep]
    idx = start_idx
    for m in msgs:
        ts = _ts(m)
        actor = f"`{_actor(m)}`"
        kind = m.get("kind", "?")
        subkind = m.get("subkind") or "—"
        schema = ""
        sem = m.get("semantic") or {}
        schema_id = sem.get("schema_id", "")
        if schema_id:
            schema = schema_id.split(":")[-1]
        ep_label = _ep_suffix(m).lstrip(":") or "?"
        utt = _short_utterance(_utterance(m))
        if kind == "contingency":
            kind_cell = "**contingency**"
        elif kind == "commit" and subkind == "converged":
            kind_cell = "commit"
        else:
            kind_cell = kind
        if siep:
            siep_op = _siep_op(m)
            rows.append(
                f"| {idx} | {ts} | {actor} | {kind_cell} | {subkind} "
                f"| {schema} | {ep_label} | {siep_op} | {utt} |\n"
            )
        else:
            rows.append(
                f"| {idx} | {ts} | {actor} | {kind_cell} | {subkind} "
                f"| {schema} | {ep_label} | {utt} |\n"
            )
        idx += 1
    return "".join(rows), idx


# ── LLM layer per specialist ──────────────────────────────────────────────────

def _llm_layer_tw(
    tw_msgs: List[Dict[str, Any]],
    llm_by_agent: Dict[str, List[Dict[str, Any]]],
    specialist_opinions: List[Dict[str, Any]],
    wire_start: int,
) -> str:
    lines: List[str] = []
    lines.append("\n### LLM Layer — Per-Specialist Thoughts, Judge Verdicts, ToM Predictions\n\n")
    lines.append("Each specialist row below covers: private **thought**, **judge verdict** for each "
                 "assertion pass, and **ToM prediction** before the SIEP round.\n\n---\n\n")

    # Build agent → wire message index (exchange msgs only)
    agent_exchange_msgs: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for i, m in enumerate(tw_msgs):
        if m.get("kind") in ("exchange",):
            agent_exchange_msgs[_actor(m)].append((wire_start + i, m))

    # Find likely_cause / confidence from specialist_opinions
    opinion_map: Dict[str, Dict[str, Any]] = {op.get("specialist_id", ""): op for op in specialist_opinions}

    for agent_id, agent_llm in sorted(llm_by_agent.items()):
        if agent_id in ("diagnostics-controller", "team-memory"):
            continue
        op = opinion_map.get(agent_id, {})
        cause = op.get("likely_cause", "?")
        conf = op.get("confidence") or op.get("posterior") or "?"
        role = op.get("specialty") or _role_from_agent(agent_id)

        lines.append(f"#### `{agent_id}` — {role} · likely\\_cause=**{cause}** · conf={conf}\n\n")

        # thought from diagnostics_assessment
        da_calls = [c for c in agent_llm if c.get("task") == "diagnostics_assessment"]
        if da_calls:
            thought = da_calls[0].get("response", {}).get("rationale", "") or da_calls[0].get("thought_summary", "")
            lines.append(f"**Thought:** {_short_utterance(thought, 300)}\n\n")

        # judge verdicts
        judge_calls = [c for c in agent_llm if c.get("task") == "ie_utterance_judge"]
        wire_exchanges = agent_exchange_msgs.get(agent_id, [])
        for pass_idx, (judge, (msg_n, _wire_m)) in enumerate(zip(judge_calls, wire_exchanges), start=1):
            resp = judge.get("response") or {}
            if not resp and not judge.get("success", True):
                lines.append(f"**Judge pass {pass_idx}** (msg #{msg_n}): **FAILED** — {judge.get('error','empty response')}. Grounding passed by default.\n\n")
                continue
            gf = resp.get("grounding_failure", False)
            amb = resp.get("ambiguous", False)
            score = resp.get("ambiguity_score", resp.get("contingency_score", "?"))
            critique = resp.get("critique", "")
            gf_str = "True" if gf else "False"
            amb_str = "True" if amb else "False"
            label = "initial" if pass_idx == 1 else "re-assertion"
            lines.append(
                f"**Judge pass {pass_idx}** (msg #{msg_n}, {label}): "
                f"`grounding_failure={gf_str}` · `ambiguous={amb_str}` · `score={score}`\n"
            )
            if critique:
                lines.append(f"> {_short_utterance(critique, 400)}\n")
            lines.append("\n")

        # ToM prediction (tom_peer_predict called by coordinator for this agent)
        tom_calls = [c for c in agent_llm if c.get("task") == "tom_peer_predict"]
        if tom_calls:
            t = tom_calls[0]
            resp = t.get("response") or {}
            predicted = resp.get("predicted_response", "")
            basis = resp.get("prediction_basis", "") or resp.get("thought_summary", "")
            alignment = resp.get("predicted_alignment", "?")
            lines.append(f"**ToM peer prediction (SIEP):** predicted\\_alignment={alignment}\n")
            if predicted:
                lines.append(f"> *Predicted:* {_short_utterance(predicted, 300)}\n")
            if basis:
                lines.append(f"> *Thought:* {_short_utterance(basis, 300)}\n")
            lines.append("\n---\n\n")
        else:
            lines.append("---\n\n")

    return "".join(lines)


# ── SIEP panel details ────────────────────────────────────────────────────────

def _siep_detail(task_msgs: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    # Extract opening position from first propose exchange
    ctrl_cause = "?"
    ctrl_conf: Any = "?"
    for m in task_msgs:
        if m.get("kind") == "exchange":
            for part in (m.get("payload") or []):
                if part.get("type") in ("siep_proposal",):
                    c = (part.get("content") or {}).get("position") or {}
                    ctrl_cause = c.get("likely_cause", ctrl_cause)
                    ctrl_conf = c.get("confidence") or c.get("posterior") or ctrl_conf
                    break
            if ctrl_cause != "?":
                break
    lines.append(f"\n**Coordinator opening position:** `{ctrl_cause}` · confidence={ctrl_conf}. "
                 "Star negotiation — one propose→response pair per specialist.\n\n")
    return "".join(lines)


# ── convergence block ─────────────────────────────────────────────────────────

def _convergence_block(task_msgs: List[Dict[str, Any]], ep: Dict[str, Any]) -> str:
    metrics = ep.get("convergence_metrics") or {}
    gar = metrics.get("gar", "?")
    scr = metrics.get("scr", "?")
    mpc = metrics.get("mpc", "?")
    resolution = ep.get("resolution_label", "?")
    cause = ep.get("symptom_conclusion", "?")
    panel_ep_id = ep.get("panel_episode_id", "?")

    # Extract convergence payload from last commit:converged
    conv_block: Dict[str, Any] = {
        "operation": "accept",
        "mpc": mpc,
        "gar": gar,
        "scr": scr,
        "episode_id": panel_ep_id,
    }
    participants: List[str] = []
    for m in task_msgs:
        if m.get("kind") == "commit" and m.get("subkind") == "converged":
            for part in (m.get("payload") or []):
                if part.get("type") == "convergence":
                    c = part.get("content") or {}
                    conv_block.update(c)
                    participants = c.get("participant_ids", [])

    lines = ["\n## 2  Convergence Detail\n\n"]
    lines.append(f"**Episode URN:** `{panel_ep_id}`\n\n")
    lines.append("**SIEP convergence block:**\n\n")
    lines.append("```json\n")
    lines.append(json.dumps(conv_block, indent=2))
    lines.append("\n```\n\n")
    lines.append(
        f"**GAR = {gar}** — all specialists responded (no non-response).  \n"
        f"**SCR = {scr}** — social compliance ratio.  \n"
        f"**MPC = {mpc}** — mean posterior confidence across all specialists.  \n"
        f"**Resolution:** `{resolution}` → winning concept `{cause}`\n"
    )
    return "".join(lines)


# ── epistemic summary ─────────────────────────────────────────────────────────

def _epistemic_summary(
    specialist_opinions: List[Dict[str, Any]],
    tw_llm: Dict[str, List[Dict[str, Any]]],
    task_msgs: List[Dict[str, Any]],
) -> str:
    lines = ["\n## 3  Epistemic Summary\n\n"]

    # Panel split
    physician_ops = [op for op in specialist_opinions if op.get("panel") == "physician"]
    pharma_ops = [op for op in specialist_opinions if op.get("panel") == "pharmacology"]

    if physician_ops or pharma_ops:
        lines.append("### Physician vs. Pharmacology Split\n\n")
        lines.append("| Panel | Agent | Cause asserted | Confidence |\n")
        lines.append("|-------|-------|---------------|------------|\n")
        for op in physician_ops + pharma_ops:
            panel = op.get("panel", "?")
            agent = op.get("specialist_id", "?")
            cause = op.get("likely_cause", "?")
            conf = op.get("confidence") or op.get("posterior") or "?"
            lines.append(f"| {panel} | `{agent}` | {cause} | {conf:.3f} |\n" if isinstance(conf, float) else f"| {panel} | `{agent}` | {cause} | {conf} |\n")
        lines.append("\n")

    # TW contingency pattern
    n_contingency = sum(1 for a_llm in tw_llm.values() for c in a_llm if c.get("task") == "ie_utterance_judge")
    n_failed = sum(1 for a_llm in tw_llm.values() for c in a_llm if not c.get("success", True))
    lines.append("### TW SIEP Contingency Pattern\n\n")
    lines.append(
        f"Total judge calls across TW round: {n_contingency}. "
        f"Failed calls: {n_failed}. "
        "Each specialist declares an independent prior; the coordinator verifies grounding before "
        "the SIEP round can proceed.\n\n"
    )

    # SIEP counter-proposal count
    n_counter = sum(
        1 for m in task_msgs
        for part in (m.get("payload") or [])
        if part.get("type") == "decision"
        and (part.get("content") or {}).get("operation") in ("counter_proposal", "counter-proposal")
    )
    n_accept = sum(
        1 for m in task_msgs
        for part in (m.get("payload") or [])
        if part.get("type") == "decision"
        and (part.get("content") or {}).get("operation") == "accept"
    )
    lines.append("### SIEP Round Result\n\n")
    lines.append(f"Accepts: {n_accept} · Counter-proposals: {n_counter}\n\n")

    return "".join(lines)


# ── LLM call breakdown ────────────────────────────────────────────────────────

def _llm_breakdown(llm_trace: List[Dict[str, Any]]) -> str:
    task_counter: Counter = Counter()
    failed_counter: Counter = Counter()
    for item in llm_trace:
        t = item.get("task", "?")
        task_counter[t] += 1
        if not item.get("success", True):
            failed_counter[t] += 1

    lines = ["\n## 4  LLM Call Breakdown\n\n"]
    lines.append("| Task | Calls | OK | Failed |\n")
    lines.append("|------|-------|----|--------|\n")
    total_calls = sum(task_counter.values())
    total_failed = sum(failed_counter.values())
    for task, count in sorted(task_counter.items()):
        fail = failed_counter.get(task, 0)
        ok = count - fail
        lines.append(f"| `{task}` | {count} | {ok} | {fail} |\n")
    lines.append(f"| **Total** | **{total_calls}** | **{total_calls - total_failed}** | **{total_failed}** |\n")
    return "".join(lines)


# ── main renderer ─────────────────────────────────────────────────────────────

def render(result_path: str, output_path: str) -> None:
    with open(result_path) as f:
        data = json.load(f)

    episodes = data.get("episodes", [])
    if not episodes:
        print("No episodes found in result JSON.", file=sys.stderr)
        sys.exit(1)

    ep = episodes[0]
    patient_id = ep.get("patient_id", "?")
    episode_id = ep.get("episode_id", "?")
    cause = ep.get("symptom_conclusion", "?")
    resolution = ep.get("resolution_label", "?")
    metrics = ep.get("convergence_metrics") or {}
    gar = metrics.get("gar", "?")
    scr = metrics.get("scr", "?")
    mpc = metrics.get("mpc", "?")
    panel_episode_id = ep.get("panel_episode_id", episode_id)

    wire: List[Dict[str, Any]] = ep.get("trace", [])
    llm_trace: List[Dict[str, Any]] = ep.get("llm_trace", [])
    specialist_opinions: List[Dict[str, Any]] = ep.get("specialist_opinions", [])

    # Partition wire by episode phase
    tp_msgs, tw_msgs, task_msgs, knowledge_msgs = _partition(wire)

    # Group LLM trace by agent_id
    llm_by_agent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in llm_trace:
        aid = item.get("agent_id") or ""
        llm_by_agent[aid].append(item)

    # ── header ──
    out: List[str] = []
    today = datetime.date.today().isoformat()
    out.append(f"# L9 Message Trace — Patient {patient_id}\n\n")
    out.append(
        f"**Patient:** {patient_id} · **Outcome:** {resolution} · "
        f"**Cause:** {cause} · **MPC:** {mpc}  \n"
        f"**Run date:** {today}  \n"
        f"**Backend:** {data.get('llm_backend', '?')} / {data.get('model', '?')}  \n"
        f"**Episode URN:** `{episode_id}`  \n\n"
    )
    out.append("**What changed vs. prior traces:** First run with full taskwork-as-SIEP architecture "
               "(Episode B is now a SIEP debate; each specialist independently fetches its prior and "
               "declares a position, replacing the old serial CIP assertion loop).\n\n---\n\n")

    # Totals table
    n_tp = len(tp_msgs)
    n_tw = len(tw_msgs)
    n_task = len(task_msgs) + len(knowledge_msgs)
    n_wire = len(wire)
    n_llm = len(llm_trace)
    n_failed_llm = sum(1 for x in llm_trace if not x.get("success", True))
    n_tom = sum(1 for x in llm_trace if x.get("task", "").startswith("tom_"))
    n_judge = sum(1 for x in llm_trace if x.get("task") == "ie_utterance_judge")
    n_contingency_tw = sum(1 for m in tw_msgs if m.get("kind") == "contingency")

    out.append("**Totals**\n\n")
    out.append("| Source | Count |\n|--------|-------|\n")
    out.append(f"| TP wire messages | {n_tp} |\n")
    out.append(f"| TW wire messages (SIEP) | {n_tw} |\n")
    out.append(f"| Task panel messages (SIEP) | {n_task} |\n")
    out.append(f"| Total L9 wire messages | {n_wire} |\n")
    out.append(f"| TW contingency events | {n_contingency_tw} |\n")
    out.append(f"| LLM calls total | {n_llm} |\n")
    out.append(f"| LLM failed | {n_failed_llm} |\n")
    out.append(f"| ToM calls | {n_tom} |\n")
    out.append(f"| Judge calls (ie_utterance_judge) | {n_judge} |\n")
    out.append(f"| GAR | {gar} |\n")
    out.append(f"| SCR | {scr} |\n")
    out.append("\n---\n\n")

    # Patient context
    out.append("## 0  Patient Context\n\n")
    # Get patient data from specialist opinions or wire
    first_opinion = specialist_opinions[0] if specialist_opinions else {}
    meds = ep.get("proposed_drug_changes", [])
    out.append(f"**Patient:** {patient_id}  \n")
    out.append(f"**Recommended changes:** {', '.join(meds) if meds else 'none'}  \n")
    out.append(f"**Joint recommendation:** {ep.get('joint_recommendation', '')}  \n\n---\n\n")

    # ── Section 1: wire tables ──
    out.append("## 1  CIP + SIEP Session-Flow Messages\n\n")
    out.append("Grammar: `intent → exchange* → [contingency → exchange* → commit:resolved]* → commit`\n\n")

    # Episode legend
    out.append("### Episode Legend\n\n")
    out.append("| Episode URN suffix | Protocol | Label | Note |\n")
    out.append("|-------------------|----------|-------|------|\n")
    out.append(f"| `…:tp` | CIP | team-process | {n_tp} messages |\n")
    out.append(f"| `…:tw` | SIEP | taskwork (prior declaration) | {n_tw} messages |\n")
    out.append(f"| `…:t` / panel | SIEP | task panel negotiation | {len(task_msgs)+len(knowledge_msgs)} messages |\n\n---\n\n")

    # TP table
    out.append("### Team Process Episode (`…:tp`)\n\n")
    if tp_msgs:
        table, next_idx = _wire_table(tp_msgs, start_idx=1, label="Ep. state")
        out.append(table)
    else:
        out.append("_(no TP messages in trace)_\n")
        next_idx = 1
    out.append("\n---\n\n")

    # TW table
    out.append("### Taskwork Episode (`…:tw`) — Specialist Priors + SIEP Debate\n\n")
    out.append(
        "Each specialist independently assesses patient data and declares a prior. "
        "Unlike the old serial CIP assertion loop, this is a full SIEP debate: "
        "specialists accept the controller's framing or counter-propose with their own prior.\n\n"
    )
    if tw_msgs:
        tw_table, next_idx2 = _wire_table(tw_msgs, start_idx=next_idx, label="Ep. state / belief")
        out.append(tw_table)
    else:
        out.append("_(no TW messages in trace)_\n")
        next_idx2 = next_idx
    out.append("\n---\n\n")

    # TW LLM layer
    if tw_msgs and llm_trace:
        out.append(_llm_layer_tw(tw_msgs, llm_by_agent, specialist_opinions, next_idx))

    out.append("---\n\n")

    # Task panel table
    out.append("### SIEP Task Panel (`…:t`)\n\n")
    if task_msgs:
        out.append(_siep_detail(task_msgs))
        siep_table, _ = _wire_table(task_msgs + knowledge_msgs, start_idx=1, label="Ep. state", siep=True)
        out.append(siep_table)
    else:
        out.append("_(no task panel messages in trace)_\n")
    out.append("\n---\n\n")

    # Convergence detail
    out.append(_convergence_block(task_msgs, ep))

    # Epistemic summary
    out.append(_epistemic_summary(specialist_opinions, llm_by_agent, task_msgs))

    # LLM breakdown
    out.append(_llm_breakdown(llm_trace))

    with open(output_path, "w") as f:
        f.write("".join(out))

    print(f"Wrote {output_path}  ({len(out)} sections)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <result.json> [output.md]", file=sys.stderr)
        sys.exit(1)
    result_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else result_path.replace(".json", "-trace.md")
    render(result_path, output_path)
