## Why Layer-9?

Multi-agent systems do not work well. The Cooper Benchmark and the MAST taxonomy paper by
Cemri et al. demonstrate this empirically: agents fail to understand their tasks, repeat
themselves, enter loops with peer agents, jointly derail conversations, and fail to detect
when their own outputs have become nonsensical. These are not edge cases — they are the
default. The consequence is that MAS applications today are largely unreliable at scale,
and the failures are structural, not incidental. The root cause is that agents communicate
at a purely syntactic level.

Agent interactions today are semantically no different from traditional API calls: a request
goes out, a response comes back. Nothing in the exchange verifies that the response engaged
the request. Nothing detects when an agent has derailed. Nothing measures whether two agents
who appear to agree share the same understanding. Nonsense propagates undetected, corrupts
shared memory, and can bring down an entire application.

This is the problem L9, IE, and SNP exist to solve: L9 is an essential function to uplift
traditional agents as these are operating in a multi-agent system (MAS) from their traditional
API-style interactions, into one where these agents are discussion, negotiating and dismissing
epistemic state, or simply: knowledge.

L9 is about enabling agents in a MAS to debate and negotiate their ground truth, and be moved
into different positions on epistemics (= knowledge) given multi-agent social pressure or
general agreements. To get to these points, agents discuss "concepts", the knowledge at hand,
and use theory-of-mind-based convergence and grounding concepts to settle jointly on those
concepts. These discussions are called "episodes".

---

Consider the following "concept-id" as it is being carried in a sample MAS application
between a set of agentic physicians debating a patient's symptoms. This is the actual
concept as it is being carried in the L9 header:

| concept:drug\_interaction | Whether this patient has a medication interaction risk requiring specialist involvement | diagnostics ⇒ pharmacy panel |

---

Then in one or more episodes of an L9 conversation the physicians address their patient's
concerns (this shows only a snippet of the conversation):

| Kind | From | To | Op | Content | Supporting evidence | Addresses evidence | Reasoning |
|---|---|---|---|---|---|---|---|
| `intent` | diagnostics-controller | *(panel)* | — | `new_disease` | — | — | *(panel opens)* |
| `exchange` | diagnostics-controller | diag-internal-medicine | **propose** | `new_disease` | dizziness, fatigue | — | *"85% [cardiology]: new\_disease — dizziness, fatigue"* |
| `exchange` | diag-internal-medicine | diagnostics-controller | **counter\_proposal** | `drug_interaction` | dizziness, fatigue, known\_interaction, nausea | dizziness, fatigue, known\_interaction, nausea | *"85% [internal\_medicine]: drug\_interaction — engages known\_interaction"* |
| `exchange` | diagnostics-controller | diag-clinical-pharmacology | **propose** | `new_disease` | dizziness, fatigue | — | *controller does not revise* |
| `exchange` | diag-clinical-pharmacology | diagnostics-controller | **counter\_proposal** | `drug_interaction` | dizziness, known\_interaction, nausea | dizziness, known\_interaction, nausea | *"97% [clinical\_pharmacology]: drug\_interaction — highest confidence, most precise evidence"* |
| `exchange` | diagnostics-controller | diag-cardiology | **propose** | `new_disease` | dizziness, fatigue | — | *controller still does not revise* |
| `exchange` | diag-cardiology | diagnostics-controller | **accept** | `new_disease` | dizziness, fatigue | dizziness, fatigue | *"85% [cardiology]: accepts controller's proposal"* |
| `exchange` | diagnostics-controller | diag-neurology | **propose** | `new_disease` | dizziness, fatigue | — | — |
| `exchange` | diag-neurology | diagnostics-controller | **accept** | `new_disease` | dizziness, fatigue | dizziness, fatigue | *"85% [cardiology]: accepts"* |
| `exchange` | diagnostics-controller | diag-immunology | **propose** | `new_disease` | dizziness, fatigue | — | — |
| `exchange` | diag-immunology | diagnostics-controller | **accept** | `new_disease` | dizziness, fatigue | dizziness, fatigue | *"85% [cardiology]: accepts"* |
| `commit:converged` | diagnostics-controller | *(panel)* | accept | `new_disease` | — | — | *"new\_disease → accept posterior=0.9500 GAR=1.0 SCR=0.0"* |
| `knowledge` | diagnostics-controller | SemanticMemory | — | `urn:concept:healthcare:new_disease` | — | — | *rule\_update: gar=1.0 scr=0.0 provenance\_weight=1.0* |
