"""Viết 2: 用词造句 — đặt câu với từ cho sẵn (thay cho "nhìn tranh đặt câu").

KHÔNG cần LLM để sinh: chỉ chọn từ mục tiêu là xong. Mỗi câu hỏi hiển thị
từ (chữ Hán + pinyin + nghĩa Việt), người học tự gõ câu. Chấm bằng LLM (M4).
Trả về list "question dict"; answer rỗng (chờ chấm LLM).
"""
from ..models import Word


def gen(session, targets: list[Word], stats, swap_pool=None) -> list[dict]:
    """Đồng bộ (không gọi LLM). Mỗi target → 1 câu hỏi. stats không đổi."""
    result: list[dict] = []
    for target in targets:
        result.append({
            "part": "make_sentence",
            "group_no": None,
            "payload": {
                "hanzi": target.hanzi,
                "pinyin": target.pinyin,
                "han_viet": target.han_viet,
                "meaning_vi": target.meaning_vi,
            },
            "answer": None,  # chấm tự do bằng LLM (M4)
            "target_word_ids": [target.id],
        })
    return result
