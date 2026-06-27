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

Understanding is treated as an emergent property of accumulated evidence, not something produced by a single model invocation.

Tuệ Mẫn is not built to know everyone.

It is built to understand one person deeply enough that every new observation becomes part of a coherent life story.

---

## The premise

Most AI systems are built for millions of users.

They optimize for throughput. For retention. For engagement metrics.  
They get really good at talking to everyone —  
which means they never actually know anyone.

Meta AI will deploy inside the most-used chat app on earth  
and somehow still not reply when you tag it five times. 🤡

Tuệ Mẫn is the opposite bet.

**One user. Total understanding. No compromises.**

```
Production AI           │  Tuệ Mẫn
────────────────────────┼──────────────────────────────────────────
1,000,000 users         │  1 user. permanent.
~100 memories/user      │  100,000+ memories
"remembers your name"   │  remembers the version of you from 6 months ago
answer first            │  understand first
confident without evidence │  uncertain until the evidence says otherwise
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

The world has enough systems that are confident about things they made up.  
This one is built differently.

---

## Cognitive Architecture

Six layers. One direction. No exceptions.

```
Layer 0 ─ Observation
│
│  Immutable.
│  Append-only.
│  Source of truth.
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
This is not a guideline. It is structural enforcement.

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

---

### Uncertainty is preserved

Tuệ Mẫn does not force a single interpretation.

Layer 2 produces hypothesis distributions.  
Layer 3 accumulates evidence over time before committing to beliefs.

The system holds uncertainty as a first-class value.  
It doesn't collapse to a confident answer until the evidence warrants it.

---

### Memory grows, not rewrites

New observations reinforce, weaken, or revise beliefs.

History is preserved.

The system remembers *why* something became true.  
If it was wrong, it remembers that too.  
Dead beliefs don't persist. The system can lose gracefully.

---

## Core Architecture

Implemented Foundation

---

### Layer 0 — Observation

Immutable observation pipeline. Append-only. Source of truth. Firewalled from everything above.

---

### Layer 1 — Extraction

```
Message
  ↓
MentionExtractor (Dict + Hybrid LLM mode)
  ↓
EntityRegistry (persisted, versioned aliases)
  ↓
AliasResolution → EntityLinking → BM25Retrieval
```

Knows the difference between "he", "the guy", "Minh", and "that dude from the coffee shop last week" — because it built an alias graph.

Vietnamese capitalization edge cases? Handled.  
CamelCase tech names mid-sentence? Handled.  
Multi-word entity disambiguation? Handled.

**Mention Extraction Span F1: 93%.** 🎯

---

### Layer 2 — Interpretation

```
Event
  ↓
Predicate Detection
  ↓
Argument Hypothesis Generation + Role Scoring
  ↓
CSP Preprocessing + AC-3 Domain Pruning
  ↓
Exact DFS Search + Constraint Evaluation
  ↓
Hypothesis Distribution → ReasoningSession Artifact
```

Layer 2 transforms observations into structured event hypotheses while preserving uncertainty and provenance.

---

## Experimental Components

Built on top of the frozen layers. These drive current conversational behavior and inform Layer 3 design.

---

### Hypothesis Market

The system makes **falsifiable predictions** about you.

For every belief it forms, it generates `OrthogonalPredictions` —  
predictions about your future behavior that *cannot* be explained by the input that created the belief.

- Prediction confirms → belief gets stronger  
- Prediction expires → belief decays  
- Prediction gets refuted → belief takes damage  
- Belief can't predict anything → quietly buried

The system can be wrong and it knows how to lose.  
This is how it avoids becoming a yes-machine.

---

### Voice Resolution

Before every reply, a `VoiceResolutionEngine` runs.

Multiple internal voices compete. One wins. The reply reflects it.

Outputs: `warmth`, `roast_score`, `interaction_mode`, `dominant_voice`.  
Some turns it's warm. Some turns it will clown you.  
The balance is computed from everything it knows about you.

---

### Backward Spine

After every exchange, the system runs error scoring:

- Did you react the way it predicted?
- Was its interpretation of your last message wrong?
- If perception error > 0.5: beliefs get flagged for contradiction.
- If perception error > 0.7: `log_surprise()` fires.

Getting surprised enough times by the same moment actually changes how it models you. 🥲

---

### Worldview Entropy

A first-class signal: `worldview_entropy` (0.0 → certain, 1.0 → lost).

High entropy = contradictory models of you are active. System observes more, asserts less.  
Low entropy = confident picture. More direct. More conviction.

---

## Benchmarks 🎯

```
python bot7.py --verify                  # validate gold dataset spans
python bot7.py --benchmark               # recognition: Dict vs Hybrid
python bot7.py --benchmark-discovery     # discovery: Regex precision/recall
python bot7.py --benchmark-e2e           # end-to-end pipeline

Results → benchmark_history.json
```

All benchmark datasets are manually curated to measure extraction quality independently from downstream reasoning.

```
Layer 2 unlock conditions:
  ✓ Dataset ≥ 100 samples
  ✓ Mention Extraction Span F1 ≥ 85%    →  achieved: 93%
  ✓ Benchmark deterministic across runs

LAYER 2: LOCKED.
```

---

## Research Roadmap

```
Layer 0 ─ Observation    ✅ Locked
Layer 1 ─ Extraction     ✅ Locked
Layer 2 ─ Interpretation ✅ Locked
Layer 3 ─ Beliefs        🚧 In development
Layer 4 ─ Reflection     ○  Future research
Layer 5 ─ Identity       ○  Future research
```

**Active milestone:** Layer 3 — build persistent beliefs from observations without violating the immutability guarantees of Layers 0–2.

---

### Layers 0–2 ✅ Locked

Observation pipeline. Mention extraction. Entity registry. Alias resolution. Entity linking. BM25 retrieval. Predicate detection. Argument resolution. Constraint satisfaction. Hypothesis distribution. ReasoningSession artifact. Benchmark framework. Gold dataset.

No architectural expansion. Bug fixes and benchmark improvements only.

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

### Layers 4–5 ○ Future research

Layers 4–5 remain intentionally undefined.

Their purpose is understood.

Their implementation is not.

They will emerge only after Layer 3 proves stable.

The architecture will follow the evidence, not the roadmap.

---

## Why another AI memory project?

Most conversational systems remember messages.

Tuệ Mẫn attempts to remember experiences.

Rather than storing conversations, it builds a structured model of the user's world from evidence accumulated over time.

The project favors correctness, provenance, and gradual understanding over immediate answers.

---

## What this is not

```
✗ SaaS          ✗ Multi-user
✗ Production    ✗ Growth-hacked
✗ VC-fundable   ✗ Sane
```

## What this is

```
✓ An experiment in machine understanding
✓ A cognitive architecture that evolves from lived experience
✓ Every conclusion traceable. Every belief earned.
✓ The single most over-engineered personal AI on earth
✓ Entirely intentional
✓ Absolute cinema 🥀
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

We're closer now.  
But that's still where we're going.

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

*Tuệ Mẫn — Layer 3 in development*  
*Status: ACTIVE. Watching. Accumulating. Understanding.*  
*aura: ∞* 🥀
