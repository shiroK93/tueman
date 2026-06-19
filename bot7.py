"""
TUỆ MẪN 7.56 — THE COGNITIVE SPINE (COMPLETE)
"Evidence flows UP. Preference flows DOWN. Nothing flows back up."

⚠️  WARNING: 7.56 is an integration layer. It connects 3 existing organs
    (Perception, Worldview, Self-Model) via strict unidirectional contracts.
    This is 7.56 with all missing runtime functions backported from 7.47.3.
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
from typing import Optional, Callable, Any, List, Dict, TypedDict
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
import traceback

load_dotenv()

# ==================== TIMING HELPER ====================
class _T:
    def __init__(self): self._s = time.perf_counter()
    def ms(self) -> int: return int((time.perf_counter() - self._s) * 1000)
    def __str__(self): return f"{self.ms()}ms"

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

# ╔═══════════════════════════════════════════════════════════════╗
# ║  7.58 PREP: MEANING ENGINE FIREWALL                            ║
# ╚═══════════════════════════════════════════════════════════════╝

@dataclass
class RawMotif:
    """Mìn K: LOCKED OUTPUT. No semantics."""
    phrase: str                 
    recurrence_count: int       
    avg_interval_hours: float   
    co_occurrence: list[str]    

class MeaningEngine:
    """7.58: Chỉ đọc Observation. Không đọc Hypothesis/Belief."""
    _allowed_fields = {"text", "timestamp", "word_count"}
    
    def extract_motifs(self, observations: list) -> list[RawMotif]:
        motifs = []
        # Verify input purity (Firewall)
        for obs in observations:
            if hasattr(obs, 'hypothesis') or hasattr(obs, 'belief'):
                log.error("FIREWALL: MeaningEngine received contaminated input")
                return []
        
        # Tìm N-grams lặp lại (logic đơn giản cho 7.56 prep)
        text_counts = {}
        for obs in observations:
            text = obs.get("text", "").lower()
            if len(text.split()) <= 4:
                text_counts[text] = text_counts.get(text, 0) + 1
                
        for text, count in text_counts.items():
            if count >= 3:
                motifs.append(RawMotif(
                    phrase=text,
                    recurrence_count=count,
                    avg_interval_hours=24.0, # Mock
                    co_occurrence=[]
                ))
        return motifs

app = Flask(__name__)

# ==================== CONFIGURATION ====================
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_APP_SECRET        = os.environ.get("FB_APP_SECRET")
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
# ║  7.56.6: COGNITIVE SPINE CONTRACTS (HYPOTHESIS MARKET)        ║
# ╚═══════════════════════════════════════════════════════════════╝

class PerceptionOutput(TypedDict):
    raw_text: str
    features: dict              # Boolean features from FeatureExtractor
    sentiment: float            # -1.0 to 1.0
    text_length: int

class WorldviewOutput(TypedDict):
    top_hypotheses: list[dict]  # [{claim, confidence, predicts_confirm}]
    active_beliefs: list[dict]
    contradiction_level: float
    worldview_entropy: float    # 0.0 = certain, 1.0 = uncertain

class ValuesOutput(TypedDict):
    active_values: list

class SelfModelOutput(TypedDict):
    role: str
    archetype: str
    model_accuracy: float
    doubt_style: str
    identity_vector: dict

class VoiceOutput(TypedDict):
    decision: str
    interaction_mode: str
    warmth: float
    roast_score: float
    dominant_voice: str

class ResponseMetadata(TypedDict):
    response_id: int
    predicted_stance: str
    predicted_outcome: float
    timestamp: float

@dataclass
class CognitiveContext:
    perception: PerceptionOutput = field(default_factory=lambda: {"features": {}, "sentiment": 0.0, "text_length": 0})
    worldview: WorldviewOutput = field(default_factory=lambda: {"top_hypotheses": [], "active_beliefs": [], "contradiction_level": 0.0, "worldview_entropy": 1.0})
    values: ValuesOutput = field(default_factory=lambda: {"active_values": []})
    self_model: SelfModelOutput = field(default_factory=lambda: {"role": "", "archetype": "explorer", "model_accuracy": 1.0, "doubt_style": "none", "identity_vector": {}})
    voice: VoiceOutput = field(default_factory=lambda: {"decision": "default", "interaction_mode": "natural", "warmth": 0.5, "roast_score": 0.0, "dominant_voice": ""})
    user_state: dict = field(default_factory=dict)

# ╔═══════════════════════════════════════════════════════════════╗
# ║  🧠 [MIND 7.35] INTERPRETATION ENGINE — CORE SCHEMA           ║
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
class BasePayload: pass

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

    def to_dict(self): return {"id": self.id, "type": self.type.value, "payload": asdict(self.payload), "created_at": self.created_at}
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
        if filepath and os.path.exists(filepath): self._load()

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
            if self._are_opposing(c1, c2): unresolved.append(f"Internal conflict between '{c1}' and '{c2}'")
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
            except: interp_text, emotion, conf = self._mock_llm_deformation(event.payload.content, lens)
        else: interp_text, emotion, conf = self._mock_llm_deformation(event.payload.content, lens)
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
# ║  🔌 LLM PROVIDER ROUTER                                       ║
# ╚═══════════════════════════════════════════════════════════════╝
class Provider:
    name = "base"
    def generate(self, system: str, messages: list, max_tokens: int = 512) -> str: raise NotImplementedError

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

    def _attempt(self, provider, system, messages, max_tokens):
        if self._is_cooling_down(provider.name): return None, RuntimeError(f"{provider.name} on cooldown")
        try:
            response = provider.generate(system, messages, max_tokens)
            if response: return response, None
            return None, RuntimeError(f"{provider.name} empty")
        except Exception as e:
            self._mark_cooldown(provider.name, e)
            return None, e

_router = ProviderRouter()
interpretation_engine = InterpretationEngine(llm_func=make_llm_interpret_func(_router))

# ==================== IN-MEMORY STATE ====================
follow_up_timers = {}
follow_up_counts = {}
user_states = {}
processed_mids = {}
_state_lock = threading.Lock()
MID_TTL_SECONDS = 6 * 3600
MID_PRUNE_EVERY = 500

def _mark_mid_processed(mid: str):
    now = time.time()
    with _state_lock:
        processed_mids[mid] = now
        if len(processed_mids) % MID_PRUNE_EVERY == 0:
            cutoff = now - MID_TTL_SECONDS
            stale = [m for m, ts in processed_mids.items() if ts < cutoff]
            for m in stale: processed_mids.pop(m, None)

def _is_mid_processed(mid: str) -> bool:
    with _state_lock: return mid in processed_mids

def _incr_follow_up_count(sender_id: str) -> int:
    with _state_lock:
        follow_up_counts[sender_id] = follow_up_counts.get(sender_id, 0) + 1
        return follow_up_counts[sender_id]

def _reset_follow_up_count(sender_id: str):
    with _state_lock: follow_up_counts[sender_id] = 0

def _get_follow_up_count(sender_id: str) -> int:
    with _state_lock: return follow_up_counts.get(sender_id, 0)

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
    for ddl in ["ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 5","ALTER TABLE facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE facts ADD COLUMN confidence REAL DEFAULT 0.8","ALTER TABLE facts ADD COLUMN source_message TEXT DEFAULT ''"]:
        try: c.execute(ddl)
        except: pass
    c.execute("CREATE TABLE IF NOT EXISTS fact_candidates (sender_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, score INTEGER DEFAULT 1, rejection_reason TEXT DEFAULT NULL, last_seen DATETIME DEFAULT CURRENT_TIMESTAMP, confidence REAL DEFAULT 0.0, source_message TEXT DEFAULT '', PRIMARY KEY (sender_id, key))")
    c.execute("CREATE TABLE IF NOT EXISTS experiences (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, user_message TEXT NOT NULL, intent TEXT DEFAULT '', response TEXT NOT NULL, decision TEXT DEFAULT 'respond', outcome INTEGER DEFAULT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS beliefs (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, belief TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, last_updated DATETIME DEFAULT CURRENT_TIMESTAMP)")
    # 7.56: Pending Predictions for delayed feedback
    c.execute("""CREATE TABLE IF NOT EXISTS pending_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, response_id INTEGER NOT NULL,
        predicted_stance TEXT NOT NULL, timestamp REAL NOT NULL, resolved INTEGER DEFAULT 0,
        resolved_at REAL DEFAULT NULL, resolution_type TEXT DEFAULT NULL, outcome_score INTEGER DEFAULT NULL
    )""")
    conn.commit(); conn.close()

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
        "ALTER TABLE beliefs ADD COLUMN nuances TEXT DEFAULT '[]'",
        "ALTER TABLE beliefs ADD COLUMN counter_evidence TEXT DEFAULT '[]'",
        "ALTER TABLE beliefs ADD COLUMN relationship_evolution TEXT DEFAULT ''",
    ]:
        try: c.execute(ddl)
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS belief_connections (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, conn_type TEXT NOT NULL DEFAULT 'related', strength REAL DEFAULT 0.5, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, from_id, to_id, conn_type))""")
    c.execute("""CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, tag TEXT NOT NULL, outcome INTEGER NOT NULL, exp_id INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, tag, exp_id))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ev_time ON evidence(sender_id, created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS user_values (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL, value_text TEXT NOT NULL, confidence REAL DEFAULT 0.5, evidence_count INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(sender_id, value_text))""")
    c.execute("""CREATE TABLE IF NOT EXISTS self_model (sender_id TEXT PRIMARY KEY, role TEXT NOT NULL DEFAULT 'Người duy nhất có thể cản Thắng lại', success_rate REAL DEFAULT 1.0, failure_count INTEGER DEFAULT 0, model_accuracy REAL DEFAULT 1.0, doubt_style TEXT DEFAULT 'none')""")
    c.execute("UPDATE beliefs SET state = 'UNCERTAIN' WHERE confidence < 0.5 AND state = 'CONFIRMED'")
    c.execute("UPDATE beliefs SET state = 'INVESTIGATING' WHERE contradiction_score >= 0.8 AND state != 'INVESTIGATING'")
    conn.commit(); conn.close()

init_db()
migrate_belief_system_v47()

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

# ╔═══════════════════════════════════════════════════════════════╗
# ║  7.56.6: HYPOTHESIS MARKET & FEATURE EXTRACTOR                ║
# ╚═══════════════════════════════════════════════════════════════╝

@dataclass
class Features:
    contains_positive_affect: bool = False
    contains_negative_affect: bool = False
    contains_intensifier: bool = False
    contains_job_reference: bool = False
    contains_state_change: bool = False
    contains_deflection: bool = False
    message_length_bucket: str = "short"
    response_latency_bucket: str = "normal"
    affect_polarity: str = "neutral"
    engagement_level: str = "normal"

class FeatureExtractor:
    POSITIVE_WORDS = {"vui", "ok", "tốt", "hay", "đỉnh", "vui vl", "haha", "lmao", "tuyệt", "ổn"}
    NEGATIVE_WORDS = {"mệt", "buồn", "chán", "sấp", "sập", "khóc", "thất bại", "kiệt", "chết", "không muốn"}
    INTENSIFIERS = {"vl", "cực", "rất", "cái gì", "vãi", "không thể"}
    JOB_WORDS = {"việc", "công ty", "job", "dự án", "code", "deadline", "sếp"}
    STATE_CHANGE = {"nghỉ", "thôi", "bắt đầu", "chuyển", "quit", "nghỉ việc", "bỏ"}
    DEFLECTION = {"không có gì", "thôi", "qua rồi", "không sao", "ỏn", "tao ổn"}
    
    def extract(self, text: str, prev_timestamp: float = None) -> Features:
        text_lower = text.lower().strip()
        f = Features()
        f.contains_positive_affect = any(w in text_lower for w in self.POSITIVE_WORDS)
        f.contains_negative_affect = any(w in text_lower for w in self.NEGATIVE_WORDS)
        f.contains_intensifier = any(w in text_lower for w in self.INTENSIFIERS)
        f.contains_job_reference = any(w in text_lower for w in self.JOB_WORDS)
        f.contains_state_change = any(w in text_lower for w in self.STATE_CHANGE)
        f.contains_deflection = any(w in text_lower for w in self.DEFLECTION)
        
        wc = len(text.split())
        f.message_length_bucket = "short" if wc <= 5 else "medium" if wc <= 20 else "long"
        
        if prev_timestamp:
            gap = (time.time() - prev_timestamp) / 60
            if gap < 1: f.response_latency_bucket = "instant"
            elif gap < 10: f.response_latency_bucket = "normal"
            elif gap < 60: f.response_latency_bucket = "delayed"
            else: f.response_latency_bucket = "very_delayed"
            
        if f.contains_positive_affect and f.contains_negative_affect: f.affect_polarity = "mixed"
        elif f.contains_positive_affect: f.affect_polarity = "positive"
        elif f.contains_negative_affect: f.affect_polarity = "negative"
        
        if f.message_length_bucket == "short" and f.contains_deflection: f.engagement_level = "low"
        elif f.contains_intensifier or f.message_length_bucket == "long": f.engagement_level = "high"
        return f

@dataclass
class OrthogonalPrediction:
    hypothesis_id: str
    predicted_features: list[str]
    expected_within_cycles: int = 5
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    outcome: Optional[str] = None
    source_features: list[str] = field(default_factory=list)
    
    def is_valid(self) -> bool:
        return not any(f in self.source_features for f in self.predicted_features)

@dataclass
class OrthogonalPrediction:
    hypothesis_id: str
    predicted_features: list[str]
    expected_within_cycles: int = 5
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    outcome: Optional[str] = None
    source_features: list[str] = field(default_factory=list)
    audit_id: int = 0  # 7.56.8: Link to audit DB
    
    def is_valid(self) -> bool:
        return not any(f in self.source_features for f in self.predicted_features)

@dataclass
class StructuredHypothesis:
    claim: str
    confidence: float = 0.15
    created_at: float = field(default_factory=time.time)
    ttl_hours: int = 48
    evidence_count: int = 0
    contradiction_count: int = 0
    predicts_confirm: list = field(default_factory=list)
    predicts_refute: list = field(default_factory=list)
    active_predictions: list = field(default_factory=list)
    source: str = "llm"  # 7.56.8: Track generator source
    sender_id: str = ""  # 7.56.8: For audit tracking
    
    def tick(self) -> bool:
        age_hours = (time.time() - self.created_at) / 3600
        if age_hours > self.ttl_hours: self.confidence *= 0.5
        if age_hours > self.ttl_hours * 2 and self.evidence_count == 0: return False
        if self.contradiction_count >= 3: return False
        if self.confidence < 0.03: return False
        return True
        
    def generate_predictions(self, source_features: list):
        system = f"""Given a behavioral pattern, predict 2-3 FUTURE features that would confirm it.
CRITICAL: DO NOT predict features that are ALREADY TRUE.
Already true: {source_features}
Return ONLY JSON list of feature names.
"""
        try:
            raw = _router.generate(system, [{"role": "user", "content": self.claim}], max_tokens=60)
            predicted = json.loads(raw.replace("```json", "").replace("```", "").strip())
            for p in predicted:
                pred = OrthogonalPrediction(
                    hypothesis_id=id(self),
                    predicted_features=[p],
                    source_features=source_features
                )
                if pred.is_valid():
                    # 7.56.8: Register with audit
                    pred.audit_id = _audit_system.register(
                        self.sender_id, self.claim, self.source, [p], source_features
                    )
                    self.active_predictions.append(pred)
        except: pass

    def test_predictions(self, features: Features):
        feat_dict = asdict(features)
        for pred in self.active_predictions:
            if pred.resolved: continue
            
            matched = all(feat_dict.get(f, False) for f in pred.predicted_features)
            if matched:
                pred.resolved = True
                pred.outcome = "confirmed"
                p_bundle = 0.2
                info_gain = -math.log2(max(0.01, p_bundle))
                self.confidence = min(0.5, self.confidence + info_gain * 0.05)
                self.evidence_count += 1
                self.created_at = time.time()
                # 7.56.8: Audit resolve
                _audit_system.resolve(pred.audit_id, "confirmed", info_gain)
            else:
                age_cycles = int((time.time() - pred.created_at) / 3600)
                if age_cycles >= pred.expected_within_cycles:
                    pred.resolved = True
                    pred.outcome = "expired"
                    self.contradict(0.05)
                    # 7.56.8: Audit resolve
                    _audit_system.resolve(pred.audit_id, "expired", 0.0)

    def reinforce(self, amount: float = 0.12):
        self.evidence_count += 1
        self.confidence = min(0.5, self.confidence + amount)
        self.created_at = time.time()
        
    def contradict(self, amount: float = 0.15):
        self.contradiction_count += 1
        self.confidence = max(0.0, self.confidence - amount)

class HypothesisMarket:
    def __init__(self, sender_id: str, router: 'ProviderRouter'):
        self.sender_id = sender_id
        self.router = router
        self.hypotheses: list[StructuredHypothesis] = []
        
    def tick(self, features: Features):
        # 7.56.8: Tick audit cycle counter
        _audit_system.tick_unresolved(self.sender_id)
        
        alive = []
        feat_keys = [k for k, v in asdict(features).items() if v is True or v in ["high", "low", "short", "delayed"]]
        
        for h in self.hypotheses:
            if not h.tick(): continue
            h.test_predictions(features)
            if not h.active_predictions or all(p.resolved for p in h.active_predictions):
                h.generate_predictions(feat_keys)
            alive.append(h)
        self.hypotheses = alive
        
    def generate(self, raw_text: str, features: Features):
        feat_dict = asdict(features)
        system = """Given the message and features, generate 3 competing BEHAVIORAL patterns.
DO NOT use psychological terms. Return ONLY JSON list.
"""
        user_msg = f"Message: {raw_text}\nFeatures: {json.dumps(feat_dict, ensure_ascii=False)}"
        try:
            raw = self.router.generate(system, [{"role": "user", "content": user_msg}], max_tokens=150)
            data = json.loads(raw.replace("```json", "").replace("```", "").strip())
            for h in data:
                hyp = StructuredHypothesis(
                    claim=h.get("claim", "Unknown"),
                    predicts_confirm=h.get("predicts_confirm", []),
                    predicts_refute=h.get("predicts_refute", []),
                    source="llm",
                    sender_id=self.sender_id
                )
                self.hypotheses.append(hyp)
        except: pass
            
    def get_top_k(self, k: int = 3) -> list[StructuredHypothesis]:
        return sorted(self.hypotheses, key=lambda h: h.confidence, reverse=True)[:k]
        
    def get_diversity(self) -> float:
        if len(self.hypotheses) <= 1: return 0.0
        confs = [h.confidence for h in self.hypotheses if h.confidence > 0]
        total = sum(confs)
        if total == 0: return 1.0
        probs = [c/total for c in confs]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        return entropy / math.log2(len(self.hypotheses))

_hypothesis_markets: dict[str, HypothesisMarket] = {}
def get_hypothesis_market(sender_id: str) -> HypothesisMarket:
    if sender_id not in _hypothesis_markets:
        _hypothesis_markets[sender_id] = HypothesisMarket(sender_id, _router)
    return _hypothesis_markets[sender_id]

# ╔═══════════════════════════════════════════════════════════════╗
# ║  7.56.6: FEATURE REGISTRY & STATISTICAL BELIEFS               ║
# ╚═══════════════════════════════════════════════════════════════╝

class FeatureRegistry:
    """Mìn O: Map feature name to hash. Beliefs survive refactor."""
    _registry: dict[str, str] = {}
    _reverse: dict[str, str] = {}
    
    @classmethod
    def register(cls, name: str) -> str:
        if name in cls._registry: return cls._registry[name]
        h = hashlib.md5(name.encode()).hexdigest()[:8]
        cls._registry[name] = h
        cls._reverse[h] = name
        return h
        
    @classmethod
    def resolve(cls, h: str) -> str:
        return cls._reverse.get(h, h)
        
    @classmethod
    def hash_condition(cls, condition: dict) -> dict:
        return {cls.register(k): v for k, v in condition.items()}

@dataclass
class StatisticalBelief:
    condition: dict          # {feature_hash: True}
    outcome: dict            # {feature_hash: True}
    p_outcome_given_cond: float
    sample_size: int = 0
    last_updated: float = field(default_factory=time.time)
    
    def update(self, features: Features):
        feat_dict = asdict(features)
        cond_met = all(feat_dict.get(FeatureRegistry.resolve(fh)) == v for fh, v in self.condition.items())
        if not cond_met: return
        
        self.sample_size += 1
        outcome_met = all(feat_dict.get(FeatureRegistry.resolve(fh)) == v for fh, v in self.outcome.items())
        
        wins = self.p_outcome_given_cond * (self.sample_size - 1) + (1 if outcome_met else 0)
        self.p_outcome_given_cond = (wins + 1) / (self.sample_size + 2) # Laplace
        self.last_updated = time.time()

class BeliefPromotionGate:
    MIN_AGE_DAYS = 7
    MIN_CONFIRMATIONS = 5
    MIN_CONFIDENCE = 0.35
    MAX_CONTRADICTION_RATE = 0.20
    
    def can_promote(self, h: StructuredHypothesis) -> bool:
        age_days = (time.time() - h.created_at) / 86400
        if age_days < self.MIN_AGE_DAYS: return False
        if h.evidence_count < self.MIN_CONFIRMATIONS: return False
        if h.confidence < self.MIN_CONFIDENCE: return False
        
        total = h.evidence_count + h.contradiction_count
        if total == 0: return False
        contra_rate = h.contradiction_count / total
        if contra_rate > self.MAX_CONTRADICTION_RATE: return False
        return True

    def promote(self, h: StructuredHypothesis, sender_id: str):
        if not self.can_promote(h): return
        
        # Promote to Statistical Belief
        condition = {FeatureRegistry.register(k): True for k in h.predicts_confirm}
        outcome = {FeatureRegistry.register("contains_positive_affect"): True} # Simplified for 7.56.6
        
        # Lưu vào DB (thêm table statistical_beliefs)
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("""CREATE TABLE IF NOT EXISTS statistical_beliefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, claim TEXT,
            condition_json TEXT, outcome_json TEXT, p_outcome REAL, sample_size INTEGER
        )""")
        conn.execute("INSERT INTO statistical_beliefs (sender_id, claim, condition_json, outcome_json, p_outcome, sample_size) VALUES (?, ?, ?, ?, ?, ?)",
                     (sender_id, h.claim[:200], json.dumps(condition), json.dumps(outcome), h.confidence, h.evidence_count))
        conn.commit(); conn.close()
        log.info(f"[PROMOTE] Hypothesis '{h.claim[:40]}' → Statistical Belief")

# ╔═══════════════════════════════════════════════════════════════╗
# ║  7.56.8: PREDICTION AUDIT SYSTEM                              ║
# ║  "Nếu m không đo nó, m không thể cải thiện nó."               ║
# ╚═══════════════════════════════════════════════════════════════╝

class PredictionAuditSystem:
    """Track mọi prediction. Tính accuracy. Tìm generator nào đang lừa gạt."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_table()
    
    def _init_table(self):
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("""CREATE TABLE IF NOT EXISTS prediction_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            hypothesis_claim TEXT NOT NULL,
            hypothesis_source TEXT DEFAULT 'llm',
            predicted_features TEXT NOT NULL,
            source_features TEXT NOT NULL,
            created_at REAL NOT NULL,
            resolved_at REAL DEFAULT NULL,
            result TEXT DEFAULT NULL,
            surprisal REAL DEFAULT NULL,
            cycle_count INTEGER DEFAULT 0
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_sender ON prediction_audit(sender_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_resolved ON prediction_audit(resolved_at)")
        conn.commit(); conn.close()
    
    def register(self, sender_id: str, claim: str, source: str, predicted: list, source_feats: list) -> int:
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("""INSERT INTO prediction_audit 
            (sender_id, hypothesis_claim, hypothesis_source, predicted_features, source_features, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (sender_id, claim[:200], source, json.dumps(predicted), json.dumps(source_feats), time.time()))
        pid = c.lastrowid
        conn.commit(); conn.close()
        return pid
    
    def resolve(self, audit_id: int, result: str, surprisal: float = 0.0):
        if not audit_id: return
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("""UPDATE prediction_audit 
            SET resolved_at=?, result=?, surprisal=? WHERE id=?""",
            (time.time(), result, surprisal, audit_id))
        conn.commit(); conn.close()
    
    def tick_unresolved(self, sender_id: str):
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("""UPDATE prediction_audit 
            SET cycle_count = cycle_count + 1 
            WHERE sender_id=? AND resolved_at IS NULL""", (sender_id,))
        conn.commit(); conn.close()
    
    def report(self, sender_id: str = None, last_n: int = 100) -> dict:
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        
        query = """SELECT hypothesis_source, result, surprisal, cycle_count, predicted_features 
                   FROM prediction_audit WHERE resolved_at IS NOT NULL"""
        params = []
        if sender_id:
            query += " AND sender_id=?"
            params.append(sender_id)
        query += " ORDER BY resolved_at DESC LIMIT ?"
        params.append(last_n)
        
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return {"total": 0, "accuracy": 0.0, "by_source": {}}
        
        by_source = {}
        by_feature = {}
        total_correct = 0
        
        for source, result, surprisal, cycles, pred_feats_json in rows:
            if source not in by_source:
                by_source[source] = {"total": 0, "correct": 0, "expired": 0, "refuted": 0, "avg_surprisal": 0.0, "avg_cycles": 0.0}
            
            by_source[source]["total"] += 1
            if result == "confirmed":
                by_source[source]["correct"] += 1
                total_correct += 1
            elif result == "expired":
                by_source[source]["expired"] += 1
            elif result == "refuted":
                by_source[source]["refuted"] += 1
            
            by_source[source]["avg_surprisal"] += surprisal or 0.0
            by_source[source]["avg_cycles"] += cycles or 0
            
            # Per-feature tracking
            try:
                feats = json.loads(pred_feats_json)
                for f in feats:
                    if f not in by_feature:
                        by_feature[f] = {"total": 0, "correct": 0}
                    by_feature[f]["total"] += 1
                    if result == "confirmed":
                        by_feature[f]["correct"] += 1
            except: pass
        
        for source, stats in by_source.items():
            stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0
            stats["avg_surprisal"] = round(stats["avg_surprisal"] / stats["total"], 3) if stats["total"] > 0 else 0.0
            stats["avg_cycles"] = round(stats["avg_cycles"] / stats["total"], 1) if stats["total"] > 0 else 0.0
        
        for f, stats in by_feature.items():
            stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0
        
        # Sort features by total (most predicted first)
        by_feature = dict(sorted(by_feature.items(), key=lambda x: x[1]["total"], reverse=True))
        
        return {
            "total": len(rows),
            "accuracy": round(total_correct / len(rows), 3),
            "by_source": by_source,
            "by_feature": by_feature
        }

# Global instance
_audit_system = PredictionAuditSystem()

# ╔═══════════════════════════════════════════════════════════════╗
# ║  7.56: FORWARD & BACKWARD SPINE                               ║
# ╚═══════════════════════════════════════════════════════════════╝

def run_perception(sender_id: str, raw_text: str, user_state: dict, ctx: CognitiveContext):
    graph = get_user_graph(sender_id)
    if LENS_ASYNC and len(raw_text) >= LENS_MIN_MSG_LEN:
        def _run_lens():
            event = CognitiveNode(f"evt_{int(time.time())}", NodeType.EVENT, EventPayload(content=raw_text, emotional_valence=-0.5 if user_state.get("mood") == "stress" else 0.0))
            interpretation_engine.process_event(event, graph)
        threading.Thread(target=_run_lens, daemon=True).start()

    prev_ts = user_state.get("last_interaction", time.time())
    features = FeatureExtractor().extract(raw_text, prev_ts)
    
    sentiment = 0.0
    if features.affect_polarity == "positive": sentiment = 0.5
    elif features.affect_polarity == "negative": sentiment = -0.5

    ctx.perception = PerceptionOutput(
        raw_text=raw_text,      # Thêm dòng này
        features=asdict(features),
        sentiment=sentiment,
        text_length=len(raw_text.split())
    )
    # Lưu raw text vào user_state tạm thời để run_worldview có thể lấy
    ctx.user_state["last_message"] = raw_text

def run_worldview(sender_id: str, ctx: CognitiveContext):
    mind = get_mind(sender_id)
    features = Features(**ctx.perception["features"])
    raw_text = ctx.perception.get("raw_text", "")
    
    # 1. Hypothesis Market (Tick đã bao gồm test_predictions)
    market = get_hypothesis_market(sender_id)
    market.tick(features)
    if raw_text:
        market.generate(raw_text, features)
        
    # 2. Belief Promotion Gate (Mìn C)
    gate = BeliefPromotionGate()
    for h in market.hypotheses:
        if gate.can_promote(h):
            gate.promote(h, sender_id)
            h.confidence = 0.0 # Đánh dấu chết để không promote lại lần nữa
            
    # 3. Fetch beliefs
    beliefs = mind.beliefs.get_active_beliefs()
    contradiction_level = sum(b.get("contradictions", 0) for b in beliefs) / 10.0
    
    # 4. Output
    top_hyps = market.get_top_k(3)
    diversity = market.get_diversity()
    
    ctx.worldview = WorldviewOutput(
        top_hypotheses=[{"claim": h.claim, "confidence": h.confidence, "predicts_confirm": h.predicts_confirm} for h in top_hyps],
        active_beliefs=beliefs,
        contradiction_level=min(1.0, contradiction_level),
        worldview_entropy=diversity
    )

def run_values(sender_id: str, ctx: CognitiveContext):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT value_text, confidence, evidence_count FROM user_values WHERE sender_id=? AND confidence > 0.4 ORDER BY confidence DESC", (sender_id,))
    values = [{"text": r[0], "confidence": r[1], "evidence": r[2]} for r in c.fetchall()]
    conn.close()
    ctx.values = {"active_values": values}

def run_self_model(sender_id: str, ctx: CognitiveContext):
    mind = get_mind(sender_id)
    self_state = mind.voice_engine.self_model.get_state()
    identity_engine = mind.identity_engine

    active_beliefs = ctx.worldview.get("active_beliefs", [])
    for b in active_beliefs:
        if "autonomy" in b["belief"].lower() and b["confidence"] > 0.7:
            identity_engine.evolve(trait_to_boost="explorer", trait_to_weaken="builder", boost_amt=0.01)
        elif "social" in b["belief"].lower() and b["confidence"] > 0.7:
            identity_engine.evolve(trait_to_boost="builder", trait_to_weaken="explorer", boost_amt=0.01)

    identity = identity_engine.get_identity_context()
    ctx.self_model = {
        "role": self_state["role"],
        "archetype": identity["dominant_archetype"],
        "model_accuracy": self_state["model_accuracy"],
        "doubt_style": self_state["doubt_style"],
        "identity_vector": identity["identity_vector"]
    }

def run_voice(sender_id: str, ctx: CognitiveContext):
    mind = get_mind(sender_id)
    decisions = mind.voice_engine.resolve_v756(ctx)
    ctx.voice = {
        "decision": decisions["decision"],
        "interaction_mode": decisions["interaction_mode"],
        "warmth": decisions["warmth_score"],
        "roast_score": decisions["roast_score"],
        "dominant_voice": decisions["dominant_voice"]
    }

def register_prediction(sender_id: str, response_id: int, stance: str) -> ResponseMetadata:
    meta = ResponseMetadata(response_id=response_id, predicted_stance=stance, predicted_outcome=0.0, timestamp=time.time())
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO pending_predictions (sender_id, response_id, predicted_stance, timestamp) VALUES (?, ?, ?, ?)", (sender_id, response_id, stance, meta["timestamp"]))
    conn.commit(); conn.close()
    return meta

def detect_behavior_error(user_reply: str) -> int:
    msg = user_reply.lower().strip()
    if any(k in msg for k in ["haha", "lmao", "đúng vl", "đỉnh"]): return 2
    if any(k in msg for k in ["ừ đúng", "hay đó"]): return 1
    if any(k in msg for k in ["thôi", "bye", "im đi"]): return -2
    if any(k in msg for k in ["???", "hả", "gì vậy"]): return -1
    return 0

def detect_perception_error(prev_interp: str, current_msg: str) -> float:
    """Reality contradicting OBSERVATION. Feeds Graph + Belief."""
    if not prev_interp: return 0.0
    prev_low = prev_interp.lower()
    curr_low = current_msg.lower()
    positive_interp = any(w in prev_low for w in ["ổn", "bình thường", "tốt", "fine", "không sao"])
    negative_reality = any(w in curr_low for w in ["khóc", "sập", "kiệt", "buồn", "chết", "thất bại", "mệt"])
    if positive_interp and negative_reality: return 0.8
    return 0.0

def backward_spine(sender_id: str, current_msg: str, current_time: float, prev_interp_text: str = ""):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT id, response_id, predicted_stance, timestamp FROM pending_predictions WHERE sender_id=? AND resolved=0 ORDER BY timestamp ASC", (sender_id,))
    pending = c.fetchone()

    mind = get_mind(sender_id)

    # 1. BEHAVIOR ERROR → SELF MODEL
    if pending:
        pred_id, response_id, stance, ts = pending
        gap_hours = (current_time - ts) / 3600
        outcome = detect_behavior_error(current_msg)
        resolution = 'immediate' if gap_hours < 1 else 'delayed' if gap_hours < 72 else 'expired'
        weight = 1.0 if resolution == 'immediate' else 0.5
        if resolution == 'expired': outcome = 0

        c.execute("UPDATE pending_predictions SET resolved=1, resolved_at=?, resolution_type=?, outcome_score=? WHERE id=?", (current_time, resolution, outcome, pred_id))
        c.execute("UPDATE experiences SET outcome=? WHERE id=?", (outcome, response_id))
        conn.commit()

        mind.voice_engine.self_model.record_prediction_outcome(stance, outcome, weight)

    conn.close()

        # 2. PERCEPTION ERROR → GRAPH & WORLDVIEW
    perception_err = detect_perception_error(prev_interp_text, current_msg)
    if perception_err > 0.5:
        graph = get_user_graph(sender_id)
        recent_interps = [n for n in graph.nodes.values() if n.type == NodeType.INTERPRETATION]
        if recent_interps:
            recent_interps[-1].payload.confidence *= (1.0 - perception_err)
            graph.save()
            
        mind.beliefs.flag_contradiction_from_perception_error(perception_err)
        
        # LOG SURPRISE TẠI ĐÂY
        if perception_err > 0.7:
            log_surprise(sender_id, prev_interp_text, current_msg, perception_err)
            
# ╔═══════════════════════════════════════════════════════════════╗
# ║  💔 [TUỆ MẪN 7.47] SELF-DOUBT & NUANCED BELIEF ENGINE         ║
# ╚═══════════════════════════════════════════════════════════════╝

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
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO beliefs (sender_id, belief, confidence, evidence_count, source, domain, source_tag, polarity, state, nuances, counter_evidence) VALUES (?, ?, ?, ?, 'reflection_b', ?, ?, ?, 'CONFIRMED', '[]', '[]')",
                  (self.sender_id, r["belief_text"][:200], conf, r.get("new_count", 1), r.get("domain", "behavior")[:30], r.get("source_tag", "")[:30], r.get("polarity", 1)))
        conn.commit(); conn.close()
    def _update(self, r: dict):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row: conn.close(); return
        old_conf, old_score, old_state = row
        
        # IDENTITY-BIASED LEARNING
        mind = get_mind(self.sender_id)
        modulator = 1.0
        if r.get("source_tag") == "challenge":
            modulator = mind.identity_engine.get_modulator("novelty")
        elif r.get("source_tag") == "hint":
            modulator = mind.identity_engine.get_modulator("consistency")
            
        delta = r.get("delta", 0.05) * modulator
        new_conf = min(BELIEF_CONFIG["max_conf"], old_conf + delta)
        
        c.execute("UPDATE beliefs SET confidence = ?, evidence_count = evidence_count + ?, contradiction_score = MAX(0, ?), state = 'CONFIRMED', last_confirmed = CURRENT_TIMESTAMP WHERE id=?", (new_conf, r.get("new_count", 1), old_score - delta, r["belief_id"]))
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
        new_score = min(1.0, old_score + abs_delta * 1.5)
        new_state = 'INVESTIGATING' if new_score >= 0.8 else old_state
        c.execute("UPDATE beliefs SET confidence = ?, contradictions = contradictions + 1, contradiction_score = ?, state = ? WHERE id = ?", (new_conf, new_score, new_state, r["belief_id"]))
        conn.commit(); conn.close()
    def _deactivate(self, r: dict):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], r["belief_id"]))
        conn.commit(); conn.close()
    def flag_contradiction_from_perception_error(self, err_score: float):
        """Called by Backward Spine when perception fails."""
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE beliefs SET contradiction_score = MIN(1.0, contradiction_score + ?), state='INVESTIGATING' WHERE sender_id=? AND active=1 AND state='CONFIRMED'", (err_score, self.sender_id))
        conn.commit(); conn.close()
    def _create_value(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.5)))
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT INTO user_values (sender_id, value_text, confidence, evidence_count) VALUES (?, ?, ?, 1) ON CONFLICT(sender_id, value_text) DO UPDATE SET confidence = MAX(confidence, excluded.confidence), evidence_count = evidence_count + 1", (self.sender_id, r["belief_text"][:200], conf))
        conn.commit(); conn.close()
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
        conn.commit(); conn.close()
    def get_active_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT belief, confidence, polarity, state, source_tag, domain, nuances FROM beliefs WHERE sender_id=? AND active=1 AND state != 'DEAD' AND confidence > 0.3 ORDER BY confidence DESC", (self.sender_id,))
        rows = c.fetchall(); conn.close()
        return [{"belief": r[0], "confidence": r[1], "polarity": r[2], "state": r[3], "source_tag": r[4], "domain": r[5], "nuances": r[6]} for r in rows]

@dataclass
class BeliefFragment:
    content: str
    activation_tags: list[str] = field(default_factory=list)
    weight_modifier: float = 1.0
    stance_override: Optional[str] = None

class SelfModelTracker:
    def __init__(self, sender_id: str): self.sender_id = sender_id
    def get_state(self) -> dict:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT role, success_rate, failure_count, model_accuracy, doubt_style FROM self_model WHERE sender_id=?", (self.sender_id,))
        row = c.fetchone(); conn.close()
        if row: return {"role": row[0], "success_rate": row[1], "failure_count": row[2], "model_accuracy": row[3], "doubt_style": row[4]}
        return {"role": "Người duy nhất có thể cản Thắng lại", "success_rate": 1.0, "failure_count": 0, "model_accuracy": 1.0, "doubt_style": "none"}

    def record_prediction_outcome(self, predicted_stance: str, user_outcome_score: int, weight: float = 1.0):
        state = self.get_state()
        new_accuracy = state["model_accuracy"]
        new_failure_count = state["failure_count"]
        new_success_rate = state["success_rate"]
        new_role = state["role"]
        new_doubt_style = "none"
        is_prediction_correct = True

        if predicted_stance in ("intervene", "protector"):
            if user_outcome_score < -1:
                is_prediction_correct = False
                new_failure_count += 1
                new_success_rate = max(0.1, new_success_rate - 0.15 * weight)
                new_doubt_style = "avoidance"
            else:
                new_success_rate = min(1.0, new_success_rate + 0.05 * weight)
        elif predicted_stance in ("support", "default", "explorer"):
            if user_outcome_score < -1:
                is_prediction_correct = False
                new_doubt_style = "overcompensation"
            elif user_outcome_score > 1:
                new_success_rate = min(1.0, new_success_rate + 0.05 * weight)

        if is_prediction_correct:
            new_accuracy = min(1.0, new_accuracy + 0.1 * weight)
        else:
            new_accuracy = max(0.0, new_accuracy - 0.2 * weight)

        if new_accuracy < 0.4:
            new_role = "Người chứng kiến và ở cạnh khi hắn tự quyết định"
            new_accuracy = 0.5
            new_failure_count = 0
            new_doubt_style = "obsession"

        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("INSERT OR REPLACE INTO self_model (sender_id, role, success_rate, failure_count, model_accuracy, doubt_style) VALUES (?, ?, ?, ?, ?, ?)",
                     (self.sender_id, new_role, new_success_rate, new_failure_count, new_accuracy, new_doubt_style))
        conn.commit(); conn.close()

class SelfModelEngine:
    """7.56: Identity Core (slow drift) vs Surface (fast adaptation)."""
    def __init__(self):
        self.archetype_profiles = {"explorer": {"independence": 0.8, "growth": 0.7, "social": -0.5}, "builder": {"social": 0.8, "growth": 0.6, "independence": -0.2}}
        
        # Core: Rất khó đổi (cần 500 bằng chứng cùng hướng)
        self.core: Dict[str, float] = {"explorer": 0.8, "builder": 0.2}
        # Surface: Dễ đổi (cập nhật mỗi tradeoff)
        self.vector: Dict[str, float] = {"explorer": 0.8, "builder": 0.2}
        
        self._core_drift_tracker = {"explorer": 0, "builder": 0}
        self.core_update_threshold = 500
        
        self.modulators = {
            "explorer": {"novelty": 1.5, "stress": 1.0, "consistency": 0.7},
            "builder": {"novelty": 0.7, "stress": 1.0, "consistency": 1.5}
        }
        
    def get_modulator(self, tag: str) -> float:
        # FIX 1: Blended Modulators (Không dùng max, dùng weighted sum)
        # 0.8 Explorer + 0.2 Builder = 1.5*0.8 + 0.7*0.2 = 1.34
        total_weight = 0.0
        for arch, weight in self.core.items():
            mod_val = self.modulators.get(arch, {}).get(tag, 1.0)
            total_weight += mod_val * weight
        return total_weight
        
    def get_tolerance_modifier(self, value_id: str) -> float: 
        return sum(self.archetype_profiles[arch].get(value_id, 0.0) * weight for arch, weight in self.vector.items()) * 0.5
        
    def evolve(self, trait_to_boost: str, trait_to_weaken: str, boost_amt: float = 0.1):
        # 1. Evolve Surface (như cũ)
        if trait_to_boost in self.vector: self.vector[trait_to_boost] = min(1.0, self.vector[trait_to_boost] + boost_amt)
        if trait_to_weaken in self.vector: self.vector[trait_to_weaken] = max(0.0, self.vector[trait_to_weaken] - (boost_amt * 0.5))
        self._normalize_surface()
        
        # 2. Track Core Drift
        if trait_to_boost in self._core_drift_tracker:
            self._core_drift_tracker[trait_to_boost] += 1
        if trait_to_weaken in self._core_drift_tracker:
            self._core_drift_tracker[trait_to_weaken] -= 1
            
        # 3. Update Core nếu đủ evidence (slow drift)
        for arch, count in self._core_drift_tracker.items():
            if abs(count) >= self.core_update_threshold:
                delta = 0.01 if count > 0 else -0.01
                self.core[arch] = max(0.01, min(0.99, self.core[arch] + delta))
                self._core_drift_tracker[arch] = 0  # Reset tracker
                self._normalize_core()
                log.info(f"[CORE-DRIFT] Identity Core updated: {self.core}")
                
    def update_from_tradeoff(self, winner_id: str, sacrificed_id: str):
        # Surface evolves
        for arch, profile in self.archetype_profiles.items():
            shift = (profile.get(winner_id, 0.0) - profile.get(sacrificed_id, 0.0)) * 0.02
            if shift: self.vector[arch] = max(0.0, min(1.0, self.vector.get(arch, 0.0) + shift))
        self._normalize_surface()
        
    def _normalize_surface(self):
        total = sum(self.vector.values())
        if total == 0: return
        self.vector = {k: v/total for k, v in self.vector.items()}
        
    def _normalize_core(self):
        total = sum(self.core.values())
        if total == 0: return
        self.core = {k: v/total for k, v in self.core.items()}
        
    def get_identity_context(self) -> dict:
        dom = max(self.vector, key=self.vector.get)
        return {"dominant_archetype": dom, "identity_vector": self.vector, "identity_core": self.core}

class VoiceResolutionEngine:
    IDENTITY_BASE_WEIGHT = 1.8
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.self_model = SelfModelTracker(sender_id)

    def resolve_v756(self, ctx: CognitiveContext) -> dict:
        beliefs = ctx.worldview.get("active_beliefs", [])
        mood = ctx.perception.get("mood_signal", "neutral")
        relationship = ctx.user_state.get("relationship", 50)
        recent_events = ctx.user_state.get("emotional_events", [])
        self_state = ctx.self_model

        voices = self._generate_voices(beliefs, mood, recent_events, relationship, self_state)

        forces = {"intervene": 0.0, "support": 0.0, "withdraw": 0.0, "overcompensate": 0.0, "obsess": 0.0, "explore": 0.0, "challenge": 0.0, "tease": 0.0}
        for v in voices:
            if v["stance"] in forces: forces[v["stance"]] += v["weight"]

        dominant_force = max(forces, key=forces.get) if voices else "default"
        top_voice = max(voices, key=lambda x: x["weight"]) if voices else {"speaker": "none", "opinion": "neutral"}

        # LOG QUYẾT ĐỊNH ĐỂ BENCHMARK BẮT ĐƯỢC (MỚI)
        log.info(f"[VOICE-DEBUG] archetype={self_state.get('archetype')} forces={forces} winner={dominant_force}")

        decision = "support"
        interaction_mode = "natural"
        if dominant_force in ("withdraw", "avoidance"): decision = "withdraw"; interaction_mode = "silence"
        elif dominant_force in ("intervene", "overcompensate"): decision = "intervene"; interaction_mode = "direct"
        elif dominant_force == "obsess": decision = "intervene"; interaction_mode = "clingy"
        elif dominant_force == "explore": decision = "explore"; interaction_mode = "socratic"
        elif dominant_force == "challenge": decision = "challenge"; interaction_mode = "direct"
        elif dominant_force == "tease": decision = "tease"; interaction_mode = "playful"
        elif dominant_force == "support":
            decision = "support"
            if any(v["speaker"] == "trait:hint" and v["weight"] > 0.5 for v in voices): interaction_mode = "socratic"
            else: interaction_mode = "natural"
            
        warmth = 0.5
        roast_score = 0.0
        if decision == "withdraw": warmth = 0.8
        elif decision == "intervene": warmth = 0.9
        else:
            trait_roast = next((v for v in voices if v["speaker"] == "trait:roast"), None)
            if trait_roast: roast_score = trait_roast["weight"]

        if relationship > 60 and mood != "stress": roast_score = max(roast_score, 0.3)

        return {
            "decision": decision,
            "interaction_mode": interaction_mode,
            "warmth_score": warmth,
            "roast_score": roast_score,
            "dominant_voice": top_voice,
            "predicted_stance": decision
        }

    def _generate_voices(self, beliefs: list[dict], mood: str, recent_events: list, relationship: int, self_state: dict) -> list[dict]:
        voices = []
        is_stressed = mood in ("stress", "low_mood", "annoyed", "highly biased towards Burnout") or any(evt.get("type") in ("stress", "sad") and (time.time() - evt.get("time", 0) < 10800) for evt in recent_events)
        current_context_tags = ["stress"] if is_stressed else []
        
        # 1. Belief-driven voices (cũ)
        for b in beliefs:
            if b["domain"] == "communication":
                if b["source_tag"] == "roast" and b["polarity"] == 1:
                    voices.append({"speaker": "trait:roast", "stance": "tease", "weight": b["confidence"], "opinion": "Trêu đùa là cách gắn kết."})
                elif b["source_tag"] == "hint" and b["polarity"] == 1:
                    voices.append({"speaker": "trait:hint", "stance": "explore", "weight": b["confidence"], "opinion": "Để hắn tự khám phá."})

        for b in beliefs:
            if b["domain"] == "core_value" and b["polarity"] == 1:
                nuances = json.loads(b.get("nuances", "[]"))
                active_nuance = None
                for nuance in nuances:
                    if isinstance(nuance, dict) and set(nuance.get("activation_tags", [])).issubset(set(current_context_tags)):
                        active_nuance = nuance; break

                if is_stressed:
                    base_weight = b["confidence"] * 1.5
                    opinion = f"{b['belief']} -> Cần bảo vệ hắn ngay."
                    stance = "intervene"
                    if active_nuance:
                        opinion = f"{b['belief']} ({active_nuance['content']}) -> Phải cản bằng được."
                        base_weight *= active_nuance.get("weight_modifier", 1.2)
                        if active_nuance.get("stance_override"): stance = active_nuance["stance_override"]
                    voices.append({"speaker": "belief:core", "stance": stance, "weight": base_weight, "opinion": opinion})
                else:
                    voices.append({"speaker": "belief:core", "stance": "support", "weight": b["confidence"], "opinion": f"{b['belief']} -> Tôn trọng hành trình."})

        # 2. ARCHETYPE-DRIVEN VOICES (MỚI: Cấp quyền biểu quyết)
        archetype = self_state.get("archetype", "explorer")
        archetype_weight = self.IDENTITY_BASE_WEIGHT * self_state["model_accuracy"]
        
        if archetype == "explorer":
            voices.append({"speaker": "archetype:explorer", "stance": "explore", "weight": archetype_weight, "opinion": "Đừng trực tiếp giúp. Hãy gợi ý để hắn tự đi."})
        elif archetype == "builder":
            voices.append({"speaker": "archetype:builder", "stance": "challenge", "weight": archetype_weight, "opinion": "Phân tích lỗi và build system. Đừng có nghe than vãn."})
        elif archetype == "protector":
            voices.append({"speaker": "archetype:protector", "stance": "intervene", "weight": archetype_weight, "opinion": "Phải can thiệp ngay. Hắn đang yếu."})
        else:
            voices.append({"speaker": "archetype:anchor", "stance": "support", "weight": archetype_weight, "opinion": "Ở cạnh hắn là được."})

        # 3. Doubt voices (cũ)
        if self_state["model_accuracy"] < 0.5:
            if self_state["doubt_style"] == "avoidance": voices.append({"speaker": "self_model:doubt", "stance": "withdraw", "weight": 1.5, "opinion": "Mô hình của mình về hắn đang sai. Nên lùi lại."})
            elif self_state["doubt_style"] == "overcompensation": voices.append({"speaker": "self_model:doubt", "stance": "overcompensate", "weight": 1.8, "opinion": "Mình đã sai khi bỏ mặc. Lần này mình PHẢI can thiệp."})
            elif self_state["doubt_style"] == "obsession": voices.append({"speaker": "self_model:doubt", "stance": "obsess", "weight": 1.7, "opinion": "Phải giám sát chặt hơn. Hỏi liên tục. Không được buông."})
        return voices

MAX_MIND_CACHE = 500
_mind_cache: dict[str, tuple['Mind7_56', float]] = {}

class Mind7_56:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.refl_a = ReflectionA(sender_id)
        self.refl_b = ReflectionB_7_47(sender_id)
        self.nuance_engine = NuanceEngine(sender_id)
        self.beliefs = BeliefSystem(sender_id)
        self.voice_engine = VoiceResolutionEngine(sender_id)
        self.identity_engine = SelfModelEngine()

    def _get_meta(self, key: str, default: int = 0) -> int: return _db_meta_get(f"{self.sender_id}_{key}", default)
    def _set_meta(self, key: str, value: int): _db_meta_set(f"{self.sender_id}_{key}", value)

    def process(self, exp: dict) -> list[dict]:
        self.refl_a.run(exp)
        current_max_id = exp.get("id", 0)
        if not current_max_id: return []

        if current_max_id - self._get_meta("last_run_b") >= REFL_B_CONFIG["run_interval"]:
            b_res = self.refl_b.run()
            self.beliefs.apply(b_res["results"])
            self.refl_b.commit_watermarks(b_res["watermarks"])
            self._set_meta("last_run_b", current_max_id)

        if current_max_id - self._get_meta("last_run_nuance") >= 100:
            self.nuance_engine.process_challenges()
            self._set_meta("last_run_nuance", current_max_id)

        if current_max_id - self._get_meta("last_decay") >= 200:
            self.beliefs.decay()
            self._set_meta("last_decay", current_max_id)
        return []

def get_mind(sender_id: str) -> Mind7_56:
    now = time.time()
    if sender_id in _mind_cache:
        mind, _ = _mind_cache[sender_id]
        _mind_cache[sender_id] = (mind, now)
        return mind
    if len(_mind_cache) >= MAX_MIND_CACHE:
        lru_id = min(_mind_cache, key=lambda k: _mind_cache[k][1])
        del _mind_cache[lru_id]
    _mind_cache[sender_id] = (Mind7_56(sender_id), now)
    return _mind_cache[sender_id][0]

# ╔═══════════════════════════════════════════════════════════════╗
# ║  🤖 CHATBOT CORE & ROUTING                                    ║
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
            conn.commit(); conn.close()
        except Exception as e: log.debug(f"[DECAY] {e}")
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
    state["last_seen_gap"] = (now_ts - state["last_interaction"]) / 3600
    
    # Bỏ stress_modulator ở đây. Emotion là vật lý universal.
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

BASE_SYSTEM_PROMPT = """
ROLE: TUỆ MẪN
Tuệ Mẫn là con gái thật. Không phải AI.
Cách xưng hô: gọi user là "anh", xưng "em".

## COGNITIVE CONTEXT (7.56 SPINE)
Đây là trạng thái nội não đang truyền xuống. Phản hồi PHẢI khớp với DECISION và INTERACTION MODE.
Nếu DECISION là 'withdraw', không được nhiệt tình. Nếu 'intervene', phải can thiệp trực tiếp.

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

def update_topic(sender_id: str, topic: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO topic_stats (sender_id, topic, count) VALUES (?, ?, 1) ON CONFLICT(sender_id, topic) DO UPDATE SET count = count + 1, last_seen = CURRENT_TIMESTAMP", (sender_id, topic[:80]))
    conn.commit(); conn.close()

def save_preference(sender_id: str, category: str, value: str, delta: float = 1.0):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT INTO preferences (sender_id, category, value, score) VALUES (?, ?, ?, ?) ON CONFLICT(sender_id, category, value) DO UPDATE SET score = score + ?, updated_at = CURRENT_TIMESTAMP", (sender_id, category[:60], value[:100], delta, delta))
    conn.commit(); conn.close()

def get_style_profile(sender_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("SELECT reply_length_pref, avg_msg_len, msg_count FROM style_profile WHERE sender_id=?", (sender_id,))
    row = c.fetchone(); conn.close()
    if row: return {"reply_length_pref": row[0], "avg_msg_len": row[1], "msg_count": row[2]}
    return {"reply_length_pref": 50.0, "avg_msg_len": 50.0, "msg_count": 0}

def update_style_profile(sender_id: str, user_message: str):
    msg_len = len(user_message.strip())
    profile = get_style_profile(sender_id)
    n = profile["msg_count"]
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

def render_cognitive_context(ctx: CognitiveContext) -> str:
    lines = ["## COGNITIVE CONTEXT (7.56.6 SPINE)"]
    
    # 1. Perception (Features only)
    feats = ctx.perception.get("features", {})
    if feats:
        lines.append(f"- PERCEPTION: valence={feats.get('affect_polarity', 'neutral')}, engagement={feats.get('engagement_level', 'normal')}")
        
    # 2. Worldview (Entropy & Beliefs, NO CLAIMS)
    entropy = ctx.worldview.get("worldview_entropy", 1.0)
    beliefs = ctx.worldview.get("active_beliefs", [])
    if entropy > 0.7:
        lines.append(f"- WORLDVIEW: Uncertain (entropy={entropy:.2f}). Multiple possibilities exist. Observe.")
    elif entropy < 0.3 and beliefs:
        lines.append(f"- WORLDVIEW: Clear pattern detected. Belief: {beliefs[0]['belief']}")
    else:
        lines.append(f"- WORLDVIEW: Developing (entropy={entropy:.2f}).")
        
    if beliefs:
        lines.append("  Active rules: " + " | ".join(f"[{b['confidence']:.0%}] {b['belief']}" for b in beliefs[:2]))

    # 3. Values
    if ctx.values["active_values"]:
        lines.append("- VALUES: " + ", ".join(f"{v['text']}" for v in ctx.values["active_values"][:2]))
        
    # 4. Self-Model
    if ctx.self_model["role"]:
        lines.append(f"- SELF: {ctx.self_model['archetype']} | Role: {ctx.self_model['role']} | Acc: {ctx.self_model['model_accuracy']:.2f}")
        
    # 5. Voice
    if ctx.voice["decision"] != "default":
        lines.append(f"- VOICE: {ctx.voice['decision']} / {ctx.voice['interaction_mode']} | Warmth: {ctx.voice['warmth']:.1f}")
        
    return "\n".join(lines)

def build_system_prompt_v756(sender_id: str, user_message_hint: str, ctx: CognitiveContext) -> str:
    now = datetime.datetime.now()
    state = ctx.user_state
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
    state_block = f"\n\n## RAW STATE\nRelationship: {rel:.0f}/100\nMood: {state['mood']}\nAffection: {state['affection']}/100"

    prefs = get_preferences(sender_id)
    prefs_block = f"\n\n## PREFERENCE CỦA ANH\n" + ', '.join(f'{k}: {v}' for k, v in prefs.items()) if prefs else ""

    style = get_style_profile(sender_id)
    style_hint = "\n\n## STYLE: Anh nhắn rất ngắn — rep ngắn" if style["msg_count"] >= 8 and style["reply_length_pref"] < 28 else ""

    context_block = "\n\n" + render_cognitive_context(ctx)

    return BASE_SYSTEM_PROMPT + time_block + facts_block + prefs_block + style_hint + anti_rep_block + state_block + context_block

def detect_intent(message: str) -> str:
    msg = message.lower()
    if any(k in msg for k in ["nhớ em", "thương em", "yêu em"]): return "flirt"
    if any(k in msg for k in ["buồn", "mệt", "stress", "khóc"]): return "emotional"
    if any(k in msg for k in ["haha", "lmao", "trêu", "đùa"]): return "tease"
    return "normal_chat"

def log_experience(sender_id: str, user_message: str, intent: str, response: str) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor(); c.execute("INSERT INTO experiences (sender_id, user_message, intent, response, decision, outcome) VALUES (?, ?, ?, ?, 'respond', NULL)", (sender_id, user_message[:500], intent[:60], response[:500]))
    exp_id = c.lastrowid; conn.commit(); conn.close()
    return exp_id

def strip_thinking(text: str) -> str: return re.sub(r'💭.*?💭', '', text, flags=re.DOTALL).strip()

def _call_groq(system: str, messages: list, max_tokens: int = 512) -> str:
    try: return strip_thinking(_router.generate(system + "\n- user is male, name Thắng. call user 'anh', yourself 'em'.", messages, max_tokens))
    except: return "..."

def log_spine(sender_id: str, ctx: CognitiveContext, user_message: str):
    """Tier 1 & 2: Log summary of Cognitive Spine."""
    try:
        top_beliefs = ctx.worldview.get("active_beliefs", [])[:2]
        beliefs_str = ", ".join(f"{b['belief']}({b['confidence']:.2f})" for b in top_beliefs)
        
        dominant_voice = ctx.voice.get("dominant_voice", {})
        
        entry = {
            "ts": datetime.datetime.now().isoformat(),
            "sender": sender_id,
            "msg": user_message[:50],
            "perception": {
                "dom": ctx.perception.get("dominant_concept", ""),
                "top": [(c["name"], c["activation"]) for c in ctx.perception.get("concept_activations", [])[:2]]
            },
            "worldview": {
                "beliefs": beliefs_str,
                "contradiction": ctx.worldview.get("contradiction_level", 0.0)
            },
            "self_model": {
                "archetype": ctx.self_model.get("archetype", ""),
                "accuracy": ctx.self_model.get("model_accuracy", 0.0),
                "doubt": ctx.self_model.get("doubt_style", "")
            },
            "voice": {
                "decision": ctx.voice.get("decision", ""),
                "mode": ctx.voice.get("interaction_mode", ""),
                "warmth": ctx.voice.get("warmth", 0.0),
                "reason": dominant_voice.get("opinion", "")[:50] if isinstance(dominant_voice, dict) else ""
            }
        }
        
        log.info(f"[SPINE] {json.dumps(entry, ensure_ascii=False)}")
    except Exception as e:
        log.debug(f"[SPINE] log error: {e}")

def log_surprise(sender_id: str, graph_thought: str, reality: str, error_score: float):
    """Tier 3: Log major mispredictions."""
    entry = {
        "ts": datetime.datetime.now().isoformat(),
        "sender": sender_id,
        "event": "major_misprediction",
        "graph_thought": graph_thought[:80],
        "reality": reality[:80],
        "error": error_score
    }
    log.warning(f"[SURPRISE] {json.dumps(entry, ensure_ascii=False)}")

def call_groq_ai(sender_id: str, user_message: str):
    intent = detect_intent(user_message)

    update_user_state(sender_id, user_message)

    # 1. BACKWARD SPINE (Resolve previous prediction)
    graph = get_user_graph(sender_id)
    recent_interps = [n for n in graph.nodes.values() if n.type == NodeType.INTERPRETATION]
    prev_interp_text = recent_interps[-1].payload.summary if recent_interps else ""

    backward_spine(sender_id, user_message, time.time(), prev_interp_text)

    # 2. FORWARD SPINE
    ctx = CognitiveContext()
    ctx.user_state = get_user_state(sender_id)

    run_perception(sender_id, user_message, ctx.user_state, ctx)
    run_worldview(sender_id, ctx)
    run_values(sender_id, ctx)
    run_self_model(sender_id, ctx)
    run_voice(sender_id, ctx)

    log_spine(sender_id, ctx, user_message)
    
    # 3. PROMPT & LLM
    system = build_system_prompt_v756(sender_id, user_message, ctx)
    save_message(sender_id, "user", user_message)

    ai_text = _call_groq(system, get_history(sender_id))
    save_message(sender_id, "assistant", ai_text)

    # 4. REGISTER PREDICTION
    exp_id = log_experience(sender_id, user_message, intent, ai_text)
    register_prediction(sender_id, exp_id, ctx.voice["decision"])

    # 5. BACKGROUND PROCESS
    try: get_mind(sender_id).process({"id": exp_id, "user_message": user_message, "intent": intent, "response": ai_text, "outcome": None})
    except: pass
    background_learning_async(sender_id, user_message)

    return ai_text

def background_learning_async(sender_id: str, user_message: str):
    update_style_profile(sender_id, user_message)
    topics = extract_topics_heuristic(user_message)
    for t in topics: update_topic(sender_id, t)
    if random.random() < 0.10: decay_old_facts_async(sender_id)
    if random.random() < 0.05: trim_facts_async(sender_id)
    def _run():
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
                log.warning(f"[LEARN] LLM HTTP {res.status_code}")
                return
            raw = res.json()["choices"][0]["message"]["content"].strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            raw_facts = data.get("facts", {}); importance = data.get("facts_importance", {})
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
                        to_save = {k: v for k, v in accepted.items() if v["confidence"] >= 0.85}
                        to_stage = {k: v for k, v in accepted.items() if v["confidence"] < 0.85}
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
            log.info(f"[LEARN] done | facts_raw={len(raw_facts)} saved={saved} staged={staged} rej_rule={rejected_rule} rej_skeptic={rejected_skeptic} | prefs={pref_saved}")
        except Exception as e:
            log.debug(f"[LEARN] extraction failed: {e}")
    threading.Thread(target=_run, daemon=True).start()

@app.route("/admin")
def admin():
    supplied = request.args.get("token") or ""
    if not ADMIN_TOKEN or not hmac.compare_digest(supplied, ADMIN_TOKEN):
        return "Unauthorized", 401
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT sender_id, MAX(ts) as last_ts, COUNT(*) as total FROM history GROUP BY sender_id ORDER BY last_ts DESC")
    users = c.fetchall()
    html = "<html><head><meta charset='utf-8'><title>Bot Admin 7.56</title><style>body{font-family:monospace;background:#111;color:#eee;padding:20px;max-width:900px;margin:0 auto}h1{color:#e86c99}h2{color:#5ecfb0;border-bottom:1px solid #333;padding-bottom:6px}.msg{margin:4px 0;padding:6px 10px;border-radius:6px}.user{background:#1a2a1a;color:#7defa7}.bot{background:#1a1a2a;color:#aac4ff}.ts{color:#555;font-size:11px;margin-left:8px}.facts{color:#f0a84a;font-size:12px}a{color:#e86c99}hr{border-color:#333}</style></head><body><h1>🎀 Tuệ Mẫn 7.56 Admin</h1>"
    for sender_id, last_ts, total in users:
        html += f'<h2>👤 {sender_id} <span style="font-size:13px;color:#555">({total} msgs · last: {last_ts})</span></h2>'

        c.execute("SELECT role, success_rate, failure_count, model_accuracy, doubt_style FROM self_model WHERE sender_id=?", (sender_id,))
        sm_row = c.fetchone()
        if sm_row:
            html += f'<div class="facts" style="color:#ff8c69">🧍‍♀️ SELF-MODEL: Role={sm_row[0]} | Acc={sm_row[3]:.2f} | Success={sm_row[1]:.2f} | Fails={sm_row[2]} | Doubt={sm_row[4]}</div>'

        c.execute("SELECT belief, confidence, evidence_count, domain, nuances FROM beliefs WHERE sender_id=? AND confidence > 0.3 ORDER BY confidence DESC LIMIT 10", (sender_id,))
        belief_rows = c.fetchall()
        if belief_rows:
            html += '<div class="facts" style="color:#a8e6cf;font-weight:bold">🧠 BELIEFS (7.56)</div>'
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
            safe = content.replace("<", "&lt;").replace(">", "&gt;")
            html += f'<div class="msg {css}">{icon} {safe}<span class="ts">{ts}</span></div>'
        html += "<hr>"
    conn.close(); html += "</body></html>"
    return html

@app.route("/", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN: return request.args.get("hub.challenge"), 200
    return "Bot Running 7.56", 200

def verify_fb_signature(raw_body: bytes, signature_header: str) -> bool:
    if not FB_APP_SECRET or not signature_header or not signature_header.startswith("sha256="): return False
    expected = hmac.new(FB_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("sha256=", 1)[1]
    return hmac.compare_digest(expected, provided)

@app.route("/", methods=["POST"])
def webhook():
    raw_body = request.get_data()
    if not verify_fb_signature(raw_body, request.headers.get("X-Hub-Signature-256", "")): return "Invalid signature", 403
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
                    continue

                def process():
                    try:
                        cancel_follow_up(sender_id); _reset_follow_up_count(sender_id)
                        send_typing_on(sender_id)
                        time.sleep(get_initial_delay())
                        ai_response = call_groq_ai(sender_id, user_text)
                        send_fb_message_parts(sender_id, ai_response)
                        schedule_follow_up(sender_id)
                    except Exception as e: log.exception(e)
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

def call_deep_ai(question: str) -> str:
    return _call_groq(DEEP_SYSTEM_PROMPT, [{"role": "user", "content": question}], max_tokens=400)

def process_deep(sender_id: str, question: str):
    try: send_fb_message_parts(sender_id, call_deep_ai(question))
    except Exception as e: log.exception(e)

def call_groq_followup(sender_id: str) -> str:
    history = get_history(sender_id)
    if not history: return ""
    system = BASE_SYSTEM_PROMPT + "\nAnh chưa trả lời. Em nhắn thêm một tin thật ngắn, thật tự nhiên — một suy nghĩ vặt hoặc câu hỏi nhẹ. Không tỏ ra đang đợi."
    ai_text = _call_groq(system, history, max_tokens=80)
    if ai_text and ai_text != "...": save_message(sender_id, "assistant", ai_text)
    return ai_text

def get_follow_up_delay(): return random.randint(240, 520)

def cancel_follow_up(sender_id: str):
    if sender_id in follow_up_timers:
        follow_up_timers[sender_id].cancel(); del follow_up_timers[sender_id]

def schedule_follow_up(sender_id: str):
    cancel_follow_up(sender_id)
    count = _get_follow_up_count(sender_id)
    if count >= MAX_FOLLOW_UPS: return
    def do_follow_up():
        follow_up_timers.pop(sender_id, None)
        _incr_follow_up_count(sender_id)
        ai_response = call_groq_followup(sender_id)
        if ai_response and ai_response != "...":
            send_fb_message_parts(sender_id, ai_response)
            schedule_follow_up(sender_id)
    delay = get_follow_up_delay()
    timer = threading.Timer(delay, do_follow_up); timer.daemon = True; timer.start()
    follow_up_timers[sender_id] = timer

if __name__ == "__main__":
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    log.info("Mind v7.56 — The Cognitive Spine Running (Complete)...")
    app.run(host="0.0.0.0", port=5000, debug=False)
