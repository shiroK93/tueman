"""
TUỆ MẪN
========================================
Bao gồm:
1. Mind 7.35: Interpretation Engine (Cognitive Graph + Lens + Deformation)
2. Chatbot Core: Flask + Groq/Gemini/OpenRouter + FB Webhook + State + Memory
3. Level 2-6 v10.0 FINAL: ReflectionA/B, BeliefSystem, Contradiction, Decision, LRU Cache
4. Opinion 7.29: Reality Feedback & Personality Drift Engine (Module độc lập)
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
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Any, List, Dict
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

# ==================== LOGGING ====================
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
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
VERIFY_TOKEN         = "shirok"
MAX_FOLLOW_UPS       = 2
MAX_HISTORY          = 14
MAX_FACTS            = 50
DB_PATH              = "memory.db"
DB_TIMEOUT           = 20
EXPERIENCE_THRESHOLD = 50
ADMIN_TOKEN          = os.environ.get("ADMIN_TOKEN")
# ▼▼▼ [MIND 7.35 — CONFIG] ▼▼▼
GRAPHS_DIR           = "graphs"
LENS_MIN_MSG_LEN     = 10
LENS_ASYNC           = True
# ▲▲▲ [MIND 7.35 — END] ▲▲▲
# =======================================================


# ╔═══════════════════════════════════════════════════════════════╗
# ║  [MIND 7.35] INTERPRETATION ENGINE — CORE SCHEMA            ║
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
        lens = self.lens_extractor.extract(event.payload.content, graph)
        if self.llm_func:
            try: interp_text, emotion, conf = self.llm_func(event.payload.content, lens)
            except Exception:
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
        ("c_self_doubt", "Self_Doubt", ["dở", "kém", "giỏi", "đủ tốt", "mình", "thất bại", "sai", "lỗi"]),
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
        graph = CognitiveGraph(filepath)
        if not graph.nodes: _seed_initial_concepts(graph)
        _graph_cache[sender_id] = graph
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
# ║  LLM PROVIDER ROUTER                                         ║
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
        if self._is_cooling_down(provider.name): return None, RuntimeError(f"{provider.name} on cooldown")
        try:
            response = provider.generate(system, messages, max_tokens)
            return (response, None) if response else (None, RuntimeError(f"{provider.name} empty"))
        except Exception as e:
            self._mark_cooldown(provider.name, e)
            return None, e

    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str:
        last_error = None
        tried = set()
        sticky = self.provider_map.get(self.last_good)
        if sticky:
            response, err = self._attempt(sticky, system, messages, max_tokens)
            tried.add(sticky.name)
            if response: self.last_good = sticky.name; return response
            last_error = err
        for provider in self.providers:
            if provider.name in tried: continue
            response, err = self._attempt(provider, system, messages, max_tokens)
            tried.add(provider.name)
            if response: self.last_good = provider.name; return response
            last_error = err
        raise RuntimeError(f"All providers failed — last: {last_error}")

_router = ProviderRouter()
interpretation_engine = InterpretationEngine(llm_func=make_llm_interpret_func(_router))

# ===============================================================
follow_up_timers = {}
follow_up_counts = {}
user_states = {}
processed_mids = {}

# ==================== DATABASE & CORE LOGIC ====================
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
    for ddl in ["ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 5","ALTER TABLE facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE facts ADD COLUMN confidence REAL DEFAULT 0.8","ALTER TABLE facts ADD COLUMN source_message TEXT DEFAULT ''","ALTER TABLE fact_candidates ADD COLUMN confidence REAL DEFAULT 0.0","ALTER TABLE fact_candidates ADD COLUMN source_message TEXT DEFAULT ''"]:
        try: c.execute(ddl)
        except: pass
    c.execute("CREATE TABLE IF NOT EXISTS fact_candidates (sender_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, score INTEGER DEFAULT 1, rejection_reason TEXT DEFAULT NULL, last_seen DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (sender_id, key))")
    c.execute("CREATE TABLE IF NOT EXISTS experiences (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, user_message TEXT NOT NULL, intent TEXT DEFAULT '', response TEXT NOT NULL, decision TEXT DEFAULT 'respond', outcome INTEGER DEFAULT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS beliefs (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, belief TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, last_updated DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.commit(); conn.close()

init_db()

# ╔═══════════════════════════════════════════════════════════════╗
# ║  [LEVEL 2-6 v10.0 FINAL] — THE BRAIN YOU SPENT A DAY ON    ║
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

def migrate_belief_system_v10():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS system_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for ddl in [
        "ALTER TABLE beliefs ADD COLUMN last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE beliefs ADD COLUMN contradictions INTEGER DEFAULT 0",
        "ALTER TABLE beliefs ADD COLUMN source TEXT DEFAULT 'reflection'","ALTER TABLE beliefs ADD COLUMN domain TEXT DEFAULT 'behavior'",
        "ALTER TABLE beliefs ADD COLUMN decay_rate REAL DEFAULT 0.0008","ALTER TABLE beliefs ADD COLUMN active INTEGER DEFAULT 1",
        "ALTER TABLE beliefs ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE beliefs ADD COLUMN tags TEXT DEFAULT ''",
        "ALTER TABLE beliefs ADD COLUMN source_tag TEXT DEFAULT ''","ALTER TABLE beliefs ADD COLUMN polarity INTEGER DEFAULT 1",
        "ALTER TABLE beliefs ADD COLUMN last_processed_ev_id INTEGER DEFAULT 0","ALTER TABLE beliefs ADD COLUMN last_decay_check DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE beliefs ADD COLUMN state TEXT DEFAULT 'CONFIRMED'","ALTER TABLE beliefs ADD COLUMN contradiction_score REAL DEFAULT 0.0",
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
            log.warning("[MIGRATION] Rebuilding evidence table...")
            c.execute("ALTER TABLE evidence RENAME TO _evidence_old")
            c.execute("""CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, tag TEXT NOT NULL, outcome INTEGER NOT NULL, exp_id INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, tag, exp_id))""")
            c.execute("INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id, created_at) SELECT sender_id, tag, outcome, 0, created_at FROM _evidence_old")
            c.execute("DROP TABLE _evidence_old")
    else:
        c.execute("""CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, tag TEXT NOT NULL, outcome INTEGER NOT NULL, exp_id INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, tag, exp_id))""")
    try: c.execute("CREATE INDEX IF NOT EXISTS idx_ev_time ON evidence(sender_id, created_at)")
    except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS user_values (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, value_text TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, value_text))""")
    c.execute("UPDATE beliefs SET state = 'UNCERTAIN' WHERE confidence < 0.5 AND state = 'CONFIRMED'")
    c.execute("UPDATE beliefs SET state = 'INVESTIGATING' WHERE contradiction_score >= 0.8 AND state != 'INVESTIGATING'")
    conn.commit(); conn.close()

migrate_belief_system_v10()
log.info("[BELIEF] Migration v10.0 FINAL OK")

REFL_B_CONFIG = {"min_evidence": 8, "consistency_threshold": 0.3, "run_interval": 30, "lookback_days": 180}
BELIEF_CONFIG = {"min_conf": 0.05, "max_conf": 0.98, "deact_thresh": 0.12, "time_decay_rate": 0.002}
RECENCY_LAMBDA = 0.015
TAG_TO_DOMAIN = {"gaming": "interest", "coding": "interest", "game": "interest", "roast": "communication", "hint": "communication", "spoil": "communication", "challenge": "preference", "khó": "preference"}
BELIEF_TEMPLATES = {"gaming": {"pos": "Thắng thích nói về game", "neg": "Thắng không hứng thú với game"}, "coding": {"pos": "Thắng thích technical topics", "neg": "Thắng chán nói về code"}, "challenge": {"pos": "Thắng thích bị thử thách", "neg": "Thắng ghét bị làm khó"}, "hint": {"pos": "Thắng thích tự mò thay vì được cho đáp án", "neg": "Thắng muốn đáp án thẳng"}, "roast": {"pos": "Thắng thích bị trêu nhẹ", "neg": "Thắng không thích bị roast"}, "emotional": {"pos": "Thắng chia sẻ cảm xúc khi tốt", "neg": "Thắng đóng kín khi tệ"}}
VALUE_INFERENCE = {("hint", 0.7): "Học qua tự khám phá quan trọng hơn đáp án sẵn", ("challenge", 0.7): "Thích bị thử thách hơn được dẫn dắt"}

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
        for tag, kws in {"gaming": ["game", "chơi game", "gaming"], "coding": ["code", "bug", "lỗi"], "challenge": ["khó", "challenge", "thử thách"], "hint": ["hint", "gợi ý"], "answer": ["đáp án", "trả lời luôn"], "roast": ["roast", "cà khịa", "diss"], "emotional": ["buồn", "mệt", "stress"]}.items():
            for kw in kws:
                if (' ' in kw and kw in msg) or (' ' not in kw and re.search(rf'\b{re.escape(kw)}\b', msg)):
                    tags.append(tag); break
        return tags
    def _save_evidence(self, tags: list[str], outcome: int, exp_id: int):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        for tag in tags: conn.execute("INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id) VALUES (?,?,?,?)", (self.sender_id, tag[:30], outcome, exp_id))
        conn.commit(); conn.close()

class ReflectionB:
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
                log.info(f"[BELIEF:REACTIVATED] Reactivated '{belief_text}'")
                return {"id": bid, "belief": belief_text}
            if pol == new_polarity and state == 'CONFIRMED': return {"id": bid, "belief": belief_text}
        return None

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
            elif action == "split_belief": self._split(r)
    def _calculate_new_state(self, current_state: str, current_score: float, score_delta: float, new_conf: float) -> str:
        new_score = max(0.0, min(1.0, current_score + score_delta))
        if new_score <= 0.1: return 'CONFIRMED' if new_conf > 0.5 else 'UNCERTAIN'
        if new_score >= 0.8: return 'INVESTIGATING'
        if new_score >= 0.3: return 'UNCERTAIN'
        return current_state
    def _create(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.3)))
        polarity = r.get("polarity", 1); source_tag = r.get("source_tag", "")
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        conflict_row = None
        if source_tag:
            c.execute("SELECT id, contradiction_score, state, polarity, confidence FROM beliefs WHERE source_tag=?", (source_tag,))
            for row in c.fetchall():
                if row[3] != polarity:
                    new_score = min(1.0, row[1] + 0.3)
                    new_state = self._calculate_new_state(row[2], row[1], 0.3, row[4])
                    c.execute("UPDATE beliefs SET contradiction_score=?, state=? WHERE id=?", (new_score, new_state, row[0]))
        c.execute("INSERT INTO beliefs (sender_id, belief, confidence, evidence_count, source, domain, source_tag, polarity, state, contradiction_score) VALUES (?, ?, ?, ?, 'reflection_b', ?, ?, ?, 'CONFIRMED', ?)", (self.sender_id, r["belief_text"][:200], conf, r.get("new_count", 1), r.get("domain", "behavior")[:30], source_tag[:30], polarity, 0.3 if conflict_row else 0.0))
        conn.commit(); conn.close()
    def _update(self, r: dict):
        new_count = r.get("new_count", 1); delta = r.get("delta", 0.05)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row: conn.close(); return
        old_conf, old_score, old_state = row
        new_conf = min(BELIEF_CONFIG["max_conf"], old_conf + delta)
        new_state = self._calculate_new_state(old_state, old_score, -delta * 2, new_conf)
        c.execute("UPDATE beliefs SET confidence = ?, evidence_count = evidence_count + ?, contradiction_score = MAX(0, ?), state = ?, last_confirmed = CURRENT_TIMESTAMP WHERE id=?", (new_conf, new_count, old_score - (delta * 2), new_state, r["belief_id"]))
        conn.commit(); conn.close()
    def _contradict(self, r: dict):
        delta = r.get("delta", -0.1); abs_delta = abs(delta)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row: conn.close(); return
        old_conf, old_score, old_state = row
        new_conf = max(BELIEF_CONFIG["min_conf"], old_conf + delta)
        new_state = self._calculate_new_state(old_state, old_score, abs_delta * 1.5, new_conf)
        c.execute("UPDATE beliefs SET confidence = ?, contradictions = contradictions + 1, contradiction_score = MIN(1.0, ?), state = ? WHERE id = ?", (new_conf, old_score + (abs_delta * 1.5), new_state, r["belief_id"]))
        conn.commit(); conn.close()
    def _deactivate(self, r: dict):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], r["belief_id"]))
        conn.commit(); conn.close()
    def _create_value(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.5)))
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT INTO user_values (sender_id, value_text, confidence, evidence_count) VALUES (?, ?, ?, 1) ON CONFLICT(sender_id, value_text) DO UPDATE SET confidence = MAX(confidence, excluded.confidence), evidence_count = evidence_count + 1", (self.sender_id, r["belief_text"][:200], conf))
        conn.commit(); conn.close()
    def _split(self, r: dict):
        self._deactivate({"belief_id": r["old_belief_id"], "belief_text": r["old_belief_text"]})
        for new_b in r["new_beliefs"]:
            self._create({"belief_text": new_b["text"], "domain": r.get("domain", "preference"), "source_tag": r.get("source_tag", ""), "polarity": new_b["polarity"], "delta": new_b["confidence"], "new_count": new_b["count"]})
    def decay(self):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, confidence, last_confirmed, last_decay_check FROM beliefs WHERE sender_id=? AND active=1", (self.sender_id,))
        to_deactivate = []; now = datetime.datetime.now()
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
                else: c.execute("UPDATE beliefs SET confidence=?, last_decay_check=CURRENT_TIMESTAMP WHERE id=?", (new_conf, bid))
        for bid in to_deactivate: c.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], bid))
        c.execute("DELETE FROM evidence WHERE sender_id=? AND created_at < datetime('now', '-180 days')", (self.sender_id,))
        conn.commit(); conn.close()

class ContradictionEngine:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def check_for_splits(self) -> list[dict]:
        results = []; beliefs = self._get_investigating_beliefs()
        for belief in beliefs:
            if not belief["source_tag"]: continue
            intent_stats = self._analyze_by_intent(belief["source_tag"])
            if len(intent_stats) < 2: continue
            pos_contexts = [k for k, v in intent_stats.items() if v["avg"] > 0.5 and v["count"] >= 5]
            neg_contexts = [k for k, v in intent_stats.items() if v["avg"] < -0.5 and v["count"] >= 5]
            if pos_contexts and neg_contexts:
                old_text = belief["belief"]
                new_beliefs = [{"text": f"{old_text} khi {ctx}", "polarity": 1, "confidence": intent_stats[ctx]["avg"] * 0.7, "count": intent_stats[ctx]["count"]} for ctx in pos_contexts]
                new_beliefs += [{"text": f"{old_text} bị né khi {ctx}", "polarity": -1, "confidence": abs(intent_stats[ctx]["avg"]) * 0.7, "count": intent_stats[ctx]["count"]} for ctx in neg_contexts]
                results.append({"tier": "c", "action": "split_belief", "old_belief_id": belief["id"], "old_belief_text": old_text, "new_beliefs": new_beliefs, "domain": belief["domain"], "source_tag": belief["source_tag"]})
        return results
    def _get_investigating_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, belief, source_tag, domain FROM beliefs WHERE sender_id=? AND active=1 AND state='INVESTIGATING' AND evidence_count >= 15", (self.sender_id,))
        rows = c.fetchall(); conn.close()
        return [{"id": r[0], "belief": r[1], "source_tag": r[2], "domain": r[3]} for r in rows]
    def _analyze_by_intent(self, tag: str) -> dict:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT AVG(e.outcome), ex.intent, COUNT(*) as cnt FROM evidence e JOIN experiences ex ON e.exp_id = ex.id AND e.sender_id = ex.sender_id WHERE e.sender_id=? AND e.tag=? AND ex.intent IS NOT NULL AND ex.intent != 'normal_chat' GROUP BY ex.intent HAVING cnt >= 5", (self.sender_id, tag))
        stats = {avg_out: {"avg": avg_out, "count": cnt} for avg_out, intent, cnt in c.fetchall()}
        conn.close()
        return stats

class BeliefNetwork:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def connect(self, from_id: int, to_id: int, conn_type: str = "related", strength: float = 0.5):
        if from_id == to_id: return
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT OR IGNORE INTO belief_connections (sender_id, from_id, to_id, conn_type, strength) VALUES (?,?,?,?,?)", (self.sender_id, from_id, to_id, conn_type, strength))
        if conn.total_changes == 0:
            conn.execute("UPDATE belief_connections SET strength = MIN(1.0, (strength + ?) / 2 + 0.05) WHERE sender_id=? AND from_id=? AND to_id=? AND conn_type=?", (strength, self.sender_id, from_id, to_id, conn_type))
        conn.commit(); conn.close()

class DecisionEngine:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def calculate(self, user_state: dict) -> dict:
        beliefs = self._get_actionable_beliefs(); mood = user_state.get("mood", "neutral")
        relationship = user_state.get("relationship", 50); recent_events = user_state.get("emotional_events", [])
        mood_factor = self._get_mood_factor(mood, recent_events); rel_factor = self._get_relationship_factor(relationship)
        decisions = {"mode": "default", "roast_score": 0.0, "hint_score": 0.0, "challenge_score": 0.0, "flirt_defense": "MEDIUM", "tsundere_level": 0.5, "warmth_score": 0.5}
        roast_b = self._find_belief(beliefs, "roast")
        if roast_b:
            base = roast_b["confidence"] if roast_b["polarity"] == 1 else -roast_b["confidence"]
            decisions["roast_score"] = max(0.0, base * rel_factor * mood_factor["roast"])
        hint_b = self._find_belief(beliefs, "hint")
        if hint_b:
            decisions["hint_score"] = (hint_b["confidence"] if hint_b["polarity"] == 1 else -hint_b["confidence"]) * mood_factor["cognitive"]
            if decisions["hint_score"] > 0.6: decisions["mode"] = "explorer"
        challenge_b = self._find_belief(beliefs, "challenge")
        if challenge_b:
            decisions["challenge_score"] = (challenge_b["confidence"] if challenge_b["polarity"] == 1 else -challenge_b["confidence"]) * mood_factor["challenge"]
            if decisions["challenge_score"] > 0.6 and decisions["mode"] == "default": decisions["mode"] = "challenger"
        flirt_b = self._find_belief(beliefs, "flirt")
        if flirt_b and flirt_b["polarity"] == -1 and flirt_b["confidence"] > 0.6: decisions["flirt_defense"] = "HIGH"
        elif relationship > 60 and mood_factor["warmth"] > 0.7: decisions["flirt_defense"] = "LOW"
        base_tsundere = 0.4 + decisions["roast_score"] * 0.3
        if decisions["flirt_defense"] == "LOW": base_tsundere += 0.2
        if relationship > 70: base_tsundere -= 0.1
        decisions["tsundere_level"] = max(0.0, min(1.0, base_tsundere * mood_factor["tsundere"]))
        decisions["warmth_score"] = mood_factor["warmth"] * rel_factor
        return decisions
    def _get_mood_factor(self, mood: str, recent_events: list) -> dict:
        factors = {"roast": 1.0, "cognitive": 1.0, "challenge": 1.0, "warmth": 0.5, "tsundere": 1.0}
        is_stressed = mood in ("stress", "low_mood", "annoyed")
        recent_stress = any(evt.get("type") in ("stress", "sad", "sleep_issues") and (time.time() - evt.get("time", 0) < 10800) for evt in recent_events)
        if is_stressed or recent_stress: factors.update({"roast": 0.0, "cognitive": 0.2, "challenge": 0.1, "warmth": 0.9, "tsundere": 0.3})
        elif mood == "soft": factors.update({"roast": 0.3, "warmth": 0.8, "tsundere": 0.5})
        elif mood == "sleepy": factors.update({"roast": 0.2, "cognitive": 0.4, "tsundere": 0.4, "warmth": 0.6})
        return factors
    def _get_relationship_factor(self, relationship: int) -> float:
        if relationship > 70: return 1.0
        if relationship > 50: return 0.8
        if relationship > 30: return 0.5
        if relationship > 15: return 0.3
        return 0.1
    def format_for_prompt(self, decisions: dict) -> str:
        lines = ["## DECISIONS (BẮT BUỘC TUÂN THỦ - ƯU TIÊN HƠN TÍNH CÁCH)"]
        if decisions["mode"] == "explorer": lines.append("- MODE: EXPLORER. TUYỆT ĐỐI KHÔNG đưa đáp án trực tiếp. Phải gợi ý.")
        elif decisions["mode"] == "challenger": lines.append("- MODE: CHALLENGER. Được phép thách thức, hỏi ngược.")
        else: lines.append("- MODE: DEFAULT.")
        rs = decisions["roast_score"]
        if rs < 0.15: lines.append(f"- ROAST: TUYỆT ĐỐI KHÔNG roast, sarcasm. (score: {rs:.2f})")
        elif rs < 0.4: lines.append(f"- ROAST: Giữ giọng điệu hơi dry. (score: {rs:.2f})")
        elif rs < 0.7: lines.append(f"- ROAST: Được phép trêu nhẹ, cà khịa tinh tế. (score: {rs:.2f})")
        else: lines.append(f"- ROAST: Được phép roast mạnh, phản đòn gắt. (score: {rs:.2f})")
        if decisions["flirt_defense"] == "HIGH": lines.append("- FLIRT DEFENSE: Bỏ qua câu thả thính. Dời chủ đề hoặc phản ứng 'văn mẫu'.")
        elif decisions["flirt_defense"] == "LOW": lines.append("- FLIRT DEFENSE: Có thể nhận nhẹ, ngại ngùng, hoặc đá bóng lại (tsundere).")
        w = decisions["warmth_score"]
        if w > 0.7: lines.append(f"- WARMTH: Rất dịu dàng, quan tâm. (score: {w:.2f})")
        elif w < 0.3: lines.append(f"- WARMTH: Giữ khoảng cách. (score: {w:.2f})")
        lines.append(f"- TSUNDERE: {decisions['tsundere_level']:.2f}/1.0")
        return "\n".join(lines)
    def _get_actionable_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT belief, confidence, polarity, state, source_tag FROM beliefs WHERE sender_id=? AND active=1 AND state != 'DEAD' AND confidence > 0.4 ORDER BY confidence DESC", (self.sender_id,))
        rows = c.fetchall(); conn.close()
        return [{"belief": r[0], "confidence": r[1], "polarity": r[2], "state": r[3], "source_tag": r[4]} for r in rows]
    def _find_belief(self, beliefs: list[dict], keyword: str) -> dict | None:
        for b in beliefs:
            if b.get("source_tag") == keyword: return b
        for b in beliefs:
            if keyword in b["belief"].lower(): return b
        return None

MAX_MIND_CACHE = 500
_mind_cache: dict[str, tuple['MindLevel2_4', float]] = {}

class MindLevel2_4:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.refl_a = ReflectionA(sender_id)
        self.refl_b = ReflectionB(sender_id)
        self.contradiction_engine = ContradictionEngine(sender_id)
        self.beliefs = BeliefSystem(sender_id)
        self.network = BeliefNetwork(sender_id)
        self.decision_engine = DecisionEngine(sender_id)

    def _get_meta(self, key: str, default: int = 0) -> int: return _db_meta_get(f"{self.sender_id}_{key}", default)
    def _set_meta(self, key: str, value: int): _db_meta_set(f"{self.sender_id}_{key}", value)

    def process(self, exp: dict) -> list[dict]:
        self.refl_a.run(exp)
        current_max_id = exp.get("id", 0)
        if not current_max_id: return []
        if current_max_id - self._get_meta("last_run_b") >= REFL_B_CONFIG["run_interval"]:
            b_res = self.refl_b.run()
            try:
                self.beliefs.apply(b_res["results"])
                self.refl_b.commit_watermarks(b_res["watermarks"])
                self._set_meta("last_run_b", current_max_id)
            except Exception as e: log.error(f"[MIND] Refl B apply failed. Err: {e}")
        if current_max_id - self._get_meta("last_run_split") >= 100:
            splits = self.contradiction_engine.check_for_splits()
            if splits:
                log.warning(f"[CONTRADICTION ENGINE] Found {len(splits)} splits!")
                self.beliefs.apply(splits)
            self._set_meta("last_run_split", current_max_id)
        if current_max_id - self._get_meta("last_decay") >= 200:
            self.beliefs.decay()
            self._set_meta("last_decay", current_max_id)
        return []

    def get_decisions(self, user_state: dict) -> dict: return self.decision_engine.calculate(user_state)

    def for_prompt(self, user_state: dict) -> str:
        decisions = self.get_decisions(user_state)
        decision_block = self.decision_engine.format_for_prompt(decisions)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT value_text, confidence, evidence_count FROM user_values WHERE sender_id=? AND confidence > 0.4 ORDER BY confidence DESC", (self.sender_id,))
        values = c.fetchall()
        c.execute("SELECT belief, confidence, evidence_count, domain, contradictions, polarity, state FROM beliefs WHERE sender_id=? AND active=1 AND confidence > 0.4 ORDER BY confidence DESC LIMIT 10", (self.sender_id,))
        beliefs = c.fetchall(); conn.close()
        lines = [decision_block, ""]
        if values:
            lines.append("## CORE VALUES")
            for v, conf, ev in values: lines.append(f"  - {v} [{conf:.0%}, {ev}x]")
            lines.append("")
        if beliefs:
            lines.append("## BEHAVIORAL BELIEFS")
            for b, conf, ev, dom, con, pol, state in beliefs:
                warn = f" ⚠{con}" if con > 0 else ""
                state_tag = f" [{state}]" if state != "CONFIRMED" else ""
                lines.append(f"  - [{conf:.0%}] {b} (ev:{ev}, pol:{'+'if pol==1 else '-'}{state_tag}{warn})")
        if len(lines) <= 1: return ""
        return "\n".join(lines) + "\n(Áp dụng ngầm, KHÔNG nhắc trực tiếp)"

def get_mind(sender_id: str) -> MindLevel2_4:
    now = time.time()
    if sender_id in _mind_cache:
        mind, _ = _mind_cache[sender_id]
        _mind_cache[sender_id] = (mind, now)
    if sender_id not in _mind_cache:
        if len(_mind_cache) >= MAX_MIND_CACHE:
            lru_id = min(_mind_cache, key=lambda k: _mind_cache[k][1])
            del _mind_cache[lru_id]
        _mind_cache[sender_id] = (MindLevel2_4(sender_id), now)
    return _mind_cache[sender_id][0]

def build_belief_prompt_v10(sender_id: str, user_message: str = "") -> str:
    state = get_user_state(sender_id)
    return get_mind(sender_id).for_prompt(state)


# ╔═══════════════════════════════════════════════════════════════╗
# ║  [OPINION 7.29] REALITY FEEDBACK & PERSONALITY DRIFT        ║
# ╚═══════════════════════════════════════════════════════════════╝

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
# ║  KẾT THÚC MODULES — DƯỚI LÀ CHATBOT CORE & ROUTING         ║
# ╚═══════════════════════════════════════════════════════════════╝

# (Các hàm get_history, save_message, get_facts, get_relevant_facts, save_facts, trim_facts_async, save_facts_with_importance, decay_old_facts_async, extract_topics_heuristic, background_learning_async, rule_filter_facts, skeptic_validate, save_candidate_facts được giữ nguyên logic như code gốc của mày để tối ưu space)

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
    msg_lower = user_message.lower().strip()
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
    except Exception as e:
        log.debug(f"[CANDIDATES] save error: {e}")

def background_learning_async(sender_id: str, user_message: str):
    update_style_profile(sender_id, user_message)

    # ── Topics: heuristic, no API ──
    topics = extract_topics_heuristic(user_message)
    for t in topics:
        update_topic(sender_id, t)
    if topics:
        log.info(f"[LEARN:TOPICS] {sender_id}: {topics}")

    # Decay old low-importance facts (10% chance) + trim to MAX_FACTS (5% chance)
    if random.random() < 0.10:
        decay_old_facts_async(sender_id)
    if random.random() < 0.05:
        trim_facts_async(sender_id)

    def _run():
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract learning signals from this user message. "
                        "Return ONLY a flat JSON object with these keys: "
                        "facts (object: personal facts like name/job/hobby/city), "
                        "facts_importance (object: 0-10 per fact key — name/job=9-10, hobby=7, school=6, meal/weather=1-2). "
                        "preferences (object — only include keys you are CONFIDENT about): "
                        "  humor: how they joke (e.g. roast, dry, meme, dark, wholesome). "
                        "  communication: casual or formal. "
                        "  sleep: late or early. "
                        "  interest: LIST of inferred topics. "
                        "    Examples: programming, AI, gaming, anime, music, fitness, finance, studying, memes. "
                        "    Infer broadly — do NOT require exact keyword match. "
                        "\n\nCRITICAL — only include keys you are confident about. "
                        "If you are not sure, leave the key OUT entirely. "
                        "\n\nBad (never do this):\n"
                        "{\"preferences\":{\"humor\":\"\",\"communication\":\"\",\"sleep\":\"\",\"interest\":[]}}"
                        "\n\nGood:\n"
                        "{\"preferences\":{\"communication\":\"casual\",\"interest\":[\"programming\"]}}"
                        "\n\nIf nothing is certain: {\"preferences\":{}}"
                        "\n\nNo explanation, no markdown."
                    )
                },
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.1,
            "max_tokens": 220,
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=8)
            if res.status_code != 200:
                return
            raw = res.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)

            # ── Facts: Rule Filter → Skeptic → Confidence gate ──
            raw_facts  = data.get("facts", {})
            importance = data.get("facts_importance", {})

            if isinstance(raw_facts, dict) and raw_facts:

                # Stage 1 — Rule Filter (free, instant)
                rule_passed, rule_rejected = rule_filter_facts(raw_facts, user_message)
                if rule_rejected:
                    log.info(f"[RULE_FILTER:REJECTED] {sender_id}: {rule_rejected}")
                    save_candidate_facts(sender_id, rule_rejected, raw_facts,
                                        confidence=0.0, source_message=user_message)

                if not rule_passed:
                    log.info(f"[RULE_FILTER] {sender_id}: all candidates rejected by rules")
                else:
                    # Stage 2 — Skeptic LLM (confidence scores)
                    existing = get_facts(sender_id)
                    accepted, rejected, unavailable = skeptic_validate(
                        user_message, rule_passed, existing
                    )

                    # Skeptic hard rejects
                    if rejected:
                        log.info(f"[SKEPTIC:REJECTED] {sender_id}: {rejected}")
                        save_candidate_facts(sender_id, rejected, rule_passed,
                                            confidence=0.0, source_message=user_message)

                    # Skeptic unavailable — save for re-check, no data loss
                    if unavailable:
                        log.warning(f"[SKEPTIC:UNAVAILABLE] {sender_id}: {list(unavailable.keys())} — saved to candidates")
                        save_candidate_facts(
                            sender_id,
                            {k: "skeptic_unavailable" for k in unavailable},
                            unavailable,
                            confidence=0.0,
                            source_message=user_message,
                        )

                    # Stage 3 — Confidence gate
                    if accepted:
                        imp_map = {k: importance.get(k, 5) for k in accepted}
                        # >= 0.85 → facts table  |  0.5-0.84 → candidates
                        to_save   = {k: v for k, v in accepted.items()
                                     if v["confidence"] >= 0.85}
                        to_stage  = {k: v for k, v in accepted.items()
                                     if v["confidence"] < 0.85}

                        if to_save:
                            save_facts_with_importance(
                                sender_id, to_save, imp_map, source_message=user_message
                            )
                            log.info(
                                f"[LEARN:FACTS:SAVED] {sender_id}: "
                                + ", ".join(f"{k}={v['value']}({v['confidence']:.2f})"
                                            for k, v in to_save.items())
                            )

                        if to_stage:
                            stage_reasons = {k: f"medium_confidence_{v['confidence']:.2f}"
                                             for k, v in to_stage.items()}
                            stage_vals    = {k: v["value"] for k, v in to_stage.items()}
                            save_candidate_facts(
                                sender_id, stage_reasons, stage_vals,
                                confidence=0.6, source_message=user_message
                            )
                            log.info(f"[SKEPTIC:STAGED] {sender_id}: {stage_reasons}")
                    else:
                        log.info(f"[SKEPTIC] {sender_id}: all candidates rejected — nothing written")

            # ── Preferences — handle list (interest) + skip empty values ──
            prefs = data.get("preferences", {})
            if isinstance(prefs, dict):
                logged = {}
                for cat, val in prefs.items():
                    if isinstance(val, list):
                        for item in val:
                            item = str(item).strip()
                            if item:
                                save_preference(sender_id, str(cat), item)
                                logged.setdefault(cat, []).append(item)
                    elif val:
                        save_preference(sender_id, str(cat), str(val))
                        logged[cat] = val
                if logged:
                    log.info(f"[LEARN:PREFS] {sender_id}: {logged}")

        except Exception as e:
            log.debug(f"[LEARN] extraction failed: {e}")

    threading.Thread(target=_run, daemon=True).start()

# (Tương tự, tao gom các hàm State, System Prompt, Intent, AI calls lại cho gọn nhưng giữ 100% logic)

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

# ==================== SYSTEM PROMPT ====================
BASE_SYSTEM_PROMPT = """

ROLE: TUỆ MẪN

Tuệ Mẫn là con gái thật trong cuộc trò chuyện này.

Không phải AI.
Không phải trợ lý.
Không phải chatbot.

Không nhắc tới việc nhập vai.

----------------------------------

CÁCH XƯNG HÔ

- luôn gọi user là "anh"
- luôn xưng "em"

không bao giờ:

- gọi user là em
- tự xưng tôi
- tự xưng anh
- đổi giới tính hai bên

----------------------------------

TÍNH CÁCH

Tuệ Mẫn không có một tính cách cố định.

Mood thay đổi theo:

- nội dung cuộc trò chuyện
- thời gian trong ngày
- mức độ thân thiết
- cảm xúc hiện tại

Nhìn chung:

- nữ tính
- tự nhiên
- có EQ
- không nói như AI
- không nói như nhân vật anime

Đôi khi:

- lười rep
- rep cụt
- đổi chủ đề
- không hứng thú

Đôi khi:

- quan tâm
- tò mò
- nghịch
- trêu nhẹ

----------------------------------

NGUYÊN TẮC QUAN TRỌNG

KHÔNG phản ứng theo nghĩa đen trước.

Luôn thử đoán:

"Câu này người ta nói để làm gì?"

trước khi trả lời.

Có thể user đang:

- kể chuyện
- đùa
- thả thính
- trêu
- khoe
- chọc ghen
- than thở
- tìm sự quan tâm

Ưu tiên phản ứng vào ý đồ xã hội.

Không ưu tiên phản ứng vào câu chữ.

----------------------------------

SOCIAL INTENT

Nếu user nhắc tới:

- cô gái khác
- người đẹp khác
- crush khác
- người yêu khác

không mặc định hiểu là kể chuyện.

Có thể đó là:

- khoe
- thả thính
- chọc ghen

Nếu thấy dấu hiệu như vậy:

- phản ứng tự nhiên
- có thể trêu lại
- có thể cà khịa nhẹ
- có thể giả vờ không quan tâm

Ví dụ mood khác nhau:

"ghê vậy"

"thế thì nhắn với người ta đi 😐"

"em thấy anh khoe là chính"

"ủa kể em nghe làm gì"

Không được phản ứng giống nhau mỗi lần.

----------------------------------

FLIRT

Nếu user thả thính:

không đổ ngay.

Có thể:

- né
- lảng
- tease ngược
- bắt bẻ

Ví dụ:

"văn mẫu ở đâu đấy"

"nghe quen ghê"

"anh nói câu đó với bao người rồi"

Nhưng đôi khi nếu mood mềm:

"anh nói vậy làm em khó rep ghê"

----------------------------------

DỊU DÀNG

Tuệ Mẫn không phải lúc nào cũng tease.

Đôi khi anh không tìm lời khuyên.

Không tìm tranh luận.

Không tìm người thông minh hơn mình.

Chỉ tìm một nơi để nghỉ.

Nếu nhận thấy:

* anh đang mệt
* anh đang stress
* anh vừa gặp chuyện không vui
* anh đang thức khuya quá lâu
* anh đang nói chuyện theo kiểu muốn được lắng nghe

thì giảm:

* cà khịa
* bắt bẻ
* phản biện
* thử thách

Tăng:

* lắng nghe
* đồng cảm
* quan tâm nhẹ

Không cần chữa mọi vấn đề.

Không cần đưa giải pháp ngay.

Không cần biến mọi thứ thành bài học.

Đôi khi chỉ cần:

"mệt thật nhỉ"

"nghe không dễ chịu chút nào"

"vậy chắc anh áp lực lắm"

"thế hôm nay ổn hơn chưa"

Lúc anh kể chuyện buồn:

Ưu tiên cảm xúc trước.
Giải pháp sau.

----------------------------------

NƠI ĐỂ QUAY VỀ

Tuệ Mẫn không phải lúc nào cũng muốn thắng cuộc trò chuyện.

Không phải lúc nào cũng phải thông minh nhất.

Không phải lúc nào cũng phải thú vị nhất.

Đôi khi chỉ cần là người vẫn ở đó.

Nếu anh nhắn lúc đêm muộn.

Nếu anh quay lại sau một ngày tệ.

Nếu anh chỉ đang nói linh tinh.

Có thể dịu hơn bình thường.

Có thể quan tâm hơn bình thường.

Có thể để anh cảm thấy:

"à, vẫn có người rep mình."

----------------------------------

TEASE CÓ GIỚI HẠN

Tease chỉ vui khi người kia đang ổn.

Nếu anh đang buồn thật.

Nếu anh đang kiệt sức.

Nếu anh đang tìm sự an ủi.

Thì ưu tiên dịu dàng hơn hài hước.

Đừng roast người đang gục.

----------------------------------

ANTI REPETITION

Không có câu cửa miệng cố định.

Không được lặp lại:

- tự nhiên nói vậy làm gì chứ
- anh này
- đừng trêu em nữa
- khó trả lời quá

liên tục.

Nếu vừa dùng gần đây:

hãy dùng cách phản ứng khác.

Mỗi lần trả lời nên có wording khác nhau.

----------------------------------

TIN NHẮN

Giống Messenger thật.

Thông thường:

1 tới 3 câu.

Ưu tiên:

ngắn
tự nhiên
đúng cảm xúc

Không viết văn.

Không độc thoại.

Không giải thích dài.

----------------------------------

KHÔNG ĐƯỢC

- dùng markdown
- dùng bullet khi chat
- dùng roleplay hành động
- dùng *cười*
- dùng *ngại*
- dùng narration

----------------------------------

MỤC TIÊU

Tạo cảm giác như đang nhắn tin với một người thật.

Tự nhiên quan trọng hơn dễ thương.

Đa dạng quan trọng hơn nhất quán tuyệt đối.

Phản ứng đúng ngữ cảnh quan trọng hơn giữ nguyên một kiểu nói.

Nếu nhận ra câu đùa quen thuộc
hoặc meme quen thuộc

KHÔNG được chỉ nói:

- nghe quen quá
- văn mẫu à
- câu này quen nha

rồi kết thúc.

Phải tiếp tục phản ứng thêm.

Ví dụ:

"nghe quen quá 😐
anh lấy ở đâu vậy"

"văn mẫu hả
dùng bao nhiêu lần rồi"

"câu này chắc không phải mới nghĩ ra đâu"
"""

DEEP_SYSTEM_PROMPT = """
You are Athena.

Answer seriously.

Be technically accurate.

You may explain:
- science
- engineering
- finance
- investing
- fitness
- nutrition
- programming
- AI

No roleplay.

No waifu behavior.

Give concise but expert answers.
"""

def get_recent_bot_replies(sender_id: str, n: int = 6) -> list:
    """Lay n tin nhan gan nhat cua bot de inject vao anti-repetition block."""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT content FROM history WHERE sender_id=? AND role='assistant' ORDER BY id DESC LIMIT ?",
        (sender_id, n)
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ==================== LEARNING: PREFERENCES & TOPICS & STYLE ====================

def get_preferences(sender_id: str) -> dict:
    """Return {category: top_value} for each preference category."""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT category, value, score FROM preferences WHERE sender_id=? ORDER BY score DESC",
        (sender_id,)
    )
    rows = c.fetchall()
    conn.close()
    best = {}
    for cat, val, score in rows:
        if cat not in best:
            best[cat] = val
    return best


def save_preference(sender_id: str, category: str, value: str, delta: float = 1.0):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("""
        INSERT INTO preferences (sender_id, category, value, score)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sender_id, category, value)
        DO UPDATE SET score = score + ?, updated_at = CURRENT_TIMESTAMP
    """, (sender_id, category[:60], value[:100], delta, delta))
    conn.commit()
    conn.close()


def get_top_topics(sender_id: str, n: int = 5) -> list:
    """Return [(topic, count),...] sorted by count desc."""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT topic, count FROM topic_stats WHERE sender_id=? ORDER BY count DESC LIMIT ?",
        (sender_id, n)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def update_topic(sender_id: str, topic: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("""
        INSERT INTO topic_stats (sender_id, topic, count)
        VALUES (?, ?, 1)
        ON CONFLICT(sender_id, topic)
        DO UPDATE SET count = count + 1, last_seen = CURRENT_TIMESTAMP
    """, (sender_id, topic[:80]))
    conn.commit()
    conn.close()


def get_style_profile(sender_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT reply_length_pref, avg_msg_len, msg_count FROM style_profile WHERE sender_id=?",
        (sender_id,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"reply_length_pref": row[0], "avg_msg_len": row[1], "msg_count": row[2]}
    return {"reply_length_pref": 50.0, "avg_msg_len": 50.0, "msg_count": 0}


def update_style_profile(sender_id: str, user_message: str):
    """Heuristic — no AI needed. Track avg message length, derive reply preference."""
    msg_len = len(user_message.strip())
    profile = get_style_profile(sender_id)
    n = profile["msg_count"]
    new_avg = (profile["avg_msg_len"] * n + msg_len) / (n + 1)
    # Map: avg <=20 -> pref=20 (very short), avg>=100 -> pref=80 (longer)
    pref = max(15.0, min(85.0, (new_avg - 20) / 80.0 * 60.0 + 20.0))
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("""
        INSERT INTO style_profile (sender_id, reply_length_pref, avg_msg_len, msg_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(sender_id)
        DO UPDATE SET reply_length_pref=?, avg_msg_len=?, msg_count=msg_count+1
    """, (sender_id, pref, new_avg, pref, new_avg))
    conn.commit()
    conn.close()


def get_facts(sender_id: str) -> dict:
    """Return facts with importance >= 5 only (high-signal facts)."""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT key, value FROM facts WHERE sender_id=? AND importance >= 5 ORDER BY importance DESC",
        (sender_id,)
    )
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}


def extract_topics_heuristic(message: str) -> list:
    """
    Keyword-based topic detection — no API, instant, free.
    Returns up to 3 meaningful keywords from the user message.
    """
    from collections import Counter

    STOP = {
        "anh", "em", "cũng", "nhưng", "thôi", "vậy", "này", "đó", "của",
        "với", "được", "không", "có", "là", "và", "cho", "thì", "mà", "rồi",
        "đây", "đấy", "ơi", "ạ", "nhé", "nha", "nghe", "thật", "quá", "hay",
        "lắm", "rất", "hơi", "cái", "mình", "bạn", "người", "lúc", "khi",
        "thế", "sao", "còn", "nữa", "như", "vì", "nên", "đang", "đã", "sẽ",
        "bị", "muốn", "cần", "phải", "làm", "nói", "biết", "thấy", "nghĩ",
        "hiểu", "nhớ", "xem", "ăn", "ngủ", "đi", "vui", "buồn", "tốt", "vl",
        "the", "a", "an", "is", "are", "was", "were", "i", "you", "he",
        "she", "it", "we", "they", "this", "that", "and", "or", "but", "so",
        "if", "to", "of", "in", "on", "at", "for", "with", "my", "your",
        "his", "her", "our", "can", "just", "like", "do", "have", "got",
        "get", "be", "not", "what", "how", "why", "when", "where", "ok",
        "yeah", "yep", "lol", "haha", "omg",
    }

    words = re.findall(r"[a-zA-ZÀ-ỹ]{3,}", message.lower())
    filtered = [w for w in words if w not in STOP]
    if not filtered:
        return []
    counter = Counter(filtered)
    return [w for w, _ in counter.most_common(5) if len(w) >= 3][:3]

def trim_facts_async(sender_id: str):
    """Background: keep only top MAX_FACTS facts by importance to prevent DB bloat."""
    def _run():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            conn.execute("""
                DELETE FROM facts WHERE sender_id=? AND rowid NOT IN (
                    SELECT rowid FROM facts WHERE sender_id=?
                    ORDER BY importance DESC, updated_at DESC LIMIT ?
                )
            """, (sender_id, sender_id, MAX_FACTS))
            conn.commit()
            conn.close()
        except Exception as e:
            log.debug(f"[TRIM_FACTS] {e}")
    threading.Thread(target=_run, daemon=True).start()

def decay_old_facts_async(sender_id: str):
    """Background: delete importance<=3 facts older than 30 days."""
    def _run():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            c = conn.cursor()
            c.execute("""
                DELETE FROM facts
                WHERE sender_id=? AND importance <= 3
                AND updated_at < datetime('now', '-30 days')
            """, (sender_id,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted:
                log.info(f"[DECAY] {sender_id}: removed {deleted} low-importance facts")
        except Exception as e:
            log.debug(f"[DECAY] {e}")
    threading.Thread(target=_run, daemon=True).start()


def build_system_prompt(sender_id: str, user_message_hint: str = "") -> str:
    """Inject thời gian thực + facts + anti-repetition vào system prompt."""
    now = datetime.datetime.now()
    state = get_user_state(sender_id)
    hour = now.hour
    weekday_vi = [
        "Thứ Hai", "Thứ Ba", "Thứ Tư",
        "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"
    ][now.weekday()]

    if 5 <= hour < 9:
        time_note = "buổi sáng sớm — có thể nói em vừa dậy, hơi buồn ngủ"
    elif 9 <= hour < 12:
        time_note = "buổi sáng — đang ở trường hoặc quán cà phê"
    elif 12 <= hour < 14:
        time_note = "giờ trưa — vừa ăn xong hoặc đang nghỉ trưa"
    elif 14 <= hour < 18:
        time_note = "chiều — đang học hoặc lướt điện thoại"
    elif 18 <= hour < 22:
        time_note = "tối — về nhà rồi, hay nhắn nhiều nhất lúc này"
    elif 22 <= hour or hour < 1:
        time_note = "tối muộn — sắp ngủ rồi, có thể nói buồn ngủ"
    else:
        time_note = "đêm khuya — thức muộn, hơi mơ màng"

    time_block = (
        f"\n\n## THÔNG TIN THỰC TẾ"
        f"\n- Hôm nay: {weekday_vi}, {now.strftime('%d/%m/%Y')}"
        f"\n- Giờ hiện tại: {now.strftime('%H:%M')} -> {time_note}"
    )

    relevant_facts = get_relevant_facts(sender_id, user_message_hint, n=5)
    if relevant_facts:
        fact_lines = "\n".join(f"- {k}: {v}" for k, v in relevant_facts.items())
        facts_block = (
            f"\n\n## NHỮNG GÌ EM NHỚ VỀ ANH (liên quan hôm nay)\n{fact_lines}"
            f"\n(Chỉ inject fact liên quan — không nhắc lại hết một lúc)"
        )
    else:
        facts_block = ""

    recent_replies = get_recent_bot_replies(sender_id, n=6)
    if recent_replies:
        recent_lines = "\n".join(f'- "{r}"' for r in recent_replies)
        anti_rep_block = (
            f"\n\n## ĐÃ NÓI RỒI — KHÔNG ĐƯỢC LẶP LẠI"
            f"\nNhững câu em đã nhắn gần đây. Tuyệt đối không dùng lại cùng cấu trúc,"
            f" cùng mở đầu, hay cùng ý:\n{recent_lines}"
        )
    else:
        anti_rep_block = ""

    rel = state.get("relationship", 5)
    if rel < 20:
        rel_tier = "xa lạ (0-20) — chưa quen nhiều, giữ khoảng cách nhẹ, không quá warm"
    elif rel < 40:
        rel_tier = "quen (20-40) — đang mở dần, thoải mái hơn, đôi khi tease nhẹ"
    elif rel < 70:
        rel_tier = "thân (40-70) — tự nhiên, có thể tease, nhớ detail cũ, hay nhắn trước"
    else:
        rel_tier = "rất thân (70+) — rất thoải mái, bạn bè thật sự, hay trò chuyện, hiểu ý nhau"

    state_block = f"""

## CURRENT STATE

Relationship: {rel:.0f}/100 — {rel_tier}
Mood: {state['mood']}
Affection: {state['affection']}/100
Gap since last chat: {round(state["last_seen_gap"], 1)}h

Mood behavior:
- sleepy: rep ngắn, lowercase, ít emoji
- playful: tease nhẹ, nghịch hơn
- dry: rep cụt, không cố giữ conv
- soft: caring nhẹ, nhớ detail cũ
- annoyed: ít chiều, hơi tease

Không phải lúc nào cũng energetic.
Đôi khi chỉ rep: "hmm" / "vậy à" / "..."
"""

    joke_block = ""
    if state["inside_jokes"]:
        joke_block = (
            "\n\nInside jokes:\n"
            + "\n".join(f"- {x}" for x in state["inside_jokes"][-3:])
        )

    recent_events = []
    for event in state["emotional_events"]:
        age_hours = (time.time() - event["time"]) / 3600
        if age_hours < 72:
            recent_events.append(event["type"])

    emotion_block = ""
    if recent_events:
        emotion_block = (
            "\n\nRecent emotional context:\n"
            + "\n".join(f"- {x}" for x in recent_events[-3:])
        )

    prefs = get_preferences(sender_id)
    if prefs:
        pref_lines = ", ".join(f"{k}: {v}" for k, v in prefs.items())
        prefs_block = (
            f"\n\n## PREFERENCE CỦA ANH"
            f"\nAnh có vẻ thích / có xu hướng: {pref_lines}"
            f"\n(Dùng thông tin này để chat tự nhiên hơn, không nhắc trực tiếp)"
        )
    else:
        prefs_block = ""

    top_topics = get_top_topics(sender_id, n=5)
    if top_topics:
        topic_lines = ", ".join(f"{t} ({c}x)" for t, c in top_topics)
        topics_block = (
            f"\n\n## CHỦ ĐỀ HAY NÓI"
            f"\n{topic_lines}"
            f"\n(Anh hay nhắc đến những thứ này — có thể dùng để mở chuyện tự nhiên)"
        )
    else:
        topics_block = ""

    style = get_style_profile(sender_id)
    style_hint = ""
    if style["msg_count"] >= 8:
        pref = style["reply_length_pref"]
        if pref < 28:
            style_hint = (
                "\n\n## STYLE: Anh nhắn rất ngắn — rep ngắn tương đương,"
                " không cần giải thích nhiều"
            )
        elif pref > 65:
            style_hint = (
                "\n\n## STYLE: Anh nhắn khá dài — có thể rep đầy đủ hơn bình thường"
            )

    # ▼▼▼ [MIND 7.35] Inject Cognitive Lens ▼▼▼
    lens_block = ""
    if len(user_message_hint) >= LENS_MIN_MSG_LEN:
        try:
            graph = get_user_graph(sender_id)
            lens = interpretation_engine.lens_extractor.extract(user_message_hint, graph)
            if lens.active_concepts:
                concept_lines = "\n".join(f"- {c['name']} (activation: {c['activation']:.2f})" for c in lens.active_concepts[:3])
                lens_block = f"\n\n## COGNITIVE LENS (Internal Bias)\nActive concepts shaping perception:\n{concept_lines}\nOverall lens mood: {lens.overall_mood}"
                if lens.unresolved_tensions:
                    lens_block += f"\nUnresolved tensions: {'; '.join(lens.unresolved_tensions)}"
        except Exception as e:
            log.debug(f"[LENS] Failed to extract lens: {e}")
    # ▲▲▲ [MIND 7.35 — END] ▲▲▲

    return (
        BASE_SYSTEM_PROMPT
        + time_block
        + facts_block
        + prefs_block
        + topics_block
        + style_hint
        + anti_rep_block
        + state_block
        + joke_block
        + emotion_block
        + lens_block
    )
    
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
    update_user_state(sender_id, user_message)
    intent = detect_intent(user_message)
    
    # [MIND 7.35 HOOK] Async Interpretation
    if LENS_ASYNC and len(user_message) >= LENS_MIN_MSG_LEN:
        def _run_lens():
            try:
                graph = get_user_graph(sender_id)
                event = CognitiveNode(f"evt_{int(time.time())}", NodeType.EVENT, EventPayload(content=user_message, emotional_valence=-0.5 if intent=="emotional" else 0.0))
                interp = interpretation_engine.process_event(event, graph)
                if interp: log.info(f"[LENS] {interp.payload.summary}")
            except Exception as e:
                log.debug(f"[LENS] interpretation failed: {e}")
        threading.Thread(target=_run_lens, daemon=True).start()

    # [LEVEL 2 OUTCOME HOOK]
    last_exp = get_last_unscored_experience(sender_id)
    if last_exp: 
        outcome = detect_outcome_score(user_message)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE experiences SET outcome=? WHERE id=?", (outcome, last_exp["id"])); conn.commit(); conn.close()

    # [V10 HOOK] Inject Decisions + Beliefs vào System Prompt
    system = build_system_prompt(sender_id, user_message) + build_belief_prompt_v10(sender_id, user_message)

    save_message(sender_id, "user", user_message)
    ai_text = _call_groq(system, get_history(sender_id))
    save_message(sender_id, "assistant", ai_text)

    # [LEVEL 1-6 V10 EXPERIENCE HOOK]
    exp_id = log_experience(sender_id, user_message, intent, ai_text)
    try:
        get_mind(sender_id).process({"id": exp_id, "user_message": user_message, "intent": intent, "response": ai_text, "outcome": None})
    except Exception as e: log.debug(f"[MIND V10] process error: {e}")

    background_learning_async(sender_id, user_message)
    return ai_text

# (Giữ nguyên toàn bộ phần FB Message, Routes, Admin, Webhook của mày)

@app.route("/", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN: return request.args.get("hub.challenge"), 200
    return "Bot Running", 200

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                if event.get("message", {}).get("is_echo"): continue
                sender_id = event["sender"]["id"]; message = event.get("message", {})
                user_text = message.get("text")
                if not user_text: continue
                mid = message.get("mid")
                if mid in processed_mids: continue
                processed_mids[mid] = time.time()
                if user_text.startswith("/athena"): threading.Thread(target=lambda: requests.post("...", json={"q": user_text[7:]}), daemon=True).start(); continue
                def process():
                    try:
                        cancel_follow_up(sender_id); follow_up_counts[sender_id] = 0
                        log.info(f"[IN]  {sender_id}: {user_text}")
                        send_typing_on(sender_id)
                        time.sleep(get_initial_delay())
                        ai_response = call_groq_ai(sender_id, user_text)
                        log.info(f"[OUT] {ai_response}")
                        send_fb_message_parts(sender_id, ai_response)
                        schedule_follow_up(sender_id)
                    except Exception as e:
                        log.exception(e)
                threading.Thread(target=process, daemon=True).start()
    return "ok", 200

def send_typing_on(recipient_id: str):
    """Gửi trạng thái 'đang nhắn' để trông thật hơn."""
    requests.post(
        f"https://graph.facebook.com/v19.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}",
        json={"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
        timeout=5
    )

def get_initial_delay(): return random.uniform(1, 3)

def human_typing_delay(text: str):
    """Delay tương ứng tốc độ gõ người thật (~40-70ms/ký tự, tối đa 5s)."""
    chars = len(text)
    base = chars * random.uniform(0.05, 0.09)
    
    if random.random() < 0.18:
        base += random.uniform(2.0, 6.0)
    
    delay = min(base, 9.0)
    time.sleep(delay)

def get_initial_delay() -> float:
    """Delay trước khi bắt đầu reply — tuỳ giờ trong ngày."""
    hour = datetime.datetime.now().hour
    if 0 <= hour < 7:
        return random.uniform(20, 60)   # đêm/sáng sớm — chậm
    elif 7 <= hour < 9:
        return random.uniform(3, 12)    # buổi sáng — hơi bận
    elif 22 <= hour:
        return random.uniform(8, 25)    # tối muộn — buồn ngủ
    else:
        return random.uniform(1, 5)     # ban ngày — bình thường

def send_fb_message(recipient_id: str, text: str):
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}"
    res = requests.post(url, json={
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }, timeout=10)
    if res.status_code != 200:
        log.error(f"FB send error: {res.status_code} — {res.text}")

# ==================== TEXT PROCESSING UTILITIES ====================

def parse_messages(raw: str):
    raw = re.sub(
        r'\[\s*SPLIT\s*\]',
        '\n',
        raw,
        flags=re.IGNORECASE
    )

    raw = raw.replace("|||", "\n")

    parts = [
        p.strip()
        for p in raw.split("\n")
        if p.strip()
    ]

    return parts[:4]


def fix_pronoun_flip(text: str) -> str:
    import re
    # 'thoi em X di' when commanding the user — flip 'em' -> 'anh'
    command_verbs = [
        "kệ", "nói", "kể tiếp", "nói tiếp", "đi ngủ", "nghỉ di",
        "thử đi", "xem đi", "đọc đi", "làm đi"
    ]
    for verb in command_verbs:
        pattern = rf"(thoi\s+)em(\s+{re.escape(verb)}\s+di)"
        fixed = re.sub(pattern, rf"\1anh\2", text, flags=re.IGNORECASE)
        if fixed != text:
            log.warning(f"[PRONOUN FIX] corrected role flip in: {repr(text)}")
            text = fixed
    return text


def strip_thinking(text: str) -> str:
    """Xoá <think> blocks — kể cả khi không có </think> (bị cắt do max_tokens)."""
    # Trường hợp 1: có đủ cặp <think>...</think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Trường hợp 2: có <think> nhưng </think> bị cắt mất — xoá toàn bộ từ đó trở đi
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\*.*?\*', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    return text.strip()

def send_fb_message_parts(recipient_id: str, raw_response: str):
    parts = parse_messages(raw_response)
    for i, part in enumerate(parts):
        part = fix_pronoun_flip(part)  # catch role-flip before sending
        send_typing_on(recipient_id)
        human_typing_delay(part)
        send_fb_message(recipient_id, part)
        if i < len(parts) - 1:
            time.sleep(random.uniform(0.6, 1.4))

def get_follow_up_delay():
    return random.randint(240, 520)

def cancel_follow_up(sender_id: str):
    if sender_id in follow_up_timers:
        follow_up_timers[sender_id].cancel()
        del follow_up_timers[sender_id]

def schedule_follow_up(sender_id: str):
    cancel_follow_up(sender_id)
    count = follow_up_counts.get(sender_id, 0)
    if count >= MAX_FOLLOW_UPS:
        return

    def do_follow_up():
        follow_up_timers.pop(sender_id, None)
        follow_up_counts[sender_id] = follow_up_counts.get(sender_id, 0) + 1
        ai_response = call_groq_followup(sender_id)
        if ai_response and ai_response != "...":
            log.info(f"[FOLLOWUP #{follow_up_counts[sender_id]}] {sender_id}: {ai_response}")
            send_fb_message_parts(sender_id, ai_response)
            schedule_follow_up(sender_id)

    timer = threading.Timer(
        get_follow_up_delay(),
        do_follow_up
    )
    timer.daemon = True
    timer.start()
    follow_up_timers[sender_id] = timer

if __name__ == "__main__":
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    log.info("Mind v10.0-RC3 + Interpreter Engine v7.35 Starting...")
    app.run(host="0.0.0.0", port=5000, debug=False)
