# Why Layer 9?

## The problem with agent APIs today

Today's interactions between agents are mostly API/RPC based: it sends
a request and gets back a response.  The exchange is purely syntactic
a structured message goes out, a structured message comes
back.  Nothing in that exchange asks whether the response actually
engaged the request, whether the two systems now share the same
understanding, or whether the answer made any sense given what was
asked.  Agents in a multi-agent system work the same way.  Each agent
is essentially an API: it takes in a prompt and returns a
completion. 

This works well enough when agents are pipelines — when one agent's
output feeds the next and the task decomposes into independent
steps and operations are deterministic.  Today's agentic tasks are not
like this anymore: real agentic apps require agents to reason jointly,
revise their positions in light of what others say, and converge on a
shared answer that none of them could have reached alone.  For that,
syntactic exchange is simply not enough anymore.

The next level up is *semantic* communication: agents don't just
exchange structured tokens, they exchange *facts* — propositions with
meaning.  Agent A tells Agent B that the patient has a drug
interaction risk.  The message carries a claim about the world.  But
even this is insufficient, because facts don't have degrees, and
agents don't hold facts — they hold *beliefs* about facts, with
varying degrees of confidence.  Agent A might be 85% sure about the
drug interaction. Agent B might be 40% sure and have contrary
evidence. If the protocol treats their assertions as equivalent facts
to be tallied, the system discards exactly the information that
matters.

The level above semantics is *epistemic* communication: agents
exchange beliefs that are calibrated about concepts, backed by
evidence, with uncertainty quantified.  This is what L9 is designed to
carry.  An L9 interaction, or session, is not based on a
request-response cycle anymore.  It is an epistemic act where
participants go back and forth until the issue has been addressed.  A
typical interaction may look like: "here is my belief about this
concept, here is my evidence, here is my uncertainty, and here is the
prior I arrived at independently before talking to you."

## Why most MAS applications fail

Cemri et al.'s [ https://arxiv.org/abs/2503.13657 ] describes cases
where agents fail to understand their tasks, repeat themselves, enter
conversational loops with peers, jointly derail conversations, and
fail to detect when their own outputs have become nonsensical.  These
are not edge cases but happen frequently.  The Cooper Benchmark [
https://arxiv.org/abs/2601.13295 ] confirms this: scaling individual
model intelligence does not fix them.

In [ https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6736398 ] a
position is provided how to address MAS failures. With current MAS
interaction technology, failures are structural. They arise from the
absence of the *collective cognitive scaffolds* that human teams use
to function as a coherent unit.  Individual intelligence improvements
cannot substitute for these scaffolds, because the failures are not
failures of individual reasoning — they are failures of *collective*
reasoning. 

Human teams are characterized not just by who is on the team and what
they know, but by *how team members interact*. Organizational
psychology distinguishes two fundamentally different things happening
inside any collaborative team: 

- **Taskwork** — what the team works on: the task requirements, the
  plans, the actual execution of the work. 
- **Teamwork** — how team members work together toward goals:
  coordination, role clarity, communication patterns, conflict
  resolution, shared mental models.

Current MAS systems conflate at best, but more likely ignore
both taskwork and teamwork.  Agents are handed a task and left to sort
out the rest. There is no explicit team formation, no agreed process,
no common understanding of who defers to whom on which
question.  Individual agent competence cannot reliably produce
collective outcomes without this structure as confirmed in the cited
papers. 

The paper identifies three essential processes every effective
collaborative team relies on, drawn from the Marks, Mathieu & Zaccaro
taxonomy of team processes:

- **TransitionTeam processes** (team process): task analysis, goal
  specification, strategy formulation — agreeing on *how* the team
  will work before the work begins. 
- **Action processes** (taskwork): monitoring goal progress,
  coordinating, actually executing the task with the team structure in
  place. 
- **Interpersonal processes**: managing conflict, maintaining
  motivation — the ongoing work of keeping a team functional.

Without the first, agents have no shared basis for
coordination. Without the second, individual outputs accumulate
without converging. Without the third, disagreements derail rather
than resolve.

## What L9 does

L9 is a MAS agent communication system designed to realize all three
collaborative processes used by humans applicable in MAS applications.
L9 is a *protocol layer* — a shared medium that carries, on every
message, the information that collective, i.e., inside the entire MAS,
cognition requires: the concept under discussion, the sending agent's
epistemic state, the phase of reasoning the team is in, and a typed
payload for the sub-protocol doing the specific epistemic work.

L9 provides structure for three phases that all serious collaborative
tasks require.

All processes in L9 are centered around episode, a sequentual set of
steps to go from "intent" to do something, "exchange" positions
between agents, to "commiting" to an outcome.  If "knowledge" is
created it can be independently established in a free-standing
episode.

**Team process.** Before any task begins, the team must agree on who
is participating, what each participant is responsible for, and how
the group operates. This is a precondition for everything
executing task work debates and tasks themselves.  Without it, agents
have no grounds for recognizing when a peer has gone off-task, no
basis for weighting whose expertise matters on which question, and no
shared understanding of when the task is done.  A team process
resolution is run as an episode: it has an intent, produces
agreements, and closes with a committed record of who is responsible
for what.

**Taskwork.** Once the team is formed, agents execute a process to
establish the task at hand. This means agents debate a coordinator's
proposal on the task at hand, establish independent beliefs about the
task (*priors*) before engaging each other in the execution step.  An
agent that has not reasoned independently has nothing genuine to
contribute as conversations must be grounded in reality; in such cases
where no prior agreement is, agents simply agree with whoever spoke
last.  Once priors are formed, agents exchange positions through
structured episodes: an intent opens the negotiation, exchanges carry
arguments and counter-arguments with explicit evidence and
uncertainty, contingencies address breakdowns in grounding, and a
commit closes the episode with a recorded outcome that the team acted
on.

**Task execution.**  Task execution is the actual work the team agreed
to perform.  In the Healthcare panel example in this repository, this
is the joint clinical debate: the coordinator proposes a diagnosis,
each specialist responds with their own evidence-backed position, and
the group negotiates until a resolution emerges.  Additional debate
happens here too where specialists counter-propose, evidence is
contested, and contingencies open when a response fails to engage what
the prior turn actually claimed.  The episode closes with a committed
outcome and a quality record: how many agents genuinely agreed,
whether any were simply pressured into compliance, and what the
collective confidence level was.  That quality record is what
distinguishes a trustworthy team decision from a nominal one.

This three-phase structure is presented sequentially for clarity. In
practice, MAS applications, just like human teams, bounce between
phases continuously.  When a task gets stuck, the taskwork may need to
be redebated, when the taskwork process cannot align on the task at
hand, maybe the team process agreement needs to be addressed.  This
can happen during the execution of episodes.

[Teams and tasks goes into more detail](./L9teamtask.md)

## Semantics and epistemics dynamicity

The kinds of epistemic problems a MAS encounters are not
fixed.  Different application domains require different kinds of
convergence.  A team of clinical agents debating drug interactions
faces different epistemic challenges than a team of legal agents
debating contract interpretation, or financial agents debating 
risk exposure.  The relevant evidence types differ, the appropriate
uncertainty representations differ, the resolution conditions differ.

The different kind of epistemic problems means there cannot be one
single universal convergence protocol. To cater for this, L9 provides
for a stable header carrying whatever is required for any epistemic
exchange, with typed, extensible payloads for the sub-protocol doing
the domain-specific work. 

The L9 header carries the universal fields: who is speaking, to whom,
about what concept, what semantic facts, in what epistemic state, with
what conviction it holds its beliefs, and in what episode is
executing.  Its payload carries typed parts defined by the active
sub-protocol. Today, L9 defines two sub-protocols:

- **CIP (Contingency Interaction Protocol)**: the pairwise grounding
  sub-protocol.  It verifies that exchanges are genuine and engaged
  the prior turn's argument.  It handles repair when there is not a
  genuine conversation.  Without CIP, apparent agreement little:
  agents can converge on nonsense while appearing to have reasoned
  together. [Contingency Interaction
  Protocol](../subprotocol/cip/docs/CIP.md)
- **SIEP (Semantic Interaction Exchange Protocol)**: the group
  convergence sub-protocol.  It structures multi-agent negotiation to
  produce a single team decision with measurable quality — how broadly
  the team agreed (GAR), whether any participant capitulated without
  being persuaded (SCR), and what the mean confidence of the
  participating agents was (MPC). [Semantic Interaction Exchange
  Protocol](../subprotocol/siep/docs/SIEP.md)

New sub-protocols can be added without changing the envelope. A
protocol for temporal belief revision: for example, what happens when
a committed outcome goes stale because the world changed, can be
defined as a new payload type.  A protocol for second-order epistemic
uncertainty can be added the same way.  L9 is not a closed system.  It
is an envelope that can carry whatever structured epistemic work the
application requires, as long as that work can be expressed as typed
payload parts within an episode. 

That extensibility is not a convenience feature.  As stated before,
semantic and epistemic problems evolve with the domain, the
application, and with what the research community learns about how
agents actually fail. The envelope must outlast any particular version
of the sub-protocols it carries.

