#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
"""
Render a run-result JSON into an interleaved L9+LLM markdown trace.

Every wire message and every LLM call is wrapped in a <details> block so
the reader can expand exactly what they want.  All 287+ wire messages are
rendered in chronological order — nothing dropped.

Usage:
    python3 render_trace.py <result.json> [--output output.md]
    python3 render_trace.py <result.json> --patient pt-1008
    python3 render_trace.py <result.json> --combined
"""
from __future__ import annotations

import json
import sys
import argparse
import datetime
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


# ── helpers ───────────────────────────────────────────────────────────────────

def _ts(msg: Dict[str, Any]) -> str:
    raw = (msg.get("attributes") or {}).get("msg_created") or msg.get("msg_created") or ""
    if not raw:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(raw.rstrip("Z"))
        return dt.strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return raw[:19]


def _ts_llm(item: Dict[str, Any]) -> str:
    raw = item.get("msg_created", "")
    if not raw:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(raw.rstrip("Z"))
        return dt.strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return raw[:19]


def _actor(msg: Dict[str, Any]) -> str:
    actors = (msg.get("participants") or {}).get("actors") or []
    return actors[0].get("id", "?") if actors else msg.get("sender", "?")


def _recipients(msg: Dict[str, Any]) -> List[str]:
    actors = (msg.get("participants") or {}).get("actors") or []
    return [a.get("id", "") for a in actors[1:] if a.get("id")]


def _utterance(msg: Dict[str, Any]) -> str:
    for part in (msg.get("payload") or []):
        if part.get("type") == "utterance":
            return str(part.get("content", "") or "")
    return ""


def _rationale(msg: Dict[str, Any]) -> str:
    for part in (msg.get("payload") or []):
        if part.get("type") == "utterance":
            return str(part.get("rationale", "") or "")
    return ""


def _episode_id(msg: Dict[str, Any]) -> str:
    return (msg.get("message") or {}).get("episode", "") or msg.get("episode_id") or ""


def _msg_id(msg: Dict[str, Any]) -> str:
    return (msg.get("message") or {}).get("id", "") or ""


def _epistemic(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return (msg.get("context") or {}).get("epistemic") or msg.get("epistemic")


def _json_block(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, indent=2, ensure_ascii=False) + "\n```"


def _hr() -> str:
    return "\n---\n\n"


# ── phase assignment ──────────────────────────────────────────────────────────

_PHASE_LABELS = {
    "session":   "Session Open",
    "tp":        "Team Process (TP)",
    "tw":        "Taskwork (TW)",
    "t":         "Task Panel (T)",
    "knowledge": "Knowledge",
}

_PHASE_PREAMBLES = {
    "session": (
        "**Protocol:** SIEP  \n"
        "**Grammar:** `intent → exchange* (one ACK per participant)`  \n"
        "**Purpose:** Session plan announcement — controller declares phases (TP → TW → T), "
        "subprotocol (SIEP), and contingency handling (CIP). All participants acknowledge."
    ),
    "tp": (
        "**Protocol:** SIEP → CIP (on contingency)  \n"
        "**Grammar:** `intent → exchange* → [contingency → repair]* → commit`  \n"
        "**Purpose:** Case framing — controller opens the session; all specialists "
        "acknowledge team process and roles. CIP fires bilaterally if grounding fails."
    ),
    "tw": (
        "**Protocol:** SIEP → CIP (on contingency)  \n"
        "**Grammar:** `intent → exchange* → [contingency → repair]* → commit`  \n"
        "**Purpose:** Taskwork — each specialist independently assesses patient data "
        "and declares a prior; controller verifies grounding. CIP fires bilaterally if grounding fails."
    ),
    "t": (
        "**Protocol:** SIEP (star negotiation) → CIP (on contingency)  \n"
        "**Grammar:** `intent → [propose → response]* → [contingency → repair]* → commit:converged`  \n"
        "**Purpose:** Task panel — SIEP frames the session and runs the debate; "
        "CIP fires bilaterally when grounding fails."
    ),
    "knowledge": (
        "**Protocol:** SIEP  \n"
        "**Purpose:** Persistent knowledge broadcast — controller announces new "
        "common ground to the TeamEpistemicMemory."
    ),
}


def _classify_phase(eid: str, kind: str = "", utterance: str = "") -> Optional[str]:
    """Return phase label from episode URN and utterance content.

    Phase detection rules:
    - session:open utterance on bare session URN → "session"
    - session:close utterance on bare session URN → "session"
    - exchange (ACK) on bare session URN → "session"
    - tp:open utterance on :tp URN → "tp"
    - panel:open on panel:taskwork URN → "tw"
    - panel:open on panel:hcpanel URN → "t"
    """
    import re as _re
    _UUID_TAIL = _re.compile(r':[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.I)

    # Session open/close/ACK: bare session URN (no :tp/:tw/:t, no panel: segment)
    if (_UUID_TAIL.search(eid) and "panel:" not in eid and "cip_repair" not in eid
            and not eid.endswith(":tp") and not eid.endswith(":tw") and not eid.endswith(":t")
            and kind in ("intent", "exchange", "commit")):
        return "session"

    # Team process: inner SIEP panel:open on panel:team_process URN
    if "panel:team_process" in eid and utterance.startswith("panel:open"):
        return "tp"

    # Taskwork: inner SIEP panel:open on panel:taskwork URN
    if "panel:taskwork" in eid and utterance.startswith("panel:open"):
        return "tw"

    # Task: inner SIEP panel:open on panel:hcpanel URN
    if "panel:hcpanel" in eid and utterance.startswith("panel:open"):
        return "t"

    return None


def _assign_phases(msgs: List[Dict[str, Any]]) -> List[Tuple[str, int, Dict[str, Any]]]:
    """Assign (phase, depth, msg) to every wire message.

    depth=0  outer SIEP session envelope (episode ends :tp/:tw/:t)
    depth=1  inner SIEP panel (team_process/taskwork/hcpanel URNs)
    depth=2  CIP repair burst (:cip_repair: in episode)
    depth=0  knowledge broadcasts (same visual level as outer SIEP)

    Knowledge messages do NOT change the current outer phase.
    CIP repairs can occur inside any phase.
    """
    current = "session"
    result: List[Tuple[str, int, Dict[str, Any]]] = []
    for m in msgs:
        kind = m.get("kind", "")
        sub = m.get("subprotocol", "") or ""
        eid = _episode_id(m)
        utt = _utterance(m)
        outer = _classify_phase(eid, kind, utt)
        if outer is not None:
            current = outer
            result.append((current, 0, m))
        elif kind == "knowledge":
            result.append(("knowledge", 0, m))
        elif ":cip_repair:" in eid:
            result.append((current, 2, m))
        elif sub == "CIP" or sub == "cip":
            # CIP messages on the inner panel episode (repair_required / reaffirm etc.)
            result.append((current, 2, m))
        else:
            # inner SIEP panel
            result.append((current, 1, m))
    return result


# ── wire event block ──────────────────────────────────────────────────────────

_DEPTH_PREFIX = {0: "", 1: "↳ SIEP &nbsp;", 2: "↳↳ CIP &nbsp;"}


def _wire_event(seq: int, msg: Dict[str, Any], phase: str, depth: int = 0) -> str:
    """One wire message as a <details> block.

    depth=0 outer SIEP session envelope, depth=1 inner SIEP panel, depth=2 CIP repair.
    """
    kind = msg.get("kind", "?")
    subkind = msg.get("subkind") or ""
    sub = msg.get("subprotocol") or "—"
    actor = _actor(msg)
    recips = _recipients(msg)
    msg_id = _msg_id(msg)
    ts = _ts(msg)

    kind_str = kind.upper() + (f":{subkind}" if subkind else "")
    to_str = ", ".join(f"`{r}`" for r in recips) if recips else "_multicast_"
    ts_str = f" {ts}" if ts else ""

    utt = _utterance(msg)
    rat = _rationale(msg)

    is_ack = utt.startswith("received:") or utt.startswith("reaffirm:")

    utt_preview = ""
    if utt and not is_ack:
        utt_preview = f' — "{utt[:90]}"' if len(utt) <= 90 else f' — "{utt[:87]}…"'

    id_str = f"`{msg_id[:8]}`" if msg_id else ""
    depth_prefix = _DEPTH_PREFIX.get(depth, "")
    summary = (
        f"[{seq}]{ts_str} &nbsp;{depth_prefix}<strong>{kind_str}</strong> &nbsp;"
        f"<code>{actor}</code> → {to_str} &nbsp;"
        f"<code>{sub}</code>"
        + (f" &nbsp;{id_str}" if id_str else "")
        + utt_preview
    )

    lines = [f"<details>\n<summary>{summary}</summary>\n\n"]

    if utt:
        lines.append(f"**Utterance:** {utt}\n\n")
    if rat and not is_ack:
        lines.append(f"**Rationale:** {rat}\n\n")

    # payload parts (excluding utterance already shown)
    for part in (msg.get("payload") or []):
        ptype = part.get("type", "?")
        if ptype == "utterance":
            continue
        pcontent = part.get("content")
        if pcontent is None:
            continue
        if ptype == "winning-position" and isinstance(pcontent, dict):
            tp_terms = pcontent.get("team_process_terms")
            if tp_terms and isinstance(tp_terms, dict):
                # TP phase: render governance terms inline
                lines.append("**Agreed governance terms:**\n\n")
                for field in ("session_objective", "debate_format", "contingency_rules",
                              "no_convergence_handling"):
                    val = tp_terms.get(field)
                    if val:
                        label = field.replace("_", " ").title()
                        if isinstance(val, dict):
                            lines.append(f"- **{label}:** {json.dumps(val)}\n")
                        else:
                            lines.append(f"- **{label}:** {val}\n")
                ra = tp_terms.get("role_assignments")
                if ra and isinstance(ra, dict):
                    lines.append("- **Role assignments:**\n")
                    for agent, roles in ra.items():
                        lines.append(f"  - `{agent}`: {', '.join(roles) if isinstance(roles, list) else roles}\n")
                lines.append("\n")
            else:
                # TW/T phase: render winning cause inline
                lc = pcontent.get("likely_cause")
                post = pcontent.get("posterior")
                rat = pcontent.get("rationale") or pcontent.get("reasoning_summary")
                ev = pcontent.get("supporting_evidence") or pcontent.get("addresses_evidence")
                if lc:
                    conf_str = f" (posterior={post:.2f})" if isinstance(post, float) else ""
                    lines.append(f"**Agreed position:** `{lc}`{conf_str}\n\n")
                if rat:
                    lines.append(f"**Rationale:** {rat}\n\n")
                if ev and isinstance(ev, list) and ev:
                    lines.append(f"**Evidence:** {', '.join(str(e) for e in ev[:5])}\n\n")
        elif ptype == "individual-positions" and isinstance(pcontent, dict):
            rows = []
            for agent, pos in pcontent.items():
                short = agent.split("-", 1)[-1] if "-" in agent else agent
                p = pos.get("posterior", "?")
                p_str = f"{p:.2f}" if isinstance(p, float) else str(p)
                position = pos.get("position", "?")
                rows.append(f"  - `{short}`: **{position}** @ {p_str}")
            if rows:
                lines.append("**Individual positions:**\n\n" + "\n".join(rows) + "\n\n")
        elif ptype == "knowledge" and isinstance(pcontent, dict):
            cid = pcontent.get("concept_id", "?")
            value = pcontent.get("value", "")
            value_detail = pcontent.get("value_detail") or {}
            post = pcontent.get("posterior")
            gar = pcontent.get("gar")
            scr = pcontent.get("scr")
            pw = pcontent.get("provenance_weight")
            cause = pcontent.get("revision_cause", "?")
            post_str = f"{post:.4f}" if isinstance(post, float) else str(post)
            gar_str = f"{gar:.4f}" if isinstance(gar, float) else str(gar)
            scr_str = f"{scr:.4f}" if isinstance(scr, float) else str(scr)
            pw_str = f"{pw:.4f}" if isinstance(pw, float) else str(pw)
            value_line = f"value=`{value}`  \n" if value and value != cid.split(":")[-1] else ""
            lines.append(
                f"**Knowledge record:** `{cid}`  \n"
                f"{value_line}"
                f"posterior={post_str} · gar={gar_str} · scr={scr_str} · provenance_weight={pw_str} · cause=`{cause}`\n\n"
            )
            if value_detail:
                lines.append(
                    f"<details><summary><code>value_detail</code></summary>\n\n"
                    + _json_block(value_detail)
                    + "\n</details>\n\n"
                )
        elif isinstance(pcontent, dict):
            # pull rich reasoning fields inline
            for key in ("reasoning_summary", "critique", "thought_summary"):
                val = pcontent.get(key) or (pcontent.get("proposal_payload") or {}).get(key)
                if val:
                    label = key.replace("_", " ").title()
                    lines.append(f"**{label}:** {val}\n\n")
            lines.append(
                f"<details><summary><code>{ptype}</code> payload</summary>\n\n"
                + _json_block(pcontent)
                + "\n\n</details>\n\n"
            )
        elif isinstance(pcontent, (list, bool, int, float)):
            lines.append(f"**`{ptype}`:** `{json.dumps(pcontent)}`\n\n")
        else:
            lines.append(f"**`{ptype}`:** {pcontent}\n\n")

    # epistemic (from context.epistemic)
    ep_block = _epistemic(msg)
    if ep_block:
        ep_str = " · ".join(f"{k}={v}" for k, v in ep_block.items() if v is not None)
        lines.append(f"**Epistemic:** `{ep_str}`\n\n")

    if msg_id:
        eid = _episode_id(msg)
        lines.append(f"**Episode:** `{eid}`  \n**Msg-id:** `{msg_id}`\n\n")

    lines.append("</details>\n\n")
    return "".join(lines)


# ── LLM call block ────────────────────────────────────────────────────────────

def _llm_event(item: Dict[str, Any]) -> str:
    """One LLM call as a <details> block."""
    task = item.get("task", "?")
    agent = item.get("agent_id", "?")
    ts = _ts_llm(item)
    success = item.get("success", True)
    thought = item.get("thought_summary", "")
    request = item.get("request", {})
    response = item.get("response", {})
    error = item.get("error", "")

    status = "✓" if success else "✗"
    ts_str = f" {ts}" if ts else ""
    thought_preview = ""
    if thought:
        thought_preview = f' — "{thought[:80]}"' if len(thought) <= 80 else f' — "{thought[:77]}…"'

    summary = (
        f"🧠 LLM:<strong>{task}</strong>"
        f" &nbsp;<code>{agent}</code>{ts_str} {status}"
        f"{thought_preview}"
    )
    lines = [f"<details>\n<summary>{summary}</summary>\n\n"]

    if not success and error:
        lines.append(f"**Error:** {error}\n\n")

    if thought:
        lines.append(f"**Thought:** {thought}\n\n")

    rationale = response.get("rationale") or response.get("reasoning_summary") or ""
    if rationale and rationale != thought:
        lines.append(f"**Rationale:** {rationale}\n\n")

    if response:
        resp_display = {k: v for k, v in response.items()
                        if k not in ("rationale", "thought_summary")}
        if resp_display:
            lines.append(
                "<details><summary><strong>Response JSON</strong></summary>\n\n"
                + _json_block(resp_display)
                + "\n\n</details>\n\n"
            )

    system_prompt = request.get("system_prompt") or ""
    user_prompt = request.get("user_prompt") or ""
    user_payload = request.get("user_payload") or request.get("payload")
    if system_prompt or user_prompt or user_payload:
        lines.append("<details><summary><strong>Prompt</strong></summary>\n\n")
        if system_prompt:
            lines.append(f"**System:** {system_prompt[:400]}"
                         + (" …_(truncated)_" if len(system_prompt) > 400 else "")
                         + "\n\n")
        if user_prompt:
            lines.append(
                "<details><summary>User prompt</summary>\n\n"
                + f"```\n{user_prompt}\n```\n\n</details>\n\n"
            )
        if user_payload:
            lines.append(
                "<details><summary>Payload</summary>\n\n"
                + _json_block(user_payload)
                + "\n\n</details>\n\n"
            )
        lines.append("</details>\n\n")

    lines.append("</details>\n\n")
    return "".join(lines)


# ── convergence block ─────────────────────────────────────────────────────────

def _render_convergence(ep: Dict[str, Any]) -> str:
    metrics = ep.get("convergence_metrics") or {}
    gar = metrics.get("gar", "?")
    scr = metrics.get("scr", "?")
    mpc = metrics.get("mpc", "?")
    resolution = ep.get("resolution_label", "?")
    cause = ep.get("symptom_conclusion", "?")

    lines = ["## Convergence\n\n"]
    lines.append(f"**Resolution:** `{resolution}` → **`{cause}`**\n\n")
    lines.append("| Metric | Value | Meaning |\n|--------|-------|---------|")
    lines.append(f"\n| GAR | `{gar}` | Genuine agreement ratio — fraction whose belief moved >5% |\n")
    lines.append(f"| SCR | `{scr}` | Social compliance ratio — fraction who rubber-stamped |\n")
    lines.append(f"| MPC | `{mpc}` | Mean posterior confidence across all specialists |\n\n")
    return "".join(lines)


# ── specialist table ──────────────────────────────────────────────────────────

def _render_specialist_table(opinions: List[Dict[str, Any]]) -> str:
    if not opinions:
        return ""
    lines = ["## Specialist Opinions\n\n"]
    lines.append("| Panel | Agent | Cause | Conf | Thought |\n")
    lines.append("|-------|-------|-------|------|---------|\n")
    for op in opinions:
        panel = op.get("panel", "?")
        agent = op.get("specialist_id", "?")
        cause = op.get("likely_cause", "?")
        conf = op.get("confidence") or op.get("posterior") or "?"
        conf_str = f"{conf:.3f}" if isinstance(conf, float) else str(conf)
        thought = op.get("rationale") or op.get("thought_summary") or ""
        lines.append(f"| {panel} | `{agent}` | **{cause}** | {conf_str} | {thought[:80]} |\n")
    lines.append("\n")
    return "".join(lines)


# ── LLM summary ───────────────────────────────────────────────────────────────

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
    lines.append(
        f"| **Total** | **{total}** | **{total - total_failed}** | **{total_failed}** |\n\n"
    )
    return "".join(lines)


# ── LLM queue helpers ─────────────────────────────────────────────────────────

def _build_llm_queues(llm_trace: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    queues: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in llm_trace:
        queues[item.get("agent_id") or "__global__"].append(item)
    return dict(queues)


_PHASE_TASKS: Dict[str, List[str]] = {
    "tp": ["tp_case_frame"],
    "tw": ["diagnostics_assessment", "team_prior_reasoning", "team_prior_commit",
           "grounding_judge"],
    "t":  ["task_accept_or_counter", "debate_accept_or_counter",
           "debate_controller_synthesis", "debate_pivot_synthesis", "grounding_judge"],
}


def _emit_llm_for_actor(
    actor: str,
    phase: str,
    queues: Dict[str, List[Dict[str, Any]]],
    consumed: Dict[str, int],
) -> List[str]:
    """Pop and render any pending LLM calls from actor for the current phase."""
    queue = queues.get(actor, [])
    idx = consumed.get(actor, 0)
    phase_tasks = set(_PHASE_TASKS.get(phase, []) + _PHASE_TASKS.get("t", []))
    result = []
    while idx < len(queue) and queue[idx].get("task") in phase_tasks:
        result.append(_llm_event(queue[idx]))
        idx += 1
    consumed[actor] = idx
    return result


# ── main render ───────────────────────────────────────────────────────────────

def render(result_path: str, output_path: str, patient_filter: Optional[str] = None) -> None:
    with open(result_path) as f:
        data = json.load(f)

    episodes = data.get("episodes", [])
    if not episodes:
        print("No episodes found.", file=sys.stderr)
        sys.exit(1)

    all_out: List[str] = []

    for ep_idx, ep in enumerate(episodes):
        patient_id = ep.get("patient_id", "?")
        if patient_filter and patient_id != patient_filter:
            continue

        episode_urn = ep.get("episode_id", "?")
        cause = ep.get("symptom_conclusion", "?")
        resolution = ep.get("resolution_label", "?")
        metrics = ep.get("convergence_metrics") or {}
        gar = metrics.get("gar", "?")
        scr = metrics.get("scr", "?")
        mpc = metrics.get("mpc", "?")

        wire: List[Dict[str, Any]] = ep.get("trace", [])
        llm_trace: List[Dict[str, Any]] = ep.get("llm_trace", [])
        opinions: List[Dict[str, Any]] = ep.get("specialist_opinions", [])

        today = datetime.date.today().isoformat()
        backend = data.get("llm_backend") or data.get("backend", "?")
        model = data.get("model", "?")

        out: List[str] = []
        if ep_idx > 0:
            out.append("\n\n---\n\n")

        # ── document header ──────────────────────────────────────────────────
        out.append(f"# L9 Interleaved Trace — Patient `{patient_id}`\n\n")
        out.append(
            f"**Patient:** `{patient_id}` · **Outcome:** `{resolution}` · "
            f"**Cause:** `{cause}`  \n"
            f"**Run date:** {today} · **Backend:** {backend} / {model}  \n"
            f"**Episode URN:** `{episode_urn}`  \n\n"
        )
        n_wire = len(wire)
        n_llm = len(llm_trace)
        n_failed = sum(1 for x in llm_trace if not x.get("success", True))
        n_cip = sum(1 for m in wire if m.get("kind") == "contingency")
        out.append("| Metric | Value |\n|--------|-------|\n")
        out.append(f"| Wire messages | {n_wire} |\n")
        out.append(f"| LLM calls | {n_llm} |\n")
        out.append(f"| LLM failed | {n_failed} |\n")
        out.append(f"| CIP contingencies | {n_cip} |\n")
        out.append(f"| GAR / SCR / MPC | {gar} / {scr} / {mpc} |\n\n")
        out.append(_hr())

        # ── patient context ──────────────────────────────────────────────────
        out.append("## Patient Context\n\n")
        rec = ep.get("joint_recommendation", "")
        meds = ep.get("proposed_drug_changes", [])
        if rec:
            out.append(f"**Joint recommendation:** {rec}  \n")
        if meds:
            out.append(f"**Recommended changes:** {', '.join(meds)}  \n")
        out.append("\n")
        out.append(_hr())

        # ── build LLM queues ─────────────────────────────────────────────────
        llm_queues = _build_llm_queues(llm_trace)
        llm_consumed: Dict[str, int] = {}

        # ── chronological walk — all 287+ messages ───────────────────────────
        phased = _assign_phases(wire)
        current_phase = ""
        seq = 1

        for phase, depth, msg in phased:
            # phase header on transition — knowledge doesn't start a new section;
            # it renders inline in the current outer phase.
            render_phase = phase if phase != "knowledge" else current_phase
            if render_phase != current_phase:
                if current_phase:
                    out.append(_hr())
                label = _PHASE_LABELS.get(render_phase, render_phase.upper())
                out.append(f"## Phase: {label}\n\n")
                preamble = _PHASE_PREAMBLES.get(render_phase, "")
                if preamble:
                    out.append(preamble + "\n\n")
                current_phase = render_phase

            actor = _actor(msg)
            kind = msg.get("kind", "")
            utt = _utterance(msg)
            is_ack = utt.startswith("received:") or utt.startswith("reaffirm:")

            # emit pending LLM calls before this agent's substantive wire message
            if not is_ack and kind in ("intent", "exchange", "commit", "contingency"):
                for block in _emit_llm_for_actor(actor, phase, llm_queues, llm_consumed):
                    out.append(block)

            out.append(_wire_event(seq, msg, phase, depth=depth))
            seq += 1

        # emit any LLM calls not yet consumed
        for agent_id, queue in llm_queues.items():
            idx = llm_consumed.get(agent_id, 0)
            for item in queue[idx:]:
                out.append(_llm_event(item))

        out.append(_hr())
        out.append(_render_convergence(ep))
        out.append(_hr())
        out.append(_render_specialist_table(opinions))
        if opinions:
            out.append(_hr())
        out.append(_render_llm_breakdown(llm_trace))

        all_out.extend(out)

    with open(output_path, "w") as f:
        f.write("".join(all_out))

    n_details = sum(1 for s in all_out if s.lstrip().startswith("<details>"))
    print(f"Wrote {output_path}  ({n_details} collapsible blocks, {len(episodes)} episode(s))")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render hcpanel result JSON to interleaved trace markdown"
    )
    parser.add_argument("result", help="Path to run-result JSON")
    parser.add_argument("--output", "-o", default=None,
                        help="Output .md path (default: <result>-trace.md)")
    parser.add_argument("--patient", default=None, help="Filter to a single patient_id")
    parser.add_argument("--combined", action="store_true",
                        help="Render all episodes into one file")
    args = parser.parse_args()

    output = args.output or args.result.replace(".json", "-trace.md")
    render(args.result, output, patient_filter=args.patient)


if __name__ == "__main__":
    main()
