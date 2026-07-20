#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
app/hcpanel/main.py — HCPanel: joint clinical debate between 5 physician and
5 pharmacology specialists using SIEP star negotiation with inline CIP gating.

Usage:
    python -m app.hcpanel.main --sessions 1 --llm-backend simulated --fresh-memory
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import tempfile
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from langgraph.graph import END, START, StateGraph

from SSTP.examples.hcpanel.agent_bus import MessageBus
from SSTP.examples.hcpanel.specialists import SpecialistAgent, DIAGNOSTICS_SPECIALISTS, PHARMACY_SPECIALISTS, ROLE_DESCRIPTIONS
from SSTP.examples.hcpanel.domain import (
    ClinicalDebateOutcome,
    DebateGraphState,
    HealthcareEpisode,
)
from SSTP.examples.hcpanel.llm_backends import build_llm_client
from SSTP.examples.hcpanel.memory import HCPanelMemory
from SSTP.examples.hcpanel.orchestration import DebateOrchestrator
from SSTP.examples.hcpanel.domain import PatientProfile

LOGGER = logging.getLogger("hcpanel")
LOG_CORRELATION_ID: ContextVar[str] = ContextVar("hcpanel_log_correlation_id", default="-")

PATIENTS_FILE = Path(__file__).with_name("patients.json")
MEMORY_STORE_FILE = Path(__file__).with_name("memory.json")

_TASK_GOAL = (
    "Joint clinical debate: patient symptom assessment, drug interaction risk, "
    "drug change proposals, and joint recommendation"
)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = LOG_CORRELATION_ID.get()
        return True


def set_correlation_id(cid: str) -> Any:
    return LOG_CORRELATION_ID.set(cid)


def reset_correlation_id(token: Any) -> None:
    LOG_CORRELATION_ID.reset(token)


def setup_logging(level: str = "INFO") -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    previous_factory = logging.getLogRecordFactory()

    def _factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        record.correlation_id = LOG_CORRELATION_ID.get()
        return record

    logging.setLogRecordFactory(_factory)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s [cid=%(correlation_id)s] - %(message)s",
    )
    logging.getLogger().addFilter(CorrelationIdFilter())
    if numeric > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "openai"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def redact_text(value: str) -> str:
    value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[REDACTED_EMAIL]", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:\+?\d[\d\s\-]{7,}\d)\b", "[REDACTED_PHONE]", value)
    return value


def load_patients(file_path: Path = PATIENTS_FILE) -> List[PatientProfile]:
    rows = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("patients file must contain a JSON list")
    patients: List[PatientProfile] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        patients.append(
            PatientProfile(
                patient_id=str(row["patient_id"]),
                locality=str(row["locality"]),
                symptoms=[str(s) for s in row.get("symptoms", [])],
                health_history=[str(s) for s in row.get("health_history", [])],
                current_medications=[str(s) for s in row.get("current_medications", [])],
                medication_allergies=[str(s) for s in row.get("medication_allergies", [])],
                insurance_plan=str(row.get("insurance_plan", "")),
                chat_history=[redact_text(str(s)) for s in row.get("chat_history", [])],
                calendar_slots_day_offsets=[int(s) for s in row.get("calendar_slots_day_offsets", [])],
            )
        )
    return patients


class HCPanelSystem:
    """Joint clinical debate coordinator — 3-node LangGraph."""

    def __init__(
        self,
        llm_backend: str = "simulated",
        model: str = "gpt-5",
        memory_store_file: Path = MEMORY_STORE_FILE,
    ) -> None:
        # One factory closure per system — each call produces an independent client
        _backend = llm_backend
        _model = model

        def _make_llm(agent_id: str = "") -> "LLMClient":
            return build_llm_client(_backend, _model, agent_id=agent_id)

        self._make_llm = _make_llm
        self.coordinator_llm = _make_llm("diagnostics-controller")

        self.memory = HCPanelMemory(memory_store_file)

        # Bus (minted fresh per session in run_session())
        self.bus: MessageBus = MessageBus(run_id="", conversation_id="")

        # Build the full roster spec so we know every agent_id before constructing.
        _roster_specs = (
            [{"agent_id": f"physician-{s['id_suffix']}", "panel": "physician", **s}
             for s in DIAGNOSTICS_SPECIALISTS]
            + [{"agent_id": f"pharmacologist-{s['id_suffix']}", "panel": "pharmacology", **s}
               for s in PHARMACY_SPECIALISTS]
        )
        _all_peer_desc = {
            sp["agent_id"]: ROLE_DESCRIPTIONS.get(sp["role"], sp["role"])
            for sp in _roster_specs
        }

        # Flat specialist roster — each agent is independent, owns its own LLMClient
        self.specialists: List[SpecialistAgent] = [
            SpecialistAgent(
                agent_id=sp["agent_id"],
                role=sp["role"], focus=sp["focus"],
                prior_belief=sp.get("prior_belief", ""), panel=sp["panel"],
                llm=_make_llm(sp["agent_id"]), bus=self.bus,
                llm_factory=_make_llm,
                peer_descriptions={k: v for k, v in _all_peer_desc.items() if k != sp["agent_id"]},
            )
            for sp in _roster_specs
        ]

        # Orchestrator for the joint panel — passes llm_factory so L9 owns ToM internally
        self.orchestrator = DebateOrchestrator(
            specialists=self.specialists,
            memory=self.memory,
            message_bus=self.bus,
            llm_factory=_make_llm,
            llm=self.coordinator_llm,
        )

        # Register all handlers once — they survive across sessions.
        self.bus.register_handler(
            HCPanelMemory.AGENT_ID,
            lambda hdr, _m=self.memory, _b=self.bus: _m.handle(hdr, _b),
        )
        for _agent in self.specialists:
            _agent.wire_up_l9(self.bus)
            self.bus.register_handler(
                _agent.agent_id,
                lambda hdr, _a=_agent: (
                    _a.dispatch_intent(hdr) if hdr.get("kind") == "intent"
                    else _a.dispatch_commit(hdr) if (
                        hdr.get("kind") == "commit" and hdr.get("subkind") == "converged"
                    )
                    else _a.dispatch_propose(hdr) if (
                        hdr.get("kind") == "exchange"
                        and any(p.get("type") == "siep-ctx" for p in hdr.get("payload", []))
                    )
                    else None
                ),
            )

        self.graph = self._build_graph()

    # ------------------------------------------------------------------ graph

    def _build_graph(self):
        graph = StateGraph(DebateGraphState)
        graph.add_node("orchestrate", self._node_orchestrate)
        graph.add_node("joint_panel", self._node_joint_panel)
        graph.add_node("coordination", self._node_coordination)
        graph.add_edge(START, "orchestrate")
        graph.add_edge("orchestrate", "joint_panel")
        graph.add_edge("joint_panel", "coordination")
        graph.add_edge("coordination", END)
        return graph.compile()

    # ------------------------------------------------------------------ nodes

    def _node_orchestrate(self, state: DebateGraphState) -> Dict[str, Any]:
        """Patient intake and team formation prep."""
        patient = state["patient"]
        episode_id = state["episode_id"]
        log: List[str] = list(state.get("orchestration_log", []))

        LOGGER.info(
            "node.orchestrate episode=%s patient=%s symptoms=%d meds=%d",
            episode_id, patient.patient_id,
            len(patient.symptoms), len(patient.current_medications),
        )

        log.append(f"orchestrate:specialists={len(self.specialists)}")
        # Snapshot only new messages (bus is empty at orchestrate entry)
        return {
            "orchestration_log": log,
            "wire_trace": self.bus.messages[:],
        }

    def _node_joint_panel(self, state: DebateGraphState) -> Dict[str, Any]:
        """Team-process preamble + SIEP star negotiation with inline CIP gating."""
        patient = state["patient"]
        episode_id = state["episode_id"]
        log: List[str] = list(state.get("orchestration_log", []))

        LOGGER.info("node.joint_panel episode=%s patient=%s", episode_id, patient.patient_id)

        outcome = self.orchestrator.run_joint_panel(
            patient=patient,
            episode_id=episode_id,
        )

        log.append(
            f"joint_panel:resolution={outcome.resolution_label}"
            f":cause={outcome.symptom_conclusion}"
            f":gar={outcome.gar:.4f}:scr={outcome.scr:.4f}:mpc={outcome.mpc:.4f}"
        )
        _offset = len(state.get("wire_trace", []))
        return {
            "outcome": outcome,
            "orchestration_log": log,
            "wire_trace": list(state["wire_trace"]) + self.bus.messages[_offset:],
        }

    def _node_coordination(self, state: DebateGraphState) -> Dict[str, Any]:
        """Promote per-agent stores, store episode."""
        episode_id = state["episode_id"]
        outcome: Optional[ClinicalDebateOutcome] = state.get("outcome")
        log: List[str] = list(state.get("orchestration_log", []))

        if outcome is None:
            log.append("coordination:outcome=missing error=no_outcome_produced")
            return {"orchestration_log": log, "error": "no_outcome_produced"}

        log.append(
            f"coordination:complete"
            f":resolution={outcome.resolution_label}"
            f":specialists={len(outcome.specialist_opinions)}"
        )
        LOGGER.info(
            "node.coordination episode=%s resolution=%s cause=%s gar=%.4f scr=%.4f",
            episode_id, outcome.resolution_label, outcome.symptom_conclusion,
            outcome.gar, outcome.scr,
        )
        _offset = len(state.get("wire_trace", []))
        return {
            "outcome": outcome,
            "orchestration_log": log,
            "wire_trace": list(state["wire_trace"]) + self.bus.messages[_offset:],
        }

    # ------------------------------------------------------------------ helpers

    def _drain_all_llm_traces(self) -> list:
        """Collect and clear trace records from every per-agent LLMClient."""
        records = self.coordinator_llm.drain_trace()
        for s in self.specialists:
            records += s.drain_llm_trace()
        return records

    # ------------------------------------------------------------------ session

    def run_session(self, patient: PatientProfile) -> HealthcareEpisode:
        episode_id = f"urn:ioc:hcpanel:episode:{patient.patient_id}:{uuid.uuid4()}"
        run_id = f"hcpanel-{uuid.uuid4()}"
        cid = f"hcpanel-session-{patient.patient_id}-{uuid.uuid4().hex[:8]}"
        token = set_correlation_id(cid)

        LOGGER.info(
            "session.start patient=%s episode=%s",
            patient.patient_id, episode_id,
        )
        try:
            self.bus.messages = []
            for agent in self.specialists:
                agent.reset_session()

            initial_state: DebateGraphState = {
                "patient": patient,
                "episode_id": episode_id,
                "run_id": run_id,
                "orchestration_log": [],
                "wire_trace": [],
                "outcome": None,
                "error": None,
            }
            final_state: DebateGraphState = self.graph.invoke(initial_state)

            outcome: Optional[ClinicalDebateOutcome] = final_state.get("outcome")
            all_messages = list(final_state.get("wire_trace", []))

            llm_trace = self._drain_all_llm_traces()
            episode = HealthcareEpisode(
                episode_id=episode_id,
                patient_id=patient.patient_id,
                outcome=outcome,
                wire_trace=all_messages,
                orchestration_log=list(final_state.get("orchestration_log", [])),
                llm_trace=llm_trace,
                timestamp_unix=int(time.time()),
            )
            self.memory.store_episode(episode)
            self.memory.save()

            LOGGER.info(
                "session.complete patient=%s episode=%s resolution=%s cause=%s gar=%.4f",
                patient.patient_id, episode_id,
                outcome.resolution_label if outcome else "none",
                outcome.symptom_conclusion if outcome else "none",
                outcome.gar if outcome else 0.0,
            )
            return episode
        finally:
            reset_correlation_id(token)


# ------------------------------------------------------------------ serialization

def serialize_episode_output(episode: HealthcareEpisode) -> Dict[str, Any]:
    outcome = episode.outcome
    if outcome is None:
        return {
            "episode_id": episode.episode_id,
            "patient_id": episode.patient_id,
            "error": "no_outcome_produced",
            "orchestration_log": episode.orchestration_log,
            "trace": episode.wire_trace,
            "llm_trace": [],
        }
    return {
        "episode_id": episode.episode_id,
        "patient_id": episode.patient_id,
        "timestamp_unix": episode.timestamp_unix,
        "symptom_conclusion": outcome.symptom_conclusion,
        "drug_interaction_risk": outcome.drug_interaction_risk,
        "proposed_drug_changes": outcome.proposed_drug_changes,
        "joint_recommendation": outcome.joint_recommendation,
        "resolution_label": outcome.resolution_label,
        "convergence_metrics": {
            "gar": outcome.gar,
            "scr": outcome.scr,
            "mpc": outcome.mpc,
        },
        "specialist_opinions": [
            {
                "specialist_id": op.specialist_id,
                "specialty": op.specialty,
                "panel": op.panel,
                "likely_cause": op.likely_cause,
                "confidence": op.confidence,
                "posterior": op.posterior,
                "drug_change_proposal": op.drug_change_proposal,
                "symptom_assessment": op.symptom_assessment,
                "reasoning": op.reasoning,
                "supporting_evidence": op.supporting_evidence,
            }
            for op in outcome.specialist_opinions
        ],
        # Full wire traces for trace rendering
        "trace": episode.wire_trace,
        "llm_trace": episode.llm_trace,
        "debate_log": outcome.debate_log,
        "orchestration_log": episode.orchestration_log,
    }


# ------------------------------------------------------------------ run_simulations

def run_simulations(
    sessions: int,
    seed: int,
    llm_backend: str,
    model: str,
    patients_file: Path,
    memory_store_file: Path,
) -> Dict[str, Any]:
    LOGGER.info(
        "simulations.start sessions=%d seed=%d backend=%s model=%s",
        sessions, seed, llm_backend, model,
    )
    rng = random.Random(seed)
    system = HCPanelSystem(
        llm_backend=llm_backend,
        model=model,
        memory_store_file=memory_store_file,
    )
    patients = load_patients(patients_file)
    outputs: List[Dict[str, Any]] = []

    for index in range(sessions):
        patient = rng.choice(patients)
        LOGGER.info(
            "simulations.session_start index=%d/%d patient=%s",
            index + 1, sessions, patient.patient_id,
        )
        episode = system.run_session(patient=patient)
        outputs.append(serialize_episode_output(episode))
        LOGGER.info(
            "simulations.session_complete index=%d/%d patient=%s resolution=%s",
            index + 1, sessions, patient.patient_id,
            (episode.outcome.resolution_label if episode.outcome else "none"),
        )

    LOGGER.info("simulations.complete sessions=%d", sessions)
    return {
        "application": "HCPanel — Joint Clinical Debate",
        "overall_task": _TASK_GOAL,
        "sessions": sessions,
        "episodes": outputs,
    }


# ------------------------------------------------------------------ main

def main() -> None:
    parser = argparse.ArgumentParser(description="HCPanel — Joint Clinical Debate")
    parser.add_argument("-n", "--sessions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm-backend", choices=["azure", "anthropic", "simulated"], default="simulated")
    parser.add_argument("--model", default="gpt-5")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--patients-file", default=str(PATIENTS_FILE))
    parser.add_argument("--memory-store-file", default=str(MEMORY_STORE_FILE))
    parser.add_argument(
        "--fresh-memory",
        action="store_true",
        help="Start with an empty memory store in a private temp file",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    app_cid = f"hcpanel-app-{uuid.uuid4().hex[:8]}"
    token = set_correlation_id(app_cid)

    memory_file = Path(args.memory_store_file)
    if args.fresh_memory:
        _fd, _tmp = tempfile.mkstemp(suffix=".json", prefix="hcpanel_memory_")
        os.close(_fd)
        os.unlink(_tmp)
        memory_file = Path(_tmp)

    LOGGER.info(
        "app.start sessions=%d backend=%s model=%s fresh_memory=%s",
        args.sessions, args.llm_backend, args.model, args.fresh_memory,
    )

    try:
        if args.sessions <= 0:
            raise ValueError("--sessions must be > 0")
        result = run_simulations(
            sessions=args.sessions,
            seed=args.seed,
            llm_backend=args.llm_backend,
            model=args.model,
            patients_file=Path(args.patients_file),
            memory_store_file=memory_file,
        )
        result["llm_backend"] = args.llm_backend
        result["model"] = args.model
        LOGGER.info("app.complete")
        print(json.dumps(result, indent=2))
    finally:
        reset_correlation_id(token)


if __name__ == "__main__":
    main()
