"""Đọc 2: 排列顺序 — sắp xếp 3 vế A/B/C thành đoạn đúng (mỗi câu 1 từ mục tiêu).

LLM trả {segments:[s,s,s], correct_order:"BAC"}: 3 vế + thứ tự các chữ cái để ghép
thành câu đúng. Code kiểm tra: đúng 3 vế không rỗng, correct_order là hoán vị ABC,
câu ghép đúng chứa từ mục tiêu, vế mở đầu không bắt đầu bằng liên từ nối.
Trả về list "question dict" (quy ước chung, xem exam.py).
"""
from pydantic import BaseModel, Field

from .. import llm
from ..models import Word
from .common import GenStats

# Vế mở đầu không được bắt đầu bằng những liên từ "kết quả / đối lập / nguyên nhân" này
_CONNECTIVES = ("所以", "但是", "而且", "因此", "然后", "因为", "可是", "不过", "既然")


class _Item(BaseModel):
    segments: list[str] = Field(min_length=3, max_length=3, description="3 vế của câu (bất kỳ thứ tự)")
    correct_order: str = Field(min_length=3, max_length=3, description="3 chữ A/B/C theo thứ tự ghép đúng (vd 'BAC')")
    explanation_vi: str = Field(description="Giải thích ngắn bằng tiếng Việt khi sắp sai")


class OrderOut(BaseModel):
    items: list[_Item] = Field(min_length=1, max_length=10)


def _prompt(n: int, targets: list[Word]) -> str:
    target_list = "\n".join(f"- {w.hanzi} ({w.meaning_vi})" for w in targets)
    return f"""Bạn là người ra đề HSK 4, phần 排列顺序.
Viết {n} câu hoàn chỉnh (HSK 3–4), mỗi câu dùng ĐÚNG 1 từ mục tiêu.
Mỗi câu: chia thành đúng 3 vế, rồi xáo 3 vế đó và ghi thứ tự chữ cái A/B/C để ghép lại đúng.
Từ mục tiêu (mỗi câu dùng 1, mỗi từ 1 lần):
{target_list}
Trả về JSON đúng {n} phần tử:
{{"items": [{{"segments": ["vế1","vế2","vế3"], "correct_order": "BAC", "explanation_vi": "..."}}, ...]}}
- segments: 3 vế của MỘT câu, đặt theo thứ tự BẤT KỶ.
- correct_order: 3 chữ A/B/C (mỗi chữ 1 lần) theo thứ tự ghép ra câu đúng.
"""


def validate_order(item: _Item, target: Word, used: set[str] | None = None) -> str | None:
    if len(item.segments) != 3 or any(not s.strip() for s in item.segments):
        return "phải có đúng 3 vế, mỗi vế không rỗng"
    order = item.correct_order.upper()
    if sorted(order) != ["A", "B", "C"]:
        return f"correct_order phải là hoán vị của ABC, hiện là '{item.correct_order}'"
    idx = {L: i for i, L in enumerate("ABC")}
    reading = "".join(item.segments[idx[L]] for L in order)
    first = item.segments[idx[order[0]]]
    if any(first.startswith(c) for c in _CONNECTIVES):
        return f"vế mở đầu ('{first}') không được bắt đầu bằng liên từ nối"
    if target.hanzi not in reading:
        return f"câu ghép đúng phải chứa từ mục tiêu '{target.hanzi}'"
    if used and target.hanzi in used:
        return f"'{target.hanzi}' đã được dùng ở câu khác"
    return None


async def gen(session, targets: list[Word], stats: GenStats,
              swap_pool: list[Word] | None = None) -> list[dict]:
    """`targets`: 1 từ mục tiêu/câu → len(targets) câu. Trả về list question dict.

    Sinh batch (1 lần gọi), sau đó sửa từng item: sai → sinh lại kèm lỗi (≤2) →
    đổi target từ swap_pool (≤2) → bỏ câu. Code kiểm tra bằng validate_order.
    """
    swap_pool = list(swap_pool or [])
    stats.calls += 1
    out = await llm.call_json(_prompt(len(targets), targets), OrderOut, max_retries=2)
    it_out = list(out.items)

    result: list[dict] = []
    used: set[str] = set()

    for i, target in enumerate(targets):
        item = it_out[i] if i < len(it_out) else _Item(
            segments=["", "", ""], correct_order="", explanation_vi="")
        err = validate_order(item, target, used)
        ok = err is None

        # (1) Sinh lại item với target hiện tại, tối đa 2 lần, kèm thông báo lỗi
        tries = 0
        while not ok and tries < 2:
            p = _prompt(1, [target]) + _err_note(err)
            try:
                retry = (await llm.call_json(p, OrderOut, max_retries=0)).items[0]
                err = validate_order(retry, target, used)
            except Exception:
                err = "gọi LLM thất bại khi sinh lại"
            stats.item_calls += 1
            stats.regenerated += 1
            tries += 1
            if err is None:
                item, ok = retry, True

        if ok:
            used.add(target.hanzi)
            result.append(_to_qdict(item, target))
            continue

        # (2) Đổi từ mục tiêu từ swap_pool (mỗi lần đổi thử sinh lại 1 lần)
        while swap_pool and not ok:
            target = swap_pool.pop(0)
            stats.swapped += 1
            p = _prompt(1, [target])
            try:
                retry = (await llm.call_json(p, OrderOut, max_retries=0)).items[0]
                err = validate_order(retry, target, used)
            except Exception:
                err = "gọi LLM thất bại"
            stats.item_calls += 1
            stats.regenerated += 1
            if err is None:
                item, ok = retry, True

        if ok:
            used.add(target.hanzi)
            result.append(_to_qdict(item, target))
        else:
            stats.dropped += 1
    return result


def _err_note(err: str) -> str:
    return f"\n[Lưu ý] Lỗi lần trước: {err}\nTrả lại đúng JSON, không kèm văn bản thừa."


def _to_qdict(item: _Item, target: Word) -> dict:
    return {
        "part": "order",
        "group_no": None,
        "payload": {
            "segments": [item.segments[0], item.segments[1], item.segments[2]],
        },
        "answer": {"order": item.correct_order.upper(),
                   "explanation_vi": item.explanation_vi},
        "target_word_ids": [target.id],
    }
