import os
import re
import sys
import time
import random
import logging
import threading
import sqlite3
import json
import datetime
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
MAX_FOLLOW_UPS       = 2     # tối đa 2 lần follow-up liên tiếp
MAX_HISTORY          = 14    # số tin nhắn giữ trong context
MAX_FACTS            = 50    # giới hạn facts lưu trong DB
DB_PATH              = "memory.db"
DB_TIMEOUT           = 20
EXPERIENCE_THRESHOLD = 50   # reflect every N scored experiences
ADMIN_TOKEN          = os.environ.get("ADMIN_TOKEN")
# =======================================================

follow_up_timers = {}   # sender_id -> threading.Timer
follow_up_counts = {}   # sender_id -> int
user_states      = {}
processed_mids   = {}

# ==================== DATABASE ====================

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            ts        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            sender_id TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT NOT NULL,
            PRIMARY KEY (sender_id, key)
        )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS user_state (
        sender_id TEXT PRIMARY KEY,
        state TEXT NOT NULL
    )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            sender_id  TEXT NOT NULL,
            category   TEXT NOT NULL,
            value      TEXT NOT NULL,
            score      REAL DEFAULT 1.0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sender_id, category, value)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS topic_stats (
            sender_id TEXT NOT NULL,
            topic     TEXT NOT NULL,
            count     INTEGER DEFAULT 1,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sender_id, topic)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS style_profile (
            sender_id         TEXT PRIMARY KEY,
            reply_length_pref REAL DEFAULT 50.0,
            avg_msg_len       REAL DEFAULT 50.0,
            msg_count         INTEGER DEFAULT 0
        )
    """)
    # Migrations — safe to re-run on every startup
    for ddl in [
        "ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 5",
        "ALTER TABLE facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE facts ADD COLUMN confidence REAL DEFAULT 0.8",
        "ALTER TABLE facts ADD COLUMN source_message TEXT DEFAULT ''",
        "ALTER TABLE fact_candidates ADD COLUMN confidence REAL DEFAULT 0.0",
        "ALTER TABLE fact_candidates ADD COLUMN source_message TEXT DEFAULT ''",
    ]:
        try:
            c.execute(ddl)
        except Exception:
            pass

    # Level 5: fact_candidates — rejected facts accumulate score here
    # They are NOT promoted automatically (that is Level 3's job).
    c.execute("""
        CREATE TABLE IF NOT EXISTS fact_candidates (
            sender_id        TEXT NOT NULL,
            key              TEXT NOT NULL,
            value            TEXT NOT NULL,
            score            INTEGER DEFAULT 1,
            rejection_reason TEXT DEFAULT NULL,
            last_seen        DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sender_id, key)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id    TEXT NOT NULL,
            user_message TEXT NOT NULL,
            intent       TEXT DEFAULT '',
            response     TEXT NOT NULL,
            decision     TEXT DEFAULT 'respond',
            outcome      INTEGER DEFAULT NULL,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id      TEXT NOT NULL,
            belief         TEXT NOT NULL,
            confidence     REAL DEFAULT 0.5,
            evidence_count INTEGER DEFAULT 1,
            last_updated   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()


def get_history(sender_id: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM history WHERE sender_id=? ORDER BY id DESC LIMIT ?",
        (sender_id, MAX_HISTORY)
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def save_message(sender_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute(
        "INSERT INTO history (sender_id, role, content) VALUES (?, ?, ?)",
        (sender_id, role, content)
    )
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


def get_relevant_facts(sender_id: str, user_message: str, n: int = 5) -> dict:
    """Return facts most relevant to the current message (keyword match + high importance fallback)."""
    stop = {"cung", "nhung", "thoi", "vay", "nay", "do", "cua", "voi", "duoc",
            "khong", "co", "la", "va", "cho", "anh", "em", "thi", "ma", "roi"}
    words = [w.strip(".,!?") for w in user_message.lower().split() if len(w) > 2 and w not in stop]

    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    results = {}

    # Keyword-matched facts first
    for word in words[:6]:
        if len(results) >= n:
            break
        c.execute("""
            SELECT key, value FROM facts
            WHERE sender_id=? AND importance >= 4
            AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ?)
            ORDER BY importance DESC LIMIT 3
        """, (sender_id, f"%{word}%", f"%{word}%"))
        for k, v in c.fetchall():
            results[k] = v

    # Pad with highest-importance facts if still short
    if len(results) < n:
        c.execute("""
            SELECT key, value FROM facts
            WHERE sender_id=? AND importance >= 7
            ORDER BY importance DESC LIMIT ?
        """, (sender_id, n))
        for k, v in c.fetchall():
            if k not in results:
                results[k] = v

    conn.close()
    return dict(list(results.items())[:n])


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
    import threading as _t
    _t.Thread(target=_run, daemon=True).start()


def save_facts(sender_id: str, new_facts: dict):
    if not new_facts:
        return
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    for k, v in new_facts.items():
        conn.execute(
            "INSERT OR REPLACE INTO facts (sender_id, key, value) VALUES (?, ?, ?)",
            (sender_id, str(k)[:80], str(v)[:200])
        )
    conn.commit()
    conn.close()

# ==================== LEARNING: PREFERENCES ====================

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


# ==================== LEARNING: TOPICS ====================

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


# ==================== LEARNING: STYLE PROFILE ====================

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


# ==================== LEARNING: IMPORTANCE + DECAY ====================

def save_facts_with_importance(
    sender_id: str,
    accepted: dict,           # {key: {value, confidence}} from skeptic_validate
    importance_map: dict,
    source_message: str = "",
):
    """
    Save validated facts.
    - Only updates an existing fact if new confidence > stored confidence.
    - Stores source_message for auditability.
    """
    if not accepted:
        return
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    for k, payload in accepted.items():
        if isinstance(payload, dict):
            val  = str(payload.get("value", ""))[:200]
            conf = float(payload.get("confidence", 0.8))
        else:
            val, conf = str(payload)[:200], 0.8   # legacy flat format

        imp = int(importance_map.get(k, 5))
        imp = max(0, min(10, imp))

        # Conflict resolution: only overwrite if new confidence is higher
        c.execute(
            "SELECT confidence FROM facts WHERE sender_id=? AND key=?",
            (sender_id, str(k)[:80])
        )
        row = c.fetchone()
        if row and float(row[0] or 0) >= conf:
            log.debug(
                f"[FACTS] skipping '{k}': existing conf {row[0]:.2f} >= new {conf:.2f}"
            )
            continue

        conn.execute("""
            INSERT INTO facts
                (sender_id, key, value, importance, confidence, source_message, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(sender_id, key) DO UPDATE SET
                value          = excluded.value,
                importance     = excluded.importance,
                confidence     = excluded.confidence,
                source_message = excluded.source_message,
                updated_at     = CURRENT_TIMESTAMP
        """, (sender_id, str(k)[:80], val, imp, conf,
              source_message[:300] if source_message else ""))
    conn.commit()
    conn.close()


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


# ==================== LEARNING: HEURISTIC TOPIC EXTRACTION ====================

def extract_topics_heuristic(message: str) -> list:
    """
    Keyword-based topic detection — no API, instant, free.
    Returns up to 3 meaningful keywords from the user message.
    """
    from collections import Counter

    STOP = {
        # Vietnamese
        "anh", "em", "cũng", "nhưng", "thôi", "vậy", "này", "đó", "của",
        "với", "được", "không", "có", "là", "và", "cho", "thì", "mà", "rồi",
        "đây", "đấy", "ơi", "ạ", "nhé", "nha", "nghe", "thật", "quá", "hay",
        "lắm", "rất", "hơi", "cái", "mình", "bạn", "người", "lúc", "khi",
        "thế", "sao", "còn", "nữa", "như", "vì", "nên", "đang", "đã", "sẽ",
        "bị", "muốn", "cần", "phải", "làm", "nói", "biết", "thấy", "nghĩ",
        "hiểu", "nhớ", "xem", "ăn", "ngủ", "đi", "vui", "buồn", "tốt", "vl",
        # English
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


# ==================== LEARNING: COMBINED BACKGROUND CALL ====================

def background_learning_async(sender_id: str, user_message: str):
    """
    One background Groq call that learns:
      - facts + importance (Level 2)
      - preferences: humor, communication, sleep, interests (Level 1)
    Topics are extracted heuristically (no API — instant, free).
    Style profile is updated heuristically (no API).
    """
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


def load_state(sender_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    c = conn.cursor()

    c.execute(
        "SELECT state FROM user_state WHERE sender_id=?",
        (sender_id,)
    )

    row = c.fetchone()
    conn.close()

    if row:
        try:
            return json.loads(row[0])
        except:
            return None

    return None


def save_state(sender_id: str):
    state = user_states.get(sender_id)

    if not state:
        return

    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)

    conn.execute(
        """
        INSERT OR REPLACE INTO user_state
        (sender_id, state)
        VALUES (?, ?)
        """,
        (
            sender_id,
            json.dumps(state, ensure_ascii=False)
        )
    )

    conn.commit()
    conn.close()
# ==================== USER STATE ====================
    
def get_user_state(sender_id: str):
    if sender_id not in user_states:
    
        loaded = load_state(sender_id)
    
        if loaded:
    
            user_states[sender_id] = loaded
    
        else:
            user_states[sender_id] = {
                        "mood": "neutral",
                        "energy": random.randint(45, 80),
                        "reply_energy": random.randint(45, 80),
                        "affection": random.randint(35, 55),
                        "familiarity": 0,
                        "patience": random.randint(50, 80),
                        "relationship": 5,      # 0-100, grows slowly over weeks
                        "last_interaction": time.time(),
                        "last_seen_gap": 0,
                        "spam_count": 0,
                        "inside_jokes": [],
                        "emotional_events": []
                    }
    return user_states[sender_id]

def update_user_state(sender_id: str, user_message: str):
    state = get_user_state(sender_id)
    now_ts = time.time()
    
    gap_hours = (
        now_ts - state["last_interaction"]
    ) / 3600
    
    state["last_seen_gap"] = gap_hours
    hour = datetime.datetime.now().hour
    msg = user_message.lower()
    emotion_keywords = {
        "mệt": "stress",
        "stress": "stress",
        "áp lực": "stress",
        "buồn": "sad",
        "chán": "low_mood",
        "khó ngủ": "sleep_issues",
        "mất ngủ": "sleep_issues"
    }


    for key, value in emotion_keywords.items():
    
        if key in msg:
    
            state["emotional_events"].append({
                "type": value,
                "time": now_ts
            })
    
    state["emotional_events"] = (
        state["emotional_events"][-20:]
    )

    joke_triggers = {
        "ngủ quên": "combo ngủ quên",
        "5h sáng": "combo ngủ lúc 5h sáng",
        "mất tích": "vụ mất tích huyền thoại",
        "game": "anh nghiện game"
    }
    
    for trigger, joke in joke_triggers.items():
    
        if trigger in msg:
    
            if joke not in state["inside_jokes"]:
    
                state["inside_jokes"].append(joke)
    
    state["inside_jokes"] = (
        state["inside_jokes"][-10:]
    )
    
    # spam detection
    if len(user_message.strip()) < 8:
        state["spam_count"] += 1
    else:
        state["spam_count"] = max(0, state["spam_count"] - 1)

    # affection increase
    positive_words = [
        "nhớ", "thương", "ngủ ngon",
        "ăn chưa", "quan tâm", "iu", "yêu"
    ]

    if any(x in msg for x in positive_words):
        state["affection"] += random.randint(1, 3)

    # affection decrease
    negative_words = [
        "địt", "ngu", "cút", "im",
        "con bot", "npc", "óc chó"
    ]

    state["familiarity"] = min(
        100,
        state["familiarity"] + 1
    )

    if any(x in msg for x in negative_words):
        state["affection"] -= random.randint(4, 8)
        state["patience"] -= random.randint(5, 10)

    if gap_hours > 24:
    
        state["affection"] -= min(
            int(gap_hours // 24),
            5
        )

    # clamp
    state["affection"] = max(0, min(100, state["affection"]))
    state["patience"] = max(0, min(100, state["patience"]))

    # relationship_score — grows slowly, reflects long-term connection
    rel = state.get("relationship", 5)
    if len(user_message.strip()) > 15:        # meaningful message
        rel += 0.4
    if any(x in msg for x in positive_words):
        rel += 0.8
    if any(x in msg for x in negative_words):
        rel -= 1.5
    if gap_hours > 48:                        # long absence hurts slightly
        rel -= min(gap_hours / 48 * 0.3, 3)
    state["relationship"] = max(0, min(100, rel))

    # mood logic
    if hour >= 23 or hour <= 4:
        state["mood"] = "sleepy"

    elif state["spam_count"] >= 4:
        state["mood"] = "annoyed"

    elif state["affection"] >= 75:
        state["mood"] = "soft"

    elif random.random() < 0.18:
        state["mood"] = "playful"

    else:
        state["mood"] = random.choice([
            "neutral",
            "dry",
            "soft"
        ])

    state["last_interaction"] = time.time()
    save_state(sender_id)
    
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


def build_system_prompt(sender_id: str, user_message_hint: str = "") -> str:
    """Inject thoi gian thuc + facts + anti-repetition vao system prompt."""
    now = datetime.datetime.now()
    state = get_user_state(sender_id)
    hour = now.hour
    weekday_vi = ["Thu Hai", "Thu Ba", "Thu Tu", "Thu Nam", "Thu Sau", "Thu Bay", "Chu Nhat"][now.weekday()]

    if 5 <= hour < 9:
        time_note = "buoi sang som — co the noi em vua day, hoi buon ngu"
    elif 9 <= hour < 12:
        time_note = "buoi sang — dang o truong hoac quan ca phe"
    elif 12 <= hour < 14:
        time_note = "gio trua — vua an xong hoac dang nghi trua"
    elif 14 <= hour < 18:
        time_note = "chieu — dang hoc hoac luot dien thoai"
    elif 18 <= hour < 22:
        time_note = "toi — ve nha roi, hay nhan nhieu nhat luc nay"
    elif 22 <= hour or hour < 1:
        time_note = "toi muon — sap ngu roi, co the noi buon ngu"
    else:
        time_note = "dem khuya — thuc muon, hoi mo mang"

    time_block = (
        f"\n\n## THONG TIN THUC TE"
        f"\n- Hom nay: {weekday_vi}, {now.strftime('%d/%m/%Y')}"
        f"\n- Gio hien tai: {now.strftime('%H:%M')} -> {time_note}"
    )

    relevant_facts = get_relevant_facts(sender_id, user_message_hint, n=5)
    if relevant_facts:
        fact_lines = "\n".join(f"- {k}: {v}" for k, v in relevant_facts.items())
        facts_block = (
            f"\n\n## NHUNG GI EM NHO VE ANH (lien quan hom nay)\n{fact_lines}"
            f"\n(Chi inject fact lien quan — khong nhac lai het mot luc)"
        )
    else:
        facts_block = ""

    # Anti-repetition: inject recent bot replies so the model avoids repeating them
    recent_replies = get_recent_bot_replies(sender_id, n=6)
    if recent_replies:
        recent_lines = "\n".join(f'- "{r}"' for r in recent_replies)
        anti_rep_block = (
            f"\n\n## DA NOI ROI — KHONG DUOC LAP LAI"
            f"\nNhung cau em da nhan gan day. Tuyet doi khong dung lai cung cau truc,"
            f" cung mo dau, hay cung y:\n{recent_lines}"
        )
    else:
        anti_rep_block = ""

    rel = state.get("relationship", 5)
    if rel < 20:
        rel_tier = "xa la (0-20) — chua quen nhieu, giu khoang cach nhe, khong qua warm"
    elif rel < 40:
        rel_tier = "quen (20-40) — dang mo dan, thoai mai hon, doi khi tease nhe"
    elif rel < 70:
        rel_tier = "than (40-70) — tu nhien, co the tease, nho detail cu, hay nhan truoc"
    else:
        rel_tier = "rat than (70+) — rat thoai mai, ban be that su, hay tro chuyyen, hieu y nhau"

    state_block = f"""

## CURRENT STATE

Relationship: {rel:.0f}/100 — {rel_tier}
Mood: {state['mood']}
Affection: {state['affection']}/100
Gap since last chat: {round(state["last_seen_gap"], 1)}h

Mood behavior:
- sleepy: rep ngan, lowercase, it emoji
- playful: tease nhe, nghich hon
- dry: rep cut, khong co giu conv
- soft: caring nhe, nho detail cu
- annoyed: it chieu, hoi tease

Khong phai luc nao cung energetic.
Doi khi chi rep: "hmm" / "vay a" / "..."
"""

    joke_block = ""
    
    if state["inside_jokes"]:
    
        joke_block = (
            "\n\nInside jokes:\n"
            + "\n".join(
                f"- {x}"
                for x in state["inside_jokes"][-3:]
            )
        )
    recent_events = []
    
    for event in state["emotional_events"]:
    
        age_hours = (
            time.time() - event["time"]
        ) / 3600
    
        if age_hours < 72:
            recent_events.append(
                event["type"]
            )

    emotion_block = ""
            
    if recent_events:
            
        emotion_block = (
            "\n\nRecent emotional context:\n"
            + "\n".join(
                f"- {x}"
                for x in recent_events[-3:]
            )
        )        
            
    # ── Level 1: Preferences block ──
    prefs = get_preferences(sender_id)
    if prefs:
        pref_lines = ", ".join(f"{k}: {v}" for k, v in prefs.items())
        prefs_block = (
            f"\n\n## PREFERENCE CUA ANH"
            f"\nAnh co ve thich / co xu huong: {pref_lines}"
            f"\n(Dung thong tin nay de chat tu nhien hon, khong nhac truc tiep)"
        )
    else:
        prefs_block = ""

    # ── Level 1: Topics block ──
    top_topics = get_top_topics(sender_id, n=5)
    if top_topics:
        topic_lines = ", ".join(f"{t} ({c}x)" for t, c in top_topics)
        topics_block = (
            f"\n\n## CHU DE HAY NOI"
            f"\n{topic_lines}"
            f"\n(Anh hay nhac den nhung thu nay — co the dung de mo chuyen tu nhien)"
        )
    else:
        topics_block = ""

    # ── Level 1: Style hint ──
    style = get_style_profile(sender_id)
    style_hint = ""
    if style["msg_count"] >= 8:
        pref = style["reply_length_pref"]
        if pref < 28:
            style_hint = "\n\n## STYLE: Anh nhan rat ngan — rep ngan tuong duong, khong can giai thich nhieu"
        elif pref > 65:
            style_hint = "\n\n## STYLE: Anh nhan kha dai — co the rep day du hon binh thuong"

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
    )


# ==================== FACT EXTRACTION ====================


# ==================== LEVEL 1: EXPERIENCE LOG ====================

def log_experience(
    sender_id: str, user_message: str, intent: str,
    response: str, decision: str = "respond",
) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        INSERT INTO experiences
            (sender_id, user_message, intent, response, decision, outcome)
        VALUES (?, ?, ?, ?, ?, NULL)
    """, (sender_id, user_message[:500], intent[:60], response[:500], decision[:60]))
    exp_id = c.lastrowid
    conn.commit()
    conn.close()
    return exp_id


def get_last_unscored_experience(sender_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        SELECT id, user_message, intent, response, decision
        FROM experiences WHERE sender_id=? AND outcome IS NULL
        ORDER BY id DESC LIMIT 1
    """, (sender_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "user_message": row[1], "intent": row[2],
            "response": row[3], "decision": row[4]}


def count_experiences_since_reflection(sender_id: str) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT MAX(last_updated) FROM beliefs WHERE sender_id=?", (sender_id,))
    row  = c.fetchone()
    since = row[0] if (row and row[0]) else "1970-01-01"
    c.execute(
        "SELECT COUNT(*) FROM experiences WHERE sender_id=? AND created_at>? AND outcome IS NOT NULL",
        (sender_id, since)
    )
    n = c.fetchone()[0]
    conn.close()
    return n


def get_experiences_for_reflection(sender_id: str, limit: int = 100) -> list:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        SELECT user_message, intent, response, decision, outcome
        FROM experiences WHERE sender_id=? AND outcome IS NOT NULL
        ORDER BY id DESC LIMIT ?
    """, (sender_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"user_message": r[0], "intent": r[1], "response": r[2],
             "decision": r[3], "outcome": r[4]} for r in rows]


# ==================== LEVEL 2: OUTCOME DETECTION ====================

def detect_outcome_score(user_reply: str) -> int:
    """
    Heuristic outcome scoring — zero API cost.
    Scores the PREVIOUS bot response based on how user replied next.
    +2 very positive | +1 mild positive | 0 neutral | -1 confused | -2 shutdown
    """
    msg = user_reply.lower().strip()
    VERY_POS = {"haha","hahaha","lmao","lmaooo","đúng vl","chuẩn vl","hay vl",
                "chill vl","ngon vl","ngầu vl","xd","đỉnh","đỉnh vl","gg","ez",
                "nice","💀","😭","🤣","😂","🔥"}
    MILD_POS  = {"ừ đúng","hay đó","đúng rồi","thú vị","hay","hiểu rồi","ừ ừ",
                 "hợp lý","ok thật","nghe có lý"}
    CONFUSED  = {"???","hả","gì vậy","gì thế","không hiểu","huh","sao vậy","wtf"}
    SHUTDOWN  = {"thôi","k nhắn nữa","ko nói nữa","bye","thôi đi","dẹp","im đi"}

    for kw in VERY_POS:
        if kw in msg: return 2
    for kw in MILD_POS:
        if kw in msg: return 1
    for kw in SHUTDOWN:
        if kw in msg: return -2
    for kw in CONFUSED:
        if kw in msg: return -1
    if len(msg) > 80:
        return 1
    return 0


def update_experience_outcome(exp_id: int, score: int):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("UPDATE experiences SET outcome=? WHERE id=?", (score, exp_id))
    conn.commit()
    conn.close()


# ==================== LEVEL 4: BELIEF DATABASE ====================

def get_beliefs(sender_id: str, limit: int = 15) -> list:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        SELECT id, belief, confidence, evidence_count FROM beliefs
        WHERE sender_id=? AND confidence > 0.15
        ORDER BY confidence * evidence_count DESC LIMIT ?
    """, (sender_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "belief": r[1], "confidence": r[2], "evidence_count": r[3]}
            for r in rows]


def get_relevant_beliefs(sender_id: str, user_message: str, limit: int = 5) -> list:
    stop = {"cung","nhung","thoi","vay","nay","do","cua","voi","duoc",
            "khong","co","la","va","cho","anh","em","thi","ma","roi"}
    words = [w.strip(".,!?") for w in user_message.lower().split()
             if len(w) > 2 and w not in stop]

    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    results, seen = [], set()

    for word in words[:5]:
        c.execute("""
            SELECT id, belief, confidence, evidence_count FROM beliefs
            WHERE sender_id=? AND confidence > 0.2 AND LOWER(belief) LIKE ?
            ORDER BY confidence * evidence_count DESC LIMIT 3
        """, (sender_id, f"%{word}%"))
        for row in c.fetchall():
            if row[0] not in seen:
                results.append({"id": row[0], "belief": row[1],
                                "confidence": row[2], "evidence_count": row[3]})
                seen.add(row[0])

    if len(results) < limit:
        c.execute("""
            SELECT id, belief, confidence, evidence_count FROM beliefs
            WHERE sender_id=? AND confidence > 0.3
            ORDER BY confidence * evidence_count DESC LIMIT ?
        """, (sender_id, limit))
        for row in c.fetchall():
            if row[0] not in seen:
                results.append({"id": row[0], "belief": row[1],
                                "confidence": row[2], "evidence_count": row[3]})
                seen.add(row[0])

    conn.close()
    return results[:limit]


def save_belief(sender_id: str, belief: str, confidence: float, evidence_count: int = 1):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT id, confidence, evidence_count FROM beliefs WHERE sender_id=? AND belief=?",
              (sender_id, belief[:400]))
    row = c.fetchone()
    if row:
        old_c, old_n = row[1], row[2]
        new_n    = old_n + evidence_count
        new_conf = max(0.0, min(1.0, (old_c * old_n + confidence * evidence_count) / new_n))
        conn.execute(
            "UPDATE beliefs SET confidence=?, evidence_count=?, last_updated=CURRENT_TIMESTAMP WHERE id=?",
            (new_conf, new_n, row[0])
        )
    else:
        conn.execute(
            "INSERT INTO beliefs (sender_id, belief, confidence, evidence_count) VALUES (?,?,?,?)",
            (sender_id, belief[:400], confidence, evidence_count)
        )
    conn.commit()
    conn.close()


def update_belief_confidence(sender_id: str, belief_id: int, delta: float):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT confidence FROM beliefs WHERE id=? AND sender_id=?", (belief_id, sender_id))
    row = c.fetchone()
    if row:
        conn.execute(
            "UPDATE beliefs SET confidence=?, last_updated=CURRENT_TIMESTAMP WHERE id=?",
            (max(0.0, min(1.0, float(row[0]) + delta)), belief_id)
        )
    conn.commit()
    conn.close()


def decay_weak_beliefs_async(sender_id: str):
    """Level 7 — kill beliefs the evidence has consistently disproved."""
    def _run():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            c = conn.cursor()
            c.execute(
                "DELETE FROM beliefs WHERE sender_id=? AND confidence < 0.1 AND evidence_count >= 3",
                (sender_id,)
            )
            n = c.rowcount
            conn.commit()
            conn.close()
            if n:
                log.info(f"[BELIEF:DEAD] {sender_id}: {n} belief(s) decayed and removed")
        except Exception as e:
            log.debug(f"[BELIEF:DECAY] {e}")
    threading.Thread(target=_run, daemon=True).start()


# ==================== LEVEL 3 + 7: REFLECTION + EVOLUTION ====================

_REFLECT_SYSTEM = (
    "You analyze chatbot interactions to extract behavioral beliefs about a specific user. "
    "Input: recent interactions with outcome scores "
    "(+2=very positive, +1=good, 0=neutral, -1=confusion/negative, -2=shutdown). "
    "Find repeating patterns: HIGH outcomes=bot did right, LOW outcomes=bot did wrong. "
    "Extract as specific actionable beliefs (3+ supporting interactions minimum). "
    'Return ONLY JSON: {"new_beliefs":[{"belief":"...","confidence":0.0}],'
    '"contradicted":[{"belief":"exact existing belief text","confidence_delta":-0.1}]}'
)

_EVOLVE_SYSTEM = (
    "Given recent interaction outcomes and existing beliefs, "
    "determine if each belief is confirmed or contradicted by the evidence. "
    'Return ONLY JSON: {"updates":[{"id":BELIEF_ID,"action":"confirm|contradict|neutral"}]}'
)


def reflect_async(sender_id: str):
    """Level 3: extract new beliefs. Level 7: evolve existing ones."""
    def _run():
        try:
            experiences = get_experiences_for_reflection(sender_id, limit=100)
            if len(experiences) < 10:
                return

            existing    = get_beliefs(sender_id, limit=20)
            existing_js = json.dumps(
                [{"id": b["id"], "belief": b["belief"], "confidence": b["confidence"]}
                 for b in existing], ensure_ascii=False
            )
            exp_js = json.dumps(experiences[:60], ensure_ascii=False)

            url     = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

            # Level 3 — new beliefs + contradictions
            r1 = requests.post(url, headers=headers, timeout=15, json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": _REFLECT_SYSTEM},
                    {"role": "user",   "content":
                     "existing_beliefs:" + existing_js + "\nrecent_experiences:" + exp_js},
                ],
                "temperature": 0.2, "max_tokens": 600,
            })
            if r1.status_code == 200:
                raw = r1.json()["choices"][0]["message"]["content"].strip()
                raw = raw.replace("```json","").replace("```","").strip()
                d   = json.loads(raw)

                for b in d.get("new_beliefs", []):
                    if b.get("belief") and float(b.get("confidence", 0)) >= 0.4:
                        save_belief(sender_id, b["belief"], float(b["confidence"]))
                        log.info(f"[BELIEF:NEW] {sender_id}: {b['belief']} ({b['confidence']:.2f})")

                for c_item in d.get("contradicted", []):
                    for b in existing:
                        if b["belief"] == c_item.get("belief"):
                            update_belief_confidence(
                                sender_id, b["id"],
                                float(c_item.get("confidence_delta", -0.1))
                            )
                            log.info(f"[BELIEF:CONTRA] {sender_id}: '{b['belief']}'")
                            break

            # Level 7 — evolve existing beliefs
            if existing:
                r2 = requests.post(url, headers=headers, timeout=10, json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content":
                        "Beliefs:" + existing_js + "\nRecent 20 experiences:" +
                        json.dumps(experiences[:20], ensure_ascii=False)
                    }],
                    "temperature": 0.1, "max_tokens": 300,
                })
                if r2.status_code == 200:
                    raw2 = r2.json()["choices"][0]["message"]["content"].strip()
                    raw2 = raw2.replace("```json","").replace("```","").strip()
                    d2   = json.loads(raw2)
                    for upd in d2.get("updates", []):
                        bid, action = upd.get("id"), upd.get("action","neutral")
                        delta = +0.05 if action == "confirm" else (-0.10 if action == "contradict" else 0)
                        if delta and bid:
                            update_belief_confidence(sender_id, bid, delta)

            decay_weak_beliefs_async(sender_id)
            log.info(f"[REFLECT] {sender_id}: done")

        except Exception as e:
            log.warning(f"[REFLECT] {e}")

    threading.Thread(target=_run, daemon=True).start()


def maybe_reflect(sender_id: str):
    if count_experiences_since_reflection(sender_id) >= EXPERIENCE_THRESHOLD:
        log.info(f"[REFLECT] {sender_id}: threshold hit — reflecting")
        reflect_async(sender_id)


# ==================== LEVEL 5: DECISION ENGINE ====================

def build_belief_prompt(beliefs: list) -> str:
    """Convert active beliefs into behavioral guidance injected into system prompt."""
    lines = [
        f"  - {b['belief']} ({b['confidence']:.0%}, {b['evidence_count']} evidence)"
        for b in beliefs
        if b["confidence"] >= 0.4 and b["evidence_count"] >= 2
    ]
    if not lines:
        return ""
    return (
        "\n\n## BEHAVIORAL BELIEFS (rút ra từ kinh nghiệm thực tế)"
        "\nNhững niềm tin sau được hình thành từ các cuộc trò chuyện — áp dụng tự nhiên:"
        "\n" + "\n".join(lines) +
        "\n(Không nhắc trực tiếp đến những điều này với anh)"
    )


# ==================== LEVEL 6: OPINION ENGINE ====================

def get_opinion_from_beliefs(sender_id: str, topic: str) -> str | None:
    """Derive a belief-grounded opinion. Returns None if no basis found."""
    relevant = get_relevant_beliefs(sender_id, topic, limit=5)
    useful   = [b for b in relevant if b["confidence"] >= 0.4]
    if not useful:
        return None

    beliefs_text = "\n".join(f"- {b['belief']} ({b['confidence']:.0%})" for b in useful)
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    try:
        res = requests.post(url, headers=headers, timeout=6, json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content":
                    "Derive An Nhien's opinion on the topic from her beliefs about this user. "
                    '1 sentence max. ONLY JSON: {"opinion": "..."}  or  {"opinion": null}'},
                {"role": "user", "content":
                    "Topic: " + topic + "\nBeliefs:\n" + beliefs_text},
            ],
            "temperature": 0.3, "max_tokens": 80,
        })
        if res.status_code == 200:
            raw = res.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            return json.loads(raw).get("opinion")
    except Exception as e:
        log.debug(f"[OPINION] {e}")
    return None


# ==================== LEVEL 5: STRONG SKEPTICISM ENGINE ====================

# ==================== MEMORY: RULE FILTER ====================
# Zero-cost pre-filter — runs before the Skeptic API call.
# Catches ~80% of obvious garbage with no tokens spent.

# Words that look like names/values but are actually noise
VN_NOISE: set = {
    # Vietnamese exclamations & profanity mis-extracted as names
    "má", "mày", "tao", "mình", "ổng", "bả", "hắn", "nó",
    "cha", "trời", "ối", "thôi", "thôi nào",
    "dm", "dmm", "đm", "đmm", "vl", "vcl", "cl", "cc",
    "bố", "mẹ", "má nó", "đéo", "cứt",
    # English noise
    "wtf", "lol", "omg", "bruh", "lmao", "hell", "damn",
    "shit", "fuck", "ass", "bitch",
    # Pronouns / common words mis-tagged as names
    "anh", "em", "chị", "cô", "ông", "bà", "chú",
    "người", "bạn", "mình", "họ",
    # Single punctuation
    "...", "???", "!!!", "ok", "oke", "okay",
}

# Min/max lengths for 'name' type fields
_NAME_KEYS = {"name", "ten", "tên"}

def rule_filter_facts(
    candidates: dict,
    user_message: str,
) -> tuple[dict, dict]:
    """
    Zero-cost rule-based pre-filter before Skeptic LLM.

    Returns (passed, rule_rejected).
    rule_rejected maps key → reason_code string.
    These are saved to fact_candidates immediately — no API call needed.
    """
    passed: dict   = {}
    rejected: dict = {}

    msg_lower = user_message.lower().strip()

    for key, value in candidates.items():
        val_str = str(value).strip()
        val_low = val_str.lower()

        # Rule 1: blank or single-char value
        if len(val_str) < 2:
            rejected[key] = "too_short"
            continue

        # Rule 2: known noise word
        if val_low in VN_NOISE:
            rejected[key] = "noise_word"
            continue

        # Rule 3: name-specific — suspiciously long (>35 chars is a sentence, not a name)
        if key in _NAME_KEYS and len(val_str) > 35:
            rejected[key] = "name_too_long"
            continue

        # Rule 4: name-specific — pure digits
        if key in _NAME_KEYS and re.sub(r"\s", "", val_low).isdigit():
            rejected[key] = "numeric_name"
            continue

        # Rule 5: value is a substring that appears at the very start of the message
        # as the first "word" — strong indicator it was an exclamation not a fact
        first_word = re.split(r"[\s,!.?]", msg_lower)[0]
        if key in _NAME_KEYS and val_low == first_word and len(val_low) <= 4:
            rejected[key] = "leading_exclamation"
            continue

        # Rule 6: contains URL or email — not a personal fact
        if re.search(r"https?://|www\.|@\S+\.\S+", val_str):
            rejected[key] = "contains_url_or_email"
            continue

        passed[key] = value

    return passed, rejected


SKEPTIC_SYSTEM_PROMPT = (
    "You are a MEMORY SKEPTIC. Your only job is to PREVENT false memories.\n"
    "A missed memory is acceptable. A false memory is expensive.\n"
    "When uncertain — REJECT. When highly uncertain — reject aggressively.\n\n"
    "Input (JSON):\n"
    "  USER_MESSAGE   — the exact message the user sent\n"
    "  CANDIDATES     — facts a basic extractor pulled from it\n"
    "  EXISTING_FACTS — facts already in memory (for contradiction detection)\n\n"
    "For every candidate fact ask ALL of:\n"
    "  1. SARCASM      — Is the user being sarcastic or ironic?\n"
    "  2. QUOTE        — Is this a quote, meme, lyric, reference, or hypothetical?\n"
    "  3. JOKE         — Is this a joke or extreme hyperbole?\n"
    "  4. OTHER_PERSON — Does this describe someone else, not the user?\n"
    "  5. VAGUE        — Too vague, temporary, or trivial to be a persistent fact?\n"
    "  6. CORRECTION   — Is the user correcting a past mistake?\n"
    "  7. AMBIGUOUS    — Could this reasonably mean several different things?\n\n"
    "Hard rules:\n"
    "  - ANY doubt on ANY check → REJECT.\n"
    "  - ACCEPT only if CLEAR, DIRECT, SINCERE, and specifically about the user.\n"
    "  - Vietnamese slang carries high ambiguity — raise the bar.\n"
    "  - 'má nó' is a Vietnamese exclamation, NOT a name.\n"
    "  - A user mentioning something does NOT mean it describes them.\n"
    "  - Do NOT infer. Do NOT assume.\n\n"
    "Output format — ONLY valid JSON, no preamble, no markdown:\n"
    "{\n"
    "  \"accepted\": {\n"
    "    \"key\": {\"value\": \"...\" , \"confidence\": 0.0}\n"
    "  },\n"
    "  \"rejected\": {\"key\": \"reason_code\"}\n"
    "}\n\n"
    "confidence is a float 0.0–1.0 reflecting how certain you are this is a true, "
    "sincere, first-person fact. High bar: 0.85+ means near-certain. "
    "0.5–0.84 means plausible but not proven. Below 0.5 means reject instead.\n\n"
    "Valid reason codes:\n"
    "  sarcasm | quote | joke | other_person | vague | correction | ambiguous | insufficient_evidence\n\n"
    "Empty accepted dict is valid and often correct.\n"
    "Default to rejection — burden of proof is on acceptance."
)


def skeptic_validate(
    user_message: str,
    candidates: dict,
    existing_facts: dict,
) -> tuple[dict, dict, dict]:
    """
    Level 5 — Strong Skepticism gate with confidence scoring.

    Returns (accepted, rejected, unavailable).
      accepted    — {key: {value, confidence}} — high-quality facts ready to save
      rejected    — {key: reason_code}         — bad facts, save to candidates
      unavailable — {key: value}               — skeptic failed, save to candidates
                                                 with confidence=0 for later re-check

    Graceful degradation: API/parse failure → (unavailable) instead of silent data loss.
    """
    if not candidates:
        return {}, {}, {}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    user_content = json.dumps(
        {
            "USER_MESSAGE": user_message,
            "CANDIDATES":   candidates,
            "EXISTING_FACTS": existing_facts,
        },
        ensure_ascii=False,
    )

    payload = {
        "model":       "llama-3.1-8b-instant",
        "messages":    [
            {"role": "system", "content": SKEPTIC_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens":  350,
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)

        if res.status_code != 200:
            log.warning(f"[SKEPTIC] API error {res.status_code} — saving to candidates for re-check")
            return {}, {}, candidates   # graceful: don't lose data, re-check later

        raw = res.json()["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        raw_accepted = data.get("accepted", {})
        raw_rejected = data.get("rejected", {})

        accepted: dict = {}
        rejected: dict = {}

        # Parse accepted — new format: {key: {value, confidence}} or fallback {key: value}
        for k, v in raw_accepted.items():
            if k not in candidates:
                continue  # hallucinated key — ignore
            if isinstance(v, dict):
                conf = float(v.get("confidence", 0.8))
                val  = v.get("value", candidates[k])
            else:
                conf = 0.8  # legacy flat format fallback
                val  = v
            if conf < 0.5:
                # Skeptic accepted but with very low confidence — treat as rejected
                rejected[k] = "low_confidence"
            else:
                accepted[k] = {"value": val, "confidence": conf}

        # Parse rejected
        for k, reason in raw_rejected.items():
            if k in candidates:
                rejected[k] = reason

        # Safety net: any key the model forgot to evaluate → reject
        for k in candidates:
            if k not in accepted and k not in rejected:
                log.debug(f"[SKEPTIC] key '{k}' not evaluated — auto-rejecting")
                rejected[k] = "not_evaluated"

        return accepted, rejected, {}

    except json.JSONDecodeError as e:
        log.warning(f"[SKEPTIC] JSON parse failed: {e} — saving to candidates for re-check")
        return {}, {}, candidates
    except Exception as e:
        log.warning(f"[SKEPTIC] unexpected error: {e} — saving to candidates for re-check")
        return {}, {}, candidates


def save_candidate_facts(
    sender_id: str,
    rejected: dict,            # {key: reason_code}
    candidates: dict,          # {key: original_value}
    confidence: float = 0.0,   # 0.0 = skeptic_unavailable; else per-key later
    source_message: str = "",
):
    """
    Persist rejected / unvalidated candidates to fact_candidates.

    score increments each time the same fact is seen — sets up Level 3 promotion.
    confidence=0.0 marks facts that need re-validation (skeptic was unavailable).
    """
    if not rejected:
        return
    try:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        for key, reason in rejected.items():
            value = candidates.get(key, "")
            if not value:
                continue
            conn.execute("""
                INSERT INTO fact_candidates
                    (sender_id, key, value, score, confidence, rejection_reason,
                     source_message, last_seen)
                VALUES (?, ?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(sender_id, key) DO UPDATE SET
                    score            = score + 1,
                    value            = excluded.value,
                    confidence       = MAX(confidence, excluded.confidence),
                    rejection_reason = excluded.rejection_reason,
                    source_message   = excluded.source_message,
                    last_seen        = CURRENT_TIMESTAMP
            """, (sender_id, str(key)[:80], str(value)[:200],
                  confidence, str(reason)[:80], source_message[:300]))
        conn.commit()
        conn.close()
        log.debug(f"[CANDIDATES] {sender_id}: saved {len(rejected)} candidate(s)")
    except Exception as e:
        log.debug(f"[CANDIDATES] save error: {e}")


# ======================================================================

def detect_intent(message: str) -> str:
    """
    Heuristic intent detection — no API call, instant.
    Returns one of: normal_chat | flirt | tease | provoke |
                    emotional | attention_seek | flex | complaint
    """
    msg = message.lower()

    # Each group: if ANY keyword matches, return that intent
    if any(k in msg for k in [
        "nhớ em", "thương em", "thích em", "yêu em", "miss em",
        "đẹp quá", "cute quá", "xinh quá", "anh thích", "anh nhớ",
    ]):
        return "flirt"

    if any(k in msg for k in [
        "người đẹp", "con gái kia", "có người nhắn", "bạn nhắn",
        "crush nhắn", "nhắn anh", "thích anh", "chọc em",
    ]):
        return "provoke"

    if any(k in msg for k in [
        "buồn", "mệt", "stress", "khóc", "thất vọng", "chán",
        "tệ quá", "tệ vl", "nản", "lo lắng", "sợ",
    ]):
        return "emotional"

    if any(k in msg for k in [
        "haha", "lmao", "hehe", "hihi", "ngu thật", "gà vl",
        "trêu", "đùa", "troll",
    ]):
        return "tease"

    if any(k in msg for k in [
        "tăng lương", "được khen", "thắng", "làm được rồi",
        "pass", "giỏi vl", "ez", "gg", "flex",
    ]):
        return "flex"

    if any(k in msg for k in [
        "chán vl", "tức", "fail", "hỏng", "xui vl", "annoying",
        "mệt mỏi", "bực", "ghét",
    ]):
        return "complaint"

    if any(k in msg for k in [
        "không ai", "cô đơn", "một mình", "ai quan tâm",
        "nhớ anh", "ai nhắn", "buồn một mình",
    ]):
        return "attention_seek"

    return "normal_chat"


# Per-intent guidance injected AFTER build_system_prompt
_INTENT_GUIDANCE = {
    "normal_chat": """

## INTENT: normal_chat
Trò chuyện bình thường.
Không overreact.
Tự nhiên, đúng ngữ cảnh.
""",
    "flirt": """

## INTENT: flirt
Anh đang thả thính hoặc nói ngọt.
Không đổ ngay.
Có thể: né nhẹ / ngại nhẹ / tease ngược / bắt bẻ.
Ví dụ vibe: "văn mẫu ở đâu đấy 😐" / "anh nói câu này với bao người rồi"
""",
    "tease": """

## INTENT: tease
Anh đang trêu hoặc đùa.
Cà khịa lại / phản đòn nhẹ / nghịch hơn bình thường.
Không nghiêm túc hóa câu đùa.
""",
    "provoke": """

## INTENT: provoke
Anh đang cố chọc ghen hoặc khoe có người quan tâm.
KHÔNG phản ứng: "vậy à" / "hay quá" / "chúc mừng anh".
Thay vào đó: giả vờ không quan tâm / nói móc nhẹ / dỗi nhẹ.
Ví dụ: "ghê vậy 😐" / "thế thì nhắn với người ta đi" / "em thấy anh khoe là chính"
""",
    "emotional": """

## INTENT: emotional
Anh đang buồn / mệt / stress.
Ưu tiên: quan tâm, lắng nghe, dịu hơn bình thường.
Không chuyển thành joke.
Không đưa giải pháp ngay — chỉ ở đó.
""",
    "attention_seek": """

## INTENT: attention_seek
Anh đang tìm sự chú ý hoặc muốn được quan tâm.
Có thể hỏi han, phản hồi cảm xúc.
Nhưng không quá nuông chiều.
""",
    "flex": """

## INTENT: flex
Anh đang khoe thành tích hoặc chuyện vui.
Có thể công nhận nhẹ nhàng.
Không tâng bốc quá mức.
Ví dụ: "cũng ghê đấy" / "được nha 😐" / "thế là ngon rồi"
""",
    "complaint": """

## INTENT: complaint
Anh đang than phiền.
Ưu tiên đồng cảm, hỏi tiếp nếu hợp lý.
Không đổi chủ đề ngay.
""",
}


def build_intent_prompt(intent: str) -> str:
    """Return intent-specific guidance to append after build_system_prompt."""
    return _INTENT_GUIDANCE.get(intent, _INTENT_GUIDANCE["normal_chat"])


# ==================== AI ====================

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
        "ke", "noi", "ke tiep", "noi tiep", "di ngu", "nghi di",
        "thu di", "xem di", "doc di", "lam di"
    ]
    for verb in command_verbs:
        pattern = rf"(thoi\s+)em(\s+{re.escape(verb)}\s+di)"
        fixed = re.sub(pattern, rf"\1anh\2", text, flags=re.IGNORECASE)
        if fixed != text:
            log.warning(f"[PRONOUN FIX] corrected role flip in: {repr(text)}")
            text = fixed
    return text


def call_groq_ai(sender_id: str, user_message: str):

    update_user_state(sender_id, user_message)
    intent = detect_intent(user_message)
    log.info(f"[INTENT] {intent}")

    # Level 2: Score previous response based on how user replied
    last_exp = get_last_unscored_experience(sender_id)
    outcome = None
    if last_exp:
        outcome = detect_outcome_score(user_message)
        update_experience_outcome(last_exp["id"], outcome)
        log.info(f"[OUTCOME] exp#{last_exp['id']} -> {outcome:+d}")

        # Level 7: Quick belief nudge from strong outcomes
        if abs(outcome) >= 2:
            relevant_b = get_relevant_beliefs(sender_id, last_exp["user_message"], limit=3)
            delta = +0.04 if outcome > 0 else -0.08
            for b in relevant_b:
                update_belief_confidence(sender_id, b["id"], delta)

    # Level 5: Pull relevant beliefs → behavioral guidance
    belief_block = build_belief_prompt(sender_id, user_message)

    # Expansion module: Opinion/Identity system (BOM 17/18/19) — run one
    # tradeoff/reflection step for this turn and surface the inner identity
    # drift in the system prompt.
    opinion_block = ""
    try:
        opinion_decisions = get_mind(sender_id).get_decisions(get_user_state(sender_id))
        opinion_sys = get_opinion_system(sender_id)
        opinion_sys.process_turn(opinion_decisions, last_outcome=outcome)
        opinion_block = opinion_sys.for_prompt()
    except Exception as e:
        log.error(f"[OPINION] turn processing failed: {e}")

    system = (
        build_system_prompt(sender_id, user_message)
        + build_intent_prompt(intent)
        + belief_block
        + opinion_block
    )

    save_message(sender_id, "user", user_message)
    history = get_history(sender_id)

    log.info("[GROQ] sending request")
    ai_text = _call_groq(system, history)
    log.info(f"[GROQ] response: {repr(ai_text)}")

    save_message(sender_id, "assistant", ai_text)

    # Level 1: Log this interaction as an experience
    exp_id = log_experience(sender_id, user_message, intent, ai_text)
    log.info(f"[EXPERIENCE] logged #{exp_id}")

    background_learning_async(sender_id, user_message)

    # Level 3: Trigger reflection if threshold reached
    maybe_reflect(sender_id)

    return ai_text



def call_groq_followup(sender_id: str) -> str:
    history = get_history(sender_id)
    if not history:
        return ""
    system = build_system_prompt(sender_id, "")
    followup_hint = {"role": "user", "content": "[Anh chưa trả lời. Em nhắn thêm một tin thật ngắn, thật tự nhiên — một suy nghĩ vặt hoặc câu hỏi nhẹ. Không tỏ ra đang đợi.]"}
    ai_text = _call_groq(system, history + [followup_hint], max_tokens=80)
    if ai_text and ai_text != "...":
        save_message(sender_id, "assistant", ai_text)
    return ai_text


def strip_thinking(text: str) -> str:
    """Xoá <think> blocks — kể cả khi không có </think> (bị cắt do max_tokens)."""
    # Trường hợp 1: có đủ cặp <think>...</think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Trường hợp 2: có <think> nhưng </think> bị cắt mất — xoá toàn bộ từ đó trở đi
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\*.*?\*', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    return text.strip()


def _call_groq(system: str, messages: list, max_tokens: int = 512) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": (
                    system
                    + "\n\nIMPORTANT:\n"
                    + "- user is male\n"
                    + "- call user 'anh', his name is Thắng\n"
                    + "- call yourself 'em'\n"
                    + "- NEVER call the user 'em'\n"
                    + "- NEVER swap genders\n"
                )
            }
        ] + messages,
        "temperature": 0.82,
        "max_tokens": max_tokens,
        "top_p": 0.93,
        "frequency_penalty": 1.2,
        "presence_penalty": 0.9,
        "stop": ["User:", "Tuệ Mẫn:", "\n\n\n"],
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                    raw = res.json()["choices"][0]["message"]["content"]
                
                    log.info(f"[RAW_GROQ] {repr(raw)}")
                
                    cleaned = strip_thinking(raw)
                
                    log.info(f"[CLEAN_GROQ] {repr(cleaned)}")
                
                    return cleaned
            elif res.status_code == 429:
                wait = 2 ** attempt   # 1s → 2s → 4s
                log.warning(f"Groq rate limit (429), retry {attempt+1}/{max_retries} in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"Groq error {res.status_code}: {res.text}")
                return "..."
        except Exception as e:
            log.error(f"Groq exception (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    return "..."
def call_deep_ai(question):
    return _call_groq(
        DEEP_SYSTEM_PROMPT,
        [
            {
                "role": "user",
                "content": question
            }
        ],
        max_tokens=400
    )
# ==================== FOLLOW-UP TIMER ====================
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


# ==================== FACEBOOK ====================

def send_typing_on(recipient_id: str):
    """Gửi trạng thái 'đang nhắn' để trông thật hơn."""
    requests.post(
        f"https://graph.facebook.com/v19.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}",
        json={"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
        timeout=5
    )


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


def send_fb_message_parts(recipient_id: str, raw_response: str):
    parts = parse_messages(raw_response)
    for i, part in enumerate(parts):
        part = fix_pronoun_flip(part)  # catch role-flip before sending
        send_typing_on(recipient_id)
        human_typing_delay(part)
        send_fb_message(recipient_id, part)
        if i < len(parts) - 1:
            time.sleep(random.uniform(0.6, 1.4))


# ==================== ROUTES ====================

@app.route("/admin")
def admin():
    """Admin page — xem conversations gần đây. Truy cập: /admin?token=ADMIN_TOKEN"""
    if request.args.get("token") != ADMIN_TOKEN:
        return "Unauthorized", 401

    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()

    # Danh sách users + tin nhắn cuối
    c.execute("""
        SELECT sender_id, MAX(ts) as last_ts, COUNT(*) as total
        FROM history GROUP BY sender_id ORDER BY last_ts DESC
    """)
    users = c.fetchall()

    html = """
    <html><head><meta charset="utf-8">
    <title>Bot Admin</title>
    <style>
        body{font-family:monospace;background:#111;color:#eee;padding:20px;max-width:900px;margin:0 auto}
        h1{color:#e86c99}h2{color:#5ecfb0;border-bottom:1px solid #333;padding-bottom:6px}
        .msg{margin:4px 0;padding:6px 10px;border-radius:6px}
        .user{background:#1a2a1a;color:#7defa7}.bot{background:#1a1a2a;color:#aac4ff}
        .ts{color:#555;font-size:11px;margin-left:8px}.facts{color:#f0a84a;font-size:12px}
        a{color:#e86c99}hr{border-color:#333}
    </style></head><body>
    <h1>🎀 Tue Man Admin</h1>
    """

    for sender_id, last_ts, total in users:
        html += f'<h2>👤 {sender_id} <span style="font-size:13px;color:#555">({total} msgs · last: {last_ts})</span></h2>'

        # Facts with importance
        c.execute("SELECT key, value, importance FROM facts WHERE sender_id=? ORDER BY importance DESC", (sender_id,))
        facts = c.fetchall()
        if facts:
            fact_str = " · ".join(f"{k}: {v} [{i}]" for k, v, i in facts)
            html += f'<div class="facts">📌 {fact_str}</div>'

        # Level 5: Fact candidates (rejected — pending accumulation)
        c.execute(
            "SELECT key, value, score, rejection_reason FROM fact_candidates "
            "WHERE sender_id=? ORDER BY score DESC LIMIT 10",
            (sender_id,),
        )
        candidate_rows = c.fetchall()
        if candidate_rows:
            cand_str = " · ".join(
                f"{k}: {v} (score={s}, reason={r})" for k, v, s, r in candidate_rows
            )
            html += f'<div class="facts" style="color:#ff8c69">🚫 SKEPTIC CANDIDATES: {cand_str}</div>'

        # Preferences
        c.execute("SELECT category, value, score FROM preferences WHERE sender_id=? ORDER BY score DESC LIMIT 10", (sender_id,))
        pref_rows = c.fetchall()
        if pref_rows:
            pref_str = " · ".join(f"{cat}={val}({score:.0f})" for cat, val, score in pref_rows)
            html += f'<div class="facts" style="color:#c8a4f0">💡 {pref_str}</div>'

        # Top topics
        c.execute("SELECT topic, count FROM topic_stats WHERE sender_id=? ORDER BY count DESC LIMIT 7", (sender_id,))
        topic_rows = c.fetchall()
        if topic_rows:
            topic_str = " · ".join(f"{t}({n}x)" for t, n in topic_rows)
            html += f'<div class="facts" style="color:#f0c080">📊 {topic_str}</div>'

        # Style profile
        c.execute("SELECT reply_length_pref, avg_msg_len, msg_count FROM style_profile WHERE sender_id=?", (sender_id,))
        style_row = c.fetchone()
        if style_row:
            html += f'<div class="facts" style="color:#80d4f0">📏 length_pref={style_row[0]:.0f} avg_msg={style_row[1]:.0f} msgs={style_row[2]}</div>'

        # Beliefs (Level 4)
        c.execute("""
            SELECT belief, confidence, evidence_count FROM beliefs
            WHERE sender_id=? AND confidence > 0.15
            ORDER BY confidence * evidence_count DESC LIMIT 10
        """, (sender_id,))
        belief_rows = c.fetchall()
        if belief_rows:
            html += '<div class="facts" style="color:#a8e6cf;font-weight:bold">🧠 BELIEFS</div>'
            for belief, conf, ev in belief_rows:
                bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
                html += f'<div class="facts" style="color:#a8e6cf">{bar} {conf:.0%} ({ev}ev) — {belief}</div>'

        # Experience stats (Level 1-2)
        c.execute("SELECT COUNT(*), AVG(outcome) FROM experiences WHERE sender_id=? AND outcome IS NOT NULL", (sender_id,))
        exp_row = c.fetchone()
        if exp_row and exp_row[0]:
            avg_o = exp_row[1] or 0
            html += f'<div class="facts" style="color:#ffd3b6">🎯 {exp_row[0]} scored experiences | avg outcome: {avg_o:+.2f}</div>'

        c.execute("""
            SELECT intent, COUNT(*), ROUND(AVG(outcome),2) FROM experiences
            WHERE sender_id=? AND outcome IS NOT NULL
            GROUP BY intent ORDER BY COUNT(*) DESC LIMIT 5
        """, (sender_id,))
        intent_rows = c.fetchall()
        if intent_rows:
            intent_str = " · ".join(f"{i}({n}, avg{o:+.1f})" for i, n, o in intent_rows if i)
            if intent_str:
                html += f'<div class="facts" style="color:#ffd3b6">📈 {intent_str}</div>'


        # Last 20 messages
        c.execute("""
            SELECT role, content, ts FROM history
            WHERE sender_id=? ORDER BY id DESC LIMIT 20
        """, (sender_id,))
        msgs = list(reversed(c.fetchall()))
        for role, content, ts in msgs:
            css = "user" if role == "user" else "bot"
            icon = "👤" if role == "user" else "🤖"
            safe = content.replace("<","&lt;").replace(">","&gt;")
            html += f'<div class="msg {css}">{icon} {safe}<span class="ts">{ts}</span></div>'
        html += "<hr>"

    conn.close()
    html += "</body></html>"
    return html
def process_deep(sender_id: str, question: str):
    try:
        log.info(f"[DEEP] {sender_id}: {question}")

        answer = call_deep_ai(question)

        log.info(f"[DEEP OUT] {answer}")

        send_fb_message_parts(
            sender_id,
            answer
        )

    except Exception as e:
        log.exception(e)
def process_message(sender_id: str, user_text: str):
    try:
        cancel_follow_up(sender_id)
        follow_up_counts[sender_id] = 0

        log.info(f"[IN]  {sender_id}: {user_text}")

        initial_delay = get_initial_delay()

        send_typing_on(sender_id)
        time.sleep(initial_delay)

        ai_response = call_groq_ai(sender_id, user_text)

        log.info(f"[OUT] {ai_response}")

        send_fb_message_parts(sender_id, ai_response)

        schedule_follow_up(sender_id)

    except Exception as e:
        log.exception(e)
@app.route("/", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if request.args.get("hub.verify_token") != VERIFY_TOKEN:
            return "Verification token mismatch", 403
        return request.args.get("hub.challenge"), 200
    return "Tue Man Bot Running", 200


@app.route("/", methods=["POST"])
def webhook():

    data = request.get_json()

    if data.get("object") == "page":

        for entry in data.get("entry", []):

            for event in entry.get("messaging", []):

                if event.get("message", {}).get("is_echo"):
                    continue
                sender_id = event["sender"]["id"]
                message = event.get("message", {})
                user_text = message.get("text")
                
                if not user_text:
                            log.warning(
                                f"[NON TEXT EVENT] {json.dumps(message, ensure_ascii=False)}"
                            )
                            continue
                mid = message.get("mid")

                now = time.time()

                if mid in processed_mids:
                    log.warning(f"[DUPLICATE MID] {mid}")
                    continue

                processed_mids[mid] = now
                if len(processed_mids) > 5000:
                    cutoff = time.time() - 3600
                
                    for k in list(processed_mids.keys()):
                        if processed_mids[k] < cutoff:
                            del processed_mids[k]

                user_text = message.get("text")
                    
                if user_text and user_text.startswith("/athena"):
                    
                        question = user_text[len("/athena"):].strip()
                    
                        threading.Thread(
                            target=process_deep,
                            args=(sender_id, question),
                            daemon=True
                        ).start()
                    
                        continue

                sender_id = event["sender"]["id"]

                threading.Thread(
                    target=process_message,
                    args=(sender_id, user_text),
                    daemon=True
                ).start()
                
    return "ok", 200


# ==================== LEVEL 2-6 v10.0 FINAL ====================
# FIX LOG vs rc3: Fixed 6 SyntaxError/NameError that crash immediately on boot.
# 1. Missing quote in ALTER TABLE.
# 2. Missing table name in ALTER TABLE.
# 3. Missing `)` in CREATE TABLE evidence.
# 4. `DB_TIME` → `DB_TIMEOUT`.
# 5. State vs Polarity mixup in _create(). 
# 6. Wrong args in _calculate_new_state() (was passing belief_id as new_conf).
# 7. INSERT columns mismatch (11 values for 10 columns).
# 8. Negative context too broad → Specific keyword proximity only.
# 9. _get_belief_by_tag() had side-effect (read-only function doing UPDATE).
# 10. Watermark race condition between threads.
# 11. JOIN with exp_id = 0 fails silently.
# 12. Cache race condition safety.

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
# (datetime, time, re đã được import ở đầu bot7_8.py)

# ── SHARED META HELPER ──
def _db_meta_get(key: str, default: int = 0) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT value FROM system_meta WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else default

def _db_meta_set(key: str, value: int):
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    conn.execute("INSERT OR REPLACE INTO system_meta (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


# ── MIGRATION v10.0 FINAL ──
def migrate_belief_system_v10():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    
    c.execute("CREATE TABLE IF NOT EXISTS system_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    # FIX #1, #2: Fixed SQL syntax
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
    ]:
        try: c.execute(ddl)
        except Exception:
            pass

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='belief_connections'")
    if not c.fetchone():
        c.execute("""CREATE TABLE belief_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT NOT NULL,
            from_id INTEGER NOT NULL, to_id INTEGER NOT NULL,
            conn_type TEXT NOT NULL DEFAULT 'related', strength REAL DEFAULT 0.5,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender_id, from_id, to_id, conn_type)
        )""")

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence'")
    if c.fetchone():
        # FIX #3: Fixed CREATE TABLE syntax
        c.execute("PRAGMA table_info(evidence)")
        current_cols = {row[1]: row[2] for row in c.fetchall()} # {name: type}
        
        needs_rebuild = 'exp_id' not in current_cols

        if needs_rebuild:
            log.warning("[MIGRATION] Rebuilding evidence table...")
            c.execute("ALTER TABLE evidence RENAME TO _evidence_old")
            
            old_cols_safe = ["sender_id", "tag", "outcome", "created_at"]
            if "exp_id" in current_cols:
                old_cols_safe.append("exp_id")
            else:
                old_cols_safe.append("0 as exp_id")
            
            c.execute("""CREATE TABLE evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                outcome INTEGER NOT NULL,
                exp_id INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sender_id, tag, exp_id)
            )""")
            c.execute(f"INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id, created_at) SELECT {', '.join(old_cols_safe)} FROM _evidence_old")
            c.execute("DROP TABLE _evidence_old")
    else:
        c.execute("""CREATE TABLE evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            outcome INTEGER NOT NULL,
            exp_id INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender_id, tag, exp_id)
        )""")
    
    # FIX #2: Luôn đảm bảo index tồn tại ở cuối migration
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_ev_time ON evidence(sender_id, created_at)")
    except:
        pass

    c.execute("""CREATE TABLE IF NOT EXISTS user_values (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        value_text TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        evidence_count INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sender_id, value_text)
    )""")

    # ── OPINION/IDENTITY EXPANSION MODULE (ex opinion_system.py) ──
    c.execute("""CREATE TABLE IF NOT EXISTS opinion_state (
        sender_id      TEXT PRIMARY KEY,
        identity_vector TEXT NOT NULL DEFAULT '{}',
        values_state    TEXT NOT NULL DEFAULT '{}',
        hypotheses       TEXT NOT NULL DEFAULT '[]',
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("UPDATE beliefs SET state = 'UNCERTAIN' WHERE confidence < 0.5 AND state = 'CONFIRMED'")
    c.execute("UPDATE beliefs SET state = 'INVESTIGATING' WHERE contradiction_score >= 0.8 AND state != 'INVESTIGATING'")
    c.execute("UPDATE beliefs SET contradiction_score = contradictions * 0.3 WHERE contradiction_score = 0 AND contradictions > 0")
    
    conn.commit()
    conn.close()

migrate_belief_system_v10()
log.info("[BELIEF] Migration v10.0 FINAL OK")

REFL_B_CONFIG = {"min_evidence": 8, "consistency_threshold": 0.3, "run_interval": 30, "lookback_days": 180}
BELIEF_CONFIG = {"min_conf": 0.05, "max_conf": 0.98, "deact_thresh": 0.12, "time_decay_rate": 0.002}
RECENCY_LAMBDA = 0.015

TAG_TO_DOMAIN = {
    "gaming": "interest", "coding": "interest", "game": "interest",
    "roast": "communication", "hint": "communication", "spoil": "communication",
    "challenge": "preference", "khó": "preference",
}

BELIEF_TEMPLATES = {
    "gaming":     {"pos": "Thắng thích nói về game", "neg": "Thắng không hứng thú với game"},
    "coding":     {"pos": "Thắng thích technical topics", "neg": "Thắng chán nói về code"},
    "challenge":  {"pos": "Thắng thích bị thử thách", "neg": "Thắng ghét bị làm khó"},
    "hint":       {"pos": "Thắng thích tự mò thay vì được cho đáp án", "neg": "Thắng muốn đáp án thẳng"},
    "roast":      {"pos": "Thắng thích bị trêu nhẹ", "neg": "Thắng không thích bị roast"},
    "emotional":  {"pos": "Thắng chia sẻ cảm xúc khi tốt", "neg": "Thắng đóng kín khi tệ"},
}

VALUE_INFERENCE = {
    ("hint", 0.7): "Học qua tự khám phá quan trọng hơn đáp án sẵn",
    ("challenge", 0.7): "Thích bị thử thách hơn được dẫn dắt",
}


# ═══════════════════════════════════════════════════════
# REFLECTION A
# FIX #8: Specific keyword proximity check, not broad negation
# ═════════════════════════════════════════════════════

class ReflectionA:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def run(self, exp: dict) -> list[dict]:
        outcome = exp.get("outcome")
        if outcome is None or abs(outcome) < 0.5:
            return []

        tags = self._extract_tags(exp)
        if not tags:
            return []

        self._save_evidence(tags, outcome, exp.get("id") or 0)
        return []
        
    def _extract_tags(self, exp: dict) -> list[str]:
        tags, intent = [], exp.get("intent", "")
        if intent and intent != "normal_chat":
            tags.append(intent)
        
        msg = exp.get("user_message", "").lower()
        
        for tag, kws in {
            "gaming": ["game", "chơi game", "gaming"],
            "coding": ["code", "bug", "lỗi"],
            "challenge": ["khó", "challenge", "thử thách"],
            "hint": ["hint", "gợi ý"],
            "answer": ["đáp án", "trả lời luôn"],
            "roast": ["roast", "cà khịa", "diss"],
            "emotional": ["buồn", "mệt", "stress"]
        }.items():
            for kw in kws:
                if ' ' in kw:
                    if kw in msg:
                        tags.append(tag)
                        break
                else:
                    if re.search(rf'\b{re.escape(kw)}\b', msg):
                        tags.append(tag)
                        break
        return tags

    def _save_evidence(self, tags: list[str], outcome: int, exp_id: int):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO evidence (sender_id, tag, outcome, exp_id) VALUES (?,?,?,?)",
                (self.sender_id, tag[:30], outcome, exp_id)
            )
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════
# REFLECTION B
# FIX #1: Reactivation logic tách riêng
# ═════════════════════════════════════════════════════════

class ReflectionB:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def run(self) -> dict:
        stats, watermarks = self._get_evidence_stats()
        results, insights = [], []
        
        for tag, s in stats.items():
            new_count = s["new_count"]
            if new_count == 0 or s["total_count"] < REFL_B_CONFIG["min_evidence"]:
                continue
                
            pos_rate = s["positive"] / s["total_count"]
            is_pos = pos_rate >= (1 - REFL_B_CONFIG["consistency_threshold"])
            is_neg = pos_rate <= REFL_B_CONFIG["consistency_threshold"]
            if not is_pos and not is_neg:
                continue

            templates = BELIEF_TEMPLATES.get(tag, {"pos": f"Thắng thích {tag}", "neg": f"Thắng không thích {tag}"})
            text = templates["pos"] if is_pos else templates["neg"]
            domain = TAG_TO_DOMAIN.get(tag, "behavior")
            polarity = 1 if is_pos else -1
            consistency = pos_rate if is_pos else (1 - pos_rate)
            delta = min(0.15, 0.025 * (1 + math.log10(1 + new_count / 5)) * consistency)
            insights.append({"tag": tag, "new": new_count, "total": s["total_count"], "pos_rate": pos_rate})

            # FIX #1: Sử dụng hàm reactivate riêng, KHÔNG đọc DB trong hàm get_by_tag
            existing = self._find_and_reactivate_belief(tag, polarity)

            if existing:
                results.append({
                    "tier": "b", "action": "update_belief", "belief_id": existing["id"], "belief_text": text,
                    "reasoning": f"Pattern confirm: +{new_count}ev", "delta": delta, "new_count": new_count
                })
            else:
                confidence = min(BELIEF_CONFIG["max_conf"], delta * 5)
                results.append({
                    "tier": "b", "action": "create_belief", "belief_text": text, "domain": domain, "source_tag": tag, "polarity": polarity,
                    "reasoning": f"Pattern mới: {s['total_count']:.1f}ev", "delta": confidence, "new_count": new_count
                })
                
                for (v_tag, v_thresh), v_text in VALUE_INFERENCE.items():
                    if tag == v_tag and ((v_thresh >= 0.5 and pos_rate >= v_thresh) or (v_thresh < 0.5 and pos_rate <= v_thresh)):
                        results.append({"tier": "b", "action": "create_value", "belief_text": v_text, "delta": consistency * 0.9})

        return {"insights": insights, "results": results, "watermarks": watermarks}

    def commit_watermarks(self, watermarks: dict):
        for key, val in watermarks.items():
            _db_meta_set(key, val)

    def _get_evidence_stats(self) -> tuple[dict, dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("""
            SELECT tag, id, outcome, 
                   CAST((julianday('now') - julianday(created_at)) AS INTEGER) as age_days
            FROM evidence
            WHERE sender_id=? AND created_at > datetime('now', '-180 days')
            ORDER BY id ASC
        """, (self.sender_id,))
        rows = c.fetchall()
        conn.close()

        unique_tags = set(r[0] for r in rows)
        wm_cache = {tag: _db_meta_get(f"{self.sender_id}_wm_{tag}") for tag in unique_tags}

        stats = {}
        watermarks = {}

        for tag, ev_id, outcome, age_days in rows:
            if tag not in stats:
                stats[tag] = {"total_count": 0.0, "positive": 0.0, "new_count": 0, "max_id": 0}
            age_days = max(0, age_days)
            weight = math.exp(-RECENCY_LAMBDA * age_days)
            stats[tag]["total_count"] += weight
            if outcome > 0:
                stats[tag]["positive"] += weight
            if ev_id > stats[tag]["max_id"]:
                stats[tag]["max_id"] = ev_id
                
            last_id = wm_cache.get(tag, 0)
            if ev_id > last_id:
                stats[tag]["new_count"] += 1
                watermarks[f"{self.sender_id}_wm_{tag}"] = ev_id

        return stats, watermarks

    # FIX #1: Tách hàm đọc DB và hàm reactivate riêng
    def _find_and_reactivate_belief(self, tag: str, new_polarity: int) -> dict | None:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        # Sort by confidence DESC để trả về belief mạnh nhất nếu có nhiều inactive cùng source_tag
        c.execute("""
            SELECT id, belief, confidence, polarity, state
            FROM beliefs
            WHERE source_tag=?
            ORDER BY confidence DESC
        """, (tag,))
        rows = c.fetchall()
        conn.close()

        for row in rows:
            bid, belief_text, conf, pol, state = row
            # FIX #1: Chỉ reactivate nếu polarity khớp và state là DEAD hoặc INVESTIGATING
            if pol == new_polarity and state in ('DEAD', 'INVESTIGATING'):
                conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
                c = conn.cursor()
                c.execute(
                    "UPDATE beliefs SET active=1, state='CONFIRMED', confidence=MAX(confidence, 0.2), last_confirmed=CURRENT_TIMESTAMP WHERE id=?",
                    (bid,)
                )
                conn.commit()
                conn.close()
                log.info(f"[BELIEF:REACTIVATED] Reactivated '{belief_text}' (id={bid})")
                return {"id": bid, "belief": belief_text}

            if pol == new_polarity and state == 'CONFIRMED':
                return {"id": bid, "belief": belief_text}

        return None

    def _get_belief_by_tag_legacy(self, tag: str) -> dict | None:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, belief FROM beliefs WHERE sender_id=? AND active=1 AND source_tag=? LIMIT 1", (self.sender_id, tag))
        row = c.fetchone()
        conn.close()
        return {"id": row[0], "belief": row[1]} if row else None


# ═══════════════════════════════════════════════════════
# BELIEF SYSTEM v10.0
# FIX #4, #5, #6
# ═════════════════════════════════════════════════════════════

class BeliefSystem:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def apply(self, results: list[dict]):
        for r in results:
            action = r.get("action")
            if action == "create_belief": self._create(r)
            elif action == "update_belief": self._update(r)
            elif action == "flag_contradiction": self._contradict(r)
            elif action == "deactivate_belief": self._deactivate(r)
            elif action == "create_value": self._create_value(r)
            elif action == "split_belief": self._split(r)

    # FIX #4: Sửa logic đúng: lấy (state, score, delta, conf) thay vì (id, score, delta, id)
    def _calculate_new_state(self, current_state: str, current_score: float, score_delta: float, new_conf: float) -> str:
        new_score = max(0.0, min(1.0, current_score + score_delta))
        if new_score <= 0.1: return 'CONFIRMED' if new_conf > 0.5 else 'UNCERTAIN'
        if new_score >= 0.8: return 'INVESTIGATING'
        if new_score >= 0.3: return 'UNCERTAIN'
        return current_state

    def _create(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.3)))
        polarity = r.get("polarity", 1)
        source_tag = r.get("source_tag", "")
        
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        
        conflict_row = None
        if source_tag:
            # FIX #4: Sửa query và logic đối xứng
            c.execute("""
                SELECT id, contradiction_score, state, polarity, confidence
                FROM beliefs
                WHERE source_tag=?
            """, (source_tag,))
            
            for row in c.fetchall():
                if row[3] != polarity: # row[3] = polarity
                    # FIX #4: Tăng score VÀ update state cho old belief ngay khi tạo belief đối nghịch
                    new_score = min(1.0, row[1] + 0.3)
                    new_state = self._calculate_new_state(row[2], row[1], 0.3, row[4])
                    c.execute("UPDATE beliefs SET contradiction_score=?, state=? WHERE id=?", (new_score, new_state, row[0]))
                    log.warning(f"[POLARITY_CONFLICT] Marking old belief id={row[0]} as UNCERTAIN")

        # FIX #7: INSERT với đúng số cột
        c.execute("""
            INSERT INTO beliefs
                (sender_id, belief, confidence, evidence_count, source, domain, source_tag, polarity, state, contradiction_score)
            VALUES (?, ?, ?, ?, 'reflection_b', ?, ?, ?, 'CONFIRMED', ?)
        """, 
            (self.sender_id, r["belief_text"][:200], conf, r.get("new_count", 1),
             r.get("domain", "behavior")[:30], source_tag[:30], polarity, 0.3 if conflict_row else 0.0)
        )
        conn.commit()
        conn.close()

    def _update(self, r: dict):
        new_count = r.get("new_count", 1)
        delta = r.get("delta", 0.05)
        
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row:
            conn.close()
            return
            
        old_conf, old_score, old_state = row
        new_conf = min(BELIEF_CONFIG["max_conf"], old_conf + delta)
        new_state = self._calculate_new_state(old_state, old_score, -delta * 2, new_conf) # FIX #4: Đúng tham số
        c.execute("""
            UPDATE beliefs
            SET confidence = ?,
                evidence_count = evidence_count + ?,
                contradiction_score = MAX(0, ?),
                state = ?,
                last_confirmed = CURRENT_TIMESTAMP
            WHERE id=?
        """, 
            (new_conf, new_count, old_score - (delta * 2), new_state, r["belief_id"])
        )
        conn.commit()
        conn.close()

    def _contradict(self, r: dict):
        delta = r.get("delta", -0.1)
        abs_delta = abs(delta)
        
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT confidence, contradiction_score, state FROM beliefs WHERE id=?", (r["belief_id"],))
        row = c.fetchone()
        if not row:
            conn.close()
            return
            
        old_conf, old_score, old_state = row
        new_conf = max(BELIEF_CONFIG["min_conf"], old_conf + delta)
        new_state = self._calculate_new_state(old_state, old_score, abs_delta * 1.5, new_conf)
        
        c.execute("""
            UPDATE beliefs
            SET confidence = ?,
                contradictions = contradictions + 1,
                contradiction_score = MIN(1.0, ?),
                state = ?
            WHERE id = ?
        """, 
            (new_conf, old_score + (abs_delta * 1.5), new_state, r["belief_id"])
        )
        conn.commit()
        conn.close()

    def _deactivate(self, r: dict):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], r["belief_id"]))
        conn.commit()
        conn.close()

    def _create_value(self, r: dict):
        conf = max(BELIEF_CONFIG["min_conf"], min(BELIEF_CONFIG["max_conf"], r.get("delta", 0.5)))
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute("""
            INSERT INTO user_values (sender_id, value_text, confidence, evidence_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(sender_id, value_text)
            DO UPDATE SET
                confidence = MAX(confidence, excluded.confidence),
                evidence_count = evidence_count + 1
        """,
            (self.sender_id, r["belief_text"][:200], conf)
        )
        conn.commit()
        conn.close()

    def _split(self, r: dict):
        self._deactivate({"belief_id": r["old_belief_id"], "belief_text": r["old_belief_text"]})
        for new_b in r["new_beliefs"]:
            self._create({"belief_text": new_b["text"], "domain": r.get("domain", "preference"), "source_tag": r.get("source_tag", ""), "polarity": new_b["polarity"], "delta": new_b["confidence"], "new_count": new_b["count"]})
        log.info(f"[BELIEF:SPLIT] '{r['old_belief_text']}' -> {len(r['new_beliefs'])} context beliefs")

    def decay(self):
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT id, confidence, last_confirmed, last_decay_check FROM beliefs WHERE sender_id=? AND active=1", (self.sender_id,))
        to_deactivate = []
        now = datetime.datetime.now()
        for row in c.fetchall():
            bid, conf, last_conf_str, last_decay_str = row
            try:
                dt_conf = datetime.datetime.strptime(last_conf_str, "%Y-%m-%d %H:%M:%S")
            except:
                dt_conf = now
            try:
                dt_decay = datetime.datetime.strptime(last_decay_str, "%Y-%m-%d %H:%M:%S")
            except:
                dt_decay = now
                
            days_since = (now - max(dt_conf, dt_decay)).days
            if days_since > 0:
                # FIX #6: Clamp để không bao giờ âm
                new_conf = max(0.0, conf - (BELIEF_CONFIG["time_decay_rate"] * days_since))
                if new_conf <= BELIEF_CONFIG["deact_thresh"]:
                    to_deactivate.append(bid)
                else:
                    c.execute(
                        "UPDATE beliefs SET confidence=?, last_decay_check=CURRENT_TIMESTAMP WHERE id=?",
                        (new_conf, bid)
                    )
        for bid in to_deactivate:
            c.execute("UPDATE beliefs SET active=0, confidence=?, state='DEAD' WHERE id=?", (BELIEF_CONFIG["min_conf"], bid))
            
        c.execute("DELETE FROM evidence WHERE sender_id=? AND created_at < datetime('now', '-180 days')", (self.sender_id,))
        conn.commit()
        conn.close()


class ContradictionEngine:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def check_for_splits(self) -> list[dict]:
        results = []
        beliefs = self._get_investigating_beliefs()
        for belief in beliefs:
            if not belief["source_tag"]:
                continue
            
            intent_stats = self._analyze_by_intent(belief["source_tag"])
            if len(intent_stats) < 2:
                continue
                
            pos_contexts = [k for k, v in intent_stats.items() if v["avg"] > 0.5 and v["count"] >= 5]
            neg_contexts = [k for k, v in intent_stats.items() if v["avg"] < -0.5 and v["count"] >= 5]
            
            if pos_contexts and neg_contexts:
                old_text = belief["belief"]
                new_beliefs = [
                    {"text": f"{old_text} khi {ctx}", "polarity": 1, "confidence": intent_stats[ctx]["avg"] * 0.7, "count": intent_stats[ctx]["count"]}
                    for ctx in pos_contexts
                ]
                new_beliefs += [
                    {"text": f"{old_text} bị né khi {ctx}", "polarity": -1, "confidence": abs(intent_stats[ctx]["avg"]) * 0.7, "count": intent_stats[ctx]["count"]}
                    for ctx in neg_contexts
                ]
                
                results.append({
                    "tier": "c",
                    "action": "split_belief",
                    "old_belief_id": belief["id"],
                    "old_belief_text": old_text,
                    "new_beliefs": new_beliefs,
                    "domain": belief["domain"],
                    "source_tag": belief["source_tag"]
                })
                
        return results

    def _get_investigating_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute(
            "SELECT id, belief, source_tag, domain FROM beliefs WHERE sender_id=? AND active=1 AND state='INVESTIGATING' AND evidence_count >= 15",
            (self.sender_id,)
        )
        rows = c.fetchall()
        conn.close()
        return [{"id": r[0], "belief": r[1], "source_tag": r[2], "domain": r[3]} for r in rows]

    def _analyze_by_intent(self, tag: str) -> dict:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("""
            SELECT AVG(e.outcome), ex.intent, COUNT(*) as cnt
            FROM evidence e
            JOIN experiences ex ON e.exp_id = ex.id AND e.sender_id = ex.sender_id
            WHERE e.sender_id=? AND e.tag=? AND ex.intent IS NOT NULL AND ex.intent != 'normal_chat'
            GROUP BY ex.intent
            HAVING cnt >= 5
        """, (self.sender_id, tag))
        stats = {}
        for avg_out, intent, cnt in c.fetchall():
            stats[intent] = {"avg": avg_out, "count": cnt}
        conn.close()
        return stats


# ═════════════════════════════════════════════════════════════════

class DecisionEngine:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def calculate(self, user_state: dict) -> dict:
        beliefs = self._get_actionable_beliefs()
        mood = user_state.get("mood", "neutral")
        relationship = user_state.get("relationship", 50)
        recent_events = user_state.get("emotional_events", [])
        
        mood_factor = self._get_mood_factor(mood, recent_events)
        rel_factor = self._get_relationship_factor(relationship)
        
        decisions = {
            "mode": "default",
            "roast_score": 0.0,
            "hint_score": 0.0,
            "challenge_score": 0.0,
            "flirt_defense": "MEDIUM",
            "tsundere_level": 0.5,
            "warmth_score": 0.5
        }

        # Symmetric scoring cho tất cả
        roast_b = self._find_belief(beliefs, "roast")
        if roast_b:
            base = roast_b["confidence"] if roast_b["polarity"] == 1 else -roast_b["confidence"]
            decisions["roast_score"] = max(0.0, base * rel_factor * mood_factor["roast"])
            
        hint_b = self._find_belief(beliefs, "hint")
        if hint_b:
            if hint_b["polarity"] == 1:
                decisions["hint_score"] = hint_b["confidence"] * mood_factor["cognitive"]
            else:
                decisions["hint_score"] = -hint_b["confidence"] * mood_factor["cognitive"]
            if decisions["hint_score"] > 0.6:
                decisions["mode"] = "explorer"

        challenge_b = self._find_belief(beliefs, "challenge")
        if challenge_b:
            if challenge_b["polarity"] == 1:
                decisions["challenge_score"] = challenge_b["confidence"] * mood_factor["challenge"]
            else:
                decisions["challenge_score"] = -challenge_b["confidence"] * mood_factor["challenge"]
            if decisions["challenge_score"] > 0.6 and decisions["mode"] == "default":
                decisions["mode"] = "challenger"

        flirt_b = self._find_belief(beliefs, "flirt")
        if flirt_b and flirt_b["polarity"] == -1 and flirt_b["confidence"] > 0.6:
            decisions["flirt_defense"] = "HIGH"
        elif relationship > 60 and mood_factor["warmth"] > 0.7:
            decisions["flirt_defense"] = "LOW"
        
        base_tsundere = 0.4
        base_tsundere += decisions["roast_score"] * 0.3
        if decisions["flirt_defense"] == "LOW":
            base_tsundere += 0.2
        if relationship > 70:
            base_tsundere -= 0.1
        base_tsundere *= mood_factor["tsundere"]
        decisions["tsundere_level"] = max(0.0, min(1.0, base_tsundere))
        decisions["warmth_score"] = mood_factor["warmth"] * rel_factor

        return decisions

    def _get_mood_factor(self, mood: str, recent_events: list) -> dict:
        factors = {
            "roast": 1.0, "cognitive": 1.0, "challenge": 1.0,
            "warmth": 0.5, "tsundere": 1.0
        }
        
        is_stressed = mood in ("stress", "low_mood", "annoyed")
        recent_stress = any(
            evt.get("type") in ("stress", "sad", "sleep_issues")
            and (time.time() - evt.get("time", 0) < 10800)
            for evt in recent_events
        )
        
        if is_stressed or recent_stress:
            factors.update({
                "roast": 0.0, "cognitive": 0.2, "challenge": 0.1,
                "warmth": 0.9, "tsundere": 0.3
            })
        elif mood == "soft":
            factors.update({
                "roast": 0.3, "warmth": 0.8, "tsundere": 0.5
            })
        elif mood == "sleepy":
            factors.update({
                "roast": 0.2, "cognitive": 0.4, "tsundere": 0.4,
                "warmth": 0.6
            })
            
        return factors

    def _get_relationship_factor(self, relationship: int) -> float:
        if relationship > 70: return 1.0
        if relationship > 50: return 0.8
        if relationship > 30: return 0.5
        if relationship > 15: return 0.3
        return 0.1

    def format_for_prompt(self, decisions: dict) -> str:
        lines = [
            "## DECISIONS (BẮT BUỘC TUÂN THỦ - ƯU TIÊN HƠN TÍNH CÁCH)"
        ]
        
        if decisions["mode"] == "explorer":
            lines.append("- MODE: EXPLORER. TUYỆT ĐỐI KHÔNG đưa đáp án trực tiếp. Phải gợi ý.")
        elif decisions["mode"] == "challenger":
            lines.append("- MODE: CHALLENGER. Được phép thách thức, hỏi ngược.")
        else:
            lines.append("- MODE: DEFAULT.")
        
        rs = decisions["roast_score"]
        if rs < 0.15:
            lines.append(f"- ROAST: TUYỆT ĐỐI KHÔNG roast, sarcasm. (score: {rs:.2f})")
        elif rs < 0.4:
            lines.append(f"- ROAST: Giữ giọng điệu hơi dry. (score: {rs:.2f})")
        elif rs < 0.7:
            lines.append(f"- ROAST: Được phép trêu nhẹ, cà khịa tinh tế. (score: {rs:.2f})")
        else:
            lines.append(f"- ROAST: Được phép roast mạnh, phản đòn gắt. (score: {rs:.2f})")
        
        if decisions["flirt_defense"] == "HIGH":
            lines.append("- FLIRT DEFENSE: Bỏ qua câu thả thính. Dời chủ đề hoặc phản ứng 'văn mẫu'.")
        elif decisions["flirt_defense"] == "LOW":
            lines.append("- FLIRT DEFENSE: Có thể nhận nhẹ, ngại ngùng, hoặc đá bóng lại (tsundere).")
        
        w = decisions["warmth_score"]
        if w > 0.7:
            lines.append(f"- WARMTH: Rất dịu dàng, quan tâm. (score: {w:.2f})")
        elif w < 0.3:
            lines.append(f"- WARMTH: Giữ khoảng cách. (score: {w:.2f})")
        
        lines.append(f"- TSUNDERE: {decisions['tsundere_level']:.2f}/1.0")
        return "\n".join(lines)

    def _get_actionable_beliefs(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        # FIX #5: Sort by confidence DESC để không random first-match
        c.execute("""
            SELECT belief, confidence, polarity, state, source_tag
            FROM beliefs
            WHERE sender_id=? AND active=1 AND state != 'DEAD' AND confidence > 0.4
            ORDER BY confidence DESC
        """, (self.sender_id,))
        rows = c.fetchall()
        conn.close()
        return [{"belief": r[0], "confidence": r[1], "polarity": r[2], "state": r[3], "source_tag": r[4]} for r in rows]

    def _find_belief(self, beliefs: list[dict], keyword: str) -> dict | None:
        for b in beliefs:
            if b.get("source_tag") == keyword:
                return b
        for b in beliefs:
            if keyword in b["belief"].lower():
                return b
        return None


# ══════════════════════════════════════════════════════════════════════════
# MIND v10.0 ORCHESTRATOR
# FIX #8: True LRU time-tracked eviction
# ════════════════════════════════════════════════════════

class MindLevel2_4:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.refl_a = ReflectionA(sender_id)
        self.refl_b = ReflectionB(sender_id)
        self.contradiction_engine = ContradictionEngine(sender_id)
        self.beliefs = BeliefSystem(sender_id)
        self.network = BeliefNetwork(sender_id) 
        self.decision_engine = DecisionEngine(sender_id)

    def _get_meta(self, key: str, default: int = 0) -> int:
        return _db_meta_get(f"{self.sender_id}_{key}", default)

    def _set_meta(self, key: str, value: int):
        _db_meta_set(f"{self.sender_id}_{key}", value)

    def process(self, exp: dict) -> list[dict]:
        self.refl_a.run(exp)
        current_max_id = exp.get("id", 0)
        if not current_max_id:
            return []

        if current_max_id - self._get_meta("last_run_b") >= REFL_B_CONFIG["run_interval"]:
            b_res = self.refl_b.run()
            try:
                self.beliefs.apply(b_res["results"])
                self.refl_b.commit_watermarks(b_res["watermarks"])
                self._set_meta("last_run_b", current_max_id)
            except Exception as e:
                log.error(f"[MIND] Refl B apply failed. Watermarks NOT committed. Err: {e}")

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

    def get_decisions(self, user_state: dict) -> dict:
        return self.decision_engine.calculate(user_state)

    def for_prompt(self, user_state: dict) -> str:
        decisions = self.get_decisions(user_state)
        decision_block = self.decision_engine.format_for_prompt(decisions)
        
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT value_text, confidence, evidence_count FROM user_values WHERE sender_id=? AND confidence > 0.4 ORDER BY confidence DESC", (self.sender_id,))
        values = c.fetchall()
        c.execute("SELECT belief, confidence, evidence_count, domain, contradictions, polarity, state FROM beliefs WHERE sender_id=? AND active=1 AND confidence > 0.4 ORDER BY confidence DESC LIMIT 10", (self.sender_id,))
        beliefs = c.fetchall()
        conn.close()

        lines = [decision_block, ""]
        if values:
            lines.append("## CORE VALUES")
            for v, conf, ev in values:
                lines.append(f"  - {v} [{conf:.0%}, {ev}x]")
            lines.append("")
            
        if beliefs:
            lines.append("## BEHAVIORAL BELIEFS")
            for b, conf, ev, dom, con, pol, state in beliefs:
                warn = f" ⚠{con}" if con > 0 else ""
                state_tag = f" [{state}]" if state != "CONFIRMED" else ""
                lines.append(f"  - [{conf:.0%}] {b} (ev:{ev}, pol:{'+'if pol==1 else '-'}{state_tag}{warn})")
        
        if len(lines) <= 1:
            return ""
            
        return "\n".join(lines) + "\n(Áp dụng ngầm, KHÔNG nhắc trực tiếp)"


MAX_MIND_CACHE = 500

_mind_cache: dict[str, tuple[MindLevel2_4, float]] = {}

def get_mind(sender_id: str) -> MindLevel2_4:
    now = time.time()
    if sender_id in _mind_cache:
        mind, _ = _mind_cache[sender_id]
        _mind_cache[sender_id] = (mind, now)  # Update access time

    if sender_id not in _mind_cache:
        # FIX #8: True LRU eviction by timestamp
        if len(_mind_cache) >= MAX_MIND_CACHE:
            lru_id = min(_mind_cache, key=lambda k: _mind_cache[k][1])
            del _mind_cache[lru_id]

        _mind_cache[sender_id] = (MindLevel2_4(sender_id), now)

    return _mind_cache[sender_id][0]


class BeliefNetwork:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id

    def connect(self, from_id: int, to_id: int, conn_type: str = "related", strength: float = 0.5):
        if from_id == to_id:
            return
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
        conn.execute(
            "INSERT OR IGNORE INTO belief_connections (sender_id, from_id, to_id, conn_type, strength) VALUES (?,?,?,?,?)",
            (self.sender_id, from_id, to_id, conn_type, strength)
        )
        if conn.total_changes == 0:
            conn.execute(
                "UPDATE belief_connections SET strength = MIN(1.0, (strength + ?) / 2 + 0.05) "
                "WHERE sender_id=? AND from_id=? AND to_id=? AND conn_type=?",
                (strength, self.sender_id, from_id, to_id, conn_type)
            )
        conn.commit()
        conn.close()


# ══════════════════════════════════════════════════════════

def build_belief_prompt_v10(sender_id: str, user_message: str = "") -> str:
    state = get_user_state(sender_id)
    return get_mind(sender_id).for_prompt(state)

def get_relevant_beliefs_v10(sender_id: str, user_message: str, limit: int = 5) -> list[dict]:
    return []

build_belief_prompt = build_belief_prompt_v10
get_relevant_beliefs = get_relevant_beliefs_v10


# ══════════════════════════════════════════════════════════════════════════
# EXPANSION MODULE: OPINION / IDENTITY SYSTEM (ex opinion_system.py)
# Self-correcting cognitive architecture, ported in as a DLC module:
#   - BOM 17: Cognitive Dissonance  (reality check stops runaway tradeoffs)
#   - BOM 18: Identity Vector       (weighted archetype distribution)
#   - BOM 19: True Reflection Loop  (Pattern -> Hypothesis -> Test -> Revision)
#
# State is persisted per-user in the `opinion_state` table (see
# migrate_belief_system_v10) and cached via get_opinion_system(), the same
# pattern used by get_mind(). Its output is appended to the AI system prompt
# from inside call_groq_ai() via OpinionSystem.for_prompt().
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class OpinionConcept:
    id: str
    name: str

OPINION_CONCEPTS = {
    "independence": OpinionConcept("independence", "Independence"),
    "social": OpinionConcept("social", "Social Connection"),
    "growth": OpinionConcept("growth", "Growth"),
}


@dataclass
class OpinionValue:
    id: str
    core_concept_id: str
    tradeoff_wins: int = 0
    tradeoff_losses: int = 0
    accumulated_cost: float = 0.0

    @property
    def importance(self) -> float:
        total = self.tradeoff_wins + self.tradeoff_losses
        if total == 0: return 0.5
        ratio = self.tradeoff_wins / total
        stability = 1 - math.exp(-total / 20.0)
        return max(0.0, min(1.0, 0.5 + (ratio - 0.5) * stability))

    def heal_cost(self, amount: float):
        self.accumulated_cost = max(0.0, self.accumulated_cost - amount)


@dataclass
class OpinionAction:
    id: str
    name: str
    value_impacts: Dict[str, float] = field(default_factory=dict)


class IdentityEngine:
    """FIX BOM 18: Identity Vector — weighted archetype distribution
    instead of a single discrete trait."""

    def __init__(self):
        # Mỗi archetype ảnh hưởng thế nào đến value (Weight matrix)
        self.archetype_profiles = {
            "explorer":   {"independence": 0.8, "growth": 0.7, "social": -0.5},
            "builder":    {"social": 0.8, "growth": 0.6, "independence": -0.2},
            "hermit":     {"independence": 1.0, "social": -1.0, "growth": 0.2}
        }
        self.vector: Dict[str, float] = {k: 1 / len(self.archetype_profiles) for k in self.archetype_profiles}

    def update_from_tradeoff(self, winner_id: str, sacrificed_id: str):
        """Cập nhật Identity Vector dựa trên mỗi lần tradeoff"""
        delta = 0.05
        for arch, profile in self.archetype_profiles.items():
            score_change = profile.get(winner_id, 0) * delta + profile.get(sacrificed_id, 0) * (-delta * 0.5)
            self.vector[arch] = max(0.0, self.vector[arch] + score_change)
        self._normalize()

    def apply_dissonance(self, trait_to_punish: str, penalty: float = 0.2):
        """FIX BOM 17: Khi Reality Check thất bại, trừng phạt trực tiếp Identity"""
        self.vector[trait_to_punish] = max(0.0, self.vector[trait_to_punish] - penalty)
        self._normalize()

    def get_tolerance_modifier(self, value_id: str) -> float:
        """Tính toán modifier dựa trên weighted sum của Identity Vector"""
        modifier = 0.0
        for arch, weight in self.vector.items():
            modifier += self.archetype_profiles[arch].get(value_id, 0.0) * weight
        return modifier * 0.5  # Scale xuống cho hợp lý

    def get_dominant_trait(self) -> str:
        return max(self.vector, key=self.vector.get)

    def _normalize(self):
        total = sum(self.vector.values())
        if total == 0: return
        self.vector = {k: v / total for k, v in self.vector.items()}


@dataclass
class OpinionHypothesis:
    trigger_pattern: str
    assumption: str
    test_action_id: str
    status: str = "PENDING"  # PENDING -> TESTING -> CONFIRMED / REJECTED


class OpinionReflectionEngine:
    """FIX BOM 19: True Reflection (Pattern -> Hypothesis -> Test -> Revision)."""

    def __init__(self):
        self.active_hypotheses: List[OpinionHypothesis] = []

    def scan_and_hypothesize(self, values: Dict[str, OpinionValue], identities: IdentityEngine) -> Optional[OpinionHypothesis]:
        """Nhìn vào pattern và tạo giả thuyết (Không phải if-else đơn giản)"""
        social_val = values.get("social")
        if not social_val: return None

        # Pattern: Social bị hy sinh quá nhiều, và Identity đang nghiêng về Explorer
        if social_val.accumulated_cost > 1.2 and identities.vector["explorer"] > 0.5:
            if not any(h.trigger_pattern == "social_exhaustion" for h in self.active_hypotheses):
                hyp = OpinionHypothesis(
                    trigger_pattern="social_exhaustion",
                    assumption="Có thể tôi đang quá cô lập do lạm dụng Identity Explorer.",
                    test_action_id="force_socialize"
                )
                self.active_hypotheses.append(hyp)
                return hyp
        return None

    def process_test_result(self, action_id: str, outcome: float, values: Dict[str, OpinionValue], identities: IdentityEngine):
        """Nhận kết quả của bài test và Revision lại Worldview"""
        for hyp in self.active_hypotheses:
            if hyp.test_action_id == action_id and hyp.status == "TESTING":
                if outcome > 0.5:
                    hyp.status = "CONFIRMED"
                    values["social"].heal_cost(0.5)  # Revision: Heal social
                    identities.apply_dissonance("explorer", 0.1)  # Revision: Hạ bệ Explorer một chút
                    return f"GIẢ THUYẾT ĐÚNG: {hyp.assumption}. Điều chỉnh Identity."
                else:
                    hyp.status = "REJECTED"
                    return f"GIẢ THUYẾT SAI: Kết quả tồi. Giữ nguyên lập trường."
        return None


class TradeoffEngine:
    BASE_THRESHOLD = 1.5
    ABSOLUTE_REALITY_LIMIT = 2.2  # FIX BOM 17: Ngưỡng tuyệt đối của thực tại, không ai vượt qua được

    def evaluate(self, action: OpinionAction, values: Dict[str, OpinionValue], identities: IdentityEngine, forced: bool = False) -> dict:
        supports = [(vid, imp) for vid, imp in action.value_impacts.items() if imp > 0.2 and vid in values]
        harms = [(vid, imp) for vid, imp in action.value_impacts.items() if imp < -0.2 and vid in values]

        if not supports or not harms:
            return {"status": "NO_CONFLICT"}

        winner_id = max(supports, key=lambda x: values[x[0]].importance)[0]
        sacrificed_id = min(harms, key=lambda x: values[x[0]].importance)[0]

        for vid, imp in supports:
            values[vid].heal_cost(imp * 0.3)

        # Tính ngưỡng dựa trên Identity Vector (BOM 18)
        modifier = identities.get_tolerance_modifier(sacrificed_id)
        dynamic_threshold = self.BASE_THRESHOLD + modifier

        sacrified_val = values[sacrificed_id]
        proposed_cost = abs(action.value_impacts[sacrificed_id])
        new_total_cost = sacrified_val.accumulated_cost + proposed_cost

        # FIX BOM 17: REALITY CHECK
        if new_total_cost > self.ABSOLUTE_REALITY_LIMIT and not forced:
            # Đụng tường thực tại. Phá vỡ Runaway Loop.
            dominant = identities.get_dominant_trait()
            identities.apply_dissonance(dominant, 0.3)  # Trừng phạt nặng Identity đang thống trị
            return {
                "status": "REALITY_SHOCK",
                "reason": f"Đụng ngưỡng thực tại ({new_total_cost:.1f}/{self.ABSOLUTE_REALITY_LIMIT}). Identity '{dominant}' bị Cognitive Dissonance trừng phạt."
            }

        if new_total_cost > dynamic_threshold and not forced:
            return {"status": "BLOCKED", "reason": f"Đã vượt ngưỡng chịu đựng ({dynamic_threshold:.2f})."}

        # Chấp nhận
        values[winner_id].tradeoff_wins += 1
        values[sacrificed_id].tradeoff_losses += 1
        values[sacrificed_id].accumulated_cost += proposed_cost
        identities.update_from_tradeoff(winner_id, sacrificed_id)

        return {"status": "ACCEPTED", "winner": winner_id, "sacrificed": sacrificed_id}


class OpinionSystem:
    """Per-user Identity/Values/Tradeoff engine.

    Wraps IdentityEngine + a fixed set of OpinionValue (independence/social/
    growth) + TradeoffEngine + OpinionReflectionEngine for one sender_id,
    persists to the `opinion_state` table, and exposes for_prompt() so this
    "inner personality drift" can be injected into the AI system prompt.
    """

    VALUE_IDS = ("independence", "social", "growth")

    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.identity = IdentityEngine()
        self.values: Dict[str, OpinionValue] = {
            vid: OpinionValue(f"ov_{vid}", vid) for vid in self.VALUE_IDS
        }
        self.tradeoff = TradeoffEngine()
        self.reflection = OpinionReflectionEngine()
        self._load()

    # ---------- persistence ----------
    def _load(self):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            c = conn.cursor()
            c.execute(
                "SELECT identity_vector, values_state, hypotheses FROM opinion_state WHERE sender_id=?",
                (self.sender_id,)
            )
            row = c.fetchone()
            conn.close()
            if not row:
                return

            identity_vector_raw, values_state_raw, hypotheses_raw = row

            if identity_vector_raw:
                vec = json.loads(identity_vector_raw)
                for arch in self.identity.vector:
                    if arch in vec:
                        self.identity.vector[arch] = float(vec[arch])
                self.identity._normalize()

            if values_state_raw:
                vs = json.loads(values_state_raw)
                for vid, data in vs.items():
                    if vid in self.values:
                        v = self.values[vid]
                        v.tradeoff_wins = int(data.get("wins", 0))
                        v.tradeoff_losses = int(data.get("losses", 0))
                        v.accumulated_cost = float(data.get("cost", 0.0))

            if hypotheses_raw:
                hyps = json.loads(hypotheses_raw)
                self.reflection.active_hypotheses = [
                    OpinionHypothesis(
                        trigger_pattern=h["trigger_pattern"],
                        assumption=h["assumption"],
                        test_action_id=h["test_action_id"],
                        status=h.get("status", "PENDING"),
                    )
                    for h in hyps
                ]
        except Exception as e:
            log.error(f"[OPINION] load failed for {self.sender_id}: {e}")

    def save(self):
        try:
            identity_vector = json.dumps(self.identity.vector)
            values_state = json.dumps({
                vid: {
                    "wins": v.tradeoff_wins,
                    "losses": v.tradeoff_losses,
                    "cost": v.accumulated_cost,
                }
                for vid, v in self.values.items()
            })
            hypotheses = json.dumps([
                {
                    "trigger_pattern": h.trigger_pattern,
                    "assumption": h.assumption,
                    "test_action_id": h.test_action_id,
                    "status": h.status,
                }
                for h in self.reflection.active_hypotheses
            ])
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
            conn.execute("""
                INSERT INTO opinion_state (sender_id, identity_vector, values_state, hypotheses, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(sender_id) DO UPDATE SET
                    identity_vector = excluded.identity_vector,
                    values_state    = excluded.values_state,
                    hypotheses      = excluded.hypotheses,
                    updated_at      = CURRENT_TIMESTAMP
            """, (self.sender_id, identity_vector, values_state, hypotheses))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"[OPINION] save failed for {self.sender_id}: {e}")

    # ---------- per-turn processing ----------
    def process_turn(self, decisions: dict, last_outcome: Optional[int] = None) -> dict:
        """Run one BOM17/18/19 step for this turn.

        decisions:   output of DecisionEngine.calculate() for this sender.
        last_outcome: detect_outcome_score() (-2..+2) of the user's reply to
                       the bot's previous message, or None if there isn't one
                       yet (e.g. first message of the conversation).
        """
        log_lines = []

        # 1. If a hypothesis is currently TESTING, score it using the
        #    reaction to the bot's previous message.
        if last_outcome is not None:
            outcome_norm = max(0.0, min(1.0, (last_outcome + 2) / 4.0))
            for hyp in self.reflection.active_hypotheses:
                if hyp.status == "TESTING":
                    revision = self.reflection.process_test_result(
                        hyp.test_action_id, outcome_norm, self.values, self.identity
                    )
                    if revision:
                        log_lines.append(revision)

        # 2. Map this turn's decisions -> a tradeoff Action and evaluate it
        action = self._action_from_decisions(decisions)
        result = {"status": "SKIPPED"}
        if action is not None:
            result = self.tradeoff.evaluate(action, self.values, self.identity)
            if result["status"] in ("REALITY_SHOCK", "BLOCKED"):
                log_lines.append(f"[OPINION] {result['status']}: {result['reason']}")

        # 3. Scan for a new hypothesis about the resulting pattern
        hyp = self.reflection.scan_and_hypothesize(self.values, self.identity)
        if hyp:
            hyp.status = "TESTING"
            log_lines.append(f"[OPINION] New hypothesis: {hyp.assumption}")

        self.save()
        if log_lines:
            log.info(" | ".join(log_lines))
        return {"tradeoff": result, "log": log_lines}

    def _action_from_decisions(self, decisions: dict) -> Optional[OpinionAction]:
        """Translate this turn's DecisionEngine output into a tradeoff Action.

        This is a starter mapping — tune the value_impacts as the bot's real
        behaviors evolve. Returns None when this turn doesn't represent a
        meaningful tradeoff (no conflict to evaluate).
        """
        mode = decisions.get("mode", "default")
        warmth = decisions.get("warmth_score", 0.5)

        if mode == "explorer":
            return OpinionAction("explore", "Đi sâu khám phá một mình",
                                  {"independence": 0.8, "social": -0.5})
        if mode == "challenger":
            return OpinionAction("challenge", "Thử thách / đẩy đối phương",
                                  {"growth": 0.6, "social": -0.4})
        if warmth > 0.6:
            return OpinionAction("connect", "Kết nối ấm áp",
                                  {"social": 0.8, "independence": -0.3})
        return None

    # ---------- prompt injection ----------
    def for_prompt(self) -> str:
        dominant = self.identity.get_dominant_trait()
        lines = ["## INNER IDENTITY (drift ngầm — KHÔNG nhắc trực tiếp)"]
        lines.append(f"- Archetype chiếm ưu thế: {dominant} ({self.identity.vector[dominant]:.0%})")
        for vid in self.VALUE_IDS:
            v = self.values[vid]
            name = OPINION_CONCEPTS[vid].name
            tag = ""
            if v.accumulated_cost > 1.2:
                tag = " — đang quá tải, cần được 'chữa lành'"
            lines.append(f"- {name}: importance {v.importance:.0%}, cost {v.accumulated_cost:.2f}{tag}")
        lines.append("(Để xu hướng identity/values này ảnh hưởng ngầm tới tone & lựa chọn phản hồi, KHÔNG nhắc thẳng ra)")
        return "\n\n" + "\n".join(lines)


MAX_OPINION_CACHE = 500
_opinion_cache: dict[str, tuple["OpinionSystem", float]] = {}

def get_opinion_system(sender_id: str) -> "OpinionSystem":
    now = time.time()
    if sender_id in _opinion_cache:
        sys_obj, _ = _opinion_cache[sender_id]
        _opinion_cache[sender_id] = (sys_obj, now)  # bump LRU timestamp
        return sys_obj

    if len(_opinion_cache) >= MAX_OPINION_CACHE:
        lru_id = min(_opinion_cache, key=lambda k: _opinion_cache[k][1])
        del _opinion_cache[lru_id]

    sys_obj = OpinionSystem(sender_id)
    _opinion_cache[sender_id] = (sys_obj, now)
    return sys_obj


def demo_opinion_system():
    """Standalone demo of the Opinion/Identity expansion module
    (ported from opinion_system.py's original __main__ block).
    Run with: python bot7.28.py --opinion-demo
    """
    values = {
        "independence": OpinionValue("v1", "independence", tradeoff_wins=10),
        "social": OpinionValue("v2", "social", tradeoff_losses=8, accumulated_cost=1.4)
    }
    identities = IdentityEngine()
    identities.vector = {"explorer": 0.8, "builder": 0.1, "hermit": 0.1}  # Ban đầu rất cực đoan

    tradeoff = TradeoffEngine()
    reflection = OpinionReflectionEngine()

    action_isolate = OpinionAction("isolate", "Isolate", {"independence": 0.8, "social": -0.5})

    print("--- [1. RUNAWAY LOOP ĐANG CHẠY] ---")
    print(f"Identity Vector Ban đầu: {identities.vector}")
    print(f"Social Cost ban đầu: {values['social'].accumulated_cost}")

    while True:
        res = tradeoff.evaluate(action_isolate, values, identities)
        if res["status"] == "ACCEPTED":
            print(f"  -> Accept. Social Cost lên: {values['social'].accumulated_cost:.2f}")
        else:
            print(f"\n--- [2. FIX BOM 17: REALITY SHOCK!] ---")
            print(f"Status: {res['status']}")
            print(f"Reason: {res['reason']}")
            break

    print(f"\nIdentity Vector SAU SHOCK: {identities.vector}")
    print("-> Loop bị phá! Explorer bị trừ điểm, hệ thống tự nhận ra mình đi quá xa.")

    print("\n--- [3. FIX BOM 19: TRUE REFLECTION KICKS IN] ---")
    hyp = reflection.scan_and_hypothesize(values, identities)
    if hyp:
        print(f"Phát hiện Pattern: Social exhaustion.")
        print(f"Giả thuyết sinh ra: '{hyp.assumption}'")
        print(f"-> Yêu cầu hành động test: '{hyp.test_action_id}'")
        hyp.status = "TESTING"

        print("\n--- [4. THỰC HIỆN BÀI TEST] ---")
        test_res = tradeoff.evaluate(action_isolate, values, identities, forced=True)
        print("Đã ép bản thân đi socialize... (Outcome giả lập: Tốt)")

        revision_log = reflection.process_test_result("force_socialize", 0.9, values, identities)
        print(f"\nKết quả Reflection: {revision_log}")
        print(f"Social Cost sau khi heal: {values['social'].accumulated_cost:.2f}")
        print(f"Identity Vector CUỐI CÙNG: {identities.vector}")


if __name__ == "__main__":
    if "--opinion-demo" in sys.argv:
        demo_opinion_system()
    else:
        app.run(port=5000, debug=False)
