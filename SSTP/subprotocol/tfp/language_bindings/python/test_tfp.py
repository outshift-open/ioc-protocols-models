"""
Tests for the TFP (Team Formation via Polling) subprotocol.

Validates the TFP payload models (``generated_models.py``) and the end-to-end example
episode:

    poll_open -> bid/decline -> select -> accept/reject -> [re_poll] -> commit

against the current model: operations are ``form_converged``/``form_failed``
(no bare ``form``), the lifecycle phase is carried by ``header.subkind``
(``team_form_*``) with no separate ``status`` field, and there is no ``profile``
discriminator or ``SkillClaim.evidence``.

Run from the repo root:
    poetry run pytest SSTP/subprotocol/tfp/language_bindings/python/test_tfp.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[5]                      # …/ioc-protocols-models
_TFP_PY = _HERE.parent
_EXAMPLES = _HERE.parents[2] / "examples"
for _p in (str(_REPO_ROOT), str(_TFP_PY), str(_EXAMPLES)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from generated_models import (  # noqa: E402
    CandidateOffer,
    RoleAssignment,
    SkillClaim,
    SkillRequirement,
    TaskSpec,
    TeamSelection,
    TFPOperation,
    TFPPayload,
    TFPSubkind,
)


# ──────────────────────────────────────────────────────────────────────────────
# Enums — the model's vocabulary (operations + lifecycle subkinds).
# ──────────────────────────────────────────────────────────────────────────────
class TestTFPEnums:
    def test_operation_values(self):
        assert {op.value for op in TFPOperation} == {
            "poll_open",
            "bid",
            "decline",
            "clarify",
            "select",
            "accept",
            "reject",
            "form_failed",
            "form_converged",
            "re_poll",
        }
        # the closing operation is split into converged/failed (no bare "form")
        assert not hasattr(TFPOperation, "FORM")
        assert TFPOperation.FORM_CONVERGED.value == "form_converged"
        assert TFPOperation.FORM_FAILED.value == "form_failed"

    def test_subkind_values(self):
        assert {sk.value for sk in TFPSubkind} == {
            "team_form",
            "team_form_converged",
            "team_form_failure",
        }


# ──────────────────────────────────────────────────────────────────────────────
# Payload models — shape, defaults, and validation.
# ──────────────────────────────────────────────────────────────────────────────
class TestTFPModels:
    def test_poll_open_payload(self):
        payload = TFPPayload(
            operation=TFPOperation.POLL_OPEN,
            poll_id="urn:ioc:tfp:poll:abc",
            task=TaskSpec(task_id="t1", description="do work"),
            required_skills=[SkillRequirement(skill="skill:python", min_proficiency=0.7)],
        )
        assert payload.operation == TFPOperation.POLL_OPEN
        assert payload.required_skills[0].mandatory is True
        # round-trips through JSON cleanly
        assert TFPPayload(**payload.model_dump()).poll_id == "urn:ioc:tfp:poll:abc"

    def test_bid_payload(self):
        payload = TFPPayload(
            operation=TFPOperation.BID,
            poll_id="p",
            offer=CandidateOffer(
                skills=[SkillClaim(skill="skill:python", proficiency=0.9)],
                availability=0.8,
            ),
        )
        assert payload.offer.skills[0].proficiency == 0.9
        assert payload.offer.availability == 0.8

    def test_skill_claim_is_skill_and_proficiency_only(self):
        # `evidence` has been removed from SkillClaim
        assert set(SkillClaim.model_fields) == {"skill", "proficiency"}
        claim = SkillClaim(skill="skill:python", proficiency=0.5)
        assert "evidence" not in claim.model_dump()

    def test_payload_has_no_status_or_profile(self):
        # `status` and `profile` were removed; phase lives in header.subkind
        fields = set(TFPPayload.model_fields)
        assert "status" not in fields
        assert "profile" not in fields
        assert fields == {
            "operation",
            "poll_id",
            "task",
            "required_skills",
            "offer",
            "selection",
            "reason",
            "reasoning_summary",
        }

    def test_optional_fields_default_to_none_or_empty(self):
        payload = TFPPayload(operation=TFPOperation.CLARIFY, poll_id="p")
        assert payload.task is None
        assert payload.offer is None
        assert payload.selection is None
        assert payload.reason is None
        assert payload.reasoning_summary is None
        assert payload.required_skills == []

    def test_proficiency_bounds_enforced(self):
        with pytest.raises(ValidationError):
            SkillClaim(skill="skill:python", proficiency=1.5)
        with pytest.raises(ValidationError):
            SkillRequirement(skill="skill:python", min_proficiency=-0.1)

    def test_operation_must_be_valid(self):
        with pytest.raises(ValidationError):
            TFPPayload(operation="not_a_real_op", poll_id="p")

    def test_poll_id_is_required(self):
        with pytest.raises(ValidationError):
            TFPPayload(operation=TFPOperation.BID)

    def test_accept_and_reject_carry_a_reason(self):
        accept = TFPPayload(
            operation=TFPOperation.ACCEPT,
            poll_id="p",
            reason="Skills match and I have capacity.",
        )
        reject = TFPPayload(
            operation=TFPOperation.REJECT,
            poll_id="p",
            reason="Already committed elsewhere this shift.",
        )
        assert accept.reason == "Skills match and I have capacity."
        assert reject.operation == TFPOperation.REJECT
        assert reject.reason == "Already committed elsewhere this shift."
        # reason is optional and defaults to None
        assert TFPPayload(operation=TFPOperation.ACCEPT, poll_id="p").reason is None

    def test_re_poll_payload(self):
        payload = TFPPayload(
            operation=TFPOperation.RE_POLL,
            poll_id="p",
            required_skills=[SkillRequirement(skill="skill:threat_intel")],
            reasoning_summary="re_poll: mandatory skills uncovered: skill:threat_intel",
        )
        assert payload.operation == TFPOperation.RE_POLL
        assert payload.required_skills[0].skill == "skill:threat_intel"

    def test_form_converged_and_failed_payloads(self):
        selection = TeamSelection(
            members=["a", "b"],
            roles=[RoleAssignment(agent_id="a", role="contributor", responsible_for=["skill:x"])],
            coverage=1.0,
            unmet_skills=[],
            aggregate_fit=0.5,
        )
        converged = TFPPayload(
            operation=TFPOperation.FORM_CONVERGED, poll_id="p", selection=selection
        )
        failed = TFPPayload(
            operation=TFPOperation.FORM_FAILED,
            poll_id="p",
            selection=TeamSelection(coverage=0.0, unmet_skills=["skill:x"]),
        )
        assert converged.operation == TFPOperation.FORM_CONVERGED
        assert converged.selection.members == ["a", "b"]
        assert failed.operation == TFPOperation.FORM_FAILED
        assert failed.selection.unmet_skills == ["skill:x"]

    def test_full_payload_round_trips(self):
        payload = TFPPayload(
            operation=TFPOperation.SELECT,
            poll_id="urn:ioc:tfp:poll:xyz",
            selection=TeamSelection(members=["a"], coverage=1.0),
            reasoning_summary="greedy cover then maximize fit",
        )
        restored = TFPPayload(**payload.model_dump())
        assert restored == payload


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end example episode.
# ──────────────────────────────────────────────────────────────────────────────
class TestTFPEpisode:
    def test_example_forms_a_team_that_covers_mandatory_skills(self):
        import team_formation_example as ex

        bus = ex.run()

        # the closing message is a converged commit
        commit = next(m for m in bus.messages if m.header.kind == "commit")
        assert commit.header.subkind == TFPSubkind.TEAM_FORM_CONVERGED.value
        assert commit.payload.data["operation"] == TFPOperation.FORM_CONVERGED.value

        sel = commit.payload.data["selection"]
        assert sel["coverage"] == 1.0
        assert sel["unmet_skills"] == []
        # threat-intel rejected, so the intel-2 fallback covers threat_intel
        assert set(sel["members"]) == {"log-analyst", "intel-2"}
        # the irrelevant candidate self-declined
        decline_ops = [
            m for m in bus.messages
            if m.payload.data.get("operation") == TFPOperation.DECLINE.value
        ]
        assert any(m.header.actors.actors[0].id == "comms-bot" for m in decline_ops)

    def test_accept_and_reject_membership_responses_have_reasons(self):
        import team_formation_example as ex

        bus = ex.run()

        accepts = [m for m in bus.messages if m.payload.data.get("operation") == "accept"]
        rejects = [m for m in bus.messages if m.payload.data.get("operation") == "reject"]

        # at least one accept and exactly one reject (threat-intel), each with a reason
        assert accepts and rejects
        assert all(m.payload.data.get("reason") for m in accepts)
        assert all(m.payload.data.get("reason") for m in rejects)
        rejecter = rejects[0].header.actors.actors[0].id
        assert rejecter == "threat-intel"
        # the decline (poll opt-out) also carries a reason
        declines = [m for m in bus.messages if m.payload.data.get("operation") == "decline"]
        assert all(m.payload.data.get("reason") for m in declines)

    def test_every_message_is_a_tfp_envelope(self):
        import team_formation_example as ex

        bus = ex.run()
        valid_ops = {op.value for op in TFPOperation}
        for m in bus.messages:
            assert m.header.protocol == "SSTP"
            assert m.header.subprotocol == "TFP"
            assert m.payload.type == "json-schema"
            assert m.header.message.episode == bus.episode
            # the payload always carries a known operation + the poll_id
            assert m.payload.data["operation"] in valid_ops
            assert m.payload.data["poll_id"].startswith("urn:ioc:tfp:poll:")

    def test_payloads_never_contain_dropped_fields(self):
        import team_formation_example as ex

        bus = ex.run()
        for m in bus.messages:
            data = m.payload.data
            assert "status" not in data
            assert "profile" not in data
            assert "utterance" not in data
            offer = data.get("offer")
            if offer:
                for claim in offer.get("skills", []):
                    assert "evidence" not in claim
            # the header attribute tag was removed too
            assert m.header.attributes is None

    def test_subkinds_tag_each_phase(self):
        import team_formation_example as ex

        bus = ex.run()

        # every turn carries one of the canonical TFP subkinds
        valid = {s.value for s in TFPSubkind}
        for m in bus.messages:
            assert m.header.subkind in valid

        by_kind: dict[str, set[str]] = {}
        for m in bus.messages:
            by_kind.setdefault(m.header.kind, set()).add(m.header.subkind)

        # non-terminal turns (poll, bids, selects) all carry the generic team_form
        # subkind; only the terminal commit is converged/failure.
        assert by_kind["intent"] == {TFPSubkind.TEAM_FORM.value}
        assert by_kind["exchange"] == {TFPSubkind.TEAM_FORM.value}
        assert by_kind["commit"] == {TFPSubkind.TEAM_FORM_CONVERGED.value}

    def test_open_world_discovery_semantics(self):
        import team_formation_example as ex

        bus = ex.run()
        senders = {m.header.actors.actors[0].id for m in bus.messages}

        # the poll is broadcast: no agent receivers and no channel recorded in
        # the envelope at all
        poll_open = next(m for m in bus.messages if m.payload.data.get("operation") == "poll_open")
        assert poll_open.header.actors.groups is None
        # no broadcast channel ever leaks into the actors list
        for m in bus.messages:
            assert all(not a.id.startswith("topic:") for a in m.header.actors.actors)

        # a silent subscriber is never heard from
        assert "ghost-agent" not in senders

        # a late responder bids but is excluded from the selected team
        slow = [m for m in bus.messages if m.header.actors.actors[0].id == "slow-intel"]
        assert slow and slow[0].payload.data.get("operation") == "bid"
        commit = next(m for m in bus.messages if m.header.kind == "commit")
        assert "slow-intel" not in commit.payload.data["selection"]["members"]

    def test_topic_does_not_expose_offers_until_bid(self):
        import team_formation_example as ex

        topic = ex.SkillPollTopic()
        agent = ex.CandidateAgent(
            "a1",
            ex.CandidateOffer(skills=[ex.SkillClaim(skill="skill:x", proficiency=0.9)]),
        )
        topic.subscribe(agent)

        poll = ex.TFPPayload(
            operation=ex.TFPOperation.POLL_OPEN,
            poll_id="p",
            required_skills=[ex.SkillRequirement(skill="skill:x", min_proficiency=0.5)],
        )
        responses = topic.broadcast(poll)
        assert len(responses) == 1
        agent_id, payload, _arrival = responses[0]
        assert agent_id == "a1"
        assert payload.operation == ex.TFPOperation.BID
        # an agent with no matching skill self-declines instead of bidding
        poll2 = ex.TFPPayload(
            operation=ex.TFPOperation.POLL_OPEN,
            poll_id="p2",
            required_skills=[ex.SkillRequirement(skill="skill:unrelated")],
        )
        _, decline_payload, _ = topic.broadcast(poll2)[0]
        assert decline_payload.operation == ex.TFPOperation.DECLINE

    def test_selection_reports_unmet_when_mandatory_skill_missing(self):
        import team_formation_example as ex

        reqs = [
            SkillRequirement(skill="skill:quantum", min_proficiency=0.9, mandatory=True),
        ]
        bids = {
            "a": CandidateOffer(skills=[SkillClaim(skill="skill:python", proficiency=1.0)]),
        }
        selection = ex.select_team(reqs, bids)
        assert selection.unmet_skills == ["skill:quantum"]
        assert selection.coverage == 0.0


class TestTFPFailureEpisode:
    """The forced-failure scenario: an uncovered mandatory skill triggers a
    re-poll and a form_failed commit."""

    def test_uncovered_mandatory_skill_triggers_repoll_then_form_failed(self):
        import team_formation_example as ex

        bus = ex.run(force_failure=True)

        # a re_poll turn is emitted: kind=exchange, subkind=team_form (non-terminal)
        re_polls = [m for m in bus.messages if m.payload.data.get("operation") == "re_poll"]
        assert len(re_polls) == 1
        re_poll = re_polls[0]
        assert re_poll.header.kind == "exchange"
        assert re_poll.header.subkind == TFPSubkind.TEAM_FORM.value
        # the re-poll names the uncovered mandatory skill
        re_poll_skills = [s["skill"] for s in re_poll.payload.data["required_skills"]]
        assert "skill:quantum_forensics" in re_poll_skills

        # the episode commits as failed
        commit = next(m for m in bus.messages if m.header.kind == "commit")
        assert commit.header.subkind == TFPSubkind.TEAM_FORM_FAILURE.value
        assert commit.payload.data["operation"] == TFPOperation.FORM_FAILED.value

        # the failed selection still reports the uncovered mandatory skill
        sel = commit.payload.data["selection"]
        assert "skill:quantum_forensics" in sel["unmet_skills"]
        assert sel["coverage"] < 1.0

    def test_happy_path_has_no_repoll_or_failure(self):
        import team_formation_example as ex

        bus = ex.run()  # default scenario converges
        ops = {m.payload.data.get("operation") for m in bus.messages}
        assert "re_poll" not in ops
        assert "form_failed" not in ops
        assert "form_converged" in ops


# ──────────────────────────────────────────────────────────────────────────────
# JSON message dump.
# ──────────────────────────────────────────────────────────────────────────────
class TestTFPMessageDump:
    def test_dump_writes_full_envelopes_and_round_trips(self, tmp_path):
        import json

        import team_formation_example as ex
        from ioc_l9.src import L9

        bus = ex.run()
        out = tmp_path / "dump.json"
        returned = ex.dump_messages(bus, out)

        # the function returns the path it wrote, and the file exists
        assert returned == out
        assert out.exists()

        doc = json.loads(out.read_text())

        # top-level metadata wrapper
        assert doc["schema"] == ex.DUMP_SCHEMA
        assert doc["episode"] == bus.episode
        assert doc["poll_id"] and doc["poll_id"].startswith("urn:ioc:tfp:poll:")
        assert doc["message_count"] == len(bus.messages)
        assert "generated_at" in doc

        # one full envelope per message, and each round-trips into ioc_l9.src.L9
        assert len(doc["messages"]) == len(bus.messages)
        for raw in doc["messages"]:
            assert "header" in raw and "payload" in raw
            # the unused header.attributes tag is dropped from the dump
            assert "attributes" not in raw["header"]
            restored = L9(**raw)
            assert restored.header.protocol == "SSTP"
            assert restored.header.subprotocol == "TFP"
            assert restored.payload.type == "json-schema"

        # the dump preserves the full payload, not just the trace columns
        first = doc["messages"][0]
        assert first["payload"]["data"]["poll_id"] == doc["poll_id"]
        assert "required_skills" in first["payload"]["data"]  # poll_open carries the task spec

    def test_dump_does_not_write_into_repo_tree(self, tmp_path):
        import team_formation_example as ex

        bus = ex.run()
        out = tmp_path / "nested" / "dump.json"  # parent dir is created on demand
        ex.dump_messages(bus, out)
        assert out.exists()
        # sanity: we wrote under tmp_path, never the example's dumps/ dir
        assert str(tmp_path) in str(out.resolve())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
