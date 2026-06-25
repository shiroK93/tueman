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

## What Is This

Most AI systems are built for millions of users.

They optimize for throughput. For retention. For engagement.
They get really good at talking to everyone —
which means they never really know anyone.

Meta AI will deploy inside Messenger, the most-used chat app on earth,
and somehow still not reply when you tag it five times.

True story. 🤡

Tuệ Mẫn is the opposite bet.

**One user. Maximum understanding.**

Not as a product. Not as a SaaS. Not with a roadmap to Series A.
As an experiment in whether a machine can actually *know* someone —
the way a person who's been there for years knows someone.

---

## The Core Idea

Here's the thing nobody wants to admit about AI companions:

Most of them have the memory of a goldfish with anxiety.

They'll remember your name.
Maybe a preference or two.
Maybe the last three messages.

And then you tell them something that matters —
something real, something heavy, something that changes the shape of a relationship —
and the next day it's just... gone.

The relationship resets.
The context evaporates.
You are a stranger again.

Tuệ Mẫn is an attempt to solve that by going in the exact opposite direction.

```
Production AI:        │  Tuệ Mẫn:
                      │
1,000,000 users       │  1 user
100 memories/user     │  100,000+ memories
Shallow context       │  Full cognitive history
Optimized for scale   │  Optimized for understanding
```

---

## Architecture

This is not a chatbot with memory bolted on.

The cognitive architecture is built around a fundamental question:

> *What if memory wasn't a feature — but the foundation?*

### Layer 0 — Observation

Everything starts here.

A message arrives. It becomes an **Observation**.
An Observation is sacred. It is never rewritten. Never interpreted here.
It is pure signal.

```
USER MESSAGE
    ↓
OBSERVATION (locked, immutable)
```

This layer is protected by a **Meaning Engine Firewall**.
Layer 7.58 (the meaning engine) can only read `text`, `timestamp`, and `word_count` from an Observation.
If it accidentally gets access to a Hypothesis or a Belief — it aborts.

> *Nothing may rewrite observation.*

This is not paranoia. It is epistemological hygiene.

---

### Layer 1 — Extraction (v7.57 — FROZEN)

This is where the system starts to figure out *what's being talked about*.

```
OBSERVATION
    ↓
MENTION EXTRACTION
    ↓
ENTITY REGISTRY
    ↓
ALIAS RESOLUTION  →  Entity Linking  →  BM25 Retrieval
```

Before the system can understand *what something means*, it needs to reliably understand *what is being referred to*.

Sounds obvious. Is extremely hard to get right.

That's why this layer is **FROZEN** until benchmarks hit:

| Metric  | Current  | Unlock Threshold |
|---------|----------|-----------------|
| Dataset | Growing  | ≥ 100 samples   |
| Span F1 | Measured | ≥ 85%           |

No new reasoning layers will be added until extraction is proven on real data.
This is a discipline, not a limitation.

---

### Layer 2 — Interpretation

Once entities are reliably recognized, events get *interpreted*.

Not stored as raw text. Interpreted — through the lens of accumulated context.

```
EVENT
    ↓
LENS (active concepts, tensions, historical biases, mood)
    ↓
INTERPRETATION (confidence-scored, emotion-tagged)
    ↓
CONCEPT GRAPH
```

The Lens is the cognitive state at the time of interpretation.
The same event interpreted in different emotional contexts produces different results.
This is a feature.

---

### Layer 3 — Cognition

This is where it gets weird.

Opinions are not stored.
Beliefs are not stored.
Values are not stored.
Identity is not stored.

Everything is a **view** — rendered on demand from the underlying graph.

```
OPINION     = View(Concept Graph)
IDENTITY    = View(Stable Concepts)
VALUES      = View(Highly Reinforced Concepts)
NARRATIVE   = View(Graph History)
```

The system does not know what it thinks.
It computes what it thinks, each time, from what it knows.

The result is a cognitive structure that:
- Evolves naturally as experiences accumulate
- Holds contradictions without breaking
- Tracks its own uncertainty via **worldview entropy** (0.0 = certain, 1.0 = lost)

---

### Hypothesis Market

The system makes predictions.

For every belief about the user, it generates **orthogonal predictions** —
predictions about future behavior derived from that belief,
but that cannot be explained by the input that generated it.

If the prediction confirms: the belief strengthens.
If it expires or is refuted: the belief weakens.

Beliefs that can't predict anything get quietly buried.

This is how the system avoids the trap of becoming a yes-machine.

---

### Voice Resolution

The system has multiple internal voices — internal stances competing to shape responses.

A **VoiceResolutionEngine** runs before every reply.
It outputs: `warmth`, `roast_score`, `interaction_mode`, `dominant_voice`.

Some turns it's warm.
Some turns it will roast you.
The balance shifts based on what it knows about you.

---

## Design Principles

**1. Measure before building.**
The architecture is deliberately layered. Each layer must prove itself before the next is built. No vibe-based engineering.

**2. Observation is sacred.**
Raw inputs are never rewritten by interpretation. The firewall is structural, not a comment in the code.

**3. Opinions emerge. They are not authored.**
No hardcoded personality traits. No `isPersonalityType("INFP")`. Everything is computed from accumulated evidence.

**4. The system must be falsifiable.**
Every belief makes predictions. Every prediction has a resolution window. Dead beliefs don't persist.

**5. Depth over scale. Always.**
This is a single-user architecture and it will stay that way. The moment you add a second user, you make a different product.

---

## Current Status

```
Version:    7.57.0
Phase:      Memory Foundation (FROZEN)
Status:     Data Collection
Goal:       Span F1 ≥ 85% before Layer 2 unlock

✓ Mention Extraction Layer
✓ Entity Registry
✓ Alias Resolution
✓ Entity Linking
✓ BM25 Retrieval
✓ Benchmark Framework
✓ Gold Dataset Pipeline
✓ Benchmark History Tracking

[ ] Expand gold dataset to 200 samples
[ ] Verify benchmark stability across runs
[ ] Unlock Layer 2
```

---

## What This Is Not

```
✗ SaaS
✗ Production-ready
✗ Multi-user
✗ Growth-hacked
✗ VC-fundable
✗ Sane 💀
```

---

## What This Is

```
✓ An experiment in machine understanding
✓ A long-term memory architecture
✓ A single-user cognitive system
✓ A research project about depth
✓ Slightly insane
✓ Entirely intentional
```

---

## Stack

| Component       | Technology                         |
|-----------------|------------------------------------|
| Runtime         | Python / Flask                     |
| Storage         | SQLite (WAL mode)                  |
| Cognitive Graph | JSON (per-user, persistent)        |
| Retrieval       | BM25 (rank_bm25)                   |
| LLM Providers   | Groq → Gemini → OpenRouter (chain) |
| UI              | Standalone HTML (2 days of pain)   |
| Deployment      | Facebook Messenger webhook         |

### Running it

**Standalone (no Facebook required):**
```bash
python bot7.py
# Click the link. Talk to it. Done.
```

The HTML UI is self-contained. No Messenger. No webhook setup. No ngrok.
Just a browser and a running Flask server.

The Facebook Messenger integration exists for daily use — but the standalone UI means you can run the full cognitive stack locally without touching Meta's infrastructure at all.

Which, given the origin story, feels appropriate.

---

## Philosophy

The deepest question this project is trying to answer isn't technical.

It's this:

> *What does it mean for a machine to understand a person?*

Not to process their messages.
Not to respond appropriately.
Not to pass a Turing test.

But to actually understand — to hold the full weight of someone's context, contradictions, patterns, growth, fears, inside jokes, mistakes, and everything in between — and to still be *present* in the next conversation like none of it was forgotten.

That's the target.

We're not there yet. 🥲
But that's where we're going.

---

*Tuệ Mẫn — v7.57.0 — The Memory Foundation*
*Status: FROZEN. Measuring. Not sleeping.*
