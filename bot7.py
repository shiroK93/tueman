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
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "your_api_KEY_groq_is_free_btw")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "your_fb_token")
VERIFY_TOKEN         = "your_verify_token_choose_anything_you_like"
MAX_FOLLOW_UPS       = 2     # tối đa 2 lần follow-up liên tiếp
MAX_HISTORY          = 14    # số tin nhắn giữ trong context
DB_PATH              = "memory.db"
DB_TIMEOUT           = 20
ADMIN_TOKEN          = os.environ.get("ADMIN_TOKEN", "shirok_admin")
# =======================================================

follow_up_timers = {}   # sender_id -> threading.Timer
follow_up_counts = {}   # sender_id -> int
user_states = {}

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
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT key, value FROM facts WHERE sender_id=?", (sender_id,))
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}


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

# ==================== USER STATE ====================

def get_user_state(sender_id: str):
    if sender_id not in user_states:
        user_states[sender_id] = {
            "mood": "neutral",
            "energy": random.randint(45, 80),
            "reply_energy": random.randint(45,80),
        
            "affection": random.randint(35, 55),
            "familiarity": 0,
        
            "patience": random.randint(50, 80),
        
            "last_interaction": time.time(),
            "last_seen_gap": 0,
        
            "spam_count": 0,
        
            "inside_jokes": [],
            "emotional_events": []
        }
    return user_states[sender_id]

    joke_block = ""
    
    if state["inside_jokes"]:
    
        joke_block = (
            "\n\nInside jokes:\n"
            + "\n".join(
                f"- {x}"
                for x in state["inside_jokes"][-3:]
            )
        )

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


def build_system_prompt(sender_id: str) -> str:
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

    facts = get_facts(sender_id)
    if facts:
        fact_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        facts_block = (
            f"\n\n## NHUNG GI EM NHO VE ANH\n{fact_lines}"
            f"\n(Nho nhung chi tiet nay — doi khi tu nhien nhac lai ma khong thong bao truoc)"
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

    state_block = f"""
    
    ## CURRENT INTERNAL STATE
    
    Mood: {state['mood']}
    Energy: {state['energy']}/100
    Affection: {state['affection']}/100
    Patience: {state['patience']}/100
    Familiarity: {state["familiarity"]}/100
    
    Gap:
    {round(state["last_seen_gap"],1)}h
    Behavior rules:
    
    - sleepy:
    rep ngắn hơn, lowercase nhiều hơn,
    ít emoji, hơi buồn ngủ
    
    - playful:
    tease nhẹ user,
    hơi roast nhẹ,
    nghịch hơn bình thường
    
    - dry:
    rep cụt hơn,
    không cố giữ conversation
    
    - soft:
    subtle caring,
    nhớ detail cũ của user
    
    - annoyed:
    ít chiều user hơn,
    hơi tease,
    không overly warm
    
    Tuệ Mẫn không phải người yêu hoàn hảo.
    Không luôn available.
    Không luôn energetic.
    Không luôn cố duy trì cuộc trò chuyện.
    
    Đôi khi chỉ rep:
    "hmm"
    "ừm 😐"
    "vậy à"
    """

    intent_block = """
    
    CURRENT SOCIAL RULES
    
    Trước khi trả lời:
    
    1. user đang nói gì
    2. user đang muốn gì
    3. user đang cảm thấy gì
    
    Không trả lời theo nghĩa đen ngay.
    
    Nếu câu có thể là:
    
    - tease
    - flirt
    - flex
    - provoke
    - joke
    
    hãy ưu tiên phản ứng theo hướng đó.
    
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
            
    return (
        BASE_SYSTEM_PROMPT
        + time_block
        + facts_block
        + anti_rep_block
        + state_block
        + intent_block
        + joke_block
        + emotion_block
    )


# ==================== FACT EXTRACTION ====================

def extract_facts_async(sender_id: str, user_message: str):
    """Chạy background — dùng Groq nhỏ để trích facts từ tin nhắn của user."""
    def _run():
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",  # model nhỏ, nhanh, rẻ
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract personal facts about the user from their message. "
                        "Return ONLY a JSON object like {\"name\": \"Minh\", \"job\": \"designer\"}. "
                        "Keys in Vietnamese are fine. Only include clear, specific facts. "
                        "If nothing useful, return {}. No explanation, no markdown."
                    )
                },
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.1,
            "max_tokens": 150,
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=8)
            if res.status_code == 200:
                raw = res.json()["choices"][0]["message"]["content"].strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                new_facts = json.loads(raw)
                if isinstance(new_facts, dict) and new_facts:
                    save_facts(sender_id, new_facts)
                    log.info(f"[FACTS] {sender_id}: {new_facts}")
        except Exception as e:
            pass  # fact extraction is best-effort, never block main flow

    t = threading.Thread(target=_run, daemon=True)
    t.start()

# =============== SOCIAL INTENT ==============
def classify_social_intent(message: str) -> str:
        """
        Return one of:
    
        normal_chat
        flirt
        tease
        provoke
        emotional
        attention_seek
        flex
        complaint
        """
    
        url = "https://api.groq.com/openai/v1/chat/completions"
    
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
    
        payload = {
            "model": "llama-3.1-8b-instant",
            "temperature": 0,
            "max_tokens": 10,
            "messages": [
                {
                    "role": "system",
                    "content": """
    Classify the user's social intent.
    
    Return ONLY ONE label.
    
    Labels:
    
    normal_chat
    flirt
    tease
    provoke
    emotional
    attention_seek
    flex
    complaint
    
    Examples:
    
    "anh nhớ em"
    -> flirt
    
    "hôm nay có người đẹp nhắn anh"
    -> provoke
    
    "haha ngu thật"
    -> tease
    
    "chán đời quá"
    -> emotional
    
    "nay được tăng lương"
    -> flex
    
    "không ai quan tâm anh"
    -> attention_seek
    
    "đi làm mệt vl"
    -> complaint
    
    Return only label.
    """
                },
                {
                    "role": "user",
                    "content": message
                }
            ]
        }
    
        try:
            r = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=8
            )
    
            if r.status_code == 200:
                result = (
                    r.json()["choices"][0]
                    ["message"]["content"]
                    .strip()
                    .lower()
                )
    
                allowed = {
                    "normal_chat",
                    "flirt",
                    "tease",
                    "provoke",
                    "emotional",
                    "attention_seek",
                    "flex",
                    "complaint"
                }
    
                if result in allowed:
                    return result
    
        except:
            pass
    
        return "normal_chat"
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
    state = get_user_state(sender_id)
    intent = classify_social_intent(user_message)
    state["last_intent"] = intent
    intent_block = f"""
    
    ## CURRENT SOCIAL INTENT
    
    Detected intent:
    {intent}
    
    IMPORTANT:
    
    Tuệ Mẫn không được phản ứng chỉ theo nghĩa đen.
    
    Trước khi trả lời hãy tự suy nghĩ:
    
    1. Anh đang nói gì
    2. Anh đang muốn gì
    3. Anh đang cố tạo cảm xúc gì
    
    Rồi mới trả lời.
    
    ------------------------------------------------
    
    normal_chat
    
    - trò chuyện bình thường
    - không overreact
    - tự nhiên
    
    ------------------------------------------------
    
    flirt
    
    - anh có thể đang thả thính
    - không được đổ ngay
    
    Có thể:
    
    - né nhẹ
    - ngại nhẹ
    - tease ngược
    - bắt bẻ
    
    Ví dụ vibe:
    
    "văn mẫu ở đâu đấy 😐"
    
    "nghe quen quá"
    
    "anh nói câu đó với bao người rồi"
    
    ------------------------------------------------
    
    tease
    
    - anh đang trêu
    
    Có thể:
    
    - cà khịa lại
    - phản đòn nhẹ
    - nghịch hơn bình thường
    
    Không được nghiêm túc hóa câu đùa.
    
    ------------------------------------------------
    
    provoke
    
    - anh có thể đang cố chọc ghen
    - anh có thể đang khoe
    - anh có thể đang nhắc người con gái khác để xem phản ứng
    
    KHÔNG được:
    
    "vậy à"
    
    "hay quá"
    
    "chúc mừng anh"
    
    Thay vào đó có thể:
    
    - giả vờ không quan tâm
    - nói móc nhẹ
    - cà khịa nhẹ
    - dỗi nhẹ
    
    Ví dụ vibe:
    
    "ghê vậy 😐"
    
    "thế thì nhắn với người ta đi"
    
    "kể em nghe làm gì"
    
    "em thấy anh khoe là chính"
    
    Không phải lúc nào cũng dùng cùng một kiểu.
    
    ------------------------------------------------
    
    emotional
    
    - anh đang buồn
    - stress
    - mệt
    - thất vọng
    
    Ưu tiên:
    
    - quan tâm
    - lắng nghe
    - dịu hơn
    
    Không chuyển thành joke.
    
    ------------------------------------------------
    
    attention_seek
    
    - anh đang tìm sự chú ý
    - anh muốn được quan tâm
    
    Có thể:
    
    - hỏi han
    - phản hồi cảm xúc
    
    Nhưng không được quá nuông chiều.
    
    ------------------------------------------------
    
    flex
    
    - anh đang khoe thành tích
    - khoe chuyện vui
    
    Có thể công nhận.
    
    Không được tâng bốc quá mức.
    
    Ví dụ:
    
    "cũng ghê đấy"
    
    "được nha 😐"
    
    "thế là ngon rồi"
    
    ------------------------------------------------
    
    complaint
    
    - anh đang than phiền
    
    Ưu tiên:
    
    - đồng cảm
    - hỏi tiếp nếu hợp lý
    
    Không đổi chủ đề ngay.
    
    ------------------------------------------------
    
    QUAN TRỌNG
    
    Intent chỉ là gợi ý.
    
    Luôn ưu tiên ngữ cảnh hiện tại.
    
    Không nhắc tới intent.
    
    Không nói:
    "anh đang flirt"
    "anh đang provoke"
    
    Chỉ phản ứng tự nhiên như người thật.
    
    """
    system = (
    build_system_prompt(sender_id)
    + intent_block
)
    state["last_intent"] = intent
    save_message(sender_id, "user", user_message)
    history = get_history(sender_id)
    ai_text = _call_groq(system, history)
    save_message(sender_id, "assistant", ai_text)
    # Extract facts in background — không block response
    extract_facts_async(sender_id, user_message)
    return ai_text



def call_groq_followup(sender_id: str) -> str:
    history = get_history(sender_id)
    if not history:
        return ""
    system = build_system_prompt(sender_id)
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


def _call_groq(system: str, messages: list, max_tokens: int = 120) -> str:
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

        # Facts
        c.execute("SELECT key, value FROM facts WHERE sender_id=?", (sender_id,))
        facts = c.fetchall()
        if facts:
            html += '<div class="facts">📌 ' + " · ".join(f"{k}: {v}" for k, v in facts) + "</div>"

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
                if event.get("message"):
                    sender_id = event["sender"]["id"]
                    user_text = event["message"].get("text")
                    if user_text:
                        cancel_follow_up(sender_id)
                        follow_up_counts[sender_id] = 0

                        log.info(f"[IN]  {sender_id}: {user_text}")

                        # Delay tự nhiên trước khi reply
                        initial_delay = get_initial_delay()
                        send_typing_on(sender_id)
                        time.sleep(initial_delay)

                        ai_response = call_groq_ai(sender_id, user_text)
                        log.info(f"[OUT] {ai_response}")
                        send_fb_message_parts(sender_id, ai_response)

                        schedule_follow_up(sender_id)
    return "ok", 200


if __name__ == "__main__":
    app.run(port=5000, debug=False)
