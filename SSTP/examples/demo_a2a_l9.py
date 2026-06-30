# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""L9 messages carried over A2A transport: TFP → SIEP → CIP → SAB

Pipeline for every message
──────────────────────────
  1. BUILD  — Create L9 message with the subprotocol builder
  2. PACK   — Serialize L9 → DataPart(media_type="application/vnd.sstp.l9+json")
  3. SEND   — Put A2A message on the bus (bus.send_l9 / bus.open_l9_task)
  4. RECV   — Receiver calls bus.recv_l9() → reconstituted L9 object

The bus exposes:
    bus.open_l9_task(l9, role, ctx_id)   → (task_id, a2a_msg)  [first message]
    bus.send_l9(task_id, l9, role, ctx_id) → a2a_msg           [subsequent]
    bus.close_l9_task(task_id, l9, role, ctx_id) → a2a_msg     [final message]
    bus.recv_l9(task_id)                 → L9                  [receiver side]

SAB messages use the same pattern via pack_sab / unpack_sab.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any, List, Optional, Tuple

# ── Path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TFP_PY    = _REPO_ROOT / "SSTP/subprotocol/tfp/language_bindings/python"
for _p in [str(_REPO_ROOT), str(_TFP_PY)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── LLM credentials ───────────────────────────────────────────────────────────
def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env(_REPO_ROOT / "SSTP/subprotocol/cip/llm.env")

# ── A2A SDK ───────────────────────────────────────────────────────────────────
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf import struct_pb2

from a2a.types.a2a_pb2 import (
    AgentCard, AgentCapabilities, AgentInterface, AgentSkill,
    Message as A2AMessage, Part, Role, Task, TaskState, TaskStatus,
)
from a2a.helpers.proto_helpers import (
    new_data_part, new_message, new_task_from_user_message, new_text_part,
)
from a2a.helpers.agent_card import display_agent_card

# ── L9 data model ────────────────────────────────────────────────────────────
from ai.outshift.data_model import (
    L9, L9Header, L9Payload, Actor, Context,
    Message as L9Msg, ParticipantSet, Semantic,
)

# ── Subprotocol builders ──────────────────────────────────────────────────────
from ai.outshift.subprotocols.tfp import (
    CandidateOffer, RoleAssignment, SkillClaim, SkillRequirement,
    TaskSpec, TeamSelection, TFPOperation, TFPPayload,
)
from ai.outshift.subprotocols.siep import (
    SIEPMessageBuilder, SIEPPayload, SIEPUtterance, SIEPBelief,
    RevisionCause, SIEPEngine,
)
from ai.outshift.subprotocols.cip import (
    CIPMessageBuilder, CIPPayload, CIPUtterance, CIPBelief,
    CIPGrounding, RepairReason, RevisionCause as CIPRevisionCause,
    CIPEngineConfig, CIPProcessor,
)
from ai.outshift.subprotocols.sab import (
    SAB, SABHeader, SABPayload, SABActors, SABAttributes, SABOrigin,
    SABIntentPayloadData, SABNegotiatePayloadData, SABCommitPayloadData,
    NegotiateSemanticContext, NegotiateCommitSemanticContext, SemanticContext,
    SAOState, SAOResponse, SAONMI, Outcome, ResponseType,
    Kind as SABKind, Subkind as SABSubkind,
)

# ── Episode constants ─────────────────────────────────────────────────────────
C_SCOPE    = "concept:material_breach"
C_TIMELINE = "concept:substantial_performance"
C_CRITERIA = "concept:sla_breach_threshold"

ISSUES  = ["governing_interpretation", "damages_cap"]
OPTIONS = {"governing_interpretation": ["us_standard", "uk_standard", "hybrid"],
           "damages_cap": ["6_months_fees", "12_months_fees", "24_months_fees"]}
N_OUTCOMES = len(OPTIONS["governing_interpretation"]) * len(OPTIONS["damages_cap"])

MEDIA_L9  = "application/vnd.sstp.l9+json"
MEDIA_SAB = "application/vnd.sstp.sab+json"
_W        = 100

_SYS_COMMERCIAL = (
    "You are commercial-agent, a commercial law AI specializing in SaaS enterprise "
    "agreements, contract-law material breach standards, and GDPR compliance. "
    "Respond in 1–2 sentences. No markdown."
)
_SYS_LIABILITY = (
    "You are liability-agent, an indemnity and damages specialist focused on "
    "consequential damages clauses, SLA breach thresholds, and cross-jurisdiction "
    "indemnity analysis. Respond in 1–2 sentences. No markdown."
)

EpisodeLog = List[Tuple[str, str, A2AMessage]]


# ─────────────────────────────────────────────────────────────────────────────
# LLM helper
# ─────────────────────────────────────────────────────────────────────────────

def _llm(agent: str, system: str, user: str, fallback: str) -> str:
    """Call LLM; falls back to `fallback` on error."""
    try:
        import litellm  # type: ignore
        model    = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        base_url = os.environ.get("LLM_API_BASE") or os.environ.get("LLM_BASE_URL") or None
        api_key  = os.environ.get("LLM_API_KEY") or None
        if base_url and not model.startswith("openai/"):
            model = f"openai/{model}"
        kw: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user}],
            "temperature": 0.4,
        }
        if api_key:  kw["api_key"]  = api_key
        if base_url: kw["base_url"] = base_url
        print(f"  [LLM] → agent={agent}  model={model}")
        resp = litellm.completion(**kw)
        text = (resp.choices[0].message.content or "").strip()
        print(f"  [LLM] ← {text[:120]}")
        return text or fallback
    except Exception as exc:
        print(f"  [LLM] ✗ {agent}: {exc}")
        return fallback


# ─────────────────────────────────────────────────────────────────────────────
# PACK / UNPACK  (L9 ↔ A2A DataPart)
# ─────────────────────────────────────────────────────────────────────────────

def pack_l9(l9: L9) -> Part:
    """Serialize L9 → A2A DataPart (media_type=application/vnd.sstp.l9+json).

    L9.model_dump_json()  →  JSON dict
    ParseDict(dict, struct_pb2.Value())  →  protobuf Value stored in Part.data
    """
    return new_data_part(json.loads(l9.model_dump_json()), media_type=MEDIA_L9)


def unpack_l9(part: Part) -> L9:
    """Reconstitute L9 from an A2A DataPart.

    MessageToDict(part.data)  →  dict
    L9.model_validate(dict)   →  L9 object
    """
    if part.media_type != MEDIA_L9:
        raise ValueError(f"Expected media_type={MEDIA_L9!r}, got {part.media_type!r}")
    return L9.model_validate(MessageToDict(part.data))


def pack_sab(sab: SAB) -> Part:
    """Serialize SAB → A2A DataPart (media_type=application/vnd.sstp.sab+json)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return new_data_part(sab.model_dump(mode="json"), media_type=MEDIA_SAB)


def unpack_sab(part: Part) -> SAB:
    """Reconstitute SAB from an A2A DataPart."""
    if part.media_type != MEDIA_SAB:
        raise ValueError(f"Expected media_type={MEDIA_SAB!r}, got {part.media_type!r}")
    return SAB.model_validate(MessageToDict(part.data))


def _find_part(msg: A2AMessage, media: str) -> Optional[Part]:
    return next((p for p in msg.parts if p.media_type == media), None)


def _envelope_label(l9: L9) -> str:
    kind = l9.header.kind.value + (f":{l9.header.subkind}" if l9.header.subkind else "")
    return f"L9/{l9.header.subprotocol}/{kind}"


def _sab_label(sab: SAB) -> str:
    kind = sab.header.kind.value + (f":{sab.header.subkind.value}" if sab.header.subkind else "")
    return f"L9/SAB/{kind}"


# ─────────────────────────────────────────────────────────────────────────────
# A2A BUS  (L9-aware)
# ─────────────────────────────────────────────────────────────────────────────

class A2ABus:
    """In-process A2A bus with L9-aware send/receive helpers.

    L9 pipeline per message:
      1. BUILD  (caller)                  → L9 object
      2. PACK   (bus.open/send/close_l9)  → A2A Message wrapping L9 DataPart
      3. SEND   (bus.open/send/close_l9)  → persisted in task history
      4. RECV   (bus.recv_l9)             → reconstituted L9 via unpack_l9
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        self._cards[card.name] = card

    # ── L9 pipeline ──────────────────────────────────────────────────────────

    def open_l9_task(self, l9: L9, role: Role, ctx_id: str) -> tuple[str, A2AMessage]:
        """STEP 2+3: Pack L9 → A2A and open a new task.  Returns (task_id, a2a_msg)."""
        task_id = str(uuid.uuid4())
        a2a     = new_message(
            parts=[new_text_part(_envelope_label(l9)), pack_l9(l9)],
            role=role, task_id=task_id, context_id=ctx_id,
        )
        self._tasks[task_id] = new_task_from_user_message(a2a)
        return task_id, a2a

    def send_l9(self, task_id: str, l9: L9, role: Role, ctx_id: str) -> A2AMessage:
        """STEP 2+3: Pack L9 → A2A and append to existing task."""
        a2a = new_message(
            parts=[new_text_part(_envelope_label(l9)), pack_l9(l9)],
            role=role, task_id=task_id, context_id=ctx_id,
        )
        task = self._tasks[task_id]
        task.history.append(a2a)
        task.status.state = TaskState.TASK_STATE_WORKING
        return a2a

    def close_l9_task(self, task_id: str, l9: L9, role: Role, ctx_id: str) -> A2AMessage:
        """STEP 2+3: Pack L9 → A2A, append, and mark task COMPLETED."""
        a2a = self.send_l9(task_id, l9, role, ctx_id)
        self._tasks[task_id].status.state = TaskState.TASK_STATE_COMPLETED
        return a2a

    def recv_l9(self, task_id: str) -> L9:
        """STEP 4: Extract and reconstitute L9 from the last message on the task."""
        last = self._tasks[task_id].history[-1]
        part = _find_part(last, MEDIA_L9)
        if part is None:
            raise ValueError(f"No L9 part found in last message of task {task_id!r}")
        return unpack_l9(part)

    # ── SAB pipeline (same pattern, SAB type) ─────────────────────────────────

    def open_sab_task(self, sab: SAB, role: Role, ctx_id: str) -> tuple[str, A2AMessage]:
        task_id = str(uuid.uuid4())
        a2a     = new_message(
            parts=[new_text_part(_sab_label(sab)), pack_sab(sab)],
            role=role, task_id=task_id, context_id=ctx_id,
        )
        self._tasks[task_id] = new_task_from_user_message(a2a)
        return task_id, a2a

    def send_sab(self, task_id: str, sab: SAB, role: Role, ctx_id: str) -> A2AMessage:
        a2a = new_message(
            parts=[new_text_part(_sab_label(sab)), pack_sab(sab)],
            role=role, task_id=task_id, context_id=ctx_id,
        )
        task = self._tasks[task_id]
        task.history.append(a2a)
        task.status.state = TaskState.TASK_STATE_WORKING
        return a2a

    def close_sab_task(self, task_id: str, sab: SAB, role: Role, ctx_id: str) -> A2AMessage:
        a2a = self.send_sab(task_id, sab, role, ctx_id)
        self._tasks[task_id].status.state = TaskState.TASK_STATE_COMPLETED
        return a2a

    def recv_sab(self, task_id: str) -> SAB:
        last = self._tasks[task_id].history[-1]
        part = _find_part(last, MEDIA_SAB)
        if part is None:
            raise ValueError(f"No SAB part found in last message of task {task_id!r}")
        return unpack_sab(part)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())


# ─────────────────────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hr(char: str = "─") -> None:
    print(char * _W)


def _print_pipeline(phase: str, step: str, a2a: A2AMessage, note: str = "") -> None:
    """Show the full pipeline: A2A message parts + reconstituted L9(header+payload)/SAB."""
    role_str = Role.Name(a2a.role).replace("ROLE_", "").lower()
    l9_part  = _find_part(a2a, MEDIA_L9)
    sab_part = _find_part(a2a, MEDIA_SAB)

    # Extract kind/subkind/sender up front for the header line
    _kind_str = "—"
    _sender   = "—"
    if l9_part:
        _l9 = unpack_l9(l9_part)
        _h  = _l9.header
        _kind_str = _h.kind.value + (f":{_h.subkind}" if _h.subkind else "")
        _sender   = _h.participants.actors[0].id if (_h.participants and _h.participants.actors) else "?"
    elif sab_part:
        _sab = unpack_sab(sab_part)
        _h   = _sab.header
        _kind_str = _h.kind.value + (f":{_h.subkind.value}" if _h.subkind else "")
        _sender   = _h.participants.actors[0].id if (_h.participants and _h.participants.actors) else "?"

    _hr()
    print(f"  [{phase}]  {step}  kind={_kind_str}  actor={_sender}")
    if note:
        print(f"  note : {note}")

    # ── ② A2A Message ─────────────────────────────────────────────────────────
    print(f"  ② A2A Message")
    print(f"       msg_id   = {a2a.message_id[:8]}\u2026")
    print(f"       role     = {role_str}")
    print(f"       task_id  = {a2a.task_id[:8]}\u2026")
    print(f"       parts    = {len(a2a.parts)}")
    for i, part in enumerate(a2a.parts):
        if part.HasField("text"):
            print(f"       part[{i}] TextPart")
            print(f"               .text       = \"{part.text[:70]}\"")
        elif part.HasField("data"):
            raw_keys = list(MessageToDict(part.data).keys())
            print(f"       part[{i}] DataPart")
            print(f"               .media_type = \"{part.media_type}\"")
            print(f"               .data       = struct_pb2.Value  keys={raw_keys}")

    # ── ④ Reconstituted L9  (L9Header + L9Payload) ────────────────────────────
    if l9_part:
        l9      = unpack_l9(l9_part)
        h       = l9.header
        actors  = h.participants.actors if h.participants else []
        sender  = actors[0].id if actors else "?"
        recvrs  = [a.id for a in actors[1:]]
        parents = h.message.parents or []
        kind_str = h.kind.value + (f":{h.subkind}" if h.subkind else "")

        print(f"  ④ L9 = L9Header + L9Payload  (unpacked from part[1])")
        print(f"     \u250c\u2500 L9Header")
        print(f"     \u2502   .protocol    = {h.protocol}")
        print(f"     \u2502   .subprotocol = {h.subprotocol}")
        print(f"     \u2502   .version     = {h.version}")
        print(f"     \u2502   .kind        = {kind_str}")
        print(f"     \u2502   .message.id      = {h.message.id[:8]}\u2026")
        print(f"     \u2502   .message.episode = \u2026{h.message.episode[-28:]}")
        print(f"     \u2502   .message.parents = {[p[:8]+chr(8230) for p in parents] or '[]'}")
        print(f"     \u2502   .participants.sender    = {sender}")
        if recvrs:
            print(f"     \u2502   .participants.receivers = {recvrs}")
        if h.context:
            print(f"     \u2502   .context.topic = {(h.context.topic or '\u2014')[:65]}")
        print(f"     \u2514\u2500 L9Payload")
        if l9.payload:
            print(f"         .type = {l9.payload.type}")
            d = l9.payload.data or {}
            if isinstance(d, dict):
                if "operation" in d:
                    print(f"         .data.operation = {d['operation']}")
                if d.get("reason"):
                    print(f"         .data.reason    = \"{str(d['reason'])[:80]}\"")
                utt = d.get("utterance") or {}
                if isinstance(utt, dict) and utt:
                    print(f"         .data.utterance.text     = \"{(utt.get('text') or '')[:80]}\"")
                    if utt.get("evidence"):
                        print(f"         .data.utterance.evidence = {utt['evidence']}")
                    if utt.get("addresses_evidence"):
                        print(f"         .data.utterance.addresses_evidence = {utt['addresses_evidence']}")
                bel = d.get("belief") or {}
                if isinstance(bel, dict) and bel:
                    print(f"         .data.belief.prior          = {bel.get('prior')}")
                    print(f"         .data.belief.posterior      = {bel.get('posterior')}")
                    print(f"         .data.belief.revision_cause = {bel.get('revision_cause', '\u2014')}")
                grd = d.get("grounding") or {}
                if isinstance(grd, dict) and grd:
                    print(f"         .data.grounding.repair_reason     = {grd.get('repair_reason')}")
                    print(f"         .data.grounding.contingency_score = {grd.get('contingency_score')}")
        print(f"     \u2713 unpack_l9(part[1]) \u2192 L9.model_validate(MessageToDict(part.data))")

    # ── ④ Reconstituted SAB ───────────────────────────────────────────────────
    elif sab_part:
        sab      = unpack_sab(sab_part)
        h        = sab.header
        actors   = h.participants.actors if h.participants else []
        sender   = actors[0].id if actors else "?"
        receiver = actors[1].id if len(actors) > 1 else "\u2014"
        kind_str = h.kind.value + (f":{h.subkind.value}" if h.subkind else "")
        d        = sab.payload.data if sab.payload else None

        print(f"  ④ SAB = SABHeader + SABPayload  (unpacked from part[1])")
        print(f"     \u250c\u2500 SABHeader")
        print(f"     \u2502   .subprotocol = {h.subprotocol}")
        print(f"     \u2502   .kind        = {kind_str}")
        print(f"     \u2502   .message.id  = {h.message.id[:8]}\u2026")
        print(f"     \u2502   .participants.sender   = {sender}")
        print(f"     \u2502   .participants.receiver = {receiver}")
        print(f"     \u2514\u2500 SABPayload")
        if d and hasattr(d, "semantic_context"):
            sc = d.semantic_context
            if hasattr(sc, "sao_state") and sc.sao_state:
                st = sc.sao_state
                print(f"         .data.sao_state.step     = {st.step}")
                print(f"         .data.sao_state.proposer = {st.current_proposer}")
                if st.current_offer:
                    for k, v in st.current_offer.items():
                        print(f"         .data.current_offer.{k} = {v}")
        print(f"     \u2713 unpack_sab(part[1]) \u2192 SAB.model_validate(MessageToDict(part.data))")


def _print_summary(log: EpisodeLog) -> None:
    _hr("═")
    print("  A2A + L9 EPISODE SUMMARY")
    _hr("═")
    for phase, label, _ in log:
        print(f"  [{phase:<4}]  {label}")
    _hr("═")
    print(f"  Total messages: {len(log)}")
    _hr("═")


def _a2a_msg_to_dict(msg: A2AMessage) -> dict:
    """Convert an A2A Message proto to a JSON-serialisable dict that also
    includes the decoded L9/SAB payload for each DataPart."""
    d = MessageToDict(msg, preserving_proto_field_name=True)
    parts_out = []
    for part in msg.parts:
        pd: dict = {}
        if part.HasField("text"):
            pd = {"type": "text", "text": part.text}
        elif part.HasField("data"):
            raw = MessageToDict(part.data)
            decoded: Optional[dict] = None
            if part.media_type == MEDIA_L9:
                try:
                    l9 = unpack_l9(part)
                    decoded = json.loads(l9.model_dump_json())
                except Exception:
                    pass
            elif part.media_type == MEDIA_SAB:
                try:
                    sab = unpack_sab(part)
                    decoded = sab.model_dump(mode="json")
                except Exception:
                    pass
            pd = {
                "type": "data",
                "media_type": part.media_type,
                "raw_proto": raw,
                "decoded_l9_or_sab": decoded,
            }
        elif part.HasField("raw"):
            pd = {"type": "raw", "bytes_len": len(part.raw)}
        else:
            pd = {"type": "url", "url": part.url}
        parts_out.append(pd)
    d["parts"] = parts_out
    return d


def _save_json(log: EpisodeLog, bus: A2ABus) -> None:
    """Save two artefacts:
    - demo_a2a_l9_messages.json — per-message list with decoded L9 + raw A2A proto
    - demo_a2a_l9_tasks.json   — full task objects as returned by bus.list_tasks()
    """
    out_dir = Path(__file__).resolve().parent

    # ── 1. per-message log (phase, label, full A2A + decoded L9) ──────────────
    messages_out = []
    for phase, label, a2a in log:
        messages_out.append({
            "phase": phase,
            "label": label,
            "a2a_message": _a2a_msg_to_dict(a2a),
        })
    msg_path = out_dir / "demo_a2a_l9_messages.json"
    msg_path.write_text(json.dumps({"episode_messages": messages_out}, indent=2))
    print(f"\n  JSON (messages) → {msg_path}")

    # ── 2. full task dump ──────────────────────────────────────────────────────
    tasks_out = {"tasks": [MessageToDict(t, preserving_proto_field_name=True)
                           for t in bus.list_tasks()]}
    task_path = out_dir / "demo_a2a_l9_tasks.json"
    task_path.write_text(json.dumps(tasks_out, indent=2))
    print(f"  JSON (tasks)    → {task_path}")


# ─────────────────────────────────────────────────────────────────────────────
# TFP L9 message helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tfp(episode: str, sender: str, receivers: List[str],
         kind: str, subkind: str, payload: TFPPayload,
         parent_id: Optional[str] = None, topic: Optional[str] = None) -> L9:
    actors = [Actor(id=sender, role="sender", attestation=None)] + [
        Actor(id=r, role="receiver", attestation=None)
        for r in receivers if not r.startswith("topic:")
    ]
    return L9(
        header=L9Header(
            protocol="SSTP", subprotocol="TFP", version="0",
            kind=kind, subkind=subkind,
            participants=ParticipantSet(actors=actors, groups=None),
            message=L9Msg(id=str(uuid.uuid4()),
                          parents=[parent_id] if parent_id else [],
                          episode=episode),
            context=Context(topic=topic or ""),
        ),
        payload=L9Payload(type="json-schema",
                          data=payload.model_dump(exclude_none=True)),
    )


def _tfp_fit(reqs: List[SkillRequirement], offer: CandidateOffer) -> float:
    total_w = sum(r.weight for r in reqs) or 1.0
    return round(sum(
        r.weight * max(
            (c.proficiency for c in offer.skills
             if c.skill == r.skill and c.proficiency >= r.min_proficiency),
            default=0.0)
        for r in reqs) / total_w, 4)


def _tfp_select(reqs: List[SkillRequirement],
                bids: dict[str, CandidateOffer]) -> TeamSelection:
    mandatory = [r for r in reqs if r.mandatory]
    members: List[str] = []
    roles:   List[RoleAssignment] = []
    covered: set[str] = set()
    for r in mandatory:
        if r.skill in covered:
            continue
        best = max(
            (a for a, o in bids.items()
             if any(c.skill == r.skill and c.proficiency >= r.min_proficiency
                    for c in o.skills)),
            key=lambda a: max(
                (c.proficiency for c in bids[a].skills if c.skill == r.skill),
                default=0.0),
            default=None)
        if best is None:
            continue
        owned = sorted(rr.skill for rr in reqs
                       if any(c.skill == rr.skill for c in bids[best].skills))
        covered.update(owned)
        if best not in members:
            members.append(best)
            roles.append(RoleAssignment(agent_id=best, role="contributor",
                                        responsible_for=owned))
    unmet    = [r.skill for r in mandatory if r.skill not in covered]
    coverage = round((len(mandatory) - len(unmet)) / max(len(mandatory), 1), 4)
    agg_fit  = round(
        sum(_tfp_fit(reqs, bids[m]) for m in members) / max(len(members), 1), 4
    ) if members else 0.0
    return TeamSelection(members=members, roles=roles, coverage=coverage,
                         unmet_skills=unmet, aggregate_fit=agg_fit)


# ─────────────────────────────────────────────────────────────────────────────
# Agent cards
# ─────────────────────────────────────────────────────────────────────────────

def _make_cards() -> tuple[AgentCard, AgentCard]:
    def _card(name: str, desc: str, url: str,
              skills: list[tuple[str, str, str]]) -> AgentCard:
        return AgentCard(
            name=name, description=desc, version="1.0",
            capabilities=AgentCapabilities(streaming=False),
            supported_interfaces=[AgentInterface(
                url=url, protocol_binding="A2A", protocol_version="1.1")],
            default_input_modes=[MEDIA_L9],
            default_output_modes=[MEDIA_L9],
            skills=[AgentSkill(id=sid, name=sname, description=sdesc, tags=[])
                    for sid, sname, sdesc in skills],
        )
    alpha = _card(
        "commercial-agent",
        "Lead agent: contract law, GDPR compliance, team coordination.",
        "a2a://agent-alpha",
        [("contract_law",    "Contract Law",    "Material breach standards."),
         ("gdpr_compliance", "GDPR Compliance", "GDPR/CCPA data processing.")],
    )
    beta = _card(
        "liability-agent",
        "Participant: indemnity analysis, damages scope specialist.",
        "a2a://agent-beta",
        [("indemnity_analysis", "Indemnity Analysis",
          "Indemnity and consequential damages.")],
    )
    return alpha, beta


# ─────────────────────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────────────────────

def run_demo() -> None:  # noqa: C901
    bus = A2ABus()
    alpha_card, beta_card = _make_cards()
    bus.register(alpha_card)
    bus.register(beta_card)

    log: EpisodeLog = []
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    ctx_id  = str(uuid.uuid4())

    def rec(phase: str, label: str, a2a: A2AMessage, note: str = "") -> A2AMessage:
        log.append((phase, label, a2a))
        _print_pipeline(phase, label, a2a, note)
        return a2a

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1  TFP — Team Formation
    # ─────────────────────────────────────────────────────────────────────────
    _hr("═")
    print("  STEP 1 — TFP   (Team Formation via Polling)")
    _hr("═")

    poll_id  = f"urn:ioc:tfp:poll:{uuid.uuid4().hex[:8]}"
    task_spec = TaskSpec(
        task_id="task:saas-contract-review",
        description="Review cross-jurisdiction SaaS enterprise agreement",
        objective="Align on material breach definition then resolve damages scope",
    )
    required = [
        SkillRequirement(skill="skill:contract_law",       min_proficiency=0.8, weight=2.0, mandatory=True),
        SkillRequirement(skill="skill:indemnity_analysis", min_proficiency=0.7, weight=1.5, mandatory=True),
        SkillRequirement(skill="skill:gdpr_compliance",    min_proficiency=0.6, weight=1.0, mandatory=False),
    ]
    tf_topic = f"Forming a team to {task_spec.description}"

    # 1a  ① BUILD L9 → ②③ PACK+SEND via bus.open_l9_task
    l9 = _tfp(episode, "commercial-agent", ["topic:tfp/polls"], "intent", "team-formation",
               TFPPayload(operation=TFPOperation.POLL_OPEN, poll_id=poll_id,
                          task=task_spec, required_skills=required,
                          reasoning_summary="Need contract_law + indemnity + GDPR for cross-jurisdiction SaaS review."),
               topic=tf_topic)
    poll_parent = l9.header.message.id
    tfp_task_id, a2a = bus.open_l9_task(l9, Role.ROLE_USER, ctx_id)  # ②③
    rec("TFP", "1a · POLL_OPEN  (commercial-agent opens poll)", a2a)
    # ④ RECV
    _ = bus.recv_l9(tfp_task_id)  # downstream agents would process this

    # 1b–1c  BIDs
    alpha_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:contract_law",    proficiency=0.92),
                SkillClaim(skill="skill:gdpr_compliance", proficiency=0.80)],
        availability=0.9, fit_score=0.88)
    beta_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:indemnity_analysis", proficiency=0.88),
                SkillClaim(skill="skill:contract_law",       proficiency=0.72)],
        availability=0.8, fit_score=0.75)

    for sender, offer in [("commercial-agent", alpha_offer), ("liability-agent", beta_offer)]:
        tag  = "1b" if sender == "commercial-agent" else "1c"
        # ① BUILD
        l9   = _tfp(episode, sender, ["commercial-agent"], "exchange", "team-formation",
                    TFPPayload(operation=TFPOperation.BID, poll_id=poll_id, offer=offer,
                               reasoning_summary=f"fit≈{_tfp_fit(required, offer)}"),
                    parent_id=poll_parent, topic=tf_topic)
        # ②③ PACK + SEND
        a2a  = bus.send_l9(tfp_task_id, l9, Role.ROLE_AGENT, ctx_id)
        rec("TFP", f"{tag} · BID  ({sender} bids)", a2a)
        # ④ RECV
        _ = bus.recv_l9(tfp_task_id)

    # 1d  SELECT
    bids      = {"commercial-agent": alpha_offer, "liability-agent": beta_offer}
    selection = _tfp_select(required, bids)
    # ① BUILD
    l9  = _tfp(episode, "commercial-agent", selection.members, "exchange", "team-formation",
               TFPPayload(operation=TFPOperation.SELECT, poll_id=poll_id, selection=selection,
                          reasoning_summary=f"coverage={selection.coverage} fit={selection.aggregate_fit}"),
               parent_id=poll_parent, topic=tf_topic)
    # ②③ PACK + SEND
    a2a = bus.send_l9(tfp_task_id, l9, Role.ROLE_AGENT, ctx_id)
    rec("TFP", "1d · SELECT  (commercial-agent selects team)", a2a,
        f"team={selection.members}  coverage={selection.coverage}")
    # ④ RECV
    _ = bus.recv_l9(tfp_task_id)

    # 1e–1f  ACCEPTs — LLM
    for sender, sys_p, user_p, fallback in [
        ("commercial-agent", _SYS_COMMERCIAL,
         "You joined a cross-jurisdiction SaaS review team. Confirm acceptance, state your expertise.",
         "Contract law and GDPR expertise confirmed; joining review team."),
        ("liability-agent", _SYS_LIABILITY,
         "You joined a cross-jurisdiction SaaS review team. Confirm acceptance, state your expertise.",
         "Indemnity and damages analysis skills ready; joining review team."),
    ]:
        tag = "1e" if sender == "commercial-agent" else "1f"
        # ① BUILD L9 (with LLM-generated reason)
        l9  = _tfp(episode, sender, ["commercial-agent"], "exchange", "team-formation",
                   TFPPayload(operation=TFPOperation.ACCEPT, poll_id=poll_id,
                              reason=_llm(sender, sys_p, user_p, fallback)),
                   parent_id=poll_parent, topic=tf_topic)
        # ②③ PACK + SEND
        a2a = bus.send_l9(tfp_task_id, l9, Role.ROLE_AGENT, ctx_id)
        rec("TFP", f"{tag} · ACCEPT  ({sender} accepts)", a2a)
        # ④ RECV
        _ = bus.recv_l9(tfp_task_id)

    # 1g  commit:converged
    # ① BUILD
    l9  = _tfp(episode, "commercial-agent", ["topic:tfp/polls"], "commit", "converged",
               TFPPayload(operation=TFPOperation.FORM_CONVERGED, poll_id=poll_id,
                          selection=selection,
                          reasoning_summary=f"Team formed: {selection.members}"),
               parent_id=poll_parent, topic=tf_topic)
    # ②③ PACK + SEND (close task)
    a2a = bus.close_l9_task(tfp_task_id, l9, Role.ROLE_AGENT, ctx_id)
    rec("TFP", "1g · commit:converged  (team formed ✓)", a2a)
    # ④ RECV
    _ = bus.recv_l9(tfp_task_id)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2  SIEP — Legal Standard Alignment
    # ─────────────────────────────────────────────────────────────────────────
    _hr("═")
    print('  STEP 2 — SIEP  (Legal Standard Alignment: aligning on "material breach")')
    _hr("═")

    siep_engine = SIEPEngine("commercial-agent", episode)

    def _siep(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    # 2a  intent
    # ① BUILD
    l9_intent = _siep("commercial-agent").to("liability-agent").intent().team_process().concept(C_SCOPE).build()
    # ②③ PACK + SEND
    siep_task_id, a2a = bus.open_l9_task(l9_intent, Role.ROLE_USER, ctx_id)
    rec("SIEP", "2a · intent  (commercial-agent opens alignment session)", a2a)
    # ④ RECV → protocol engine
    siep_engine.process(bus.recv_l9(siep_task_id))

    # 2b  commercial-agent aligns — LLM
    # ① BUILD L9 (with LLM-generated utterance)
    l9 = (_siep("commercial-agent")
          .to("liability-agent")
          .exchange().taskwork().asserted().concept(C_SCOPE)
          .parents(l9_intent.header.message.id)
          .payload(SIEPPayload(
              utterance=SIEPUtterance(
                  text=_llm("commercial-agent", _SYS_COMMERCIAL,
                             f"Alignment session on '{C_SCOPE}'. Confirm contract-law material breach standard, citing SLA uptime clause 14.2.",
                             f"Confirmed: {C_SCOPE} — SLA uptime clause 14.2 breach satisfies the contract-law material breach threshold."),
                  evidence=[C_SCOPE, C_CRITERIA]),
              belief=SIEPBelief(prior=0.80, posterior=0.80,
                                revision_cause=RevisionCause.semantic_memory),
          )).build())
    # ②③ PACK + SEND
    a2a = bus.send_l9(siep_task_id, l9, Role.ROLE_AGENT, ctx_id)
    rec("SIEP", "2b · exchange  (commercial-agent aligns on material breach)", a2a)
    # ④ RECV → protocol engine
    siep_engine.process(bus.recv_l9(siep_task_id))

    # 2c  liability-agent drifts — LLM
    # ① BUILD L9 (with LLM-generated drift utterance)
    l9_drift = (_siep("liability-agent")
                .to("commercial-agent")
                .exchange().taskwork().asserted().concept(C_TIMELINE)
                .parents(l9_intent.header.message.id)
                .payload(SIEPPayload(
                    utterance=SIEPUtterance(
                        text=_llm("liability-agent", _SYS_LIABILITY,
                                  f"Alignment session on 'material breach' but you mistakenly apply tort doctrine '{C_TIMELINE}'. "
                                  "Express your (wrong) belief citing a performance timeline.",
                                  f"My analysis aligns on {C_TIMELINE}: vendor's 3-week delivery constitutes substantial performance under tort doctrine."),
                        evidence=[C_TIMELINE]),
                    belief=SIEPBelief(prior=0.60, posterior=0.60,
                                      revision_cause=RevisionCause.semantic_memory),
                )).build())
    # ②③ PACK + SEND
    a2a = bus.send_l9(siep_task_id, l9_drift, Role.ROLE_AGENT, ctx_id)
    rec("SIEP", "2c · exchange  (liability-agent drifts to tort doctrine ⚠)", a2a,
        f"⚠ mismatch: '{C_TIMELINE}' (tort) ≠ '{C_SCOPE}' (contract-law) → escalate to CIP")
    # ④ RECV → protocol engine (detects mismatch)
    siep_engine.process(bus.recv_l9(siep_task_id))

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3  CIP — Contingency Repair
    # ─────────────────────────────────────────────────────────────────────────
    _hr("═")
    print("  STEP 3 — CIP   (Contingency Repair: doctrine mismatch on liability-agent)")
    _hr("═")

    cip_episode = f"urn:ioc:cip:{uuid.uuid4()}"
    cip_proc    = CIPProcessor("repair-cognition-engine", cip_episode, CIPEngineConfig(
        derailment_causes={
            "scope_mismatch":    ["{listener}, your reply applied the wrong legal doctrine."],
            "alignment_failure": ["{listener}, your reply did not engage the agreed legal standard."],
        },
        nonsense_derailment_causes=set(),
        repair_utterances={
            "repair_hard_stop":      "{listener}, stop — restate only under the contract-law material breach standard.",
            "repair_anchor":         "{listener}, re-anchor on the contract-law material breach definition.",
            "repair_alignment":      "{listener}, restate within the agreed operative legal standard.",
            "request_clarification": "{listener}, clarify how your reply addresses material breach under contract law.",
            "default":               "{listener}, remain within the contract-law material breach standard.",
        },
        normal_utterance_template="{listener}, continue within the shared contract-law material breach standard.",
    ))

    def _cip(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(cip_episode, sender)

    # 3a  commercial-agent raises contingency
    # ① BUILD
    l9_req = (_cip("commercial-agent")
              .to("liability-agent")
              .contingency().grounding().challenged().concept(C_SCOPE)
              .parents(l9_drift.header.message.id)
              .payload(CIPPayload(grounding=CIPGrounding(
                  contingency_verified=False, contingency_score=0.0,
                  repair_reason=RepairReason.scope_mismatch,
                  challenges=[C_SCOPE, C_CRITERIA])))
              .text("repair_required:reason=scope_mismatch:target=liability-agent")
              .build())
    # ②③ PACK + SEND
    cip_task_id, a2a = bus.open_l9_task(l9_req, Role.ROLE_USER, ctx_id)
    rec("CIP", "3a · contingency  (commercial-agent raises repair request)", a2a)
    # ④ RECV → repair-cognition-engine processes
    l9_recv = bus.recv_l9(cip_task_id)

    # repair-cognition-engine: ① BUILD repair guidance (LLM via CIPProcessor)
    l9_guidance = cip_proc.process(l9_recv)[0]
    guidance_text = (l9_guidance.payload.data or {}).get("utterance", {}).get("text", "") if l9_guidance.payload else ""
    # ②③ PACK + SEND
    a2a = bus.send_l9(cip_task_id, l9_guidance, Role.ROLE_AGENT, ctx_id)
    rec("CIP", "3b · repair_guidance  (repair-cognition-engine issues hard-stop — LLM)", a2a,
        "repair-cognition-engine")
    # ④ RECV → liability-agent receives guidance
    _ = bus.recv_l9(cip_task_id)

    # 3c  liability-agent re-anchors — LLM
    # ① BUILD L9 (informed by guidance_text from 3b)
    l9_reanchor = (_cip("liability-agent")
                   .to("repair-cognition-engine")
                   .contingency().grounding().revised().concept(C_SCOPE)
                   .parents(l9_guidance.header.message.id)
                   .payload(CIPPayload(
                       utterance=CIPUtterance(
                           text=_llm("liability-agent", _SYS_LIABILITY,
                                     f"Repair instruction: \"{guidance_text}\"\n"
                                     f"Re-anchor on {C_SCOPE} (contract law), set aside tort. Reference SLA clause 14.2.",
                                     f"Re-anchoring on {C_SCOPE}: SLA clause 14.2 breach is material breach under contract law. Tort doctrine set aside."),
                           evidence=[C_SCOPE, C_CRITERIA],
                           addresses_evidence=[C_SCOPE, C_CRITERIA],
                           repair_depth=1),
                       belief=CIPBelief(prior=0.68, posterior=0.75,
                                        revision_cause=CIPRevisionCause.repair_resolution)))
                   .text("Re-anchoring on contract-law material breach.")
                   .build())
    # ②③ PACK + SEND
    a2a = bus.send_l9(cip_task_id, l9_reanchor, Role.ROLE_AGENT, ctx_id)
    rec("CIP", "3c · contingency_response  (liability-agent re-anchors)", a2a)
    # ④ RECV → repair-cognition-engine processes
    l9_recv = bus.recv_l9(cip_task_id)

    # repair-cognition-engine: ① BUILD commit:resolved (LLM via CIPProcessor)
    l9_resolved = cip_proc.process(l9_recv)[0]
    # ②③ PACK + SEND (close task)
    a2a = bus.close_l9_task(cip_task_id, l9_resolved, Role.ROLE_AGENT, ctx_id)
    rec("CIP", "3d · commit:resolved  (repair-cognition-engine closes — alignment restored)", a2a)
    # ④ RECV → all parties receive resolution
    _ = bus.recv_l9(cip_task_id)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4  SAB — Consequential Damages Negotiation
    # ─────────────────────────────────────────────────────────────────────────
    _hr("═")
    print("  STEP 4 — SAB   (Semantic Negotiation: consequential damages clause)")
    _hr("═")

    sab_episode   = f"urn:ioc:episode:sab:{uuid.uuid4()}"
    session_id    = f"urn:ioc:sab:session:{uuid.uuid4()}"
    origin_buyer  = SABOrigin(actor_id="commercial-agent", attestation=None)
    origin_seller = SABOrigin(actor_id="liability-agent",  attestation=None)
    attrs         = SABAttributes(msg_created_at="2026-06-24T10:00:00Z")
    payload_hash  = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
    content_text  = "Consequential damages clause resolved: governing interpretation and liability cap."
    sab_topic     = f"{content_text} | issues: {json.dumps(ISSUES)} | options: {json.dumps(OPTIONS)}"
    agreed        = {"governing_interpretation": "hybrid", "damages_cap": "12_months_fees"}

    def _actors(s: str, r: str) -> SABActors:
        return SABActors(actors=[Actor(id=s, role="sender",   attestation=None),
                                 Actor(id=r, role="receiver", attestation=None)])

    def _sab_hdr(mid: str, parents: List[str], s: str, r: str,
                 kind: SABKind, subkind: SABSubkind) -> SABHeader:
        return SABHeader(
            protocol="SSTP", subprotocol="SAB", version="0",
            kind=kind, subkind=subkind,
            participants=_actors(s, r),
            message=L9Msg(id=mid, parents=parents, episode=sab_episode),
            policy=None,
            context=Context(topic=sab_topic, epistemic=None,
                            semantic=Semantic(schema_id="urn:ioc:schema:sab-l9:v1",
                                             ontology_ref="urn:ioc:ontology:sab:v1")),
            attributes=attrs)

    def _neg(mid, dt, origin, step_n, t, offer, proposer, last_neg, resp, nmi=None):
        return SABPayload(type="json-schema",
                          data=SABNegotiatePayloadData(
                              message_id=mid, version="0", dt_created=dt,
                              origin=origin, payload_hash=payload_hash,
                              semantic_context=NegotiateSemanticContext(
                                  session_id=session_id,
                                  sao_state=SAOState(
                                      running=True, started=True, step=step_n, time=t,
                                      relative_time=round(t/60, 3), timedout=False,
                                      agreement=None, n_negotiators=2,
                                      current_offer=offer, current_proposer=proposer,
                                      current_proposer_agent=proposer,
                                      n_acceptances=0, last_negotiator=last_neg),
                                  sao_response=SAOResponse(
                                      response=ResponseType(resp), outcome=offer),
                                  nmi=nmi)))

    nmi   = SAONMI(id=session_id, n_outcomes=N_OUTCOMES,
                   shared_time_limit=60.0, shared_n_steps=20,
                   private_time_limit=30.0, step_time_limit=10.0,
                   negotiator_time_limit=5.0, offering_is_accepting=True)
    id_i  = str(uuid.uuid4())
    id_r1 = str(uuid.uuid4()); id_r2 = str(uuid.uuid4())
    id_r3 = str(uuid.uuid4()); id_r4 = str(uuid.uuid4())
    id_c  = str(uuid.uuid4())

    # 4a  SAB open — ① BUILD
    sab = SAB(
        header=_sab_hdr(id_i, [], "commercial-agent", "topic:sab/sessions",
                        SABKind.contingency, SABSubkind.negotiate),
        payload=SABPayload(type="json-schema",
                           data=SABIntentPayloadData(
                               message_id=id_i, version="0",
                               dt_created="2026-06-24T10:00:00Z",
                               origin=origin_buyer, payload_hash=payload_hash,
                               semantic_context=SemanticContext(schema_version="1.0"))))
    # ②③ PACK + SEND
    sab_task_id, a2a = bus.open_sab_task(sab, Role.ROLE_USER, ctx_id)
    rec("SAB", "4a · negotiate_open  (commercial-agent opens SAB)", a2a,
        "issues: governing_interpretation × damages_cap")
    # ④ RECV
    _ = bus.recv_sab(sab_task_id)

    # 4b–4e  negotiation rounds
    for tag, s, r, role, mid, dt, origin, sn, t, offer, proposer, last_neg, resp, nmi_arg, note in [
        ("4b", "commercial-agent", "liability-agent",  Role.ROLE_AGENT,
         id_r1, "2026-06-24T10:00:02Z", origin_buyer,  0,  2.1,
         {"governing_interpretation": "us_standard", "damages_cap": "6_months_fees"},
         "commercial-agent", None, 3, nmi,
         "commercial→liability: us_standard / 6_months_fees"),
        ("4c", "liability-agent",  "commercial-agent", Role.ROLE_AGENT,
         id_r2, "2026-06-24T10:00:08Z", origin_seller, 1,  8.4,
         {"governing_interpretation": "uk_standard", "damages_cap": "24_months_fees"},
         "liability-agent", "commercial-agent", 1, None,
         "liability→commercial: uk_standard / 24_months_fees"),
        ("4d", "commercial-agent", "liability-agent",  Role.ROLE_AGENT,
         id_r3, "2026-06-24T10:00:14Z", origin_buyer,  2, 14.7,
         agreed, "commercial-agent", "liability-agent", 1, None,
         "commercial→liability: hybrid / 12_months_fees"),
        ("4e", "liability-agent",  "commercial-agent", Role.ROLE_AGENT,
         id_r4, "2026-06-24T10:00:20Z", origin_seller, 3, 20.3,
         agreed, "commercial-agent", "commercial-agent", 0, None,
         "liability-agent accepts ✓"),
    ]:
        # ① BUILD SAB
        sab = SAB(header=_sab_hdr(mid, [id_i], s, r, SABKind.contingency, SABSubkind.negotiate),
                  payload=_neg(mid, dt, origin, sn, t, offer, proposer, last_neg, resp, nmi_arg))
        # ②③ PACK + SEND
        a2a = bus.send_sab(sab_task_id, sab, role, ctx_id)
        rec("SAB", f"{tag} · negotiate  ({note})", a2a)
        # ④ RECV
        _ = bus.recv_sab(sab_task_id)

    # 4f  commit:converged — ① BUILD
    sab = SAB(
        header=_sab_hdr(id_c, [id_i], "commercial-agent", "topic:sab/sessions",
                        SABKind.commit, SABSubkind.converged),
        payload=SABPayload(type="json-schema",
                           data=SABCommitPayloadData(
                               message_id=id_c, version="0",
                               dt_created="2026-06-24T10:00:25Z",
                               origin=origin_buyer, payload_hash=payload_hash,
                               semantic_context=NegotiateCommitSemanticContext(
                                   session_id=session_id,
                                   outcome=Outcome("agreement"),
                                   content_text=content_text,
                                   agents_negotiating=["commercial-agent", "liability-agent"],
                                   final_agreement=[
                                       {"issue_id": "governing_interpretation", "chosen_option": "hybrid"},
                                       {"issue_id": "damages_cap",              "chosen_option": "12_months_fees"},
                                   ]))))
    # ②③ PACK + SEND (close task)
    a2a = bus.close_sab_task(sab_task_id, sab, Role.ROLE_AGENT, ctx_id)
    rec("SAB", "4f · commit:converged  (damages clause agreed ✓)", a2a,
        "governing=hybrid  cap=12_months_fees")
    # ④ RECV
    _ = bus.recv_sab(sab_task_id)

    # ─────────────────────────────────────────────────────────────────────────
    _print_summary(log)
    _save_json(log, bus)
    print()
    for card in [alpha_card, beta_card]:
        display_agent_card(card)
        print()


if __name__ == "__main__":
    run_demo()
