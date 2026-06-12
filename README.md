# Tuệ Mẫn

> Một AI companion có khả năng ghi nhớ, phản tư, hình thành niềm tin và thay đổi theo trải nghiệm.

---

## Tại sao dự án này tồn tại?

Dự án bắt đầu từ một ý tưởng rất đơn giản:

> "Nếu AI có thể nhớ mình và thực sự học từ các cuộc trò chuyện thì sao?"

Thay vì chỉ lưu memory hoặc nhồi thêm context vào prompt, Tuệ Mẫn được xây dựng theo hướng:

```
Memory
↓
Experience
↓
Reflection
↓
Belief
↓
Decision
↓
Identity
```

Mục tiêu không phải tạo ra một chatbot biết nhiều hơn.

Mục tiêu là tạo ra một chatbot có thể thay đổi theo thời gian.

---

## Kiến trúc

### Level 0 — Memory

Lưu trữ thông tin người dùng.

Ví dụ:

* Sở thích
* Sự kiện
* Những điều đã nhắc trước đó

Đây chỉ là dữ liệu.

Chưa phải nhận thức.

---

### Level 1 — Experience

Mỗi cuộc trò chuyện được lưu thành trải nghiệm.

Ví dụ:

```json
{
  "user_message": "...",
  "response": "...",
  "outcome": 2
}
```

Outcome thể hiện mức độ thành công của tương tác.

---

### Level 2 — Reflection

Hệ thống phản tư nhiều tầng.

#### Reflection A

Học ngay từ trải nghiệm vừa xảy ra.

Ví dụ:

```
Đưa hint
↓
Conversation tiếp tục tốt
↓
Hint tốt hơn đáp án thẳng
```

#### Reflection B

Tìm pattern từ nhiều trải nghiệm.

Ví dụ:

```
Gaming
↓
Outcome tốt liên tục
↓
Hình thành belief
```

#### Reflection C

Kiểm tra xem belief hiện tại còn đúng hay không.

Ví dụ:

```
Belief:
"Người dùng thích challenge"

↓

Evidence mới:
Liên tục né challenge

↓

Belief bị nghi ngờ
```

---

### Level 3 — Belief System

Belief không chỉ là một câu văn.

Mỗi belief có:

```json
{
  "belief": "...",
  "confidence": 0.81,
  "evidence_count": 37,
  "last_confirmed": "...",
  "contradictions": 3,
  "domain": "interest"
}
```

Belief có thể mạnh lên, yếu đi hoặc bị vô hiệu hóa.

---

### Level 4 — Belief Network

Belief không tồn tại độc lập.

Ví dụ:

```
Thích challenge
├─ Coding
├─ Puzzle
├─ Learning
└─ Strategy games
```

Các belief liên kết với nhau thành mạng lưới.

---

### Level 5 — Contradiction Engine

Hệ thống theo dõi mâu thuẫn.

Ví dụ:

```
Belief:
Người dùng thích roast

↓

Evidence:
Liên tục phản ứng tiêu cực với roast

↓

Confidence giảm
```

Không phải mọi belief đều sống mãi.

---

### Level 6 — Decision Layer

Biến belief thành hành vi.

Ví dụ:

```python
if likes_hint > 0.8:
    use_hint_mode()

if likes_roast < 0.4:
    disable_roast()
```

Belief không chỉ để lưu.

Belief ảnh hưởng trực tiếp tới cách AI trả lời.

---

### Level 7 — Meta Beliefs (Planned)

Belief về belief.

Ví dụ:

```
"Tôi nghĩ người dùng thích gaming."

Confidence:
0.61
```

AI biết mức độ chắc chắn của chính mình.

---

### Level 8 — Identity (Long-term Goal)

Không còn là:

> Người dùng là ai?

Mà là:

> Tuệ Mẫn là ai?

Ví dụ:

* Thích giải thích bằng ví dụ.
* Ưu tiên tính chính xác.
* Không thích trả lời quá máy móc.
* Có phong cách giao tiếp riêng.

Đây là mục tiêu dài hạn của dự án.

---

## Triết lý

Dự án không cố gắng tạo AGI.

Dự án cũng không cố gắng tạo một AI tự duyệt web, tự nghiên cứu hay tự làm mọi thứ.

Trọng tâm là:

```
Experience
↓
Reflection
↓
Belief
```

Vì một AI không thay đổi theo trải nghiệm sẽ mãi chỉ là một prompt rất dài.

---

## Trạng thái hiện tại

* Memory System
* Experience Tracking
* Reflection A/B/C
* Belief System
* Belief Decay
* Contradiction Detection
* Belief Network
* Decision Foundation

Đang phát triển.

---

## Ghi chú

Dự án này được bắt đầu vì một lý do cực kỳ ngớ ngẩn:

> Bị Meta AI ghost (tận 5 lần).

Không ngờ cuối cùng lại thành một kiến trúc nhận thức thu nhỏ.

💀
