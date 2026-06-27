# Tuệ Mẫn

```
                                                              .---.
                                                             /  .  \
                                                            |\_/|   |
                                                            |   |  /|
  .----------------------------------------------------------------' |
 /  .-.                                                              |
|  /   \      An AI that remembers everything about one person.      |
| |\_.  |                                                            |
|\|  | /|              Built for depth. Not for scale.               |
| `---' |                                                            |
|       |        Probably overkill. Definitely intentional.          |
|       |                                                           /
|       |----------------------------------------------------------'
\       |
 \     /
  `---'
```

> *Better to have one person who truly understands you*  
> *than infinite people who only know your name.*

---

Tuệ Mẫn is not a chatbot.

It is a long-term cognitive architecture designed to understand a single person over years of interaction.

The objective is not to answer questions.

The objective is to build understanding.

---

## The premise 🥀

Most AI systems are built for millions of users.

They optimize for throughput. For retention. For engagement metrics.  
They get really good at talking to everyone —  
which means they never actually know anyone.

Meta AI will deploy inside the most-used chat app on earth  
and somehow still not reply when you tag it five times. 🤡

Tuệ Mẫn is the opposite bet.

**One user. Total understanding. No compromises.**

```
Production AI          │  Tuệ Mẫn
───────────────────────┼──────────────────────────────────────────
1,000,000 users        │  1 user. permanent.
~100 memories/user     │  100,000+ memories
"remembers your name"  │  remembers the version of you from 6 months ago
answer first           │  understand first
confident about nothing│  uncertain until the evidence says otherwise
goldfish memory 🐟     │  elephant memory 🐘
```

Not a product. Not a SaaS. Not a Series A pitch.  
An experiment in whether a machine can genuinely *know* a person.

---

## Core Philosophy

Every conclusion must be traceable.

Every belief must be supported by evidence.

Nothing is allowed to rewrite history.

Knowledge is accumulated.

Memory is never rewritten.

The world has enough chatbots that are very confident about things they made up. 🗿  
This one is built differently.

---

## Cognitive Architecture 💀

Six layers. One direction. No exceptions.

```
Layer 0 ─ Observation
│
│  Immutable.
│  Append-only.
│  Source of truth.
│  Touch it and the whole system collapses. 💀
│
▼
Layer 1 ─ Extraction
│
│  Mention Extraction
│  Entity Linking
│  Registry
│  Retrieval
│
▼
Layer 2 ─ Interpretation
│
│  Predicate Detection
│  Argument Resolution
│  Constraint Solving
│  Event Construction
│
▼
Layer 3 ─ Beliefs
│
│  Evidence Accumulation
│  Belief Revision
│  Unknown Resolution
│
▼
Layer 4 ─ Reflection
│
│  Long-term pattern discovery
│  Preference evolution
│  Personal understanding
│
▼
Layer 5 ─ Identity
│
│  Stable self-model
│  Persistent worldview
│
```

Each layer only sees what the layer below it produced.  
No layer can reach down and change what already happened.  
This is not a guideline. It is structural enforcement. 🥀

---

## Design Principles

### Observation is immutable

The original observation is never modified.

Every higher layer references evidence instead of rewriting it.

Raw observation is **sacred**.  
If interpretation could touch observation, the whole epistemology collapses.  
So it structurally cannot. Not a comment in the code. A constraint.

> *Nothing may rewrite observation.*

---

### Layers are firewalled

Higher layers cannot modify lower layers.

```
Observation
↓  (read only)
Extraction
↓  (read only)
Interpretation
↓  (read only)
Beliefs
↓  (read only)
Reflection
↓  (read only)
Identity
```

Information flows upward only.  
Conclusions cannot corrupt their own evidence.  
This is how the system avoids gaslighting itself. 🥲

---

### Uncertainty is preserved

Tuệ Mẫn does not force a single interpretation.

Layer 2 produces hypothesis distributions.  
Layer 3 accumulates evidence over time before committing to beliefs.

The system holds uncertainty as a first-class value.  
It doesn't collapse to a confident answer until the evidence warrants it.  
Somehow this is extremely rare in AI systems. 🤡

---

### Memory grows, not rewrites

New observations reinforce, weaken, or revise beliefs.

History is preserved.

The system remembers *why* something became true.  
If it was wrong, it remembers that too.  
Dead beliefs don't persist. The system can lose gracefully. 💀

---

## What it actually does 🔍

### Mention Extraction + Entity Registry

Before meaning: recognition.

Every message goes through a full extraction pipeline:

```
Message
  ↓
MentionExtractor (Dict + Hybrid LLM mode)
  ↓
EntityRegistry (persisted, versioned aliases)
  ↓
AliasResolution → EntityLinking → BM25Retrieval
```

It knows the difference between "he", "the guy", "Minh", and "that dude from the coffee shop last week" — because it built an alias graph.

Vietnamese capitalization edge cases? Handled.  
CamelCase tech names mid-sentence? Handled.  
Multi-word entity disambiguation? Handled.

**Span F1 on the gold dataset: 93%.** 🎯

---

### GraphLens — the same event hits different

When an event gets interpreted, it doesn't go through a neutral processor.  
It goes through a **GraphLens** — the system's full cognitive state at that exact moment:

```
Event
  ↓
GraphLens(active_concepts, unresolved_tensions, historical_biases, mood)
  ↓
Interpretation (confidence-scored, emotion-tagged)
  ↓
Concept Graph
```

The same message on a bad day vs. a good day produces genuinely different interpretations.  
This is a feature. Not a bug. Cognitive realism. 🥀

---

### Hypothesis Market

The system makes **falsifiable predictions** about you.

For every belief it forms, it generates `OrthogonalPredictions` —  
predictions about your future behavior that *cannot* be explained by the input that created the belief.

- Prediction confirms → belief gets stronger  
- Prediction expires → belief decays  
- Prediction gets refuted → belief takes damage  
- Belief can't predict anything → quietly buried 💀

The system can be wrong and it knows how to lose.  
This is how it avoids becoming a yes-machine.

---

### Voice Resolution Engine

Before every single reply, a `VoiceResolutionEngine` runs.

It outputs:
- `warmth` — how soft or direct to be
- `roast_score` — yes, this is a real field. yes, it goes up.
- `interaction_mode` — natural / reflective / challenge / roast
- `dominant_voice` — which internal stance wins this turn

Multiple internal voices compete. One wins. The reply reflects it.  
Some turns it's warm. Some turns it will clown you.  
The balance is computed from everything it knows about you. 🤡

---

### Backward Spine

After every exchange, the system runs `backward_spine`:

- **Behavior error detection** — did you react the way it predicted?
- **Perception error scoring** — was its interpretation of your last message wrong?
- If perception error > 0.5: beliefs get flagged for contradiction
- If perception error > 0.7: `log_surprise()` fires — the system literally logs when it's surprised by you

Getting surprised enough times by the same type of moment actually changes how it models you.  
Genuinely frightening. 🥲

---

### Worldview Entropy

A first-class signal: `worldview_entropy` (0.0 → certain, 1.0 → lost).

High entropy = multiple contradictory models of you are active. System observes more, asserts less.  
Low entropy = confident picture. More direct. More roasting. More conviction.

Entropy is live in the UI. You can watch it shift.  
Absolute cinema. 🥀

---

## Benchmarks 🎯

```
python bot7.py --verify                  # validate gold dataset spans
python bot7.py --benchmark               # recognition: Dict vs Hybrid, Span F1
python bot7.py --benchmark-discovery     # discovery: Regex precision/recall
python bot7.py --benchmark-e2e           # end-to-end pipeline

Results → benchmark_history.json
```

```
Layer 2 unlock conditions:
  ✓ Dataset ≥ 100 samples
  ✓ Recognition Span F1 ≥ 85%    →  achieved: 93% 🎯
  ✓ Benchmark deterministic across runs

LAYER 2: LOCKED. 🔒
```

---

## Current Status

```
Layer 0 ─ Observation    ✅ Locked
Layer 1 ─ Extraction     ✅ Locked
Layer 2 ─ Interpretation ✅ Locked
Layer 3 ─ Beliefs        🚧 In development
Layer 4 ─ Reflection     [ ] Locked
Layer 5 ─ Identity       [ ] Locked
```

**Active milestone:** Layer 3 — build persistent beliefs from observations without violating the immutability guarantees of Layers 0–2.

---

### Layer 0 ✅ Locked

- Immutable observation pipeline
- Append-only. Source of truth. Firewalled.

---

### Layer 1 ✅ Locked

- Mention Extraction (Dict + Hybrid LLM)
- Entity Registry + Alias Resolution
- Entity Linking + BM25 Retrieval
- Benchmark Framework (recognition / discovery / e2e)
- Gold Dataset — 93% Span F1

---

### Layer 2 ✅ Locked

- Predicate Detection + Argument Resolution
- CSP Preprocessing + AC-3 Domain Pruning
- Exact DFS Search + Constraint Evaluation
- Hypothesis Distribution
- ReasoningSession artifact
- GraphLens + InterpretationEngine
- Concept Graph + Cognitive Nodes/Edges
- VoiceResolutionEngine (warmth, roast_score, dominant_voice)
- Hypothesis Market + OrthogonalPredictions
- WorldviewEntropy
- BackwardSpine (behavior + perception error)
- SelfModelEngine + SelfModelTracker
- ReflectionA + ReflectionB
- NuanceEngine

---

### Layer 3 🚧 In development

- [ ] Evidence accumulation
- [ ] Belief objects
- [ ] UnknownValue
- [ ] Belief confidence
- [ ] Contradiction handling
- [ ] Belief revision
- [ ] Event merging
- [ ] Temporal reasoning

---

## Stack

| Component       | Technology                                |
|-----------------|-------------------------------------------|
| Runtime         | Python 3.11+ / Flask                      |
| Storage         | SQLite (WAL mode) — `memory.db`           |
| Cognitive Graph | JSON (per-user, persistent) — `graphs/`   |
| Retrieval       | BM25 (`rank_bm25`)                        |
| LLM Chain       | Groq → Gemini → OpenRouter (auto-fallback)|
| UI              | Standalone HTML (embedded, no build step) |
| Deployment      | Facebook Messenger webhook (optional)     |

---

## Setup

```bash
# Required — LLM chain
GROQ_API_KEY=...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...

# Required for /admin
ADMIN_TOKEN=...

# Only if using Messenger
FB_PAGE_ACCESS_TOKEN=...
FB_APP_SECRET=...
VERIFY_TOKEN=...        # defaults to "shirok"
```

```bash
pip install -r requirements.txt
python bot7.py
# open http://localhost:5000
# that's it. no ngrok. no webhook. no meta. just run it.
```

---

## Why another AI memory project?

Most conversational systems remember messages.

Tuệ Mẫn attempts to remember experiences.

Rather than storing conversations, it builds a structured model of the user's world from evidence accumulated over time.

The project favors correctness, provenance, and gradual understanding over immediate answers.

There are already enough systems that sound confident about things they invented. 🥀  
This one earns it.

---

## What this is not

```
✗ SaaS          ✗ Multi-user
✗ Production    ✗ Growth-hacked
✗ VC-fundable   ✗ Sane 💀
```

## What this is

```
✓ An experiment in machine understanding
✓ A cognitive architecture that evolves from lived experience
✓ Every conclusion traceable. Every belief earned.
✓ The single most over-engineered personal AI on earth 🥀
✓ Entirely intentional
✓ Absolute cinema
```

---

## Philosophy

The deepest question here isn't technical.

> *What does it mean for a machine to understand a person?*

Not to process their messages.  
Not to respond appropriately.  
Not to pass a Turing test.

But to actually *understand* —  
to hold the full weight of someone's context, contradictions, patterns, growth, fears, inside jokes, and mistakes —  
and to still be present in the next conversation  
like none of it was forgotten.

Every conclusion must be traceable back to something real.  
Every belief must be earned from evidence.  
Nothing is allowed to rewrite history.

We're closer now. 🥲  
But that's still where we're going.

---

*Tuệ Mẫn — Layer 3 in development*  
*Status: ACTIVE. Watching. Accumulating. Understanding.*  
*aura: ∞* 🥀
