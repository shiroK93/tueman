import os
import re
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
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "your_grok_api,_go_get_one_at_their_website,_its_free")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "yoor_fb_page_access_token,_you_willl_need_to_create_a_fanpage_to_get_the_token")
VERIFY_TOKEN         = "shirok"
MAX_FOLLOW_UPS       = 2     # tối đa 2 lần follow-up liên tiếp
MAX_HISTORY          = 14    # số tin nhắn giữ trong context
MAX_FACTS            = 50    # giới hạn facts lưu trong DB
DB_PATH              = "memory.db"
DB_TIMEOUT           = 20
ADMIN_TOKEN          = os.environ.get("ADMIN_TOKEN", "shirok_admin")
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
    # Migrate facts table — add importance & updated_at if not already there
    try:
        c.execute("ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 5")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE facts ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
    except Exception:
        pass
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

def save_facts_with_importance(sender_id: str, new_facts: dict, importance_map: dict):
    """Save facts with 0-10 importance scores."""
    if not new_facts:
        return
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    for k, v in new_facts.items():
        imp = int(importance_map.get(k, 5))
        imp = max(0, min(10, imp))
        conn.execute("""
            INSERT INTO facts (sender_id, key, value, importance, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(sender_id, key)
            DO UPDATE SET value=excluded.value, importance=excluded.importance,
                          updated_at=CURRENT_TIMESTAMP
        """, (sender_id, str(k)[:80], str(v)[:200], imp))
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

            # ── Facts with importance ──
            facts = data.get("facts", {})
            importance = data.get("facts_importance", {})
            if isinstance(facts, dict) and facts:
                save_facts_with_importance(sender_id, facts, importance)
                log.info(f"[LEARN:FACTS] {sender_id}: {facts} | importance: {importance}")

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

# ==================== INTENT DETECTION ====================

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

    system = (
        build_system_prompt(sender_id, user_message)
        + build_intent_prompt(intent)
    )

    save_message(sender_id, "user", user_message)

    history = get_history(sender_id)

    log.info("[GROQ] sending request")

    ai_text = _call_groq(system, history)

    log.info(f"[GROQ] response: {repr(ai_text)}")

    save_message(sender_id, "assistant", ai_text)

    background_learning_async(sender_id, user_message)

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
        "model": "qwen/qwen3-32b",
        "messages": [
            {
                "role": "system",
                "content": (
                    system
                    + "\n\nIMPORTANT:\n"
                    + "- user is male\n"
                    + "- call user 'anh'\n"
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
                raw = res.json()["choices"][0]["message"]["content"].strip()
                return strip_thinking(raw)
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

if __name__ == "__main__":
    app.run(port=5000, debug=False)
