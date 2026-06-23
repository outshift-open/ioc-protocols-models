"""
TFP — Team Formation via Polling: runnable end-to-end example.

Scenario
--------
A `recruiter` agent holds a task ("triage a suspicious-login security incident")
that needs several skills. It does **not** know the roster: it broadcasts a poll
to a topic, and any subscribed agent decides for itself whether to bid. The
recruiter never holds the candidates' capability profiles — it learns them only
from the bids that come back, within a bounded **response window**. It then
selects a team that covers the mandatory skills and forms it.

This is the *open-world* discovery model: candidates self-select, late responders
are dropped, and silent agents are simply never heard from. The recruiter can
only ever claim "best team among agents that responded within the window."

Every message is a real L9 envelope (``src.L9``) carrying a typed
``TFPPayload`` in its payload. Run it directly:

    poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py

or, without poetry, from the repo root:

    PYTHONPATH=. python SSTP/subprotocol/tfp/examples/team_formation_example.py
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── make `src` (L9) and the TFP binding importable when run as a script ───────
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]          # …/ioc-protocols-models
_TFP_PY = _HERE.parents[1] / "language_bindings" / "python"
for _p in (str(_REPO_ROOT), str(_TFP_PY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src import L9, L9Header, L9Payload                                  # noqa: E402
from src.primitives import Actor, ParticipantSet, Context, Message       # noqa: E402
from data_model import (                                                 # noqa: E402
    CandidateOffer,
    RoleAssignment,
    SkillClaim,
    SkillRequirement,
    TaskSpec,
    TeamSelection,
    TFPOperation,
    TFPPayload,
)

# Canonical L9 header.subkind tags for TFP turns. The header subkind is a
# free-form string: non-terminal turns are tagged "team-formation"; the terminal
# commit is "converged" (team formed) or "abort" (formation failed).
SUBKIND_TEAM_FORMATION = "team-formation"
SUBKIND_CONVERGED = "converged"
SUBKIND_ABORT = "abort"

PROTOCOL = "SSTP"
SUBPROTOCOL = "TFP"
VERSION = "0"


# ──────────────────────────────────────────────────────────────────────────────
# A tiny in-memory bus that builds well-formed L9 + TFP messages.
# Mirrors the AgentBus pattern described in SSTP/documentation/L9.md.
# ──────────────────────────────────────────────────────────────────────────────
class TFPBus:
    def __init__(self, episode: str) -> None:
        self.episode = episode
        self.task_description = ""   # L9 header topic; learned from the poll's TaskSpec
        # Cumulative, insertion-ordered roster of every actor id seen in the
        # episode (senders + receivers). The header.participants list is rebuilt
        # from this on each turn, so it keeps growing as new agents participate
        # and eventually holds everyone who took part in the episode.
        self.participants: List[str] = []
        self.messages: List[L9] = []

    def emit(
        self,
        *,
        sender: str,
        receivers: List[str],
        kind: str,
        payload: TFPPayload,
        subkind: str = "",
        parent_id: Optional[str] = None,
    ) -> L9:
        # Broadcast channels (``topic:…``) are not actors; only agents appear in
        # the header. The channel is dropped from the envelope entirely.
        agent_receivers = [r for r in receivers if not r.startswith("topic:")]

        # Accumulate only agents (sender + agent receivers) into the episode roster.
        for aid in [sender, *agent_receivers]:
            if aid not in self.participants:
                self.participants.append(aid)

        # Rebuild the header roster: the current sender first (so actors[0] is the
        # author of this turn), then this turn's agent receivers, then every other
        # agent that has participated so far. The list keeps growing across the
        # episode until it holds every agent that took part. Roles tag this turn's
        # sender/receivers; previously-seen agents are `participant`.
        ordered_ids: List[str] = []
        for aid in [sender, *agent_receivers, *self.participants]:
            if aid not in ordered_ids:
                ordered_ids.append(aid)
        participants = ParticipantSet(
            actors=[
                Actor(
                    id=aid,
                    role=(
                        "sender" if aid == sender
                        else "receiver" if aid in agent_receivers
                        else "participant"
                    ),
                )
                for aid in ordered_ids
            ],
            groups=None,
        )
        # The header topic carries the human-readable task description so every
        # turn in the episode is identifiable by what the team is forming around.
        # The poll (poll_open) is the only turn that carries the TaskSpec, so we
        # latch its description and reuse it for the rest of the episode.
        if payload.task and payload.task.description:
            self.task_description = payload.task.description
        header = L9Header(
            protocol=PROTOCOL,
            subprotocol=SUBPROTOCOL,
            version=VERSION,
            kind=kind,
            subkind=subkind,
            participants=participants,
            message=Message(
                id=str(uuid.uuid4()),
                parents=parent_id or "",
                episode=self.episode,
            ),
            context=Context(
                topic=f"Forming a team to {self.task_description}" if self.task_description else "",
            ),
        )
        msg = L9(
            header=header,
            payload=L9Payload(
                type="json-schema",
                data=payload.model_dump(exclude_none=True),
            ),
        )
        self.messages.append(msg)
        return msg


def _describe(p: Dict[str, Any]) -> str:
    """Derive a short human-readable note for the trace from the payload itself."""
    if p.get("reason"):
        return p["reason"]
    if p.get("reasoning_summary"):
        return p["reasoning_summary"]
    sel = p.get("selection")
    if sel and sel.get("members"):
        return "members: " + ", ".join(sel["members"])
    return ""


def _print_trace(bus: TFPBus) -> None:
    print(f"\n{'kind':<12}{'op':<11}{'from':<14}{'to':<26}note")
    print("-" * 100)
    for m in bus.messages:
        h, p = m.header, m.payload.data
        sender = h.participants.actors[0].id
        receivers = ",".join(a.id for a in h.participants.actors if a.role == "receiver") or "(broadcast)"
        kind = h.kind + (f":{h.subkind}" if h.subkind else "")
        print(f"{kind:<12}{p.get('operation',''):<11}{sender:<14}{receivers:<26}{_describe(p)}")


# ──────────────────────────────────────────────────────────────────────────────
# Dump the full L9 envelopes exchanged during the episode to JSON.
# Unlike `_print_trace` (which shows only a few columns), this serializes every
# complete message (header + payload) so the exchange can be replayed/inspected.
# ──────────────────────────────────────────────────────────────────────────────
DUMP_SCHEMA = "ioc.tfp.message_dump.v1"


def _poll_id_of(bus: "TFPBus") -> Optional[str]:
    """Best-effort poll_id: the first poll_id seen in any TFP payload."""
    for m in bus.messages:
        pid = m.payload.data.get("poll_id")
        if pid:
            return pid
    return None


def _dump_message(msg: L9) -> Dict[str, Any]:
    """Serialize one L9 envelope, dropping the unused header.attributes field."""
    d = msg.model_dump()
    d["header"].pop("attributes", None)  # TFP does not use header attributes
    return d


def build_dump(bus: "TFPBus") -> Dict[str, Any]:
    """Build the dump document: metadata wrapper + every full L9 envelope."""
    return {
        "schema": DUMP_SCHEMA,
        "episode": bus.episode,
        "poll_id": _poll_id_of(bus),
        "message_count": len(bus.messages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "messages": [_dump_message(m) for m in bus.messages],
    }


def dump_messages(bus: "TFPBus", path: Optional[Path] = None) -> Path:
    """
    Serialize every L9 message in ``bus.messages`` (full header + payload) to a
    pretty-printed JSON file and return the path written.

    If ``path`` is None, the dump is written to a single, stable, predictable
    file at ``examples/dumps/team_formation_latest.json`` (overwritten each run)
    so it is always easy to find. This file is intentionally kept visible (not
    git-ignored) so it shows up in your editor's file tree.
    """
    if path is None:
        dumps_dir = _HERE.parent / "dumps"
        dumps_dir.mkdir(parents=True, exist_ok=True)
        path = dumps_dir / "team_formation_latest.json"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(json.dumps(build_dump(bus), indent=2, ensure_ascii=False), encoding="utf-8")
    return path.resolve()


# ──────────────────────────────────────────────────────────────────────────────
# Selection logic: greedy cover of mandatory skills by proficiency.
# ──────────────────────────────────────────────────────────────────────────────
def _proficiency_for(offer: CandidateOffer, req: SkillRequirement) -> Optional[float]:
    """The candidate's proficiency for ``req`` if it meets the minimum, else None."""
    qualifying = [
        c.proficiency for c in offer.skills
        if c.skill == req.skill and c.proficiency >= req.min_proficiency
    ]
    return max(qualifying) if qualifying else None


def _candidate_fit(reqs: List[SkillRequirement], offer: CandidateOffer) -> float:
    """Weighted fit in [0,1]: how well this candidate's claims satisfy the requirements."""
    total_w = sum(r.weight for r in reqs) or 1.0
    score = sum(r.weight * (_proficiency_for(offer, r) or 0.0) for r in reqs)
    return round(score / total_w, 4)


def select_team(
    reqs: List[SkillRequirement],
    bids: Dict[str, CandidateOffer],
) -> TeamSelection:
    mandatory = [r for r in reqs if r.mandatory]
    members: List[str] = []
    roles: List[RoleAssignment] = []
    covered: set[str] = set()

    # Greedy: for each uncovered mandatory skill, pick the best-qualified candidate
    # (highest proficiency) and give it every required skill it qualifies for.
    for r in mandatory:
        if r.skill in covered:
            continue
        candidates = {a: _proficiency_for(o, r) for a, o in bids.items()}
        best = max(
            (a for a, prof in candidates.items() if prof is not None),
            key=lambda a: candidates[a],
            default=None,
        )
        if best is None:
            continue
        owned = sorted(rr.skill for rr in reqs if _proficiency_for(bids[best], rr) is not None)
        covered.update(owned)
        if best not in members:
            members.append(best)
            roles.append(RoleAssignment(agent_id=best, role="contributor", responsible_for=owned))

    unmet = [r.skill for r in mandatory if r.skill not in covered]
    coverage = round((len(mandatory) - len(unmet)) / (len(mandatory) or 1), 4)
    agg_fit = round(sum(_candidate_fit(reqs, bids[m]) for m in members) / len(members), 4) if members else 0.0
    return TeamSelection(
        members=members,
        roles=roles,
        coverage=coverage,
        unmet_skills=unmet,
        aggregate_fit=agg_fit,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Open-world discovery: candidate agents + a broadcast topic.
# The recruiter does NOT know who is subscribed or what they can do — it learns
# capabilities only from the bids that come back.
# ──────────────────────────────────────────────────────────────────────────────
class CandidateAgent:
    """
    A peer agent that owns its capability profile *privately*. The recruiter
    never reads ``_offer`` directly; it only ever sees what the agent chooses to
    disclose in a bid. Each agent decides on its own whether to bid or decline,
    how long it takes to respond, and how it answers a membership proposal.
    """

    def __init__(
        self,
        agent_id: str,
        offer: CandidateOffer,
        *,
        response_latency_ms: int = 50,
        membership: Optional[tuple[bool, str]] = None,
        silent: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self._offer = offer
        self.response_latency_ms = response_latency_ms
        self._membership = membership or (True, "Skills match the task and I have capacity this shift.")
        self.silent = silent

    def respond_to_poll(self, poll: TFPPayload) -> Optional[tuple[TFPPayload, int]]:
        """Decide whether to bid. Returns ``(payload, arrival_ms)`` or ``None`` (silent)."""
        if self.silent:
            return None
        required = {r.skill for r in poll.required_skills}
        relevant = [c for c in self._offer.skills if c.skill in required]
        if not relevant:
            payload = TFPPayload(
                operation=TFPOperation.DECLINE,
                poll_id=poll.poll_id,
                reason="None of my skills match the required skills for this poll.",
            )
        else:
            payload = TFPPayload(
                operation=TFPOperation.BID,
                poll_id=poll.poll_id,
                offer=self._offer,
                reasoning_summary=f"fit≈{_candidate_fit(poll.required_skills, self._offer)}",
            )
        return payload, self.response_latency_ms

    def respond_to_select(self, poll_id: str) -> TFPPayload:
        """Answer the recruiter's proposal to join — accept or reject, with a reason."""
        accepts, reason = self._membership
        return TFPPayload(
            operation=TFPOperation.ACCEPT if accepts else TFPOperation.REJECT,
            poll_id=poll_id,
            reason=reason,
        )


class SkillPollTopic:
    """
    A broadcast pub-sub channel. The recruiter publishes a poll *without knowing*
    who is subscribed; each subscriber decides for itself whether to respond. This
    is what makes the poll open-world — there is no roster.
    """

    def __init__(self) -> None:
        self._subscribers: List[CandidateAgent] = []

    def subscribe(self, agent: CandidateAgent) -> None:
        self._subscribers.append(agent)

    def broadcast(self, poll: TFPPayload) -> List[tuple[str, TFPPayload, int]]:
        """Deliver the poll to every subscriber; collect (agent_id, response, arrival_ms)."""
        out: List[tuple[str, TFPPayload, int]] = []
        for agent in self._subscribers:
            r = agent.respond_to_poll(poll)
            if r is not None:
                payload, arrival = r
                out.append((agent.agent_id, payload, arrival))
        return out

    def request_membership(self, agent_id: str, poll_id: str) -> TFPPayload:
        """Point-to-point once the recruiter knows the id (learned from a bid)."""
        agent = next(a for a in self._subscribers if a.agent_id == agent_id)
        return agent.respond_to_select(poll_id)


# ──────────────────────────────────────────────────────────────────────────────
# The example episode.
# ──────────────────────────────────────────────────────────────────────────────
def run(force_failure: bool = False) -> TFPBus:
    """Run the example episode.

    With ``force_failure=True`` an extra mandatory skill that no subscriber
    possesses is added to the requirements, so the team cannot converge — this
    exercises the re-poll (``re_poll`` operation, ``team-formation`` subkind) and the
    ``form_failed`` operation / ``abort`` subkind commit path.
    """
    episode = str(uuid.uuid4())
    bus = TFPBus(episode=episode)
    recruiter = "recruiter"
    topic_name = "topic:tfp/polls/secops"
    window_ms = 100   # response window — bids that arrive later are dropped

    # --- Candidate agents subscribe to the topic. Each owns its profile -------
    # privately; the recruiter has NO list of these and never reads their offers.
    topic = SkillPollTopic()
    topic.subscribe(CandidateAgent(
        "log-analyst",
        CandidateOffer(
            skills=[
                SkillClaim(skill="skill:log_triage", proficiency=0.92),
                SkillClaim(skill="skill:siem_query", proficiency=0.80),
            ],
            fit_score=0.9,   # availability is optional and omitted here
        ),
        response_latency_ms=45,
    ))
    topic.subscribe(CandidateAgent(
        "threat-intel",
        CandidateOffer(
            skills=[
                SkillClaim(skill="skill:threat_intel", proficiency=0.88),
                SkillClaim(skill="skill:ioc_enrichment", proficiency=0.85),
            ],
            fit_score=0.82,
        ),
        response_latency_ms=60,
        # threat-intel is the best bidder but rejects, forcing a fallback re-select.
        membership=(False, "Already committed to incident-4470 this shift; at capacity."),
    ))
    topic.subscribe(CandidateAgent(
        "intel-2",   # fallback threat-intel, re-selected once threat-intel rejects
        CandidateOffer(skills=[SkillClaim(skill="skill:threat_intel", proficiency=0.72)], fit_score=0.7),
        response_latency_ms=85,
    ))
    topic.subscribe(CandidateAgent(
        "forensics",
        CandidateOffer(
            skills=[
                SkillClaim(skill="skill:host_forensics", proficiency=0.90),
                SkillClaim(skill="skill:log_triage", proficiency=0.60),
            ],
            fit_score=0.7,
        ),
        response_latency_ms=70,
    ))
    topic.subscribe(CandidateAgent(
        "comms-bot",   # hears the poll but has nothing relevant — self-declines
        CandidateOffer(skills=[SkillClaim(skill="skill:status_reporting", proficiency=0.95)], fit_score=0.1),
        response_latency_ms=30,
    ))
    topic.subscribe(CandidateAgent(
        "slow-intel",  # would be the BEST threat-intel, but answers too late → dropped
        CandidateOffer(skills=[SkillClaim(skill="skill:threat_intel", proficiency=0.99)], fit_score=0.95),
        response_latency_ms=250,
    ))
    topic.subscribe(CandidateAgent(
        "ghost-agent",  # subscribed but silent — the recruiter never hears from it
        CandidateOffer(skills=[SkillClaim(skill="skill:translation", proficiency=0.9)]),
        silent=True,
    ))

    # --- Required skills for the task -----------------------------------------
    required = [
        SkillRequirement(skill="skill:log_triage", min_proficiency=0.7, weight=2.0, mandatory=True),
        SkillRequirement(skill="skill:threat_intel", min_proficiency=0.6, weight=1.5, mandatory=True),
        SkillRequirement(skill="skill:host_forensics", min_proficiency=0.6, weight=1.0, mandatory=False),
    ]
    if force_failure:
        # No subscriber owns this skill, so a mandatory requirement stays uncovered:
        # the recruiter re-polls and the episode commits as form_failed.
        required.append(
            SkillRequirement(skill="skill:quantum_forensics", min_proficiency=0.9, weight=1.0, mandatory=True)
        )
    poll_id = "urn:ioc:tfp:poll:" + uuid.uuid4().hex[:8]
    task = TaskSpec(
        task_id="incident-4471",
        description="Triage a suspicious-login security incident across SIEM + endpoint data",
        objective="Confirm or dismiss compromise within 30 minutes",
    )
    poll = TFPPayload(
        operation=TFPOperation.POLL_OPEN,
        poll_id=poll_id,
        task=task,
        required_skills=required,
        reasoning_summary="Need log triage + threat intel; host forensics is a nice-to-have.",
    )

    # === 1. intent / poll_open — BROADCAST to the topic ======================
    # The recruiter addresses the topic, not a roster: it does not know who listens.
    open_msg = bus.emit(
        sender=recruiter,
        receivers=[topic_name],
        kind="intent",
        subkind=SUBKIND_TEAM_FORMATION,
        payload=poll,
    )
    parent = open_msg.header.message.id

    # === 2. discovery: candidates self-select; collect bids within the window =
    responses = topic.broadcast(poll)
    responses.sort(key=lambda r: r[2])   # process in arrival order
    received_bids: Dict[str, CandidateOffer] = {}
    for agent_id, payload, arrival_ms in responses:
        late = arrival_ms > window_ms
        bus.emit(
            sender=agent_id,
            receivers=[recruiter],
            kind="exchange",
            subkind=SUBKIND_TEAM_FORMATION,
            parent_id=parent,
            payload=payload,
        )
        # only on-time bids are eligible for selection
        if not late and payload.operation == TFPOperation.BID:
            received_bids[agent_id] = payload.offer

    # === 3. evaluate + select, handling accept/reject with fallback re-select =
    # `pool` shrinks as candidates reject; selection is recomputed over the
    # remaining bidders until every selected member has accepted (or we run out).
    pool: Dict[str, CandidateOffer] = dict(received_bids)
    accepted: List[str] = []
    contacted: set[str] = set()
    selection = select_team(required, pool)

    for _round in range(1, 4):  # bounded re-selection rounds
        new_members = [m for m in selection.members if m not in contacted]
        if not new_members:
            break
        for member in new_members:
            contacted.add(member)
            # initiator proposes membership ("the proposal to join the team")
            bus.emit(
                sender=recruiter,
                receivers=[member],
                kind="exchange",
                subkind=SUBKIND_TEAM_FORMATION,
                parent_id=parent,
                payload=TFPPayload(
                    operation=TFPOperation.SELECT,
                    poll_id=poll_id,
                    selection=selection,
                ),
            )
            # === 4. exchange / accept | reject (each carries a reason) ========
            # The agent itself decides; the recruiter just relays its response.
            response = topic.request_membership(member, poll_id)
            accepts = response.operation == TFPOperation.ACCEPT
            bus.emit(
                sender=member,
                receivers=[recruiter],
                kind="exchange",
                subkind=SUBKIND_TEAM_FORMATION,
                parent_id=parent,
                payload=response,
            )
            if accepts:
                accepted.append(member)
            else:
                pool.pop(member, None)  # remove rejecter, re-select a fallback
        # recompute over the (possibly reduced) pool for the next round
        selection = select_team(required, pool)

    # final team is computed strictly over the members who actually accepted
    selection = select_team(required, {a: received_bids[a] for a in accepted})
    formation_ok = not selection.unmet_skills and bool(selection.members)

    # === 5. Re-poll if mandatory coverage is incomplete =================
    if not formation_ok:
        bus.emit(
            sender=recruiter,
            receivers=[topic_name],
            kind="exchange",
            subkind=SUBKIND_TEAM_FORMATION,
            parent_id=parent,
            payload=TFPPayload(
                operation=TFPOperation.RE_POLL,
                poll_id=poll_id,
                required_skills=[r for r in required if r.skill in selection.unmet_skills],
                reasoning_summary="re_poll: mandatory skills uncovered: " + ", ".join(selection.unmet_skills),
            ),
        )

    # === 6. commit / form =====================================================
    bus.emit(
        sender=recruiter,
        receivers=[topic_name],
        kind="commit",
        subkind=(SUBKIND_CONVERGED if formation_ok else SUBKIND_ABORT),
        parent_id=parent,
        payload=TFPPayload(
            operation=(TFPOperation.FORM_CONVERGED if formation_ok else TFPOperation.FORM_FAILED),
            poll_id=poll_id,
            selection=selection,
            reasoning_summary=(
                f"coverage={selection.coverage} aggregate_fit={selection.aggregate_fit}"
            ),
        ),
    )


    return bus


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the TFP team-formation example.")
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Where to write the full L9 message dump (JSON). "
             "Defaults to examples/dumps/team_formation_latest.json.",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        help="Force an unsatisfiable mandatory skill so the episode re-polls and "
             "commits as form_failed (demonstrates the failure path).",
    )
    args = parser.parse_args(argv)

    bus = run(force_failure=args.fail)
    _print_trace(bus)

    form = bus.messages[-1].payload.data
    sel = form.get("selection", {})
    print("\n" + "=" * 100)
    print(f"Episode : {bus.episode}")
    print(f"Members : {sel.get('members')}")
    print(f"Roles   :")
    for ro in sel.get("roles", []):
        print(f"          {ro['agent_id']:<14} {ro['role']:<12} owns {ro['responsible_for']}")
    print(f"Coverage: {sel.get('coverage')}   Aggregate fit: {sel.get('aggregate_fit')}   "
          f"Unmet: {sel.get('unmet_skills')}")
    print("=" * 100)

    if args.out:
        out_path: Optional[Path] = Path(args.out)
    else:
        # name the default dump by scenario so success and failure runs don't clobber
        scenario = "failure" if args.fail else "success"
        out_path = _HERE.parent / "dumps" / f"team_formation_{scenario}.json"
    dump_path = dump_messages(bus, out_path)
    print("\n" + "=" * 100)
    print(f"L9 MESSAGE DUMP: {len(bus.messages)} envelopes written to")
    print(f"  {dump_path}")
    print("(this file is kept visible in your editor's file tree — open the path above)")
    print("=" * 100)


if __name__ == "__main__":
    main()
