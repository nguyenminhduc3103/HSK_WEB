"""Công cụ chung cho các bộ sinh đề: chọn từ, từ nhiễu, thống kê, sửa item sai."""
import random
from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import Word, WordStat


@dataclass
class GenStats:
    """Thống kê 1 phần đề (tỉ lệ mục phải sinh lại)."""

    calls: int = 0        # lời gọi "batch" ban đầu (1 per phần)
    item_calls: int = 0   # lời gọi sinh lại từng item
    regenerated: int = 0
    swapped: int = 0      # số item phải đổi từ mục tiêu
    dropped: int = 0      # số câu bị bỏ hẳn

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["item_regens"] = self.item_calls
        d["regen_rate"] = (
            round(self.item_calls / max(self.calls, 1), 2) if self.calls else 0.0
        )
        return d


def load_word_stats(session: Session) -> dict:
    """{word_id: WordStat} (chỉ các từ có dòng stat)."""
    rows = session.exec(select(WordStat)).all()
    return {r.word_id: r for r in rows}


def _least_seen(words: list[Word], stats: dict) -> list[Word]:
    """Sắp theo (seen tăng); random trong nhóm cùng seen."""

    def key(w):
        s = stats.get(w.id)
        return s.seen if s else 0

    groups: dict[int, list[Word]] = {}
    for w in words:
        groups.setdefault(key(w), []).append(w)
    out: list[Word] = []
    for seen_val in sorted(groups):
        g = groups[seen_val]
        random.shuffle(g)
        out += g
    return out


def pick_words(
    session: Session,
    n: int,
    exclude: set[str] | None = None,
    level4_ratio: float = 0.7,
    prefer_newest: bool = True,
) -> list[Word]:
    """Chọn n từ (không thuộc `exclude`).

    - Có `level` trong DB: ~level4_ratio từ HSK 4, phần lại HSK 3, rồi HSK khác.
    - Không có `level`: ưu tiên từ `seen` ít nhất (từ mới), random trong nhóm.
    """
    exclude = exclude or set()
    words = [
        w for w in session.exec(select(Word)).all()
        if w.hanzi not in exclude
    ]
    if not words:
        return []
    stats = load_word_stats(session) if prefer_newest else {}
    has_level = any(w.level is not None for w in words)

    out: list[Word] = []
    if has_level:
        lvl4 = _least_seen([w for w in words if w.level == 4], stats)
        lvl3 = _least_seen([w for w in words if w.level == 3], stats)
        other = _least_seen([w for w in words if w.level not in (3, 4)], stats)
        n4 = round(n * level4_ratio)
        out += lvl4[:n4]
        out += lvl3[: max(0, n - len(out))]
        out += other[: max(0, n - len(out))]
    else:
        out = _least_seen(words, stats)
    return out[:n]


def random_distractor(session: Session, exclude: set[str], level: int | None = None) -> str:
    """Lấy 1 từ nhiễu từ DB (không thuộc `exclude`), cùng level nếu chỉ định."""
    stmt = select(Word).where(Word.hanzi.not_in(list(exclude)))
    if level is not None:
        stmt = stmt.where(Word.level == level)
    cands = session.exec(stmt).all()
    if not cands:  # fallback: cùng cấp không có -> bất kỳ
        cands = session.exec(select(Word).where(Word.hanzi.not_in(list(exclude)))).all()
    if not cands:
        raise ValueError(f"Không có từ nhiễu (excluded={exclude}, level={level})")
    return random.choice(cands).hanzi


# ---------------------------------------------------------------------------
# Sửa từng item (mục 6.3): item sai -> sinh lại kèm lỗi (<= max_retries)
# -> đổi từ mục tiêu -> bỏ câu.
# ---------------------------------------------------------------------------
async def repair_item(
    gen_one,
    target: Word,
    validator,
    ctx: dict,
    stats: GenStats,
    swap_pool: list[Word],
    max_retries: int = 2,
    err: str | None = None,
):
    """Thử sinh 1 item với `target` (quá trình có retry).

    - `gen_one(hanzi, err, ctx)` trả về item pydantic (gọi LLM).
    - `validator(item, target, ctx)` trả None nếu hợp lệ, hoặc str lỗi.
    - Sai -> retry kèm lỗi; vẫn sai mà có swap_pool -> đổi target; cuối cùng None.

    Trả về (item, target_final) hoặc (None, target).
    """
    current = target
    for _ in range(max_retries + 1):
        item = await gen_one(current.hanzi, err, ctx)
        stats.item_calls += 1
        stats.regenerated += 1
        err = validator(item, current, ctx)
        if err is None:
            return item, current
    if swap_pool:
        current = swap_pool.pop(0)
        stats.swapped += 1
        err = None
        for _ in range(max_retries + 1):
            item = await gen_one(current.hanzi, err, ctx)
            stats.item_calls += 1
            stats.regenerated += 1
            err = validator(item, current, ctx)
            if err is None:
                return item, current
    stats.dropped += 1
    return None, target
