"""Ghép đề (mục 6 PLAN): chọn từ mục tiêu, chạy 5 bộ sinh song song, lưu DB.

Quy ước "question dict" (mọi bộ sinh trả về list dict này):
    {"part": str, "group_no": int|None,
     "payload": dict,      # thứ người làm thấy (KHÔNG chứa đáp án)
     "answer": dict|None,  # đáp án (chỉ lưu DB, không gửi trang làm bài)
     "target_word_ids": [int]}
"""
import asyncio
import json
import random
import logging

logger = logging.getLogger(__name__)

from sqlmodel import Session, select

from .config import settings
from .gen import build_sentence, fill_blank, make_sentence, order, reading
from .gen.common import GenStats, pick_words
from .models import Exam, Question, Word, WordStat

# Số câu hỏi Đọc 3: đề đầy đủ = 14 đoạn × 1 câu + 3 đoạn × 2 câu = 20 câu
FULL_SPEC = {
    "fill_blank_groups": 2,   # 2 × 5 = 10 câu
    "order": 10,
    "reading": [1] * 14 + [2] * 3,
    "build_sentence": 10,
    "make_sentence": 5,
}
MINI_SPEC = {
    "fill_blank_groups": 1,   # 5 câu
    "order": 5,
    "reading": [1] * 8 + [2] * 1,
    "build_sentence": 5,
    "make_sentence": 3,
}


def pick_wrong_words(session: Session, n: int = 5) -> list[Word]:
    """~n từ sai gần nhất: wrong > 0, correct_streak < 2, theo last_wrong_at giảm (6.1)."""
    rows = session.exec(
        select(WordStat)
        .where(WordStat.wrong > 0, WordStat.correct_streak < 2)
        .order_by(WordStat.last_wrong_at.desc())
    ).all()
    out: list[Word] = []
    for r in rows[:n]:
        w = session.get(Word, r.word_id)
        if w:
            out.append(w)
    return out


def plan_targets(session: Session, spec: dict) -> dict[str, list[Word]]:
    """Chia từ mục tiêu cho từng phần (6.1).

    - ~5 từ sai gần nhất ưu tiên: 3 từ đầu vào Đọc 1, phần còn lại vào Viết 2,
      nếu dư (rare) thì sang Viết 1.
    - Số câu còn lại: từ `seen` ít nhất (từ mới), mỗi từ dùng đúng 1 lần;
      DB nhỏ không đủ thì cho dùng lại.
    """
    slots = {
        "fill_blank": 5 * spec["fill_blank_groups"],
        "order": spec["order"],
        "reading": len(spec["reading"]),  # 1 từ / 1 đoạn
        "build_sentence": spec["build_sentence"],
        "make_sentence": spec["make_sentence"],
    }
    total = sum(slots.values())

    wrong = pick_wrong_words(session, 5)
    fresh = pick_words(session, total, exclude={w.hanzi for w in wrong})
    fb_wrong = wrong[:3]
    ms_wrong = wrong[3:3 + slots["make_sentence"]]
    bs_wrong = wrong[3 + slots["make_sentence"]:]

    used: set[int] = set(w.id for w in wrong)
    pool = list(fresh)

    def take(n: int) -> list[Word]:
        out = [w for w in pool if w.id not in used][:n]
        used.update(w.id for w in out)
        if len(out) < n and pool:  # DB nhỏ: lấp bằng từ đã dùng rồi
            out += [pool[i % len(pool)] for i in range(len(out), n)]
        return out

    targets = {
        "fill_blank": fb_wrong + take(slots["fill_blank"] - len(fb_wrong)),
        "make_sentence": ms_wrong + take(slots["make_sentence"] - len(ms_wrong)),
        "build_sentence": bs_wrong + take(slots["build_sentence"] - len(bs_wrong)),
        "order": take(slots["order"]),
        "reading": take(slots["reading"]),
    }
    for v in targets.values():
        random.shuffle(v)
    return targets


async def generate_exam(session: Session, mode: str = "full") -> tuple[int, dict, int, list[str]]:
    """Sinh 1 đề + lưu DB. Trả về (exam_id, stats theo phần, số câu, danh sách lỗi bộ sinh)."""
    spec = FULL_SPEC if mode == "full" else MINI_SPEC
    targets = plan_targets(session, spec)

    exam = Exam(mode=mode, model=settings.llm_model, status="failed")
    session.add(exam)
    session.commit()
    session.refresh(exam)

    stats = {p: GenStats() for p in (
        "fill_blank", "order", "reading", "build_sentence", "make_sentence")}

    missing: list[str] = []
    for name, words in targets.items():
        needed = (5 * spec["fill_blank_groups"] if name == "fill_blank"
                  else (len(spec["reading"]) if name == "reading" else spec[name]))
        if len(words) < needed:
            missing.append(f"{name}: cần {needed} target, chỉ có {len(words)}")
    if missing:
        raise ValueError("Thiếu từ vựng cho đề: " + "; ".join(missing))

    reading_specs = list(zip(targets["reading"], spec["reading"]))

    async def gen_make_sentence() -> list[dict]:
        # This generator is synchronous (no LLM); gather requires awaitables.
        return make_sentence.gen(session, targets["make_sentence"], stats["make_sentence"])

    # Run parts sequentially to avoid concurrent quota spikes. This does not
    # bypass an exhausted provider quota: 429s are surfaced in `errors` below.
    parts = []
    coros = [
        ("fill_blank", fill_blank.gen(
            session, targets["fill_blank"], stats["fill_blank"],
            groups=spec["fill_blank_groups"])),
        ("order", order.gen(session, targets["order"], stats["order"])),
        ("reading", reading.gen(session, reading_specs, stats["reading"])),
        ("build_sentence", build_sentence.gen(
            session, targets["build_sentence"], stats["build_sentence"])),
        ("make_sentence", gen_make_sentence()),
    ]
    for part_name, coro in coros:
        try:
            parts.append(await coro)
        except Exception as exc:
            logger.exception("Exam generation failed for part=%s exam_id=%s",
                             part_name, exam.id)
            parts.append(exc)

    n_q = 0
    errors: list[str] = []
    for part_name, res in zip(stats, parts):
        if isinstance(res, Exception):
            errors.append(f"{part_name}: {res}")
            continue  # phần này hỏng hẳn — bỏ (đề vẫn dùng được phần còn lại)
        n_q += len(res)
        for i, q in enumerate(res, 1):
            session.add(Question(
                exam_id=exam.id,
                part=q["part"],
                number=i,
                group_no=q.get("group_no"),
                payload_json=json.dumps(q["payload"], ensure_ascii=False),
                answer_json=json.dumps(q["answer"], ensure_ascii=False),
                target_word_ids_json=json.dumps(q.get("target_word_ids", [])),
            ))

    exam.status = "ready" if n_q > 0 else "failed"
    session.commit()
    session.refresh(exam)
    return exam.id, {p: s.as_dict() for p, s in stats.items()}, n_q, errors


async def generate_many(session: Session, n: int, mode: str = "full") -> list[tuple[int, dict, int, list[str]]]:
    """Sinh `n` đề nối tiếp (tôn trọng rate limit free tier)."""
    out = []
    for _ in range(n):
        out.append(await generate_exam(session, mode))
    return out
