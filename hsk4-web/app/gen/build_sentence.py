"""Viết 1: 完成句子 — sắp xếp các từ/cụm thành câu đúng (3–6 cụm).

LLM trả {sentence, chunks} (chunks theo thứ tự đúng) + explanation_vi.
Code kiểm tra: 3–6 cụm, "".join(chunks) khớp câu (bỏ khoảng trắng/dấu câu),
câu chứa từ mục tiêu. Code tự XÁO thứ tự các cụm (tránh trùng thứ tự đúng).
Trả về list "question dict"; đáp án = thứ tự cụm gốc (chỉ code giữ).
"""
import random
import unicodedata

from pydantic import BaseModel, Field

from .. import llm
from ..models import Word
from .common import GenStats

_PUNCT = "，。！？、；：…"


def _norm(s: str) -> str:
    """Bỏ khoảng trắng + dấu câu để so khớp sentence vs "".join(chunks)."""
    s = unicodedata.normalize("NFC", s)
    return "".join(ch for ch in s if not ch.isspace() and ch not in _PUNCT)


class _Item(BaseModel):
    sentence: str = Field(description="Câu hoàn chỉnh (các cụm nối liền = câu này)")
    chunks: list[str] = Field(min_length=3, max_length=6, description="3–6 từ/cụm theo THỨ TỰ ĐÚNG")
    explanation_vi: str


class BuildOut(BaseModel):
    items: list[_Item] = Field(min_length=1, max_length=10)


def _prompt(targets: list[Word]) -> str:
    target_list = "\n".join(f"- {w.hanzi} ({w.meaning_vi})" for w in targets)
    n = len(targets)
    return f"""Bạn là người ra đề HSK 4, phần 完成句子.
Với mỗi từ mục tiêu: viết MỘT câu hoàn chỉnh (HSK 3–4) có chứa từ đó,
rồi tách câu thành 3–6 từ/cụm (chỉ tách theo ranh giới từ, không tách giữa 2 chữ của 1 từ).
Từ mục tiêu (mỗi từ 1 câu):
{target_list}
Trả về JSON đúng {n} phần tử:
{{"items": [{{"sentence":"...","chunks":["cụm1","cụm2","..."],"explanation_vi":"..."}}, ...]}}
- chunks: đặt theo THỨ TỰ ĐÚNG để ghép thành câu; nối liền các cụm phải chính là câu đó.
"""


def validate_build(item: _Item, target: Word) -> str | None:
    if not (3 <= len(item.chunks) <= 6):
        return f"số cụm phải 3–6 (hiện {len(item.chunks)})"
    if any(not c.strip() for c in item.chunks):
        return "có cụm rỗng"
    if _norm(item.sentence) != _norm("".join(item.chunks)):
        return "nối liền các chunks không khớp với sentence"
    if target.hanzi not in item.sentence:
        return f"câu phải chứa từ mục tiêu '{target.hanzi}'"
    return None


async def gen(session, targets: list[Word], stats: GenStats,
              swap_pool: list[Word] | None = None) -> list[dict]:
    swap_pool = list(swap_pool or [])
    stats.calls += 1
    out = await llm.call_json(_prompt(targets), BuildOut, max_retries=2)
    it_out = list(out.items)

    result: list[dict] = []
    for i, target in enumerate(targets):
        item = it_out[i] if i < len(it_out) else _Item(
            sentence="", chunks=["", "", ""], explanation_vi="")
        err = validate_build(item, target)
        ok = err is None

        tries = 0
        while not ok and tries < 2:
            p = _prompt([target]) + f"\n[Lưu ý] Lỗi: {err}\nTrả lại đúng JSON."
            try:
                retry = (await llm.call_json(p, BuildOut, max_retries=0)).items[0]
                err = validate_build(retry, target)
            except Exception:
                err = "gọi LLM thất bại"
            stats.item_calls += 1
            stats.regenerated += 1
            tries += 1
            if err is None:
                item, ok = retry, True

        if ok:
            result.append(_to_qdict(item, target))
            continue

        while swap_pool and not ok:
            target = swap_pool.pop(0)
            stats.swapped += 1
            p = _prompt([target])
            try:
                retry = (await llm.call_json(p, BuildOut, max_retries=0)).items[0]
                err = validate_build(retry, target)
            except Exception:
                err = "gọi LLM thất bại"
            stats.item_calls += 1
            stats.regenerated += 1
            if err is None:
                item, ok = retry, True
                break

        if ok:
            result.append(_to_qdict(item, target))
        else:
            stats.dropped += 1
    return result


def _to_qdict(item: _Item, target: Word) -> dict:
    """Xáo thứ tự cụm trong code (đáp án giữ thứ tự đúng `chunks`).

    payload.chunks = thứ tự HIỂN THỊ (đã xáo). answer.chunks = thứ tự ĐÚNG.
    Chấm: so khớp user sắp các cụm hiển thị theo đúng answer.chunks.
    """
    chunks = list(item.chunks)
    shown = list(chunks)
    for _ in range(10):
        random.shuffle(shown)
        if shown != chunks:
            break
    return {
        "part": "build_sentence",
        "group_no": None,
        "payload": {
            "chunks": shown,
            "explanation_vi": item.explanation_vi,
        },
        "answer": {"chunks": chunks},
        "target_word_ids": [target.id],
    }
