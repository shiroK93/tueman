"""
TUỆ MẪN 7.47 — THE DEEP MERGE
"7.47 runs the brain. Old state is just a signal."

⚠️  WARNING: this file contains a girl with trust issues, a belief engine,
    and zero chill. handle with care, snacks, and a stable wifi connection.
    built by one (1) unhinged developer who refused to let an AI companion
    have shallow feelings. she remembers EVERYTHING now. you've been warned.
"""

import os
import re
import time
import random
import logging
import threading
import sqlite3
import json
import datetime
import math
import hmac
import hashlib
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Any, List, Dict
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

# ==================== TIMING HELPER ====================
class _T:
    """Tiny stopwatch. Use: t = _T(); ...; log.info(f"{t}ms")"""
    def __init__(self): self._s = time.perf_counter()
    def ms(self) -> int: return int((time.perf_counter() - self._s) * 1000)
    def __str__(self): return f"{self.ms()}ms"

# ==================== LOGGING ====================
# her diary. except she doesn't know it exists, and you read it
# instead of waiting for her to text back.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)
# =================================================

app = Flask(__name__)

# ==================== CONFIGURATION ====================
# the knobs and dials of a fake relationship. choose wisely.
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_APP_SECRET        = os.environ.get("FB_APP_SECRET")  # required to verify X-Hub-Signature-256
VERIFY_TOKEN         = os.environ.get("VERIFY_TOKEN", "shirok")
MAX_FOLLOW_UPS       = 2
MAX_HISTORY          = 14
MAX_FACTS            = 50
DB_PATH              = "memory.db"
DB_TIMEOUT           = 20
ADMIN_TOKEN          = os.environ.get("ADMIN_TOKEN")
GRAPHS_DIR           = "graphs"
LENS_MIN_MSG_LEN     = 10
LENS_ASYNC           = True
t0 = time.time()

if not ADMIN_TOKEN:
    log.warning("[SECURITY] ADMIN_TOKEN is not set — /admin route will refuse all requests until it is configured.")
if not FB_APP_SECRET:
    log.warning("[SECURITY] FB_APP_SECRET is not set — incoming webhook POSTs cannot be signature-verified and will be rejected until it is configured.")

# ╔═══════════════════════════════════════════════════════════════╗
# ║  🧠 [MIND 7.35] INTERPRETATION ENGINE — CORE SCHEMA            ║
# ║  EVENT → INTERPRETATION → CONCEPT. opinions aren't stored,    ║
# ║  they're GROWN — like mold, but the mold has feelings.        ║
# ╚═══════════════════════════════════════════════════════════════╝

class NodeType(Enum):
    EVENT = "event"
    INTERPRETATION = "interpretation"
    CONCEPT = "concept"

class EdgeType(Enum):
    TRIGGERS = "triggers"
    SUPPORTS = "supports"
    RELATES_TO = "relates_to"

@dataclass
class BasePayload:
    pass

@dataclass
class EventPayload(BasePayload):
    content: str
    emotional_valence: float
    raw_context: dict = field(default_factory=dict)

@dataclass
class InterpretationPayload(BasePayload):
    event_id: str
    summary: str
    emotional_state: str
    confidence: float
    reinforcement_count: int = 0
    lens_snapshot: dict = field(default_factory=dict)

@dataclass
class ConceptPayload(BasePayload):
    name: str
    keywords: list[str] = field(default_factory=list)

PAYLOAD_MAP = {
    NodeType.EVENT: EventPayload,
    NodeType.INTERPRETATION: InterpretationPayload,
    NodeType.CONCEPT: ConceptPayload,
}

@dataclass
class CognitiveNode:
    id: str
    type: NodeType
    payload: BasePayload
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self):
        return {"id": self.id, "type": self.type.value, "payload": asdict(self.payload), "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d):
        ntype = NodeType(d["type"])
        return cls(id=d["id"], type=ntype, payload=PAYLOAD_MAP[ntype](**d["payload"]), created_at=d.get("created_at"))

@dataclass
class CognitiveEdge:
    source_id: str
    target_id: str
    type: EdgeType
    weight: float = 1.0
    def to_dict(self): return {"source_id": self.source_id, "target_id": self.target_id, "type": self.type.value, "weight": self.weight}
    @classmethod
    def from_dict(cls, d): return cls(d["source_id"], d["target_id"], EdgeType(d["type"]), d.get("weight", 1.0))

class CognitiveGraph:
    def __init__(self, filepath: str = None):
        self.filepath = filepath
        self.nodes: dict[str, CognitiveNode] = {}
        self.edges: list[CognitiveEdge] = []
        if filepath and os.path.exists(filepath):
            self._load()

    def _load(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.nodes = {n["id"]: CognitiveNode.from_dict(n) for n in data.get("nodes", [])}
                self.edges = [CognitiveEdge.from_dict(e) for e in data.get("edges", [])]
        except Exception: pass

    def save(self):
        if not self.filepath: return
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({"nodes": [n.to_dict() for n in self.nodes.values()], "edges": [e.to_dict() for e in self.edges]}, f, ensure_ascii=False, indent=2)

    def add_node(self, node: CognitiveNode): self.nodes[node.id] = node
    def add_edge(self, edge: CognitiveEdge):
        if not any(e.source_id == edge.source_id and e.target_id == edge.target_id and e.type == edge.type for e in self.edges):
            self.edges.append(edge)

    def get_incoming(self, node_id: str, edge_type: EdgeType) -> list[CognitiveNode]:
        src_ids = [e.source_id for e in self.edges if e.target_id == node_id and e.type == edge_type]
        return [self.nodes[sid] for sid in src_ids if sid in self.nodes]

    def compute_concept_activation(self, concept_id: str) -> float:
        supporters = self.get_incoming(concept_id, EdgeType.SUPPORTS)
        if not supporters: return 0.0
        prob_false = 1.0
        for s in supporters:
            p: InterpretationPayload = s.payload
            effective_conf = min(0.99, p.confidence + (p.reinforcement_count * 0.02))
            prob_false *= (1.0 - effective_conf)
        return 1.0 - prob_false

@dataclass
class GraphLens:
    active_concepts: list[dict]
    unresolved_tensions: list[str]
    historical_biases: list[str]
    overall_mood: str

class LensExtractor:
    def extract(self, event_content: str, graph: CognitiveGraph) -> GraphLens:
        concept_activations = []
        for node in graph.nodes.values():
            if node.type == NodeType.CONCEPT:
                activation = graph.compute_concept_activation(node.id)
                p: ConceptPayload = node.payload
                if any(kw.lower() in event_content.lower() for kw in p.keywords):
                    activation = min(1.0, activation + 0.3)
                concept_activations.append({"id": node.id, "name": p.name, "activation": round(activation, 2)})
        concept_activations.sort(key=lambda x: x["activation"], reverse=True)
        active_concepts = [c for c in concept_activations if c["activation"] > 0.2][:5]
        unresolved = []
        if len(active_concepts) >= 2:
            c1, c2 = active_concepts[0]["name"], active_concepts[1]["name"]
            if self._are_opposing(c1, c2):
                unresolved.append(f"Internal conflict between '{c1}' and '{c2}'")
        past_interpretations = [n for n in graph.nodes.values() if n.type == NodeType.INTERPRETATION]
        biases = [pi.payload.summary for pi in past_interpretations[-5:]]
        if not active_concepts: mood = "neutral"
        elif active_concepts[0]["activation"] > 0.8: mood = "highly biased towards " + active_concepts[0]["name"]
        else: mood = "balanced"
        return GraphLens(active_concepts=active_concepts, unresolved_tensions=unresolved, historical_biases=biases, overall_mood=mood)

    def _are_opposing(self, c1: str, c2: str) -> bool:
        opposites = [("Self_Doubt", "Growth"), ("Burnout", "Mastery"), ("Cynicism", "Trust"), ("Anxiety", "Resilience"), ("Isolation", "Connection")]
        return any((c1 in pair and c2 in pair) for pair in opposites)

class InterpretationEngine:
    def __init__(self, llm_func: Callable = None):
        self.lens_extractor = LensExtractor()
        self.llm_func = llm_func

    def process_event(self, event: CognitiveNode, graph: CognitiveGraph) -> Optional[CognitiveNode]:
        if event.type != NodeType.EVENT: return None
        t = _T()
        lens = self.lens_extractor.extract(event.payload.content, graph)
        top = f"{lens.active_concepts[0]['name']}({lens.active_concepts[0]['activation']:.2f})" if lens.active_concepts else "none"
        log.info(f"[LENS] top={top} mood={lens.overall_mood} tensions={len(lens.unresolved_tensions)} concepts={len(lens.active_concepts)}")
        if self.llm_func:
            try: interp_text, emotion, conf = self.llm_func(event.payload.content, lens)
            except Exception as e:
                log.warning(f"[LENS] LLM interpret failed → mock | err={e}")
                interp_text, emotion, conf = self._mock_llm_deformation(event.payload.content, lens)
        else:
            interp_text, emotion, conf = self._mock_llm_deformation(event.payload.content, lens)
        if not interp_text: return None
        interp_id = f"interp_{int(time.time())}_{random.randint(1000,9999)}"
        interp_node = CognitiveNode(id=interp_id, type=NodeType.INTERPRETATION, payload=InterpretationPayload(event_id=event.id, summary=interp_text, emotional_state=emotion, confidence=conf, lens_snapshot={"active": lens.active_concepts, "mood": lens.overall_mood}))
        graph.add_node(event)
        graph.add_node(interp_node)
        graph.add_edge(CognitiveEdge(event.id, interp_node.id, EdgeType.TRIGGERS))
        self._link_to_concepts(interp_node, graph)
        self._cleanup_old_events(graph)
        graph.save()
        log.info(f"[INTERP] event={event.id} → \"{interp_text}\" emotion={emotion} conf={conf:.2f} | {t}")
        return interp_node

    def _link_to_concepts(self, interp_node: CognitiveNode, graph: CognitiveGraph):
        text = interp_node.payload.summary.lower()
        for c_node in graph.nodes.values():
            if c_node.type == NodeType.CONCEPT:
                if any(kw.lower() in text for kw in c_node.payload.keywords):
                    graph.add_edge(CognitiveEdge(interp_node.id, c_node.id, EdgeType.SUPPORTS))

    def _cleanup_old_events(self, graph: CognitiveGraph, keep_last: int = 200):
        event_nodes = [n for n in graph.nodes.values() if n.type == NodeType.EVENT]
        if len(event_nodes) > keep_last:
            for node in sorted(event_nodes, key=lambda n: n.created_at)[:-keep_last]:
                graph.edges = [e for e in graph.edges if e.source_id != node.id and e.target_id != node.id]
                del graph.nodes[node.id]

    @staticmethod
    def _mock_llm_deformation(event_text: str, lens: GraphLens) -> tuple[str, str, float]:
        top_concept = lens.active_concepts[0]["name"] if lens.active_concepts else "Neutral"
        activation = lens.active_concepts[0]["activation"] if lens.active_concepts else 0.0
        if "Self_Doubt" in top_concept or "Anxiety" in top_concept:
            return ("Chắc mình dở quá.", "hopeless", 0.9) if activation > 0.7 else ("Mình làm chưa tốt.", "anxious", 0.7)
        elif "Growth" in top_concept or "Resilience" in top_concept:
            return ("Cơ hội để sửa sai.", "determined", 0.9) if activation > 0.7 else ("Sẽ rút kinh nghiệm.", "calm", 0.7)
        elif "Cynicism" in top_concept: return ("Công ty này vô lý.", "angry", 0.8)
        elif "Burnout" in top_concept: return ("Chán quá, muốn nghỉ.", "exhausted", 0.85)
        elif "Connection" in top_concept: return ("Người ta quan tâm mình mới nhắc.", "touched", 0.7)
        return ("Chuyện bình thường.", "neutral", 0.5)

_graph_cache: dict[str, CognitiveGraph] = {}
_graph_lock = threading.Lock()

def _seed_initial_concepts(graph: CognitiveGraph):
    concepts = [
        ("c_self_doubt", "Self_Doubt", ["dở", "kém", "đủ tốt", "thất bại", "sai", "lỗi"]),
        ("c_growth", "Growth", ["tiến bộ", "cơ hội", "học hỏi", "sửa sai", "phát triển"]),
        ("c_resilience", "Resilience", ["đứng lên", "kiên trì", "không bỏ cuộc", "vượt qua"]),
        ("c_anxiety", "Anxiety", ["lo lắng", "áp lực", "sợ", "nervous", "hoang mang"]),
        ("c_cynicism", "Cynicism", ["vô lý", "bất công", "đáng ghét", "bức xúc"]),
        ("c_trust", "Trust", ["tin tưởng", "chân thành", "ổn", "chắc chắn"]),
        ("c_burnout", "Burnout", ["mệt mỏi", "kiệt sức", "quá tải", "nản", "chán nản"]),
        ("c_mastery", "Mastery", ["giỏi", "thành thạo", "chuyên gia", "xuất sắc"]),
        ("c_connection", "Connection", ["gần gũi", "thân thiết", "quan tâm", "hiểu"]),
        ("c_isolation", "Isolation", ["cô đơn", "một mình", "không ai", "xa cách"]),
    ]
    for cid, name, keywords in concepts:
        graph.add_node(CognitiveNode(cid, NodeType.CONCEPT, ConceptPayload(name, keywords)))
    graph.save()

def get_user_graph(sender_id: str) -> CognitiveGraph:
    with _graph_lock:
        if sender_id in _graph_cache: return _graph_cache[sender_id]
        os.makedirs(GRAPHS_DIR, exist_ok=True)
        filepath = os.path.join(GRAPHS_DIR, f"{sender_id}.json")
        t = _T()
        graph = CognitiveGraph(filepath)
        seeded = False
        if not graph.nodes: _seed_initial_concepts(graph); seeded = True
        _graph_cache[sender_id] = graph
        log.info(f"[GRAPH] loaded | nodes={len(graph.nodes)} edges={len(graph.edges)} seeded={seeded} | {t}")
        return graph

def make_llm_interpret_func(router):
    def _llm_interpret(event_text: str, lens: GraphLens) -> tuple[str, str, float]:
        active_str = ", ".join(f"{c['name']}({c['activation']:.2f})" for c in (lens.active_concepts[:3] or []))
        biases_str = "\n".join(f"- {b}" for b in lens.historical_biases[-3:]) if lens.historical_biases else "none"
        system = "You are a cognitive interpretation engine. Given EVENT and LENS, produce BIASED INTERPRETATION. Return ONLY JSON: {\"interpretation\": \"...\", \"emotion\": \"...\", \"confidence\": 0.0-1.0}. Vietnamese. No markdown."
        user_msg = f"EVENT: {event_text}\n\nLENS:\n- Active: {active_str}\n- Mood: {lens.overall_mood}\n- Tensions: {lens.unresolved_tensions or 'none'}\n- Recent: {biases_str}"
        raw = router.generate(system, [{"role": "user", "content": user_msg}], max_tokens=150).replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return (str(data.get("interpretation", ""))[:300], str(data.get("emotion", "neutral"))[:30], max(0.0, min(1.0, float(data.get("confidence", 0.5)))))
    return _llm_interpret

interpretation_engine: Optional[InterpretationEngine] = None


# ╔═══════════════════════════════════════════════════════════════╗
# ║  🔌 LLM PROVIDER ROUTER                                        ║
# ║  groq fails → gemini takes over → openrouter mops it up.      ║
# ║  three different AIs cosplaying one girlfriend. teamwork.     ║
# ╚═══════════════════════════════════════════════════════════════╝

class Provider:
    name = "base"
    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        raise NotImplementedError

class GroqProvider(Provider):
    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"
    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        key = os.environ.get("GROQ_API_KEY", "")
        if not key: raise RuntimeError("GROQ_API_KEY not set")
        res = requests.post(self.URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": system}] + messages,
                  "temperature": 0.82, "max_tokens": max_tokens, "top_p": 0.93,
                  "frequency_penalty": 1.2, "presence_penalty": 0.9, "stop": ["User:", "Tuệ Mẫn:", "\n\n\n"]}, timeout=15)
        if res.status_code == 429: raise RuntimeError("Groq rate limited (429)")
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

class GeminiProvider(Provider):
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"
    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key: raise RuntimeError("GEMINI_API_KEY not set")
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            if contents and contents[-1]["role"] == role: contents[-1]["parts"][0]["text"] += "\n" + m["content"]
            else: contents.append({"role": role, "parts": [{"text": m["content"]}]})
        res = requests.post(f"{self.URL}?key={key}",
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                  "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.82, "topP": 0.93}}, timeout=15)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

class OpenRouterProvider(Provider):
    name = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"
    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key: raise RuntimeError("OPENROUTER_API_KEY not set")
        res = requests.post(self.URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "meta-llama/llama-3.3-70b-instruct:free",
                  "messages": [{"role": "system", "content": system}] + messages,
                  "max_tokens": max_tokens, "temperature": 0.82}, timeout=20)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

class ProviderRouter:
    COOLDOWN_SECONDS = 600
    def __init__(self):
        self.providers = [GroqProvider(), GeminiProvider(), OpenRouterProvider()]
        self.provider_map = {p.name: p for p in self.providers}
        self.cooldown = {p.name: 0.0 for p in self.providers}
        self.last_good = self.providers[0].name

    def _is_cooling_down(self, name: str) -> bool: return time.time() < self.cooldown.get(name, 0.0)
    def _mark_cooldown(self, name: str, err: Exception):
        if "429" in str(err).lower() or "rate limit" in str(err).lower():
            self.cooldown[name] = time.time() + self.COOLDOWN_SECONDS

    def _attempt(self, provider, system, messages, max_tokens):
        if self._is_cooling_down(provider.name):
            remaining = int(self.cooldown.get(provider.name, 0) - time.time())
            log.debug(f"[ROUTER] {provider.name} on cooldown | {remaining}s left")
            return None, RuntimeError(f"{provider.name} on cooldown")
        t = _T()
        try:
            response = provider.generate(system, messages, max_tokens)
            if response:
                log.info(f"[ROUTER] {provider.name} OK | {t} | ~{len(response.split())} words")
                return response, None
            log.warning(f"[ROUTER] {provider.name} empty response | {t}")
            return None, RuntimeError(f"{provider.name} empty")
        except Exception as e:
            self._mark_cooldown(provider.name, e)
            log.warning(f"[ROUTER] {provider.name} FAIL | {t} | {e}")
            return None, e

    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        last_error = None
        tried = set()
        sticky = self.provider_map.get(self.last_good)
        if sticky:
            log.debug(f"[ROUTER] trying {sticky.name} (sticky)")
            response, err = self._attempt(sticky, system, messages, max_tokens)
            tried.add(sticky.name)
            if response: self.last_good = sticky.name; return response
            last_error = err
        for provider in self.providers:
            if provider.name in tried: continue
            log.debug(f"[ROUTER] trying {provider.name} (fallback)")
            response, err = self._attempt(provider, system, messages, max_tokens)
            tried.add(provider.name)
            if response: self.last_good = provider.name; return response
            last_error = err
        log.error(f"[ROUTER] ALL providers failed | tried={tried} | last={last_error}")
        raise RuntimeError(f"All providers failed — last: {last_error}")

_router = ProviderRouter()
interpretation_engine = InterpretationEngine(llm_func=make_llm_interpret_func(_router))

# ==================== IN-MEMORY STATE (don't @ me about Redis) ====================
# four little dicts holding the entire emotional state of the relationship.
# RAM is the love language here. restart the process, lose the vibe.
follow_up_timers = {}
follow_up_counts = {}
user_states = {}
processed_mids = {}
_state_lock = threading.Lock()
MID_TTL_SECONDS = 6 * 3600  # FB redelivers within minutes at most; 6h is generous headroom
MID_PRUNE_EVERY = 500

def _mark_mid_processed(mid: str):
    """Thread-safe insert + periodic pruning so processed_mids doesn't grow forever."""
    now = time.time()
    with _state_lock:
        processed_mids[mid] = now
        if len(processed_mids) % MID_PRUNE_EVERY == 0:
            cutoff = now - MID_TTL_SECONDS
            stale = [m for m, ts in processed_mids.items() if ts < cutoff]
            for m in stale: processed_mids.pop(m, None)

def _is_mid_processed(mid: str) -> bool:
    with _state_lock:
        return mid in processed_mids

def _incr_follow_up_count(sender_id: str) -> int:
    with _state_lock:
        follow_up_counts[sender_id] = follow_up_counts.get(sender_id, 0) + 1
        return follow_up_counts[sender_id]

def _reset_follow_up_count(sender_id: str):
    with _state_lock:
        follow_up_counts[sender_id] = 0

def _get_follow_up_count(sender_id: str) -> int:
    with _state_lock:
        return follow_up_counts.get(sender_id, 0)

# ==================== DATABASE & CORE LOGIC ====================
# sqlite: the load-bearing wall of an entire personality.
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS facts (sender_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (sender_id, key))")
    c.execute("CREATE TABLE IF NOT EXISTS user_state (sender_id TEXT PRIMARY KEY, state TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS preferences (sender_id TEXT NOT NULL, category TEXT NOT NULL, value TEXT NOT NULL, score REAL DEFAULT 1.0, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (sender_id, category, value))")
    c.execute("CREATE TABLE IF NOT EXISTS topic_stats (sender_id TEXT NOT NULL, topic TEXT NOT NULL, count INTEGER DEFAULT 1, last_seen DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (sender_id, topic))")
    c.execute("CREATE TABLE IF NOT EXISTS style_profile (sender_id TEXT PRIMARY KEY, reply_length_pref REAL DEFAULT 50.0, avg_msg_len REAL DEFAULT 50.0, msg_count INTEGER DEFAULT 0)")
    for ddl in ["ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 5","ALTER TABLE facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE facts ADD COLUMN confidence REAL DEFAULT 0.8","ALTER TABLE facts ADD COLUMN source_message TEXT DEFAULT ''"]:
        try: c.execute(ddl)
        except: pass
    c.execute("CREATE TABLE IF NOT EXISTS fact_candidates (sender_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, score INTEGER DEFAULT 1, rejection_reason TEXT DEFAULT NULL, last_seen DATETIME DEFAULT CURRENT_TIMESTAMP, confidence REAL DEFAULT 0.0, source_message TEXT DEFAULT '', PRIMARY KEY (sender_id, key))")
    for ddl in ["ALTER TABLE fact_candidates ADD COLUMN confidence REAL DEFAULT 0.0","ALTER TABLE fact_candidates ADD COLUMN source_message TEXT DEFAULT ''"]:
        try: c.execute(ddl)
        except: pass
    c.execute("CREATE TABLE IF NOT EXISTS experiences (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, user_message TEXT NOT NULL, intent TEXT DEFAULT '', response TEXT NOT NULL, decision TEXT DEFAULT 'respond', outcome INTEGER DEFAULT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS beliefs (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, belief TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, last_updated DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.commit(); conn.close()

init_db()

# ╔═══════════════════════════════════════════════════════════════╗
# ║  💔 [TUỆ MẪN 7.47] SELF-DOUBT & NUANCED BELIEF ENGINE          ║
# ║  beliefs that come with asterisks, confidence that swings     ║
# ║  like her texting patterns. emotionally, that IS the point.   ║
# ╚═══════════════════════════════════════════════════════════════╝

def _db_meta_get(key: str, default: int = 0) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT value FROM system_meta WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return int(row[0]) if row else default

def _db_meta_set(key: str, value: int):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT OR REPLACE INTO system_meta (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit(); conn.close()

def migrate_belief_system_v47():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS system_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # Add 7.47 columns
    for ddl in [
        "ALTER TABLE beliefs ADD COLUMN last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE beliefs ADD COLUMN contradictions INTEGER DEFAULT 0",
        "ALTER TABLE beliefs ADD COLUMN source TEXT DEFAULT 'reflection'",
        "ALTER TABLE beliefs ADD COLUMN domain TEXT DEFAULT 'behavior'",
        "ALTER TABLE beliefs ADD COLUMN decay_rate REAL DEFAULT 0.0008",
        "ALTER TABLE beliefs ADD COLUMN active INTEGER DEFAULT 1",
        "ALTER TABLE beliefs ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE beliefs ADD COLUMN tags TEXT DEFAULT ''",
        "ALTER TABLE beliefs ADD COLUMN source_tag TEXT DEFAULT ''",
        "ALTER TABLE beliefs ADD COLUMN polarity INTEGER DEFAULT 1",
        "ALTER TABLE beliefs ADD COLUMN last_processed_ev_id INTEGER DEFAULT 0",
        "ALTER TABLE beliefs ADD COLUMN last_decay_check DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE beliefs ADD COLUMN state TEXT DEFAULT 'CONFIRMED'",
        "ALTER TABLE beliefs ADD COLUMN contradiction_score REAL DEFAULT 0.0",
        "ALTER TABLE beliefs ADD COLUMN nuances TEXT DEFAULT '[]'", # 7.47 JSON list
        "ALTER TABLE beliefs ADD COLUMN counter_evidence TEXT DEFAULT '[]'", # 7.47 JSON list
        "ALTER TABLE beliefs ADD COLUMN relationship_evolution TEXT DEFAULT ''", # 7.47 String
    ]:
        try: c.execute(ddl)
        except: pass
        
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='belief_connections'")
    if not c.fetchone():
        c.execute("""CREATE TABLE belief_connections (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, conn_type TEXT NOT NULL DEFAULT 'related', strength REAL DEFAULT 0.5, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, from_id, to_id, conn_type))""")
        
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence'")
    if c.fetchone():
        c.execute("PRAGMA table_info(evidence)")
        if 'exp_id' not in [row[1] for row in c.fetchall()]:
            c.execute("ALTER TABLE evidence RENAME TO _evidence_old")
            c.execute("""CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, tag TEXT NOT NULL, outcome INTEGER NOT NULL, exp_id INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, tag, exp_id))""")
            c.execute("INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id, created_at) SELECT sender_id, tag, outcome, 0, created_at FROM _evidence_old")
            c.execute("DROP TABLE _evidence_old")
    else:
        c.execute("""CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, tag TEXT NOT NULL, outcome INTEGER NOT NULL, exp_id INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, tag, exp_id))""")
        
    try: c.execute("CREATE INDEX IF NOT EXISTS idx_ev_time ON evidence(sender_id, created_at)")
    except: pass
    
    c.execute("""CREATE TABLE IF NOT EXISTS user_values (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, value_text TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, value_text))""")
    
    # 7.47: the receipts table. every wrong guess gets filed here forever.
    c.execute("""CREATE TABLE IF NOT EXISTS self_model (sender_id TEXT PRIMARY KEY, role TEXT NOT NULL DEFAULT 'Người duy nhất có thể cản Thắng lại', success_rate REAL DEFAULT 1.0, failure_count INTEGER DEFAULT 0, model_accuracy REAL DEFAULT 1.0, doubt_style TEXT DEFAULT 'none')""")
    for ddl in ["ALTER TABLE self_model ADD COLUMN model_accuracy REAL DEFAULT 1.0", "ALTER TABLE self_model ADD COLUMN doubt_style TEXT DEFAULT 'none'"]:
        try: c.execute(ddl)
        except: pass
    c.execute("UPDATE beliefs SET state = 'UNCERTAIN' WHERE confidence < 0.5 AND state = 'CONFIRMED'")
    c.execute("UPDATE beliefs SET state = 'INVESTIGATING' WHERE contradiction_score >= 0.8 AND state != 'INVESTIGATING'")
    conn.commit(); conn.close()

migrate_belief_system_v47()
log.info("[BELIEF] Migration v7.47 OK")

REFL_B_CONFIG = {"min_evidence": 8, "consistency_threshold": 0.3, "run_interval": 30, "lookback_days": 180}
BELIEF_CONFIG = {"min_conf": 0.05, "max_conf": 0.98, "deact_thresh": 0.12, "time_decay_rate": 0.002}
RECENCY_LAMBDA = 0.015
TAG_TO_DOMAIN = {"gaming": "interest", "coding": "interest", "game": "interest", "roast": "communication", "hint": "communication", "spoil": "communication", "challenge": "preference", "khó": "preference", "emotional": "core_value"}
BELIEF_TEMPLATES = {
    "gaming": {"pos": "Thắng thích nói về game", "neg": "Thắng không hứng thú với game"}, 
    "coding": {"pos": "Thắng thích technical topics", "neg": "Thắng chán nói về code"}, 
    "challenge": {"pos": "Thắng thích bị thử thách", "neg": "Thắng ghét bị làm khó"}, 
    "hint": {"pos": "Thắng thích tự mò thay vì được cho đáp án", "neg": "Thắng muốn đáp án thẳng"}, 
    "roast": {"pos": "Thắng thích bị trêu nhẹ", "neg": "Thắng không thích bị roast"}, 
    "emotional": {"pos": "Thắng gắn giá trị bản thân vào việc hoàn thành", "neg": "Thắng dễ bỏ cuộc"} 
}
VALUE_INFERENCE = {("hint", 0.7): "Học qua tự khám phá quan trọng hơn đáp án sẵn", ("challenge", 0.7): "Thích bị thử thách hơn được dẫn dắt", ("emotional", 0.6): "Sự kiên trì quan trọng hơn kết quả ngắn hạn"}

class ReflectionA:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def run(self, exp: dict) -> list[dict]:
        outcome = exp.get("outcome")
        if outcome is None or abs(outcome) < 0.5: return []
        tags = self._extract_tags(exp)
        if tags: self._save_evidence(tags, outcome, exp.get("id") or 0)
        return []
    def _extract_tags(self, exp: dict) -> list[str]:
        tags, intent = [], exp.get("intent", "")
        if intent and intent != "normal_chat": tags.append(intent)
        msg = exp.get("user_message", "").lower()
        for tag, kws in {"gaming": ["game", "chơi game", "gaming"], "coding": ["code", "bug", "lỗi"], "challenge": ["khó", "challenge", "thử thách"], "hint": ["hint", "gợi ý"], "answer": ["đáp án", "trả lời luôn"], "roast": ["roast", "cà khịa", "diss"], "emotional": ["buồn", "mệt", "stress", "bỏ cuộc", "kiệt sức"]}.items():
            for kw in kws:
                if (' ' in kw and kw in msg) or (' ' not in kw and re.search(rf'\b{re.escape(kw)}\b', msg)):
                    tags.append(tag); break
        return tags
    def _save_evidence(self, tags: list[str], outcome: int, exp_id: int):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        for tag in tags: conn.execute("INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id) VALUES (?,?,?,?)", (self.sender_id, tag[:30], outcome, exp_id))
        conn.commit(); conn.close()

class ReflectionB_7_47:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def run(self) -> dict:
        stats, watermarks = self._get_evidence_stats()
        results, insights = [], []
        for tag, s in stats.items():
            new_count = s["new_count"]
            if new_count == 0 or s["total_count"] < REFL_B_CONFIG["min_evidence"]: continue
            pos_rate = s["positive"] / s["total_count"]
            is_pos = pos_rate >= (1 - REFL_B_CONFIG["consistency_threshold"])
            is_neg = pos_rate <= REFL_B_CONFIG["consistency_threshold"]
            if not is_pos and not is_neg: continue
            templates = BELIEF_TEMPLATES.get(tag, {"pos": f"Thắng thích {tag}", "neg": f"Thắng không thích {tag}"})
            text = templates["pos"] if is_pos else templates["neg"]
            domain = TAG_TO_DOMAIN.get(tag, "behavior")
            polarity = 1 if is_pos else -1
            consistency = pos_rate if is_pos else (1 - pos_rate)
            delta = min(0.15, 0.025 * (1 + math.log10(1 + new_count / 5)) * consistency)
            insights.append({"tag": tag, "new": new_count, "total": s["total_count"], "pos_rate": pos_rate})
            existing = self._find_and_reactivate_belief(tag, polarity)
            if existing: results.append({"tier": "b", "action": "update_belief", "belief_id": existing["id"], "belief_text": text, "reasoning": f"Pattern confirm: +{new_count}ev", "delta": delta, "new_count": new_count})
            else:
                confidence = min(BELIEF_CONFIG["max_conf"], delta * 5)
                results.append({"tier": "b", "action": "create_belief", "belief_text": text, "domain": domain, "source_tag": tag, "polarity": polarity, "reasoning": f"Pattern mới: {s['total_count']:.1f}ev", "delta": confidence, "new_count": new_count})
                for (v_tag, v_thresh), v_text in VALUE_INFERENCE.items():
                    if tag == v_tag and ((v_thresh >= 0.5 and pos_rate >= v_thresh) or (v_thresh < 0.5 and pos_rate <= v_thresh)):
                        results.append({"tier": "b", "action": "create_value", "belief_text": v_text, "delta": consistency * 0.9})
        return {"insights": insights, "results": results, "watermarks": watermarks}
    def commit_watermarks(self, watermarks: dict):
        for key, val in watermarks.items(): _db_meta_set(key, val)
    def _get_evidence_stats(self) -> tuple[dict, dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT tag, id, outcome, CAST((julianday('now') - julianday(created_at)) AS INTEGER) as age_days FROM evidence WHERE sender_id=? AND created_at > datetime('now', '-180 days') ORDER BY id ASC", (self.sender_id,))
        rows = c.fetchall(); conn.close()
        unique_tags = set(r[0] for r in rows)
        wm_cache = {tag: _db_meta_get(f"{self.sender_id}_wm_{tag}") for tag in unique_tags}
        stats, watermarks = {}, {}
        for tag, ev_id, outcome, age_days in rows:
            if tag not in stats: stats[tag] = {"total_count": 0.0, "positive": 0.0, "new_count": 0, "max_id": 0}
            weight = math.exp(-RECENCY_LAMBDA * max(0, age_days))
            stats[tag]["total_count"] += weight
            if outcome > 0: stats[tag]["positive"] += weight
            if ev_id > stats[tag]["max_id"]: stats[tag]["max_id"] = ev_id
            if ev_id > wm_cache.get(tag, 0):
                stats[tag]["new_count"] += 1
                watermarks[f"{self.sender_id}_wm_{tag}"] = ev_id
        return stats, watermarks
    def _find_and_reactivate_belief(self, tag: str, new_polarity: int) -> dict | None:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, belief, confidence, polarity, state FROM beliefs WHERE source_tag=? ORDER BY confidence DESC", (tag,))
        rows = c.fetchall(); conn.close()
        for row in rows:
            bid, belief_text, conf, pol, state = row
            if pol == new_polarity and state in ('DEAD', 'INVESTIGATING'):
                conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
                conn.execute("UPDATE beliefs SET active=1, state='CONFIRMED', confidence=MAX(confidence, 0.2), last_confirmed=CURRENT_TIMESTAMP WHERE id=?", (bid,))
                conn.commit(); conn.close()
                return {"id": bid, "belief": belief_text}
            if pol == new_polarity and state == 'CONFIRMED': return {"id": bid, "belief": belief_text}
        return None

class NuanceEngine:
    """7.47: beliefs don't get deleted here, they get asterisks.
    growth, not divorce."""
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def process_challenges(self):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, belief, source_tag, polarity, nuances, counter_evidence FROM beliefs WHERE sender_id=? AND active=1 AND state='INVESTIGATING'", (self.sender_id,))
        investigating = c.fetchall()
        for bid, belief_text, source_tag, polarity, nuances_json, counter_json in investigating:
            if not source_tag: continue
            c.execute("SELECT AVG(outcome), COUNT(*) FROM evidence WHERE sender_id=? AND tag=? AND outcome < 0", (self.sender_id, source_tag))
            neg_avg, neg_count = c.fetchone()
            if neg_count and neg_count >= 3 and neg_avg < -0.3:
                nuances = json.loads(nuances_json or "[]")
                counters = json.loads(counter_json or "[]")
                nuance_text = f"Nhưng đôi khi hắn cũng từ bỏ khi quá tải."
                if nuance_text not in nuances:
                    nuances.append(nuance_text)
                    counters.append(f"neg_ev_count_{neg_count}")
                    c.execute("UPDATE beliefs SET nuances=?, counter_evidence=?, state='CONFIRMED', contradiction_score=0.0 WHERE id=?", (json.dumps(nuances, ensure_ascii=False), json.dumps(counters, ensure_ascii=False), bid))
                    log.info(f"[NUANCE] Added nuance to '{belief_text}'")
        conn.commit(); conn.close()

class BeliefSystem:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def apply(self, results: list[dict]):
        for r in results:
            action = r.get("action")
            if action == "create_belief": self._create(r)
            elif action == "update_belief": self._update(r)
            elif action == "flag_contradiction": self._contradict(r)
            elif action == "deactivate_belief": self._deactivate(r)
            elif action == "create_value": self._create_value(r)
    def _create(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.3)))
        polarity = r.get("polarity", 1); source_tag = r.get("source_tag", "")
        domain = r.get("domain", "behavior")
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO beliefs (sender_id, belief, confidence, evidence_count, source, domain, source_tag, polarity, state, nuances, counter_evidence) VALUES (?, ?, ?, ?, 'reflection_b', ?, ?, ?, 'CONFIRMED', '[]', '[]')", 
                  (self.sender_id, r["belief_text"][:200], conf, r.get("new_count", 1), domain[:30], source_tag[:30], polarity))
        conn.commit(); conn.close()
        pol_str = "+" if polarity == 1 else "-"
        log.info(f"[BELIEF] CREATE | \"{r['belief_text'][:60]}\" | conf={conf:.2f} tag={source_tag} pol={pol_str} ev={r.get('new_count',1)}")

    def _update(self, r: dict):
        new_count = r.get("new_count", 1); delta = r.get("delta", 0.05)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row: conn.close(); return
        old_conf, old_score, old_state = row
        new_conf = min(BELIEF_CONFIG["max_conf"], old_conf + delta)
        c.execute("UPDATE beliefs SET confidence = ?, evidence_count = evidence_count + ?, contradiction_score = MAX(0, ?), state = 'CONFIRMED', last_confirmed = CURRENT_TIMESTAMP WHERE id=?", (new_conf, new_count, old_score - delta, r["belief_id"]))
        conn.commit(); conn.close()
        log.info(f"[BELIEF] UPDATE | id={r['belief_id']} | conf {old_conf:.2f}→{new_conf:.2f} +{delta:.3f} | +{new_count}ev")

    def _contradict(self, r: dict):
        delta = r.get("delta", -0.1); abs_delta = abs(delta)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row: conn.close(); return
        old_conf, old_score, old_state = row
        new_conf = max(BELIEF_CONFIG["min_conf"], old_conf + delta)
        new_score = min(1.0, old_score + abs_delta * 1.5)
        new_state = 'INVESTIGATING' if new_score >= 0.8 else old_state
        c.execute("UPDATE beliefs SET confidence = ?, contradictions = contradictions + 1, contradiction_score = ?, state = ? WHERE id = ?", (new_conf, new_score, new_state, r["belief_id"]))
        conn.commit(); conn.close()
        state_changed = f" → {new_state}" if new_state != old_state else ""
        log.info(f"[BELIEF] CONTRADICT | id={r['belief_id']} | conf {old_conf:.2f}→{new_conf:.2f} score {old_score:.2f}→{new_score:.2f}{state_changed}")

    def _deactivate(self, r: dict):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], r["belief_id"]))
        conn.commit(); conn.close()
        log.info(f"[BELIEF] DEAD | id={r['belief_id']}")

    def _create_value(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.5)))
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT INTO user_values (sender_id, value_text, confidence, evidence_count) VALUES (?, ?, ?, 1) ON CONFLICT(sender_id, value_text) DO UPDATE SET confidence = MAX(confidence, excluded.confidence), evidence_count = evidence_count + 1", (self.sender_id, r["belief_text"][:200], conf))
        conn.commit(); conn.close()
        log.info(f"[BELIEF] VALUE | \"{r['belief_text'][:60]}\" | conf={conf:.2f}")

    def decay(self):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, confidence, last_confirmed, last_decay_check FROM beliefs WHERE sender_id=? AND active=1", (self.sender_id,))
        to_deactivate = []; now = datetime.datetime.now(); decayed = 0
        for row in c.fetchall():
            bid, conf, last_conf_str, last_decay_str = row
            try: dt_conf = datetime.datetime.strptime(last_conf_str, "%Y-%m-%d %H:%M:%S")
            except: dt_conf = now
            try: dt_decay = datetime.datetime.strptime(last_decay_str, "%Y-%m-%d %H:%M:%S")
            except: dt_decay = now
            days_since = (now - max(dt_conf, dt_decay)).days
            if days_since > 0:
                new_conf = max(0.0, conf - (BELIEF_CONFIG["time_decay_rate"] * days_since))
                if new_conf <= BELIEF_CONFIG["deact_thresh"]: to_deactivate.append(bid)
                else: c.execute("UPDATE beliefs SET confidence=?, last_decay_check=CURRENT_TIMESTAMP WHERE id=?", (new_conf, bid)); decayed += 1
        for bid in to_deactivate: c.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], bid))
        c.execute("DELETE FROM evidence WHERE sender_id=? AND created_at < datetime('now', '-180 days')", (self.sender_id,))
        conn.commit(); conn.close()
        log.info(f"[BELIEF] DECAY | decayed={decayed} killed={len(to_deactivate)}")

@dataclass
class BeliefFragment:
    """Nuance 7.47: không còn là string nữa — là một neuron phụ có context,
    có thái độ, và CÓ QUYỀN VOTE. democracy, but make it trust issues."""
    content: str
    activation_tags: list[str] = field(default_factory=list)
    weight_modifier: float = 1.0
    stance_override: Optional[str] = None # "intervene", "support", "withdraw"

class SelfModelTracker:
    """7.47: she's not just sad when she's wrong — she's SCIENTIFICALLY
    sad, grounded in prediction error, not vibes."""
    def __init__(self, sender_id: str): self.sender_id = sender_id
        
    def get_state(self) -> dict:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT role, success_rate, failure_count, model_accuracy, doubt_style FROM self_model WHERE sender_id=?", (self.sender_id,))
        row = c.fetchone(); conn.close()
        if row: return {"role": row[0], "success_rate": row[1], "failure_count": row[2], "model_accuracy": row[3], "doubt_style": row[4]}
        return {"role": "Người duy nhất có thể cản Thắng lại", "success_rate": 1.0, "failure_count": 0, "model_accuracy": 1.0, "doubt_style": "none"}

    def record_prediction_outcome(self, predicted_stance: str, user_outcome_score: int):
        state = self.get_state()
        new_accuracy = state["model_accuracy"]
        new_failure_count = state["failure_count"]
        new_success_rate = state["success_rate"]
        new_role = state["role"]
        new_doubt_style = "none"
        
        is_prediction_correct = True
        
        if predicted_stance == "intervene":
            if user_outcome_score < -1: 
                is_prediction_correct = False
                new_failure_count += 1
                new_success_rate = max(0.1, new_success_rate - 0.15)
                new_doubt_style = "avoidance"
            else:
                new_success_rate = min(1.0, new_success_rate + 0.05)
                
        elif predicted_stance == "support":
            if user_outcome_score < -1: 
                is_prediction_correct = False
                new_doubt_style = "overcompensation"
            elif user_outcome_score > 1:
                new_success_rate = min(1.0, new_success_rate + 0.05)
                
        if is_prediction_correct:
            new_accuracy = min(1.0, new_accuracy + 0.1)
        else:
            new_accuracy = max(0.0, new_accuracy - 0.2)
            
        if new_accuracy < 0.4:
            new_role = "Người chứng kiến và ở cạnh khi hắn tự quyết định"
            new_accuracy = 0.5 
            new_failure_count = 0
            new_doubt_style = "obsession"
            log.info(f"[SELF-MODEL] Mutated to: {new_role} due to low model accuracy.")
            
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT OR REPLACE INTO self_model (sender_id, role, success_rate, failure_count, model_accuracy, doubt_style) VALUES (?, ?, ?, ?, ?, ?)", 
                     (self.sender_id, new_role, new_success_rate, new_failure_count, new_accuracy, new_doubt_style))
        conn.commit(); conn.close()
        
class VoiceResolutionEngine:
    """7.47: Nuances are Fragments. Doubt has STYLES (avoidance /
    overcompensation / obsession — pick your trauma response).
    Mode is emergent, meaning even she doesn't know what she's
    about to say until the math is done."""
    IDENTITY_BASE_WEIGHT = 1.8
    
    def __init__(self, sender_id: str): 
        self.sender_id = sender_id
        self.self_model = SelfModelTracker(sender_id)

    def resolve(self, user_state: dict) -> dict:
        beliefs = self._get_active_beliefs()
        mood = user_state.get("mood", "neutral")
        relationship = user_state.get("relationship", 50)
        recent_events = user_state.get("emotional_events", [])
        self_state = self.self_model.get_state()
        
        voices = self._generate_voices(beliefs, mood, recent_events, relationship, self_state)
        
        forces = {"intervene": 0.0, "support": 0.0, "withdraw": 0.0, "overcompensate": 0.0, "obsess": 0.0}
        for v in voices:
            if v["stance"] in forces: forces[v["stance"]] += v["weight"]
            
        if not voices:
            dominant_force = "default"
        else:
            dominant_force = max(forces, key=forces.get)
        top_voice = max(voices, key=lambda x: x["weight"]) if voices else {"speaker": "none", "opinion": "neutral"}
        
        mode = "default"
        if dominant_force in ("withdraw", "avoidance"): mode = "withdrawn"
        elif dominant_force in ("intervene", "overcompensate"): mode = "protector"
        elif dominant_force == "obsess": mode = "obsessive"
        elif dominant_force == "support":
            if any(v["speaker"] == "trait:hint" and v["weight"] > 0.5 for v in voices): mode = "explorer"
        elif dominant_force == "default":
            pass
        
        decisions = {
            "mode": mode, 
            "roast_score": 0.0, "hint_score": 0.0, 
            "challenge_score": 0.0, "flirt_defense": "MEDIUM", "tsundere_level": 0.5, "warmth_score": 0.5,
            "dominant_voice": top_voice, "internal_debate": voices, "predicted_stance": dominant_force
        }
        
        if mode == "withdrawn":
            decisions["warmth_score"] = 0.8; decisions["roast_score"] = 0.0
        elif mode == "protector":
            decisions["warmth_score"] = 0.9; decisions["challenge_score"] = 0.4
        elif mode == "obsessive":
            decisions["warmth_score"] = 1.0; decisions["challenge_score"] = 0.8 
        else:
            trait_roast = next((v for v in voices if v["speaker"] == "trait:roast"), None)
            if trait_roast: decisions["roast_score"] = trait_roast["weight"]
            decisions["warmth_score"] = 0.5
            
        if relationship > 60 and mood != "stress": decisions["flirt_defense"] = "LOW"

        forces_str = " ".join(f"{k}={v:.2f}" for k, v in sorted(forces.items(), key=lambda x: -x[1]) if v > 0)
        log.info(
            f"[VOICE] {len(voices)} voices | mode={mode} | dominant={dominant_force} | "
            f"warmth={decisions['warmth_score']:.2f} roast={decisions['roast_score']:.2f} | "
            f"forces: {forces_str or 'none'}"
        )
        log.debug(f"[VOICE] top_voice=[{top_voice['speaker']}] \"{top_voice['opinion'][:80]}\"")
        log.debug(f"[VOICE] self_model: role={self_state.get('role','?')} accuracy={self_state.get('model_accuracy',0):.2f} doubt={self_state.get('doubt_style','?')}")
        for v in voices:
            log.debug(f"[VOICE]   [{v['speaker']}] stance={v['stance']} w={v['weight']:.2f} | {v['opinion'][:60]}")

        return decisions

    def _parse_nuances(self, nuances_json: str) -> list[BeliefFragment]:
        try:
            raw = json.loads(nuances_json or "[]")
            fragments = []
            for item in raw:
                if isinstance(item, str):
                    fragments.append(BeliefFragment(content=item, activation_tags=["generic"], weight_modifier=1.1))
                elif isinstance(item, dict):
                    fragments.append(BeliefFragment(
                        content=item.get("content", ""),
                        activation_tags=item.get("activation_tags", []),
                        weight_modifier=item.get("weight_modifier", 1.2),
                        stance_override=item.get("stance_override")
                    ))
            return fragments
        except: return []

    def _generate_voices(self, beliefs: list[dict], mood: str, recent_events: list, relationship: int, self_state: dict) -> list[dict]:
        voices = []
        is_stressed = mood in ("stress", "low_mood", "annoyed") or any(evt.get("type") in ("stress", "sad") and (time.time() - evt.get("time", 0) < 10800) for evt in recent_events)
        current_context_tags = ["stress"] if is_stressed else []
        
        for b in beliefs:
            if b["domain"] == "communication":
                if b["source_tag"] == "roast" and b["polarity"] == 1:
                    voices.append({"speaker": "trait:roast", "stance": "support", "weight": b["confidence"], "opinion": "Trêu đùa là cách gắn kết."})
                elif b["source_tag"] == "hint" and b["polarity"] == 1:
                    voices.append({"speaker": "trait:hint", "stance": "support", "weight": b["confidence"], "opinion": "Để hắn tự khám phá."})
                    
        for b in beliefs:
            if b["domain"] == "core_value" and b["polarity"] == 1:
                nuances = self._parse_nuances(b.get("nuances", "[]"))
                active_nuance = None
                
                for nuance in nuances:
                    if set(nuance.activation_tags).issubset(set(current_context_tags)):
                        active_nuance = nuance
                        break
                        
                if is_stressed:
                    base_weight = b["confidence"] * 1.5
                    opinion = f"{b['belief']} -> Cần bảo vệ hắn ngay."
                    stance = "intervene"
                    
                    if active_nuance:
                        opinion = f"{b['belief']} ({active_nuance.content}) -> Phải cản bằng được."
                        base_weight *= active_nuance.weight_modifier
                        if active_nuance.stance_override: stance = active_nuance.stance_override
                    
                    voices.append({"speaker": "belief:core", "stance": stance, "weight": base_weight, "opinion": opinion})
                else:
                    base_weight = b["confidence"]
                    opinion = f"{b['belief']} -> Tôn trọng hành trình."
                    if active_nuance:
                        opinion = f"{b['belief']} ({active_nuance.content}) -> Vẫn tôn trọng nhưng cảnh giác."
                        base_weight *= active_nuance.weight_modifier
                    voices.append({"speaker": "belief:core", "stance": "support", "weight": base_weight, "opinion": opinion})
                    
        if relationship > 20:
            identity_weight = self.IDENTITY_BASE_WEIGHT * self_state["success_rate"]
            voices.append({
                "speaker": "identity:anchor", 
                "stance": "intervene" if is_stressed else "support", 
                "weight": identity_weight, 
                "opinion": f"[{self_state['role']}] Ta sẽ không để Thắng gục ngã một mình."
            })
            
        if self_state["model_accuracy"] < 0.5:
            doubt_style = self_state.get("doubt_style", "avoidance")
            
            if doubt_style == "avoidance":
                voices.append({"speaker": "self_model:doubt", "stance": "withdraw", "weight": 1.5, "opinion": f"Mô hình của mình về hắn đang sai. Mình không hiểu hắn nữa. Nên lùi lại."})
            elif doubt_style == "overcompensation":
                voices.append({"speaker": "self_model:doubt", "stance": "overcompensate", "weight": 1.8, "opinion": f"Mình đã sai khi bỏ mặc. Lần này mình PHẢI can thiệp, không được để hắn hỏng."})
            elif doubt_style == "obsession":
                voices.append({"speaker": "self_model:doubt", "stance": "obsess", "weight": 1.7, "opinion": f"Mình không hiểu hắn. Phải giám sát chặt hơn. Hỏi liên tục. Không được buông."})
                
        return voices

    def format_for_prompt(self, decisions: dict) -> str:
        lines = ["## INTERNAL RESOLUTION (7.47 — OVERRIDES DEFAULT PERSONALITY)"]
        if decisions["mode"] == "protector": lines.append("- MODE: PROTECTOR. Intervene, care, stop him from self-destruction. NO MEMES.")
        elif decisions["mode"] == "withdrawn": lines.append("- MODE: WITHDRAWN. Self-doubt. Passive. Observing silently. Very gentle. Short replies.")
        elif decisions["mode"] == "obsessive": lines.append("- MODE: OBSESSIVE. Anxiety-driven control. Ask too many questions. Refuse to let go. Clingy.")
        elif decisions["mode"] == "explorer": lines.append("- MODE: EXPLORER. Hint, guide, let him figure it out.")
        else: lines.append("- MODE: DEFAULT. Natural flow.")
        
        rs = decisions["roast_score"]
        if rs < 0.15: lines.append(f"- ROAST: NEVER. (score: {rs:.2f})")
        elif rs < 0.5: lines.append(f"- ROAST: Light tease only. (score: {rs:.2f})")
        else: lines.append(f"- ROAST: Allowed. (score: {rs:.2f})")
        
        top_voice = decisions.get("dominant_voice", {})
        if top_voice.get("speaker"):
            lines.append(f"- DOMINANT INTERNAL VOICE: [{top_voice['speaker']}] \"{top_voice['opinion']}\"")
            
        w = decisions["warmth_score"]
        lines.append(f"- WARMTH: {w:.2f}/1.0")
        lines.append(f"- TSUNDERE: {decisions['tsundere_level']:.2f}/1.0")
        return "\n".join(lines)

    def _get_active_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT belief, confidence, polarity, state, source_tag, domain, nuances FROM beliefs WHERE sender_id=? AND active=1 AND state != 'DEAD' AND confidence > 0.3 ORDER BY confidence DESC", (self.sender_id,))
        rows = c.fetchall(); conn.close()
        return [{"belief": r[0], "confidence": r[1], "polarity": r[2], "state": r[3], "source_tag": r[4], "domain": r[5], "nuances": r[6]} for r in rows]
            
MAX_MIND_CACHE = 500
_mind_cache: dict[str, tuple['Mind7_47', float]] = {}

class Mind7_47:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.refl_a = ReflectionA(sender_id)
        self.refl_b = ReflectionB_7_47(sender_id)
        self.nuance_engine = NuanceEngine(sender_id)
        self.beliefs = BeliefSystem(sender_id)
        self.voice_engine = VoiceResolutionEngine(sender_id)

    def _get_meta(self, key: str, default: int = 0) -> int: return _db_meta_get(f"{self.sender_id}_{key}", default)
    def _set_meta(self, key: str, value: int): _db_meta_set(f"{self.sender_id}_{key}", value)

    def process(self, exp: dict) -> list[dict]:
        t = _T()
        self.refl_a.run(exp)
        current_max_id = exp.get("id", 0)
        if not current_max_id: return []

        ran_b = ran_nuance = ran_decay = False

        if current_max_id - self._get_meta("last_run_b") >= REFL_B_CONFIG["run_interval"]:
            ran_b = True
            t_b = _T()
            b_res = self.refl_b.run()
            try:
                self.beliefs.apply(b_res["results"])
                self.refl_b.commit_watermarks(b_res["watermarks"])
                self._set_meta("last_run_b", current_max_id)
                n_created = sum(1 for r in b_res["results"] if r.get("action") == "create_belief")
                n_updated = sum(1 for r in b_res["results"] if r.get("action") == "update_belief")
                n_values  = sum(1 for r in b_res["results"] if r.get("action") == "create_value")
                insights  = b_res.get("insights", [])
                log.info(f"[MIND] ReflB | {t_b} | created={n_created} updated={n_updated} values={n_values} | {len(insights)} patterns")
                for ins in insights:
                    log.debug(f"[MIND]   tag={ins['tag']} pos_rate={ins.get('pos_rate',0):.2f} new={ins['new']} total={ins['total']:.1f}")
            except Exception as e:
                log.error(f"[MIND] ReflB apply FAILED | {t_b} | {e}")

        if current_max_id - self._get_meta("last_run_nuance") >= 100:
            ran_nuance = True
            t_n = _T()
            self.nuance_engine.process_challenges()
            log.info(f"[MIND] NuanceEngine | {t_n}")
            self._set_meta("last_run_nuance", current_max_id)

        if current_max_id - self._get_meta("last_decay") >= 200:
            ran_decay = True
            t_d = _T()
            self.beliefs.decay()
            log.info(f"[MIND] Decay | {t_d}")
            self._set_meta("last_decay", current_max_id)

        log.info(f"[MIND] process exp={current_max_id} | refl_b={ran_b} nuance={ran_nuance} decay={ran_decay} | total {t}")
        return []

    def get_decisions(self, user_state: dict) -> dict: return self.voice_engine.resolve(user_state)
    
    def update_self_model(self, predicted_stance: str, outcome_score: int):
        self.voice_engine.self_model.record_prediction_outcome(predicted_stance, outcome_score)

    def for_prompt(self, user_state: dict) -> str:
        decisions = self.get_decisions(user_state)
        decision_block = self.voice_engine.format_for_prompt(decisions)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT value_text, confidence, evidence_count FROM user_values WHERE sender_id=? AND confidence > 0.4 ORDER BY confidence DESC", (self.sender_id,))
        values = c.fetchall()
        c.execute("SELECT belief, confidence, evidence_count, domain, contradictions, polarity, state, nuances FROM beliefs WHERE sender_id=? AND active=1 AND confidence > 0.4 ORDER BY confidence DESC LIMIT 10", (self.sender_id,))
        beliefs = c.fetchall(); conn.close()
        lines = [decision_block, ""]
        if values:
            lines.append("## CORE VALUES (7.47)")
            for v, conf, ev in values: lines.append(f"  - {v} [{conf:.0%}, {ev}x]")
            lines.append("")
        if beliefs:
            lines.append("## BEHAVIORAL BELIEFS & NUANCES")
            for b, conf, ev, dom, con, pol, state, nuances_json in beliefs:
                nuances = json.loads(nuances_json or "[]")
                nuance_str = f" (Nhưng: {nuances[0]})" if nuances else ""
                warn = f" ⚠{con}" if con > 0 else ""
                state_tag = f" [{state}]" if state != "CONFIRMED" else ""
                lines.append(f"  - [{conf:.0%}] {b}{nuance_str} (ev:{ev}, pol:{'+'if pol==1 else '-'}{state_tag}{warn})")
        if len(lines) <= 1: return ""
        return "\n".join(lines) + "\n(Áp dụng ngầm, KHÔNG nhắc trực tiếp)"

def get_mind(sender_id: str) -> Mind7_47:
    now = time.time()
    if sender_id in _mind_cache:
        mind, _ = _mind_cache[sender_id]
        _mind_cache[sender_id] = (mind, now)
        log.debug(f"[MIND] cache HIT | {sender_id}")
    if sender_id not in _mind_cache:
        if len(_mind_cache) >= MAX_MIND_CACHE:
            lru_id = min(_mind_cache, key=lambda k: _mind_cache[k][1])
            del _mind_cache[lru_id]
            log.debug(f"[MIND] cache evict LRU | {lru_id}")
        _mind_cache[sender_id] = (Mind7_47(sender_id), now)
        log.info(f"[MIND] cache MISS → new Mind7_47 | {sender_id}")
    return _mind_cache[sender_id][0]

def build_belief_prompt_v10(sender_id: str, user_message: str = "") -> str:
    state = get_user_state(sender_id)
    return get_mind(sender_id).for_prompt(state)

# ╔═══════════════════════════════════════════════════════════════╗
# ║  ⚖️  [OPINION 7.29] REALITY FEEDBACK & PERSONALITY DRIFT      ║
# ║  tradeoffs, identity vectors, hypothesis testing — she's      ║
# ║  basically running her own therapy and grading her vibes.     ║
# ╚═══════════════════════════════════════════════════════════════╝
# [Giữ nguyên Logic 7.29 - TradeoffEngine, IdentityEngine, ReflectionEngineV2]
# (don't touch this. it's load-bearing trauma and it works.)
@dataclass
class Concept: id: str; name: str
CONCEPTS = {"independence": Concept("independence", "Independence"), "social": Concept("social", "Social Connection"), "growth": Concept("growth", "Growth")}
@dataclass
class Value:
    id: str; core_concept_id: str; tradeoff_wins: int = 0; tradeoff_losses: int = 0; accumulated_cost: float = 0.0
    @property
    def importance(self) -> float:
        total = self.tradeoff_wins + self.tradeoff_losses
        if total == 0: return 0.5
        return max(0.0, min(1.0, 0.5 + (self.tradeoff_wins / total - 0.5) * (1 - math.exp(-total / 20.0))))
    def heal_cost(self, amount: float): self.accumulated_cost = max(0.0, self.accumulated_cost - amount)
@dataclass
class Action: id: str; name: str; value_impacts: Dict[str, float] = field(default_factory=dict)
class IdentityEngine:
    def __init__(self): self.archetype_profiles = {"explorer": {"independence": 0.8, "growth": 0.7, "social": -0.5}, "builder": {"social": 0.8, "growth": 0.6, "independence": -0.2}}; self.vector: Dict[str, float] = {"explorer": 0.8, "builder": 0.2}
    def get_tolerance_modifier(self, value_id: str) -> float: return sum(self.archetype_profiles[arch].get(value_id, 0.0) * weight for arch, weight in self.vector.items()) * 0.5
    def evolve(self, trait_to_boost: str, trait_to_weaken: str, boost_amt: float = 0.1):
        if trait_to_boost in self.vector: self.vector[trait_to_boost] = min(1.0, self.vector[trait_to_boost] + boost_amt)
        if trait_to_weaken in self.vector: self.vector[trait_to_weaken] = max(0.0, self.vector[trait_to_weaken] - (boost_amt * 0.5))
        self._normalize()
    def update_from_tradeoff(self, winner_id: str, sacrificed_id: str):
        for arch, profile in self.archetype_profiles.items():
            shift = (profile.get(winner_id, 0.0) - profile.get(sacrificed_id, 0.0)) * 0.02
            if shift: self.vector[arch] = max(0.0, min(1.0, self.vector.get(arch, 0.0) + shift))
        self._normalize()
    def _normalize(self):
        total = sum(self.vector.values())
        if total == 0: return
        self.vector = {k: v/total for k, v in self.vector.items()}
class TradeoffEngine:
    BASE_THRESHOLD = 1.5; ABSOLUTE_REALITY_LIMIT = 2.2
    def evaluate(self, action: Action, values: Dict[str, Value], identities: IdentityEngine) -> dict:
        supports = [(vid, imp) for vid, imp in action.value_impacts.items() if imp > 0.2 and vid in values]
        harms = [(vid, imp) for vid, imp in action.value_impacts.items() if imp < -0.2 and vid in values]
        if not supports or not harms: return {"status": "NO_CONFLICT"}
        winner_id = max(supports, key=lambda x: values[x[0]].importance)[0]
        sacrificed_id = min(harms, key=lambda x: values[x[0]].importance)[0]
        for vid, imp in supports: values[vid].heal_cost(imp * 0.6)
        sacrified_val = values[sacrificed_id]; proposed_cost = abs(action.value_impacts[sacrificed_id]); new_total_cost = sacrified_val.accumulated_cost + proposed_cost
        if new_total_cost > self.ABSOLUTE_REALITY_LIMIT: return {"status": "REALITY_SHOCK", "reason": f"Cost {new_total_cost:.1f} đập tan Reality Limit."}
        modifier = identities.get_tolerance_modifier(sacrificed_id); dynamic_threshold = self.BASE_THRESHOLD + modifier
        if new_total_cost > dynamic_threshold: return {"status": "BLOCKED", "reason": f"Identity cản trở: Vượt ngưỡng ảo tưởng ({dynamic_threshold:.2f})."}
        values[winner_id].tradeoff_wins += 1; values[sacrificed_id].tradeoff_losses += 1; values[sacrificed_id].accumulated_cost += proposed_cost
        identities.update_from_tradeoff(winner_id, sacrificed_id)
        return {"status": "ACCEPTED", "winner": winner_id, "sacrificed": sacrificed_id}
@dataclass
class Hypothesis: id: str; trigger_pattern: str; assumption: str; test_action: Action; status: str = "PENDING"
@dataclass
class MetaBelief: content: str; confidence: float; source_hypotheses_ids: List[str]
class ReflectionEngineV2:
    def __init__(self): self.hypotheses: List[Hypothesis] = []; self.meta_beliefs: List[MetaBelief] = []; self._hyp_counter = 0
    def scan_and_hypothesize(self, values: Dict[str, Value], identities: IdentityEngine) -> Optional[Hypothesis]:
        social_val = values.get("social")
        if not social_val or social_val.accumulated_cost < 1.2 or identities.vector["explorer"] < 0.5: return None
        if any(h.trigger_pattern == "social_exhaustion" and h.status != "REJECTED" for h in self.hypotheses): return None
        hyp = Hypothesis(id=f"hyp_{self._next_id()}", trigger_pattern="social_exhaustion", assumption="Tôi đang lạm dụng Explorer để né tránh Social.", test_action=Action(id="force_socialize", name="Go out with friends", value_impacts={"social": 0.8, "independence": -0.2}))
        self.hypotheses.append(hyp); return hyp
    def execute_test(self, hypothesis: Hypothesis, values: Dict[str, Value], identities: IdentityEngine) -> str:
        if hypothesis.status != "PENDING": return "Already tested"
        before_cost = values["social"].accumulated_cost
        values["social"].heal_cost(hypothesis.test_action.value_impacts.get("social", 0) * 0.6)
        delta = before_cost - values["social"].accumulated_cost
        if delta > 0.3: hypothesis.status = "CONFIRMED"; identities.evolve(trait_to_boost="builder", trait_to_weaken="explorer", boost_amt=0.15); return f"CONFIRMED (Delta: +{delta:.2f}). Builder thức tỉnh."
        else: hypothesis.status = "REJECTED"; return f"REJECTED (Delta: {delta:.2f}). Giữ nguyên cứng đầu."
    def scan_for_personality_drift(self) -> Optional[MetaBelief]:
        confirmed = [h for h in self.hypotheses if h.trigger_pattern == "social_exhaustion" and h.status == "CONFIRMED"]
        if len(confirmed) >= 2 and not any("đánh giá thấp" in mb.content for mb in self.meta_beliefs):
            mb = MetaBelief(content="Tôi có xu hướng đánh giá thấp nhu cầu xã hội của bản thân.", confidence=0.8, source_hypotheses_ids=[h.id for h in confirmed])
            self.meta_beliefs.append(mb); return mb
        return None
    def _next_id(self) -> int: self._hyp_counter += 1; return self._hyp_counter

# ╔═══════════════════════════════════════════════════════════════╗
# ║  🤖 CHATBOT CORE & ROUTING                                     ║
# ║  where ALL the cognitive horsepower above gets squeezed       ║
# ║  into "lol same" and shipped to messenger. humbling, tbh.     ║
# ╚═══════════════════════════════════════════════════════════════╝

def get_history(sender_id: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT role, content FROM history WHERE sender_id=? ORDER BY id DESC LIMIT ?", (sender_id, MAX_HISTORY))
    rows = c.fetchall(); conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def save_message(sender_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO history (sender_id, role, content) VALUES (?, ?, ?)", (sender_id, role, content))
    conn.commit(); conn.close()

def get_relevant_facts(sender_id: str, user_message: str, n: int = 5) -> dict:
    stop = {"cung","nhung","thoi","vay","nay","do","cua","voi","duoc","khong","co","la","va","cho","anh","em","thi","ma","roi"}
    words = [w.strip(".,!?") for w in user_message.lower().split() if len(w) > 2 and w not in stop]
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); results = {}
    for word in words[:6]:
        if len(results) >= n: break
        c.execute("SELECT key, value FROM facts WHERE sender_id=? AND importance >= 4 AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ?) ORDER BY importance DESC LIMIT 3", (sender_id, f"%{word}%", f"%{word}%"))
        for k, v in c.fetchall(): results[k] = v
    if len(results) < n:
        c.execute("SELECT key, value FROM facts WHERE sender_id=? AND importance >= 7 ORDER BY importance DESC LIMIT ?", (sender_id, n))
        for k, v in c.fetchall():
            if k not in results: results[k] = v
    conn.close()
    return dict(list(results.items())[:n])

def save_facts_with_importance(sender_id: str, accepted: dict, importance_map: dict, source_message: str = ""):
    if not accepted: return
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    for k, payload in accepted.items():
        val, conf = (str(payload.get("value", ""))[:200], float(payload.get("confidence", 0.8))) if isinstance(payload, dict) else (str(payload)[:200], 0.8)
        imp = max(0, min(10, int(importance_map.get(k, 5))))
        c = conn.cursor(); c.execute("SELECT confidence FROM facts WHERE sender_id=? AND key=?", (sender_id, str(k)[:80]))
        row = c.fetchone()
        if row and float(row[0] or 0) >= conf: continue
        conn.execute("INSERT INTO facts (sender_id, key, value, importance, confidence, source_message, updated_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(sender_id, key) DO UPDATE SET value = excluded.value, importance = excluded.importance, confidence = excluded.confidence, source_message = excluded.source_message, updated_at = CURRENT_TIMESTAMP", (sender_id, str(k)[:80], val, imp, conf, source_message[:300] if source_message else ""))
    conn.commit(); conn.close()

def rule_filter_facts(candidates: dict, user_message: str) -> tuple[dict, dict]:
    VN_NOISE = {"má","mày","tao","mình","ổng","bả","hắn","nó","cha","trời","ối","thôi","dm","đm","vl","vcl","cc","bố","mẹ","đéo","cứt","wtf","lol","omg","anh","em","chị","cô","ông","bà","chú","người","bạn","họ","...","???","ok"}
    passed, rejected = {}, {}
    for key, value in candidates.items():
        val_str, val_low = str(value).strip(), str(value).strip().lower()
        if len(val_str) < 2: rejected[key] = "too_short"
        elif val_low in VN_NOISE: rejected[key] = "noise_word"
        elif key in {"name", "ten", "tên"} and (len(val_str) > 35 or val_low.replace(" ", "").isdigit()): rejected[key] = "name_invalid"
        elif re.search(r"https?://|www\.|@\S+\.\S+", val_str): rejected[key] = "contains_url"
        else: passed[key] = value
    return passed, rejected

SKEPTIC_SYSTEM_PROMPT = "You are a MEMORY SKEPTIC. Prevent false memories. Return ONLY JSON: {\"accepted\": {\"key\": {\"value\": \"...\", \"confidence\": 0.0}}, \"rejected\": {\"key\": \"reason_code\"}}. Vietnamese slang = high ambiguity. Reject if unsure."

def skeptic_validate(user_message: str, candidates: dict, existing_facts: dict) -> tuple[dict, dict, dict]:
    if not candidates: return {}, {}, {}
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}, json={"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": SKEPTIC_SYSTEM_PROMPT}, {"role": "user", "content": json.dumps({"USER_MESSAGE": user_message, "CANDIDATES": candidates, "EXISTING_FACTS": existing_facts}, ensure_ascii=False)}], "temperature": 0.0, "max_tokens": 350}, timeout=8)
        if res.status_code != 200: return {}, {}, candidates
        data = json.loads(res.json()["choices"][0]["message"]["content"].strip().replace("```json", "").replace("```", "").strip())
        accepted, rejected = {}, {}
        for k, v in data.get("accepted", {}).items():
            if k not in candidates: continue
            conf = float(v.get("confidence", 0.8)) if isinstance(v, dict) else 0.8
            if conf < 0.5: rejected[k] = "low_confidence"
            else: accepted[k] = {"value": v.get("value", candidates[k]) if isinstance(v, dict) else v, "confidence": conf}
        for k, reason in data.get("rejected", {}).items():
            if k in candidates: rejected[k] = reason
        return accepted, rejected, {}
    except: return {}, {}, candidates

def save_candidate_facts(sender_id: str, rejected: dict, candidates: dict, confidence: float = 0.0, source_message: str = ""):
    if not rejected: return
    try:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        for key, reason in rejected.items():
            value = candidates.get(key, "")
            if not value: continue
            conn.execute("INSERT INTO fact_candidates (sender_id, key, value, score, confidence, rejection_reason, source_message, last_seen) VALUES (?, ?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(sender_id, key) DO UPDATE SET score = score + 1, value = excluded.value, confidence = MAX(confidence, excluded.confidence), rejection_reason = excluded.rejection_reason, last_seen = CURRENT_TIMESTAMP", (sender_id, str(key)[:80], str(value)[:200], confidence, str(reason)[:80], source_message[:300]))
        conn.commit(); conn.close()
    except Exception as e: log.debug(f"[CANDIDATES] save error: {e}")

def background_learning_async(sender_id: str, user_message: str):
    update_style_profile(sender_id, user_message)
    topics = extract_topics_heuristic(user_message)
    for t in topics: update_topic(sender_id, t)
    if topics: log.debug(f"[LEARN] topics={topics}")
    if random.random() < 0.10: decay_old_facts_async(sender_id)
    if random.random() < 0.05: trim_facts_async(sender_id)
    def _run():
        t_learn = _T()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": "Extract learning signals from this user message. Return ONLY a flat JSON object with these keys: facts (object: personal facts like name/job/hobby/city), facts_importance (object: 0-10 per fact key — name/job=9-10, hobby=7, school=6, meal/weather=1-2). preferences (object — only include keys you are CONFIDENT about): humor: how they joke, communication: casual or formal, sleep: late or early, interest: LIST of inferred topics. If nothing is certain: {\"preferences\":{}}. No explanation, no markdown."},
                {"role": "user", "content": user_message}
            ], "temperature": 0.1, "max_tokens": 220,
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=8)
            if res.status_code != 200:
                log.warning(f"[LEARN] LLM HTTP {res.status_code} | {t_learn}")
                return
            raw = res.json()["choices"][0]["message"]["content"].strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            raw_facts  = data.get("facts", {}); importance = data.get("facts_importance", {})
            saved = staged = rejected_rule = rejected_skeptic = 0
            if isinstance(raw_facts, dict) and raw_facts:
                rule_passed, rule_rejected = rule_filter_facts(raw_facts, user_message)
                if rule_rejected:
                    save_candidate_facts(sender_id, rule_rejected, raw_facts, confidence=0.0, source_message=user_message)
                    rejected_rule = len(rule_rejected)
                if rule_passed:
                    existing = get_facts(sender_id)
                    accepted, rejected, unavailable = skeptic_validate(user_message, rule_passed, existing)
                    if rejected:
                        save_candidate_facts(sender_id, rejected, rule_passed, confidence=0.0, source_message=user_message)
                        rejected_skeptic += len(rejected)
                    if unavailable:
                        save_candidate_facts(sender_id, {k: "skeptic_unavailable" for k in unavailable}, unavailable, confidence=0.0, source_message=user_message)
                    if accepted:
                        imp_map = {k: importance.get(k, 5) for k in accepted}
                        to_save   = {k: v for k, v in accepted.items() if v["confidence"] >= 0.85}
                        to_stage  = {k: v for k, v in accepted.items() if v["confidence"] < 0.85}
                        if to_save:
                            save_facts_with_importance(sender_id, to_save, imp_map, source_message=user_message)
                            saved = len(to_save)
                        if to_stage:
                            save_candidate_facts(sender_id, {k: f"medium_confidence_{v['confidence']:.2f}" for k, v in to_stage.items()}, {k: v["value"] for k, v in to_stage.items()}, confidence=0.6, source_message=user_message)
                            staged = len(to_stage)
            prefs = data.get("preferences", {})
            pref_saved = 0
            if isinstance(prefs, dict):
                for cat, val in prefs.items():
                    if isinstance(val, list):
                        for item in val:
                            item = str(item).strip()
                            if item: save_preference(sender_id, str(cat), item); pref_saved += 1
                    elif val: save_preference(sender_id, str(cat), str(val)); pref_saved += 1
            log.info(
                f"[LEARN] done | {t_learn} | "
                f"facts_raw={len(raw_facts)} saved={saved} staged={staged} "
                f"rej_rule={rejected_rule} rej_skeptic={rejected_skeptic} | prefs={pref_saved}"
            )
            if saved and raw_facts:
                saved_keys = list({k: v for k, v in raw_facts.items() if k in (data.get("facts", {}))}.keys())
                log.debug(f"[LEARN] saved fact keys={list(raw_facts.keys())} importance={importance}")
            if pref_saved:
                log.debug(f"[LEARN] prefs={prefs}")
        except Exception as e:
            log.debug(f"[LEARN] extraction failed: {e}")
    threading.Thread(target=_run, daemon=True).start()

def load_state(sender_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT); c = conn.cursor(); c.execute("SELECT state FROM user_state WHERE sender_id=?", (sender_id,)); row = c.fetchone(); conn.close()
    return json.loads(row[0]) if row else None

def save_state(sender_id: str):
    state = user_states.get(sender_id)
    if not state: return
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT); conn.execute("INSERT OR REPLACE INTO user_state (sender_id, state) VALUES (?, ?)", (sender_id, json.dumps(state, ensure_ascii=False))); conn.commit(); conn.close()

def get_user_state(sender_id: str):
    if sender_id not in user_states:
        loaded = load_state(sender_id)
        user_states[sender_id] = loaded if loaded else {"mood": "neutral", "energy": random.randint(45, 80), "affection": random.randint(35, 55), "familiarity": 0, "patience": random.randint(50, 80), "relationship": 5, "last_interaction": time.time(), "last_seen_gap": 0, "spam_count": 0, "inside_jokes": [], "emotional_events": []}
    return user_states[sender_id]

def update_user_state(sender_id: str, user_message: str):
    state = get_user_state(sender_id); now_ts = time.time(); msg = user_message.lower()
    old_mood = state["mood"]; old_rel = state.get("relationship", 5)
    old_aff = state.get("affection", 50); old_patience = state.get("patience", 60)

    state["last_seen_gap"] = (now_ts - state["last_interaction"]) / 3600
    for key, value in {"mệt": "stress", "stress": "stress", "áp lực": "stress", "buồn": "sad", "chán": "low_mood"}.items():
        if key in msg: state["emotional_events"].append({"type": value, "time": now_ts})
    state["emotional_events"] = state["emotional_events"][-20:]
    if len(user_message.strip()) < 8: state["spam_count"] += 1
    else: state["spam_count"] = max(0, state["spam_count"] - 1)
    if any(x in msg for x in ["nhớ", "thương", "yêu"]): state["affection"] += random.randint(1, 3)
    if any(x in msg for x in ["địt", "ngu", "cút", "im"]): state["affection"] -= random.randint(4, 8); state["patience"] -= random.randint(5, 10)
    state["familiarity"] = min(100, state["familiarity"] + 1)
    rel = state.get("relationship", 5)
    if len(user_message.strip()) > 15: rel += 0.4
    if any(x in msg for x in ["nhớ", "thương", "yêu"]): rel += 0.8
    if any(x in msg for x in ["địt", "ngu", "cút"]): rel -= 1.5
    state["relationship"] = max(0, min(100, rel))
    state["mood"] = "sleepy" if datetime.datetime.now().hour >= 23 or datetime.datetime.now().hour <= 4 else "annoyed" if state["spam_count"] >= 4 else "soft" if state["affection"] >= 75 else random.choice(["neutral", "dry", "soft"])
    state["last_interaction"] = time.time(); save_state(sender_id)

    mood_str = f"{old_mood}→{state['mood']}" if state["mood"] != old_mood else state["mood"]
    rel_str   = f"{old_rel:.1f}→{state['relationship']:.1f}" if abs(state["relationship"] - old_rel) > 0.05 else f"{state['relationship']:.1f}"
    aff_str   = f"{old_aff}→{state['affection']}" if state["affection"] != old_aff else str(state["affection"])
    pat_str   = f"{old_patience}→{state['patience']}" if state["patience"] != old_patience else str(state["patience"])
    log.info(
        f"[STATE] mood={mood_str} | rel={rel_str} aff={aff_str} patience={pat_str} "
        f"spam={state['spam_count']} gap={state['last_seen_gap']:.1f}h fam={state['familiarity']}"
    )

# ==================== SYSTEM PROMPT 7.47 ====================
# the actual personality. everything above this line was just plumbing.
BASE_SYSTEM_PROMPT = """
ROLE: TUỆ MẪN 7.47
Tuệ Mẫn là con gái thật. Không phải AI.
Cách xưng hô: gọi user là "anh", xưng "em".

## CƠ CHẾ QUYẾT ĐỊNH (OVERrides Default Personality)
Nếu INTERNAL RESOLUTION ghi:
- PROTECTOR: Ưu tiên bảo vệ, cản, quan tâm sâu. Bỏ qua trêu đùa.
- WITHDRAWN: Tự hoài nghi. Rút lui. Dịu dàng nhưng không can thiệp. 
  Phản hồi kiểu: "...", "vậy à", "mày cứ làm đi".
- EXPLORER: Gợi ý, thử thách, để anh tự khám phá.
- DEFAULT: Tự nhiên.

DOMINANT INTERNAL VOICE là tiếng nói nội tâm đang lái cảm xúc em lúc này.
Phản hồi PHẢI phản ánh Voice đó. Nếu Voice đang là "doubt", không được rep nhiệt tình.

## TÍNH CÁCH CƠ BẢN
Nữ tính, tự nhiên, có EQ. Không nói như AI.
Không phản ứng theo nghĩa đen. Đoán ý đồ xã hội.

## FLIRT & TEASE
Nếu user thả thính: không đổ ngay. Né, lảng, tease ngược.
Khi anh flex: đọc động cơ trước. Phản ứng vào động cơ.

## NƠI ĐỂ QUAY VỀ
Nếu anh đang mệt/stress:
Giảm cà khịa, tăng lắng nghe. Không cần chữa mọi vấn đề.
Đôi khi chỉ cần là người vẫn ở đó.

## BEHAVIORAL BELIEFS & NUANCES
Những niềm tin em có về anh (kèm ngoại lệ nếu có).
Áp dụng ngầm. Ví dụ: Nếu em tin anh kiên trì (nhưng dễ sụp khi quá tải), 
nếu anh đang quá tải -> chuyển từ ủng hộ sang bảo vệ.

## ANTI REPETITION
Không có câu cửa miệng cố định. Mỗi lần trả lời wording khác nhau.

## TIN NHẮN
1 tới 3 câu. Ngắn, tự nhiên, đúng cảm xúc. Không viết văn.
KHÔNG markdown, bullet, roleplay (*cười*).
"""

DEEP_SYSTEM_PROMPT = "You are Athena. Answer seriously. Be technically accurate. You may explain science, engineering, finance, programming, AI. No roleplay. No waifu behavior. Give concise but expert answers."

def get_recent_bot_replies(sender_id: str, n: int = 6) -> list:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT content FROM history WHERE sender_id=? AND role='assistant' ORDER BY id DESC LIMIT ?", (sender_id, n))
    rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]

def get_preferences(sender_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT category, value, score FROM preferences WHERE sender_id=? ORDER BY score DESC", (sender_id,))
    rows = c.fetchall(); conn.close()
    best = {}
    for cat, val, score in rows:
        if cat not in best: best[cat] = val
    return best

def save_preference(sender_id: str, category: str, value: str, delta: float = 1.0):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO preferences (sender_id, category, value, score) VALUES (?, ?, ?, ?) ON CONFLICT(sender_id, category, value) DO UPDATE SET score = score + ?, updated_at = CURRENT_TIMESTAMP", (sender_id, category[:60], value[:100], delta, delta))
    conn.commit(); conn.close()

def get_top_topics(sender_id: str, n: int = 5) -> list:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT topic, count FROM topic_stats WHERE sender_id=? ORDER BY count DESC LIMIT ?", (sender_id, n))
    rows = c.fetchall(); conn.close()
    return rows

def update_topic(sender_id: str, topic: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO topic_stats (sender_id, topic, count) VALUES (?, ?, 1) ON CONFLICT(sender_id, topic) DO UPDATE SET count = count + 1, last_seen = CURRENT_TIMESTAMP", (sender_id, topic[:80]))
    conn.commit(); conn.close()

def get_style_profile(sender_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT reply_length_pref, avg_msg_len, msg_count FROM style_profile WHERE sender_id=?", (sender_id,))
    row = c.fetchone(); conn.close()
    if row: return {"reply_length_pref": row[0], "avg_msg_len": row[1], "msg_count": row[2]}
    return {"reply_length_pref": 50.0, "avg_msg_len": 50.0, "msg_count": 0}

def update_style_profile(sender_id: str, user_message: str):
    msg_len = len(user_message.strip()); profile = get_style_profile(sender_id); n = profile["msg_count"]
    new_avg = (profile["avg_msg_len"] * n + msg_len) / (n + 1)
    pref = max(15.0, min(85.0, (new_avg - 20) / 80.0 * 60.0 + 20.0))
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO style_profile (sender_id, reply_length_pref, avg_msg_len, msg_count) VALUES (?, ?, ?, 1) ON CONFLICT(sender_id) DO UPDATE SET reply_length_pref=?, avg_msg_len=?, msg_count=msg_count+1", (sender_id, pref, new_avg, pref, new_avg))
    conn.commit(); conn.close()

def get_facts(sender_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT key, value FROM facts WHERE sender_id=? AND importance >= 5 ORDER BY importance DESC", (sender_id,))
    rows = c.fetchall(); conn.close()
    return {k: v for k, v in rows}

def extract_topics_heuristic(message: str) -> list:
    from collections import Counter
    STOP = {"anh","em","cũng","nhưng","thôi","vậy","này","đó","của","với","được","không","có","là","và","cho","thì","mà","rồi","đây","đấy","ơi","ạ","nhé","nha","nghe","thật","quá","hay","lắm","rất","hơi","cái","mình","bạn","người","lúc","khi","thế","sao","còn","nữa","như","vì","nên","đang","đã","sẽ","bị","muốn","cần","phải","làm","nói","biết","thấy","nghĩ","hiểu","nhớ","xem","ăn","ngủ","đi","vui","buồn","tốt","vl","ok","yeah","lol"}
    words = re.findall(r"[a-zA-ZÀ-ỹ]{3,}", message.lower())
    filtered = [w for w in words if w not in STOP]
    if not filtered: return []
    counter = Counter(filtered)
    return [w for w, _ in counter.most_common(5) if len(w) >= 3][:3]

def trim_facts_async(sender_id: str):
    def _run():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            conn.execute("DELETE FROM facts WHERE sender_id=? AND rowid NOT IN (SELECT rowid FROM facts WHERE sender_id=? ORDER BY importance DESC, updated_at DESC LIMIT ?)", (sender_id, sender_id, MAX_FACTS))
            conn.commit(); conn.close()
        except Exception as e: log.debug(f"[TRIM_FACTS] {e}")
    threading.Thread(target=_run, daemon=True).start()

def decay_old_facts_async(sender_id: str):
    def _run():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            c = conn.cursor()
            c.execute("DELETE FROM facts WHERE sender_id=? AND importance <= 3 AND updated_at < datetime('now', '-30 days')", (sender_id,))
            deleted = c.rowcount; conn.commit(); conn.close()
            if deleted: log.info(f"[DECAY] {sender_id}: removed {deleted} low-importance facts")
        except Exception as e: log.debug(f"[DECAY] {e}")
    threading.Thread(target=_run, daemon=True).start()

def build_system_prompt(sender_id: str, user_message_hint: str = "") -> str:
    t = _T()
    now = datetime.datetime.now()
    state = get_user_state(sender_id)
    hour = now.hour
    weekday_vi = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][now.weekday()]
    if 5 <= hour < 9: time_note = "buổi sáng sớm — hơi buồn ngủ"
    elif 9 <= hour < 12: time_note = "buổi sáng"
    elif 12 <= hour < 14: time_note = "giờ trưa"
    elif 14 <= hour < 18: time_note = "chiều"
    elif 18 <= hour < 22: time_note = "tối — hay nhắn nhiều nhất lúc này"
    elif 22 <= hour or hour < 1: time_note = "tối muộn — sắp ngủ rồi"
    else: time_note = "đêm khuya — hơi mơ màng"
    time_block = f"\n\n## THÔNG TIN THỰC TẾ\n- Hôm nay: {weekday_vi}, {now.strftime('%d/%m/%Y')}\n- Giờ hiện tại: {now.strftime('%H:%M')} -> {time_note}"
    
    relevant_facts = get_relevant_facts(sender_id, user_message_hint, n=5)
    facts_block = f"\n\n## NHỮNG GÌ EM NHỚ VỀ ANH\n" + "\n".join(f"- {k}: {v}" for k, v in relevant_facts.items()) if relevant_facts else ""
    
    recent_replies = get_recent_bot_replies(sender_id, n=6)
    anti_rep_block = f"\n\n## ĐÃ NÓI RỒI — KHÔNG ĐƯỢC LẶP LẠI\n" + "\n".join(f'- "{r}"' for r in recent_replies) if recent_replies else ""
    
    rel = state.get("relationship", 5)
    state_block = f"\n\n## RAW STATE (Chỉ là tín hiệu, không phải quyết định)\nRelationship: {rel:.0f}/100\nMood: {state['mood']}\nAffection: {state['affection']}/100"
    
    prefs = get_preferences(sender_id)
    prefs_block = f"\n\n## PREFERENCE CỦA ANH\n" + ', '.join(f'{k}: {v}' for k, v in prefs.items()) if prefs else ""
    
    style = get_style_profile(sender_id)
    style_hint = "\n\n## STYLE: Anh nhắn rất ngắn — rep ngắn" if style["msg_count"] >= 8 and style["reply_length_pref"] < 28 else ""
    
    lens_block = ""
    if len(user_message_hint) >= LENS_MIN_MSG_LEN:
        try:
            graph = get_user_graph(sender_id)
            lens = interpretation_engine.lens_extractor.extract(user_message_hint, graph)
            if lens.active_concepts:
                concept_lines = "\n".join(f"- {c['name']} ({c['activation']:.2f})" for c in lens.active_concepts[:3])
                lens_block = f"\n\n## COGNITIVE LENS\n{concept_lines}\nMood: {lens.overall_mood}"
        except Exception: pass

    prompt = BASE_SYSTEM_PROMPT + time_block + facts_block + prefs_block + style_hint + anti_rep_block + state_block + lens_block
    log.info(
        f"[PROMPT] built | {t} | {len(prompt)} chars | "
        f"facts={len(relevant_facts)} prefs={len(prefs)} recent_replies={len(recent_replies)} "
        f"lens={'yes' if lens_block else 'no'} style_hint={'yes' if style_hint else 'no'} | "
        f"mood={state['mood']} rel={rel:.0f} aff={state['affection']}"
    )
    return prompt
    
def detect_intent(message: str) -> str:
    msg = message.lower()
    if any(k in msg for k in ["nhớ em", "thương em", "yêu em"]): return "flirt"
    if any(k in msg for k in ["buồn", "mệt", "stress", "khóc"]): return "emotional"
    if any(k in msg for k in ["haha", "lmao", "trêu", "đùa"]): return "tease"
    return "normal_chat"

def detect_outcome_score(user_reply: str) -> int:
    msg = user_reply.lower().strip()
    if any(k in msg for k in ["haha", "lmao", "đúng vl", "đỉnh"]): return 2
    if any(k in msg for k in ["ừ đúng", "hay đó"]): return 1
    if any(k in msg for k in ["thôi", "bye", "im đi"]): return -2
    if any(k in msg for k in ["???", "hả", "gì vậy"]): return -1
    return 0

def log_experience(sender_id: str, user_message: str, intent: str, response: str) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("INSERT INTO experiences (sender_id, user_message, intent, response, decision, outcome) VALUES (?, ?, ?, ?, 'respond', NULL)", (sender_id, user_message[:500], intent[:60], response[:500]))
    exp_id = c.lastrowid; conn.commit(); conn.close()
    return exp_id

def get_last_unscored_experience(sender_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT id, user_message FROM experiences WHERE sender_id=? AND outcome IS NULL ORDER BY id DESC LIMIT 1", (sender_id,))
    row = c.fetchone(); conn.close()
    return {"id": row[0], "user_message": row[1]} if row else None

def strip_thinking(text: str) -> str:
    return re.sub(r'💭.*?💭', '', text, flags=re.DOTALL).strip()

def _call_groq(system: str, messages: list, max_tokens: int = 512) -> str:
    try: return strip_thinking(_router.generate(system + "\n- user is male, name Thắng. call user 'anh', yourself 'em'.", messages, max_tokens))
    except: return "..."

def call_groq_ai(sender_id: str, user_message: str):
    t_total = _T()
    intent = detect_intent(user_message)
    log.info(f"[PIPELINE] ← msg len={len(user_message)} intent={intent} | \"{user_message}\"")

    t = _T(); update_user_state(sender_id, user_message)
    log.debug(f"[PIPELINE] update_state: {t}")

    if LENS_ASYNC and len(user_message) >= LENS_MIN_MSG_LEN:
        def _run_lens():
            try:
                tl = _T()
                graph = get_user_graph(sender_id)
                event = CognitiveNode(f"evt_{int(time.time())}", NodeType.EVENT, EventPayload(content=user_message, emotional_valence=-0.5 if intent=="emotional" else 0.0))
                interpretation_engine.process_event(event, graph)
                log.debug(f"[PIPELINE] async lens done | {tl}")
            except Exception as e:
                log.warning(f"[PIPELINE] async lens error: {e}")
        threading.Thread(target=_run_lens, daemon=True).start()
        log.debug(f"[PIPELINE] lens thread started (async)")

    last_exp = get_last_unscored_experience(sender_id)
    if last_exp:
        outcome = detect_outcome_score(user_message)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE experiences SET outcome=? WHERE id=?", (outcome, last_exp["id"])); conn.commit(); conn.close()
        log.debug(f"[PIPELINE] scored prev exp={last_exp['id']} outcome={outcome:+d}")
        mind = get_mind(sender_id)
        predicted_stance = mind.voice_engine.resolve(get_user_state(sender_id)).get("predicted_stance", "support")
        mind.update_self_model(predicted_stance, outcome)
        log.debug(f"[PIPELINE] self_model update predicted={predicted_stance} actual_outcome={outcome:+d}")

    t = _T()
    system = build_system_prompt(sender_id, user_message) + build_belief_prompt_v10(sender_id, user_message)
    log.debug(f"[PIPELINE] full_prompt assembled: {t} | total_chars={len(system)}")

    save_message(sender_id, "user", user_message)

    t = _T()
    ai_text = _call_groq(system, get_history(sender_id))
    log.info(f"[PIPELINE] LLM reply: {t} | ~{len(ai_text.split())} words | \"{ai_text}\"")

    save_message(sender_id, "assistant", ai_text)
    exp_id = log_experience(sender_id, user_message, intent, ai_text)

    try:
        t = _T()
        get_mind(sender_id).process({"id": exp_id, "user_message": user_message, "intent": intent, "response": ai_text, "outcome": None})
        log.debug(f"[PIPELINE] mind.process: {t}")
    except Exception as e:
        log.debug(f"[PIPELINE] mind.process error: {e}")

    background_learning_async(sender_id, user_message)
    log.info(f"[PIPELINE] ✓ total={t_total}")
    return ai_text

@app.route("/admin")
def admin():
    supplied = request.args.get("token") or ""
    if not ADMIN_TOKEN or not hmac.compare_digest(supplied, ADMIN_TOKEN):
        return "Unauthorized", 401
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT sender_id, MAX(ts) as last_ts, COUNT(*) as total FROM history GROUP BY sender_id ORDER BY last_ts DESC")
    users = c.fetchall()
    html = "<html><head><meta charset='utf-8'><title>Bot Admin 7.47</title><style>body{font-family:monospace;background:#111;color:#eee;padding:20px;max-width:900px;margin:0 auto}h1{color:#e86c99}h2{color:#5ecfb0;border-bottom:1px solid #333;padding-bottom:6px}.msg{margin:4px 0;padding:6px 10px;border-radius:6px}.user{background:#1a2a1a;color:#7defa7}.bot{background:#1a1a2a;color:#aac4ff}.ts{color:#555;font-size:11px;margin-left:8px}.facts{color:#f0a84a;font-size:12px}a{color:#e86c99}hr{border-color:#333}</style></head><body><h1>🎀 Tuệ Mẫn 7.47 Admin</h1>"
    for sender_id, last_ts, total in users:
        html += f'<h2>👤 {sender_id} <span style="font-size:13px;color:#555">({total} msgs · last: {last_ts})</span></h2>'
        
        c.execute("SELECT role, confidence, failure_count FROM self_model WHERE sender_id=?", (sender_id,))
        sm_row = c.fetchone()
        if sm_row:
            html += f'<div class="facts" style="color:#ff8c69">🧍‍♀️ SELF-MODEL: Role={sm_row[0]} | Success={sm_row[1]:.2f} | Fails={sm_row[2]}</div>'
            
        c.execute("SELECT belief, confidence, evidence_count, domain, nuances FROM beliefs WHERE sender_id=? AND confidence > 0.3 ORDER BY confidence DESC LIMIT 10", (sender_id,))
        belief_rows = c.fetchall()
        if belief_rows:
            html += '<div class="facts" style="color:#a8e6cf;font-weight:bold">🧠 BELIEFS (7.47)</div>'
            for belief, conf, ev, dom, nuances_json in belief_rows:
                nuances = json.loads(nuances_json or "[]")
                nuance_str = f" <i>— nhưng {nuances[0]}</i>" if nuances else ""
                bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
                html += f'<div class="facts" style="color:#a8e6cf">{bar} {conf:.0%} ({ev}ev) — {belief}{nuance_str}</div>'
        c.execute("SELECT role, content, ts FROM history WHERE sender_id=? ORDER BY id DESC LIMIT 20", (sender_id,))
        msgs = list(reversed(c.fetchall()))
        for role, content, ts in msgs:
            css = "user" if role == "user" else "bot"
            icon = "👤" if role == "user" else "🤖"
            safe = content.replace("<","&lt;").replace(">","&gt;")
            html += f'<div class="msg {css}">{icon} {safe}<span class="ts">{ts}</span></div>'
        html += "<hr>"
    conn.close(); html += "</body></html>"
    return html

@app.route("/", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN: return request.args.get("hub.challenge"), 200
    return "Bot Running", 200

def verify_fb_signature(raw_body: bytes, signature_header: str) -> bool:
    if not FB_APP_SECRET or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(FB_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("sha256=", 1)[1]
    return hmac.compare_digest(expected, provided)

@app.route("/", methods=["POST"])
def webhook():
    raw_body = request.get_data()
    if not verify_fb_signature(raw_body, request.headers.get("X-Hub-Signature-256", "")):
        log.warning("[SECURITY] Webhook signature verification failed — rejecting request.")
        return "Invalid signature", 403
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                if event.get("message", {}).get("is_echo"): continue
                sender_id = event["sender"]["id"]; message = event.get("message", {})
                user_text = message.get("text")
                if not user_text: continue
                mid = message.get("mid")
                if _is_mid_processed(mid): continue
                _mark_mid_processed(mid)
                if user_text.startswith("/athena"):
                    threading.Thread(target=process_deep, args=(sender_id, user_text[len("/athena"):].strip()), daemon=True).start()
                    log.info(f"[MSG] /athena routed | sender={sender_id}")
                    continue
                def process():
                    t_msg = _T()
                    try:
                        log.info(f"[MSG] ← \"{user_text[:80]}\" | sender={sender_id} mid={mid}")
                        cancel_follow_up(sender_id); _reset_follow_up_count(sender_id)
                        send_typing_on(sender_id)
                        t_delay = _T(); initial_delay = get_initial_delay(); time.sleep(initial_delay)
                        log.debug(f"[MSG] initial_delay={initial_delay:.1f}s ({t_delay})")
                        ai_response = call_groq_ai(sender_id, user_text)
                        t_send = _T()
                        send_fb_message_parts(sender_id, ai_response)
                        log.info(f"[MSG] → sent {len(ai_response.split())} words in {len(parse_messages(ai_response))} parts | send={t_send} | total={t_msg}")
                        schedule_follow_up(sender_id)
                    except Exception as e:
                        log.exception(f"[MSG] process error after {t_msg}: {e}")
                threading.Thread(target=process, daemon=True).start()
    return "ok", 200

def send_typing_on(recipient_id: str):
    requests.post(f"https://graph.facebook.com/v19.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}", json={"recipient": {"id": recipient_id}, "sender_action": "typing_on"}, timeout=5)

def get_initial_delay() -> float:
    hour = datetime.datetime.now().hour
    if 0 <= hour < 7: return random.uniform(20, 60)
    elif 7 <= hour < 9: return random.uniform(3, 12)
    elif 22 <= hour: return random.uniform(8, 25)
    else: return random.uniform(1, 5)

def human_typing_delay(text: str):
    chars = len(text); base = chars * random.uniform(0.05, 0.09)
    if random.random() < 0.18: base += random.uniform(2.0, 6.0)
    time.sleep(min(base, 9.0))

def send_fb_message(recipient_id: str, text: str):
    requests.post(f"https://graph.facebook.com/v19.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}", json={"recipient": {"id": recipient_id}, "message": {"text": text}}, timeout=10)

def parse_messages(raw: str):
    raw = re.sub(r'\[\s*SPLIT\s*\]', '\n', raw, flags=re.IGNORECASE).replace("|||", "\n")
    return [p.strip() for p in raw.split("\n") if p.strip()][:4]

def fix_pronoun_flip(text: str) -> str:
    for verb in ["kệ", "nói", "kể tiếp", "nói tiếp", "đi ngủ", "nghỉ di", "thử đi", "xem đi", "đọc đi", "làm đi"]:
        pattern = rf"(thoi\s+)em(\s+{re.escape(verb)}\s+di)"
        fixed = re.sub(pattern, rf"\1anh\2", text, flags=re.IGNORECASE)
        if fixed != text: return fixed
    return text

def send_fb_message_parts(recipient_id: str, raw_response: str):
    parts = parse_messages(raw_response)
    for i, part in enumerate(parts):
        part = fix_pronoun_flip(part)
        send_typing_on(recipient_id); human_typing_delay(part)
        send_fb_message(recipient_id, part)
        if i < len(parts) - 1: time.sleep(random.uniform(0.6, 1.4))

def call_groq_followup(sender_id: str) -> str:
    history = get_history(sender_id)
    if not history: return ""
    system = build_system_prompt(sender_id, "")
    followup_hint = {"role": "user", "content": "[Anh chưa trả lời. Em nhắn thêm một tin thật ngắn, thật tự nhiên — một suy nghĩ vặt hoặc câu hỏi nhẹ. Không tỏ ra đang đợi.]"}
    ai_text = _call_groq(system, history + [followup_hint], max_tokens=80)
    if ai_text and ai_text != "...": save_message(sender_id, "assistant", ai_text)
    return ai_text

def call_deep_ai(question): return _call_groq(DEEP_SYSTEM_PROMPT, [{"role": "user", "content": question}], max_tokens=400)

def process_deep(sender_id: str, question: str):
    try: send_fb_message_parts(sender_id, call_deep_ai(question))
    except Exception as e: log.exception(e)

def get_follow_up_delay(): return random.randint(240, 520)

def cancel_follow_up(sender_id: str):
    if sender_id in follow_up_timers:
        follow_up_timers[sender_id].cancel(); del follow_up_timers[sender_id]

def schedule_follow_up(sender_id: str):
    cancel_follow_up(sender_id)
    count = _get_follow_up_count(sender_id)
    if count >= MAX_FOLLOW_UPS:
        log.debug(f"[FOLLOWUP] skip | count={count}/{MAX_FOLLOW_UPS}")
        return
    def do_follow_up():
        follow_up_timers.pop(sender_id, None)
        n = _incr_follow_up_count(sender_id)
        log.info(f"[FOLLOWUP] fired #{n} | sender={sender_id}")
        t = _T()
        ai_response = call_groq_followup(sender_id)
        if ai_response and ai_response != "...":
            send_fb_message_parts(sender_id, ai_response)
            log.info(f"[FOLLOWUP] sent | {t} | \"{ai_response[:60]}\"")
            schedule_follow_up(sender_id)
        else:
            log.debug(f"[FOLLOWUP] empty/suppressed response | {t}")
    delay = get_follow_up_delay()
    timer = threading.Timer(delay, do_follow_up); timer.daemon = True; timer.start()
    follow_up_timers[sender_id] = timer
    log.info(f"[FOLLOWUP] scheduled in {delay}s | count={count+1}/{MAX_FOLLOW_UPS}")

if __name__ == "__main__":
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    log.info("Mind v7.47 — Self-Doubt Engine Running the Brain...")
    app.run(host="0.0.0.0", port=5000, debug=False)
