"""
L9 SDK — Fluent builder for constructing L9Protocol objects.

Usage:
    from l9.sdk import L9Builder
    from l9.shared import Knowledge, EvidenceBundle
    from l9.communication import QueryRequest
    from l9.validation import LearningOutcome, ValidationSubKind

    protocol = (
        L9Builder()
        .teamwork()
            .hire("agent-nlp", knowledge=[Knowledge(domain="NLP", facts=["tokenization"])])
            .hire("agent-plan", knowledge=[Knowledge(domain="Planning", facts=["PDDL"])])
        .goal()
            .attach(EvidenceBundle(bundle_id="b-1", source="rag", content=["doc A"]))
            .commit(
                goal="Build a summarizer",
                intent="Reduce reading time",
                problems=["ambiguous scope"],
                solution="Limit to 3 sentences",
            )
        .planning()
            .task("tokenize-input")
            .task("generate-summary")
            .allocate("tokenize-input", "agent-nlp")
            .depend("generate-summary", on="tokenize-input")
        .communication()
            .query(QueryRequest(query_id="q-1", query_text="NLP papers", target="rag"))
            .ingest(EvidenceBundle(bundle_id="b-2", source="rag", content=["doc B"]))
        .validation()
            .mode(ValidationSubKind.ONLINE)
            .learn(LearningOutcome(
                source_validation_id="val-1",
                updated_knowledge=[Knowledge(domain="NLP", facts=["summarization"])],
                insights=["Short summaries score higher"],
            ))
        .build()
    )
"""

from __future__ import annotations

from typing import List, Optional

from l9 import L9Protocol
from l9.shared import Knowledge, EvidenceBundle
from l9.teamwork import AgentHiringKind
from l9.goal_intent import GoalIntentKind, ConsensusCommitPayload
from l9.planning import PlanningKind
from l9.communication import CommunicationKind, QueryRequest
from l9.validation import ValidationKind, LearningOutcome, ValidationSubKind


# ─────────────────────────────────────────────────────────────────────────────
# Phase builders — each returns the parent L9Builder for chaining
# ─────────────────────────────────────────────────────────────────────────────

class TeamworkBuilder:
    """Fluent builder for Phase 1 — AgentHiring (teamwork)."""

    def __init__(self, parent: L9Builder) -> None:
        self._parent = parent
        self._kind = AgentHiringKind()

    def hire(
        self,
        agent_id: str,
        role: str = "",
        knowledge: Optional[List[Knowledge]] = None,
    ) -> TeamworkBuilder:
        """Register an agent with optional role and knowledge domains."""
        self._kind.state.available_agents.append(agent_id)
        if role:
            self._kind.state.assigned_agents[role] = agent_id
            self._kind.state.team.append(agent_id)
        for k in (knowledge or []):
            self._kind.register_knowledge(agent_id, k)
        return self

    # ── navigation back to parent phases ──

    def goal(self) -> GoalIntentBuilder:
        return self._parent.goal()

    def planning(self) -> PlanningBuilder:
        return self._parent.planning()

    def communication(self) -> CommunicationBuilder:
        return self._parent.communication()

    def validation(self) -> ValidationBuilder:
        return self._parent.validation()

    def build(self) -> L9Protocol:
        return self._parent.build()


class GoalIntentBuilder:
    """Fluent builder for Phase 2 — GoalIntent."""

    def __init__(self, parent: L9Builder) -> None:
        self._parent = parent
        self._kind = GoalIntentKind()

    def attach(self, bundle: EvidenceBundle) -> GoalIntentBuilder:
        """Attach an EvidenceBundle to the goal context."""
        self._kind.attach_evidence(bundle)
        return self

    def commit(
        self,
        goal: str,
        intent: str = "",
        problems: Optional[List[str]] = None,
        solution: str = "",
        supporting_bundles: Optional[List[EvidenceBundle]] = None,
    ) -> GoalIntentBuilder:
        """Record a consensus commit."""
        payload = ConsensusCommitPayload(
            goal_specified=goal,
            intent_behind_it=intent,
            problems_found=problems or [],
            solution=solution,
            supporting_bundles=supporting_bundles or self._kind.state.evidence_bundles[:],
        )
        self._kind.consensus_commit(payload)
        return self

    # ── navigation ──

    def teamwork(self) -> TeamworkBuilder:
        return self._parent.teamwork()

    def planning(self) -> PlanningBuilder:
        return self._parent.planning()

    def communication(self) -> CommunicationBuilder:
        return self._parent.communication()

    def validation(self) -> ValidationBuilder:
        return self._parent.validation()

    def build(self) -> L9Protocol:
        return self._parent.build()


class PlanningBuilder:
    """Fluent builder for Phase 3 — Planning."""

    def __init__(self, parent: L9Builder) -> None:
        self._parent = parent
        self._kind = PlanningKind()

    def task(self, task_id: str) -> PlanningBuilder:
        """Add a task to the plan."""
        self._kind.state.tasks.append(task_id)
        return self

    def allocate(self, task_id: str, agent_id: str) -> PlanningBuilder:
        """Assign a task to an agent."""
        self._kind.state.resource_map[task_id] = agent_id
        return self

    def depend(self, task_id: str, on: str) -> PlanningBuilder:
        """Declare that task_id depends on another task."""
        self._kind.state.dependencies.setdefault(task_id, []).append(on)
        return self

    def commit(self) -> PlanningBuilder:
        """Mark the plan as committed."""
        self._kind.state.plan_committed = True
        return self

    # ── navigation ──

    def teamwork(self) -> TeamworkBuilder:
        return self._parent.teamwork()

    def goal(self) -> GoalIntentBuilder:
        return self._parent.goal()

    def communication(self) -> CommunicationBuilder:
        return self._parent.communication()

    def validation(self) -> ValidationBuilder:
        return self._parent.validation()

    def build(self) -> L9Protocol:
        return self._parent.build()


class CommunicationBuilder:
    """Fluent builder for Phase 4 — Communication."""

    def __init__(self, parent: L9Builder) -> None:
        self._parent = parent
        self._kind = CommunicationKind()

    def query(self, request: QueryRequest) -> CommunicationBuilder:
        """Issue a query to retrieve an EvidenceBundle."""
        self._kind.query(request)
        return self

    def ingest(self, bundle: EvidenceBundle) -> CommunicationBuilder:
        """Absorb an EvidenceBundle into shared state."""
        self._kind.ingest(bundle)
        return self

    def message(self, sender: str, receiver: str, content: str) -> CommunicationBuilder:
        """Log an agent-to-agent message."""
        self._kind.state.message_log.append(
            {"sender": sender, "receiver": receiver, "content": content}
        )
        return self

    def state(self, key: str, value: object) -> CommunicationBuilder:
        """Set a value in shared state."""
        self._kind.state.shared_state[key] = value
        return self

    # ── navigation ──

    def teamwork(self) -> TeamworkBuilder:
        return self._parent.teamwork()

    def goal(self) -> GoalIntentBuilder:
        return self._parent.goal()

    def planning(self) -> PlanningBuilder:
        return self._parent.planning()

    def validation(self) -> ValidationBuilder:
        return self._parent.validation()

    def build(self) -> L9Protocol:
        return self._parent.build()


class ValidationBuilder:
    """Fluent builder for Phase 5 — Validation."""

    def __init__(self, parent: L9Builder) -> None:
        self._parent = parent
        self._kind = ValidationKind()

    def mode(self, sub_kind: ValidationSubKind) -> ValidationBuilder:
        """Set the validation mode."""
        self._kind.state.validation_mode = sub_kind
        return self

    def result(self, passed: bool, detail: Optional[dict] = None) -> ValidationBuilder:
        """Record a validation result."""
        self._kind.state.passed = passed
        self._kind.state.results.append({"passed": passed, **(detail or {})})
        return self

    def learn(self, outcome: LearningOutcome) -> ValidationBuilder:
        """Record a learning outcome derived from validation."""
        self._kind.learn(outcome)
        return self

    # ── navigation ──

    def teamwork(self) -> TeamworkBuilder:
        return self._parent.teamwork()

    def goal(self) -> GoalIntentBuilder:
        return self._parent.goal()

    def planning(self) -> PlanningBuilder:
        return self._parent.planning()

    def communication(self) -> CommunicationBuilder:
        return self._parent.communication()

    def build(self) -> L9Protocol:
        return self._parent.build()


# ─────────────────────────────────────────────────────────────────────────────
# Root builder
# ─────────────────────────────────────────────────────────────────────────────

class L9Builder:
    """
    Fluent builder for L9Protocol.

    Entry points (any phase can be started first):
        .teamwork()      → TeamworkBuilder
        .goal()          → GoalIntentBuilder
        .planning()      → PlanningBuilder
        .communication() → CommunicationBuilder
        .validation()    → ValidationBuilder
        .build()         → L9Protocol
    """

    def __init__(self) -> None:
        self._teamwork     = TeamworkBuilder(self)
        self._goal         = GoalIntentBuilder(self)
        self._planning     = PlanningBuilder(self)
        self._communication = CommunicationBuilder(self)
        self._validation   = ValidationBuilder(self)

    def teamwork(self) -> TeamworkBuilder:
        return self._teamwork

    def goal(self) -> GoalIntentBuilder:
        return self._goal

    def planning(self) -> PlanningBuilder:
        return self._planning

    def communication(self) -> CommunicationBuilder:
        return self._communication

    def validation(self) -> ValidationBuilder:
        return self._validation

    def build(self) -> L9Protocol:
        """Assemble and return a validated L9Protocol."""
        return L9Protocol(
            agent_hiring=self._teamwork._kind,
            goal_intent=self._goal._kind,
            planning=self._planning._kind,
            communication=self._communication._kind,
            validation=self._validation._kind,
        )
