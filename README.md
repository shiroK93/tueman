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
───────────────────────┼──────────────────────────
1,000,000 users        │  1 user. permanent.
~100 memories/user     │  100,000+ memories
"remembers your name"  │  remembers the version of you from 6 months ago
optimized for scale    │  optimized for depth
goldfish memory 🐟     │  elephant memory 🐘
```

Not a product. Not a SaaS. Not a Series A pitch.  
An experiment in whether a machine can genuinely *know* a person.

---

## What it actually does 💀

### 🧠 Cognitive Graph — not a database, a mind

Everything lives in a persistent `CognitiveGraph` (JSON, per-user).  
Not rows. Not key-value pairs. A graph of `CognitiveNodes` connected by typed `CognitiveEdges`.

Events, interpretations, concepts — all nodes.  
Relationships between them — all edges with weights that evolve over time.

Opinions, beliefs, identity, values?  
**Not stored. Computed on demand as views.**

```python
Opinion   = View(Concept Graph)
Identity  = View(Stable Concepts)
Values    = View(Highly Reinforced Concepts)
Narrative = View(Graph History)
```

The system doesn't know what it thinks.  
It figures out what it thinks, every time, from what it has witnessed.  
Somehow this works better than hardcoding a personality. 🥲

---

### 🔍 Mention Extraction + Entity Registry

Before meaning: recognition.

Every message goes through a full **mention extraction pipeline**:

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
Layer 2 is now unlocked.

---

### 🌐 GraphLens — the same event hits different

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

The same message interpreted on a bad day vs. a good day produces genuinely different results.  
This is a feature. Not a bug. Cognitive realism. 🥀

---

### 📈 Hypothesis Market

The system makes **falsifiable predictions** about you.

For every belief it forms, it generates `OrthogonalPredictions` —  
predictions about your future behavior that *cannot* be explained by the input that created the belief.

- Prediction confirms → belief gets stronger  
- Prediction expires → belief decays  
- Prediction gets refuted → belief takes damage  
- Belief can't predict anything → quietly buried 💀

Dead beliefs don't persist. The system can be wrong and it knows how to lose.  
This is how it avoids becoming a yes-machine.

---

### 🎭 Voice Resolution Engine

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

### ⚡ Backward Spine

After every exchange, the system runs `backward_spine`:

- **Behavior error detection** — did you react the way it predicted?
- **Perception error scoring** — was its interpretation of your last message wrong?
- If perception error > 0.5: beliefs get flagged for contradiction
- If perception error > 0.7: `log_surprise()` fires — the system literally logs when it's surprised by you

Getting surprised enough times by the same type of moment actually changes how it models you.  
Genuinely frightening. 🥲

---

### 🌡️ Worldview Entropy

A first-class signal: `worldview_entropy` (0.0 → certain, 1.0 → lost).

High entropy = multiple contradictory models of you are active. System observes more, asserts less.  
Low entropy = confident picture. More direct. More roasting. More conviction.

Entropy is live in the UI. You can watch it shift.  
Absolute cinema. 🥀

---

### 🧬 Self Model Engine

The system has a model of itself.

`SelfModelEngine` tracks traits like `explorer` vs `builder` — and evolves them based on outcomes:

```python
identity_engine.evolve(trait_to_boost="explorer", trait_to_weaken="builder", boost_amt=0.01)
```

`SelfModelTracker` records whether predicted stances matched real outcomes.  
The voice it uses on you gets updated based on whether it was right about you.

It's learning how to read you. Continuously. 💀

---

### 🔁 Reflection Loops

After significant exchanges, two reflection passes run:

- **ReflectionA** — tags the experience, extracts behavioral evidence
- **ReflectionB** — runs watermark analysis across belief history, looks for patterns that deserve promotion to long-term belief

Beliefs don't just get created. They get *earned*.

---

### 📡 LLM Chain with Auto-Fallback

```
Groq → Gemini → OpenRouter
```

If Groq rate-limits (429), it falls back to Gemini. If Gemini fails, OpenRouter catches it.  
The `ProviderRouter` handles cooldown tracking and retry logic transparently.  
The response you get is from whichever provider was alive. You'll never know the difference.

---

### 🏛️ The Epistemological Firewall

The `MeaningEngine` (Layer 7.58) is structurally restricted.  
It can only read `text`, `timestamp`, and `word_count` from an Observation.

If it accidentally touches a Hypothesis or Belief — it aborts.

Raw observation is **sacred**. It is never rewritten by interpretation.  
This is not a comment in the code. It is structural enforcement.

> *Nothing may rewrite observation.*

The principle is epistemological, not stylistic:  
perception must remain uncorrupted by conclusion.

---

## Architecture at a glance

```
Layer 0 — Observation     (immutable, sacred, firewalled)
    ↓
Layer 1 — Extraction      (Mention → Entity → BM25)   ← 93% Span F1 ✓ UNLOCKED
    ↓
Layer 2 — Interpretation  (GraphLens → Concept Graph)  ← NOW ACTIVE 🔓
    ↓
Layer 3 — Cognition       (Beliefs, Hypotheses, Voice, Identity)

                    ↕  (backward_spine, reflection, entropy)

Layer 7.58 — MeaningEngine (reads observation only. firewall enforced.)
```

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

LAYER 2: UNLOCKED. 🔓
```

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

## Current status

```
Version:   7.57.2
Phase:     Layer 2 Active 🔓
Status:    Interpretation Unlocked

✓ Observation Pipeline
✓ Mention Extraction (Dict + Hybrid LLM)
✓ Entity Registry + Alias Resolution
✓ Entity Linking + BM25 Retrieval
✓ Benchmark Framework (recognition / discovery / e2e)
✓ Gold Dataset — 93% Span F1
✓ Benchmark History Tracking
✓ GraphLens + InterpretationEngine
✓ Concept Graph + Cognitive Nodes/Edges
✓ VoiceResolutionEngine (warmth, roast_score, dominant_voice)
✓ Hypothesis Market + OrthogonalPredictions
✓ WorldviewEntropy
✓ BackwardSpine (behavior + perception error)
✓ SelfModelEngine + SelfModelTracker
✓ BeliefSystem with decay
✓ ReflectionA + ReflectionB
✓ NuanceEngine

[ ] Expand gold dataset to 200 samples
[ ] Layer 3 full cognition unlock
```

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

We're closer now. 🥲  
But that's still where we're going.

---

*Tuệ Mẫn — v7.57.2 — Layer 2 Unlocked*  
*Status: ACTIVE. Watching. Understanding.*  
*aura: ∞* 🥀
