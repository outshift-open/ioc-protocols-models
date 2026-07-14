#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
"""
Render a run-result JSON into an interleaved L9+LLM markdown trace.

Design: wire messages and LLM calls are interleaved structurally by phase
and agent.  Within each phase, each agent's LLM thinking block appears
immediately before their wire message — giving a full prompt → thought →
response → wire-event reading order.  Utterances are shown in full.

Usage:
    python3 render_trace.py <result.json> [--output output.md] [--combined]
"""
from __future__ import annotations

import json
import sys
import argparse
import datetime
from collections import defaultdict, Counter
from typing import Any, Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────────────

def _ts_llm(item: Dict[str, Any]) -> str:
    raw = item.get("msg_created", "")
    if not raw:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(raw.rstrip("Z"))
        return dt.strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
    except Exception:
        return raw[:19]


def _actor(msg: Dict[str, Any]) -> str:
    actors = (msg.get("participants") or {}).get("actors") or []
    return actors[0].get("id", "?") if actors else "?"


def _recipients(msg: Dict[str, Any]) -> List[str]:
    actors = (msg.get("participants") or {}).get("actors") or []
    return [a.get("id", "") for a in actors[1:] if a.get("id")]


def _utterance(msg: Dict[str, Any]) -> str:
    for part in (msg.get("payload") or []):
        if part.get("type") == "utterance":
            return str(part.get("content", ""))
    return ""


def _rationale(msg: Dict[str, Any]) -> str:
    """Extract rationale from the utterance payload part."""
    for part in (msg.get("payload") or []):
        if part.get("type") == "utterance":
            return str(part.get("rationale", "") or "")
    return ""


def _rich_payload(msg: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Return (type, content) for all non-utterance payload parts."""
    result = []
    for part in (msg.get("payload") or []):
        if part.get("type") != "utterance":
            result.append((part.get("type", "?"), part.get("content")))
    return result


def _ep_id(msg: Dict[str, Any]) -> str:
    return (msg.get("message") or {}).get("episode", "") or ""


def _msg_id(msg: Dict[str, Any]) -> str:
    return (msg.get("message") or {}).get("id", "")[:8]


def _phase_of(msg: Dict[str, Any]) -> str:
    eid = _ep_id(msg)
    if eid.endswith(":tp"):
        return "tp"
    if eid.endswith(":tw"):
        return "tw"
    if eid.endswith(":t"):
        return "t"
    if msg.get("kind") == "knowledge":
        return "knowledge"
    return "other"


def _json_block(obj: Any, indent: int = 2) -> str:
    return "```json\n" + json.dumps(obj, indent=indent, ensure_ascii=False) + "\n```"


def _hr() -> str:
    return "\n---\n\n"


# ── partition ─────────────────────────────────────────────────────────────────

def _partition(wire: List[Dict[str, Any]]) -> Tuple[list, list, list, list, list]:
    """Split outer-envelope messages into tp / tw / t / knowledge / other."""
    tp, tw, task, knowledge, other = [], [], [], [], []
    for m in wire:
        phase = _phase_of(m)
        if phase == "tp":
            tp.append(m)
        elif phase == "tw":
            tw.append(m)
        elif phase == "t":
            task.append(m)
        elif phase == "knowledge":
            knowledge.append(m)
        else:
            other.append(m)
    return tp, tw, task, knowledge, other


# ── wire event block ──────────────────────────────────────────────────────────

def _wire_event(seq: int, msg: Dict[str, Any], phase_label: str) -> str:
    """Render one wire message as a headed block with full utterance + payload."""
    kind = msg.get("kind", "?")
    subkind = msg.get("subkind") or ""
    actor = _actor(msg)
    recips = _recipients(msg)
    msg_id = _msg_id(msg)

    kind_display = kind.upper()
    if subkind:
        kind_display += f":{subkind}"

    # Header line
    to_str = ", ".join(f"`{r}`" for r in recips) if recips else "_(multicast)_"
    lines = [
        f"### [{seq}] `{actor}` → {to_str} &nbsp; **{kind_display}** &nbsp; `{phase_label}` &nbsp; `id={msg_id}`\n\n"
    ]

    # Utterance + rationale
    utt = _utterance(msg)
    rat = _rationale(msg)
    if utt:
        lines.append(f"**Utterance:** {utt}\n\n")
    if rat and not utt.startswith("received:"):
        lines.append(f"**Rationale:** {rat}\n\n")

    # Rich payload parts — extract inline reasoning from siep/cip blocks before dumping JSON
    for ptype, pcontent in _rich_payload(msg):
        if pcontent is None:
            continue
        if isinstance(pcontent, dict):
            # Pull out reasoning fields from siep/cip proposal payloads
            if ptype in ("siep", "cip"):
                pp = (pcontent.get("proposal_payload") or {})
                rs = pp.get("reasoning_summary") or pcontent.get("reasoning_summary") or ""
                critique = pcontent.get("critique") or pp.get("critique") or ""
                if rs:
                    lines.append(f"**Reasoning:** {rs}\n\n")
                if critique:
                    lines.append(f"**Critique:** {critique}\n\n")
            lines.append(f"**`{ptype}`**\n\n")
            lines.append(_json_block(pcontent))
            lines.append("\n\n")
        elif isinstance(pcontent, (list, bool, int, float)):
            lines.append(f"**`{ptype}`:** `{json.dumps(pcontent)}`\n\n")
        else:
            lines.append(f"**`{ptype}`:** {pcontent}\n\n")

    # Epistemic block
    ep_block = msg.get("epistemic")
    if ep_block:
        lines.append(f"**epistemic:** `{json.dumps(ep_block)}`\n\n")

    return "".join(lines)


# ── LLM call block ────────────────────────────────────────────────────────────

def _llm_event(item: Dict[str, Any]) -> str:
    task = item.get("task", "?")
    agent = item.get("agent_id", "?")
    ts = _ts_llm(item)
    success = item.get("success", True)
    thought = item.get("thought_summary", "")
    request = item.get("request", {})
    response = item.get("response", {})
    error = item.get("error", "")

    status = "OK" if success else f"**FAILED** — {error}"
    ts_str = f" · {ts}" if ts else ""

    lines = [
        f"<details>\n<summary>🧠 <strong>LLM: {task}</strong> · `{agent}`{ts_str} · {status}</summary>\n\n"
    ]

    # Thought summary + rationale — most important, shown before the JSON
    if thought:
        lines.append(f"**Thought:** {thought}\n\n")
    rationale = response.get("rationale") or response.get("reasoning_summary") or ""
    if rationale and rationale != thought:
        lines.append(f"**Rationale:** {rationale}\n\n")

    # Full response as JSON (collapsed under reasoning above)
    if response:
        resp_display = {k: v for k, v in response.items() if k not in ("rationale", "thought_summary")}
        if resp_display:
            lines.append("**Response:**\n\n")
            lines.append(_json_block(resp_display))
            lines.append("\n\n")

    # Prompt (payload only, not system prompt — it's boilerplate)
    user_payload = request.get("user_payload") or request.get("payload")
    if user_payload:
        lines.append("**Prompt payload:**\n\n")
        lines.append(_json_block(user_payload))
        lines.append("\n\n")

    lines.append("</details>\n\n")
    return "".join(lines)


# ── phase renderer ────────────────────────────────────────────────────────────

def _render_phase(
    label: str,
    msgs: List[Dict[str, Any]],
    llm_by_agent: Dict[str, List[Dict[str, Any]]],
    phase_key: str,
    seq_start: int,
    llm_tasks_for_phase: List[str],
    preamble: str = "",
) -> Tuple[str, int]:
    """
    Render one phase as a sequence of interleaved LLM + wire events.

    For each wire message, if the sending agent has LLM calls for this phase
    that haven't been emitted yet, emit them first, then the wire message.

    Controller LLM calls (e.g. tp_case_frame) are emitted before the intent.
    """
    lines = [f"## Phase: {label}\n\n"]
    if preamble:
        lines.append(preamble + "\n\n")

    # consumed[agent_id] = index of next LLM call to emit for this agent in this phase
    consumed: Dict[str, int] = defaultdict(int)

    # Filter per-agent LLM calls to only those relevant to this phase
    phase_llm: Dict[str, List[Dict[str, Any]]] = {}
    for agent_id, calls in llm_by_agent.items():
        relevant = [c for c in calls if c.get("task") in llm_tasks_for_phase]
        if relevant:
            phase_llm[agent_id] = relevant

    seq = seq_start

    for msg in msgs:
        actor = _actor(msg)
        kind = msg.get("kind", "")

        # Before the intent (first message), emit controller LLM calls
        if kind == "intent" and actor in phase_llm:
            for call in phase_llm[actor][consumed[actor]:]:
                lines.append(_llm_event(call))
                consumed[actor] += 1

        # Before each specialist's exchange, emit their LLM calls
        elif kind == "exchange":
            if actor in phase_llm:
                for call in phase_llm[actor][consumed[actor]:]:
                    lines.append(_llm_event(call))
                    consumed[actor] += 1

        lines.append(_wire_event(seq, msg, phase_key))
        seq += 1

    # Any remaining LLM calls not yet emitted (e.g. controller synthesis after all exchanges)
    for agent_id, calls in phase_llm.items():
        remaining = calls[consumed[agent_id]:]
        for call in remaining:
            lines.append(_llm_event(call))

    return "".join(lines), seq


# ── knowledge section ─────────────────────────────────────────────────────────

def _render_knowledge(msgs: List[Dict[str, Any]], seq_start: int) -> Tuple[str, int]:
    if not msgs:
        return "", seq_start
    lines = ["## Knowledge Broadcast\n\n"]
    seq = seq_start
    for msg in msgs:
        lines.append(_wire_event(seq, msg, "knowledge"))
        seq += 1
    return "".join(lines), seq


# ── convergence + metrics ─────────────────────────────────────────────────────

def _render_convergence(ep: Dict[str, Any], task_msgs: List[Dict[str, Any]]) -> str:
    metrics = ep.get("convergence_metrics") or {}
    gar = metrics.get("gar", "?")
    scr = metrics.get("scr", "?")
    mpc = metrics.get("mpc", "?")
    resolution = ep.get("resolution_label", "?")
    cause = ep.get("symptom_conclusion", "?")

    # Extract convergence payload from commit:converged
    conv_block: Dict[str, Any] = {"mpc": mpc, "gar": gar, "scr": scr}
    for m in task_msgs:
        if m.get("kind") == "commit" and m.get("subkind") == "converged":
            for part in (m.get("payload") or []):
                if part.get("type") == "convergence":
                    conv_block.update(part.get("content") or {})

    lines = ["## Convergence\n\n"]
    lines.append(f"**Resolution:** `{resolution}` → **`{cause}`**\n\n")
    lines.append(f"| Metric | Value | Meaning |\n|--------|-------|---------|")
    lines.append(f"\n| GAR | `{gar}` | Genuine agreement ratio — fraction whose belief moved >5% |\n")
    lines.append(f"| SCR | `{scr}` | Social compliance ratio — fraction who rubber-stamped |\n")
    lines.append(f"| MPC | `{mpc}` | Mean posterior confidence across all specialists |\n\n")
    lines.append("**Convergence block:**\n\n")
    lines.append(_json_block(conv_block))
    lines.append("\n\n")
    return "".join(lines)


# ── specialist summary table ──────────────────────────────────────────────────

def _render_specialist_table(specialist_opinions: List[Dict[str, Any]]) -> str:
    if not specialist_opinions:
        return ""
    lines = ["## Specialist Opinions\n\n"]
    lines.append("| Panel | Agent | Cause | Conf | Interaction↑ | Disease↑ | Thought |\n")
    lines.append("|-------|-------|-------|------|-------------|---------|--------|\n")
    for op in specialist_opinions:
        panel = op.get("panel", "?")
        agent = op.get("specialist_id", "?")
        cause = op.get("likely_cause", "?")
        conf = op.get("confidence") or op.get("posterior") or "?"
        inter = op.get("interaction_likelihood", "")
        dis = op.get("new_disease_likelihood", "")
        thought = op.get("rationale") or op.get("thought_summary") or ""
        conf_str = f"{conf:.3f}" if isinstance(conf, float) else str(conf)
        inter_str = f"{inter:.3f}" if isinstance(inter, float) else str(inter)
        dis_str = f"{dis:.3f}" if isinstance(dis, float) else str(dis)
        lines.append(
            f"| {panel} | `{agent}` | **{cause}** | {conf_str} | {inter_str} | {dis_str} | {thought[:80]} |\n"
        )
    lines.append("\n")
    return "".join(lines)


# ── LLM call breakdown ────────────────────────────────────────────────────────

def _render_llm_breakdown(llm_trace: List[Dict[str, Any]]) -> str:
    task_counter: Counter = Counter()
    failed_counter: Counter = Counter()
    for item in llm_trace:
        t = item.get("task", "?")
        task_counter[t] += 1
        if not item.get("success", True):
            failed_counter[t] += 1

    total = sum(task_counter.values())
    total_failed = sum(failed_counter.values())

    lines = ["## LLM Call Summary\n\n"]
    lines.append("| Task | Calls | OK | Failed |\n|------|-------|----|--------|\n")
    for task, count in sorted(task_counter.items()):
        fail = failed_counter.get(task, 0)
        lines.append(f"| `{task}` | {count} | {count - fail} | {fail} |\n")
    lines.append(f"| **Total** | **{total}** | **{total - total_failed}** | **{total_failed}** |\n\n")
    return "".join(lines)


# ── main renderer ─────────────────────────────────────────────────────────────

def render(result_path: str, output_path: str, patient_filter: Optional[str] = None) -> None:
    with open(result_path) as f:
        data = json.load(f)

    episodes = data.get("episodes", [])
    if not episodes:
        print("No episodes found in result JSON.", file=sys.stderr)
        sys.exit(1)

    all_out: List[str] = []

    for ep_idx, ep in enumerate(episodes):
        patient_id = ep.get("patient_id", "?")
        if patient_filter and patient_id != patient_filter:
            continue

        episode_id = ep.get("episode_id", "?")
        cause = ep.get("symptom_conclusion", "?")
        resolution = ep.get("resolution_label", "?")
        metrics = ep.get("convergence_metrics") or {}
        gar = metrics.get("gar", "?")
        scr = metrics.get("scr", "?")
        mpc = metrics.get("mpc", "?")

        wire: List[Dict[str, Any]] = ep.get("trace", [])
        llm_trace: List[Dict[str, Any]] = ep.get("llm_trace", [])
        specialist_opinions: List[Dict[str, Any]] = ep.get("specialist_opinions", [])

        tp_msgs, tw_msgs, task_msgs, knowledge_msgs, _ = _partition(wire)

        # Group LLM trace by agent_id
        llm_by_agent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in llm_trace:
            llm_by_agent[item.get("agent_id") or ""].append(item)

        today = datetime.date.today().isoformat()

        # ── document header ──
        out: List[str] = []
        if ep_idx > 0:
            out.append("\n\n---\n\n")
        out.append(f"# L9 Interleaved Trace — Patient `{patient_id}`\n\n")
        out.append(
            f"**Patient:** `{patient_id}` · **Outcome:** `{resolution}` · "
            f"**Cause:** `{cause}`  \n"
            f"**Run date:** {today} · **Backend:** {data.get('llm_backend','?')} / {data.get('model','?')}  \n"
            f"**Episode URN:** `{episode_id}`  \n\n"
        )

        # Totals
        n_wire = len(wire)
        n_llm = len(llm_trace)
        n_failed = sum(1 for x in llm_trace if not x.get("success", True))
        n_contingency = sum(1 for m in tw_msgs + task_msgs if m.get("kind") == "contingency")
        out.append("| Metric | Value |\n|--------|-------|\n")
        out.append(f"| Wire messages | {n_wire} |\n")
        out.append(f"| TP / TW / T | {len(tp_msgs)} / {len(tw_msgs)} / {len(task_msgs)+len(knowledge_msgs)} |\n")
        out.append(f"| LLM calls | {n_llm} |\n")
        out.append(f"| LLM failed | {n_failed} |\n")
        out.append(f"| Contingency events | {n_contingency} |\n")
        out.append(f"| GAR / SCR / MPC | {gar} / {scr} / {mpc} |\n\n")
        out.append(_hr())

        # ── Patient context ──
        out.append("## Patient Context\n\n")
        out.append(f"**Patient:** `{patient_id}`  \n")
        meds = ep.get("proposed_drug_changes", [])
        out.append(f"**Recommended changes:** {', '.join(meds) if meds else 'none'}  \n")
        rec = ep.get("joint_recommendation", "")
        if rec:
            out.append(f"**Joint recommendation:** {rec}  \n")
        out.append("\n")
        out.append(_hr())

        seq = 1

        # ── Phase TP ──
        tp_preamble = (
            "**Protocol:** SNP  \n"
            "**Grammar:** `intent → exchange* → commit`  \n"
            "**Purpose:** Case framing — controller opens the session, "
            "all specialists acknowledge team process and roles.\n"
        )
        tp_out, seq = _render_phase(
            "Team Process (TP)",
            tp_msgs,
            llm_by_agent,
            "tp",
            seq,
            llm_tasks_for_phase=["tp_case_frame", "tp_process_debate", "tp_escalation_debate",
                                  "tp_process_synthesis", "tp_process_commit"],
            preamble=tp_preamble,
        )
        out.append(tp_out)
        out.append(_hr())

        # ── Phase TW ──
        tw_preamble = (
            "**Protocol:** SNP  \n"
            "**Grammar:** `intent → exchange* → commit`  \n"
            "**Purpose:** Taskwork — each specialist independently assesses "
            "patient data and declares a prior; controller verifies grounding.\n"
        )
        tw_out, seq = _render_phase(
            "Taskwork (TW) — Prior Declaration",
            tw_msgs,
            llm_by_agent,
            "tw",
            seq,
            llm_tasks_for_phase=["diagnostics_assessment", "team_prior_reasoning",
                                  "team_prior_commit"],
            preamble=tw_preamble,
        )
        out.append(tw_out)
        out.append(_hr())

        # ── Phase T (SIEP panel) ──
        t_preamble = (
            "**Protocol:** SNP → SIEP (star negotiation) → CIP (on contingency)  \n"
            "**Grammar:** `intent → [propose → response]* → commit:converged`  \n"
            "**Purpose:** Task panel — SNP frames the session; SIEP runs the debate; "
            "CIP fires bilaterally only when a specialist contingency needs grounding repair.\n"
        )
        t_out, seq = _render_phase(
            "Task Panel (T) — SIEP Negotiation",
            task_msgs,
            llm_by_agent,
            "t",
            seq,
            llm_tasks_for_phase=["task_accept_or_counter", "debate_accept_or_counter",
                                  "debate_controller_synthesis", "debate_pivot_synthesis"],
            preamble=t_preamble,
        )
        out.append(t_out)
        out.append(_hr())

        # ── Knowledge ──
        k_out, seq = _render_knowledge(knowledge_msgs, seq)
        if k_out:
            out.append(k_out)
            out.append(_hr())

        # ── Convergence ──
        out.append(_render_convergence(ep, task_msgs))
        out.append(_hr())

        # ── Specialist opinions table ──
        out.append(_render_specialist_table(specialist_opinions))
        if specialist_opinions:
            out.append(_hr())

        # ── LLM summary ──
        out.append(_render_llm_breakdown(llm_trace))

        all_out.extend(out)

    with open(output_path, "w") as f:
        f.write("".join(all_out))
    print(f"Wrote {output_path}  ({len(all_out)} sections, {len(episodes)} episode(s))")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Render hcpanel result JSON to interleaved trace markdown")
    parser.add_argument("result", help="Path to run-result JSON")
    parser.add_argument("--output", "-o", default=None, help="Output .md path (default: replace .json with -trace.md)")
    parser.add_argument("--patient", default=None, help="Filter to a single patient_id")
    parser.add_argument("--combined", action="store_true", help="Render all episodes into one file")
    args = parser.parse_args()

    output = args.output or args.result.replace(".json", "-trace.md")
    render(args.result, output, patient_filter=args.patient)


if __name__ == "__main__":
    main()
