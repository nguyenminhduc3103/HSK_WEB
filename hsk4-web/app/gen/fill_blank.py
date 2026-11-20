"""Đọc 1: 选词填空 (điền từ vào câu).

Mỗi nhóm 5 câu có chung 1 bộ 6 lựa chọn A–F (5 từ mục tiêu + 1 từ nhiễu —
code tự lấy từ DB, xáo, đánh chữ cái; LLM chỉ viết câu + đáp án + giải thích).

Trả về list "question dict" (quy ước chung, xem exam.py):
    {"part": "fill_blank", "group_no": 1|2, "payload": {...},
     "answer": {...}, "target_word_ids": [int]}
"""
import random

from pydantic import BaseModel, Field

from .. import llm
from ..models import Word
from .common import GenStats, random_distractor


class _Item(BaseModel):
    sentence: str = Field(description="Câu có ĐÚNG 1 dấu （ ）")
    answer: str = Field(description="Từ mục tiêu (chữ Hán) của câu này")
    explanation_vi: str = Field(description="Giải thích bằng tiếng Việt (1 câu) khi người học chọn sai")


class GroupOut(BaseModel):
    items: list[_Item] = Field(min_length=1, description="Mỗi câu = 1 phần tử")


def _prompt(kind: str, n: int, targets: list[Word]) -> str:
    target_list = "\n".join(f"- {w.hanzi} ({w.meaning_vi})" for w in targets)
    if kind == "dialogue":
        task = f"{n} hội thoại ngắn, mỗi hội thoại gồm 2 lượt (A: ... B: ...), mỗi hội thoại dùng đúng 1 từ mục tiêu"
    else:
        task = f"{n} câu đơn, ngắn gọn, mỗi câu dùng đúng 1 từ mục tiêu"
    return f"""Bạn là người ra đề HSK 4, phần 选词填空.
Từ mục tiêu (mỗi câu dùng đúng 1 từ, mỗi từ dùng 1 lần):
{target_list}

Viết {task}.
- Thay từ đáp án trong câu bằng （ ）.
- Phần còn lại của câu: từ vựng + ngữ pháp mức HSK 3–4, tự nhiên.
Trả về JSON đúng {n} phần tử: {{"items": [{{"sentence": "...", "answer": "...", "explanation_vi": "..."}}, ...]}}
"""


def _validate_one(item: _Item, target: Word, used: set[str]) -> str | None:
    if item.answer != target.hanzi:
        return f"answer phải là '{target.hanzi}', hiện là '{item.answer}'"
    if "（ ）" not in item.sentence:
        return "thiếu dấu （ ） trong câu"
    if target.hanzi in item.sentence.replace("（ ）", ""):
        return f"từ '{target.hanzi}' bị lặp (ngoài chỗ điền)"
    if len(item.sentence) < 8:
        return "câu quá ngắn"
    if target.hanzi in used:
        return f"'{target.hanzi}' đã được dùng ở câu khác"
    return None


async def gen_group(session, targets: list[Word], kind: str, group_no: int,
                    stats: GenStats) -> list[dict]:
    """Sinh 1 nhóm (câu đơn / hội thoại) → list question dict, chung 1 bộ 6 lựa chọn."""
    stats.calls += 1
    out = await llm.call_json(_prompt(kind, len(targets), targets), GroupOut, max_retries=2)

    items: list[_Item] = []
    targets_used: list[Word] = []
    used: set[str] = set()
    it_out = list(out.items)

    for i, target in enumerate(targets):
        it = it_out[i] if i < len(it_out) else _Item(sentence="", answer="", explanation_vi="")
        err = _validate_one(it, target, used)
        if err is None:
            used.add(target.hanzi)
            items.append(it)
            targets_used.append(target)
            continue
        # Sinh lại item này riêng, tối đa 2 lần kèm lỗi
        ok = False
        for _ in range(2):
            stats.item_calls += 1
            stats.regenerated += 1
            p = f"{_prompt(kind, 1, [target])}\n[Lưu ý] Lỗi lần trước: {err}"
            retry = (await llm.call_json(p, GroupOut, max_retries=0)).items[0]
            err = _validate_one(retry, target, used)
            if err is None:
                used.add(target.hanzi)
                items.append(retry)
                targets_used.append(target)
                ok = True
                break
        if not ok:
            stats.dropped += 1
            continue

    answers = [it.answer for it in items]
    distractor = random_distractor(session, set(answers))
    choices = answers + [distractor]
    random.shuffle(choices)
    label = {c: chr(65 + i) for i, c in enumerate(choices)}

    result: list[dict] = []
    for it, tw in zip(items, targets_used):
        result.append(
            {
                "part": "fill_blank",
                "group_no": group_no,
                "payload": {
                    "sentence": it.sentence,
                    "choices": [[chr(65 + k), c] for k, c in enumerate(choices)],
                },
                "answer": {
                    "label": label[it.answer],
                    "explanation_vi": it.explanation_vi,
                },
                "target_word_ids": [tw.id],
            }
        )
    return result


async def gen(session, targets: list[Word], stats: GenStats,
              groups: int = 2, kind: str = "simple") -> list[dict]:
    """`groups`=2 (đề full: 5 đơn + 5 hội thoại) hoặc `groups`=1 (đề mini: 5 câu)."""
    per = 5
    out: list[dict] = []
    for g in range(groups):
        g_no = g + 1
        k = "dialogue" if g == 1 else kind
        chunk = targets[g * per:(g + 1) * per]
        if len(chunk) < 5:
            chunk = targets[len(out):]  # không đủ: dùng nốt
        out += await gen_group(session, chunk, k, g_no, stats)
    return out
