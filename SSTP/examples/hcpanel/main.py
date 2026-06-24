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

from SSTP.subprotocol.siep.src.epistemic.stores import (
    AgentBeliefStore, AgentEpistemicStore, PeerInteractionStore, TaskworkStore,
)
from SSTP.examples.hcpanel.tem import TeamEpistemicMemoryAgent
from SSTP.subprotocol.siep.src.tomcore.cognition import TheoryOfMindEngine

from SSTP.examples.hcpanel.agent_bus import HCPanelAgentBus
from SSTP.examples.hcpanel.specialists import PharmacologyController, PhysicianController
from SSTP.examples.hcpanel.domain import (
    ClinicalDebateOutcome,
    DebateGraphState,
    HealthcareEpisode,
)
from SSTP.examples.hcpanel.llm_backends import (
    AnthropicHealthcareLLMClient,
    AzureOpenAIHealthcareLLMClient,
    SimulatedHealthcareLLMClient,
)
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
        # LLM backend selection
        if llm_backend == "azure":
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_key = os.getenv("AZURE_OPENAI_KEY")
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
            if endpoint and api_key:
                try:
                    self.llm = AzureOpenAIHealthcareLLMClient(
                        endpoint=endpoint, api_key=api_key,
                        api_version=api_version, model=model,
                    )
                except Exception:
                    LOGGER.warning("hcpanel.llm_fallback reason=azure_init_failed")
                    self.llm = SimulatedHealthcareLLMClient()
            else:
                LOGGER.warning("hcpanel.llm_fallback reason=missing_azure_env")
                self.llm = SimulatedHealthcareLLMClient()
        elif llm_backend == "anthropic":
            api_key = os.getenv("LITELLM_API_KEY")
            base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.prod.outshift.ai")
            litellm_model = os.getenv(
                "LITELLM_HAIKU_MODEL",
                "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
            )
            if api_key:
                try:
                    self.llm = AnthropicHealthcareLLMClient(
                        api_key=api_key, base_url=base_url, model=litellm_model,
                    )
                except Exception:
                    LOGGER.warning("hcpanel.llm_fallback reason=anthropic_init_failed")
                    self.llm = SimulatedHealthcareLLMClient()
            else:
                LOGGER.warning("hcpanel.llm_fallback reason=missing_litellm_key")
                self.llm = SimulatedHealthcareLLMClient()
        else:
            self.llm = SimulatedHealthcareLLMClient()

        # Coordinator-level memory (no per-agent stores here)
        self.memory = HCPanelMemory(memory_store_file)
        self.memory.load()

        # Team Epistemic Memory agent (cross-episode knowledge)
        self.team_epistemic_agent = TeamEpistemicMemoryAgent(
            store_path=memory_store_file.parent / "hcpanel_team_epistemic.json",
            use_case="healthcare",
        )

        # ToM engine — drives assess_utterance + predict_peer_response per SNP exchange
        self.tom = TheoryOfMindEngine(self.llm)

        # Bus (minted fresh per session in run_session())
        self.bus: HCPanelAgentBus = HCPanelAgentBus(run_id="", conversation_id="")

        # Per-agent-owning controllers — no stores on the controller itself
        self.physician_ctrl = PhysicianController(self.llm, bus=self.bus)
        self.pharmacy_ctrl = PharmacologyController(self.llm, bus=self.bus)

        # Orchestrator for the joint panel
        self.orchestrator = DebateOrchestrator(
            physician_ctrl=self.physician_ctrl,
            pharmacy_ctrl=self.pharmacy_ctrl,
            memory=self.memory,
            ie_bus=self.bus,
            tom_engine=self.tom,
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
        """Patient intake, team formation, prior alignment."""
        patient = state["patient"]
        episode_id = state["episode_id"]
        log: List[str] = list(state.get("orchestration_log", []))

        LOGGER.info(
            "node.orchestrate episode=%s patient=%s symptoms=%d meds=%d",
            episode_id, patient.patient_id,
            len(patient.symptoms), len(patient.current_medications),
        )

        semantic_rules = (
            list(self.memory.semantic_rule_store._store.values())
            if hasattr(self.memory.semantic_rule_store, "_store") else []
        )
        # Pass episode_id=None to suppress bus emission — positions are re-emitted
        # inside Episode B (taskwork) in run_joint_panel().
        physician_positions = self.physician_ctrl.assess_all(
            patient, episode_id=None,
            likelihood_store=self.memory.likelihood_store,
            semantic_rules=semantic_rules,
        )
        pharmacy_positions = self.pharmacy_ctrl.assess_all(
            patient, episode_id=None,
            likelihood_store=self.memory.likelihood_store,
            semantic_rules=semantic_rules,
        )
        log.append(f"orchestrate:physician_positions={len(physician_positions)}")
        log.append(f"orchestrate:pharmacy_positions={len(pharmacy_positions)}")
        # Snapshot only new messages (bus is empty at orchestrate entry)
        return {
            "orchestration_log": log,
            "agent_messages": self.bus.messages[:],
            "physician_positions": physician_positions,
            "pharmacy_positions": pharmacy_positions,
        }

    def _node_joint_panel(self, state: DebateGraphState) -> Dict[str, Any]:
        """Team-process preamble + SIEP star negotiation with inline CIP gating."""
        patient = state["patient"]
        episode_id = state["episode_id"]
        log: List[str] = list(state.get("orchestration_log", []))

        physician_positions: Dict[str, Any] = state.get("physician_positions", {})
        pharmacy_positions: Dict[str, Any] = state.get("pharmacy_positions", {})

        LOGGER.info(
            "node.joint_panel episode=%s physicians=%d pharmacologists=%d",
            episode_id,
            len(physician_positions),
            len(pharmacy_positions),
        )

        outcome = self.orchestrator.run_joint_panel(
            patient=patient,
            episode_id=episode_id,
            physician_positions=physician_positions,
            pharmacy_positions=pharmacy_positions,
        )

        log.append(
            f"joint_panel:resolution={outcome.resolution_label}"
            f":cause={outcome.symptom_conclusion}"
            f":gar={outcome.gar:.4f}:scr={outcome.scr:.4f}:mpc={outcome.mpc:.4f}"
        )
        snp_trace = list(state.get("snp_trace", [])) + outcome.snp_trace
        _offset = len(state.get("agent_messages", []))
        return {
            "outcome": outcome,
            "orchestration_log": log,
            "snp_trace": snp_trace,
            "agent_messages": list(state["agent_messages"]) + self.bus.messages[_offset:],
        }

    def _node_coordination(self, state: DebateGraphState) -> Dict[str, Any]:
        """Write kind=knowledge, promote per-agent stores, store episode."""
        episode_id = state["episode_id"]
        outcome: Optional[ClinicalDebateOutcome] = state.get("outcome")
        log: List[str] = list(state.get("orchestration_log", []))

        if outcome is None:
            log.append("coordination:outcome=missing error=no_outcome_produced")
            return {"orchestration_log": log, "error": "no_outcome_produced"}

        # star.run() already emits kind=knowledge on the panel episode for each convergence
        # result. We update TeamEpistemicMemory here without re-emitting to avoid duplicates.
        panel_episode_id = outcome.panel_episode_id or episode_id
        for truth in self.memory.convergence_store._store.values():
            provenance_weight = round(
                (1.0 - truth.social_compliance_ratio) * truth.genuine_agreement_ratio, 4
            )
            self.team_epistemic_agent.update(
                concept_id=truth.concept_id,
                posterior=truth.consensus_posterior,
                gar=truth.genuine_agreement_ratio,
                scr=truth.social_compliance_ratio,
                provenance_weight=provenance_weight,
                episode_id=episode_id,
            )

        # Promote peer outcomes to each SpecialistAgent's own PeerInteractionStore
        for agent in self.physician_ctrl.specialists + self.pharmacy_ctrl.specialists:
            agent.promote_peer_outcomes(episode_id=episode_id)

        log.append(
            f"coordination:knowledge_written=true"
            f":resolution={outcome.resolution_label}"
            f":specialists={len(outcome.specialist_opinions)}"
        )
        LOGGER.info(
            "node.coordination episode=%s resolution=%s cause=%s gar=%.4f scr=%.4f",
            episode_id, outcome.resolution_label, outcome.symptom_conclusion,
            outcome.gar, outcome.scr,
        )
        _offset = len(state.get("agent_messages", []))
        return {
            "outcome": outcome,
            "orchestration_log": log,
            "snp_trace": list(state.get("snp_trace", [])),
            "agent_messages": list(state["agent_messages"]) + self.bus.messages[_offset:],
        }

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
            # Fresh bus, ToM engine, and per-agent stores per session.
            # Agent state is strictly private — no epistemic state survives across sessions.
            self.bus = HCPanelAgentBus(run_id=run_id, conversation_id=run_id)
            self.tom = TheoryOfMindEngine(self.llm)
            self.orchestrator.tom_engine = self.tom
            for agent in self.physician_ctrl.specialists + self.pharmacy_ctrl.specialists:
                agent.bus = self.bus
                agent.belief_store = AgentBeliefStore()
                agent.peer_store = PeerInteractionStore()
                agent.taskwork_store = TaskworkStore()
                agent.epistemic_store = AgentEpistemicStore(agent.agent_id)
            self.physician_ctrl.bus = self.bus
            self.pharmacy_ctrl.bus = self.bus
            self.orchestrator.ie_bus = self.bus

            initial_state: DebateGraphState = {
                "patient": patient,
                "episode_id": episode_id,
                "run_id": run_id,
                "orchestration_log": [],
                "agent_messages": [],
                "snp_trace": [],
                "outcome": None,
                "error": None,
                "physician_positions": {},
                "pharmacy_positions": {},
            }
            final_state: DebateGraphState = self.graph.invoke(initial_state)

            outcome: Optional[ClinicalDebateOutcome] = final_state.get("outcome")
            snp_trace = list(final_state.get("snp_trace", []))
            all_messages = list(final_state.get("agent_messages", []))

            llm_trace = (
                self.llm.drain_trace()
                if hasattr(self.llm, "drain_trace")
                else []
            )
            episode = HealthcareEpisode(
                episode_id=episode_id,
                patient_id=patient.patient_id,
                outcome=outcome,
                agent_messages=all_messages,
                snp_trace=snp_trace,
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
            "ie_trace": episode.agent_messages,
            "snp_trace": episode.snp_trace,
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
        "ie_trace": episode.agent_messages,
        "snp_trace": outcome.snp_trace,
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
