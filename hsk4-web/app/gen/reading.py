"""Đọc 3: 阅读理解 — đoạn ngắn + câu hỏi trắc nghiệm 4 lựa chọn.

Mỗi "phần tử" (spec): 1 từ mục tiêu + số câu hỏi (1 hoặc 2) → LLM viết MỘT đoạn
ngắn chứa từ đó + các câu hỏi. Code kiểm tra: đoạn 40–150 chữ, chứa từ mục tiêu;
mỗi câu 4 lựa chọn khác nhau, 0 ≤ answer_index ≤ 3. Code tự XÁO vị trí đáp án
(LLM hay để ở A) và gán chữ A–D. Trả về list "question dict" (quy ước xem exam.py).
"""
import random

from pydantic import BaseModel, Field

from .. import llm
from ..models import Word
from .common import GenStats


class _Q(BaseModel):
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation_vi: str


class _Item(BaseModel):
    passage: str
    questions: list[_Q] = Field(min_length=1, max_length=2)


class ReadingOut(BaseModel):
    items: list[_Item] = Field(min_length=1)


def _prompt(specs: list[tuple[Word, int]]) -> str:
    lines = "\n".join(
        f"{i + 1}. từ mục tiêu: {w.hanzi} ({w.meaning_vi}) — viết {nq} câu hỏi"
        for i, (w, nq) in enumerate(specs)
    )
    return f"""Bạn là người ra đề HSK 4, phần 阅读理解.
Với MỖI từ mục tiêu trong danh sách (mỗi từ 1 đoạn riêng):
viết MỘT đoạn ngắn (40–150 chữ, HSK 3–4) có chứa từ đó, kèm số câu hỏi ghi trong
danh sách. Mỗi câu: hỏi hiểu nội dung, 4 lựa chọn (đúng 1), trả index đáp án (0–3).
{lines}
Trả về JSON, items đúng số thứ tự danh sách trên:
{{"items": [{{"passage":"...","questions":[{{"question":"...","options":["...","...","...","..."],"answer_index":0,"explanation_vi":"..."}}], ...}}]}}
"""


def validate_reading(item: _Item, target: Word, nq: int) -> str | None:
    if len(item.questions) != nq:
        return f"phải có {nq} câu hỏi (hiện {len(item.questions)})"
    if not (40 <= len(item.passage.strip()) <= 150):
        return f"đoạn phải 40–150 chữ (hiện {len(item.passage.strip())})"
    if target.hanzi not in item.passage:
        return f"đoạn phải chứa từ mục tiêu '{target.hanzi}'"
    for q in item.questions:
        if len(set(q.options)) != 4:
            return "4 lựa chọn của một câu phải khác nhau"
        if not (0 <= q.answer_index <= 3):
            return f"answer_index phải 0..3 (hiện {q.answer_index})"
    return None


async def _gen_one(spec: tuple[Word, int], err: str | None) -> _Item:
    target, nq = spec
    p = _prompt([spec])
    if err:
        p += f"\n[Lưu ý] Lỗi lần trước: {err}\nTrả lại đúng JSON, không kèm văn bản thừa."
    out = await llm.call_json(p, ReadingOut, max_retries=0)
    return out.items[0]


async def gen(session, specs: list[tuple[Word, int]], stats: GenStats,
              group_offset: int = 1, swap_pool: list[Word] | None = None) -> list[dict]:
    """`specs`: [(word, n_cau_hoi)] — mỗi word 1 đoạn, n câu hỏi (1–2).

    `group_offset`: số thứ tự đoạn của nhóm này (để UI gom đoạn 2 câu lại).
    """
    if not specs:
        return []
    swap_pool = list(swap_pool or [])
    stats.calls += 1
    out = await llm.call_json(_prompt(specs), ReadingOut, max_retries=2)
    it_out = list(out.items)

    result: list[dict] = []
    used_groups = group_offset

    for i, (target, nq) in enumerate(specs):
        item = it_out[i] if i < len(it_out) else _Item(passage="", questions=[])
        err = validate_reading(item, target, nq)
        ok = err is None

        tries = 0
        while not ok and tries < 2:
            p = _prompt([(target, nq)]) + f"\n[Lưu ý] Lỗi: {err}\nTrả lại đúng JSON."
            try:
                retry = (await llm.call_json(p, ReadingOut, max_retries=0)).items[0]
                err = validate_reading(retry, target, nq)
            except Exception:
                err = "gọi LLM thất bại"
            stats.item_calls += 1
            stats.regenerated += 1
            tries += 1
            if err is None:
                item, ok = retry, True

        if ok:
            result += _to_qdicts(item, target, used_groups)
            used_groups += 1
            continue

        while swap_pool and not ok:
            target = swap_pool.pop(0)
            stats.swapped += 1
            p = _prompt([(target, nq)])
            try:
                retry = (await llm.call_json(p, ReadingOut, max_retries=0)).items[0]
                err = validate_reading(retry, target, nq)
            except Exception:
                err = "gọi LLM thất bại"
            stats.item_calls += 1
            stats.regenerated += 1
            if err is None:
                item, ok = retry, True
                break

        if ok:
            result += _to_qdicts(item, target, used_groups)
            used_groups += 1
        else:
            stats.dropped += 1
    return result


def _to_qdicts(item: _Item, target: Word, group_no: int) -> list[dict]:
    """Mỗi câu hỏi → 1 question dict; xáo 4 lựa chọn trong code, gán chữ A–D."""
    out: list[dict] = []
    for q in item.questions:
        options = list(q.options)
        correct = options[q.answer_index]
        random.shuffle(options)
        label = {o: chr(65 + k) for k, o in enumerate(options)}
        out.append({
            "part": "reading",
            "group_no": group_no,
            "payload": {
                "passage": item.passage,
                "question": q.question,
                "options": [[chr(65 + k), o] for k, o in enumerate(options)],
                "explanation_vi": q.explanation_vi,
            },
            "answer": {"label": label[correct]},
            "target_word_ids": [target.id],
        })
    return out
